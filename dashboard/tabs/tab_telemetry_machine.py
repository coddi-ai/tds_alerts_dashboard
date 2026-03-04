"""
Telemetry Machine Detail Tab Layout.

Displays component-level analysis for a selected unit:
machine header, component status table, and AI recommendation.
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_machine_header_card(
    unit_id: str,
    overall_status: str,
    priority_score: float,
    machine_score: float,
    evaluation_week: int,
    evaluation_year: int
) -> dbc.Card:
    """
    Create machine summary header card.
    
    Args:
        unit_id: Unit identifier
        overall_status: Machine overall status
        priority_score: Machine priority score
        machine_score: Machine score
        evaluation_week: Evaluation week number
        evaluation_year: Evaluation year
    
    Returns:
        Bootstrap card with machine summary
    """
    status_colors = {
        'Normal': 'success',
        'Alerta': 'warning',
        'Anormal': 'danger',
        'InsufficientData': 'secondary'
    }
    badge_color = status_colors.get(overall_status, 'secondary')

    return dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-truck me-2"),
                        f"Unidad: {unit_id}"
                    ], className="mb-0"),
                ], width='auto'),
                dbc.Col([
                    dbc.Badge(
                        overall_status,
                        color=badge_color,
                        pill=True,
                        className="fs-6 px-3 py-2"
                    )
                ], width='auto'),
                dbc.Col([
                    html.Span([
                        html.Strong("Prioridad: "),
                        f"{priority_score:.2f}"
                    ], className="me-4"),
                    html.Span([
                        html.Strong("Score: "),
                        f"{machine_score:.3f}"
                    ], className="me-4"),
                    html.Span([
                        html.Strong("Semana: "),
                        f"{evaluation_week:02d}/{evaluation_year}"
                    ])
                ], className="text-muted")
            ], align="center")
        ])
    ], className="shadow-sm mb-4")


def create_ai_recommendation_card(recommendation_text: str = None) -> dbc.Card:
    """
    Create AI recommendation card for a machine.
    
    Args:
        recommendation_text: AI recommendation text, or None if not available
    
    Returns:
        Bootstrap card with AI recommendation
    """
    if recommendation_text:
        content = html.P(recommendation_text, className="mb-0", style={"whiteSpace": "pre-wrap"})
        card_color = "light"
        icon_class = "fas fa-robot me-2 text-primary"
    else:
        content = html.P(
            "No hay recomendación IA disponible aún - ¡próximamente!",
            className="mb-0 text-muted fst-italic"
        )
        card_color = "light"
        icon_class = "fas fa-robot me-2 text-secondary"

    return dbc.Card([
        dbc.CardHeader([
            html.H5([
                html.I(className=icon_class),
                "Recomendación IA"
            ], className="mb-0")
        ]),
        dbc.CardBody([content], style={"minHeight": "200px"})
    ], className="shadow-sm", color=card_color)


def create_machine_detail_inline(
    header_card,
    component_table_data: list,
    ai_recommendation_card,
    unit_id: str = None
) -> html.Div:
    """
    Create inline machine detail content (for embedding in fleet view).
    
    Args:
        header_card: Machine header card component
        component_table_data: Component table data as list of dicts
        ai_recommendation_card: AI recommendation card component
        unit_id: Unit identifier for navigation
    
    Returns:
        Dash HTML Div with machine detail
    """
    return html.Div([
        html.Hr(className="my-4"),

        # Machine Header
        header_card,

        # Component Table + AI Recommendation
        dbc.Row([
            # Component Status Table
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-microchip me-2"),
                            "Estado de Componentes"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id='telemetry-component-status-table',
                            columns=[
                                {'name': 'Componente', 'id': 'Componente'},
                                {'name': 'Estado', 'id': 'Estado'},
                                {'name': 'Score', 'id': 'Score', 'type': 'numeric'},
                                {'name': 'Señales', 'id': 'Señales', 'type': 'numeric'},
                                {'name': 'Cobertura', 'id': 'Cobertura'},
                            ],
                            data=component_table_data,
                            sort_action='native',
                            filter_action='native',
                            row_selectable='single',
                            selected_rows=[],
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
                            ]
                        )
                    ])
                ], className="shadow-sm")
            ], lg=7),

            # AI Recommendation
            dbc.Col([
                ai_recommendation_card
            ], lg=5)
        ]),

        # Navigate to Component Analysis button
        dbc.Row([
            dbc.Col([
                dbc.Button(
                    [
                        html.I(className="fas fa-search-plus me-2"),
                        "Ir a Análisis de Componentes"
                    ],
                    id='telemetry-nav-to-component',
                    color='primary',
                    className='mt-3',
                    size='lg'
                ),
                # Hidden store with unit_id (read by callback as State)
                dcc.Store(
                    id='telemetry-nav-unit-store',
                    data=unit_id
                )
            ], className="text-center")
        ])
    ])


def create_telemetry_machine_layout() -> html.Div:
    """
    Create machine detail tab layout.
    
    Returns:
        Dash HTML Div with machine detail components
    """
    logger.info("Creating Telemetry Machine Detail layout")

    return html.Div([
        # Machine Selector
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Label("Seleccionar Unidad:", className="fw-bold mb-1"),
                                dcc.Dropdown(
                                    id='telemetry-machine-selector',
                                    placeholder="Seleccione una unidad...",
                                    clearable=False,
                                    className="mb-0"
                                )
                            ], md=6),
                        ])
                    ])
                ], className="shadow-sm mb-4")
            ])
        ]),

        # Machine Header (dynamic)
        html.Div(id='telemetry-machine-header'),

        # Component Table and Radar Chart
        dbc.Row([
            # Component Status Table
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-microchip me-2"),
                            "Estado de Componentes"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            dash_table.DataTable(
                                id='telemetry-component-status-table',
                                columns=[
                                    {'name': 'Componente', 'id': 'Componente'},
                                    {'name': 'Estado', 'id': 'Estado'},
                                    {'name': 'Score', 'id': 'Score', 'type': 'numeric'},
                                    {'name': 'Señales', 'id': 'Señales', 'type': 'numeric'},
                                    {'name': 'Cobertura', 'id': 'Cobertura'},
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
            ], lg=7),

            # Radar Chart
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-spider me-2"),
                            "Radar de Componentes"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            dcc.Graph(
                                id='telemetry-component-radar-chart',
                                config={'displayModeBar': False}
                            ),
                            type='circle'
                        )
                    ])
                ], className="shadow-sm")
            ], lg=5)
        ])
    ])
