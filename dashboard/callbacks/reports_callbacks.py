"""
Reports Detail tab callbacks for Multi-Technical-Alerts dashboard.

Complete refactored implementation with 4-level hierarchy and auto-loading.
"""

from dash import Input, Output, State, html, dash_table
from dash.exceptions import PreventUpdate
import pandas as pd
import json
from pathlib import Path
from config.settings import get_settings
from src.utils.file_utils import safe_read_parquet
from src.data.loaders import load_stewart_limits
from dashboard.components.charts import create_radar_chart, create_time_series_chart
import dash_bootstrap_components as dbc
import logging

logger = logging.getLogger(__name__)


def register_reports_callbacks(app):
    """
    Register callbacks for Reports Detail tab with 4-level hierarchy.
    
    Args:
        app: Dash application instance
    """
    
    # Level 2: Update Familia options when client changes (or navigation state changes)
    @app.callback(
        [Output('reports-familia-selector', 'options'),
         Output('reports-familia-selector', 'value')],
        [Input('client-selector', 'value'),
         Input('navigation-state', 'data')],
        [State('reports-familia-selector', 'value')]
    )
    def update_familia_options(client, nav_state, current_familia):
        """Update familia (machine type) options."""
        logger.info(f"update_familia_options called: client={client}, nav_state={nav_state}, current={current_familia}")
        
        if not client:
            return [], None
        
        settings = get_settings()
        reports_file = settings.get_processed_path() / f"{client.lower()}_classified.parquet"
        
        if not reports_file.exists():
            logger.error(f"File not found: {reports_file}")
            return [], None
        
        try:
            df = safe_read_parquet(reports_file)
            familias = sorted(df['machineName'].dropna().unique().tolist())
            options = [{'label': f, 'value': f} for f in familias]
            
            # Check if navigation state provides a familia
            if nav_state and nav_state.get('familia'):
                default_value = nav_state['familia']
                logger.info(f"Using familia from navigation: {default_value}")
            elif current_familia and current_familia in familias:
                # Keep current selection if valid
                default_value = current_familia
                logger.info(f"Keeping current familia: {default_value}")
            else:
                # Auto-select first familia only on initial load
                default_value = familias[0] if familias else None
                logger.info(f"Auto-selecting first familia: {default_value}")
            
            return options, default_value
            
        except Exception as e:
            logger.exception(f"Error in update_familia_options: {e}")
            return [], None
    
    
    # Level 3: Update Equipo options when familia changes (or navigation state changes)
    @app.callback(
        [Output('reports-equipo-selector', 'options'),
         Output('reports-equipo-selector', 'value')],
        [Input('reports-familia-selector', 'value'),
         Input('client-selector', 'value'),
         Input('navigation-state', 'data')],
        [State('reports-equipo-selector', 'value')]
    )
    def update_equipo_options(familia, client, nav_state, current_equipo):
        """Update equipo (unitId) options."""
        logger.info(f"update_equipo_options called: familia={familia}, client={client}, nav_state={nav_state}, current={current_equipo}")
        
        if not familia or not client:
            return [], None
        
        settings = get_settings()
        reports_file = settings.get_processed_path() / f"{client.lower()}_classified.parquet"
        
        if not reports_file.exists():
            return [], None
        
        try:
            df = safe_read_parquet(reports_file)
            df = df[df['machineName'] == familia]
            
            equipos = sorted(df['unitId'].dropna().unique().tolist())
            options = [{'label': e, 'value': e} for e in equipos]
            
            # Check if navigation state provides an equipo
            if nav_state and nav_state.get('equipo'):
                default_value = nav_state['equipo']
                logger.info(f"Using equipo from navigation: {default_value}")
            elif current_equipo and current_equipo in equipos:
                # Keep current selection if still valid
                default_value = current_equipo
                logger.info(f"Keeping current equipo: {default_value}")
            else:
                # Auto-select first equipo
                default_value = equipos[0] if equipos else None
                logger.info(f"Auto-selecting first equipo: {default_value}")
            
            return options, default_value
            
        except Exception as e:
            logger.exception(f"Error in update_equipo_options: {e}")
            return [], None
    
    
    # Level 4: Update Component options when equipo changes (or navigation state changes)
    @app.callback(
        [Output('reports-component-selector', 'options'),
         Output('reports-component-selector', 'value'),
         Output('navigation-state', 'data', allow_duplicate=True)],  # Clear navigation state after use
        [Input('reports-equipo-selector', 'value'),
         Input('reports-familia-selector', 'value'),
         Input('client-selector', 'value'),
         Input('navigation-state', 'data')],
        [State('reports-component-selector', 'value')],
        prevent_initial_call=True
    )
    def update_component_options(equipo, familia, client, nav_state, current_component):
        """Update component options."""
        logger.info(f"update_component_options called: equipo={equipo}, familia={familia}, client={client}, nav_state={nav_state}, current={current_component}")
        
        if not equipo or not familia or not client:
            return [], None, None
        
        settings = get_settings()
        reports_file = settings.get_processed_path() / f"{client.lower()}_classified.parquet"
        
        if not reports_file.exists():
            return [], None, None
        
        try:
            df = safe_read_parquet(reports_file)
            df = df[(df['machineName'] == familia) & (df['unitId'] == equipo)]
            
            components = sorted(df['componentName'].dropna().unique().tolist())
            options = [{'label': c, 'value': c} for c in components]
            
            # Check if navigation state provides a component
            if nav_state and nav_state.get('component'):
                default_value = nav_state['component']
                logger.info(f"Using component from navigation: {default_value}")
                # Clear navigation state after using it
                return options, default_value, None
            elif current_component and current_component in components:
                # Keep current selection if still valid
                default_value = current_component
                logger.info(f"Keeping current component: {default_value}")
                return options, default_value, nav_state
            else:
                # Auto-select first component
                default_value = components[0] if components else None
                logger.info(f"Auto-selecting first component: {default_value}")
                return options, default_value, nav_state
            
        except Exception as e:
            logger.exception(f"Error in update_component_options: {e}")
            return [], None, None
    
    
    # Level 5: Update Date options when component changes
    @app.callback(
        [Output('reports-date-selector', 'options'),
         Output('reports-date-selector', 'value')],
        [Input('reports-component-selector', 'value'),
         Input('reports-equipo-selector', 'value'),
         Input('reports-familia-selector', 'value'),
         Input('client-selector', 'value')],
        [State('reports-date-selector', 'value')]
    )
    def update_date_options(component, equipo, familia, client, current_date):
        """Update sample date options (most recent first)."""
        logger.info(f"update_date_options called: client={client}, familia={familia}, equipo={equipo}, component={component}, current={current_date}")
        
        if not all([component, equipo, familia, client]):
            logger.warning(f"Missing parameters: component={component}, equipo={equipo}, familia={familia}, client={client}")
            return [], None
        
        settings = get_settings()
        reports_file = settings.get_processed_path() / f"{client.lower()}_classified.parquet"
        
        logger.info(f"Looking for file: {reports_file}")
        
        if not reports_file.exists():
            logger.error(f"File not found: {reports_file}")
            return [], None
        
        try:
            df = safe_read_parquet(reports_file)
            logger.info(f"Loaded {len(df)} rows from {reports_file}")
            logger.info(f"Columns: {df.columns.tolist()}")
            logger.info(f"Unique familias: {df['machineName'].unique().tolist()}")
            logger.info(f"Unique equipos: {df['unitId'].unique().tolist()}")
            
            df = df[(df['machineName'] == familia) & 
                   (df['unitId'] == equipo) & 
                   (df['componentName'] == component)]
            
            logger.info(f"After filtering: {len(df)} rows")
            
            # Sort by date descending (most recent first)
            df = df.sort_values('sampleDate', ascending=False)
            
            dates = df['sampleDate'].unique()
            logger.info(f"Found {len(dates)} unique dates")
            
            options = [{'label': pd.to_datetime(d).strftime('%Y-%m-%d'), 'value': str(d)} 
                      for d in dates]
            
            # Get string representations for comparison
            date_strs = [str(d) for d in dates]
            
            # Preserve current selection if it's still valid
            if current_date and current_date in date_strs:
                default_value = current_date
                logger.info(f"Keeping current date: {default_value}")
            else:
                # Auto-select most recent date (index 0)
                default_value = str(dates[0]) if len(dates) > 0 else None
                logger.info(f"Auto-selecting most recent date: {default_value}")
            
            logger.info(f"Returning {len(options)} date options, default={default_value}")
            return options, default_value
            
        except Exception as e:
            logger.exception(f"Error in update_date_options: {e}")
            return [], None
    
    
    # Main display callback: Update all content when date changes
    @app.callback(
        [Output('reports-sample-info-display', 'children'),
         Output('reports-radar-charts-container', 'children'),
         Output('reports-ai-recommendation-display', 'children'),
         Output('reports-essays-selector', 'options'),
         Output('reports-historical-comparison', 'children')],
        [Input('reports-date-selector', 'value'),
         Input('reports-component-selector', 'value'),
         Input('reports-equipo-selector', 'value'),
         Input('reports-familia-selector', 'value'),
         Input('client-selector', 'value')]
    )
    def update_report_display(sample_date, component, equipo, familia, client):
        """Update all report displays."""
        from plotly.graph_objects import Figure
        
        logger.info(f"update_report_display called: client={client}, familia={familia}, equipo={equipo}, component={component}, date={sample_date}")
        
        if not all([sample_date, component, equipo, familia, client]):
            logger.warning(f"Missing parameters in update_report_display")
            return ("Select filters to view report", "", 
                   "No recommendation", [], "No data")
        
        settings = get_settings()
        reports_file = settings.get_processed_path() / f"{client.lower()}_classified.parquet"
        limits_file = settings.get_stewart_limits_path()
        
        logger.info(f"Reports file: {reports_file}, exists: {reports_file.exists()}")
        
        if not reports_file.exists():
            logger.error(f"Reports file not found: {reports_file}")
            return ("No data available", "",
                   "No recommendation", [], "No data")
        
        try:
            df = safe_read_parquet(reports_file)
            limits = load_stewart_limits(limits_file) if limits_file.exists() else None
            
            logger.info(f"Loaded {len(df)} rows, filtering for: familia={familia}, equipo={equipo}, component={component}, date={sample_date}")
            
            # Convert sample_date string to just date part for comparison
            sample_date_only = pd.to_datetime(sample_date).strftime('%Y-%m-%d')
            df['sampleDate_str'] = pd.to_datetime(df['sampleDate']).dt.strftime('%Y-%m-%d')
            
            # Find the sample
            sample_df = df[(df['machineName'] == familia) & 
                          (df['unitId'] == equipo) & 
                          (df['componentName'] == component) &
                          (df['sampleDate_str'] == sample_date_only)]
            
            logger.info(f"Found {len(sample_df)} matching samples")
            
            if sample_df.empty:
                logger.warning(f"No sample found after filtering")
                return ("No sample found", "",
                       "No recommendation", [], "No data")
            
            sample = sample_df.iloc[0]
            logger.info(f"Sample found: {sample.get('sampleNumber', 'N/A')}")
            
            # 1. Sample Info Card
            info = create_sample_info_card(sample)
            
            # 2. Radar Charts by GroupElement (includes tables)
            radar_charts = create_radar_charts_by_group(sample, limits, df)
            
            # 3. AI Recommendation
            ai_display = create_ai_recommendation_display(sample)
            
            # 4. Essay options for time series
            essay_options = get_essay_options(df)
            
            # 5. Historical Comparison
            historical_comp = create_historical_comparison(sample, df, equipo, component)
            
            logger.info("Successfully generated all report components")
            return info, radar_charts, ai_display, essay_options, historical_comp
            
        except Exception as e:
            logger.exception(f"Error in update_report_display: {e}")
            return (f"Error: {str(e)}", "",
                   "Error", [], "Error")
    
    
    # Time series callback - Create subplot for each essay
    @app.callback(
        Output('reports-time-series-chart', 'figure'),
        [Input('reports-essays-selector', 'value'),
         Input('reports-component-selector', 'value'),
         Input('reports-equipo-selector', 'value'),
         Input('client-selector', 'value')]
    )
    def update_time_series(essays, component, equipo, client):
        """Update time series chart with subplots."""
        from plotly.graph_objects import Figure
        from plotly.subplots import make_subplots
        import plotly.graph_objects as go
        
        if not all([essays, component, equipo, client]) or not essays:
            return Figure()
        
        # Limit to 6 essays for readability
        essays = essays[:6]
        
        settings = get_settings()
        reports_file = settings.get_processed_path() / f"{client.lower()}_classified.parquet"
        limits_file = settings.get_stewart_limits_path()
        
        if not reports_file.exists():
            return Figure()
        
        try:
            df = safe_read_parquet(reports_file)
            limits = load_stewart_limits(limits_file) if limits_file.exists() else None
            
            # Filter to this equipment and component
            history = df[(df['unitId'] == equipo) & (df['componentName'] == component)].sort_values('sampleDate')
            
            if history.empty:
                return Figure()
            
            # Create subplots - one row per essay, shared x-axis
            fig = make_subplots(
                rows=len(essays),
                cols=1,
                shared_xaxes=True,
                vertical_spacing=0.05,
                subplot_titles=[f"{essay}" for essay in essays]
            )
            
            # Get limits for this component
            if limits:
                familia = history.iloc[0]['machineName']
                comp_limits = limits.get(client, {}).get(familia, {}).get(component, {})
            else:
                comp_limits = {}
            
            # Add trace for each essay
            for idx, essay in enumerate(essays, 1):
                # Extract values
                essay_values = history[essay].dropna()
                essay_dates = history.loc[essay_values.index, 'sampleDate']
                
                # Add actual values line
                fig.add_trace(
                    go.Scatter(
                        x=essay_dates,
                        y=essay_values,
                        mode='lines+markers',
                        name=essay,
                        line=dict(color='#1f77b4', width=2),
                        marker=dict(size=6),
                        showlegend=False
                    ),
                    row=idx, col=1
                )
                
                # Add threshold lines if available
                if essay in comp_limits:
                    thresholds = comp_limits[essay]
                    
                    # Normal threshold
                    if 'threshold_normal' in thresholds:
                        fig.add_trace(
                            go.Scatter(
                                x=essay_dates,
                                y=[thresholds['threshold_normal']] * len(essay_dates),
                                mode='lines',
                                name='Normal',
                                line=dict(color='green', dash='dash', width=1),
                                showlegend=(idx == 1)
                            ),
                            row=idx, col=1
                        )
                    
                    # Alert threshold
                    if 'threshold_alert' in thresholds:
                        fig.add_trace(
                            go.Scatter(
                                x=essay_dates,
                                y=[thresholds['threshold_alert']] * len(essay_dates),
                                mode='lines',
                                name='Alert',
                                line=dict(color='orange', dash='dash', width=1),
                                showlegend=(idx == 1)
                            ),
                            row=idx, col=1
                        )
                    
                    # Critic threshold
                    if 'threshold_critic' in thresholds:
                        fig.add_trace(
                            go.Scatter(
                                x=essay_dates,
                                y=[thresholds['threshold_critic']] * len(essay_dates),
                                mode='lines',
                                name='Critic',
                                line=dict(color='red', dash='dash', width=1),
                                showlegend=(idx == 1)
                            ),
                            row=idx, col=1
                        )
                
                # Update y-axis label
                fig.update_yaxes(title_text="ppm", row=idx, col=1)
            
            # Update x-axis label (only last one)
            fig.update_xaxes(title_text="Date", row=len(essays), col=1)
            
            # Update layout
            fig.update_layout(
                height=300 * len(essays),
                title_text="Time Series Analysis",
                hovermode='x unified',
                showlegend=True,
                legend=dict(
                    orientation='h',
                    yanchor='bottom',
                    y=1.02,
                    xanchor='right',
                    x=1
                )
            )
            
            return fig
            
        except Exception as e:
            logger.exception(f"Error in update_time_series: {e}")
            return Figure()


