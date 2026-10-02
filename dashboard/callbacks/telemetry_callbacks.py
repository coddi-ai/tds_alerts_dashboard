"""Callbacks for the reportable telemetry fleet and unit views."""

from src.i18n import t
from dashboard.components.labels import status_label
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd
from dash import callback, Input, Output, State, ctx, html, dcc, dash_table
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from src.data.loaders import load_silver_telemetry_week, _data_path
from dashboard.components.telemetry_charts import (
    STATUS_COLORS,
    build_fleet_heatmap,
    build_heatmap_insights,
    build_signal_timeseries_card,
    translate_system,
)
from dashboard.components.telemetry_report import (
    build_fleet_matrix_rows,
    build_fleet_priority_rows,
    build_signal_rows,
    build_system_rows,
    client_facing_manifest,
    client_facing_text,
    filter_fleet_snapshot,
    format_urgency,
    load_telemetry_snapshot,
    _events_for_signal_cached,
)
from dashboard.tabs.tab_telemetry_fleet import create_telemetry_fleet_layout
from dashboard.tabs.tab_telemetry_unit_detail import create_telemetry_unit_detail_layout
from dashboard.components.source_status import render_service_source_status
from src.utils.logger import get_logger

logger = get_logger(__name__)


@callback(Output('telemetry-availability-notice', 'children'), Input('client-selector', 'value'))
def update_telemetry_availability(client):
    if not client:
        return html.Div()
    snapshot = load_telemetry_snapshot(client)
    source_status = render_service_source_status(client, "monitoring-telemetry")
    if snapshot.unit_health.empty and snapshot.system_health.empty:
        return html.Div([
            source_status,
            dbc.Alert([
                html.I(className="fas fa-info-circle me-2"),
                t("telemetry_callbacks.no_hay_datos_de_telemetria_disponibles", str_client_upper=str(client).upper())
            ], color="info"),
        ])
    return source_status


@callback(
    Output('telemetry-reference-date', 'children'),
    [Input('telemetry-health-tabs', 'value'), Input('client-selector', 'value')],
)
def update_reference_date(active_tab, client):
    """Show the materialized evaluation identity and refresh when client changes."""
    if not client:
        raise PreventUpdate
    manifest = client_facing_manifest(load_telemetry_snapshot(client).manifest)
    if not manifest:
        return html.Small(t("telemetry_callbacks.sin_datos_de_referencia"), className="text-muted")
    week = manifest.get('evaluation_week', '?')
    year = manifest.get('evaluation_year', '?')
    timestamp = str(manifest.get('execution_timestamp', ''))
    date_str = timestamp[:10] if timestamp else ''
    return html.Div([
        html.Small([html.I(className="fas fa-calendar-alt me-1"), t("telemetry_callbacks.semana", week=week, year=year)], className="d-block text-muted"),
        html.Small([html.I(className="fas fa-sync-alt me-1"), t("telemetry_callbacks.actualizado", date_str=date_str)], className="d-block text-muted") if date_str else html.Span(),
    ])


@callback(Output('telemetry-health-tab-content', 'children'), Input('telemetry-health-tabs', 'value'))
def render_telemetry_health_tab(active_tab):
    if active_tab == 'fleet-overview':
        return create_telemetry_fleet_layout()
    if active_tab == 'unit-detail':
        return create_telemetry_unit_detail_layout()
    return html.Div(t("telemetry_callbacks.seleccion_invalida"))


@callback(
    [Output('telemetry-fleet-model-filter', 'options'), Output('telemetry-fleet-system-filter', 'options'), Output('telemetry-fleet-system-filter', 'value')],
    [Input('telemetry-health-tabs', 'value'), Input('client-selector', 'value')],
)
def populate_fleet_filters(active_tab, client):
    if active_tab != 'fleet-overview' or not client:
        raise PreventUpdate
    snapshot = load_telemetry_snapshot(client)
    models = sorted(set(snapshot.equipment_models.values()))
    systems = sorted({str(v) for v in snapshot.system_health.get('system', pd.Series(dtype=str)).map(translate_system).dropna()})
    options = [{'label': system, 'value': system} for system in systems]
    return ([{'label': model, 'value': model} for model in models], options, systems)


def _with_status_labels(rows: list[dict], columns) -> list[dict]:
    """Copy of `rows` whose status cells hold the display text. Tables show - and their style
    rules match - the translated label; the raw status stays in the callbacks' own data."""
    return [
        {**row, **{col: status_label(row[col]) for col in columns if isinstance(row.get(col), str)}}
        for row in rows
    ]


def _kpi_card(label: str, value, icon: str, color: str, bg_color: str) -> dbc.Col:
    return dbc.Col([
        dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.I(className=f"{icon} fa-2x text-{color} mb-2"),
                    html.H6(label, className="text-muted text-uppercase mb-2", style={'fontSize': '0.78rem', 'letterSpacing': '0.4px'}),
                    html.H2(str(value), className=f"text-{color} mb-0 fw-bold")
                ], className="text-center")
            ])
        ], className="shadow-sm border-0", style={'backgroundColor': bg_color})
    ], xs=6, md=2, lg=2)


