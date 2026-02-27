"""
Telemetry Machine Detail Tab Layout.

This tab provides component-level analysis for a specific unit with:
- Machine Selector: Dropdown to select unit
- Machine Info Header: Status summary
- Component Status Table: List of components with scores
- Component Radar Chart: Visual component health breakdown
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_telemetry_machine_layout():
    """
    Create layout for Telemetry Machine Detail tab.
    
    Returns:
        Dash component tree for machine detail
    """
    layout = dbc.Container([
        # Header
        dbc.Row([
            dbc.Col([
                html.H3("Machine Detail", className="mb-3"),
                html.P(
                    "Component-level analysis for a specific unit.",
                    className="text-muted"
                )
            ])
        ], className="mb-4"),
        
        # Machine Selector Section
        dbc.Row([
            dbc.Col([
                html.Label("Select Unit:", className="fw-bold"),
                dcc.Dropdown(
                    id="telemetry-machine-selector",
                    options=[],
                    value=None,
                    placeholder="Select a unit...",
                    clearable=False,
                    className="mb-3"
                )
            ], width=12, lg=6)
        ], className="mb-4"),
        
        # Machine Info Header
        dbc.Row([
            dbc.Col([
                dcc.Loading(
                    id="loading-telemetry-machine-header",
                    type="circle",
                    children=[
                        html.Div(id="telemetry-machine-header")
                    ]
                )
            ], width=12)
        ], className="mb-4"),
        
        # Component Status Table Section
        dbc.Row([
            dbc.Col([
                html.H5("Component Status", className="mb-3"),
                html.P(
                    "Click on a component row to view signal-level details.",
                    className="text-muted small"
                ),
                dcc.Loading(
                    id="loading-telemetry-component-table",
                    type="circle",
                    children=[
                        dash_table.DataTable(
                            id="telemetry-component-status-table",
                            columns=[
                                {"name": "Component", "id": "component"},
                                {"name": "Status", "id": "component_status"},
                                {"name": "Score", "id": "component_score"},
                                {"name": "# Signals", "id": "num_signals"},
                                {"name": "# Anormal", "id": "num_anormal"},
                                {"name": "# Alerta", "id": "num_alerta"},
                                {"name": "Coverage", "id": "coverage"}
                            ],
                            data=[],
                            sort_action="native",
                            filter_action="native",
                            row_selectable="single",
                            selected_rows=[],
                            page_size=10,
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
                                    'if': {'column_id': 'component_status', 'filter_query': '{component_status} eq "Normal"'},
                                    'backgroundColor': '#d4edda',
                                    'color': '#155724'
                                },
                                {
                                    'if': {'column_id': 'component_status', 'filter_query': '{component_status} eq "Alerta"'},
                                    'backgroundColor': '#fff3cd',
                                    'color': '#856404'
                                },
                                {
                                    'if': {'column_id': 'component_status', 'filter_query': '{component_status} eq "Anormal"'},
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
            ], width=12)
        ], className="mb-4"),
        
        # Component Radar Chart Section
        dbc.Row([
            dbc.Col([
                html.H5("Component Health Radar", className="mb-3"),
                dcc.Loading(
                    id="loading-telemetry-component-radar",
                    type="circle",
                    children=[
                        dcc.Graph(
                            id="telemetry-component-radar-chart",
                            config={'displayModeBar': True}
                        )
                    ]
                )
            ], width=12, lg=10)
        ], className="mb-4"),
        
        # Hidden div to store machine data
        html.Div(id="telemetry-machine-data-store", style={'display': 'none'}),
        
    ], fluid=True, className="p-4")
    
    return layout


def create_machine_header_card(unit_id: str, overall_status: str, priority_score: float, 
                                machine_score: float, evaluation_week: int, evaluation_year: int):
    """
    Create machine info header card.
    
    Args:
        unit_id: Unit identifier
        overall_status: Machine overall status
        priority_score: Priority score
        machine_score: Machine score
        evaluation_week: Evaluation week
        evaluation_year: Evaluation year
    
    Returns:
        Dash component for machine header
    """
    # Status color mapping
    status_colors = {
        'Normal': 'success',
        'Alerta': 'warning',
        'Anormal': 'danger'
    }
    
    status_color = status_colors.get(overall_status, 'secondary')
    
    card = dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H4(f"Unit: {unit_id}", className="mb-2"),
                    html.Div([
                        dbc.Badge(overall_status, color=status_color, className="me-2", pill=True),
                        html.Span(f"Week {evaluation_week:02d}/{evaluation_year}", className="text-muted")
                    ])
                ], width=12, lg=6),
                dbc.Col([
                    html.Div([
                        html.Strong("Priority Score: "),
                        html.Span(f"{priority_score:.2f}", className="text-primary fs-5")
                    ], className="mb-2"),
                    html.Div([
                        html.Strong("Machine Score: "),
                        html.Span(f"{machine_score:.3f}", className="text-secondary fs-5")
                    ])
                ], width=12, lg=6, className="text-lg-end")
            ])
        ])
    ], className="mb-3", color="light")
    
    return card
