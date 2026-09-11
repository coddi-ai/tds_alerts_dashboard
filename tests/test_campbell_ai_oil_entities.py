"""Acceptance cases AC03-AC09: equipment / component / sample contract and latest-sample pick.

Fixtures are synthetic and dated relative to today, so a case cannot start failing because
the calendar moved past a hardcoded date. Expected values are written out by hand rather than
derived from the function under test.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.campbell_ai.chart_registry import DashboardChartRegistry
from src.campbell_ai.data import DashboardDataRepository
from src.campbell_ai.errors import CampbellDataError
from src.campbell_ai.oil_entities import (
    LEVEL_COMPONENT,
    LEVEL_MACHINE,
    SCOPE_HISTORY,
    SCOPE_LATEST,
    SCOPE_LATEST_IN_PERIOD,
    latest_sample_per_component,
)
from src.campbell_ai.visualization import DashboardVisualizationService


def _days_ago(days: int) -> str:
    return (pd.Timestamp.today().normalize() - pd.Timedelta(days=days)).isoformat()


def _sample(
    unit: str,
    component: str,
    days: int,
    status: str,
    *,
    sample_number: str,
    severity: int = 0,
    iron: float = 10.0,
    normalized: str | None = None,
) -> dict:
    return {
        "unitId": unit,
        "sampleNumber": sample_number,
        "componentName": component,
        "componentNameNormalized": component if normalized is None else normalized,
        "report_status": status,
        "sampleDate": _days_ago(days),
        "severity_score": severity,
        "oilHourRange": "LT_1000",
        "limit_source": "oil_hour_stratified",
        "Hierro": iron,
    }


def _repository(tmp_path, rows: list[dict], machine_rows: list[dict] | None = None):
    oil = tmp_path / "oil" / "golden" / "cda"
    oil.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(oil / "classified.parquet", index=False)
    if machine_rows is not None:
        pd.DataFrame(machine_rows).to_parquet(oil / "machine_status.parquet", index=False)
    return DashboardDataRepository(tmp_path)


# --------------------------------------------------------------- AC03 / AC04


def test_ac03_the_latest_sample_is_returned_even_past_sixty_days(tmp_path):
    """A component sampled 200 days ago still has a current condition."""
    repository = _repository(
        tmp_path,
        [_sample("T_9", "motor", 200, "Alerta", sample_number="S-1", severity=9)],
    )

    payload = json.loads(repository.query_oil_components("CDA"))

    assert payload["total_rows"] == 1
    assert payload["scope"] == SCOPE_LATEST
    assert payload["scope_detail"]["level"] == LEVEL_COMPONENT
    # The date is reported rather than the sample being dropped by a window.
    assert payload["records"][0]["sampleDate"][:10] == _days_ago(200)[:10]
    assert payload["scope_detail"]["newest"][:10] == _days_ago(200)[:10]


def test_ac04_a_recent_normal_sample_wins_over_an_old_abnormal_one(tmp_path):
    """Filtering condition before selecting the sample used to resurface the old one."""
    repository = _repository(
        tmp_path,
        [
            _sample("T_9", "motor", 400, "Anormal", sample_number="S-old", severity=30),
            _sample("T_9", "motor", 5, "Normal", sample_number="S-new", severity=1),
        ],
    )

    current = json.loads(repository.query_oil_components("CDA"))

    assert current["total_rows"] == 1
    assert current["records"][0]["sampleNumber"] == "S-new"
    assert current["records"][0]["report_status"] == "Normal"

    # Asking for the abnormal ones must not rescue the superseded sample: the component's
    # current condition is Normal, so the abnormal filter has nothing to return.
    abnormal = json.loads(repository.query_oil_components("CDA", status="Anormal"))
    assert abnormal["total_rows"] == 0
    assert "no hay componentes en esa condicion" in abnormal["filter_hints"]["detail"].lower()

    # The history scope is where the old sample is still visible.
    history = json.loads(repository.query_oil_components("CDA", latest_only=False))
    assert history["scope"] == SCOPE_HISTORY
    assert history["total_rows"] == 2


# ---------------------------------------------------------------------- AC05


def test_ac05_same_day_samples_break_ties_deterministically(tmp_path):
    """Two samples on one date are real; the winner must not depend on row order."""
    rows = [
        _sample("T_9", "motor", 10, "Normal", sample_number="S-1"),
        _sample("T_9", "motor", 10, "Anormal", sample_number="S-2", severity=20),
    ]
    forward = json.loads(_repository(tmp_path, rows).query_oil_components("CDA"))

    reversed_path = tmp_path / "reversed"
    backward = json.loads(
        _repository(reversed_path, list(reversed(rows))).query_oil_components("CDA")
    )

    assert forward["total_rows"] == 1
    # The higher sample number wins in both orders, so repeating the question is stable.
    assert forward["records"][0]["sampleNumber"] == "S-2"
    assert backward["records"][0]["sampleNumber"] == "S-2"


def test_ac05_an_invalid_date_never_outranks_a_real_one(tmp_path):
    """`sort_values` puts NaT last, which used to elect the undated row as the newest."""
    rows = [
        _sample("T_9", "motor", 30, "Normal", sample_number="S-dated"),
        _sample("T_9", "motor", 30, "Anormal", sample_number="S-undated", severity=40),
    ]
    rows[1]["sampleDate"] = "no es una fecha"
    repository = _repository(tmp_path, rows)

    payload = json.loads(repository.query_oil_components("CDA"))

    assert payload["total_rows"] == 1
    assert payload["records"][0]["sampleNumber"] == "S-dated"


def test_ac05_a_group_with_only_undated_samples_still_reports_one(tmp_path):
    """An undated sample is not a valid date, but it is the only thing there is."""
    rows = [_sample("T_9", "motor", 10, "Normal", sample_number="S-1")]
    rows[0]["sampleDate"] = None
    repository = _repository(tmp_path, rows)

    payload = json.loads(repository.query_oil_components("CDA"))

    assert payload["total_rows"] == 1
    assert payload["scope_detail"]["samples_without_date"] == 1
    # No date range is claimed for a sample that has no usable date.
    assert "newest" not in payload["scope_detail"]


def test_ac05_all_essays_of_the_selected_sample_stay_together(tmp_path):
    """One row is one sample and the essays are its columns, so nothing is split off."""
    rows = [
        _sample("T_9", "motor", 5, "Alerta", sample_number="S-new", iron=88.0),
        _sample("T_9", "motor", 90, "Normal", sample_number="S-old", iron=12.0),
    ]
    frame = pd.DataFrame(rows)

    selected = latest_sample_per_component(
        frame,
        unit_col="unitId",
        component_col="componentNameNormalized",
        date_col="sampleDate",
        sample_id_col="sampleNumber",
    )

    assert list(selected["sampleNumber"]) == ["S-new"]
    assert list(selected["Hierro"]) == [88.0]


# ---------------------------------------------------------------------- AC06


def test_ac06_an_explicit_period_is_honoured_in_both_scopes(tmp_path):
    """"The latest sample within a period" and "the history of a period" differ."""
    repository = _repository(
        tmp_path,
        [
            _sample("T_9", "motor", 5, "Normal", sample_number="S-now"),
            _sample("T_9", "motor", 40, "Alerta", sample_number="S-mid", severity=9),
            _sample("T_9", "motor", 50, "Anormal", sample_number="S-early", severity=25),
        ],
    )
    start, end = _days_ago(60)[:10], _days_ago(30)[:10]

    latest_in_period = json.loads(
        repository.query_oil_components("CDA", start_date=start, end_date=end)
    )
    history_of_period = json.loads(
        repository.query_oil_components(
            "CDA", latest_only=False, start_date=start, end_date=end
        )
    )

    # Newest sample inside the window, not the newest overall and not the whole window.
    assert latest_in_period["total_rows"] == 1
    assert latest_in_period["records"][0]["sampleNumber"] == "S-mid"
    assert latest_in_period["requested_period"]["mode"] == "explicit"

    assert history_of_period["total_rows"] == 2
    assert {record["sampleNumber"] for record in history_of_period["records"]} == {
        "S-mid",
        "S-early",
    }


# ---------------------------------------------------------------------- AC07


def _parity_rows() -> list[dict]:
    return [
        # Two samples for one component: only the newest may be counted.
        _sample("T_9", "motor", 5, "Normal", sample_number="S-1"),
        _sample("T_9", "motor", 120, "Anormal", sample_number="S-0", severity=30),
        # Outside any 60-day window, so a windowed path would lose it entirely.
        _sample("T_9", "transmision", 300, "Alerta", sample_number="S-2", severity=9),
        _sample("T_15", "motor", 20, "Anormal", sample_number="S-3", severity=28),
    ]


def test_ac07_text_registered_chart_and_ad_hoc_chart_share_one_population(tmp_path):
    repository = _repository(tmp_path, _parity_rows())

    payload = json.loads(repository.query_oil_components("CDA"))
    registered = DashboardChartRegistry(repository).render("cda", "oil_component_status")
    ad_hoc = DashboardVisualizationService(repository).create_chart(
        client="cda", dataset="oil_components", chart_type="bar", dimension="status"
    )

    expected = {"Normal": 1, "Alerta": 1, "Anormal": 1}
    assert payload["total_rows"] == 3
    assert payload["by_status"] == expected
    assert registered.summary["by_status"] == expected
    assert ad_hoc.summary["sample_scope"] == SCOPE_LATEST
    assert sum(ad_hoc.summary["top"].values()) == 3
    # The subtitle states the selection rule instead of claiming a period.
    assert "Muestra más reciente" in ad_hoc.description


def test_ac07_a_time_dimension_still_gets_the_history_scope(tmp_path):
    """The same source answers trends; asking for one must not collapse to one sample."""
    repository = _repository(tmp_path, _parity_rows())

    trend = DashboardVisualizationService(repository).create_chart(
        client="cda",
        dataset="oil_components",
        chart_type="line",
        dimension="day",
        metric="hierro",
        aggregation="mean",
        days=3650,
    )

    assert trend.summary["sample_scope"] == SCOPE_HISTORY
    assert sum(trend.summary["top"].values()) > 0


# --------------------------------------------------------------- AC08 / AC09


def test_ac08_the_machine_aggregate_is_never_presented_as_a_sample(tmp_path):
    """The reported failure: a transmission sample answered as the engine's result."""
    repository = _repository(
        tmp_path,
        [
            _sample("T_9", "motor", 10, "Normal", sample_number="S-motor"),
            _sample("T_9", "transmision", 3, "Anormal", sample_number="S-trans", severity=30),
        ],
        machine_rows=[
            {
                "unit_id": "T_9",
                "overall_status": "Anormal",
                "latest_sample_date": _days_ago(3),
                "machine_score": 30,
                "priority_score": 30,
                "components_alerta": 0,
                "components_anormal": 1,
                "component_details": json.dumps(
                    [
                        {
                            "component": "transmision",
                            "status": "Anormal",
                            "severity_score": 30,
                            "weight": 0.5,
                            "sample_date": _days_ago(3),
                        },
                        {
                            "component": "motor",
                            "status": "Normal",
                            "severity_score": 1,
                            "weight": 0.5,
                            "sample_date": _days_ago(10),
                        },
                    ]
                ),
            }
        ],
    )

    machine = json.loads(repository.query_oil_status("CDA"))
    components = json.loads(repository.query_oil_components("CDA", unit_id="T_9"))

    # Three levels stay distinct: the machine is Anormal, the engine sample is Normal.
    assert machine["level"] == LEVEL_MACHINE
    assert machine["records"][0]["overall_status"] == "Anormal"
    assert "agregado" in machine["aggregation"].lower()
    assert components["scope_detail"]["level"] == LEVEL_COMPONENT

    engine = [
        record
        for record in components["records"]
        if record["componentNameNormalized"] == "motor"
    ]
    assert len(engine) == 1
    assert engine[0]["report_status"] == "Normal"
    assert engine[0]["sampleNumber"] == "S-motor"

    # The explanation may only attribute the aggregate to components the source published,
    # with the weights it published.
    contributors = machine["records"][0]["contributing_components"]
    assert [entry["component"] for entry in contributors] == ["transmision", "motor"]
    assert {entry["weight"] for entry in contributors} == {0.5}


