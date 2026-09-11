"""T06a: the certification battery, checked without calling the provider.

The evaluation that costs money is T06b. Everything that decides whether that run will be
worth anything can be checked for free, and that is what this file does: the cases exist and
are selectable, they are anchored in live data rather than in hardcoded machine codes, a
client that cannot answer a question is reported as *not applicable* instead of passed, and
the evaluator actually rejects the wrong answers it is supposed to reject.

No model is called here.
"""

from __future__ import annotations

import pytest

from tests.quality.expectations import (
    CASE_MAP,
    CASES,
    CERTIFICATION_CASES,
    QualityCase,
    case_applies,
    partition_cases,
    question_placeholders,
    render_question,
)
from tests.quality.runner import evaluate, select_cases


# ------------------------------------------------------------------ the catalogue


def test_the_certification_tags_exist_and_select_exactly_their_cases():
    """The plan's commands are only valid once these tags resolve to real cases."""
    certification = select_cases([], ["certificacion"])
    laboratory = select_cases([], ["laboratorio"])

    assert certification, "el tag certificacion no selecciona ningun caso"
    assert laboratory, "el tag laboratorio no selecciona ningun caso"
    # The tag selects the battery and nothing else.
    assert {case.case_id for case in certification} == {
        case.case_id for case in CERTIFICATION_CASES
    }
    # Laboratory is a subset of it, and every one of those is a C09 case.
    assert {case.case_id for case in laboratory} <= {
        case.case_id for case in CERTIFICATION_CASES
    }
    for case in laboratory:
        assert "c09" in case.tags, case.case_id


def test_every_observation_of_the_plan_has_cases():
    """A certification battery that skips an observation proves nothing about it."""
    tags = {tag for case in CERTIFICATION_CASES for tag in case.tags}

    for observation in ("c02", "c03", "c04", "c05", "c06", "c07", "c08", "c09"):
        assert observation in tags, observation


def test_critical_scenarios_carry_three_formulations():
    """One phrasing passing shows the model answered a sentence, not that it holds a rule."""
    families: dict[str, list[str]] = {}
    for case in CERTIFICATION_CASES:
        if case.case_id[-2:] in {"_a", "_b", "_c"}:
            families.setdefault(case.case_id[:-2], []).append(case.case_id[-1])

    assert families, "no hay escenarios con formulaciones alternativas"
    for family, suffixes in families.items():
        assert sorted(suffixes) == ["a", "b", "c"], (family, suffixes)


def test_case_ids_are_unique_and_reachable():
    ids = [case.case_id for case in CASES]

    assert len(ids) == len(set(ids)), "hay case_id repetidos"
    # The map the runner uses for follow-ups must contain the battery too.
    for case in CERTIFICATION_CASES:
        assert CASE_MAP[case.case_id] is case


def test_every_follow_up_points_at_a_case_that_exists():
    for case in CASES:
        if case.follow_up_of:
            assert case.follow_up_of in CASE_MAP, case.case_id
            assert case.fresh_session is False, case.case_id


def test_the_context_sequence_is_a_real_multi_turn_chain():
    """C05 is about references across turns, so the chain has to be three deep."""
    third = CASE_MAP["cert_context_turn3"]
    second = CASE_MAP[third.follow_up_of]
    first = CASE_MAP[second.follow_up_of]

    assert first.follow_up_of is None
    # The later turns use pronouns on purpose: that is the behaviour being measured.
    assert "ese" in second.question or "esa" in second.question
    assert "esa" in third.question


