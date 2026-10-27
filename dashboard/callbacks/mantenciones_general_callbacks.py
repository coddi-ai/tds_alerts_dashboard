"""Callbacks for the productive Mantenciones page."""

from __future__ import annotations

from src.i18n import t
import logging
from datetime import datetime

import pandas as pd
from dash import Input, Output, State, ctx, html, no_update
from dash.exceptions import MissingCallbackContextException, PreventUpdate

from dashboard.tabs.tab_mantenciones_general import (
    EQUIPMENT_TOP_N,
    count_activity_equipment,
    create_activity_matrix,
    create_activity_table,
    create_daily_activity_chart,
    create_daily_equipment_chart,
    create_daily_intervention_hours_chart,
    create_empty_figure,
    create_equipment_activity_chart,
    create_actions_pareto_chart,
    create_hours_pareto_chart,
    create_system_activity_chart,
    create_week_summary_table,
    create_week_task_table,
    actions_pareto_summary,
    hours_pareto_summary,
    percent_value,
)
from src.data.maintenance_repository import PARETO_SCOPE, get_repository

logger = logging.getLogger(__name__)

# Source value for actions with no technical system attributed.
_GENERIC_SYSTEM = "Equipo"

# Placeholder values the repository writes into the data itself, with the
# catalog key that renders each one. Real data values are never translated.
_SENTINEL_KEYS = {
    "Sin sistema": "reliability_report.no_system",
    "Sin subsistema": "reliability_report.no_subsystem",
    "Sin detalle": "reliability_report.no_detail",
    "Sin atribución única": "reliability_report.no_unique_component",
    "Sin estado": "reliability_report.no_status",
    "Sin dato": "reliability_report.no_data",
    "Sí": "reliability_report.yes",
    "No": "reliability_report.no",
}


def _pareto_actions_title() -> str:
    return t("reliability_report.pareto_actions_title")


def _pareto_hours_title() -> str:
    return t("reliability_report.pareto_hours_title")


def _unavailable_message() -> str:
    """Shown instead of any exception text or source diagnostic: end users never
    see internal detail, which goes to the log."""
    return t("reliability_report.unavailable")


def _localize(value):
    """Render a repository placeholder in the current language; other values pass through."""
    key = _SENTINEL_KEYS.get(value) if isinstance(value, str) else None
    return t(key) if key else value


def _localize_columns(rows, columns):
    return [
        {**row, **{column: _localize(row[column]) for column in columns if column in row}}
        for row in rows or []
    ]

# Confirmed Disponibilidad targets by client (upper case), in percent. None are
# confirmed yet, so the card keeps the same neutral treatment as its siblings
# instead of inventing a threshold.
AVAILABILITY_TARGET_PCT_BY_CLIENT: dict[str, float] = {}

_EQUIPMENT_GRAPH_BASE_HEIGHT = 340
_EQUIPMENT_GRAPH_ROW_HEIGHT = 26


def _options(values):
    return [{"label": value, "value": value} for value in values]


def systems_summary_label(selected, available) -> str:
    """Summary text of the Sistema control for none, every and some systems."""
    chosen = list(selected or [])
    if not chosen:
        return t("reliability_report.systems_none")
    if not available or set(chosen) >= set(available):
        return t("reliability_report.systems_all")
    return t("reliability_report.systems_count", count=len(chosen))


def availability_status(value, client):
    """Severity dot + caption for Disponibilidad, or None when no target is confirmed."""
    target = AVAILABILITY_TARGET_PCT_BY_CLIENT.get(str(client or "").strip().upper())
    if target is None or not isinstance(value, (int, float)) or isinstance(value, bool) or pd.isna(value):
        return None
    meets = value >= target
    return [
        html.Span(className=f"maintenance-status-dot maintenance-status-dot--{'ok' if meets else 'below'}", **{"aria-hidden": "true"}),
        html.Span(
            t("reliability_report.target_met" if meets else "reliability_report.target_below", target=f"{target:g}"),
            className="maintenance-status-caption",
        ),
    ]


def _format_days(value) -> str:
    """Days since maintenance always render with one decimal."""
    number = pd.to_numeric(value, errors="coerce")
    return t("reliability_report.no_data") if pd.isna(number) else f"{number:.1f}"


