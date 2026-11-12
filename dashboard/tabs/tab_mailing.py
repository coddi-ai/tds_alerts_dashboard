"""Admin-only "Mailing" page: manual send of the alert summary email (tickets 03 and 03.1).

The layout is a fixed skeleton: every component the callbacks read or write exists from the
start, and `dashboard/callbacks/mailing_callbacks.py` fills it for the dashboard's selected
client from `src.mailing.get_mailing_context`. The page has no client selector of its own and
decides nothing about who may receive the email: the backend validates the selection.

Two columns on a wide screen: the recipients card on the left and a sticky summary card (report,
schedule, subject, period, counts, buttons) on the right; they stack on a narrow one.
"""

from dash import dcc, html
import dash_bootstrap_components as dbc

from src.i18n import t

# Recipient groups in display order; the id suffix is shared with the callbacks.
GROUP_IDS = ("client", "technical", "management")
# Groups with a "select all" button. Coddi Técnico has none: all its rows are locked.
BUTTON_GROUPS = ("client", "management")


def group_ids(group: str) -> dict:
    return {
        "checklist": f"mailing-sel-{group}",
        "title": f"mailing-group-title-{group}",
        "count": f"mailing-group-count-{group}",
        "heading": f"mailing-group-heading-{group}",
        "slot": f"mailing-group-slot-{group}",
        "button": f"mailing-group-btn-{group}",
        "summary": f"mailing-sum-{group}",
    }


def _detail(label_key: str, value_id: str) -> html.Div:
    return html.Div(
        [
            html.Div(t(label_key), className="mailing-detail-label"),
            html.Div("", id=value_id, className="mailing-detail-value"),
        ],
        className="mailing-detail",
    )


def create_checklist(group: str, options: list, value: list) -> dcc.Checklist:
    """The checkboxes of one group.

    A new checklist is mounted for every client instead of updating `options` in place: Dash 4's
    renderer crashes (and resets the whole layout) when the options of a checklist, whose labels
    are components, change from one non-empty list to another.
    """
    return dcc.Checklist(
        id=group_ids(group)["checklist"],
        options=options,
        value=value,
        className="mailing-checklist",
        labelClassName="mailing-option",
        inputClassName="mailing-checkbox",
    )


def _group(group: str) -> html.Div:
    ids = group_ids(group)
    header = [
        html.Span("", id=ids["title"], className="mailing-group-name"),
        html.Span("", id=ids["count"], className="mailing-group-count"),
    ]
    if group in BUTTON_GROUPS:
        # A real button: label and aria-label follow the selection (see update_counters).
        header.append(
            html.Button("", id=ids["button"], type="button", n_clicks=0, className="mailing-group-btn",
                        style={"display": "none"})
        )
    return html.Div(
        [
            html.Div(header, id=ids["heading"], className="mailing-group-header"),
            html.Div(create_checklist(group, [], []), id=ids["slot"]),
        ],
        className="mailing-group",
        role="group",
        **{"aria-labelledby": ids["heading"]},
    )


def _summary_box(group: str) -> html.Div:
    return html.Div(
        [
            html.Span(t(f"mailing.summary.{group}"), className="mailing-sum-label"),
            html.Span("0", id=group_ids(group)["summary"], className="mailing-sum-count"),
        ],
        className=f"mailing-sum-box mailing-sum-box--{group}",
    )


def _recipients_card() -> html.Section:
    return html.Section(
        [
            html.Div(
                [
                    html.H5(t("mailing.recipients.heading"), className="mailing-card-title mb-0"),
                    html.Span("", id="mailing-counter", className="mailing-counter"),
                ],
                className="mailing-recipients-header",
            ),
            # One line under the heading; it changes with the environment.
            html.P("", id="mailing-help", className="mailing-help"),
            html.Div(
                [_group(group) for group in GROUP_IDS],
                id="mailing-recipients",
                className="mailing-recipients",
            ),
        ],
        className="mailing-card mailing-card--recipients",
    )


