"""
Alerts General Tab Layout.

Displays:
- Distribution of Alerts per Unit (horizontal bar chart)
- Distribution of Alerts per Month (vertical bar chart)
- Distribution of Alert Trigger (treemap)
- Alerts Table (interactive DataTable)
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create layout for Alerts General tab.
    
    Returns:
        Dash HTML Div with complete general tab layout
    """
    logger.info("Creating Alerts General Tab layout")
    
    layout = html.Div([
        # Summary stats at the top
        html.Div(id='alerts-summary-stats', className="mb-3"),
        
        # Top Row: 3 Analytics Charts (Unit | Month | Treemap)
        dbc.Row([
            # Distribution per Unit
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-truck me-2"),
                            "Distribución por Unidad"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-unit-chart",
                            type="circle",
                            children=[
                                dcc.Graph(
                                    id='alerts-unit-distribution-chart',
                                    config={'displayModeBar': False},
                                    clear_on_unhover=True
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm mb-4")
            ], md=4),
            
            # Distribution per Month
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-calendar-alt me-2"),
                            "Distribución por Mes"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-month-chart",
                            type="circle",
                            children=[
                                dcc.Graph(
                                    id='alerts-month-distribution-chart',
                                    config={'displayModeBar': False},
                                    clear_on_unhover=True
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm mb-4")
            ], md=4),
            
            # Trigger Distribution Treemap
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-signal me-2"),
                            "Distribución por Fuente"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-trigger-chart",
                            type="circle",
                            children=[
                                dcc.Graph(
                                    id='alerts-trigger-distribution-chart',
                                    config={'displayModeBar': False},
                                    clear_on_unhover=True
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm mb-4")
            ], md=4)
        ]),
        
        # Bottom Row: Table (8 cols) | System Distribution (4 cols)
        dbc.Row([
            # Alerts Table Section
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-table me-2"),
                            "Tabla de Alertas"
                        ], className="mb-0"),
                        html.Small(
                            " → Haga clic en cualquier fila para ver detalles completos",
                            className="text-muted ms-2"
                        )
                    ]),
                    dbc.CardBody([
                        # Table
                        dcc.Loading(
                            id="loading-alerts-table",
                            type="circle",
                            children=[
                                html.Div(id='alerts-table-container')
                            ]
                        )
                    ])
                ], className="shadow-sm")
            ], md=8),
            
            # System Distribution Pie Chart
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-cogs me-2"),
                            "Distribución por Sistema"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-system-chart",
                            type="circle",
                            children=[
                                dcc.Graph(
                                    id='alerts-system-distribution-chart',
                                    config={'displayModeBar': False},
                                    clear_on_unhover=True
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm")
            ], md=4)
        ])
    ], className="p-4")
    
    logger.info("Alerts General Tab layout created successfully")
    return layout


def create_summary_stats_display(total_alerts: int, 
                                 total_units: int, 
                                 telemetry_pct: float, 
                                 oil_pct: float) -> dbc.Row:
    """
    Create summary statistics display.
    
    Args:
        total_alerts: Total number of alerts
        total_units: Total number of unique units with alerts
        telemetry_pct: Percentage of alerts with telemetry evidence
        oil_pct: Percentage of alerts with oil evidence
    
    Returns:
        Bootstrap Row with stat cards
    """
    return dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Total Alertas", className="text-muted mb-2"),
                    html.H3(f"{total_alerts:,}", className="text-primary mb-0")
                ])
            ], className="text-center", outline=True, color="primary")
        ], md=3),
        
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Unidades Afectadas", className="text-muted mb-2"),
                    html.H3(f"{total_units}", className="text-info mb-0")
                ])
            ], className="text-center", outline=True, color="info")
        ], md=3),
        
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("% con Telemetría", className="text-muted mb-2"),
                    html.H3(f"{telemetry_pct:.1f}%", className="text-success mb-0")
                ])
            ], className="text-center", outline=True, color="success")
        ], md=3),
        
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("% con Tribología", className="text-muted mb-2"),
                    html.H3(f"{oil_pct:.1f}%", className="text-warning mb-0")
                ])
            ], className="text-center", outline=True, color="warning")
        ], md=3)
    ], className="g-3")