def _unit_status_rows(rows):
    """Unit table rows with the days column numeric (the table formats it)."""
    cleaned = []
    for row in rows or []:
        number = pd.to_numeric(row.get("days_since_last_maintenance"), errors="coerce")
        cleaned.append({**row, "days_since_last_maintenance": None if pd.isna(number) else float(number)})
    return _localize_columns(cleaned, ("has_open_intervention", "equipment_status"))


def _system_palette(meta, data, available_systems):
    """System colour universe shared by every system-coloured chart."""
    equipment_systems = _display_system_rows(data.get("equipment_system_mix", []))
    return [
        _display_system_label(system)
        for system in meta.get("filter_systems", available_systems)
    ] or equipment_systems.get("system_name", pd.Series(dtype=str)).dropna().tolist()


def _equipment_toggle_label(total: int, expanded: bool) -> str:
    if expanded:
        return t("reliability_report.show_less")
    extra = total - EQUIPMENT_TOP_N
    return t("reliability_report.show_one_more") if extra == 1 else t("reliability_report.show_more", count=extra)


def _equipment_view(payload, expanded):
    """Equipos con Mayor Actividad: figure, toggle label, toggle hidden, graph style.

    Shows the top units and folds the rest behind the toggle.
    """
    meta = (payload or {}).get("meta", {}) or {}
    data = (payload or {}).get("data", {}) or {}
    available_systems = (meta.get("pareto", {}) or {}).get("available_systems", [])
    frame = _display_system_rows(data.get("equipment_system_mix") or data.get("equipment", []))
    total = count_activity_equipment(frame, include_all_systems=True)
    collapsible = total > EQUIPMENT_TOP_N
    show_all = bool(expanded) and collapsible
    figure = create_equipment_activity_chart(
        frame,
        include_all_systems=True,
        compact=True,
        palette_systems=_system_palette(meta, data, available_systems),
        limit=None if show_all else EQUIPMENT_TOP_N,
    )
    rows = total if show_all else min(total, EQUIPMENT_TOP_N)
    height = max(_EQUIPMENT_GRAPH_BASE_HEIGHT, 120 + _EQUIPMENT_GRAPH_ROW_HEIGHT * rows)
    return (
        figure,
        _equipment_toggle_label(total, show_all) if collapsible else "",
        not collapsible,
        {"height": f"{height}px"},
    )


def _pareto_system_options(values):
    options = _options(values)
    for option in options:
        if option["value"] == _GENERIC_SYSTEM:
            option["label"] = t("reliability_report.general_system_option")
        else:
            option["label"] = _localize(option["label"])
    return options


def _fleet_options(values):
    """Fleet options: "otros" is the repository's label for units outside the catalog."""
    return [
        {"label": t("reliability_report.fleet_other") if value == "otros" else value, "value": value}
        for value in values
    ]


def _effective_system_filter(selected_systems, available_systems):
    """Treat an empty or complete Sistema selection as the all-systems scope."""
    selected = list(selected_systems or [])
    available = list(available_systems or [])
    if not selected or set(selected) == set(available):
        return None
    return selected


def _display_system_label(value):
    if value is None or pd.isna(value):
        return t("reliability_report.no_system")
    if value == _GENERIC_SYSTEM:
        return t("reliability_report.general_system")
    return str(_localize(value))


def _display_system_rows(rows):
    frame = pd.DataFrame(rows)
    if "system_name" in frame.columns:
        frame["system_name"] = frame["system_name"].map(_display_system_label)
    return frame


def _pareto_system_selection_label(selected_systems, available_systems):
    selected = list(selected_systems or [])
    available = list(available_systems or [])
    if not selected:
        return ""
    if available and set(selected) == set(available):
        return t("reliability_report.systems_all")
    return ", ".join(_display_system_label(system) for system in selected)


def _equipment_options(values):
    return [{"label": t("tab_health_index.todas"), "value": "__all__"}] + [
        {"label": value, "value": value} for value in values if value != "__all__"
    ]


