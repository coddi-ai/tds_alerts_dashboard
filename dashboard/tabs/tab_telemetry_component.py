"""
Telemetry Component Detail Tab Layout.

Displays signal-level evaluations for a selected component:
selectors, signal evaluation table, and weekly distribution boxplots.
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_component_header_card(
    unit_id: str,
    component: str,
    component_status: str,
    component_score: float,
    num_signals: int,
    coverage: float
) -> dbc.Card:
    """
    Create component summary header card.
    
    Args:
        unit_id: Unit identifier
        component: Component name
        component_status: Component status
        component_score: Component score
        num_signals: Number of signals evaluated
        coverage: Signal coverage percentage
    
    Returns:
        Bootstrap card with component summary
    """
    status_colors = {
        'Normal': 'success',
        'Alerta': 'warning',
        'Anormal': 'danger',
        'InsufficientData': 'secondary'
    }
    badge_color = status_colors.get(component_status, 'secondary')

    return dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-cogs me-2"),
                        f"{component}"
                    ], className="mb-0"),
                    html.Small(f"Unidad: {unit_id}", className="text-muted")
                ], width='auto'),
                dbc.Col([
                    dbc.Badge(
                        component_status,
                        color=badge_color,
                        pill=True,
                        className="fs-6 px-3 py-2"
                    )
                ], width='auto'),
                dbc.Col([
                    html.Span([
                        html.Strong("Score: "),
                        f"{component_score:.3f}"
                    ], className="me-4"),
                    html.Span([
                        html.Strong("Señales: "),
                        f"{num_signals}"
                    ], className="me-4"),
                    html.Span([
                        html.Strong("Cobertura: "),
                        f"{coverage:.1%}" if isinstance(coverage, (int, float)) else str(coverage)
                    ])
                ], className="text-muted")
            ], align="center")
        ])
    ], className="shadow-sm mb-4")


def create_telemetry_component_layout() -> html.Div:
    """
    Create component detail tab layout.
    
    Returns:
        Dash HTML Div with component detail components
    """
    logger.info("Creating Telemetry Component Detail layout")

    return html.Div([
        # Selectors Row
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            # Unit Selector
                            dbc.Col([
                                html.Label("Unidad:", className="fw-bold mb-1"),
                                dcc.Dropdown(
                                    id='telemetry-component-unit-selector',
                                    placeholder="Seleccione unidad...",
                                    clearable=False
                                )
                            ], md=3),

                            # Component Selector
                            dbc.Col([
                                html.Label("Componente:", className="fw-bold mb-1"),
                                dcc.Dropdown(
                                    id='telemetry-component-selector',
                                    placeholder="Seleccione componente...",
                                    clearable=False,
                                    disabled=True
                                )
                            ], md=4),
                        ])
                    ])
                ], className="shadow-sm mb-4")
            ])
        ]),

        # Component Header (dynamic)
        html.Div(id='telemetry-component-header'),

        # Signal Evaluation Table
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-wave-square me-2"),
                            "Evaluación de Señales"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            dash_table.DataTable(
                                id='telemetry-signal-evaluation-table',
                                columns=[
                                    {'name': 'Señal', 'id': 'signal'},
                                    {'name': 'Estado', 'id': 'signal_status'},
                                    {'name': 'Score', 'id': 'score', 'type': 'numeric'},
                                    {'name': 'Muestras', 'id': 'samples', 'type': 'numeric'},
                                    {'name': 'Anomalía %', 'id': 'anomaly_%', 'type': 'numeric'},
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
                                        'if': {'filter_query': '{signal_status} = "Anormal"'},
                                        'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                                        'color': '#dc3545',
                                        'fontWeight': 'bold'
                                    },
                                    {
                                        'if': {'filter_query': '{signal_status} = "Alerta"'},
                                        'backgroundColor': 'rgba(255, 193, 7, 0.1)',
                                        'color': '#856404',
                                        'fontWeight': 'bold'
                                    },
                                    {
                                        'if': {'filter_query': '{signal_status} = "Normal"'},
                                        'backgroundColor': 'rgba(40, 167, 69, 0.05)',
                                        'color': '#28a745'
                                    }
                                ]
                            ),
                            type='circle'
                        )
                    ])
                ], className="shadow-sm mb-4")
            ])
        ]),

        # Weekly Boxplots
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-chart-bar me-2"),
                            "Distribución Semanal de Señales"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            dcc.Graph(
                                id='telemetry-weekly-boxplots',
                                config={'displayModeBar': True, 'displaylogo': False}
                            ),
                            type='circle'
                        )
                    ])
                ], className="shadow-sm")
            ])
        ]),

        # Daily Time Series Section
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-chart-line me-2"),
                            "Serie Temporal Diaria"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        # Signal selector (single)
                        dbc.Row([
                            dbc.Col([
                                html.Label("Seleccionar Señal:", className="fw-bold mb-1"),
                                dcc.Dropdown(
                                    id='telemetry-daily-signal-selector',
                                    placeholder="Seleccione una señal para visualizar...",
                                    clearable=False,
                                    disabled=True
                                )
                            ], md=6),
                        ], className="mb-3"),
                        # Daily timeseries chart
                        dcc.Loading(
                            dcc.Graph(
                                id='telemetry-daily-timeseries',
                                config={'displayModeBar': True, 'displaylogo': False},
                                style={'display': 'none'}
                            ),
                            type='circle'
                        )
                    ])
                ], className="shadow-sm mt-4")
            ])
        ])
    ])
