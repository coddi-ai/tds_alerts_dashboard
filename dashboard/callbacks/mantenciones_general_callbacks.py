"""Callbacks for the productive Mantenciones page."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from dash import Input, Output, State, ctx, html, no_update
from dash.exceptions import MissingCallbackContextException, PreventUpdate

from dashboard.tabs.tab_mantenciones_general import (
    create_activity_matrix,
    create_activity_table,
    create_daily_activity_chart,
    create_daily_equipment_chart,
    create_daily_intervention_hours_chart,
    create_empty_figure,
    create_equipment_activity_chart,
    create_equipment_pareto_chart,
    create_emin_actions_pareto_chart,
    create_emin_hours_pareto_chart,
    create_system_activity_chart,
    create_week_summary_table,
    create_week_task_table,
)
from src.data.maintenance_repository import PARETO_SCOPE, get_repository

_EMIN_GENERIC_SYSTEM = "Equipo"
_EMIN_GENERIC_SYSTEM_OPTION = "General del equipo (sin sistema técnico atribuido)"
_EMIN_GENERIC_SYSTEM_CHART = "General del equipo"


def _options(values):
    return [{"label": value, "value": value} for value in values]


def _maintenance_root_class(client):
    classes = ["p-4", "maintenance-view-root"]
    if str(client or "").strip().upper() == "EMIN":
        classes.append("maintenance-emin")
    return " ".join(classes)


def _pareto_system_options(client, values):
    options = _options(values)
    if str(client or "").strip().upper() == "EMIN":
        for option in options:
            if option["value"] == _EMIN_GENERIC_SYSTEM:
                option["label"] = _EMIN_GENERIC_SYSTEM_OPTION
    return options


def _display_system_label(client, value):
    if value is None or pd.isna(value):
        return "Sin sistema"
    if str(client or "").strip().upper() == "EMIN" and value == _EMIN_GENERIC_SYSTEM:
        return _EMIN_GENERIC_SYSTEM_CHART
    return str(value)


def _display_system_rows(rows, client):
    frame = pd.DataFrame(rows)
    if (
        str(client or "").strip().upper() == "EMIN"
        and "system_name" in frame.columns
    ):
        frame["system_name"] = frame["system_name"].map(
            lambda value: _display_system_label(client, value)
        )
    return frame


def _effective_pareto_metric(
    client,
    metric,
    selected_systems,
    available_systems,
    hours_available,
    client_changed=False,
):
    """Keep EMIN's Hours choice only when its complete system scope is selected."""
    if metric != "hours":
        return metric or "actions"
    if str(client or "").strip().upper() != "EMIN":
        return "actions"
    available = set(available_systems or [])
    selected = set(selected_systems or [])
    if client_changed or not hours_available or not available or selected != available:
        return "actions"
    return "hours"


def _pareto_system_selection_label(client, selected_systems, available_systems):
    selected = list(selected_systems or [])
    available = list(available_systems or [])
    if not selected:
        return ""
    if available and set(selected) == set(available):
        return "Todos los sistemas"
    return ", ".join(_display_system_label(client, system) for system in selected)


def _equipment_options(values):
    return [{"label": "Todas", "value": "__all__"}] + [
        {"label": value, "value": value} for value in values if value != "__all__"
    ]


def _empty_contract():
    pareto_scope = {**PARETO_SCOPE, "system_aliases": list(PARETO_SCOPE["system_aliases"])}
    return {
        "status": "empty",
        "meta": {"period": None, "period_label": "Sin datos", "available_months": [], "source_start": None, "source_end": None, "is_current_period": False, "detail_total": 0, "pareto_scope": pareto_scope, "pareto": {"available_systems": [], "selected_systems": [], "metric": "actions", "hours_available": False, "metric_options": [{"label": "Acciones", "value": "actions"}, {"label": "Horas", "value": "hours", "disabled": True}]}, "estimated_kpis": {"status": "unavailable", "label": "FUENTE", "reason": "Sin fuente cargada."}},
        "filters": {"fleets": [], "systems": [], "equipment": [], "subsystems": []},
        "kpis": {"equipment": 0, "actions": 0, "records": 0, "systems": 0, "activity_days": 0, "motor_share_pct": None, "availability_est_pct": None, "downtime_est_hours": None, "mtbf_est_hours": None, "mttr_est_hours": None},
        "data": {"daily": [], "system_mix": [], "system_mix_detail": [], "pareto": [], "system_pareto": [], "train_force_pareto": [], "equipment": [], "equipment_system_mix": [], "matrix": [], "detail": [], "unit_status": []},
    }


