"""Callbacks of the admin "Mailing" page (see dashboard/tabs/tab_mailing.py).

The page decides nothing: every value shown comes from `src.mailing.get_mailing_context`, the
preview from `build_preview` and the send from `send_manual`, and each of those re-checks the
admin role on the server. The callbacks are plain module-level functions (registered at the
bottom) so they can be called directly in tests.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

import itertools
import time

import dash
from dash import Input, Output, State, ctx, html
from dash.exceptions import PreventUpdate

from dashboard.tabs.tab_mailing import GROUP_IDS, create_checklist, group_ids
from src.i18n import t
from src.mailing import (
    MailingError,
    build_preview,
    config as mailing_config,
    get_mailing_context,
    send_manual,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_STAMPS = itertools.count(1)

GROUP_KEYS = {
    "client": mailing_config.GROUP_CLIENT,
    "technical": mailing_config.GROUP_TECHNICAL,
    "management": mailing_config.GROUP_MANAGEMENT,
}


# --------------------------------------------------------------------------- helpers


def _tag(text: str, kind: str) -> html.Span:
    return html.Span(text, className=f"mailing-tag mailing-tag--{kind}")


def _option(recipient: dict) -> dict:
    """One checkbox row: bold name, email, and its text tags. Clicking any of it toggles."""
    tags: List = []
    group = recipient["group"]
    if group == mailing_config.GROUP_CLIENT and not recipient["send_email"]:
        tags.append(_tag(t("mailing.tag.no_auto"), "muted"))
    if group == mailing_config.GROUP_TECHNICAL:
        tags.append(_tag(t("mailing.tag.always"), "technical"))
    label = html.Span(
        [
            html.Span(
                [html.Span(recipient["name"], className="mailing-name"),
                 html.Span(recipient["email"], className="mailing-email")],
                className="mailing-identity",
            ),
            html.Span(tags, className="mailing-tags"),
        ],
        className="mailing-row",
    )
    return {
        "label": label,
        "value": recipient["email"],
        # Only Técnico is locked (cannot be removed); the environment disables nothing.
        "disabled": bool(recipient["disabled"] or recipient["locked"]),
    }


def _selected(*value_lists: Optional[Iterable[str]]) -> List[str]:
    emails: List[str] = []
    for values in value_lists:
        emails += list(values or [])
    return list(dict.fromkeys(emails))


def _plural(n: int, one_key: str, many_key: str) -> str:
    return t(one_key) if n == 1 else t(many_key, n=n)


def _environment_label(context: dict) -> str:
    return t("mailing.env.production") if context.get("is_production") else t("mailing.env.development")


def _chips(context: dict) -> list:
    return [
        html.Span(t("mailing.chip.client", client=context["client_label"]), className="mailing-chip mailing-chip--client"),
        html.Span(t("mailing.chip.environment", environment=_environment_label(context)),
                  className="mailing-chip mailing-chip--env"),
    ]


# --------------------------------------------------------------------------- render


def _unavailable(message: str, client_label: Optional[str] = None):
    chips = [] if client_label is None else [
        html.Span(t("mailing.chip.client", client=client_label), className="mailing-chip mailing-chip--client")
    ]
    return (chips, message, {"display": "none"}, "", "", "", "", "", "", "",
            *[create_checklist(g, [], []) for g in GROUP_IDS], None)


def render_context(client, user_data, _page_load):
    """Fill the page for the dashboard's current client. Returns one value per Output below."""
    if not client:
        return _unavailable(t("mailing.no_client"))
    try:
        context = get_mailing_context(client, user_data)
    except MailingError as exc:
        logger.warning("mailing page: context refused (%s)", exc.code)
        return _unavailable(t("mailing.forbidden") if exc.code == "forbidden" else t("mailing.context_error"))

    if not context["configured"]:
        return _unavailable(t("mailing.not_configured"), context["client_label"])

    by_group = {key: [r for r in context["recipients"] if r["group"] == group] for key, group in GROUP_KEYS.items()}
    titles = [
        t("mailing.group.client", client=context["client_label"]),
        t("mailing.group.technical"),
        t("mailing.group.management"),
    ]
    checklists = [
        create_checklist(
            key,
            [_option(r) for r in by_group[key]],
            [r["email"] for r in by_group[key] if r["selected_by_default"]],
        )
        for key in GROUP_IDS
    ]
    return (
        _chips(context),
        "",
        {"display": "block"},
        context["report_title"],
        f"{context['client_label']} · {context['schedule_description']}.",
        context["subject"],
        context["period"]["text"],
        *titles,
        *checklists,
        mailing_config.normalize_client(client),
    )


# --------------------------------------------------------------------------- counters


def update_counters(client_options, client_value, tech_options, tech_value, mgmt_options, mgmt_value):
    """Live counters: heading, per group header and the action bar sentence."""
    groups = [(client_options, client_value), (tech_options, tech_value), (mgmt_options, mgmt_value)]
    group_counts = [t("mailing.count", selected=len(value or []), total=len(options or [])) for options, value in groups]
    selected = len(_selected(client_value, tech_value, mgmt_value))
    total = sum(len(options or []) for options, _ in groups)
    return (
        t("mailing.recipients.counter", n=selected, total=total),
        *group_counts,
        _plural(selected, "mailing.action.summary_one", "mailing.action.summary_many"),
    )


# --------------------------------------------------------------------------- preview


