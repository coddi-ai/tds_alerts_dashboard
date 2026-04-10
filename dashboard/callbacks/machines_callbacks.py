"""
Machines Overview tab callbacks for Multi-Technical-Alerts dashboard.

Complete implementation with all 4 sections from documentation.
"""

from dash import Input, Output, State, html, dcc, dash_table
from dash.exceptions import PreventUpdate
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path
from config.settings import get_settings
from src.utils.file_utils import safe_read_parquet
from src.utils.logger import get_logger
from dashboard.components.charts import create_status_pie_chart, STATUS_COLORS
from dashboard.components.tables import create_priority_table, create_machine_detail_table
import dash_bootstrap_components as dbc

logger = get_logger(__name__)


def register_machines_callbacks(app):
    """
    Register callbacks for Machines Overview tab.
    
    Args:
        app: Dash application instance
    """
    
    # SECTION 1: Machine-Level Overview (Pie + Priority Table)
    @app.callback(
        [Output('status-pie-chart', 'figure'),
         Output('priority-table-container', 'children'),
         Output('machine-detail-selector', 'options'),
         Output('nav-equipment-selector', 'options')],
        [Input('client-selector', 'value')]
    )
    def update_machines_overview(client):
        """Update machines overview based on client."""
        logger.info(f"Machines overview callback triggered: client={client}")
        
        if not client:
            from plotly.graph_objects import Figure
            logger.warning("No client selected")
            return Figure(), "Please select a client", [], []
        
        settings = get_settings()
        
        # Load machine status data from golden layer
        machine_file = settings.get_machine_status_path(client)
        logger.info(f"Looking for machine file at: {machine_file}")
        
        if not machine_file.exists():
            from plotly.graph_objects import Figure
            logger.error(f"Machine file not found: {machine_file}")
            return Figure(), f"No machine data available at {machine_file}", [], []
        
        try:
            df = safe_read_parquet(machine_file)
            
            # Create pie chart
            pie_chart = create_status_pie_chart(df)
            
            # Create priority table
            priority_table = create_priority_table(df)
            
            # Machine options for detail selector - add "All Machines" option
            machines = sorted(df['unit_id'].unique().tolist())
            machine_options = [{'label': 'All Machines', 'value': 'ALL'}] + [{'label': m.upper(), 'value': m} for m in machines]
            
            return pie_chart, priority_table, machine_options, machine_options[1:]  # Nav options without "All"
            
        except Exception as e:
            from plotly.graph_objects import Figure
            return Figure(), f"Error: {str(e)}", [], []
    
    
    # SECTION 2: Machine Detail Drill-Down
    @app.callback(
        [Output('machine-info-header', 'children'),
         Output('machine-detail-table-container', 'children')],
        [Input('machine-detail-selector', 'value'),
         Input('client-selector', 'value')]
    )
    def update_machine_details(unit_id, client):
        """Update machine detail view."""
        if not client:
            return "", "Select a client to view machine details"
        
        if not unit_id:
            return "", "Select a machine to view component details"
        
        settings = get_settings()
        
        # Load classified reports from golden layer
        reports_file = settings.get_classified_reports_path(client)
        
        if not reports_file.exists():
            return "", "No reports data available"
        
        try:
            df = safe_read_parquet(reports_file)
            
            # Filter to selected machine(s)
            if unit_id == 'ALL':
                machine_df = df.copy()
                header_text = "All Machines"
            else:
                machine_df = df[df['unitId'] == unit_id].copy()
                header_text = f"Machine: {unit_id}"
            
            if machine_df.empty:
                return "", f"No data found for {header_text}"
            
            # Get latest samples for each component (per machine if ALL)
            if unit_id == 'ALL':
                latest_samples = machine_df.loc[machine_df.groupby(['unitId', 'componentName'])['sampleDate'].idxmax()]
            else:
                latest_samples = machine_df.loc[machine_df.groupby('componentName')['sampleDate'].idxmax()]
            
            # Prepare display data
            if unit_id == 'ALL':
                display_df = latest_samples[['unitId', 'componentName', 'report_status', 'severity_score', 
                                              'essays_broken', 'sampleDate']].copy()
            else:
                display_df = latest_samples[['componentName', 'report_status', 'severity_score', 
                                              'essays_broken', 'sampleDate']].copy()
            
            # Format date
            if 'sampleDate' in display_df.columns:
                display_df['sampleDate'] = pd.to_datetime(display_df['sampleDate']).dt.strftime('%Y-%m-%d')
            
            # Create header
            if unit_id != 'ALL':
                machine_info = machine_df.iloc[0]
                machine_type_display = str(machine_info.get('machineName', 'N/A')).title()
                header = html.Div([
                    html.H5(f"Machine: {unit_id.upper()}", className="mb-2"),
                    html.P([
                        f"Client: {machine_info.get('client', 'N/A').upper()} | ",
                        f"Machine Type: {machine_type_display} | ",
                        f"Total Components: {len(latest_samples)}"
                    ], className="text-muted")
                ])
            else:
                header = html.Div([
                    html.H5(f"Showing all machines ({len(machine_df['unitId'].unique())} machines, {len(latest_samples)} components)", className="mb-2")
                ])
            
            # Create table
            table = create_machine_detail_table(display_df)
            
            return header, table
            
        except Exception as e:
            return "", f"Error: {str(e)}"
    
    
    # Navigation: Update component dropdown based on equipment selection
    @app.callback(
        Output('nav-component-selector', 'options'),
        [Input('nav-equipment-selector', 'value'),
         Input('client-selector', 'value')]
    )
    def update_nav_component_options(unit_id, client):
        """Update component options for navigation."""
        if not unit_id or not client:
            return []
        
        settings = get_settings()
        reports_file = settings.get_classified_reports_path(client)
        
        if not reports_file.exists():
            return []
        
        try:
            df = safe_read_parquet(reports_file)
            df = df[df['unitId'] == unit_id]
            
            components = sorted(df['componentName'].unique().tolist())
            return [{'label': c.title(), 'value': c} for c in components]
            
        except:
            return []
    
    
    # SECTION 3: Component-Level Distribution Charts
    @app.callback(
        [Output('component-status-pie-chart', 'figure'),
         Output('component-status-histogram', 'figure')],
        [Input('client-selector', 'value')]
    )
    def update_component_distributions(client):
        """Update component-level distribution charts."""
        if not client:
            from plotly.graph_objects import Figure
            return Figure(), Figure()
        
        settings = get_settings()
        reports_file = settings.get_classified_reports_path(client)
        
        if not reports_file.exists():
            from plotly.graph_objects import Figure
            return Figure(), Figure()
        
        try:
            df = safe_read_parquet(reports_file)
            
            # Get latest sample for each machine-component combination
            latest_components = df.loc[df.groupby(['unitId', 'componentName'])['sampleDate'].idxmax()]
            
            # Component status pie chart
            status_counts = latest_components['report_status'].value_counts()
            
            pie_fig = go.Figure(data=[go.Pie(
                labels=status_counts.index,
                values=status_counts.values,
                marker=dict(colors=[STATUS_COLORS.get(s, '#999999') for s in status_counts.index]),
                hole=0.4,
                textinfo='label+percent+value',
                textfont=dict(size=14)
            )])
            
            pie_fig.update_layout(
                title="Component Status Distribution",
                title_font_size=16,
                showlegend=True,
                height=400
            )
            
            # Component status histogram – reports per component, colored by status
            histogram_fig = px.histogram(
                latest_components,
                x='componentName',
                color='report_status',
                color_discrete_map=STATUS_COLORS,
                title="Reports per Component by Status",
                barmode='stack'
            )
            
            histogram_fig.update_layout(
                xaxis_title="Component",
                yaxis_title="Number of Reports",
                showlegend=True,
                height=400,
                xaxis_tickangle=-45
            )
            
            return pie_fig, histogram_fig
            
        except Exception as e:
            from plotly.graph_objects import Figure
            return Figure(), Figure()
    
    
    # SECTION 4: Critical Components Analysis
    @app.callback(
        Output('critical-components-container', 'children'),
        [Input('client-selector', 'value')]
    )
    def update_critical_components(client):
        """Update critical components table with AI recommendations."""
        if not client:
            return html.Div("Please select a client", className="text-muted p-3")
        
        settings = get_settings()
        reports_file = settings.get_classified_reports_path(client)
        
        if not reports_file.exists():
            return html.Div("No reports data available", className="text-warning p-3")
        
        try:
            df = safe_read_parquet(reports_file)
            
            # Get latest sample for each machine-component
            latest_components = df.loc[df.groupby(['unitId', 'componentName'])['sampleDate'].idxmax()]
            
            # Filter to critical components (Anormal or Alerta)
            critical = latest_components[latest_components['report_status'].isin(['Anormal', 'Alerta'])]
            
            if critical.empty:
                return dbc.Alert(
                    "✅ No critical components found. All systems operating normally!",
                    color="success"
                )
            
            # Sort by severity (Anormal first, then by severity score)
            critical = critical.sort_values(
                by=['report_status', 'severity_score'],
                ascending=[True, False]  # Anormal < Alerta alphabetically, so True puts Anormal first
            )
            
            # Create expandable sections for each critical component
            components = []
            
            for idx, row in critical.iterrows():
                status_color = 'danger' if row['report_status'] == 'Anormal' else 'warning'
                status_icon = '🔴' if row['report_status'] == 'Anormal' else '🟡'
                
                # Apply formatting to display names
                unit_display = str(row['unitId']).upper()
                component_display = str(row['componentName']).title()
                
                # Create component card
                card = dbc.Card([
                    dbc.CardHeader([
                        html.Div([
                            html.Span(f"{status_icon} ", style={'fontSize': '1.2em'}),
                            html.Strong(f"{unit_display} - {component_display}"),
                            html.Span(
                                f" {row['report_status']}",
                                className=f"badge bg-{status_color} ms-2"
                            ),
                            html.Span(
                                f" Score: {row.get('severity_score', 0)}",
                                className="badge bg-secondary ms-2"
                            ),
                            html.Span(
                                f" Essays Broken: {row.get('essays_broken', 0)}",
                                className="badge bg-info ms-2"
                            )
                        ])
                    ]),
                    dbc.CardBody([
                        html.P([
                            html.Strong("Sample Date: "),
                            pd.to_datetime(row['sampleDate']).strftime('%Y-%m-%d') if pd.notna(row['sampleDate']) else 'N/A'
                        ]),
                        html.Hr(),
                        html.H6("🤖 AI Recommendation:", className="mb-2"),
                        html.Div(
                            row.get('ai_recommendation', 'No AI recommendation available'),
                            style={'whiteSpace': 'pre-wrap'}
                        )
                    ])
                ], className="mb-3", color=status_color, outline=True)
                
                components.append(card)
            
            return html.Div([
                html.P(f"Found {len(critical)} components requiring attention:", className="fw-bold mb-3"),
                html.Div(components)
            ])
            
        except Exception as e:
            return html.Div(f"Error: {str(e)}", className="text-danger p-3")
    
    
    # NAVIGATION: Handle "Navigate to Report" button
    @app.callback(
        [Output('navigation-state', 'data'),
         Output('oil-internal-tabs', 'value')],
        [Input('nav-to-report-button', 'n_clicks')],
        [State('nav-equipment-selector', 'value'),
         State('nav-component-selector', 'value'),
         State('client-selector', 'value')],
        prevent_initial_call=True
    )
    def navigate_to_report(n_clicks, equipo, component, client):
        """Navigate to Report Detail tab within Oil section with pre-filled filters."""
        if not n_clicks or not all([equipo, component, client]):
            raise PreventUpdate
        
        # Get familia (machineName) for the selected equipment
        settings = get_settings()
        reports_file = settings.get_classified_reports_path(client)
        
        if not reports_file.exists():
            raise PreventUpdate
        
        try:
            df = safe_read_parquet(reports_file)
            equipo_data = df[df['unitId'] == equipo]
            
            if equipo_data.empty:
                raise PreventUpdate
            
            familia = equipo_data.iloc[0]['machineName']
            
            # Prepare navigation state
            nav_state = {
                'familia': familia,
                'equipo': equipo,
                'component': component,
                'client': client
            }
            
            # Switch to Report Detail internal tab within Oil section
            return nav_state, 'report-detail'
            
        except Exception as e:
            raise PreventUpdate
