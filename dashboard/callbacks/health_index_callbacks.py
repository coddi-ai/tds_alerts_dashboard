"""
Callbacks for Health Index Dashboard.

Handles all interactivity for health index visualizations.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import io

from dash import Input, Output, State, callback, html, dcc, no_update, callback_context
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from dashboard.components.health_index_charts import (
    create_health_index_timeline,
    create_health_index_heatmap,
    create_health_index_bar_chart,
    create_health_index_distribution,
    create_health_status_pie,
    create_health_gauge
)
from dashboard.components.health_index_tables import (
    create_health_index_detail_table,
    create_critical_units_table,
    create_system_summary_table,
    create_unit_detail_card
)
from src.utils.logger import get_logger
from config.settings import get_settings

logger = get_logger(__name__)


def get_health_index_data_path() -> Path:
    """
    Get the path to health index data file.
    
    Returns:
        Path to health_index.parquet file
    """
    settings = get_settings()
    # Use settings.data_root which works both in Docker and local
    data_path = settings.data_root / "telemetry" / "golden" / "cda" / "Health_Index" / "health_index.parquet"
    return data_path


def load_health_index_data() -> pd.DataFrame:
    """
    Load health index data from parquet file.
    
    Returns:
        DataFrame with health index data
    """
    try:
        data_path = get_health_index_data_path()
        logger.info(f"Loading Health Index data from: {data_path}")
        
        if not data_path.exists():
            logger.error(f"Health Index data file not found: {data_path}")
            return pd.DataFrame()
        
        df = pd.read_parquet(data_path)
        logger.info(f"Loaded {len(df)} health index records")
        return df
    except Exception as e:
        logger.error(f"Error loading health index data: {e}")
        return pd.DataFrame()


# ========================================
# DATA LOADING AND FILTERING
# ========================================

def register_health_index_callbacks(app):
    """
    Register all callbacks for Health Index tab.
    
    Args:
        app: Dash application instance
    """
    
    def apply_filters(df: pd.DataFrame, filters: Dict) -> pd.DataFrame:
        """Apply filters to dataframe."""
        if df.empty or not filters:
            return df
        
        df_filtered = df.copy()
        
        # Date range filter
        if filters.get('start_date'):
            df_filtered = df_filtered[df_filtered['start_time'] >= filters['start_date']]
        if filters.get('end_date'):
            df_filtered = df_filtered[df_filtered['end_time'] <= filters['end_date']]
        
        # Model filter
        if filters.get('model') and filters['model'] != 'all':
            df_filtered = df_filtered[df_filtered['truck_model'] == filters['model']]
        
        # Unit filter
        if filters.get('units') and 'all' not in filters['units']:
            df_filtered = df_filtered[df_filtered['Unit'].isin(filters['units'])]
        
        # HI range filter
        if filters.get('hi_range') and filters['hi_range'] != 'all':
            if filters['hi_range'] == 'critical':
                df_filtered = df_filtered[df_filtered['health_index'] < 0.5]
            elif filters['hi_range'] == 'warning':
                df_filtered = df_filtered[
                    (df_filtered['health_index'] >= 0.5) & 
                    (df_filtered['health_index'] < 0.8)
                ]
            elif filters['hi_range'] == 'healthy':
                df_filtered = df_filtered[df_filtered['health_index'] >= 0.8]
        
        return df_filtered
    
    @callback(
        [Output('health-index-data-store', 'data'),
         Output('health-index-unit-filter', 'options'),
         Output('health-index-date-range', 'start_date'),
         Output('health-index-date-range', 'end_date')],
        [Input('health-index-refresh-button', 'n_clicks'),
         Input('client-selector', 'value')],
        prevent_initial_call=False
    )
    def load_and_initialize_data(n_clicks, client):
        """Load data and initialize filter options."""
        logger.info(f"load_and_initialize_data called - n_clicks: {n_clicks}, client: {client}")
        
        # Check client access
        if not client or client.lower() != 'cda':
            logger.warning(f"Client {client} does not have access to Health Index")
            raise PreventUpdate
        
        # Load data
        logger.info("Loading Health Index data...")
        df = load_health_index_data()
        
        if df.empty:
            return {}, [], None, None
        
        # Get unique units for filter
        units = sorted(df['Unit'].unique().tolist())
        unit_options = [{'label': 'Todas', 'value': 'all'}] + [
            {'label': unit, 'value': unit} for unit in units
        ]
        
        # Get date range - default to last week of available data
        end_date = df['end_time'].max()
        # Calculate start date as 7 days before the end date
        start_date = end_date - timedelta(days=7)
        
        # Make sure start_date is not before the actual data start
        actual_start = df['start_time'].min()
        if start_date < actual_start:
            start_date = actual_start
        
        logger.info(f"Initialized Health Index data with date range: {start_date} to {end_date}")
        logger.info(f"Loaded {len(df):,} total records, {df['Unit'].nunique()} unique units")
        
        # Convert to dict for storage
        data_dict = df.to_dict('records')
        
        return data_dict, unit_options, start_date, end_date


    @callback(
        Output('health-index-filters-store', 'data'),
        [Input('health-index-date-range', 'start_date'),
         Input('health-index-date-range', 'end_date'),
         Input('health-index-model-filter', 'value'),
         Input('health-index-unit-filter', 'value'),
         Input('health-index-range-filter', 'value')],
        prevent_initial_call=False
    )
    def update_filters(start_date, end_date, model, units, hi_range):
        """Store current filter values."""
        return {
            'start_date': start_date,
            'end_date': end_date,
            'model': model,
            'units': units if isinstance(units, list) else [units],
            'hi_range': hi_range
        }

    # ========================================
    # KPI CARDS
    # ========================================

    @callback(
        Output('health-index-kpi-cards', 'children'),
        [Input('health-index-data-store', 'data'),
         Input('health-index-filters-store', 'data')],
        prevent_initial_call=False
    )
    def update_kpi_cards(data, filters):
        """Update KPI cards with current metrics."""
        if not data:
            return html.Div()  # Return empty div while loading
        
        df = pd.DataFrame(data)
        df_filtered = apply_filters(df, filters)
        
        if df_filtered.empty:
            return dbc.Alert("No hay datos para los filtros seleccionados", color="warning")
        
        # Calculate KPIs
        avg_hi = df_filtered['health_index'].mean()
        
        total_records = len(df_filtered)
        healthy_pct = (df_filtered['health_index'] >= 0.8).sum() / total_records * 100
        warning_pct = ((df_filtered['health_index'] >= 0.5) & 
                       (df_filtered['health_index'] < 0.8)).sum() / total_records * 100
        critical_pct = (df_filtered['health_index'] < 0.5).sum() / total_records * 100
        
        # Number of unique units
        n_units = df_filtered['Unit'].nunique()
        
        # Create KPI cards
        cards = dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-heartbeat fa-2x text-primary mb-2"),
                            html.H3(f"{avg_hi:.3f}", className="mb-0"),
                            html.P("HI Promedio Flota", className="text-muted mb-0 small")
                        ], className="text-center")
                    ])
                ], className="shadow-sm")
            ], md=2),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-check-circle fa-2x text-success mb-2"),
                            html.H3(f"{healthy_pct:.1f}%", className="mb-0"),
                            html.P("Equipos Saludables", className="text-muted mb-0 small"),
                            html.P(f"(HI ≥ 0.8)", className="text-muted mb-0", style={'fontSize': '0.7rem'})
                        ], className="text-center")
                    ])
                ], className="shadow-sm")
            ], md=2),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-exclamation-triangle fa-2x text-warning mb-2"),
                            html.H3(f"{warning_pct:.1f}%", className="mb-0"),
                            html.P("En Precaución", className="text-muted mb-0 small"),
                            html.P(f"(0.5 ≤ HI < 0.8)", className="text-muted mb-0", style={'fontSize': '0.7rem'})
                        ], className="text-center")
                    ])
                ], className="shadow-sm")
            ], md=2),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-times-circle fa-2x text-danger mb-2"),
                            html.H3(f"{critical_pct:.1f}%", className="mb-0"),
                            html.P("En Alerta", className="text-muted mb-0 small"),
                            html.P(f"(HI < 0.5)", className="text-muted mb-0", style={'fontSize': '0.7rem'})
                        ], className="text-center")
                    ])
                ], className="shadow-sm")
            ], md=2),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-truck fa-2x text-info mb-2"),
                            html.H3(f"{n_units}", className="mb-0"),
                            html.P("Unidades Monitoreadas", className="text-muted mb-0 small")
                        ], className="text-center")
                    ])
                ], className="shadow-sm")
            ], md=2),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-database fa-2x text-secondary mb-2"),
                            html.H3(f"{total_records:,}", className="mb-0"),
                            html.P("Registros Totales", className="text-muted mb-0 small")
                        ], className="text-center")
                    ])
                ], className="shadow-sm")
            ], md=2)
        ], className="mb-4")
        
        return cards


    # ========================================
    # CRITICAL ALERTS
    # ========================================

    @callback(
        Output('health-index-critical-alerts', 'children'),
        [Input('health-index-data-store', 'data'),
         Input('health-index-filters-store', 'data')],
        prevent_initial_call=False
    )
    def update_critical_alerts(data, filters):
        """Update critical alerts section."""
        if not data:
            return html.Div()  # Return empty div while loading
        
        df = pd.DataFrame(data)
        df_filtered = apply_filters(df, filters)
        
        if df_filtered.empty:
            return html.Div()
        
        # Only show if there are critical units
        critical_df = df_filtered[df_filtered['health_index'] < 0.5]
        if critical_df.empty:
            return html.Div()
        
        return dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-bell me-2"),
                            "Atención Prioritaria"
                        ], className="mb-0 text-danger")
                    ]),
                    dbc.CardBody([
                        create_critical_units_table(df_filtered, threshold=0.5)
                    ])
                ], className="mb-4 border-danger")
            ], width=12)
        ])


    # ========================================
    # TAB CONTENT
    # ========================================

    @callback(
        Output('health-index-tab-content', 'children'),
        [Input('health-index-system-tabs', 'value'),
         Input('health-index-data-store', 'data'),
         Input('health-index-filters-store', 'data')],
        prevent_initial_call=False
    )
    def update_tab_content(selected_tab, data, filters):
        """Update content based on selected tab."""
        if not data:
            return dbc.Alert([
                dbc.Spinner(size="sm", color="primary"),
                html.Span(" Cargando datos del Health Index...", className="ms-2")
            ], color="info", className="mt-4")
        
        df = pd.DataFrame(data)
        
        # Apply filters if they exist
        if filters:
            df_filtered = apply_filters(df, filters)
        else:
            df_filtered = df
        
        if df_filtered.empty:
            return dbc.Alert("No hay datos para los filtros seleccionados. Intente ajustar los filtros o haga clic en 'Actualizar'.", 
                            color="warning", className="mt-4")
        
        if selected_tab == 'all-systems':
            return create_all_systems_content(df_filtered)
        else:
            return create_system_specific_content(df_filtered, selected_tab)

    def create_all_systems_content(df: pd.DataFrame) -> html.Div:
        """Create content for all systems view."""
        return html.Div([
            # Timeline
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H6([
                                html.I(className="fas fa-chart-line me-2"),
                                "Evolución Temporal del Health Index"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Graph(
                                id='health-index-main-timeline',
                                figure=create_health_index_timeline(df),
                                config={'displayModeBar': True}
                            )
                        ])
                    ], className="shadow-sm")
                ], width=12)
            ], className="mb-4"),
            
            # Heatmap and Bar chart
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H6([
                                html.I(className="fas fa-th me-2"),
                                "Heatmap por Unidad y Sistema"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Graph(
                                id='health-index-main-heatmap',
                                figure=create_health_index_heatmap(df),
                                config={'displayModeBar': True}
                            )
                        ])
                    ], className="shadow-sm")
                ], md=6),
                
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H6([
                                html.I(className="fas fa-bar-chart me-2"),
                                "HI Actual por Unidad"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Graph(
                                id='health-index-main-bar',
                                figure=create_health_index_bar_chart(df),
                                config={'displayModeBar': True}
                            )
                        ])
                    ], className="shadow-sm")
                ], md=6)
            ], className="mb-4"),
            
            # Detail table
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H6([
                                html.I(className="fas fa-table me-2"),
                                "Tabla Detallada"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            create_health_index_detail_table(df)
                        ])
                    ], className="shadow-sm")
                ], width=12)
            ])
        ])

    def create_system_specific_content(df: pd.DataFrame, system: str) -> html.Div:
        """Create content for specific system."""
        # Filter by system
        df_system = df[df['component'] == system]
        
        if df_system.empty:
            return dbc.Alert(f"No hay datos para el sistema {system}", color="warning")
        
        return html.Div([
            # System KPIs
            dbc.Row([
                dbc.Col([
                    create_system_kpi_cards(df_system, system)
                ], width=12)
            ], className="mb-4"),
            
            # Charts
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H6([
                                html.I(className="fas fa-chart-area me-2"),
                                f"Evolución Temporal - {system}"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Graph(
                                figure=create_health_index_timeline(df_system, selected_system=system),
                                config={'displayModeBar': True}
                            )
                        ])
                    ], className="shadow-sm")
                ], width=12)
            ], className="mb-4"),
            
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H6([
                                html.I(className="fas fa-chart-bar me-2"),
                                "Distribución"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Graph(
                                figure=create_health_index_distribution(df_system, system),
                                config={'displayModeBar': True}
                            )
                        ])
                    ], className="shadow-sm")
                ], md=6),
                
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H6([
                                html.I(className="fas fa-chart-pie me-2"),
                                "Estado del Sistema"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Graph(
                                figure=create_health_status_pie(df_system, system),
                                config={'displayModeBar': True}
                            )
                        ])
                    ], className="shadow-sm")
                ], md=6)
            ], className="mb-4"),
            
            # System summary table
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H6([
                                html.I(className="fas fa-table me-2"),
                                f"Resumen por Unidad - {system}"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            create_system_summary_table(df_system, system)
                        ])
                    ], className="shadow-sm")
                ], width=12)
            ])
        ])

    def create_system_kpi_cards(df: pd.DataFrame, system: str) -> dbc.Row:
        """Create KPI cards for specific system."""
        avg_hi = df['health_index'].mean()
        min_hi = df['health_index'].min()
        max_hi = df['health_index'].max()
        
        healthy = (df['health_index'] >= 0.8).sum() / len(df) * 100
        
        return dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.H4(f"{avg_hi:.3f}", className="mb-1"),
                            html.P(f"HI Promedio - {system}", className="text-muted mb-0 small")
                        ], className="text-center")
                    ])
                ], className="shadow-sm")
            ], md=3),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.H4(f"{min_hi:.3f}", className="mb-1 text-danger"),
                            html.P("HI Mínimo", className="text-muted mb-0 small")
                        ], className="text-center")
                    ])
                ], className="shadow-sm")
            ], md=3),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.H4(f"{max_hi:.3f}", className="mb-1 text-success"),
                            html.P("HI Máximo", className="text-muted mb-0 small")
                        ], className="text-center")
                    ])
                ], className="shadow-sm")
            ], md=3),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.H4(f"{healthy:.1f}%", className="mb-1 text-primary"),
                            html.P("Registros Saludables", className="text-muted mb-0 small")
                        ], className="text-center")
                    ])
                ], className="shadow-sm")
            ], md=3)
        ])


    # ========================================
    # INDIVIDUAL CHART CALLBACKS (for general view)
    # ========================================

    @callback(
        Output('health-index-detail-table', 'children'),
        [Input('health-index-data-store', 'data'),
         Input('health-index-filters-store', 'data')],
        prevent_initial_call=False
    )
    def update_detail_table(data, filters):
        """Update detail table."""
        if not data:
            return html.Div("Cargando datos...", className="text-muted text-center p-4")
        
        df = pd.DataFrame(data)
        df_filtered = apply_filters(df, filters)
        
        if df_filtered.empty:
            return html.Div("No hay datos para los filtros seleccionados", 
                          className="text-muted text-center p-4")
        
        return create_health_index_detail_table(df_filtered)

    @callback(
        Output('health-index-status-pie', 'figure'),
        [Input('health-index-data-store', 'data'),
         Input('health-index-filters-store', 'data')],
        prevent_initial_call=False
    )
    def update_status_pie(data, filters):
        """Update status distribution pie chart."""
        if not data:
            from dashboard.components.health_index_charts import _empty_figure
            return _empty_figure("Cargando datos...")
        
        df = pd.DataFrame(data)
        df_filtered = apply_filters(df, filters)
        
        return create_health_status_pie(df_filtered)

    @callback(
        Output('health-index-timeline-chart', 'figure'),
        [Input('health-index-data-store', 'data'),
         Input('health-index-filters-store', 'data')],
        prevent_initial_call=False
    )
    def update_timeline_chart(data, filters):
        """Update timeline chart."""
        if not data:
            from dashboard.components.health_index_charts import _empty_figure
            return _empty_figure("Cargando datos...")
        
        df = pd.DataFrame(data)
        df_filtered = apply_filters(df, filters)
        
        return create_health_index_timeline(df_filtered)

    @callback(
        Output('health-index-heatmap', 'figure'),
        [Input('health-index-data-store', 'data'),
         Input('health-index-filters-store', 'data')],
        prevent_initial_call=False
    )
    def update_heatmap(data, filters):
        """Update heatmap."""
        if not data:
            from dashboard.components.health_index_charts import _empty_figure
            return _empty_figure("Cargando datos...")
        
        df = pd.DataFrame(data)
        df_filtered = apply_filters(df, filters)
        
        return create_health_index_heatmap(df_filtered)

    @callback(
        Output('health-index-bar-chart', 'figure'),
        [Input('health-index-data-store', 'data'),
         Input('health-index-filters-store', 'data')],
        prevent_initial_call=False
    )
    def update_bar_chart(data, filters):
        """Update bar chart."""
        if not data:
            from dashboard.components.health_index_charts import _empty_figure
            return _empty_figure("Cargando datos...")
        
        df = pd.DataFrame(data)
        df_filtered = apply_filters(df, filters)
        
        return create_health_index_bar_chart(df_filtered)

    #========================================
    # DOWNLOAD CSV
    # ========================================

    @callback(
        Output('health-index-download-data', 'data'),
        Input('health-index-download-button', 'n_clicks'),
        [State('health-index-data-store', 'data'),
         State('health-index-filters-store', 'data')],
        prevent_initial_call=True
    )
    def download_csv(n_clicks, data, filters):
        """Download filtered data as CSV."""
        if not data:
            raise PreventUpdate
        
        df = pd.DataFrame(data)
        df_filtered = apply_filters(df, filters)
        
        # Format for export
        df_export = df_filtered[['Unit', 'truck_model', 'component', 'health_index', 
                                 'start_time', 'end_time']].copy()
        df_export.columns = ['Unidad', 'Modelo', 'Sistema', 'Health Index', 
                             'Fecha Inicio', 'Fecha Fin']
        
        return dcc.send_data_frame(df_export.to_csv, 
                                   f"health_index_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                   index=False)

    # ========================================
    # CLIENT NOTICE
    # ========================================

    @callback(
        Output('health-index-client-notice', 'style'),
        Input('client-selector', 'value'),
        prevent_initial_call=False
    )
    def toggle_client_notice(client):
        """Show/hide client restriction notice."""
        if client and client.lower() == 'cda':
            return {'display': 'none'}
        return {'display': 'block'}
    
    logger.info("Health Index callbacks registered successfully")
