"""
Chart components for Telemetry Dashboard.

Reusable Plotly figure builders for telemetry monitoring visualizations.
"""

import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ========================================
# COLOR SCHEMES
# ========================================

STATUS_COLORS = {
    'Normal': '#28a745',
    'Alerta': '#ffc107',
    'Anormal': '#dc3545',
    'InsufficientData': '#6c757d'
}

HISTORICAL_COLOR = '#B0C4DE'  # Light steel blue


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
        height=300
    )
    return fig


# ========================================
# FLEET OVERVIEW CHARTS
# ========================================

def build_fleet_kpi_cards(machine_df: pd.DataFrame) -> go.Figure:
    """
    Build KPI indicator cards for fleet health overview.
    
    Args:
        machine_df: DataFrame with machine status (filtered to latest week)
    
    Returns:
        Plotly Figure with 4 indicator traces
    """
    if machine_df.empty:
        return _empty_figure("Sin datos de flota disponibles")

    try:
        total_units = len(machine_df)
        status_counts = machine_df['overall_status'].value_counts()

        normal_count = status_counts.get('Normal', 0)
        alerta_count = status_counts.get('Alerta', 0)
        anormal_count = status_counts.get('Anormal', 0)

        normal_pct = (normal_count / total_units) * 100 if total_units > 0 else 0
        alerta_pct = (alerta_count / total_units) * 100 if total_units > 0 else 0
        anormal_pct = (anormal_count / total_units) * 100 if total_units > 0 else 0

        fig = make_subplots(
            rows=1, cols=4,
            specs=[[{'type': 'indicator'}] * 4],
            subplot_titles=('Total Unidades', 'Normal', 'Alerta', 'Anormal')
        )

        # Total Units
        fig.add_trace(go.Indicator(
            mode="number",
            value=total_units,
            number={'font': {'size': 40}}
        ), row=1, col=1)

        # Normal
        fig.add_trace(go.Indicator(
            mode="number",
            value=normal_count,
            title={'text': f"{normal_pct:.1f}%"},
            number={'font': {'size': 40, 'color': STATUS_COLORS['Normal']}}
        ), row=1, col=2)

        # Alerta
        fig.add_trace(go.Indicator(
            mode="number",
            value=alerta_count,
            title={'text': f"{alerta_pct:.1f}%"},
            number={'font': {'size': 40, 'color': STATUS_COLORS['Alerta']}}
        ), row=1, col=3)

        # Anormal
        fig.add_trace(go.Indicator(
            mode="number",
            value=anormal_count,
            title={'text': f"{anormal_pct:.1f}%"},
            number={'font': {'size': 40, 'color': STATUS_COLORS['Anormal']}}
        ), row=1, col=4)

        fig.update_layout(
            height=200,
            showlegend=False,
            margin=dict(t=40, b=10, l=10, r=10)
        )

        return fig

    except Exception as e:
        logger.error(f"Error building fleet KPI cards: {e}")
        return _empty_figure(f"Error: {str(e)}")


def build_fleet_pie_chart(machine_df: pd.DataFrame) -> go.Figure:
    """
    Build status distribution pie chart for fleet overview.
    
    Args:
        machine_df: DataFrame with machine status (filtered to latest week)
    
    Returns:
        Plotly Figure with pie chart
    """
    if machine_df.empty:
        return _empty_figure("Sin datos de flota disponibles")

    try:
        status_counts = machine_df['overall_status'].value_counts()

        fig = go.Figure(data=[go.Pie(
            labels=status_counts.index,
            values=status_counts.values,
            marker=dict(colors=[STATUS_COLORS.get(s, '#999') for s in status_counts.index]),
            textinfo='label+value+percent',
            textposition='auto',
            hovertemplate='%{label}<br>Cantidad: %{value}<br>Porcentaje: %{percent}<extra></extra>'
        )])

        fig.update_layout(
            title_text="Distribución de Estado de Flota",
            height=400,
            showlegend=True,
            legend=dict(orientation='h', yanchor='bottom', y=-0.1, xanchor='center', x=0.5),
            margin=dict(t=50, b=50, l=20, r=20)
        )

        return fig

    except Exception as e:
        logger.error(f"Error building fleet pie chart: {e}")
        return _empty_figure(f"Error: {str(e)}")


# ========================================
# MACHINE DETAIL CHARTS
# ========================================

