"""
Callbacks for Alerts Dashboard.

Handles all interactivity for the unified alerts view with internal tabs,
interactive filtering, and cross-navigation.
"""

from src.i18n import t
from src.i18n.data_text import localized_value
import pandas as pd
from dash import callback, callback_context, clientside_callback, ALL, Input, Output, State, html, dcc, no_update, dash_table
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from datetime import date, datetime, timedelta
import numpy as np
import plotly.graph_objects as go
from src.data.emin_alert_evidence import (
    alert_reference,
    evidence_flag,
    oil_report_reference,
)

from src.data.loaders import (
    load_alerts_data,
    load_telemetry_values,
    load_telemetry_states,
    load_telemetry_limits,
    load_telemetry_alerts_metadata,
    load_component_mapping,
    load_feature_names,
    load_telemetry_alert_detail_for_alert,
    load_oil_classified,
    load_maintenance_week,
    load_emin_maintenance_evidence,
    load_essays_mapping,
    _data_path,
)
from dashboard.components.alerts_charts import (
    create_alerts_per_unit_chart,
    create_alerts_per_month_chart,
    create_alerts_per_week_chart,
    create_system_signal_treemap,
    create_oil_radar_chart,
    create_gps_route_map_golden,
    create_context_kpis_cards_golden
)
from dashboard.components.oil_charts import (
    build_oil_time_series_grid,
    build_oil_radar_view,
)
from dashboard.components.alerts_tables import (
    # W34-03: create_alerts_datatable is a legacy, unused variant of the
    # alerts table (different columns/page size, exposes ID/Fuente as
    # visible columns) — deliberately not imported here. The live table is
    # create_alerts_report_table below. See test_w34_alerts_table.py for the
    # regression guard.
    alerts_report_table_styles,
    create_alerts_report_table,
    create_maintenance_display,
    parse_ia_message_sections,
)
from dashboard.components.alerts_report import (
    alert_summary,
    filter_alert_rows,
    prepare_alert_rows,
    translate_alert_component,
    translate_alert_system,
)
from dashboard.components.alert_signal_grid import (
    SIGNALS_COLLAPSE_ID,
    SIGNALS_LABELS_ID,
    SIGNALS_TOGGLE_ID,
    create_signal_evidence,
    prepare_signal_panels,
)
from dashboard.components.alert_case_header import (
    analysis_block,
    evidence_source_chips,
    trigger_signal_callout,
)
from dashboard.tabs.tab_alerts_general import (
    create_summary_stats_display,
    create_active_filters_bar,
    default_alert_dates,
    create_layout as create_general_layout,
)
from dashboard.tabs.tab_alerts_detail import (
    SOURCE_FILTER_DEFAULT,
    SOURCE_FILTER_NO,
    SOURCE_FILTER_YES,
    create_alert_detail_content,
    create_oil_status_display,
    create_layout as create_detail_layout
)
from dashboard.components.source_status import render_service_source_chips
from src.utils.logger import get_logger
from src.utils.date_utils import format_local, to_utc_naive
from config.settings import Settings

logger = get_logger(__name__)
settings = Settings()

# Configuration
M1 = 60  # Minutes before alert
M2 = 10  # Minutes after alert
MAPBOX_TOKEN = settings.mapbox_token


