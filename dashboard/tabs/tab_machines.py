"""
Machines Overview tab for Multi-Technical-Alerts dashboard.

Displays machine-level status aggregations and priority tables.
Complete implementation with all 4 sections from documentation.
"""

from dash import dcc, html
import dash_bootstrap_components as dbc
from dashboard.components.filters import create_status_filter


def create_machines_tab() -> dbc.Container:
    """
    Create Tab 2: Machines Overview.
    
    Complete implementation with 4 sections:
    1. Machine-level status distribution (pie chart + priority table)
    2. Machine detail drill-down (component breakdown)
    3. Component-level status distribution (pie chart + histogram)
    4. Critical components analysis (AI recommendations)
    
    Returns:
        Bootstrap container with tab layout
    """
    return dbc.Container([
        html.H3("Machines Overview", className="mt-4 mb-3"),
        html.Hr(),
        
        # Filters
        dbc.Row([
            create_status_filter()
        ], className="mb-4"),
        
        # SECTION 1: Machine-Level Summary
        html.H4("📊 Machine Status Distribution", className="mt-4 mb-3"),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Status Distribution (Machines)", className="fw-bold"),
                    dbc.CardBody(
                        dcc.Graph(id='status-pie-chart')
                    )
                ])
            ], width=6),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Priority Machines (Top 10)", className="fw-bold"),
                    dbc.CardBody(
                        html.Div(id='priority-table-container')
                    )
                ])
            ], width=6)
        ], className="mb-4"),
        
        # SECTION 2: Machine Detail Drill-Down
        html.Hr(),
        html.H4("🔍 Machine Component Details", className="mt-4 mb-3"),
        dbc.Row([
            dbc.Col([
                html.Label("Select Machine for Details:", className="fw-bold"),
                dcc.Dropdown(
                    id='machine-detail-selector',
                    placeholder='Select a machine or view all...',
                    className="mb-3"
                )
            ], width=6)
        ]),
        
        dbc.Card([
            dbc.CardHeader("Component Breakdown", className="fw-bold"),
            dbc.CardBody([
                html.Div(id='machine-info-header', className="mb-3"),
                html.Div(id='machine-detail-table-container')
            ])
        ], className="mb-4"),
        
        # Quick Navigation
        dbc.Card([
            dbc.CardHeader("🧭 Quick Navigation to Report Detail", className="fw-bold"),
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
                            placeholder='Select component...'
                        )
                    ], width=4),
                    dbc.Col([
                        html.Div([
                            html.Label("\u00a0", className="fw-bold"),  # Spacer
                            dbc.Button(
                                "Navigate to Report Detail →",
                                id='nav-to-report-button',
                                color="primary",
                                className="w-100"
                            )
                        ])
                    ], width=4)
                ])
            ])
        ], className="mb-4"),
        
        # SECTION 3: Component-Level Distribution
        html.Hr(),
        html.H4("📈 Component Status Distribution", className="mt-4 mb-3"),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Status Distribution (Components)", className="fw-bold"),
                    dbc.CardBody(
                        dcc.Graph(id='component-status-pie-chart')
                    )
                ])
            ], width=6),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Component Status Histogram", className="fw-bold"),
                    dbc.CardBody(
                        dcc.Graph(id='component-status-histogram')
                    )
                ])
            ], width=6)
        ], className="mb-4"),
        
        # SECTION 4: Critical Components Analysis
        html.Hr(),
        html.H4("⚠️ Critical Components (Anormal & Alerta)", className="mt-4 mb-3"),
        dbc.Card([
            dbc.CardHeader("Components Requiring Attention", className="fw-bold"),
            dbc.CardBody(
                html.Div(id='critical-components-container')
            )
        ])
        
    ], fluid=True)
