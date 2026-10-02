"""Validación de Avisos page layout (Conexión ERP).

Left panel: pending warnings for the globally-selected client (client-selector
in the navbar). Right panel: read-only Coddi fields + editable ERP fields.
Reactive logic lives in dashboard/callbacks/integration_avisos_callbacks.py —
client comes from the global selector, not a page-local dropdown (this page's
content is identical across clients, only the data feeding it changes).

The rejection collapse (erp-validator-rejection-collapse + its textarea/button)
and the two result alerts (erp-validator-success-alert / -error-alert) live in
the STATIC part of create_layout() rather than inside create_detail_form()'s
per-warning content, even though they're only meaningful once a warning is
selected. _handle_action's Outputs are those two alerts; when they only came
into existence dynamically (nested inside create_detail_form's returned tree),
State reads inside that callback (client-selector, user-info-store) came back
empty in practice — every other callback on this page has outputs that exist
in the initial static layout and doesn't show this. Keeping these elements
static (just visually inert until a warning is selected) sidesteps it.
"""
from __future__ import annotations

from src.i18n import t
from datetime import datetime, timezone

import dash_bootstrap_components as dbc
from dash import dcc, html

from src.data.erp_schemas import (
    CONDITION_LABEL_LABELS,
    SEVERITY_LABELS,
    SOURCE_LABELS,
    SYSTEM_LABELS,
    Severity,
    Warning,
)
from src.data.erp_write_operations import MAX_TITLE_LENGTH

_LABEL_COLOR = {"alerta": "warning", "anormal": "danger"}
_LABEL_BORDER = {"alerta": "border-warning", "anormal": "border-danger"}


def _age_label(warning: Warning) -> str:
    total_hours = int((datetime.now(timezone.utc) - warning.generated_at).total_seconds() // 3600)
    if total_hours < 48:
        return f"{total_hours}h"
    return f"{total_hours // 24}d"


def create_pending_item(warning: Warning, is_selected: bool = False) -> html.Div:
    """Compact card: asset id + criticality on one line, source + age on the next.
    Severity and system are omitted here (still shown in full in the detail
    panel) to keep the list scannable at normal zoom."""
    border = _LABEL_BORDER.get(warning.condition_label.value, "border-secondary")
    selected_classes = " shadow-sm" if is_selected else ""
    return html.Div(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(
                        [
                            html.Strong(warning.asset_id, className="small text-truncate", style={"maxWidth": "70%"}),
                            dbc.Badge(
                                CONDITION_LABEL_LABELS.get(warning.condition_label, warning.condition_label.value),
                                color=_LABEL_COLOR.get(warning.condition_label.value, "secondary"),
                                className="ms-1",
                                style={"fontSize": "0.65rem"},
                            ),
                        ],
                        className="d-flex justify-content-between align-items-center",
                    ),
                    html.Small(
                        f"{SOURCE_LABELS.get(warning.source, warning.source.value)} · {_age_label(warning)}",
                        className="text-muted",
                        style={"fontSize": "0.7rem"},
                    ),
                ],
                className="py-1 px-2",
            ),
            className=f"border-start {border} border-3{selected_classes}",
            style={"backgroundColor": "#eef6fc" if is_selected else None},
        ),
        id={"type": "erp-validator-select-pending", "index": warning.warning_id},
        n_clicks=0,
        className="mb-1",
        style={"cursor": "pointer"},
    )


def create_detail_placeholder(message: str) -> html.Div:
    return html.Div(
        [html.I(className="fas fa-hand-pointer fa-2x text-muted mb-3"), html.P(message, className="text-muted")],
        className="text-center py-5",
    )


