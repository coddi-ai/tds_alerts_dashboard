"""Oil report PDF export and the time-series section's range (Monitoreo > Aceite > Detalle de reporte).

Covers: the 3-calendar-month default window and its cap at the examined sample (requirements 10 and
11), the model the PDF is built from (same data/limits/statuses/AI text as the tab, requirements 3-8),
the rendered pages (content, compact header, footer "Página X de Y", nothing clipped, no mockup
leftovers) and the download callback (loading/error/enable rules).
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from dashboard.callbacks import oil_report_pdf_callbacks as pdfcb
from dashboard.callbacks import reports_callbacks as rc
from dashboard.components import oil_report_pdf as pdf
from dashboard.components.oil_charts import (
    TIME_SERIES_CHARTS,
    clip_history_to_window,
    collect_chart_series,
    default_time_series_window,
    resolve_time_series_window,
    unit_history,
)
from src.i18n import forced_language, load_catalog, t

ts = pd.Timestamp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LIMITS_BAND = {"LIC": None, "LIM": None, "LSM": 15.0, "LSC": 20.0}
LIMITS_TWO_SIDED = {"LIC": 9.0, "LIM": 10.0, "LSM": 16.0, "LSC": 18.0}


def _limits(client="EMIN", familia="camion", component="motor"):
    """Four-limit structure as load_stewart_limits_four returns it: client > machine > component >
    essay > oil-hour range."""
    comp = {name: {"ALL": dict(LIMITS_BAND)} for name in
            ("Hierro", "Cobre", "Estaño", "Cromo", "Plomo", "Aluminio", "Silicio", "Sodio", "Potasio", "Agua")}
    comp["Viscocidad"] = {"ALL": dict(LIMITS_TWO_SIDED)}
    return {client: {familia: {component: comp}}}


def _frame(n=10, *, last_status="Anormal", with_viscosity=True, long_comment=None):
    """Weekly samples of one unit/component, newest last. Hierro rises so that the last one is
    above its critical limit (20)."""
    dates = pd.date_range("2026-03-01", periods=n, freq="14D")
    rows = []
    for i, day in enumerate(dates):
        newest = i == n - 1
        rows.append({
            "client": "EMIN", "sampleNumber": f"R{i:03d}", "sampleDate": day,
            "unitId": "csl006", "machineName": "camion", "componentName": "mando final derecho",
            "componentNameNormalized": "motor", "componentHours": 12345.0 if newest else None,
            "oilMeter": 87.5 if newest else float("nan"), "oilHourRange": "ALL",
            "report_status": last_status if newest else "Normal",
            "essays_broken": 1 if newest else 0,
            "breached_essays": '[{"essay": "Hierro", "value": 25.0, "threshold": "Condenatorio", "limit": 20.0}]' if newest else "[]",
            "anomalyType": "Desgaste de Componentes" if newest else "Normal",
            "ai_recommendation": (long_comment or "Diagnóstico: Desgaste elevado.\nAcción: Revisar filtros. Cambiar aceite.") if newest
                                 else f"Diagnóstico: Normal {i}. " + "Texto largo de la recomendación. " * 12,
            "daysSincePrevious": 14 if i else float("nan"),
            "Hierro": 25.0 if newest else 5.0 + i, "Índice PQ": 3.0, "Cobre": 1.0 + i / 10, "Estaño": 0.5,
            "Cromo": 0.3, "Plomo": 0.2, "Níquel": 0.1, "Aluminio": 2.0,
            "Silicio": 6.0, "Sodio": 3.0, "Potasio": 1.0, "Agua": float("nan"), "Combustible": float("nan"),
            "Boro": 70.0, "Magnesio": 600.0,
            "Viscocidad": 12.5 if with_viscosity else float("nan"),
            "Hollín": float("nan"), "Oxidación": float("nan"),
            "Zinc": 900.0,                                   # not in the report's mapping: out of scope
        })
    return pd.DataFrame(rows)


def _build(df=None, sample_date=None, limits="default", **kwargs):
    df = _frame() if df is None else df
    sample_date = sample_date or str(df["sampleDate"].max())
    limits = _limits() if limits == "default" else limits
    return pdfcb.build_oil_report(df, limits, "EMIN", "camion", "csl006", "mando final derecho", sample_date,
                                  today="2026-11-26", **kwargs)


def _render(report, **kwargs):
    return pdf.render_oil_report_pdf(report, compress=False, **kwargs)


def _pages(data: bytes):
    fitz = pytest.importorskip("pymupdf")
    document = fitz.open(stream=data, filetype="pdf")
    return [page.get_text() for page in document]


# ---------------------------------------------------------------------------
# B. Time-series range: 3 calendar months before the examined sample, never past it
# ---------------------------------------------------------------------------

def _days(*days):
    return [ts(day) for day in days]


def test_default_window_starts_at_the_earlier_of_six_months_and_the_third_most_recent_sample():
    # spec example 1: 6 months back from 2026-11-14 is 2026-05-14 and that window holds 5 samples
    # (06-07, 06-21, 09-10, 10-21, 11-14) against 3 for the last-3 rule -> it starts 6 months back
    samples = _days("2026-01-22", "2026-06-07", "2026-06-21", "2026-09-10", "2026-10-21", "2026-11-14")
    assert default_time_series_window("2026-11-14", samples) == (ts("2026-05-14"), ts("2026-11-14"))
    # spec example 2: the 6-month window (from 2026-03-10) holds 2 samples, the last-3 rule 3
    # -> it starts at the 3rd most recent sample
    samples = _days("2026-01-10", "2026-05-10", "2026-09-10")
    assert default_time_series_window("2026-09-10", samples) == (ts("2026-01-10"), ts("2026-09-10"))
    # a sample taken during the day still ends the window on its own date
    assert default_time_series_window("2026-09-10T13:22:00.000000000", [ts("2026-01-10 08:00"), ts("2026-05-10"),
                                                                         ts("2026-09-10 13:22")])[0] == ts("2026-01-10")


def test_default_window_counts_only_samples_up_to_the_examined_one():
    samples = _days("2026-01-10", "2026-05-10", "2026-09-10", "2026-11-14", "2026-12-01")
    # examining 2026-09-10: the later samples are ignored, so the 3rd most recent is 2026-01-10
    assert default_time_series_window("2026-09-10", samples) == (ts("2026-01-10"), ts("2026-09-10"))
    # examining 2026-05-10: only 2 samples up to it -> the oldest one
    assert default_time_series_window("2026-05-10", samples) == (ts("2026-01-10"), ts("2026-05-10"))
    # 2026-12-01: 6 months back (2026-06-01) is earlier than the 3rd most recent (2026-09-10)
    assert default_time_series_window("2026-12-01", samples) == (ts("2026-06-01"), ts("2026-12-01"))


def test_default_window_with_fewer_than_three_samples_starts_at_the_oldest():
    assert default_time_series_window("2026-11-14", _days("2025-01-01", "2026-11-14")) == (ts("2025-01-01"), ts("2026-11-14"))
    # also when both are within 6 months
    assert default_time_series_window("2026-11-14", _days("2026-10-01", "2026-11-14")) == (ts("2026-10-01"), ts("2026-11-14"))
    # a unit's very first report
    assert default_time_series_window("2026-11-14", _days("2026-11-14")) == (ts("2026-11-14"), ts("2026-11-14"))
    # the examined sample is the first one counted even when the history does not list it
    assert default_time_series_window("2026-11-14", []) == (ts("2026-11-14"), ts("2026-11-14"))
    assert default_time_series_window(None, _days("2026-01-01")) == (None, None)


def test_default_window_month_arithmetic_is_calendar_months():
    dense = [ts("2026-02-01") + pd.Timedelta(days=7 * i) for i in range(40)]
    # 6 months before 2026-08-30 is 2026-02-28 (February has no 30th: the shorter month clamps), not 182 days
    sample = max(day for day in dense if day <= ts("2026-08-31"))
    start, end = default_time_series_window(sample, dense)
    assert end == sample == ts("2026-08-30") and start == ts("2026-02-28")


def test_both_boundaries_of_the_default_window_are_inclusive():
    samples = _days("2026-01-10", "2026-05-10", "2026-09-10")
    start, end = default_time_series_window("2026-09-10", samples)
    frame = pd.DataFrame({"sampleDate": pd.to_datetime(samples)})
    assert list(clip_history_to_window(frame, start, end)["sampleDate"]) == samples       # the 3rd sample and the examined one
    # six months back landing exactly on a sample keeps that sample
    samples = _days("2026-05-14", "2026-08-01", "2026-09-10", "2026-11-14")
    start, end = default_time_series_window("2026-11-14", samples)
    assert start == ts("2026-05-14")
    assert list(clip_history_to_window(pd.DataFrame({"sampleDate": pd.to_datetime(samples)}), start, end)["sampleDate"]) == samples


def test_window_never_reaches_past_the_examined_sample():
    samples = _days("2026-01-10", "2026-05-10", "2026-09-10", "2026-11-14")
    # the picker holds the range of a newer sample: the older sample caps it
    start, end = resolve_time_series_window("2026-06-10", "2026-03-10", "2026-11-14", samples)
    assert (start, end) == (ts("2026-03-10"), ts("2026-06-10"))
    # nothing typed in yet: the default window of THAT sample (2 samples up to 2026-05-10 -> the oldest)
    assert resolve_time_series_window("2026-05-10", None, None, samples) == (ts("2026-01-10"), ts("2026-05-10"))
    # an end the user picked earlier than the sample is respected
    assert resolve_time_series_window("2026-06-10", None, "2026-05-01", samples)[1] == ts("2026-05-01")
    # no sample selected: nothing to cap against
    assert resolve_time_series_window(None, "2026-01-01", "2026-02-01", samples) == (ts("2026-01-01"), ts("2026-02-01"))


def test_clipping_counts_the_whole_end_day():
    frame = pd.DataFrame({"sampleDate": pd.to_datetime(
        ["2026-08-13 23:59", "2026-08-14 00:00", "2026-11-14 14:30", "2026-11-15 00:01"])})
    kept = clip_history_to_window(frame, ts("2026-08-14"), ts("2026-11-14"))
    assert list(kept["sampleDate"]) == [ts("2026-08-14 00:00"), ts("2026-11-14 14:30")]


class _Capture:
    """A stand-in for the Dash app that keeps the registered callbacks by function name."""

    def __init__(self):
        self.callbacks = {}

    def callback(self, *args, **kwargs):
        def register(function):
            self.callbacks[function.__name__] = function
            return function
        return register


def _stub_reports(monkeypatch, tmp_path, df):
    """reports_callbacks registered against a stub app, reading `df` as the client's reports."""
    reports_file = tmp_path / "classified.parquet"
    reports_file.write_text("x")

    class Settings:
        def get_classified_reports_path(self, client):
            return reports_file

        def get_stewart_limits_four_path(self, client):
            return tmp_path / "missing.parquet"

    monkeypatch.setattr(rc, "get_settings", lambda: Settings())
    monkeypatch.setattr(rc, "load_oil_classified", lambda client: df.copy())
    app = _Capture()
    rc.register_reports_callbacks(app)
    return app.callbacks, df


