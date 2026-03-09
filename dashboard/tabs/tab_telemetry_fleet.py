"""
Telemetry Fleet Overview Tab Layout.

Displays fleet-level health KPIs, machine status table,
and status distribution pie chart.
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_telemetry_fleet_layout() -> html.Div:
    """
    Create fleet overview tab layout.
    
    Returns:
        Dash HTML Div with fleet overview components
    """
    logger.info("Creating Telemetry Fleet Overview layout")

    return html.Div([
        # KPI Cards Row
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dcc.Loading(
                            dcc.Graph(
                                id='telemetry-fleet-kpi-cards',
                                config={'displayModeBar': False},
                                style={'height': '200px'}
                            ),
                            type='circle'
                        )
                    ])
                ], className="shadow-sm mb-4")
            ])
        ]),

        # Table and Pie Chart Row
        dbc.Row([
            # Fleet Status Table
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-table me-2"),
                            "Estado de Flota"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            dash_table.DataTable(
                                id='telemetry-fleet-status-table',
                                columns=[
                                    {'name': 'Unidad', 'id': 'Unidad'},
                                    {'name': 'Estado', 'id': 'Estado'},
                                    {'name': 'Prioridad', 'id': 'Prioridad', 'type': 'numeric'},
                                    {'name': 'Score', 'id': 'Score', 'type': 'numeric'},
                                    {'name': 'Componentes (A/L/N)', 'id': 'Componentes (A/L/N)'},
                                    {'name': 'Semana', 'id': 'Semana', 'type': 'numeric'},
                                    {'name': 'Año', 'id': 'Año', 'type': 'numeric'},
                                ],
                                data=[],
                                sort_action='native',
                                filter_action='native',
                                page_size=15,
                                style_table={'overflowX': 'auto'},
                                style_header={
                                    'backgroundColor': '#f8f9fa',
                                    'fontWeight': 'bold',
                                    'textAlign': 'center'
                                },
                                style_cell={
                                    'textAlign': 'center',
                                    'padding': '8px',
                                    'fontSize': '13px'
                                },
                                style_data_conditional=[
                                    {
                                        'if': {'filter_query': '{Estado} = "Anormal"'},
                                        'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                                        'color': '#dc3545',
                                        'fontWeight': 'bold'
                                    },
                                    {
                                        'if': {'filter_query': '{Estado} = "Alerta"'},
                                        'backgroundColor': 'rgba(255, 193, 7, 0.1)',
                                        'color': '#856404',
                                        'fontWeight': 'bold'
                                    },
                                    {
                                        'if': {'filter_query': '{Estado} = "Normal"'},
                                        'backgroundColor': 'rgba(40, 167, 69, 0.05)',
                                        'color': '#28a745'
                                    }
                                ],
                                row_selectable='single',
                                selected_rows=[]
                            ),
                            type='circle'
                        )
                    ])
                ], className="shadow-sm")
            ], lg=8),

            # Status Pie Chart
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-chart-pie me-2"),
                            "Distribución de Estado"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            dcc.Graph(
                                id='telemetry-fleet-status-pie',
                                config={'displayModeBar': False}
                            ),
                            type='circle'
                        )
                    ])
                ], className="shadow-sm")
            ], lg=4)
        ]),

        # Machine Detail (appears inline below when a row is selected)
        html.Div(id='telemetry-machine-detail-container', className="mt-4")
    ])
