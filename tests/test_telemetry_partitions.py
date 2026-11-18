"""Partitioned alert telemetry (one Parquet file per alert week): layout, partitioner, read path,
S3 sync and the script.

The readers must return what they returned when they loaded the whole telemetry CSV, so the central
tests here run the previous algorithm (filter the CSV on stripped-text ``AlertID`` and ``Unit``)
and compare it with the partition readers. The fixture is built to hurt: an alert whose telemetry
window crosses a Sunday/Monday boundary, ids that repeat across units, an alert without telemetry,
an alert with no parsable date, rows no alert claims, and a source whose rows are not in time order.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from plotly.utils import PlotlyJSONEncoder

from src.data import alert_partition_builder as alerts_builder
from src.data import alert_partition_s3 as s3_sync
from src.data import alert_partitions as alert_store
from src.data import loaders
from src.data import telemetry_partition_builder as builder
from src.data import telemetry_partitions as store
from src.utils.date_utils import to_utc_naive
from tests.alert_partition_support import FakeS3
from tests.telemetry_partition_support import SOURCE_FILE, write_source_csv

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "partition_alerts.py"
_spec = importlib.util.spec_from_file_location("partition_alerts_script_telemetry", SCRIPT)
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

CONFIG = s3_sync.S3Config(bucket="bucket", prefix="MultiTechnique Alerts/alerts/golden")
TEL = s3_sync.TELEMETRY_DATASET


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

def _alerts() -> pd.DataFrame:
    return pd.DataFrame([
        # Monday 00:05Z: week 07-06. Its telemetry starts Sunday 22:00Z (week 06-29 by its own clock).
        {"FusionID": "CAP-1", "TelemetryID": "TEL-1", "UnitId": "CA-1", "Timestamp": "2026-07-06T00:05:00+00:00"},
        {"FusionID": "CAP-2", "TelemetryID": "TEL-2", "UnitId": "CA-2", "Timestamp": "2026-07-14T10:00:00+00:00"},
        {"FusionID": "CAP-3", "TelemetryID": "TEL-3", "UnitId": "CA-1", "Timestamp": "2026-07-20T10:00:00+00:00"},  # no telemetry
        {"FusionID": "CAP-4", "TelemetryID": "TEL-4", "UnitId": "CA-3", "Timestamp": None},                            # undated
        {"FusionID": "CAP-5", "TelemetryID": "TEL-5", "UnitId": "CA-1", "Timestamp": "2026-07-14T11:00:00+00:00"},
    ])


def _window(alert_id, unit, alert_time, start, n, step, trigger="imp_lb_psi", offset=0.0):
    first = pd.Timestamp(start)
    rows = []
    for i in range(n):
        stamp = (first + pd.Timedelta(minutes=step * i)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        rows.append({
            "AlertID": alert_id,
            "Alert_Index": np.nan,
            "Alert_TimeStart": alert_time,
            "TimeStart": stamp,
            "Unit": unit,
            "Trigger": trigger,
            "State": "Operacional" if i % 2 else "Ralenti",
            "SubState": None if i == 0 else f"Sub {i % 3}",
            "GPSLat": -22.5 + offset + i * 0.001,
            "GPSLon": -68.9 - i * 0.001,
            "GPSElevation": 2800.0 + i,
            "Payload_Value": np.nan if i % 3 == 0 else 120.5 + i,
            "imp_lb_psi_Value": 31.0 + offset + i * 1.5,
            "imp_lb_psi_Upper_Limit": 40.0,
            "imp_lb_psi_Lower_Limit": 12.5 if i % 2 else 11.0,
            "engine_speed_rpm_Value": 1500.0 + i if i % 2 else np.nan,
            "coolant_pressure_psi_Value": np.nan,        # present as a column, never captured
        })
    return rows


def _telemetry() -> pd.DataFrame:
    rows = []
    # Deliberately not in time order: the source order must survive the partitioning.
    rows += _window("TEL-2", "CA-2", "2026-07-14T10:00:00+00:00", "2026-07-14T09:00:00+00:00", 4, 20, offset=1.0)
    rows += _window("CAP-1", "CA-1", "2026-07-06T00:05:00+00:00", "2026-07-05T22:00:00+00:00", 6, 30, offset=2.0)
    rows += _window("GHOST", "CA-1", "2026-07-08T10:00:00+00:00", "2026-07-08T09:00:00+00:00", 2, 20)      # no alert
    rows += _window("TEL-5", "CA-1", "2026-07-14T11:00:00+00:00", "2026-07-14T10:00:00+00:00", 3, 20, trigger="imt_lbf_c")
    rows += _window("TEL-4", "CA-3", None, "2026-07-01T10:00:00+00:00", 2, 20)                                # undated alert
    rows += _window("TEL-2", "CA-9", "2026-07-14T10:00:00+00:00", "2026-07-14T09:00:00+00:00", 2, 20)      # id of CAP-2, other unit
    return pd.DataFrame(rows)


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DASHBOARD_FRAME_ENGINE", "pandas")
    store._read_index_cached.cache_clear()
    loaders._load_telemetry_alert_detail_for_alert_cached.cache_clear()
    return tmp_path


def _client_dir(root, client="capstone") -> Path:
    return root / "alerts" / "golden" / client


def _write_alerts(root, client="capstone", frame=None) -> Path:
    path = _client_dir(root, client) / "consolidated_alerts.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    (frame if frame is not None else _alerts()).to_csv(path, index=False)
    return path


def _source(root, client="capstone") -> Path:
    return root / "telemetry" / "golden" / client / SOURCE_FILE


def _build(root, client="capstone"):
    return builder.build_client(client, SOURCE_FILE, root)


def _validate(root, client="capstone"):
    return builder.validate_client(client, SOURCE_FILE, root)


@pytest.fixture
def built(data_root):
    _write_alerts(data_root)
    write_source_csv(data_root, "capstone", _telemetry())
    return data_root, _build(data_root)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _original_rows(root, alert_ids, unit, client="capstone") -> pd.DataFrame:
    """What the dashboard used to read: the CSV filtered on stripped text, TimeStart normalized."""
    frame = pd.read_csv(_source(root, client), low_memory=False)
    keep = frame["AlertID"].astype(str).str.strip().isin([str(i).strip() for i in alert_ids])
    keep &= frame["Unit"].astype(str).str.strip().eq(unit)
    frame = frame[keep].reset_index(drop=True)
    frame["TimeStart"] = to_utc_naive(frame["TimeStart"])
    return frame


# ---------------------------------------------------------------------------
# Layout and partitioner
# ---------------------------------------------------------------------------

def test_every_telemetry_row_goes_to_the_week_of_its_alert_not_of_its_own_timestamp(built):
    root, result = built
    # CAP-1 fires Monday 07-06 00:05Z; three of its six samples are from Sunday 07-05 (the week of 06-29).
    assert "2026-06-29/telemetry.parquet" not in result.files
    assert result.partition_files["2026-07-06/telemetry.parquet"].rows == 6
    own_weeks = alert_store.week_starts(to_utc_naive(pd.read_csv(_source(root))["TimeStart"]))
    assert "2026-06-29" in set(own_weeks)  # the straddle is real: those rows would be in another week by their own clock
    week = store.read_weeks(_client_dir(root), ["2026-07-06"])
    assert set(week["AlertID"]) == {"CAP-1"} and len(week) == 6
    # Alerts of one week and unit share the file; a repeated id of another unit does not follow it.
    shared = store.read_weeks(_client_dir(root), ["2026-07-13"])
    assert set(zip(shared["AlertID"], shared["Unit"])) == {("TEL-2", "CA-2"), ("TEL-5", "CA-1")}


def test_the_alert_is_found_by_telemetry_id_or_fusion_id_and_the_unit(built):
    root, result = built
    directory = _client_dir(root)
    assert set(result.partition_files) == {
        "2026-07-06/telemetry.parquet", "2026-07-13/telemetry.parquet",
        "undated/telemetry.parquet", "unmatched/telemetry.parquet",
    }
    by_fusion = store.read_alert(directory, ["TEL-1", "CAP-1"], "CA-1")      # capstone keys on FusionID
    by_telemetry = store.read_alert(directory, ["TEL-2", "CAP-2"], "CA-2")   # this one on TelemetryID
    assert len(by_fusion) == 6 and set(by_fusion["AlertID"]) == {"CAP-1"}
    assert len(by_telemetry) == 4 and set(by_telemetry["Unit"]) == {"CA-2"}


def test_telemetry_with_no_alert_is_kept_reported_and_not_dropped(built, data_root, caplog):
    root, result = built
    assert result.unmatched_rows == 4 and result.unmatched_keys == 2  # GHOST/CA-1 and TEL-2/CA-9
    assert result.partition_files["unmatched/telemetry.parquet"].rows == 4
    assert result.partition_rows == result.source_rows == len(_telemetry())
    unmatched = store.read_weeks(_client_dir(root), ["unmatched"])
    assert set(zip(unmatched["AlertID"], unmatched["Unit"])) == {("GHOST", "CA-1"), ("TEL-2", "CA-9")}
    with caplog.at_level("WARNING"):
        _build(root)
    assert "4 telemetry rows" in caplog.text and "match no alert" in caplog.text


def test_telemetry_of_an_alert_without_a_parsable_date_goes_to_undated(built):
    root, result = built
    assert result.undated_rows == 2
    undated = store.read_weeks(_client_dir(root), ["undated"])
    assert set(undated["AlertID"]) == {"TEL-4"}


def test_partitions_equal_the_source_in_columns_dtypes_values_and_order(built):
    root, _ = built
    report = _validate(root)
    assert report.ok, report.problems

    source = pd.read_csv(_source(root), low_memory=False)
    combined = store.read_weeks(_client_dir(root), store.list_weeks(_client_dir(root)))
    assert list(combined.columns) == list(source.columns)
    assert [str(d) for d in combined.dtypes] == [str(d) for d in source.dtypes]
    pd.testing.assert_frame_equal(combined, source)  # values, nulls, GPS floats, strings, source row order


def test_validation_catches_a_row_in_the_wrong_week_and_a_changed_value(built):
    root, _ = built
    alerts = _client_dir(root) / "consolidated_alerts.csv"
    frame = pd.read_csv(alerts)
    frame.loc[frame.FusionID == "CAP-2", "Timestamp"] = "2026-08-04T10:00:00+00:00"   # the alert moved weeks
    frame.to_csv(alerts, index=False)
    problems = "\n".join(_validate(root).problems)
    assert "2026-07-13 holds" in problems

    frame.loc[frame.FusionID == "CAP-2", "Timestamp"] = "2026-07-14T10:00:00+00:00"
    frame.to_csv(alerts, index=False)
    assert _validate(root).ok
    source = pd.read_csv(_source(root), low_memory=False)
    source.loc[0, "imp_lb_psi_Value"] = 99.0
    source.to_csv(_source(root), index=False)
    assert any("values differ" in p for p in _validate(root).problems)


def test_the_source_csv_is_never_modified(data_root):
    _write_alerts(data_root)
    csv = write_source_csv(data_root, "capstone", _telemetry())
    before = (_sha(csv), csv.stat().st_mtime_ns)
    _build(data_root)
    _build(data_root)
    assert (_sha(csv), csv.stat().st_mtime_ns) == before


def test_rerun_on_the_same_source_rewrites_nothing_and_duplicates_nothing(built):
    root, first = built
    files = sorted(_client_dir(root).rglob("*.parquet"))
    snapshot = {p: (_sha(p), p.stat().st_mtime_ns) for p in files}
    second = _build(root)
    assert second.written == [] and second.unchanged == len(first.partition_files) and second.removed == []
    assert snapshot == {p: (_sha(p), p.stat().st_mtime_ns) for p in sorted(_client_dir(root).rglob("*.parquet"))}
    assert {r: f.sha256 for r, f in first.files.items()} == {r: f.sha256 for r, f in second.files.items()}
    assert second.partition_rows == first.partition_rows == second.source_rows


def test_a_changed_source_regenerates_exactly_the_changed_partitions_including_the_current_week(built):
    root, _ = built
    source = pd.read_csv(_source(root), low_memory=False)
    extra = pd.DataFrame(_window("TEL-2", "CA-2", "2026-07-14T10:00:00+00:00", "2026-07-14T10:30:00+00:00", 1, 1))
    pd.concat([source, extra], ignore_index=True).to_csv(_source(root), index=False)

    second = _build(root)
    assert set(second.written) == {"2026-07-13/telemetry.parquet", "_telemetry_index.parquet"}
    assert second.partition_rows == len(source) + 1
    assert _validate(root).ok


def test_partitions_the_source_no_longer_yields_are_removed_and_nothing_else_is_touched(built):
    root, _ = built
    directory = _client_dir(root)
    alerts_builder.build_client("capstone", root)
    other = directory / "backtest" / "keep.txt"
    other.parent.mkdir(parents=True)
    other.write_text("not a telemetry partition")
    alert_files = {p: _sha(p) for p in directory.rglob("file.parquet")}

    source = pd.read_csv(_source(root), low_memory=False)
    source[source.AlertID != "TEL-4"].to_csv(_source(root), index=False)
    result = _build(root)
    assert result.removed == ["undated/telemetry.parquet"]
    assert not (directory / "undated" / "telemetry.parquet").exists()
    assert (directory / "undated" / "file.parquet").is_file()    # the alerts partition of that folder stays
    assert other.read_text() == "not a telemetry partition"
    assert {p: _sha(p) for p in directory.rglob("file.parquet")} == alert_files


def test_a_failed_replace_leaves_the_previous_partition_and_no_temp_file(built, monkeypatch):
    root, _ = built
    target = _client_dir(root) / "2026-07-13" / "telemetry.parquet"
    before = target.read_bytes()
    source = pd.read_csv(_source(root), low_memory=False)
    source.loc[source.AlertID == "TEL-2", "imp_lb_psi_Value"] = 77.0
    source.to_csv(_source(root), index=False)

    def broken_replace(src, dst):
        raise OSError("disk went away")

    monkeypatch.setattr(alerts_builder.os, "replace", broken_replace)
    with pytest.raises(OSError):
        _build(root)
    assert target.read_bytes() == before                       # still the complete old file
    assert len(store.read_weeks(_client_dir(root), ["2026-07-13"])) == 7
    assert not list(_client_dir(root).rglob("*.tmp-*"))
    assert not (_client_dir(root) / ".alerts_partition.lock").exists()


def test_telemetry_and_alerts_partitions_coexist_whichever_runs_first(built):
    root, _ = built
    directory = _client_dir(root)
    alerts_builder.build_client("capstone", root)          # alerts after the telemetry
    telemetry = {p: _sha(p) for p in directory.rglob("telemetry.parquet")}
    for name in ("2026-07-06", "2026-07-13"):
        assert (directory / name / "file.parquet").is_file() and (directory / name / "telemetry.parquet").is_file()
    alerts = {p: _sha(p) for p in directory.rglob("file.parquet")}

    assert _build(root).written == []                      # telemetry after the alerts: nothing to rewrite
    alerts_builder.build_client("capstone", root)          # and the alerts again: must not touch the telemetry
    assert telemetry == {p: _sha(p) for p in directory.rglob("telemetry.parquet")}
    assert alerts == {p: _sha(p) for p in directory.rglob("file.parquet")}
    assert alert_store.list_weeks(directory) == ["2026-07-06", "2026-07-13", "2026-07-20", "undated"]
    assert store.list_weeks(directory) == ["2026-07-06", "2026-07-13", "undated", "unmatched"]
    assert _validate(root).ok and alerts_builder.validate_client("capstone", root).ok


def test_the_layout_never_uses_the_alerts_file_name_and_lists_special_weeks_last(built):
    root, _ = built
    directory = _client_dir(root)
    assert store.TELEMETRY_FILE != alert_store.PARTITION_FILE
    assert store.list_weeks(directory) == ["2026-07-06", "2026-07-13", "undated", "unmatched"]
    assert not list(directory.rglob("file.parquet"))
    assert store.partition_relpath("2026-07-06") == "2026-07-06/telemetry.parquet"


def test_two_builds_cannot_overlap(data_root):
    _write_alerts(data_root)
    write_source_csv(data_root, "capstone", _telemetry())
    lock = _client_dir(data_root) / ".alerts_partition.lock"
    lock.write_text("123")
    with pytest.raises(alerts_builder.PartitionBuildError, match="Another partition run"):
        _build(data_root)
    old = datetime.now().timestamp() - 3 * 3600
    os.utime(lock, (old, old))
    assert _build(data_root).source_rows == len(_telemetry())


def test_building_without_alerts_or_source_is_a_clear_error(data_root):
    write_source_csv(data_root, "capstone", _telemetry())
    with pytest.raises(alerts_builder.PartitionBuildError, match="consolidated_alerts.csv"):
        _build(data_root)
    with pytest.raises(builder.TelemetrySourceMissing):
        builder.build_client("cda", SOURCE_FILE, data_root)


def test_cda_style_integer_alert_ids_are_matched_as_text_per_unit(data_root):
    alerts = pd.DataFrame([
        {"FusionID": "F-0-1", "TelemetryID": 0, "UnitId": "T_11", "Timestamp": "2025-08-11 18:01:00"},
        {"FusionID": "F-1-2", "TelemetryID": 1, "UnitId": "T_11", "Timestamp": "2025-09-08 20:25:00"},
        {"FusionID": "F-0-3", "TelemetryID": 0, "UnitId": "T_13", "Timestamp": "2025-02-09 05:08:00"},
    ])
    rows = []
    for alert_id, unit, when in ((0, "T_11", "2025-08-11 18:01:00"), (1, "T_11", "2025-09-08 20:25:00"), (0, "T_13", "2025-02-09 05:08:00")):
        rows += _window(alert_id, unit, when, when, 3, 10)
    _write_alerts(data_root, "cda", alerts)
    write_source_csv(data_root, "cda", pd.DataFrame(rows))
    result = builder.build_client("cda", SOURCE_FILE, data_root)
    assert result.unmatched_rows == 0
    assert sorted(result.partition_files) == ["2025-02-03/telemetry.parquet", "2025-08-11/telemetry.parquet", "2025-09-08/telemetry.parquet"]
    # AlertID 0 exists for two units: each unit reads only its own rows.
    assert len(store.read_alert(_client_dir(data_root, "cda"), ["0", "F-0-1"], "T_11")) == 3
    assert len(store.read_alert(_client_dir(data_root, "cda"), ["0", "F-0-3"], "T_13")) == 3
    assert builder.validate_client("cda", SOURCE_FILE, data_root).ok


def test_two_alerts_of_different_weeks_claiming_one_key_are_counted_and_still_found(data_root):
    alerts = pd.DataFrame([
        {"FusionID": "A", "TelemetryID": "SAME", "UnitId": "U1", "Timestamp": "2026-07-06T10:00:00+00:00"},
        {"FusionID": "SAME", "TelemetryID": "B", "UnitId": "U1", "Timestamp": "2026-07-20T10:00:00+00:00"},
    ])
    _write_alerts(data_root, frame=alerts)
    write_source_csv(data_root, "capstone", pd.DataFrame(_window("SAME", "U1", "2026-07-06T10:00:00+00:00", "2026-07-06T09:00:00+00:00", 3, 10)))
    result = _build(data_root)
    assert result.ambiguous_keys == 1 and set(result.partition_files) == {"2026-07-06/telemetry.parquet"}
    # Either alert finds the rows through the index (they live where the first alert put them).
    assert len(store.read_alert(_client_dir(data_root), ["B", "SAME"], "U1")) == 3


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------

def test_the_index_locates_every_group_without_reading_a_partition(built):
    root, result = built
    index = store.read_index(_client_dir(root))
    assert list(index.columns) == ["AlertID", "Unit", "Trigger", "Alert_TimeStart", "week", "rows", "first_row", "part_sha"]
    assert int(index["rows"].sum()) == len(_telemetry()) == store.total_rows(_client_dir(root))
    one = index[(index.AlertID == "CAP-1") & (index.Unit == "CA-1")].iloc[0]
    assert (one["week"], one["rows"]) == ("2026-07-06", 6)
    assert set(index["week"]) == set(result.partition_files and [rel.split("/")[0] for rel in result.partition_files])
    assert store.weeks_of(index[index.AlertID == "TEL-5"]) == ["2026-07-13"]
    assert store.schema_columns(_client_dir(root)) == list(pd.read_csv(_source(root), nrows=0).columns)


def test_the_index_file_changes_whenever_any_partition_does(built):
    root, _ = built
    directory = _client_dir(root)
    before = store.index_signature(directory)
    _build(root)
    assert store.index_signature(directory) == before          # idempotent
    source = pd.read_csv(_source(root), low_memory=False)
    source.loc[source.AlertID == "TEL-5", "imp_lb_psi_Value"] = 1.25   # a value changes, no row is added
    source.to_csv(_source(root), index=False)
    _build(root)
    assert store.index_signature(directory) != before          # so caches keyed on it can never be stale


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

@pytest.fixture
def read_log(monkeypatch):
    seen: list[str] = []
    real = pq.read_table

    def spy(path, *args, **kwargs):
        path = Path(path)
        seen.append(path.name if path.name.startswith("_") else f"{path.parent.name}/{path.name}")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(pq, "read_table", spy)
    return seen


def test_one_alert_reads_the_index_and_a_single_week(built, read_log):
    root, _ = built
    frame = store.read_alert(_client_dir(root), ["TEL-1", "CAP-1"], "CA-1")
    assert len(frame) == 6
    assert read_log == ["_telemetry_index.parquet", "2026-07-06/telemetry.parquet"]


def test_the_loader_returns_what_the_csv_filter_returned(built):
    root, _ = built
    for alert_ids, unit in (
        (["TEL-1", "CAP-1"], "CA-1"), (["TEL-2", "CAP-2"], "CA-2"), (["TEL-5", "CAP-5"], "CA-1"),
        (["TEL-4", "CAP-4"], "CA-3"), ([" TEL-2 ", "CAP-2"], " CA-2 "),
    ):
        got = loaders.load_telemetry_alert_detail_for_alert("capstone", alert_ids, unit)
        want = _original_rows(root, alert_ids, unit.strip())
        assert not want.empty
        pd.testing.assert_frame_equal(got.reset_index(drop=True), want)   # columns, dtypes, values, row order
        assert got["TimeStart"].dt.tz is None                              # the same UTC-naive normalization


def test_an_alert_that_straddles_a_week_boundary_comes_back_whole(built):
    root, _ = built
    got = loaders.load_telemetry_alert_detail_for_alert("capstone", ["TEL-1", "CAP-1"], "CA-1")
    assert len(got) == 6
    assert got["TimeStart"].min() == pd.Timestamp("2026-07-05 22:00") and got["TimeStart"].max() == pd.Timestamp("2026-07-06 00:30")


def test_ids_that_repeat_across_units_never_merge(built):
    got = loaders.load_telemetry_alert_detail_for_alert("capstone", ["TEL-2"], "CA-2")
    assert set(got["Unit"]) == {"CA-2"} and len(got) == 4
    other = loaders.load_telemetry_alert_detail_for_alert("capstone", ["TEL-2"], "CA-9")
    assert set(other["Unit"]) == {"CA-9"}  # the unmatched rows are still reachable by their own key


@pytest.mark.parametrize("alert_ids,unit", [
    (["TEL-3", "CAP-3"], "CA-1"),      # an alert with no telemetry
    (["TEL-1"], "CA-2"),               # right id, other unit
    (["nope"], "CA-1"),
    ([], "CA-1"), (["TEL-1"], ""), ([None, " "], "CA-1"),
])
def test_missing_telemetry_is_empty_not_an_error(built, alert_ids, unit):
    assert loaders.load_telemetry_alert_detail_for_alert("capstone", alert_ids, unit).empty


def test_a_client_without_partitions_a_missing_week_and_a_stale_index_are_empty(built):
    root, _ = built
    assert loaders.load_telemetry_alert_detail_for_alert("emin", ["x"], "u").empty
    (_client_dir(root) / "2026-07-06" / "telemetry.parquet").unlink()      # the week's file not there (yet)
    loaders._load_telemetry_alert_detail_for_alert_cached.cache_clear()
    assert loaders.load_telemetry_alert_detail_for_alert("capstone", ["TEL-1", "CAP-1"], "CA-1").empty
    assert store.read_weeks(_client_dir(root), ["1999-01-04", "2026-07-13"]).shape[0] == 7
    assert store.read_alert(_client_dir(root, "nobody"), ["x"], "u").empty
    assert store.list_weeks(_client_dir(root, "nobody")) == [] and store.read_index(_client_dir(root, "nobody")).empty


def test_a_new_weekly_run_is_never_answered_from_the_previous_cache(built):
    root, _ = built
    first = loaders.load_telemetry_alert_detail_for_alert("capstone", ["TEL-2", "CAP-2"], "CA-2")
    assert first["imp_lb_psi_Value"].iloc[0] == 32.0
    source = pd.read_csv(_source(root), low_memory=False)
    source.loc[source.AlertID == "TEL-2", "imp_lb_psi_Value"] = 5.0
    source.to_csv(_source(root), index=False)
    _build(root)
    again = loaders.load_telemetry_alert_detail_for_alert("capstone", ["TEL-2", "CAP-2"], "CA-2")
    assert set(again.loc[again.Unit == "CA-2", "imp_lb_psi_Value"]) == {5.0}


def test_readers_work_without_the_source_files(built):
    """Delete the telemetry CSV and the alerts CSV: every migrated reader still runs."""
    root, _ = built
    _source(root).unlink()
    (_client_dir(root) / "consolidated_alerts.csv").unlink()
    loaders._load_telemetry_alert_detail_for_alert_cached.cache_clear()

    assert len(loaders.load_telemetry_alert_detail_for_alert("capstone", ["TEL-1", "CAP-1"], "CA-1")) == 6

    from config.service_data_sources import SOURCE_DATE_FIELDS
    from src.data.catalog import build_client_availability, clear_availability_cache
    from src.data.source_freshness import latest_data_date

    clear_availability_cache()
    probe = build_client_availability("capstone", root)["telemetry_alert_detail"]
    assert probe.status == "available"
    assert latest_data_date(probe.path, SOURCE_DATE_FIELDS["telemetry_alert_detail"], date(2026, 12, 1)) == date(2026, 7, 14)

    from src.campbell_ai.data import DashboardDataRepository
    repository = DashboardDataRepository(root)
    detail = json.loads(repository.query_alert_detail("capstone", alert_id="CAP-1", unit_id="CA-1"))
    assert detail["alerts_matched"] == 1 and detail["records"][0]["samples"] == 6
    assert repository.telemetry_signal_limits("capstone")
    assert json.loads(repository.describe_dataset("capstone", "alerts_detail"))["datasets"]["alerts_detail"]["rows"] == len(_telemetry())


def test_the_detail_section_renders_from_partitions_alone(built, monkeypatch):
    from dashboard.callbacks import alerts_callbacks as callbacks

    root, _ = built
    _source(root).unlink()
    row = pd.Series({"TelemetryID": "TEL-1", "FusionID": "CAP-1", "UnitId": "CA-1",
                     "Timestamp": pd.Timestamp("2026-07-06 00:05")})
    section = callbacks.create_telemetry_evidence_section(row, "capstone")
    payload = json.dumps(section, cls=PlotlyJSONEncoder)
    assert "Evidencia de Telemetr" in payload and '"y": [' in payload     # the section and its plotted series
    no_data = pd.Series({"TelemetryID": "TEL-3", "FusionID": "CAP-3", "UnitId": "CA-1",
                         "Timestamp": pd.Timestamp("2026-07-20 10:00")})
    warning = callbacks.create_telemetry_evidence_section(no_data, "capstone")   # as today when telemetry is missing
    assert "color" in json.dumps(warning, default=str)
    assert callbacks.create_telemetry_evidence_section(no_data, "emin").children in (None, [])


# ---------------------------------------------------------------------------
# Freshness chip and catalog probe
# ---------------------------------------------------------------------------

def test_the_freshness_chip_dates_the_data_like_the_csv_did(built):
    from config.service_data_sources import SOURCE_DATE_FIELDS
    from src.data import source_freshness
    from src.data.catalog import build_client_availability, clear_availability_cache

    root, _ = built
    clear_availability_cache()
    field = SOURCE_DATE_FIELDS["telemetry_alert_detail"]
    probe = build_client_availability("capstone", root)["telemetry_alert_detail"]
    assert Path(probe.path).name == "_telemetry_index.parquet" and probe.status == "available"
    for today in (date(2026, 7, 10), date(2026, 7, 14), date(2026, 12, 1)):
        old = source_freshness._days_of(pd.read_csv(_source(root), usecols=["Alert_TimeStart"], dtype=str)["Alert_TimeStart"])
        expected = max((day for day in old if day <= today), default=None)
        assert source_freshness.latest_data_date(probe.path, field, today) == expected


def test_a_client_without_telemetry_reports_the_source_as_missing(built):
    from src.data.catalog import build_client_availability, clear_availability_cache

    root, _ = built
    clear_availability_cache()
    assert build_client_availability("emin", root)["telemetry_alert_detail"].status == "missing"


# ---------------------------------------------------------------------------
# Campbell AI
# ---------------------------------------------------------------------------

@pytest.fixture
def repository(built):
    from src.campbell_ai.data import DashboardDataRepository
    from src.campbell_ai import index as vocabulary_index

    from src.campbell_ai import data as campbell_data

    root, _ = built
    vocabulary_index.reset()
    campbell_data.clear_telemetry_limit_cache()      # process-global, keyed by client only
    yield DashboardDataRepository(root)
    campbell_data.clear_telemetry_limit_cache()


def test_campbell_reads_only_the_weeks_a_filter_can_match(repository, read_log):
    detail = json.loads(repository.query_alert_detail("capstone", alert_id="CAP-1", unit_id="CA-1"))
    assert detail["alerts_matched"] == 1 and detail["detail_rows_scanned"] == 6
    assert detail["records"][0]["peak_value"] == 31.0 + 2.0 + 5 * 1.5   # offset 2.0, last of six samples
    assert read_log == ["_telemetry_index.parquet", "2026-07-06/telemetry.parquet"]


def test_campbell_unit_and_trigger_queries_match_the_source(repository, built):
    root, _ = built
    source = pd.read_csv(_source(root), low_memory=False)
    by_unit = json.loads(repository.query_alert_detail("capstone", unit_id="CA-1"))
    assert by_unit["detail_rows_scanned"] == int((source.Unit == "CA-1").sum())
    by_trigger = json.loads(repository.query_alert_detail("capstone", trigger="imt_lbf"))
    assert by_trigger["detail_rows_scanned"] == int((source.Trigger == "imt_lbf_c").sum()) == 3


def test_campbell_empty_answers_keep_their_hints_and_errors(repository):
    missing = json.loads(repository.query_alert_detail("capstone", unit_id="CA-1", trigger="nada"))
    assert missing["alerts_matched"] == 0
    assert missing["filter_hints"]["available_triggers"] == ["imp_lb_psi", "imt_lbf_c"]
    from src.campbell_ai.errors import CampbellDataError
    with pytest.raises(CampbellDataError, match="requiere alert_id, unit_id o trigger"):
        repository.query_alert_detail("capstone")
    with pytest.raises(CampbellDataError, match="Sin filas de detalle"):
        repository.alert_signal_series("capstone", alert_id="nope", unit_id="CA-1")
    with pytest.raises(CampbellDataError, match="Fuente de datos no disponible"):
        repository.query_alert_detail("emin", unit_id="x")


def test_campbell_signal_series_without_an_alert_takes_the_newest_of_the_unit(repository):
    payload = repository.alert_signal_series("capstone", unit_id="CA-1")
    assert payload["alert_id"] == "TEL-5"  # the unit's latest telemetry sample belongs to TEL-5 (07-14)
    series = repository.alert_signal_series("capstone", alert_id="CAP-1", unit_id="CA-1")
    assert series["samples"] == 6 and "imp_lb_psi" in series["signals_available"]


def test_campbell_limits_table_is_built_from_the_limit_columns_of_every_week(repository, read_log):
    table = repository.telemetry_signal_limits("capstone")
    assert set(table) == {"imp_lb_psi"} and table["imp_lb_psi"]["upper"][("CA-1", "Sub 1")] == 40.0
    # A reading of all weeks, but the index plus one projection per partition and nothing else.
    assert sorted(read_log) == sorted([
        "_telemetry_index.parquet", "2026-07-06/telemetry.parquet", "2026-07-13/telemetry.parquet",
        "undated/telemetry.parquet", "unmatched/telemetry.parquet",
    ])


def test_campbell_describe_and_vocabulary_come_from_the_index(repository, read_log):
    described = json.loads(repository.describe_dataset("capstone", "alerts_detail"))["datasets"]["alerts_detail"]
    assert described["available"] and described["rows"] == len(_telemetry())
    assert described["columns"][:3] == ["AlertID", "Alert_Index", "Alert_TimeStart"]
    units = described["filters"]["unit_id"]["values"]
    assert units[0] == "CA-1" and described["filters"]["trigger"]["values"] == ["imp_lb_psi", "imt_lbf_c"]
    assert [name for name in read_log if name != "_telemetry_index.parquet" and not name.endswith("telemetry.parquet")] == []
    assert not [name for name in read_log if name.endswith("2026-07-06/telemetry.parquet")]  # no partition was opened


def test_campbell_validation_and_context_chart(repository):
    from src.campbell_ai.chart_registry import DashboardChartRegistry
    from src.campbell_ai.errors import CampbellDataError

    check = repository.validate_client("capstone")["datasets"]["alerts_detail"]
    assert check["valid"] and check["exists"]
    registry = DashboardChartRegistry(repository)
    figure, detail = registry._alert_context_signals("capstone", {"unit_id": "CA-1", "alert_id": "CAP-1"})
    assert detail["alert_id"] == "CAP-1" and detail["samples"] == 6
    with pytest.raises(CampbellDataError, match="Sin detalle de alertas para ZZ"):
        registry._alert_context_signals("capstone", {"unit_id": "ZZ"})
    with pytest.raises(CampbellDataError, match="no existe para CA-1"):
        registry._alert_context_signals("capstone", {"unit_id": "CA-1", "alert_id": "nope"})


def test_campbell_cannot_load_the_telemetry_as_a_file(repository):
    from src.campbell_ai.errors import CampbellDataError
    with pytest.raises(CampbellDataError, match="particiones semanales"):
        repository.load("alerts_detail", "capstone")


# ---------------------------------------------------------------------------
# S3 sync
# ---------------------------------------------------------------------------

def _keys(s3, client="capstone"):
    return {k for k in s3.objects if k.startswith(f"{CONFIG.prefix}/{client}/")}


def test_backfill_sync_mirrors_the_local_layout_and_marks_only_the_telemetry_history(built):
    _, result = built
    s3 = FakeS3()
    sync = s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=False, write_backfill_marker=True, dataset=TEL)
    prefix = "MultiTechnique Alerts/alerts/golden/capstone"
    assert _keys(s3) == {f"{prefix}/{rel}" for rel in result.files} | {f"{prefix}/_telemetry_backfill_complete.json"}
    assert f"{prefix}/2026-07-06/telemetry.parquet" in s3.objects
    assert not any(key.endswith("_backfill_complete.json") and "_telemetry" not in key for key in s3.objects)
    assert sync.marker_written and len(sync.uploaded) == len(result.files)
    assert s3_sync.verify_client(s3, CONFIG, result, dataset=TEL) == []


def test_s3_telemetry_partitions_have_the_same_rows_as_the_local_ones(built):
    import io

    _, result = built
    s3 = FakeS3()
    s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=False, write_backfill_marker=True, dataset=TEL)
    for rel, local in result.partition_files.items():
        remote = s3.objects[f"{CONFIG.prefix}/capstone/{rel}"]
        assert pq.read_table(io.BytesIO(remote["Body"])).num_rows == local.rows == int(remote["Metadata"]["rows"])


def test_the_weekly_telemetry_sync_refuses_until_the_telemetry_backfill_is_synced_even_with_the_alerts_marker(built):
    root, result = built
    s3 = FakeS3()
    # The alerts backfill reached S3 long ago: its marker exists.
    marker = f"{CONFIG.prefix}/capstone/{alert_store.BACKFILL_MARKER_FILE}"
    s3.objects[marker] = {"Body": b"{}", "Metadata": {}}
    with pytest.raises(s3_sync.S3SyncError, match="no complete telemetry history"):
        s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=True, dataset=TEL)
    assert s3.puts == []
    s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=False, write_backfill_marker=True, dataset=TEL)
    again = s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=True, dataset=TEL)   # now it may run
    assert again.uploaded == []


def test_rerunning_uploads_nothing_and_a_changed_week_uploads_only_it(built):
    root, first = built
    s3 = FakeS3()
    s3_sync.sync_client(s3, CONFIG, first, require_backfill_marker=False, write_backfill_marker=True, dataset=TEL)
    s3.puts.clear()
    assert s3_sync.sync_client(s3, CONFIG, first, require_backfill_marker=True, dataset=TEL).uploaded == []
    source = pd.read_csv(_source(root), low_memory=False)
    source.loc[source.AlertID == "TEL-5", "imp_lb_psi_Value"] = 3.5
    source.to_csv(_source(root), index=False)
    second = _build(root)
    sync = s3_sync.sync_client(s3, CONFIG, second, require_backfill_marker=True, dataset=TEL)
    assert set(sync.uploaded) == {"2026-07-13/telemetry.parquet", "_telemetry_index.parquet"}
    assert s3_sync.verify_client(s3, CONFIG, second, dataset=TEL) == []


def test_a_failed_upload_is_reported_keeps_local_files_and_is_retried_next_run(built):
    root, result = built
    s3 = FakeS3()
    s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=False, write_backfill_marker=True, dataset=TEL)
    source = pd.read_csv(_source(root), low_memory=False)
    source.loc[source.AlertID == "TEL-5", "imp_lb_psi_Value"] = 4.5
    source.to_csv(_source(root), index=False)
    second = _build(root)
    failing = f"{CONFIG.prefix}/capstone/2026-07-13/telemetry.parquet"
    s3.fail_put.add(failing)

    with pytest.raises(s3_sync.S3SyncError, match="1 of .* uploads failed"):
        s3_sync.sync_client(s3, CONFIG, second, require_backfill_marker=True, dataset=TEL)
    assert _validate(root).ok                       # local output complete and valid
    assert s3.objects[failing]["Metadata"]["sha256"] != second.files["2026-07-13/telemetry.parquet"].sha256

    s3.fail_put.clear()
    retried = _build(root)
    assert retried.written == []                    # nothing to regenerate ...
    sync = s3_sync.sync_client(s3, CONFIG, retried, require_backfill_marker=True, dataset=TEL)
    assert "2026-07-13/telemetry.parquet" in sync.uploaded   # ... but the pending upload is retried
    assert s3_sync.verify_client(s3, CONFIG, retried, dataset=TEL) == []


def test_each_dataset_deletes_only_its_own_stale_keys(built):
    root, result = built
    alerts_result = alerts_builder.build_client("capstone", root)
    s3 = FakeS3()
    prefix = f"{CONFIG.prefix}/capstone"
    s3.objects[f"{prefix}/consolidated_alerts.csv"] = {"Body": b"csv", "Metadata": {}}
    s3.objects[f"{prefix}/2026-07-06/file.parquet"] = {"Body": b"someone's alert partition", "Metadata": {}}
    s3.objects[f"{prefix}/2099-01-01/telemetry.parquet"] = {"Body": b"stale telemetry", "Metadata": {}}
    sync = s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=False, write_backfill_marker=True, dataset=TEL)
    assert sync.deleted == ["2099-01-01/telemetry.parquet"]
    assert f"{prefix}/2026-07-06/file.parquet" in s3.objects and f"{prefix}/consolidated_alerts.csv" in s3.objects
    # ... and syncing the alerts never deletes a telemetry object.
    s3_sync.sync_client(s3, CONFIG, alerts_result, require_backfill_marker=False, write_backfill_marker=True)
    assert f"{prefix}/2026-07-06/telemetry.parquet" in s3.objects
    assert {k for k in s3.objects if k.endswith("_backfill_complete.json")} == {
        f"{prefix}/_backfill_complete.json", f"{prefix}/_telemetry_backfill_complete.json",
    }


def test_verification_reports_every_kind_of_mismatch(built):
    _, result = built
    s3 = FakeS3()
    s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=False, write_backfill_marker=True, dataset=TEL)
    prefix = f"{CONFIG.prefix}/capstone"
    del s3.objects[f"{prefix}/2026-07-06/telemetry.parquet"]
    s3.objects[f"{prefix}/2026-07-13/telemetry.parquet"]["Body"] += b"x"
    s3.objects[f"{prefix}/2099-01-01/telemetry.parquet"] = {"Body": b"x", "Metadata": {}}
    problems = "\n".join(s3_sync.verify_client(s3, CONFIG, result, dataset=TEL))
    assert "missing in S3" in problems and "size differs" in problems and "extra in S3" in problems


# ---------------------------------------------------------------------------
# Script: modes, exit codes
# ---------------------------------------------------------------------------

def _run(root, *, backfill=False, sync=False, validate=False, verify=False, s3=None, datasets=("alerts", "telemetry")):
    return cli.run(
        root=str(root), clients=None, backfill=backfill, sync_s3=sync, validate=validate, verify_s3=verify,
        s3_options={"bucket": "bucket"}, s3_client=s3, datasets=datasets,
    )


def _two_clients(root):
    """capstone with telemetry, emin without (EMIN publishes none)."""
    alerts = _alerts().assign(sistema="motor", Trigger_type="Telemetria", Trigger_Var="imp_lb_psi")
    for client in ("capstone", "emin"):
        _write_alerts(root, client, alerts)
    write_source_csv(root, "capstone", _telemetry())


def test_backfill_builds_the_telemetry_locally_with_s3_off_by_default(data_root, monkeypatch):
    _two_clients(data_root)
    monkeypatch.setattr(cli.s3_sync, "make_s3_client", lambda config: pytest.fail("S3 was used"))
    assert cli.main(["--backfill", "--data-root", str(data_root)]) == 0
    assert store.list_weeks(_client_dir(data_root)) == ["2026-07-06", "2026-07-13", "undated", "unmatched"]
    assert alert_store.has_partitions(_client_dir(data_root)) and alert_store.has_partitions(_client_dir(data_root, "emin"))
    assert not store.has_telemetry(_client_dir(data_root, "emin"))      # no source: nothing to partition, no error
    assert cli.parse_args(["--backfill"]).sync_s3 is False and cli.parse_args(["--backfill"]).dataset == "all"


def test_dataset_flag_runs_only_the_telemetry_half(data_root):
    _two_clients(data_root)
    assert cli.main(["--backfill", "--dataset", "telemetry", "--data-root", str(data_root)]) == 0
    assert store.has_telemetry(_client_dir(data_root)) and not alert_store.has_partitions(_client_dir(data_root))
    with pytest.raises(SystemExit):
        cli.parse_args(["--dataset", "other"])


def test_backfill_validation_runs_by_default_and_a_failure_stops_the_push(data_root, monkeypatch):
    _two_clients(data_root)
    s3 = FakeS3()
    monkeypatch.setattr(cli.telemetry_builder, "validate_client",
                        lambda *a, **k: alerts_builder.ValidationReport("capstone", 1, 0, 0, ["boom"]))
    assert _run(data_root, backfill=True, sync=True, validate=True, s3=s3, datasets=("telemetry",)) == cli.EXIT_BUILD_ERROR
    assert s3.puts == [] and store.has_telemetry(_client_dir(data_root))   # local files stay; nothing was pushed


def test_backfill_with_the_flag_syncs_then_the_weekly_run_can_follow(data_root):
    _two_clients(data_root)
    s3 = FakeS3()
    assert _run(data_root, backfill=True, sync=True, validate=True, s3=s3) == 0
    keys = {k.split("/", 4)[-1] for k in s3.objects}
    assert {"_backfill_complete.json", "_telemetry_backfill_complete.json", "2026-07-06/telemetry.parquet",
            "_telemetry_index.parquet"} <= {k.split("capstone/")[-1] for k in s3.objects if "/capstone/" in k}
    assert _run(data_root, sync=True, s3=s3) == 0
    assert _run(data_root, verify=True, s3=s3) == 0       # --verify-s3 covers the telemetry too


def test_the_weekly_run_refuses_telemetry_until_its_own_backfill_was_synced(data_root, caplog):
    _two_clients(data_root)
    s3 = FakeS3()
    assert _run(data_root, backfill=True, sync=True, validate=True, s3=s3, datasets=("alerts",)) == 0   # alerts history only
    with caplog.at_level("ERROR"):
        status = _run(data_root, sync=True, s3=s3)
    assert status == cli.EXIT_S3_ERROR
    assert "no complete telemetry history" in caplog.text
    assert not any("telemetry.parquet" in k for k in s3.objects)          # nothing of it was pushed
    assert _run(data_root, backfill=True, sync=True, validate=True, s3=s3, datasets=("telemetry",)) == 0
    assert _run(data_root, sync=True, s3=s3) == 0


def test_a_failed_weekly_telemetry_upload_exits_nonzero_keeps_local_files_and_retries(data_root, caplog):
    _two_clients(data_root)
    s3 = FakeS3()
    _run(data_root, backfill=True, sync=True, validate=True, s3=s3)
    source = pd.read_csv(_source(data_root), low_memory=False)
    source.loc[source.AlertID == "TEL-5", "imp_lb_psi_Value"] = 9.0
    source.to_csv(_source(data_root), index=False)
    s3.fail_put = {k for k in s3.objects if k.endswith("2026-07-13/telemetry.parquet")}
    with caplog.at_level("ERROR"):
        assert _run(data_root, sync=True, s3=s3) == cli.EXIT_S3_ERROR == 2
    assert "telemetry S3 sync failed" in caplog.text
    assert _validate(data_root).ok
    s3.fail_put.clear()
    assert _run(data_root, sync=True, s3=s3) == 0
    assert _run(data_root, verify=True, s3=s3) == 0


def test_a_telemetry_failure_does_not_stop_the_alerts_and_vice_versa(data_root, monkeypatch):
    _two_clients(data_root)
    monkeypatch.setattr(cli.telemetry_builder, "build_client", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad csv")))
    assert _run(data_root, backfill=True, validate=True) == cli.EXIT_BUILD_ERROR
    assert alert_store.has_partitions(_client_dir(data_root))              # the alerts half still ran


def test_a_vanished_source_with_existing_partitions_is_an_error_and_deletes_nothing(data_root):
    _two_clients(data_root)
    assert _run(data_root, backfill=True, validate=True) == 0
    before = {p: _sha(p) for p in _client_dir(data_root).rglob("telemetry.parquet")}
    _source(data_root).unlink()                         # e.g. the data mount is missing
    assert _run(data_root) == cli.EXIT_BUILD_ERROR
    assert before == {p: _sha(p) for p in _client_dir(data_root).rglob("telemetry.parquet")}


def test_the_script_is_the_only_code_that_names_the_telemetry_source():
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for folder in ("src", "dashboard", "config"):
        for path in (root / folder).rglob("*"):
            if path.suffix in {".py", ".json", ".md", ".yml", ".yaml"} and "__pycache__" not in path.parts:
                if "wide_with_gps" in path.read_text(encoding="utf-8", errors="ignore"):
                    offenders.append(str(path.relative_to(root)))
    assert offenders == []
    assert "wide_with_gps" in SCRIPT.read_text(encoding="utf-8")
