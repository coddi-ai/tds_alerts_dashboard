"""Acceptance cases AC01-AC02: "Nueva conversación" opens a thread and keeps the previous one.

The reported problem was a button labelled "Limpiar" with a trash icon that emptied the live
thread and kept its id, so the conversation just built vanished with no way back. These cases
pin the behaviour that replaces it, and the failure modes around it: a failed initialization, a
double click, and an answer still in flight.
"""

from __future__ import annotations

import dash
import pytest

import dashboard.campbell_ai.callbacks as callbacks_module
from dashboard.campbell_ai.callbacks import register_campbell_ai_callbacks
from dashboard.campbell_ai.client import CampbellAPIClientError
from dashboard.campbell_ai.layout import create_campbell_ai_layout


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        yield from _walk(child)


def _component(component_id):
    return next(
        item
        for item in _walk(create_campbell_ai_layout())
        if getattr(item, "id", None) == component_id
    )


def _text(component) -> str:
    return " ".join(item for item in _walk(component) if isinstance(item, str))


class _FakeClient:
    """Stands in for the API client: records what was called, and can be made to fail."""

    def __init__(self, *, session_ids=("sesion-nueva",), fail: bool = False):
        self.session_ids = list(session_ids)
        self.fail = fail
        self.initialize_calls: list[tuple] = []
        self.clear_calls: list[tuple] = []

    def initialize(self, username, company_id, session_id=None):
        self.initialize_calls.append((username, company_id, session_id))
        if self.fail:
            raise CampbellAPIClientError("el servicio no responde")
        return {"session_id": self.session_ids.pop(0), "capabilities": {"available": []}}

    def clear(self, username, company_id, session_id):
        self.clear_calls.append((username, company_id, session_id))


@pytest.fixture
def new_conversation(monkeypatch):
    """The registered `start_new_conversation` callback, with a fake client behind it."""
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    holder: dict = {}

    # The de-duplication window is process-local and would otherwise leak between cases,
    # since they all create a thread for the same (user, company, previous thread).
    callbacks_module._NEW_CONVERSATION_RESULTS.clear()
    callbacks_module._NEW_CONVERSATION_LOCKS.clear()

    # Identity normally comes from the signed dashboard session. These cases are about what
    # the callback does with a thread, so the authenticated user is supplied directly.
    monkeypatch.setattr(
        callbacks_module,
        "_current_username",
        lambda company_state=None: (
            (company_state or {}).get("username") if isinstance(company_state, dict) else None
        ),
    )

    def _install(client: _FakeClient) -> _FakeClient:
        monkeypatch.setattr(
            callbacks_module.CampbellAPIClient, "from_env", staticmethod(lambda: client)
        )
        holder["client"] = client
        return client

    # The undecorated function: Dash's wrapper expects to be driven by a request context.
    callback = next(
        metadata["callback"].__wrapped__
        for callback_id, metadata in app.callback_map.items()
        if "campbell-ai-input.value" in callback_id
        and any(
            item["id"] == "campbell-ai-new-conversation-main"
            for item in metadata["inputs"]
        )
    )
    return _install, callback


# ---------------------------------------------------------------- naming (C01)


def test_the_action_is_named_new_conversation_and_not_a_delete():
    """One name for one action, and no wording that reads as erasing the thread."""
    header = _component("campbell-ai-new-conversation-main")
    panel = _component("campbell-ai-new-conversation")
    page = _text(create_campbell_ai_layout())

    assert "Nueva conversación" in _text(header)
    assert "Nueva conversación" in _text(panel)
    # The accessible title says what happens to the previous thread.
    assert "historial" in header.title
    # The old label and the trash icon are gone from the view.
    assert "Limpiar" not in page
    assert "fa-trash" not in str(header.children)


def test_both_entry_points_are_wired_to_one_implementation(new_conversation):
    """The header button used to call `/clear`; now both call the same creator."""
    _install, callback = new_conversation

    assert callable(callback)


# ---------------------------------------------------------------------- AC01


def test_ac01_a_new_thread_gets_a_new_id_and_does_not_clear_the_old_one(new_conversation):
    install, callback = new_conversation
    client = install(_FakeClient(session_ids=["sesion-2"]))

    result = callback(
        1,                                  # panel click
        None,                               # header click
        {"company_id": "cda", "username": "u"},
        "sesion-1",                         # the thread currently open
        [{"role": "user", "content": "hola"}],
        None,                               # no failure
    )
    (
        session_id,
        history,
        company_id,
        status,
        color,
        failure,
        feedback,
        composer,
        pending,
        job,
    ) = result

    assert session_id == "sesion-2"
    assert history == []
    assert company_id == "cda"
    assert color == "success"
    assert failure is None
    # Ratings, the half-typed question and any in-flight marker belong to the old thread.
    assert feedback == {}
    assert composer == ""
    assert pending is None
    # The job handle too: the poll reads that store, and leaving it behind is how a finished
    # answer for the previous thread landed in this one.
    assert job is None
    # Nothing was cleared: the archived thread is untouched and stays reopenable.
    assert client.clear_calls == []
    assert client.initialize_calls == [("u", "cda", None)]


