"""
Main layout for Multi-Technical-Alerts dashboard.

Defines the overall application layout and navigation.
"""

from dash import dcc, html
import dash_bootstrap_components as dbc
from dashboard.tabs.tab_limits import create_limits_tab
from dashboard.tabs.tab_machines import create_machines_tab
from dashboard.tabs.tab_reports import create_reports_tab
from dashboard.components.filters import create_client_selector


def create_login_page() -> dbc.Container:
    """
    Create login page layout.
    
    Returns:
        Bootstrap container with login form
    """
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.H2("Multi-Technical Alerts", className="text-center mb-4 mt-5"),
                    html.P("Oil Analysis Dashboard", className="text-center text-muted mb-4"),
                    
                    dbc.Card([
                        dbc.CardBody([
                            html.H4("Login", className="mb-4"),
                            
                            dbc.Alert(
                                id='login-alert',
                                is_open=False,
                                color='danger',
                                duration=4000
                            ),
                            
                            dbc.Input(
                                id='username-input',
                                placeholder='Username',
                                type='text',
                                className='mb-3'
                            ),
                            
                            dbc.Input(
                                id='password-input',
                                placeholder='Password',
                                type='password',
                                className='mb-3'
                            ),
                            
                            dbc.Button(
                                'Login',
                                id='login-button',
                                color='primary',
                                className='w-100'
                            )
                        ])
                    ], className='shadow')
                ])
            ], width=4, className='mx-auto')
        ])
    ], fluid=True, className='min-vh-100 bg-light')


def create_navbar(user_data: dict) -> dbc.Navbar:
    """
    Create navigation bar.
    
    Args:
        user_data: User information dictionary
    
    Returns:
        Bootstrap navbar
    """
    return dbc.Navbar(
        dbc.Container([
            dbc.Row([
                dbc.Col([
                    html.A(
                        dbc.Row([
                            dbc.Col(html.I(className="fas fa-oil-can me-2")),
                            dbc.Col(dbc.NavbarBrand("Multi-Technical Alerts", className="ms-2"))
                        ], align="center", className="g-0"),
                        href="/",
                        style={"textDecoration": "none"}
                    )
                ], width="auto"),
                
                dbc.Col([
                    html.Span(f"User: {user_data.get('username', 'Unknown')} ", className="text-white me-3"),
                    html.Span(f"Role: {user_data.get('role', 'N/A').title()} ", className="text-white-50 me-3"),
                    dbc.Button("Logout", id='logout-button', color="light", size="sm", outline=True)
                ], width="auto", className="ms-auto")
            ], align="center", className="w-100")
        ], fluid=True),
        color="dark",
        dark=True,
        className="mb-4"
    )


def create_main_dashboard(user_data: dict) -> html.Div:
    """
    Create main dashboard layout.
    
    Args:
        user_data: User information dictionary
    
    Returns:
        Main dashboard layout
    """
    # Get clients user has access to
    available_clients = user_data.get('clients', [])
    
    return html.Div([
        create_navbar(user_data),
        
        dbc.Container([
            # Client selector
            create_client_selector(available_clients),
            
            # Tabs
            dbc.Tabs([
                dbc.Tab(
                    create_limits_tab(),
                    label="Stewart Limits",
                    tab_id="tab-limits",
                    className="pt-3"
                ),
                dbc.Tab(
                    create_machines_tab(),
                    label="Machines Overview",
                    tab_id="tab-machines",
                    className="pt-3"
                ),
                dbc.Tab(
                    create_reports_tab(),
                    label="Reports Detail",
                    tab_id="tab-reports",
                    className="pt-3"
                )
            ], id='main-tabs', active_tab='tab-limits')
            
        ], fluid=True)
    ])


def create_app_layout() -> html.Div:
    """
    Create the complete application layout.
    
    Returns:
        Root layout with stores and page content
    """
    return html.Div([
        # Store user info
        dcc.Store(id='user-info-store', storage_type='session'),
        
        # Store navigation state for cross-page navigation
        dcc.Store(id='navigation-state', storage_type='memory'),
        
        # Store for active tab
        dcc.Store(id='active-tab-store', storage_type='memory'),
        
        # Page content (login or dashboard)
        html.Div(id='page-content')
    ])
