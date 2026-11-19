"""Partitioned alert storage (one Parquet file per week): layout, partitioner, read path, S3 sync, schedule.

The views must show exactly what they showed when they loaded the whole CSV, so the central
tests here run the previous General-tab algorithm over the whole CSV history (`csv_history`, the
oracle of the removed CSV loader) and compare it, output by output, with the partitioned callback.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from plotly.utils import PlotlyJSONEncoder

from dashboard.callbacks import alerts_callbacks as callbacks
from tests.alert_partition_support import csv_history
from dashboard.components.alerts_report import (
    alert_filter_catalog,
    alert_summary,
    prepare_alert_rows,
)
from dashboard.tabs.tab_alerts_detail import create_layout as detail_layout
from dashboard.tabs.tab_alerts_general import default_alert_dates
from src.data import alert_partition_builder as builder
from src.data import alert_partition_s3 as s3_sync
from src.data import alert_partitions as store
from src.data import loaders
from src.utils.date_utils import format_local
from tests.alert_partition_support import FakeS3

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "partition_alerts.py"
_spec = importlib.util.spec_from_file_location("partition_alerts_script", SCRIPT)
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

def _row(n, unit, when, system="motor", signal="imp_lb_psi", trigger="Telemetria", **extra):
    return {
        "FusionID": f"F-{n:03d}", "TelemetryID": f"T-{n}", "TribologyID": extra.pop("TribologyID", None),
        "Timestamp": when, "UnitId": unit, "Trigger_type": trigger, "Trigger_Var": signal,
        "mensaje_ia": f"Diagnóstico: caso {n}\nCausa probable: desgaste\nAcciones: revisar",
        "sistema": system, "subsistema": "admission", "componente": "engine", "SourceType": "x",
        **extra,
    }


def _dataset():
    """Several weeks and units, ISO offsets, week boundaries and ties on purpose."""
    rows = [
        _row(1, "CA-1", "2026-07-05T23:59:00+00:00"),                         # Sunday: week of 06-29
        _row(2, "CA-1", "2026-07-06T00:00:00+00:00"),                         # Monday: week of 07-06
        _row(3, "CA-2", "2026-07-06T00:00:00+00:00", system="frenos"),        # tie with #2, other unit
        _row(4, "CA-1", "2026-07-10T12:00:00-04:00", signal="imt_lbf_c"),     # offset -> 16:00 UTC
        _row(5, "CA-3", "2026-07-12T16:00:00+00:00", signal=None),
        _row(6, "CA-2", "2026-07-13T08:00:00+00:00", trigger="Mixto", TribologyID=77.0),
        _row(7, "CA-2", "2026-07-20T16:00:00+00:00", system="frenos"),
        _row(8, "CA-3", "2026-07-21T01:00:00+00:00", trigger="Tribologia", TribologyID=78.0),
        _row(9, "CA-1", "2026-07-27T16:00:00+00:00"),
        _row(10, "CA-4", "2026-08-03T16:00:00+00:00", signal="brake_temp", system="frenos"),
    ]
    return pd.DataFrame(rows)


def _write_csv(root: Path, client: str, frame: pd.DataFrame) -> Path:
    path = root / "alerts" / "golden" / client / "consolidated_alerts.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DASHBOARD_FRAME_ENGINE", "pandas")
    callbacks._cached_alert_catalog.cache_clear()
    return tmp_path


@pytest.fixture
def built(data_root):
    csv = _write_csv(data_root, "capstone", _dataset())
    return data_root, csv, builder.build_client("capstone", data_root)


def _client_dir(root, client="capstone"):
    return root / "alerts" / "golden" / client


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Layout and partitioner
# ---------------------------------------------------------------------------

def test_weeks_are_monday_dates_on_the_utc_clock_the_weekly_chart_uses(built):
    root, _, result = built
    weeks = store.list_weeks(_client_dir(root))
    assert weeks == ["2026-06-29", "2026-07-06", "2026-07-13", "2026-07-20", "2026-07-27", "2026-08-03"]
    # Sunday 23:59 UTC belongs to the week of 06-29, Monday 00:00 UTC opens 07-06.
    assert (_client_dir(root) / "2026-06-29" / "file.parquet").is_file()
    assert (_client_dir(root) / "2026-07-06" / "file.parquet").is_file()
    # An alert with an offset is placed by its UTC instant (12:00-04:00 == 16:00Z, same week).
    assert result.partition_files["2026-07-06/file.parquet"].rows == 4  # #2, #3, #4 and #5
    ts = pd.Series(pd.to_datetime(["2026-07-05 23:59", "2026-07-06 00:00"]))
    assert store.week_starts(ts).tolist() == ["2026-06-29", "2026-07-06"]


def test_week_id_is_the_weekly_chart_bar(built):
    """A partition is exactly one bar of Evolución temporal: same expression, same key."""
    from dashboard.components.alerts_charts import create_alerts_per_week_chart

    root, _, _ = built
    frame = prepare_alert_rows(csv_history("capstone"))
    figure = create_alerts_per_week_chart(frame)
    bars = {week[0] for trace in figure.data for week in trace.customdata}
    assert bars == set(store.list_weeks(_client_dir(root)))


def test_every_week_has_one_partition_with_every_unit_and_row_totals_match_the_csv(built):
    root, csv, result = built
    source = pd.read_csv(csv)
    assert result.source_rows == result.partition_rows == len(source) == 10
    assert (_client_dir(root) / "_alert_index.parquet").is_file()
    files = sorted(_client_dir(root).rglob("file.parquet"))
    assert [(p.parent.name, p.parent.parent.name) for p in files] == [(w, "capstone") for w in store.list_weeks(_client_dir(root))]
    assert {w: f.rows for w, f in ((k.split("/")[0], v) for k, v in result.partition_files.items())} == {
        "2026-06-29": 1, "2026-07-06": 4, "2026-07-13": 1, "2026-07-20": 2, "2026-07-27": 1, "2026-08-03": 1,
    }
    # No unit folders: the week holds every unit.
    assert not [d for d in _client_dir(root).glob("*/*") if d.is_dir()]
    week = store.read_scope(_client_dir(root), ["2026-07-06"])
    assert set(week["UnitId"]) == {"CA-1", "CA-2", "CA-3"}


def test_partitions_equal_the_csv_in_columns_dtypes_values_and_order(built):
    root, csv, _ = built
    report = builder.validate_client("capstone", root)
    assert report.ok, report.problems

    source = pd.read_csv(csv)
    combined = store.read_scope(_client_dir(root), store.list_weeks(_client_dir(root)))
    assert list(combined.columns) == list(source.columns)
    assert [str(d) for d in combined.dtypes] == [str(d) for d in source.dtypes]
    pd.testing.assert_frame_equal(combined, source)  # values, nulls, floats, source row order


def test_partition_rows_come_back_in_source_order_even_for_equal_timestamps(built):
    root, csv, _ = built
    combined = store.read_scope(_client_dir(root), ["2026-07-06"])
    # #2 (CA-1) and #3 (CA-2) share a timestamp and live in different partitions; #4 and #5 follow.
    assert combined["FusionID"].tolist() == ["F-002", "F-003", "F-004", "F-005"]


def test_the_source_csv_is_never_modified(data_root):
    csv = _write_csv(data_root, "capstone", _dataset())
    before = (_sha(csv), csv.stat().st_mtime_ns)
    builder.build_client("capstone", data_root)
    builder.build_client("capstone", data_root)
    assert (_sha(csv), csv.stat().st_mtime_ns) == before


def test_rerun_on_the_same_source_changes_nothing(built):
    root, _, first = built
    snapshot = {p: (_sha(p), p.stat().st_mtime_ns) for p in _client_dir(root).rglob("*.parquet")}
    second = builder.build_client("capstone", root)
    assert second.written == [] and second.unchanged == len(first.partition_files) and second.removed == []
    assert snapshot == {p: (_sha(p), p.stat().st_mtime_ns) for p in _client_dir(root).rglob("*.parquet")}
    assert {r: f.sha256 for r, f in first.files.items()} == {r: f.sha256 for r, f in second.files.items()}


def test_changed_source_regenerates_exactly_the_changed_partitions_including_the_current_week(built):
    root, csv, first = built
    source = pd.read_csv(csv)
    # A new alert in the (in-progress) last week, and a corrected message in an old week.
    source = pd.concat([source, pd.DataFrame([_row(11, "CA-4", "2026-08-05T10:00:00+00:00")])], ignore_index=True)
    source.loc[source.FusionID == "F-001", "mensaje_ia"] = "Diagnóstico: corregido"
    source.to_csv(csv, index=False)

    second = builder.build_client("capstone", root)
    assert set(second.written) == {"2026-08-03/file.parquet", "2026-06-29/file.parquet", "_alert_index.parquet"}
    assert second.partition_rows == 11
    assert builder.validate_client("capstone", root).ok


def test_partitions_the_source_no_longer_yields_are_removed_and_nothing_else_is_touched(built):
    root, csv, _ = built
    other = _client_dir(root) / "backtest" / "keep.txt"
    other.parent.mkdir(parents=True)
    other.write_text("not an alert partition")
    source = pd.read_csv(csv)
    source[source.FusionID != "F-010"].to_csv(csv, index=False)

    result = builder.build_client("capstone", root)
    assert result.removed == ["2026-08-03/file.parquet"]
    assert not (_client_dir(root) / "2026-08-03").exists()  # emptied folders go too
    assert other.read_text() == "not an alert partition" and csv.is_file()


def test_a_failed_replace_leaves_the_previous_partition_and_no_temp_file(built, monkeypatch):
    root, csv, _ = built
    target = _client_dir(root) / "2026-08-03" / "file.parquet"
    before = target.read_bytes()
    source = pd.read_csv(csv)
    source.loc[source.FusionID == "F-010", "mensaje_ia"] = "cambiado"
    source.to_csv(csv, index=False)

    def broken_replace(src, dst):
        raise OSError("disk went away")

    monkeypatch.setattr(builder.os, "replace", broken_replace)
    with pytest.raises(OSError):
        builder.build_client("capstone", root)
    assert target.read_bytes() == before                       # still the complete old file
    assert store.read_scope(_client_dir(root), ["2026-08-03"]).shape[0] == 1
    assert not list(_client_dir(root).rglob("*.tmp-*"))        # no half-written leftovers
    assert not (_client_dir(root) / ".alerts_partition.lock").exists()


def test_a_reader_during_a_rebuild_only_ever_sees_complete_files(built):
    """Replacement is write-temp-then-rename: every file a listing can show is readable."""
    root, csv, _ = built
    paths = list(_client_dir(root).rglob("file.parquet"))
    for _ in range(3):
        builder.build_client("capstone", root)
        for path in paths:
            assert store.read_paths([path]).shape[0] >= 1


def test_two_builds_cannot_overlap(data_root):
    _write_csv(data_root, "capstone", _dataset())
    lock = _client_dir(data_root) / ".alerts_partition.lock"
    lock.write_text("123")
    with pytest.raises(builder.PartitionBuildError, match="Another partition run"):
        builder.build_client("capstone", data_root)
    old = datetime.now().timestamp() - 3 * 3600
    os.utime(lock, (old, old))  # a crashed run's lock is taken over
    assert builder.build_client("capstone", data_root).source_rows == 10


def test_any_unit_id_is_just_data_not_a_path(data_root):
    odd = ["A/B", "..", "Camión 1", "CON", "ca-1", "CA-1"]
    frame = pd.DataFrame([_row(i, unit, f"2026-07-0{i + 1}T10:00:00+00:00") for i, unit in enumerate(odd)])
    _write_csv(data_root, "capstone", frame)
    builder.build_client("capstone", data_root)
    assert builder.validate_client("capstone", data_root).ok
    assert sorted(p.parent.name for p in _client_dir(data_root).rglob("file.parquet")) == ["2026-06-29", "2026-07-06"]
    assert set(loaders.load_alerts_for_scope("capstone")["UnitId"]) == set(odd)
    # Selection is an exact match, also between ids that differ only by case.
    assert loaders.load_alerts_for_scope("capstone", units=["ca-1"])["FusionID"].tolist() == ["F-004"]
    assert loaders.load_alerts_for_scope("capstone", units=["A/B", "Camión 1"]).shape[0] == 2


def test_the_previous_unit_folder_layout_is_cleared_on_the_next_run(built):
    root, _, _ = built
    legacy = _client_dir(root) / "2026-07-06" / "CA-1"
    legacy.mkdir()
    (legacy / "file.parquet").write_bytes(b"old layout")
    other = _client_dir(root) / "2026-07-06" / "notes"
    other.mkdir()
    (other / "readme.txt").write_text("not ours")
    result = builder.build_client("capstone", root)
    assert result.removed == ["2026-07-06/CA-1/file.parquet"]
    assert not legacy.exists() and (other / "readme.txt").exists()  # only layout folders go


def test_rows_without_a_parsable_date_or_unit_are_kept_not_dropped(data_root):
    frame = pd.DataFrame([
        _row(1, "CA-1", "2026-07-06T10:00:00+00:00"),
        _row(2, "CA-1", None),
        _row(3, None, "2026-07-06T10:00:00+00:00"),
    ])
    _write_csv(data_root, "capstone", frame)
    result = builder.build_client("capstone", data_root)
    assert result.partition_rows == 3 == result.source_rows
    assert set(result.partition_files) == {"undated/file.parquet", "2026-07-06/file.parquet"}
    assert result.partition_files["2026-07-06/file.parquet"].rows == 2  # the one without a unit is kept
    assert builder.validate_client("capstone", data_root).ok
    # Only a fully open range reads the undated rows (a date bound would drop them anyway).
    assert loaders.load_alerts_for_scope("capstone").shape[0] == 3
    assert loaders.load_alerts_for_scope("capstone", start_date="2026-01-01").shape[0] == 2


def test_every_client_with_a_consolidated_csv_is_found(data_root):
    for client in ("capstone", "cda"):
        _write_csv(data_root, client, _dataset())
    (data_root / "alerts" / "golden" / "emptydir").mkdir()
    assert builder.discover_clients(data_root) == ["capstone", "cda"]


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

@pytest.fixture
def read_log(monkeypatch):
    seen: list[str] = []
    real = store.pq.read_table

    def spy(path, *args, **kwargs):
        path = Path(path)
        seen.append(path.name if path.name.startswith("_") else f"{path.parent.name}/{path.name}")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(store.pq, "read_table", spy)
    return seen


def test_a_range_reads_only_its_week_files_and_a_unit_selection_keeps_that_unit(built, read_log):
    frame = loaders.load_alerts_for_scope("capstone", units=["CA-2"], start_date="2026-07-06", end_date="2026-07-26")
    # Chile 07-06 .. 07-26 is 07-06 04:00 .. 07-27 04:00 UTC, which touches the week that opens
    # on Monday 07-27 00:00 UTC: four week files, no more.
    assert sorted(read_log) == [
        "2026-07-06/file.parquet", "2026-07-13/file.parquet", "2026-07-20/file.parquet", "2026-07-27/file.parquet",
    ]
    assert set(frame["UnitId"]) == {"CA-2"} and len(frame) == 3


def test_all_units_come_with_the_selected_weeks(built, read_log):
    # Desde/Hasta are Chile calendar days: 07-13 .. 07-19 ends at 07-20 04:00 UTC, so the next
    # UTC week (07-20) is opened too; the row filters then trim it away.
    frame = loaders.load_alerts_for_scope("capstone", start_date="2026-07-13", end_date="2026-07-19")
    assert sorted(read_log) == ["2026-07-13/file.parquet", "2026-07-20/file.parquet"]
    assert len(frame) == 3
    assert callbacks.update_general_tab("capstone", "2026-07-13", "2026-07-19", {})[5].startswith("Mostrando 1 alertas")
    read_log.clear()
    loaders.load_alerts_for_scope("capstone", start_date="2026-07-06", end_date="2026-07-12")
    assert sorted(read_log) == ["2026-07-06/file.parquet", "2026-07-13/file.parquet"]


def test_a_range_starting_mid_week_reads_the_whole_week_then_trims_to_the_exact_range(built):
    # Desde 07-08 (Chile midnight) is mid-week: the week of 07-06 is opened ...
    weeks = store.select_weeks(_client_dir(built[0]), *loaders._utc_bounds("2026-07-08", "2026-07-14"))
    assert weeks == ["2026-07-06", "2026-07-13"]
    frame = prepare_alert_rows(loaders.load_alerts_for_scope("capstone", start_date="2026-07-08", end_date="2026-07-14"))
    assert {"F-002", "F-003"} <= set(frame["FusionID"])  # ... so its early alerts were read

    # ... and the exact range is what the views then show.
    caption = callbacks.update_general_tab("capstone", "2026-07-08", "2026-07-14", {})[5]
    assert "Mostrando 3 alertas de 3 unidades" in caption  # #4 (07-10), #5 (07-12), #6 (07-13)
    # One Chile day: 07-05 spans 07-05 04:00 .. 07-06 04:00 UTC, i.e. the Sunday-night alert of
    # one UTC week and the two Monday-00:00 alerts of the next.
    assert callbacks.update_general_tab("capstone", "2026-07-05", "2026-07-05", {})[5].startswith("Mostrando 3 alertas de 2 unidades")


def test_weeks_and_units_without_partitions_are_empty_not_errors(built):
    assert loaders.load_alerts_for_scope("capstone", start_date="2030-01-01", end_date="2030-02-01").empty
    assert loaders.load_alerts_for_scope("capstone", units=["NOPE"]).empty
    assert loaders.load_alerts_for_scope("ghost-client").empty
    assert loaders.load_alert_by_id("capstone", "F-999").empty
    # The views degrade to their empty states.
    out = callbacks.update_general_tab("capstone", "2030-01-01", "2030-02-01", {})
    assert out[5].startswith("No hay alertas para los filtros")
    assert callbacks.initialize_alert_dropdown("capstone", None, None, "2030-01-01", "all", None) == []
    assert callbacks.initialize_alert_dropdown("ghost-client", None, None, None, "all", None) == []


def test_a_unit_selected_without_alerts_in_range_keeps_the_fleet_charts(built):
    figures = callbacks.update_general_tab("capstone", "2026-07-06", "2026-07-12", {"unit": ["CA-4"]})
    assert "No hay alertas para los filtros" in figures[5]
    # The unit chart still shows the units that do have alerts in that range.
    assert {x for trace in figures[0].data for x in trace.x} == {"CA-1", "CA-3"}


def test_neither_view_needs_the_consolidated_csv_at_runtime(built, monkeypatch):
    root, csv, _ = built
    csv.unlink()
    original = pd.read_csv

    def guard(path, *args, **kwargs):
        assert "consolidated_alerts" not in str(path), "the CSV was read"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", guard)
    monkeypatch.setattr(loaders, "fast_read_csv", lambda *a, **k: pytest.fail("the CSV was read"))
    assert callbacks.sync_filter_controls("capstone", {})[0]
    assert "Mostrando 10 alertas" in callbacks.update_general_tab("capstone", None, None, {})[5]
    assert callbacks.populate_detail_filter_options("capstone")[0]
    assert callbacks.initialize_alert_dropdown("capstone", None, None, None, "all", None)
    assert callbacks.filter_alert_dropdown_by_criteria(None, None, None, "all", "capstone", None)
    assert "F-006" in str(callbacks.update_detail_view("F-006", "capstone", None))


# ---------------------------------------------------------------------------
# Vista General: identical to the previous (full CSV) implementation
# ---------------------------------------------------------------------------

def _legacy_general(client, start_date, end_date, active_filters):
    """The previous `update_general_tab` body, over the whole CSV."""
    alerts_df = csv_history(client)
    filters = callbacks._normalise_filters(active_filters)
    prepared = prepare_alert_rows(alerts_df)
    in_range = callbacks._filtered_alerts(prepared, start_date, end_date, {})
    if in_range.empty:
        return None
    filtered_df = callbacks._filtered_alerts(prepared, start_date, end_date, filters)
    s = callbacks.settings
    unit_chart = callbacks.create_alerts_per_unit_chart(
        callbacks._filtered_alerts(prepared, start_date, end_date, filters, skip=("unit",)),
        target_pct=s.alert_unit_chart_target_pct, max_bars=s.alert_unit_chart_max_bars,
        selected_units=filters.get("unit", []),
    )
    week_chart = callbacks.create_alerts_per_week_chart(
        callbacks._filtered_alerts(prepared, start_date, end_date, filters, skip=("week",)),
        selected_week=filters.get("week"),
        week_range=(in_range["Timestamp"].min(), in_range["Timestamp"].max()),
    )
    treemap = callbacks.create_system_signal_treemap(
        callbacks._filtered_alerts(prepared, start_date, end_date, filters, skip=("system", "trigger")),
        selected_system=filters.get("system"), selected_trigger=filters.get("trigger"),
    )
    summary = alert_summary(filtered_df)
    stats = callbacks.create_summary_stats_display(summary["total"], summary["units"], mixed_count=summary["mixed"])
    table = None if filtered_df.empty else callbacks.create_alerts_report_table(filtered_df)
    caption = "" if filtered_df.empty else (
        f"{summary['total']}|{summary['units']}|{format_local(summary['latest'])}"
    )
    return [unit_chart, week_chart, treemap, stats, table], caption, summary


def _encode(value):
    return json.dumps(value, cls=PlotlyJSONEncoder, sort_keys=True, default=str)


SCENARIOS = [
    ("whole history", None, None, {}),
    ("range", "2026-07-06", "2026-07-26", {}),
    ("mid-week start", "2026-07-08", "2026-07-21", {}),
    ("only Desde", "2026-07-13", None, {}),
    ("only Hasta", None, "2026-07-12", {}),
    ("one unit", None, None, {"unit": ["CA-2"]}),
    ("two units + range", "2026-07-06", "2026-07-26", {"unit": ["CA-1", "CA-3"]}),
    ("unit + system", None, None, {"unit": ["CA-2", "CA-3"], "system": "Frenos"}),
    ("week click", None, None, {"week": "2026-07-06"}),
    ("unit + week + trigger", None, None, {"unit": ["CA-1", "CA-2"], "week": "2026-07-06", "trigger": "imp_lb_psi"}),
    ("trigger", None, None, {"trigger": "imt_lbf_c"}),
    ("unit without alerts in range", "2026-07-06", "2026-07-12", {"unit": ["CA-4"]}),
    ("unknown unit", None, None, {"unit": ["NOPE"]}),
]


@pytest.mark.parametrize("name,start,end,active", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_general_view_matches_the_previous_implementation(built, name, start, end, active):
    legacy = _legacy_general("capstone", start, end, active)
    assert legacy is not None
    components, caption, summary = legacy
    unit_chart, week_chart, treemap, stats, table, text = callbacks.update_general_tab("capstone", start, end, active)

    assert _encode(unit_chart) == _encode(components[0])      # Distribución por unidad
    assert _encode(week_chart) == _encode(components[1])      # Evolución temporal
    assert _encode(treemap) == _encode(components[2])         # Distribución por sistema
    assert _encode(stats) == _encode(components[3])           # KPIs: total, unidades, multitécnicas
    if components[4] is None:
        assert "No hay alertas" in text
    else:
        assert _encode(table) == _encode(components[4])
        total, units, latest = caption.split("|")
        assert text == f"Mostrando {total} alertas de {units} unidades · Última alerta: {latest}" or latest in text
        assert f"{summary['total']}" in text


def test_filter_options_come_from_the_whole_history_like_before(built):
    full = alert_filter_catalog(csv_history("capstone"))
    assert callbacks._alert_catalog("capstone") == full
    assert full["units"] == ["CA-1", "CA-2", "CA-3", "CA-4"]
    # ... even though a 1-week range only loads one week.
    assert callbacks.sync_filter_controls("capstone", {})[0] == [
        {"label": u, "value": u} for u in full["units"]
    ]


def test_unit_chart_is_not_narrowed_by_the_unit_selection(built):
    everyone = callbacks.update_general_tab("capstone", None, None, {})[0]
    selected = callbacks.update_general_tab("capstone", None, None, {"unit": ["CA-2"]})[0]
    assert {x for t in selected.data for x in t.x} == {x for t in everyone.data for x in t.x}


# ---------------------------------------------------------------------------
# Vista Detallada
# ---------------------------------------------------------------------------

def _recent_dataset():
    today = date.today()
    start = today - timedelta(weeks=12)
    rows = []
    for i in range(36):
        day = start + timedelta(days=i * 2 + 1)
        rows.append(_row(
            i, f"CA-{i % 3 + 1}", f"{day.isoformat()}T15:00:00+00:00",
            trigger="Mixto" if i % 2 else "Telemetria", TribologyID=100.0 + i if i % 2 else None,
        ))
    return pd.DataFrame(rows)


@pytest.fixture
def recent(data_root):
    _write_csv(data_root, "capstone", _recent_dataset())
    return builder.build_client("capstone", data_root)


def test_detail_opens_on_the_last_four_weeks_same_calculation_as_the_general_view():
    from dash import dcc

    def find(component):
        if getattr(component, "id", None) == "detail-filter-date-from":
            return component
        children = getattr(component, "children", None)
        for child in children if isinstance(children, (list, tuple)) else [children]:
            if hasattr(child, "children") or hasattr(child, "id"):
                found = find(child)
                if found is not None:
                    return found
        return None

    picker = find(detail_layout())
    assert isinstance(picker, dcc.DatePickerSingle)
    assert picker.date == default_alert_dates()[0]
    assert picker.clearable and picker.placeholder == "Sin límite"  # "Sin límite" stays selectable


def test_opening_detail_does_not_load_the_full_history(recent, read_log):
    start = default_alert_dates()[0]
    options = callbacks.initialize_alert_dropdown("capstone", None, None, start, "all", None)
    weeks = {entry.split("/")[0] for entry in read_log if entry.endswith("file.parquet") and "/" in entry}
    assert weeks and min(weeks) >= (date.fromisoformat(start) - timedelta(days=6)).isoformat()
    assert len(weeks) <= 5
    # Only alerts of the loaded scope are listed.
    assert 0 < len(options) < 36
    assert all(
        date.fromisoformat(o["label"].split(" | ")[1][:10]) >= date.fromisoformat(start) for o in options
    )


def test_sin_limite_returns_the_full_history(recent, read_log):
    options = callbacks.filter_alert_dropdown_by_criteria(None, None, None, "all", "capstone", None)
    assert len(options) == 36
    assert len({entry.split("/")[0] for entry in read_log}) >= 10
    assert len(callbacks.initialize_alert_dropdown("capstone", None, None, None, "all", None)) == 36


def test_detail_filters_work_from_the_partitions(recent):
    f = callbacks.filter_alert_dropdown_by_criteria
    everything = f(None, None, None, "all", "capstone", None)
    only_unit = f(["CA-1"], None, None, "all", "capstone", None)
    assert 0 < len(only_unit) < len(everything) and all("| CA-1 |" in o["label"] for o in only_unit)
    with_oil = f(None, None, None, "yes", "capstone", None)
    without = f(None, None, None, "no", "capstone", None)
    assert len(with_oil) + len(without) == len(everything) == 36
    assert len(f(None, ["motor"], None, "all", "capstone", None)) == 36
    assert f(None, ["frenos"], None, "all", "capstone", None) == []
    recent_only = f(None, None, default_alert_dates()[0], "all", "capstone", None)
    assert 0 < len(recent_only) < 36


def test_selector_matches_the_previous_implementation_for_the_same_filters(built):
    """Same options, same order, as the old full-CSV `_filter_alerts` over the same rows."""
    for units, sistemas, start, tribology in [
        (None, None, None, "all"), (None, None, None, "yes"), (["CA-2"], None, "2026-07-08", "all"),
        (None, ["frenos"], None, "no"), (["CA-1", "CA-3"], ["motor"], "2026-07-06", "yes"),
    ]:
        legacy = callbacks._alert_dropdown_options(
            callbacks._filter_alerts(csv_history("capstone"), "capstone", units, sistemas, start, tribology)
        )
        assert callbacks.filter_alert_dropdown_by_criteria(units, sistemas, start, tribology, "capstone", None) == legacy
        assert callbacks.initialize_alert_dropdown("capstone", units, sistemas, start, tribology, None) == legacy


def test_an_alert_outside_the_loaded_weeks_stays_selectable_when_navigated_to(recent):
    start = default_alert_dates()[0]
    old = "F-001"  # about eleven weeks old
    base = callbacks.initialize_alert_dropdown("capstone", None, None, start, "all", None)
    assert old not in {o["value"] for o in base}
    kept = callbacks.initialize_alert_dropdown("capstone", None, None, start, "all", {"alert_id": old})
    assert old in {o["value"] for o in kept} and len(kept) == len(base) + 1


def test_alert_detail_reads_a_single_partition_and_is_unchanged(built, read_log):
    detail = callbacks.update_detail_view("F-006", "capstone", None)
    assert [e for e in read_log if e.endswith("file.parquet")] == ["2026-07-13/file.parquet"]
    legacy_row = csv_history("capstone").query("FusionID == 'F-006'").iloc[0]
    assert _encode(detail.children[0]) == _encode(callbacks._alert_case_header(legacy_row))
    assert "no encontrada" in str(callbacks.update_detail_view("F-404", "capstone", None))


def test_detail_filter_options_list_the_whole_history(built):
    units, systems = callbacks.populate_detail_filter_options("capstone")
    assert [u["value"] for u in units] == ["CA-1", "CA-2", "CA-3", "CA-4"]
    assert [s["value"] for s in systems] == ["frenos", "motor"]


# ---------------------------------------------------------------------------
# S3 sync
# ---------------------------------------------------------------------------

CONFIG = s3_sync.S3Config(bucket="bucket", prefix="MultiTechnique Alerts/alerts/golden")


def _keys(s3, client="capstone"):
    return {k for k in s3.objects if k.startswith(f"{CONFIG.prefix}/{client}/")}


def test_backfill_sync_mirrors_the_local_layout_and_marks_the_history_complete(built):
    _, _, result = built
    s3 = FakeS3()
    sync = s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=False, write_backfill_marker=True)
    prefix = "MultiTechnique Alerts/alerts/golden/capstone"
    assert _keys(s3) == {f"{prefix}/{rel}" for rel in result.files} | {f"{prefix}/_backfill_complete.json"}
    assert f"{prefix}/2026-07-06/file.parquet" in s3.objects
    assert sync.marker_written and len(sync.uploaded) == len(result.files)
    assert s3_sync.verify_client(s3, CONFIG, result) == []


def test_s3_partitions_have_the_same_rows_as_the_local_ones(built):
    import io
    import pyarrow.parquet as pq

    _, _, result = built
    s3 = FakeS3()
    s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=False, write_backfill_marker=True)
    for rel, local in result.partition_files.items():
        remote = s3.objects[f"{CONFIG.prefix}/capstone/{rel}"]
        assert pq.read_table(io.BytesIO(remote["Body"])).num_rows == local.rows == int(remote["Metadata"]["rows"])


def test_rerunning_the_sync_uploads_nothing_and_creates_no_duplicates(built):
    _, _, result = built
    s3 = FakeS3()
    s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=False, write_backfill_marker=True)
    before = {k: v["Body"] for k, v in s3.objects.items()}
    s3.puts.clear()
    again = s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=True)
    assert again.uploaded == [] and again.unchanged == len(result.files) and s3.puts == []
    assert {k: v["Body"] for k, v in s3.objects.items()} == before


def test_weekly_sync_uploads_every_regenerated_partition_including_the_current_week(built):
    root, csv, first = built
    s3 = FakeS3()
    s3_sync.sync_client(s3, CONFIG, first, require_backfill_marker=False, write_backfill_marker=True)
    source = pd.read_csv(csv)
    source = pd.concat([source, pd.DataFrame([_row(11, "CA-4", "2026-08-05T10:00:00+00:00")])], ignore_index=True)
    source.to_csv(csv, index=False)

    second = builder.build_client("capstone", root)
    sync = s3_sync.sync_client(s3, CONFIG, second, require_backfill_marker=True)
    assert set(sync.uploaded) == {"2026-08-03/file.parquet", "_alert_index.parquet"}
    assert s3_sync.verify_client(s3, CONFIG, second) == []


def test_the_weekly_sync_refuses_to_run_before_the_backfill_reached_s3(built):
    _, _, result = built
    s3 = FakeS3()
    with pytest.raises(s3_sync.S3SyncError, match="no complete history"):
        s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=True)
    assert s3.puts == []


def test_a_failed_upload_is_reported_keeps_local_files_and_is_retried_next_run(built):
    root, _, result = built
    s3 = FakeS3()
    s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=False, write_backfill_marker=True)

    local = {p: _sha(p) for p in _client_dir(root).rglob("file.parquet")}
    stale_key = f"{CONFIG.prefix}/capstone/2026-08-03/file.parquet"
    # Next week's data changes one partition; its upload fails.
    csv = _client_dir(root) / "consolidated_alerts.csv"
    source = pd.read_csv(csv)
    source.loc[source.FusionID == "F-010", "mensaje_ia"] = "nuevo texto"
    source.to_csv(csv, index=False)
    second = builder.build_client("capstone", root)
    s3.fail_put.add(stale_key)

    with pytest.raises(s3_sync.S3SyncError, match="1 of .* uploads failed"):
        s3_sync.sync_client(s3, CONFIG, second, require_backfill_marker=True)
    # Local output is valid and complete; S3 still holds the old (complete) object.
    assert builder.validate_client("capstone", root).ok
    assert s3.objects[stale_key]["Metadata"]["sha256"] != second.files["2026-08-03/file.parquet"].sha256

    # Next run: same local files, S3 healthy again -> the pending partition goes up.
    s3.fail_put.clear()
    retried = builder.build_client("capstone", root)
    assert retried.written == []  # nothing to regenerate ...
    sync = s3_sync.sync_client(s3, CONFIG, retried, require_backfill_marker=True)
    assert sync.uploaded == ["2026-08-03/file.parquet"]  # ... but the pending upload is retried
    assert s3_sync.verify_client(s3, CONFIG, retried) == []
    assert local.keys() == {p for p in _client_dir(root).rglob("file.parquet")}


def test_partitions_gone_from_the_source_are_deleted_from_s3_and_other_objects_are_not(built):
    root, csv, result = built
    s3 = FakeS3()
    prefix = f"{CONFIG.prefix}/capstone"
    s3.objects[f"{prefix}/consolidated_alerts.csv"] = {"Body": b"csv", "Metadata": {}}
    s3.objects[f"{prefix}/backtest/x/file.parquet"] = {"Body": b"bt", "Metadata": {}}
    # An object of the previous {week}/{unit}/ layout, if one was ever synced, is cleared too.
    s3.objects[f"{prefix}/2026-07-06/CA-1/file.parquet"] = {"Body": b"old", "Metadata": {}}
    first = s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=False, write_backfill_marker=True)
    assert first.deleted == ["2026-07-06/CA-1/file.parquet"]
    assert f"{prefix}/2026-07-06/CA-1/file.parquet" not in s3.objects
    source = pd.read_csv(csv)
    source[source.FusionID != "F-010"].to_csv(csv, index=False)
    sync = s3_sync.sync_client(s3, CONFIG, builder.build_client("capstone", root), require_backfill_marker=True)
    assert sync.deleted == ["2026-08-03/file.parquet"]
    assert f"{prefix}/2026-08-03/file.parquet" not in s3.objects
    assert f"{prefix}/consolidated_alerts.csv" in s3.objects and f"{prefix}/backtest/x/file.parquet" in s3.objects


def test_verification_reports_every_kind_of_mismatch(built):
    _, _, result = built
    s3 = FakeS3()
    s3_sync.sync_client(s3, CONFIG, result, require_backfill_marker=False, write_backfill_marker=True)
    prefix = f"{CONFIG.prefix}/capstone"
    del s3.objects[f"{prefix}/2026-07-06/file.parquet"]
    s3.objects[f"{prefix}/2026-07-13/file.parquet"]["Body"] += b"x"
    s3.objects[f"{prefix}/2099-01-01/file.parquet"] = {"Body": b"x", "Metadata": {}}
    problems = "\n".join(s3_sync.verify_client(s3, CONFIG, result))
    assert "missing in S3" in problems and "size differs" in problems and "extra in S3" in problems


def test_bucket_and_prefix_are_configurable_and_shared(monkeypatch):
    monkeypatch.delenv("ALERT_PARTITIONS_S3_BUCKET", raising=False)
    monkeypatch.setenv("BUCKET_NAME", "from-env")
    monkeypatch.delenv("ALERT_PARTITIONS_S3_PREFIX", raising=False)
    config = s3_sync.S3Config.from_env()
    assert (config.bucket, config.prefix) == ("from-env", "MultiTechnique Alerts/alerts/golden")
    monkeypatch.setenv("ALERT_PARTITIONS_S3_BUCKET", "special")
    monkeypatch.setenv("ALERT_PARTITIONS_S3_PREFIX", "/other/prefix/")
    config = s3_sync.S3Config.from_env()
    assert (config.bucket, config.client_prefix("CAPSTONE")) == ("special", "other/prefix/capstone")
    monkeypatch.delenv("ALERT_PARTITIONS_S3_BUCKET")
    monkeypatch.delenv("BUCKET_NAME")
    with pytest.raises(s3_sync.S3SyncError):
        s3_sync.S3Config.from_env()


# ---------------------------------------------------------------------------
# Script: modes, exit codes, schedule
# ---------------------------------------------------------------------------

def _run_cli(data_root, *flags, s3=None):
    return cli.run(
        root=str(data_root), clients=None,
        backfill="--backfill" in flags, sync_s3="--sync-s3" in flags or "--weekly" in flags,
        validate="--validate" in flags or "--backfill" in flags,
        s3_options={"bucket": "bucket"}, s3_client=s3,
    )


def test_backfill_runs_locally_with_s3_off_by_default(data_root, monkeypatch):
    _write_csv(data_root, "capstone", _dataset())
    _write_csv(data_root, "cda", _dataset())
    monkeypatch.setattr(cli.s3_sync, "make_s3_client", lambda config: pytest.fail("S3 was used"))
    assert cli.main(["--backfill", "--data-root", str(data_root)]) == 0
    for client in ("capstone", "cda"):
        assert store.has_partitions(_client_dir(data_root, client))
    assert cli.parse_args(["--backfill"]).sync_s3 is False


def test_sync_s3_is_only_for_the_backfill_and_never_implicit():
    with pytest.raises(SystemExit):
        cli.parse_args(["--sync-s3"])
    args = cli.parse_args(["--backfill", "--sync-s3"])
    assert args.backfill and args.sync_s3


def test_backfill_with_the_flag_syncs_then_the_weekly_run_can_follow(data_root):
    _write_csv(data_root, "capstone", _dataset())
    s3 = FakeS3()
    assert cli.run(root=str(data_root), clients=None, backfill=True, sync_s3=True, validate=True,
                   s3_options={"bucket": "bucket"}, s3_client=s3) == 0
    assert any(k.endswith("_backfill_complete.json") for k in s3.objects)
    assert cli.run(root=str(data_root), clients=None, backfill=False, sync_s3=True, validate=False,
                   s3_options={"bucket": "bucket"}, s3_client=s3) == 0


def test_a_failed_weekly_sync_exits_nonzero_and_leaves_valid_local_partitions(data_root, caplog):
    _write_csv(data_root, "capstone", _dataset())
    s3 = FakeS3()
    cli.run(root=str(data_root), clients=None, backfill=True, sync_s3=True, validate=True,
            s3_options={"bucket": "bucket"}, s3_client=s3)
    csv = _client_dir(data_root) / "consolidated_alerts.csv"
    frame = pd.read_csv(csv)
    frame.loc[0, "mensaje_ia"] = "cambio"
    frame.to_csv(csv, index=False)
    s3.fail_put = {k for k in s3.objects if k.endswith("2026-06-29/file.parquet")}

    with caplog.at_level("ERROR"):
        status = cli.run(root=str(data_root), clients=None, backfill=False, sync_s3=True, validate=False,
                         s3_options={"bucket": "bucket"}, s3_client=s3)
    assert status == cli.EXIT_S3_ERROR == 2
    assert "S3 sync failed" in caplog.text
    assert builder.validate_client("capstone", data_root).ok

    s3.fail_put.clear()  # next scheduled run
    assert cli.run(root=str(data_root), clients=None, backfill=False, sync_s3=True, validate=False,
                   s3_options={"bucket": "bucket"}, s3_client=s3) == 0


def test_weekly_run_without_a_bucket_is_an_error_not_a_silent_skip(data_root, monkeypatch):
    _write_csv(data_root, "capstone", _dataset())
    monkeypatch.delenv("BUCKET_NAME", raising=False)
    monkeypatch.delenv("ALERT_PARTITIONS_S3_BUCKET", raising=False)
    assert cli.run(root=str(data_root), clients=None, backfill=False, sync_s3=True, validate=False,
                   s3_options={}) == cli.EXIT_S3_ERROR
    assert store.has_partitions(_client_dir(data_root))  # the local partitions were still produced


def test_a_validation_failure_stops_the_push_to_s3(data_root, monkeypatch):
    _write_csv(data_root, "capstone", _dataset())
    monkeypatch.setattr(cli.builder, "validate_client", lambda *a, **k: builder.ValidationReport(
        "capstone", 10, 9, 5, ["row count: partitions 9 != source 10"]))
    s3 = FakeS3()
    status = cli.run(root=str(data_root), clients=None, backfill=True, sync_s3=True, validate=True,
                     s3_options={"bucket": "bucket"}, s3_client=s3)
    assert status == cli.EXIT_BUILD_ERROR and s3.puts == []


def test_schedule_is_wednesday_four_am_in_an_explicit_timezone():
    args = cli.parse_args([])
    assert (args.weekday, args.time, args.timezone) == ("wednesday", "04:00", "America/Santiago")
    zone = ZoneInfo(args.timezone)
    weekday, run_time = cli.parse_weekday(args.weekday), cli.parse_time(args.time)

    # Tuesday evening -> the next day at 04:00; Wednesday 03:00 -> same day; Wednesday 04:00 -> +7.
    assert cli.next_run(datetime(2026, 11, 17, 20, 0, tzinfo=zone), weekday, run_time) == datetime(2026, 11, 18, 4, 0, tzinfo=zone)
    assert cli.next_run(datetime(2026, 11, 18, 3, 0, tzinfo=zone), weekday, run_time) == datetime(2026, 11, 18, 4, 0, tzinfo=zone)
    assert cli.next_run(datetime(2026, 11, 18, 4, 0, tzinfo=zone), weekday, run_time) == datetime(2026, 11, 25, 4, 0, tzinfo=zone)
    # The wall-clock hour holds across Chile's DST change (first Sunday of September 2026).
    after_change = cli.next_run(datetime(2026, 9, 7, 12, 0, tzinfo=zone), weekday, run_time)
    assert after_change == datetime(2026, 9, 9, 4, 0, tzinfo=zone) and after_change.utcoffset() == timedelta(hours=-3)
    # ... and across the April change back to UTC-4 (summer time ends 2026-04-04).
    summer = cli.next_run(datetime(2026, 3, 30, 12, 0, tzinfo=zone), weekday, run_time)
    winter = cli.next_run(datetime(2026, 4, 6, 12, 0, tzinfo=zone), weekday, run_time)
    assert (summer, summer.utcoffset()) == (datetime(2026, 4, 1, 4, 0, tzinfo=zone), timedelta(hours=-3))
    assert (winter, winter.utcoffset()) == (datetime(2026, 4, 8, 4, 0, tzinfo=zone), timedelta(hours=-4))


def test_schedule_settings_can_be_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("ALERT_PARTITIONS_TIMEZONE", "UTC")
    monkeypatch.setenv("ALERT_PARTITIONS_WEEKDAY", "thursday")
    monkeypatch.setenv("ALERT_PARTITIONS_TIME", "05:30")
    args = cli.parse_args([])
    assert (args.weekday, args.time, args.timezone) == ("thursday", "05:30", "UTC")


def test_a_csv_without_an_optional_column_still_loads_and_scopes(data_root):
    from dashboard.components.alerts_charts import NO_SIGNAL_KEY
    from dashboard.components.alerts_report import prepare_scope_rows

    _write_csv(data_root, "capstone", _dataset().drop(columns=["Trigger_Var"]))
    builder.build_client("capstone", data_root)
    scope = loaders.load_alerts_for_scope("capstone")
    assert len(scope) == 10 and "Trigger_Var" not in scope.columns
    assert set(prepare_scope_rows(scope)["signal_key"]) == {NO_SIGNAL_KEY}  # no signal column = no signal


def test_daily_clients_have_their_own_run_and_the_weekly_run_leaves_them_out():
    zone = ZoneInfo("America/Santiago")
    daily = cli.parse_clients("emin")
    assert daily == ["emin"] and cli.parse_clients("none") == [] and cli.parse_clients("Emin, cda") == ["emin", "cda"]

    found = ["capstone", "cda", "emin"]
    assert cli.weekly_clients(None, daily, found) == ["capstone", "cda"]       # emin has its own run
    assert cli.weekly_clients(None, [], found) == found
    assert cli.weekly_clients(["emin", "capstone"], daily, found) == ["capstone"]
    assert cli.daily_run_clients(None, daily) == ["emin"]
    assert cli.daily_run_clients(["capstone"], daily) == []                    # --client limits the daily set too
    assert cli.daily_run_clients(["emin"], daily) == ["emin"]
    assert cli.daily_run_clients(None, []) == []

    # The default daily time is after EMIN's data is complete (10:00) and before its 12:00 e-mail.
    assert cli.parse_time(cli.DEFAULT_DAILY_TIME) == cli.parse_time("10:30")
    daily_time = cli.parse_time("10:30")
    assert cli.next_daily_run(datetime(2026, 11, 18, 10, 0, tzinfo=zone), daily_time) == datetime(2026, 11, 18, 10, 30, tzinfo=zone)
    assert cli.next_daily_run(datetime(2026, 11, 18, 10, 30, tzinfo=zone), daily_time) == datetime(2026, 11, 19, 10, 30, tzinfo=zone)


def test_the_schedule_runs_weekly_clients_on_their_day_and_emin_every_day_after_ten(monkeypatch):
    """Walk four runs of the loop with a fake clock."""
    zone = ZoneInfo("America/Santiago")
    args = cli.parse_args(["--schedule"])
    assert (args.time, args.daily_time, args.daily_clients) == ("04:00", "10:30", "emin")
    clock = [datetime(2026, 11, 17, 20, 0, tzinfo=zone)]
    calls = []

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    def fake_wait(seconds):
        clock[0] = clock[0] + timedelta(seconds=seconds)
        return len(calls) >= 4  # stop after the fourth run

    monkeypatch.setattr(cli, "datetime", FakeDatetime)
    monkeypatch.setattr(cli._STOP, "wait", fake_wait)
    monkeypatch.setattr(cli.builder, "discover_clients", lambda root=None: ["capstone", "cda", "emin"])
    monkeypatch.setattr(cli, "_run_from_args",
                        lambda a, clients=None: (calls.append((clock[0].strftime("%Y-%m-%d %H:%M"), clients)), 0)[1])
    monkeypatch.setattr(cli.signal, "signal", lambda *a: None)
    cli._STOP.clear()
    try:
        cli.schedule_forever(args)
    finally:
        cli._STOP.clear()
    assert calls == [
        ("2026-11-18 04:00", ["capstone", "cda"]),   # Wednesday, weekly clients only
        ("2026-11-18 10:30", ["emin"]),              # EMIN's own run, after its 10:00 update
        ("2026-11-19 10:30", ["emin"]),
        ("2026-11-20 10:30", ["emin"]),
    ]
