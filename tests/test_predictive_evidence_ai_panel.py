"""Predictivo -> Componente -> Evidencia: source of the unit-level Analisis Inteligente panel.

Diagnóstico / Causa probable / Acciones come from `unit_failure_analisis` (`diagnostico`,
`causa_probable`, `acciones`) and from nothing else - no `mode_failure_analisis` row and no
legacy flat file ever stands in for it - read from the same (year, week) run as `risk_scores`."""
import pandas as pd
import pytest

from dashboard.tabs import tab_predictive_evidence as ev
from src.data import predictive_v2

EMPTY = {"diagnostico": None, "causa_probable": None, "acciones": None}
RUN = (2026, 45)


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


@pytest.fixture
def tables(monkeypatch):
    """Patch the readers; `data["reads"]` records every (client, component, run) asked of
    `unit_failure_analisis`, and the table is only served for exactly RUN."""
    data = {"unit": pd.DataFrame(), "run": RUN, "reads": []}

    def load(client, component, run=None):
        data["reads"].append((client, component, run))
        return data["unit"] if run == RUN else pd.DataFrame()

    monkeypatch.setattr(predictive_v2, "load_unit_failure_analisis", load)
    monkeypatch.setattr(predictive_v2, "latest_risk_scores_run", lambda c, comp: data["run"])
    return data


def _resolve(unit="CA-83"):
    return ev._resolve_unit_ai_panel("capstone", "motor", unit)


def test_the_three_segments_come_from_the_three_unit_failure_analisis_columns(tables):
    tables["unit"] = pd.DataFrame([_unit_row()])
    panel = _resolve()
    assert panel["diagnostico"] == "Diagnostico de la unidad"
    assert panel["causa_probable"] == "Causa de la unidad"
    assert panel["acciones"] == '["Inmediato: revisar"]'


def test_narrative_is_read_from_the_same_run_as_the_risk_scores(tables):
    tables["unit"] = pd.DataFrame([_unit_row()])
    _resolve()
    assert tables["reads"] == [("capstone", "motor", RUN)]


def test_a_run_without_the_narrative_table_shows_the_empty_panel_not_an_older_run(tables):
    tables["unit"] = pd.DataFrame([_unit_row()])
    tables["run"] = (2026, 46)  # risk_scores is a newer run than the narrative
    assert _resolve() == EMPTY


def test_component_without_risk_scores_shows_the_empty_panel(tables):
    tables["unit"] = pd.DataFrame([_unit_row()])
    tables["run"] = None
    assert _resolve() == EMPTY


def test_omitida_unit_shows_the_empty_panel(tables):
    tables["unit"] = pd.DataFrame([_unit_row(estado="normal", fuente="omitida")])
    assert _resolve() == EMPTY


def test_null_or_blank_narrative_shows_the_empty_panel(tables):
    tables["unit"] = pd.DataFrame([_unit_row(diagnostico=None, causa_probable="  ", acciones=None)])
    assert _resolve() == EMPTY


def test_unit_absent_from_the_table_shows_the_empty_panel(tables):
    tables["unit"] = pd.DataFrame([_unit_row(unit="CA-90")])
    assert _resolve("CA-83") == EMPTY


def test_duplicate_unit_rows_resolve_to_one_narrative(tables):
    # Local Capstone snapshot repeats each unit's row 3x with the same Fecha.
    tables["unit"] = pd.DataFrame([_unit_row()] * 3)
    assert _resolve()["diagnostico"] == "Diagnostico de la unidad"


def test_most_recent_row_wins(tables):
    tables["unit"] = pd.DataFrame([
        _unit_row(diagnostico="Viejo", Fecha=pd.Timestamp("2026-09-10")),
        _unit_row(diagnostico="Nuevo", Fecha=pd.Timestamp("2026-09-12")),
    ])
    assert _resolve()["diagnostico"] == "Nuevo"


def test_no_client_renders_the_empty_panel_kwargs(tables):
    assert ev._resolve_unit_ai_panel(None, "motor", "CA-83") == EMPTY
    assert tables["reads"] == []


def test_no_fallback_source_is_reachable_from_the_panel():
    # mode_failure_analisis and the deleted analisis_inteligente.parquet must not be readable here.
    for name in ("_mode_narrative_panel", "load_analisis_inteligente"):
        assert not hasattr(ev, name)
    for name in ("load_mode_failure_analisis", "get_unit_mode_failure_analisis"):
        assert not hasattr(predictive_v2, name)


# ── the reader itself: the partition is matched exactly ───────────────────────

def _write_partition(root, year, week, rows):
    folder = root / "unit_failure_analisis" / f"year={year}" / f"week={week}"
    folder.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(folder / "unit_failure_analisis.parquet")


def test_load_unit_failure_analisis_reads_exactly_the_requested_run(tmp_path, monkeypatch):
    monkeypatch.setattr(predictive_v2, "unit_failure_analisis_base_path", lambda c, comp: tmp_path / "unit_failure_analisis")
    _write_partition(tmp_path, 2026, 44, [_unit_row(diagnostico="semana 44")])
    _write_partition(tmp_path, 2026, 45, [_unit_row(diagnostico="semana 45")])

    assert predictive_v2.load_unit_failure_analisis("c", "motor", run=(2026, 44))["diagnostico"].tolist() == ["semana 44"]
    assert predictive_v2.load_unit_failure_analisis("c", "motor", run=(2026, 45))["diagnostico"].tolist() == ["semana 45"]
    assert predictive_v2.load_unit_failure_analisis("c", "motor", run=(2026, 46)).empty
    assert predictive_v2.load_unit_failure_analisis("c", "motor")["diagnostico"].tolist() == ["semana 45"]  # latest


def test_latest_risk_scores_run_is_the_newest_week_numerically(tmp_path, monkeypatch):
    base = tmp_path / "risk_scores"
    for year, week in ((2025, 52), (2026, 9), (2026, 45)):
        (base / f"year={year}" / f"week={week}").mkdir(parents=True)
    monkeypatch.setattr(predictive_v2, "risk_scores_base_path", lambda c, comp: base)
    assert predictive_v2.latest_risk_scores_run("c", "motor") == (2026, 45)  # 45 > 9, not a string sort
    monkeypatch.setattr(predictive_v2, "risk_scores_base_path", lambda c, comp: tmp_path / "absent")
    assert predictive_v2.latest_risk_scores_run("c", "motor") is None
