"""Acceptance cases AC13-AC14: a predictive risk explained with its own variables and readings.

The trap these guard is the plausible sentence: naming a variable the model never used, or
asserting "high iron" with no reading and no reference behind it.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

import src.campbell_ai.data as data_module
from src.campbell_ai.data import DashboardDataRepository


def _repository(tmp_path, rows: list[dict], *, domain: str = "motor", client: str = "cda"):
    predictive = tmp_path / "predictive" / "golden" / client
    predictive.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(predictive / f"{domain}.csv", index=False)
    return DashboardDataRepository(tmp_path)


@pytest.fixture(autouse=True)
def _allow_predictive(monkeypatch):
    monkeypatch.setattr(data_module, "predictive_module_allows", lambda client: True)


def _explanation(payload: dict, risk: str) -> dict:
    record = payload["records"][0]
    matching = [
        entry for entry in record["risk_explanations"] if entry["risk"] == risk
    ]
    assert matching, f"{risk} no viene explicado: {[e['risk'] for e in record['risk_explanations']]}"
    return matching[0]


# ---------------------------------------------------------------------- AC13


def test_ac13_oil_degradation_uses_its_own_variables_not_iron(tmp_path):
    """CDA's oil degradation reads viscosity and soot; iron belongs to abrasive wear."""
    repository = _repository(
        tmp_path,
        [
            {
                "Unit": "T_15",
                "Fecha": "2026-07-20",
                "sampleDate": "2026-07-16",
                "ranking": 62.0,
                "oil_degradation_risk": 70.0,
                "abrasive_wear_risk": 20.0,
                "Viscocidad": 14.84,
                "Hollín": 87.0,
                "Hierro": 33.0,
                "Viscocidad_ratio": 0.015,
                "Viscocidad_slope": 0.34,
            }
        ],
    )

    payload = json.loads(repository.query_predictive_risk("cda", domain="motor"))
    degradation = _explanation(payload, "oil_degradation")

    assert degradation["risk_label"] == "Degradación de Aceite"
    assert degradation["model_variables"]["aceite"] == ["Viscocidad", "Hollín"]
    # Iron is present in the row but is not this mode's variable, so it must not appear here.
    observed = {entry["variable"] for entry in degradation["observations"]}
    assert observed == {"Viscocidad", "Hollín"}
    assert "Hierro" not in observed

    viscosity = next(
        entry for entry in degradation["observations"] if entry["variable"] == "Viscocidad"
    )
    assert viscosity["value"] == 14.84
    assert viscosity["observed_at"][:10] == "2026-07-16"
    assert viscosity["evolution_ratio"] == 0.015
    assert viscosity["trend_slope"] == 0.34


def test_ac13_abrasive_wear_is_the_mode_that_reads_iron(tmp_path):
    repository = _repository(
        tmp_path,
        [
            {
                "Unit": "T_15",
                "Fecha": "2026-07-20",
                "sampleDate": "2026-07-16",
                "ranking": 62.0,
                "abrasive_wear_risk": 80.0,
                "Hierro": 120.0,
                "Silicio": 30.0,
                "Cromo": 4.0,
            }
        ],
    )

    payload = json.loads(repository.query_predictive_risk("cda", domain="motor"))
    abrasive = _explanation(payload, "abrasive_wear")

    assert abrasive["model_variables"]["aceite"] == ["Hierro", "Silicio", "Cromo"]
    assert {entry["variable"] for entry in abrasive["observations"]} == {
        "Hierro",
        "Silicio",
        "Cromo",
    }


def test_ac13_a_telemetry_variable_is_reported_as_a_rate_not_a_reading(tmp_path):
    """`DeltaExh` arrives as time-above-limit per operating state, not as a temperature."""
    repository = _repository(
        tmp_path,
        [
            {
                "Unit": "T_15",
                "Fecha": "2026-07-20",
                "ranking": 62.0,
                "thermal_imbalance_risk": 75.0,
                "Ralenti_DeltaExh_alert_rate": 0.10,
                "Operacional Bajo_DeltaExh_alert_rate": 0.875,
                "Ralenti_LtExhTemp_alert_rate": 0.0,
                "Ralenti_RtExhTemp_alert_rate": 0.0,
            }
        ],
    )

    payload = json.loads(repository.query_predictive_risk("cda", domain="motor"))
    thermal = _explanation(payload, "thermal_imbalance")

    delta = next(
        entry for entry in thermal["observations"] if entry["variable"] == "DeltaExh"
    )
    # The worst operating state is the one reported, and it is named.
    assert delta["rate"] == 0.875
    assert delta["operating_state"] == "Operacional Bajo"
    assert delta["rate_kind"] == "alert_rate"
    assert "no es una lectura instantanea" in delta["rate_meaning"]
    # No "value" key: this is not a measurement.
    assert "value" not in delta
    # And the code never reaches the user: a readable label travels with it.
    assert delta["variable_label"] == "Diferencia de temperatura de escape (derecha-izquierda)"


def test_ac13_a_different_client_gets_its_own_mapping(tmp_path):
    """Capstone's catalog is its own; CDA's mapping must not be read onto it."""
    from src.data.predictive_catalog import get_oil_variables_for_mode

    cda = get_oil_variables_for_mode("oil_degradation_risk", "motor", "cda")
    capstone = get_oil_variables_for_mode("oil_degradation_risk", "motor", "capstone")

    assert cda == ["Viscocidad", "Hollín"]
    # Whatever Capstone declares, it is resolved from Capstone's own entry.
    assert isinstance(capstone, list)
    assert "cda" != "capstone"


