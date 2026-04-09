"""
Chart components for Health Index Dashboard.

Reusable Plotly figure builders for health index visualizations.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ========================================
# COLOR SCHEMES
# ========================================

HEALTH_STATUS_COLORS = {
    'critical': '#dc3545',    # Rojo
    'warning': '#ffc107',     # Amarillo
    'healthy': '#28a745'      # Verde
}

# Escala de colores para heatmap (del rojo al verde)
HEATMAP_COLORSCALE = [
    [0.0, '#dc3545'],   # Rojo (crítico)
    [0.5, '#ffc107'],   # Amarillo (precaución)
    [0.8, '#90EE90'],   # Verde claro
    [1.0, '#28a745']    # Verde (saludable)
]


def get_hi_color(hi_value: float) -> str:
    """
    Get color based on health index value.
    
    Args:
        hi_value: Health index value (0-1)
    
    Returns:
        Color hex string
    """
    if hi_value < 0.5:
        return HEALTH_STATUS_COLORS['critical']
    elif hi_value < 0.8:
        return HEALTH_STATUS_COLORS['warning']
    else:
        return HEALTH_STATUS_COLORS['healthy']


def get_hi_status(hi_value: float) -> str:
    """
    Get status label based on health index value.
    
    Args:
        hi_value: Health index value (0-1)
    
    Returns:
        Status string
    """
    if hi_value < 0.5:
        return '🔴 Crítico'
    elif hi_value < 0.8:
        return '🟡 Precaución'
    else:
        return '🟢 Saludable'


def _empty_figure(message: str = "Sin datos disponibles") -> go.Figure:
    """Create an empty figure with a message."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=14, color='gray')
    )
    fig.update_layout(
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        height=300,
        template='plotly_white'
    )
    return fig


# ========================================
# TIMELINE CHARTS
# ========================================

def create_health_index_timeline(
    df: pd.DataFrame,
    selected_units: Optional[List[str]] = None,
    selected_system: Optional[str] = None
) -> go.Figure:
    """
    Create timeline chart showing health index evolution for each unit.
    
    Args:
        df: DataFrame with health index data
        selected_units: List of units to display (None = all)
        selected_system: Specific system to filter by (None = all systems average)
    
    Returns:
        Plotly figure
    """
    if df is None or df.empty:
        return _empty_figure("No hay datos de Health Index disponibles")
    
    try:
        # Filter by system if specified
        if selected_system and selected_system != 'all-systems':
            df_filtered = df[df['component'] == selected_system].copy()
        else:
            # Average across all systems
            df_filtered = df.groupby(['Unit', 'start_time', 'truck_model']).agg({
                'health_index': 'mean'
            }).reset_index()
        
        # Filter by units if specified
        if selected_units and 'all' not in selected_units:
            df_filtered = df_filtered[df_filtered['Unit'].isin(selected_units)]
        
        if df_filtered.empty:
            return _empty_figure("No hay datos para los filtros seleccionados")
        
        # Create figure
        fig = go.Figure()
        
        # Add trace for each unit
        units = sorted(df_filtered['Unit'].unique())
        
        for unit in units:
            unit_data = df_filtered[df_filtered['Unit'] == unit].sort_values('start_time')
            
            if unit_data.empty:
                continue
            
            # Get average HI for color
            avg_hi = unit_data['health_index'].mean()
            color = get_hi_color(avg_hi)
            
            fig.add_trace(go.Scatter(
                x=unit_data['start_time'],
                y=unit_data['health_index'],
                name=unit,
                mode='lines+markers',
                line=dict(width=2),
                marker=dict(size=4),
                hovertemplate=(
                    f"<b>{unit}</b><br>" +
                    "Fecha: %{x|%d/%m/%Y %H:%M}<br>" +
                    "Health Index: %{y:.4f}<br>" +
                    "<extra></extra>"
                )
            ))
        
        # Add threshold lines
        fig.add_hline(y=0.8, line_dash="dash", line_color="green", 
                      annotation_text="Saludable (0.8)", annotation_position="right")
        fig.add_hline(y=0.5, line_dash="dash", line_color="red", 
                      annotation_text="Crítico (0.5)", annotation_position="right")
        
        # Update layout
        fig.update_layout(
            title=dict(
                text="Evolución Temporal del Health Index",
                font=dict(size=16)
            ),
            xaxis_title="Fecha",
            yaxis_title="Health Index",
            yaxis=dict(range=[0, 1.05]),
            hovermode='x unified',
            template='plotly_white',
            height=400,
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.02
            )
        )
        
        return fig
        
    except Exception as e:
        logger.error(f"Error creating timeline chart: {e}")
        return _empty_figure(f"Error al crear gráfico: {str(e)}")


