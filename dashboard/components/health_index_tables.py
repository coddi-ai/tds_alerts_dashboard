"""
Table components for Health Index Dashboard.

Reusable table builders for health index data display.
"""

import pandas as pd
from typing import Optional, List
import dash_bootstrap_components as dbc
from dash import html, dash_table

from src.utils.logger import get_logger

logger = get_logger(__name__)


def get_status_badge(hi_value: float) -> html.Span:
    """
    Create status badge based on health index value.
    
    Args:
        hi_value: Health index value (0-1)
    
    Returns:
        Dash HTML Span with badge
    """
    if hi_value < 0.5:
        return html.Span("🔴 Crítico", className="badge bg-danger")
    elif hi_value < 0.8:
        return html.Span("🟡 Precaución", className="badge bg-warning text-dark")
    else:
        return html.Span("🟢 Saludable", className="badge bg-success")


def create_health_index_detail_table(
    df: pd.DataFrame,
    page_size: int = 15
):
    """
    Create detailed table of health index data.
    
    Args:
        df: DataFrame with health index data
        page_size: Number of rows per page
    
    Returns:
        Dash DataTable or html.Div if no data
    """
    if df is None or df.empty:
        return html.Div("No hay datos disponibles", className="text-muted text-center p-4")
    
    try:
        # Prepare data for table
        table_data = df.copy()
        
        # Calculate average HI per unit and system
        summary = table_data.groupby(['Unit', 'component', 'truck_model']).agg({
            'health_index': 'mean',
            'start_time': 'max'
        }).reset_index()
        
        summary.columns = ['Unidad', 'Sistema', 'Modelo', 'HI Promedio', 'Última Actualización']
        
        # Format columns
        summary['HI Promedio'] = summary['HI Promedio'].round(4)
        summary['Última Actualización'] = pd.to_datetime(summary['Última Actualización']).dt.strftime('%Y-%m-%d %H:%M')
        
        # Add status column
        def get_status_text(hi):
            if hi < 0.5:
                return '🔴 Crítico'
            elif hi < 0.8:
                return '🟡 Precaución'
            else:
                return '🟢 Saludable'
        
        summary['Estado'] = summary['HI Promedio'].apply(get_status_text)
        
        # Sort by HI (lowest first - most critical)
        summary = summary.sort_values('HI Promedio')
        
        # Reorder columns
        summary = summary[['Unidad', 'Modelo', 'Sistema', 'HI Promedio', 'Estado', 'Última Actualización']]
        
        # Create DataTable
        table = dash_table.DataTable(
            id='health-index-table',
            columns=[
                {'name': 'Unidad', 'id': 'Unidad'},
                {'name': 'Modelo', 'id': 'Modelo'},
                {'name': 'Sistema', 'id': 'Sistema'},
                {'name': 'HI Promedio', 'id': 'HI Promedio', 'type': 'numeric'},
                {'name': 'Estado', 'id': 'Estado'},
                {'name': 'Última Actualización', 'id': 'Última Actualización'}
            ],
            data=summary.to_dict('records'),
            page_size=page_size,
            page_action='native',
            sort_action='native',
            sort_mode='multi',
            filter_action='native',
            style_table={'overflowX': 'auto'},
            style_header={
                'backgroundColor': '#f8f9fa',
                'fontWeight': 'bold',
                'textAlign': 'center',
                'border': '1px solid #dee2e6'
            },
            style_cell={
                'textAlign': 'center',
                'padding': '8px',
                'fontFamily': 'Arial, sans-serif',
                'fontSize': '13px'
            },
            style_data_conditional=[
                # Highlight critical rows
                {
                    'if': {
                        'filter_query': '{Estado} contains "Crítico"',
                    },
                    'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                    'color': '#dc3545',
                    'fontWeight': 'bold'
                },
                # Highlight warning rows
                {
                    'if': {
                        'filter_query': '{Estado} contains "Precaución"',
                    },
                    'backgroundColor': 'rgba(255, 193, 7, 0.1)',
                    'color': '#856404',
                    'fontWeight': 'bold'
                },
                # Highlight healthy rows
                {
                    'if': {
                        'filter_query': '{Estado} contains "Saludable"',
                    },
                    'backgroundColor': 'rgba(40, 167, 69, 0.05)',
                    'color': '#28a745'
                }
            ],
            style_data={
                'border': '1px solid #dee2e6'
            }
        )
        
        return table
        
    except Exception as e:
        logger.error(f"Error creating detail table: {e}")
        return html.Div(f"Error al crear tabla: {str(e)}", className="text-danger text-center p-4")