def _priority_table(rows: list[dict]):
    if not rows:
        return dbc.Alert(t("telemetry_callbacks.no_hay_unidades_para_los_filtros"), color="info")
    columns = [
        {'name': t("alerts_general.filter_unit"), 'id': 'unit'},
        {'name': t("health_index_callbacks.modelo"), 'id': 'model'},
        {'name': t("fleet_overview.col_status"), 'id': 'overall_status'},
        {'name': t("telemetry_callbacks.sistemas_afectados"), 'id': 'systems_in_alert', 'type': 'numeric'},
        {'name': t("telemetry_callbacks.sistema_principal"), 'id': 'top_system'},
        {'name': t("tab_telemetry_unit_detail.senal_principal"), 'id': 'top_signal_display'},
        {'name': t("telemetry_callbacks.urgencia"), 'id': 'urgency_display'},
        {'name': t("telemetry_callbacks.accion_recomendada"), 'id': 'recommended_action'},
        {'name': 'top_system_raw', 'id': 'top_system_raw'},
        {'name': 'top_signal', 'id': 'top_signal'},
    ]
    data = []
    for row in rows:
        item = dict(row)
        item['urgency_display'] = format_urgency(item.get('urgency'))
        item['recommended_action'] = item.get('recommended_action') or '-'
        data.append(item)
    return dash_table.DataTable(
        id='telemetry-fleet-priority-table',
        columns=columns,
        data=data,
        row_selectable='single',
        selected_rows=[],
        sort_action='native',
        filter_action='native',
        page_size=12,
        tooltip_data=[
            {'recommended_action': {'value': row.get('recommended_action') or '', 'type': 'markdown'}}
            for row in data
        ],
        tooltip_duration=None,
        style_table={'overflowX': 'auto'},
        style_header={'backgroundColor': '#2c3e50', 'color': 'white', 'fontWeight': 'bold', 'textAlign': 'center'},
        style_cell={'padding': '8px', 'fontSize': '12px', 'whiteSpace': 'normal', 'height': 'auto', 'textAlign': 'center'},
        style_cell_conditional=[
            {'if': {'column_id': 'unit'}, 'textAlign': 'left', 'fontWeight': '600'},
            {'if': {'column_id': 'top_system'}, 'textAlign': 'left'},
            {'if': {'column_id': 'top_signal_display'}, 'textAlign': 'left'},
            {'if': {'column_id': 'recommended_action'}, 'textAlign': 'left', 'minWidth': '260px', 'maxWidth': '420px'},
            {'if': {'column_id': 'top_system_raw'}, 'display': 'none'},
            {'if': {'column_id': 'top_signal'}, 'display': 'none'},
        ],
        style_data_conditional=[
            {'if': {'filter_query': '{overall_status} = "Anormal"'}, 'backgroundColor': 'rgba(231, 76, 60, .12)', 'color': '#b02a37', 'fontWeight': 'bold'},
            {'if': {'filter_query': '{overall_status} = "Alerta"'}, 'backgroundColor': 'rgba(243, 156, 18, .12)', 'color': '#856404', 'fontWeight': 'bold'},
            {'if': {'filter_query': '{overall_status} = "InsufficientData"'}, 'backgroundColor': 'rgba(149, 165, 166, .15)', 'color': '#657174'},
            {'if': {'filter_query': '{overall_status} = "Normal"', 'column_id': 'overall_status'}, 'color': '#198754'},
        ],
    )


# Status color conventions mirrored from the oil fleet heatmap
# (dashboard/callbacks/machines_callbacks.py: _STATUS_BG/_STATUS_FG for
# component-level cells, _MACHINE_STATUS_BG/_MACHINE_STATUS_FG for the
# machine-level summary column) so both general tables read the same way.
_SYSTEM_STATUS_BG = {'Normal': '#d4edda', 'Alerta': '#fff3cd', 'Anormal': '#f8d7da', 'InsufficientData': '#eef0f2'}
_SYSTEM_STATUS_FG = {'Normal': '#155724', 'Alerta': '#856404', 'Anormal': '#721c24', 'InsufficientData': '#657174'}
_OVERALL_STATUS_BG = {'Normal': '#28a745', 'Alerta': '#ffc107', 'Anormal': '#dc3545', 'InsufficientData': '#6c757d'}
_OVERALL_STATUS_FG = {'Normal': '#ffffff', 'Alerta': '#000000', 'Anormal': '#ffffff', 'InsufficientData': '#ffffff'}


