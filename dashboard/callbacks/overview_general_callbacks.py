"""
Callbacks for Overview General tab.
Handles data loading and visualization for consolidated executive summary.
"""

from dash import callback, Output, Input, State, html, dash_table
from dash.exceptions import PreventUpdate
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pathlib import Path
import logging

from src.utils.file_utils import safe_read_parquet
from src.data.loaders import load_telemetry_machine_status
from src.data.maintenance_repository import get_repository

logger = logging.getLogger(__name__)


def calculate_alert_criticality_score(df_alerts: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    """
    Calculate equipment criticality score based on recent alerts.
    
    Formula: More alerts for same equipment/component = higher criticality
    
    Args:
        df_alerts: DataFrame with alert data
        days: Number of days to consider recent alerts
        
    Returns:
        DataFrame with equipment, alert_count, component_count, score, and status
    """
    cutoff_date = datetime.now() - timedelta(days=days)
    
    # Filter recent alerts
    recent = df_alerts[df_alerts['fecha_alerta'] >= cutoff_date].copy() if 'fecha_alerta' in df_alerts.columns else df_alerts
    
    if recent.empty:
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])
    
    # Group by equipment and component
    grouped = recent.groupby(['equipo', 'componente']).size().reset_index(name='alerts_per_component')
    
    # Calculate metrics per equipment
    equipment_stats = grouped.groupby('equipo').agg({
        'alerts_per_component': 'sum',  # Total alerts
        'componente': 'nunique'  # Number of affected components
    }).reset_index()
    
    equipment_stats.columns = ['equipo', 'alert_count', 'component_count']
    
    # Criticality score: alerts * component diversity factor
    equipment_stats['criticality_score'] = (
        equipment_stats['alert_count'] * 
        (1 + equipment_stats['component_count'] * 0.5)
    ).round(1)
    
    # Categorize status
    def categorize_status(score):
        if score == 0:
            return 'Normal'
        elif score <= 5:
            return 'Atención'
        elif score <= 15:
            return 'Alerta'
        else:
            return 'Crítico'
    
    equipment_stats['status'] = equipment_stats['criticality_score'].apply(categorize_status)
    
    return equipment_stats.sort_values('criticality_score', ascending=False)


def create_telemetry_bar_chart(df_telemetry: pd.DataFrame) -> go.Figure:
    """
    Create compact bar chart showing fleet status distribution from telemetry.
    
    Args:
        df_telemetry: DataFrame with telemetry machine status
        
    Returns:
        Plotly figure
    """
    if df_telemetry.empty:
        return create_empty_figure("No hay datos")
    
    # Count by status
    status_col = 'Estado' if 'Estado' in df_telemetry.columns else 'status'
    status_counts = df_telemetry[status_col].value_counts().reset_index()
    status_counts.columns = ['Estado', 'Cantidad']
    
    # Color mapping
    color_map = {
        'Normal': '#28a745',
        'Alerta': '#ffc107',
        'Anormal': '#dc3545',
        'Sin Datos': '#6c757d'
    }
    
    colors = [color_map.get(status, '#3498db') for status in status_counts['Estado']]
    
    fig = go.Figure(data=[
        go.Bar(
            x=status_counts['Estado'],
            y=status_counts['Cantidad'],
            marker_color=colors,
            text=status_counts['Cantidad'],
            textposition='auto',
            textfont=dict(size=14, color='white'),
            hovertemplate='<b>%{x}</b><br>%{y} equipos<extra></extra>'
        )
    ])
    
    fig.update_layout(
        title=None,
        xaxis_title=None,
        yaxis_title=None,
        height=220,
        margin=dict(l=30, r=10, t=10, b=40),
        plot_bgcolor='white',
        showlegend=False,
        font=dict(size=11)
    )
    
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor='#f0f0f0', showticklabels=True)
    
    return fig