@pytest.fixture
def reports_app(monkeypatch, tmp_path):
    """A unit sampled every 14 days (14 samples, 2026-03-01 .. 2026-08-30)."""
    return _stub_reports(monkeypatch, tmp_path, _frame(n=14))


SPARSE_DATES = ["2026-01-10", "2026-05-10", "2026-09-10", "2026-11-14"]


@pytest.fixture
def sparse_app(monkeypatch, tmp_path):
    """A rarely sampled unit: where the last-3-samples rule, not the 6 months, sets the range."""
    df = _frame(n=len(SPARSE_DATES))
    df["sampleDate"] = pd.to_datetime(SPARSE_DATES)
    return _stub_reports(monkeypatch, tmp_path, df)


UNIT = ("mando final derecho", "csl006", "EMIN")             # component, equipo, client


def _figure_dates(layout):
    """Every x value drawn by every chart of the grid, and the y of its limit lines."""
    dates, limit_ys = [], []
    stack = [layout]
    while stack:
        node = stack.pop()
        figure = getattr(node, "figure", None)
        if figure is not None:
            for trace in figure.data:
                dates.extend(pd.to_datetime(list(trace.x)))
            limit_ys.extend(shape.y0 for shape in (figure.layout.shapes or ()))
        children = getattr(node, "children", None)
        if isinstance(children, (list, tuple)):
            stack.extend(children)
        elif children is not None:
            stack.append(children)
    return dates, limit_ys


def test_picker_is_reset_to_the_default_range_of_the_selected_sample(reports_app):
    callbacks, df = reports_app
    reset = callbacks["reset_time_series_range"]
    latest = str(df["sampleDate"].max())
    older = str(df["sampleDate"].iloc[5])

    # a unit sampled every 14 days: 6 months hold the most samples. 2026-08-30 -> 2026-02-28
    start, end, maximum, visible = reset(latest, *UNIT)
    assert (start, end, maximum, visible) == ("2026-02-28", "2026-08-30", "2026-08-30", "2026-08-30")

    # an older sample: its own range, and the picker cannot go past its date
    assert reset(older, *UNIT) == ("2025-11-10", "2026-05-10", "2026-05-10", "2026-05-10")

    # back to the most recent: its range again
    assert reset(latest, *UNIT)[:2] == ("2026-02-28", "2026-08-30")
    assert reset(None, *UNIT) == (None, None, None, None)
    assert reset(latest, None, "csl006", "EMIN") == (None, None, None, None)


def test_picker_follows_the_last_three_samples_when_they_reach_further_back(sparse_app):
    callbacks, _df = sparse_app
    reset = callbacks["reset_time_series_range"]
    # 2026-11-14: 6 months back (05-14) holds 2 samples, the last 3 reach 2026-05-10
    assert reset("2026-11-14", *UNIT)[:2] == ("2026-05-10", "2026-11-14")
    # 2026-09-10: 6 months back (03-10) holds 2, the last 3 reach 2026-01-10
    assert reset("2026-09-10", *UNIT)[:2] == ("2026-01-10", "2026-09-10")
    # 2026-05-10: only 2 samples up to it (the 2 later ones do not count) -> the oldest, 2026-01-10
    assert reset("2026-05-10", *UNIT)[:3] == ("2026-01-10", "2026-05-10", "2026-05-10")
    # the very first report: just its own day
    assert reset("2026-01-10", *UNIT)[:2] == ("2026-01-10", "2026-01-10")
    # back to the most recent: its range is restored
    assert reset("2026-11-14", *UNIT)[:2] == ("2026-05-10", "2026-11-14")


def test_the_dashboard_default_and_the_pdf_use_the_same_range(sparse_app):
    """The picker's default, the grid drawn from it and the PDF's charts for every sample of a unit."""
    callbacks, df = sparse_app
    reset, grid = callbacks["reset_time_series_range"], callbacks["update_time_series_grid"]
    for sample in df["sampleDate"]:
        start, end, _max, _visible = reset(str(sample), *UNIT)
        report = _build(df, str(sample))
        assert (report.window_start.strftime("%Y-%m-%d"), report.window_end.strftime("%Y-%m-%d")) == (start, end)
        # the PDF's points start exactly where the range does (both bounds inclusive) ...
        pdf_days = [day for chart in report.charts for s in chart.series for day, _v in s.points]
        assert min(pdf_days) >= report.window_start and max(pdf_days) == report.window_end
        # ... and so do the dashboard's, with no range typed in (the grid applies the same rule itself)
        dates, _ = _figure_dates(grid(UNIT[0], UNIT[1], None, None, "EMIN", str(sample)))
        assert min(dates) == min(pdf_days) and max(dates) == max(pdf_days)
        assert all(report.window_start <= day <= report.window_end for day in dates)


def test_pdf_ignores_a_manual_range_set_on_screen(sparse_app):
    """The grid honors a typed range; the PDF has no access to it and always uses the default."""
    callbacks, df = sparse_app
    grid = callbacks["update_time_series_grid"]
    sample = str(df["sampleDate"].iloc[3])                       # 2026-11-14, default range from 2026-05-10
    typed, _ = _figure_dates(grid(UNIT[0], UNIT[1], "2026-01-01", "2026-11-14", "EMIN", sample))
    assert min(typed) == ts("2026-01-10")
    assert _build(df, sample).window_start == ts("2026-05-10")


def test_grid_of_an_older_sample_shows_nothing_dated_after_it(reports_app):
    callbacks, df = reports_app
    grid = callbacks["update_time_series_grid"]
    older = df["sampleDate"].iloc[5]
    # the picker still holds the newest sample's range (the instant before it resets) ...
    stale_end = df["sampleDate"].max().strftime("%Y-%m-%d")
    layout = grid("mando final derecho", "csl006", "2026-03-01", stale_end, "EMIN", str(older))
    dates, _ = _figure_dates(layout)
    assert dates and max(dates) <= older
    # ... and with no range at all (all history before the picker is set)
    dates, _ = _figure_dates(grid("mando final derecho", "csl006", None, None, "EMIN", str(older)))
    assert dates and max(dates) <= older
    # the most recent sample is still fully shown
    dates, _ = _figure_dates(grid("mando final derecho", "csl006", None, None, "EMIN", str(df["sampleDate"].max())))
    assert max(dates) == df["sampleDate"].max()


def test_grid_keeps_the_sample_taken_at_a_time_of_day_on_the_last_day(reports_app, monkeypatch):
    callbacks, df = reports_app
    df = df.copy()
    df["sampleDate"] = df["sampleDate"] + pd.Timedelta(hours=14, minutes=30)
    monkeypatch.setattr(rc, "load_oil_classified", lambda client: df.copy())
    sample = df["sampleDate"].iloc[-1]
    layout = callbacks["update_time_series_grid"](
        "mando final derecho", "csl006", sample.strftime("%Y-%m-%d"), sample.strftime("%Y-%m-%d"), "EMIN", str(sample))
    dates, _ = _figure_dates(layout)
    assert dates == [sample] * len(dates) and dates


