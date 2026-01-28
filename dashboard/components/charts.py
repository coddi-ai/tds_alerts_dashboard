"""
Reusable chart components for Multi-Technical-Alerts dashboard.
"""

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from typing import List, Dict


# Color scheme
STATUS_COLORS = {
    'Normal': '#28a745',   # Green
    'Alerta': '#ffc107',   # Yellow/Amber
    'Anormal': '#dc3545'   # Red
}


def create_status_pie_chart(df: pd.DataFrame) -> go.Figure:
    """
    Create pie chart showing machine status distribution.
    
    Args:
        df: DataFrame with machine statuses
    
    Returns:
        Plotly figure
    """
    if df.empty:
        return go.Figure()
    
    status_counts = df['overall_status'].value_counts()
    
    fig = go.Figure(data=[go.Pie(
        labels=status_counts.index,
        values=status_counts.values,
        marker=dict(colors=[STATUS_COLORS.get(s, '#999999') for s in status_counts.index]),
        hole=0.4,
        textinfo='label+percent+value',
        textfont=dict(size=14)
    )])
    
    fig.update_layout(
        title="Machine Status Distribution",
        title_font_size=18,
        showlegend=True,
        height=400
    )
    
    return fig


def create_radar_chart(
    sample: pd.Series,
    limits: Dict,
    group_element: str,
    essays_in_group: List[str]
) -> go.Figure:
    """
    Create radar chart for essays in a GroupElement.
    
    Args:
        sample: Sample data row
        limits: Stewart Limits dictionary
        group_element: GroupElement name
        essays_in_group: List of essay names in this group
    
    Returns:
        Plotly figure
    """
    client = sample.get('client', '')
    machine = sample.get('machineName', '')
    component = sample.get('componentName', '')
    
    # Get limits for this machine/component
    sel_limits = limits.get(client, {}).get(machine, {}).get(component, {})
    
    # Prepare data
    categories = []
    values = []
    marginal = []
    condenatorio = []
    critico = []
    
    for essay in essays_in_group:
        if essay in sample.index and not pd.isna(sample[essay]):
            categories.append(essay)
            values.append(sample[essay])
            
            # Get limits
            essay_limits = sel_limits.get(essay, {})
            marginal.append(essay_limits.get('threshold_normal', 0))
            condenatorio.append(essay_limits.get('threshold_alert', 0))
            critico.append(essay_limits.get('threshold_critic', 0))
    
    if not categories:
        return go.Figure()
    
    # Create radar chart
    fig = go.Figure()
    
    # Add threshold lines
    fig.add_trace(go.Scatterpolar(
        r=marginal + [marginal[0]],
        theta=categories + [categories[0]],
        name='Marginal',
        line=dict(color='#28a745', width=2, dash='dash')
    ))
    
    fig.add_trace(go.Scatterpolar(
        r=condenatorio + [condenatorio[0]],
        theta=categories + [categories[0]],
        name='Condenatorio',
        line=dict(color='#ffc107', width=2, dash='dash')
    ))
    
    fig.add_trace(go.Scatterpolar(
        r=critico + [critico[0]],
        theta=categories + [categories[0]],
        name='Crítico',
        line=dict(color='#dc3545', width=2, dash='dash')
    ))
    
    # Add actual values
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]],
        theta=categories + [categories[0]],
        name='Actual',
        fill='toself',
        fillcolor='rgba(23, 162, 184, 0.3)',
        line=dict(color='#17a2b8', width=3)
    ))
    
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, max(max(values), max(critico)) * 1.2])
        ),
        title=f"Radar Chart - {group_element}",
        title_font_size=16,
        showlegend=True,
        height=500
    )
    
    return fig


def create_time_series_chart(
    df: pd.DataFrame,
    unit_id: str,
    component: str,
    essays: List[str],
    limits: Dict = None
) -> go.Figure:
    """
    Create time series chart for essays in a component.
    
    Args:
        df: DataFrame with samples
        unit_id: Machine unit ID
        component: Component name
        essays: List of essay names to plot
        limits: Stewart Limits dictionary (optional)
    
    Returns:
        Plotly figure
    """
    # Filter data
    filtered_df = df[(df['unitId'] == unit_id) & (df['componentName'] == component)].copy()
    
    if filtered_df.empty:
        return go.Figure()
    
    filtered_df = filtered_df.sort_values('sampleDate')
    
    fig = go.Figure()
    
    # Add line for each essay
    for essay in essays:
        if essay in filtered_df.columns:
            fig.add_trace(go.Scatter(
                x=filtered_df['sampleDate'],
                y=filtered_df[essay],
                mode='lines+markers',
                name=essay,
                line=dict(width=2),
                marker=dict(size=6)
            ))
            
            # Add threshold lines if limits provided
            if limits:
                client = filtered_df['client'].iloc[0]
                machine = filtered_df['machineName'].iloc[0]
                
                essay_limits = limits.get(client, {}).get(machine, {}).get(component, {}).get(essay, {})
                
                if essay_limits:
                    # Critic threshold
                    critic = essay_limits.get('threshold_critic')
                    if critic and not pd.isna(critic):
                        fig.add_hline(
                            y=critic,
                            line_dash="dash",
                            line_color="#dc3545",
                            annotation_text=f"{essay} Crítico",
                            annotation_position="right"
                        )
    
    fig.update_layout(
        title=f"Time Series - {unit_id} / {component}",
        title_font_size=16,
        xaxis_title="Sample Date",
        yaxis_title="Value",
        hovermode='x unified',
        height=500,
        showlegend=True
    )
    
    return fig


def create_bar_chart(data: Dict[str, int], title: str, color: str = '#17a2b8') -> go.Figure:
    """
    Create simple bar chart.
    
    Args:
        data: Dictionary of {label: value}
        title: Chart title
        color: Bar color
    
    Returns:
        Plotly figure
    """
    fig = go.Figure(data=[go.Bar(
        x=list(data.keys()),
        y=list(data.values()),
        marker_color=color
    )])
    
    fig.update_layout(
        title=title,
        title_font_size=16,
        xaxis_title="",
        yaxis_title="Count",
        height=350
    )
    
    return fig
