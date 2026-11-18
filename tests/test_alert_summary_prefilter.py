"""The alert summary prepares only the alerts that can fall in its period (and gets the same result).

`prepare_alert_rows` is slow per row; the email used to prepare the client's whole history to keep one
week. `alert_summary.slice_to_period` cuts the raw frame first. These tests prove the cut never changes the
result and that it really reduces the work.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from src.mailing import alert_summary, config

START = datetime(2026, 1, 1, 0, 0)  # UTC-naive, like the loader's output


def make_frame(stamps, unit_cycle=("CA-1", "CA-2", "CA-3")):
    frame = pd.DataFrame({
        "UnitId": [unit_cycle[i % len(unit_cycle)] for i in range(len(stamps))],
        "sistema": ["motor" if i % 2 else "frenos" for i in range(len(stamps))],
        "Timestamp": pd.to_datetime(list(stamps)),
    })
    frame["has_telemetry"] = True
    frame["has_tribology"] = False
    frame["Trigger_type"] = ["Mixto" if i % 7 == 0 else "Telemetria" for i in range(len(stamps))]
    frame["Trigger_Var"] = "imp_lb_psi"
    frame["componente"] = "engine"
    frame["subsistema"] = "admission"
    frame["FusionID"] = [f"F-{i}" for i in range(len(frame))]
    frame["mensaje_ia"] = "Diagnóstico: Presión anómala en admisión."
    frame["mensaje_ia_eng"] = "Diagnosis: Abnormal intake pressure."
    return frame


@pytest.fixture
def history(monkeypatch):
    """Alerts every 5 hours for ~10 months, so every day boundary (and both Chile DST changes) is crossed."""
    stamps = [START + timedelta(hours=5 * i) for i in range(1500)]
    frame = make_frame(stamps)
    from src.data import loaders

    monkeypatch.setattr(loaders, "load_alerts_data", lambda client: frame)
    return frame


def unsliced(monkeypatch):
    """The previous behaviour: prepare everything, then filter."""
    monkeypatch.setattr(alert_summary, "slice_to_period", lambda alerts, start, end: alerts)


PERIODS = [
    (date(2026, 3, 9), date(2026, 3, 15)),    # an ordinary week
    (date(2026, 3, 10), date(2026, 3, 10)),   # one day
    (date(2026, 4, 4), date(2026, 4, 6)),     # Chile's end of daylight saving (night of Apr 4-5)
    (date(2026, 9, 5), date(2026, 9, 7)),     # Chile's start of daylight saving (night of Sep 5-6)
    (date(2026, 5, 1), date(2026, 5, 31)),    # a month
    (date(2026, 1, 1), date(2026, 3, 1)),     # touching the start of the data
    (date(2026, 9, 1), date(2026, 12, 31)),   # touching the end of the data
    (date(2025, 1, 1), date(2027, 1, 1)),     # all of it
    (date(2024, 1, 1), date(2024, 1, 7)),     # before any data
]


@pytest.mark.parametrize("start,end", PERIODS)
def test_the_sliced_result_is_identical_to_preparing_everything(history, monkeypatch, start, end):
    sliced = alert_summary.load_period_records("capstone", start, end)
    unsliced(monkeypatch)
    reference = alert_summary.load_period_records("capstone", start, end)
    assert sliced == reference


@pytest.mark.parametrize("start,end", PERIODS)
def test_the_slice_never_drops_an_alert_the_exact_filter_keeps(history, start, end):
    """The safety property: the slice is a superset of what the exact Chile-day filter keeps."""
    from dashboard.components.alerts_report import filter_prepared_rows, prepare_alert_rows

    kept = filter_prepared_rows(prepare_alert_rows(history), start_date=start, end_date=end)
    sliced = alert_summary.slice_to_period(history, start, end)
    assert set(kept["FusionID"]) <= set(sliced["FusionID"])


def test_only_the_alerts_near_the_period_are_prepared(history, monkeypatch):
    import dashboard.components.alerts_report as report_module

    seen = []
    real = report_module.prepare_alert_rows
    monkeypatch.setattr(report_module, "prepare_alert_rows", lambda frame: seen.append(len(frame)) or real(frame))
    records = alert_summary.load_period_records("capstone", date(2026, 3, 9), date(2026, 3, 15))
    assert records and seen == [seen[0]] and seen[0] < 0.1 * len(history)  # a week of ~10 months of alerts
    assert seen[0] >= len(records)


def test_a_period_with_no_alerts_prepares_nothing(history, monkeypatch):
    import dashboard.components.alerts_report as report_module

    calls = []
    monkeypatch.setattr(report_module, "prepare_alert_rows", lambda frame: calls.append(1) or frame)
    assert alert_summary.load_period_records("capstone", date(2024, 1, 1), date(2024, 1, 7)) == []
    assert calls == []


def test_the_boundary_days_in_chile_time_are_kept_exactly(monkeypatch):
    """Period 14-15 July in Chile (winter, UTC-4); the stamps are UTC-naive."""
    frame = make_frame([
        datetime(2026, 7, 16, 2, 0),    # 22:00 on the 15th in Chile -> inside
        datetime(2026, 7, 15, 23, 0),   # 19:00 on the 15th in Chile -> inside
        datetime(2026, 7, 16, 4, 30),   # 00:30 on the 16th in Chile -> outside
        datetime(2026, 7, 14, 4, 30),   # 00:30 on the 14th in Chile -> inside
        datetime(2026, 7, 14, 3, 59),   # 23:59 on the 13th in Chile -> outside
    ])
    from src.data import loaders

    monkeypatch.setattr(loaders, "load_alerts_data", lambda client: frame)
    records = alert_summary.load_period_records("capstone", date(2026, 7, 14), date(2026, 7, 15))
    assert sorted(r.when.strftime("%d %H:%M") for r in records) == ["14 00:30", "15 19:00", "15 22:00"]


def test_timestamps_with_an_offset_are_normalised_before_slicing(monkeypatch):
    """Capstone's raw ISO strings may carry `-04:00`; the slice uses the same normaliser as the page."""
    frame = make_frame(["2026-07-15T12:00:00-04:00", "2026-07-01T12:00:00-04:00", "2026-07-15T23:30:00-04:00"])
    frame["Timestamp"] = pd.Series(["2026-07-15T12:00:00-04:00", "2026-07-01T12:00:00-04:00", "2026-07-15T23:30:00-04:00"])
    from src.data import loaders

    monkeypatch.setattr(loaders, "load_alerts_data", lambda client: frame)
    sliced = alert_summary.load_period_records("capstone", date(2026, 7, 15), date(2026, 7, 15))
    unsliced(monkeypatch)
    assert sliced == alert_summary.load_period_records("capstone", date(2026, 7, 15), date(2026, 7, 15))
    assert len(sliced) == 2


