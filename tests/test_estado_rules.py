"""
config/estado_rules.py: the one place that decides a technique's and a unit's Estado
(documentation/general/estado_rule.md).

Covers the rule itself, that Mantención never contributes, that the plain-language text
about stale data is derived from the same thresholds, and that changing the rule in that
one place changes Fleet Overview and Unit Detail together.
"""

from datetime import timedelta

import pytest

import config.estado_rules as rules
import dashboard.components.fleet_overview as fo


@pytest.mark.parametrize(
    "label,age,expected,driver",
    [
        ("Normal", "Ok", "Normal", "both"),
        ("Alerta", "Ok", "Alerta", "label"),
        ("Normal", "Atención", "Alerta", "data"),
        ("Normal", "Preocupante", "Anormal", "data"),   # fresh components, stale data
        ("Alerta", "Preocupante", "Anormal", "data"),   # T_10: 4 components in Alerta, stale
        ("Anormal", "Ok", "Anormal", "label"),
        ("Crítico", "Ok", "Anormal", "label"),          # Alertas' synonym
        ("Alerta", "Sin Datos", "Alerta", "label"),     # age unknown: the technique's own status
        ("Sin Datos", "Preocupante", "Sin Datos", "none"),
        ("InsufficientData", "Ok", "Sin Datos", "none"),
        (None, "Ok", "Sin Datos", "none"),
    ],
)
def test_technique_estado(label, age, expected, driver):
    resolution = rules.technique_estado(label, age)
    assert (resolution.value, resolution.driver) == (expected, driver)


def test_the_technique_score_is_dropped_once_stale_data_decides():
    assert rules.technique_estado("Alerta", "Ok").label_kept
    assert not rules.technique_estado("Alerta", "Preocupante").label_kept


def test_unit_estado_is_the_worst_technique():
    assert rules.unit_estado({"alerts": "Normal", "oil": "Alerta", "predictive": "Anormal"}) == ("Anormal", 3, 2)
    assert rules.unit_estado({"alerts": "Normal", "oil": "Normal"}) == ("Normal", 1, 0)


def test_unit_estado_with_no_reading_is_sin_datos_never_normal():
    assert rules.unit_estado({"alerts": "Sin Datos", "oil": "Sin Datos"})[0] == "Sin Datos"
    assert rules.unit_estado({})[0] == "Sin Datos"


def test_maintenance_never_contributes_to_the_unit_estado():
    assert "maintenance" in rules.NO_STATUS_TECHNIQUES
    assert rules.unit_estado({"alerts": "Normal", "maintenance": "Anormal"}) == ("Normal", 1, 0)
    assert rules.unit_estado({"maintenance": "Anormal"})[0] == "Sin Datos"


def test_staleness_text_is_derived_from_the_thresholds():
    # Telemetria: Ok under 2 h, Atención under 24 h, Preocupante from there.
    assert rules.staleness_floor_limits("Telemetria") == {"Alerta": timedelta(hours=2), "Anormal": timedelta(hours=24)}
    assert rules.staleness_floor_limits("Tribologia") == {"Alerta": timedelta(days=20), "Anormal": timedelta(days=40)}
    assert rules.staleness_floor_limits("Desconocida") == {}


def test_staleness_floor_limits_follow_the_rule(monkeypatch):
    """If Atención no longer forces Alerta, no text may claim that it does."""
    monkeypatch.setattr(rules, "STALENESS_FLOOR", {"Ok": "Normal", "Atención": "Normal", "Preocupante": "Anormal"})
    assert rules.staleness_floor_limits("Telemetria") == {"Anormal": timedelta(hours=24)}


def test_changing_the_rule_in_one_place_moves_every_screen(monkeypatch):
    """Fleet Overview's cell, the unit's Estado and Unit Detail's snapshot all come from
    `technique_estado`: loosening STALENESS_FLOOR is the only edit needed."""
    from tests.test_fleet_overview import _patch_all_sources

    def estados():
        _patch_all_sources(
            monkeypatch, enabled={"monitoring-alerts": True},
            alerts=({"U1": "Normal"}, {}, "Preocupante", "25 días"),
        )
        snapshot = fo.get_unit_snapshot("TESTCO", "U1")
        return snapshot["technique_status"]["alerts"], snapshot["overall_status"]

    assert estados() == ("Anormal", "Anormal")
    monkeypatch.setattr(rules, "STALENESS_FLOOR", {"Ok": "Normal", "Atención": "Alerta", "Preocupante": "Alerta"})
    assert estados() == ("Alerta", "Alerta")