def test_ac09_component_aliases_do_not_invent_a_second_latest_sample(tmp_path):
    """ENEX stores "bastidor izquierdo" and "bastidor izquierdo " for one position."""
    repository = _repository(
        tmp_path,
        [
            _sample(
                "T_9", "bastidor izquierdo", 60, "Anormal",
                sample_number="S-old", severity=30, normalized="bastidor izquierdo",
            ),
            _sample(
                "T_9", "bastidor izquierdo ", 4, "Normal",
                sample_number="S-new", normalized="bastidor izquierdo ",
            ),
            # A genuinely different position must stay separate.
            _sample(
                "T_9", "bastidor derecho", 4, "Alerta",
                sample_number="S-right", severity=9, normalized="bastidor derecho",
            ),
        ],
    )

    payload = json.loads(repository.query_oil_components("CDA"))

    assert payload["total_rows"] == 2
    assert {record["sampleNumber"] for record in payload["records"]} == {"S-new", "S-right"}


def test_ac09_a_component_without_samples_is_reported_as_missing_data(tmp_path):
    repository = _repository(
        tmp_path, [_sample("T_9", "motor", 10, "Normal", sample_number="S-1")]
    )

    payload = json.loads(repository.query_oil_components("CDA", component="mando final"))

    assert payload["total_rows"] == 0
    hints = payload["filter_hints"]
    assert hints["available_components"] == ["motor"]
    assert "no equivale a condicion normal" in hints["detail"].lower()