def test_the_range_section_describes_the_adaptive_default():
    es = load_catalog("es")["tab_reports.evolucion_de_variables_de_analisis_de"]
    assert "últimos 6 meses o las últimas 3 muestras (lo que incluya más muestras) hasta la muestra seleccionada" in es
    assert "9 meses" not in es and "3 meses previos" not in es
    en = load_catalog("en")["tab_reports.evolucion_de_variables_de_analisis_de"]
    assert "last 6 months or the last 3 samples" in en and "9 months" not in en


def test_the_picker_has_no_default_of_its_own_in_the_layout():
    """Start, end and the latest allowed date come from the sample, so the control starts empty."""
    from dashboard.tabs.tab_reports import create_reports_tab

    picker = _find(create_reports_tab(), "reports-date-range-picker")
    assert getattr(picker, "start_date", None) is None and getattr(picker, "max_date_allowed", None) is None


def _find(node, component_id):
    if getattr(node, "id", None) == component_id:
        return node
    children = getattr(node, "children", None)
    for child in children if isinstance(children, (list, tuple)) else [children]:
        if child is not None and not isinstance(child, str):
            found = _find(child, component_id)
            if found is not None:
                return found
    return None


def test_dashboard_grid_and_pdf_share_one_series_and_limits_source():
    """collect_chart_series is what both the on-screen grid and the PDF read."""
    df = _frame()
    data = collect_chart_series(df, ["Hierro", "Índice PQ"], _limits()["EMIN"]["camion"]["motor"], "ALL")
    assert [s["essay"] for s in data["series"]] == ["Hierro", "Índice PQ"]
    assert [line["value"] for line in data["upper"]] == [20.0]          # Índice PQ has no limit
    assert data["lower"] == []                                           # LIC/LIM null: no lower line
    two_sided = collect_chart_series(df, ["Viscocidad"], _limits()["EMIN"]["camion"]["motor"], "ALL")
    assert [line["value"] for line in two_sided["lower"]] == [9.0]
    assert collect_chart_series(df, ["Hollín", "Oxidación"], {}, "ALL")["series"] == []


# ---------------------------------------------------------------------------
# A. The report model: the tab's data, no calculation of its own
# ---------------------------------------------------------------------------

def test_identity_and_filename():
    report = _build()
    ident = report.identity
    assert (ident.equipo, ident.componente, ident.familia, ident.cliente) == ("CSL006", "Mando Final Derecho", "Camión", "EMIN")
    assert ident.fecha == "2026-07-05" and ident.report_id == "R009"
    assert ident.componente_horas == "12.345 hrs" and ident.aceite_horas == "88 hrs"           # hours: no decimals, "." for thousands
    assert pdfcb.pdf_filename("csl006", "mando final derecho", ts("2026-11-14")) == "CSL006_Mando-Final-Derecho_2026-11-14.pdf"
    assert pdfcb.pdf_filename("a/b", "c:d?", ts("2026-01-02")) == "A-B_C-D_2026-01-02.pdf"


def test_fields_without_value_show_na():
    df = _frame()
    df["componentHours"] = None
    df["oilMeter"] = float("nan")
    ident = _build(df).identity
    assert ident.componente_horas == "N/A" and ident.aceite_horas == "N/A"
    assert pdf.safe_text("N/A") == "N/A"


def test_anormal_report_lists_anomaly_count_and_the_out_of_limit_tests_with_their_state():
    cls = _build().classification
    assert cls.status == "Anormal" and cls.detailed
    assert cls.anomaly == "Desgaste de Componentes"
    assert cls.out_of_limit == 1 and cls.flagged == [("Hierro", "high")]


def test_normal_report_shows_the_status_alone():
    cls = _build(_frame(last_status="Normal")).classification
    assert cls.status == "Normal" and not cls.detailed


def test_alerta_report_also_gets_the_details():
    assert _build(_frame(last_status="Alerta")).classification.detailed


def test_comparison_is_against_the_previous_sample_not_the_latest_two():
    df = _frame()
    older = _build(df, str(df["sampleDate"].iloc[5]))
    comp = older.comparison
    assert comp.previous_date == df["sampleDate"].iloc[4].strftime("%Y-%m-%d")
    assert comp.previous_status == "Normal" and comp.days == 14
    latest = _build(df).comparison
    assert latest.previous_date == df["sampleDate"].iloc[-2].strftime("%Y-%m-%d")
    assert latest.new_critical == ["Hierro"] and latest.resolved_count == 0


def test_no_comparison_without_a_previous_sample():
    df = _frame()
    assert _build(df, str(df["sampleDate"].iloc[0])).comparison is None
    assert _build(df, str(df["sampleDate"].iloc[0])).previous_date is None


def test_ai_message_is_the_dashboards_split():
    ai = _build().ai
    assert ai.available and ai.diagnosis == "Desgaste elevado."
    assert ai.actions == rc._split_actions("Revisar filtros. Cambiar aceite.") == ["Revisar filtros.", "Cambiar aceite."]
    missing = _frame()
    missing["ai_recommendation"] = None
    assert not _build(missing).ai.available


def test_pdf_follows_the_selected_report_not_the_latest():
    df = _frame()
    older = _build(df, str(df["sampleDate"].iloc[4]))
    assert older.identity.report_id == "R004" and older.identity.fecha == df["sampleDate"].iloc[4].strftime("%Y-%m-%d")
    assert older.classification.status == "Normal"
    assert older.window_end == df["sampleDate"].iloc[4].normalize()
    assert [h.report_id for h in older.history][0] == "R004"
    assert all(h.date <= older.identity.fecha for h in older.history)
    for chart in older.charts:                                   # nothing after the examined sample
        assert all(day <= older.window_end for s in chart.series for day, _ in s.points)


def test_pdf_window_is_the_default_one_whatever_is_set_on_screen():
    report = _build()
    # 10 samples every 14 days up to 2026-07-05: six months back (2026-01-05) holds more than the last 3
    assert report.window_start == ts("2026-01-05") and report.window_end == ts("2026-07-05")
    for chart in report.charts:
        for series in chart.series:
            assert all(report.window_start <= day <= report.window_end for day, _ in series.points)


def test_charts_without_data_are_omitted_and_the_rest_keep_dashboard_titles():
    titles = [c.title for c in _build().charts]
    # no Hollín/Oxidación, Combustible-only or Agua data -> Viscosidad is the only optional one
    assert "Viscosidad" in titles and "Hollín & Oxidación" not in titles
    assert titles[:5] == ["Hierro & PQ", "Cobre & Estaño", "Cromo & Plomo", "Silicio & Aluminio", "Sodio & Potasio"]
    assert "Combustible & Agua" not in titles                    # neither essay has data: omitted, no placeholder
    no_visc = [c.title for c in _build(_frame(with_viscosity=False)).charts]
    assert "Viscosidad" not in no_visc
    assert set(no_visc) <= {c["title"] for c in TIME_SERIES_CHARTS}


def _entry(essay, threshold="Critico", direction="upper", limit=5.0, value=9.0):
    """One stored `breached_essays` entry, as the pipeline writes it."""
    return {"essay": essay, "value": value, "threshold": threshold, "limit": limit, "direction": direction, "points": 5}


def _flagged(df, *entries):
    """`df` with the newest report's stored out-of-limit list set to `entries`."""
    df = df.copy()
    last = df.index[-1]
    df.at[last, "breached_essays"] = json.dumps(list(entries))
    df.at[last, "essays_broken"] = len(entries)
    return df


def _rows(report):
    return [row for group in report.groups for row in group.rows]


def _highlighted(report):
    return [row for row in _rows(report) if row.state not in (None, "normal")]


def _group(report, title):
    return {g.title: g for g in report.groups}[title]


def test_chart_limits_are_one_line_per_test_labelled_for_the_margin():
    charts = {c.title: c for c in _build().charts}
    hierro = charts["Hierro & PQ"]
    assert [(l.kind, l.value, l.label) for l in hierro.limits] == [("upper", 20.0, "Fe 20,0")]   # PQ has none (it is not on a chart line)
    visc = charts["Viscosidad"]
    assert {(l.kind, l.value, l.label) for l in visc.limits} == {("upper", 18.0, "máx 18,00"), ("lower", 9.0, "mín 9,00")}
    # two tests with the same limit are two lines, each named: nothing is merged into an invented value
    assert [(l.essay, l.value, l.label) for l in charts["Cromo & Plomo"].limits] == [("Cromo", 20.0, "Cr 20,0"), ("Plomo", 20.0, "Pb 20,0")]


def test_chart_legend_carries_the_current_value_and_the_out_of_limit_state():
    hierro, pq = next(c for c in _build().charts if c.title == "Hierro & PQ").series
    assert (hierro.name, hierro.current, hierro.state) == ("Hierro", 25.0, "high")
    assert (pq.name, pq.current, pq.state) == ("Índice PQ", 3.0, None)


