"""Reactive callbacks for Conexión ERP (Validación de Avisos / Seguimiento de Avisos).

Both pages' content depends on the globally-selected client (client-selector
in the navbar) rather than a page-local dropdown (migration_guide.md §3).
List/KPI/chart callbacks (which have no other way to know which client to
load) resolve it the same way predictive_pages_callbacks.py._resolve_client
does: client-selector -> user-info-store's first client -> settings default.

Warning-scoped callbacks (view detail / approve / reject) instead resolve
client_id from the warning record itself via
erp_warning_store.find_by_id_any_client — the record is the source of truth
for which client a warning belongs to, and this keeps those actions working
regardless of what's currently selected in the client-selector.

Access to approve/reject is governed entirely by whether the operator can
reach this tab and see the warning at all (platform login + client access);
there's no separate identity/permission check layered on top of that.
"""
from __future__ import annotations

import logging
import math
import time

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback, dcc, html

from config.settings import get_settings
from dashboard.components.erp_bars import (
    empty_state,
    lifecycle_bar,
    percent,
    severity_bars,
    source_classification_bars,
    system_bars,
)
from dashboard.components.erp_chips import (
    ESTADO_STYLES,
    classification_chip,
    estado_chip,
    severity_chip,
)
from dashboard.layout import ERP_NAV_REFRESH_STORE_ID
from dashboard.tabs.tab_integration_seguimiento_avisos import (
    ALL_OPTION,
    DATES_ID,
    FILTER_IDS,
    PAGE_SIZE,
    TABLE_HEADERS,
)
from dashboard.tabs.tab_integration_validacion_avisos import (
    FILTER_ALL,
    FILTER_LABELS,
    create_detail_form,
    create_detail_placeholder,
    create_pending_item,
    operator_message,
    title_counter_class,
    title_counter_text,
)
from src.data import erp_warning_store
from src.data.erp_schemas import (
    CONDITION_LABEL_LABELS,
    ConditionLabel,
    Severity,
    SEVERITY_LABELS,
    Source,
    SOURCE_LABELS,
    STATUS_LABELS,
    System,
    SYSTEM_LABELS,
    WarningStatus,
)
from src.i18n import t, LazyLabels
from src.data.erp_write_operations import MAX_TITLE_LENGTH, approve_and_send, can_approve, reject

logger = logging.getLogger(__name__)

# pending-list sort priority (1.1): Anormal before Alerta before anything else, ties broken newest-first
_CRITICALITY_PRIORITY = {"anormal": 0, "alerta": 1, "normal": 2}
# validation-rate trend outcome labels (raw WarningStatus values, not the full STATUS_LABELS set —
# only "sent"/"rejected" ever appear here since validation_rate_trend restricts to terminal states)
_OUTCOME_LABELS = LazyLabels({"sent": "erp.status.sent", "rejected": "erp.status.rejected"})
# Sólo los avisos en estado terminal abren el detalle de fila del Registro de Avisos.
def _row_detail_status_labels() -> frozenset:
    """Computed per call, not at import: the table shows the translated label, so the
    comparison must use the label of the language being served."""
    return frozenset({STATUS_LABELS[WarningStatus.sent], STATUS_LABELS[WarningStatus.rejected]})
# Registro de Avisos (2.2): las columnas categóricas se muestran con las etiquetas
# declaradas en erp_schemas — las mismas del filtro y de los gráficos de arriba.
# Los valores almacenados mezclan idiomas (`inspections`, `medium`, `pending`),
# así que un title-case sobre el valor crudo dejaba media tabla en inglés.
# Identificadores (warning_id, asset_id, erp_reference), el operador y las fechas
# se muestran tal cual.
_TABLE_LABEL_MAPS = {
    "source": (Source, SOURCE_LABELS),
    "system": (System, SYSTEM_LABELS),
    "condition_label": (ConditionLabel, CONDITION_LABEL_LABELS),
    "severity": (Severity, SEVERITY_LABELS),
    "status": (WarningStatus, STATUS_LABELS),
}
# Raw values the chip cells need (the labelled row only has the translated text).
_RAW_CHIP_COLUMNS = ("condition_label", "severity", "status")

_TIME_SERIES_COLOR = "#2563eb"
_TIME_SERIES_FILL = "rgba(37, 99, 235, 0.12)"
_ID_PREVIEW_CHARS = 8


