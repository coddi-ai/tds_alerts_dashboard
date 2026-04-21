"""
Machines Overview tab for Multi-Technical-Alerts dashboard.

Redesigned following OIL-M-01 through OIL-M-06 requirements:
- Condition-first fleet summary with interactive donut
- User-facing diagnostic table columns
- Persistent master-detail flow
- Component evidence focused on condition
- Quick navigation relocated to top
- Stacked bar chart for component distribution
"""

from dash import dcc, html
import dash_bootstrap_components as dbc


def create_machines_tab() -> dbc.Container:
    """
    Create Tab: Machines Overview (Oil).
    
    Redesigned layout with:
    1. Interactive fleet status donut + priority table (OIL-M-01, OIL-M-02)
    2. Quick navigation to report detail (OIL-M-05)
    3. Persistent machine selection with component detail (OIL-M-03, OIL-M-04)
    4. Component status stacked bar chart (OIL-M-06)
    
    Returns:
        Bootstrap container with tab layout
    """
    return dbc.Container([
        html.H3("Machines Overview", className="mt-4 mb-3"),
        html.Hr(),
        
        # ========================================
        # SECTION 1: Fleet Status Summary (OIL-M-01)
        # ========================================
        html.H4("📊 Fleet Status Summary", className="mt-4 mb-3"),
        html.P("Click a segment in the donut chart to filter the priority table by status.", className="text-muted"),
        
        dbc.Row([
            # Left: Status Donut (interactive)
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Machine Status Distribution", className="fw-bold"),
                    dbc.CardBody([
                        dcc.Graph(id='status-donut-chart'),
                        html.Div(id='status-filter-indicator', className="mt-2 text-center")
                    ])
                ])
            ], width=5),
            
            # Right: Priority Table (OIL-M-02)
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Priority Machines", className="fw-bold"),
                    dbc.CardBody(
                        html.Div(id='priority-table-container')
                    )
                ])
            ], width=7)
        ], className="mb-4"),
        
        # ========================================
        # SECTION 2: Machine Detail (OIL-M-03, OIL-M-04)
        # ========================================
        html.Hr(),
        html.H4("🔍 Machine Component Details", className="mt-4 mb-3"),
        html.P("Select a machine from the priority table or use the selector below.", className="text-muted"),
        
        # Persistent machine selection indicator
        dbc.Alert(
            id='machine-selection-indicator',
            children="No machine selected",
            color="light",
            className="mb-3"
        ),
        
        # Machine selector (alternative to table selection)
        dbc.Row([
            dbc.Col([
                html.Label("Or select machine manually:", className="fw-bold"),
                dcc.Dropdown(
                    id='machine-detail-selector',
                    placeholder='Select a machine...',
                    className="mb-3"
                )
            ], width=6)
        ]),
        
        # Component detail table
        dbc.Card([
            dbc.CardHeader("Component Breakdown (Sorted Worst-First)", className="fw-bold"),
            dbc.CardBody(
                html.Div(id='machine-detail-table-container')
            )
        ], className="mb-4"),
        
        # ========================================
        # SECTION 3: Quick Navigation (OIL-M-05)
        # ========================================
        html.Hr(),
        html.H4("🧭 Quick Navigation to Report Detail", className="mt-4 mb-3"),
        
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Equipment:", className="fw-bold"),
                        dcc.Dropdown(
                            id='nav-equipment-selector',
                            placeholder='Select equipment...'
                        )
                    ], width=4),
                    dbc.Col([
                        html.Label("Component:", className="fw-bold"),
                        dcc.Dropdown(
                            id='nav-component-selector',
                            placeholder='Select component...',
                            disabled=True
                        )
                    ], width=4),
                    dbc.Col([
                        html.Div([
                            html.Label("\u00a0", className="fw-bold"),  # Spacer
                            dbc.Button(
                                "Navigate to Report Detail →",
                                id='nav-to-report-button',
                                color="primary",
                                className="w-100",
                                disabled=True
                            )
                        ])
                    ], width=4)
                ])
            ])
        ], className="mb-4"),
        
        # ========================================
        # SECTION 4: Component Distribution (OIL-M-06)
        # ========================================
        html.Hr(),
        html.H4("📈 Component Status Distribution", className="mt-4 mb-3"),
        
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.Span("Component Status by Type", className="fw-bold"),
                        dbc.Button(
                            "Toggle Grouping",
                            id='toggle-component-grouping',
                            color="secondary",
                            size="sm",
                            className="float-end"
                        )
                    ]),
                    dbc.CardBody([
                        html.Div(id='component-grouping-indicator', className="mb-2 text-muted small"),
                        dcc.Graph(id='component-stacked-bar-chart')
                    ])
                ])
            ], width=12)
        ], className="mb-4"),
        
        # Hidden store for component grouping toggle state
        dcc.Store(id='component-grouping-state', data={'use_normalized': False})
        
    ], fluid=True)