def _normalise_alert_identifier(value) -> str:
    """Return an alert identifier in the same text form used by CSV data."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _select_telemetry_alert_data(
    telemetry_golden: pd.DataFrame,
    alert_row: pd.Series,
) -> tuple[pd.DataFrame, list[str], str]:
    """Select detail rows using Capstone's textual telemetry identifiers.

    Detail artifacts may key ``AlertID`` with either the consolidated
    ``TelemetryID`` or ``FusionID``. Both are strings, often with a ``CAP-``
    prefix, so matching must remain textual and must not coerce IDs to ints.
    """
    identifiers = []
    for field in ("TelemetryID", "FusionID"):
        identifier = _normalise_alert_identifier(alert_row.get(field))
        if identifier and identifier not in identifiers:
            identifiers.append(identifier)

    unit_id = _normalise_alert_identifier(alert_row.get("UnitId"))
    if not identifiers or not unit_id:
        return telemetry_golden.iloc[0:0].copy(), identifiers, unit_id

    alert_keys = telemetry_golden["AlertID"].map(_normalise_alert_identifier)
    unit_keys = telemetry_golden["Unit"].map(_normalise_alert_identifier)
    mask = alert_keys.isin(identifiers) & unit_keys.eq(unit_id)
    return telemetry_golden.loc[mask].copy(), identifiers, unit_id


# ========================================
# TAB SWITCHING CALLBACK
# ========================================

@callback(
    Output('alerts-tab-content', 'children'),
    [Input('alerts-internal-tabs', 'value')]
)
def render_tab_content(active_tab):
    """
    Render content for selected internal tab.
    
    Args:
        active_tab: 'general' or 'detail'
    
    Returns:
        Tab content layout
    """
    if active_tab == 'general':
        return create_general_layout()
    elif active_tab == 'detail':
        return create_detail_layout()
    else:
        return html.Div(t("alerts_callbacks.tab_no_encontrado"))


# ========================================
# GENERAL TAB CALLBACKS
# ========================================

@callback(
    Output('alerts-source-status', 'children'),
    Input('client-selector', 'value'),
)
def update_alerts_source_status(client):
    if not client:
        return html.Div()
    return render_service_source_chips(client, "monitoring-alerts")

@callback(
    [
        Output('alerts-unit-distribution-chart', 'figure'),
        Output('alerts-month-distribution-chart', 'figure'),
        Output('alerts-system-distribution-chart', 'figure'),
        Output('alerts-summary-stats', 'children'),
        Output('alerts-table-container', 'children'),
        Output('alerts-general-filter-summary', 'children'),
    ],
    [
        Input('client-selector', 'value'),
        Input('alerts-date-start', 'date'),
        Input('alerts-date-end', 'date'),
        Input('alerts-general-active-filters', 'data'),
    ]
)
def update_general_tab(client: str, start_date: str, end_date: str, active_filters: dict):
    """
    Update all components in the General Tab when client changes or filters are applied.

    Args:
        client: Selected client identifier
        start_date, end_date: Desde / Hasta date inputs (None leaves that side open)
        active_filters: Cross-filter selections from clicking the charts
            (keys: 'unit', 'week', 'system', 'trigger'), combined with AND.

    Returns:
        Tuple of (unit_chart, month_chart, system_chart, stats, table, filter_summary).
        The summary describes the same rows as the charts and table: date range and
        chart filters together.
    """
    if not client:
        raise PreventUpdate

    logger.info(f"Loading alerts general view for client: {client}")
    # Load alerts data
    alerts_df = load_alerts_data(client)

    if alerts_df.empty:
        logger.warning(f"No alerts data available for client: {client}")
        empty_fig = {'data': [], 'layout': {'title': t("alerts_callbacks.no_data_available")}}
        empty_alert = dbc.Alert(t("menace_control_callbacks.no_hay_datos_de_alertas_disponibles"), color="warning")
        return empty_fig, empty_fig, empty_fig, empty_alert, empty_alert, ""

    active_filters = active_filters or {}

    try:
        # Apply the same presentation filter set to KPIs, charts and table,
        # combining the date range with any active chart cross-filters (AND).
        unit_filter = [active_filters['unit']] if active_filters.get('unit') else None
        system_filter = [active_filters['system']] if active_filters.get('system') else None
        trigger_filter = [active_filters['trigger']] if active_filters.get('trigger') else None
        filtered_df = filter_alert_rows(
            alerts_df, unit=unit_filter, system=system_filter, trigger=trigger_filter,
            start_date=start_date, end_date=end_date,
        )

        week_value = active_filters.get('week')
        if week_value and not filtered_df.empty:
            week_start = pd.to_datetime(week_value)
            week_end = week_start + pd.Timedelta(days=7)
            filtered_df = filtered_df[(filtered_df['Timestamp'] >= week_start) & (filtered_df['Timestamp'] < week_end)]

        if filtered_df.empty:
            logger.warning("No data after applying filters")
            empty_fig = {'data': [], 'layout': {'title': t("alerts_callbacks.no_hay_datos_con_los_filtros")}}
            empty_alert = dbc.Alert(t("alerts_callbacks.no_hay_datos_con_los_filtros"), color="info")
            return empty_fig, empty_fig, empty_fig, empty_alert, empty_alert, t("alerts_callbacks.no_hay_alertas_para_los_filtros")

        # Create charts (using filtered data for visualization) - removed trigger_chart
        unit_chart = create_alerts_per_unit_chart(filtered_df, top_n=settings.alert_unit_chart_top_n)
        month_chart = create_alerts_per_week_chart(filtered_df)
        system_chart = create_system_signal_treemap(filtered_df)

        # Calculate summary statistics
        summary = alert_summary(filtered_df)
        stats = create_summary_stats_display(summary['total'], summary['units'], mixed_count=summary['mixed'])

        # Create table
        table = create_alerts_report_table(filtered_df)

        latest = format_local(summary['latest'])  # W34-06: local wall-clock time
        filter_summary = t("alerts_callbacks.mostrando_alertas_de_unidades_ultima_alert", summary_total=summary['total'], summary_units=summary['units'], latest=latest)
        logger.info(f"General tab updated successfully with {summary['total']} alerts")
        return unit_chart, month_chart, system_chart, stats, table, filter_summary

    except Exception as e:
        logger.error(f"Error updating general tab: {e}")
        error_fig = {'data': [], 'layout': {'title': t("component_hours_callbacks.error", str_e=str(e))}}
        error_alert = dbc.Alert(t("alerts_callbacks.error_al_cargar_datos", str_e=str(e)), color="danger")
        return error_fig, error_fig, error_fig, error_alert, error_alert, t("component_hours_callbacks.error", str_e=str(e))


@callback(
    Output('alerts-general-active-filters-bar', 'children'),
    Input('alerts-general-active-filters', 'data'),
)
def render_active_filters_bar(active_filters):
    """The one "Filtros activos" bar shared by every chart; None (nothing rendered)
    while no filter is active."""
    return create_active_filters_bar(active_filters)


def _chart_click_filter(chart_id: str, click_data) -> tuple[str, str] | None:
    """``(filter key, value)`` selected by a click on one of the General tab's charts.

    Every chart is read here and the pair goes through the one toggle in
    `update_active_filters`, so a unit, a week, a system and a trigger all behave the
    same way. ``None`` when the click selects nothing: no point, the aggregated "Otras"
    bar, or a treemap cell that is only a grouping (the subsystems).
    """
    points = (click_data or {}).get('points') or []
    customdata = points[0].get('customdata') if points else None
    if not isinstance(customdata, list) or not customdata:
        return None
    if chart_id == 'alerts-unit-distribution-chart':
        key, value = 'unit', customdata[0]
    elif chart_id == 'alerts-month-distribution-chart':
        key, value = 'week', customdata[0]
    elif chart_id == 'alerts-system-distribution-chart':
        # Each treemap node names its own filter: [key, value] - system cells carry the
        # system, trigger cells the signal, subsystem cells nothing.
        key, value = (customdata + [None])[:2]
    else:
        return None
    return (key, value) if key and value else None


@callback(
    Output('alerts-general-active-filters', 'data', allow_duplicate=True),
    [
        Input('alerts-unit-distribution-chart', 'clickData'),
        Input('alerts-month-distribution-chart', 'clickData'),
        Input('alerts-system-distribution-chart', 'clickData'),
        Input({'type': 'alerts-general-filter-chip', 'key': ALL}, 'n_clicks'),
        Input({'type': 'alerts-general-filter-clear-all', 'index': ALL}, 'n_clicks'),
    ],
    State('alerts-general-active-filters', 'data'),
    prevent_initial_call=True,
)
def update_active_filters(_unit_click, _week_click, _system_click, _chip_clicks, _clear_clicks, current):
    """
    Maintain the shared cross-filter state for the General tab's charts.

    Clicking a bar/point/cell sets (or, if already active, clears) that dimension's
    filter; dimensions combine with AND. A chip's own × removes just that dimension;
    "Limpiar todo" clears all.
    """
    triggered = callback_context.triggered[0] if callback_context.triggered else None
    trigger = callback_context.triggered_id
    # A chip or button that was just mounted reports n_clicks 0/None, and an untouched
    # chart reports no click: neither is a user action.
    if not triggered or not triggered.get('value'):
        raise PreventUpdate

    current = dict(current or {})

    if isinstance(trigger, dict) and trigger.get('type') == 'alerts-general-filter-clear-all':
        return {}

    if isinstance(trigger, dict) and trigger.get('type') == 'alerts-general-filter-chip':
        current.pop(trigger.get('key'), None)
        return current

    target = _chart_click_filter(trigger, triggered['value'])
    if target is None:
        raise PreventUpdate

    key, value = target
    if current.get(key) == value:
        current.pop(key, None)
    else:
        current[key] = value
    return current


@callback(
    Output('alerts-general-active-filters', 'data', allow_duplicate=True),
    Input('client-selector', 'value'),
    prevent_initial_call=True,
)
def reset_active_filters_on_client_change(_client):
    """Drop any chart cross-filter when the client changes, since selections
    (unit/week/system) don't necessarily carry over to a different client."""
    return {}


def _active_alert_row(active_cell, table_data):
    """The table row behind the clicked cell, or None.

    Matched on the row's id, not on ``active_cell['row']``: that index counts from the top
    of the *current page*, so it points at another alert as soon as the table is sorted,
    filtered or on a later page.
    """
    row_id = (active_cell or {}).get('row_id')
    if row_id is None:
        return None
    return next((row for row in table_data or [] if row.get('id') == row_id), None)


@callback(
    Output('alerts-general-selected-alert', 'children'),
    Input('alerts-datatable', 'active_cell'),
    State('alerts-datatable', 'data'),
    prevent_initial_call=True,
)
def render_selected_alert_summary(active_cell, table_data):
    """Show a compact decision summary below the executive table."""
    row = _active_alert_row(active_cell, table_data)
    if row is None:
        return html.Div()
    return dbc.Card([
        dbc.CardHeader([
            html.I(className='fas fa-bullseye me-2'),
            t("alerts_callbacks.resumen_de", row_get_id=row.get('ID', '-')),
        ]),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([html.Small(t("alerts_general.filter_unit"), className='text-muted d-block'), html.Strong(row.get('Unidad', '-'))], md=2),
                dbc.Col([html.Small(t("alerts_general.filter_system"), className='text-muted d-block'), html.Strong(row.get('Sistema', '-'))], md=2),
                # Same color as this source's chip in the table and the legend.
                dbc.Col([html.Small(t("tab_integration_validacion_avisos.fuente"), className='text-muted d-block'), html.Strong(row.get('Fuente', '-'), style={'color': row['fuente_color']} if row.get('fuente_color') else None)], md=2),
                dbc.Col([html.Small(t("alerts_callbacks.evidencia"), className='text-muted d-block'), html.Strong(row.get('Evidencia', '-'))], md=6),
            ], className='mb-3'),
            html.Strong(row.get('diagnostico_completo') or row.get('Diagnóstico', t("alerts_report.sin_diagnostico_ia_disponible")), className='d-block'),
            html.P(row.get('causa_completa') or t("alerts_report.sin_causa_probable_registrada"), className='text-muted mt-2 mb-1', style={'whiteSpace': 'pre-wrap'}),
            html.Div([
                html.I(className='fas fa-wrench me-1'),
                html.Strong(t("telemetry_callbacks.accion")),
                row.get('accion_completa') or row.get('Acción', t("alerts_report.sin_accion_recomendada_registrada")),
            ], className='text-primary mt-2'),
            _maintenance_context_summary(row),
            dbc.Button([
                html.I(className='fas fa-arrow-right me-1'), t("alerts_callbacks.ver_detalle_de_la_alerta")
            ], id='general-nav-to-detail-button', color='primary', size='sm', className='mt-3'),
        ]),
    ], className='shadow-sm', style={'borderLeft': '4px solid #3498db'})