def _label_or_titlecase(enum_cls, labels, value):
    """Declared label for a stored enum value; title-case for anything unexpected."""
    try:
        return labels[enum_cls(value)]
    except (ValueError, KeyError):
        return str(value).title()


def _labelled_display(df):
    display = df.copy()
    for col, (enum_cls, labels) in _TABLE_LABEL_MAPS.items():
        if col in display.columns:
            display[col] = display[col].astype(str).map(
                lambda value, enum_cls=enum_cls, labels=labels: _label_or_titlecase(
                    enum_cls, labels, value
                )
            )
    return display


def _resolve_client(selected_client, user_data) -> str:
    """Resolve the active client the same way the predictive pages do."""
    if selected_client:
        return selected_client.lower()
    if user_data and user_data.get("clients"):
        return user_data["clients"][0].lower()
    settings = get_settings()
    return settings.clients[0].lower() if settings.clients else "cda"


# ---------------------------------------------------------------------------
# Validación de Avisos
# ---------------------------------------------------------------------------

def _pending_sorted(client_id: str) -> list:
    pending = erp_warning_store.read_warnings(client_id, "pending")
    return sorted(
        pending,
        key=lambda w: (
            _CRITICALITY_PRIORITY.get(w.condition_label.value, 99),
            -w.generated_at.timestamp(),
        ),
    )


def _filter_pending(pending: list, search, label_filter) -> list:
    """Asset-id substring search (case-insensitive) and the Todos / Anormal / Alerta segment."""
    term = (search or "").strip().lower()
    if term:
        pending = [w for w in pending if term in w.asset_id.lower()]
    if label_filter in FILTER_LABELS:
        pending = [w for w in pending if w.condition_label.value == label_filter]
    return pending


@callback(
    Output("erp-validator-warning-list", "children"),
    Input("client-selector", "value"),
    Input("user-info-store", "data"),
    Input("erp-validator-selected-warning-id", "data"),
    Input("erp-validator-search", "value"),
    Input("erp-validator-filter-label", "value"),
)
def _refresh_pending_list(selected_client, user_data, selected_warning_id, search=None, label_filter=FILTER_ALL):
    """Also triggered by selection changes (not just the client selector):
    after an approve/reject action resets erp-validator-selected-warning-id
    to None, this re-reads from disk so the just-actioned warning disappears
    from the list without a manual page refresh. The same selection also
    drives which card renders as selected (1.2)."""
    client_id = _resolve_client(selected_client, user_data)
    all_pending = _pending_sorted(client_id)
    logger.info("client=%s pending_count=%d", client_id, len(all_pending))
    if not all_pending:
        return html.P(t("integration_avisos_callbacks.no_hay_avisos_pendientes"), className="erp-list-empty")
    pending = _filter_pending(all_pending, search, label_filter)
    if not pending:
        return html.P(t("tab_integration_validacion_avisos.ningun_aviso_coincide"), className="erp-list-empty")
    return [create_pending_item(w, is_selected=(w.warning_id == selected_warning_id)) for w in pending]


@callback(
    Output("erp-validator-pending-count", "children"),
    Input("client-selector", "value"),
    Input("user-info-store", "data"),
    Input("erp-validator-selected-warning-id", "data"),
    Input("erp-validator-search", "value"),
    Input("erp-validator-filter-label", "value"),
)
def _refresh_pending_count(selected_client, user_data, _selected_warning_id, search=None, label_filter=FILTER_ALL):
    """Count next to the list heading: '62', or '12 de 62' while a search/segment narrows the list.
    The selection is an input only so the count follows an approve or reject, which takes a warning
    out of the pending set."""
    all_pending = _pending_sorted(_resolve_client(selected_client, user_data))
    shown = len(_filter_pending(all_pending, search, label_filter))
    total = len(all_pending)
    return str(total) if shown == total else t("tab_integration_validacion_avisos.n_de_total", n=shown, total=total)


