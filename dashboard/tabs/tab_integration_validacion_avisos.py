"""Validación de Avisos page layout (Conexión ERP).

Left column: pending warnings for the globally-selected client (client-selector in the
navbar), searchable and filterable. Right column: the selected warning - read-only Coddi
context, editable ERP fields, and an action bar pinned to the bottom of the panel.
Reactive logic lives in dashboard/callbacks/integration_avisos_callbacks.py — client comes
from the global selector, not a page-local dropdown (this page's content is identical across
clients, only the data feeding it changes). Chip colors come from dashboard/components/
erp_chips.py, layout and shape from assets/erp_avisos.css.

The action bar (Rechazar… / Aprobar y Enviar al ERP), the rejection collapse and the two
result alerts live in the STATIC part of create_layout() rather than inside
create_detail_form()'s per-warning content, even though they're only meaningful once a
warning is selected. _handle_action's Outputs are those two alerts; when they only came
into existence dynamically (nested inside create_detail_form's returned tree), State reads
inside that callback (client-selector, user-info-store) came back empty in practice — every
other callback on this page has outputs that exist in the initial static layout and doesn't
show this. Keeping these elements static (the action bar just hidden until a warning is
selected) sidesteps it, and lets the operator field drive the buttons' disabled state without
an Output on a component that is re-created on every selection.
"""
from __future__ import annotations

from datetime import datetime, timezone

import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard.components.erp_chips import classification_chip, severity_chip, severity_label
from src.data.erp_schemas import (
    CONDITION_LABEL_LABELS,
    SOURCE_LABELS,
    SYSTEM_LABELS,
    ConditionLabel,
    Severity,
    Warning,
)
from src.data.erp_write_operations import MAX_TITLE_LENGTH
from src.i18n import t

# Segmented filter of the pending list: every value except "all" is a ConditionLabel value.
FILTER_ALL = "all"
FILTER_LABELS = (ConditionLabel.anormal.value, ConditionLabel.alerta.value)


def _age_label(warning: Warning) -> str:
    total_hours = int((datetime.now(timezone.utc) - warning.generated_at).total_seconds() // 3600)
    if total_hours < 48:
        return t("tab_integration_validacion_avisos.hace_horas", n=total_hours)
    return t("tab_integration_validacion_avisos.hace_dias", n=total_hours // 24)


def title_counter_text(value: str | None) -> str:
    return f"{len(value or '')} / {MAX_TITLE_LENGTH}"


def title_counter_class(value: str | None) -> str:
    size = len(value or "")
    if size > MAX_TITLE_LENGTH:
        return "erp-counter erp-counter--over"
    if size == MAX_TITLE_LENGTH:
        return "erp-counter erp-counter--full"
    return "erp-counter"


def operator_message(operator: str | None) -> html.Span:
    """Inline state of the operator field: the error while it's empty, 'Listo' once it has a name."""
    if (operator or "").strip():
        return html.Span(
            [html.I(className="fas fa-check-circle", **{"aria-hidden": "true"}), t("tab_integration_validacion_avisos.listo")],
            className="erp-field-msg erp-field-msg--ok",
        )
    return html.Span(
        [
            html.I(className="fas fa-exclamation-circle", **{"aria-hidden": "true"}),
            t("integration_avisos_callbacks.debe_indicar_el_nombre_del_operador"),
        ],
        className="erp-field-msg erp-field-msg--error",
    )


def create_pending_item(warning: Warning, is_selected: bool = False) -> html.Button:
    """Neutral card as a real button: asset id + severity chip on one line, then
    'Clasificación · Fuente · Sistema' and the age. The selected one gets a single blue border and a
    light-blue fill; no card carries a severity-colored border (ui_notes_improved.md §2)."""
    meta = " · ".join(
        (
            CONDITION_LABEL_LABELS.get(warning.condition_label, warning.condition_label.value),
            SOURCE_LABELS.get(warning.source, warning.source.value),
            SYSTEM_LABELS.get(warning.system, warning.system.value),
        )
    )
    return html.Button(
        [
            html.Span(
                [html.Strong(warning.asset_id, className="erp-pending-item__asset"), severity_chip(warning.severity)],
                className="erp-pending-item__top",
            ),
            html.Span(meta, className="erp-pending-item__meta"),
            html.Span(_age_label(warning), className="erp-pending-item__age"),
        ],
        id={"type": "erp-validator-select-pending", "index": warning.warning_id},
        n_clicks=0,
        type="button",
        className="erp-pending-item is-selected" if is_selected else "erp-pending-item",
        **({"aria-current": "true"} if is_selected else {}),
    )


def create_detail_placeholder(message: str) -> html.Div:
    return html.Div(
        [html.I(className="fas fa-hand-pointer fa-2x", **{"aria-hidden": "true"}), html.P(message, className="mb-0")],
        className="erp-empty erp-empty--detail",
        role="status",
    )


def _ai_tag() -> html.Span:
    return html.Span(
        [html.I(className="fas fa-robot", **{"aria-hidden": "true"}), t("tab_integration_validacion_avisos.sugerido_por_ia")],
        className="erp-ai-tag",
    )


def _field_label(text: str, html_for: str, *, tag: html.Span | None = None, extra: html.Span | None = None) -> html.Div:
    return html.Div(
        [html.Label(text, htmlFor=html_for, className="erp-field-label"), tag, extra],
        className="erp-field-head",
    )


def _detail_header(warning: Warning) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.H2(warning.asset_id, className="erp-detail__asset"),
                    classification_chip(warning.condition_label),
                    severity_chip(warning.severity),
                ],
                className="erp-detail__title",
            ),
            html.Span(
                t(
                    "tab_integration_validacion_avisos.generado_el",
                    fecha=warning.generated_at.strftime("%d/%m/%Y %H:%M"),
                ),
                className="erp-detail__generated",
            ),
        ],
        className="erp-detail__header",
    )