def build_component_radar_chart(component_details: List[Dict]) -> go.Figure:
    """
    Build radar chart showing component health scores.
    
    Args:
        component_details: List of component dictionaries with 'component' and 'component_score'
    
    Returns:
        Plotly Figure with radar chart
    """
    if not component_details:
        return _empty_figure("Sin datos de componentes disponibles")

    try:
        df = pd.DataFrame(component_details)

        if 'component' not in df.columns or 'component_score' not in df.columns:
            return _empty_figure("Faltan campos de datos de componentes")

        # Sort by component name
        df = df.sort_values('component')

        categories = df['component'].tolist()
        values = df['component_score'].tolist()

        # Close the radar polygon
        categories_closed = categories + [categories[0]]
        values_closed = values + [values[0]]

        # Determine fill color based on worst status
        statuses = df.get('component_status', pd.Series(['Normal'] * len(df)))
        if 'Anormal' in statuses.values:
            fill_color = 'rgba(220, 53, 69, 0.2)'
            line_color = STATUS_COLORS['Anormal']
        elif 'Alerta' in statuses.values:
            fill_color = 'rgba(255, 193, 7, 0.2)'
            line_color = STATUS_COLORS['Alerta']
        else:
            fill_color = 'rgba(40, 167, 69, 0.2)'
            line_color = STATUS_COLORS['Normal']

        fig = go.Figure()

        fig.add_trace(go.Scatterpolar(
            r=values_closed,
            theta=categories_closed,
            fill='toself',
            fillcolor=fill_color,
            line=dict(color=line_color, width=2),
            marker=dict(size=8, color=line_color),
            name='Score Componente',
            hovertemplate='%{theta}<br>Score: %{r:.3f}<extra></extra>'
        ))

        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, max(values) * 1.2 if max(values) > 0 else 1],
                    showticklabels=True,
                    tickfont=dict(size=9)
                ),
                angularaxis=dict(tickfont=dict(size=10))
            ),
            showlegend=False,
            title="Radar de Salud de Componentes",
            height=400,
            margin=dict(t=50, b=20, l=60, r=60)
        )

        return fig

    except Exception as e:
        logger.error(f"Error building component radar chart: {e}")
        return _empty_figure(f"Error: {str(e)}")