# ========================================
# HEATMAP
# ========================================

def create_health_index_heatmap(df: pd.DataFrame) -> go.Figure:
    """
    Create heatmap showing health index by unit and system.
    
    Args:
        df: DataFrame with health index data
    
    Returns:
        Plotly figure
    """
    if df is None or df.empty:
        return _empty_figure("No hay datos de Health Index disponibles")
    
    try:
        # Calculate average HI per unit and component
        heatmap_data = df.groupby(['Unit', 'component'])['health_index'].mean().reset_index()
        
        # Pivot for heatmap
        pivot_data = heatmap_data.pivot(index='Unit', columns='component', values='health_index')
        
        # Sort units
        pivot_data = pivot_data.sort_index()
        
        # Create heatmap
        fig = go.Figure(data=go.Heatmap(
            z=pivot_data.values,
            x=pivot_data.columns,
            y=pivot_data.index,
            colorscale=HEATMAP_COLORSCALE,
            zmin=0,
            zmax=1,
            text=np.round(pivot_data.values, 3),
            texttemplate='%{text:.3f}',
            textfont=dict(size=10),
            hovertemplate=(
                "Unidad: %{y}<br>" +
                "Sistema: %{x}<br>" +
                "HI Promedio: %{z:.4f}<br>" +
                "<extra></extra>"
            ),
            colorbar=dict(
                title="Health Index",
                tickvals=[0, 0.5, 0.8, 1.0],
                ticktext=['0.0', '0.5 (Crítico)', '0.8 (Precaución)', '1.0']
            )
        ))
        
        fig.update_layout(
            title="Health Index Promedio por Unidad y Sistema",
            xaxis_title="Sistema",
            yaxis_title="Unidad",
            template='plotly_white',
            height=500
        )
        
        return fig
        
    except Exception as e:
        logger.error(f"Error creating heatmap: {e}")
        return _empty_figure(f"Error al crear heatmap: {str(e)}")


# ========================================
# BAR CHARTS
# ========================================

def create_health_index_bar_chart(df: pd.DataFrame, top_n: int = 20) -> go.Figure:
    """
    Create bar chart showing current health index by unit.
    
    Args:
        df: DataFrame with health index data
        top_n: Number of most recent records to show per unit
    
    Returns:
        Plotly figure
    """
    if df is None or df.empty:
        return _empty_figure("No hay datos de Health Index disponibles")
    
    try:
        # Get most recent HI for each unit (average across systems)
        latest_data = df.sort_values('end_time').groupby('Unit').tail(top_n)
        unit_hi = latest_data.groupby('Unit')['health_index'].mean().sort_values()
        
        # Create colors based on HI value
        colors = [get_hi_color(hi) for hi in unit_hi.values]
        
        # Create bar chart
        fig = go.Figure(data=[
            go.Bar(
                x=unit_hi.values,
                y=unit_hi.index,
                orientation='h',
                marker=dict(color=colors),
                text=[f"{hi:.3f}" for hi in unit_hi.values],
                textposition='auto',
                hovertemplate=(
                    "<b>%{y}</b><br>" +
                    "Health Index: %{x:.4f}<br>" +
                    "<extra></extra>"
                )
            )
        ])
        
        # Add threshold lines
        fig.add_vline(x=0.5, line_dash="dash", line_color="red", 
                      annotation_text="Crítico", annotation_position="top")
        fig.add_vline(x=0.8, line_dash="dash", line_color="orange", 
                      annotation_text="Precaución", annotation_position="top")
        
        fig.update_layout(
            title="Health Index Actual por Unidad",
            xaxis_title="Health Index",
            yaxis_title="Unidad",
            xaxis=dict(range=[0, 1.05]),
            template='plotly_white',
            height=400,
            showlegend=False
        )
        
        return fig
        
    except Exception as e:
        logger.error(f"Error creating bar chart: {e}")
        return _empty_figure(f"Error al crear gráfico de barras: {str(e)}")


# ========================================
# DISTRIBUTION CHARTS
# ========================================

