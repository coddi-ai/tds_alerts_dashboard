"""
Telemetry chart building functions for Multi-Technical Alerts Dashboard.

This module provides reusable chart functions for telemetry visualizations.
All functions return Plotly Figure objects ready for display in Dash.
"""

import pandas as pd
import numpy as np
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Status color scheme
STATUS_COLORS = {
    'Normal': '#28a745',    # Green
    'Alerta': '#ffc107',    # Yellow/Amber
    'Anormal': '#dc3545',   # Red
    'InsufficientData': '#6c757d'  # Gray
}


def build_fleet_kpi_cards(machine_df: pd.DataFrame) -> go.Figure:
    """
    Build KPI indicator cards showing fleet health metrics.
    
    Args:
        machine_df: DataFrame with machine status data
    
    Returns:
        Plotly Figure with 4 indicator subplots (Total, Normal, Alerta, Anormal)
    """
    if machine_df.empty:
        logger.warning("Empty machine dataframe provided to build_fleet_kpi_cards")
        return go.Figure()
    
    # Calculate metrics
    total_units = len(machine_df)
    status_counts = machine_df['overall_status'].value_counts()
    
    normal_count = status_counts.get('Normal', 0)
    alerta_count = status_counts.get('Alerta', 0)
    anormal_count = status_counts.get('Anormal', 0)
    
    normal_pct = (normal_count / total_units) * 100 if total_units > 0 else 0
    alerta_pct = (alerta_count / total_units) * 100 if total_units > 0 else 0
    anormal_pct = (anormal_count / total_units) * 100 if total_units > 0 else 0
    
    # Create subplots
    fig = make_subplots(
        rows=1, cols=4,
        specs=[[{'type': 'indicator'}, {'type': 'indicator'}, 
                {'type': 'indicator'}, {'type': 'indicator'}]],
        subplot_titles=('Total Units', 'Normal', 'Alerta', 'Anormal')
    )
    
    # Total Units
    fig.add_trace(go.Indicator(
        mode="number",
        value=total_units,
        title={'text': "Total Units"},
        number={'font': {'size': 40}}
    ), row=1, col=1)
    
    # Normal
    fig.add_trace(go.Indicator(
        mode="number+delta",
        value=normal_count,
        title={'text': f"Normal ({normal_pct:.1f}%)"},
        number={'font': {'size': 40, 'color': STATUS_COLORS['Normal']}},
        delta={'reference': total_units * 0.8, 'relative': False}
    ), row=1, col=2)
    
    # Alerta
    fig.add_trace(go.Indicator(
        mode="number",
        value=alerta_count,
        title={'text': f"Alerta ({alerta_pct:.1f}%)"},
        number={'font': {'size': 40, 'color': STATUS_COLORS['Alerta']}}
    ), row=1, col=3)
    
    # Anormal
    fig.add_trace(go.Indicator(
        mode="number",
        value=anormal_count,
        title={'text': f"Anormal ({anormal_pct:.1f}%)"},
        number={'font': {'size': 40, 'color': STATUS_COLORS['Anormal']}}
    ), row=1, col=4)
    
    fig.update_layout(
        height=250,
        title_text="Fleet Health KPIs",
        showlegend=False,
        margin=dict(t=80, b=20, l=20, r=20)
    )
    
    return fig


def build_fleet_pie_chart(machine_df: pd.DataFrame) -> go.Figure:
    """
    Build pie chart showing fleet status distribution.
    
    Args:
        machine_df: DataFrame with machine status data
    
    Returns:
        Plotly Figure with pie chart
    """
    if machine_df.empty:
        logger.warning("Empty machine dataframe provided to build_fleet_pie_chart")
        return go.Figure()
    
    status_counts = machine_df['overall_status'].value_counts()
    
    fig = go.Figure(data=[go.Pie(
        labels=status_counts.index,
        values=status_counts.values,
        marker=dict(colors=[STATUS_COLORS.get(status, '#999') for status in status_counts.index]),
        textinfo='label+value+percent',
        textposition='auto',
        hovertemplate='%{label}<br>Count: %{value}<br>Percentage: %{percent}<extra></extra>'
    )])
    
    fig.update_layout(
        title_text="Fleet Status Distribution",
        height=500,
        showlegend=True,
        margin=dict(t=60, b=20, l=20, r=20)
    )
    
    return fig