@callback(
    Output('alerts-datatable', 'style_data_conditional'),
    Input('alerts-datatable', 'active_cell'),
    prevent_initial_call=True,
)
def highlight_selected_alert_row(active_cell):
    """Highlight the whole row behind the detail card, not only the clicked cell."""
    return alerts_report_table_styles((active_cell or {}).get('row_id'))


def _maintenance_context_summary(row):
    """Show matching maintenance context without changing the published source."""
    if not evidence_flag(row.get("has_maintenance")):
        return html.Div()
    summary = row.get("maintenance_summary", "")
    tasks = row.get("maintenance_tasks", "")
    return html.Div([
        html.Hr(),
        html.H6([
            html.I(className="fas fa-tools me-2"),
            t("alerts_callbacks.linked_maintenance_context", week=row.get("maintenance_week", "")),
        ]),
        html.P(t(
            "alerts_callbacks.maintenance_iso_window",
            start=row.get("maintenance_window_start", "")[:10],
            end=row.get("maintenance_window_end", "")[:10],
        ), className="text-muted small") if row.get("maintenance_window_start") else None,
        html.Div([
            html.Strong(t("alerts_callbacks.weekly_unit_summary")),
            html.P(summary, className="mb-2", style={"whiteSpace": "pre-wrap"}),
        ]) if summary else None,
        html.Details([
            html.Summary(t("alerts_callbacks.reported_activities")),
            html.Div(tasks, className="mt-2", style={"whiteSpace": "pre-wrap"}),
        ], open=True) if tasks else None,
        html.Div(t("alerts_callbacks.detention_duration_unreported"), className="text-muted small"),
    ], className="alert-maintenance-context mt-3")


@callback(
    Output('alerts-selected-alert-id', 'data'),
    Input('alerts-datatable', 'active_cell'),
    State('alerts-datatable', 'data'),
    prevent_initial_call=True,
)
def store_selected_alert(active_cell, table_data):
    row = _active_alert_row(active_cell, table_data)
    if row is None:
        raise PreventUpdate
    return row.get('ID')


@callback(
    [Output('alerts-date-start', 'date'),
     Output('alerts-date-end', 'date')],
    [Input('alerts-date-range-clear', 'n_clicks')],
    prevent_initial_call=True
)
def clear_date_range(_):
    """Put both Desde and Hasta back to the rolling four-week window ending today."""
    return default_alert_dates()


def _filter_alerts(alerts_df, client, units=None, sistemas=None, start_date=None,
                   source_filter=None, keep_alert_id=None):
    """Apply the Detalle filter panel to the alerts frame.

    ``source_filter`` is the "Con Tribología" / "Con Multitécnica" segmented
    control: 'yes' / 'no' narrow the list, anything else ('all', None) leaves it
    alone. ``keep_alert_id`` is an alert that stays selectable even when the
    filters would drop it, so jumping to a specific alert from the General tab is
    not undone by the control's default.
    """
    filtered_df = alerts_df.copy()

    if units:
        filtered_df = filtered_df[filtered_df['UnitId'].isin(units)]

    if sistemas:
        filtered_df = filtered_df[filtered_df['sistema'].isin(sistemas)]

    # W34-05: "fecha desde" — inclusive, Chile calendar day. The picker
    # gives a naive calendar date the user chose in local terms; its
    # midnight boundary is converted to UTC (Timestamp's own
    # representation, W34-06) before comparing, so the boundary doesn't
    # shift by the 3-4h offset. An invalid/unparseable date degrades to
    # "no lower bound" rather than raising — a broken date filter must
    # not take down the whole dropdown.
    if start_date:
        try:
            start_utc = to_utc_naive(pd.Timestamp(start_date), source_tz="America/Santiago")
            # Critical-review follow-up: Chile's DST transition lands on
            # local midnight, so a boundary date can itself be
            # nonexistent/ambiguous — to_utc_naive returns NaT for that
            # rather than raising, so it needs its own check here (the
            # except below only catches an unparseable date string).
            if pd.isna(start_utc):
                logger.warning(f"Fecha desde cae en una transición de horario de verano, ignorando filtro: {start_date!r}")
            else:
                filtered_df = filtered_df[filtered_df['Timestamp'] >= start_utc]
        except (ValueError, TypeError):
            logger.warning(f"Fecha desde inválida, ignorando filtro: {start_date!r}")

    if source_filter in (SOURCE_FILTER_YES, SOURCE_FILTER_NO):
        wants_source = source_filter == SOURCE_FILTER_YES
        if str(client or '').lower() == 'emin':
            # EMIN filters the published multi-technique type.
            has_source = filtered_df['Trigger_type'].eq('Mixto').fillna(False)
        else:
            has_source = filtered_df['has_tribology'] == True
        filtered_df = filtered_df[has_source if wants_source else ~has_source]

    if keep_alert_id and keep_alert_id not in set(filtered_df['FusionID']):
        filtered_df = pd.concat([filtered_df, alerts_df[alerts_df['FusionID'] == keep_alert_id]])

    return filtered_df


def _alert_dropdown_options(alerts_df) -> list:
    """Dropdown options for an (already filtered) alerts frame, newest first."""
    # Critical-review follow-up: assign the formatted column once,
    # directly on the frame, instead of a separate Series indexed by
    # `.loc[idx]` inside the loop.
    sorted_df = alerts_df.sort_values('Timestamp', ascending=False).copy()
    sorted_df['_fecha_local'] = format_local(sorted_df['Timestamp'], fmt='%Y-%m-%d %H:%M')
    options = []
    for _, row in sorted_df.iterrows():
        # W34-06: local wall-clock time in the dropdown label, matching
        # the table/header/chart.
        label = f"{row['FusionID']} | {row['_fecha_local']} | {row['UnitId']} | {translate_alert_component(row['componente'])}"
        options.append({'label': label, 'value': row['FusionID']})
    return options


@callback(
    Output('alert-selector-dropdown', 'options'),
    [Input('client-selector', 'value')],
    [
        State('detail-filter-unit', 'value'),
        State('detail-filter-sistema', 'value'),
        State('detail-filter-date-from', 'date'),
        State('detail-filter-tribology', 'value'),
        State('alerts-navigation-state', 'data'),
    ]
)
def initialize_alert_dropdown(client: str, units=None, sistemas=None, start_date=None,
                              source_filter=SOURCE_FILTER_DEFAULT, nav_data=None):
    """
    Initialize alert selector dropdown.

    Runs when the detail tab is rendered and when the client changes. It reads
    the filter panel's current state (the "Con Tribología" control starts on its
    default) so the list always agrees with what the filters show.

    Args:
        client: Selected client identifier
        units, sistemas, start_date, source_filter: Current filter panel values
        nav_data: Pending General -> Detalle navigation; its alert stays listed

    Returns:
        List of dropdown options
    """
    if not client:
        raise PreventUpdate

    logger.info(f"Initializing alert dropdown for client: {client}")

    alerts_df = load_alerts_data(client)

    if alerts_df.empty:
        return []

    try:
        keep_alert_id = (nav_data or {}).get('alert_id')
        options = _alert_dropdown_options(
            _filter_alerts(alerts_df, client, units, sistemas, start_date, source_filter, keep_alert_id)
        )
        logger.info(f"Dropdown initialized with {len(options)} alerts")
        return options

    except Exception as e:
        logger.error(f"Error initializing dropdown: {e}")
        return []


# ========================================
# GENERAL TAB NAVIGATION BUTTON CALLBACKS
# ========================================