def _fleet_status_table(rows: list[dict], systems: list[str]):
    """Render one fleet matrix with a system action tooltip per cell."""
    if not rows:
        return dbc.Alert(t("telemetry_callbacks.no_hay_unidades_para_los_filtros"), color="info")
    rows = _with_status_labels(rows, [*systems, "overall_status"])
    columns = [
        {"name": t("alerts_general.filter_unit"), "id": "unit"},
        {"name": t("health_index_callbacks.modelo"), "id": "model"},
        *[{"name": system, "id": system} for system in systems],
        {"name": t("fleet_overview.col_status"), "id": "overall_status"},
    ]
    tooltip_data = []
    for row in rows:
        tooltip_data.append({
            system: {
                "value": t("telemetry_callbacks.estado_accion", row_get_system_ins=row.get(system) or status_label('InsufficientData'), row_get__system_ac=row.get('_system_actions', {}).get(system, t("telemetry_report.sin_accion_recomendada_registrada"))),
                "type": "markdown",
            }
            for system in systems
        })
    cell_conditional = [
        {"if": {"column_id": "unit"}, "textAlign": "left", "fontWeight": "600", "minWidth": "80px"},
        {"if": {"column_id": "model"}, "textAlign": "left"},
        {"if": {"column_id": "overall_status"}, "minWidth": "110px"},
    ]
    data_conditional = []
    for column_id in systems:
        for state, background in _SYSTEM_STATUS_BG.items():
            data_conditional.append({
                "if": {"filter_query": f'{{{column_id}}} = "{status_label(state)}"', "column_id": column_id},
                "backgroundColor": background,
                "color": _SYSTEM_STATUS_FG[state],
                "fontWeight": "bold",
                "textAlign": "center",
            })
    for state, background in _OVERALL_STATUS_BG.items():
        data_conditional.append({
            "if": {"filter_query": f'{{overall_status}} = "{status_label(state)}"', "column_id": "overall_status"},
            "backgroundColor": background,
            "color": _OVERALL_STATUS_FG[state],
            "fontWeight": "bold",
            "textAlign": "center",
            "fontSize": "13px",
            "borderLeft": f"3px solid {background}",
        })
    return dash_table.DataTable(
        id="telemetry-fleet-status-table",
        columns=columns,
        data=rows,
        active_cell=None,
        cell_selectable=True,
        tooltip_data=tooltip_data,
        tooltip_duration=None,
        css=[{'selector': '.dash-table-tooltip', 'rule': 'max-width: 400px; white-space: normal;'}],
        sort_action="native",
        page_action="native",
        page_size=25,
        style_table={"overflowX": "auto"},
        style_header={'backgroundColor': '#343a40', 'color': 'white', 'fontWeight': 'bold',
                      'textAlign': 'center', 'fontSize': '11px'},
        style_cell={'textAlign': 'center', 'padding': '6px 10px', 'fontSize': '11px',
                    'minWidth': '75px', 'whiteSpace': 'nowrap'},
        style_cell_conditional=cell_conditional,
        style_data_conditional=data_conditional,
    )


@callback(
    Output('telemetry-fleet-table-container', 'children'),
    [
        Input('telemetry-health-tabs', 'value'),
        Input('client-selector', 'value'),
        Input('telemetry-fleet-model-filter', 'value'),
        Input('telemetry-fleet-status-filter', 'value'),
        Input('telemetry-fleet-system-filter', 'value'),
    ],
)
def update_fleet_overview(active_tab, client, model, statuses, systems):
    if active_tab != 'fleet-overview' or not client:
        raise PreventUpdate
    try:
        snapshot = load_telemetry_snapshot(client)
        if model and model not in set(snapshot.equipment_models.values()):
            model = None
        valid_systems = set(snapshot.system_health.get('system', pd.Series(dtype=str)).map(translate_system).dropna())
        systems = [system for system in (systems or []) if system in valid_systems]
        unit_health, _ = filter_fleet_snapshot(snapshot, model, statuses, systems)
        # Keep the complete system snapshot for main-system navigation; the
        # selector controls visible columns only and must not change the case.
        _, all_system_health = filter_fleet_snapshot(snapshot, model, statuses, [])
        system_health = all_system_health
        rows, visible = build_fleet_matrix_rows(snapshot, unit_health, all_system_health, systems)
        return _fleet_status_table(rows, visible)
        if unit_health.empty:
            empty = dbc.Alert(t("telemetry_callbacks.no_hay_unidades_para_los_filtros"), color="info")
            return empty

        counts = unit_health.get('overall_status', pd.Series(dtype=str)).value_counts()
        kpi = dbc.Row([
            _kpi_card(t("telemetry_callbacks.total"), len(unit_health), "fas fa-truck", "info", "#f0f8ff"),
            _kpi_card(t("erp.condition.normal"), int(counts.get('Normal', 0)), "fas fa-check-circle", "success", "#f0fff4"),
            _kpi_card(t("erp.condition.alerta"), int(counts.get('Alerta', 0)), "fas fa-exclamation-circle", "warning", "#fffcf0"),
            _kpi_card(t("erp.condition.anormal"), int(counts.get('Anormal', 0)), "fas fa-times-circle", "danger", "#fff5f5"),
            _kpi_card(t("alerts_report.sin_evidencia"), int(counts.get('InsufficientData', 0)), "fas fa-question-circle", "secondary", "#f3f4f5"),
        ], className="g-3 mb-4 justify-content-center")

        heatmap = build_fleet_heatmap(system_health, unit_health)
        insights = build_heatmap_insights(system_health, unit_health)
        insight_row = dbc.Row([
            dbc.Col([html.Small(t("telemetry_callbacks.unidad_mas_riesgosa"), className="text-muted d-block"), html.Strong(insights['most_risky_unit'])], className="text-center", md=4),
            dbc.Col([html.Small(t("telemetry_callbacks.sistema_con_mayor_riesgo"), className="text-muted d-block"), html.Strong(insights['most_critical_system'])], className="text-center", md=4),
            dbc.Col([html.Small(t("telemetry_callbacks.estado_mas_critico"), className="text-muted d-block"), html.Strong(insights.get('most_critical_status', '-'), className="text-danger")], className="text-center", md=4),
        ], className="g-2 py-2 border rounded bg-light")
        rows = build_fleet_priority_rows(snapshot, unit_health, system_health)
        rows, visible = build_fleet_matrix_rows(snapshot, unit_health, system_health, systems)
        return _fleet_status_table(rows, visible)
    except Exception as exc:
        logger.exception("Error en Vista de Flota: %s", exc)
        error = dbc.Alert(t("telemetry_callbacks.error_cargando_datos_de_telemetria", exc=exc), color="danger")
        return error


