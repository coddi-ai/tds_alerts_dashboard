"""Hot Sheet, Menace Control, Fleet overview and Unit summary read the weekly alert partitions.

They used to load the whole ``consolidated_alerts.csv`` and filter a trailing window. They now
read only the weeks that window touches (plus, where a section lists "every unit that ever had
an alert" or "the newest alert", the light index / the newest week). What they show must not
change, so every test here runs a section twice on the same data: once on the partitioned read
path and once on the *whole normalized history* (what the CSV loader used to hand them), and
compares the output.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

from dashboard.callbacks import hot_sheet_callbacks as hot
from dashboard.callbacks import menace_control_callbacks as menace
from src.data import fleet_status as overview
from src.data import fleet_status as fleet
from dashboard.components import unit_summary_content as usc
from src.data import alert_partitions as store
from src.data import loaders
from tests.alert_partition_support import build_partitions, write_consolidated_csv

CLIENT = "capstone"
EMPTY_CLIENT = "cda"


# ---------------------------------------------------------------------------
# Fixture data: alerts relative to "now" so the sections' own default windows apply
# ---------------------------------------------------------------------------

def _stamp(days_ago: float) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _row(n, unit, days_ago, signal="Engine Oil Pressure", system="motor", component="engine"):
    return {
        "FusionID": f"F-{n:03d}", "TelemetryID": f"T-{n}", "TribologyID": None,
        "Timestamp": _stamp(days_ago) if days_ago is not None else None,
        "UnitId": unit, "Trigger_type": "Telemetria", "Trigger_Var": signal, "Trigger": signal,
        "mensaje_ia": f"Diagnóstico: caso {n}\nCausa probable: desgaste\nAcciones: revisar",
        "sistema": system, "subsistema": "admission", "componente": component, "SourceType": "x",
    }


def _raw_alerts() -> pd.DataFrame:
    """Alerts 0.5 to 400 days old, several units, several weeks, one undated row.

    ``U-OLD`` only has alerts older than every window; ``U-UNDATED`` only has an unparseable
    timestamp. The ages are chosen so that most cut-offs (7, 14, 28, 30, 56, 90 days) fall in the
    *middle* of a week that holds alerts on both sides of them.
    """
    ages = [
        ("U-1", 0.5), ("U-1", 1.2), ("U-2", 2.5), ("U-1", 6.5), ("U-3", 7.5), ("U-2", 9.0),
        ("U-3", 13.5), ("U-1", 14.5), ("U-2", 20.0), ("U-3", 27.5), ("U-1", 28.5), ("U-2", 29.5),
        ("U-3", 30.5), ("U-1", 45.0), ("U-2", 55.5), ("U-3", 56.5), ("U-2", 80.0), ("U-1", 89.5),
        ("U-3", 90.5), ("U-OLD", 150.0), ("U-OLD", 399.0), ("U-UNDATED", None),
    ]
    rows = []
    for n, (unit, days_ago) in enumerate(ages, start=1):
        signal = ("Engine Coolant Temperature", "Transmission Oil Temperature", "Hydraulic Pressure")[n % 3]
        rows.append(_row(n, unit, days_ago, signal=signal, system=("motor", "frenos")[n % 2],
                         component=("engine", "bomba", "radiador")[n % 3]))
    return pd.DataFrame(rows)


@pytest.fixture
def raw():
    return _raw_alerts()


@pytest.fixture
def data_root(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DASHBOARD_FRAME_ENGINE", "pandas")
    write_consolidated_csv(tmp_path, CLIENT, raw)
    build_partitions(tmp_path, CLIENT)
    return tmp_path


@pytest.fixture
def history(raw):
    """The whole history normalized: what the CSV loader handed the sections."""
    return loaders._normalize_alerts_frame(raw.copy())


def _plain(value):
    """A Dash component tree (or anything the sections return) as comparable JSON text."""
    def convert(obj):
        if hasattr(obj, "to_plotly_json"):
            return convert(obj.to_plotly_json())
        if isinstance(obj, dict):
            return {str(k): convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [convert(v) for v in obj]
        if isinstance(obj, pd.DataFrame):
            return json.loads(obj.to_json(orient="split", date_format="iso", default_handler=str))
        return obj
    return json.dumps(convert(value), sort_keys=True, default=str)


def _csv_is_unreadable(root, monkeypatch):
    """Delete the CSV and make any later attempt to open one fail loudly."""
    (root / "alerts" / "golden" / CLIENT / "consolidated_alerts.csv").unlink()
    real_exists = loaders.Path.exists

    def guarded(self, *args, **kwargs):
        assert "consolidated_alerts" not in str(self), "a section looked for the CSV"
        return real_exists(self, *args, **kwargs)

    monkeypatch.setattr(loaders.Path, "exists", guarded)


# ---------------------------------------------------------------------------
# No CSV: every migrated section runs from the partitions alone
# ---------------------------------------------------------------------------

def test_every_section_runs_without_the_csv(data_root, monkeypatch):
    _csv_is_unreadable(data_root, monkeypatch)
    unit = "U-1"

    hot_table = hot.update_hot_sheet_table(CLIENT)
    assert getattr(hot_table, "color", None) != "danger", _plain(hot_table)[:300]
    assert "U-1" in _plain(hot_table) and "U-OLD" in _plain(hot_table)  # units of the whole history

    for days in (30, 90, 365):
        for callback in (menace.update_summary_cards, menace.update_equipment_status_table,
                         menace.update_critical_systems_table):
            result = callback(days, CLIENT)
            assert getattr(result, "color", None) != "danger", (callback.__name__, days, _plain(result)[:300])

    status, value, label, elapsed = fleet._alerts_status_map(CLIENT)
    assert status and value and label != "Sin Datos" and elapsed != "N/A"
    counts = fleet._alerts_window_counts(CLIENT)
    assert set(counts) == {"U-1", "U-2", "U-3", "U-OLD"}

    card = usc._alerts_section(CLIENT, unit, "Normal")
    assert "Graph" in _plain(card)
    assert usc._alerts_data_date(CLIENT) is not None


# ---------------------------------------------------------------------------
# Same output as on the whole history
# ---------------------------------------------------------------------------

def test_hot_sheet_equals_the_whole_history_run(data_root, history, monkeypatch):
    new = _plain(hot.update_hot_sheet_table(CLIENT))
    monkeypatch.setattr(hot, "load_alerts_since", lambda client, since: history)
    monkeypatch.setattr(hot, "load_alert_units", lambda client: None)  # units from the frame, as before
    assert new == _plain(hot.update_hot_sheet_table(CLIENT))
    assert hot.get_hot_sheet_data(history, pd.DataFrame())["Estado_Telemetria"].nunique() > 1  # not trivially equal


@pytest.mark.parametrize("days", [3, 30, 60, 90, 180, 365])
def test_menace_control_equals_the_whole_history_run(data_root, history, monkeypatch, days):
    callbacks = (menace.update_summary_cards, menace.update_equipment_status_table,
                 menace.update_critical_systems_table)
    new = [_plain(callback(days, CLIENT)) for callback in callbacks]
    monkeypatch.setattr(menace, "_load_window_alerts", lambda client, d: history)
    assert new == [_plain(callback(days, CLIENT)) for callback in callbacks]


def test_fleet_overview_alert_maps_equal_the_whole_history_run(data_root, history):
    status, value, label, elapsed = fleet._alerts_status_map(CLIENT)
    scores = overview.calculate_alert_criticality_score(history, 30)
    assert status == dict(zip(scores["equipo"], scores["status"]))
    assert value == dict(zip(scores["equipo"], scores["criticality_score"]))
    expected_label, expected_elapsed = fleet._freshness_from_naive_timestamp(history["Timestamp"].max(), "alerts")
    assert (label, elapsed) == (expected_label, expected_elapsed)

    counts = fleet._alerts_window_counts(CLIENT)
    expected = overview.count_alerts_by_window(history)
    assert counts == expected
    assert list(counts) == list(expected)  # same order too
    assert counts["U-OLD"] == (0, 0, 0)  # known from the history, nothing in any window
    assert "U-UNDATED" not in counts  # no dated alert: the old count never saw it


def test_unit_summary_alerts_equal_the_whole_history_run(data_root, history, monkeypatch):
    units = ("U-1", "U-2", "U-3", "U-OLD", "U-UNDATED", "NOT-A-UNIT")
    new = {unit: _plain(usc._alerts_section(CLIENT, unit, "Normal")) for unit in units}
    date = usc._alerts_data_date(CLIENT)
    assert date == pd.Timestamp(history["Timestamp"].max())

    monkeypatch.setattr(usc, "load_alerts_since", lambda client, since: history)
    assert new == {unit: _plain(usc._alerts_section(CLIENT, unit, "Normal")) for unit in units}


def test_unit_summary_with_a_stale_feed_keeps_its_fallback_window(tmp_path, monkeypatch):
    """A feed more than STALE_DATA_FALLBACK_WEEKS old anchors the window on its newest alert."""
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    old = pd.DataFrame([_row(1, "U-1", 400), _row(2, "U-1", 410), _row(3, "U-2", 500), _row(4, "U-1", 480)])
    write_consolidated_csv(tmp_path, CLIENT, old)
    build_partitions(tmp_path, CLIENT)
    history = loaders._normalize_alerts_frame(old.copy())

    new = _plain(usc._alerts_section(CLIENT, "U-1", "Normal"))
    assert "Graph" in new and "fa-flask" in new  # the fallback banner is shown
    monkeypatch.setattr(usc, "load_alerts_since", lambda client, since: history)
    assert new == _plain(usc._alerts_section(CLIENT, "U-1", "Normal"))


# ---------------------------------------------------------------------------
# Windows that start mid-week, and only the weeks they need
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("days", [7, 14, 28, 30, 56, 90])
def test_a_window_starting_mid_week_returns_exactly_the_alerts_inside_it(data_root, history, days):
    cutoff = datetime.now() - timedelta(days=days)
    loaded = loaders.load_alerts_since(CLIENT, cutoff)
    # The loader returns whole weeks: a superset of the window, never missing one of its alerts ...
    assert set(history.loc[history["Timestamp"] >= cutoff, "FusionID"]) <= set(loaded["FusionID"])
    # ... and the section's exact filter then trims it to the window, row for row.
    inside = loaded[loaded["Timestamp"] >= cutoff]
    expected = history[history["Timestamp"] >= cutoff]
    assert inside["FusionID"].tolist() == expected["FusionID"].tolist()
    assert len(inside) > 0


def test_a_window_reads_only_the_weeks_it_touches(data_root, monkeypatch):
    requested = []
    real = store.read_scope
    monkeypatch.setattr(store, "read_scope", lambda directory, weeks, columns=None: (requested.append(list(weeks)),
                                                                                    real(directory, weeks, columns))[1])
    cutoff = datetime.now() - timedelta(days=14)
    loaders.load_alerts_since(CLIENT, cutoff)
    weeks = requested[-1]
    every_week = store.list_weeks(data_root / "alerts" / "golden" / CLIENT)
    assert 0 < len(weeks) <= 3 and len(weeks) < len(every_week)
    assert weeks[0] == store.week_of(pd.Timestamp(cutoff)) and "undated" not in weeks

    requested.clear()
    assert loaders.latest_alert_timestamp(CLIENT) is not None
    assert requested == [[max(w for w in every_week if w != "undated")]]  # the newest week, one file


# ---------------------------------------------------------------------------
# Nothing there: no errors
# ---------------------------------------------------------------------------

def test_a_client_without_partitions_is_empty_everywhere(data_root):
    assert loaders.load_alerts_since(EMPTY_CLIENT, datetime.now()).empty
    assert loaders.latest_alert_timestamp(EMPTY_CLIENT) is None
    assert loaders.load_alert_units(EMPTY_CLIENT) == []

    assert getattr(hot.update_hot_sheet_table(EMPTY_CLIENT), "color", None) != "danger"
    for callback in (menace.update_summary_cards, menace.update_equipment_status_table,
                     menace.update_critical_systems_table):
        result = callback(90, EMPTY_CLIENT)
        assert result.color == "warning"  # "no alert data available"
    assert fleet._alerts_status_map(EMPTY_CLIENT) == ({}, {}, "Sin Datos", "N/A")
    assert fleet._alerts_window_counts(EMPTY_CLIENT) == {}
    assert usc._alerts_data_date(EMPTY_CLIENT) is None
    card = usc._alerts_section(EMPTY_CLIENT, "U-1", "Sin Datos")
    assert "Graph" not in _plain(card)


def test_a_window_after_the_last_alert_is_empty_but_not_an_error(data_root):
    """Weeks with no data are empty; "nothing in the window" is not "no alert data"."""
    future = datetime.now() + timedelta(days=60)
    window = loaders.load_alerts_since(CLIENT, future)
    assert window.empty and "Timestamp" in window.columns and "UnitId" in window.columns
    assert loaders.client_has_alert_partitions(CLIENT)


def test_menace_distinguishes_an_empty_window_from_no_data(data_root, monkeypatch):
    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=1000)

    monkeypatch.setattr(menace, "datetime", Later)
    for callback in (menace.update_equipment_status_table, menace.update_critical_systems_table):
        result = callback(30, CLIENT)
        assert result.color == "info"  # "no alerts in the last 30 days", not "no data"
    cards = menace.update_summary_cards(30, CLIENT)
    assert "0" in _plain(cards) and getattr(cards, "color", None) != "warning"


def test_a_unit_that_never_had_an_alert_is_handled(data_root):
    assert "NOT-A-UNIT" not in fleet._alerts_window_counts(CLIENT)
    assert "Graph" not in _plain(usc._alerts_section(CLIENT, "NOT-A-UNIT", "Normal"))
    table = _plain(hot.update_hot_sheet_table(CLIENT))
    assert "NOT-A-UNIT" not in table


def test_undated_only_history_has_a_nat_feed_date(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    write_consolidated_csv(tmp_path, CLIENT, pd.DataFrame([_row(1, "U-1", None)]))
    build_partitions(tmp_path, CLIENT)
    assert pd.isna(loaders.latest_alert_timestamp(CLIENT))
    assert usc._alerts_data_date(CLIENT) is None
    assert fleet._alerts_window_counts(CLIENT) == {}
    assert fleet._alerts_status_map(CLIENT)[2:] == ("Sin Datos", "N/A")


# ---------------------------------------------------------------------------
# The alert-summary e-mail, the data-source chips and Campbell AI: same partitions, no CSV
# ---------------------------------------------------------------------------

def test_email_builds_from_the_partitions_without_the_csv(data_root, history, monkeypatch):
    from datetime import date

    from src.mailing import alert_summary
    from src.mailing.report import ReportRequest

    today = date.today()
    # A weekly-shaped request whose bounds fall mid-week, over data that has alerts on both sides.
    request = ReportRequest(CLIENT, "weekly", today - timedelta(days=40), today - timedelta(days=13), today)
    monkeypatch.setattr(loaders, "load_alerts_for_scope", lambda client, **kwargs: history)  # whole history
    expected = alert_summary.build_alert_summary(request)
    monkeypatch.undo()

    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(data_root))
    _csv_is_unreadable(data_root, monkeypatch)
    content = alert_summary.build_alert_summary(request)
    assert content.html == expected.html and content.meta == expected.meta
    assert content.meta["total_alerts"] > 0


def test_email_reads_only_the_weeks_of_its_period(data_root, monkeypatch):
    from datetime import date

    from src.mailing import alert_summary

    requested = []
    real = store.read_scope
    monkeypatch.setattr(store, "read_scope", lambda directory, weeks, columns=None: (requested.append(list(weeks)),
                                                                                    real(directory, weeks, columns))[1])
    today = date.today()
    alert_summary.load_period_records(CLIENT, today - timedelta(days=16), today - timedelta(days=10))
    every_week = store.list_weeks(data_root / "alerts" / "golden" / CLIENT)
    assert 1 <= len(requested[-1]) <= 2 and len(requested[-1]) < len(every_week)


def test_email_for_a_period_without_partitions_is_the_empty_email(data_root):
    from datetime import date

    from src.mailing import alert_summary
    from src.mailing.report import ReportRequest

    request = ReportRequest(CLIENT, "weekly", date(2019, 1, 7), date(2019, 1, 13), date(2019, 1, 16))
    assert "Sin alertas registradas en el período." in alert_summary.build_alert_summary(request).html
    assert alert_summary.load_period_records(EMPTY_CLIENT, date(2026, 1, 1), date(2026, 1, 7)) == []


def test_data_source_chip_and_probe_are_dated_by_the_newest_partition(data_root, history, monkeypatch):
    from config.service_data_sources import SOURCE_DATE_FIELDS
    from src.data.catalog import _build_client_availability_uncached
    from src.data.source_freshness import latest_data_date

    _csv_is_unreadable(data_root, monkeypatch)
    probe = _build_client_availability_uncached(CLIENT, data_root)["alerts_consolidated"]
    newest = store.newest_partition(data_root / "alerts" / "golden" / CLIENT)
    assert probe.status == "available" and probe.path == str(newest) and newest.name == "file.parquet"

    latest_utc = pd.Timestamp(history["Timestamp"].max())
    chile_day = latest_utc.tz_localize("UTC").tz_convert("America/Santiago").date()
    assert latest_data_date(probe.path, SOURCE_DATE_FIELDS["alerts_consolidated"], today=date_far_ahead()) == chile_day

    missing = _build_client_availability_uncached(EMPTY_CLIENT, data_root)["alerts_consolidated"]
    assert missing.status == "missing" and missing.path is None


def date_far_ahead():
    from datetime import date

    return date.today() + timedelta(days=5)


def test_campbell_ai_reads_the_alert_partitions_and_gets_the_csv_frame(data_root, raw, monkeypatch):
    from src.campbell_ai.data import DashboardDataRepository

    csv_copy = data_root / "reference.csv"
    (data_root / "alerts" / "golden" / CLIENT / "consolidated_alerts.csv").replace(csv_copy)
    reference = pd.read_csv(csv_copy, low_memory=False)

    repository = DashboardDataRepository(data_root)
    frame = repository.load("alerts", CLIENT)
    pd.testing.assert_frame_equal(frame, reference)  # same values, dtypes and row order as read_csv
    assert repository.read_columns(repository.dataset_path("alerts", CLIENT)) == list(reference.columns)
    probe = repository._probe_frame(repository.dataset_path("alerts", CLIENT), count_rows=True)
    assert probe["rows"] == len(reference) and probe["columns"] == list(reference.columns)
    assert json.loads(repository.query_alerts(CLIENT, limit=5))["total"] > 0


def test_campbell_ai_alert_frame_follows_a_rewritten_partition(data_root, raw):
    """The cache key is the newest mtime among the partitions: a rewritten week is seen."""
    import os
    import time

    from src.campbell_ai.data import DashboardDataRepository

    repository = DashboardDataRepository(data_root)
    first = repository.load("alerts", CLIENT)
    directory = data_root / "alerts" / "golden" / CLIENT
    week_file = store.newest_partition(directory)
    table = store.pq.read_table(week_file)
    metadata = table.schema.metadata
    units = table["UnitId"].to_pylist()
    units[0] = "U-CHANGED"
    position = table.schema.get_field_index("UnitId")
    table = table.set_column(position, "UnitId", store.pa.array(units)).replace_schema_metadata(metadata)
    store.pq.write_table(table, week_file)
    future = time.time() + 10
    os.utime(week_file, (future, future))  # the index is untouched: only the partition moved
    assert "U-CHANGED" in set(repository.load("alerts", CLIENT)["UnitId"])
    assert "U-CHANGED" not in set(first["UnitId"])