def create_critical_units_table(df: pd.DataFrame, threshold: float = 0.5) -> html.Div:
    """
    Create table showing units requiring priority attention.
    
    Args:
        df: DataFrame with health index data
        threshold: Health index threshold for critical status
    
    Returns:
        Dash HTML Div with table
    """
    if df is None or df.empty:
        return html.Div("No hay datos disponibles", className="text-muted text-center p-4")
    
    try:
        # Get latest HI for each unit-system combination
        latest = df.sort_values('end_time').groupby(['Unit', 'component']).tail(1)
        
        # Filter critical units
        critical = latest[latest['health_index'] < threshold].copy()
        
        if critical.empty:
            return dbc.Alert([
                html.I(className="fas fa-check-circle me-2"),
                "¡Excelente! No hay unidades en estado crítico."
            ], color="success", className="mb-0")
        
        # Sort by HI (lowest first)
        critical = critical.sort_values('health_index')
        
        # Format data
        critical['health_index_formatted'] = critical['health_index'].round(4)
        critical['end_time_formatted'] = pd.to_datetime(critical['end_time']).dt.strftime('%Y-%m-%d %H:%M')
        
        # Create table rows
        table_rows = []
        for _, row in critical.iterrows():
            table_rows.append(
                html.Tr([
                    html.Td(row['Unit'], className="fw-bold"),
                    html.Td(row['truck_model']),
                    html.Td(row['component']),
                    html.Td(
                        html.Span(f"{row['health_index_formatted']:.4f}", 
                                 className="badge bg-danger"),
                        className="text-center"
                    ),
                    html.Td(row['end_time_formatted'], className="text-muted small")
                ])
            )
        
        # Create table
        table = dbc.Table([
            html.Thead([
                html.Tr([
                    html.Th("Unidad"),
                    html.Th("Modelo"),
                    html.Th("Sistema"),
                    html.Th("Health Index", className="text-center"),
                    html.Th("Última Actualización")
                ])
            ]),
            html.Tbody(table_rows)
        ], bordered=True, hover=True, responsive=True, striped=True, className="mb-0")
        
        return html.Div([
            dbc.Alert([
                html.I(className="fas fa-exclamation-triangle me-2"),
                html.Strong(f"Atención: {len(critical)} unidades requieren revisión inmediata")
            ], color="danger", className="mb-3"),
            table
        ])
        
    except Exception as e:
        logger.error(f"Error creating critical units table: {e}")
        return html.Div(f"Error al crear tabla: {str(e)}", className="text-danger text-center p-4")