# Helper functions
def create_sample_info_card(sample):
    """Create sample information card."""
    status_class = {
        'Anormal': 'danger',
        'Alerta': 'warning',
        'Normal': 'success'
    }.get(sample.get('report_status', 'Normal'), 'secondary')
    
    return dbc.Card([
        dbc.CardBody([
            html.H5(f"Sample: {sample.get('sampleNumber', 'N/A')}", className="mb-3"),
            dbc.Row([
                dbc.Col([
                    html.P([
                        html.Strong("Client: "), f"{sample.get('client', 'N/A')}", html.Br(),
                        html.Strong("Familia: "), f"{sample.get('machineName', 'N/A')}", html.Br(),
                        html.Strong("Equipo: "), f"{sample.get('unitId', 'N/A')}", html.Br(),
                        html.Strong("Component: "), f"{sample.get('componentName', 'N/A')}", html.Br(),
                    ])
                ], width=6),
                dbc.Col([
                    html.P([
                        html.Strong("Sample Date: "), 
                        f"{pd.to_datetime(sample.get('sampleDate')).strftime('%Y-%m-%d') if pd.notna(sample.get('sampleDate')) else 'N/A'}", 
                        html.Br(),
                        html.Strong("Status: "), 
                        html.Span(
                            sample.get('report_status', 'N/A'),
                            className=f"badge bg-{status_class} ms-2"
                        ), html.Br(),
                        html.Strong("Severity Score: "), f"{sample.get('severity_score', 0)}", html.Br(),
                        html.Strong("Essays Broken: "), f"{sample.get('essays_broken', 0)}"
                    ])
                ], width=6)
            ])
        ])
    ], color="light")