def _pareto_presentation(client, meta=None):
    """Select client-specific Pareto labels and all-system chart semantics."""
    client_name = str(client or (meta or {}).get("client") or "").strip().upper()
    if client_name == "EMIN":
        return {
            "all_systems": True,
            "equipment_title": "Pareto de acciones por unidad",
            "system_title": "Pareto de horas intervenidas por unidad",
            "system_label": "todos los sistemas",
        }
    scope_mode = ((meta or {}).get("pareto_scope") or {}).get("mode")
    if client_name in {"EMIN", "CAPSTONE"} or scope_mode == "all_systems":
        return {
            "all_systems": True,
            "equipment_title": "Pareto de actividad de mantenimiento · todos los sistemas por equipo",
            "system_title": "Pareto de actividad de mantenimiento · todos los sistemas por sistema",
            "system_label": "todos los sistemas",
        }
    return {
        "all_systems": False,
        "equipment_title": "Pareto de actividad de mantenimiento · Motor por equipo",
        "system_title": "Pareto de actividad de mantenimiento · Tren de Fuerza por equipo",
        "system_label": "Motor",
    }


def _refresh_requested() -> bool:
    """Return whether the current invocation came from the refresh button."""
    try:
        return ctx.triggered_id == "btn-refresh-maintenance"
    except MissingCallbackContextException:
        return False


def _format_estimated(value, suffix: str) -> str:
    """Format source-backed KPIs without inventing a zero for missing values."""
    if not isinstance(value, (int, float)):
        return "—"
    if suffix == "%":
        return f"{value:.1f}%"
    return f"{value:,.1f} h"


def _source_alert(meta: dict):
    end = meta.get("source_end")
    estimated = meta.get("estimated_kpis", {})
    if not end:
        if estimated.get("status") == "source":
            coverage = estimated.get("coverage", {})
            reference_date = coverage.get("reference_date")
            label = "No hay detalle de acciones disponible; los indicadores usan las vistas de horas." if meta.get("source_status") == "partial" else "Cobertura de horas disponible desde las vistas de confiabilidad."
            if reference_date:
                label += f" El estado puntual corresponde al {reference_date}; no representa necesariamente el día de hoy."
            return html.Div([html.I(className="fas fa-database me-2"), label], className="alert alert-info")
        return html.Div([html.I(className="fas fa-database me-2"), "No hay datos de mantenciones disponibles para este cliente."], className="alert alert-warning")
    date_label = str(end)[:10]
    coverage = estimated.get("coverage", {})
    coverage_label = coverage.get("window_label")
    source_files = estimated.get("source") or []
    source_name = str(source_files[0]).replace("\\", "/").rsplit("/", 1)[-1] if source_files else "fuente de actividad"
    source_label = (
        "Horas y KPIs de fuente"
        if estimated.get("source_kind") in {"calendar_intervention_hours", "intervention_hours_monthly", "business_kpis_monthly", "business_kpis_70d"}
        else "Horas/KPIs no disponibles"
    )
    estimated_note = f"{source_label} · fuente: {source_name} · cobertura: {coverage_label or 'no disponible'}."
    reference_start = coverage.get("reference_start")
    reference_end = coverage.get("reference_end")
    if reference_start and reference_end:
        estimated_note += f" Referencia: {str(reference_start)[:10]} a {str(reference_end)[:10]}."
    reason = estimated.get("reason")
    if reason:
        estimated_note += f" Fallback: {reason}"
    return html.Div(
        [
            html.I(className="fas fa-database me-2"),
            html.Span("Cobertura de fuente: ", className="fw-bold"),
            html.Span(f"{str(meta.get('source_start') or '')[:10]} a {date_label}. "),
            html.Span("El último período disponible se muestra por defecto; la fuente puede estar histórica.", className="text-muted"),
            html.Br(),
            html.Span(estimated_note, className="text-muted small"),
        ],
        className="alert alert-info",
        style={"overflowWrap": "anywhere"},
    )