def _context_section(warning: Warning) -> html.Div:
    return html.Div(
        [
            html.H4(
                [html.I(className="fas fa-info-circle me-2"), t("tab_integration_validacion_avisos.contexto_del_aviso")],
                className="text-primary mb-3 mt-2 pb-2 border-bottom",
            ),
            html.P(t("tab_integration_validacion_avisos.informacion_generada_por_el_agente_de"), className="text-muted mb-3"),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Small(t("tab_integration_validacion_avisos.fuente"), className="text-muted fw-bold d-block"),
                            html.P(SOURCE_LABELS.get(warning.source, warning.source.value), className="mb-0"),
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            html.Small(t("alerts_general.filter_system"), className="text-muted fw-bold d-block"),
                            html.P(SYSTEM_LABELS.get(warning.system, warning.system.value), className="mb-0"),
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            html.Small(t("tab_integration_validacion_avisos.id_del_activo"), className="text-muted fw-bold d-block"),
                            html.P(warning.asset_id, className="mb-0"),
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            html.Small(t("tab_integration_validacion_avisos.clasificacion"), className="text-muted fw-bold d-block"),
                            dbc.Badge(
                                CONDITION_LABEL_LABELS.get(warning.condition_label, warning.condition_label.value),
                                color=_LABEL_COLOR.get(warning.condition_label.value, "secondary"),
                            ),
                        ],
                        md=3,
                    ),
                    dbc.Col(
                        [
                            html.Small(t("tab_integration_validacion_avisos.generado"), className="text-muted fw-bold d-block"),
                            html.P(warning.generated_at.strftime("%d/%m/%Y %H:%M"), className="mb-0"),
                        ],
                        md=3,
                    ),
                ],
                className="g-2 mb-2",
            ),
            html.Small(
                t("tab_integration_validacion_avisos.evidencia_registro_s", len_warning_suppor=len(warning.supporting_data.get('raw_signal', []))),
                className="text-muted",
            ),
        ]
    )


def _erp_fields_section(warning: Warning) -> html.Div:
    return html.Div(
        [
            html.H4(
                [html.I(className="fas fa-paper-plane me-2"), t("tab_integration_validacion_avisos.datos_para_el_erp")],
                className="text-primary mb-3 mt-4 pb-2 border-bottom",
            ),
            html.P(t("tab_integration_validacion_avisos.revise_y_complete_la_informacion_antes"), className="text-muted mb-3"),
            html.Label(
                [html.I(className="fas fa-heading me-1"), t("tab_integration_validacion_avisos.titulo_short_text_sap_40_caracteres")],
                className="fw-bold mb-1",
            ),
            dbc.Input(
                id="erp-validator-field-title",
                type="text",
                maxLength=MAX_TITLE_LENGTH,
                value=warning.title,
                className="mb-3",
            ),
            html.Label(
                [html.I(className="fas fa-align-left me-1"), t("tab_integration_validacion_avisos.descripcion_long_text_sap")],
                className="fw-bold mb-1",
            ),
            dbc.Textarea(id="erp-validator-field-description", rows=4, value=warning.description, className="mb-3"),
            html.Label([html.I(className="fas fa-tools me-1"), t("tab_integration_validacion_avisos.accion_recomendada")], className="fw-bold mb-1"),
            dbc.Textarea(
                id="erp-validator-field-action", rows=3, value=warning.recommended_action, className="mb-3"
            ),
            html.Label([html.I(className="fas fa-sticky-note me-1"), t("tab_integration_validacion_avisos.notas_del_operador")], className="fw-bold mb-1"),
            dbc.Textarea(
                id="erp-validator-field-notes", rows=2, value=warning.operator_notes or "", className="mb-3"
            ),
            html.Label(
                [html.I(className="fas fa-tachometer-alt me-1"), t("tab_integration_validacion_avisos.severidad_prioridad_sap")],
                className="fw-bold mb-1",
            ),
            dcc.Dropdown(
                id="erp-validator-field-severity",
                options=[{"label": SEVERITY_LABELS[s], "value": s.value} for s in Severity],
                value=warning.severity.value,
                clearable=False,
                className="mb-3",
            ),
        ]
    )


def create_detail_form(warning: Warning) -> html.Div:
    """Per-warning content only. The rejection collapse and result alerts are
    intentionally NOT here — they live in the static create_layout() tree
    instead (see the module docstring note on _handle_action's outputs).
    The operator field also isn't here — it's a single session-scoped field
    near the top of the page (see _operator_bar / create_layout)."""
    return html.Div(
        [
            _context_section(warning),
            _erp_fields_section(warning),
            html.Div(
                [
                    dbc.Button(
                        [html.I(className="fas fa-paper-plane me-2"), t("tab_integration_validacion_avisos.aprobar_y_enviar_al_erp")],
                        id="erp-validator-btn-approve",
                        color="success",
                        size="lg",
                        className="me-3",
                    ),
                    dbc.Button(
                        [html.I(className="fas fa-times me-2"), t("tab_integration_validacion_avisos.rechazar")],
                        id="erp-validator-btn-reject",
                        color="danger",
                        outline=True,
                        size="lg",
                    ),
                ],
                className="d-flex mt-4 pt-3 border-top",
            ),
        ]
    )


