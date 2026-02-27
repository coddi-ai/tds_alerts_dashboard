"""
Telemetry Limits Tab Layout.

This tab displays baseline thresholds and training data:
- Baseline Info Card: Training period and metadata
- Baseline Thresholds Table: P2, P5, P95, P98 percentiles per signal
- Unit Filter: Dropdown to filter by unit
- Export Options: Download baselines as CSV (future)
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_telemetry_limits_layout():
    """
    Create layout for Telemetry Limits tab.
    
    Returns:
        Dash component tree for limits display
    """
    layout = dbc.Container([
        # Header
        dbc.Row([
            dbc.Col([
                html.H3("Telemetry Limits", className="mb-3"),
                html.P(
                    "Baseline percentile thresholds for sensor anomaly detection.",
                    className="text-muted"
                )
            ])
        ], className="mb-4"),
        
        # Baseline Info Card
        dbc.Row([
            dbc.Col([
                dcc.Loading(
                    id="loading-telemetry-limits-info",
                    type="circle",
                    children=[
                        html.Div(id="telemetry-limits-info-card")
                    ]
                )
            ], width=12)
        ], className="mb-4"),
        
        # Filters Section
        dbc.Row([
            dbc.Col([
                html.Label("Filter by Unit:", className="fw-bold"),
                dcc.Dropdown(
                    id="telemetry-limits-unit-filter",
                    options=[{'label': 'All Units', 'value': 'all'}],
                    value='all',
                    clearable=False,
                    className="mb-3"
                )
            ], width=12, lg=4),
            dbc.Col([
                html.Label("Filter by Estado:", className="fw-bold"),
                dcc.Dropdown(
                    id="telemetry-limits-estado-filter",
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
        
        # Baseline Thresholds Table Section
        dbc.Row([
            dbc.Col([
                html.H5("Baseline Thresholds", className="mb-3"),
                html.P([
                    html.Strong("P2/P98: "), "Extreme bounds (alarm thresholds) | ",
                    html.Strong("P5/P95: "), "Warning bounds (alert thresholds)"
                ], className="text-muted small mb-3"),
                dcc.Loading(
                    id="loading-telemetry-limits-table",
                    type="circle",
                    children=[
                        dash_table.DataTable(
                            id="telemetry-baseline-thresholds-table",
                            columns=[
                                {"name": "Unit", "id": "Unit"},
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
                            page_size=25,
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
            ], width=12)
        ], className="mb-4"),
        
        # Hidden div to store baseline data
        html.Div(id="telemetry-baseline-data-store", style={'display': 'none'}),
        
    ], fluid=True, className="p-4")
    
    return layout


def create_baseline_info_card(baseline_filename: str, num_records: int, num_units: int, 
                               num_signals: int, num_states: int):
    """
    Create baseline info card with metadata.
    
    Args:
        baseline_filename: Name of baseline file
        num_records: Total records in baseline
        num_units: Number of unique units
        num_signals: Number of unique signals
        num_states: Number of unique estados
    
    Returns:
        Dash component for baseline info card
    """
    # Extract date from filename (baseline_YYYYMMDD.parquet)
    try:
        date_str = baseline_filename.replace('baseline_', '').replace('.parquet', '')
        from datetime import datetime
        baseline_date = datetime.strptime(date_str, '%Y%m%d').strftime('%B %d, %Y')
    except:
        baseline_date = "Unknown"
    
    card = dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.H5("Baseline Information", className="mb-3"),
                    html.Div([
                        html.Strong("Baseline Date: "),
                        html.Span(baseline_date, className="text-primary")
                    ], className="mb-2"),
                    html.Div([
                        html.Strong("File: "),
                        html.Span(baseline_filename, className="text-muted small")
                    ])
                ], width=12, lg=6),
                dbc.Col([
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Span(str(num_records), className="fs-4 text-primary d-block"),
                                html.Small("Total Records", className="text-muted")
                            ], className="text-center mb-2")
                        ], width=3),
                        dbc.Col([
                            html.Div([
                                html.Span(str(num_units), className="fs-4 text-success d-block"),
                                html.Small("Units", className="text-muted")
                            ], className="text-center mb-2")
                        ], width=3),
                        dbc.Col([
                            html.Div([
                                html.Span(str(num_signals), className="fs-4 text-info d-block"),
                                html.Small("Signals", className="text-muted")
                            ], className="text-center mb-2")
                        ], width=3),
                        dbc.Col([
                            html.Div([
                                html.Span(str(num_states), className="fs-4 text-secondary d-block"),
                                html.Small("Estados", className="text-muted")
                            ], className="text-center mb-2")
                        ], width=3)
                    ])
                ], width=12, lg=6)
            ])
        ])
    ], className="mb-3", color="light")
    
    return card