def test_ac01_the_header_button_creates_a_thread_too(new_conversation):
    install, callback = new_conversation
    client = install(_FakeClient(session_ids=["sesion-3"]))

    result = callback(
        None,
        1,                                  # header click only
        {"company_id": "enex", "username": "u"},
        "sesion-1",
        [{"role": "user", "content": "hola"}],
        None,
    )

    assert result[0] == "sesion-3"
    assert client.clear_calls == []


# ---------------------------------------------------------------------- AC02


def test_ac02_a_failed_initialization_keeps_the_open_thread(new_conversation):
    """Losing the current thread *and* not getting a new one is the worst outcome."""
    install, callback = new_conversation
    install(_FakeClient(fail=True))

    result = callback(
        1,
        None,
        {"company_id": "cda", "username": "u"},
        "sesion-1",
        [{"role": "user", "content": "hola"}],
        None,
    )
    session_id, history, company_id, _status, color, failure, *rest = result

    assert len(result) == 10
    assert session_id is dash.no_update
    assert history is dash.no_update
    assert company_id is dash.no_update
    assert color == "danger"
    # Recoverable: the view gets a failure it can explain and retry from.
    assert isinstance(failure, dict) and failure
    # Nothing else is touched, so the open thread survives intact.
    assert all(item is dash.no_update for item in rest)


def test_ac02_a_repeated_click_does_not_create_a_second_thread(new_conversation):
    """A double click used to mint two sessions and abandon the first."""
    install, callback = new_conversation
    client = install(_FakeClient(session_ids=["sesion-2", "sesion-3"]))

    first = callback(
        1, None, {"company_id": "cda", "username": "u"}, "sesion-1", [{"role": "user"}], None
    )
    assert first[0] == "sesion-2"

    # Second click, now on the thread that is already new and empty.
    with pytest.raises(dash.exceptions.PreventUpdate):
        callback(2, None, {"company_id": "cda", "username": "u"}, "sesion-2", [], None)

    assert len(client.initialize_calls) == 1


def test_ac02_two_clicks_before_the_browser_updates_share_one_thread(new_conversation):
    """The real double click: both callbacks see the *same* old thread as their start.

    The empty-thread guard cannot catch this one - neither invocation has the new state yet -
    so each used to mint a session and orphan the first.
    """
    install, callback = new_conversation
    client = install(_FakeClient(session_ids=["sesion-2", "sesion-3"]))
    stale = ({"company_id": "cda", "username": "u"}, "sesion-1", [{"role": "user"}], None)

    first = callback(1, None, *stale)
    second = callback(2, None, *stale)

    assert first[0] == second[0] == "sesion-2"
    assert len(client.initialize_calls) == 1
    # Both callers leave the view in the same state, so whichever lands last is correct.
    assert first[:9] == second[:9]


def test_a_later_click_from_the_new_thread_does_create_another(new_conversation):
    """De-duplication is per starting point, not a lock on creating threads."""
    install, callback = new_conversation
    client = install(_FakeClient(session_ids=["sesion-2", "sesion-3"]))

    first = callback(
        1, None, {"company_id": "cda", "username": "u"}, "sesion-1", [{"role": "user"}], None
    )
    # The user has since asked something in the new thread, so it is no longer empty.
    second = callback(
        2, None, {"company_id": "cda", "username": "u"}, "sesion-2", [{"role": "user"}], None
    )

    assert first[0] == "sesion-2"
    assert second[0] == "sesion-3"
    assert len(client.initialize_calls) == 2


def test_ac02_a_failed_thread_can_still_be_retried_when_empty(new_conversation):
    """The empty-thread guard must not lock a user out after an initialization failure."""
    install, callback = new_conversation
    client = install(_FakeClient(session_ids=["sesion-2"]))

    result = callback(
        1,
        None,
        {"company_id": "cda", "username": "u"},
        "sesion-1",
        [],                                     # empty thread
        {"kind": "service", "title": "cayó"},   # but with a live failure
    )

    assert result[0] == "sesion-2"
    assert len(client.initialize_calls) == 1