@callback(
    Output("erp-validator-selected-warning-id", "data"),
    Input({"type": "erp-validator-select-pending", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _select_pending(_n_clicks):
    triggered = dash.ctx.triggered_id
    if not triggered or not any(_n_clicks):
        raise dash.exceptions.PreventUpdate
    logger.info("warning_id=%s selected", triggered["index"])
    return triggered["index"]


@callback(
    Output("erp-validator-form-content", "children"),
    Input("erp-validator-selected-warning-id", "data"),
)
def _render_detail(warning_id):
    if not warning_id:
        return create_detail_placeholder(t("tab_integration_validacion_avisos.seleccione_un_aviso_para_revisarlo"))
    found = erp_warning_store.find_by_id_any_client(warning_id)
    if found is None:
        logger.warning("warning_id=%s not found (no longer pending?)", warning_id)
        return create_detail_placeholder(t("integration_avisos_callbacks.el_aviso_ya_no_esta_pendiente"))
    warning, _client_id, _state = found
    return create_detail_form(warning)


@callback(
    Output("erp-validator-operator-input", "value"),
    Input("user-info-store", "data"),
    State("erp-validator-operator-store", "data"),
)
def _restore_operator(_user_data, stored_operator):
    """Populate the operator field from the session store on page (re)load.
    user-info-store is used purely as an on-load trigger (fires once when
    this page mounts, then again only on the rare login/logout in between) —
    the actual value always comes from the State read, not the Input."""
    return stored_operator or ""


@callback(
    Output("erp-validator-operator-store", "data"),
    Input("erp-validator-operator-input", "value"),
    prevent_initial_call=True,
)
def _save_operator(value):
    """One-directional: input -> store. Restoring the other way (store ->
    input) is handled by _restore_operator on an unrelated trigger, so this
    doesn't loop back into it."""
    return value


@callback(
    Output("erp-validator-operator-feedback", "children"),
    Output("erp-validator-operator-input", "invalid"),
    Output("erp-validator-footer", "hidden"),
    Output("erp-validator-btn-approve", "disabled"),
    Output("erp-validator-btn-reject", "disabled"),
    Output("erp-validator-footer-note", "children"),
    Input("erp-validator-operator-input", "value"),
    Input("erp-validator-selected-warning-id", "data"),
)
def _update_action_bar(operator, selected_warning_id):
    """The operator name gates both actions: while it's empty the field shows its inline error and
    Aprobar / Rechazar stay disabled; with a name it reads 'Listo' and the footer says who the
    validation will be recorded under. The footer itself only shows once a warning is selected."""
    name = (operator or "").strip()
    note = (
        [t("tab_integration_validacion_avisos.se_registrara_como_validado_por"), " ", html.Strong(name)]
        if name
        else t("tab_integration_validacion_avisos.indique_el_operador_para_continuar")
    )
    return operator_message(operator), not name, not selected_warning_id, not name, not name, note


@callback(
    Output("erp-validator-title-counter", "children"),
    Output("erp-validator-title-counter", "className"),
    Input("erp-validator-field-title", "value"),
    prevent_initial_call=True,
)
def _update_title_counter(value):
    return title_counter_text(value), title_counter_class(value)


@callback(
    Output("erp-validator-severity-preview", "children"),
    Input("erp-validator-field-severity", "value"),
    prevent_initial_call=True,
)
def _update_severity_preview(value):
    return severity_chip(value) if value else ""


@callback(
    Output("erp-validator-rejection-collapse", "is_open"),
    Output("erp-validator-field-rejection", "value"),
    Input("erp-validator-btn-reject", "n_clicks"),
    Input("erp-validator-selected-warning-id", "data"),
    State("erp-validator-rejection-collapse", "is_open"),
    prevent_initial_call=True,
)
def _toggle_rejection_collapse(_n_clicks, _selected_warning_id, is_open):
    """Rechazar… opens/closes the reason form. Changing (or clearing) the selection closes it and
    drops the text, so a reason typed for one warning can't be submitted against another."""
    if dash.ctx.triggered_id == "erp-validator-btn-reject":
        return not is_open, dash.no_update
    return False, ""


def _action_result(success=None, error=None, selected=dash.no_update, rejection_feedback="", changed=False):
    """Outputs of _handle_action: success alert, error alert, selection, inline rejection error and the
    sidebar refresh signal. `changed` marks an action that took a warning out of the pending set: it
    bumps the shell's refresh store so the sidebar re-renders with the new pending count. A store
    rather than the badge itself: a callback outputting to the badge (which the sidebar re-creates on
    every render) gets re-run by Dash on each re-render, before this page's State fields exist."""
    refresh = time.time_ns() if changed else dash.no_update
    return (success or "", bool(success), error or "", bool(error), selected, rejection_feedback, refresh)


# The per-warning fields (title ... severity) only exist once a warning is selected, hence
# allow_optional on those States; the buttons that trigger this are static (see the tab module).
@callback(
    Output("erp-validator-success-alert", "children"),
    Output("erp-validator-success-alert", "is_open"),
    Output("erp-validator-error-alert", "children"),
    Output("erp-validator-error-alert", "is_open"),
    Output("erp-validator-selected-warning-id", "data", allow_duplicate=True),
    Output("erp-validator-rejection-feedback", "children"),
    Output(ERP_NAV_REFRESH_STORE_ID, "data"),
    Input("erp-validator-btn-approve", "n_clicks"),
    Input("erp-validator-btn-confirm-reject", "n_clicks"),
    State("erp-validator-selected-warning-id", "data"),
    State("erp-validator-operator-store", "data"),
    State("erp-validator-field-title", "value", allow_optional=True),
    State("erp-validator-field-description", "value", allow_optional=True),
    State("erp-validator-field-action", "value", allow_optional=True),
    State("erp-validator-field-notes", "value", allow_optional=True),
    State("erp-validator-field-severity", "value", allow_optional=True),
    State("erp-validator-field-rejection", "value"),
    prevent_initial_call=True,
)
def _handle_action(
    _approve_clicks,
    _confirm_reject_clicks,
    warning_id,
    operator_name,
    title,
    description,
    recommended_action,
    operator_notes,
    severity,
    reject_reason,
):
    """Access to this action is governed entirely by whether the operator can
    reach this tab and see the warning at all (platform login + the warning
    existing under one of their clients) — no separate identity/permission
    check here. `client_id` comes from the warning record itself, not the
    client-selector, so this doesn't depend on that selector's state either.
    The operator's name comes from the session-scoped operator field in the
    page header (erp-validator-operator-store) rather than a per-warning
    field, so it's reused across every approve/reject in the session. Both
    buttons are disabled while it's empty (_update_action_bar); the check
    below only backstops a click that gets through anyway."""
    if not warning_id:
        raise dash.exceptions.PreventUpdate

    found = erp_warning_store.find_by_id_any_client(warning_id)
    if found is None:
        logger.warning("warning_id=%s not found for action (no longer pending?)", warning_id)
        return _action_result(error=t("integration_avisos_callbacks.el_aviso_ya_no_esta_disponible"), selected=None)

    _warning, client_id, _state = found
    operator_id = (operator_name or "").strip()

    if not operator_id:
        logger.warning("client=%s warning_id=%s action blocked: operator not provided", client_id, warning_id)
        return _action_result(error=t("integration_avisos_callbacks.debe_indicar_el_nombre_del_operador"))

    triggered = dash.ctx.triggered_id

    if triggered == "erp-validator-btn-approve":
        if not can_approve(title, warning_id, recommended_action):
            logger.warning(
                "client=%s warning_id=%s approve blocked: missing required field(s)", client_id, warning_id
            )
            return _action_result(error=t("integration_avisos_callbacks.titulo_asset_y_accion_recomendada_son"))
        if len(title) > MAX_TITLE_LENGTH:
            logger.warning(
                "client=%s warning_id=%s approve blocked: title exceeds %d chars",
                client_id,
                warning_id,
                MAX_TITLE_LENGTH,
            )
            return _action_result(
                error=t("integration_avisos_callbacks.el_titulo_excede_caracteres", MAX_TITLE_LENGTH=MAX_TITLE_LENGTH)
            )
        logger.info(
            "client=%s warning_id=%s operator=%s approving and sending to ERP", client_id, warning_id, operator_id
        )
        result = approve_and_send(
            client_id,
            warning_id,
            operator_id=operator_id,
            title=title,
            description=description,
            recommended_action=recommended_action,
            operator_notes=operator_notes or None,
            severity=severity,
        )
        if result.status == "sent":
            logger.info(
                "client=%s warning_id=%s sent to ERP erp_reference=%s",
                client_id,
                warning_id,
                result.erp_reference,
            )
            return _action_result(
                success=[t("integration_avisos_callbacks.aviso_enviado_al_erp_correctamente_referen"), html.Strong(result.erp_reference)],
                selected=None,
                changed=True,
            )
        logger.error(
            "client=%s warning_id=%s ERP push failed: %s", client_id, warning_id, result.operator_notes
        )
        return _action_result(
            error=t("integration_avisos_callbacks.error_al_enviar_al_erp", result_operator_no=result.operator_notes),
            selected=None,
            changed=True,
        )

    if triggered == "erp-validator-btn-confirm-reject":
        if not (reject_reason or "").strip():
            logger.warning("client=%s warning_id=%s reject blocked: no reason given", client_id, warning_id)
            return _action_result(
                rejection_feedback=html.Span(
                    [
                        html.I(className="fas fa-exclamation-circle", **{"aria-hidden": "true"}),
                        t("integration_avisos_callbacks.debe_indicar_un_motivo_de_rechazo"),
                    ],
                    className="erp-field-msg erp-field-msg--error",
                )
            )
        reject(client_id, warning_id, operator_id=operator_id, reason=reject_reason)
        logger.info(
            "client=%s warning_id=%s operator=%s rejected reason=%r", client_id, warning_id, operator_id, reject_reason
        )
        return _action_result(
            success=t("integration_avisos_callbacks.aviso_rechazado"), selected=None, changed=True
        )

    raise dash.exceptions.PreventUpdate


# ---------------------------------------------------------------------------
# Seguimiento de Avisos
# ---------------------------------------------------------------------------

@callback(
    Output(FILTER_IDS["asset"], "options"),
    Output(FILTER_IDS["asset"], "value"),
    Input("client-selector", "value"),
    Input("user-info-store", "data"),
)
def _populate_asset_options(selected_client, user_data):
    """Asset ID is a select, not free text — options come from that client's own data."""
    client_id = _resolve_client(selected_client, user_data)
    assets = sorted(erp_warning_store.load_all_warnings(client_id)["asset_id"].dropna().unique())
    logger.info("client=%s asset_options=%d", client_id, len(assets))
    all_option = {"label": t("tab_integration_seguimiento_avisos.opcion_todos"), "value": ALL_OPTION}
    return [all_option, *({"label": a, "value": a} for a in assets)], ALL_OPTION


@callback(
    Output(FILTER_IDS["source"], "value"),
    Output(FILTER_IDS["system"], "value"),
    Output(FILTER_IDS["label"], "value"),
    Output(FILTER_IDS["severity"], "value"),
    Output(FILTER_IDS["status"], "value"),
    Output(FILTER_IDS["asset"], "value", allow_duplicate=True),
    Output(DATES_ID, "start_date"),
    Output(DATES_ID, "end_date"),
    Input("erp-viewer-clear-filters", "n_clicks"),
    prevent_initial_call=True,
)
def _clear_filters(_n_clicks):
    """Limpiar filtros: every filter back to 'all' / no dates."""
    return (ALL_OPTION,) * 6 + (None, None)


def _peak_indices(counts: list, limit: int = 8) -> set:
    """Points that get a value label: local maxima at least half as tall as the series' peak (and the
    peak itself), at most `limit` of them so a long series isn't a wall of numbers."""
    if not counts:
        return set()
    top = max(counts)
    last = len(counts) - 1
    peaks = {
        i
        for i, value in enumerate(counts)
        if value >= top / 2
        and value >= (counts[i - 1] if i > 0 else -1)
        and value >= (counts[i + 1] if i < last else -1)
    }
    peaks.add(counts.index(top))
    if len(peaks) > limit:
        peaks = set(sorted(peaks, key=lambda i: (-counts[i], i))[:limit])
    return peaks


def _style_axes(fig: go.Figure, days: list) -> None:
    """Calendar dates only on the x axis (never a timestamp), one tick per day on a short range."""
    fig.update_xaxes(type="date", tickformat="%d/%m/%Y", hoverformat="%d/%m/%Y", showgrid=False)
    span = (max(days) - min(days)).days if days else 0
    if span <= 10:
        fig.update_xaxes(dtick=86400000)
    fig.update_layout(
        margin=dict(l=20, r=20, t=30, b=20),
        font=dict(size=12, color="#334155"),
        legend=dict(orientation="h", y=-0.25),
    )


def _over_time_component(filtered):
    """Daily line with a light area fill and the peaks labelled, plus the text description the
    chart itself can't give a screen reader (also shown as its caption)."""
    daily = (
        filtered.assign(day=filtered["generated_at"].dt.date).groupby("day").size().reset_index(name="count")
    )
    days, counts = list(daily["day"]), [int(c) for c in daily["count"]]
    peaks = _peak_indices(counts)
    fig = go.Figure(
        go.Scatter(
            x=days,
            y=counts,
            mode="lines+markers+text",
            text=[str(c) if i in peaks else "" for i, c in enumerate(counts)],
            textposition="top center",
            cliponaxis=False,
            line=dict(color=_TIME_SERIES_COLOR, width=2),
            marker=dict(size=7, color=_TIME_SERIES_COLOR),
            fill="tozeroy",
            fillcolor=_TIME_SERIES_FILL,
            hovertemplate=t("integration_avisos_callbacks.b_fecha_b_br_cantidad_de"),
        )
    )
    _style_axes(fig, days)
    fig.update_yaxes(
        rangemode="tozero",
        tickformat="d",
        title_text=t("integration_avisos_callbacks.cantidad_de_avisos"),
        **({"dtick": 1} if max(counts) <= 6 else {}),
    )
    top = max(counts)
    caption = t(
        "tab_integration_seguimiento_avisos.descripcion_avisos_en_el_tiempo",
        total=sum(counts),
        dias=len(counts),
        max=top,
        fecha=days[counts.index(top)].strftime("%d/%m/%Y"),
    )
    graph = html.Div(
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
        role="img",
        **{"aria-labelledby": "erp-viewer-over-time-caption"},
    )
    return graph, caption


def _validation_rate_component(filtered):
    """Sent vs rejected share per day; with fewer than two distinct days of resolved warnings a line
    has nothing to draw, so the empty state replaces the plot."""
    trend = erp_warning_store.validation_rate_trend(filtered)
    if trend.empty or trend["day"].nunique() < 2:
        return empty_state(t("tab_integration_seguimiento_avisos.tendencia_sin_datos"), icon="fa-chart-line")
    days = sorted(trend["day"].unique())
    fig = go.Figure()
    for outcome, group in trend.groupby("outcome"):
        fig.add_scatter(
            x=group["day"].astype(str),
            y=group["rate"],
            name=_OUTCOME_LABELS.get(outcome, outcome),
            mode="lines+markers",
            line=dict(color=ESTADO_STYLES.get(outcome, ESTADO_STYLES["rejected"])["fill"], width=2),
            hovertemplate=t("integration_avisos_callbacks.b_b_br_fecha_br_tasa"),
        )
    _style_axes(fig, days)
    # A single outcome (a filter on Estado) would otherwise lose the legend and the line its name.
    fig.update_layout(showlegend=True)
    fig.update_xaxes(ticklabelstandoff=8)
    fig.update_yaxes(range=[0, 105], ticksuffix="%", title_text=t("integration_avisos_callbacks.tasa_de_validacion"))
    return dcc.Graph(figure=fig, config={"displayModeBar": False})


def _table_rows(filtered) -> list[dict]:
    """Registro de Avisos rows, newest first: the labelled display values of
    erp_warning_store.TABLE_COLUMNS plus `_raw` (the stored enum values the chips are colored from)."""
    ordered = filtered.sort_values("generated_at", ascending=False)
    source = ordered[erp_warning_store.TABLE_COLUMNS].copy()
    raw = source[list(_RAW_CHIP_COLUMNS)].astype(str).to_dict("records")
    source["generated_at"] = source["generated_at"].dt.strftime("%d/%m/%Y %H:%M")
    for column in ("validated_by", "erp_reference"):
        source[column] = source[column].fillna("")
    rows = _labelled_display(source.astype(str)).to_dict("records")
    for row, raw_values in zip(rows, raw):
        row["_raw"] = raw_values
    return rows


def _duration_label(hours: float | None) -> str:
    """Average time to validation: hours up to two days, days beyond (2622.1 h isn't readable)."""
    if hours is None:
        return "–"
    return f"{hours:g} h" if hours < 48 else f"{hours / 24:.1f} d"


def _share_caption(count: int, total: int) -> str:
    return t("tab_integration_seguimiento_avisos.pct_del_total", pct=percent(count, total))


@callback(
    Output("erp-viewer-kpi-total", "children"),
    Output("erp-viewer-kpi-pending", "children"),
    Output("erp-viewer-kpi-sent", "children"),
    Output("erp-viewer-kpi-rejected", "children"),
    Output("erp-viewer-kpi-avg-hours", "children"),
    Output("erp-viewer-kpi-pending-share", "children"),
    Output("erp-viewer-kpi-sent-share", "children"),
    Output("erp-viewer-kpi-rejected-share", "children"),
    Output("erp-viewer-lifecycle", "children"),
    Output("erp-viewer-over-time", "children"),
    Output("erp-viewer-over-time-caption", "children"),
    Output("erp-viewer-by-source", "children"),
    Output("erp-viewer-by-severity", "children"),
    Output("erp-viewer-by-system", "children"),
    Output("erp-viewer-validation-rate", "children"),
    Output("erp-viewer-table-rows", "data"),
    Input("client-selector", "value"),
    Input("user-info-store", "data"),
    Input(FILTER_IDS["source"], "value"),
    Input(FILTER_IDS["system"], "value"),
    Input(FILTER_IDS["label"], "value"),
    Input(FILTER_IDS["severity"], "value"),
    Input(FILTER_IDS["status"], "value"),
    Input(FILTER_IDS["asset"], "value"),
    Input(DATES_ID, "start_date"),
    Input(DATES_ID, "end_date"),
)
def _refresh(selected_client, user_data, source, system, condition_label, severity, status, asset_id, start_date, end_date):
    client_id = _resolve_client(selected_client, user_data)
    source, system, condition_label, severity, status, asset_id = (
        None if value == ALL_OPTION else value for value in (source, system, condition_label, severity, status, asset_id)
    )

    df = erp_warning_store.load_all_warnings(client_id)
    filtered = erp_warning_store.apply_filters(
        df, source, system, condition_label, severity, status, asset_id, start_date, end_date
    )
    logger.info(
        "client=%s loaded=%d after_filters=%d source=%s system=%s label=%s severity=%s status=%s asset=%s",
        client_id,
        len(df),
        len(filtered),
        source,
        system,
        condition_label,
        severity,
        status,
        asset_id,
    )

    kpis = erp_warning_store.compute_kpis(filtered)
    total, pending, sent, rejected = kpis["total"], kpis["pending"], kpis["validated_and_sent"], kpis["rejected"]
    avg_hours = kpis["avg_hours_to_validation"]
    kpi_outputs = (
        str(total),
        str(pending),
        str(sent),
        str(rejected),
        _duration_label(avg_hours),
        _share_caption(pending, total),
        _share_caption(sent, total),
        _share_caption(rejected, total),
    )

    if filtered.empty:
        nothing = empty_state(t("tab_integration_seguimiento_avisos.sin_avisos_para_los_filtros"))
        return (*kpi_outputs, nothing, nothing, "", nothing, nothing, nothing, nothing, [])

    by_source = (
        filtered.groupby(["source", "condition_label"]).size().unstack(fill_value=0)
    )
    source_rows = [
        (
            _label_or_titlecase(Source, SOURCE_LABELS, name),
            int(counts.get(ConditionLabel.anormal.value, 0)),
            int(counts.get(ConditionLabel.alerta.value, 0)),
        )
        for name, counts in by_source.iterrows()
    ]
    severity_counts = {str(k): int(v) for k, v in filtered["severity"].value_counts().items()}
    system_counts: dict[str, int] = {}
    for name, count in filtered["system"].value_counts().items():
        label = _label_or_titlecase(System, SYSTEM_LABELS, name)
        system_counts[label] = system_counts.get(label, 0) + int(count)

    over_time, over_time_caption = _over_time_component(filtered)
    return (
        *kpi_outputs,
        lifecycle_bar(pending, sent, rejected),
        over_time,
        over_time_caption,
        source_classification_bars(source_rows),
        severity_bars(severity_counts),
        system_bars(system_counts),
        _validation_rate_component(filtered),
        _table_rows(filtered),
    )


@callback(
    Output("erp-viewer-table-page", "data"),
    Input("erp-viewer-page-prev", "n_clicks"),
    Input("erp-viewer-page-next", "n_clicks"),
    Input("erp-viewer-table-rows", "data"),
    State("erp-viewer-table-page", "data"),
)
def _change_page(_prev, _next, rows, page):
    """Anterior / Siguiente move one page; new rows (a filter changed) go back to the first."""
    last_page = max(0, math.ceil(len(rows or []) / PAGE_SIZE) - 1)
    triggered = dash.ctx.triggered_id
    if triggered == "erp-viewer-page-next":
        return min((page or 0) + 1, last_page)
    if triggered == "erp-viewer-page-prev":
        return max((page or 0) - 1, 0)
    return 0


def _table_row(row: dict, terminal_labels: frozenset) -> html.Tr:
    raw = row["_raw"]
    full_id = row["warning_id"]
    preview = full_id if len(full_id) <= _ID_PREVIEW_CHARS else f"{full_id[:_ID_PREVIEW_CHARS]}…"
    if row["status"] in terminal_labels:
        id_cell = html.Button(
            preview,
            id={"type": "erp-viewer-row-open", "index": full_id},
            n_clicks=0,
            type="button",
            title=full_id,
            className="erp-table__id-button",
        )
    else:
        id_cell = html.Span(preview, title=full_id)
    return html.Tr(
        [
            html.Td(id_cell, className="erp-table__warning_id"),
            html.Td(row["asset_id"]),
            html.Td(row["source"]),
            html.Td(row["system"]),
            html.Td(classification_chip(raw["condition_label"])),
            html.Td(severity_chip(raw["severity"])),
            html.Td(estado_chip(raw["status"])),
            html.Td(row["generated_at"], className="erp-table__generated_at"),
            html.Td(row["validated_by"] or "—"),
            html.Td(row["erp_reference"] or "—"),
        ]
    )


@callback(
    Output("erp-viewer-table-body", "children"),
    Output("erp-viewer-table-label", "children"),
    Output("erp-viewer-page-indicator", "children"),
    Output("erp-viewer-page-prev", "disabled"),
    Output("erp-viewer-page-next", "disabled"),
    Input("erp-viewer-table-rows", "data"),
    Input("erp-viewer-table-page", "data"),
)
def _render_table(rows, page):
    """One page of the Registro de Avisos, with its 'Mostrando x–y de N' label."""
    rows = rows or []
    total = len(rows)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(page or 0, 0), pages - 1)
    start = page * PAGE_SIZE
    chunk = rows[start : start + PAGE_SIZE]
    terminal_labels = _row_detail_status_labels()
    body = [_table_row(row, terminal_labels) for row in chunk] or [
        html.Tr(
            html.Td(
                t("tab_integration_seguimiento_avisos.sin_avisos_para_los_filtros"),
                colSpan=len(TABLE_HEADERS),
                className="erp-table__empty",
            )
        )
    ]
    label = t(
        "tab_integration_seguimiento_avisos.mostrando",
        start=start + 1 if total else 0,
        end=start + len(chunk),
        total=total,
    )
    indicator = t("tab_integration_seguimiento_avisos.pagina_de", page=page + 1, pages=pages)
    return body, label, indicator, page <= 0, page >= pages - 1


def _row_detail_content(row: dict | None):
    # La tabla muestra el estado ya traducido, así que la comparación va contra
    # las mismas etiquetas y no contra los valores crudos del store.
    if not row or row.get("status") not in _row_detail_status_labels():
        return ""
    logger.info("row detail opened warning_id=%s status=%s", row.get("warning_id"), row.get("status"))
    shown = {key: value for key, value in row.items() if not key.startswith("_")}
    return dbc.Card(dbc.CardBody(html.Pre(str(shown))), className="erp-card mt-3")


@callback(
    Output("erp-viewer-row-detail", "children"),
    Input({"type": "erp-viewer-row-open", "index": ALL}, "n_clicks"),
    State("erp-viewer-table-rows", "data"),
)
def _row_detail(n_clicks, rows):
    """Sólo los avisos en estado terminal tienen el botón de ID que abre el detalle de fila; una
    tabla nueva (otra página, otro filtro) lo cierra."""
    triggered = dash.ctx.triggered_id
    if not triggered or not any(n_clicks or []):
        return ""
    row = next((r for r in rows or [] if r["warning_id"] == triggered["index"]), None)
    return _row_detail_content(row)