def open_preview(n_clicks, client, user_data):
    """Open the email as it would be sent. Sends nothing."""
    if not n_clicks:
        raise PreventUpdate
    try:
        preview = build_preview(client, user_data)
    except MailingError as exc:
        return False, "", "", _feedback_data("error", t("mailing.preview_error"), detail=exc.user_message)
    except Exception:  # noqa: BLE001 - the page must never show internals
        logger.exception("mailing page: preview failed")
        return False, "", "", _feedback_data("error", t("mailing.preview_error"))
    return True, preview["html"], preview["subject"], None


# --------------------------------------------------------------------------- send


def _feedback_data(kind: str, message: str, detail: Optional[str] = None, failed: Optional[List[str]] = None) -> dict:
    """What a send/preview outcome stores. `stamp` makes every outcome a new value, so the same
    message twice in a row still reaches the page."""
    return {"kind": kind, "message": message, "detail": detail, "failed": failed or [], "stamp": f"{time.time_ns()}-{next(_STAMPS)}"}


def show_feedback(send_result, preview_result, _client):
    """The one writer of the feedback region: a send or preview outcome, or nothing when the
    client changes (an old result must not describe another client)."""
    data = {"mailing-send-result": send_result, "mailing-preview-result": preview_result}.get(ctx.triggered_id)
    if not data:
        return ""
    body = [html.Div(data["message"], className="mailing-feedback-message")]
    if data.get("detail"):
        body.append(html.Div(data["detail"], className="mailing-feedback-detail"))
    if data.get("failed"):
        body.append(html.Ul([html.Li(email) for email in data["failed"]], className="mailing-feedback-list"))
    return html.Div(body, className=f"mailing-feedback-box mailing-feedback-box--{data['kind']}")


def send_now(n_clicks, client, user_data, client_value, tech_value, mgmt_value, rendered_for):
    """Send to the selected recipients. The backend validates the selection.

    Only a real click for the client on screen sends. A click count of 0, or a selection that was
    not built for this client (a layout reset, a stale page), is ignored: a send reaches real people.
    """
    if not n_clicks or rendered_for != mailing_config.normalize_client(client):
        raise PreventUpdate
    selected = _selected(client_value, tech_value, mgmt_value)
    try:
        result = send_manual(client, selected, user_data)
    except MailingError as exc:
        return _feedback_data("error", t("mailing.send.failure"), detail=exc.user_message)
    except Exception:  # noqa: BLE001 - never show a stack trace or a URL
        logger.exception("mailing page: unexpected send error")
        return _feedback_data("error", t("mailing.send.failure"))

    total = result["total"]
    ok = result["sent"]
    failed = [r["email"] for r in result["recipients"] if r["status"] != "sent"]
    if not failed:
        return _feedback_data("success", _plural(total, "mailing.send.success_one", "mailing.send.success_many"))
    if ok:
        return _feedback_data("warning", t("mailing.send.partial", ok=ok, n=total), failed=failed)
    return _feedback_data("error", t("mailing.send.failure"))


# --------------------------------------------------------------------------- registration


def register_mailing_callbacks(app: dash.Dash) -> None:
    render_outputs = [
        Output("mailing-chips", "children"),
        Output("mailing-unavailable", "children"),
        Output("mailing-main", "style"),
        Output("mailing-report-title", "children"),
        Output("mailing-report-subtitle", "children"),
        Output("mailing-subject", "children"),
        Output("mailing-period", "children"),
        *[Output(group_ids(g)["title"], "children") for g in GROUP_IDS],
        *[Output(group_ids(g)["slot"], "children") for g in GROUP_IDS],
        Output("mailing-rendered-for", "data"),
    ]
    app.callback(
        render_outputs,
        Input("client-selector", "value"),
        State("user-info-store", "data"),
        Input("mailing-page-load", "data"),
    )(lambda client, user_data, page_load: render_context(client, user_data, page_load))

    checklist_inputs = []
    for g in GROUP_IDS:
        checklist_inputs += [Input(group_ids(g)["checklist"], "options"), Input(group_ids(g)["checklist"], "value")]
    app.callback(
        Output("mailing-counter", "children"),
        *[Output(group_ids(g)["count"], "children") for g in GROUP_IDS],
        Output("mailing-send-summary", "children"),
        *checklist_inputs,
    )(update_counters)

    app.callback(
        Output("mailing-preview-modal", "is_open"),
        Output("mailing-preview-frame", "srcDoc"),
        Output("mailing-preview-subject", "children"),
        Output("mailing-preview-result", "data"),
        Input("mailing-preview-btn", "n_clicks"),
        State("client-selector", "value"),
        State("user-info-store", "data"),
        prevent_initial_call=True,
    )(open_preview)

    app.callback(
        Output("mailing-feedback", "children"),
        Input("mailing-send-result", "data"),
        Input("mailing-preview-result", "data"),
        Input("client-selector", "value"),
    )(show_feedback)

    app.callback(
        Output("mailing-send-result", "data"),
        Input("mailing-send-btn", "n_clicks"),
        State("client-selector", "value"),
        State("user-info-store", "data"),
        State(group_ids("client")["checklist"], "value"),
        State(group_ids("technical")["checklist"], "value"),
        State(group_ids("management")["checklist"], "value"),
        State("mailing-rendered-for", "data"),
        prevent_initial_call=True,
        # While the request runs: both buttons and every checkbox are disabled and the primary
        # button says "Enviando…". This is what stops a double click.
        running=[
            (Output("mailing-send-btn", "disabled"), True, False),
            (Output("mailing-preview-btn", "disabled"), True, False),
            (Output("mailing-send-btn", "children"), t("mailing.button.sending"), t("mailing.button.send")),
            (Output("mailing-recipients", "className"), "mailing-recipients mailing-busy", "mailing-recipients"),
            (Output("mailing-recipients", "aria-busy"), "true", "false"),
        ],
    )(send_now)
