"""Per-failure-mode status: the Calendario de estado, the Riesgo por modo de falla table and the
risk_level readers all take the status from `risk_scores.risk_level` - never from `risk_value`."""
import pandas as pd
import pytest

from dashboard.components import predictive_charts as pc
from dashboard.components import predictive_state as ps
from dashboard.components.predictive_charts import create_mode_status_calendar
from src.data import predictive_v2

END = pd.Timestamp("2026-01-31")
MODES = {"bearing_wear_risk": "Bearing", "other_risk": "Other"}
CODE = {level: i for i, level in enumerate(ps.RISK_LEVELS)}


def _values(bearing, other, start="2026-01-01"):
    dates = pd.date_range(start, periods=len(bearing), freq="D")
    return pd.DataFrame({"Fecha": dates, "bearing_wear_risk": bearing, "other_risk": other})


def _levels(bearing, other, start="2026-01-01"):
    dates = pd.date_range(start, periods=len(bearing), freq="D")
    return pd.DataFrame({"Fecha": dates, "bearing_wear_risk": bearing, "other_risk": other})


def _codes(fig):
    """{row label: [code per day]} of the heatmap."""
    heat = fig.data[0]
    return {y: list(z) for y, z in zip(heat.y, heat.z)}


# ── risk_level vocabulary ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, level", [
    ("Saludable", "Saludable"), ("monitoreo", "Monitoreo"), ("Prioridad alta", "Prioridad alta"),
    ("Critico", "Critico"), ("Crítico", "Critico"), (" CRÍTICO ", "Critico"),
    ("Alerta", None), ("", None), (None, None), (float("nan"), None), (pd.NA, None),
])
def test_normalize_risk_level_accepts_the_contract_spelling_and_nothing_else(raw, level):
    assert ps.normalize_risk_level(raw) == level


def test_every_level_has_one_color_and_one_label_key():
    assert set(ps.RISK_LEVEL_STYLE) == set(ps.RISK_LEVELS)
    colors = [ps.RISK_LEVEL_STYLE[level]["color"] for level in ps.RISK_LEVELS]
    assert len(set(colors)) == len(colors) and ps.RISK_LEVEL_NO_DATA_COLOR not in colors
    assert [ps.risk_level_label(level) for level in ps.RISK_LEVELS] == [
        "Saludable", "Monitoreo", "Prioridad alta", "Crítico"]
    assert ps.risk_level_label(None) == "Sin datos"


# ── Calendario de estado ──────────────────────────────────────────────────────

def test_cell_color_is_the_delivered_risk_level_whatever_the_value():
    # A value of 90 delivered as Saludable and a value of 0 delivered as Critico: the level wins.
    levels = _levels(["Saludable"] * 31, ["Critico"] * 31)
    values = _values([90.0] * 31, [0.0] * 31)
    codes = _codes(create_mode_status_calendar(values, MODES, END, days=31, risk_levels=levels))
    assert set(codes["Bearing"]) == {CODE["Saludable"]}
    assert set(codes["Other"]) == {CODE["Critico"]}


def test_each_day_takes_its_own_level():
    seq = list(ps.RISK_LEVELS) + ["Saludable"] * 27
    codes = _codes(create_mode_status_calendar(
        _values([10.0] * 31, [10.0] * 31), MODES, END, days=31, risk_levels=_levels(seq, seq)))
    assert codes["Bearing"][:4] == [0, 1, 2, 3]


def test_the_same_value_can_carry_different_levels_on_different_days():
    # risk_level is not a function of risk_value: the same 12.3 is Monitoreo one day, Prioridad alta the next.
    levels = _levels(["Monitoreo", "Prioridad alta"] * 15 + ["Monitoreo"], ["Saludable"] * 31)
    codes = _codes(create_mode_status_calendar(
        _values([12.3] * 31, [0.0] * 31), MODES, END, days=31, risk_levels=levels))["Bearing"]
    assert codes[:2] == [CODE["Monitoreo"], CODE["Prioridad alta"]]


def test_day_without_a_row_is_no_data_not_saludable():
    levels = _levels(["Monitoreo"] * 31, ["Monitoreo"] * 31).drop(index=15)
    codes = _codes(create_mode_status_calendar(
        _values([20.0] * 31, [20.0] * 31), MODES, END, days=31, risk_levels=levels))["Bearing"]
    assert codes[15] == pc._NO_DATA_CODE and codes[16] == CODE["Monitoreo"]


def test_unrecognised_or_null_level_is_no_data():
    levels = _levels(["Alerta", None, "Crítico"] + ["Saludable"] * 28, ["Saludable"] * 31)
    codes = _codes(create_mode_status_calendar(
        _values([5.0] * 31, [5.0] * 31), MODES, END, days=31, risk_levels=levels))["Bearing"]
    assert codes[:3] == [pc._NO_DATA_CODE, pc._NO_DATA_CODE, CODE["Critico"]]  # accent variant still maps