def test_table_groups_members_rows_and_collapsed_lines():
    report = _build()
    assert [g.title for g in report.groups] == ["Metales de desgaste", "Contaminación", "Aditivos", "Condición del lubricante"]
    wear = _group(report, "Metales de desgaste")
    assert [r.test for r in wear.rows] == ["Hierro (Fe)", "Cobre (Cu)", "Estaño (Sn)", "Cromo (Cr)", "Plomo (Pb)", "Aluminio (Al)"]
    # valued tests with no limit at all (and not out of limit) share one line instead of a row each
    assert wear.no_limit == ["Índice PQ 3", "Ni 0,1"] and wear.no_data == []
    contamination = _group(report, "Contaminación")
    assert [r.test for r in contamination.rows] == ["Silicio (Si)", "Sodio (Na)", "Potasio (K)"]
    assert contamination.no_data == ["Agua", "Combustible"]
    additives = _group(report, "Aditivos")
    # B, Mg, Ca, then the other additive elements of the team's mapping; no limits here, so the valued ones collapse
    assert additives.rows == [] and additives.no_limit == ["B 70,0", "Mg 600,0", "Zn 900,0"]
    assert additives.no_data == ["Calcio (Ca)", "Bario (Ba)", "Molibdeno (Mo)", "Fósforo (P)"]
    condition = _group(report, "Condición del lubricante")
    assert [r.test for r in condition.rows] == ["Viscosidad"] and condition.no_data == ["Hollín", "Oxidación"]

    hierro = wear.rows[0]
    assert (hierro.value, hierro.state, hierro.unit) == ("25,0", "high", "ppm")
    # both thresholds: marginal (the file's LSM) and critical (the stored limit the report was classified against)
    assert (hierro.lower_marginal, hierro.lower, hierro.upper_marginal, hierro.upper) == ("—", "—", "15,0", "20,0")
    assert hierro.previous == "13,0"                                    # 5 + 8 (the sample before)
    viscosity = condition.rows[0]
    assert (viscosity.value, viscosity.unit, viscosity.state) == ("12,50", "cSt", "normal")
    assert (viscosity.lower_marginal, viscosity.lower, viscosity.upper_marginal, viscosity.upper) == ("10,00", "9,00", "16,00", "18,00")


def test_a_group_without_any_value_is_one_collapsed_line():
    condition = _group(_build(_frame(with_viscosity=False)), "Condición del lubricante")
    assert condition.rows == [] and condition.no_data == ["Viscosidad", "Hollín", "Oxidación"]


def test_stored_severity_and_direction_give_the_test_state():
    cases = [("Marginal", "upper", "marginal_high"), ("Marginal", "lower", "marginal_low"),
             ("Critico", "upper", "high"), ("Condenatorio", "upper", "high"),
             ("Critico", "lower", "low"), ("Condenatorio", "lower", "low")]
    for threshold, direction, state in cases:
        assert pdfcb._flag_state({"threshold": threshold, "direction": direction}) == state


def test_status_is_the_stored_one_and_header_table_and_comparison_use_one_list():
    """Silicio is Normal on the limits file (6 < 15) but the report stores it as critical: the PDF follows
    the report. Calcio is not in the fixed groups of the spec and Plata is in none: both still appear."""
    df = _frame()
    df["Calcio"] = 3000.0
    df["Plata"] = 0.5
    df = _flagged(df, _entry("Hierro", "Condenatorio", limit=20.0, value=25.0), _entry("Calcio", "Critico", limit=2500.0, value=3000.0),
                  _entry("Plata", "Marginal", limit=0.4, value=0.5), _entry("Silicio", "Critico", limit=5.0, value=6.0))
    report = _build(df)
    cls = report.classification
    # critical (▲) first, then marginal (△), each in the table's order
    assert cls.flagged == [("Hierro", "high"), ("Silicio", "high"), ("Calcio", "high"), ("Plata", "marginal_high")]
    assert cls.out_of_limit == 4
    # ... and they are exactly the highlighted rows of the table
    assert sorted((r.essay, r.state) for r in _highlighted(report)) == sorted(cls.flagged)
    states = {r.essay: r for r in _rows(report)}
    assert (states["Silicio"].state, states["Silicio"].upper) == ("high", "5,0")        # stored, not recomputed
    assert (states["Calcio"].state, states["Calcio"].value, states["Calcio"].upper) == ("high", "3.000,0", "2.500,0")
    assert states["Plata"].state == "marginal_high" and states["Plata"].upper_marginal == "0,4"
    assert [r.test for r in _group(report, "Aditivos").rows] == ["Calcio (Ca)"]
    assert "Plata (Ag)" in [r.test for r in _group(report, "Otros ensayos").rows]
    # the comparison reads the same lists: ▲ are "críticos", △ are "marginales", against a clean previous sample
    assert report.comparison.new_critical == ["Hierro", "Silicio", "Calcio"]
    assert report.comparison.new_marginal == ["Plata"] and report.comparison.resolved_count == 0


def test_table_state_fallback_follows_the_four_limit_classification():
    limits = {"LIC": 9.0, "LIM": 10.0, "LSM": 16.0, "LSC": 18.0}
    cases = {5.0: "low", 9.5: "marginal_low", 12.0: "normal", 17.0: "marginal_high", 19.0: "high"}
    assert {value: pdfcb._table_state(value, limits) for value in cases} == cases
    assert pdfcb._table_state(None, limits) is None and pdfcb._table_state(5.0, None) is None


def test_a_report_that_stores_only_names_gets_the_dashboards_own_classification():
    df = _frame().copy()
    df.at[df.index[-1], "breached_essays"] = json.dumps(["Hierro"])              # legacy format: names only
    assert _group(_build(df), "Metales de desgaste").rows[0].state == "high"
    df.at[df.index[-1], "breached_essays"] = "[]"                               # nothing stored: the dashboard recalculates
    report = _build(df)
    assert report.classification.flagged == [("Hierro", "high")]
    assert _group(report, "Metales de desgaste").rows[0].state == "high"


def test_a_normal_test_has_no_flag_and_one_without_limits_has_no_row_or_verdict():
    wear = _group(_build(), "Metales de desgaste")
    assert [r.state for r in wear.rows] == ["high", "normal", "normal", "normal", "normal", "normal"]
    assert "Índice PQ 3" in wear.no_limit and all("Índice PQ" not in r.test for r in wear.rows)


def test_missing_limits_collapse_everything_but_a_stored_flag_that_keeps_its_status_and_limit():
    report = _build(limits=None)
    wear = _group(report, "Metales de desgaste")
    (hierro,) = wear.rows
    assert (hierro.state, hierro.upper, hierro.lower, hierro.upper_marginal) == ("high", "20,0", "—", "—")
    assert len(wear.no_limit) == 7


def test_an_out_of_limit_test_without_any_limit_keeps_its_own_row():
    df = _flagged(_frame(), _entry("Zinc", "Marginal", limit=None, value=900.0))
    zinc = next(r for r in _group(_build(df), "Aditivos").rows if r.essay == "Zinc")
    assert (zinc.state, zinc.upper, zinc.lower, zinc.upper_marginal) == ("marginal_high", "—", "—", "—")


def test_history_takes_the_shorter_of_the_last_six_samples_and_the_last_six_months():
    ids = lambda report: [h.report_id for h in report.history]
    # dense unit (a sample every 14 days): the last 6 samples are fewer than the 11 of the last 6 months
    df = _frame(n=14)
    report = _build(df, str(df["sampleDate"].iloc[10]))
    assert ids(report) == [f"R{i:03d}" for i in range(10, 4, -1)]
    assert [h.is_current for h in report.history] == [True] + [False] * 5
    # with only 3 samples both candidates are those 3 (a tie)
    assert ids(_build(df, str(df["sampleDate"].iloc[2]))) == ["R002", "R001", "R000"]
    # sparse unit: only 2 samples in the last 6 months (05-14 .. 11-14) against 4 samples
    sparse = _frame(n=4)
    sparse["sampleDate"] = pd.to_datetime(SPARSE_DATES)
    assert ids(_build(sparse, "2026-11-14")) == ["R003", "R002"]
    # the boundary (examined date - 6 months) is inclusive: 2026-05-14 counts
    edge = _frame(n=5)
    edge["sampleDate"] = pd.to_datetime(["2025-01-01", "2025-03-01", "2025-06-01", "2026-05-14", "2026-11-14"])
    assert ids(_build(edge, "2026-11-14")) == ["R004", "R003"]
    assert ids(_build(edge, "2026-05-14")) == ["R003"]        # judged on its own history: 1 sample in its 6 months
    # an older sample is judged on the history it had: nothing dated after it
    assert all(h.date <= "2026-05-14" for h in _build(edge, "2026-05-14").history)


def test_history_comment_of_the_examined_sample_is_split_like_the_dashboards():
    current, *others = _build().history
    assert (current.diagnosis, current.action) == ("Desgaste elevado.", "Revisar filtros. Cambiar aceite.")
    assert current.is_current and not any(h.is_current for h in others)
    assert all(h.comment.startswith("Diagnóstico: Normal") for h in others)