def create_maintenance_bar_chart(df_status: pd.DataFrame, df_downtime: pd.DataFrame) -> go.Figure:
    """
    Create compact grouped bar chart showing operational vs stopped equipment with MTD.
    
    Args:
        df_status: DataFrame with status counts
        df_downtime: DataFrame with downtime MTD data
        
    Returns:
        Plotly figure
    """
    if df_status.empty:
        return create_empty_figure("No hay datos")
    
    # Get counts
    sanos = df_status[df_status['machine_status'] == 'SANO']['n_machines'].sum() if not df_status.empty else 0
    detenidos = df_status[df_status['machine_status'] == 'DETENIDO']['n_machines'].sum() if not df_status.empty else 0
    
    # Get MTD
    mtd_hours = df_downtime['total_downtime_hours_mtd'].iloc[0] if not df_downtime.empty else 0
    
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        name='Sanos',
        x=['Status'],
        y=[sanos],
        text=[f'{sanos}'],
        textposition='inside',
        textfont=dict(size=16, color='white'),
        marker_color='#28a745',
        hovertemplate='<b>Operativos</b><br>%{y} equipos<extra></extra>'
    ))
    
    fig.add_trace(go.Bar(
        name=f'Detenidos ({mtd_hours:.0f}h)',
        x=['Status'],
        y=[detenidos],
        text=[f'{detenidos}'],
        textposition='inside',
        textfont=dict(size=16, color='white'),
        marker_color='#dc3545',
        hovertemplate=f'<b>Detenidos</b><br>%{{y}} equipos<br>MTD: {mtd_hours:.1f}h<extra></extra>'
    ))
    
    fig.update_layout(
        title=None,
        barmode='group',
        height=220,
        margin=dict(l=10, r=10, t=10, b=30),
        plot_bgcolor='white',
        showlegend=True,
        legend=dict(
            orientation="h", 
            yanchor="bottom", 
            y=1.02, 
            xanchor="center", 
            x=0.5,
            font=dict(size=10)
        ),
        font=dict(size=11)
    )
    
    fig.update_xaxes(showgrid=False, showticklabels=False)
    fig.update_yaxes(showgrid=True, gridcolor='#f0f0f0', showticklabels=True)
    
    return fig


def create_oil_pie_chart(df_oil: pd.DataFrame) -> go.Figure:
    """
    Create compact donut chart showing oil analysis status distribution.
    
    Args:
        df_oil: DataFrame with oil analysis data
        
    Returns:
        Plotly figure
    """
    if df_oil.empty or 'estado' not in df_oil.columns:
        return create_empty_figure("No hay datos")
    
    # Count by status and get unique machines
    df_unique = df_oil.drop_duplicates(subset=['equipo']) if 'equipo' in df_oil.columns else df_oil
    status_counts = df_unique['estado'].value_counts()
    
    # Color mapping
    colors = {
        'NORMAL': '#28a745',
        'ANORMAL': '#dc3545',
        'ALERTA': '#ffc107'
    }
    
    color_list = [colors.get(status, '#6c757d') for status in status_counts.index]
    
    fig = go.Figure(data=[go.Pie(
        labels=status_counts.index,
        values=status_counts.values,
        marker_colors=color_list,
        hole=0.5,
        textposition='inside',
        textinfo='value',
        textfont=dict(size=14, color='white'),
        hovertemplate='<b>%{label}</b><br>%{value} equipos (%{percent})<extra></extra>'
    )])
    
    fig.update_layout(
        title=None,
        height=220,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.05,
            font=dict(size=10)
        ),
        font=dict(size=11)
    )
    
    return fig


