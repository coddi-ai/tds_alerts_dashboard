"""
Authentication callbacks for Multi-Technical-Alerts dashboard.
"""

from dash import Input, Output, State, html
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from dashboard.auth import authenticate_user


def register_auth_callbacks(app):
    """
    Register authentication-related callbacks.
    
    Args:
        app: Dash application instance
    """
    
    @app.callback(
        [Output('user-info-store', 'data'),
         Output('login-alert', 'children'),
         Output('login-alert', 'is_open')],
        Input('login-button', 'n_clicks'),
        [State('username-input', 'value'),
         State('password-input', 'value')],
        prevent_initial_call=True
    )
    def login(n_clicks, username, password):
        """Handle user login."""
        if not username or not password:
            return None, "Please enter username and password", True
        
        user = authenticate_user(username, password)
        
        if user:
            return user, "", False
        else:
            return None, "Invalid username or password", True
    
    
    @app.callback(
        Output('page-content', 'children'),
        Input('user-info-store', 'data')
    )
    def display_page(user_data):
        """Display login page or main dashboard based on auth status."""
        from dashboard.layout import create_login_page, create_main_dashboard
        
        if user_data is None:
            return create_login_page()
        else:
            return create_main_dashboard(user_data)
    
    
    @app.callback(
        Output('user-info-store', 'data', allow_duplicate=True),
        Input('logout-button', 'n_clicks'),
        prevent_initial_call=True
    )
    def logout(n_clicks):
        """Handle user logout."""
        return None