def test_zero_only_groups_collapse_into_a_strip_and_groups_without_data_are_omitted():
    df = _frame()
    df["Combustible"] = 0.0
    df["Agua"] = 0.0
    report = _build(df)
    assert [s.title for s in report.strips] == ["Combustible & Agua"]
    assert report.strips[0].items == [("Combustible", None), ("Agua", "máx 20,00")]         # the limits as chips
    titles = [c.title for c in report.charts]
    assert "Combustible & Agua" not in titles and "Hollín & Oxidación" not in titles
    assert "Hollín & Oxidación" not in [s.title for s in report.strips]                       # no data: omitted, not a strip
    # zeros that are flagged, or below a lower limit, are not "within limits": they stay a chart
    flagged = _build(_flagged(df, _entry("Agua", "Marginal", limit=0.0, value=0.0)))
    assert flagged.strips == [] and "Combustible & Agua" in [c.title for c in flagged.charts]
    limits = _limits()
    limits["EMIN"]["camion"]["motor"]["Agua"] = {"ALL": {"LIC": 1.0, "LIM": 2.0, "LSM": 15.0, "LSC": 20.0}}
    assert _build(df, limits=limits).strips == []


def test_axis_has_three_gridlines_and_covers_the_limits():
    for lo, hi in ((0, 131), (3.2, 7.9), (0, 0), (-5, 40), (0.0, 0.31), (900, 1240)):
        ymin, ymax, step = pdf._axis3(lo, hi)
        assert ymin <= lo and ymax >= hi and abs((ymax - ymin) - 2 * step) < 1e-9


def test_month_ticks_are_month_starts_thinned_to_fit():
    labels = [label for _day, label in pdf.month_ticks(ts("2026-02-03"), ts("2026-08-03"))]
    assert labels == ["mar", "may", "jul"]
    long = [label for _day, label in pdf.month_ticks(ts("2024-01-15"), ts("2026-08-03"))]
    assert len(long) <= 5 and all(label.split(" ")[-1].isdigit() for label in long)            # a range over a year names the year
    assert [label for _d, label in pdf.month_ticks(ts("2026-08-05"), ts("2026-08-20"))] == ["ago"]


def test_unknown_sample_is_reported():
    with pytest.raises(pdfcb.ReportNotFound):
        _build(sample_date="1999-01-01")


def test_limits_are_found_whatever_the_casing_of_the_client():
    df = _frame()
    report = pdfcb.build_oil_report(df, _limits(), "emin", "camion", "csl006", "mando final derecho",
                                    str(df["sampleDate"].max()), today="2026-11-26")
    assert report.groups[0].rows[0].upper == "20,0"


def test_units_agree_with_the_rest_of_the_product():
    from src.data.predictive_catalog import OIL_LABELS
    for labels in OIL_LABELS.values():
        for essay, label in labels.items():
            match = re.search(r"\(([^)]+)\)\s*$", label)
            if match and essay in pdfcb.ESSAY_UNITS:
                assert pdfcb.ESSAY_UNITS[essay] == match.group(1), essay


def test_every_pdf_state_label_exists_in_both_catalogs():
    for language in ("es", "en"):
        catalog = load_catalog(language)
        assert all(key in catalog for key, _shape, _color in pdf.TEST_STATES.values())


# ---------------------------------------------------------------------------
# A. The rendered document
# ---------------------------------------------------------------------------

def test_pdf_sections_follow_the_specified_order_and_ship_nothing_from_the_mockup():
    data = _render(_build())
    assert data.startswith(b"%PDF")
    text = "\n".join(_pages(data))
    order = [text.index(label) for label in (
        "CSL006", "Estado del reporte", "Análisis y recomendación de IA", "Valores de ensayo y límites",
        "Historial de muestras", "Tendencia de ensayos")]
    assert order == sorted(order)
    for label in ("Familia", "Cliente", "Fecha de muestra", "ID de reporte", "Horómetro del componente", "Horómetro del aceite"):
        assert label in text
    lowered = text.lower()
    for leftover in ("mockup", "ilustrativ", "[ logo ]", "[lím.]", "fuera de escala", "9 meses"):
        assert leftover not in lowered, leftover


def test_page_one_status_details_and_comparison_line():
    first = re.sub(r"\s+", " ", _pages(_render(_build()))[0])          # wrapped lines read as one
    for text in ("ANORMAL", "Anomalía detectada", "Desgaste de Componentes", "Ensayos fuera de límite",
                 "Hierro", "DIAGNÓSTICO", "Desgaste elevado.", "ACCIONES",
                 "Revisar filtros.", "Cambiar aceite.",
                 "Respecto a la muestra anterior (2026-06-21 · Normal · hace 14 días): 1 nuevo ensayo crítico — Hierro · 0 ensayos resueltos."):
        assert text in first, text


def test_series_section_states_the_range_once_and_the_current_sample_mark():
    text = re.sub(r"\s+", " ", "\n".join(_pages(_render(_build()))))
    assert text.count("Rango: 2026-01-05 a 2026-07-05") == 1
    assert "el punto grande es el reporte actual (2026-07-05)" in text


def test_normal_report_page_one_has_only_the_status():
    first = _pages(_render(_build(_frame(last_status="Normal"))))[0]
    assert "NORMAL" in first
    assert "Anomalía detectada" not in first and "Ensayos fuera de límite" not in first


def test_first_report_has_no_comparison_line():
    df = _frame()
    first = _pages(_render(_build(df, str(df["sampleDate"].iloc[0]))))[0]
    assert "Respecto a la muestra anterior" not in first


def test_values_table_columns_group_column_states_and_previous_date_header():
    text = "\n".join(_pages(_render(_build())))
    for header in ("Grupo", "Ensayo", "Unidad", "Valor", "Lím. inferior", "Lím. superior", "Marg.", "Crít.", "Estado", "Anterior"):
        assert header in text
    for key in ("Marginal: fuera del límite marginal", "Crítico: fuera del límite crítico", "— sin límite o sin valor"):
        assert key in " ".join(text.split())                                  # the symbol legend above the table
    assert "2026-06-21" in text
    assert "Crítico · alto" in text
    assert "Filas resaltadas = ensayos fuera de límite (1)" in text       # the highlighted rows, = the header's count
    flat = " ".join(text.split())                              # the group name wraps inside its narrow column
    for group in ("Metales de desgaste", "Contaminación", "Aditivos", "Condición del lubricante"):
        assert group in flat
    assert "Agua · Combustible — sin datos en esta muestra" in flat
    assert "Sin límite definido: Índice PQ 3 · Ni 0,1" in flat


def test_the_group_name_spans_its_rows_and_a_group_never_splits_across_pages():
    from reportlab.platypus import Table

    table = next(b for b in pdf._values_block(_build()) if isinstance(b, Table))
    group_spans = [c for c in table._spanCmds if c[1][0] == 0 and c[2][0] == 0 and c[1][1] >= 2]     # below the 2 header rows
    assert len(group_spans) == 4                                                # one spanned name cell per group
    assert all(c[2][1] > c[1][1] for c in group_spans)                          # over more than one row


def test_critical_rows_are_tinted_more_strongly_than_marginal_ones():
    def luminance(color):
        return 0.299 * color.red + 0.587 * color.green + 0.114 * color.blue
    assert luminance(pdf.CRITICAL_FILL) < luminance(pdf.MARGINAL_FILL) < 1


def test_every_page_has_the_footer_and_pages_after_the_first_the_compact_header():
    pages = _pages(_render(_build()))
    assert len(pages) >= 2
    for number, text in enumerate(pages, start=1):
        assert f"Página {number} de {len(pages)}" in text
        assert "ID de reporte R009 · CSL006 · Muestra 2026-07-05" in text
        assert "Generado: 2026-11-26" in text
    for text in pages[1:]:
        for item in ("CSL006", "Mando Final Derecho", "Camión", "EMIN", "Muestra 2026-07-05 · ID R009", "ANORMAL"):
            assert item in text, item


def test_history_is_a_timeline_with_the_current_comment_in_full_and_the_rest_cut_to_two_lines():
    long_comment = "Diagnóstico: " + "palabra " * 90 + "FINAL. Acción: Revisar."
    report = _build(_frame(long_comment=long_comment))
    text = " ".join("\n".join(_pages(_render(report))).split())
    assert "actual" in text
    assert "Diagnóstico palabra" in text and "FINAL." in text and "Acción Revisar." in text   # the examined comment, in full
    assert "…" in text                                                                         # the others end in an ellipsis
    for entry in report.history:                                                                # every ID whole, never broken
        assert f"ID {entry.report_id}" in text
    # each of the other entries shows at most two lines of comment
    cut = pdf.wrap_lines("palabra " * 200, 150.0, pdf.FONT, 7.2, 2)
    assert len(cut) == 2 and cut[-1].endswith("…")
    assert pdf.wrap_lines("corto", 150.0, pdf.FONT, 7.2, 2) == ["corto"]


