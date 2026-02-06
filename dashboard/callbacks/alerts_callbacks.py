"""
Callbacks for Alerts Dashboard.

Handles all interactivity for alerts general and detail views.
"""

import pandas as pd
from dash import callback, Input, Output, State, html, dcc, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from datetime import datetime, timedelta
import numpy as np

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
from dashboard.tabs.tab_alerts_general import create_summary_stats_display
from dashboard.tabs.tab_alerts_detail import (
    create_alert_detail_content,
    create_oil_status_display
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Configuration
M1 = 60  # Minutes before alert
M2 = 10  # Minutes after alert
MAPBOX_TOKEN = "pk.eyJ1IjoicGF0bzI2IiwiYSI6ImNscDdvc2FxNDF6b2sya3F2eHZ6bG1pdzgifQ.uW_fqM1_9beP_OTFvHm3Nw"


# ========================================
# GENERAL TAB CALLBACKS
# ========================================

@callback(
    [
        Output('alerts-unit-distribution-chart', 'figure'),
        Output('alerts-month-distribution-chart', 'figure'),
        Output('alerts-trigger-distribution-chart', 'figure'),
        Output('alerts-summary-stats', 'children'),
        Output('alerts-table-container', 'children')
    ],
    [Input('client-selector', 'value')]
)
def update_general_tab(client: str):
    """
    Update all components in the General Tab when client changes.
    
    Args:
        client: Selected client identifier
    
    Returns:
        Tuple of (unit_chart, month_chart, trigger_chart, stats, table)
    """
    if not client:
        raise PreventUpdate
    
    logger.info(f"Loading alerts general view for client: {client}")
    
    # Load alerts data
    alerts_df = load_alerts_data(client)
    
    if alerts_df.empty:
        logger.warning(f"No alerts data available for client: {client}")
        empty_fig = {'data': [], 'layout': {'title': 'No data available'}}
        empty_alert = dbc.Alert("No hay datos de alertas disponibles", color="warning")
        return empty_fig, empty_fig, empty_fig, empty_alert, empty_alert
    
    try:
        # Create charts
        unit_chart = create_alerts_per_unit_chart(alerts_df)
        month_chart = create_alerts_per_month_chart(alerts_df)
        trigger_chart = create_trigger_distribution_treemap(alerts_df)
        
        # Calculate summary statistics
        total_alerts = len(alerts_df)
        total_units = alerts_df['UnitId'].nunique()
        telemetry_pct = (alerts_df['has_telemetry'].sum() / total_alerts * 100) if total_alerts > 0 else 0
        oil_pct = (alerts_df['has_tribology'].sum() / total_alerts * 100) if total_alerts > 0 else 0
        
        stats = create_summary_stats_display(total_alerts, total_units, telemetry_pct, oil_pct)
        
        # Create table
        table = create_alerts_datatable(alerts_df)
        
        logger.info(f"General tab updated successfully with {total_alerts} alerts")
        return unit_chart, month_chart, trigger_chart, stats, table
    
    except Exception as e:
        logger.error(f"Error updating general tab: {e}")
        error_fig = {'data': [], 'layout': {'title': f'Error: {str(e)}'}}
        error_alert = dbc.Alert(f"Error al cargar datos: {str(e)}", color="danger")
        return error_fig, error_fig, error_fig, error_alert, error_alert


@callback(
    Output('alert-selector-dropdown', 'options'),
    [Input('client-selector', 'value')]
)
def update_alert_dropdown(client: str):
    """
    Populate alert selector dropdown with available alerts.
    
    Args:
        client: Selected client identifier
    
    Returns:
        List of dropdown options
    """
    if not client:
        raise PreventUpdate
    
    logger.info(f"Populating alert dropdown for client: {client}")
    
    alerts_df = load_alerts_data(client)
    
    if alerts_df.empty:
        return []
    
    try:
        # Create dropdown options
        options = []
        for _, row in alerts_df.sort_values('Timestamp', ascending=False).iterrows():
            label = f"{row['FusionID']} | {row['Timestamp'].strftime('%Y-%m-%d %H:%M')} | {row['UnitId']} | {row['componente']}"
            options.append({'label': label, 'value': row['FusionID']})
        
        logger.info(f"Dropdown populated with {len(options)} alerts")
        return options
    
    except Exception as e:
        logger.error(f"Error populating dropdown: {e}")
        return []


@callback(
    [
        Output('active-section-store', 'data', allow_duplicate=True),
        Output('alert-selector-dropdown', 'value', allow_duplicate=True)
    ],
    [
        Input('alerts-datatable', 'selected_rows')
    ],
    [
        State('alerts-datatable', 'data'),
        State('client-selector', 'value')
    ],
    prevent_initial_call=True
)
def navigate_to_detail_from_table(selected_rows, table_data, client):
    """
    Navigate to detail tab when a row is selected in the alerts table.
    
    Args:
        selected_rows: List of selected row indices
        table_data: Current table data
        client: Selected client
    
    Returns:
        Tuple of (new_section, alert_id)
    """
    if not selected_rows or not table_data or not client:
        raise PreventUpdate
    
    try:
        # Get the selected alert ID from the table
        selected_fusion_id = table_data[selected_rows[0]]['ID']
        logger.info(f"Table row selected, navigating to detail view for alert: {selected_fusion_id}")
        
        # Navigate to detail tab and set the dropdown value
        return 'monitoring-alerts-detail', selected_fusion_id
    
    except Exception as e:
        logger.error(f"Error navigating to detail from table: {e}")
        raise PreventUpdate


# ========================================
# DETAIL TAB CALLBACKS
# ========================================

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
        show_telemetry = trigger_type in ['Telemetria', 'Mixto']
        show_oil = trigger_type in ['Tribologia', 'Mixto']
        show_maintenance = pd.notna(alert_row.get('Semana_Resumen_Mantencion'))
        
        logger.info(f"Evidence sections - Telemetry: {show_telemetry}, Oil: {show_oil}, Maintenance: {show_maintenance}")
        
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
            
            # Sensor Trends
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-chart-line me-2"),
                                "Tendencias de Sensores"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Graph(
                                figure=sensor_trends_fig,
                                config={'displayModeBar': True}
                            )
                        ])
                    ], className="shadow-sm mb-4")
                ], md=12)
            ]),
            
            # GPS Map and Context KPIs
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-map-marked-alt me-2"),
                                "Ruta GPS"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Graph(
                                figure=gps_map_fig,
                                config={'displayModeBar': True}
                            )
                        ])
                    ], className="shadow-sm mb-4")
                ], md=8),
                
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-info-circle me-2"),
                                "Contexto"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            context_kpis
                        ])
                    ], className="shadow-sm mb-4")
                ], md=4)
            ])
        ], className="mb-5")
    
    except Exception as e:
        logger.error(f"Error creating telemetry evidence: {e}")
        return html.Div([
            dbc.Alert(f"Error al cargar evidencia de telemetría: {str(e)}", color="danger")
        ])