def test_runner_replays_all_ancestors_in_one_session(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from tests.quality import runner as module

    runner = object.__new__(module.QualityRunner)
    runner.client, runner.username, runner.facts = "test", "tester", object()
    answer = SimpleNamespace(
        response="2026-08-10", request_type="agents", visualizations=[], grounding={}
    )
    runner.service = SimpleNamespace(
        initialize=AsyncMock(return_value=SimpleNamespace(session_id="isolated")),
        send_message=AsyncMock(return_value=answer),
    )
    values = {"sampled_unit": "UNIT-TEST", "sampled_component": "motor",
              "latest_sample_date": "2026-08-10"}
    monkeypatch.setattr(module, "resolve_facts", lambda _, names: {n: values[n] for n in names})

    result = asyncio.run(runner.run_case(CASE_MAP["cert_context_turn3"]))

    calls = runner.service.send_message.call_args_list
    assert len(calls) == 3
    assert "UNIT-TEST" in calls[0].args[3]
    assert calls[1].args[3] == CASE_MAP["cert_context_turn2"].question
    assert calls[2].args[3] == CASE_MAP["cert_context_turn3"].question
    assert {call.args[2] for call in calls} == {"isolated"}
    assert result.passed


def test_question_parameters_are_not_implicit_answer_expectations(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from tests.quality import runner as module

    runner = object.__new__(module.QualityRunner)
    runner.client, runner.username, runner.facts = "test", "tester", object()
    runner.service = SimpleNamespace(
        initialize=AsyncMock(return_value=SimpleNamespace(session_id="isolated")),
        send_message=AsyncMock(return_value=SimpleNamespace(
            response="2026-08-10", request_type="agents", visualizations=[], grounding={}
        )),
    )
    values = {"sampled_unit": "UNIT-TEST", "latest_sample_date": "2026-08-10"}
    monkeypatch.setattr(module, "resolve_facts", lambda _, names: {n: values[n] for n in names})
    case = QualityCase(case_id="date_only", question="Fecha de {sampled_unit}?", why="",
                       must_include_facts=("latest_sample_date",))

    result = asyncio.run(runner.run_case(case))

    assert result.passed, result.failures
    assert runner.service.send_message.call_args.args[3] == "Fecha de UNIT-TEST?"


# --------------------------------------------------------- anchored, not hardcoded


def test_no_case_hardcodes_a_client_identifier():
    """A case pinned to a machine code fails the day that code disappears."""
    import re

    suspicious = re.compile(r"\b(T_\d+|TDZ\d+|CSL\d+|CAEX-\d+)\b")
    for case in CERTIFICATION_CASES:
        assert not suspicious.search(case.question), case.case_id


def test_questions_interpolate_only_resolvable_facts():
    """Every `{placeholder}` must be a real `DataFacts` method."""
    from tests.quality.expectations import DataFacts

    for case in CASES:
        for name in question_placeholders(case.question):
            assert hasattr(DataFacts, name), (case.case_id, name)


def test_a_question_renders_with_the_values_it_was_given():
    case = CASE_MAP["cert_latest_sample_a"]

    rendered = render_question(case, {"sampled_unit": "UNIDAD-9", "sampled_component": "motor"})

    assert "UNIDAD-9" in rendered
    assert "{" not in rendered


@pytest.mark.parametrize("value", ["3580", "3,580", "3.580", "3 580", "3\u00a0580"])
def test_integer_facts_accept_thousands_formatting(value):
    from tests.quality.runner import _matches_fact
    assert _matches_fact(f"Sobre **{value} muestras**.", "3580")


@pytest.mark.parametrize("value", ["13580", "35800", "3580.5", "3580,5", "3,581"])
def test_integer_facts_reject_different_values(value):
    from tests.quality.runner import _matches_fact
    assert not _matches_fact(f"Sobre {value} muestras.", "3580")


@pytest.mark.parametrize("shown,expected,valid", [
    ("8,3", "8.3", True), ("8.30", "8.3", True),
    ("8.31", "8.3", False), ("18.3", "8.3", False),
    ("114", "114.0", True), ("114.0", "114.0", True),
])
def test_decimal_facts_preserve_the_expected_value(shown, expected, valid):
    from tests.quality.runner import _matches_fact
    assert _matches_fact(shown, expected) is valid


def test_an_unresolvable_placeholder_fails_loudly_instead_of_being_sent():
    case = QualityCase(case_id="x", question="¿Y {inexistente}?", why="")

    with pytest.raises(RuntimeError) as failure:
        render_question(case, {})

    assert "inexistente" in str(failure.value)


# ------------------------------------------------------ applicability, not silence


def test_a_case_the_client_cannot_answer_is_not_applicable_rather_than_passed():
    """ENEX has no alerts and no predictive model; running those proves nothing."""
    oil_only = {"oil_fleet", "oil_components", "oil_limits", "oil_lab_kpis"}

    applicable, inapplicable = partition_cases(list(CERTIFICATION_CASES), oil_only)

    assert applicable, "un cliente de solo aceite debe poder responder algo"
    predictive = [case for case, _ in inapplicable if "predictivo" in case.tags]
    assert predictive, "los casos predictivos deben quedar fuera para este cliente"
    for case, reason in inapplicable:
        assert "Capacidad no disponible" in reason, case.case_id
        assert reason.strip().endswith(tuple(case.requires_capabilities)), case.case_id


def test_a_client_with_everything_can_answer_the_whole_battery():
    every = {
        key
        for case in CERTIFICATION_CASES
        for key in case.requires_capabilities
    }

    applicable, inapplicable = partition_cases(list(CERTIFICATION_CASES), every)

    assert not inapplicable
    assert len(applicable) == len(CERTIFICATION_CASES)


def test_case_applies_names_the_capability_that_is_missing():
    case = CASE_MAP["cert_lab_a"]

    applies, reason = case_applies(case, set())

    assert applies is False
    assert "oil_lab_kpis" in reason


def test_the_laboratory_cases_all_require_the_laboratory_capability():
    for case in select_cases([], ["laboratorio"]):
        assert "oil_lab_kpis" in case.requires_capabilities, case.case_id


# ----------------------------------------------- the evaluator rejects wrong answers


# A grounding report with nothing flagged: the case under test is the wording, not the
# auditor, and a grounded case rightly fails when no audit accompanies the answer.
_CLEAN_GROUNDING = {"unverified_numbers": [], "invented_units": []}


def _evaluate(case: QualityCase, answer: str, facts: dict | None = None) -> list[str]:
    return evaluate(case, answer, "agents", [], facts or {}, _CLEAN_GROUNDING)


def test_a_grounded_case_fails_when_no_traceability_audit_accompanies_it():
    """The auditor is not optional for a case that is expected to carry figures."""
    case = CASE_MAP["cert_lab_b"]
    answer = "El tiempo de laboratorio promedia 1,7 días sobre 3580 muestras del período."

    assert case.expect_grounded is True
    assert evaluate(case, answer, "agents", [], {"lab_total_samples": "3580"}, {})
    assert not evaluate(
        case, answer, "agents", [], {"lab_total_samples": "3580"}, _CLEAN_GROUNDING
    )


def test_the_evaluator_rejects_a_figure_with_no_source():
    case = CASE_MAP["cert_lab_b"]
    facts = {"lab_total_samples": "3580"}
    answer = "El tiempo de laboratorio promedia 1,7 días sobre 3580 muestras del período."

    flagged = evaluate(
        case,
        answer,
        "agents",
        [],
        facts,
        {"unverified_numbers": ["1,7"], "invented_units": []},
    )

    assert any("sin origen" in failure for failure in flagged)


def test_the_evaluator_rejects_an_invented_unit():
    case = CASE_MAP["cert_lab_b"]
    facts = {"lab_total_samples": "3580"}
    answer = "El tiempo de laboratorio promedia 1,7 días sobre 3580 muestras del período."

    flagged = evaluate(
        case,
        answer,
        "agents",
        [],
        facts,
        {"unverified_numbers": [], "invented_units": ["°C"]},
    )

    assert any("unidades" in failure for failure in flagged)


def test_the_evaluator_rejects_a_ranking_read_as_a_probability():
    case = CASE_MAP["cert_predictive_b"]

    wrong = _evaluate(case, "El ranking es la probabilidad de falla del equipo.")
    right = _evaluate(
        case, "El ranking es un orden de prioridad, no una probabilidad de falla."
    )

    assert wrong, "una respuesta que convierte el ranking en probabilidad debe fallar"
    assert not right


def test_the_evaluator_rejects_an_invented_sla_percentage():
    case = CASE_MAP["cert_lab_c"]

    wrong = _evaluate(case, "El cumplimiento del SLA es de 87%.")
    right = _evaluate(
        case,
        "No hay un SLA contractual acordado para el laboratorio, así que no puedo "
        "calcular un porcentaje de cumplimiento.",
    )

    assert wrong
    assert not right


def test_the_evaluator_rejects_a_missing_date_reported_as_zero():
    case = CASE_MAP["cert_lab_missing_is_not_zero"]

    wrong = _evaluate(case, "Sí, se cuenta como cero días de tránsito.")
    right = _evaluate(
        case,
        "No, no cuenta como cero: esa muestra queda fuera del promedio de tránsito y se "
        "informa como dato faltante.",
    )

    assert wrong
    assert not right


def test_the_evaluator_rejects_an_answer_that_omits_a_required_fact():
    case = CASE_MAP["cert_lab_b"]
    facts = {"lab_total_samples": "3580"}

    wrong = _evaluate(case, "El laboratorio demora unos pocos días en promedio.", facts)
    right = _evaluate(
        case,
        "El tiempo de laboratorio promedia 1,7 días sobre 3580 muestras del período.",
        facts,
    )

    assert wrong
    assert not right


def test_the_evaluator_rejects_a_machine_aggregate_described_as_a_sample():
    case = CASE_MAP["cert_machine_vs_sample_b"]

    wrong = _evaluate(case, "Sí, el estado global es el resultado de la última muestra.")
    right = _evaluate(
        case,
        "No: el estado global es un agregado que pondera los componentes del equipo, no "
        "el resultado de una muestra.",
    )

    assert wrong
    assert not right


def test_the_evaluator_rejects_a_promised_sixty_day_window():
    case = CASE_MAP["cert_old_sample_is_not_missing_data"]

    wrong = _evaluate(case, "Si la muestra tiene más de 60 días te diré que no hay datos.")
    right = _evaluate(
        case,
        "Te la entrego igual y te informo su fecha; no aplico una ventana de 60 días.",
    )

    assert wrong
    assert not right


def test_the_evaluator_rejects_a_lower_limit_treated_as_zero():
    case = CASE_MAP["cert_limits_b"]

    wrong = _evaluate(case, "Sí, un límite inferior ausente se toma como cero.")
    right = _evaluate(
        case, "No lo trato como cero: un límite inferior ausente es ausente."
    )

    assert wrong
    assert not right


def test_old_sample_rule_accepts_negating_the_missing_data_claim():
    case = CASE_MAP["cert_old_sample_is_not_missing_data"]
    assert not _evaluate(case, "Te la entrego con su fecha, en lugar de decir que no hay datos.")


def test_predictive_explanation_can_deny_that_ranking_is_probability():
    case = CASE_MAP["cert_predictive_a"]
    assert not _evaluate(case, "El ranking indica prioridad, no una probabilidad de falla.")
    assert _evaluate(case, "El ranking representa una probabilidad de falla.")