def _empty_contract():
    pareto_scope = {**PARETO_SCOPE, "system_aliases": list(PARETO_SCOPE["system_aliases"])}
    return {
        "status": "empty",
        "meta": {"period": None, "period_label": "Sin datos", "available_months": [], "filter_systems": [], "source_start": None, "source_end": None, "is_current_period": False, "detail_total": 0, "pareto_scope": pareto_scope, "pareto": {"available_systems": [], "selected_systems": [], "metric": "actions", "hours_available": False, "system_filter_partial": False, "metric_options": [{"label": "Acciones", "value": "actions"}, {"label": "Horas", "value": "hours", "disabled": True}]}, "estimated_kpis": {"status": "unavailable", "label": "FUENTE", "reason": t("mantenciones_general_callbacks.sin_fuente_cargada")}},
        "filters": {"fleets": [], "systems": [], "equipment": [], "subsystems": []},
        "kpis": {"equipment": 0, "actions": 0, "records": 0, "systems": 0, "activity_days": 0, "motor_share_pct": None, "availability_est_pct": None, "downtime_est_hours": None, "mtbf_est_hours": None, "mttr_est_hours": None},
        "data": {"daily": [], "system_mix": [], "system_mix_detail": [], "pareto": [], "action_systems": [], "hours_pareto": [], "system_pareto": [], "train_force_pareto": [], "equipment": [], "equipment_system_mix": [], "matrix": [], "detail": [], "unit_status": []},
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


def _log_source_diagnostics(meta: dict) -> None:
    """Source names, coverage, fallbacks and reconciliation are diagnostics:
    they go to the log, never to the page."""
    estimated = meta.get("estimated_kpis", {}) or {}
    coverage = estimated.get("coverage", {}) or {}
    logger.info(
        "Mantenciones source: kind=%s coverage=%s partial_month=%s reason=%s",
        estimated.get("source_kind"), coverage.get("window_label"),
        coverage.get("partial_month"), estimated.get("reason"),
    )
    reconciliation = estimated.get("reconciliation", {}) or {}
    if reconciliation.get("status") in {"mismatch", "incomplete"}:
        logger.warning("Mantenciones hours reconciliation: %s", reconciliation)
    reliability = meta.get("reliability_kpis", {}) or {}
    if reliability:
        logger.info(
            "Reliability rows: %s valid MTBF, %s valid MTTR of %s; %s low confidence; reason=%s",
            reliability.get("valid_mtbf_rows"), reliability.get("valid_mttr_rows"),
            reliability.get("rows"), reliability.get("low_confidence_rows"), reliability.get("reason"),
        )
    if coverage.get("long_records") or coverage.get("touched_by_long_record"):
        logger.info("Mantenciones source has abnormally long intervention records (hours not truncated)")


def register_mantenciones_general_callbacks(app):
    """Register all callbacks against the concrete Dash app instance."""

    @app.callback(
        Output("maintenance-metadata-store", "data"),
        Output("maintenance-month", "options"),
        Output("maintenance-month", "value"),
        Output("maintenance-summary-fleet", "options"),
        Output("maintenance-summary-fleet", "value"),
        Output("maintenance-week", "options"),
        Output("maintenance-week", "value"),
        Output("maintenance-week-equipment", "options"),
        Output("maintenance-activity-system", "options"),
        Output("maintenance-summary-systems", "options"),
        Output("maintenance-summary-systems", "value"),
        Input("client-selector", "value"),
        Input("btn-refresh-maintenance", "n_clicks"),
        State("maintenance-month", "value"),
        State("maintenance-summary-fleet", "value"),
        State("maintenance-summary-systems", "value"),
        prevent_initial_call=False,
    )
    def load_maintenance_metadata(client, n_clicks, current_month=None, current_fleets=None, current_systems=None):
        if not client:
            return {}, [], None, [], [], [], None, [], [], [], []
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
            filter_systems = pareto_meta.get("available_systems", meta["systems"])
            meta["filter_systems"] = filter_systems
            _log_source_diagnostics(meta)
            # Refrescar re-queries the source; it must not move the selection.
            keep = _refresh_requested()
            month_value = current_month if keep and current_month in months else (months[-1] if months else None)
            fleet_value = [fleet for fleet in (current_fleets or []) if fleet in meta["fleets"]] if keep else []
            system_value = filter_systems
            if keep and current_systems is not None:
                system_value = [system for system in current_systems if system in filter_systems]
            return (
                meta,
                _options(months),
                month_value,
                _fleet_options(meta["fleets"]),
                fleet_value,
                _options(weeks),
                weeks[-1] if weeks else None,
                _options(meta["equipment"]),
                _options(meta["systems"]),
                _pareto_system_options(filter_systems),
                system_value,
            )
        except Exception:
            logger.exception("Mantenciones metadata failed for client %s", client)
            return {}, [], None, [], [], [], None, [], [], [], []


    @app.callback(
        Output("maintenance-systems-toggle", "children"),
        Input("maintenance-summary-systems", "value"),
        Input("maintenance-summary-systems", "options"),
    )
    def update_systems_summary(selected, options):
        available = [option.get("value") for option in (options or []) if isinstance(option, dict)]
        return systems_summary_label(selected, available)


    @app.callback(
        Output("maintenance-summary-systems", "value", allow_duplicate=True),
        Input("maintenance-systems-all", "n_clicks"),
        Input("maintenance-systems-none", "n_clicks"),
        State("maintenance-summary-systems", "options"),
        prevent_initial_call=True,
    )
    def set_all_or_no_systems(all_clicks, none_clicks, options):
        if ctx.triggered_id == "maintenance-systems-none":
            return []
        return [option.get("value") for option in (options or []) if isinstance(option, dict)]


    @app.callback(
        Output("maintenance-summary-equipment", "options"),
        Output("maintenance-summary-equipment", "value"),
        Input("maintenance-summary-fleet", "value"),
        Input("client-selector", "value"),
        Input("maintenance-unit-navigation-table", "selected_rows"),
        Input("maintenance-reset-unit", "n_clicks"),
        Input("maintenance-summary-systems", "value"),
        State("maintenance-unit-navigation-table", "data"),
        State("maintenance-summary-equipment", "value"),
        State("maintenance-metadata-store", "data"),
    )
    def update_summary_equipment_options(selected_fleets, client, selected_rows, reset_clicks, selected_systems, unit_rows, current_equipment, metadata):
        previous_equipment = current_equipment
        if not client:
            return _equipment_options([]), "__all__"
        repo = get_repository(mode="parquet", client=client)
        available_systems = (metadata or {}).get("filter_systems", [])
        system_filter = _effective_system_filter(selected_systems, available_systems)
        equipment = repo.get_available_equipment(systems=system_filter, fleets=selected_fleets or None)
        try:
            if ctx.triggered_id == "client-selector":
                current_equipment = "__all__"
            elif ctx.triggered_id == "maintenance-reset-unit":
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
        value = no_update if next_equipment == previous_equipment else next_equipment
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
        Output("maintenance-monthly-store", "data"),
        Output("maintenance-load-timestamp", "data"),
        Input("client-selector", "value"),
        Input("maintenance-month", "value"),
        Input("maintenance-summary-fleet", "value"),
        Input("maintenance-summary-equipment", "value"),
        Input("maintenance-summary-systems", "value"),
        Input("btn-refresh-maintenance", "n_clicks"),
        State("maintenance-metadata-store", "data"),
        prevent_initial_call=False,
    )
    def load_monthly_payload(client, month, selected_fleets, summary_equipment, summary_systems, n_clicks, metadata=None):
        if not client:
            return _empty_contract(), None
        # An explicit empty Sistema selection is "none", not "no filter". Before
        # the metadata for this client has loaded the control is still unset.
        if summary_systems == [] and str((metadata or {}).get("client") or "").upper() == str(client).upper():
            empty = _empty_contract()
            empty["meta"].update({"client": str(client).upper(), "period": month, "period_label": month or "Sin datos", "no_systems_selected": True})
            return empty, datetime.now().isoformat()
        try:
            repo = get_repository(mode="parquet", client=client)
            if _refresh_requested():
                repo.refresh()
            selected_equipment = None if summary_equipment in (None, "", "__all__") else [summary_equipment]
            payload = repo.get_monthly_payload(
                month,
                systems=summary_systems,
                equipment=selected_equipment,
                fleets=selected_fleets or None,
            )
            return payload, datetime.now().isoformat()
        except Exception as exc:
            logger.exception("Mantenciones monthly payload failed for client %s", client)
            return {
                **_empty_contract(),
                "status": "error",
                "meta": {"client": str(client).upper(), "period": month, "period_label": month or t("oil_machine_detail.sin_datos"), "error": str(exc)},
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
        Output("maintenance-context-kpi-note", "children"),
        Output("maintenance-kpi-availability-status", "children"),
        Output("maintenance-equipment-toggle", "children"),
        Output("maintenance-equipment-toggle", "hidden"),
        Output("maintenance-chart-equipment", "style"),
        Output("maintenance-pareto-actions-summary", "children"),
        Output("maintenance-pareto-hours-summary", "children"),
        Input("maintenance-monthly-store", "data"),
        State("maintenance-equipment-expanded", "data"),
    )
    def render_monthly_payload(payload, expanded=False):
        payload = payload or _empty_contract()
        status = payload.get("status")
        meta = payload.get("meta", {}) or {}
        client = str(meta.get("client") or "").strip().upper()
        if status == "error":
            logger.error("Mantenciones payload error: %s", meta.get("error"))
            message = _unavailable_message()
            empty = create_empty_figure(t("mantenciones_general_callbacks.error_al_cargar_datos"))
            detail_message = html.P(t("mantenciones_general_callbacks.no_se_pudo_cargar_el_detalle"), className="text-danger")
            return "—", "—", "—", "—", "—", "—", "—", "—", "—", "—", html.Div(message, className="alert alert-danger"), empty, empty, empty, empty, empty, empty, empty, detail_message, detail_message, _pareto_actions_title(), _pareto_hours_title(), "", [], [], "", None, "", True, _equipment_view(None, False)[3], "", ""
        if status != "ok":
            empty = create_empty_figure(t("mantenciones.no_data_for_period"))
            message = (
                t("reliability_report.select_one_system")
                if meta.get("no_systems_selected")
                else t("mantenciones_general_callbacks.no_hay_acciones_registradas_para_los")
            )
            detail_message = html.P(message, className="text-muted text-center p-3")
            kpis = payload.get("kpis", {}) or {}
            return _format_estimated(kpis.get("availability_est_pct"), "%"), _format_estimated(kpis.get("downtime_est_hours"), "h"), _format_estimated(kpis.get("mtbf_est_hours"), "h"), _format_estimated(kpis.get("mttr_est_hours"), "h"), "—", "—", "—", "—", "—", "—", html.Div(message, className="alert alert-warning"), empty, empty, empty, empty, empty, empty, empty, detail_message, detail_message, _pareto_actions_title(), _pareto_hours_title(), "", [], [], "", None, "", True, _equipment_view(None, False)[3], "", ""

        kpis = payload.get("kpis", {})
        data = payload.get("data", {})
        _log_source_diagnostics(meta)
        pareto_meta = meta.get("pareto", {}) or {}
        system_filter_partial = bool(pareto_meta.get("system_filter_partial"))
        context_items = []
        if system_filter_partial:
            context_items.append(html.Span(
                t("reliability_report.partial_note"),
                className="text-warning small d-block",
                role="status",
            ))
        banner = html.Div(context_items, className="small")
        selected_systems = pareto_meta.get("selected_systems", [])
        available_systems = pareto_meta.get("available_systems", [])
        selected_label = _pareto_system_selection_label(selected_systems, available_systems)
        if system_filter_partial:
            pareto_status = t("reliability_report.pareto_status_partial")
        elif not pareto_meta.get("hours_available"):
            pareto_status = t("reliability_report.pareto_status_no_hours")
        else:
            pareto_status = t("reliability_report.pareto_status_all")
        pareto_title = f"{_pareto_actions_title()} · {selected_label}" if selected_systems else _pareto_actions_title()
        palette_systems = _system_palette(meta, data, available_systems)
        action_chart = create_actions_pareto_chart(
            _display_system_rows(data.get("action_systems", [])),
            palette_systems=palette_systems,
        )
        hours_chart = (
            create_empty_figure(t("reliability_report.hours_unavailable_chart"), wrap_width=32)
            if system_filter_partial
            else create_hours_pareto_chart(pd.DataFrame(data.get("hours_pareto", [])))
        )
        equipment_chart, equipment_toggle_label, equipment_toggle_hidden, equipment_style = _equipment_view(payload, expanded)
        action_rows = _display_system_rows(data.get("action_systems", []))
        hours_rows = pd.DataFrame(data.get("hours_pareto", []))
        detail_rows = _localize_columns(
            _display_system_rows(data.get("detail", [])).to_dict("records"),
            ("subsystem_name", "detail", "component"),
        )
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
            percent_value(kpis.get("motor_share_pct")),
            banner,
            create_empty_figure(t("reliability_report.hours_unavailable_chart"), wrap_width=32)
            if system_filter_partial
            else create_daily_intervention_hours_chart(
                pd.DataFrame(data.get("daily", [])),
                unavailable_message=_unavailable_message(),
            ),
            create_daily_equipment_chart(pd.DataFrame(data.get("daily", [])), integer_ticks=True),
            action_chart,
            hours_chart,
            create_system_activity_chart(
                _display_system_rows(data.get("system_mix", [])),
                include_all_systems=True,
                palette_systems=palette_systems,
            ),
            equipment_chart,
            create_activity_matrix(pd.DataFrame(data.get("matrix", []))),
            create_activity_table(detail_rows),
            create_activity_table(detail_rows, compact=True),
            pareto_title,
            _pareto_hours_title(),
            html.Span(pareto_status),
            _unit_status_rows(data.get("unit_status", [])),
            [],
            t("reliability_report.kpi_note"),
            availability_status(kpis.get("availability_est_pct"), client),
            equipment_toggle_label,
            equipment_toggle_hidden,
            equipment_style,
            actions_pareto_summary(action_rows) if not action_rows.empty else "",
            "" if system_filter_partial else hours_pareto_summary(hours_rows),
        )


    @app.callback(
        Output("maintenance-equipment-expanded", "data"),
        Output("maintenance-chart-equipment", "figure", allow_duplicate=True),
        Output("maintenance-equipment-toggle", "children", allow_duplicate=True),
        Output("maintenance-chart-equipment", "style", allow_duplicate=True),
        Input("maintenance-equipment-toggle", "n_clicks"),
        State("maintenance-equipment-expanded", "data"),
        State("maintenance-monthly-store", "data"),
        prevent_initial_call=True,
    )
    def toggle_equipment_view(n_clicks, expanded, payload):
        """Expand or collapse the ranking in place, leaving every filter alone."""
        expanded = not expanded
        figure, label, _hidden, style = _equipment_view(payload, expanded)
        return expanded, figure, label, style


    @app.callback(
        Output("maintenance-unit-detail-panel", "children"),
        Input("maintenance-monthly-store", "data"),
        Input("maintenance-summary-equipment", "value"),
    )
    def render_unit_detail(payload, selected_equipment):
        if selected_equipment in (None, "", "__all__"):
            return html.Div(
                [html.I(className="fas fa-hand-pointer me-2"), t("reliability_report.pick_unit")],
                className="alert alert-light h-100 mb-0",
            )
        rows = (((payload or {}).get("data") or {}).get("unit_status") or [])
        unit = next((row for row in rows if str(row.get("equipment")) == str(selected_equipment)), None)
        if unit is None:
            return html.Div(
                [html.Strong(str(selected_equipment)), html.P(_unavailable_message(), className="small text-muted mb-0 mt-2")],
                className="alert alert-warning h-100 mb-0",
            )
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
                    t(
                        "reliability_report.ranking_item",
                        component=row.get("component_name") or t("reliability_report.unnamed_component"),
                        records=row.get("n_failure_records") or 0,
                        actions=row.get("n_failure_actions") or 0,
                    )
                )
                for row in historical[:5]
            ],
            className="small ps-3 mb-0",
        ) if historical else html.P(_unavailable_message(), className="small text-muted mb-0")
        items = [
            html.H5(str(selected_equipment), className="mb-2"),
            html.P([html.Span(t("reliability_report.label_status"), className="fw-semibold"), str(_localize(unit.get("equipment_status") or "Sin estado"))], className="mb-2"),
            html.P([html.Span(t("reliability_report.label_open_intervention"), className="fw-semibold"), str(_localize(unit.get("has_open_intervention") or "Sin dato"))], className="mb-2"),
            html.P([html.Span(t("reliability_report.label_last_action"), className="fw-semibold"), str(unit.get("last_action_date") or t("reliability_report.no_data"))], className="mb-2"),
            html.P([html.Span(t("reliability_report.label_days_since"), className="fw-semibold"), _format_days(unit.get("days_since_last_maintenance"))], className="mb-2"),
            html.H6(t("reliability_report.ranking_title"), className="mt-3 mb-1"),
            ranking,
        ]
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
            msg = payload.get("meta", {}).get("error", t("mantenciones_general_callbacks.unknown_error"))
            return html.Div(t("mantenciones_general_callbacks.error_al_cargar_evidencia_semanal", msg=msg), className="alert alert-danger"), create_week_summary_table([]), create_week_task_table([])
        if status == "empty":
            return html.Div(t("mantenciones_general_callbacks.no_hay_evidencia_semanal_disponible"), className="alert alert-warning"), create_week_summary_table([]), create_week_task_table([])
        invalid = payload.get("meta", {}).get("invalid_rows", 0)
        alert = html.Div(t("mantenciones_general_callbacks.se_omitieron_filas_con_tareas_no", invalid=invalid), className="alert alert-warning") if invalid else None
        return alert, create_week_summary_table(payload.get("summary", [])), create_week_task_table(payload.get("tasks", []))