def create_oil_evidence_section(alert_row: pd.Series, client: str) -> html.Div:
    """
    Create oil evidence section with radar chart and report status.
    
    Args:
        alert_row: Selected alert data
        client: Client identifier
    
    Returns:
        HTML Div with oil evidence
    """
    logger.info("Creating oil evidence section")
    
    try:
        # Load oil data
        oil_classified = load_oil_classified(client)
        
        if oil_classified.empty or pd.isna(alert_row.get('TribologyID')):
            return html.Div([
                dbc.Alert("No hay datos de tribología disponibles", color="warning")
            ])
        
        # Filter for this sample
        oil_report = oil_classified[
            oil_classified['sampleNumber'] == alert_row['TribologyID']
        ]
        
        if oil_report.empty:
            return html.Div([
                dbc.Alert(f"Reporte no encontrado para muestra: {alert_row['TribologyID']}", color="warning")
            ])
        
        oil_report = oil_report.iloc[0]
        
        # Get essay columns
        essay_cols = [col for col in oil_classified.columns if 'ppm' in col.lower()]
        
        if not essay_cols:
            return html.Div([
                dbc.Alert("No hay datos de ensayos disponibles", color="warning")
            ])
        
        # Create radar chart
        radar_fig = create_oil_radar_chart(oil_report, essay_cols)
        
        # Create status display
        report_status = oil_report.get('report_status', 'N/A')
        breached_essays = oil_report.get('breached_essays', [])
        if isinstance(breached_essays, str):
            import json
            try:
                breached_essays = json.loads(breached_essays)
            except:
                breached_essays = []
        ai_recommendation = oil_report.get('ai_recommendation', '')
        
        status_display = create_oil_status_display(
            report_status=report_status,
            breached_essays=breached_essays,
            ai_recommendation=ai_recommendation
        )
        
        # Build section
        return html.Div([
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-flask me-2"),
                        "Evidencia de Tribología"
                    ], className="text-warning mb-3")
                ])
            ]),
            
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-vial me-2"),
                                "Análisis de Aceite"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Graph(
                                figure=radar_fig,
                                config={'displayModeBar': False}
                            )
                        ])
                    ], className="shadow-sm mb-4")
                ], md=8),
                
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-clipboard-check me-2"),
                                "Estado del Reporte"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            status_display
                        ])
                    ], className="shadow-sm mb-4")
                ], md=4)
            ])
        ], className="mb-5")
    
    except Exception as e:
        logger.error(f"Error creating oil evidence: {e}")
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
