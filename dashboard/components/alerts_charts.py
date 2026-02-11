"""
Chart components for Alerts Dashboard.

Functions to create Plotly figures for alerts analytics.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import plotly.colors

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Operational state color mapping
STATE_COLORS = {
    'Operacional': '#2ecc71',  # Green
    'Ralenti': '#f39c12',      # Orange
    'ND': '#95a5a6'            # Gray
}


def create_alerts_per_unit_chart(alerts_df: pd.DataFrame) -> go.Figure:
    """
    Create horizontal bar chart showing distribution of alerts per unit.
    
    Args:
        alerts_df: DataFrame with columns ['UnitId', 'sistema']
    
    Returns:
        Plotly Figure with horizontal bar chart
    """
    if alerts_df.empty:
        logger.warning("Cannot create alerts per unit chart: empty dataframe")
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Count alerts per unit and system
        alerts_per_unit = alerts_df.groupby(['UnitId', 'sistema']).size().reset_index(name='Count')
        
        # Sort systems in reverse alphabetical order for consistent ordering
        alerts_per_unit['sistema'] = pd.Categorical(
            alerts_per_unit['sistema'],
            categories=sorted(alerts_per_unit['sistema'].unique(), reverse=True),
            ordered=True
        )
        alerts_per_unit = alerts_per_unit.sort_values('sistema')
        
        # Create horizontal bar chart
        fig = px.bar(
            alerts_per_unit,
            y='UnitId',
            x='Count',
            color='sistema',
            orientation='h',
            title='Distribución de Alertas por Unidad',
            labels={'Count': 'Número de Alertas', 'UnitId': 'Unidad'},
            template='plotly_white',
            height=500,
            color_discrete_sequence=plotly.colors.qualitative.Set1
        )
        
        fig.update_layout(
            yaxis={'categoryorder': 'total ascending'},
            showlegend=True,
            legend=dict(title='Sistema'),
            hovermode='closest'
        )
        
        logger.info("Created alerts per unit chart successfully")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating alerts per unit chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_alerts_per_month_chart(alerts_df: pd.DataFrame) -> go.Figure:
    """
    Create vertical bar chart showing distribution of alerts per month.
    
    Args:
        alerts_df: DataFrame with columns ['Month', 'sistema']
    
    Returns:
        Plotly Figure with vertical bar chart
    """
    if alerts_df.empty:
        logger.warning("Cannot create alerts per month chart: empty dataframe")
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Count alerts per month and system
        alerts_per_month = alerts_df.groupby(['Month', 'sistema']).size().reset_index(name='Count')
        alerts_per_month['Month_str'] = alerts_per_month['Month'].astype(str)
        
        # Sort systems in reverse alphabetical order for consistent ordering
        alerts_per_month['sistema'] = pd.Categorical(
            alerts_per_month['sistema'],
            categories=sorted(alerts_per_month['sistema'].unique(), reverse=True),
            ordered=True
        )
        alerts_per_month = alerts_per_month.sort_values('sistema')
        
        # Create vertical bar chart
        fig = px.bar(
            alerts_per_month,
            x='Month_str',
            y='Count',
            color='sistema',
            title='Distribución de Alertas por Mes',
            labels={'Month_str': 'Mes', 'Count': 'Número de Alertas'},
            template='plotly_white',
            height=500,
            color_discrete_sequence=plotly.colors.qualitative.Set1
        )
        
        fig.update_layout(
            xaxis_tickangle=-45,
            showlegend=True,
            legend=dict(title='Sistema'),
            hovermode='x unified'
        )
        
        logger.info("Created alerts per month chart successfully")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating alerts per month chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_trigger_distribution_treemap(alerts_df: pd.DataFrame) -> go.Figure:
    """
    Create treemap showing distribution of alert triggers.
    
    Args:
        alerts_df: DataFrame with column ['Trigger_type']
    
    Returns:
        Plotly Figure with treemap
    """
    if alerts_df.empty:
        logger.warning("Cannot create trigger distribution treemap: empty dataframe")
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Count alerts by trigger type
        trigger_counts = alerts_df['Trigger_type'].value_counts().reset_index()
        trigger_counts.columns = ['Trigger_type', 'Frequency']
        
        # Create treemap
        fig = px.treemap(
            trigger_counts,
            path=['Trigger_type'],
            values='Frequency',
            title='Distribución de Fuente de Alertas',
            color='Frequency',
            color_continuous_scale='Blues',
            height=500
        )
        
        fig.update_traces(
            textinfo='label+value+percent parent',
            textfont_size=14
        )
        
        logger.info("Created trigger distribution treemap successfully")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating trigger distribution treemap: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_sensor_trends_chart(
    telemetry_values: pd.DataFrame,
    telemetry_states: pd.DataFrame,
    limits_config: pd.DataFrame,
    unit_id: str,
    sensor_columns: List[str],
    alert_time: datetime,
    window_start: datetime,
    window_end: datetime,
    feature_names: Dict[str, str]
) -> go.Figure:
    """
    Create multi-panel time series chart showing sensor trends with limits.
    
    Args:
        telemetry_values: DataFrame with telemetry sensor values
        telemetry_states: DataFrame with operational states
        limits_config: DataFrame with sensor limits
        unit_id: Unit identifier
        sensor_columns: List of sensor column names to display
        alert_time: Alert timestamp
        window_start: Start of time window
        window_end: End of time window
        feature_names: Dictionary mapping feature codes to Spanish names
    
    Returns:
        Plotly Figure with subplots (one per sensor)
    """
    if telemetry_values.empty:
        logger.warning("Cannot create sensor trends chart: empty telemetry values")
        return go.Figure().add_annotation(
            text="No telemetry data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Filter data for unit and time window
        unit_data = telemetry_values[
            (telemetry_values['Unit'] == unit_id) &
            (telemetry_values['Fecha'] >= window_start) &
            (telemetry_values['Fecha'] <= window_end)
        ].copy()
        
        # Merge with states
        if not telemetry_states.empty:
            unit_data = unit_data.merge(
                telemetry_states[['Fecha', 'Unit', 'Estado', 'EstadoCarga']],
                on=['Fecha', 'Unit'],
                how='left'
            )
        
        if unit_data.empty:
            logger.warning("No telemetry data in time window")
            return go.Figure().add_annotation(
                text="No data in time window",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
        
        # Merge limits into unit_data
        if not limits_config.empty:
            unit_limits = limits_config[limits_config['Unit'] == unit_id].copy()
            
            for sensor in sensor_columns:
                feature_limits = unit_limits[unit_limits['Feature'] == sensor].copy()
                
                if not feature_limits.empty:
                    feature_limits = feature_limits.rename(columns={
                        'Limit_Lower': f'{sensor}_Lower',
                        'Limit_Upper': f'{sensor}_Upper'
                    })
                    
                    unit_data = unit_data.merge(
                        feature_limits[['Estado', 'EstadoCarga', f'{sensor}_Lower', f'{sensor}_Upper']],
                        on=['Estado', 'EstadoCarga'],
                        how='left'
                    )
        
        # Create subplots
        fig = make_subplots(
            rows=len(sensor_columns),
            cols=1,
            shared_xaxes=True,
            subplot_titles=[feature_names.get(sensor, sensor) for sensor in sensor_columns],
            vertical_spacing=0.08
        )
        
        # Plot each sensor
        for idx, sensor in enumerate(sensor_columns, 1):
            sensor_name = feature_names.get(sensor, sensor)
            
            # Plot data points colored by operational state
            for estado in unit_data['Estado'].dropna().unique():
                estado_data = unit_data[unit_data['Estado'] == estado]
                
                fig.add_trace(
                    go.Scatter(
                        x=estado_data['Fecha'],
                        y=estado_data[sensor],
                        mode='markers',
                        name=f'{estado}',
                        legendgroup=estado,
                        showlegend=(idx == 1),  # Only show legend for first subplot
                        marker=dict(
                            color=STATE_COLORS.get(estado, '#95a5a6'),
                            size=6
                        ),
                        hovertemplate=(
                            f'<b>{sensor_name}</b><br>' +
                            'Hora: %{x}<br>' +
                            'Valor: %{y:.2f}<br>' +
                            f'Estado: {estado}<br>' +
                            '<extra></extra>'
                        )
                    ),
                    row=idx,
                    col=1
                )
            
            # Plot continuous limit lines
            lower_col = f'{sensor}_Lower'
            upper_col = f'{sensor}_Upper'
            
            if lower_col in unit_data.columns and unit_data[lower_col].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=unit_data['Fecha'],
                        y=unit_data[lower_col],
                        mode='lines',
                        name='Límite Inferior',
                        legendgroup='limits',
                        showlegend=(idx == 1),
                        line=dict(color='red', width=2, dash='dash'),
                        hovertemplate='Límite Inferior: %{y:.2f}<extra></extra>'
                    ),
                    row=idx,
                    col=1
                )
            
            if upper_col in unit_data.columns and unit_data[upper_col].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=unit_data['Fecha'],
                        y=unit_data[upper_col],
                        mode='lines',
                        name='Límite Superior',
                        legendgroup='limits',
                        showlegend=(idx == 1),
                        line=dict(color='red', width=2, dash='dash'),
                        hovertemplate='Límite Superior: %{y:.2f}<extra></extra>'
                    ),
                    row=idx,
                    col=1
                )
            
            # Add alert time marker
            y_min = unit_data[sensor].min()
            y_max = unit_data[sensor].max()
            
            if lower_col in unit_data.columns and unit_data[lower_col].notna().any():
                y_min = min(y_min, unit_data[lower_col].min())
            if upper_col in unit_data.columns and unit_data[upper_col].notna().any():
                y_max = max(y_max, unit_data[upper_col].max())
            
            if pd.notna(y_min) and pd.notna(y_max):
                y_range = y_max - y_min if y_max != y_min else 1
                y_extended_min = y_min - (0.1 * y_range)
                y_extended_max = y_max + (0.1 * y_range)
                
                fig.add_trace(
                    go.Scatter(
                        x=[alert_time, alert_time],
                        y=[y_extended_min, y_extended_max],
                        mode='lines',
                        name='⚠️ Alerta',
                        legendgroup='alert',
                        showlegend=(idx == 1),
                        line=dict(color='orange', width=3),
                        hovertemplate=f"Momento de Alerta: {alert_time}<extra></extra>"
                    ),
                    row=idx,
                    col=1
                )
        
        # Update layout
        fig.update_layout(
            title={
                'text': f'Análisis de Tendencias - {unit_id}',
                'x': 0.5,
                'xanchor': 'center',
                'font': dict(size=16, color='#2c3e50')
            },
            height=300 * len(sensor_columns),
            template='plotly_white',
            hovermode='x unified',
            margin=dict(l=60, r=20, t=50, b=40)
        )
        
        # Update axes
        fig.update_xaxes(
            title_text='Hora',
            showgrid=True,
            gridwidth=1,
            gridcolor='#ecf0f1',
            row=len(sensor_columns),
            col=1
        )
        
        for i in range(1, len(sensor_columns) + 1):
            fig.update_yaxes(
                title_text='Valor',
                showgrid=True,
                gridwidth=1,
                gridcolor='#ecf0f1',
                row=i,
                col=1
            )
        
        logger.info(f"Created sensor trends chart with {len(sensor_columns)} sensors")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating sensor trends chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_gps_route_map(
    telemetry_values: pd.DataFrame,
    unit_id: str,
    alert_time: datetime,
    window_start: datetime,
    window_end: datetime,
    mapbox_token: str
) -> go.Figure:
    """
    Create GPS route map with alert location.
    
    Args:
        telemetry_values: DataFrame with GPS columns (GPSLat, GPSLon, Fecha)
        unit_id: Unit identifier
        alert_time: Alert timestamp
        window_start: Start of time window
        window_end: End of time window
        mapbox_token: Mapbox access token
    
    Returns:
        Plotly Figure with GPS map
    """
    if telemetry_values.empty:
        logger.warning("Cannot create GPS map: empty telemetry values")
        return go.Figure().add_annotation(
            text="No GPS data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Filter data
        unit_data = telemetry_values[
            (telemetry_values['Unit'] == unit_id) &
            (telemetry_values['Fecha'] >= window_start) &
            (telemetry_values['Fecha'] <= window_end)
        ].copy()
        
        gps_data = unit_data.dropna(subset=['GPSLat', 'GPSLon']).copy()
        
        if gps_data.empty:
            logger.warning("No GPS data in time window")
            return go.Figure().add_annotation(
                text="No GPS data in time window",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
        
        # Normalize time for color gradient
        time_min = gps_data['Fecha'].min()
        time_max = gps_data['Fecha'].max()
        
        if time_max > time_min:
            gps_data['TimeNorm'] = (gps_data['Fecha'] - time_min) / (time_max - time_min)
        else:
            gps_data['TimeNorm'] = 0.5
        
        # Create map
        fig = go.Figure()
        
        # Add route line
        fig.add_trace(go.Scattermapbox(
            lat=gps_data['GPSLat'],
            lon=gps_data['GPSLon'],
            mode='lines',
            line=dict(width=2, color='rgba(100, 100, 100, 0.5)'),
            showlegend=False,
            hoverinfo='skip'
        ))
        
        # Add colored points
        fig.add_trace(go.Scattermapbox(
            lat=gps_data['GPSLat'],
            lon=gps_data['GPSLon'],
            mode='markers',
            marker=dict(
                size=10,
                color=gps_data['TimeNorm'],
                colorscale='Reds',
                showscale=False
            ),
            showlegend=False,
            text=gps_data['Fecha'].dt.strftime('%H:%M:%S'),
            hovertemplate='Hora: %{text}<extra></extra>'
        ))
        
        # Add alert marker
        alert_idx = (gps_data['Fecha'] - alert_time).abs().argmin()
        alert_point = gps_data.iloc[alert_idx]
        
        fig.add_trace(go.Scattermapbox(
            lat=[alert_point['GPSLat']],
            lon=[alert_point['GPSLon']],
            mode='markers',
            marker=dict(
                size=25,
                color='black',
                symbol='marker'
            ),
            showlegend=False,
            text=[f"⚠️ Alerta: {alert_time.strftime('%H:%M:%S')}"],
            hovertemplate='%{text}<extra></extra>'
        ))
        
        fig.update_layout(
            mapbox=dict(
                accesstoken=mapbox_token,
                style="satellite-streets",
                center=dict(
                    lat=gps_data['GPSLat'].mean(),
                    lon=gps_data['GPSLon'].mean()
                ),
                zoom=14
            ),
            title='Ruta GPS - Vista Satelital',
            height=600,
            margin=dict(l=0, r=0, t=40, b=0),
            showlegend=False
        )
        
        logger.info(f"Created GPS route map with {len(gps_data)} points")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating GPS route map: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_oil_radar_chart(oil_report: pd.Series, essay_cols: List[str]) -> go.Figure:
    """
    Create radar chart showing oil essay levels.
    
    Args:
        oil_report: Series with oil report data
        essay_cols: List of essay column names (ending with _ppm)
    
    Returns:
        Plotly Figure with radar chart
    """
    # Check if data is available (Series doesn't have .empty attribute)
    if oil_report is None or len(oil_report) == 0 or not essay_cols:
        logger.warning("Cannot create oil radar chart: empty data or no essay columns")
        return go.Figure().add_annotation(
            text="No oil data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        fig = go.Figure()
        
        # Get values for each essay column
        r_values = [float(oil_report.get(col, 0)) if pd.notna(oil_report.get(col, 0)) else 0 for col in essay_cols]
        theta_values = [col.replace('_ppm', '').replace('_', ' ').title() for col in essay_cols]
        
        # Calculate max value for scale (ensure at least 1 for visibility)
        max_value = max(r_values) if max(r_values) > 0 else 1
        
        # Add actual values
        fig.add_trace(go.Scatterpolar(
            r=r_values,
            theta=theta_values,
            fill='toself',
            name='Valores Actuales',
            line_color='#3498db',
            hovertemplate='<b>%{theta}</b><br>Valor: %{r:.2f} ppm<extra></extra>'
        ))
        
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, max_value * 1.2]
                )
            ),
            title='Análisis de Aceite - Niveles de Elementos',
            height=500,
            showlegend=True
        )
        
        logger.info(f"Created oil radar chart successfully with {len(essay_cols)} essays")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating oil radar chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_system_distribution_pie_chart(alerts_df: pd.DataFrame) -> go.Figure:
    """
    Create pie chart showing distribution of alerts per system.
    
    Args:
        alerts_df: DataFrame with column ['sistema']
    
    Returns:
        Plotly Figure with pie chart
    """
    if alerts_df.empty:
        logger.warning("Cannot create system distribution pie chart: empty dataframe")
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Count alerts by system
        system_counts = alerts_df['sistema'].value_counts().reset_index()
        system_counts.columns = ['sistema', 'Count']
        
        # Sort systems in reverse alphabetical order
        system_counts = system_counts.sort_values('sistema', ascending=False)
        
        # Create pie chart
        fig = px.pie(
            system_counts,
            values='Count',
            names='sistema',
            title='Distribución por Sistema',
            hole=0.3,  # Makes it a donut chart
            color_discrete_sequence=plotly.colors.qualitative.Set1
        )
        
        fig.update_traces(
            textposition='inside',
            textinfo='percent+label',
            hovertemplate='<b>%{label}</b><br>Alertas: %{value}<br>Porcentaje: %{percent}<extra></extra>'
        )
        
        fig.update_layout(
            height=500,
            showlegend=True,
            legend=dict(
                orientation="v",
                yanchor="middle",
                y=0.5,
                xanchor="left",
                x=1.05
            )
        )
        
        logger.info("Created system distribution pie chart successfully")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating system distribution pie chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