def _operator_bar() -> dbc.Card:
    """Session-scoped operator name — entered once, reused for every approve/reject
    on this page (dashboard.layout's erp-validator-operator-store, storage_type='session').
    Anyone who can reach this tab can act; there's no separate identity check
    beyond typing a name here, since it's recorded as `validated_by`."""
    return dbc.Card(
        dbc.CardBody(
            dbc.Row(
                [
                    dbc.Col(
                        html.Label(
                            [html.I(className="fas fa-user me-1"), t("tab_integration_validacion_avisos.operador_obligatorio")],
                            className="fw-bold mb-0",
                        ),
                        width="auto",
                        className="d-flex align-items-center",
                    ),
                    dbc.Col(
                        [
                            dbc.Input(
                                id="erp-validator-operator-input",
                                type="text",
                                placeholder=t("tab_integration_validacion_avisos.ingrese_su_nombre"),
                                debounce=True,
                            ),
                            html.Small(id="erp-validator-operator-feedback", className="text-danger"),
                        ],
                        md=4,
                    ),
                ],
                className="g-2 align-items-center",
            ),
            className="py-2",
        ),
        className="shadow-sm mb-3",
    )


def create_layout() -> dbc.Container:
    return dbc.Container(
        [
            html.Div(
                [
                    html.H3(
                        [html.I(className="fas fa-clipboard-check me-2"), t("nav.service.integration-validacion-avisos")],
                        className="text-primary mb-2",
                    ),
                    html.P(
                        t("tab_integration_validacion_avisos.revise_edite_y_apruebe_los_avisos"),
                        className="text-muted",
                    ),
                ],
                className="mb-4",
            ),
            dcc.Store(id="erp-validator-selected-warning-id"),
            _operator_bar(),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.H5(
                                        [html.I(className="fas fa-list me-2"), t("tab_integration_validacion_avisos.avisos_pendientes")],
                                        className="mb-0",
                                    ),
                                    className="bg-primary text-white",
                                ),
                                dbc.CardBody(
                                    dcc.Loading(
                                        html.Div(
                                            id="erp-validator-warning-list",
                                            style={"maxHeight": "70vh", "overflowY": "auto"},
                                        ),
                                        type="circle",
                                    ),
                                    className="p-2",
                                ),
                            ],
                            className="shadow-sm h-100",
                        ),
                        md=4,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.H5(
                                        [html.I(className="fas fa-clipboard-check me-2"), t("tab_integration_validacion_avisos.detalle_del_aviso")],
                                        className="mb-0",
                                    ),
                                    className="bg-light",
                                ),
                                dbc.CardBody(
                                    [
                                        dcc.Loading(
                                            html.Div(
                                                id="erp-validator-form-content",
                                                children=create_detail_placeholder(t("tab_integration_validacion_avisos.seleccione_un_aviso_pendiente")),
                                            ),
                                            type="circle",
                                        ),
                                        # Static (present from initial layout, not nested inside
                                        # create_detail_form's dynamic children) — see module docstring.
                                        dbc.Collapse(
                                            [
                                                html.Label(
                                                    [
                                                        html.I(className="fas fa-comment-alt me-1"),
                                                        t("tab_integration_validacion_avisos.motivo_de_rechazo"),
                                                    ],
                                                    className="fw-bold mb-1 mt-3 text-danger",
                                                ),
                                                dbc.Textarea(
                                                    id="erp-validator-field-rejection",
                                                    rows=2,
                                                    placeholder=t("tab_integration_validacion_avisos.indique_por_que_se_rechaza_este"),
                                                    className="border-danger",
                                                ),
                                                dbc.Button(
                                                    t("tab_integration_validacion_avisos.confirmar_rechazo"),
                                                    id="erp-validator-btn-confirm-reject",
                                                    color="danger",
                                                    className="mt-2",
                                                ),
                                            ],
                                            id="erp-validator-rejection-collapse",
                                            is_open=False,
                                        ),
                                        dbc.Alert(
                                            id="erp-validator-success-alert",
                                            color="success",
                                            is_open=False,
                                            dismissable=True,
                                            className="mt-3",
                                        ),
                                        dbc.Alert(
                                            id="erp-validator-error-alert",
                                            color="danger",
                                            is_open=False,
                                            dismissable=True,
                                            className="mt-3",
                                        ),
                                    ]
                                ),
                            ],
                            className="shadow-sm h-100",
                        ),
                        md=8,
                    ),
                ],
                className="gx-3",
            ),
        ],
        fluid=True,
        className="p-4",
    )