# ========================================
# COMPONENT DETAIL CHARTS
# ========================================

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
    Build weekly distribution boxplots with baseline bands for multiple signals.
    
    Horizontal boxplots showing 6 weeks of data per signal, with current week
    colored by evaluation status and P5-P95 baseline bands.
    
    Args:
        unit_id: Selected unit ID
        component: Selected component name
        signals_table: DataFrame with signal evaluations (signal, signal_status, score)
        combined_df: Concatenated silver data for all weeks
        baseline_df: Baseline thresholds DataFrame
        current_week: Current evaluation week number
        current_year: Current evaluation year
    
    Returns:
        Plotly Figure with multi-signal boxplot grid
    """
    if signals_table.empty or combined_df.empty:
        return _empty_figure("Sin datos de señales disponibles para gráficos")

    try:
        signal_list = signals_table['signal'].tolist()
        num_signals = len(signal_list)

        if num_signals == 0:
            return _empty_figure("Sin señales para graficar")

        # Determine grid layout (max 2 columns)
        if num_signals == 1:
            n_rows, n_cols = 1, 1
        elif num_signals == 2:
            n_rows, n_cols = 1, 2
        else:
            n_cols = 2
            n_rows = (num_signals + 1) // 2

        # Create subplots
        fig = make_subplots(
            rows=n_rows,
            cols=n_cols,
            subplot_titles=[s for s in signal_list],
            vertical_spacing=0.08,
            horizontal_spacing=0.10,
            shared_yaxes=True if n_cols > 1 else False
        )

        # Get baselines for this unit
        unit_baselines = pd.DataFrame()
        if baseline_df is not None and not baseline_df.empty:
            unit_baselines = baseline_df[
                (baseline_df['Unit'] == unit_id) &
                (baseline_df['Signal'].isin(signal_list))
            ].copy()

        # Sort weeks chronologically (most recent at top)
        week_labels_sorted = sorted(
            combined_df['week_label'].unique(),
            key=lambda x: (int(x.split('/')[1]), int(x.split()[1].split('/')[0])),
            reverse=True
        )

        for idx, signal_name in enumerate(signal_list):
            row = (idx // n_cols) + 1
            col = (idx % n_cols) + 1

            if signal_name not in combined_df.columns:
                continue

            signal_data = combined_df[combined_df[signal_name].notna()].copy()
            if signal_data.empty:
                continue

            # Get signal status
            signal_row = signals_table[signals_table['signal'] == signal_name]
            signal_status = 'Normal'
            if not signal_row.empty and 'signal_status' in signal_row.columns:
                signal_status = signal_row.iloc[0]['signal_status']

            current_week_color = STATUS_COLORS.get(signal_status, STATUS_COLORS['Normal'])

            # Get baselines
            percentile_refs = {}
            if not unit_baselines.empty:
                signal_baselines = unit_baselines[unit_baselines['Signal'] == signal_name]
                if not signal_baselines.empty:
                    percentile_refs = {
                        'P2': signal_baselines['P2'].mean(),
                        'P5': signal_baselines['P5'].mean(),
                        'P95': signal_baselines['P95'].mean(),
                        'P98': signal_baselines['P98'].mean()
                    }

            # Add boxplots per week
            for week_label in week_labels_sorted:
                week_data = signal_data[signal_data['week_label'] == week_label][signal_name]
                if week_data.empty:
                    continue

                is_current = (week_label == f'Sem {current_week:02d}/{current_year}')
                box_color = current_week_color if is_current else HISTORICAL_COLOR

                # Violin (density)
                fig.add_trace(
                    go.Violin(
                        x=week_data,
                        y=[week_label] * len(week_data),
                        orientation='h',
                        side='both',
                        line_color=box_color,
                        fillcolor=box_color,
                        opacity=0.3,
                        points=False,
                        meanline_visible=False,
                        showlegend=False,
                        width=0.8,
                        hoverinfo='skip'
                    ),
                    row=row, col=col
                )

                # Box (median + quartiles)
                fig.add_trace(
                    go.Box(
                        x=week_data,
                        y=[week_label] * len(week_data),
                        orientation='h',
                        boxmean=False,
                        marker=dict(color=box_color, opacity=0.7, size=3),
                        line=dict(width=2 if is_current else 1, color=box_color),
                        fillcolor='rgba(255,255,255,0)',
                        boxpoints=False,
                        showlegend=False,
                        width=0.4,
                        hovertemplate=(
                            f'<b>{week_label}</b><br>'
                            'Mediana: %{x:.2f}<br>'
                            '<extra></extra>'
                        )
                    ),
                    row=row, col=col
                )

            # Add baseline bands
            if percentile_refs:
                fig.add_vrect(
                    x0=percentile_refs['P5'],
                    x1=percentile_refs['P95'],
                    fillcolor='rgba(40, 167, 69, 0.1)',
                    line_width=0,
                    row=row, col=col,
                    layer='below'
                )
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

        # Add status legend traces
        for status, color in STATUS_COLORS.items():
            if status != 'InsufficientData':
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode='markers',
                    marker=dict(size=10, color=color),
                    name=status, showlegend=True
                ))
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode='markers',
            marker=dict(size=10, color=HISTORICAL_COLOR),
            name='Histórico', showlegend=True
        ))

        fig.update_layout(
            title=dict(
                text=(
                    f'Distribución Semanal de Señales - {component} (Unidad: {unit_id})<br>'
                    '<sub>Semana actual con color de estado | Banda baseline P5-P95</sub>'
                ),
                font=dict(size=14)
            ),
            height=350 * n_rows,
            showlegend=True,
            legend=dict(
                orientation='h', yanchor='bottom', y=1.02,
                xanchor='right', x=1,
                bgcolor='rgba(255,255,255,0.8)',
                bordercolor='lightgray', borderwidth=1
            ),
            font=dict(size=10)
        )

        # Axis formatting
        for i in range(1, n_rows + 1):
            for j in range(1, n_cols + 1):
                fig.update_xaxes(
                    title_text="Valor", showgrid=True,
                    gridwidth=0.5, gridcolor='lightgray',
                    row=i, col=j
                )
                if j == 1:
                    fig.update_yaxes(
                        title_text="Semana", showgrid=False, row=i, col=j
                    )
                else:
                    fig.update_yaxes(
                        showticklabels=False, showgrid=False, row=i, col=j
                    )

        return fig

    except Exception as e:
        logger.error(f"Error building weekly boxplots: {e}")
        import traceback
        traceback.print_exc()
        return _empty_figure(f"Error: {str(e)}")


def build_daily_timeseries(
    selected_signal: str,
    unit_id: str,
    component: str,
    combined_daily: pd.DataFrame,
    baseline_df: pd.DataFrame
) -> go.Figure:
    """
    Build daily time series boxplots for a single signal across multiple weeks.
    
    Args:
        selected_signal: Signal name to plot
        unit_id: Selected unit ID
        component: Selected component name
        combined_daily: Concatenated daily data with 'Fecha' column
        baseline_df: Baseline thresholds DataFrame
    
    Returns:
        Plotly Figure with daily violin + box plots
    """
    if combined_daily.empty or selected_signal not in combined_daily.columns:
        return _empty_figure(f"Sin datos para la señal {selected_signal}")

    try:
        # Ensure datetime
        if not pd.api.types.is_datetime64_any_dtype(combined_daily['Fecha']):
            combined_daily = combined_daily.copy()
            combined_daily['Fecha'] = pd.to_datetime(combined_daily['Fecha'])

        combined_daily = combined_daily.sort_values('Fecha')
        signal_data = combined_daily[combined_daily[selected_signal].notna()].copy()

        if signal_data.empty:
            return _empty_figure(f"Sin datos para la señal {selected_signal}")

        signal_data['date_label'] = signal_data['Fecha'].dt.strftime('%m/%d')
        date_labels = signal_data.groupby('date_label')['Fecha'].first().sort_values().index.tolist()

        # Get baselines
        percentile_refs = {}
        if baseline_df is not None and not baseline_df.empty:
            unit_baselines = baseline_df[
                (baseline_df['Unit'] == unit_id) &
                (baseline_df['Signal'] == selected_signal)
            ]
            if not unit_baselines.empty:
                percentile_refs = {
                    'P2': unit_baselines['P2'].mean(),
                    'P5': unit_baselines['P5'].mean(),
                    'P95': unit_baselines['P95'].mean(),
                    'P98': unit_baselines['P98'].mean()
                }

        fig = go.Figure()

        for date_label in date_labels:
            day_data = signal_data[signal_data['date_label'] == date_label][selected_signal]
            if day_data.empty:
                continue

            fig.add_trace(go.Violin(
                y=day_data, x=[date_label] * len(day_data),
                orientation='v', side='both',
                line_color='#87CEEB', fillcolor='#87CEEB',
                opacity=0.3, points=False,
                meanline_visible=False, showlegend=False,
                width=0.8, hoverinfo='skip'
            ))

            fig.add_trace(go.Box(
                y=day_data, x=[date_label] * len(day_data),
                orientation='v', boxmean=False,
                marker=dict(color='#87CEEB', opacity=0.7, size=3),
                line=dict(width=1, color='#87CEEB'),
                fillcolor='rgba(255,255,255,0)',
                boxpoints=False, showlegend=False,
                width=0.4,
                hovertemplate=(
                    f'<b>{date_label}</b><br>'
                    'Mediana: %{y:.2f}<br>'
                    '<extra></extra>'
                )
            ))

        if percentile_refs:
            fig.add_hrect(
                y0=percentile_refs['P5'], y1=percentile_refs['P95'],
                fillcolor='rgba(40, 167, 69, 0.1)',
                line_width=0, layer='below'
            )
            fig.add_hline(
                y=percentile_refs['P2'],
                line=dict(color='rgba(220, 53, 69, 0.3)', dash='dot', width=1)
            )
            fig.add_hline(
                y=percentile_refs['P98'],
                line=dict(color='rgba(220, 53, 69, 0.3)', dash='dot', width=1)
            )

        fig.update_layout(
            title=dict(
                text=(
                    f'Serie Temporal Diaria - {selected_signal} - {component} '
                    f'(Unidad: {unit_id})<br>'
                    '<sub>Banda baseline P5-P95</sub>'
                ),
                font=dict(size=14)
            ),
            height=500,
            showlegend=False,
            xaxis_title="Fecha (MM/DD)",
            yaxis_title="Valor",
            xaxis=dict(showgrid=True, gridwidth=0.5, gridcolor='lightgray'),
            yaxis=dict(showgrid=True, gridwidth=0.5, gridcolor='lightgray'),
            font=dict(size=10)
        )

        return fig

    except Exception as e:
        logger.error(f"Error building daily timeseries: {e}")
        return _empty_figure(f"Error: {str(e)}")
