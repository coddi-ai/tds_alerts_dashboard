"""Predictivo -> Componente -> Evidencia: source of the unit-level Analisis
Inteligente panel. `unit_failure_analisis` leads; the worst-mode row of
`mode_failure_analisis` only stands in for units the upstream LLM pass skipped."""
import pandas as pd
import pytest

from dashboard.tabs import tab_predictive_evidence as ev
from src.data import predictive_v2

HEALTHY_TEXT = "El equipo no presenta indicios de este modo de fallo."


def _unit_row(unit="CA-83", estado="anormal", fuente="llm", **over):
    row = {
        "Unit": unit,
        "Fecha": pd.Timestamp("2026-09-12"),
        "estado": estado,
        "peor_modo": "thermal_imbalance_risk",
        "diagnostico": "Diagnostico de la unidad",
        "causa_probable": "Causa de la unidad",
        "acciones": '["Inmediato: revisar"]',
        "analisis_fuente": fuente,
    }
    row.update(over)
    return row


def _mode_row(status="ok", unit="CA-83", mode="thermal_imbalance_risk", **over):
    row = {
        "Unit": unit,
        "failure_mode": mode,
        "criticidad": "Monitoreo" if status == "ok" else "Saludable",
        "diagnostico": "Diagnostico del modo",
        "probable_cause": "Causa del modo",
        "recommended_actions": '["Inmediato: revisar el modo"]',
        "analysis_status": status,
    }
    if status == "healthy_default":
        row.update(diagnostico=HEALTHY_TEXT, probable_cause="Dentro de parametros normales")
    row.update(over)
    return row


@pytest.fixture
def tables(monkeypatch):
    """Patch the three loaders; returns a dict the test fills in."""
    data = {"unit": pd.DataFrame(), "mode": pd.DataFrame(), "legacy": pd.DataFrame()}
    monkeypatch.setattr(predictive_v2, "load_unit_failure_analisis", lambda c, comp: data["unit"])
    monkeypatch.setattr(
        predictive_v2,
        "get_unit_mode_failure_analisis",
        lambda c, comp, u: data["mode"][data["mode"]["Unit"] == u] if not data["mode"].empty else pd.DataFrame(),
    )
    monkeypatch.setattr(ev, "load_analisis_inteligente", lambda c: data["legacy"])
    return data


def _resolve(unit="CA-83"):
    return ev._resolve_unit_ai_panel("capstone", "motor", unit)


def test_unit_narrative_wins_over_a_healthy_default_mode_row(tables):
    # Real Capstone case: CA-83 is anormal, but its worst mode scores under
    # FLAG_THRESHOLD so the mode table says "no indications of this mode".
    tables["unit"] = pd.DataFrame([_unit_row()])
    tables["mode"] = pd.DataFrame([_mode_row("healthy_default")])
    panel = _resolve()
    assert panel["diagnostico"] == "Diagnostico de la unidad"
    assert panel["causa_probable"] == "Causa de la unidad"


def test_normal_unit_without_unit_narrative_gets_the_healthy_message(tables):
    tables["unit"] = pd.DataFrame([_unit_row(estado="normal", fuente="omitida", diagnostico=None)])
    tables["mode"] = pd.DataFrame([_mode_row("healthy_default")])
    assert _resolve()["diagnostico"] == HEALTHY_TEXT


def test_omitida_unit_with_a_flagged_mode_uses_the_mode_row(tables):
    tables["unit"] = pd.DataFrame([_unit_row(estado="alerta", fuente="omitida", diagnostico=None)])
    tables["mode"] = pd.DataFrame([_mode_row("ok")])
    assert _resolve()["diagnostico"] == "Diagnostico del modo"


def test_omitida_non_normal_unit_never_shows_the_healthy_message(tables):
    tables["unit"] = pd.DataFrame([_unit_row(estado="anormal", fuente="omitida", diagnostico=None)])
    tables["mode"] = pd.DataFrame([_mode_row("healthy_default")])
    assert _resolve() == {"diagnostico": None, "causa_probable": None, "acciones": None}


def test_mode_fallback_rules_status_changes_the_header(tables):
    tables["unit"] = pd.DataFrame([_unit_row(fuente="omitida", diagnostico=None)])
    tables["mode"] = pd.DataFrame([_mode_row("fallback_rules")])
    assert "reglas" in _resolve()["header_text"].lower()


def test_mode_error_status_never_leaks_the_stored_text(tables):
    tables["unit"] = pd.DataFrame([_unit_row(fuente="omitida", diagnostico=None)])
    tables["mode"] = pd.DataFrame([_mode_row("error", probable_cause="BadRequestError: boom")])
    panel = _resolve()
    assert "BadRequestError" not in str(panel)
    assert panel["diagnostico"] is None and panel["acciones"] is None


def test_duplicate_unit_rows_resolve_to_one_narrative(tables):
    # Local Capstone snapshot repeats each unit's row 3x with the same Fecha.
    tables["unit"] = pd.DataFrame([_unit_row()] * 3)
    assert _resolve()["diagnostico"] == "Diagnostico de la unidad"


def test_legacy_flat_file_is_used_when_the_new_table_is_absent(tables):
    tables["legacy"] = pd.DataFrame([_unit_row(diagnostico="Diagnostico legacy")])
    assert _resolve()["diagnostico"] == "Diagnostico legacy"


def test_nothing_on_file_renders_the_empty_panel_kwargs(tables):
    assert _resolve() == {"diagnostico": None, "causa_probable": None, "acciones": None}
    assert ev._resolve_unit_ai_panel(None, "motor", "CA-83") == {
        "diagnostico": None, "causa_probable": None, "acciones": None,
    }