def build_component_radar_chart(component_details: List[Dict]) -> go.Figure:
    """
    Build radar chart showing component health scores.
    
    Args:
        component_details: List of component detail dictionaries
    
    Returns:
        Plotly Figure with radar chart
    """
    if not component_details:
        logger.warning("Empty component_details provided to build_component_radar_chart")
        return go.Figure()
    
    # Convert to DataFrame for easier manipulation
    radar_data = pd.DataFrame(component_details)
    
    # Ensure required columns exist
    if 'component' not in radar_data.columns or 'component_score' not in radar_data.columns:
        logger.warning("Missing required columns in component_details")
        return go.Figure()
    
    # Create radar chart
    fig = go.Figure()
    
    fig.add_trace(go.Scatterpolar(
        r=radar_data['component_score'].tolist() + [radar_data['component_score'].iloc[0]],  # Close the polygon
        theta=radar_data['component'].tolist() + [radar_data['component'].iloc[0]],
        fill='toself',
        name='Component Score',
        line=dict(color='blue'),
        fillcolor='rgba(0, 100, 200, 0.3)',
        hovertemplate='%{theta}<br>Score: %{r:.3f}<extra></extra>'
    ))
    
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, max(1.0, radar_data['component_score'].max() * 1.1)]
            )
        ),
        showlegend=False,
        title="Component Health Radar",
        height=600,
        margin=dict(t=80, b=20, l=80, r=80)
    )
    
    return fig


