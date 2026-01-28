"""
Reports Detail tab for Multi-Technical-Alerts dashboard.

Displays sample-level analysis with radar charts and time series.
"""

from dash import dcc, html
import dash_bootstrap_components as dbc


def create_reports_tab() -> dbc.Container:
    """
    Create Tab 3: Reports Detail Analysis.
    
    Features:
    - 4-level filter hierarchy: Client → Familia → Equipo → Componente
    - Auto-loads most recent sample on page load
    - Radar charts by GroupElement
    - Value analysis table
    - Time series chart with threshold lines
    - AI recommendations display
    - Historical comparison table
    
    Returns:
        Bootstrap container with tab layout
    """
    return dbc.Container([
        html.H3("Reports Detail Analysis", className="mt-4 mb-3"),
        html.Hr(),
        
        # 4-Level Filter Hierarchy
        dbc.Card([
            dbc.CardHeader("Filter Hierarchy", className="fw-bold"),
            dbc.CardBody([
                dbc.Row([
                    # Level 2: Familia (Machine Type)
                    dbc.Col([
                        html.Label("Familia (Machine Type):", className="fw-bold"),
                        dcc.Dropdown(
                            id='reports-familia-selector',
                            placeholder='Select machine type...',
                            className="mb-3"
                        )
                    ], width=3),
                    
                    # Level 3: Equipo (Unit ID)
                    dbc.Col([
                        html.Label("Equipo (Unit ID):", className="fw-bold"),
                        dcc.Dropdown(
                            id='reports-equipo-selector',
                            placeholder='Select equipment...',
                            className="mb-3"
                        )
                    ], width=3),
                    
                    # Level 4: Componente
                    dbc.Col([
                        html.Label("Componente:", className="fw-bold"),
                        dcc.Dropdown(
                            id='reports-component-selector',
                            placeholder='Select component...',
                            className="mb-3"
                        )
                    ], width=3),
                    
                    # Sample Date
                    dbc.Col([
                        html.Label("Sample Date:", className="fw-bold"),
                        dcc.Dropdown(
                            id='reports-date-selector',
                            placeholder='Select date...',
                            className="mb-3"
                        )
                    ], width=3)
                ])
            ])
        ], className="mb-4"),
        
        # Sample information card
        dbc.Card([
            dbc.CardHeader("Sample Information", className="fw-bold"),
            dbc.CardBody(
                html.Div(id='reports-sample-info-display')
            )
        ], className="mb-4"),
        
        # SECTION 1: Analysis Section - Radar charts with tables per GroupElement
        dbc.Card([
            dbc.CardHeader("📊 Report Analysis", className="fw-bold"),
            dbc.CardBody([
                html.Div(id='reports-radar-charts-container')  # Contains grouped sections
            ])
        ], className="mb-4"),
        
        # SECTION 2: AI Recommendations (below analysis)
        dbc.Card([
            dbc.CardHeader("🤖 AI Recommendation", className="fw-bold"),
            dbc.CardBody(
                html.Div(id='reports-ai-recommendation-display')
            )
        ], className="mb-4"),
        
        # SECTION 3: Time Series Analysis
        dbc.Card([
            dbc.CardHeader("📈 Time Series Analysis", className="fw-bold"),
            dbc.CardBody([
                html.Label("Select Essays to Plot:", className="fw-bold mb-2"),
                dcc.Dropdown(
                    id='reports-essays-selector',
                    multi=True,
                    placeholder='Select essays (up to 6)...',
                    className="mb-3"
                ),
                dcc.Graph(id='reports-time-series-chart')
            ])
        ], className="mb-4"),
        
        # SECTION 4: Historical Comparison
        dbc.Card([
            dbc.CardHeader("🔄 Comparison with Previous Reports", className="fw-bold"),
            dbc.CardBody(
                html.Div(id='reports-historical-comparison')
            )
        ], className="mb-4")
        
    ], fluid=True)
