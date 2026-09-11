"""Acceptance case AC20: the diagnosed cause of partial context loss, pinned in code.

C05's agreed scope is a diagnosis and material for the manual, not a rewrite of memory. What
is testable is the *mechanism*, and these cases pin it so a future change cannot quietly
invalidate the diagnosis:

1. The conversation history exists and is replayed - "it has no memory" is wrong.
2. It is bounded by a character budget, so an entity named only in an early turn can be
   evicted once the answers in between are large.
3. The specialist agents receive only `question` + `context`; they never see the
   conversation, so an unresolved pronoun reaching them cannot be resolved at all.
4. The mitigation applied is a prompt rule that requires restating resolved entities before
   delegating.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from src.campbell_ai.config import CampbellSettings
from src.campbell_ai.prompts import load_prompt


def _runtime_source() -> str:
    import src.campbell_ai.agents_runtime as runtime

    return Path(runtime.__file__).read_text(encoding="utf-8")


# ------------------------------------------------------- cause 1: memory exists


def test_the_conversation_is_replayed_into_every_turn():
    """The claim to rule out first: Campbell AI does keep the thread."""
    import src.campbell_ai.agents_runtime as runtime

    source = inspect.getsource(runtime.CampbellAgentRuntime._conversation_input)

    assert "_budgeted_history" in source
    # The current question is appended after the replayed history, not instead of it.
    assert "Consulta del usuario" in source


def test_the_history_budget_is_configurable_and_bounded():
    declared = {
        field
        for field in CampbellSettings.__dataclass_fields__
        if "history" in field
    }

    assert {
        "max_history_messages",
        "max_history_chars",
        "max_history_message_chars",
    } <= declared


# --------------------------------------------- cause 2: the budget evicts turns


def test_an_early_entity_can_be_evicted_once_the_answers_are_large(tmp_path):
    """Newest-first budgeting: a first-turn entity is droppable, and the drop is logged."""
    import src.campbell_ai.agents_runtime as runtime

    source = inspect.getsource(runtime.CampbellAgentRuntime._budgeted_history)
    tree = ast.parse(source.lstrip())

    # Iterated newest-first, which is what makes the oldest turn the one dropped.
    assert "reversed(messages)" in source
    # The most recent turn always survives, so the budget cannot empty the history.
    assert "selected" in source and "break" in source
    # Truncation is marked in the text rather than silent.
    assert "_TRUNCATION_NOTE" in source
    assert "recortada por longitud" in runtime.CampbellAgentRuntime._TRUNCATION_NOTE
    assert isinstance(tree, ast.Module)


def test_a_truncated_answer_is_marked_so_it_is_not_read_as_complete():
    import src.campbell_ai.agents_runtime as runtime

    note = runtime.CampbellAgentRuntime._TRUNCATION_NOTE

    assert note.strip().startswith("[")
    assert "anterior" in note


# ------------------------------- cause 3: specialists never see the conversation


def test_the_specialists_receive_only_the_text_the_head_passes_them():
    """The dominant cause: a pronoun that reaches a specialist is unresolvable there.

    Parsed from the source because it is a structural fact about the delegation, not a
    runtime behaviour that can be observed without calling a model.
    """
    source = _runtime_source()
    tree = ast.parse(source)
    delegations = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name
        in {"data_analysis", "visualization_analysis", "technical_analysis"}
    }

    assert set(delegations) == {
        "data_analysis",
        "visualization_analysis",
        "technical_analysis",
    }
    for name, node in delegations.items():
        arguments = {argument.arg for argument in node.args.args}
        # Only the question and a free-text context: no conversation, no history.
        assert "question" in arguments, name
        assert arguments <= {"question", "context", "evidence"}, (name, arguments)
        body = ast.get_source_segment(source, node) or ""
        assert "_budgeted_history" not in body, name
        assert "messages" not in body, name


# ---------------------------------------- mitigation: the entity-restatement rule


def test_the_head_is_required_to_restate_resolved_entities_before_delegating():
    prompt = load_prompt("head_maintenance_base.md")

    assert "Los agentes especializados no ven la conversación" in prompt
    for token in ("equipo", "componente", "período", "alcance"):
        assert token in prompt, token
    # And it must ask instead of choosing when the reference is genuinely ambiguous.
    assert "pregunta al usuario" in prompt


def test_the_shared_glossary_states_the_same_selection_rules():
    """The rules the head applies are the ones the data layer emits, not a second set."""
    glossary = load_prompt("oil_entity_levels.md")

    assert "muestra más reciente" in glossary
    assert "Declara siempre el alcance" in glossary
    # Missing data is not a normal condition, in the glossary every agent reads.
    assert "no es condición normal" in glossary


# ------------------------------------------------------------ manual material


def test_the_manual_documents_the_limitation_and_what_to_do_about_it():
    """AC20's deliverable: the limitation written down, with a usable workaround."""
    manual = Path("documentation/general/campbell_ai_manual_usuario.md").read_text(
        encoding="utf-8"
    )

    for section in (
        "Los tres niveles del análisis de aceite",
        "Condición actual frente a historial",
        "Límites de referencia",
        "Tiempos de laboratorio",
        "Nueva conversación",
        "Limitación conocida: referencias entre turnos",
    ):
        assert section in manual, section
    # It names the two causes rather than calling it a lack of memory.
    assert "no ven la conversación" in manual
    assert "_budgeted_history" in manual
    assert "no** es falta de memoria" in manual
    # And it states what is still pending, instead of implying the problem is solved.
    assert "Pendiente." in manual
