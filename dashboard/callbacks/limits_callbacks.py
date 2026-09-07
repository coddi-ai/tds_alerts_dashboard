"""
Stewart Limits tab callbacks for Multi-Technical-Alerts dashboard.
"""

from dash import Input, Output, State, html
from dash.exceptions import PreventUpdate
import pandas as pd
from pathlib import Path
from config.settings import get_settings
from src.utils.file_utils import safe_read_parquet
from src.data.sqlite_repository import sqlite_load
from dashboard.components.tables import create_limits_table


def _load_limits_for_client(client):
    sqlite_frame = sqlite_load(client, "load_stewart_limits_four", client)
    if sqlite_frame is not None:
        return sqlite_frame
    settings = get_settings()
    limits_file = settings.get_stewart_limits_four_path(client)
    if not limits_file.exists():
        return None
    return safe_read_parquet(limits_file)


def register_limits_callbacks(app):
    """
    Register callbacks for Stewart Limits tab.
    
    Args:
        app: Dash application instance
    """
    
    @app.callback(
        [Output('machine-selector', 'options'),
         Output('machine-selector', 'value')],
        Input('client-selector', 'value')
    )
    def update_machine_options(client):
        """Update machine dropdown based on selected client."""
        if not client:
            return [], None
        
        df = _load_limits_for_client(client)
        if df is None:
            return [], None
        
        try:
            machines = sorted(df['machine'].unique().tolist())
            options = [{'label': m, 'value': m} for m in machines]
            
            # Return options and None for value (no default selection)
            return options, None
        except Exception as e:
            print(f"Error loading machine options: {e}")
            return [], None
    
    
    @app.callback(
        [Output('component-selector', 'options'),
         Output('component-selector', 'value')],
        [Input('client-selector', 'value'),
         Input('machine-selector', 'value')]
    )
    def update_component_options(client, machine):
        """Update component dropdown based on selected client and machine."""
        if not client:
            return [], None
        
        df = _load_limits_for_client(client)
        if df is None:
            return [], None
        
        try:
            if machine:
                df = df[df['machine'] == machine]
            
            components = sorted(df['component'].unique().tolist())
            options = [{'label': c, 'value': c} for c in components]
            
            # Return options and None for value (no default selection)
            return options, None
        except Exception as e:
            print(f"Error loading component options: {e}")
            return [], None
    
    
    @app.callback(
        Output('limits-table-container', 'children'),
        [Input('client-selector', 'value'),
         Input('machine-selector', 'value'),
         Input('component-selector', 'value'),
         Input('limits-search', 'value')]
    )
    def update_limits_table(client, machine, component, search_text):
        """Update limits table based on filters."""
        if not client:
            return html.Div("Please select a client to view limits", className="text-muted p-3")
        
        df = _load_limits_for_client(client)
        if df is None:
            return html.Div("No limits data available", className="text-warning p-3")
        
        try:
            # Filter by machine if selected
            if machine:
                df = df[df['machine'] == machine]
            
            # Filter by component if selected
            if component:
                df = df[df['component'] == component]
            
            # Search filter
            if search_text:
                df = df[df['essay'].str.contains(search_text, case=False, na=False)]
            
            if df.empty:
                return html.Div("No limits found matching the current filters", className="text-muted p-3")
            
            return create_limits_table(df)
            
        except Exception as e:
            return html.Div(f"Error loading limits: {str(e)}", className="text-danger p-3")