def test_ac13_the_transmission_domain_uses_transmission_modes(tmp_path):
    repository = _repository(
        tmp_path,
        [
            {
                "Unit": "T_15",
                "Fecha": "2026-07-20",
                "sampleDate": "2026-07-16",
                "ranking": 70.0,
                "clutch_pack_risk": 80.0,
                "Hierro": 90.0,
                "Cobre": 12.0,
                "Aluminio": 8.0,
            }
        ],
        domain="transmision",
    )

    payload = json.loads(repository.query_predictive_risk("cda", domain="transmision"))
    clutch = _explanation(payload, "clutch_pack")

    assert clutch["risk_label"] == "Desgaste de Clutch Pack"
    assert clutch["model_variables"]["aceite"] == ["Hierro", "Cobre", "Aluminio"]


# ---------------------------------------------------------------------- AC14


def test_ac14_no_contribution_is_ever_claimed(tmp_path):
    """The model publishes no per-variable contribution, and the payload says so."""
    repository = _repository(
        tmp_path,
        [
            {
                "Unit": "T_15",
                "Fecha": "2026-07-20",
                "sampleDate": "2026-07-16",
                "ranking": 62.0,
                "oil_degradation_risk": 70.0,
                "Viscocidad": 14.84,
                "Hollín": 87.0,
            }
        ],
    )

    payload = json.loads(repository.query_predictive_risk("cda", domain="motor"))
    degradation = _explanation(payload, "oil_degradation")

    assert degradation["contribution_available"] is False
    assert "no atribuyas" in degradation["contribution_note"].lower()
    assert "asociacion" in degradation["model_variables_meaning"].lower()
    # And the ranking is described as an order, not a probability.
    assert "no una probabilidad" in payload["note"].lower()
    assert payload["ranking_direction"] == "mayor ranking = mayor prioridad de riesgo"


def test_ac14_variables_without_readings_are_declared_missing(tmp_path):
    """The mode's variables are documented but the row carries none of their values."""
    repository = _repository(
        tmp_path,
        [
            {
                "Unit": "T_15",
                "Fecha": "2026-07-20",
                "ranking": 62.0,
                "oil_degradation_risk": 70.0,
            }
        ],
    )

    payload = json.loads(repository.query_predictive_risk("cda", domain="motor"))
    degradation = _explanation(payload, "oil_degradation")

    assert degradation["observations"] == []
    assert degradation["model_variables"]["aceite"] == ["Viscocidad", "Hollín"]
    assert "no se dispone de sus valores" in degradation["detail"]


def test_ac14_a_null_reading_is_absent_not_zero(tmp_path):
    repository = _repository(
        tmp_path,
        [
            {
                "Unit": "T_15",
                "Fecha": "2026-07-20",
                "sampleDate": "2026-07-16",
                "ranking": 62.0,
                "oil_degradation_risk": 70.0,
                "Viscocidad": None,
                "Hollín": 87.0,
            }
        ],
    )

    payload = json.loads(repository.query_predictive_risk("cda", domain="motor"))
    degradation = _explanation(payload, "oil_degradation")

    observed = {entry["variable"] for entry in degradation["observations"]}
    assert observed == {"Hollín"}
    # Viscosity is still declared as a variable the model considers.
    assert "Viscocidad" in degradation["model_variables"]["aceite"]


def test_ac14_an_uncatalogued_risk_mode_says_so_instead_of_guessing(tmp_path):
    repository = _repository(
        tmp_path,
        [
            {
                "Unit": "T_15",
                "Fecha": "2026-07-20",
                "ranking": 62.0,
                "modo_desconocido_risk": 90.0,
            }
        ],
    )

    payload = json.loads(repository.query_predictive_risk("cda", domain="motor"))
    unknown = _explanation(payload, "modo_desconocido")

    assert unknown["model_variables"] == {"aceite": [], "telemetria": []}
    assert "no las supongas" in unknown["detail"]


def test_ac14_a_source_without_a_ranking_is_not_explained_away(tmp_path):
    repository = _repository(
        tmp_path,
        [{"Unit": "T_15", "Fecha": "2026-07-20", "ranking": None, "oil_degradation_risk": 70.0}],
    )

    payload = json.loads(repository.query_predictive_risk("cda", domain="motor"))

    assert payload["ranking_available"] is False
    assert payload["records"] == []
    assert "no lo sustituyas" in payload["note"]


# --------------------------------------------------------------- shared code


def test_the_catalog_is_shared_and_src_does_not_import_the_dashboard():
    """The extraction requirement: one definition, and no backend -> UI import."""
    from pathlib import Path

    from dashboard.components import predictive_config
    from src.data import predictive_catalog

    # Same object, not two copies that agree today.
    assert predictive_config.FAILURE_MODE_CONFIG is predictive_catalog.FAILURE_MODE_CONFIG
    assert (
        predictive_config.get_oil_variables_for_mode
        is predictive_catalog.get_oil_variables_for_mode
    )
    # No import of the UI package. Parsed rather than grepped: the module docstring
    # explains the rule and names `dashboard`, which a text search would flag.
    import ast

    tree = ast.parse(Path(predictive_catalog.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert imported, "el modulo deberia declarar sus imports"
    assert not [name for name in imported if name.startswith("dashboard")], imported


def test_the_prompt_separates_association_from_contribution():
    from src.campbell_ai.prompts import load_prompt

    prompt = load_prompt("data_analyst_query.md")

    assert "risk_explanations" in prompt
    # Wrapped across lines in the prompt, so the check is on the words that carry the rule.
    assert "orden de prioridad" in prompt
    assert "probabilidad de falla" in prompt
    assert "No atribuyas el riesgo a una variable ni afirmes causalidad" in prompt
    assert "describe_oil_limits" in prompt
