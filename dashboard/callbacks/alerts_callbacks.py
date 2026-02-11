"""
Callbacks for Alerts Dashboard.

Handles all interactivity for the unified alerts view with internal tabs,
interactive filtering, and cross-navigation.
"""

import pandas as pd
from dash import callback, Input, Output, State, html, dcc, no_update, dash_table
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from datetime import datetime, timedelta
import numpy as np
import plotly.graph_objects as go

from src.data.loaders import (
    load_alerts_data,
    load_telemetry_values,
    load_telemetry_states,
    load_telemetry_limits,
    load_telemetry_alerts_metadata,
    load_component_mapping,
    load_feature_names,
    load_oil_classified,
    load_maintenance_week
)
from dashboard.components.alerts_charts import (
    create_alerts_per_unit_chart,
    create_alerts_per_month_chart,
    create_trigger_distribution_treemap,
    create_system_distribution_pie_chart,
    create_sensor_trends_chart,
    create_gps_route_map,
    create_oil_radar_chart
)
from dashboard.components.alerts_tables import (
    create_alerts_datatable,
    create_alert_detail_card,
    create_context_kpis_cards,
    create_maintenance_display
)
from dashboard.tabs.tab_alerts_general import create_summary_stats_display, create_layout as create_general_layout
from dashboard.tabs.tab_alerts_detail import (
    create_alert_detail_content,
    create_oil_status_display,
    create_layout as create_detail_layout
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Configuration
M1 = 60  # Minutes before alert
M2 = 10  # Minutes after alert
MAPBOX_TOKEN = "pk.eyJ1IjoicGF0bzI2IiwiYSI6ImNscDdvc2FxNDF6b2sya3F2eHZ6bG1pdzgifQ.uW_fqM1_9beP_OTFvHm3Nw"


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
        return html.Div("Tab no encontrado")


# ========================================
# STORES FOR FILTERING
# ========================================

# Store for active filters in General tab
@callback(
    Output('alerts-filter-store', 'data'),
    [
        Input('alerts-unit-distribution-chart', 'clickData'),
        Input('alerts-month-distribution-chart', 'clickData'),
        Input('alerts-trigger-distribution-chart', 'clickData'),
        Input('alerts-system-distribution-chart', 'clickData')
    ],
    [State('alerts-filter-store', 'data')]
)
def update_filters_from_clicks(unit_click, month_click, trigger_click, system_click, current_filters):
    """
    Update filter store based on chart clicks.
    Toggle behavior: clicking the same value again clears that filter.
    
    Args:
        unit_click: Click data from unit distribution chart
        month_click: Click data from month distribution chart
        trigger_click: Click data from trigger distribution chart
        system_click: Click data from system distribution chart
        current_filters: Current filter state
    
    Returns:
        Updated filters dictionary
    """
    from dash import callback_context
    
    if not callback_context.triggered:
        return current_filters or {}
    
    filters = current_filters or {}
    trigger_id = callback_context.triggered[0]['prop_id'].split('.')[0]
    
    # Handle unit click - toggle behavior
    if trigger_id == 'alerts-unit-distribution-chart' and unit_click:
        unit = unit_click['points'][0]['y']
        if filters.get('unit') == unit:
            # Clicking same unit - clear filter
            filters.pop('unit', None)
            logger.info(f"Unit filter cleared (was: {unit})")
        else:
            filters['unit'] = unit
            logger.info(f"Unit filter set to: {unit}")
    
    # Handle month click - toggle behavior
    elif trigger_id == 'alerts-month-distribution-chart' and month_click:
        month = month_click['points'][0]['x']
        if filters.get('month') == month:
            # Clicking same month - clear filter
            filters.pop('month', None)
            logger.info(f"Month filter cleared (was: {month})")
        else:
            filters['month'] = month
            logger.info(f"Month filter set to: {month}")
    
    # Handle trigger click - toggle behavior
    elif trigger_id == 'alerts-trigger-distribution-chart' and trigger_click:
        trigger = trigger_click['points'][0]['label']
        if filters.get('trigger') == trigger:
            # Clicking same trigger - clear filter
            filters.pop('trigger', None)
            logger.info(f"Trigger filter cleared (was: {trigger})")
        else:
            filters['trigger'] = trigger
            logger.info(f"Trigger filter set to: {trigger}")
    
    # Handle system click - toggle behavior
    elif trigger_id == 'alerts-system-distribution-chart' and system_click:
        system = system_click['points'][0]['label']
        if filters.get('sistema') == system:
            # Clicking same system - clear filter
            filters.pop('sistema', None)
            logger.info(f"System filter cleared (was: {system})")
        else:
            filters['sistema'] = system
            logger.info(f"System filter set to: {system}")
    
    return filters


# ========================================
# GENERAL TAB CALLBACKS
# ========================================

@callback(
    [
        Output('alerts-unit-distribution-chart', 'figure'),
        Output('alerts-month-distribution-chart', 'figure'),
        Output('alerts-trigger-distribution-chart', 'figure'),
        Output('alerts-system-distribution-chart', 'figure'),
        Output('alerts-summary-stats', 'children'),
        Output('alerts-table-container', 'children')
    ],
    [
        Input('client-selector', 'value'),
        Input('alerts-filter-store', 'data')
    ]
)
def update_general_tab(client: str, filters: dict):
    """
    Update all components in the General Tab when client changes or filters are applied.
    
    Args:
        client: Selected client identifier
        filters: Dictionary with active filters (unit, month, trigger, sistema)
    
    Returns:
        Tuple of (unit_chart, month_chart, trigger_chart, system_chart, stats, table)
    """
    if not client:
        raise PreventUpdate
    
    logger.info(f"Loading alerts general view for client: {client}")
    if filters:
        logger.info(f"Active filters: {filters}")
    
    # Load alerts data
    alerts_df = load_alerts_data(client)
    
    if alerts_df.empty:
        logger.warning(f"No alerts data available for client: {client}")
        empty_fig = {'data': [], 'layout': {'title': 'No data available'}}
        empty_alert = dbc.Alert("No hay datos de alertas disponibles", color="warning")
        return empty_fig, empty_fig, empty_fig, empty_fig, empty_alert, empty_alert
    
    try:
        # Apply filters if present
        filtered_df = alerts_df.copy()
        
        if filters:
            if 'unit' in filters and filters['unit']:
                filtered_df = filtered_df[filtered_df['UnitId'] == filters['unit']]
                logger.info(f"After unit filter: {len(filtered_df)} rows")
            if 'month' in filters and filters['month']:
                # Extract year-month for comparison (YYYY-MM format)
                month_str = str(filters['month'])[:7]  # Take first 7 chars: '2025-01'
                filtered_df['Month_str'] = filtered_df['Month'].astype(str).str[:7]
                filtered_df = filtered_df[filtered_df['Month_str'] == month_str]
                logger.info(f"After month filter ({month_str}): {len(filtered_df)} rows")
            if 'trigger' in filters and filters['trigger']:
                filtered_df = filtered_df[filtered_df['Trigger_type'] == filters['trigger']]
                logger.info(f"After trigger filter: {len(filtered_df)} rows")
            if 'sistema' in filters and filters['sistema']:
                filtered_df = filtered_df[filtered_df['sistema'] == filters['sistema']]
                logger.info(f"After sistema filter: {len(filtered_df)} rows")
        
        if filtered_df.empty:
            logger.warning("No data after applying filters")
            empty_fig = {'data': [], 'layout': {'title': 'No hay datos con los filtros aplicados'}}
            empty_alert = dbc.Alert("No hay datos con los filtros aplicados", color="info")
            return empty_fig, empty_fig, empty_fig, empty_fig, empty_alert, empty_alert
        
        # Create charts (using filtered data for visualization)
        unit_chart = create_alerts_per_unit_chart(filtered_df)
        month_chart = create_alerts_per_month_chart(filtered_df)
        trigger_chart = create_trigger_distribution_treemap(filtered_df)
        system_chart = create_system_distribution_pie_chart(filtered_df)
        
        # Calculate summary statistics
        total_alerts = len(filtered_df)
        total_units = filtered_df['UnitId'].nunique()
        telemetry_pct = (filtered_df['has_telemetry'].sum() / total_alerts * 100) if total_alerts > 0 else 0
        oil_pct = (filtered_df['has_tribology'].sum() / total_alerts * 100) if total_alerts > 0 else 0
        
        stats = create_summary_stats_display(total_alerts, total_units, telemetry_pct, oil_pct)
        
        # Create table
        table = create_alerts_datatable(filtered_df)
        
        logger.info(f"General tab updated successfully with {total_alerts} alerts")
        return unit_chart, month_chart, trigger_chart, system_chart, stats, table
    
    except Exception as e:
        logger.error(f"Error updating general tab: {e}")
        error_fig = {'data': [], 'layout': {'title': f'Error: {str(e)}'}}
        error_alert = dbc.Alert(f"Error al cargar datos: {str(e)}", color="danger")
        return error_fig, error_fig, error_fig, error_fig, error_alert, error_alert


@callback(
    Output('alert-selector-dropdown', 'options'),
    [Input('client-selector', 'value')]
)
def initialize_alert_dropdown(client: str):
    """
    Initialize alert selector dropdown with all available alerts.
    
    Args:
        client: Selected client identifier
    
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
        # Create dropdown options
        options = []
        for _, row in alerts_df.sort_values('Timestamp', ascending=False).iterrows():
            label = f"{row['FusionID']} | {row['Timestamp'].strftime('%Y-%m-%d %H:%M')} | {row['UnitId']} | {row['componente']}"
            options.append({'label': label, 'value': row['FusionID']})
        
        logger.info(f"Dropdown initialized with {len(options)} alerts")
        return options
    
    except Exception as e:
        logger.error(f"Error initializing dropdown: {e}")
        return []


@callback(
    [
        Output('alerts-internal-tabs', 'value', allow_duplicate=True),
        Output('alert-selector-dropdown', 'value', allow_duplicate=True)
    ],
    [
        Input('alerts-datatable', 'active_cell')
    ],
    [
        State('alerts-datatable', 'derived_virtual_data')
    ],
    prevent_initial_call=True
)
def navigate_to_detail_on_row_click(active_cell, derived_data):
    """
    Navigate to detail tab when a table cell is clicked.
    Uses active_cell with derived_virtual_data to handle pagination/filtering.
    
    Args:
        active_cell: Dictionary with 'row' and 'column' keys indicating clicked cell
        derived_data: Currently visible/filtered table data
    
    Returns:
        Tuple of (tab_value, alert_id)
    """
    logger.info(f"🔵 NAVIGATE CALLBACK TRIGGERED: active_cell={active_cell}, has_data={bool(derived_data)}")
    
    if not active_cell or not derived_data:
        logger.info("❌ No cell clicked or no data, preventing update")
        raise PreventUpdate
    
    try:
        # Get the row index from active_cell (refers to currently visible page)
        row_index = active_cell['row']
        
        # Get the selected alert ID from derived data (handles pagination/filtering)
        selected_fusion_id = derived_data[row_index]['ID']
        logger.info(f"✅ Row {row_index} clicked! Navigating to detail for alert: {selected_fusion_id}")
        
        # Switch to detail tab and set the dropdown value
        return 'detail', selected_fusion_id
    
    except Exception as e:
        logger.error(f"❌ ERROR navigating to detail from row click: {e}", exc_info=True)
        raise PreventUpdate


# ========================================
# DETAIL TAB FILTER CALLBACKS
# ========================================

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
        sistema_options = [{'label': sistema, 'value': sistema} for sistema in sorted(alerts_df['sistema'].unique())]
        
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
        Input('detail-filter-telemetry', 'value'),
        Input('detail-filter-tribology', 'value'),
        Input('client-selector', 'value')
    ],
    [State('alert-selector-dropdown', 'value')],
    prevent_initial_call=True
)
def filter_alert_dropdown_by_criteria(units, sistemas, has_telemetry, has_tribology, client, current_value):
    """
    Filter alert dropdown based on selected detail filters.
    Preserves current selection if it's still in the filtered list.
    
    Args:
        units: Selected units (list)
        sistemas: Selected sistemas (list)
        has_telemetry: Filter for telemetry presence
        has_tribology: Filter for tribology presence
        client: Selected client
        current_value: Currently selected alert ID
    
    Returns:
        Filtered alert options
    """
    logger.info(f"filter_alert_dropdown_by_criteria called with current_value={current_value}")
    
    if not client:
        raise PreventUpdate
    
    # Check if any filters are actually set
    has_any_filter = any([units, sistemas, has_telemetry, has_tribology])
    if not has_any_filter:
        logger.info("No filters set, skipping filter update")
        raise PreventUpdate
    
    alerts_df = load_alerts_data(client)
    
    if alerts_df.empty:
        return []
    
    try:
        # Apply filters
        filtered_df = alerts_df.copy()
        
        if units:
            filtered_df = filtered_df[filtered_df['UnitId'].isin(units)]
        
        if sistemas:
            filtered_df = filtered_df[filtered_df['sistema'].isin(sistemas)]
        
        if has_telemetry == 'yes':
            filtered_df = filtered_df[filtered_df['has_telemetry'] == True]
        elif has_telemetry == 'no':
            filtered_df = filtered_df[filtered_df['has_telemetry'] == False]
        
        if has_tribology == 'yes':
            filtered_df = filtered_df[filtered_df['has_tribology'] == True]
        elif has_tribology == 'no':
            filtered_df = filtered_df[filtered_df['has_tribology'] == False]
        
        # Create filtered options
        alert_options = []
        for _, row in filtered_df.sort_values('Timestamp', ascending=False).iterrows():
            label = f"{row['FusionID']} | {row['Timestamp'].strftime('%Y-%m-%d %H:%M')} | {row['UnitId']} | {row['componente']}"
            alert_options.append({'label': label, 'value': row['FusionID']})
        
        logger.info(f"Filtered alerts: {len(alert_options)} options")
        return alert_options
    
    except Exception as e:
        logger.error(f"Error filtering alert dropdown: {e}")
        return []

@callback(
    Output('alert-detail-content', 'children'),
    [
        Input('alert-selector-dropdown', 'value'),
        Input('client-selector', 'value')
    ],
    prevent_initial_call=False
)
def update_detail_view(dropdown_value, client):
    """
    Update detail view when an alert is selected from dropdown.
    
    Args:
        dropdown_value: FusionID selected from dropdown
        client: Selected client identifier
    
    Returns:
        Updated detail content layout
    """
    logger.info(f"update_detail_view called: dropdown_value={dropdown_value}, client={client}")
    
    if not client:
        logger.warning("No client selected, preventing update")
        raise PreventUpdate
    
    # Determine selected alert from dropdown
    selected_fusion_id = dropdown_value
    
    if not selected_fusion_id:
        logger.info("No alert selected, showing placeholder")
        return dbc.Alert([
            html.I(className="fas fa-arrow-up me-2"),
            "Por favor, seleccione una alerta para ver los detalles"
        ], color="info", className="text-center")
    
    logger.info(f"Loading detail view for alert: {selected_fusion_id}")
    
    # Load alerts data
    alerts_df = load_alerts_data(client)
    
    if alerts_df.empty:
        return dbc.Alert("No hay datos de alertas disponibles", color="warning")
    
    # Find selected alert
    alert_row = alerts_df[alerts_df['FusionID'] == selected_fusion_id]
    
    if alert_row.empty:
        return dbc.Alert(f"Alerta no encontrada: {selected_fusion_id}", color="danger")
    
    alert_row = alert_row.iloc[0]
    
    try:
        # Determine which evidence sections to show
        trigger_type = alert_row['Trigger_type']
        # Normalize trigger type comparison (case-insensitive)
        trigger_lower = str(trigger_type).lower()
        show_telemetry = 'telemetria' in trigger_lower or 'mixto' in trigger_lower
        show_oil = 'tribologia' in trigger_lower or 'oil' in trigger_lower or 'mixto' in trigger_lower
        show_maintenance = pd.notna(alert_row.get('Semana_Resumen_Mantencion'))
        
        logger.info(f"Trigger type: {trigger_type}, Evidence sections - Telemetry: {show_telemetry}, Oil: {show_oil}, Maintenance: {show_maintenance}")
        
        # Create detail content structure
        sections = []
        
        # 1. Alert Specification Card
        sections.append(
            dbc.Row([
                dbc.Col([
                    create_alert_detail_card(alert_row)
                ], md=12)
            ], className="mb-4")
        )
        
        # 2. Telemetry Evidence (conditional)
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
        return dbc.Alert(f"Error al cargar detalles: {str(e)}", color="danger")


def create_telemetry_evidence_section(alert_row: pd.Series, client: str) -> html.Div:
    """
    Create telemetry evidence section with sensor trends, GPS, and KPIs.
    
    Args:
        alert_row: Selected alert data
        client: Client identifier
    
    Returns:
        HTML Div with telemetry evidence
    """
    logger.info("Creating telemetry evidence section")
    
    try:
        # Load telemetry data
        telemetry_values = load_telemetry_values(client)
        telemetry_states = load_telemetry_states(client)
        limits_config = load_telemetry_limits(client)
        telemetry_alerts = load_telemetry_alerts_metadata(client)
        component_mapping = load_component_mapping(client)
        feature_names = load_feature_names(client)
        
        if telemetry_values.empty:
            return html.Div([
                dbc.Alert("No hay datos de telemetría disponibles", color="warning")
            ])
        
        # Define time window
        alert_time = alert_row['Timestamp']
        window_start = alert_time - timedelta(minutes=M1)
        window_end = alert_time + timedelta(minutes=M2)
        
        # Filter data for unit and time window
        unit_data = telemetry_values[
            (telemetry_values['Unit'] == alert_row['UnitId']) &
            (telemetry_values['Fecha'] >= window_start) &
            (telemetry_values['Fecha'] <= window_end)
        ].copy()
        
        # Merge with states
        if not telemetry_states.empty:
            unit_data = unit_data.merge(
                telemetry_states[['Fecha', 'Unit', 'Estado', 'EstadoCarga']],
                on=['Fecha', 'Unit'],
                how='left'
            )
        
        if unit_data.empty:
            return html.Div([
                dbc.Alert("No hay datos de telemetría en la ventana de tiempo", color="warning")
            ])
        
        # Get trigger feature and related features
        alert_trigger = None
        if pd.notna(alert_row.get('TelemetryID')) and not telemetry_alerts.empty:
            trigger_info = telemetry_alerts[
                telemetry_alerts['AlertID'] == str(alert_row['TelemetryID'])
            ]
            if not trigger_info.empty:
                alert_trigger = trigger_info.iloc[0]['Trigger']
        
        # Determine which sensors to display
        sensor_columns = []
        if alert_trigger and not component_mapping.empty:
            feature_map = component_mapping[
                component_mapping['PrimaryFeature'] == alert_trigger
            ]
            
            if not feature_map.empty:
                feature_map = feature_map.iloc[0]
                primary_feature = feature_map['PrimaryFeature']
                related_features = feature_map['RelatedFeatures']
                
                # Convert to list if needed
                if isinstance(related_features, np.ndarray):
                    related_features = related_features.tolist()
                elif not isinstance(related_features, list):
                    related_features = []
                
                # Combine features
                features_to_display = [primary_feature] + related_features
                sensor_columns = [f for f in features_to_display if f in unit_data.columns]
        
        # Fallback: use first 3 sensor columns
        if not sensor_columns:
            sensor_columns = [col for col in unit_data.columns 
                             if col not in ['Fecha', 'Unit', 'Estado', 'EstadoCarga', 
                                           'GPSLat', 'GPSLon', 'GPSElevation']][:3]
        
        # Create sensor trends chart
        sensor_trends_fig = create_sensor_trends_chart(
            telemetry_values=telemetry_values,
            telemetry_states=telemetry_states,
            limits_config=limits_config,
            unit_id=alert_row['UnitId'],
            sensor_columns=sensor_columns,
            alert_time=alert_time,
            window_start=window_start,
            window_end=window_end,
            feature_names=feature_names
        )
        
        # Create GPS map (if GPS data available)
        gps_map_fig = create_gps_route_map(
            telemetry_values=telemetry_values,
            unit_id=alert_row['UnitId'],
            alert_time=alert_time,
            window_start=window_start,
            window_end=window_end,
            mapbox_token=MAPBOX_TOKEN
        )
        
        # Create context KPIs
        context_kpis = create_context_kpis_cards(
            alert_row=alert_row,
            telemetry_data=unit_data,
            alert_time=alert_time
        )
        
        # Build section
        return html.Div([
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-satellite-dish me-2"),
                        "Evidencia de Telemetría"
                    ], className="text-info mb-3")
                ])
            ]),
            
            # TimeSeries | GPS (side by side)
            dbc.Row([
                # Sensor Trends (left side - 6 columns)
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-chart-line me-2"),
                                "Tendencias de Sensores"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-sensor-trends-callback",
                                type="circle",
                                children=[
                                    dcc.Graph(
                                        figure=sensor_trends_fig,
                                        config={'displayModeBar': True}
                                    )
                                ]
                            )
                        ])
                    ], className="shadow-sm mb-4")
                ], md=6),
                
                # GPS Map (right side - 6 columns)
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-map-marked-alt me-2"),
                                "Ruta GPS"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-gps-map-callback",
                                type="circle",
                                children=[
                                    dcc.Graph(
                                        figure=gps_map_fig,
                                        config={'displayModeBar': True},
                                        style={'height': '600px'}
                                    )
                                ]
                            )
                        ])
                    ], className="shadow-sm mb-4")
                ], md=6)
            ]),
            
            # Context KPIs (full width)
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-tachometer-alt me-2"),
                                "Indicadores de Contexto"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-context-kpis-callback",
                                type="circle",
                                children=[
                                    context_kpis
                                ]
                            )
                        ])
                    ], className="shadow-sm mb-4")
                ], md=12)
            ])
        ], className="mb-5")
    
    except Exception as e:
        logger.error(f"Error creating telemetry evidence: {e}")
        return html.Div([
            dbc.Alert(f"Error al cargar evidencia de telemetría: {str(e)}", color="danger")
        ])


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
        from dash import dash_table
        
        # Load oil data
        oil_classified = load_oil_classified(client)
        
        # Check if oil data is available
        tribology_id = alert_row.get('TribologyID')
        if oil_classified.empty or tribology_id is None or (isinstance(tribology_id, float) and pd.isna(tribology_id)):
            return html.Div([
                dbc.Alert("No hay datos de tribología disponibles", color="warning")
            ])
        
        # Filter for this sample
        oil_report = oil_classified[
            oil_classified['sampleNumber'] == tribology_id
        ]
        
        if oil_report.empty:
            return html.Div([
                dbc.Alert(f"Reporte no encontrado para muestra: {tribology_id}", color="warning")
            ])
        
        oil_report = oil_report.iloc[0]
        
        # Load essays_elements mapping
        essays_file = Path("data/oil/essays_elements.xlsx")
        if not essays_file.exists():
            return html.Div([
                dbc.Alert("Archivo essays_elements.xlsx no encontrado", color="warning")
            ])
        
        essays_df = pd.read_excel(essays_file)
        essays_df = essays_df.dropna(subset=['ElementNameSpanish', 'GroupElement'])
        
        # Group essays by GroupElement
        group_mapping = essays_df.groupby('GroupElement')['ElementNameSpanish'].apply(list).to_dict()
        
        # Order groups: Desgaste, Aditivos, then others alphabetically
        priority_groups = ['Desgaste', 'Aditivos']
        ordered_groups = []
        for group in priority_groups:
            if group in group_mapping:
                ordered_groups.append(group)
        remaining_groups = sorted([g for g in group_mapping.keys() if g not in priority_groups])
        ordered_groups.extend(remaining_groups)
        
        # Load Stewart limits
        from src.data.loaders import load_stewart_limits
        from config.settings import get_settings
        settings = get_settings()
        limits_file = settings.get_stewart_limits_path(client)
        limits = load_stewart_limits(limits_file) if limits_file.exists() else None
        
        if not limits:
            return html.Div([
                dbc.Alert("Límites Stewart no disponibles", color="warning")
            ])
        
        # Get limits for this component
        machine = oil_report.get('machineName', '')
        component_normalized = oil_report.get('componentNameNormalized', oil_report.get('componentName', ''))
        
        if client not in limits or machine not in limits[client] or component_normalized not in limits[client][machine]:
            return html.Div([
                dbc.Alert(f"Límites no disponibles para {machine}/{component_normalized}", color="warning")
            ])
        
        comp_limits = limits[client][machine][component_normalized]
        
        # Create charts and tables for each group
        charts_and_tables = []
        
        for group_name in ordered_groups:
            essays = group_mapping[group_name]
            
            # Filter essays that exist in sample and have limits
            valid_essays = [e for e in essays if e in oil_report.index and pd.notna(oil_report[e]) and e in comp_limits]
            
            if not valid_essays:
                continue
            
            # Prepare data for radar chart and table
            normalized_values = []
            actual_values = []
            table_data = []
            
            for essay in valid_essays:
                value = float(oil_report[essay])
                actual_values.append(value)
                
                normal = comp_limits[essay].get('threshold_normal', 0)
                alert = comp_limits[essay].get('threshold_alert', 0)
                critic = comp_limits[essay].get('threshold_critic', 0)
                
                # Normalize value for radar chart (0-100 scale)
                if value >= critic:
                    norm_value = 100
                elif value >= alert:
                    norm_value = 70 + (value - alert) / max(critic - alert, 1) * 30
                elif value >= normal:
                    norm_value = 50 + (value - normal) / max(alert - normal, 1) * 20
                else:
                    norm_value = (value / max(normal, 1)) * 50
                
                normalized_values.append(min(norm_value, 100))
                
                # Determine status
                if value >= critic:
                    status = 'Crítico'
                    color = '#dc3545'
                elif value >= alert:
                    status = 'Condenatorio'
                    color = '#fd7e14'
                elif value >= normal:
                    status = 'Marginal'
                    color = '#ffc107'
                else:
                    status = 'Normal'
                    color = '#28a745'
                
                table_data.append({
                    'essay': essay,
                    'value': round(value, 2),
                    'status': status,
                    'normal': round(normal, 2),
                    'alert': round(alert, 2),
                    'critic': round(critic, 2),
                    '_color': color
                })
            
            # Sort table by status severity
            status_order = {'Crítico': 0, 'Condenatorio': 1, 'Marginal': 2, 'Normal': 3}
            table_data.sort(key=lambda x: (status_order.get(x['status'], 4), x['essay']))
            
            # Create radar chart
            fig = go.Figure()
            
            # Add threshold rings
            fig.add_trace(go.Scatterpolar(
                r=[90] * len(valid_essays),
                theta=valid_essays,
                name='Crítico',
                line=dict(color='red', dash='dash', width=2),
                fill=None,
                mode='lines'
            ))
            
            fig.add_trace(go.Scatterpolar(
                r=[70] * len(valid_essays),
                theta=valid_essays,
                name='Condenatorio',
                line=dict(color='orange', dash='dash', width=2),
                fill=None,
                mode='lines'
            ))
            
            fig.add_trace(go.Scatterpolar(
                r=[50] * len(valid_essays),
                theta=valid_essays,
                name='Marginal',
                line=dict(color='#ffc107', dash='dash', width=2),
                fill=None,
                mode='lines'
            ))
            
            # Determine fill color based on report status
            status_color = {
                'Anormal': '#dc3545',
                'Condenatorio': '#fd7e14',
                'Critico': '#dc3545',
                'Normal': '#28a745'
            }.get(oil_report.get('report_status', 'Normal'), '#17a2b8')
            
            # Add actual values
            fig.add_trace(go.Scatterpolar(
                r=normalized_values,
                theta=valid_essays,
                name='Valores Actuales',
                line=dict(color=status_color, width=3),
                fill='toself',
                fillcolor=status_color,
                opacity=0.4,
                hovertemplate='<b>%{theta}</b><br>Valor Real: %{customdata}<br>Normalizado: %{r:.1f}<extra></extra>',
                customdata=actual_values
            ))
            
            fig.update_layout(
                polar=dict(
                    radialaxis=dict(
                        visible=True,
                        range=[0, 100],
                        tickvals=[0, 25, 50, 75, 100],
                        ticktext=['0', '25', '50', '75', '100']
                    ),
                    angularaxis=dict(
                        rotation=90,
                        direction='clockwise'
                    )
                ),
                title=dict(
                    text=f"{group_name}",
                    x=0.5,
                    xanchor='center',
                    font=dict(size=14, weight='bold')
                ),
                showlegend=True,
                legend=dict(
                    orientation='h',
                    yanchor='bottom',
                    y=-0.2,
                    xanchor='center',
                    x=0.5,
                    font=dict(size=10)
                ),
                height=400,
                margin=dict(l=50, r=50, t=50, b=80)
            )
            
            # Create table
            group_table = dash_table.DataTable(
                columns=[
                    {'name': 'Ensayo', 'id': 'essay'},
                    {'name': 'Valor', 'id': 'value', 'type': 'numeric'},
                    {'name': 'Estado', 'id': 'status'},
                    {'name': 'Límite Normal', 'id': 'normal', 'type': 'numeric'},
                    {'name': 'Límite Alerta', 'id': 'alert', 'type': 'numeric'},
                    {'name': 'Límite Crítico', 'id': 'critic', 'type': 'numeric'}
                ],
                data=table_data,
                style_table={'overflowX': 'auto'},
                style_cell={
                    'textAlign': 'left',
                    'padding': '8px',
                    'fontSize': '13px',
                    'fontFamily': 'Arial'
                },
                style_header={
                    'backgroundColor': '#2c3e50',
                    'color': 'white',
                    'fontWeight': 'bold',
                    'textAlign': 'center'
                },
                style_data_conditional=[
                    {
                        'if': {'filter_query': '{status} = "Crítico"'},
                        'backgroundColor': '#f8d7da',
                        'color': '#721c24',
                        'fontWeight': 'bold'
                    },
                    {
                        'if': {'filter_query': '{status} = "Condenatorio"'},
                        'backgroundColor': '#fff3cd',
                        'color': '#856404'
                    },
                    {
                        'if': {'filter_query': '{status} = "Marginal"'},
                        'backgroundColor': '#fff8e1',
                        'color': '#856404'
                    },
                    {
                        'if': {'filter_query': '{status} = "Normal"'},
                        'backgroundColor': '#d4edda',
                        'color': '#155724'
                    }
                ]
            )
            
            # Add chart and table for this group
            charts_and_tables.append(
                dbc.Row([
                    dbc.Col([
                        dbc.Card([
                            dbc.CardBody([
                                dcc.Graph(
                                    figure=fig,
                                    config={'displayModeBar': False}
                                )
                            ])
                        ], className="shadow-sm mb-3")
                    ], md=6),
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.H6(f"Detalle - {group_name}", className="mb-0")
                            ]),
                            dbc.CardBody([
                                group_table
                            ])
                        ], className="shadow-sm mb-3")
                    ], md=6)
                ], className="mb-4")
            )
        
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
        
        return html.Div([
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-flask me-2"),
                        "Evidencia de Tribología"
                    ], className="text-warning mb-2"),
                    dbc.Badge(
                        f"Estado: {report_status}",
                        color=status_color,
                        className="mb-3",
                        style={'fontSize': '1rem'}
                    )
                ])
            ]),
            html.Div(charts_and_tables)
        ], className="mb-5")
    
    except Exception as e:
        logger.error(f"Error creating oil evidence: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return html.Div([
            dbc.Alert(f"Error al cargar evidencia de tribología: {str(e)}", color="danger")
        ])


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
        # Get maintenance week
        maintenance_week = alert_row.get('Semana_Resumen_Mantencion')
        
        if pd.isna(maintenance_week):
            return html.Div([
                dbc.Alert("No hay referencia de semana de mantenimiento", color="info")
            ])
        
        # Load maintenance data
        maintenance_df = load_maintenance_week(client, maintenance_week)
        
        if maintenance_df.empty:
            return html.Div([
                dbc.Alert(f"No hay datos de mantenimiento para semana {maintenance_week}", color="warning")
            ])
        
        # Filter for this unit
        unit_maintenance = maintenance_df[
            maintenance_df['UnitId'] == alert_row['UnitId']
        ]
        
        if unit_maintenance.empty:
            return html.Div([
                dbc.Alert(f"No hay datos de mantenimiento para unidad {alert_row['UnitId']}", color="warning")
            ])
        
        unit_maintenance = unit_maintenance.iloc[0]
        
        # Create maintenance display
        maintenance_card = create_maintenance_display(
            maintenance_data=unit_maintenance,
            alert_system=alert_row['sistema']
        )
        
        # Build section
        return html.Div([
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-tools me-2"),
                        "Evidencia de Mantenimiento"
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
            dbc.Alert(f"Error al cargar evidencia de mantenimiento: {str(e)}", color="danger")
        ])