# Legacy selected-unit summary retained as a helper for backwards compatibility;
# the fleet matrix no longer renders a separate summary card.
def _legacy_selected_fleet_unit(selected_rows, client, model, statuses, systems, table_data, visible_data):
    [
        Input('telemetry-fleet-priority-table', 'selected_rows'),
        Input('client-selector', 'value'),
        Input('telemetry-fleet-model-filter', 'value'),
        Input('telemetry-fleet-status-filter', 'value'),
        Input('telemetry-fleet-system-filter', 'value'),
    ],
    [State('telemetry-fleet-priority-table', 'data'), State('telemetry-fleet-priority-table', 'derived_viewport_data')],
    prevent_initial_call=True,
def update_selected_fleet_unit(selected_rows, client, model, statuses, systems, table_data, visible_data):
    table_data = visible_data or table_data
    if not selected_rows or not table_data or not client:
        return html.Div()
    row = table_data[selected_rows[0]]
    return dbc.Card([
        dbc.CardHeader([html.I(className="fas fa-robot me-2"), t("telemetry_callbacks.resumen_de", row_get_unit=row.get('unit', '-'))]),
        dbc.CardBody([
            html.P(row.get('description') or t("telemetry_callbacks.sin_descripcion_ia_disponible"), className="mb-1"),
            html.P(row.get('explaining') or "", className="text-muted mb-1", style={'whiteSpace': 'pre-wrap'}),
            html.Div([
                html.I(className="fas fa-wrench me-1"),
                html.Strong(t("telemetry_callbacks.accion")), row.get('recommended_action') or t("telemetry_callbacks.sin_accion_recomendada_disponible")
            ], className="text-primary")
        ])
    ], className="shadow-sm mb-4", style={'borderLeft': '4px solid #3498db'})


@callback(
    [
        Output('telemetry-health-tabs', 'value', allow_duplicate=True),
        Output('telemetry-navigation-state', 'data', allow_duplicate=True),
    ],
    [Input('telemetry-fleet-status-table', 'active_cell')],
    [State('telemetry-fleet-status-table', 'data'), State('telemetry-fleet-status-table', 'derived_viewport_data')],
    prevent_initial_call=True,
)
def navigate_from_fleet(active_cell, table_data, visible_data):
    table_data = visible_data or table_data
    unit = system = signal = None
    source = None
    if active_cell and table_data:
        row = table_data[active_cell.get('row', 0)]
        column_id = active_cell.get('column_id')
        unit = row.get('unit')
        system = row.get('_system_map', {}).get(column_id) if column_id else None
        if not system:
            system = row.get('_top_system_raw') or None
        source = 'fleet_matrix'
    if not unit:
        raise PreventUpdate
    return 'unit-detail', {'unit': unit, 'system': system, 'signal': signal, 'source': source}


@callback(
    [Output('telemetry-detail-unit-selector', 'options'), Output('telemetry-detail-unit-selector', 'value')],
    [Input('telemetry-health-tabs', 'value'), Input('client-selector', 'value'), Input('telemetry-navigation-state', 'data')],
    State('telemetry-detail-unit-selector', 'value'),
)
def populate_unit_selector(active_tab, client, navigation_state, current_value):
    if active_tab != 'unit-detail' or not client:
        raise PreventUpdate
    snapshot = load_telemetry_snapshot(client)
    unit_health = snapshot.unit_health
    if unit_health.empty or 'unit' not in unit_health.columns:
        return [], None
    ordered = unit_health.sort_values('priority_score', ascending=False, na_position='last')
    options = [{'label': row['unit'], 'value': row['unit']} for _, row in ordered.iterrows()]
    requested = (navigation_state or {}).get('unit')
    if requested in [item['value'] for item in options]:
        return options, requested
    if current_value in [item['value'] for item in options]:
        return options, current_value
    return options, options[0]['value']