@callback(
    Output('alerts-navigation-state', 'data'),
    [Input('general-nav-to-detail-button', 'n_clicks')],
    [State('alerts-selected-alert-id', 'data')],
    prevent_initial_call=True
)
def navigate_to_detail_from_general(n_clicks, selected_alert_id):
    """
    Store navigation request from General tab to Detail tab with selected alert.
    Uses store-based pattern to avoid direct output to dynamically rendered component.
    
    Args:
        n_clicks: Number of times button has been clicked
        selected_alert_id: FusionID of selected alert from dropdown
    
    Returns:
        Navigation data dictionary
    """
    logger.info(f"[NAV] BUTTON CALLBACK TRIGGERED! n_clicks={n_clicks}, alert={selected_alert_id}")
    
    if not n_clicks or not selected_alert_id:
        raise PreventUpdate
    
    logger.info(f"[NAV] Storing navigation request to Detail tab with alert: {selected_alert_id}")
    
    # Store navigation data for listener callback to process
    return {
        'target_tab': 'detail',
        'alert_id': selected_alert_id
    }


@callback(
    Output('alerts-internal-tabs', 'value', allow_duplicate=True),
    [Input('alerts-navigation-state', 'data')],
    prevent_initial_call=True
)
def switch_to_detail_tab(nav_data):
    """
    Switch to detail tab when navigation is triggered from general tab button.
    
    Args:
        nav_data: Navigation data from alerts-navigation-state store
    
    Returns:
        Tab value to switch to
    """
    logger.info(f"[NAV] TAB SWITCH LISTENER TRIGGERED: nav_data={nav_data}")
    
    if not nav_data or not nav_data.get('target_tab'):
        raise PreventUpdate
    
    target_tab = nav_data['target_tab']
    logger.info(f"[NAV] Switching to tab: {target_tab}")
    
    return target_tab


@callback(
    Output('alert-selector-dropdown', 'value', allow_duplicate=True),
    [
        Input('alert-selector-dropdown', 'options'),
        Input('alerts-navigation-state', 'data')
    ],
    [State('alerts-internal-tabs', 'value')],
    prevent_initial_call=True
)
def set_alert_from_navigation(dropdown_options, nav_data, active_tab):
    """
    Set the alert dropdown value when navigating from general tab.
    Triggers when dropdown options are populated AND navigation state has data.
    
    Args:
        dropdown_options: Dropdown options (triggers when populated)
        nav_data: Navigation data from alerts-navigation-state store
        active_tab: Currently active internal tab ('general' or 'detail')
    
    Returns:
        Alert ID to select in dropdown
    """
    from dash import callback_context
    
    trigger_info = callback_context.triggered[0] if callback_context.triggered else None
    logger.info(f"[NAV] set_alert_from_navigation called: tab={active_tab}, nav_data={nav_data}, triggered_by={trigger_info}")
    
    # Only apply if we're on detail tab
    if active_tab != 'detail':
        logger.info(f"[NAV] Not on detail tab (current: {active_tab}), skipping")
        raise PreventUpdate
        
    if not nav_data or not nav_data.get('alert_id'):
        logger.info("[NAV] No navigation data or alert_id, skipping")
        raise PreventUpdate
    
    # Only apply if navigation target is detail tab
    if nav_data.get('target_tab') != 'detail':
        logger.info(f"[NAV] Navigation target is not detail (target: {nav_data.get('target_tab')}), skipping")
        raise PreventUpdate
    
    alert_id = nav_data['alert_id']
    logger.info(f"[NAV] Setting dropdown value to: {alert_id}")
    
    return alert_id


# ========================================
# DETAIL TAB FILTER CALLBACKS
# ========================================

@callback(
    Output('detail-source-filter-label', 'children'),
    Input('client-selector', 'value'),
)
def configure_detail_source_filter(client):
    """EMIN filters the published multi-technique type; other clients filter oil."""
    is_emin = str(client or '').lower() == 'emin'
    return [
        html.I(className='fas fa-fingerprint me-1' if is_emin else 'fas fa-oil-can me-1'),
        t('tab_alerts_detail.con_multitecnica' if is_emin else 'tab_alerts_detail.con_tribologia'),
    ]


@callback(
    [
        Output('detail-filter-unit', 'options'),
        Output('detail-filter-sistema', 'options')
    ],
    [Input('client-selector', 'value')]
)
def populate_detail_filter_options(client: str):
    """
    Populate filter options in detail tab.
    
    Args:
        client: Selected client identifier
    
    Returns:
        Tuple of (unit_options, sistema_options)
    """
    if not client:
        raise PreventUpdate
    
    alerts_df = load_alerts_data(client)
    
    if alerts_df.empty:
        return [], []
    
    try:
        # Unit filter options
        unit_options = [{'label': unit, 'value': unit} for unit in sorted(alerts_df['UnitId'].unique())]
        
        # Sistema filter options
        sistema_options = [
            {'label': translate_alert_system(sistema), 'value': sistema}
            for sistema in sorted(alerts_df['sistema'].unique())
        ]
        
        logger.info(f"Filter options populated: {len(unit_options)} units, {len(sistema_options)} sistemas")
        return unit_options, sistema_options
    
    except Exception as e:
        logger.error(f"Error populating filter options: {e}")
        return [], []


@callback(
    Output('alert-selector-dropdown', 'options', allow_duplicate=True),
    [
        Input('detail-filter-unit', 'value'),
        Input('detail-filter-sistema', 'value'),
        Input('detail-filter-date-from', 'date'),
        Input('detail-filter-tribology', 'value'),
        Input('client-selector', 'value')
    ],
    [State('alert-selector-dropdown', 'value')],
    prevent_initial_call=True
)
def filter_alert_dropdown_by_criteria(units, sistemas, start_date, has_tribology, client, current_value):
    """
    Filter alert dropdown based on selected detail filters.

    Args:
        units: Selected units (list)
        sistemas: Selected sistemas (list)
        start_date: "Fecha desde" (W34-05, replaces the telemetry filter) —
            a plain calendar date string (e.g. "2026-08-01") from
            detail-filter-date-from, interpreted as a Chile calendar day.
            Inclusive; None/"" means no lower bound.
        has_tribology: The "Con Tribología" segmented control: 'yes' / 'no' /
            'all'. For EMIN it filters the published Multitécnica type, for the
            rest oil presence. The legacy component ID and argument are retained
            for existing callers; None behaves like 'all'.
        client: Selected client
        current_value: Currently selected alert ID

    Returns:
        Filtered alert options
    """
    logger.info(f"filter_alert_dropdown_by_criteria called with current_value={current_value}")

    if not client:
        raise PreventUpdate

    alerts_df = load_alerts_data(client)

    if alerts_df.empty:
        return []

    try:
        options = _alert_dropdown_options(
            _filter_alerts(alerts_df, client, units, sistemas, start_date, has_tribology)
        )
        logger.info(f"Filtered alerts: {len(options)} options")
        return options

    except Exception as e:
        logger.error(f"Error filtering alert dropdown: {e}")
        return []