def _context_item(label: str, value: str) -> html.Div:
    return html.Div([html.Dt(label), html.Dd(value)], className="erp-context__item")


def _context_section(warning: Warning) -> html.Section:
    evidence = len(warning.supporting_data.get("raw_signal", []))
    return html.Section(
        [
            html.Div(
                [
                    html.H3(t("tab_integration_validacion_avisos.contexto_del_aviso"), className="erp-section__title"),
                    html.Span(
                        [html.I(className="fas fa-lock", **{"aria-hidden": "true"}), t("tab_integration_validacion_avisos.generado_por_ia_solo_lectura")],
                        className="erp-readonly-tag",
                    ),
                ],
                className="erp-section__head",
            ),
            html.Dl(
                [
                    _context_item(
                        t("tab_integration_validacion_avisos.fuente"), SOURCE_LABELS.get(warning.source, warning.source.value)
                    ),
                    _context_item(
                        t("alerts_general.filter_system"), SYSTEM_LABELS.get(warning.system, warning.system.value)
                    ),
                    _context_item(
                        t("tab_integration_validacion_avisos.clasificacion"),
                        CONDITION_LABEL_LABELS.get(warning.condition_label, warning.condition_label.value),
                    ),
                    _context_item(
                        t("tab_integration_validacion_avisos.evidencia"),
                        t("tab_integration_validacion_avisos.n_registros", n=evidence),
                    ),
                ],
                className="erp-context",
            ),
        ],
        className="erp-section",
    )


def _erp_fields_section(warning: Warning) -> html.Section:
    severity_options = [{"label": severity_label(s), "value": s.value} for s in Severity]
    return html.Section(
        [
            html.Div(
                [
                    html.H3(t("tab_integration_validacion_avisos.datos_para_el_erp"), className="erp-section__title"),
                    html.P(t("tab_integration_validacion_avisos.revise_y_complete_la_informacion_antes"), className="erp-section__hint"),
                ],
                className="erp-section__head erp-section__head--stack",
            ),
            _field_label(
                t("tab_integration_validacion_avisos.titulo_short_text_sap"),
                "erp-validator-field-title",
                extra=html.Span(
                    title_counter_text(warning.title),
                    id="erp-validator-title-counter",
                    className=title_counter_class(warning.title),
                    **{"aria-live": "polite"},
                ),
            ),
            dbc.Input(
                id="erp-validator-field-title",
                type="text",
                maxLength=MAX_TITLE_LENGTH,
                value=warning.title,
                autoComplete="off",
                className="erp-input mb-3",
            ),
            _field_label(
                t("tab_integration_validacion_avisos.descripcion_long_text_sap").strip(),
                "erp-validator-field-description",
                tag=_ai_tag(),
            ),
            dbc.Textarea(
                id="erp-validator-field-description", rows=4, value=warning.description, className="erp-input mb-3"
            ),
            _field_label(
                t("tab_integration_validacion_avisos.accion_recomendada").strip(),
                "erp-validator-field-action",
                tag=_ai_tag(),
            ),
            dbc.Textarea(
                id="erp-validator-field-action", rows=3, value=warning.recommended_action, className="erp-input mb-3"
            ),
            _field_label(
                t("tab_integration_validacion_avisos.notas_del_operador").strip(),
                "erp-validator-field-notes",
                extra=html.Span(t("tab_integration_validacion_avisos.opcional"), className="erp-field-optional"),
            ),
            dbc.Textarea(
                id="erp-validator-field-notes", rows=2, value=warning.operator_notes or "", className="erp-input mb-3"
            ),
            _field_label(
                t("tab_integration_validacion_avisos.severidad_prioridad_sap").strip(),
                "erp-validator-field-severity",
            ),
            html.Div(
                [
                    dbc.Select(
                        id="erp-validator-field-severity",
                        options=severity_options,
                        value=warning.severity.value,
                        className="erp-input erp-severity-select",
                    ),
                    html.Div(
                        [
                            html.Span(t("tab_integration_validacion_avisos.vista_previa"), className="erp-field-optional"),
                            html.Span(severity_chip(warning.severity), id="erp-validator-severity-preview"),
                        ],
                        className="erp-severity-preview",
                    ),
                ],
                className="erp-severity-row",
            ),
        ],
        className="erp-section",
    )