def _identity_display(snapshot, unit: str) -> html.Div:
    manifest = client_facing_manifest(snapshot.manifest)
    if not unit:
        return html.Div()
    return html.Div([
        html.Span(t("telemetry_callbacks.unidad", unit=unit), className="me-3"),
        html.Span(t("telemetry_callbacks.modelo", snapshot_equipment=snapshot.equipment_models.get(unit, 'N/D')), className="me-3"),
        html.Span(t("telemetry_callbacks.evaluacion_semana", manifest_get_evalu=manifest.get('evaluation_week', '?'), manifest_get_evalu2=manifest.get('evaluation_year', '?')), className="me-3"),
        html.Span(t("telemetry_callbacks.ejecucion", str_manifest_get_e=str(manifest.get('execution_timestamp', ''))[:10]))
    ])


def _decision_summary(snapshot, unit: str, system_rows: list[dict]) -> html.Div:
    unit_row = snapshot.unit_health[snapshot.unit_health.get('unit', pd.Series(dtype=str)) == unit]
    if unit_row.empty:
        return dbc.Alert(t("telemetry_callbacks.no_hay_datos_para_la_unidad"), color="info")
    row = unit_row.iloc[0]
    top = system_rows[0] if system_rows else {}
    unit_comment = snapshot.unit_comments[snapshot.unit_comments.get('unit', pd.Series(dtype=str)) == unit] if not snapshot.unit_comments.empty else pd.DataFrame()
    comment = unit_comment.iloc[0] if not unit_comment.empty else None
    description = client_facing_text(_text_value(comment, 'description', 'comment') or _text_value(row, 'executive_summary'), snapshot.signal_registry) or t("telemetry_callbacks.operando_dentro_de_parametros_normales")
    explaining = client_facing_text(_text_value(comment, 'explaining'), snapshot.signal_registry)
    action = client_facing_text(_text_value(comment, 'recommended_action'), snapshot.signal_registry)
    urgency = format_urgency(_text_value(comment, 'urgency'))
    status = row.get('overall_status', 'InsufficientData')
    # A missing current-period IA comment must remain explicit.  Do not let
    # the generic normal fallback misrepresent an alerting/anormal unit.
    if status in {'Alerta', 'Anormal'} and not (
        _text_value(comment, 'description', 'comment')
        or _text_value(row, 'executive_summary')
    ):
        description = t("telemetry_callbacks.analisis_ia_no_disponible_para_esta")
    color = {'Normal': 'success', 'Alerta': 'warning', 'Anormal': 'danger', 'InsufficientData': 'secondary'}.get(status, 'secondary')
    title = t("telemetry_callbacks.por_que_esta_en_alerta") if status in {'Alerta', 'Anormal'} else t("tab_telemetry_unit_detail.resumen_de_la_unidad")
    return dbc.Card([
        dbc.CardHeader([html.I(className="fas fa-bullseye me-2"), title]),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([html.Small(t("fleet_overview.col_status"), className="text-muted d-block"), dbc.Badge(status_label(status), color=color, pill=True)], md=2),
                dbc.Col([html.Small(t("telemetry_callbacks.sistemas_afectados"), className="text-muted d-block"), html.Strong(str(int(row.get('n_anormal_systems', 0) or 0) + int(row.get('n_alerta_systems', 0) or 0)))], md=2),
                dbc.Col([html.Small(t("telemetry_callbacks.sistema_principal"), className="text-muted d-block"), html.Strong(top.get('system', '-'))], md=3),
                dbc.Col([html.Small(t("tab_telemetry_unit_detail.senal_principal"), className="text-muted d-block"), html.Strong(top.get('top_signal_display', '-'))], md=3),
                dbc.Col([html.Small(t("telemetry_callbacks.urgencia"), className="text-muted d-block"), html.Strong(urgency)], md=2),
            ], className="mb-3"),
            html.Strong(description, className="d-block"),
            html.P(explaining or top.get('explaining') or top.get('description') or "", className="text-muted mb-1", style={'whiteSpace': 'pre-wrap'}),
            html.Div([html.I(className="fas fa-wrench me-1"), html.Strong(t("telemetry_callbacks.accion")), action or top.get('recommended_action') or t("telemetry_callbacks.sin_accion_recomendada_disponible")], className="text-primary")
        ])
    ], className="shadow-sm mb-4", style={'borderLeft': f"4px solid {STATUS_COLORS.get(status, '#95a5a6')}"})