def test_an_unknown_unit_is_missing_data_not_a_normal_condition(tmp_path):
    repository = _repository(
        tmp_path, [_sample("T_9", "motor", 10, "Normal", sample_number="S-1")]
    )

    payload = json.loads(repository.query_oil_components("CDA", unit_id="T_404"))

    assert payload["total_rows"] == 0
    assert "no tiene muestras" in payload["filter_hints"]["detail"].lower()


def test_the_shared_glossary_reaches_the_agents_that_reason_about_levels():
    """C04/C07 wording must be one file, not five copies that drift."""
    from src.campbell_ai.prompts import load_prompt

    glossary = load_prompt("oil_entity_levels.md")

    for token in ("Equipo", "Componente", "Muestra", "agregado", "sampleNumber"):
        assert token in glossary, token
    query_prompt = load_prompt("data_analyst_query.md")
    assert "estado agregado" in query_prompt
    # The stale wording that described the machine aggregate as a sample is gone.
    assert "fila por equipo con su muestra de aceite más reciente" not in query_prompt


@pytest.mark.parametrize("scope_getter", [lambda p: p["scope_detail"]["selection"]])
def test_every_oil_payload_declares_its_own_scope(tmp_path, scope_getter):
    repository = _repository(
        tmp_path, [_sample("T_9", "motor", 10, "Normal", sample_number="S-1")]
    )

    latest = json.loads(repository.query_oil_components("CDA"))
    history = json.loads(repository.query_oil_components("CDA", latest_only=False))

    assert "sin ventana temporal implicita" in scope_getter(latest)
    assert "historico" in scope_getter(history).lower()


