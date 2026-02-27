"""
Telemetry Component Detail Tab Layout.

This tab provides signal-level evaluations with historical baselines:
- Component Selector: Dropdown to select component (with default selection)
- Component Info Header: Component status summary
- Signal Evaluation Table: Signals with scores, status, and data quality
- Weekly Distribution Boxplots: Historical signal distributions
- Daily Time Series: Detailed day-by-day signal evolution
- Baseline Limits: Threshold values for selected component
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_telemetry_component_layout():
    """
    Create layout for Telemetry Component Detail tab.
    
    Returns:
        Dash component tree for component detail
    """
    layout = dbc.Container([
        # Header
        dbc.Row([
            dbc.Col([
                html.H3("Component Detail", className="mb-3"),
                html.P(
                    "Signal-level evaluations with historical baselines and threshold limits.",
                    className="text-muted"
                )
            ])
        ], className="mb-4"),
        
        # Selectors Section
        dbc.Row([
            dbc.Col([
                html.Label("Select Unit:", className="fw-bold"),
                dcc.Dropdown(
                    id="telemetry-component-unit-selector",
                    options=[],
                    value=None,
                    placeholder="Select a unit...",
                    clearable=False,
                    className="mb-3"
                )
            ], width=12, lg=4),
            dbc.Col([
                html.Label("Select Component:", className="fw-bold"),
                dcc.Dropdown(
                    id="telemetry-component-selector",
                    options=[],
                    value=None,
                    placeholder="Select a component...",
                    clearable=False,
                    className="mb-3",
                    disabled=True
                )
            ], width=12, lg=4),
            dbc.Col([
                html.Label("Machine State Filter:", className="fw-bold"),
                dcc.Dropdown(
                    id="telemetry-estado-filter",
                    options=[
                        {'label': 'All States', 'value': 'all'},
                        {'label': 'Operacional', 'value': 'Operacional'},
                        {'label': 'Ralenti', 'value': 'Ralenti'},
                        {'label': 'Apagada', 'value': 'Apagada'}
                    ],
                    value='all',
                    clearable=False,
                    className="mb-3"
                )
            ], width=12, lg=4)
        ], className="mb-4"),
        
        # Component Info Header
        dbc.Row([
            dbc.Col([
                dcc.Loading(
                    id="loading-telemetry-component-header",
                    type="circle",
                    children=[
                        html.Div(id="telemetry-component-header")
                    ]
                )
            ], width=12)
        ], className="mb-4"),
        
        # Signal Evaluation Table Section
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-list-ul me-2"),
                            "Signal Evaluations"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        html.P(
                            "Signals evaluated with Severity-Weighted Percentile Window Scoring methodology.",
                            className="text-muted small"
                        ),
                        dcc.Loading(
                            id="loading-telemetry-signal-table",
                            type="circle",
                            children=[
                                dash_table.DataTable(
                                    id="telemetry-signal-evaluation-table",
                                    columns=[
                                        {"name": "Signal", "id": "signal"},
                                        {"name": "Status", "id": "signal_status"},
                                        {"name": "Score", "id": "score"},
                                        {"name": "Samples", "id": "samples"},
                                        {"name": "Anomaly %", "id": "anomaly_%"}
                                    ],
                                    data=[],
                                    sort_action="native",
                                    filter_action="native",
                                    row_selectable="single",
                                    selected_rows=[],
                                    page_size=12,
                                    style_table={'overflowX': 'auto'},
                                    style_cell={
                                        'textAlign': 'left',
                                        'padding': '10px',
                                        'fontFamily': 'Arial, sans-serif',
                                        'fontSize': '14px'
                                    },
                                    style_header={
                                        'backgroundColor': '#f8f9fa',
                                        'fontWeight': 'bold',
                                        'borderBottom': '2px solid #dee2e6'
                                    },
                                    style_data_conditional=[
                                        {
                                            'if': {'column_id': 'signal_status', 'filter_query': '{signal_status} eq "Normal"'},
                                            'backgroundColor': '#d4edda',
                                            'color': '#155724'
                                        },
                                        {
                                            'if': {'column_id': 'signal_status', 'filter_query': '{signal_status} eq "Alerta"'},
                                            'backgroundColor': '#fff3cd',
                                            'color': '#856404'
                                        },
                                        {
                                            'if': {'column_id': 'signal_status', 'filter_query': '{signal_status} eq "Anormal"'},
                                            'backgroundColor': '#f8d7da',
                                            'color': '#721c24'
                                        },
                                        {
                                            'if': {'row_index': 'odd'},
                                            'backgroundColor': '#f8f9fa'
                                        }
                                    ]
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm")
            ], width=12)
        ], className="mb-4"),
        
        # Weekly Boxplots Section
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-chart-bar me-2"),
                            "Weekly Signal Distributions"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        html.P(
                            "Horizontal boxplots showing signal distributions over the last 6 weeks with baseline thresholds (P5-P95).",
                            className="text-muted small"
                        ),
                        dcc.Loading(
                            id="loading-telemetry-weekly-boxplots",
                            type="circle",
                            children=[
                                dcc.Graph(
                                    id="telemetry-weekly-boxplots",
                                    config={'displayModeBar': True}
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm")
            ], width=12)
        ], className="mb-4"),
        
        # Daily Time Series Section (NEW)
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-chart-line me-2"),
                            "Daily Time Series"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        html.P(
                            "Day-by-day signal evolution over the last 4 weeks (select a signal from the table above).",
                            className="text-muted small"
                        ),
                        dcc.Loading(
                            id="loading-telemetry-daily-timeseries",
                            type="circle",
                            children=[
                                dcc.Graph(
                                    id="telemetry-daily-timeseries",
                                    config={'displayModeBar': True}
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm")
            ], width=12)
        ], className="mb-4"),
        
        # Divider
        html.Hr(className="my-4"),
        
        # Baseline Limits Section (Bottom - NEW)
        dbc.Row([
            dbc.Col([
                html.H4([
                    html.I(className="fas fa-sliders-h me-2"),
                    "Baseline Limits"
                ], className="mb-3"),
                html.P(
                    "Threshold percentiles for the selected component and machine state.",
                    className="text-muted"
                )
            ])
        ], className="mb-3"),
        
        # Limits Info Card
        dbc.Row([
            dbc.Col([
                dcc.Loading(
                    id="loading-telemetry-component-limits-info",
                    type="circle",
                    children=[
                        html.Div(id="telemetry-component-limits-info-card")
                    ]
                )
            ], width=12)
        ], className="mb-4"),
        
        # Baseline Thresholds Table
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-table me-2"),
                            "Component Thresholds"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        html.P([
                            html.Strong("P2/P98: "), "Extreme bounds (alarm thresholds) | ",
                            html.Strong("P5/P95: "), "Warning bounds (alert thresholds)"
                        ], className="text-muted small mb-3"),
                        dcc.Loading(
                            id="loading-telemetry-component-limits-table",
                            type="circle",
                            children=[
                                dash_table.DataTable(
                                    id="telemetry-component-baseline-table",
                                    columns=[
                                        {"name": "Signal", "id": "Signal"},
                                        {"name": "Estado", "id": "EstadoMaquina"},
                                        {"name": "P2", "id": "P2"},
                                        {"name": "P5", "id": "P5"},
                                        {"name": "P95", "id": "P95"},
                                        {"name": "P98", "id": "P98"}
                                    ],
                                    data=[],
                                    sort_action="native",
                                    filter_action="native",
                                    page_size=20,
                                    style_table={'overflowX': 'auto'},
                                    style_cell={
                                        'textAlign': 'left',
                                        'padding': '10px',
                                        'fontFamily': 'Arial, sans-serif',
                                        'fontSize': '14px'
                                    },
                                    style_header={
                                        'backgroundColor': '#f8f9fa',
                                        'fontWeight': 'bold',
                                        'borderBottom': '2px solid #dee2e6'
                                    },
                                    style_data_conditional=[
                                        {
                                            'if': {'row_index': 'odd'},
                                            'backgroundColor': '#f8f9fa'
                                        }
                                    ]
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm")
            ], width=12)
        ], className="mb-4"),
        
        # Hidden divs to store component data
        html.Div(id="telemetry-component-data-store", style={'display': 'none'}),
        html.Div(id="telemetry-signals-data-store", style={'display': 'none'}),
        
    ], fluid=True, className="p-4")
    
    return layout


def create_component_header_card(component: str, component_status: str, component_score: float,
                                  num_signals: int, num_anormal: int, num_alerta: int,
                                  coverage: float, unit_id: str):
    """
    Create component summary header card.
    
    Args:
        component: Component name
        component_status: Component status
        component_score: Component health score
        num_signals: Number of signals
        num_anormal: Number of anormal signals
        num_alerta: Number of alerta signals
        coverage: Signal coverage percentage
        unit_id: Unit identifier
    
    Returns:
        Dash component for component header card
    """
    # Status badge color
    status_color_map = {
        'Normal': 'success',
        'Alerta': 'warning',
        'Anormal': 'danger'
    }
    badge_color = status_color_map.get(component_status, 'secondary')
    
    card = dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-cogs me-2"),
                        component
                    ], className="mb-2"),
                    html.P([
                        html.Small("Unit: ", className="text-muted"),
                        html.Strong(unit_id)
                    ], className="mb-2"),
                    dbc.Badge(component_status, color=badge_color, className="fs-6")
                ], width=12, lg=4),
                dbc.Col([
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Span(f"{component_score:.3f}", className="fs-4 text-primary d-block"),
                                html.Small("Component Score", className="text-muted")
                            ], className="text-center")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                html.Span(f"{coverage:.1%}", className="fs-4 text-info d-block"),
                                html.Small("Coverage", className="text-muted")
                            ], className="text-center")
                        ], width=6)
                    ])
                ], width=12, lg=4),
                dbc.Col([
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Span(str(num_signals), className="fs-5 text-secondary d-block"),
                                html.Small("Signals", className="text-muted")
                            ], className="text-center")
                        ], width=4),
                        dbc.Col([
                            html.Div([
                                html.Span(str(num_anormal), className="fs-5 text-danger d-block"),
                                html.Small("Anormal", className="text-muted")
                            ], className="text-center")
                        ], width=4),
                        dbc.Col([
                            html.Div([
                                html.Span(str(num_alerta), className="fs-5 text-warning d-block"),
                                html.Small("Alerta", className="text-muted")
                            ], className="text-center")
                        ], width=4)
                    ])
                ], width=12, lg=4)
            ])
        ])
    ], className="shadow-sm border-info", style={'borderLeft': '5px solid'})
    
    return card


def create_component_header_card(unit_id: str, component: str, component_status: str, 
                                  component_score: float, num_signals: int, coverage: float):
    """
    Create component info header card.
    
    Args:
        unit_id: Unit identifier
        component: Component name
        component_status: Component status
        component_score: Component score
        num_signals: Number of signals
        coverage: Signal coverage percentage
    
    Returns:
        Dash component for component header
    """
    # Status color mapping
    status_colors = {
        'Normal': 'success',
        'Alerta': 'warning',
        'Anormal': 'danger'
    }
    
    status_color = status_colors.get(component_status, 'secondary')
    
    card = dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H4(f"Component: {component}", className="mb-2"),
                    html.Div([
                        dbc.Badge(component_status, color=status_color, className="me-2", pill=True),
                        html.Span(f"Unit: {unit_id}", className="text-muted")
                    ])
                ], width=12, lg=6),
                dbc.Col([
                    html.Div([
                        html.Strong("Component Score: "),
                        html.Span(f"{component_score:.3f}", className="text-primary fs-5")
                    ], className="mb-2"),
                    html.Div([
                        html.Strong("Signals: "),
                        html.Span(f"{num_signals}", className="text-secondary me-3"),
                        html.Strong("Coverage: "),
                        html.Span(f"{coverage:.1%}", className="text-secondary")
                    ])
                ], width=12, lg=6, className="text-lg-end")
            ])
        ])
    ], className="mb-3", color="light")
    
    return card
