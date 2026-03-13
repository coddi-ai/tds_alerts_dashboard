# Standard color mapping for sistema
SISTEMA_COLORS = {
    'Tren de Fuerza': '#1f77b4',
    'Motor': '#ff7f0e',
    'Frenos': '#2ca02c',
    'Direccion': '#d62728',
}
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
import dash_bootstrap_components as dbc
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
            title=None,
            labels={'Count': 'Número de Alertas', 'UnitId': 'Unidad'},
            template='plotly_white',
            height=500,
            color_discrete_map=SISTEMA_COLORS
        )
        # Horizontal, compact legend at top right
        fig.update_layout(
            yaxis={'categoryorder': 'total ascending'},
            showlegend=True,
            legend=dict(
                title='Sistema',
                orientation='h',
                x=1,
                y=1.08,
                xanchor='right',
                yanchor='bottom',
                font=dict(size=11),
                itemwidth=80
            ),
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
            title=None,
            labels={'Month_str': 'Mes', 'Count': 'Número de Alertas'},
            template='plotly_white',
            height=500,
            color_discrete_map=SISTEMA_COLORS
        )
        # Horizontal, compact legend at top right
        fig.update_layout(
            xaxis_tickangle=-45,
            showlegend=True,
            legend=dict(
                title='Sistema',
                orientation='h',
                x=1,
                y=1.08,
                xanchor='right',
                yanchor='bottom',
                font=dict(size=11),
                itemwidth=80
            ),
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
        
        # Create treemap (no frequency bar, just label)
        fig = px.treemap(
            trigger_counts,
            path=['Trigger_type'],
            values='Frequency',
            title=None,
            color_discrete_sequence=['#3498db'],
            height=500
        )
        fig.update_traces(
            textinfo='label+percent parent',
            textfont_size=14
        )
        fig.update_layout(showlegend=False)
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
    **DEPRECATED**: Use create_sensor_trends_chart_golden() instead.
    
    Old implementation: Create multi-panel time series chart showing sensor trends with limits.
    This function loads from silver layer and performs complex merging operations.
    
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
    **DEPRECATED**: Use create_gps_route_map_golden() instead.
    
    Old implementation: Create GPS route map with alert location.
    This function loads from silver layer and performs filtering operations.
    
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
        
        # Create pie chart with standard color mapping
        fig = px.pie(
            system_counts,
            values='Count',
            names='sistema',
            title=None,  # Remove title
            hole=0.3,  # Makes it a donut chart
            color='sistema',
            color_discrete_map=SISTEMA_COLORS
        )
        fig.update_traces(
            textposition='inside',
            textinfo='percent+label',
            hovertemplate='<b>%{label}</b><br>Alertas: %{value}<br>Porcentaje: %{percent}<extra></extra>'
        )
        # Remove legend
        fig.update_layout(
            height=500,
            showlegend=False
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

# ================================
# NEW GOLDEN LAYER CHART FUNCTIONS
# ================================

def create_sensor_trends_chart_golden(
    alert_data: pd.DataFrame,
    feature_names: List[str],
    unit_id: str,
    alert_time: datetime,
    feature_name_map: Optional[Dict[str, str]] = None
) -> go.Figure:
    """
    Create multi-panel time series chart using pre-processed golden layer data.
    
    Args:
        alert_data: DataFrame with alert data from golden layer
        feature_names: List of feature names to plot
        unit_id: Unit identifier
        alert_time: Alert timestamp
        feature_name_map: Dictionary mapping feature codes to Spanish names
    
    Returns:
        Plotly Figure with subplots (one per sensor)
    """
    if alert_data.empty or not feature_names:
        logger.warning("Cannot create sensor trends chart: empty data or no features")
        return go.Figure().add_annotation(
            text="No sensor data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    try:
        # Filter data to M1 minutes before and M2 minutes after alert
        M1 = 90  # minutes before alert
        M2 = 10   # minutes after alert
        time_window_start = alert_time - timedelta(minutes=M1)
        time_window_end = alert_time + timedelta(minutes=M2)
        
        alert_data_filtered = alert_data[
            (alert_data['TimeStart'] >= time_window_start) &
            (alert_data['TimeStart'] <= time_window_end)
        ].copy()
        
        if alert_data_filtered.empty:
            logger.warning(f"No data in time window [{time_window_start}, {time_window_end}]")
            return go.Figure().add_annotation(
                text="No sensor data in time window",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
        
        # Use filtered data for plotting
        alert_data = alert_data_filtered
        
        # Use Spanish names if mapping provided
        subplot_titles = [feature_name_map.get(f, f) if feature_name_map else f for f in feature_names]
        fig = make_subplots(
            rows=len(feature_names),
            cols=1,
            shared_xaxes=True,
            subplot_titles=subplot_titles,
            vertical_spacing=0.08
        )
        # Plot each feature
        for idx, feature in enumerate(feature_names, 1):
            value_col = f'{feature}_Value'
            upper_col = f'{feature}_Upper_Limit'
            lower_col = f'{feature}_Lower_Limit'
            display_name = feature_name_map.get(feature, feature) if feature_name_map else feature
            # Plot values colored by state (if available)
            if 'State' in alert_data.columns and alert_data['State'].notna().any():
                for state in alert_data['State'].dropna().unique():
                    state_data = alert_data[alert_data['State'] == state]
                    fig.add_trace(
                        go.Scatter(
                            x=state_data['TimeStart'],
                            y=state_data[value_col],
                            mode='markers',
                            name=state,
                            legendgroup=state,
                            showlegend=(idx == 1),
                            marker=dict(
                                color=STATE_COLORS.get(state, '#95a5a6'),
                                size=6
                            ),
                            hovertemplate=(
                                f'<b>{display_name}</b><br>' +
                                'Hora: %{x}<br>' +
                                'Valor: %{y:.2f}<br>' +
                                f'Estado: {state}<br>' +
                                '<extra></extra>'
                            )
                        ),
                        row=idx,
                        col=1
                    )
            else:
                # Plot without state coloring
                fig.add_trace(
                    go.Scatter(
                        x=alert_data['TimeStart'],
                        y=alert_data[value_col],
                        mode='markers',
                        name=display_name,
                        showlegend=(idx == 1),
                        marker=dict(size=6, color='#3498db'),
                        hovertemplate=(
                            f'<b>{display_name}</b><br>' +
                            'Hora: %{x}<br>' +
                            'Valor: %{y:.2f}<br>' +
                            '<extra></extra>'
                        )
                    ),
                    row=idx,
                    col=1
                )
            # Plot limits
            if lower_col in alert_data.columns and alert_data[lower_col].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=alert_data['TimeStart'],
                        y=alert_data[lower_col],
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
            
            if upper_col in alert_data.columns and alert_data[upper_col].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=alert_data['TimeStart'],
                        y=alert_data[upper_col],
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
            
        
        # Update layout
        fig.update_layout(
            title={
                'text': f'Análisis de Tendencias - {unit_id} (Golden Layer)',
                'x': 0.5,
                'xanchor': 'center',
                'font': dict(size=16, color='#2c3e50')
            },
            height=300 * len(feature_names),
            template='plotly_white',
            hovermode='x unified',
            margin=dict(l=60, r=20, t=50, b=40)
        )
        
        # Update axes (no legend)
        fig.update_layout(
            height=300 + 180 * len(feature_names),
            template='plotly_white',
            showlegend=False,
            margin=dict(l=40, r=20, t=10, b=40),
            hovermode='x unified',
            title_text=None
        )
        
        # Add alert time vertical lines as shapes (full height in each subplot)
        for idx in range(1, len(feature_names) + 1):
            yref = 'y' if idx == 1 else f'y{idx}'
            fig.add_shape(
                type='line',
                x0=alert_time,
                x1=alert_time,
                y0=0,
                y1=1,
                yref=f'{yref} domain',
                line=dict(color='rgba(128, 128, 128, 0.6)', width=2, dash='dot'),
                row=idx,
                col=1
            )
        
        logger.info(f"Created sensor trends chart (golden layer) with {len(feature_names)} features")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating sensor trends chart (golden layer): {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_gps_route_map_golden(
    alert_data: pd.DataFrame,
    unit_id: str,
    alert_time: datetime,
    mapbox_token: str
) -> go.Figure:
    """
    Create GPS route map using pre-processed golden layer data.
    
    Args:
        alert_data: DataFrame with GPS data from golden layer
        unit_id: Unit identifier
        alert_time: Alert timestamp
        mapbox_token: Mapbox access token
    
    Returns:
        Plotly Figure with GPS map
    """
    if alert_data.empty:
        logger.warning("Cannot create GPS map: empty data")
        return go.Figure().add_annotation(
            text="No GPS data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Filter data to M1 minutes before alert (GPS shows route only up to alert time)
        M1 = 90  # minutes before alert
        time_window_start = alert_time - timedelta(minutes=M1)
        
        alert_data_filtered = alert_data[
            (alert_data['TimeStart'] >= time_window_start) &
            (alert_data['TimeStart'] <= alert_time)
        ].copy()
        
        # Filter GPS data
        gps_data = alert_data_filtered.dropna(subset=['GPSLat', 'GPSLon']).copy()
        
        if gps_data.empty:
            logger.warning("No GPS data with valid coordinates")
            return go.Figure().add_annotation(
                text="No GPS data with valid coordinates",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
        
        # Normalize time for color gradient
        time_min = gps_data['TimeStart'].min()
        time_max = gps_data['TimeStart'].max()
        
        if time_max > time_min:
            gps_data['TimeNorm'] = (gps_data['TimeStart'] - time_min) / (time_max - time_min)
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
            text=gps_data['TimeStart'].dt.strftime('%H:%M:%S'),
            hovertemplate='Hora: %{text}<extra></extra>'
        ))
        
        # Add alert marker (find closest point to alert_time) - last point since we filtered up to alert
        alert_idx = (gps_data['TimeStart'] - alert_time).abs().argmin()
        alert_point = gps_data.iloc[alert_idx]
        
        # Add white border circle first (bottom layer)
        fig.add_trace(go.Scattermapbox(
            lat=[alert_point['GPSLat']],
            lon=[alert_point['GPSLon']],
            mode='markers',
            marker=dict(
                size=35,
                color='white',
                opacity=0.9,
                symbol='circle',
                allowoverlap=True
            ),
            showlegend=False,
            hoverinfo='skip'
        ))
        
        # Add red circle on top
        fig.add_trace(go.Scattermapbox(
            lat=[alert_point['GPSLat']],
            lon=[alert_point['GPSLon']],
            mode='markers',
            marker=dict(
                size=25,
                color='red',
                symbol='circle',
                allowoverlap=True
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
            title=None,
            height=600,
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False
        )
        
        logger.info(f"Created GPS route map (golden layer) with {len(gps_data)} points")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating GPS route map (golden layer): {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_context_kpis_cards_golden(
    alert_data: pd.DataFrame,
    alert_time: pd.Timestamp,
    trigger: str
) -> dbc.Row:
    """
    Create KPI cards using pre-processed golden layer data.
    
    Args:
        alert_data: DataFrame with alert data from golden layer
        alert_time: Alert timestamp
        trigger: Trigger feature name
    
    Returns:
        Bootstrap Row with KPI cards
    """
    import dash_bootstrap_components as dbc
    from dash import html
    
    if alert_data.empty:
        return dbc.Alert("No hay datos de contexto disponibles", color="info")
    
    try:
        # Get first data point (alert time)
        alert_point = alert_data.iloc[0]
        
        # KPI 1: Elevation Status
        if 'GPSElevation' in alert_data.columns and len(alert_data) > 5:
            elevation_before = alert_data['GPSElevation'].iloc[:5].mean()
            elevation_after = alert_data['GPSElevation'].iloc[-5:].mean()
            gradient = (elevation_after - elevation_before) / 5 if pd.notna(elevation_before) and pd.notna(elevation_after) else 0
            
            if gradient > 0.05:
                elevation_status = "⬆️ Subiendo"
                elevation_color = "info"
            elif gradient < -0.05:
                elevation_status = "⬇️ Bajando"
                elevation_color = "warning"
            else:
                elevation_status = "➡️ Plano"
                elevation_color = "secondary"
        else:
            elevation_status = "❓ Desconocido"
            elevation_color = "light"
        
        # KPI 2: Operational State
        if 'State' in alert_point.index and pd.notna(alert_point['State']):
            state = alert_point['State']
            if state == 'Operacional':
                state_display = "✅ Operacional"
                state_color = "success"
            elif state == 'Ralenti':
                state_display = "⚠️ Ralenti"
                state_color = "warning"
            else:
                state_display = "❓ Desconocido"
                state_color = "light"
        else:
            state_display = "❓ Desconocido"
            state_color = "light"
        
        # KPI 3: Engine Speed (always EngSpd) - rounded to nearest hundred
        engspd_value_col = "EngSpd_Value"
        if engspd_value_col in alert_point.index and pd.notna(alert_point[engspd_value_col]):
            engspd_value = alert_point[engspd_value_col]
            engspd_rounded = round(engspd_value / 100) * 100
            engspd_display = f"{engspd_rounded:.0f} RPM"
            engspd_color = "primary"
        else:
            engspd_display = "-1"
            engspd_color = "light"
        
        # Create KPI cards
        kpi_row = dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("🏔️ Elevación", className="text-muted mb-2"),
                        html.H4(elevation_status, className="mb-0")
                    ])
                ], color=elevation_color, outline=True)
            ], md=4),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("🔧 Estado Operacional", className="text-muted mb-2"),
                        html.H4(state_display, className="mb-0")
                    ])
                ], color=state_color, outline=True)
            ], md=4),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("⚙️ Velocidad del Motor", className="text-muted mb-2"),
                        html.H4(engspd_display, className="mb-0")
                    ])
                ], color=engspd_color, outline=True)
            ], md=4)
        ], className="mb-4")
        
        logger.info("Created context KPI cards (golden layer) successfully")
        return kpi_row
    
    except Exception as e:
        logger.error(f"Error creating context KPI cards (golden layer): {e}")
        return dbc.Alert(f"Error al mostrar KPIs: {str(e)}", color="danger")