def _alert_case_header(row: pd.Series) -> html.Div:
    """Render the single client-facing alert summary and its IA analysis."""
    prepared = prepare_alert_rows(pd.DataFrame([row])).iloc[0]
    timestamp = prepared.get('date_display', '-')
    diagnosis = parse_ia_message_sections(localized_value(row, 'mensaje_ia', ''))

    return dbc.Card([
        dbc.CardHeader([
            html.I(className='fas fa-fingerprint me-2'),
            html.Strong(t("alerts_callbacks.alerta", prepared_get_fusio=prepared.get('FusionID', '-')))
        ], className='bg-light'),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([html.Small(t("alerts_general.filter_unit"), className='text-muted d-block text-nowrap'), html.Strong(prepared.get('UnitId', '-'))], xs=6, lg=2),
                dbc.Col([html.Small(t("alerts_general.filter_system"), className='text-muted d-block text-nowrap'), html.Strong(prepared.get('system_display', '-'))], xs=6, lg=2),
                dbc.Col([html.Small(t("tab_mantenciones_general.componente"), className='text-muted d-block text-nowrap'), html.Strong(prepared.get('component_display', '-'))], xs=6, lg=3),
                dbc.Col([html.Small(t("tab_mantenciones_general.fecha"), className='text-muted d-block text-nowrap'), html.Strong(timestamp)], xs=6, lg=3),
                # One chip per source that contributed evidence, from the
                # alert's own source list (the same one the table's "Evidencia"
                # column reads). The old single "Fuente" pill and the
                # "Evidencia: ..." line said the same thing twice.
                dbc.Col(evidence_source_chips(row), xs=12, lg=12, className='mt-3'),
            ], className='g-3'),
            # The one signal that triggered the alert, set apart from the rest of the header.
            trigger_signal_callout(prepared.get('signal_display')),
            dbc.Alert(t("alerts_callbacks.published_mixed_incomplete"), color="info", className="mt-3 mb-0")
            if evidence_flag(row.get("source_references_checked"))
            and row.get("Trigger_type") == "Mixto"
            and sum(evidence_flag(row.get(flag)) for flag in ("has_telemetry", "has_tribology", "has_maintenance")) < 2
            else None,
            html.H5([
                html.I(className='fas fa-brain me-2'),
                t("alerts_callbacks.analisis_inteligente")
            ], className='text-primary mt-4 mb-3 pb-2 border-bottom'),
            dbc.Row([
                analysis_block(t("ai_analysis_panel.diagnostico"), diagnosis.get('diagnostico'), 'fa-search'),
                analysis_block(t("ai_analysis_panel.causa_probable"), diagnosis.get('causa_probable'), 'fa-project-diagram'),
                # The verification question has its own field in the published
                # message; it is read, never cut out of the action text.
                analysis_block(
                    t("alerts_callbacks.accion_recomendada"), diagnosis.get('acciones'), 'fa-wrench',
                    verification=diagnosis.get('verificacion'),
                ),
            ], className='g-3'),
        ])
    ], className='shadow-sm', style={'borderTop': '3px solid #3498db'})


@callback(
    Output('alert-detail-content', 'children'),
    [
        Input('alert-selector-dropdown', 'value'),
        Input('client-selector', 'value'),
        Input('alerts-navigation-state', 'data')
    ],
    prevent_initial_call=False
)
def update_detail_view(dropdown_value, client, nav_data):
    """
    Update detail view when an alert is selected from dropdown or via navigation.
    
    Args:
        dropdown_value: FusionID selected from dropdown
        client: Selected client identifier
        nav_data: Navigation data from alerts-navigation-state store
    
    Returns:
        Updated detail content layout
    """
    logger.info(f"update_detail_view called: dropdown_value={dropdown_value}, client={client}, nav_data={nav_data}")
    
    if not client:
        logger.warning("No client selected, preventing update")
        raise PreventUpdate
    
    # Determine selected alert from dropdown OR navigation state
    selected_fusion_id = dropdown_value
    
    # If dropdown is empty but navigation state has an alert ID, use that
    if not selected_fusion_id and nav_data and nav_data.get('alert_id'):
        selected_fusion_id = nav_data.get('alert_id')
        logger.info(f"Using alert ID from navigation state: {selected_fusion_id}")
    
    if not selected_fusion_id:
        logger.info("No alert selected, showing placeholder")
        return dbc.Alert([
            html.I(className="fas fa-arrow-up me-2"),
            t("tab_alerts_detail.por_favor_seleccione_una_alerta_para")
        ], color="info", className="text-center")
    
    logger.info(f"Loading detail view for alert: {selected_fusion_id}")
    
    # Load alerts data
    alerts_df = load_alerts_data(client)
    
    if alerts_df.empty:
        return dbc.Alert(t("menace_control_callbacks.no_hay_datos_de_alertas_disponibles"), color="warning")
    
    # Find selected alert
    alert_row = alerts_df[alerts_df['FusionID'] == selected_fusion_id]
    
    if alert_row.empty:
        return dbc.Alert(t("alerts_callbacks.alerta_no_encontrada", selected_fusion_id=selected_fusion_id), color="danger")
    
    alert_row = alert_row.iloc[0]
    
    try:
        # Determine which evidence sections to show
        trigger_type = alert_row['Trigger_type']
        # Normalize trigger type comparison (case-insensitive)
        trigger_lower = str(trigger_type).lower()
        show_telemetry = 'telemetria' in trigger_lower or 'mixto' in trigger_lower
        show_oil = 'tribologia' in trigger_lower or 'oil' in trigger_lower or 'mixto' in trigger_lower
        show_maintenance = pd.notna(alert_row.get('Semana_Resumen_Mantencion'))
        if client.lower() == 'emin':
            # Published source data owns the type; maintenance is context.
            show_telemetry = evidence_flag(alert_row.get('has_telemetry'))
            show_oil = evidence_flag(alert_row.get('has_tribology'))
            show_maintenance = True
        
        logger.info(f"Trigger type: {trigger_type}, Evidence sections - Telemetry: {show_telemetry}, Oil: {show_oil}, Maintenance: {show_maintenance}")
        
        # Render the alert itself first. Evidence is appended only after the
        # identity and IA analysis are available, avoiding a graph-first state.
        sections = [_alert_case_header(alert_row)]

        if show_telemetry:
            sections.append(create_telemetry_evidence_section(alert_row, client))
        
        # 3. Oil Evidence (conditional)
        if show_oil:
            sections.append(create_oil_evidence_section(alert_row, client))
        
        # 4. Maintenance Evidence (always if available)
        if show_maintenance:
            sections.append(create_maintenance_evidence_section(alert_row, client))
        
        return html.Div(sections)
    
    except Exception as e:
        logger.error(f"Error creating detail view: {e}")
        return dbc.Alert(t("alerts_callbacks.error_al_cargar_detalles", str_e=str(e)), color="danger")


clientside_callback(
    """
    function(children) {
        if (!children) {
            return window.dash_clientside.no_update;
        }
        // The detail content can include large Plotly figures.  Scroll only
        // after Dash has committed the new content so the alert header is
        // the first visible element, instead of the browser restoring a
        // middle-of-page position from the previous alert.
        window.requestAnimationFrame(function() {
            window.scrollTo({top: 0, left: 0, behavior: 'auto'});
            document.documentElement.scrollTop = 0;
            document.body.scrollTop = 0;
        });
        return Date.now();
    }
    """,
    Output('alerts-detail-scroll-trigger', 'data'),
    Input('alert-detail-content', 'children'),
    prevent_initial_call=True,
)


clientside_callback(
    """
    function(clicks, isOpen, labels) {
        if (!clicks || !labels) {
            return [window.dash_clientside.no_update, window.dash_clientside.no_update];
        }
        const open = !isOpen;
        // Charts expanded from a hidden container were laid out at zero width;
        // a resize once the panel is visible makes Plotly measure them again.
        [50, 400].forEach(function(delay) {
            window.setTimeout(function() { window.dispatchEvent(new Event('resize')); }, delay);
        });
        return [open, open ? labels.less : labels.more];
    }
    """,
    Output(SIGNALS_COLLAPSE_ID, 'is_open'),
    Output(SIGNALS_TOGGLE_ID, 'children'),
    Input(SIGNALS_TOGGLE_ID, 'n_clicks'),
    State(SIGNALS_COLLAPSE_ID, 'is_open'),
    State(SIGNALS_LABELS_ID, 'data'),
    prevent_initial_call=True,
)