# -------------------------------------- H02: one scope vocabulary in every route


def _scope_rows() -> list[dict]:
    return [
        _sample("T_9", "motor", 5, "Normal", sample_number="S-now"),
        _sample("T_9", "motor", 40, "Alerta", sample_number="S-mid", severity=9),
        _sample("T_9", "motor", 50, "Anormal", sample_number="S-early", severity=25),
        # Sampled once, long ago: its current condition, and outside any recent window.
        _sample("T_9", "transmision", 200, "Alerta", sample_number="S-trans", severity=9),
    ]


def _chart(repository, **kwargs):
    return DashboardVisualizationService(repository).create_chart(
        client="cda", dataset="oil_components", chart_type="bar", dimension="status", **kwargs
    )


def test_h02_a_relative_window_is_a_period_and_is_actually_applied(tmp_path):
    """`days` was never consulted when choosing the scope, so the window was ignored.

    A 30-day chart therefore still included a sample from 200 days earlier.
    """
    repository = _repository(tmp_path, _scope_rows())

    artifact = _chart(repository, days=30)

    assert artifact.summary["sample_scope"] == SCOPE_HISTORY
    assert sum(artifact.summary["top"].values()) == 1
    # Only the sample inside the window survives; the old transmission is out.
    assert artifact.summary["top"] == {"Normal": 1}


