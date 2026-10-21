"""Evidence's Resumen de Condición and Perfil de riesgo use the 7d / 90d windows,
plus the 7d-vs-90d risk trend marker."""
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


def test_resumen_de_condicion_cards(monkeypatch):
    latest = _latest()
    monkeypatch.setattr(ev, "attach_status", lambda df, client, component: df)
    monkeypatch.setattr(ev, "_resolve_unit_ai_panel", lambda *a, **k: {})
    monkeypatch.setattr(ev, "create_ai_analysis_panel", lambda **k: None)
    monkeypatch.setattr(ev, "resolve_failure_modes", lambda component, client: MODES)
    df = pd.DataFrame({"Unit": ["U1", "U2"], "Fecha": pd.to_datetime(["2026-01-02", "2026-01-02"])})
    texts = _texts(ev.render_initial_content("U1", df, latest, "motor", "cda"))
    assert "Ranking 7 días" in texts and "40.0" in texts
    assert "Riesgo acum. 90d" in texts and "20.0" in texts
    assert not {"Ranking actual", "Riesgo acum. 30d"} & set(texts)
    assert "Tendencia de riesgo" in texts and any("Aumentando" in s for s in texts)  # 40 vs 20
    assert "Modo dominante" in texts and "Última evidencia" in texts