def create_telemetry_evidence_section(alert_row: pd.Series, client: str) -> html.Div:
    """
    Create telemetry evidence section with sensor trends, GPS, and KPIs.
    Uses pre-processed golden layer data for simplicity and performance.
    
    Args:
        alert_row: Selected alert data
        client: Client identifier
    
    Returns:
        HTML Div with telemetry evidence
    """
    logger.info("Creating telemetry evidence section using golden layer data")
    
    try:
        alert_ids = list(dict.fromkeys(
            identifier
            for identifier in (
                _normalise_alert_identifier(alert_row.get('TelemetryID')),
                _normalise_alert_identifier(alert_row.get('FusionID')),
            )
            if identifier
        ))
        unit_id = _normalise_alert_identifier(alert_row.get('UnitId'))

        if not alert_ids:
            return html.Div([
                dbc.Alert(t("alerts_callbacks.esta_alerta_no_tiene_un_identificador"), color="info")
            ])
        if not unit_id:
            return html.Div([
                dbc.Alert(t("alerts_callbacks.esta_alerta_no_tiene_unitid_asociado"), color="info")
            ])

        # Read only the selected alert/unit when Polars is available. The
        # pandas fallback preserves the previous cached behavior.
        telemetry_golden = load_telemetry_alert_detail_for_alert(
            client, alert_ids, unit_id
        )

        if telemetry_golden.empty:
            if client.lower() == "emin":
                # The alert header already contains the event information.
                return html.Div()
            return html.Div([
                dbc.Alert(t("alerts_callbacks.no_hay_datos_de_telemetria_disponibles"), color="warning")
            ])

        # Filter telemetry data by BOTH AlertID AND Unit (AlertID is unique
        # per unit, not globally). Keep the comparison textual: Capstone IDs
        # are deterministic strings such as CAP-....
        alert_data, _, _ = _select_telemetry_alert_data(telemetry_golden, alert_row)
        
        if alert_data.empty:
            if client.lower() == "emin":
                return html.Div()
            return html.Div([
                dbc.Alert(
                    t("alerts_callbacks.no_se_encontraron_datos_de_telemetria", join_alert_ids=', '.join(alert_ids)),
                    color="warning",
                )
            ])
        
        # Drop columns with all NaN values
        alert_data_clean = alert_data.dropna(axis=1, how='all')
        
        # Extract metadata
        unit_id = alert_data_clean['Unit'].iloc[0]
        # IMPORTANT: Use alert_time from alerts_data, NOT from telemetry TimeStart
        # TimeStart is just the beginning of the telemetry window, not the actual alert moment
        alert_time = pd.to_datetime(alert_row.get('Timestamp'))
        trigger = alert_data_clean['Trigger'].iloc[0]
        
        logger.info(f"Processing telemetry alert: Unit={unit_id}, Time={alert_time}, Trigger={trigger}")

        # Load feature names mapping for Spanish titles (use FEATURE_NAMES_ES from alerts_charts)
        from dashboard.components.alerts_charts import FEATURE_NAMES_ES, select_plottable_signals
        feature_name_map = FEATURE_NAMES_ES

        # Alert-context header shown above the telemetry charts: alert id,
        # unit and the (Spanish) trigger signal name.
        alert_id_display = (
            _normalise_alert_identifier(alert_row.get('FusionID'))
            or _normalise_alert_identifier(alert_row.get('TelemetryID'))
            or '-'
        )
        trigger_display = (
            feature_name_map.get(trigger, trigger) if pd.notna(trigger) else t("alerts_callbacks.sin_senal")
        )

        # Identify features to plot (columns ending with _Value)
        value_cols = [col for col in alert_data_clean.columns if col.endswith('_Value')]
        feature_names = [col.replace('_Value', '') for col in value_cols]

        # W34-11: a panel is drawn only for signals that are both present in the
        # source (checked above) AND permitted (see select_plottable_signals).
        # Data stays available for KPIs regardless of this filter —
        # alert_data_clean itself is untouched.
        feature_names, uncatalogued = select_plottable_signals(feature_names)
        if uncatalogued:
            logger.warning(
                "Señales presentes en la fuente pero no catalogadas en SIGNAL_LABELS, "
                f"omitidas del gráfico de tendencias: {uncatalogued}"
            )

        if not feature_names:
            return html.Div([
                dbc.Alert(t("alerts_callbacks.no_se_encontraron_senales_con_valores"), color="warning")
            ])

        logger.info(f"Found {len(feature_names)} features to plot: {feature_names}")
        
        # One panel per signal in the alert window: the trigger is featured, the
        # rest go to the progressive grid (dashboard/components/alert_signal_grid.py).
        signal_panels, local_alert_time = prepare_signal_panels(
            alert_data=alert_data_clean,
            feature_names=feature_names,
            alert_time=alert_time,
            trigger=trigger,
            feature_name_map=feature_name_map,
            client=client,
        )
        if signal_panels:
            signal_evidence = create_signal_evidence(
                signal_panels, local_alert_time, settings.alert_supporting_signals_visible
            )
        else:
            signal_evidence = dbc.Alert(t("alerts_charts.no_sensor_data_in_time_window"), color="info", className="mb-0")

        # Create GPS map (if GPS data available)
        gps_map_fig = create_gps_route_map_golden(
            alert_data=alert_data_clean,
            unit_id=unit_id,
            alert_time=alert_time,
            mapbox_token=MAPBOX_TOKEN
        )
        
        # Create context KPIs
        context_kpis = create_context_kpis_cards_golden(
            alert_data=alert_data_clean,
            alert_time=alert_time,
            trigger=trigger
        )
        
        # Build section with NEW LAYOUT: [Trends full] then [KPIs 4 | GPS 8]
        return html.Div([
            # Section header
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-signal me-2"),
                        t("tab_alerts_detail.evidencia_de_telemetria")
                    ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
                    html.P(t("tab_alerts_detail.analisis_de_datos_de_sensores_y"), 
                           className="text-muted mb-3")
                ])
            ]),

            # Row 1: trigger signal + supporting signals (FULL WIDTH)
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-chart-line me-2"),
                                t("tab_alerts_detail.tendencias_de_sensores")
                            ], className="mb-0"),
                            html.Div(
                                t("alerts_callbacks.alerta_gatillo", alert_id_display=alert_id_display, unit_id=unit_id, trigger_display=trigger_display),
                                className="small fw-bold text-primary mt-1"
                            ),
                            # Quality-review follow-up: a signal present in the
                            # source but not yet in SIGNAL_LABELS used to be
                            # invisible here (logger.warning only, nothing on
                            # screen) — this line is the only user-facing
                            # trace that some evidence exists but isn't
                            # charted, so it's never mistaken for "not
                            # recorded".
                            html.Div(
                                [
                                    html.I(className="fas fa-triangle-exclamation me-1"),
                                    t("alerts_callbacks.senal_es_adicional_es_no_catalogada", len_uncatalogued=len(uncatalogued)),
                                ],
                                className="small text-warning mt-1",
                            ) if uncatalogued else None,
                        ], className="bg-light"),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-sensor-trends-callback",
                                type="circle",
                                children=[signal_evidence]
                            )
                        ])
                    ], className="shadow-sm mb-4")
                ], md=12)
            ]),
            
            # Row 2: KPIs (LEFT, 1 col x 4 rows, 4 cols) + GPS Map (RIGHT, 8 cols) - SAME HEIGHT
            dbc.Row([
                # Left: KPIs (vertical layout, 1 column x 4 rows)
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-tachometer-alt me-2"),
                                t("tab_alerts_detail.indicadores_de_contexto")
                            ], className="mb-0")
                        ], className="bg-light"),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-context-kpis-callback",
                                type="circle",
                                children=[context_kpis]
                            )
                        ], className="p-3")
                    ], className="shadow-sm mb-4 h-100")  # h-100 for full height
                ], md=4),
                
                # Right: GPS Map
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-map-marked-alt me-2"),
                                t("tab_alerts_detail.ubicacion_y_ruta_gps")
                            ], className="mb-0")
                        ], className="bg-light"),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-gps-map-callback",
                                type="circle",
                                children=[
                                    dcc.Graph(
                                        figure=gps_map_fig,
                                        config={'displayModeBar': True},
                                        style={'height': '500px'}
                                    )
                                ]
                            )
                        ], className="p-2")
                    ], className="shadow-sm mb-4 h-100")  # h-100 for full height
                ], md=8)
            ], className="gx-3")  # Horizontal spacing between columns
        ], className="mb-5")
    
    except Exception as e:
        logger.error(f"Error creating telemetry evidence: {e}")
        return html.Div([
            dbc.Alert(t("alerts_callbacks.error_al_cargar_evidencia_de_telemetria", str_e=str(e)), color="danger")
        ])