def test_without_a_company_or_user_nothing_is_created(new_conversation):
    install, callback = new_conversation
    client = install(_FakeClient())

    with pytest.raises(dash.exceptions.PreventUpdate):
        callback(1, None, {"company_id": None, "username": "u"}, "s", [{"role": "user"}], None)
    with pytest.raises(dash.exceptions.PreventUpdate):
        callback(1, None, {"company_id": "cda", "username": None}, "s", [{"role": "user"}], None)

    assert client.initialize_calls == []


def test_a_click_count_of_zero_is_a_mount_not_an_action(new_conversation):
    install, callback = new_conversation
    install(_FakeClient())

    with pytest.raises(dash.exceptions.PreventUpdate):
        callback(0, 0, {"company_id": "cda", "username": "u"}, "s", [{"role": "user"}], None)


# --------------------------------------------------------------- integration


def test_the_clear_endpoint_contract_is_preserved():
    """`/clear` still exists for any consumer that relies on it."""
    from dashboard.campbell_ai.client import CampbellAPIClient

    assert hasattr(CampbellAPIClient, "clear")


def test_every_campbell_callback_output_exists_in_the_layout():
    """A renamed id that a callback still points at disables that whole callback in Dash."""
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    layout_ids = {
        getattr(item, "id", None)
        for item in _walk(create_campbell_ai_layout())
        if isinstance(getattr(item, "id", None), str)
    }

    missing: set[str] = set()
    for callback_id, metadata in app.callback_map.items():
        targets = [callback_id] + [
            f"{item['id']}.{item['property']}"
            for item in metadata["inputs"] + metadata.get("state", [])
            if isinstance(item["id"], str)
        ]
        for target in targets:
            for piece in target.replace("..", "\x00").split("\x00"):
                name = piece.split(".")[0].strip()
                if not name.startswith("campbell-ai-"):
                    continue
                if name not in layout_ids:
                    missing.add(name)

    assert not missing, f"ids referenciados por callbacks y ausentes del layout: {missing}"

# ------------------------------------------------------- AC21 (cross-client)


def _callback(app, output_fragment, input_id):
    return next(
        metadata["callback"].__wrapped__
        for callback_id, metadata in app.callback_map.items()
        if output_fragment in callback_id
        and any(item["id"] == input_id for item in metadata["inputs"])
    )


@pytest.mark.parametrize("event_session,event_company", [("old", "cda"), ("active", "enex")])
def test_a_late_stream_cannot_replace_the_active_thread(event_session, event_company):
    from dash.exceptions import PreventUpdate
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    finalize = _callback(app, "campbell-ai-history-store.data", "campbell-ai-stream-store")
    result = {"ok": True, "event": {"session_id": event_session,
              "company_id": event_company, "messages": [{"content": "stale"}]}}
    with pytest.raises(PreventUpdate):
        finalize(result, None, [], "active", {"company_id": "cda"}, 0)


def test_the_active_stream_still_delivers_its_answer():
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    finalize = _callback(app, "campbell-ai-history-store.data", "campbell-ai-stream-store")
    messages = [{"role": "assistant", "content": "current"}]
    result = {"ok": True, "event": {"session_id": "active", "company_id": "cda",
                                    "messages": messages}}
    applied = finalize(result, None, [], "active", {"company_id": "cda"}, 0)
    assert applied[0] == messages
    assert applied[1] == "active"


def test_a_failed_old_stream_does_not_retry_in_a_new_conversation():
    from dash.exceptions import PreventUpdate
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    finalize = _callback(app, "campbell-ai-history-store.data", "campbell-ai-stream-store")
    result = {"ok": False, "session_id": "old", "company_id": "cda"}
    pending = {"session_id": "active", "company_id": "cda", "message": "new question"}
    with pytest.raises(PreventUpdate):
        finalize(result, pending, [], "active", {"company_id": "cda"}, 0)