def create_system_summary_table(df: pd.DataFrame, system: str) -> html.Div:
    """
    Create summary table for a specific system.
    
    Args:
        df: DataFrame with health index data
        system: System name to filter
    
    Returns:
        Dash HTML Div with table
    """
    if df is None or df.empty:
        return html.Div("No hay datos disponibles", className="text-muted text-center p-4")
    
    try:
        # Filter by system
        system_data = df[df['component'] == system].copy()
        
        if system_data.empty:
            return html.Div(f"No hay datos para el sistema {system}", 
                          className="text-muted text-center p-4")
        
        # Calculate stats per unit
        summary = system_data.groupby('Unit').agg({
            'health_index': ['mean', 'min', 'max', 'std'],
            'truck_model': 'first'
        }).reset_index()
        
        summary.columns = ['Unidad', 'HI Medio', 'HI Mínimo', 'HI Máximo', 'Desv. Std', 'Modelo']
        
        # Format numbers
        for col in ['HI Medio', 'HI Mínimo', 'HI Máximo', 'Desv. Std']:
            summary[col] = summary[col].round(4)
        
        # Add status
        def get_status(hi):
            if hi < 0.5:
                return '🔴'
            elif hi < 0.8:
                return '🟡'
            else:
                return '🟢'
        
        summary['Estado'] = summary['HI Medio'].apply(get_status)
        
        # Sort by HI Medio
        summary = summary.sort_values('HI Medio')
        
        # Reorder columns
        summary = summary[['Estado', 'Unidad', 'Modelo', 'HI Medio', 'HI Mínimo', 'HI Máximo', 'Desv. Std']]
        
        # Create DataTable
        table = dash_table.DataTable(
            columns=[{'name': col, 'id': col} for col in summary.columns],
            data=summary.to_dict('records'),
            style_table={'overflowX': 'auto'},
            style_cell={
                'textAlign': 'left',
                'padding': '10px',
                'fontFamily': 'Arial, sans-serif',
                'fontSize': '14px'
            },
            style_header={
                'backgroundColor': '#f8f9fa',
                'fontWeight': 'bold',
                'border': '1px solid #dee2e6'
            },
            style_data={
                'border': '1px solid #dee2e6'
            },
            style_data_conditional=[
                {
                    'if': {'column_id': 'Estado'},
                    'textAlign': 'center',
                    'fontSize': '18px'
                }
            ]
        )
        
        return table
        
    except Exception as e:
        logger.error(f"Error creating system summary table: {e}")
        return html.Div(f"Error al crear tabla: {str(e)}", 
                       className="text-danger text-center p-4")


def create_unit_detail_card(df: pd.DataFrame, unit: str) -> dbc.Card:
    """
    Create detailed card for a specific unit showing HI by system.
    
    Args:
        df: DataFrame with health index data
        unit: Unit identifier
    
    Returns:
        Bootstrap Card component
    """
    if df is None or df.empty:
        return dbc.Card([
            dbc.CardBody("No hay datos disponibles", className="text-muted")
        ])
    
    try:
        # Filter by unit
        unit_data = df[df['Unit'] == unit].copy()
        
        if unit_data.empty:
            return dbc.Card([
                dbc.CardBody(f"No hay datos para la unidad {unit}", className="text-muted")
            ])
        
        # Get latest HI per system
        latest = unit_data.sort_values('end_time').groupby('component').tail(1)
        
        # Get model
        model = unit_data['truck_model'].iloc[0]
        
        # Create system rows
        system_rows = []
        for _, row in latest.iterrows():
            hi = row['health_index']
            
            # Status badge
            if hi < 0.5:
                badge = html.Span("Crítico", className="badge bg-danger")
            elif hi < 0.8:
                badge = html.Span("Precaución", className="badge bg-warning text-dark")
            else:
                badge = html.Span("Saludable", className="badge bg-success")
            
            system_rows.append(
                dbc.ListGroupItem([
                    dbc.Row([
                        dbc.Col(html.Strong(row['component']), width=4),
                        dbc.Col(html.Span(f"{hi:.4f}", className="font-monospace"), width=4),
                        dbc.Col(badge, width=4, className="text-end")
                    ])
                ])
            )
        
        card = dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-truck me-2"),
                    f"Unidad {unit} - {model}"
                ], className="mb-0")
            ]),
            dbc.CardBody([
                html.H6("Health Index por Sistema:", className="mb-3"),
                dbc.ListGroup(system_rows, flush=True)
            ])
        ])
        
        return card
        
    except Exception as e:
        logger.error(f"Error creating unit detail card: {e}")
        return dbc.Card([
            dbc.CardBody(f"Error: {str(e)}", className="text-danger")
        ])