def create_detail_form(warning: Warning) -> html.Div:
    """Per-warning content only. The action bar, rejection collapse and result alerts are
    intentionally NOT here — they live in the static create_layout() tree instead (see the
    module docstring). The operator field isn't here either — it's a single session-scoped
    field in the page header (see _operator_field / create_layout)."""
    return html.Div([_detail_header(warning), _context_section(warning), _erp_fields_section(warning)])


def _operator_field() -> html.Div:
    """Session-scoped operator name — entered once, reused for every approve/reject on this page
    (dashboard.layout's erp-validator-operator-store, storage_type='session'). Anyone who can reach
    this tab can act; there's no separate identity check beyond typing a name here, since it's
    recorded as `validated_by`. While it's empty the action buttons stay disabled."""
    return html.Div(
        [
            html.Label(
                [t("tab_integration_validacion_avisos.operador"), html.Span(" *", className="erp-required", **{"aria-hidden": "true"})],
                htmlFor="erp-validator-operator-input",
                className="erp-field-label",
            ),
            html.Div(
                [
                    dbc.Input(
                        id="erp-validator-operator-input",
                        type="text",
                        placeholder=t("tab_integration_validacion_avisos.ingrese_su_nombre"),
                        required=True,
                        autoComplete="name",
                        className="erp-input",
                    ),
                    html.Div(
                        operator_message(None),
                        id="erp-validator-operator-feedback",
                        className="erp-operator__feedback",
                        role="status",
                        **{"aria-live": "polite"},
                    ),
                ],
                className="erp-operator__control",
            ),
        ],
        className="erp-operator",
    )


def _pending_panel() -> html.Section:
    return html.Section(
        [
            html.Div(
                [
                    html.H2(t("tab_integration_validacion_avisos.avisos_pendientes"), className="erp-panel__title"),
                    html.Span(id="erp-validator-pending-count", className="erp-count-pill"),
                ],
                className="erp-panel__head",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label(
                                t("tab_integration_validacion_avisos.buscar_por_id_del_activo"),
                                htmlFor="erp-validator-search",
                                className="erp-field-label",
                            ),
                            dbc.Input(
                                id="erp-validator-search",
                                type="search",
                                value="",
                                autoComplete="off",
                                className="erp-input erp-input--compact",
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            html.Span(
                                t("tab_integration_validacion_avisos.clasificacion"),
                                id="erp-validator-filter-label-text",
                                className="erp-field-label",
                            ),
                            html.Div(
                                dbc.RadioItems(
                                    id="erp-validator-filter-label",
                                    name="erp-validator-filter-label",
                                    options=[
                                        {"label": t("tab_integration_validacion_avisos.filtro_todos"), "value": FILTER_ALL},
                                        *(
                                            {
                                                "label": CONDITION_LABEL_LABELS[ConditionLabel(value)],
                                                "value": value,
                                            }
                                            for value in FILTER_LABELS
                                        ),
                                    ],
                                    value=FILTER_ALL,
                                    inline=True,
                                    className="erp-segmented",
                                    inputClassName="erp-segmented__input",
                                    labelClassName="erp-segmented__label",
                                    labelCheckedClassName="erp-segmented__label--checked",
                                ),
                                role="group",
                                **{"aria-labelledby": "erp-validator-filter-label-text"},
                            ),
                        ]
                    ),
                ],
                className="erp-list-controls",
            ),
            dcc.Loading(
                html.Div(id="erp-validator-warning-list", className="erp-pending-list"),
                type="circle",
                delay_show=400,
                parent_className="erp-pending-list-wrap",
            ),
        ],
        className="erp-panel erp-pending-panel",
    )


