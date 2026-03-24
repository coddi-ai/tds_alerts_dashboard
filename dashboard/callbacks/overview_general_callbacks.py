"""
Callbacks for Overview General tab.
Handles data loading and visualization for consolidated executive summary.
"""

from dash import callback, Output, Input, State, html, dash_table
from dash.exceptions import PreventUpdate
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pathlib import Path
import logging

from src.utils.file_utils import safe_read_parquet
from src.data.loaders import load_telemetry_machine_status, load_alerts_data
from src.data.maintenance_repository import get_repository

logger = logging.getLogger(__name__)


def clean_numpy_types(data):
    """
    Recursively clean numpy types from nested data structures to make them JSON serializable.
    Converts numpy arrays to lists and numpy types to Python native types.
    Also handles pandas Timestamp and Period types.
    
    Args:
        data: The data structure to clean (dict, list, numpy types, etc.)
        
    Returns:
        Cleaned data structure with Python native types only
    """
    if isinstance(data, dict):
        return {key: clean_numpy_types(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [clean_numpy_types(item) for item in data]
    elif isinstance(data, np.ndarray):
        return [clean_numpy_types(item) for item in data.tolist()]
    elif isinstance(data, (np.integer, np.floating)):
        return data.item()
    elif isinstance(data, np.bool_):
        return bool(data)
    elif isinstance(data, (pd.Timestamp, pd.Period)):
        return str(data)
    elif pd.isna(data):
        return None
    else:
        return data


def calculate_alert_criticality_score(df_alerts: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    """
    Calculate equipment criticality score based on recent alerts.
    
    Formula: More alerts for same equipment/component = higher criticality
    
    Args:
        df_alerts: DataFrame with alert data (using real columns: Timestamp, Unidad, Componente)
        days: Number of days to consider recent alerts
        
    Returns:
        DataFrame with equipment, alert_count, component_count, score, and status
    """
    if df_alerts.empty:
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])
    
    # Use correct column names from load_alerts_data
    if 'Timestamp' not in df_alerts.columns:
        logger.warning(f"Column 'Timestamp' not found. Available: {df_alerts.columns.tolist()}")
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])
    
    cutoff_date = datetime.now() - timedelta(days=days)
    
    # Ensure Timestamp is datetime (it might be string after clean_numpy_types)
    if 'Timestamp' in df_alerts.columns:
        df_alerts['Timestamp'] = pd.to_datetime(df_alerts['Timestamp'])
    
    # Filter recent alerts
    recent = df_alerts[df_alerts['Timestamp'] >= cutoff_date].copy()
    
    if recent.empty:
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])
    
    # Use correct column names: UnitId (equipment) and componente (component)
    if 'UnitId' not in recent.columns or 'componente' not in recent.columns:
        logger.warning(f"Required columns not found. Available: {recent.columns.tolist()}")
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])
    
    # Group by equipment and component
    grouped = recent.groupby(['UnitId', 'componente']).size().reset_index(name='alerts_per_component')
    
    # Calculate metrics per equipment
    equipment_stats = grouped.groupby('UnitId').agg({
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


def create_telemetry_pie_chart(df_telemetry: pd.DataFrame) -> go.Figure:
    """
    Create compact pie chart showing fleet status distribution from telemetry.
    
    Args:
        df_telemetry: DataFrame with telemetry machine status (using real columns: overall_status)
        
    Returns:
        Plotly figure
    """
    if df_telemetry.empty:
        return create_empty_figure("No hay datos")
    
    # Use correct column name from load_telemetry_machine_status
    if 'overall_status' not in df_telemetry.columns:
        logger.warning(f"Column 'overall_status' not found. Available: {df_telemetry.columns.tolist()}")
        return create_empty_figure("Datos incompletos")
    
    # Count by status
    status_counts = df_telemetry['overall_status'].value_counts()
    
    # Color mapping (matching telemetry status values)
    color_map = {
        'Normal': '#28a745',
        'Alerta': '#ffc107',
        'Anormal': '#dc3545',
        'Sin Datos': '#6c757d'
    }
    
    colors = [color_map.get(status, '#3498db') for status in status_counts.index]
    
    fig = go.Figure(data=[go.Pie(
        labels=status_counts.index,
        values=status_counts.values,
        marker_colors=colors,
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


def create_maintenance_pie_chart(df_status: pd.DataFrame, df_downtime: pd.DataFrame) -> go.Figure:
    """
    Create compact pie chart showing operational vs stopped equipment.
    
    Args:
        df_status: DataFrame with status counts
        df_downtime: DataFrame with downtime MTD data
        
    Returns:
        Plotly figure
    """
    if df_status.empty:
        return create_empty_figure("No hay datos")
    
    # Get counts
    sanos = int(df_status[df_status['machine_status'] == 'SANO']['n_machines'].sum()) if not df_status.empty else 0
    detenidos = int(df_status[df_status['machine_status'] == 'DETENIDO']['n_machines'].sum()) if not df_status.empty else 0
    
    # Get MTD
    mtd_hours = df_downtime['total_downtime_hours_mtd'].iloc[0] if not df_downtime.empty else 0
    
    labels = ['Operativos', f'Detenidos ({mtd_hours:.0f}h MTD)']
    values = [sanos, detenidos]
    colors = ['#28a745', '#dc3545']
    
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        marker_colors=colors,
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


def create_critical_equipment_summary_table(df_telemetry: pd.DataFrame, df_oil: pd.DataFrame, 
                                            df_alerts: pd.DataFrame, df_maintenance: pd.DataFrame) -> html.Div:
    """
    Create summary table showing only equipment with problems across all technical areas.
    
    Format: Unidad | Tribología | Telemetría | Alertas | Mantenciones | Estado General
    
    Args:
        df_telemetry: Telemetry data
        df_oil: Oil analysis data
        df_alerts: Alerts data
        df_maintenance: Maintenance data
        
    Returns:
        Dash DataTable component with only critical/warning equipment
    """
    if df_telemetry.empty and df_oil.empty and df_alerts.empty and df_maintenance.empty:
        return html.Div(html.P("No hay datos disponibles", className="text-muted text-center p-2 mb-0", style={'fontSize': '12px'}))
    
    try:
        summary_data = []
        
        # Get unique equipment from all sources
        equipos = set()
        if not df_telemetry.empty and 'unit_id' in df_telemetry.columns:
            equipos.update(df_telemetry['unit_id'].unique())
        if not df_oil.empty and 'equipo' in df_oil.columns:
            equipos.update(df_oil['equipo'].unique())
        if not df_alerts.empty and 'UnitId' in df_alerts.columns:
            equipos.update(df_alerts['UnitId'].unique())
        if not df_maintenance.empty and 'machine_code' in df_maintenance.columns:
            equipos.update(df_maintenance['machine_code'].unique())
        
        # Calculate alert scores
        alert_scores = calculate_alert_criticality_score(df_alerts, 30) if not df_alerts.empty else pd.DataFrame()
        
        for equipo in sorted(equipos):
            # Telemetry status
            telem_status = 'N/A'
            if not df_telemetry.empty and 'unit_id' in df_telemetry.columns:
                equipo_telem = df_telemetry[df_telemetry['unit_id'] == equipo]
                if not equipo_telem.empty and 'overall_status' in equipo_telem.columns:
                    telem_status = equipo_telem['overall_status'].iloc[0]
            
            # Oil/Tribology status
            oil_status = 'N/A'
            if not df_oil.empty and 'equipo' in df_oil.columns:
                equipo_oil = df_oil[df_oil['equipo'] == equipo]
                if not equipo_oil.empty and 'estado' in equipo_oil.columns:
                    oil_status = equipo_oil['estado'].iloc[0]
            
            # Alert status
            alert_status = 'Normal'
            if not alert_scores.empty:
                equipo_alerts = alert_scores[alert_scores['equipo'] == equipo]
                if not equipo_alerts.empty:
                    alert_status = equipo_alerts['status'].iloc[0]
            
            # Maintenance status (map SANO->Normal, DETENIDO->Anormal)
            maint_status = 'N/A'
            if not df_maintenance.empty and 'machine_code' in df_maintenance.columns:
                equipo_maint = df_maintenance[df_maintenance['machine_code'] == equipo]
                if not equipo_maint.empty and 'machine_status' in equipo_maint.columns:
                    raw_status = equipo_maint['machine_status'].iloc[0]
                    # Map to coherent naming: SANO=Normal, DETENIDO=Anormal
                    if raw_status == 'SANO':
                        maint_status = 'Normal'
                    elif raw_status == 'DETENIDO':
                        maint_status = 'Anormal'
                    else:
                        maint_status = raw_status
            
            # Determine general status (worst case)
            status_priority = {
                'Anormal': 3, 'ANORMAL': 3, 'Crítico': 3,
                'Alerta': 2, 'ALERTA': 2, 'Atención': 2,
                'Normal': 1, 'NORMAL': 1,
                'N/A': 0
            }
            
            statuses = [telem_status, oil_status, alert_status, maint_status]
            priorities = [status_priority.get(s, 0) for s in statuses]
            max_priority = max(priorities)
            
            # Only include equipment with problems (priority >= 2)
            if max_priority >= 2:
                # Determine general status label
                if max_priority == 3:
                    general_status = 'Crítico'
                elif max_priority == 2:
                    general_status = 'Alerta'
                else:
                    general_status = 'Normal'
                
                summary_data.append({
                    'Unidad': equipo,
                    'Tribología': oil_status,
                    'Telemetría': telem_status,
                    'Alertas': alert_status,
                    'Mantenciones': maint_status,
                    'Estado General': general_status
                })
        
        if not summary_data:
            return html.Div(html.P("✓ No hay equipos con problemas", className="text-success text-center p-2 mb-0", style={'fontSize': '12px'}))
        
        df_summary = pd.DataFrame(summary_data)
        
        # Sort by severity (Crítico first)
        df_summary['_priority'] = df_summary['Estado General'].map({'Crítico': 3, 'Alerta': 2, 'Normal': 1})
        df_summary = df_summary.sort_values('_priority', ascending=False).drop('_priority', axis=1)
        
        return dash_table.DataTable(
            data=df_summary.to_dict('records'),
            columns=[{'name': col, 'id': col} for col in df_summary.columns],
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
                # Telemetry - Anormal (coherente con gráfico pie)
                {
                    'if': {'filter_query': '{Telemetría} = "Anormal"', 'column_id': 'Telemetría'},
                    'backgroundColor': '#dc3545',
                    'color': 'white',
                    'fontWeight': 'bold'
                },
                # Telemetry - Alerta
                {
                    'if': {'filter_query': '{Telemetría} = "Alerta"', 'column_id': 'Telemetría'},
                    'backgroundColor': '#ffc107',
                    'color': '#000',
                    'fontWeight': 'bold'
                },
                # Telemetry - Normal
                {
                    'if': {'filter_query': '{Telemetría} = "Normal"', 'column_id': 'Telemetría'},
                    'backgroundColor': '#28a745',
                    'color': 'white',
                    'fontWeight': 'bold'
                },
                # Tribology - ANORMAL (coherente con gráfico pie)
                {
                    'if': {'filter_query': '{Tribología} = "ANORMAL"', 'column_id': 'Tribología'},
                    'backgroundColor': '#dc3545',
                    'color': 'white',
                    'fontWeight': 'bold'
                },
                # Tribology - ALERTA
                {
                    'if': {'filter_query': '{Tribología} = "ALERTA"', 'column_id': 'Tribología'},
                    'backgroundColor': '#ffc107',
                    'color': '#000',
                    'fontWeight': 'bold'
                },
                # Tribology - NORMAL
                {
                    'if': {'filter_query': '{Tribología} = "NORMAL"', 'column_id': 'Tribología'},
                    'backgroundColor': '#28a745',
                    'color': 'white',
                    'fontWeight': 'bold'
                },
                # Alerts - Crítico
                {
                    'if': {'filter_query': '{Alertas} = "Crítico"', 'column_id': 'Alertas'},
                    'backgroundColor': '#dc3545',
                    'color': 'white',
                    'fontWeight': 'bold'
                },
                # Alerts - Alerta or Atención
                {
                    'if': {'filter_query': '{Alertas} = "Alerta" || {Alertas} = "Atención"', 'column_id': 'Alertas'},
                    'backgroundColor': '#ffc107',
                    'color': '#000',
                    'fontWeight': 'bold'
                },
                # Alerts - Normal
                {
                    'if': {'filter_query': '{Alertas} = "Normal"', 'column_id': 'Alertas'},
                    'backgroundColor': '#28a745',
                    'color': 'white',
                    'fontWeight': 'bold'
                },
                # Maintenance - Anormal (DETENIDO mapeado a Anormal)
                {
                    'if': {'filter_query': '{Mantenciones} = "Anormal"', 'column_id': 'Mantenciones'},
                    'backgroundColor': '#dc3545',
                    'color': 'white',
                    'fontWeight': 'bold'
                },
                # Maintenance - Normal (SANO mapeado a Normal)
                {
                    'if': {'filter_query': '{Mantenciones} = "Normal"', 'column_id': 'Mantenciones'},
                    'backgroundColor': '#28a745',
                    'color': 'white',
                    'fontWeight': 'bold'
                },
                # Estado General - Crítico
                {
                    'if': {'filter_query': '{Estado General} = "Crítico"', 'column_id': 'Estado General'},
                    'backgroundColor': '#dc3545',
                    'color': 'white',
                    'fontWeight': 'bold'
                },
                # Estado General - Alerta
                {
                    'if': {'filter_query': '{Estado General} = "Alerta"', 'column_id': 'Estado General'},
                    'backgroundColor': '#ffc107',
                    'color': '#000',
                    'fontWeight': 'bold'
                }
            ]
        )
    except Exception as e:
        logger.error(f"Error creating critical equipment summary table: {e}", exc_info=True)
        return html.Div(html.P("Error al generar tabla", className="text-danger text-center p-2 mb-0", style={'fontSize': '12px'}))


def create_alerts_pie_chart(df_alerts: pd.DataFrame, days: int = 30) -> go.Figure:
    """
    Create compact pie chart showing components affected by alerts.
    
    Args:
        df_alerts: DataFrame with alerts data
        days: Number of days to consider
        
    Returns:
        Plotly figure
    """
    if df_alerts.empty:
        return create_empty_figure("No hay datos")
    
    # Filter by date range
    if 'Timestamp' in df_alerts.columns:
        cutoff_date = datetime.now() - timedelta(days=days)
        df_alerts['Timestamp'] = pd.to_datetime(df_alerts['Timestamp'])
        df_recent = df_alerts[df_alerts['Timestamp'] >= cutoff_date].copy()
    else:
        df_recent = df_alerts.copy()
    
    if df_recent.empty:
        return create_empty_figure(f"Sin alertas")
    
    # Count alerts by component
    if 'componente' not in df_recent.columns:
        return create_empty_figure("Datos incompletos")
    
    # Count alerts per component
    component_counts = df_recent['componente'].value_counts().head(10)  # Top 10 components
    
    if component_counts.empty:
        return create_empty_figure("Sin componentes")
    
    # Generate distinct colors for components
    import plotly.colors as pc
    colors_palette = pc.qualitative.Set3[:len(component_counts)]
    
    fig = go.Figure(data=[go.Pie(
        labels=component_counts.index,
        values=component_counts.values,
        marker_colors=colors_palette,
        hole=0.5,
        textposition='inside',
        textinfo='value',
        textfont=dict(size=12, color='white'),
        hovertemplate='<b>%{label}</b><br>%{value} alertas (%{percent})<extra></extra>'
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
            font=dict(size=9)
        ),
        font=dict(size=11)
    )
    
    return fig


def create_summary_table(df_telemetry: pd.DataFrame, df_maintenance: pd.DataFrame, 
                         df_oil: pd.DataFrame, df_alerts: pd.DataFrame) -> html.Div:
    """
    Create comprehensive summary table combining all technical areas.
    
    Args:
        df_telemetry: Telemetry data (with correct columns: unit_id, overall_status)
        df_maintenance: Maintenance data
        df_oil: Oil analysis data
        df_alerts: Alerts data (with correct columns: Unidad, Componente, Timestamp)
        
    Returns:
        Dash DataTable component
    """
    try:
        # Build summary by equipment
        summary_data = []
        
        # Get unique equipment from all sources (using correct column names)
        equipos = set()
        if not df_telemetry.empty and 'unit_id' in df_telemetry.columns:
            equipos.update(df_telemetry['unit_id'].unique())
        if not df_alerts.empty and 'Unidad' in df_alerts.columns:
            equipos.update(df_alerts['Unidad'].unique())
        
        alert_scores = calculate_alert_criticality_score(df_alerts, 30) if not df_alerts.empty else pd.DataFrame()
        
        for equipo in sorted(equipos):
            # Telemetry status (use correct column: unit_id and overall_status)
            telem_status = 'N/A'
            if not df_telemetry.empty and 'unit_id' in df_telemetry.columns:
                equipo_telem = df_telemetry[df_telemetry['unit_id'] == equipo]
                if not equipo_telem.empty and 'overall_status' in equipo_telem.columns:
                    telem_status = equipo_telem['overall_status'].iloc[0]
            
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
            
            # Load Telemetry data using proper loader (most recent week/year available)
            df_telemetry = load_telemetry_machine_status(client)
            if not df_telemetry.empty:
                # Get most recent week/year combination using correct column names
                if 'evaluation_week' in df_telemetry.columns and 'evaluation_year' in df_telemetry.columns:
                    most_recent = df_telemetry.sort_values(['evaluation_year', 'evaluation_week'], ascending=False).iloc[0]
                    latest_year = most_recent['evaluation_year']
                    latest_week = most_recent['evaluation_week']
                    df_telemetry = df_telemetry[
                        (df_telemetry['evaluation_year'] == latest_year) & 
                        (df_telemetry['evaluation_week'] == latest_week)
                    ]
                    telemetry_latest = f"Semana {latest_week}, Año {latest_year}"
                    logger.info(f"Telemetry: Using most recent data - {telemetry_latest}")
            
            # Load Maintenance data (already filtered by MTD) - MUST pass client parameter
            repo = get_repository(mode="parquet", client=client)
            df_status = repo.get_status_counts()
            df_downtime = repo.get_downtime_mtd()
            logger.info(f"Maintenance: Loaded {len(df_status)} status records for client: {client}")
            
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
            
            # Load Alerts data using proper loader (load all recent alerts, filtering happens in visualizations)
            df_alerts = load_alerts_data(client)
            alerts_period = "Últimos 90 días (por defecto)"  # Default period shown
            if not df_alerts.empty:
                logger.info(f"Alerts: Loaded {len(df_alerts)} alerts (will be filtered by visualization)")
            
            # Serialize to JSON with metadata about data freshness
            # Clean numpy types before serialization
            data = {
                "telemetry": clean_numpy_types(df_telemetry.to_dict("records")) if not df_telemetry.empty else [],
                "maintenance_status": clean_numpy_types(df_status.to_dict("records")) if not df_status.empty else [],
                "maintenance_downtime": clean_numpy_types(df_downtime.to_dict("records")) if not df_downtime.empty else [],
                "oil": clean_numpy_types(df_oil.to_dict("records")) if not df_oil.empty else [],
                "alerts": clean_numpy_types(df_alerts.to_dict("records")) if not df_alerts.empty else [],
                "metadata": {
                    "telemetry_latest": telemetry_latest,
                    "oil_latest": oil_latest,
                    "alerts_period": "Configurable (ver filtro)",  # Dynamic based on filter
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
        """Update global KPI cards using correct column names."""
        if not data:
            return "0", "0", "0", "0"
        
        try:
            # Parse data
            df_telemetry = pd.DataFrame(data.get("telemetry", []))
            df_status = pd.DataFrame(data.get("maintenance_status", []))
            df_oil = pd.DataFrame(data.get("oil", []))
            df_alerts = pd.DataFrame(data.get("alerts", []))
            
            logger.info(f"KPI Update - Telemetry rows: {len(df_telemetry)}, Maintenance rows: {len(df_status)}, Oil rows: {len(df_oil)}, Alerts rows: {len(df_alerts)}")
            
            # Total equipment (priority: telemetry > maintenance > oil)
            if not df_telemetry.empty:
                total = len(df_telemetry)
                logger.info(f"Total from telemetry: {total}")
            elif not df_status.empty:
                total = int(df_status['n_machines'].sum())
                # If maintenance shows 0 machines but we have oil data, use oil instead
                if total == 0 and not df_oil.empty:
                    if 'equipo' in df_oil.columns:
                        total = df_oil['equipo'].nunique()
                        logger.info(f"Total from oil (fallback from empty maintenance): {total}")
                    else:
                        total = len(df_oil)
                        logger.info(f"Total from oil length (fallback): {total}")
                else:
                    logger.info(f"Total from maintenance: {total}")
            elif not df_oil.empty:
                # Count unique equipment from oil analysis
                if 'equipo' in df_oil.columns:
                    total = df_oil['equipo'].nunique()
                    logger.info(f"Total from oil (equipo column): {total}, unique values: {df_oil['equipo'].unique()[:5]}")
                else:
                    total = len(df_oil)
                    logger.info(f"Total from oil (length): {total}")
            else:
                total = 0
                logger.info("Total: No data available")
            
            # Operational equipment (use correct column: overall_status)
            operational = 0
            if not df_telemetry.empty and 'overall_status' in df_telemetry.columns:
                operational = (df_telemetry['overall_status'] == 'Normal').sum()
            elif not df_status.empty:
                operational = int(df_status[df_status['machine_status'] == 'SANO']['n_machines'].sum())
                # If maintenance shows 0 operational but we have oil data, use oil instead
                if operational == 0 and not df_oil.empty and 'estado' in df_oil.columns:
                    operational = (df_oil['estado'] == 'NORMAL').sum()
                    logger.info(f"Operational from oil (fallback from empty maintenance): {operational}")
            elif not df_oil.empty and 'estado' in df_oil.columns:
                # Count equipment with NORMAL status in oil analysis
                operational = (df_oil['estado'] == 'NORMAL').sum()
                logger.info(f"Operational from oil: {operational}, estados: {df_oil['estado'].value_counts().to_dict()}")
            
            # Warning equipment (Alerta status in telemetry or oil)
            warning = 0
            if not df_telemetry.empty and 'overall_status' in df_telemetry.columns:
                warning = (df_telemetry['overall_status'] == 'Alerta').sum()
            elif not df_oil.empty and 'estado' in df_oil.columns:
                warning = (df_oil['estado'] == 'ALERTA').sum()
            
            # Critical equipment (Anormal in telemetry, oil, or high alert score)
            critical = 0
            if not df_telemetry.empty and 'overall_status' in df_telemetry.columns:
                critical = (df_telemetry['overall_status'] == 'Anormal').sum()
            elif not df_oil.empty and 'estado' in df_oil.columns:
                critical = (df_oil['estado'] == 'ANORMAL').sum()
            
            # Add critical from alerts
            if not df_alerts.empty:
                alert_scores = calculate_alert_criticality_score(df_alerts, 30)
                if not alert_scores.empty:
                    critical += (alert_scores['status'] == 'Crítico').sum()
            
            logger.info(f"Final KPIs - Total: {total}, Operational: {operational}, Warning: {warning}, Critical: {critical}")
            return str(total), str(operational), str(warning), str(critical)
            
        except Exception as e:
            logger.error(f"Error updating global KPIs: {e}", exc_info=True)
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
            return create_telemetry_pie_chart(df_telemetry)
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
            return create_maintenance_pie_chart(df_status, df_downtime)
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
    def update_critical_equipment_table(data):
        """Update critical equipment summary table."""
        if not data:
            return html.P("No hay datos disponibles", className="text-muted text-center p-3")
        
        try:
            df_telemetry = pd.DataFrame(data.get("telemetry", []))
            df_oil = pd.DataFrame(data.get("oil", []))
            df_alerts = pd.DataFrame(data.get("alerts", []))
            df_maintenance = pd.DataFrame(data.get("maintenance_status", []))
            return create_critical_equipment_summary_table(df_telemetry, df_oil, df_alerts, df_maintenance)
        except Exception as e:
            logger.error(f"Error updating critical equipment table: {e}")
            return html.P("Error al cargar tabla", className="text-danger text-center p-3")
    
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
            return create_alerts_pie_chart(df_alerts, days)
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