def _summary_card() -> html.Aside:
    return html.Aside(
        [
            html.H5("", id="mailing-report-title", className="mailing-card-title"),
            html.P("", id="mailing-report-subtitle", className="mailing-card-subtitle"),
            html.Div(
                [_detail("mailing.detail.subject", "mailing-subject"),
                 _detail("mailing.detail.period", "mailing-period")],
                className="mailing-details",
            ),
            html.Div("", id="mailing-send-summary", className="mailing-send-summary"),
            html.Div([_summary_box(group) for group in GROUP_IDS], className="mailing-breakdown"),
            html.Div(
                [
                    html.Button(
                        t("mailing.button.send"),
                        id="mailing-send-btn",
                        type="button",
                        className="mailing-btn mailing-btn--primary",
                        n_clicks=0,
                    ),
                    html.Button(
                        t("mailing.button.preview"),
                        id="mailing-preview-btn",
                        type="button",
                        className="mailing-btn mailing-btn--secondary",
                        n_clicks=0,
                    ),
                ],
                className="mailing-buttons",
            ),
            html.P(t("mailing.note"), className="mailing-note"),
            # Announced to screen readers when a send finishes.
            html.Div("", id="mailing-feedback", className="mailing-feedback", role="status",
                     **{"aria-live": "polite"}),
        ],
        className="mailing-card mailing-card--summary",
        **{"aria-labelledby": "mailing-report-title"},
    )


def _preview_modal() -> dbc.Modal:
    # The email renders in a fully sandboxed iframe (no scripts, no same-origin).
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(t("mailing.modal.title"), id="mailing-modal-title"),
                            close_button=True),
            dbc.ModalBody(
                [
                    html.Div("", id="mailing-preview-subject", className="mailing-preview-subject"),
                    html.Iframe(
                        id="mailing-preview-frame",
                        srcDoc="",
                        sandbox="",
                        title=t("mailing.modal.frame_title"),
                        className="mailing-preview-frame",
                    ),
                ]
            ),
        ],
        id="mailing-preview-modal",
        size="xl",
        scrollable=True,
        is_open=False,
        keyboard=True,
        labelledby="mailing-modal-title",
    )


def _confirm_modal() -> dbc.Modal:
    """Asked only outside production when a Cliente contact is selected (a real email to a client).

    Esc, the backdrop and `Cancelar` close it without sending; focus starts on `Cancelar`
    (clientside callback) and returns to `Enviar Ahora` on close. react-bootstrap's modal traps focus.
    """
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(t("mailing.confirm.title"), id="mailing-confirm-title"),
                            close_button=True),
            dbc.ModalBody(
                [
                    # Text label included: the amber background is never the only signal.
                    html.Div(t("mailing.confirm.notice"), className="mailing-confirm-notice"),
                    html.Ul([], id="mailing-confirm-counts", className="mailing-confirm-counts"),
                ]
            ),
            dbc.ModalFooter(
                [
                    html.Button(t("mailing.confirm.cancel"), id="mailing-confirm-cancel", type="button",
                                n_clicks=0, className="mailing-btn mailing-btn--secondary"),
                    html.Button("", id="mailing-confirm-send", type="button", n_clicks=0,
                                className="mailing-btn mailing-btn--primary"),
                ],
                className="mailing-confirm-footer",
            ),
        ],
        id="mailing-confirm-modal",
        is_open=False,
        keyboard=True,
        backdrop=True,
        centered=True,
        labelledby="mailing-confirm-title",
    )


def create_layout() -> html.Div:
    return html.Div(
        [
            dcc.Store(id="mailing-page-load", data=True),
            # Outcomes of a send / a preview; `show_feedback` is the only writer of the feedback region.
            dcc.Store(id="mailing-send-result"),
            # A request to send (written by `request_send` once any confirmation is done).
            dcc.Store(id="mailing-send-trigger"),
            # The client the visible recipient selection was built for (see send_now).
            dcc.Store(id="mailing-rendered-for"),
            dcc.Store(id="mailing-preview-result"),
            dcc.Store(id="mailing-focus-dummy"),
            html.Div(
                [
                    html.Div(
                        [
                            html.H4(
                                [html.I(className="fas fa-envelope me-2", **{"aria-hidden": "true"}), t("mailing.title")],
                                className="text-primary mb-1",
                            ),
                            html.P(t("mailing.subtitle"), className="text-muted mb-0"),
                        ],
                        className="mailing-title-block",
                    ),
                    html.Div(id="mailing-chips", className="mailing-chips"),
                    # "Fuentes de Datos" button + popover (dashboard/callbacks/data_sources_callbacks.py).
                    html.Div(id="mailing-source-status", className="ds-header-slot"),
                ],
                className="mailing-header",
            ),
            # Shown instead of the cards when the client has no mailing configuration.
            html.Div(id="mailing-unavailable", className="mailing-unavailable", role="status"),
            # Recipients first in the DOM: on a narrow screen they stack above the summary.
            html.Div([_recipients_card(), _summary_card()], id="mailing-main", className="mailing-grid"),
            _preview_modal(),
            _confirm_modal(),
        ],
        className="mailing-page",
    )