def _detail_panel() -> html.Section:
    return html.Section(
        [
            html.Div(
                [
                    # Static (present from initial layout, not nested inside
                    # create_detail_form's dynamic children) — see module docstring.
                    dbc.Alert(
                        id="erp-validator-success-alert",
                        color="success",
                        is_open=False,
                        dismissable=True,
                        className="mb-3",
                    ),
                    dbc.Alert(
                        id="erp-validator-error-alert",
                        color="danger",
                        is_open=False,
                        dismissable=True,
                        className="mb-3",
                    ),
                    dcc.Loading(
                        html.Div(
                            id="erp-validator-form-content",
                            children=create_detail_placeholder(
                                t("tab_integration_validacion_avisos.seleccione_un_aviso_para_revisarlo")
                            ),
                        ),
                        type="circle",
                    ),
                ],
                className="erp-detail__body",
            ),
            html.Div(
                [
                    dbc.Collapse(
                        html.Div(
                            [
                                html.Label(
                                    [
                                        t("tab_integration_validacion_avisos.motivo_de_rechazo").strip(),
                                        html.Span(" *", className="erp-required", **{"aria-hidden": "true"}),
                                    ],
                                    htmlFor="erp-validator-field-rejection",
                                    className="erp-field-label",
                                ),
                                dbc.Textarea(
                                    id="erp-validator-field-rejection",
                                    rows=2,
                                    required=True,
                                    placeholder=t("tab_integration_validacion_avisos.indique_por_que_se_rechaza_este"),
                                    className="erp-input",
                                ),
                                html.Div(
                                    id="erp-validator-rejection-feedback",
                                    className="erp-operator__feedback",
                                    role="alert",
                                ),
                                dbc.Button(
                                    t("tab_integration_validacion_avisos.confirmar_rechazo"),
                                    id="erp-validator-btn-confirm-reject",
                                    color="danger",
                                    type="button",
                                    className="erp-action-btn",
                                ),
                            ],
                            className="erp-reject",
                        ),
                        id="erp-validator-rejection-collapse",
                        is_open=False,
                    ),
                    html.Div(
                        [
                            html.Span(id="erp-validator-footer-note", className="erp-detail__note"),
                            html.Div(
                                [
                                    dbc.Button(
                                        t("tab_integration_validacion_avisos.rechazar_accion"),
                                        id="erp-validator-btn-reject",
                                        color="danger",
                                        outline=True,
                                        disabled=True,
                                        type="button",
                                        className="erp-action-btn",
                                    ),
                                    dbc.Button(
                                        [
                                            html.I(className="fas fa-paper-plane me-2", **{"aria-hidden": "true"}),
                                            t("tab_integration_validacion_avisos.aprobar_y_enviar_al_erp"),
                                        ],
                                        id="erp-validator-btn-approve",
                                        color="primary",
                                        disabled=True,
                                        type="button",
                                        className="erp-action-btn",
                                    ),
                                ],
                                className="erp-detail__buttons",
                            ),
                        ],
                        className="erp-detail__actions",
                    ),
                ],
                id="erp-validator-footer",
                className="erp-detail__footer",
                hidden=True,
            ),
        ],
        className="erp-panel erp-detail",
        **{"aria-label": t("tab_integration_validacion_avisos.detalle_del_aviso")},
    )


def create_layout() -> dbc.Container:
    return dbc.Container(
        [
            html.Header(
                [
                    html.Div(
                        [
                            html.H1(t("nav.service.integration-validacion-avisos"), className="erp-page-title"),
                            html.P(
                                t("tab_integration_validacion_avisos.revise_edite_y_apruebe_los_avisos"),
                                className="erp-page-subtitle",
                            ),
                        ]
                    ),
                    _operator_field(),
                ],
                className="erp-page-header",
            ),
            dcc.Store(id="erp-validator-selected-warning-id"),
            html.Div([_pending_panel(), _detail_panel()], className="erp-validator-grid"),
        ],
        fluid=True,
        className="erp-page",
    )