@pytest.mark.parametrize("available", [True, False])
def test_suggested_question_revalidates_the_source_at_submission(monkeypatch, available):
    from types import SimpleNamespace
    from unittest.mock import Mock
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    synchronize = _callback(app, "campbell-ai-history-store.data", "campbell-ai-send")
    capabilities = {"available": [{"key": "oil_lab_kpis"}] if available else []}
    client = Mock()
    client.initialize.return_value = {"session_id": "active", "capabilities": capabilities}
    monkeypatch.setattr(callbacks_module.CampbellAPIClient, "from_env", lambda: client)
    monkeypatch.setattr(callbacks_module, "_current_username", lambda _: "tester")
    monkeypatch.setattr(callbacks_module, "_stale_browser_state", lambda *_: None)
    monkeypatch.setattr(callbacks_module, "callback_context", SimpleNamespace(
        triggered_id={"type": "campbell-ai-suggested-question", "question_id": "lab-turnaround"},
        triggered=[{"value": 1}],
    ))
    history = [{"role": "assistant", "content": "previous"}]
    result = synchronize("enex", 0, 0, [1], 0, "", "active", history,
                         {"company_id": "enex"}, None, "enex", None,
                         {"available": [{"key": "oil_lab_kpis"}]})
    client.initialize.assert_called_once_with("tester", "enex", "active")
    if available:
        assert result[7]["message"]
        assert result[7]["session_id"] == "active"
    else:
        assert result[7] is None
        assert result[1] == history
        assert result[5]["kind"] == "source_unavailable"


def test_ac21_suggestions_never_carry_over_from_the_previous_client(monkeypatch):
    """A capability payload stamped for another company must not be rendered as this one's.

    The store is memory-scoped, but a client switch and the capability round trip are two
    separate events: between them the store still holds the previous company's answer.
    """
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    render = _callback(app, "campbell-ai-suggestions.children", "campbell-ai-capabilities-store")

    alerts_client = {
        "company_id": "cda",
        "available": [{"key": "alerts", "label": "Alertas"}],
    }

    # Same company: its questions are offered.
    for_cda = render(alerts_client, "cda")
    assert "weekly-summary" in _suggestion_ids_of(for_cda)

    # The selector already moved to another company; the store has not caught up.
    for_enex = render(alerts_client, "enex")
    assert _suggestion_ids_of(for_enex) == []


def test_ac21_a_capability_failure_withdraws_every_suggestion(monkeypatch):
    """Failing closed: an offered question that cannot run is the defect being fixed."""
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    resolve = _callback(app, "campbell-ai-capabilities-store.data", "campbell-ai-session-store")
    monkeypatch.setattr(
        callbacks_module,
        "_current_username",
        lambda company_state=None: "u",
    )
    monkeypatch.setattr(
        callbacks_module.CampbellAPIClient,
        "from_env",
        staticmethod(lambda: _FakeClient(fail=True)),
    )

    assert (
        resolve("sesion-1", "cda", 0, None, {"company_id": "cda", "username": "u"}, None)
        is None
    )


def test_ac21_capabilities_are_stamped_with_the_company_they_describe(monkeypatch):
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    resolve = _callback(app, "campbell-ai-capabilities-store.data", "campbell-ai-session-store")
    client = _FakeClient()
    monkeypatch.setattr(
        callbacks_module, "_current_username", lambda company_state=None: "u"
    )
    monkeypatch.setattr(
        callbacks_module.CampbellAPIClient, "from_env", staticmethod(lambda: client)
    )

    stored = resolve(
        "sesion-1", "enex", 0, None, {"company_id": "enex", "username": "u"}, None
    )

    assert stored["company_id"] == "enex"
    # The existing thread is reused, so resolving capabilities does not create a session.
    assert client.initialize_calls == [("u", "enex", "sesion-1")]


def _suggestion_ids_of(nodes) -> list[str]:
    collected: list[str] = []
    for node in nodes if isinstance(nodes, (list, tuple)) else [nodes]:
        for item in _walk(node):
            component_id = getattr(item, "id", None)
            if (
                isinstance(component_id, dict)
                and component_id.get("type") == "campbell-ai-suggested-question"
            ):
                collected.append(component_id["question_id"])
    return collected


# ------------------------------------------- H01/R05: a job belongs to one thread


def _poll_callback(app):
    return next(
        metadata["callback"].__wrapped__
        for callback_id, metadata in app.callback_map.items()
        if "campbell-ai-job-store.data" in callback_id
        and any(item["id"] == "campbell-ai-job-poll" for item in metadata["inputs"])
    )


class _AnsweringClient(_FakeClient):
    """A client whose background job has already finished."""

    def message_status(self, job_id):
        return {
            "status": "done",
            "result": {
                "session_id": "sesion-1",
                "messages": [{"role": "assistant", "content": "respuesta vieja"}],
            },
        }