def normalize_value(value, normal, alert, critic):
    """Normalize essay value to 0-100 scale based on thresholds."""
    if pd.isna(value):
        return 0
    
    # Below normal threshold - linear scale from 0 to 50
    if value <= normal:
        if normal == 0:
            return 0
        return (value / normal) * 50
    
    # Normal to alert range - scale from 50 to 70
    elif value <= alert:
        if alert == normal:
            return 50
        return 50 + ((value - normal) / (alert - normal)) * 20
    
    # Alert to critic range - scale from 70 to 90
    elif value <= critic:
        if critic == alert:
            return 70
        return 70 + ((value - alert) / (critic - alert)) * 20
    
    # Above critic - scale from 90 to 100
    else:
        return 90 + min((value - critic) / critic * 10, 10)


def create_radar_charts_by_group(sample, limits, df):
    """Create radar charts grouped by GroupElement with corresponding value tables."""
    import plotly.graph_objects as go
    from pathlib import Path
    from dash import dcc
    
    # Load essays_elements to get GroupElement mapping
    essays_file = Path("data/oil/essays_elements.xlsx")
    if not essays_file.exists():
        return html.P("essays_elements.xlsx not found", className="text-muted")
    
    try:
        essays_df = pd.read_excel(essays_file)
        essays_df = essays_df.dropna(subset=['ElementNameSpanish', 'GroupElement'])
        
        # Group essays by GroupElement
        group_mapping = essays_df.groupby('GroupElement')['ElementNameSpanish'].apply(list).to_dict()
        
        # Get limits for this component
        machine = sample.get('machineName', '')
        component = sample.get('componentName', '')
        client = sample.get('client', '')
        
        if limits and client in limits and machine in limits[client] and component in limits[client][machine]:
            comp_limits = limits[client][machine][component]
        else:
            return html.P("No limits available for radar charts", className="text-muted")
        
        # Create radar charts
        charts = []
        
        for group_name, essays in group_mapping.items():
            # Filter essays that exist in sample and have limits
            valid_essays = [e for e in essays if e in sample.index and pd.notna(sample[e]) and e in comp_limits]
            
            if not valid_essays:
                continue
            
            # Normalize values
            normalized_values = []
            actual_values = []
            
            for essay in valid_essays:
                value = float(sample[essay])
                actual_values.append(value)
                
                normal = comp_limits[essay].get('threshold_normal', 0)
                alert = comp_limits[essay].get('threshold_alert', 0)
                critic = comp_limits[essay].get('threshold_critic', 0)
                
                norm_value = normalize_value(value, normal, alert, critic)
                normalized_values.append(norm_value)
            
            # Create radar chart
            fig = go.Figure()
            
            # Add threshold rings
            fig.add_trace(go.Scatterpolar(
                r=[90] * len(valid_essays),
                theta=valid_essays,
                name='Crítico',
                line=dict(color='red', dash='dash', width=2),
                fill=None,
                mode='lines'
            ))
            
            fig.add_trace(go.Scatterpolar(
                r=[70] * len(valid_essays),
                theta=valid_essays,
                name='Alerta',
                line=dict(color='orange', dash='dash', width=2),
                fill=None,
                mode='lines'
            ))
            
            fig.add_trace(go.Scatterpolar(
                r=[50] * len(valid_essays),
                theta=valid_essays,
                name='Normal',
                line=dict(color='green', dash='dash', width=2),
                fill=None,
                mode='lines'
            ))
            
            # Determine color based on status
            status_color = {
                'Anormal': '#dc3545',
                'Alerta': '#ffc107',
                'Normal': '#28a745'
            }.get(sample.get('report_status', 'Normal'), '#1f77b4')
            
            # Add actual values
            fig.add_trace(go.Scatterpolar(
                r=normalized_values,
                theta=valid_essays,
                name='Valores Actuales',
                line=dict(color=status_color, width=3),
                fill='toself',
                fillcolor=status_color,
                opacity=0.4,
                hovertemplate='<b>%{theta}</b><br>Valor: %{customdata}<br>Normalizado: %{r:.1f}<extra></extra>',
                customdata=actual_values
            ))
            
            # Update layout
            fig.update_layout(
                polar=dict(
                    radialaxis=dict(
                        visible=True,
                        range=[0, 100],
                        tickvals=[0, 25, 50, 75, 100],
                        ticktext=['0', '25', '50', '75', '100']
                    ),
                    angularaxis=dict(
                        rotation=90,
                        direction='clockwise'
                    )
                ),
                title=dict(
                    text=f"{group_name}",
                    x=0.5,
                    xanchor='center',
                    font=dict(size=14)
                ),
                showlegend=True,
                legend=dict(
                    orientation='h',
                    yanchor='bottom',
                    y=-0.2,
                    xanchor='center',
                    x=0.5,
                    font=dict(size=10)
                ),
                height=350,
                margin=dict(l=50, r=50, t=50, b=50)
            )
            
            # Create value table for this group
            group_table_data = []
            for i, essay in enumerate(valid_essays):
                value = actual_values[i]
                normal = comp_limits[essay].get('threshold_normal', 0)
                alert = comp_limits[essay].get('threshold_alert', 0)
                critic = comp_limits[essay].get('threshold_critic', 0)
                
                # Determine status
                if value >= critic:
                    status = 'Crítico'
                    color = '#dc3545'  # red
                elif value >= alert:
                    status = 'Condenatorio'
                    color = '#fd7e14'  # orange
                elif value >= normal:
                    status = 'Marginal'
                    color = '#ffc107'  # yellow
                else:
                    status = 'Normal'
                    color = '#28a745'  # green
                
                group_table_data.append({
                    'essay': essay,
                    'value': round(value, 2),
                    'status': status,
                    'normal': round(normal, 2),
                    'alert': round(alert, 2),
                    'critic': round(critic, 2),
                    '_color': color
                })
            
            # Sort by status severity
            status_order = {'Crítico': 0, 'Condenatorio': 1, 'Marginal': 2, 'Normal': 3}
            group_table_data.sort(key=lambda x: (status_order.get(x['status'], 4), x['essay']))
            
            # Create table for this group
            group_table = dash_table.DataTable(
                columns=[
                    {'name': 'Essay', 'id': 'essay'},
                    {'name': 'Value', 'id': 'value', 'type': 'numeric'},
                    {'name': 'Status', 'id': 'status'},
                    {'name': 'Normal', 'id': 'normal', 'type': 'numeric'},
                    {'name': 'Alert', 'id': 'alert', 'type': 'numeric'},
                    {'name': 'Critic', 'id': 'critic', 'type': 'numeric'}
                ],
                data=[{k: v for k, v in item.items() if k != '_color'} for item in group_table_data],
                style_cell={
                    'textAlign': 'left',
                    'padding': '8px',
                    'fontSize': '12px',
                    'overflow': 'hidden',
                    'textOverflow': 'ellipsis',
                    'maxWidth': 0
                },
                style_header={
                    'backgroundColor': '#17a2b8',
                    'color': 'white',
                    'fontWeight': 'bold',
                    'textAlign': 'center'
                },
                style_data_conditional=[
                    {
                        'if': {'row_index': i, 'column_id': 'status'},
                        'backgroundColor': item['_color'],
                        'color': 'white' if item['_color'] in ['#dc3545', '#17a2b8', '#28a745'] else 'black',
                        'fontWeight': 'bold'
                    }
                    for i, item in enumerate(group_table_data)
                ],
                page_size=10,
                style_table={'overflowX': 'auto'}
            )
            
            # Add section for this GroupElement
            charts.append(
                html.Div([
                    html.H5(f"📊 {group_name}", className="mt-3 mb-3"),
                    dbc.Row([
                        dbc.Col([
                            dcc.Graph(figure=fig, config={'displayModeBar': False})
                        ], width=6),
                        dbc.Col([
                            group_table
                        ], width=6)
                    ])
                ], className="mb-4")
            )
        
        return html.Div(charts) if charts else html.P("No radar data available", className="text-muted")
        
    except Exception as e:
        logger.exception(f"Error creating radar charts: {e}")
        return html.P(f"Error: {str(e)}", className="text-danger")


