"""
Telemetry Limits Tab Layout.

Displays baseline thresholds for sensor anomaly detection:
info card, filters, and baseline thresholds table.
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_baseline_info_card(
    baseline_filename: str,
    num_records: int,
    num_units: int,
    num_signals: int,
    num_states: int
) -> dbc.Card:
    """
    Create baseline metadata info card.
    
    Args:
        baseline_filename: Name of the baseline file loaded
        num_records: Total number of baseline records
        num_units: Number of unique units
        num_signals: Number of unique signals
        num_states: Number of unique machine states
    
    Returns:
        Bootstrap card with baseline metadata
    """
    return dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H5([
                        html.I(className="fas fa-database me-2"),
                        "Información de Baseline"
                    ], className="mb-0"),
                ], width='auto'),
                dbc.Col([
                    html.Span([
                        html.Strong("Archivo: "),
                        baseline_filename
                    ], className="me-4"),
                    html.Span([
                        html.Strong("Registros: "),
                        f"{num_records:,}"
                    ], className="me-4"),
                    html.Span([
                        html.Strong("Unidades: "),
                        f"{num_units}"
                    ], className="me-4"),
                    html.Span([
                        html.Strong("Señales: "),
                        f"{num_signals}"
                    ], className="me-4"),
                    html.Span([
                        html.Strong("Estados: "),
                        f"{num_states}"
                    ])
                ], className="text-muted")
            ], align="center")
        ])
    ], className="shadow-sm mb-4", color="light")


def create_telemetry_limits_layout() -> html.Div:
    """
    Create telemetry limits tab layout.
    
    Returns:
        Dash HTML Div with limits components
    """
    logger.info("Creating Telemetry Limits layout")

    return html.Div([
        # Header
        dbc.Row([
            dbc.Col([
                html.H3([
                    html.I(className="fas fa-sliders-h me-2"),
                    "Límites de Telemetría - Baselines"
                ], className="text-primary mb-1"),
                html.P(
                    "Umbrales percentiles (P2, P5, P95, P98) para detección de anomalías",
                    className="text-muted"
                )
            ])
        ], className="mb-4"),

        # Info Card (dynamic)
        html.Div(id='telemetry-limits-info-card'),

        # Filters Row
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Label("Filtrar por Unidad:", className="fw-bold mb-1"),
                                dcc.Dropdown(
                                    id='telemetry-limits-unit-filter',
                                    options=[{'label': 'Todas las Unidades', 'value': 'all'}],
                                    value='all',
                                    clearable=False
                                )
                            ], md=4),
                            dbc.Col([
                                html.Label("Filtrar por Estado:", className="fw-bold mb-1"),
                                dcc.Dropdown(
                                    id='telemetry-limits-estado-filter',
                                    options=[
                                        {'label': 'Todos', 'value': 'all'},
                                        {'label': 'Operacional', 'value': 'Operacional'},
                                        {'label': 'Ralenti', 'value': 'Ralenti'},
                                        {'label': 'Apagada', 'value': 'Apagada'}
                                    ],
                                    value='all',
                                    clearable=False
                                )
                            ], md=4),
                        ])
                    ])
                ], className="shadow-sm mb-4")
            ])
        ]),

        # Baseline Thresholds Table
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-table me-2"),
                            "Umbrales de Baseline"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            dash_table.DataTable(
                                id='telemetry-baseline-thresholds-table',
                                columns=[
                                    {'name': 'Unidad', 'id': 'Unidad'},
                                    {'name': 'Señal', 'id': 'Señal'},
                                    {'name': 'Estado', 'id': 'Estado'},
                                    {'name': 'P2', 'id': 'P2', 'type': 'numeric', 'format': {'specifier': '.4f'}},
                                    {'name': 'P5', 'id': 'P5', 'type': 'numeric', 'format': {'specifier': '.4f'}},
                                    {'name': 'P95', 'id': 'P95', 'type': 'numeric', 'format': {'specifier': '.4f'}},
                                    {'name': 'P98', 'id': 'P98', 'type': 'numeric', 'format': {'specifier': '.4f'}},
                                ],
                                data=[],
                                sort_action='native',
                                filter_action='native',
                                page_size=20,
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
                                }
                            ),
                            type='circle'
                        )
                    ])
                ], className="shadow-sm")
            ])
        ])
    ])
