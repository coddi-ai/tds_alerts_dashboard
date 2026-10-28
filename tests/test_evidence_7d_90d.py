"""Evidence's Resumen de Condición and Perfil de riesgo use the 7d / 90d windows,
plus the 7d-vs-90d risk trend marker."""
import re

import numpy as np
import pandas as pd
import pytest

from dashboard.components.predictive_charts import create_comparative_bars
from dashboard.tabs import tab_predictive_evidence as ev

MODES = {"m1": "Modo Uno", "m2": "Modo Dos"}


@pytest.mark.parametrize("r7, r90, expected", [
    (30.0, 20.0, "increasing"), (25.1, 20.0, "increasing"),
    (25.0, 20.0, "stable"), (20.0, 20.0, "stable"), (15.0, 20.0, "stable"),
    (14.9, 20.0, "decreasing"), (5.0, 40.0, "decreasing"),
    (np.nan, 20.0, None), (20.0, np.nan, None),
])
def test_risk_trend_three_states_with_5_point_tolerance(r7, r90, expected):
    assert ev.risk_trend(r7, r90) == expected


def _latest():
    return pd.DataFrame({
        "Unit": ["U1", "U2"], "ranking": [50.0, 10.0], "avg_ranking_7d": [40.0, 10.0],
        "avg_ranking_30d": [30.0, 10.0], "ranking_acum_90d": [20.0, 10.0], "status": ["Alerta", "Normal"],
        "m1_7d": [70.0, 10.0], "m2_7d": [5.0, 15.0], "m1_30d": [1.0, 1.0], "m2_30d": [2.0, 2.0],
    })


def test_perfil_de_riesgo_bars_use_the_7_day_window():
    latest = _latest()
    fig = create_comparative_bars(latest.iloc[0], latest, MODES)
    fleet, unit = fig.data
    by_mode = lambda trace: dict(zip(trace.y, trace.x))
    assert by_mode(unit) == {"Modo Uno": 70.0, "Modo Dos": 5.0}
    assert by_mode(fleet) == {"Modo Uno": 40.0, "Modo Dos": 10.0}


def _texts(component):
    out = []
    def walk(node):
        if isinstance(node, (list, tuple)):
            for n in node:
                walk(n)
        elif hasattr(node, "children"):
            walk(node.children)
        elif isinstance(node, str):
            out.append(node)
    walk(component)
    return out


def _render_resumen(monkeypatch, latest=None):
    latest = _latest() if latest is None else latest
    monkeypatch.setattr(ev, "attach_status", lambda df, client, component: df)
    monkeypatch.setattr(ev, "_resolve_unit_ai_panel", lambda *a, **k: {})
    monkeypatch.setattr(ev, "create_ai_analysis_panel", lambda **k: None)
    monkeypatch.setattr(ev, "resolve_failure_modes", lambda component, client: MODES)
    df = pd.DataFrame({"Unit": ["U1", "U2"], "Fecha": pd.to_datetime(["2026-01-02", "2026-01-02"])})
    return ev.render_initial_content("U1", df, latest, "motor", "cda")


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None and not isinstance(children, str):
        yield from _walk(children)


def _tiles(rendered):
    return [n for n in _walk(rendered) if "ev-tile" in (getattr(n, "className", None) or "").split()]


def test_resumen_de_condicion_cards(monkeypatch):
    texts = _texts(_render_resumen(monkeypatch))
    assert "Ranking 7 días" in texts and "40.0" in texts
    assert "Riesgo acum. 90d" in texts and "20.0" in texts
    assert not {"Ranking actual", "Riesgo acum. 30d"} & set(texts)
    assert "Tendencia de riesgo" in texts and "Empeorando" in texts  # 40 vs 20
    assert "Modo dominante" in texts


def test_kpi_tiles_are_ordered_90d_7d_trend_mode(monkeypatch):
    titles = [_texts(tile)[0] for tile in _tiles(_render_resumen(monkeypatch))]
    assert titles == ["Riesgo acum. 90d", "Ranking 7 días", "Tendencia de riesgo", "Modo dominante"]