def _system_analysis_card(system_row: dict | None) -> html.Div:
    """Render the materialized system-level IA explanation before signals."""
    if not system_row:
        return dbc.Alert(t("telemetry_callbacks.no_hay_un_sistema_seleccionado_para"), color="info")
    status = system_row.get('system_status', 'InsufficientData')
    color = {'Normal': 'success', 'Alerta': 'warning', 'Anormal': 'danger', 'InsufficientData': 'secondary'}.get(status, 'secondary')
    description = system_row.get('description') or t("telemetry_callbacks.sin_evaluacion_ia_disponible_para_este")
    explaining = system_row.get('explaining') or ""
    action = system_row.get('recommended_action') or t("telemetry_callbacks.sin_accion_recomendada_disponible")
    return dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([html.Small(t("alerts_general.filter_system"), className="text-muted d-block"), html.Strong(system_row.get('system', '-'))], md=3),
                dbc.Col([html.Small(t("fleet_overview.col_status"), className="text-muted d-block"), dbc.Badge(status_label(status), color=color, pill=True)], md=2),
                dbc.Col([html.Small(t("telemetry_callbacks.senales_con_hallazgo"), className="text-muted d-block"), html.Strong(str(system_row.get('signals_in_alert', 0)))], md=2),
                dbc.Col([html.Small(t("tab_telemetry_unit_detail.senal_principal"), className="text-muted d-block"), html.Strong(system_row.get('top_signal_display', '-'))], md=5),
            ], className="mb-3"),
            html.Strong(description, className="d-block"),
            html.P(explaining, className="text-muted mb-2", style={'whiteSpace': 'pre-wrap'}) if explaining else html.Span(),
            html.Div([html.I(className="fas fa-wrench me-1"), html.Strong(t("telemetry_callbacks.accion")), action], className="text-primary"),
        ])
    ], className="shadow-sm mb-4", style={'borderLeft': f"4px solid {STATUS_COLORS.get(status, '#95a5a6')}"})


def _text_value(row, *fields):
    if row is None:
        return None
    for field in fields:
        try:
            value = row.get(field, '')
        except AttributeError:
            value = ''
        if value is not None and not pd.isna(value) and str(value).strip():
            return str(value)
    return None


@callback(
    [
        Output('telemetry-detail-ai-comment', 'children'),
        Output('telemetry-detail-system-table', 'data'),
        Output('telemetry-detail-system-table', 'selected_rows'),
        Output('telemetry-detail-system-selector', 'options'),
        Output('telemetry-detail-system-selector', 'value'),
    ],
    [Input('telemetry-detail-unit-selector', 'value'), Input('client-selector', 'value')],
    State('telemetry-navigation-state', 'data'),
)
def update_unit_detail_header(unit, client, navigation_state):
    if not unit or not client:
        raise PreventUpdate
    try:
        snapshot = load_telemetry_snapshot(client, include_detail=True)
        system_rows = build_system_rows(snapshot, unit)
        options = [{'label': row['system'], 'value': row['system']} for row in system_rows]
        requested_system = (navigation_state or {}).get('system') if (navigation_state or {}).get('unit') == unit else None
        selected_system = requested_system if requested_system in [item['value'] for item in options] else (options[0]['value'] if options else None)
        selected_index = [next((idx for idx, row in enumerate(system_rows) if row.get('system') == selected_system), 0)] if system_rows else []
        return _decision_summary(snapshot, unit, system_rows), _with_status_labels(system_rows, ('system_status',)), selected_index, options, selected_system
    except Exception as exc:
        logger.exception("Error actualizando detalle de unidad: %s", exc)
        return dbc.Alert(t("telemetry_callbacks.error_cargando_la_unidad", exc=exc), color="danger"), [], [], [], None


@callback(
    Output('telemetry-detail-system-analysis', 'children'),
    [Input('telemetry-detail-system-selector', 'value'), Input('telemetry-detail-unit-selector', 'value'), Input('client-selector', 'value')],
    prevent_initial_call=True,
)
def update_selected_system_summary(system, unit, client):
    """Refresh the decision block when the user changes the selected system."""
    if not unit or not system or not client:
        raise PreventUpdate
    snapshot = load_telemetry_snapshot(client, include_detail=True)
    rows = build_system_rows(snapshot, unit)
    selected = [row for row in rows if row.get('system') == system]
    selected_row = selected[0] if selected else None
    return _system_analysis_card(selected_row)


@callback(
    Output('telemetry-detail-system-selector', 'value', allow_duplicate=True),
    Input('telemetry-detail-system-table', 'selected_rows'),
    State('telemetry-detail-system-table', 'data'),
    prevent_initial_call=True,
)
def sync_system_table_selection(selected_rows, table_data):
    if not selected_rows or not table_data:
        raise PreventUpdate
    return table_data[selected_rows[0]].get('system')


@callback(
    [
        Output('telemetry-detail-signal-table', 'data'),
        Output('telemetry-detail-signal-table', 'selected_rows'),
        Output('telemetry-detail-signal-selector', 'options'),
    ],
    [Input('telemetry-detail-system-selector', 'value'), Input('telemetry-detail-unit-selector', 'value'), Input('client-selector', 'value')],
    State('telemetry-navigation-state', 'data'),
)
def update_signal_section(system, unit, client, navigation_state):
    if not unit or not system or not client:
        raise PreventUpdate
    try:
        snapshot = load_telemetry_snapshot(client, include_detail=True)
        rows = build_signal_rows(snapshot, unit, system)
        options = [{'label': f"{row['signal']} ({status_label(row['status'])})", 'value': row['signal_raw']} for row in rows]
        requested = (navigation_state or {}).get('signal') if (navigation_state or {}).get('unit') == unit else None
        selected = requested if requested in [item['value'] for item in options] else (options[0]['value'] if options else None)
        selected_rows = [next((idx for idx, row in enumerate(rows) if row['signal_raw'] == selected), 0)] if rows else []
        return _with_status_labels(rows, ('status',)), selected_rows, options
    except Exception as exc:
        logger.exception("Error actualizando señales: %s", exc)
        return [], [], []