def build_weekly_boxplots(
    unit_id: str,
    component: str,
    signals_table: pd.DataFrame,
    combined_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    current_week: int,
    current_year: int
) -> go.Figure:
    """
    Build weekly distribution boxplots for signals in a component.
    
    Args:
        unit_id: Unit identifier
        component: Component name
        signals_table: DataFrame with signal evaluation data
        combined_df: Combined silver data across multiple weeks
        baseline_df: Baseline thresholds DataFrame
        current_week: Current evaluation week number
        current_year: Current evaluation year
    
    Returns:
        Plotly Figure with boxplot subplots
    """
    if signals_table.empty or combined_df.empty:
        logger.warning("Empty data provided to build_weekly_boxplots")
        return go.Figure()
    
    signal_list = signals_table['signal'].tolist()
    num_signals = len(signal_list)
    
    if num_signals == 0:
        logger.warning("No signals to plot")
        return go.Figure()
    
    # Determine grid layout (max 2 columns)
    if num_signals == 1:
        n_rows, n_cols = 1, 1
    elif num_signals == 2:
        n_rows, n_cols = 1, 2
    else:
        n_cols = 2
        n_rows = (num_signals + 1) // 2  # Ceiling division
    
    # Create subplots
    specs = [[{'type': 'xy'}] * n_cols for _ in range(n_rows)]
    
    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=[f'{signal}' for signal in signal_list],
        vertical_spacing=0.08,
        horizontal_spacing=0.10,
        specs=specs,
        shared_yaxes=True if n_cols > 1 else False
    )
    
    # Sort weeks chronologically (reversed for horizontal display)
    week_labels_sorted = sorted(
        combined_df['week_label'].unique(),
        key=lambda x: (int(x.split('/')[1]), int(x.split()[1].split('/')[0])),
        reverse=True  # Most recent at top
    )
    
    # Status color mapping
    status_color_map = {
        'Anormal': '#dc3545',  # Red
        'Alerta': '#ffc107',   # Yellow/Amber
        'Normal': '#28a745'    # Green
    }
    historical_color = '#B0C4DE'  # Light steel blue for historical weeks
    
    # Build each signal's boxplot
    for idx, signal_name in enumerate(signal_list):
        # Calculate position in grid
        row = (idx // n_cols) + 1
        col = (idx % n_cols) + 1
        
        # Check if signal exists in data
        if signal_name not in combined_df.columns:
            logger.warning(f"Signal {signal_name} not found in data columns")
            continue
        
        # Get signal data
        signal_data = combined_df[combined_df[signal_name].notna()].copy()
        
        if signal_data.empty:
            logger.warning(f"No data for signal {signal_name}")
            continue
        
        # Get signal status from signals_table for color mapping (for CURRENT week only)
        signal_row = signals_table[signals_table['signal'] == signal_name]
        if not signal_row.empty and 'signal_status' in signal_row.columns:
            signal_status = signal_row.iloc[0]['signal_status']
        else:
            signal_status = 'Normal'
        
        current_week_color = status_color_map.get(signal_status, '#28a745')
        
        # Get baseline thresholds for this signal (if available)
        signal_baselines = baseline_df[
            (baseline_df['Unit'] == unit_id) &
            (baseline_df['Signal'] == signal_name)
        ]
        percentile_refs = {}
        if not signal_baselines.empty:
            # Aggregate across states (take mean if multiple states exist)
            percentile_refs = {
                'P2': signal_baselines['P2'].mean(),
                'P5': signal_baselines['P5'].mean(),
                'P95': signal_baselines['P95'].mean(),
                'P98': signal_baselines['P98'].mean()
            }
        
        # Add horizontal boxplots + violins for each week
        for week_label in week_labels_sorted:
            week_data = signal_data[signal_data['week_label'] == week_label][signal_name]
            
            if not week_data.empty:
                # Determine if this is current week
                is_current = (week_label == f'Week {current_week:02d}/{current_year}')
                
                # Choose color
                box_color = current_week_color if is_current else historical_color
                
                # Add violin plot (no points, just density)
                fig.add_trace(
                    go.Violin(
                        x=week_data,
                        y=[week_label] * len(week_data),
                        name=week_label,
                        orientation='h',
                        side='both',
                        line_color=box_color,
                        fillcolor=box_color,
                        opacity=0.3,
                        points=False,  # No point cloud
                        meanline_visible=False,
                        showlegend=False,
                        width=0.8,
                        hoverinfo='skip'
                    ),
                    row=row, col=col
                )
                
                # Add box plot on top (median + quartiles)
                fig.add_trace(
                    go.Box(
                        x=week_data,
                        y=[week_label] * len(week_data),
                        name=week_label,
                        orientation='h',
                        boxmean=False,
                        marker=dict(
                            color=box_color,
                            opacity=0.7,
                            size=3
                        ),
                        line=dict(
                            width=2 if is_current else 1,
                            color=box_color
                        ),
                        fillcolor='rgba(255,255,255,0)',
                        boxpoints=False,  # No outlier points
                        showlegend=False,
                        width=0.4,
                        hovertemplate=(
                            f'<b>{week_label}</b><br>' +
                            'Median: %{x:.2f}<br>' +
                            '<extra></extra>'
                        )
                    ),
                    row=row, col=col
                )
        
        # Add baseline reference bands if available
        if percentile_refs:
            # P5-P95 "normal band" (light green)
            fig.add_vrect(
                x0=percentile_refs['P5'],
                x1=percentile_refs['P95'],
                fillcolor='rgba(40, 167, 69, 0.1)',  # Light green
                line_width=0,
                row=row, col=col,
                layer='below'
            )
            
            # P2 and P98 extreme bounds (dashed lines)
            fig.add_vline(
                x=percentile_refs['P2'],
                line=dict(color='rgba(220, 53, 69, 0.3)', dash='dot', width=1),
                row=row, col=col
            )
            fig.add_vline(
                x=percentile_refs['P98'],
                line=dict(color='rgba(220, 53, 69, 0.3)', dash='dot', width=1),
                row=row, col=col
            )
    
    # Add legend traces for status colors
    legend_traces = []
    for status, color in status_color_map.items():
        legend_traces.append(
            go.Scatter(
                x=[None],
                y=[None],
                mode='markers',
                marker=dict(size=10, color=color),
                name=f'{status}',
                showlegend=True
            )
        )
    legend_traces.append(
        go.Scatter(
            x=[None],
            y=[None],
            mode='markers',
            marker=dict(size=10, color=historical_color),
            name='Historical',
            showlegend=True
        )
    )
    
    # Add legend traces to figure
    for trace in legend_traces:
        fig.add_trace(trace)
    
    # Update layout
    fig.update_layout(
        title=dict(
            text=f'Weekly Signal Distributions - {component} (Unit: {unit_id})<br>' +
                 '<sub>Current week colored by evaluation status | P5-P95 baseline band</sub>',
            font=dict(size=14)
        ),
        height=350 * n_rows,
        showlegend=True,
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1,
            bgcolor='rgba(255,255,255,0.8)',
            bordercolor='lightgray',
            borderwidth=1
        ),
        font=dict(size=10),
        margin=dict(t=120, b=60, l=80, r=80)
    )
    
    # Update axes - only show y-axis label on leftmost column
    for i in range(1, n_rows + 1):
        for j in range(1, n_cols + 1):
            fig.update_xaxes(
                title_text="Value",
                showgrid=True,
                gridwidth=0.5,
                gridcolor='lightgray',
                row=i, col=j
            )
            if j == 1:
                fig.update_yaxes(
                    title_text="Week",
                    showgrid=False,
                    row=i, col=j
                )
            else:
                fig.update_yaxes(
                    showticklabels=False,
                    showgrid=False,
                    row=i, col=j
                )
    
    return fig


