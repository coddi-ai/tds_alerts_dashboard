"""
Main layout for Multi-Technical-Alerts dashboard.

Defines the overall application layout and navigation.
"""

from dash import dcc, html
import dash_bootstrap_components as dbc
from dashboard.tabs.tab_limits import create_limits_tab
from dashboard.tabs.tab_machines import create_machines_tab
from dashboard.tabs.tab_reports import create_reports_tab
from dashboard.tabs.tab_alerts import create_layout as create_alerts_tab
from dashboard.tabs.tab_mantenciones_general import layout_mantenciones_general
from dashboard.tabs.tab_telemetry import create_layout as create_telemetry_tab
from dashboard.tabs.tab_overview_general import create_layout as create_overview_general_tab
from dashboard.tabs.tab_oil import create_layout as create_oil_tab
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


def create_placeholder_content(section_name: str) -> html.Div:
    """
    Create placeholder content for sections under development.
    
    Args:
        section_name: Name of the section being developed
    
    Returns:
        Placeholder div with "In Progress" message
    """
    return html.Div([
        dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.I(className="fas fa-tools fa-3x mb-3 text-muted"),
                    html.H3("In Progress", className="text-muted"),
                    html.P(
                        f"The {section_name} section is currently under development.",
                        className="text-muted mb-2"
                    ),
                    html.P(
                        "This feature will be available soon. Check the migration plan for timeline.",
                        className="text-muted small"
                    )
                ], className="text-center py-5")
            ])
        ])
    ], className="mt-4")


def create_main_dashboard(user_data: dict) -> html.Div:
    """
    Create main dashboard layout with multi-section navigation.
    
    Args:
        user_data: User information dictionary
    
    Returns:
        Main dashboard layout with left menu and content area
    """
    # Get clients user has access to
    available_clients = user_data.get('clients', [])
    
    # Define navigation structure
    navigation_items = [
        {
            'section': 'overview',
            'label': 'Overview',
            'icon': 'fas fa-tachometer-alt',
            'subsections': [
                {'id': 'overview-general', 'label': 'General', 'tab': create_overview_general_tab}
            ]
        },
        {
            'section': 'monitoring',
            'label': 'Monitoring',
            'icon': 'fas fa-chart-line',
            'subsections': [
                {'id': 'monitoring-alerts', 'label': 'Alerts', 'tab': create_alerts_tab},
                {'id': 'monitoring-telemetry', 'label': 'Telemetry', 'tab': create_telemetry_tab},
                {'id': 'monitoring-mantentions', 'label': 'Mantentions', 'tab': layout_mantenciones_general},
                {'id': 'monitoring-oil', 'label': 'Oil', 'tab': create_oil_tab}
            ]
        },
        {
            'section': 'limits',
            'label': 'Limits',
            'icon': 'fas fa-sliders-h',
            'subsections': [
                {'id': 'limits-oil', 'label': 'Oil', 'tab': create_limits_tab}
            ]
        }
    ]
    
    # Build left menu
    menu_items = []
    for section in navigation_items:
        # Section header
        menu_items.append(
            html.Div([
                html.I(className=f"{section['icon']} me-2"),
                html.Span(section['label'], className="fw-bold")
            ], className="text-white mb-2 mt-3")
        )
        
        # Subsections
        for subsection in section['subsections']:
            menu_items.append(
                dbc.Button(
                    subsection['label'],
                    id={'type': 'nav-button', 'index': subsection['id']},
                    color="link",
                    className="text-start text-white-50 w-100 mb-1 ps-4",
                    style={"textDecoration": "none", "fontSize": "0.9rem"}
                )
            )
    
    left_menu = html.Div([
        html.Div([
            html.H5("Navigation", className="text-white mb-3"),
            html.Hr(className="bg-white"),
            *menu_items
        ], className="p-3")
    ], style={
        "width": "250px",
        "backgroundColor": "#2c3e50",
        "minHeight": "calc(100vh - 80px)",
        "position": "fixed",
        "left": 0,
        "top": "80px"
    })
    
    # Content area
    content_area = html.Div([
        # Client selector
        create_client_selector(available_clients),
        
        # Dynamic content
        html.Div(id='section-content', className="mt-3")
        
    ], style={
        "marginLeft": "250px",
        "padding": "20px"
    })
    
    return html.Div([
        create_navbar(user_data),
        left_menu,
        content_area,
        
        # Store for active section
        dcc.Store(id='active-section-store', data='overview-general')
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
        
        # Store for alerts internal navigation
        dcc.Store(id='alerts-navigation-state', storage_type='memory'),
        
        # Page content (login or dashboard)
        html.Div(id='page-content')
    ])