@callback(
    Output('telemetry-detail-signal-selector', 'value'),
    Input('telemetry-detail-signal-table', 'selected_rows'),
    Input('telemetry-detail-signal-table', 'data'),
    prevent_initial_call=True,
)
def sync_signal_table_selection(selected_rows, table_data):
    if not selected_rows or not table_data:
        raise PreventUpdate
    return table_data[selected_rows[0]].get('signal_raw')


@callback(
    Output('telemetry-detail-signal-table', 'selected_rows', allow_duplicate=True),
    Input('telemetry-detail-signal-selector', 'value'),
    State('telemetry-detail-signal-table', 'data'),
    prevent_initial_call=True,
)
def sync_signal_selector_selection(signal, table_data):
    """Keep the radio selection aligned when the signal dropdown changes."""
    if not signal or not table_data:
        raise PreventUpdate
    selected_index = next(
        (idx for idx, row in enumerate(table_data) if row.get('signal_raw') == signal),
        None,
    )
    if selected_index is None:
        raise PreventUpdate
    return [selected_index]


@lru_cache(maxsize=256)
def _load_recent_telemetry_signal_cached(
    client: str,
    unit: str,
    signal: str,
    cache_key: str,
    weeks: int = 5,
) -> pd.DataFrame:
    """Load only the selected signal from the latest weeks needed by the UI.

    Five ISO weeks cover the "last month" range selector plus its boundary
    week; loading eight weeks added I/O without expanding any client-facing
    range.
    """
    snapshot = load_telemetry_snapshot(client)
    manifest = snapshot.manifest
    anchor_year = int(manifest.get('evaluation_year', datetime.now().isocalendar()[0]))
    anchor_week = int(manifest.get('evaluation_week', datetime.now().isocalendar()[1]))
    available_weeks = manifest.get('silver_weeks_available', [])
    frames = []
    if available_weeks:
        candidates = [(anchor_year, int(w)) for w in sorted({int(w) for w in available_weeks}, reverse=True)[:weeks]]
    else:
        silver_dir = _data_path("telemetry", "silver", client.lower(), "Telemetry_Wide_With_States")
        existing = [
            week for week in range(1, 54)
            if (silver_dir / f"Week{week:02d}Year{anchor_year}.parquet").exists()
        ]
        if existing:
            candidates = [(anchor_year, week) for week in sorted(existing, reverse=True)[:weeks]]
        else:
            anchor_date = date.fromisocalendar(anchor_year, anchor_week, 1)
            candidates = [
                ((anchor_date - timedelta(weeks=i)).isocalendar().year,
                 (anchor_date - timedelta(weeks=i)).isocalendar().week)
                for i in range(weeks)
            ]
    for year, week in candidates:
        frame = load_silver_telemetry_week(client, int(week), int(year), columns=['Unit', 'Fecha', signal])
        if not frame.empty and 'Unit' in frame.columns and signal in frame.columns:
            frame = frame[frame['Unit'] == unit]
            if not frame.empty:
                frames.append(frame)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values('Fecha') if 'Fecha' in combined.columns else combined


def _signal_kpi_table(row: dict) -> html.Table:
    values = [
        (t("telemetry_callbacks.total_eventos"), row.get('total_events', 0)),
        (t("telemetry_callbacks.warnings"), row.get('warnings', 0)),
        (t("telemetry_callbacks.episodio_maximo"), f"{row.get('longest_episode', 0)} min"),
        (t("tab_telemetry_unit_detail.tendencia"), row.get('trend_detected', 'No')),
        (t("telemetry_callbacks.direccion_de_tendencia"), row.get('trend_direction', '-')),
        (t("telemetry_callbacks.formula"), row.get('trend_formula', '-')),
        (t("tab_telemetry_unit_detail.fuera_de_rango"), f"{row.get('abnormal_pct', 0):.2f}%"),
    ]
    return html.Table([
        html.Tbody([html.Tr([html.Td(label, className="fw-bold"), html.Td(str(value), className="text-end")]) for label, value in values])
    ], className="table table-sm table-borderless")