def build_daily_timeseries(
    unit_id: str,
    component: str,
    signal: str,
    combined_daily: pd.DataFrame,
    baseline_df: pd.DataFrame,
    current_week: int,
    current_year: int
) -> go.Figure:
    """
    Build daily time series boxplots for a single signal.
    
    Args:
        unit_id: Unit identifier
        component: Component name
        signal: Signal name
        combined_daily: Combined daily data across multiple weeks
        baseline_df: Baseline thresholds DataFrame
        current_week: Current evaluation week number
        current_year: Current evaluation year
    
    Returns:
        Plotly Figure with daily boxplot time series
    """
    if combined_daily.empty:
        logger.warning("Empty combined_daily provided to build_daily_timeseries")
        return go.Figure()
    
    # Check if signal exists
    if signal not in combined_daily.columns:
        logger.warning(f"Signal {signal} not found in data columns")
        return go.Figure()
    
    if 'Fecha' not in combined_daily.columns:
        logger.warning("'Fecha' column not found")
        return go.Figure()
    
    # Convert Fecha to datetime if needed
    if not pd.api.types.is_datetime64_any_dtype(combined_daily['Fecha']):
        combined_daily = combined_daily.copy()
        combined_daily['Fecha'] = pd.to_datetime(combined_daily['Fecha'])
    
    # Sort by date
    combined_daily = combined_daily.sort_values('Fecha')
    
    # Filter signal data
    signal_data = combined_daily[combined_daily[signal].notna()].copy()
    
    if signal_data.empty:
        logger.warning(f"No data for signal {signal}")
        return go.Figure()
    
    # Create date label
    signal_data['date_label'] = signal_data['Fecha'].dt.strftime('%m/%d')
    
    # Get unique dates in order
    date_labels = signal_data.groupby('date_label')['Fecha'].first().sort_values().index.tolist()
    
    # Get baseline thresholds for this signal (if available)
    signal_baselines = baseline_df[
        (baseline_df['Unit'] == unit_id) &
        (baseline_df['Signal'] == signal)
    ]
    percentile_refs = {}
    if not signal_baselines.empty:
        # Aggregate across states (take mean if multiple states exist)
        percentile_refs = {
            'P2': signal_baselines['P2'].mean(),
            'P5': signal_baselines['P5'].mean(),
            'P95': signal_baselines['P95'].mean(),
            'P98': signal_baselines['P98'].mean()
        }
    
    # Create plot
    fig = go.Figure()
    
    # Add violin + boxplot for each day
    for date_label in date_labels:
        day_data = signal_data[signal_data['date_label'] == date_label][signal]
        
        if not day_data.empty:
            # Add violin plot (no points, just density)
            fig.add_trace(
                go.Violin(
                    y=day_data,
                    x=[date_label] * len(day_data),
                    name=date_label,
                    orientation='v',
                    side='both',
                    line_color='#87CEEB',
                    fillcolor='#87CEEB',
                    opacity=0.3,
                    points=False,
                    meanline_visible=False,
                    showlegend=False,
                    width=0.8,
                    hoverinfo='skip'
                )
            )
            
            # Add box plot on top
            fig.add_trace(
                go.Box(
                    y=day_data,
                    x=[date_label] * len(day_data),
                    name=date_label,
                    orientation='v',
                    boxmean=False,
                    marker=dict(
                        color='#87CEEB',
                        opacity=0.7,
                        size=3
                    ),
                    line=dict(width=1, color='#87CEEB'),
                    fillcolor='rgba(255,255,255,0)',
                    boxpoints=False,
                    showlegend=False,
                    width=0.4,
                    hovertemplate=(
                        f'<b>{date_label}</b><br>' +
                        'Median: %{y:.2f}<br>' +
                        '<extra></extra>'
                    )
                )
            )
    
    # Add baseline reference bands if available
    if percentile_refs:
        # P5-P95 "normal band" (light green)
        fig.add_hrect(
            y0=percentile_refs['P5'],
            y1=percentile_refs['P95'],
            fillcolor='rgba(40, 167, 69, 0.1)',
            line_width=0,
            layer='below'
        )
        
        # P2 and P98 extreme bounds (dashed lines)
        fig.add_hline(
            y=percentile_refs['P2'],
            line=dict(color='rgba(220, 53, 69, 0.3)', dash='dot', width=1)
        )
        fig.add_hline(
            y=percentile_refs['P98'],
            line=dict(color='rgba(220, 53, 69, 0.3)', dash='dot', width=1)
        )
    
    # Update layout
    fig.update_layout(
        title=dict(
            text=f'Daily Time Series - {signal} - {component} (Unit: {unit_id})<br>' +
                 '<sub>4 weeks of data | P5-P95 baseline band</sub>',
            font=dict(size=14)
        ),
        height=500,
        showlegend=False,
        xaxis_title="Date (MM/DD)",
        yaxis_title="Value",
        xaxis=dict(showgrid=True, gridwidth=0.5, gridcolor='lightgray'),
        yaxis=dict(showgrid=True, gridwidth=0.5, gridcolor='lightgray'),
        font=dict(size=10),
        margin=dict(t=100, b=60, l=60, r=60)
    )
    
    return fig
