"""
Telemetry Fleet Overview Tab Layout.

This tab provides a high-level fleet health snapshot with:
- KPI Cards: Total units, Normal %, Alerta %, Anormal %
- Fleet Status Table & Pie Chart: Sortable machine list and visual distribution
- Machine Detail: Component analysis for selected machine (bottom section)
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_telemetry_fleet_layout():
    """
    Create layout for Telemetry Fleet Overview tab.
    
    Returns:
        Dash component tree for fleet overview
    """
    layout = dbc.Container([
        # Header
        dbc.Row([
            dbc.Col([
                html.H3("Fleet Overview", className="mb-3"),
                html.P(
                    "High-level fleet health snapshot with machine status distribution.",
                    className="text-muted"
                )
            ])
        ], className="mb-4"),
        
        # KPI Cards Section
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-tachometer-alt me-2"),
                            "Fleet Health KPIs"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-telemetry-fleet-kpis",
                            type="circle",
                            children=[
                                dcc.Graph(
                                    id="telemetry-fleet-kpi-cards",
                                    config={'displayModeBar': False}
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm")
            ], width=12)
        ], className="mb-4"),
        
        # Fleet Status Table & Pie Chart Row
        dbc.Row([
            # Fleet Status Table Section
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-table me-2"),
                            "Fleet Status Table"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        html.P(
                            "Sortable machine list with component health summary.",
                            className="text-muted small"
                        ),
                        dcc.Loading(
                            id="loading-telemetry-fleet-table",
                            type="circle",
                            children=[
                                dash_table.DataTable(
                                    id="telemetry-fleet-status-table",
                                    columns=[
                                        {"name": "Unit ID", "id": "unit_id"},
                                        {"name": "Status", "id": "overall_status"},
                                        {"name": "Priority Score", "id": "priority_score"},
                                        {"name": "Machine Score", "id": "machine_score"},
                                        {"name": "Components (A/L/N)", "id": "components"},
                                        {"name": "Week", "id": "evaluation_week"},
                                        {"name": "Year", "id": "evaluation_year"}
                                    ],
                                    data=[],
                                    sort_action="native",
                                    filter_action="native",
                                    row_selectable=False,
                                    page_size=15,
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
                                            'if': {'column_id': 'overall_status', 'filter_query': '{overall_status} eq "Normal"'},
                                            'backgroundColor': '#d4edda',
                                            'color': '#155724'
                                        },
                                        {
                                            'if': {'column_id': 'overall_status', 'filter_query': '{overall_status} eq "Alerta"'},
                                            'backgroundColor': '#fff3cd',
                                            'color': '#856404'
                                        },
                                        {
                                            'if': {'column_id': 'overall_status', 'filter_query': '{overall_status} eq "Anormal"'},
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
            ], md=8),
            
            # Status Pie Chart Section
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-chart-pie me-2"),
                            "Status Distribution"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-telemetry-fleet-pie",
                            type="circle",
                            children=[
                                dcc.Graph(
                                    id="telemetry-fleet-status-pie",
                                    config={'displayModeBar': False}
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm")
            ], md=4)
        ], className="mb-4"),
        
        # Divider
        html.Hr(className="my-4"),
        
        # Machine Detail Section (Bottom)
        dbc.Row([
            dbc.Col([
                html.H4([
                    html.I(className="fas fa-cog me-2"),
                    "Machine Detail"
                ], className="mb-3"),
                html.P(
                    "Select a machine to view component-level health analysis.",
                    className="text-muted"
                )
            ])
        ], className="mb-3"),
        
        # Machine Selector
        dbc.Row([
            dbc.Col([
                html.Label("Select Machine:", className="fw-bold"),
                dcc.Dropdown(
                    id="telemetry-machine-selector",
                    options=[],
                    value=None,
                    placeholder="Select a machine...",
                    clearable=True,
                    className="mb-3"
                )
            ], width=12, lg=6)
        ], className="mb-4"),
        
        # Machine Header Card (Summary)
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
        
        # Component Table & Radar Chart Row
        dbc.Row([
            # Component Table
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-list me-2"),
                            "Component Status"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-telemetry-component-table",
                            type="circle",
                            children=[
                                dash_table.DataTable(
                                    id="telemetry-machine-component-table",
                                    columns=[
                                        {"name": "Component", "id": "component"},
                                        {"name": "Status", "id": "component_status"},
                                        {"name": "Score", "id": "component_score"},
                                        {"name": "Signals", "id": "num_signals"},
                                        {"name": "Anormal", "id": "num_anormal"},
                                        {"name": "Alerta", "id": "num_alerta"},
                                        {"name": "Coverage %", "id": "coverage"}
                                    ],
                                    data=[],
                                    sort_action="native",
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
                    ])
                ], className="shadow-sm")
            ], md=7),
            
            # Radar Chart
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-chart-area me-2"),
                            "Component Radar"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-telemetry-component-radar",
                            type="circle",
                            children=[
                                dcc.Graph(
                                    id="telemetry-machine-component-radar",
                                    config={'displayModeBar': False}
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm")
            ], md=5)
        ], className="mb-4"),
        
        # Hidden div to store fleet data
        html.Div(id="telemetry-fleet-data-store", style={'display': 'none'}),
        
    ], fluid=True, className="p-4")
    
    return layout


def create_machine_header_card(unit_id: str, overall_status: str, priority_score: float, 
                                machine_score: float, evaluation_week: int, evaluation_year: int,
                                anormal_count: int, alerta_count: int, normal_count: int):
    """
    Create machine summary header card.
    
    Args:
        unit_id: Machine unit identifier
        overall_status: Overall machine status
        priority_score: Priority score
        machine_score: Machine health score
        evaluation_week: Evaluation week number
        evaluation_year: Evaluation year
        anormal_count: Number of anormal components
        alerta_count: Number of alerta components
        normal_count: Number of normal components
    
    Returns:
        Dash component for machine header card
    """
    # Status badge color
    status_color_map = {
        'Normal': 'success',
        'Alerta': 'warning',
        'Anormal': 'danger'
    }
    badge_color = status_color_map.get(overall_status, 'secondary')
    
    card = dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-truck me-2"),
                        f"Unit {unit_id}"
                    ], className="mb-2"),
                    dbc.Badge(overall_status, color=badge_color, className="fs-6")
                ], width=12, lg=4),
                dbc.Col([
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Span(f"{priority_score:.2f}", className="fs-4 text-primary d-block"),
                                html.Small("Priority Score", className="text-muted")
                            ], className="text-center")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                html.Span(f"{machine_score:.2f}", className="fs-4 text-info d-block"),
                                html.Small("Machine Score", className="text-muted")
                            ], className="text-center")
                        ], width=6)
                    ])
                ], width=12, lg=4),
                dbc.Col([
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Span(str(anormal_count), className="fs-5 text-danger d-block"),
                                html.Small("Anormal", className="text-muted")
                            ], className="text-center")
                        ], width=4),
                        dbc.Col([
                            html.Div([
                                html.Span(str(alerta_count), className="fs-5 text-warning d-block"),
                                html.Small("Alerta", className="text-muted")
                            ], className="text-center")
                        ], width=4),
                        dbc.Col([
                            html.Div([
                                html.Span(str(normal_count), className="fs-5 text-success d-block"),
                                html.Small("Normal", className="text-muted")
                            ], className="text-center")
                        ], width=4)
                    ])
                ], width=12, lg=4)
            ]),
            html.Hr(className="my-2"),
            html.P([
                html.Strong("Evaluation: "),
                f"Week {evaluation_week:02d}/{evaluation_year}"
            ], className="text-muted small mb-0")
        ])
    ], className="shadow-sm border-primary", style={'borderLeft': '5px solid'})
    
    return card