def create_oil_ranking_table(df_oil: pd.DataFrame) -> html.Div:
    """
    Create compact ranking table of top 10 critical equipment based on oil analysis.
    
    Args:
        df_oil: DataFrame with oil analysis data
        
    Returns:
        Dash DataTable component
    """
    if df_oil.empty:
        return html.Div(html.P("No hay datos disponibles", className="text-muted text-center p-2 mb-0", style={'fontSize': '12px'}))
    
    # Filter abnormal/alert status
    critical = df_oil[df_oil['estado'].isin(['ANORMAL', 'ALERTA'])].copy()
    
    if critical.empty:
        return html.Div(html.P("✓ No hay equipos críticos", className="text-success text-center p-2 mb-0", style={'fontSize': '12px'}))
    
    # Get unique equipment and their worst status
    if 'equipo' in critical.columns:
        # Group by equipment and get the worst status
        status_priority = {'ANORMAL': 2, 'ALERTA': 1, 'NORMAL': 0}
        critical['priority'] = critical['estado'].map(status_priority)
        top_critical = critical.groupby('equipo').agg({
            'estado': 'first',
            'priority': 'max'
        }).reset_index()
        top_critical = top_critical.sort_values('priority', ascending=False).head(10)
        top_critical = top_critical[['equipo', 'estado']]
        top_critical.columns = ['Equipo', 'Estado']
    else:
        return html.Div(html.P("Formato de datos incorrecto", className="text-muted text-center p-2 mb-0", style={'fontSize': '12px'}))
    
    return dash_table.DataTable(
        data=top_critical.to_dict('records'),
        columns=[{'name': col, 'id': col} for col in top_critical.columns],
        style_table={'overflowX': 'auto', 'height': '180px', 'overflowY': 'auto'},
        style_header={
            'backgroundColor': '#f8f9fa',
            'fontWeight': 'bold',
            'textAlign': 'center',
            'fontSize': '11px',
            'padding': '6px'
        },
        style_cell={
            'textAlign': 'center',
            'padding': '6px',
            'fontSize': '11px',
            'whiteSpace': 'normal',
            'height': 'auto'
        },
        style_data_conditional=[
            {
                'if': {'filter_query': '{Estado} = "ANORMAL"', 'column_id': 'Estado'},
                'backgroundColor': '#dc3545',
                'color': 'white',
                'fontWeight': 'bold'
            },
            {
                'if': {'filter_query': '{Estado} = "ALERTA"', 'column_id': 'Estado'},
                'backgroundColor': '#ffc107',
                'color': '#000',
                'fontWeight': 'bold'
            }
        ]
    )


def create_alerts_bar_chart(df_alerts: pd.DataFrame, days: int = 30) -> go.Figure:
    """
    Create compact bar chart showing top 10 critical equipment by alert frequency.
    
    Args:
        df_alerts: DataFrame with alerts data
        days: Number of days to consider
        
    Returns:
        Plotly figure
    """
    if df_alerts.empty:
        return create_empty_figure("No hay datos")
    
    # Calculate criticality scores
    equipment_scores = calculate_alert_criticality_score(df_alerts, days)
    
    if equipment_scores.empty:
        return create_empty_figure(f"Sin alertas ({days}d)")
    
    # Get top 10 for compact view
    top_10 = equipment_scores.head(10)
    
    # Color by status
    color_map = {
        'Crítico': '#dc3545',
        'Alerta': '#ffc107',
        'Atención': '#17a2b8',
        'Normal': '#28a745'
    }
    
    colors = [color_map.get(status, '#6c757d') for status in top_10['status']]
    
    fig = go.Figure(data=[
        go.Bar(
            x=top_10['equipo'],
            y=top_10['criticality_score'],
            marker_color=colors,
            text=top_10['alert_count'],
            textposition='inside',
            textfont=dict(size=11, color='white'),
            hovertemplate='<b>%{x}</b><br>Score: %{y:.1f}<br>Alertas: %{customdata[0]}<br>Componentes: %{customdata[1]}<extra></extra>',
            customdata=top_10[['alert_count', 'component_count']].values
        )
    ])
    
    fig.update_layout(
        title=None,
        xaxis_title=None,
        yaxis_title=None,
        height=180,
        margin=dict(l=30, r=10, t=10, b=50),
        plot_bgcolor='white',
        showlegend=False,
        font=dict(size=10)
    )
    
    fig.update_xaxes(showgrid=False, tickangle=-45, tickfont=dict(size=9))
    fig.update_yaxes(showgrid=True, gridcolor='#f0f0f0', showticklabels=True)
    
    return fig