def create_health_index_distribution(
    df: pd.DataFrame,
    system: Optional[str] = None
) -> go.Figure:
    """
    Create histogram/distribution chart of health index values.
    
    Args:
        df: DataFrame with health index data
        system: Specific system to filter by (None = all)
    
    Returns:
        Plotly figure
    """
    if df is None or df.empty:
        return _empty_figure("No hay datos disponibles")
    
    try:
        # Filter by system if specified
        if system and system != 'all-systems':
            df_filtered = df[df['component'] == system]
        else:
            df_filtered = df
        
        if df_filtered.empty:
            return _empty_figure("No hay datos para el sistema seleccionado")
        
        # Create histogram
        fig = go.Figure()
        
        # Add histogram
        fig.add_trace(go.Histogram(
            x=df_filtered['health_index'],
            nbinsx=50,
            marker_color='lightblue',
            marker_line_color='navy',
            marker_line_width=1,
            name='Distribución',
            hovertemplate=(
                "Rango HI: %{x}<br>" +
                "Cantidad: %{y}<br>" +
                "<extra></extra>"
            )
        ))
        
        # Add threshold lines
        fig.add_vline(x=0.5, line_dash="dash", line_color="red", 
                      annotation_text="Crítico (0.5)")
        fig.add_vline(x=0.8, line_dash="dash", line_color="orange", 
                      annotation_text="Precaución (0.8)")
        
        fig.update_layout(
            title=f"Distribución de Health Index{f' - {system}' if system and system != 'all-systems' else ''}",
            xaxis_title="Health Index",
            yaxis_title="Frecuencia",
            template='plotly_white',
            height=350,
            showlegend=False
        )
        
        return fig
        
    except Exception as e:
        logger.error(f"Error creating distribution chart: {e}")
        return _empty_figure(f"Error al crear distribución: {str(e)}")


# ========================================
# PIE CHARTS
# ========================================

def create_health_status_pie(df: pd.DataFrame, system: Optional[str] = None) -> go.Figure:
    """
    Create pie chart showing distribution of health status categories.
    
    Args:
        df: DataFrame with health index data
        system: Specific system to filter by (None = all)
    
    Returns:
        Plotly figure
    """
    if df is None or df.empty:
        return _empty_figure("No hay datos disponibles")
    
    try:
        # Filter by system if specified
        if system and system != 'all-systems':
            df_filtered = df[df['component'] == system]
        else:
            df_filtered = df
        
        if df_filtered.empty:
            return _empty_figure("No hay datos para el sistema seleccionado")
        
        # Categorize health index
        def categorize_hi(hi):
            if hi < 0.5:
                return '🔴 Crítico'
            elif hi < 0.8:
                return '🟡 Precaución'
            else:
                return '🟢 Saludable'
        
        df_filtered['status'] = df_filtered['health_index'].apply(categorize_hi)
        
        # Count by status
        status_counts = df_filtered['status'].value_counts()
        
        # Create pie chart
        fig = go.Figure(data=[go.Pie(
            labels=status_counts.index,
            values=status_counts.values,
            marker=dict(
                colors=[HEALTH_STATUS_COLORS['healthy'], 
                       HEALTH_STATUS_COLORS['warning'], 
                       HEALTH_STATUS_COLORS['critical']]
            ),
            textinfo='label+percent',
            hovertemplate=(
                "<b>%{label}</b><br>" +
                "Cantidad: %{value}<br>" +
                "Porcentaje: %{percent}<br>" +
                "<extra></extra>"
            )
        )])
        
        fig.update_layout(
            title=f"Estado de Salud{f' - {system}' if system and system != 'all-systems' else ''}",
            template='plotly_white',
            height=350
        )
        
        return fig
        
    except Exception as e:
        logger.error(f"Error creating pie chart: {e}")
        return _empty_figure(f"Error al crear gráfico: {str(e)}")


# ========================================
# GAUGE CHARTS
# ========================================

def create_health_gauge(hi_value: float, title: str = "Health Index") -> go.Figure:
    """
    Create gauge chart for a single health index value.
    
    Args:
        hi_value: Health index value (0-1)
        title: Chart title
    
    Returns:
        Plotly figure
    """
    try:
        # Determine color
        color = get_hi_color(hi_value)
        
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=hi_value,
            domain={'x': [0, 1], 'y': [0, 1]},
            title={'text': title, 'font': {'size': 16}},
            number={'suffix': "", 'font': {'size': 40}},
            gauge={
                'axis': {'range': [0, 1], 'tickwidth': 1},
                'bar': {'color': color},
                'bgcolor': "white",
                'borderwidth': 2,
                'bordercolor': "gray",
                'steps': [
                    {'range': [0, 0.5], 'color': '#ffe6e6'},
                    {'range': [0.5, 0.8], 'color': '#fff4e6'},
                    {'range': [0.8, 1], 'color': '#e6ffe6'}
                ],
                'threshold': {
                    'line': {'color': "red", 'width': 4},
                    'thickness': 0.75,
                    'value': 0.5
                }
            }
        ))
        
        fig.update_layout(
            height=250,
            template='plotly_white'
        )
        
        return fig
        
    except Exception as e:
        logger.error(f"Error creating gauge: {e}")
        return _empty_figure(f"Error al crear gauge: {str(e)}")