def test_a_long_report_flows_onto_more_pages_and_nothing_is_cut():
    actions = " ".join(f"Realizar la acción número {i} con el procedimiento completo." for i in range(60))
    report = _build(_frame(long_comment=f"Diagnóstico: {'texto ' * 600}ULTIMA-PALABRA.\nAcción: {actions}"))
    pages = _pages(_render(report))
    assert len(pages) >= 3
    text = "\n".join(pages)
    assert "ULTIMA-PALABRA." in text and "acción número 59" in text
    for number, page in enumerate(pages, start=1):
        assert f"Página {number} de {len(pages)}" in page


def test_text_outside_the_pdf_fonts_never_breaks_the_document():
    df = _frame(long_comment="Diagnóstico: Δ ≥ 5 → ✓ 日本語 sin problema.\nAcción: Revisar <filtro> & cambiar.")
    pages = _pages(_render(_build(df)))
    text = "\n".join(pages)
    assert ">= 5" in text and "<filtro> & cambiar." in text


def test_status_is_text_plus_a_shape_in_the_pdf():
    """Each status is a word (found in the page text) and a drawn shape (vector paths on the page)."""
    fitz = pytest.importorskip("pymupdf")
    document = fitz.open(stream=_render(_build()), filetype="pdf")
    page = document[0]
    assert "ANORMAL" in page.get_text()
    assert len(page.get_drawings()) > 20


def test_logo_slot_only_when_an_asset_exists(tmp_path):
    fitz = pytest.importorskip("pymupdf")
    from PIL import Image

    without = fitz.open(stream=_render(_build()), filetype="pdf")
    assert without[0].get_images() == []
    logo = tmp_path / "logo.png"
    Image.new("RGB", (400, 120), (30, 60, 120)).save(logo)
    with_logo = fitz.open(stream=_render(_build(logo_path=logo)), filetype="pdf")
    assert len(with_logo[0].get_images()) == 1
    rect = with_logo[0].get_image_rects(with_logo[0].get_images()[0][0])[0]
    assert rect.x1 > with_logo[0].rect.width * 0.8 and rect.y0 < with_logo[0].rect.height * 0.15      # top right
    # a path that is not an image never breaks the report: the slot is omitted
    broken = tmp_path / "broken.png"
    broken.write_text("not an image")
    assert _pages(_render(_build(logo_path=broken)))[0].count("CSL006") >= 1


def test_find_logo_is_none_until_the_asset_is_provided(monkeypatch, tmp_path):
    monkeypatch.setattr(pdfcb, "LOGO_DIR", tmp_path)
    assert pdfcb.find_logo() is None
    (tmp_path / "oil_report_logo.png").write_bytes(b"x")
    assert pdfcb.find_logo() == tmp_path / "oil_report_logo.png"


def test_english_pdf_uses_the_english_labels():
    with forced_language("en"):
        text = "\n".join(_pages(_render(_build())))
    assert "Page 1 of" in text and "Report ID" in text
    assert "Valores de ensayo y límites" not in text and "Essay values and limits" in text
    assert "Compared with the previous sample" in text
    assert "Critical · high" in text


# ---------------------------------------------------------------------------
# A. The download button and callback
# ---------------------------------------------------------------------------

@pytest.fixture
def pdf_app():
    app = _Capture()
    pdfcb.register_oil_report_pdf_callbacks(app)
    return app.callbacks


def test_button_is_enabled_only_when_a_report_is_loaded(pdf_app):
    toggle = pdf_app["toggle_pdf_button"]
    assert toggle("camion", "csl006", "mando final derecho", "2026-07-05") is False
    for incomplete in (("camion", "csl006", "mando final derecho", None), (None, "csl006", "m", "d"),
                       ("camion", None, "m", "d"), ("camion", "csl006", None, "d")):
        assert toggle(*incomplete) is True


def test_layout_has_the_button_disabled_a_download_target_and_feedback():
    from dashboard.tabs.tab_reports import create_reports_tab

    layout = create_reports_tab()
    button = _find(layout, "reports-pdf-button")
    assert button.disabled is True
    assert "Descargar reporte en PDF" in str(button.children)
    assert _find(layout, "reports-pdf-download") is not None
    assert _find(layout, "reports-pdf-feedback") is not None
    assert _find(layout, "reports-pdf-loading").style == {"display": "none"}


def test_download_returns_the_selected_report_with_the_suggested_name(pdf_app, monkeypatch):
    calls = []

    def fake_generate(client, familia, equipo, component, sample_date):
        calls.append((client, familia, equipo, component, sample_date))
        return b"%PDF-fake", "CSL006_Mando-Final-Derecho_2026-11-14.pdf"

    monkeypatch.setattr(pdfcb, "generate_oil_report_pdf", fake_generate)
    data, feedback = pdf_app["download_report_pdf"](1, "camion", "csl006", "mando final derecho", "2026-11-14", "EMIN")
    assert feedback is None and data["filename"] == "CSL006_Mando-Final-Derecho_2026-11-14.pdf"
    assert base64.b64decode(data["content"]) == b"%PDF-fake"
    assert calls == [("EMIN", "camion", "csl006", "mando final derecho", "2026-11-14")]


