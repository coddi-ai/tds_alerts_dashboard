"""Admin-only "Mailing" page: manual send of the alert summary email.

The layout is a fixed skeleton: every component the callbacks read or write exists from the
start, and `dashboard/callbacks/mailing_callbacks.py` fills it for the dashboard's selected
client from `src.mailing.get_mailing_context`. The page has no client selector of its own and
decides nothing about who may receive the email: the backend validates the selection.
"""

from dash import dcc, html
import dash_bootstrap_components as dbc

from src.i18n import t

# Recipient groups in display order; the id suffix is shared with the callbacks.
GROUP_IDS = ("client", "technical", "management")


def group_ids(group: str) -> dict:
    return {
        "checklist": f"mailing-sel-{group}",
        "title": f"mailing-group-title-{group}",
        "count": f"mailing-group-count-{group}",
        "heading": f"mailing-group-heading-{group}",
        "slot": f"mailing-group-slot-{group}",
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
    return html.Div(
        [
            html.Div(
                [
                    html.Span("", id=ids["title"], className="mailing-group-name"),
                    html.Span("", id=ids["count"], className="mailing-group-count"),
                ],
                id=ids["heading"],
                className="mailing-group-header",
            ),
            html.Div(create_checklist(group, [], []), id=ids["slot"]),
        ],
        className="mailing-group",
        role="group",
        **{"aria-labelledby": ids["heading"]},
    )


def create_layout() -> html.Div:
    return html.Div(
        [
            dcc.Store(id="mailing-page-load", data=True),
            # Outcomes of a send / a preview; `show_feedback` is the only writer of the feedback region.
            dcc.Store(id="mailing-send-result"),
            # The client the visible recipient selection was built for (see send_now).
            dcc.Store(id="mailing-rendered-for"),
            dcc.Store(id="mailing-preview-result"),
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
            # Shown instead of the card when the client has no mailing configuration.
            html.Div(id="mailing-unavailable", className="mailing-unavailable", role="status"),
            html.Div(
                [
                    # Report card
                    html.Section(
                        [
                            html.H5("", id="mailing-report-title", className="mailing-card-title"),
                            html.P("", id="mailing-report-subtitle", className="mailing-card-subtitle"),
                            html.Div(
                                [_detail("mailing.detail.subject", "mailing-subject"),
                                 _detail("mailing.detail.period", "mailing-period")],
                                className="mailing-details",
                            ),
                        ],
                        className="mailing-card",
                    ),
                    # Recipients: the only recipient control
                    html.Section(
                        [
                            html.Div(
                                [
                                    html.H5(t("mailing.recipients.heading"), className="mailing-card-title mb-0"),
                                    html.Span("", id="mailing-counter", className="mailing-counter"),
                                ],
                                className="mailing-recipients-header",
                            ),
                            html.Div(
                                [_group(group) for group in GROUP_IDS],
                                id="mailing-recipients",
                                className="mailing-recipients",
                            ),
                            html.P(t("mailing.recipients.help"), className="mailing-help"),
                        ],
                        className="mailing-card",
                    ),
                    # Action bar
                    html.Div(
                        [
                            html.Div("", id="mailing-send-summary", className="mailing-send-summary"),
                            html.Div(
                                [
                                    html.Button(
                                        t("mailing.button.preview"),
                                        id="mailing-preview-btn",
                                        type="button",
                                        className="mailing-btn mailing-btn--secondary",
                                        n_clicks=0,
                                    ),
                                    html.Button(
                                        t("mailing.button.send"),
                                        id="mailing-send-btn",
                                        type="button",
                                        className="mailing-btn mailing-btn--primary",
                                        n_clicks=0,
                                    ),
                                ],
                                className="mailing-buttons",
                            ),
                        ],
                        className="mailing-actions",
                    ),
                    # Announced to screen readers when a send finishes.
                    html.Div("", id="mailing-feedback", className="mailing-feedback", role="status",
                             **{"aria-live": "polite"}),
                ],
                id="mailing-main",
            ),
            # Preview: the email renders in a fully sandboxed iframe (no scripts, no same-origin).
            dbc.Modal(
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
            ),
        ],
        className="mailing-page",
    )