def create_summary_table(df_telemetry: pd.DataFrame, df_maintenance: pd.DataFrame, 
                         df_oil: pd.DataFrame, df_alerts: pd.DataFrame) -> html.Div:
    """
    Create comprehensive summary table combining all technical areas.
    
    Args:
        df_telemetry: Telemetry data
        df_maintenance: Maintenance data
        df_oil: Oil analysis data
        df_alerts: Alerts data
        
    Returns:
        Dash DataTable component
    """
    try:
        # Build summary by equipment
        summary_data = []
        
        # Get unique equipment from all sources
        equipos = set()
        if not df_telemetry.empty and 'Unidad' in df_telemetry.columns:
            equipos.update(df_telemetry['Unidad'].unique())
        if not df_alerts.empty and 'equipo' in df_alerts.columns:
            equipos.update(df_alerts['equipo'].unique())
        
        alert_scores = calculate_alert_criticality_score(df_alerts, 30) if not df_alerts.empty else pd.DataFrame()
        
        for equipo in sorted(equipos):
            # Telemetry status
            telem_status = 'N/A'
            if not df_telemetry.empty and 'Unidad' in df_telemetry.columns:
                equipo_telem = df_telemetry[df_telemetry['Unidad'] == equipo]
                if not equipo_telem.empty:
                    telem_status = equipo_telem['Estado'].iloc[0]
            
            # Oil status
            oil_status = 'N/A'
            if not df_oil.empty and 'equipo' in df_oil.columns:
                equipo_oil = df_oil[df_oil['equipo'] == equipo]
                if not equipo_oil.empty:
                    oil_status = equipo_oil['estado'].iloc[0]
            
            # Alert score
            alert_score = 0
            alert_status = 'Normal'
            if not alert_scores.empty:
                equipo_alerts = alert_scores[alert_scores['equipo'] == equipo]
                if not equipo_alerts.empty:
                    alert_score = equipo_alerts['criticality_score'].iloc[0]
                    alert_status = equipo_alerts['status'].iloc[0]
            
            summary_data.append({
                'Equipo': equipo,
                'Telemetría': telem_status,
                'Aceite': oil_status,
                'Score Alertas': f"{alert_score:.1f}",
                'Estado Alertas': alert_status
            })
        
        df_summary = pd.DataFrame(summary_data)
        
        if df_summary.empty:
            return html.P("No hay datos disponibles", className="text-muted text-center p-3")
        
        return dash_table.DataTable(
            data=df_summary.to_dict('records'),
            columns=[{'name': col, 'id': col} for col in df_summary.columns],
            sort_action='native',
            filter_action='native',
            page_size=20,
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
                # Telemetry status colors
                {
                    'if': {
                        'filter_query': '{Telemetría} = "Anormal"',
                        'column_id': 'Telemetría'
                    },
                    'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                    'color': '#dc3545',
                    'fontWeight': 'bold'
                },
                {
                    'if': {
                        'filter_query': '{Telemetría} = "Alerta"',
                        'column_id': 'Telemetría'
                    },
                    'backgroundColor': 'rgba(255, 193, 7, 0.1)',
                    'color': '#856404',
                    'fontWeight': 'bold'
                },
                # Oil status colors
                {
                    'if': {
                        'filter_query': '{Aceite} = "ANORMAL"',
                        'column_id': 'Aceite'
                    },
                    'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                    'color': '#dc3545',
                    'fontWeight': 'bold'
                },
                {
                    'if': {
                        'filter_query': '{Aceite} = "ALERTA"',
                        'column_id': 'Aceite'
                    },
                    'backgroundColor': 'rgba(255, 193, 7, 0.1)',
                    'color': '#856404',
                    'fontWeight': 'bold'
                },
                # Alert status colors
                {
                    'if': {
                        'filter_query': '{Estado Alertas} = "Crítico"',
                        'column_id': 'Estado Alertas'
                    },
                    'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                    'color': '#dc3545',
                    'fontWeight': 'bold'
                },
                {
                    'if': {
                        'filter_query': '{Estado Alertas} = "Alerta"',
                        'column_id': 'Estado Alertas'
                    },
                    'backgroundColor': 'rgba(255, 193, 7, 0.1)',
                    'color': '#856404',
                    'fontWeight': 'bold'
                }
            ]
        )
    except Exception as e:
        logger.error(f"Error creating summary table: {e}", exc_info=True)
        return html.P("Error al generar tabla resumen", className="text-danger text-center p-3")


def create_empty_figure(message: str) -> go.Figure:
    """
    Create empty figure with message.
    
    Args:
        message: Message to display
        
    Returns:
        Empty Plotly figure
    """
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=14, color="gray")
    )
    fig.update_layout(
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        plot_bgcolor='white',
        height=300
    )
    return fig