def test_download_failure_shows_an_error_message_and_no_file(pdf_app, monkeypatch):
    def broken(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(pdfcb, "generate_oil_report_pdf", broken)
    data, feedback = pdf_app["download_report_pdf"](1, "camion", "csl006", "mando final derecho", "2026-11-14", "EMIN")
    assert data is None
    assert "No se pudo generar el PDF" in str(feedback.children) and feedback.color == "danger"


def test_download_without_a_loaded_report_is_refused_with_a_message(pdf_app):
    data, feedback = pdf_app["download_report_pdf"](1, "camion", None, "mando final derecho", "2026-11-14", "EMIN")
    assert data is None and "Seleccione" in str(feedback.children)


def test_generate_reads_the_clients_data_and_returns_a_real_pdf(monkeypatch, tmp_path):
    class Settings:
        def get_stewart_limits_four_path(self, client):
            return tmp_path / "limits.parquet"

    (tmp_path / "limits.parquet").write_text("x")
    monkeypatch.setattr(pdfcb, "get_settings", lambda: Settings())
    monkeypatch.setattr(pdfcb, "load_oil_classified", lambda client: _frame())
    monkeypatch.setattr(pdfcb, "load_stewart_limits_four", lambda path: _limits())
    data, name = pdfcb.generate_oil_report_pdf("EMIN", "camion", "csl006", "mando final derecho", "2026-07-05")
    assert data.startswith(b"%PDF") and name == "CSL006_Mando-Final-Derecho_2026-07-05.pdf"


# ---------------------------------------------------------------------------
# The mockup's layout facts (documentation/pdf_oil/)
# ---------------------------------------------------------------------------

def test_two_column_section_is_a_third_history_and_two_thirds_charts():
    assert abs(pdf.RIGHT_W / pdf.LEFT_W - 2) < 0.02
    fitz = pytest.importorskip("pymupdf")
    document = fitz.open(stream=_render(_build()), filetype="pdf")
    for page in document:
        history, charts = page.search_for("Historial de muestras"), page.search_for("Tendencia de ensayos")
        if history and charts:
            assert history[0].x0 < charts[0].x0                                               # history on the left
            assert abs((charts[0].x0 - history[0].x0) - (pdf.LEFT_W + pdf.COL_GAP)) < 3       # charts start after a third
            assert abs(history[0].y0 - charts[0].y0) < 3                                       # side by side
            break
    else:
        pytest.fail("no page has both columns")


def test_chart_cards_are_two_per_row_in_the_right_column():
    from reportlab.platypus import Table

    report = _build()
    blocks = pdf._chart_blocks(report)
    rows = [b for b, _after in blocks[1:] if isinstance(b, Table)]
    first_row = blocks[0][0].items[-1]                                      # heading + first row travel together
    cells = [row._cellvalues[0] for row in [first_row] + rows]
    assert all(len(c) == 3 and c[1] == "" for c in cells)                  # card, gutter, card
    assert sum(1 for c in cells for card in (c[0], c[2]) if card != "") == len(report.charts)
    assert abs(pdf.CARD_W * 2 + pdf.CARD_GAP - pdf.RIGHT_W) < 0.01


def test_limit_labels_always_name_the_test_when_the_chart_plots_several():
    both = ["Hierro", "Índice PQ"]
    assert pdfcb._limit_label("upper", "Hierro", 119.0, both, 1) == "Fe 119,0"
    assert pdfcb._limit_label("upper", "Índice PQ", 121.0, both, 0) == "PQ 121"
    assert pdfcb._limit_label("lower", "Índice PQ", 15.0, both, 0) == "PQ mín 15"
    assert pdfcb._limit_label("upper", "Viscocidad", 9.0, ["Viscocidad"], 2) == "máx 9,00"
    assert pdfcb._limit_label("lower", "Viscocidad", 5.0, ["Viscocidad"], 2) == "mín 5,00"


def test_comparison_sentence_pluralizes_and_names_the_new_critical_tests():
    one = pdf._comparison_line(pdf.Comparison("2026-10-21", "Normal", 24, ["Cobre"], 0)).text
    assert "(2026-10-21 · Normal · hace 24 días): 1 nuevo ensayo crítico — Cobre · 0 ensayos resueltos." in one
    many = pdf._comparison_line(pdf.Comparison("2026-10-21", "Alerta", 1, ["Cobre", "Níquel"], 1)).text
    assert "hace 1 día" in many and "2 nuevos ensayos críticos — Cobre, Níquel" in many and "1 ensayo resuelto." in many
    none = pdf._comparison_line(pdf.Comparison("2026-10-21", "Normal", None, [], 2)).text
    assert "hace" not in none and "0 nuevos ensayos críticos · 2 ensayos resueltos." in none
    mixed = pdf._comparison_line(pdf.Comparison("2026-10-21", "Normal", 5, ["Hierro"], 0, ["Sodio"])).text
    assert "1 nuevo ensayo crítico — Hierro · 1 nuevo ensayo marginal — Sodio · 0 ensayos resueltos." in mixed


def test_every_dynamic_translation_key_of_the_pdf_exists_in_both_catalogs():
    keys = [f"oil_report_pdf.{name}" for name in (
        "cmp_lead", "cmp_days_one", "cmp_days_many", "cmp_new_one", "cmp_new_many", "cmp_resolved_one",
        "cmp_resolved_many", "footer_ident", "header_sample", "limit_max", "limit_min", "unit_index",
        "series_note", "values_note", "history_note", "no_data_line", "zero_strip", "action_singular",
        "id_short", "months_short", "group_others", "col_group", "col_previous")]
    for language in ("es", "en"):
        catalog = load_catalog(language)
        assert [key for key in keys if key not in catalog] == []
        assert len(catalog["oil_report_pdf.months_short"].split(",")) == 12


# --- the two-column packing -------------------------------------------------------------------

def _spacers(*heights):
    from reportlab.platypus import Spacer
    return [(Spacer(1, h), 0) for h in heights]


def test_two_column_moves_whole_blocks_and_never_splits_one():
    section = pdf.TwoColumn(_spacers(30, 30, 30), 100, _spacers(50, 50), 200, 10)
    assert section.wrap(310, 1000)[1] == 100
    head, rest = section.split(310, 70)
    assert [b.height for b, _a in head.left] == [30, 30] and [b.height for b, _a in head.right] == [50]
    assert [b.height for b, _a in rest.left] == [30] and [b.height for b, _a in rest.right] == [50]
    assert head.wrap(310, 70)[1] <= 70 and rest.wrap(310, 70)[1] <= 70
    # everything fits: nothing to split off
    assert len(section.split(310, 500)) == 1 and section.split(310, 500)[0].wrap(310, 500)[1] == 100


def test_two_column_waits_for_the_next_page_when_not_even_one_block_fits():
    section = pdf.TwoColumn(_spacers(30), 100, _spacers(50), 200, 10)
    assert section.split(310, 20) == []                                       # start on a fresh page instead
    tall = pdf.TwoColumn(_spacers(pdf.FRAME_H + 50), 100, _spacers(10), 200, 10)
    head, rest = tall.split(310, pdf.FRAME_H)                                  # the small block goes now ...
    assert len(head.right) == 1 and head.left == [] and len(rest.left) == 1
    forced = rest.split(310, pdf.FRAME_H)                                      # ... the oversized one is forced onto a fresh page
    assert len(forced) == 1 and len(forced[0].left) == 1


def test_a_long_report_flows_across_pages_with_every_block_whole():
    report = _build()
    base = report.history[1]
    report.history = report.history[:1] + [
        pdf.HistoryRow(f"X{i:04d}", f"2026-0{1 + i % 6}-1{i % 9}", "Normal", "—", base.comment) for i in range(30)]
    report.charts = report.charts * 6
    pages = _pages(_render(report))
    assert len(pages) >= 4
    text = "\n".join(pages)
    for i in range(30):
        assert len(re.findall(rf"ID X{i:04d}\b", text)) == 1                  # each history entry once, whole
    for number, page in enumerate(pages, start=1):
        assert f"Página {number} de {len(pages)}" in page
    assert text.count("Hierro & PQ") == 6                                      # every chart card, once each


def test_logo_slot_is_top_right_only_when_an_asset_exists_and_nothing_else_changes(tmp_path):
    fitz = pytest.importorskip("pymupdf")
    from PIL import Image

    plain = _pages(_render(_build()))
    logo = tmp_path / "logo.png"
    Image.new("RGB", (400, 120), (30, 60, 120)).save(logo)
    document = fitz.open(stream=_render(_build(logo_path=logo)), filetype="pdf")
    assert len(document[0].get_images()) == 1
    assert len(plain) == len(document)


# ---------------------------------------------------------------------------
# Fix list (reference report: T_14, mando final trasero derecho, 2026-05-17)
# ---------------------------------------------------------------------------

def _t14():
    """The reference case: Hierro 141 (limit 119) and Índice PQ 137 (limit 121) critical; Potasio 5 (stored
    critical limit 5, the file says 3 / 4) critical; Sodio 4 (stored marginal limit 4, the file says 5 / 6)
    marginal. The previous sample is clean."""
    df = _frame(n=8)
    df["Índice PQ"] = 50.0                                        # inside its 15 - 121 band in every earlier sample
    last = df.index[-1]
    for column, value in (("Hierro", 141.0), ("Índice PQ", 137.0), ("Sodio", 4.0), ("Potasio", 5.0)):
        df.at[last, column] = value
    df = _flagged(df, _entry("Hierro", "Critico", limit=119.0, value=141.0), _entry("Potasio", "Critico", limit=5.0, value=5.0),
                  _entry("Sodio", "Marginal", limit=4.0, value=4.0), _entry("Índice PQ", "Critico", limit=121.0, value=137.0))
    limits = _limits()
    comp = limits["EMIN"]["camion"]["motor"]
    comp["Hierro"] = {"ALL": {"LIC": None, "LIM": None, "LSM": 92.0, "LSC": 119.0}}
    comp["Índice PQ"] = {"ALL": {"LIC": 15.0, "LIM": 19.0, "LSM": 101.0, "LSC": 121.0}}
    comp["Sodio"] = {"ALL": {"LIC": None, "LIM": None, "LSM": 5.0, "LSC": 6.0}}
    comp["Potasio"] = {"ALL": {"LIC": None, "LIM": None, "LSM": 3.0, "LSC": 4.0}}
    return df, limits


def _number(text):
    return float(text.replace(".", "").replace(",", "."))


def assert_chart_limits_are_table_limits(report):
    """Every limit line of every chart is a limit printed in the table for the same test."""
    rows = {row.essay: row for row in _rows(report)}
    drawn = 0
    for chart in report.charts:
        for limit in chart.limits:
            row = rows[limit.essay]
            printed = [v for v in (row.lower_marginal, row.lower, row.upper_marginal, row.upper) if v != "—"]
            assert any(abs(_number(v) - limit.value) < 1e-9 for v in printed), (limit.essay, limit.value, printed)
            assert any(limit.label.endswith(v) for v in printed), (limit.label, printed)
            drawn += 1
    return drawn


def test_chart_limits_equal_the_table_limits_in_the_reference_report():
    df, limits = _t14()
    report = _build(df, limits=limits)
    rows = {r.essay: r for r in _rows(report)}
    # the table shows both thresholds, so a reader can tell why each test has its status
    assert (rows["Sodio"].upper_marginal, rows["Sodio"].upper, rows["Sodio"].state) == ("4,0", "6,0", "marginal_high")
    assert (rows["Potasio"].upper_marginal, rows["Potasio"].upper, rows["Potasio"].state) == ("3,0", "5,0", "high")
    assert (rows["Hierro"].upper_marginal, rows["Hierro"].upper) == ("92,0", "119,0")
    assert (rows["Índice PQ"].lower_marginal, rows["Índice PQ"].lower, rows["Índice PQ"].upper) == ("19", "15", "121")
    charts = {c.title: c for c in report.charts}
    # one labelled line per test, with the table's value: no merged "máx 120", no value that is not a limit
    assert sorted(l.label for l in charts["Hierro & PQ"].limits) == ["Fe 119,0", "PQ 121", "PQ mín 15"]
    assert sorted(l.label for l in charts["Sodio & Potasio"].limits) == ["K 5,0", "Na 6,0"]
    assert assert_chart_limits_are_table_limits(report) >= 5


def test_chart_limits_equal_the_table_limits_in_every_scenario():
    df, limits = _t14()
    scenarios = [_build(), _build(limits=None), _build(_flagged(_frame(), _entry("Cobre", "Marginal", limit=0.9, value=1.0))),
                 _build(df, limits=limits), _build(df, str(df["sampleDate"].iloc[3]), limits=limits)]
    sparse = _frame(n=4)
    sparse["sampleDate"] = pd.to_datetime(SPARSE_DATES)
    scenarios.append(_build(sparse, "2026-11-14"))
    assert sum(assert_chart_limits_are_table_limits(report) for report in scenarios) > 10


def test_header_and_comparison_list_the_out_of_limit_tests_by_severity_with_the_tables_count():
    df, limits = _t14()
    report = _build(df, limits=limits)
    cls = report.classification
    assert cls.flagged == [("Hierro", "high"), ("Índice PQ", "high"), ("Potasio", "high"), ("Sodio", "marginal_high")]
    assert cls.out_of_limit == 4 == len(_highlighted(report))
    assert [(r.essay, r.state) for r in _highlighted(report)] != []
    assert sorted((r.essay, r.state) for r in _highlighted(report)) == sorted(cls.flagged)
    # "críticos" is ▲ only: Sodio (△) is a new marginal test, not a critical one
    assert report.comparison.new_critical == ["Hierro", "Índice PQ", "Potasio"] and report.comparison.new_marginal == ["Sodio"]
    first = re.sub(r"\s+", " ", _pages(_render(report))[0])
    assert "3 nuevos ensayos críticos — Hierro, Índice PQ, Potasio · 1 nuevo ensayo marginal — Sodio" in first
    assert "Ensayos fuera de límite" in first and "Ensayos críticos" not in first


def test_the_header_list_draws_a_symbol_per_test():
    fitz = pytest.importorskip("pymupdf")
    df, limits = _t14()
    page = fitz.open(stream=_render(_build(df, limits=limits)), filetype="pdf")[0]
    assert len(pdf.SymbolList(_build(df, limits=limits).classification.flagged, 120.0).entries) == 4
    assert len(page.get_drawings()) > 30


def test_the_report_statuses_have_distinct_symbols_and_colors_and_match_the_dashboard():
    from pathlib import Path

    from shared.severity import STATUS_TIERS, STATUS_TIER_BY_ESTADO

    assert pdf.STATUS_SHAPES == {"Normal": "circle", "Alerta": "triangle", "Anormal": "diamond"}
    assert len(set(pdf.STATUS_SHAPES.values())) == 3
    assert len({v["text"] for v in pdf.STATUS_STYLE.values()}) == 3
    # the dashboard's chip draws the same shapes (assets/status_chip.css)
    css = (Path(__file__).resolve().parent.parent / "dashboard" / "assets" / "status_chip.css").read_text(encoding="utf-8")
    assert "status-chip--normal .status-chip__shape" in css and "border-radius: 50%" in css
    assert "polygon(50% 0, 100% 100%, 0 100%)" in css                                        # Alerta: triangle
    assert "polygon(50% 0, 100% 50%, 50% 100%, 0 50%)" in css                                # Anormal: diamond
    # the pills take the dashboard's own tiers
    for status in ("Normal", "Alerta", "Anormal"):
        background, text, _border = pdf.status_colors(status)
        tier = STATUS_TIERS[STATUS_TIER_BY_ESTADO[status]]
        assert background.hexval()[2:].lower() == (tier["badge_bg"] if status == "Normal" else tier["bg"]).lstrip("#").lower()


def test_alerta_is_rendered_in_the_classification_block_the_history_and_the_status_key():
    df = _frame(last_status="Alerta")
    df.at[df.index[-3], "report_status"] = "Alerta"
    text = " ".join("\n".join(_pages(_render(_build(df)))).split())
    assert "ALERTA" in text                                                  # the pill of the classification block
    assert "Normal Alerta Anormal" in text                                   # the key under "Historial de muestras"
    assert len(re.findall(r"2026-0\d-\d\d Alerta", text)) >= 1               # an Alerta entry of the timeline
    first = _pages(_render(_build(df)))[0]
    assert "Anomalía detectada" in first                                     # Alerta carries the details too


def test_truncated_comments_never_end_inside_a_word_or_a_number():
    text = ("Diagnóstico: Desgaste severo en componentes internos (Fe 127,0 ppm, Al 2,0 ppm, Si 21,0 ppm). Índice PQ 1.234,5 "
            "elevado y exceso de aditivos (Ca 3.728,0 ppm) que indica contaminación por refrigerante y degradación")
    cuts = 0
    for width in range(60, 260, 7):
        lines = pdf.wrap_lines(text, width, pdf.FONT, 7.2, 3)
        assert len(lines) <= 3
        last = lines[-1]
        if not last.endswith("…"):
            continue
        cuts += 1
        body = " ".join(lines[:-1] + [last[:-1]])
        assert text.startswith(body), (width, body)
        assert text[len(body)] in " .,;:", (width, body)                        # the next character starts a new word
        tail = last[:-1]
        assert not re.search(r"[\d.,]$", tail) and not re.search(r"(^|\s)[^\W\d_]{1,2}$", tail), (width, tail)   # no dangling number or "Al"
    assert cuts > 5


def test_valued_tests_without_a_limit_share_one_line_per_group():
    df, limits = _t14()
    for column in ("Cromo", "Bario", "Molibdeno", "Plata", "Titanio", "Vanadio", "Manganeso"):
        df[column] = 0.0
    df["Manganeso"] = 1.0
    df.at[df.index[-2], "Manganeso"] = 3.0                                    # the previous value differs: it is shown
    comp = limits["EMIN"]["camion"]["motor"]
    comp.pop("Cromo")
    report = _build(df, limits=limits)
    lines = [text for group in report.groups for text in group.no_limit]
    assert "Cr 0,0" in " ".join(lines) and "Ba 0,0" in " ".join(lines) and "Mo 0,0" in " ".join(lines)
    assert any("Mn 1,0 (ant. 3,0)" in line for line in lines)
    for essay in ("Cromo", "Bario", "Molibdeno", "Plata", "Titanio", "Vanadio", "Manganeso"):
        assert essay not in {r.essay for r in _rows(report)}                  # no row of their own
    assert {"Hierro", "Sodio", "Potasio", "Índice PQ"} <= {r.essay for r in _rows(report)}   # flagged ones keep theirs


def test_one_number_rule_for_the_whole_pdf():
    # table, limits, header and prose share separators and the decimals of the unit
    assert pdf.format_number(18418, 0) == "18.418" and pdf.format_number(3263, 1) == "3.263,0"
    assert pdf.format_number(0.15, 2) == "0,15" and pdf.format_number(None) == "—" and pdf.format_number(-0.0, 1) == "0,0"
    with forced_language("en"):
        assert pdf.format_number(18418, 0) == "18,418" and pdf.format_number(3263, 1) == "3,263.0"
    localize = pdf.localize_text_numbers
    assert localize("Fe 3641,0 ppm y K 96,0 ppm") == "Fe 3.641,0 ppm y K 96,0 ppm"
    assert localize("Fe 159 ppm y K 4 ppm") == "Fe 159,0 ppm y K 4,0 ppm"           # the unit's decimals, as in the table
    assert localize("agua (1,0%) y viscosidad 25,4 cSt") == "agua (1,00%) y viscosidad 25,40 cSt"
    assert localize("cada 125 hrs, Índice PQ 137, ID R120-56198-0161 del 2026-05-17") == "cada 125 hrs, Índice PQ 137, ID R120-56198-0161 del 2026-05-17"
    assert localize("Ca 3.728,0 ppm") == "Ca 3.728,0 ppm" and localize(None) == ""
    with forced_language("en"):
        assert localize("Fe 3641.0 ppm and K 96.0 ppm") == "Fe 3,641.0 ppm and K 96.0 ppm"


def test_every_number_in_the_rendered_pdf_follows_the_rule():
    df = _frame()
    df["componentHours"] = 18418.0
    df["oilMeter"] = 3549.0
    df.at[df.index[-1], "Hierro"] = 3263.0
    df.at[df.index[-1], "ai_recommendation"] = "Diagnóstico: Hierro 3263 ppm y plomo 96,0 ppm, agua 3641,0 ppm.\nAcción: Revisar a 125 hrs."
    df = _flagged(df, _entry("Hierro", "Critico", limit=20.0, value=3263.0))
    report = _build(df)
    assert (report.identity.componente_horas, report.identity.aceite_horas) == ("18.418 hrs", "3.549 hrs")
    text = " ".join("\n".join(_pages(_render(report))).split())
    assert "18.418 hrs" in text and "3.549 hrs" in text
    assert "3.263,0" in text                                                   # the table
    assert "Hierro 3.263,0 ppm y plomo 96,0 ppm, agua 3.641,0 ppm" in text    # the AI text, by the same rule
    assert not re.search(r"\b3263\b|\b3641\b|\b18,418\b|\b3549[.,]0\b", text)


def test_names_the_data_spells_without_accents_are_spelled_right():
    df = _frame()
    df["Numero Total Basico"] = 6.6
    report = _build(df)
    assert report.identity.familia == "Camión"
    others = _group(report, "Otros ensayos")
    assert others.no_limit == ["Número total básico 6,6"]
    assert pdfcb._display_essay("Numero Total Basico") == "Número total básico"
    assert pdfcb._display_name("camion") == "Camión" and pdfcb._display_name("transmision") == "Transmisión"
    text = "\n".join(_pages(_render(report)))
    assert "Número total básico" in text and "Camión" in text and "Camion" not in text and "Numero" not in text