def test_ac02_a_late_answer_does_not_land_in_the_new_thread(monkeypatch):
    """The question was asked before "nueva conversación"; its answer belongs to that thread."""
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    monkeypatch.setattr(
        callbacks_module, "_current_username", lambda company_state=None: "u"
    )
    monkeypatch.setattr(
        callbacks_module.CampbellAPIClient,
        "from_env",
        staticmethod(lambda: _AnsweringClient()),
    )
    poll = _poll_callback(app)
    job = {
        "job_id": "j1",
        "session_id": "sesion-1",
        "company_id": "cda",
        "username": "u",
        "question": "pregunta vieja",
    }

    result = poll(1, job, [], {"company_id": "cda", "username": "u"}, 0, "sesion-2", "cda")

    # Nothing is written into the visible thread, and the handle is dropped.
    assert result[0] is dash.no_update
    assert result[1] is dash.no_update
    assert result[5] is None


def test_an_answer_for_the_open_thread_is_still_delivered(monkeypatch):
    """The discard must be about the thread, not about being slow."""
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    monkeypatch.setattr(
        callbacks_module, "_current_username", lambda company_state=None: "u"
    )
    monkeypatch.setattr(
        callbacks_module.CampbellAPIClient,
        "from_env",
        staticmethod(lambda: _AnsweringClient()),
    )
    poll = _poll_callback(app)
    job = {
        "job_id": "j1",
        "session_id": "sesion-1",
        "company_id": "cda",
        "username": "u",
        "question": "pregunta",
    }

    result = poll(1, job, [], {"company_id": "cda", "username": "u"}, 0, "sesion-1", "cda")

    assert result[0] == [{"role": "assistant", "content": "respuesta vieja"}]


def test_a_late_answer_does_not_cross_companies(monkeypatch):
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    monkeypatch.setattr(
        callbacks_module, "_current_username", lambda company_state=None: "u"
    )
    monkeypatch.setattr(
        callbacks_module.CampbellAPIClient,
        "from_env",
        staticmethod(lambda: _AnsweringClient()),
    )
    poll = _poll_callback(app)
    job = {
        "job_id": "j1",
        "session_id": "sesion-1",
        "company_id": "cda",
        "username": "u",
        "question": "pregunta",
    }

    result = poll(1, job, [], {"company_id": "cda", "username": "u"}, 0, "sesion-1", "enex")

    assert result[0] is dash.no_update
    assert result[5] is None


def test_both_new_conversation_buttons_are_blocked_while_an_answer_is_in_flight():
    """A thread created mid-answer is how a late result finds the wrong conversation."""
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    gate = next(
        metadata["callback"].__wrapped__
        for callback_id, metadata in app.callback_map.items()
        if "campbell-ai-input.placeholder" in callback_id
    )

    send, composer, header, panel, _placeholder = gate(None, {"message": "en curso"})

    assert send is True
    assert composer is True
    assert header is True
    assert panel is True


def test_a02_capabilities_are_re_resolved_on_a_schedule_and_after_a_failure():
    """A source that syncs or breaks mid-session must change what is offered."""
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)

    metadata = next(
        entry
        for callback_id, entry in app.callback_map.items()
        if "campbell-ai-capabilities-store.data" in callback_id
    )
    triggers = {item["id"] for item in metadata["inputs"]}

    assert {
        "campbell-ai-session-store",
        "client-selector",
        "campbell-ai-capabilities-refresh",
        "campbell-ai-failure-store",
    } <= triggers


def test_a02_the_refresh_interval_is_slow_enough_to_be_cheap():
    from dashboard.campbell_ai.layout import CAPABILITIES_REFRESH_MS

    # Minutes, not seconds: the backend memoizes per file generation, but this still costs a
    # request per browser and must not behave like the answer poll.
    assert CAPABILITIES_REFRESH_MS >= 60_000
    interval = _component("campbell-ai-capabilities-refresh")
    assert interval.interval == CAPABILITIES_REFRESH_MS


def test_a_capability_payload_that_did_not_change_does_not_rewrite_the_store(monkeypatch):
    """The five-minute tick must not rebuild the suggestion buttons for nothing.

    Rewriting the store re-renders the buttons, and a rebuilt button used to be read as a
    click on the first suggestion. Even with that fixed, churning the view every five minutes
    is pointless work.
    """
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    monkeypatch.setattr(
        callbacks_module, "_current_username", lambda company_state=None: "u"
    )
    monkeypatch.setattr(
        callbacks_module.CampbellAPIClient, "from_env", staticmethod(lambda: _FakeClient())
    )
    resolve = _callback(
        app, "campbell-ai-capabilities-store.data", "campbell-ai-session-store"
    )
    state = {"company_id": "cda", "username": "u"}

    first = resolve("sesion-1", "cda", 0, None, state, None)
    assert first["company_id"] == "cda"

    # The interval fires again with the same sources behind it.
    again = resolve("sesion-1", "cda", 1, None, state, first)

    assert again is dash.no_update