def create_value_analysis_table(sample, limits):
    """Create value analysis table showing all essays with thresholds."""
    if limits is None:
        return html.P("No limits data available", className="text-muted")
    
    # Get limits for this component
    machine = sample.get('machineName', '')
    component = sample.get('componentName', '')
    client = sample.get('client', '')
    
    if not (limits and client in limits and machine in limits[client] and component in limits[client][machine]):
        return html.P("No limits available", className="text-muted")
    
    comp_limits = limits[client][machine][component]
    
    # Get metadata columns to exclude
    metadata_cols = {'client', 'sampleNumber', 'sampleDate', 'unitId', 'machineName', 
                    'machineModel', 'machineBrand', 'machineHours', 'machineSerialNumber',
                    'componentName', 'componentHours', 'componentSerialNumber',
                    'oilMeter', 'oilBrand', 'oilType', 'oilWeight',
                    'previousSampleNumber', 'previousSampleDate', 'daysSincePrevious',
                    'group_element', 'essays_broken', 'severity_score', 'report_status',
                    'breached_essays', 'ai_recommendation', 'ai_generated_at',
                    'unitId_generated', 'componentName_generated', 'sampleDate_generated', 
                    'client_generated', 'sampleDate_str'}
    
    # Build comparison data
    analysis_data = []
    
    for col in sample.index:
        if col not in metadata_cols and pd.notna(sample[col]) and col in comp_limits:
            try:
                value = float(sample[col])
                normal = comp_limits[col].get('threshold_normal', 0)
                alert = comp_limits[col].get('threshold_alert', 0)
                critic = comp_limits[col].get('threshold_critic', 0)
                
                # Determine status
                if value >= critic:
                    status = 'Crítico'
                    color = '#dc3545'  # red
                elif value >= alert:
                    status = 'Condenatorio'
                    color = '#fd7e14'  # orange
                elif value >= normal:
                    status = 'Marginal'
                    color = '#ffc107'  # yellow
                else:
                    status = 'Normal'
                    color = '#28a745'  # green
                
                analysis_data.append({
                    'essay': col,
                    'value': round(value, 2),
                    'status': status,
                    'normal': round(normal, 2),
                    'alert': round(alert, 2),
                    'critic': round(critic, 2),
                    '_color': color
                })
            except:
                continue
    
    if not analysis_data:
        return html.P("No analysis data available", className="text-muted")
    
    # Sort by status severity
    status_order = {'Crítico': 0, 'Condenatorio': 1, 'Marginal': 2, 'Normal': 3}
    analysis_data.sort(key=lambda x: (status_order.get(x['status'], 4), x['essay']))
    
    # Create table
    return dash_table.DataTable(
        columns=[
            {'name': 'Essay', 'id': 'essay'},
            {'name': 'Value', 'id': 'value', 'type': 'numeric'},
            {'name': 'Status', 'id': 'status'},
            {'name': 'Normal', 'id': 'normal', 'type': 'numeric'},
            {'name': 'Alert', 'id': 'alert', 'type': 'numeric'},
            {'name': 'Critic', 'id': 'critic', 'type': 'numeric'}
        ],
        data=[{k: v for k, v in item.items() if k != '_color'} for item in analysis_data],
        style_cell={
            'textAlign': 'left',
            'padding': '8px',
            'fontSize': '12px',
            'overflow': 'hidden',
            'textOverflow': 'ellipsis',
            'maxWidth': 0
        },
        style_header={
            'backgroundColor': '#17a2b8',
            'color': 'white',
            'fontWeight': 'bold',
            'textAlign': 'center'
        },
        style_data_conditional=[
            {
                'if': {'row_index': i, 'column_id': 'status'},
                'backgroundColor': item['_color'],
                'color': 'white' if item['_color'] in ['#dc3545', '#17a2b8', '#28a745'] else 'black',
                'fontWeight': 'bold'
            }
            for i, item in enumerate(analysis_data)
        ],
        page_size=15,
        style_table={'overflowX': 'auto', 'maxHeight': '600px', 'overflowY': 'auto'}
    )