def test_h02_the_latest_in_period_scope_matches_the_query_tool(tmp_path):
    repository = _repository(tmp_path, _scope_rows())
    start, end = _days_ago(60)[:10], _days_ago(30)[:10]

    payload = json.loads(
        repository.query_oil_components("CDA", start_date=start, end_date=end)
    )
    artifact = _chart(
        repository, start_date=start, end_date=end, scope=SCOPE_LATEST_IN_PERIOD
    )

    assert payload["scope"] == SCOPE_LATEST_IN_PERIOD
    assert artifact.summary["sample_scope"] == SCOPE_LATEST_IN_PERIOD
    # The newest sample inside the window, in both routes: one, and the same one.
    assert payload["total_rows"] == sum(artifact.summary["top"].values()) == 1
    assert payload["records"][0]["sampleNumber"] == "S-mid"
    assert artifact.summary["top"] == {"Alerta": 1}
    # The subtitle states the rule and the period rather than implying either.
    assert "dentro del periodo" in artifact.description


def test_h02_the_history_scope_matches_the_query_tool(tmp_path):
    repository = _repository(tmp_path, _scope_rows())
    start, end = _days_ago(60)[:10], _days_ago(30)[:10]

    payload = json.loads(
        repository.query_oil_components(
            "CDA", latest_only=False, start_date=start, end_date=end
        )
    )
    artifact = _chart(repository, start_date=start, end_date=end, scope=SCOPE_HISTORY)

    assert payload["scope"] == SCOPE_HISTORY
    assert payload["total_rows"] == sum(artifact.summary["top"].values()) == 2


def test_h02_current_condition_survives_the_change(tmp_path):
    """AC03 must not regress: with no period asked, an old sample is still current."""
    repository = _repository(tmp_path, _scope_rows())

    payload = json.loads(repository.query_oil_components("CDA"))
    artifact = _chart(repository)

    assert payload["scope"] == SCOPE_LATEST
    assert artifact.summary["sample_scope"] == SCOPE_LATEST
    assert payload["total_rows"] == sum(artifact.summary["top"].values()) == 2
    # The 200-day transmission is that component's current condition and stays.
    assert artifact.summary["top"] == {"Alerta": 1, "Normal": 1}


def test_h02_an_unknown_scope_is_rejected_rather_than_guessed(tmp_path):
    repository = _repository(tmp_path, _scope_rows())

    with pytest.raises(CampbellDataError) as failure:
        _chart(repository, scope="lo_que_sea")

    assert "Alcance no permitido" in str(failure.value)


def test_h02_latest_in_period_without_a_period_is_rejected(tmp_path):
    repository = _repository(tmp_path, _scope_rows())

    with pytest.raises(CampbellDataError) as failure:
        _chart(repository, scope=SCOPE_LATEST_IN_PERIOD)

    assert "requiere un periodo" in str(failure.value)


def test_h02_a_non_oil_source_keeps_its_sixty_day_default(tmp_path):
    """`days=0` must not become "no window" for sources that always had one."""
    alerts = tmp_path / "alerts" / "golden" / "cda"
    alerts.mkdir(parents=True)
    pd.DataFrame(
        [
            {"UnitId": "T_9", "Timestamp": _days_ago(5), "sistema": "Motor"},
            {"UnitId": "T_9", "Timestamp": _days_ago(400), "sistema": "Motor"},
        ]
    ).to_csv(alerts / "consolidated_alerts.csv", index=False)
    repository = DashboardDataRepository(tmp_path)

    artifact = DashboardVisualizationService(repository).create_chart(
        client="cda", dataset="alerts", chart_type="bar", dimension="system"
    )

    # The 400-day-old alert is outside the default window, as it always was.
    assert sum(artifact.summary["top"].values()) == 1