def test_no_tile_uses_a_colored_left_accent(monkeypatch):
    rendered = _render_resumen(monkeypatch)
    assert not [n for n in _walk(rendered) if "kpi-accent" in (getattr(n, "className", None) or "")]
    assert not [n for n in _walk(rendered)
                if "borderLeft" in (getattr(n, "style", None) or {}) or "border-left" in str(getattr(n, "style", None) or "")]


def test_risk_tiles_show_a_gauge_and_a_chip_on_the_same_scale(monkeypatch):
    by_title = {_texts(t)[0]: t for t in _tiles(_render_resumen(monkeypatch))}
    for title, value, chip in [("Riesgo acum. 90d", "20.0", "Normal"), ("Ranking 7 días", "40.0", "Atención")]:
        tile = by_title[title]
        assert value in _texts(tile) and chip in _texts(tile)
        gauge = next(n for n in _walk(tile) if "ev-gauge" in (getattr(n, "className", None) or "").split())
        assert gauge.role == "meter" and getattr(gauge, "aria-valuemax") == 100


@pytest.mark.parametrize("value, label", [(0, "Normal"), (39.9, "Normal"), (40, "Atención"), (69.9, "Atención"), (70, "Crítico"), (100, "Crítico")])
def test_risk_chip_thresholds_are_shared_by_both_tiles(value, label):
    assert ev.risk_band(value)[1] == label
    for tile in (ev._risk_tile("a", value, ""), ev._risk_tile("b", value, "")):
        assert label in _texts(tile)


def test_risk_tile_without_a_score_is_neutral_not_healthy():
    tile = ev._risk_tile("Ranking", float("nan"), "sub")
    assert "—" in _texts(tile) and "Normal" not in _texts(tile) and "Sin Datos" in _texts(tile)


def test_trend_tile_states_the_direction_in_words():
    for r7, r90, word, arrow in [(40, 20, "Empeorando", "▲"), (10, 30, "Mejorando", "▼"), (20, 22, "Estable", "●")]:
        texts = _texts(ev._risk_trend_card(r7, r90))
        assert word in texts and arrow in texts and any("pts" in s for s in texts)


def test_dominant_mode_tile_stays_out_of_the_risk_palette():
    tile = ev._dominant_mode_card("Modo Uno", 12.3)
    rendered = str(tile)
    assert "ev-tile--mode" in rendered
    for _, _, fill, chip_bg, chip_text in ev.RISK_SCALE_BANDS:
        assert not {fill, chip_bg, chip_text} & set(re.findall(r"#[0-9a-fA-F]{6}", rendered))
    assert "ev-gauge" not in rendered and "ev-chip" not in rendered


def test_ultima_evidencia_is_subtitle_metadata_not_a_tile(monkeypatch):
    rendered = _render_resumen(monkeypatch)
    assert not any("Última evidencia" in _texts(tile)[0] for tile in _tiles(rendered))
    meta = next(n for n in _walk(rendered) if "ev-meta" in (getattr(n, "className", None) or "").split())
    assert any(s.startswith("Última evidencia") for s in _texts(meta)) and "02 Jan 2026" in _texts(meta)


@pytest.mark.parametrize("status, tier", [
    ("Normal", "normal"), ("normal", "normal"), ("Alerta", "anormal"), ("Anormal", "critico"),
    ("Sin Datos", None), (None, None), ("", None),
])
def test_banner_tier_comes_from_the_unit_status(status, tier):
    assert ev.banner_tier(status) == tier
    assert ev.unit_banner_style(status)["tier"] == tier


def test_each_banner_tier_has_its_own_fill_and_normal_has_no_alarm_color():
    fills = {tier: ev.unit_banner_style(s)["banner"]["background"]
             for tier, s in [("normal", "Normal"), ("anormal", "Alerta"), ("critico", "Anormal"), (None, "Sin Datos")]}
    assert len(set(fills.values())) == 4
    assert "e24b4a" in fills["critico"] and "b45309" in fills["anormal"]
    assert not {"e24b4a", "b45309", "ef9f27"} & set(re.findall(r"[0-9a-f]{6}", fills["normal"], re.I))