def test_without_risk_levels_there_is_no_calendar_and_values_never_stand_in():
    values = _values([99.0] * 31, [99.0] * 31)
    assert create_mode_status_calendar(values, MODES, END, days=31) is None
    assert create_mode_status_calendar(values, MODES, END, days=31, risk_levels=pd.DataFrame()) is None
    assert create_mode_status_calendar(values, MODES, END, days=31, risk_levels=_levels([None] * 31, [None] * 31)).data[0].z is not None


def test_palette_and_legend_come_from_the_shared_level_table():
    fig = create_mode_status_calendar(
        _values([1.0] * 31, [1.0] * 31), MODES, END, days=31,
        risk_levels=_levels(["Saludable"] * 31, ["Saludable"] * 31))
    colorscale_colors = {c for _, c in fig.data[0].colorscale}
    assert colorscale_colors == {ps.RISK_LEVEL_STYLE[l]["color"] for l in ps.RISK_LEVELS} | {ps.RISK_LEVEL_NO_DATA_COLOR}
    assert [t.name for t in fig.data[1:]] == ["Saludable", "Monitoreo", "Prioridad alta", "Crítico", "Sin datos"]


def test_no_threshold_machinery_is_left_in_the_chart_module():
    for name in ("classify_criticidad", "get_mode_thresholds", "_load_mode_thresholds", "CRITICIDAD_BANDS"):
        assert not hasattr(pc, name)


# ── Riesgo por Modo de Falla table (Predictivo > Resumen) ─────────────────────

def _fm_cell_backgrounds(level, value=20.0, mode="bearing_wear_risk", with_levels=True):
    from dashboard.tabs import tab_predictive_overview as ov

    latest = pd.DataFrame({
        "Unit": ["U1"], "status": "Normal", "ranking": 1.0, "avg_ranking_30d": 1.0,
        f"{mode}_30d": value,
    })
    levels = pd.DataFrame({mode: [level]}, index=pd.Index(["U1"], name="Unit")) if with_levels else None
    table = ov._failure_table(latest, "avg_ranking_30d", "avg_ranking_30d", False, {mode: "Modo"}, levels)
    row = table.children[0].children[1].children[0]
    return row.children[-1].style["background"]


@pytest.mark.parametrize("level", ps.RISK_LEVELS)
def test_failure_table_cell_takes_the_tone_of_the_risk_level(level):
    assert _fm_cell_backgrounds(level) == ps.RISK_LEVEL_STYLE[level]["cell_bg"]


def test_failure_table_cell_tone_ignores_the_number_it_shows():
    assert _fm_cell_backgrounds("Saludable", value=95.0) == ps.RISK_LEVEL_STYLE["Saludable"]["cell_bg"]
    assert _fm_cell_backgrounds("Critico", value=0.0) == ps.RISK_LEVEL_STYLE["Critico"]["cell_bg"]


def test_failure_table_without_a_level_is_neutral_never_green():
    from dashboard.components.labels import NO_DATA_BG

    assert _fm_cell_backgrounds(None) == NO_DATA_BG
    assert _fm_cell_backgrounds("Saludable", with_levels=False) == NO_DATA_BG
    assert _fm_cell_backgrounds("Saludable", mode="bearing_wear_risk") != NO_DATA_BG


# ── risk_level readers ────────────────────────────────────────────────────────

def _long():
    rows = []
    for unit in ("A", "B"):
        for day, (lvl_m1, lvl_rank) in enumerate([("Saludable", "Monitoreo"), ("Prioridad alta", "Prioridad alta")], start=1):
            d = pd.Timestamp(f"2026-01-0{day}")
            rows.append({"Unit": unit, "Fecha": d, "failure_mode": "m1", "risk_value": 1.0, "risk_level": lvl_m1})
            rows.append({"Unit": unit, "Fecha": d, "failure_mode": "ranking", "risk_value": 2.0, "risk_level": lvl_rank})
    rows.append({"Unit": "A", "Fecha": pd.Timestamp("2026-01-03"), "failure_mode": "m2", "risk_value": 3.0, "risk_level": "Critico"})
    return pd.DataFrame(rows)


def test_risk_levels_to_wide_keeps_the_delivered_strings_and_leaves_gaps_empty():
    wide = predictive_v2.risk_levels_to_wide(_long())
    a = wide[wide.Unit == "A"].set_index("Fecha")
    assert a.loc["2026-01-01", "m1"] == "Saludable" and a.loc["2026-01-02", "m1"] == "Prioridad alta"
    assert pd.isna(a.loc["2026-01-01", "m2"]) and a.loc["2026-01-03", "m2"] == "Critico"
    assert "ranking" in wide.columns


def test_risk_levels_to_wide_without_the_column_is_empty():
    assert predictive_v2.risk_levels_to_wide(_long().drop(columns="risk_level")).empty
    assert predictive_v2.risk_levels_to_wide(pd.DataFrame()).empty


def test_latest_risk_levels_is_the_last_day_each_unit_has_for_each_mode():
    latest = predictive_v2.latest_risk_levels(predictive_v2.risk_levels_to_wide(_long()))
    assert latest.loc["A", "m1"] == "Prioridad alta"   # 02 Jan (A has no m1 row on the 03rd)
    assert latest.loc["A", "m2"] == "Critico"
    assert pd.isna(latest.loc["B", "m2"])
