"""Callbacks for the productive Mantenciones page."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from dash import Input, Output, State, ctx, html
from dash.exceptions import MissingCallbackContextException, PreventUpdate

from dashboard.tabs.tab_mantenciones_general import (
    create_activity_matrix,
    create_activity_table,
    create_daily_activity_chart,
    create_empty_figure,
    create_equipment_activity_chart,
    create_equipment_pareto_chart,
    create_system_activity_chart,
    create_week_summary_table,
    create_week_task_table,
)
from src.data.maintenance_repository import PARETO_SCOPE, get_repository


def _options(values):
    return [{"label": value, "value": value} for value in values]


def _empty_contract():
    pareto_scope = {**PARETO_SCOPE, "system_aliases": list(PARETO_SCOPE["system_aliases"])}
    return {
        "status": "empty",
        "meta": {"period": None, "period_label": "Sin datos", "available_months": [], "source_start": None, "source_end": None, "is_current_period": False, "detail_total": 0, "pareto_scope": pareto_scope, "estimated_kpis": {"status": "unavailable", "label": "ESTIMADO", "reason": "Sin fuente cargada."}},
        "filters": {"systems": [], "equipment": [], "subsystems": []},
        "kpis": {"equipment": 0, "actions": 0, "records": 0, "systems": 0, "activity_days": 0, "motor_share_pct": None, "availability_est_pct": None, "downtime_est_hours": None, "mtbf_est_hours": None, "mttr_est_hours": None},
        "data": {"daily": [], "system_mix": [], "pareto": [], "equipment": [], "matrix": [], "detail": []},
    }


def _refresh_requested() -> bool:
    """Return whether the current invocation came from the refresh button."""
    try:
        return ctx.triggered_id == "btn-refresh-maintenance"
    except MissingCallbackContextException:
        return False


def _format_estimated(value, suffix: str) -> str:
    """Format proxy KPIs without inventing a zero for missing values."""
    if not isinstance(value, (int, float)):
        return "—"
    if suffix == "%":
        return f"{value:.1f}%"
    return f"{value:,.1f} h"


def _source_alert(meta: dict):
    end = meta.get("source_end")
    if not end:
        return html.Div([html.I(className="fas fa-database me-2"), "No hay datos de mantenciones disponibles para este cliente."], className="alert alert-warning")
    date_label = str(end)[:10]
    estimated = meta.get("estimated_kpis", {})
    coverage = estimated.get("coverage", {})
    coverage_label = coverage.get("window_label")
    estimated_note = f" KPIs ESTIMADOS: {coverage_label}." if coverage_label else ""
    return html.Div(
        [
            html.I(className="fas fa-database me-2"),
            html.Span("Cobertura de fuente: ", className="fw-bold"),
            html.Span(f"{meta.get('source_start', '')[:10]} a {date_label}. "),
            html.Span(f"El último período disponible se muestra por defecto; la fuente puede estar histórica.{estimated_note}", className="text-muted"),
        ],
        className="alert alert-info",
    )


def register_mantenciones_general_callbacks(app):
    """Register all callbacks against the concrete Dash app instance."""

    @app.callback(
        Output("maintenance-metadata-store", "data"),
        Output("maintenance-source-alert", "children"),
        Output("maintenance-month", "options"),
        Output("maintenance-month", "value"),
        Output("maintenance-week", "options"),
        Output("maintenance-week", "value"),
        Output("maintenance-week-equipment", "options"),
        Output("maintenance-activity-system", "options"),
        Input("client-selector", "value"),
        Input("btn-refresh-maintenance", "n_clicks"),
        prevent_initial_call=False,
    )
    def load_maintenance_metadata(client, n_clicks):
        if not client:
            return {}, _source_alert({}), [], None, [], None, [], []
        try:
            repo = get_repository(mode="parquet", client=client)
            if _refresh_requested():
                repo.refresh()
            months = repo.get_available_months()
            weeks = repo.get_available_weeks()
            latest_payload = repo.get_monthly_payload(months[-1] if months else None)
            meta = latest_payload.get("meta", {})
            meta.update(
                {
                    "available_months": months,
                    "available_weeks": weeks,
                    "equipment": repo.get_available_equipment(),
                    "systems": repo.get_available_systems(),
                    "subsystems": repo.get_available_subsystems(),
                }
            )
            return (
                meta,
                _source_alert(meta),
                _options(months),
                months[-1] if months else None,
                _options(weeks),
                weeks[-1] if weeks else None,
                _options(meta["equipment"]),
                _options(meta["systems"]),
            )
        except Exception as exc:
            return {}, html.Div(f"Error al cargar la fuente de mantenciones: {exc}", className="alert alert-danger"), [], None, [], None, [], []


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
        Output("maintenance-monthly-store", "data"),
        Output("maintenance-load-timestamp", "data"),
        Input("client-selector", "value"),
        Input("maintenance-month", "value"),
        Input("maintenance-activity-system", "value"),
        Input("maintenance-activity-subsystem", "value"),
        Input("maintenance-activity-equipment", "value"),
        Input("btn-refresh-maintenance", "n_clicks"),
        prevent_initial_call=False,
    )
    def load_monthly_payload(client, month, systems, subsystems, equipment, n_clicks):
        if not client:
            return _empty_contract(), None
        try:
            repo = get_repository(mode="parquet", client=client)
            if _refresh_requested():
                repo.refresh()
            payload = repo.get_monthly_payload(month, systems=systems, equipment=equipment, subsystems=subsystems)
            return payload, datetime.now().isoformat()
        except Exception as exc:
            return {
                **_empty_contract(),
                "status": "error",
                "meta": {"period": month, "period_label": month or "Sin datos", "error": str(exc)},
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
        Output("maintenance-chart-pareto", "figure"),
        Output("maintenance-chart-system-mix", "figure"),
        Output("maintenance-chart-equipment", "figure"),
        Output("maintenance-chart-matrix", "figure"),
        Output("maintenance-activity-table", "children"),
        Input("maintenance-monthly-store", "data"),
    )
    def render_monthly_payload(payload):
        payload = payload or _empty_contract()
        status = payload.get("status")
        if status == "error":
            message = payload.get("meta", {}).get("error", "Error desconocido")
            empty = create_empty_figure("Error al cargar datos")
            return "—", "—", "—", "—", "—", "—", "—", "—", "—", html.Div(f"Error al cargar mantenciones: {message}", className="alert alert-danger"), empty, empty, empty, empty, empty, html.P("No se pudo cargar el detalle.", className="text-danger")
        if status != "ok":
            empty = create_empty_figure("Sin datos para este período")
            message = "No hay acciones registradas para los filtros seleccionados."
            return "—", "—", "—", "—", "—", "—", "—", "—", "—", html.Div(message, className="alert alert-warning"), empty, empty, empty, empty, empty, html.P(message, className="text-muted text-center p-3")

        kpis = payload.get("kpis", {})
        data = payload.get("data", {})
        meta = payload.get("meta", {})
        banner = None
        if not meta.get("is_current_period"):
            banner = html.Div(
                f"Período histórico seleccionado: {meta.get('period_label', 'N/A')}. Último dato de fuente: {str(meta.get('source_end', ''))[:10]}.",
                className="alert alert-warning",
            )
        motor_share = kpis.get("motor_share_pct")
        motor_share_label = f"{motor_share:.1f}%" if isinstance(motor_share, (int, float)) else "—"
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
            create_daily_activity_chart(pd.DataFrame(data.get("daily", []))),
            create_equipment_pareto_chart(pd.DataFrame(data.get("pareto", []))),
            create_system_activity_chart(pd.DataFrame(data.get("system_mix", []))),
            create_equipment_activity_chart(pd.DataFrame(data.get("equipment", []))),
            create_activity_matrix(pd.DataFrame(data.get("matrix", []))),
            create_activity_table(data.get("detail", [])),
        )


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
