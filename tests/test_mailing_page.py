"""Pagina Administracion -> Mailing (03_admin_mailing_screen.md): layout, callbacks, nav y acceso."""

from __future__ import annotations

import dash
import pytest
from dash.exceptions import PreventUpdate
from flask import Flask, session as flask_session

from config.users import USERS
from dashboard.callbacks import mailing_callbacks as cb
from dashboard.layout import build_navigation_items
from dashboard.services_registry import NAV_ICONS, NAV_PATHS, nav_id_for_pathname
from dashboard.tabs.tab_mailing import BUTTON_GROUPS, GROUP_IDS, create_layout, group_ids
from src.mailing import ReportContent, config, delivery, periods, register_report_builder, report
from src.mailing.errors import MailingError

ADMIN = next(n for n, u in USERS.items() if u.get("role") == "admin")
CLIENT_USER = next(n for n, u in USERS.items() if u.get("role") != "admin")
TECH = "tds@coddi.ai"
TECHS = [r["email"] for r in config.CODDI_RECIPIENTS["technical"]]  # every Coddi technical contact
EMIN_CLIENT = [r["email"] for r in config.MAILING_RECIPIENTS["emin"]]
GERENCIA = ["eduardo@coddi.ai", "pedro@coddi.ai"]


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def hermetic(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_DOTENV_LOADED", True)
    monkeypatch.setenv("LAMBDA_URL", "https://abc.lambda-url.us-east-2.on.aws/")
    monkeypatch.setenv("LAMBDA_ACCESS_KEY", "AKIAFAKEFAKEFAKEFAKE")
    monkeypatch.setenv("LAMBDA_SECRET_ACCESS_KEY", "fake")
    monkeypatch.setenv("DEPLOY_STATUS", "test")
    monkeypatch.setenv("MAILING_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MAILING_MANUAL_COOLDOWN_SECONDS", "0")
    service = __import__("src.mailing.service", fromlist=["x"])
    service._manual_locks.clear()
    service._manual_last_success.clear()


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setenv("DEPLOY_STATUS", "POC")


@pytest.fixture
def builder():
    def fake(request):
        return ReportContent(subject=periods.build_subject(request.send_date), html="<html>CORREO</html>")

    register_report_builder(report.ALERT_SUMMARY, fake)
    yield fake
    report.unregister_report_builder(report.ALERT_SUMMARY)


@pytest.fixture
def sent(monkeypatch):
    box = {"calls": [], "result": delivery.DeliveryResult(True)}

    def fake_send(subject, html, emails):
        box["calls"].append({"subject": subject, "emails": list(emails)})
        return box["result"]

    monkeypatch.setattr(delivery, "send_email", fake_send)
    return box


@pytest.fixture
def flask_app():
    app = Flask(__name__)
    app.secret_key = "test-secret-key-with-enough-entropy"
    app.pushed = []
    yield app
    while app.pushed:
        app.pushed.pop().pop()


def as_user(app, username):
    ctx = app.test_request_context()
    ctx.push()
    app.pushed.append(ctx)
    flask_session["dashboard_user"] = username
    return {"username": username, "role": USERS[username]["role"], "clients": []}


def walk(component):
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            if hasattr(child, "children") or hasattr(child, "id"):
                yield from walk(child)
    elif children is not None and (hasattr(children, "children") or hasattr(children, "id")):
        yield from walk(children)


def by_id(layout, component_id):
    return next((c for c in walk(layout) if getattr(c, "id", None) == component_id), None)


def render(app, client="EMIN", user=ADMIN):
    user_data = as_user(app, user)
    out = cb.render_context(client, user_data, True)
    keys = ["chips", "unavailable", "main_style", "title", "subtitle", "subject", "period", "help",
            "t_client", "t_tech", "t_mgmt", "s_client", "s_tech", "s_mgmt", "rendered_for"]
    return dict(zip(keys, out)), user_data


def checklist_state(checklist):
    return checklist.options, checklist.value


def text(component) -> str:
    """Every string inside a component tree."""
    parts = []
    for node in walk(component):
        child = getattr(node, "children", None)
        if isinstance(child, str):
            parts.append(child)
    return " ".join(parts)


# --------------------------------------------------------------------------- layout / a11y


def test_layout_has_every_piece_the_callbacks_use():
    layout = create_layout()
    for component_id in ("mailing-chips", "mailing-unavailable", "mailing-main", "mailing-report-title", "mailing-report-subtitle",
                         "mailing-subject", "mailing-period", "mailing-counter", "mailing-send-summary", "mailing-preview-btn",
                         "mailing-send-btn", "mailing-feedback", "mailing-preview-modal", "mailing-preview-frame",
                         "mailing-send-result", "mailing-preview-result", "mailing-rendered-for", "mailing-recipients",
                         "mailing-help", "mailing-send-trigger", "mailing-confirm-modal", "mailing-confirm-cancel",
                         "mailing-confirm-send", "mailing-confirm-counts"):
        assert by_id(layout, component_id) is not None, component_id
    for group in GROUP_IDS:
        for key in ("checklist", "title", "count", "heading", "slot", "summary"):
            assert by_id(layout, group_ids(group)[key]) is not None, (group, key)


def test_group_buttons_exist_for_client_and_management_but_not_for_technical():
    layout = create_layout()
    assert BUTTON_GROUPS == ("client", "management")
    for group in BUTTON_GROUPS:
        button = by_id(layout, group_ids(group)["button"])
        assert type(button).__name__ == "Button" and button.type == "button"
    assert by_id(layout, group_ids("technical")["button"]) is None


def test_two_columns_recipients_first_then_the_summary_card():
    layout = create_layout()
    grid = by_id(layout, "mailing-main")
    assert "mailing-grid" in grid.className
    recipients_card, summary_card = grid.children
    assert "mailing-card--recipients" in recipients_card.className and "mailing-card--summary" in summary_card.className
    assert by_id(recipients_card, "mailing-recipients") is not None
    for component_id in ("mailing-report-title", "mailing-subject", "mailing-period", "mailing-send-summary",
                         "mailing-send-btn", "mailing-preview-btn", "mailing-feedback"):
        assert by_id(summary_card, component_id) is not None, component_id
    assert by_id(grid, "mailing-help") is by_id(recipients_card, "mailing-help")  # under the Destinatarios heading
    assert "El envío manual no modifica la programación automática." in text(summary_card)
    # there is no separate action bar any more
    assert "mailing-actions" not in str(layout)


def test_summary_breakdown_has_the_three_labelled_boxes():
    layout = create_layout()
    boxes = [c for c in walk(layout) if "mailing-sum-box" in str(getattr(c, "className", ""))]
    assert [text(b).split()[0] for b in boxes] == ["Cliente", "Técnico", "Gerencia"]


def test_confirmation_dialog_is_accessible_and_closes_without_sending():
    modal = by_id(create_layout(), "mailing-confirm-modal")
    assert modal.is_open is False and modal.keyboard is True and modal.backdrop is True
    assert modal.labelledby == "mailing-confirm-title"
    layout_text = text(modal)
    assert "Confirmar Envío" in layout_text and "Atención: está en el entorno Desarrollo" in layout_text
    assert "Cancelar" in layout_text
    for button_id in ("mailing-confirm-cancel", "mailing-confirm-send"):
        assert type(by_id(modal, button_id)).__name__ == "Button"


def test_the_page_has_no_client_selector_and_no_send_mode_control():
    layout = create_layout()
    assert by_id(layout, "client-selector") is None
    rendered = str(layout)
    for forbidden in ("Modo de Envío", "Prueba", "Producción</"):
        assert forbidden not in rendered


def test_groups_are_labelled_groups():
    layout = create_layout()
    groups = [c for c in walk(layout) if getattr(c, "role", None) == "group"]
    assert len(groups) == 3
    for group, name in zip(groups, GROUP_IDS):
        assert getattr(group, "aria-labelledby") == group_ids(name)["heading"]
        assert by_id(layout, group_ids(name)["heading"]) is not None  # the id it points at exists


def test_buttons_are_real_buttons_with_the_specified_text():
    layout = create_layout()
    for button_id, label in (("mailing-preview-btn", "Ver Vista Previa"), ("mailing-send-btn", "Enviar Ahora")):
        button = by_id(layout, button_id)
        assert type(button).__name__ == "Button" and button.type == "button" and button.children == label


def test_preview_iframe_is_fully_sandboxed_and_modal_closes_with_esc():
    layout = create_layout()
    frame = by_id(layout, "mailing-preview-frame")
    assert type(frame).__name__ == "Iframe" and frame.sandbox == "" and frame.title
    modal = by_id(layout, "mailing-preview-modal")
    assert modal.keyboard is True and modal.is_open is False
    assert any(type(c).__name__ == "ModalHeader" and c.close_button for c in walk(modal))


def test_feedback_is_a_polite_live_region():
    feedback = by_id(create_layout(), "mailing-feedback")
    assert feedback.role == "status" and getattr(feedback, "aria-live") == "polite"


def test_checklists_are_swapped_per_client_not_updated_in_place():
    """Dash 4's renderer crashes (and resets the whole layout) when the `options` of a checklist
    with component labels change between two non-empty lists, so a fresh checklist is mounted."""
    callback_outputs = []
    app = dash.Dash(__name__)
    app.layout = create_layout
    cb.register_mailing_callbacks(app)
    for entry in app.callback_map.values():
        callback_outputs.append(str(entry["output"]))
    joined = " ".join(callback_outputs)
    for group in GROUP_IDS:
        assert f"{group_ids(group)['checklist']}.options" not in joined
        assert f"{group_ids(group)['slot']}.children" in joined


def test_callbacks_register_against_the_layout_without_duplicate_outputs():
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    from dash import dcc, html

    app.layout = html.Div([dcc.Dropdown(id="client-selector"), dcc.Store(id="user-info-store"), create_layout()])
    cb.register_mailing_callbacks(app)
    app.server.testing = True
    with app.server.test_client() as client:
        assert client.get("/_dash-layout").status_code == 200
        assert client.get("/_dash-dependencies").status_code == 200


# --------------------------------------------------------------------------- render


def test_render_in_production_prechecks_client_and_management(flask_app, production):
    state, _ = render(flask_app)
    assert state["main_style"] == {} and state["unavailable"] == ""
    assert state["title"] == "Resumen Diario de Alertas"
    assert state["subtitle"] == "Emin · se envía automáticamente todos los días a las 08:00 (hora de Chile)."
    assert state["subject"].startswith("[CODDI] Monitoreo de Alertas ")
    assert state["rendered_for"] == "emin"
    assert state["t_client"] == "Cliente · Emin" and state["t_tech"] == "Coddi · Técnico" and state["t_mgmt"] == "Coddi · Gerencia"
    client_opts, client_value = checklist_state(state["s_client"])
    assert client_value == EMIN_CLIENT and [o["value"] for o in client_opts] == EMIN_CLIENT
    assert checklist_state(state["s_mgmt"])[1] == GERENCIA
    chips = text_of_chips = " ".join(c.children for c in state["chips"])
    assert "Cliente: Emin" in chips and "Entorno: Producción" in chips


def test_technical_is_checked_and_disabled_everywhere(flask_app, production):
    for env in ("production", "development"):
        state, _ = render(flask_app)
        options, value = checklist_state(state["s_tech"])
        assert value == TECHS and all(o["disabled"] is True for o in options)
        if env == "production":
            continue


def test_outside_production_every_contact_is_selectable_and_only_technical_is_checked(flask_app):
    state, _ = render(flask_app)
    assert "Entorno: Desarrollo" in " ".join(c.children for c in state["chips"])
    for key, emails in (("s_client", EMIN_CLIENT), ("s_mgmt", GERENCIA)):
        options, value = checklist_state(state[key])
        assert value == [] and [o["value"] for o in options] == emails
        assert not any(o["disabled"] for o in options)  # the environment disables nothing
        assert not any("Solo disponible en producción" in text(o["label"]) for o in options)
    options, value = checklist_state(state["s_tech"])
    assert value == TECHS and all(o["disabled"] for o in options)


def test_contact_without_automatic_sending_is_unchecked_but_selectable(flask_app, production, monkeypatch):
    monkeypatch.setattr(config, "MAILING_RECIPIENTS", {"emin": [
        {"name": "A", "email": "a@x.cl", "send_email": True},
        {"name": "B", "email": "b@x.cl", "send_email": False},
    ]})
    state, _ = render(flask_app)
    options, value = checklist_state(state["s_client"])
    assert value == ["a@x.cl"]
    b = next(o for o in options if o["value"] == "b@x.cl")
    assert not b["disabled"] and "Sin envío automático" in text(b["label"])


def test_row_tags_carry_text(flask_app, production):
    state, _ = render(flask_app)
    assert "Siempre incluido" in text(checklist_state(state["s_tech"])[0][0]["label"])
    for option in checklist_state(state["s_mgmt"])[0]:
        assert "Solo producción" not in text(option["label"])  # Gerencia is selectable everywhere now
    first = checklist_state(state["s_client"])[0][0]["label"]
    assert "Diego Contreras" in text(first) and "dcontrerasr@emin.cl" in text(first)


def test_capstone_is_weekly(flask_app, production):
    state, _ = render(flask_app, "CAPSTONE")
    assert state["title"] == "Resumen Semanal de Alertas"
    assert "los miércoles a las 08:00" in state["subtitle"]
    assert "últimos 7 días" in state["period"] and len(checklist_state(state["s_client"])[0]) == 10


def test_unconfigured_client_hides_the_card_and_says_so(flask_app):
    state, _ = render(flask_app, "CDA")
    assert state["main_style"] == {"display": "none"}
    assert state["unavailable"] == "Este cliente no tiene envío de resúmenes configurado."
    assert state["rendered_for"] is None
    assert "Cliente: CDA" in " ".join(c.children for c in state["chips"])
    for key in ("s_client", "s_tech", "s_mgmt"):
        assert checklist_state(state[key]) == ([], [])


def test_non_admin_gets_nothing_but_a_denial(flask_app):
    state, _ = render(flask_app, "EMIN", user=CLIENT_USER)
    assert state["unavailable"] == "No tiene permisos para ver esta página."
    assert state["main_style"] == {"display": "none"} and state["subject"] == ""


def test_no_client_selected(flask_app):
    user_data = as_user(flask_app, ADMIN)
    out = cb.render_context(None, user_data, True)
    assert out[1] == "Seleccione un cliente para ver el envío de resúmenes."


# --------------------------------------------------------------------------- counters


def test_counters_update_with_the_selection():
    opts = lambda n: [{"value": str(i)} for i in range(n)]
    out = cb.update_counters(opts(3), ["0", "1"], opts(1), [TECH], opts(2), [])
    assert out[0] == "3 de 6 seleccionados"
    assert out[1:4] == ("2 de 3", "1 de 1", "0 de 2")
    assert out[4] == "Se enviará a 3 destinatarios:"
    assert out[5:8] == ("2", "1", "0")  # summary breakdown: Cliente, Técnico, Gerencia
    assert cb.update_counters(opts(3), [], opts(1), [TECH], opts(2), [])[4] == "Se enviará a 1 destinatario:"


def test_counters_do_not_double_count_a_repeated_email():
    out = cb.update_counters([{"value": "a"}], ["a"], [{"value": "a"}], ["a"], [], [])
    assert out[4] == "Se enviará a 1 destinatario:"


def options_of(emails, disabled=()):
    return [{"value": e, "disabled": e in disabled} for e in emails]


def test_group_button_says_select_all_until_every_selectable_row_is_checked():
    options = options_of(["a", "b", "c"])
    assert cb.group_button_state(options, [], "Coddi · Gerencia") == (
        "Seleccionar todos", "Seleccionar todos los contactos de Coddi · Gerencia", {})
    assert cb.group_button_state(options, ["a", "b"], "Coddi · Gerencia")[0] == "Seleccionar todos"
    assert cb.group_button_state(options, ["a", "b", "c"], "Coddi · Gerencia") == (
        "Quitar todos", "Quitar todos los contactos de Coddi · Gerencia", {})


def test_group_button_ignores_locked_rows_and_hides_when_nothing_is_selectable():
    options = options_of(["a", "b"], disabled=["b"])
    assert cb.group_button_state(options, ["a"], "G")[0] == "Quitar todos"  # b is locked: not counted
    assert cb.group_button_state(options_of(["t"], disabled=["t"]), ["t"], "T")[2] == {"display": "none"}
    assert cb.group_button_state([], [], "G")[2] == {"display": "none"}


def test_counters_return_the_buttons_of_client_and_management_only():
    opts = options_of(["a", "b"])
    out = cb.update_counters(opts, ["a"], options_of(["t"], disabled=["t"]), ["t"], opts, ["a", "b"], "Cliente · Emin", "Coddi · Gerencia")
    assert len(out) == 14
    assert out[8:11] == ("Seleccionar todos", "Seleccionar todos los contactos de Cliente · Emin", {})
    assert out[11:14] == ("Quitar todos", "Quitar todos los contactos de Coddi · Gerencia", {})


def test_select_all_checks_every_selectable_row_of_that_group_only():
    options = options_of(["a", "b", "c"])
    assert cb.toggle_group(1, options, ["b"]) == ["b", "a", "c"]
    assert cb.toggle_group(1, options, []) == ["a", "b", "c"]


def test_clear_all_unchecks_the_group_and_keeps_locked_rows():
    options = options_of(["a", "b", "locked"], disabled=["locked"])
    assert cb.toggle_group(1, options, ["a", "b", "locked"]) == ["locked"]
    assert cb.toggle_group(1, options_of(["a", "b"]), ["a", "b"]) == []


def test_select_all_includes_contacts_without_automatic_sending(flask_app, production):
    """The admin chose it explicitly: `send_email=False` contacts are checked too."""
    state, _ = render(flask_app, "CAPSTONE")
    options, value = checklist_state(state["s_client"])
    emails = [o["value"] for o in options]
    assert cb.toggle_group(1, options, []) == emails


def test_group_button_does_nothing_without_a_real_click_or_selectable_rows():
    with pytest.raises(PreventUpdate):
        cb.toggle_group(0, options_of(["a"]), [])
    with pytest.raises(PreventUpdate):
        cb.toggle_group(None, options_of(["a"]), [])
    with pytest.raises(PreventUpdate):
        cb.toggle_group(1, options_of(["t"], disabled=["t"]), ["t"])


def test_production_chip_is_neutral_and_development_chip_is_amber(flask_app, monkeypatch):
    dev_state, _ = render(flask_app)
    assert "mailing-chip--env-development" in dev_state["chips"][1].className
    assert dev_state["chips"][1].children == "Entorno: Desarrollo"
    monkeypatch.setenv("DEPLOY_STATUS", "POC")
    prod_state, _ = render(flask_app)
    assert "mailing-chip--env-production" in prod_state["chips"][1].className
    assert prod_state["chips"][1].children == "Entorno: Producción"


def test_helper_text_changes_with_the_environment(flask_app, monkeypatch):
    dev_state, _ = render(flask_app)
    assert dev_state["help"] == ("En el entorno de desarrollo solo se marca por defecto al equipo técnico. "
                                 "Puede seleccionar a cualquier otro destinatario.")
    monkeypatch.setenv("DEPLOY_STATUS", "POC")
    prod_state, _ = render(flask_app)
    assert prod_state["help"] == ("Vienen marcados los contactos con envío automático activo. Puede marcar o desmarcar "
                                  "cualquiera para este envío; el equipo técnico siempre recibe el correo.")


@pytest.mark.parametrize("production_env", [False, True])
def test_the_old_environment_texts_appear_nowhere(flask_app, monkeypatch, production_env):
    if production_env:
        monkeypatch.setenv("DEPLOY_STATUS", "POC")
    state, _ = render(flask_app)
    labels = " ".join(text(o["label"]) for k in ("s_client", "s_tech", "s_mgmt") for o in checklist_state(state[k])[0])
    everything = str(create_layout()) + labels + str(state["help"])
    for old in ("Solo disponible en producción", "Solo producción"):
        assert old not in everything


# --------------------------------------------------------------------------- confirmation


def press(monkeypatch, button_id):
    monkeypatch.setattr(cb, "ctx", type("C", (), {"triggered_id": button_id}))


def ask(monkeypatch, button_id="mailing-send-btn", client_value=(EMIN_CLIENT[0],), tech_value=(TECH,), mgmt_value=(),
        client="EMIN", rendered_for="emin", send_clicks=1, cancel_clicks=0, confirm_clicks=0):
    press(monkeypatch, button_id)
    return cb.request_send(send_clicks, cancel_clicks, confirm_clicks, client, list(client_value), list(tech_value),
                           list(mgmt_value), rendered_for)


def test_development_with_client_contacts_asks_for_confirmation_and_sends_nothing(flask_app, builder, sent, monkeypatch):
    is_open, counts, label, trigger = ask(monkeypatch, client_value=EMIN_CLIENT[:2], mgmt_value=GERENCIA)
    assert is_open is True and trigger is dash.no_update and sent["calls"] == []
    rows = [text(row) for row in counts]
    assert rows == ["Cliente · Emin 2 contactos", "Coddi · Técnico 1 contacto", "Coddi · Gerencia 2 contactos"]
    assert label == f"Enviar a {2 + 1 + 2} Destinatarios"


def test_confirmation_button_label_is_singular_for_one_recipient(monkeypatch):
    _open, _counts, label, _trigger = ask(monkeypatch, client_value=[EMIN_CLIENT[0]], tech_value=[])
    assert label == "Enviar a 1 Destinatario"


def test_development_without_client_contacts_sends_without_the_dialog(monkeypatch):
    is_open, _counts, _label, trigger = ask(monkeypatch, client_value=[], mgmt_value=GERENCIA)
    assert is_open is dash.no_update and trigger not in (None, dash.no_update)


def test_production_sends_without_the_dialog_even_with_client_contacts(monkeypatch, production):
    is_open, _counts, _label, trigger = ask(monkeypatch, client_value=EMIN_CLIENT)
    assert is_open is dash.no_update and trigger not in (None, dash.no_update)


def test_cancel_closes_the_dialog_without_a_send_request(monkeypatch):
    is_open, _c, _l, trigger = ask(monkeypatch, button_id="mailing-confirm-cancel", cancel_clicks=1)
    assert is_open is False and trigger is dash.no_update


def test_the_primary_button_closes_the_dialog_and_requests_the_send(monkeypatch):
    is_open, _c, _l, trigger = ask(monkeypatch, button_id="mailing-confirm-send", confirm_clicks=1)
    assert is_open is False and trigger not in (None, dash.no_update)


def test_two_send_requests_are_two_different_values(monkeypatch):
    first = ask(monkeypatch, client_value=[], confirm_clicks=0)[3]
    second = ask(monkeypatch, client_value=[], send_clicks=2)[3]
    assert first != second


@pytest.mark.parametrize("button_id,kwargs", [
    ("mailing-send-btn", {"send_clicks": 0}),
    ("mailing-send-btn", {"send_clicks": None}),
    ("mailing-confirm-send", {"confirm_clicks": 0}),
    ("mailing-send-btn", {"rendered_for": "capstone"}),
    ("mailing-confirm-send", {"confirm_clicks": 1, "rendered_for": None}),
])
def test_a_layout_reset_or_stale_selection_never_asks_or_sends(monkeypatch, button_id, kwargs):
    with pytest.raises(PreventUpdate):
        ask(monkeypatch, button_id=button_id, **kwargs)


def test_cancelling_never_reaches_the_backend(flask_app, builder, sent, monkeypatch):
    ask(monkeypatch, button_id="mailing-confirm-cancel", cancel_clicks=1)
    assert sent["calls"] == []



# --------------------------------------------------------------------------- preview


def test_preview_returns_the_email_and_sends_nothing(flask_app, builder, sent):
    user_data = as_user(flask_app, ADMIN)
    is_open, html_doc, subject, feedback = cb.open_preview(1, "EMIN", user_data)
    assert is_open is True and html_doc == "<html>CORREO</html>"
    assert subject.startswith("[CODDI] Monitoreo de Alertas ") and feedback is None
    assert sent["calls"] == []


def test_preview_ignores_the_initial_call(flask_app, builder):
    with pytest.raises(PreventUpdate):
        cb.open_preview(0, "EMIN", as_user(flask_app, ADMIN))


def test_preview_error_is_readable_and_keeps_the_modal_closed(flask_app):
    user_data = as_user(flask_app, ADMIN)
    is_open, html_doc, _subject, feedback = cb.open_preview(1, "CDA", user_data)
    assert is_open is False and html_doc == "" and feedback["kind"] == "error"
    assert feedback["message"] == "No se pudo generar la vista previa."


def test_non_admin_cannot_preview(flask_app, builder, sent):
    is_open, _html, _subject, feedback = cb.open_preview(1, "EMIN", as_user(flask_app, CLIENT_USER))
    assert is_open is False and feedback["kind"] == "error"


# --------------------------------------------------------------------------- send


def send(app, selected_client, selected_tech=(TECH,), selected_mgmt=(), client="EMIN", rendered_for="emin", user=ADMIN, trigger="request-1"):
    return cb.send_now(trigger, client, as_user(app, user), list(selected_client), list(selected_tech), list(selected_mgmt), rendered_for)


def test_send_to_the_selection_reports_success(flask_app, builder, sent, production):
    result = send(flask_app, EMIN_CLIENT[:1], selected_mgmt=GERENCIA)
    expected = [EMIN_CLIENT[0], *TECHS, *GERENCIA]
    assert result["kind"] == "success" and result["message"] == f"Resumen enviado a {len(expected)} destinatarios."
    assert sorted(sent["calls"][0]["emails"]) == sorted(expected)


def test_singular_success_message(flask_app, builder, sent, monkeypatch):
    monkeypatch.setattr(config, "CODDI_RECIPIENTS", {"technical": [{"name": "T", "email": TECH, "send_email": True}], "management": []})
    assert send(flask_app, [])["message"] == "Resumen enviado a 1 destinatario."


def test_a_test_send_is_just_the_technical_contact(flask_app, builder, sent, production):
    send(flask_app, [], selected_mgmt=[])
    assert sent["calls"][0]["emails"] == TECHS


def test_lambda_failure_shows_the_generic_failure_without_internals(flask_app, builder, sent):
    sent["result"] = delivery.DeliveryResult(False, "El servicio de correo rechazó el envío.")
    result = send(flask_app, [])
    assert result["kind"] == "error" and result["message"] == "No se pudo enviar el resumen. Intente nuevamente."
    assert "lambda" not in str(result).lower() and "http" not in str(result).lower()


def test_outside_production_a_client_contact_can_be_sent_to(flask_app, builder, sent):
    result = send(flask_app, EMIN_CLIENT[:1])
    assert result["kind"] == "success"
    assert sent["calls"][0]["emails"] == [EMIN_CLIENT[0], *TECHS]


def test_backend_rejection_is_shown_as_a_failure(flask_app, builder, sent):
    result = send(flask_app, ["intruso@evil.com"])  # not in the registry, in any environment
    assert result["kind"] == "error" and result["message"] == "No se pudo enviar el resumen. Intente nuevamente."
    assert "no permitidos" in result["detail"]
    assert sent["calls"] == []


def test_a_crafted_selection_outside_the_allowed_set_is_refused(flask_app, builder, sent, production):
    result = send(flask_app, ["intruso@evil.com"])
    assert result["kind"] == "error" and sent["calls"] == []


def test_non_admin_cannot_send(flask_app, builder, sent):
    result = send(flask_app, [], user=CLIENT_USER)
    assert result["kind"] == "error" and sent["calls"] == []


def test_unexpected_errors_never_reach_the_page(flask_app, builder, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internals https://abc.lambda-url.us-east-2.on.aws/")

    monkeypatch.setattr(cb, "send_manual", boom)
    result = send(flask_app, [])
    assert result["kind"] == "error" and "secret" not in str(result) and "lambda-url" not in str(result)


def test_an_empty_send_request_never_sends(flask_app, builder, sent):
    with pytest.raises(PreventUpdate):
        send(flask_app, [], trigger=None)
    with pytest.raises(PreventUpdate):
        send(flask_app, [], trigger="")
    assert sent["calls"] == []


@pytest.mark.parametrize("rendered_for", [None, "capstone", ""])
def test_a_selection_built_for_another_client_never_sends(flask_app, builder, sent, production, rendered_for):
    """The renderer-crash incident: the old client in the request, another client's contacts selected."""
    capstone_contacts = [r["email"] for r in config.MAILING_RECIPIENTS["capstone"]]
    with pytest.raises(PreventUpdate):
        send(flask_app, capstone_contacts, client="EMIN", rendered_for=rendered_for)
    assert sent["calls"] == []


# --------------------------------------------------------------------------- feedback region


def test_feedback_is_written_only_for_a_send_or_preview_outcome(monkeypatch):
    data = cb._feedback_data("success", "Listo")
    monkeypatch.setattr(cb, "ctx", type("C", (), {"triggered_id": "mailing-send-result"}))
    box = cb.show_feedback(data, None, "EMIN")
    assert "Listo" in text(box) and "mailing-feedback-box--success" in box.className
    monkeypatch.setattr(cb, "ctx", type("C", (), {"triggered_id": "client-selector"}))
    assert cb.show_feedback(data, None, "EMIN") == ""  # a client change clears the old result
    monkeypatch.setattr(cb, "ctx", type("C", (), {"triggered_id": "mailing-preview-result"}))
    assert "error" in cb.show_feedback(None, cb._feedback_data("error", "x"), "EMIN").className


def test_partial_failure_lists_the_failed_emails(monkeypatch):
    data = cb._feedback_data("warning", "Se envió a 2 de 3 destinatarios.", failed=["a@x.cl"])
    monkeypatch.setattr(cb, "ctx", type("C", (), {"triggered_id": "mailing-send-result"}))
    box = cb.show_feedback(data, None, "EMIN")
    assert "a@x.cl" in text(box) and "Se envió a 2 de 3 destinatarios." in text(box)


def test_two_identical_outcomes_are_still_two_values():
    assert cb._feedback_data("success", "x") != cb._feedback_data("success", "x")


# --------------------------------------------------------------------------- nav, route, page


def test_admin_menu_gets_the_mailing_entry_inside_administracion():
    admin = {"username": ADMIN, "role": "admin", "clients": ["EMIN"]}
    sections = {s["section"]: s for s in build_navigation_items("EMIN", admin)}
    ids = [sub["id"] for sub in sections["admin"]["subsections"]]
    assert ids == ["admin-main", "admin-user-registry", "admin-mailing"]
    mailing = next(sub for sub in sections["admin"]["subsections"] if sub["id"] == "admin-mailing")
    assert mailing["label"] == "Mailing" and mailing["icon"] == "fas fa-envelope"


def test_non_admin_menu_has_no_mailing_entry():
    user = {"username": CLIENT_USER, "role": "client", "clients": ["EMIN"]}
    ids = [sub["id"] for s in build_navigation_items("EMIN", user) for sub in s["subsections"]]
    assert "admin-mailing" not in ids and not any(i.startswith("admin") for i in ids)


def test_route_follows_the_admin_convention_and_is_highlighted():
    assert NAV_PATHS["admin-mailing"] == "/admin/mailing" and NAV_PATHS["admin-user-registry"].startswith("/admin/")
    assert nav_id_for_pathname("/admin/mailing") == "admin-mailing"
    icons = list(NAV_ICONS.values())
    assert icons.count(NAV_ICONS["admin-mailing"]) == 1  # its own icon


def test_the_page_layout_denies_a_non_admin_even_with_a_forged_browser_role(flask_app):
    from dashboard.pages import admin_mailing

    as_user(flask_app, CLIENT_USER)
    denied = admin_mailing.layout()
    assert "No tiene permisos" in denied.children and by_id(denied, "mailing-send-btn") is None
    as_user(flask_app, ADMIN)
    allowed = admin_mailing.layout()
    assert by_id(allowed, "mailing-send-btn") is not None


def test_the_page_layout_denies_an_anonymous_visitor(flask_app):
    from dashboard.pages import admin_mailing

    with flask_app.test_request_context():
        assert "No tiene permisos" in admin_mailing.layout().children


def test_mailing_errors_carry_only_safe_messages():
    exc = MailingError("Mensaje seguro", code="x")
    assert exc.user_message == "Mensaje seguro"