def test_missing_or_unreadable_timestamps_do_not_break_the_slice(monkeypatch):
    frame = make_frame(["2026-07-15 16:00", "2026-07-15 17:00"])
    frame.loc[1, "Timestamp"] = pd.NaT
    assert len(alert_summary.slice_to_period(frame, date(2026, 7, 15), date(2026, 7, 15))) == 1  # the NaT row is dropped
    no_column = frame.drop(columns=["Timestamp"])
    assert alert_summary.slice_to_period(no_column, date(2026, 7, 15), date(2026, 7, 15)) is no_column  # nothing to slice by


def test_the_margin_is_two_days_and_symmetric():
    assert alert_summary.PREFILTER_MARGIN_DAYS == 2
    frame = make_frame([datetime(2026, 7, 10, 12, 0) + timedelta(days=d) for d in range(-5, 6)])
    sliced = alert_summary.slice_to_period(frame, date(2026, 7, 10), date(2026, 7, 10))
    days = sorted(ts.day for ts in sliced["Timestamp"])
    assert days == [8, 9, 10, 11, 12]


def test_the_slice_does_not_change_the_clients_data(history):
    before = history.copy(deep=True)
    alert_summary.load_period_records("capstone", date(2026, 3, 9), date(2026, 3, 15))
    pd.testing.assert_frame_equal(history, before)
