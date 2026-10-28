"""Calendario de estado: bands come from the client's calibrated thresholds."""
import pandas as pd

from dashboard.components import predictive_charts as pc
from dashboard.components.predictive_charts import (
    classify_criticidad,
    create_mode_status_calendar,
    get_mode_thresholds,
)

END = pd.Timestamp("2026-01-31")
MODES = {"bearing_wear_risk": "Bearing", "unknown_mode_risk": "Unknown"}


def _frame(bearing, unknown, start="2026-01-01"):
    dates = pd.date_range(start, periods=len(bearing), freq="D")
    return pd.DataFrame({"Fecha": dates, "bearing_wear_risk": bearing, "unknown_mode_risk": unknown})


def _codes(fig):
    """{row label: [band code per day]} of the heatmap."""
    heat = fig.data[0]
    return {y: list(z) for y, z in zip(heat.y, heat.z)}


def test_capstone_thresholds_are_loaded_per_mode():
    edges = get_mode_thresholds("Capstone")
    assert edges["bearing_wear_risk"] == (5.8292, 16.3931, 42.9137)
    assert len(edges) == 10


def test_client_without_file_has_no_thresholds():
    assert get_mode_thresholds("cda") == {}
    assert get_mode_thresholds(None) == {}


def test_classify_uses_given_edges_and_keeps_missing_as_none():
    assert classify_criticidad(20.0) == 0  # fixed 35/55/75
    assert classify_criticidad(20.0, (5.8292, 16.3931, 42.9137)) == 2
    assert classify_criticidad(float("nan"), (1, 2, 3)) is None


def test_calibrated_mode_uses_its_edges_on_the_7_day_mean():
    # 31 days at 20: far under the fixed 35, but above bearing's P90 (16.39).
    df = _frame([20.0] * 31, [20.0] * 31)
    fig = create_mode_status_calendar(df, MODES, END, days=31, client="capstone")
    codes = _codes(fig)
    assert set(codes["Bearing"]) == {2}  # Prioridad alta
    assert set(codes["Unknown"]) == {0}  # no calibration -> fixed bands, Saludable


def test_mean_smooths_a_single_spike():
    values = [0.0] * 31
    values[-1] = 50.0  # daily 50 >= P98 (42.9), but the 7-day mean is ~7.1
    fig = create_mode_status_calendar(_frame(values, values), MODES, END, days=31, client="capstone")
    assert _codes(fig)["Bearing"][-1] == 1  # Monitoreo, not Crítico
    assert _codes(fig)["Unknown"][-1] == 1  # daily 50 against the fixed 35/55/75


def test_day_without_reading_stays_no_data_under_the_mean():
    df = _frame([20.0] * 31, [20.0] * 31).drop(index=15)
    fig = create_mode_status_calendar(df, MODES, END, days=31, client="capstone")
    assert _codes(fig)["Bearing"][15] == pc._NO_DATA_CODE
    assert _codes(fig)["Bearing"][16] == 2


def test_without_client_every_mode_keeps_the_fixed_bands():
    df = _frame([60.0] * 31, [60.0] * 31)
    fig = create_mode_status_calendar(df, MODES, END, days=31)
    assert set(_codes(fig)["Bearing"]) == {2}  # 55 <= 60 < 75


# ── Riesgo por Modo de Falla table (Predictivo > Resumen) ─────────────────────

def _fm_cell_backgrounds(client, value, mode="bearing_wear_risk"):
    from dashboard.tabs import tab_predictive_overview as ov

    latest = pd.DataFrame({
        "Unit": ["U1"], "status": "Normal", "ranking": 1.0, "avg_ranking_30d": 1.0,
        f"{mode}_30d": value,
    })
    table = ov._failure_table(latest, "avg_ranking_30d", "avg_ranking_30d", False, {mode: "Modo"}, client)
    row = table.children[0].children[1].children[0]
    return row.children[-1].style["background"]


def test_failure_table_cell_takes_the_mode_band_for_a_calibrated_client():
    from dashboard.tabs import tab_predictive_overview as ov

    bands = ov._BAND_CELL_STYLES
    # bearing edges: 5.8292 / 16.3931 / 42.9137
    assert _fm_cell_backgrounds("capstone", 3.0) == bands[0]["background"]
    assert _fm_cell_backgrounds("capstone", 10.0) == bands[1]["background"]
    assert _fm_cell_backgrounds("capstone", 20.0) == bands[2]["background"]
    assert _fm_cell_backgrounds("capstone", 45.0) == bands[3]["background"]


def test_failure_table_cell_keeps_the_fixed_style_without_thresholds():
    from dashboard.tabs import tab_predictive_overview as ov

    # 20 is Saludable under 40/70; the same value is Prioridad alta for capstone.
    assert _fm_cell_backgrounds("cda", 20.0) == ov._score_cell_style(20.0)["background"]
    assert _fm_cell_backgrounds(None, 20.0) == ov._score_cell_style(20.0)["background"]
    assert _fm_cell_backgrounds("capstone", 20.0, mode="unknown_mode_risk") == ov._score_cell_style(20.0)["background"]


def test_failure_table_missing_value_stays_neutral_for_a_calibrated_client():
    from dashboard.tabs import tab_predictive_overview as ov

    assert _fm_cell_backgrounds("capstone", float("nan")) == ov._score_cell_style(None)["background"]