def _build_oil_tendencia_view(history_full, comp_limits, oil_hour_range, start_date, end_date):
    """
    Build the Tendencia (oil report history) sub-view: a date-range filter on
    the oil REPORT date (sampleDate, inclusive boundaries) plus the shared
    9-chart time-series grid. Isolated by design - this filter only affects
    this chart, not the rest of Monitoring > Alertas.

    Args:
        history_full: Unfiltered sampleDate-sorted history for this equipment/component.
        comp_limits: Four-limit Stewart limits dict for this component.
        oil_hour_range: oilHourRange of the most recent sample, for limit lookup.
        start_date, end_date: ISO date strings (or None for no bound).

    Returns:
        List of Dash components (date-range picker row + the chart grid).
    """
    history = history_full
    if not history.empty:
        if start_date:
            history = history[history['sampleDate'] >= pd.to_datetime(start_date)]
        if end_date:
            history = history[history['sampleDate'] <= pd.to_datetime(end_date)]

    grid = build_oil_time_series_grid(history, comp_limits, oil_hour_range)

    return [
        dbc.Row([
            dbc.Col([
                html.Small(t("alerts_callbacks.rango_de_fechas_reporte_de_aceite"), className="text-muted me-2"),
                dcc.DatePickerRange(
                    id='alert-oil-tendencia-date-range',
                    start_date=start_date,
                    end_date=end_date,
                    display_format='DD/MM/YYYY',
                    className="d-inline-block",
                ),
            ], width='auto'),
            dbc.Col([
                dbc.Button([html.I(className="fas fa-times me-1"), t("alerts_callbacks.limpiar")],
                           id='alert-oil-tendencia-date-clear', color="outline-secondary", size="sm")
            ], width='auto'),
        ], className="mb-2 align-items-center g-2"),
        grid,
    ]


def create_oil_evidence_section(alert_row: pd.Series, client: str) -> html.Div:
    """
    Create oil evidence section with grouped radar charts and threshold tables.
    Matches the style from monitoring>oil section.
    
    Args:
        alert_row: Selected alert data
        client: Client identifier
    
    Returns:
        HTML Div with oil evidence
    """
    logger.info("Creating oil evidence section")
    
    try:
        from pathlib import Path

        tribology_id = oil_report_reference(alert_row) if client.lower() == "emin" else alert_row.get('TribologyID')
        if not alert_reference(tribology_id):
            return html.Div([
                dbc.Alert(t("alerts_callbacks.no_oil_reference"), color="info")
            ])

        # Load oil data only when the alert actually references a sample.
        oil_classified = load_oil_classified(client)
        
        # Check if oil data is available
        if oil_classified.empty or tribology_id is None or (isinstance(tribology_id, float) and pd.isna(tribology_id)):
            return html.Div([
                dbc.Alert(t("alerts_callbacks.no_hay_datos_de_tribologia_disponibles"), color="warning")
            ])
        
        # Filter for this sample
        oil_report = oil_classified[
            oil_classified['sampleNumber'].map(alert_reference) == alert_reference(tribology_id)
        ]
        
        if oil_report.empty:
            return html.Div([
                dbc.Alert(t("alerts_callbacks.reporte_no_encontrado_para_muestra", tribology_id=tribology_id), color="warning")
            ])
        
        oil_report = oil_report.iloc[0]
        
        # Load essays_elements mapping
        essays_file = _data_path("oil", "essays_elements.xlsx")
        if not essays_file.exists():
            return html.Div([
                dbc.Alert(t("reports_callbacks.archivo_essays_elements_xlsx_no_encontrado"), color="warning")
            ])
        
        essays_df = load_essays_mapping(essays_file)

        # Load four-limit Stewart limits (LIC/LIM/LSM/LSC, data contract v2.8)
        from src.data.loaders import load_stewart_limits_four
        from config.settings import get_settings
        settings = get_settings()
        limits_file = settings.get_stewart_limits_four_path(client)
        limits = load_stewart_limits_four(limits_file) if limits_file.exists() else None

        if not limits:
            return html.Div([
                dbc.Alert(t("alerts_callbacks.limites_stewart_no_disponibles"), color="warning")
            ])

        # Get limits for this component
        machine = oil_report.get('machineName', '')
        component_normalized = oil_report.get('componentNameNormalized', oil_report.get('componentName', ''))

        if client not in limits or machine not in limits[client] or component_normalized not in limits[client][machine]:
            return html.Div([
                dbc.Alert(t("alerts_callbacks.limites_no_disponibles_para", machine=machine, component_normalized=component_normalized), color="warning")
            ])

        comp_limits = limits[client][machine][component_normalized]

        # Get sample's oil hour range for v2.3 stratified limits
        sample_oil_hour_range = oil_report.get('oilHourRange', 'UNKNOWN')
        logger.info(f"Sample oilHourRange: {sample_oil_hour_range}")

        # ── Tendencia: same equipment/component history, shared grid builder ──
        # Scoped to a date-range filter on the oil REPORT date (sampleDate),
        # defaulting to this equipment/component's own latest 12 months of
        # history. This filter is isolated to the Tendencia chart below - it
        # does not affect the alerts list/table/KPIs elsewhere in Monitoring >
        # Alertas.
        unit_id = oil_report.get('unitId')
        oil_component_name = oil_report.get('componentName')
        tendencia_history_full = oil_classified[
            (oil_classified['unitId'] == unit_id) & (oil_classified['componentName'] == oil_component_name)
        ].copy()
        if not tendencia_history_full.empty:
            tendencia_history_full['sampleDate'] = pd.to_datetime(tendencia_history_full['sampleDate'])
            tendencia_history_full = tendencia_history_full.sort_values('sampleDate')

        default_end = tendencia_history_full['sampleDate'].max() if not tendencia_history_full.empty else None
        default_start = (default_end - pd.DateOffset(months=12)) if default_end is not None else None
        default_start_str = default_start.strftime('%Y-%m-%d') if default_start is not None else None
        default_end_str = default_end.strftime('%Y-%m-%d') if default_end is not None else None

        tendencia_context = {
            'client': client,
            'unit_id': unit_id,
            'component_name': oil_component_name,
            'machine': machine,
            'component_normalized': component_normalized,
            'oil_hour_range': sample_oil_hour_range,
        }

        tendencia_view_children = _build_oil_tendencia_view(
            tendencia_history_full, comp_limits, sample_oil_hour_range,
            start_date=default_start_str, end_date=default_end_str,
        )

        # Radar charts + tables for the latest essay, shared with
        # Monitoring > Oil > Details (dashboard/components/oil_charts.py::build_oil_radar_view)
        charts_and_tables = build_oil_radar_view(oil_report, comp_limits, sample_oil_hour_range, essays_df)

        # Build final section
        report_status = oil_report.get('report_status', 'N/A')
        status_colors = {
            'Normal': 'success',
            'Marginal': 'warning',
            'Condenatorio': 'danger',
            'Critico': 'danger',
            'Anormal': 'danger'
        }
        status_color = status_colors.get(report_status, 'secondary')
        
        # Get oil meter and oil hour range for display
        oil_meter = oil_report.get('oilMeter', None)
        oil_meter_display = f"{oil_meter:.1f}h" if pd.notna(oil_meter) else "N/A"
        
        # Oil hour range badge color and text
        oil_hour_range_colors = {
            'LT_1000': 'success',  # Fresh oil - green
            'GE_1000': 'warning',  # Aged oil - orange
            'UNKNOWN': 'secondary'  # Unknown - gray
        }
        oil_hour_range_labels = {
            'LT_1000': t("alerts_callbacks.aceite_fresco_1000h"),
            'GE_1000': t("alerts_callbacks.aceite_envejecido_1000h"),
            'UNKNOWN': t("alerts_callbacks.edad_de_aceite_desconocida")
        }
        oil_hour_color = oil_hour_range_colors.get(sample_oil_hour_range, 'secondary')
        oil_hour_label = oil_hour_range_labels.get(sample_oil_hour_range, sample_oil_hour_range)
        
        return html.Div([
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-flask me-2"),
                        t("alerts_callbacks.analisis_de_aceite")
                    ], className="text-warning mb-2"),
                    html.Div([
                        dbc.Badge(
                            t("alerts_callbacks.estado", report_status=report_status),
                            color=status_color,
                            className="me-2",
                            style={'fontSize': '1rem'}
                        ),
                        dbc.Badge(
                            t("alerts_callbacks.id_muestra", tribology_id=tribology_id),
                            color="info",
                            className="me-2",
                            style={'fontSize': '1rem'}
                        ),
                        dbc.Badge(
                            t("alerts_callbacks.horas_aceite", oil_meter_display=oil_meter_display),
                            color="dark",
                            className="me-2",
                            style={'fontSize': '1rem'}
                        ),
                        dbc.Badge(
                            oil_hour_label,
                            color=oil_hour_color,
                            className="mb-3",
                            style={'fontSize': '1rem'},
                            title=t("alerts_callbacks.limites_estratificados_v2_3_basados_en")
                        )
                    ], className="mb-3")
                ])
            ]),
            dcc.Store(id='alert-oil-tendencia-context', data=tendencia_context),
            dcc.Tabs(
                id='alert-oil-view-selector',
                value='tendencia',
                children=[
                    # pred-tab: the indicator sits under the label alone, not across
                    # the tab's share of the whole bar (see custom_tabs.css).
                    dcc.Tab(label=t("tab_reports.tendencia"), value='tendencia',
                            className='custom-tab pred-tab',
                            selected_className='custom-tab--selected pred-tab--selected'),
                    dcc.Tab(label=t("tab_reports.ultimo_ensayo"), value='ultimo_ensayo',
                            className='custom-tab pred-tab',
                            selected_className='custom-tab--selected pred-tab--selected'),
                ],
                className='mb-3'
            ),
            html.Div(id='alert-oil-tendencia-view', children=tendencia_view_children),
            html.Div(id='alert-oil-radar-view', children=[html.Div(charts_and_tables)],
                     style={'display': 'none'}),
        ], className="mb-5")
    
    except Exception as e:
        logger.error(f"Error creating oil evidence: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return html.Div([
            dbc.Alert(t("alerts_callbacks.error_al_cargar_evidencia_de_tribologia", str_e=str(e)), color="danger")
        ])