def register_mantenciones_general_callbacks(app):
    """Register all callbacks against the concrete Dash app instance."""

    @app.callback(
        Output("maintenance-metadata-store", "data"),
        Output("maintenance-source-alert", "children"),
        Output("maintenance-month", "options"),
        Output("maintenance-month", "value"),
        Output("maintenance-summary-fleet", "options"),
        Output("maintenance-summary-fleet", "value"),
        Output("maintenance-week", "options"),
        Output("maintenance-week", "value"),
        Output("maintenance-week-equipment", "options"),
        Output("maintenance-activity-system", "options"),
        Output("maintenance-pareto-systems", "options"),
        Output("maintenance-pareto-systems", "value"),
        Output("maintenance-pareto-metric", "options"),
        Output("maintenance-view-root", "className"),
        Input("client-selector", "value"),
        Input("btn-refresh-maintenance", "n_clicks"),
        prevent_initial_call=False,
    )
    def load_maintenance_metadata(client, n_clicks):
        if not client:
            return {}, _source_alert({}), [], None, [], [], [], None, [], [], [], [], [{"label": "Acciones", "value": "actions"}, {"label": "Horas", "value": "hours", "disabled": True}], _maintenance_root_class(client)
        try:
            repo = get_repository(mode="parquet", client=client)
            if _refresh_requested():
                repo.refresh()
            months = repo.get_available_months()
            weeks = repo.get_available_weeks()
            latest_payload = repo.get_monthly_payload(months[-1] if months else None)
            meta = latest_payload.get("meta", {})
            pareto_meta = meta.get("pareto", {}) or {}
            meta.update(
                {
                    "available_months": months,
                    "available_weeks": weeks,
                    "equipment": repo.get_available_equipment(),
                    "fleets": repo.get_available_fleets(),
                    "systems": repo.get_available_systems(),
                    "subsystems": repo.get_available_subsystems(),
                }
            )
            return (
                meta,
                None if str(client).upper() == "EMIN" else _source_alert(meta),
                _options(months),
                months[-1] if months else None,
                _options(meta["fleets"]),
                [],
                _options(weeks),
                weeks[-1] if weeks else None,
                _options(meta["equipment"]),
                _options(meta["systems"]),
                _pareto_system_options(client, pareto_meta.get("available_systems", [])),
                pareto_meta.get("selected_systems", []),
                pareto_meta.get("metric_options", [{"label": "Acciones", "value": "actions"}]),
                _maintenance_root_class(client),
            )
        except Exception as exc:
            error_text = "No se dispone de esta información momentáneamente." if str(client).upper() == "EMIN" else f"Error al cargar la fuente de mantenciones: {exc}"
            return {}, html.Div(error_text, className="alert alert-danger"), [], None, [], [], [], None, [], [], [], [], [{"label": "Acciones", "value": "actions"}, {"label": "Horas", "value": "hours", "disabled": True}], _maintenance_root_class(client)


    @app.callback(
        Output("maintenance-pareto-metric", "value"),
        Input("client-selector", "value"),
        Input("maintenance-pareto-systems", "value"),
        Input("maintenance-metadata-store", "data"),
        State("maintenance-pareto-metric", "value"),
        State("maintenance-pareto-systems", "options"),
        prevent_initial_call=True,
    )
    def keep_pareto_metric_available(client, selected_systems, metadata, metric, system_options):
        pareto = ((metadata or {}).get("pareto") or {})
        available = [
            option.get("value")
            for option in (system_options or [])
            if isinstance(option, dict) and option.get("value") is not None
        ] or pareto.get("available_systems", [])
        next_metric = _effective_pareto_metric(
            client,
            metric,
            selected_systems,
            available,
            pareto.get("hours_available"),
            client_changed=ctx.triggered_id == "client-selector",
        )
        return no_update if next_metric == metric else next_metric


    @app.callback(
        Output("maintenance-summary-equipment", "options"),
        Output("maintenance-summary-equipment", "value"),
        Input("maintenance-summary-fleet", "value"),
        Input("client-selector", "value"),
        Input("maintenance-unit-navigation-table", "selected_rows"),
        Input("maintenance-reset-unit", "n_clicks"),
        State("maintenance-unit-navigation-table", "data"),
        State("maintenance-summary-equipment", "value"),
    )
    def update_summary_equipment_options(selected_fleets, client, selected_rows, reset_clicks, unit_rows, current_equipment):
        previous_equipment = current_equipment
        if not client:
            return _equipment_options([]), "__all__"
        repo = get_repository(mode="parquet", client=client)
        equipment = repo.get_available_equipment(fleets=selected_fleets or None)
        try:
            if ctx.triggered_id == "client-selector":
                current_equipment = "__all__"
            elif ctx.triggered_id == "maintenance-reset-unit" and str(client).upper() == "EMIN":
                current_equipment = "__all__"
            elif ctx.triggered_id == "maintenance-unit-navigation-table" and selected_rows:
                row_index = selected_rows[0]
                if isinstance(row_index, int) and 0 <= row_index < len(unit_rows or []):
                    current_equipment = (unit_rows[row_index] or {}).get("equipment", current_equipment)
        except MissingCallbackContextException:
            pass
        if current_equipment not in (None, "", "__all__") and current_equipment not in equipment:
            current_equipment = "__all__"
        next_equipment = current_equipment or "__all__"
        # Rendering either Pareto also clears the navigation-table selection.
        # Avoid re-emitting the unchanged unit and resetting the expanded view.
        value = no_update if str(client).upper() == "EMIN" and next_equipment == previous_equipment else next_equipment
        return _equipment_options(equipment), value


    @app.callback(
        Output("maintenance-activity-equipment", "options"),
        Output("maintenance-activity-equipment", "value"),
        Output("maintenance-activity-subsystem", "options"),
        Output("maintenance-activity-subsystem", "value"),
        Input("maintenance-activity-system", "value"),
        Input("client-selector", "value"),
        State("maintenance-activity-equipment", "value"),
        State("maintenance-activity-subsystem", "value"),
    )
    def update_activity_cascades(selected_systems, client, current_equipment, current_subsystems):
        if not client:
            raise PreventUpdate
        repo = get_repository(mode="parquet", client=client)
        equipment = repo.get_available_equipment(selected_systems or None)
        subsystems = repo.get_available_subsystems(selected_systems or None, current_equipment or None)
        equipment_set = set(equipment)
        subsystem_set = set(subsystems)
        equipment_value = [value for value in (current_equipment or []) if value in equipment_set] or None
        subsystem_value = [value for value in (current_subsystems or []) if value in subsystem_set] or None
        return _options(equipment), equipment_value, _options(subsystems), subsystem_value


    @app.callback(
        Output("maintenance-emin-pareto-view", "data"),
        Input("maintenance-pareto-actions-show-all", "n_clicks"),
        Input("maintenance-pareto-hours-show-all", "n_clicks"),
        Input("maintenance-month", "value"),
        Input("maintenance-summary-fleet", "value"),
        Input("maintenance-summary-equipment", "value"),
        Input("maintenance-pareto-systems", "value"),
        Input("client-selector", "value"),
        State("maintenance-emin-pareto-view", "data"),
        prevent_initial_call=True,
    )
    def update_emin_pareto_view(actions_clicks, hours_clicks, month, fleets, equipment, systems, client, current):
        if str(client or "").upper() != "EMIN":
            return {"actions": False, "hours": False}
        state = dict(current or {})
        trigger = ctx.triggered_id
        if trigger == "maintenance-pareto-actions-show-all":
            state["actions"] = True
        elif trigger == "maintenance-pareto-hours-show-all":
            state["hours"] = True
        elif trigger == "maintenance-pareto-systems":
            state["actions"] = False
        else:
            state = {"actions": False, "hours": False}
        return state

    @app.callback(
        Output("maintenance-monthly-store", "data"),
        Output("maintenance-load-timestamp", "data"),
        Input("client-selector", "value"),
        Input("maintenance-month", "value"),
        Input("maintenance-summary-fleet", "value"),
        Input("maintenance-summary-equipment", "value"),
        Input("maintenance-activity-system", "value"),
        Input("maintenance-activity-subsystem", "value"),
        Input("maintenance-activity-equipment", "value"),
        Input("maintenance-pareto-systems", "value"),
        Input("maintenance-pareto-metric", "value"),
        Input("btn-refresh-maintenance", "n_clicks"),
        prevent_initial_call=False,
    )
    def load_monthly_payload(client, month, selected_fleets, summary_equipment, systems, subsystems, equipment, pareto_systems, pareto_metric, n_clicks):
        if not client:
            return _empty_contract(), None
        try:
            repo = get_repository(mode="parquet", client=client)
            if _refresh_requested():
                repo.refresh()
            selected_equipment = None if summary_equipment in (None, "", "__all__") else [summary_equipment]
            payload = repo.get_monthly_payload(
                month,
                systems=systems,
                equipment=selected_equipment,
                subsystems=subsystems,
                fleets=selected_fleets or None,
                pareto_systems=pareto_systems,
                pareto_metric=pareto_metric or "actions",
            )
            return payload, datetime.now().isoformat()
        except Exception as exc:
            return {
                **_empty_contract(),
                "status": "error",
                "meta": {"client": str(client).upper(), "period": month, "period_label": month or "Sin datos", "error": str(exc)},
            }, None


    @app.callback(
        Output("maintenance-kpi-availability-est", "children"),
        Output("maintenance-kpi-downtime-est", "children"),
        Output("maintenance-kpi-mtbf-est", "children"),
        Output("maintenance-kpi-mttr-est", "children"),
        Output("maintenance-kpi-equipment", "children"),
        Output("maintenance-kpi-actions", "children"),
        Output("maintenance-kpi-records", "children"),
        Output("maintenance-kpi-systems", "children"),
        Output("maintenance-kpi-days", "children"),
        Output("maintenance-kpi-motor-share", "children"),
        Output("maintenance-month-status", "children"),
        Output("maintenance-chart-daily", "figure"),
        Output("maintenance-chart-daily-equipment", "figure"),
        Output("maintenance-chart-pareto", "figure"),
        Output("maintenance-chart-pareto-tren-fuerza", "figure"),
        Output("maintenance-chart-system-mix", "figure"),
        Output("maintenance-chart-equipment", "figure"),
        Output("maintenance-chart-matrix", "figure"),
        Output("maintenance-activity-table", "children"),
        Output("maintenance-summary-detail-table", "children"),
        Output("maintenance-chart-pareto-title", "children"),
        Output("maintenance-chart-pareto-tren-fuerza-title", "children"),
        Output("maintenance-pareto-status", "children"),
        Output("maintenance-unit-navigation-table", "data"),
        Output("maintenance-unit-navigation-table", "selected_rows"),
        Output("maintenance-system-mix-note", "children"),
        Output("maintenance-context-kpi-note", "children"),
        Input("maintenance-monthly-store", "data"),
        Input("maintenance-emin-pareto-view", "data"),
    )
    def render_monthly_payload(payload, pareto_view=None):
        payload = payload or _empty_contract()
        status = payload.get("status")
        meta = payload.get("meta", {}) or {}
        client = str(meta.get("client") or "").strip().upper()
        presentation = _pareto_presentation(meta.get("client"), meta)
        if status == "error":
            message = "No se dispone de esta información momentáneamente." if client == "EMIN" else payload.get("meta", {}).get("error", "Error desconocido")
            empty = create_empty_figure("Error al cargar datos")
            detail_message = html.P("No se pudo cargar el detalle.", className="text-danger")
            return "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", html.Div(f"Error al cargar mantenciones: {message}", className="alert alert-danger"), empty, empty, empty, empty, empty, empty, empty, detail_message, detail_message, presentation["equipment_title"], presentation["system_title"], "", [], [], "", ""
        if status != "ok":
            empty = create_empty_figure("Sin datos para este período")
            message = "No hay acciones registradas para los filtros seleccionados."
            detail_message = html.P(message, className="text-muted text-center p-3")
            kpis = payload.get("kpis", {}) or {}
            return _format_estimated(kpis.get("availability_est_pct"), "%"), _format_estimated(kpis.get("downtime_est_hours"), "h"), _format_estimated(kpis.get("mtbf_est_hours"), "h"), _format_estimated(kpis.get("mttr_est_hours"), "h"), "—", "—", "—", "—", "—", "—", html.Div(message, className="alert alert-warning"), empty, empty, empty, empty, empty, empty, empty, detail_message, detail_message, presentation["equipment_title"], presentation["system_title"], "", [], [], "", ""

        kpis = payload.get("kpis", {})
        data = payload.get("data", {})
        banner = None
        context_items = []
        if client != "EMIN" and not meta.get("is_current_period"):
            context_items.append(html.Span(
                f"Período {meta.get('period_label', 'N/A')} · histórico respecto a hoy",
                className="badge text-bg-light border me-2",
            ))
        time_coverage = (meta.get("estimated_kpis") or {}).get("coverage", {})
        time_meta = meta.get("estimated_kpis", {}) or {}
        if client != "EMIN" and time_meta.get("status") != "source" and time_meta.get("reason"):
            context_items.append(html.Span(
                f"Disponibilidad/downtime sin estimación: {time_meta['reason']}",
                className="text-warning small d-block",
            ))
        reconciliation = time_meta.get("reconciliation", {}) or {}
        if client != "EMIN" and reconciliation.get("status") == "mismatch":
            context_items.append(html.Span(
                f"Advertencia: query 4/7/8/9 no concilian (diferencia máxima {reconciliation.get('max_delta_hours')} h).",
                className="text-warning small d-block",
            ))
        elif client != "EMIN" and reconciliation.get("status") == "incomplete" and reconciliation.get("source_totals_hours"):
            sources = ", ".join(reconciliation["source_totals_hours"])
            context_items.append(html.Span(
                f"Conciliación parcial de horas; fuentes comparables disponibles: {sources}.",
                className="text-muted small d-block",
            ))
        if client != "EMIN" and time_coverage.get("partial_month"):
            observed = time_coverage.get("observed_days")
            calendar = time_coverage.get("calendar_days")
            context_items.append(html.Span(
                f"Mes parcial · {observed}/{calendar} días observados",
                className="badge text-bg-warning me-2",
            ))
        reliability = meta.get("reliability_kpis", {}) or {}
        confidence_note = None
        if client != "EMIN" and reliability.get("rows"):
            low = int(reliability.get("low_confidence_rows") or 0)
            total = int(reliability.get("rows") or 0)
            valid_mtbf = int(reliability.get("valid_mtbf_rows") or 0)
            valid_mttr = int(reliability.get("valid_mttr_rows") or 0)
            confidence_note = html.Span(
                f"Query 5: {valid_mtbf}/{total} filas válidas MTBF, {valid_mttr}/{total} MTTR; {low} con baja confianza.",
                className="text-muted small me-2",
            )
            context_items.append(confidence_note)
        elif client != "EMIN" and reliability.get("reason"):
            context_items.append(html.Span(
                f"MTBF/MTTR sin estimación: {reliability['reason']}",
                className="text-warning small d-block",
            ))
        reference_date = time_coverage.get("reference_date")
        reference_note = html.Span(
            f"Estado puntual de equipos al {reference_date} (no es estado de hoy).",
            className="text-muted small me-2",
        ) if reference_date else None
        if client != "EMIN" and reference_note:
            context_items.append(reference_note)
        long_note = html.Span(
            "La fuente identifica registros de intervención anormalmente largos; las horas no se truncaron.",
            className="text-warning small",
        ) if time_coverage.get("long_records") or time_coverage.get("touched_by_long_record") else None
        if client != "EMIN" and long_note:
            context_items.append(long_note)
        downtime_note = html.Span(
            "Disponibilidad calendario y downtime son estimaciones sobre horas-equipo intervenidas; no confirman una detención operacional.",
            className="text-muted small d-block mt-1",
        )
        context_items.append(downtime_note)
        banner = html.Div(context_items, className="small")
        motor_share = kpis.get("motor_share_pct")
        motor_share_label = f"{motor_share:.1f}%" if isinstance(motor_share, (int, float)) else "—"
        pareto_meta = meta.get("pareto", {}) or {}
        selected_systems = pareto_meta.get("selected_systems", [])
        available_systems = pareto_meta.get("available_systems", [])
        pareto_metric = pareto_meta.get("metric", "actions")
        selected_label = _pareto_system_selection_label(
            client, selected_systems, available_systems
        )
        chart_system_label = selected_label if selected_systems else presentation["system_label"]
        system_mix_note = ""
        context_kpi_note = (
            "Días según fecha operacional · Actividad en Motor como porcentaje de acciones únicas."
            if client == "EMIN"
            else ""
        )
        if client == "EMIN":
            pareto_status = "El filtro de sistemas se aplica solo al Pareto de acciones; las horas y los indicadores conservan el mes, la flota y la unidad seleccionados."
        elif not selected_systems:
            pareto_status = "Selecciona uno o más sistemas para ver el Pareto. Este filtro no afecta los KPIs ni los otros gráficos."
        elif pareto_meta.get("reason"):
            pareto_status = f"{pareto_meta['reason']} El filtro aplica solo a este Pareto."
        else:
            unit = "horas-equipo" if pareto_metric == "hours" else "acciones únicas"
            pareto_status = f"{selected_label} · {unit} por equipo. Filtro exclusivo de este Pareto."
        pareto_title = (
            f"Pareto de horas intervenidas por equipo · {selected_label}"
            if pareto_metric == "hours"
            else f"Pareto de actividad por equipo · {selected_label}"
        ) if selected_systems else "Pareto de actividad por equipo"
        if client == "EMIN":
            view = pareto_view or {}
            equipment_systems = _display_system_rows(data.get("equipment_system_mix", []), client)
            action_chart = create_emin_actions_pareto_chart(
                _display_system_rows(data.get("emin_action_systems", []), client),
                show_all=bool(view.get("actions")),
                palette_systems=equipment_systems.get("system_name", pd.Series(dtype=str)).dropna(),
            )
            hours_chart = create_emin_hours_pareto_chart(
                pd.DataFrame(data.get("emin_hours_pareto", [])),
                show_all=bool(view.get("hours")),
            )
            pareto_title = f"Pareto de acciones por unidad · {selected_label}" if selected_systems else "Pareto de acciones por unidad"
            second_title = "Pareto de horas intervenidas por unidad"
        else:
            action_chart = create_equipment_pareto_chart(
                pd.DataFrame(data.get("pareto", [])),
                system_label=chart_system_label,
                metric=pareto_metric,
                compact=False,
            )
            hours_chart = create_equipment_pareto_chart(
                _display_system_rows(data.get("system_pareto", []) if presentation["all_systems"] else data.get("train_force_pareto", []), client),
                system_label=presentation["system_label"] if presentation["all_systems"] else "Tren de Fuerza",
            )
            second_title = presentation["system_title"]
        return (
            _format_estimated(kpis.get("availability_est_pct"), "%"),
            _format_estimated(kpis.get("downtime_est_hours"), "h"),
            _format_estimated(kpis.get("mtbf_est_hours"), "h"),
            _format_estimated(kpis.get("mttr_est_hours"), "h"),
            str(kpis.get("equipment", "—")),
            str(kpis.get("actions", "—")),
            str(kpis.get("records", "—")),
            str(kpis.get("systems", "—")),
            str(kpis.get("activity_days", "—")),
            motor_share_label,
            banner,
            create_daily_intervention_hours_chart(
                pd.DataFrame(data.get("daily", [])),
                unavailable_message="No se dispone de esta información momentáneamente." if client == "EMIN" else "La fuente no trae horas-equipo intervenidas",
            ),
            create_daily_equipment_chart(pd.DataFrame(data.get("daily", []))),
            action_chart,
            hours_chart,
            create_system_activity_chart(
                _display_system_rows(data.get("system_mix", []), client),
                include_all_systems=presentation["all_systems"],
            ),
            create_equipment_activity_chart(
                _display_system_rows(data.get("equipment_system_mix") or data.get("equipment", []), client),
                include_all_systems=presentation["all_systems"],
                compact=client == "EMIN",
            ),
            create_activity_matrix(pd.DataFrame(data.get("matrix", []))),
            create_activity_table(data.get("detail", [])),
            create_activity_table(data.get("detail", []), compact=client == "EMIN"),
            pareto_title,
            second_title,
            html.Span(pareto_status),
            data.get("unit_status", []),
            [],
            system_mix_note,
            context_kpi_note,
        )


    @app.callback(
        Output("maintenance-unit-detail-panel", "children"),
        Input("maintenance-monthly-store", "data"),
        Input("maintenance-summary-equipment", "value"),
    )
    def render_unit_detail(payload, selected_equipment):
        is_emin = str(((payload or {}).get("meta") or {}).get("client") or "").upper() == "EMIN"
        if selected_equipment in (None, "", "__all__"):
            return html.Div(
                [html.I(className="fas fa-hand-pointer me-2"), "Selecciona una unidad en la tabla o en el filtro superior."],
                className="alert alert-light h-100 mb-0",
            )
        rows = (((payload or {}).get("data") or {}).get("unit_status") or [])
        unit = next((row for row in rows if str(row.get("equipment")) == str(selected_equipment)), None)
        if unit is None:
            return html.Div(
                [html.Strong(str(selected_equipment)), html.P("No se dispone de esta información momentáneamente." if is_emin else "No hay estado puntual disponible en query 10 para esta unidad.", className="small text-muted mb-0 mt-2")],
                className="alert alert-warning h-100 mb-0",
            )
        reference = unit.get("reference_date") or "sin fecha de referencia"
        historical = [
            row for row in (((payload or {}).get("data") or {}).get("historical_failures") or [])
            if str(row.get("machine_code")) == str(selected_equipment)
        ]
        historical.sort(
            key=lambda row: (
                float(row.get("n_failure_records") or 0),
                float(row.get("n_failure_actions") or 0),
            ),
            reverse=True,
        )
        ranking = html.Ul(
            [
                html.Li(
                    f"{row.get('component_name') or 'Componente sin nombre'} · "
                    f"{row.get('n_failure_records') or 0} registros / "
                    f"{row.get('n_failure_actions') or 0} acciones"
                )
                for row in historical[:5]
            ],
            className="small ps-3 mb-0",
        ) if historical else html.P("No se dispone de esta información momentáneamente." if is_emin else "Sin filas en el ranking histórico.", className="small text-muted mb-0")
        items = [
            html.H5(str(selected_equipment), className="mb-2"),
            html.P([html.Span("Estado: ", className="fw-semibold"), str(unit.get("equipment_status") or "Sin estado")], className="mb-2"),
            html.P([html.Span("Intervención abierta: ", className="fw-semibold"), str(unit.get("has_open_intervention") or "Sin dato")], className="mb-2"),
            html.P([html.Span("Última acción: ", className="fw-semibold"), str(unit.get("last_action_date") or "Sin dato")], className="mb-2"),
            html.P([html.Span("Días desde mantención: ", className="fw-semibold"), str(unit.get("days_since_last_maintenance") if unit.get("days_since_last_maintenance") is not None else "Sin dato")], className="mb-2"),
            html.Small(f"Fotografía de estado al {reference}. No equivale a una detención operacional confirmada.", className="text-muted") if not is_emin else None,
            html.H6("Ranking histórico de componentes", className="mt-3 mb-1"),
            html.Small("Query 6 · histórico acumulado; no se limita al mes seleccionado.", className="text-muted d-block mb-1") if not is_emin else None,
            ranking,
        ]
        if unit.get("n_long_records") and not is_emin:
            items.append(html.P(f"Registros largos reportados: {unit['n_long_records']}", className="text-warning small mt-2 mb-0"))
        return html.Div(items, className="border rounded bg-light p-3 h-100")


    @app.callback(
        Output("maintenance-weekly-store", "data"),
        Input("client-selector", "value"),
        Input("maintenance-week", "value"),
        Input("maintenance-week-equipment", "value"),
        Input("btn-refresh-maintenance", "n_clicks"),
        prevent_initial_call=False,
    )
    def load_weekly_payload(client, week, equipment, n_clicks):
        if not client:
            return {"status": "empty", "meta": {}, "summary": [], "tasks": []}
        try:
            repo = get_repository(mode="parquet", client=client)
            if _refresh_requested():
                repo.refresh()
            return repo.get_weekly_evidence(week, equipment=equipment)
        except Exception as exc:
            return {"status": "error", "meta": {"error": str(exc)}, "summary": [], "tasks": []}


    @app.callback(
        Output("maintenance-week-status", "children"),
        Output("maintenance-week-summary-table", "children"),
        Output("maintenance-week-task-table", "children"),
        Input("maintenance-weekly-store", "data"),
    )
    def render_weekly_payload(payload):
        payload = payload or {"status": "empty", "meta": {}, "summary": [], "tasks": []}
        status = payload.get("status")
        if status == "error":
            msg = payload.get("meta", {}).get("error", "Error desconocido")
            return html.Div(f"Error al cargar evidencia semanal: {msg}", className="alert alert-danger"), create_week_summary_table([]), create_week_task_table([])
        if status == "empty":
            return html.Div("No hay evidencia semanal disponible.", className="alert alert-warning"), create_week_summary_table([]), create_week_task_table([])
        invalid = payload.get("meta", {}).get("invalid_rows", 0)
        alert = html.Div(f"Se omitieron {invalid} filas con tareas no interpretables.", className="alert alert-warning") if invalid else None
        return alert, create_week_summary_table(payload.get("summary", [])), create_week_task_table(payload.get("tasks", []))