@callback(
    Output('telemetry-detail-signal-cards', 'children'),
    [
        Input('telemetry-detail-signal-selector', 'value'),
        Input('telemetry-detail-system-selector', 'value'),
        Input('telemetry-detail-unit-selector', 'value'),
        Input('client-selector', 'value'),
        # W34-09: the 1/7/30-day buttons only change the plotted window —
        # unit/sistema/señal are separate Inputs above and are untouched by
        # this one changing.
        Input('telemetry-detail-window-days', 'value'),
    ],
)
def update_signal_cards(signal, system, unit, client, window_days):
    if not signal or not system or not unit or not client:
        return dbc.Alert(t("telemetry_callbacks.seleccione_una_unidad_sistema_y_senal"), color="info")
    try:
        snapshot = load_telemetry_snapshot(client, include_detail=True)
        rows = build_signal_rows(snapshot, unit, system)
        row = next((item for item in rows if item['signal_raw'] == signal), None)
        if row is None:
            return dbc.Alert(t("telemetry_callbacks.no_hay_evidencia_para_la_senal"), color="info")
        raw = _load_recent_telemetry_signal_cached(client.lower(), unit, signal, snapshot.cache_key)
        numeric_values = (
            pd.to_numeric(raw[signal], errors='coerce').dropna()
            if not raw.empty and signal in raw.columns
            else pd.Series(dtype=float)
        )
        has_valid_series = not numeric_values.empty
        trend_df = snapshot.trends[(snapshot.trends.get('unit', pd.Series(dtype=str)) == unit) & (snapshot.trends.get('signal', pd.Series(dtype=str)) == signal)] if not snapshot.trends.empty else pd.DataFrame()
        event_df = _events_for_signal_cached(
            client.lower(), snapshot.cache_key, unit, signal
        )
        # W34-09: simplified view — window_days from the button group,
        # show_events left at its default (False): no event/anomaly
        # overlays. event_df is still loaded above because the KPI table
        # below (_signal_kpi_table) shows total_events/warnings independent
        # of whether the chart draws overlays for them.
        figure = build_signal_timeseries_card(
            signal, raw, snapshot.limits, trend_df, unit, event_df,
            window_days=window_days or 1,
        )
        metadata = snapshot.signal_metadata.get(signal, {})
        coverage_notice = None
        if not has_valid_series:
            coverage_notice = dbc.Alert([
                html.Strong(t("telemetry_callbacks.sin_datos_validos_para_esta_senal")),
                t("telemetry_callbacks.la_columna_tecnica_no_contiene_observacion", signal=signal, unit=unit),
                t("telemetry_callbacks.no_se_sustituye_por_otra_senal"),
                t("telemetry_callbacks.el_estado_materializado_y_los_eventos", row_get_status_ins=row.get('status', 'InsufficientData')),
            ], color="secondary", className="small mb-3")
        if has_valid_series and not event_df.empty and 'end_time' in event_df.columns and 'Fecha' in raw.columns:
            classified_until = pd.to_datetime(event_df['end_time'], errors='coerce').max()
            observed_until = pd.to_datetime(raw['Fecha'], errors='coerce').max()
            if pd.notna(classified_until) and pd.notna(observed_until) and classified_until < observed_until:
                coverage_notice = dbc.Alert(
                    t("telemetry_callbacks.eventos_clasificados_hasta_los_datos_poste", classified_until_s=classified_until.strftime('%d/%m/%Y')),
                    color="light", className="small mb-3",
                )
        status_color = {'Normal': 'success', 'Alerta': 'warning', 'Anormal': 'danger', 'InsufficientData': 'secondary'}.get(row['status'], 'secondary')
        badge_label = status_label(row['status']) if has_valid_series else t("oil_machine_detail.sin_datos")
        card_border_color = STATUS_COLORS.get(row['status'], '#95a5a6') if has_valid_series else STATUS_COLORS.get('InsufficientData', '#95a5a6')
        card = dbc.Card([
            dbc.CardHeader([
                    html.Strong(row['signal']),
                    dbc.Badge(badge_label, color=status_color if has_valid_series else 'secondary', pill=True, className="ms-2"),
                    html.Small(t("telemetry_callbacks.estado_materializado", row_status=status_label(row['status'])), className="text-muted ms-2") if not has_valid_series else html.Span()
                ], className="bg-light"),
                dbc.CardBody([
                    coverage_notice or html.Span(),
                    dbc.Row([
                        dbc.Col([
                        html.Div([html.Small(t("telemetry_callbacks.nombre_tecnico"), className="text-muted d-block"), html.Strong(row.get('signal_raw', '-') or '-')], className="mb-2"),
                        html.Div([html.Small(t("telemetry_callbacks.unidad_de_medida"), className="text-muted d-block"), html.Strong(metadata.get('unit', '-') or '-')], className="mb-2"),
                        html.Div([html.Small(t("telemetry_callbacks.diagnostico_ia"), className="text-muted d-block"), html.Strong(row.get('description', ''))], className="mb-1"),
                        html.P(row.get('explaining') or "", className="text-muted", style={'whiteSpace': 'pre-wrap'}),
                        _signal_kpi_table(row),
                    ], lg=4),
                    dbc.Col([
                        dcc.Graph(
                            figure=figure,
                            config={'displayModeBar': False},
                            style={'height': '620px'},
                        )
                    ], lg=8)
                ])
            ])
        ], className="shadow-sm mb-3", style={'borderLeft': f"4px solid {card_border_color}"})
        return card
    except Exception as exc:
        logger.exception("Error construyendo evidencia de señal: %s", exc)
        return dbc.Alert(t("telemetry_callbacks.error_cargando_evidencia", exc=exc), color="danger")