def register_overview_general_callbacks(app):
    """
    Register all callbacks for Overview General tab.
    
    Args:
        app: Dash application instance
    """
    
    @callback(
        [
            Output("store-overview-data", "data"),
            Output("store-overview-timestamp", "data"),
        ],
        [
            Input("btn-refresh-overview", "n_clicks"),
            Input("client-selector", "value"),
        ],
        prevent_initial_call=False
    )
    def load_overview_data(n_clicks, client):
        """
        Load all data for the overview general tab.
        Uses the most recent available data for each technical area.
        """
        if not client:
            raise PreventUpdate
        
        try:
            logger.info(f"Loading overview data for client: {client}")
            
            # Initialize metadata variables
            telemetry_latest = "N/A"
            oil_latest = "N/A"
            alerts_period = "N/A"
            
            # Load Telemetry data (most recent week/year available)
            df_telemetry = load_telemetry_machine_status(client)
            if not df_telemetry.empty:
                # Get most recent week/year combination
                if 'Semana' in df_telemetry.columns and 'Año' in df_telemetry.columns:
                    most_recent = df_telemetry.sort_values(['Año', 'Semana'], ascending=False).iloc[0]
                    latest_year = most_recent['Año']
                    latest_week = most_recent['Semana']
                    df_telemetry = df_telemetry[
                        (df_telemetry['Año'] == latest_year) & 
                        (df_telemetry['Semana'] == latest_week)
                    ]
                    telemetry_latest = f"Semana {latest_week}, Año {latest_year}"
                    logger.info(f"Telemetry: Using most recent data - {telemetry_latest}")
            
            # Load Maintenance data (already filtered by MTD)
            repo = get_repository(mode="parquet")
            df_status = repo.get_status_counts()
            df_downtime = repo.get_downtime_mtd()
            logger.info(f"Maintenance: Loaded {len(df_status)} status records")
            
            # Load Oil analysis data (most recent sample per equipment)
            reports_file = f'data/oil/golden/{client.lower()}/classified.parquet'
            df_oil = safe_read_parquet(Path(reports_file))
            if df_oil is None or df_oil.empty:
                df_oil = pd.DataFrame()
            else:
                # Get most recent analysis per equipment
                if 'sampleDate' in df_oil.columns and 'unitId' in df_oil.columns:
                    df_oil['sampleDate'] = pd.to_datetime(df_oil['sampleDate'])
                    # Get the most recent sample for each equipment
                    df_oil = df_oil.sort_values('sampleDate', ascending=False)
                    df_oil = df_oil.groupby('unitId').first().reset_index()
                    latest_date = df_oil['sampleDate'].max()
                    oil_latest = latest_date.strftime("%Y-%m-%d")
                    logger.info(f"Oil Analysis: Using most recent data - Latest sample: {oil_latest}")
                
                # Map report_status to estado if needed
                if 'report_status' in df_oil.columns and 'estado' not in df_oil.columns:
                    status_mapping = {
                        'Normal': 'NORMAL',
                        'Alerta': 'ALERTA',
                        'Anormal': 'ANORMAL',
                        'Crítico': 'ANORMAL'
                    }
                    df_oil['estado'] = df_oil['report_status'].map(status_mapping).fillna('NORMAL')
                
                # Rename unitId to equipo for consistency
                if 'unitId' in df_oil.columns and 'equipo' not in df_oil.columns:
                    df_oil['equipo'] = df_oil['unitId']
            
            # Load Alerts data (recent alerts only - last 60 days by default)
            alerts_file = f'data/alerts/golden/{client.lower()}/consolidated_alerts.csv'
            try:
                df_alerts = pd.read_csv(alerts_file)
                if 'Timestamp' in df_alerts.columns:
                    df_alerts['Timestamp'] = pd.to_datetime(df_alerts['Timestamp'])
                    # Filter last 60 days
                    cutoff_date = datetime.now() - timedelta(days=60)
                    df_alerts = df_alerts[df_alerts['Timestamp'] >= cutoff_date]
                    alerts_period = "Últimos 60 días"
                    logger.info(f"Alerts: Using recent data - {alerts_period}, {len(df_alerts)} alerts")
                
                # Rename columns for consistency
                if 'Unidad' in df_alerts.columns and 'equipo' not in df_alerts.columns:
                    df_alerts['equipo'] = df_alerts['Unidad']
                if 'Componente' in df_alerts.columns and 'componente' not in df_alerts.columns:
                    df_alerts['componente'] = df_alerts['Componente']
                if 'Timestamp' in df_alerts.columns and 'fecha_alerta' not in df_alerts.columns:
                    df_alerts['fecha_alerta'] = df_alerts['Timestamp']
            except FileNotFoundError:
                logger.warning(f"Alerts file not found: {alerts_file}")
                df_alerts = pd.DataFrame()
            except Exception as e:
                logger.error(f"Error loading alerts: {e}")
                df_alerts = pd.DataFrame()
            
            # Serialize to JSON with metadata about data freshness
            data = {
                "telemetry": df_telemetry.to_dict("records") if not df_telemetry.empty else [],
                "maintenance_status": df_status.to_dict("records") if not df_status.empty else [],
                "maintenance_downtime": df_downtime.to_dict("records") if not df_downtime.empty else [],
                "oil": df_oil.to_dict("records") if not df_oil.empty else [],
                "alerts": df_alerts.to_dict("records") if not df_alerts.empty else [],
                "metadata": {
                    "telemetry_latest": telemetry_latest,
                    "oil_latest": oil_latest,
                    "alerts_period": alerts_period,
                    "maintenance": "MTD (Month to Date)"
                }
            }
            
            timestamp = datetime.now().isoformat()
            logger.info("Overview data loaded successfully with latest available data")
            
            return data, timestamp
            
        except Exception as e:
            logger.error(f"Error loading overview data: {e}", exc_info=True)
            return {}, None
    
    @callback(
        [
            Output("overview-kpi-total", "children"),
            Output("overview-kpi-operational", "children"),
            Output("overview-kpi-warning", "children"),
            Output("overview-kpi-critical", "children"),
        ],
        [Input("store-overview-data", "data")]
    )
    def update_global_kpis(data):
        """Update global KPI cards."""
        if not data:
            return "0", "0", "0", "0"
        
        try:
            # Parse data
            df_telemetry = pd.DataFrame(data.get("telemetry", []))
            df_status = pd.DataFrame(data.get("maintenance_status", []))
            df_alerts = pd.DataFrame(data.get("alerts", []))
            
            # Total equipment (from telemetry or maintenance)
            total = len(df_telemetry) if not df_telemetry.empty else df_status['n_machines'].sum() if not df_status.empty else 0
            
            # Operational equipment
            operational = 0
            if not df_telemetry.empty and 'Estado' in df_telemetry.columns:
                operational = (df_telemetry['Estado'] == 'Normal').sum()
            elif not df_status.empty:
                operational = df_status[df_status['machine_status'] == 'SANO']['n_machines'].sum()
            
            # Warning equipment (Alerta status in telemetry)
            warning = 0
            if not df_telemetry.empty and 'Estado' in df_telemetry.columns:
                warning = (df_telemetry['Estado'] == 'Alerta').sum()
            
            # Critical equipment (Anormal in telemetry or high alert score)
            critical = 0
            if not df_telemetry.empty and 'Estado' in df_telemetry.columns:
                critical = (df_telemetry['Estado'] == 'Anormal').sum()
            
            # Add critical from alerts
            if not df_alerts.empty:
                alert_scores = calculate_alert_criticality_score(df_alerts, 30)
                if not alert_scores.empty:
                    critical += (alert_scores['status'] == 'Crítico').sum()
            
            return str(total), str(operational), str(warning), str(critical)
            
        except Exception as e:
            logger.error(f"Error updating global KPIs: {e}")
            return "Error", "Error", "Error", "Error"
    
    @callback(
        Output("overview-telemetry-chart", "figure"),
        [Input("store-overview-data", "data")]
    )
    def update_telemetry_chart(data):
        """Update telemetry fleet status chart."""
        if not data or not data.get("telemetry"):
            return create_empty_figure("No hay datos de telemetría disponibles")
        
        try:
            df_telemetry = pd.DataFrame(data["telemetry"])
            return create_telemetry_bar_chart(df_telemetry)
        except Exception as e:
            logger.error(f"Error updating telemetry chart: {e}")
            return create_empty_figure("Error al cargar gráfico")
    
    @callback(
        Output("overview-maintenance-chart", "figure"),
        [Input("store-overview-data", "data")]
    )
    def update_maintenance_chart(data):
        """Update maintenance operational status chart."""
        if not data:
            return create_empty_figure("No hay datos de mantenciones disponibles")
        
        try:
            df_status = pd.DataFrame(data.get("maintenance_status", []))
            df_downtime = pd.DataFrame(data.get("maintenance_downtime", []))
            return create_maintenance_bar_chart(df_status, df_downtime)
        except Exception as e:
            logger.error(f"Error updating maintenance chart: {e}")
            return create_empty_figure("Error al cargar gráfico")
    
    @callback(
        Output("overview-oil-chart", "figure"),
        [Input("store-overview-data", "data")]
    )
    def update_oil_chart(data):
        """Update oil analysis pie chart."""
        if not data or not data.get("oil"):
            return create_empty_figure("No hay datos de análisis de aceite")
        
        try:
            df_oil = pd.DataFrame(data["oil"])
            return create_oil_pie_chart(df_oil)
        except Exception as e:
            logger.error(f"Error updating oil chart: {e}")
            return create_empty_figure("Error al cargar gráfico")
    
    @callback(
        Output("overview-oil-ranking-table", "children"),
        [Input("store-overview-data", "data")]
    )
    def update_oil_ranking(data):
        """Update oil analysis ranking table."""
        if not data or not data.get("oil"):
            return html.P("No hay datos disponibles", className="text-muted text-center p-3")
        
        try:
            df_oil = pd.DataFrame(data["oil"])
            return create_oil_ranking_table(df_oil)
        except Exception as e:
            logger.error(f"Error updating oil ranking: {e}")
            return html.P("Error al cargar ranking", className="text-danger text-center p-3")
    
    @callback(
        Output("overview-alerts-chart", "figure"),
        [
            Input("store-overview-data", "data"),
            Input("overview-alerts-days-filter", "value")
        ]
    )
    def update_alerts_chart(data, days):
        """Update alerts critical equipment chart."""
        if not data or not data.get("alerts"):
            return create_empty_figure("No hay datos de alertas disponibles")
        
        try:
            df_alerts = pd.DataFrame(data["alerts"])
            return create_alerts_bar_chart(df_alerts, days)
        except Exception as e:
            logger.error(f"Error updating alerts chart: {e}")
            return create_empty_figure("Error al cargar gráfico")
    
    @callback(
        Output("overview-summary-table", "children"),
        [Input("store-overview-data", "data")]
    )
    def update_summary_table(data):
        """Update comprehensive summary table."""
        if not data:
            return html.P("No hay datos disponibles", className="text-muted text-center p-3")
        
        try:
            df_telemetry = pd.DataFrame(data.get("telemetry", []))
            df_status = pd.DataFrame(data.get("maintenance_status", []))
            df_oil = pd.DataFrame(data.get("oil", []))
            df_alerts = pd.DataFrame(data.get("alerts", []))
            
            return create_summary_table(df_telemetry, df_status, df_oil, df_alerts)
        except Exception as e:
            logger.error(f"Error updating summary table: {e}")
            return html.P("Error al cargar tabla", className="text-danger text-center p-3")
    
    @callback(
        Output("overview-last-update", "children"),
        [Input("store-overview-timestamp", "data")]
    )
    def update_timestamp(timestamp):
        """Update last update timestamp."""
        if not timestamp:
            return "N/A"
        
        try:
            dt = datetime.fromisoformat(timestamp)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.error(f"Error formatting timestamp: {e}")
            return "Error"
    
    @callback(
        [
            Output("overview-telemetry-timestamp", "children"),
            Output("overview-maintenance-timestamp", "children"),
            Output("overview-oil-timestamp", "children"),
            Output("overview-alerts-timestamp", "children"),
        ],
        [Input("store-overview-data", "data")]
    )
    def update_section_timestamps(data):
        """Update individual section timestamps with data freshness info."""
        if not data or 'metadata' not in data:
            return "", "", "", ""
        
        try:
            metadata = data['metadata']
            
            telemetry_ts = f"📅 {metadata.get('telemetry_latest', 'N/A')}" if metadata.get('telemetry_latest') != 'N/A' else ""
            maintenance_ts = f"📅 {metadata.get('maintenance', 'MTD')}"
            oil_ts = f"📅 {metadata.get('oil_latest', 'N/A')}" if metadata.get('oil_latest') != 'N/A' else ""
            alerts_ts = f"📅 {metadata.get('alerts_period', 'N/A')}" if metadata.get('alerts_period') != 'N/A' else ""
            
            return telemetry_ts, maintenance_ts, oil_ts, alerts_ts
        except Exception as e:
            logger.error(f"Error updating section timestamps: {e}")
            return "", "", "", ""