def create_historical_comparison(sample, df, equipo, component):
    """Create historical comparison table."""
    # Get history for this equipment and component
    history = df[(df['unitId'] == equipo) & (df['componentName'] == component)].sort_values('sampleDate', ascending=False)
    
    if len(history) < 2:
        return dbc.Alert("Need at least 2 reports for comparison", color="info")
    
    # Get current and previous report
    current = history.iloc[0]
    previous = history.iloc[1]
    
    # Compare dates
    current_date = pd.to_datetime(current['sampleDate']).strftime('%Y-%m-%d')
    previous_date = pd.to_datetime(previous['sampleDate']).strftime('%Y-%m-%d')
    
    # Get metadata columns to exclude
    metadata_cols = {'client', 'sampleNumber', 'sampleDate', 'unitId', 'machineName', 
                    'machineModel', 'machineBrand', 'machineHours', 'machineSerialNumber',
                    'componentName', 'componentHours', 'componentSerialNumber',
                    'oilMeter', 'oilBrand', 'oilType', 'oilWeight',
                    'previousSampleNumber', 'previousSampleDate', 'daysSincePrevious',
                    'group_element', 'essays_broken', 'severity_score', 'report_status',
                    'breached_essays', 'ai_recommendation', 'ai_generated_at',
                    'unitId_generated', 'componentName_generated', 'sampleDate_generated', 
                    'client_generated', 'sampleDate_str'}
    
    # Build comparison data
    comparison_data = []
    
    for col in current.index:
        if col not in metadata_cols and pd.notna(current[col]):
            try:
                current_val = float(current[col])
                previous_val = float(previous[col]) if pd.notna(previous.get(col)) else None
                
                if previous_val is not None:
                    change = current_val - previous_val
                    change_pct = (change / previous_val * 100) if previous_val != 0 else 0
                    
                    # Determine trend
                    if abs(change_pct) < 5:
                        trend = '→'
                        trend_color = ''
                    elif change_pct > 0:
                        trend = '↑'
                        trend_color = 'background-color: #ffebee' if change_pct > 20 else ''
                    else:
                        trend = '↓'
                        trend_color = 'background-color: #e8f5e9' if change_pct < -20 else ''
                    
                    comparison_data.append({
                        'essay': col,
                        'current': round(current_val, 2),
                        'previous': round(previous_val, 2),
                        'change': round(change, 2),
                        'change_pct': round(change_pct, 1),
                        'trend': trend,
                        '_color': trend_color
                    })
            except:
                continue
    
    if not comparison_data:
        return html.P("No comparison data available", className="text-muted")
    
    # Sort by absolute change percentage (descending)
    comparison_data.sort(key=lambda x: abs(x['change_pct']), reverse=True)
    comparison_data = comparison_data[:20]  # Top 20 changes
    
    # Create info cards
    info_cards = dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Current Report", className="text-muted mb-1"),
                    html.H5(current_date),
                    html.P(f"Status: {current.get('report_status', 'N/A')}", className="mb-0")
                ])
            ])
        ], width=6),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Previous Report", className="text-muted mb-1"),
                    html.H5(previous_date),
                    html.P(f"Status: {previous.get('report_status', 'N/A')}", className="mb-0")
                ])
            ])
        ], width=6)
    ], className="mb-3")
    
    # Create comparison table
    table = dash_table.DataTable(
        columns=[
            {'name': 'Essay', 'id': 'essay'},
            {'name': 'Current', 'id': 'current', 'type': 'numeric'},
            {'name': 'Previous', 'id': 'previous', 'type': 'numeric'},
            {'name': 'Change', 'id': 'change', 'type': 'numeric'},
            {'name': 'Change %', 'id': 'change_pct', 'type': 'numeric'},
            {'name': 'Trend', 'id': 'trend'}
        ],
        data=[{k: v for k, v in item.items() if k != '_color'} for item in comparison_data],
        style_cell={'textAlign': 'center', 'padding': '8px', 'fontSize': '12px'},
        style_header={
            'backgroundColor': '#6c757d',
            'color': 'white',
            'fontWeight': 'bold'
        },
        style_data_conditional=[
            {
                'if': {'row_index': i},
                'backgroundColor': item['_color'].split(': ')[1] if item['_color'] else ''
            }
            for i, item in enumerate(comparison_data) if item['_color']
        ],
        page_size=10
    )
    
    return html.Div([info_cards, table])