@callback(
    Output('alert-oil-tendencia-view', 'style'),
    Output('alert-oil-radar-view', 'style'),
    Input('alert-oil-view-selector', 'value'),
    prevent_initial_call=True,
)
def toggle_oil_evidence_view(view):
    """Switch between the Tendencia grid and the Último Ensayo radar without re-rendering either."""
    if view == 'ultimo_ensayo':
        return {'display': 'none'}, {'display': 'block'}
    return {'display': 'block'}, {'display': 'none'}


@callback(
    Output('alert-oil-tendencia-view', 'children'),
    Input('alert-oil-tendencia-date-range', 'start_date'),
    Input('alert-oil-tendencia-date-range', 'end_date'),
    State('alert-oil-tendencia-context', 'data'),
    prevent_initial_call=True,
)
def update_oil_tendencia_range(start_date, end_date, context):
    """
    Re-filter the Tendencia chart by oil report date (sampleDate). Isolated by
    design: only this chart's Output is touched, nothing else in Monitoring >
    Alertas reacts to this filter.
    """
    if not context:
        raise PreventUpdate

    from src.data.loaders import load_stewart_limits_four
    from config.settings import get_settings

    client = context['client']
    oil_classified = load_oil_classified(client)
    history_full = oil_classified[
        (oil_classified['unitId'] == context['unit_id'])
        & (oil_classified['componentName'] == context['component_name'])
    ].copy()
    if not history_full.empty:
        history_full['sampleDate'] = pd.to_datetime(history_full['sampleDate'])
        history_full = history_full.sort_values('sampleDate')

    settings = get_settings()
    limits_file = settings.get_stewart_limits_four_path(client)
    limits = load_stewart_limits_four(limits_file) if limits_file.exists() else {}
    comp_limits = limits.get(client, {}).get(context['machine'], {}).get(context['component_normalized'], {})

    return _build_oil_tendencia_view(
        history_full, comp_limits, context['oil_hour_range'],
        start_date=start_date, end_date=end_date,
    )


@callback(
    Output('alert-oil-tendencia-date-range', 'start_date'),
    Output('alert-oil-tendencia-date-range', 'end_date'),
    Input('alert-oil-tendencia-date-clear', 'n_clicks'),
    prevent_initial_call=True,
)
def clear_oil_tendencia_date_range(_):
    """Clear the Tendencia date filter, showing the full available history."""
    return None, None


def _create_emin_maintenance_evidence_section(alert_row):
    result = load_emin_maintenance_evidence(alert_row)
    heading = html.H4([
        html.I(className="fas fa-tools me-2"),
        t("alerts_callbacks.evidencia_de_mantenimiento"),
    ], className="text-secondary mb-3")
    window = html.P(t(
        "alerts_callbacks.maintenance_iso_window",
        start=result["start"][:10], end=result["end"][:10],
    ), className="text-muted") if result["start"] else None
    if result["evidence"] is None:
        message = t("alerts_callbacks.maintenance_" + result["status"])
        return html.Div([heading, window, dbc.Alert(message, color="info")], className="mb-4")
    return html.Div([
        heading, window,
        create_maintenance_display(
            result["evidence"], alert_row["sistema"], include_all_systems=True,
        ),
    ], className="mb-4")


def create_maintenance_evidence_section(alert_row: pd.Series, client: str) -> html.Div:
    """
    Create maintenance evidence section.
    
    Args:
        alert_row: Selected alert data
        client: Client identifier
    
    Returns:
        HTML Div with maintenance evidence
    """
    logger.info("Creating maintenance evidence section")
    
    try:
        if client.lower() == 'emin':
            return _create_emin_maintenance_evidence_section(alert_row)
        # Get maintenance week
        maintenance_week = alert_row.get('Semana_Resumen_Mantencion')
        
        if pd.isna(maintenance_week) or not maintenance_week:
            return html.Div([
                dbc.Alert(t("alerts_callbacks.no_hay_referencia_de_semana_de"), color="info")
            ])
        
        # Load maintenance data
        maintenance_df = load_maintenance_week(client, maintenance_week)
        
        if maintenance_df.empty:
            return html.Div([
                dbc.Alert(t("alerts_callbacks.no_hay_datos_de_mantenimiento_para", maintenance_week=maintenance_week), color="warning")
            ])
        
        # Filter for this unit
        matches = maintenance_df[maintenance_df['UnitId'] == alert_row['UnitId']]
        unit_maintenance = None if matches.empty else matches.iloc[0]

        if unit_maintenance is None:
            return html.Div([
                dbc.Alert(t("alerts_callbacks.no_hay_datos_de_mantenimiento_para_2", alert_row_unitid=alert_row['UnitId']), color="warning")
            ])

        
        # Create maintenance display
        maintenance_card = create_maintenance_display(
            maintenance_data=unit_maintenance,
            alert_system=alert_row['sistema'],
        )
        
        # Build section
        return html.Div([
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-tools me-2"),
                        t("alerts_callbacks.evidencia_de_mantenimiento")
                    ], className="text-secondary mb-3")
                ])
            ]),
            
            dbc.Row([
                dbc.Col([
                    maintenance_card
                ], md=12)
            ])
        ], className="mb-4")
    
    except Exception as e:
        logger.error(f"Error creating maintenance evidence: {e}")
        return html.Div([
            dbc.Alert(t("alerts_callbacks.error_al_cargar_evidencia_de_mantenimiento", str_e=str(e)), color="danger")
        ])