def create_ai_recommendation_display(sample):
    """Create AI recommendation display."""
    ai_rec = sample.get('ai_recommendation', 'No AI recommendation available for this sample.')
    
    status_color = {
        'Anormal': 'danger',
        'Alerta': 'warning',
        'Normal': 'success'
    }.get(sample.get('report_status', 'Normal'), 'light')
    
    return dbc.Alert([
        html.H6("🤖 AI Analysis:", className="alert-heading"),
        html.Hr(),
        html.P(ai_rec, style={'whiteSpace': 'pre-wrap'})
    ], color=status_color)


def get_essay_options(df):
    """Get essay column options for time series."""
    metadata_cols = {'client', 'sampleNumber', 'sampleDate', 'unitId', 'machineName', 
                    'machineModel', 'machineBrand', 'machineHours', 'machineSerialNumber',
                    'componentName', 'componentHours', 'componentSerialNumber',
                    'oilMeter', 'oilBrand', 'oilType', 'oilWeight',
                    'previousSampleNumber', 'previousSampleDate', 'daysSincePrevious',
                    'group_element', 'essays_broken', 'severity_score', 'report_status',
                    'breached_essays', 'ai_recommendation', 'ai_generated_at',
                    'unitId_generated', 'componentName_generated', 'sampleDate_generated', 'client_generated'}
    essays = [col for col in df.columns if col not in metadata_cols]
    return [{'label': e, 'value': e} for e in sorted(essays)]
