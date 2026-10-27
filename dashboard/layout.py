"""
Main layout for Multi-Technical-Alerts dashboard.

Defines the overall application layout and navigation.

Custom CSS for navigation and layout styling is automatically loaded from:
- dashboard/assets/custom_layout.css
"""

from src.i18n import t
from dash import dcc, html
import dash_bootstrap_components as dbc
import dash
import os
from pathlib import Path
from typing import Optional
from config.settings import get_settings, APP_VERSION
from config.client_services import is_service_enabled
from dashboard.components.language_selector import create_language_selector, LANGUAGE_SYNC_STORE_ID
from dashboard.auth import current_dashboard_user_data, is_admin
from dashboard.services_registry import (
    SERVICE_SECTIONS,
    nav_icon,
    nav_path as _nav_path,
    section_label,
    service_label,
)
from dashboard.troubleshooting_handoff import troubleshooting_agent_configured


# Predictive components that get a sidebar link (icons live in services_registry.NAV_ICONS)
PREDICTIVE_NAV_COMPONENTS = ("motor", "transmision")


def _campbell_ai_enabled() -> bool:
    """Keep the new navigation entry behind an environment feature flag."""
    return os.getenv("CAMPBELL_AI_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _discover_predictive_components(client: str) -> list:
    """Discover available predictive component CSVs for a client."""
    settings = get_settings()
    data_dir = Path(settings.data_root) / "predictive" / "golden" / client
    if not data_dir.exists():
        return []
    return sorted([f.replace(".csv", "") for f in os.listdir(data_dir) if f.endswith(".csv")])


def create_login_page() -> dbc.Container:
    """
    Create redesigned login page with improved spacing, logo visibility, and form usability.

    Returns:
        Bootstrap container with professional login form
    """
    return dbc.Container([
        html.Div(
            create_language_selector(),
            style={"position": "fixed", "top": "16px", "right": "24px", "zIndex": 1000},
        ),
        dbc.Row([
            dbc.Col([
                # Login card with integrated branding
                dbc.Card([
                    dbc.CardBody([
                        # Branding section
                        html.Div([
                            html.Div(
                                html.Img(
                                    src="https://raw.githubusercontent.com/coddi-ai/tds_alerts_dashboard/refs/heads/dev/dashboard/assets/logo.svg",
                                    style={
                                        "height": "64px",
                                        "width": "auto",
                                        "padding": "8px 16px",
                                        "backgroundColor": "white",
                                        "borderRadius": "8px",
                                        "border": "2px solid #e0e0e0",
                                        "boxShadow": "0 2px 8px rgba(0,0,0,0.08)"
                                    }
                                ),
                                className="text-center"
                            ),
                            html.H3(
                                t("app.platform_title"),
                                className="text-center mt-3 mb-1",
                                style={"fontWeight": "600", "color": "#1a252f", "fontSize": "1.4rem"}
                            ),
                            html.P(
                                t("app.platform_subtitle"),
                                className="text-center mb-0 text-muted",
                                style={"fontSize": "0.9rem"}
                            )
                        ], style={
                            "padding": "32px 32px 24px 32px",
                            "borderBottom": "2px solid #f0f0f0",
                            "backgroundColor": "#fafafa"
                        }),
                        
                        # Login form section
                        html.Div([
                            html.H4(
                                t("login.title"),
                                className="mb-1 text-center",
                                style={"fontWeight": "600", "fontSize": "1.3rem"}
                            ),
                            # html.P(
                            #     "Enter your credentials to access the platform",
                            #     className="text-center text-muted mb-4",
                            #     style={"fontSize": "0.85rem"}
                            # ),

                            dbc.Alert(
                                id='login-alert',
                                is_open=False,
                                color='danger',
                                duration=4000,
                                className="mb-3"
                            ),

                            # Username field
                            html.Div([
                                html.Label(
                                    t("login.username"),
                                    className="form-label fw-500 mb-2",
                                    style={"fontSize": "0.9rem", "color": "#495057"}
                                ),
                                dbc.InputGroup([
                                    dbc.InputGroupText(
                                        html.I(className="fas fa-user"),
                                        style={"backgroundColor": "#f8f9fa"}
                                    ),
                                    dbc.Input(
                                        id='username-input',
                                        placeholder=t("login.username_placeholder"),
                                        type='text',
                                        style={"fontSize": "0.95rem"},
                                        autoComplete="username"
                                    )
                                ], className="mb-3")
                            ]),

                            # Password field
                            html.Div([
                                html.Label(
                                    t("login.password"),
                                    className="form-label fw-500 mb-2",
                                    style={"fontSize": "0.9rem", "color": "#495057"}
                                ),
                                dbc.InputGroup([
                                    dbc.InputGroupText(
                                        html.I(className="fas fa-lock"),
                                        style={"backgroundColor": "#f8f9fa"}
                                    ),
                                    dbc.Input(
                                        id='password-input',
                                        placeholder=t("login.password_placeholder"),
                                        type='password',
                                        style={"fontSize": "0.95rem"},
                                        autoComplete="current-password"
                                    )
                                ], className="mb-4")
                            ]),

                            # Login button with loading state
                            dbc.Button(
                                [
                                    html.I(className="fas fa-sign-in-alt me-2"),
                                    t("login.title")
                                ],
                                id='login-button',
                                n_clicks=0,
                                color='primary',
                                size="lg",
                                className='w-100',
                                style={
                                    "fontWeight": "600",
                                    "padding": "12px",
                                    "fontSize": "1rem"
                                }
                            ),
                            
                            # Loading indicator (hidden by default)
                            dbc.Spinner(
                                id="login-spinner",
                                size="sm",
                                color="primary",
                                spinner_style={"display": "none"},
                                spinnerClassName="mt-3 text-center"
                            )
                        ], style={"padding": "32px"})
                    ], style={"padding": "0"})
                ], className='shadow-lg', style={
                    "borderRadius": "12px",
                    "border": "none",
                    "overflow": "hidden"
                })
            ], width=12, lg=5, xl=4, className='mx-auto')
        ], className="align-items-center min-vh-100"),

        # Version footnote, bottom-left of the screen
        html.Div(
            f"v{APP_VERSION}",
            style={
                "position": "fixed",
                "bottom": "12px",
                "left": "16px",
                "color": "rgba(255, 255, 255, 0.5)",
                "fontSize": "0.75rem"
            }
        )
    ], fluid=True, style={
        "background": "#00173b",
        "minHeight": "100vh"
    })

def _user_initials(label: str) -> str:
    """Two-letter avatar text from a user name (or the first two letters of a single word)."""
    parts = [p for p in str(label).replace('_', ' ').replace('.', ' ').split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _client_mark(client: Optional[str]) -> str:
    """Short text for the logo placeholder (shared with update_client_logo)."""
    return (client or "")[:3].upper()


def _client_logo(client: Optional[str]) -> html.Div:
    """
    The current client's logo, a read-only display for every role.

    dashboard/callbacks/navigation_callbacks.py::update_client_logo swaps the image when the
    client changes - for an admin that re-render is the only confirmation of a switch. If the
    asset cannot be loaded, dashboard/assets/client_logo_handler.js flips the wrapper to
    data-logo-state="fallback", which shows the bordered initials placeholder instead of a
    broken image.
    """
    return html.Div(
        [
            html.Img(
                id='client-logo-img',
                src='',
                alt='',
                className="topbar-client-logo",
                style={"display": "none"},  # Shown by update_client_logo once a client is set
            ),
            html.Span(
                _client_mark(client),
                id='client-logo-placeholder',
                className="topbar-client-logo-placeholder",
            ),
        ],
        id='client-logo',
        className="topbar-client-logo-wrap",
    )


def _client_switcher(user_data: dict, available_clients: list[str]) -> html.Div:
    """
    The admin-only client selector (the logo it drives lives on the left, see _client_logo).

    #client-selector stays in the DOM for every role because the page callbacks read it as
    their client context. For anyone but an admin it is rendered hidden and without
    persistence, holding the user's own client - the server decides that here, at render time,
    like every other role-gated element (see build_navigation_items for the admin section).
    """
    admin = is_admin(user_data)
    selector = dcc.Dropdown(
        id='client-selector',
        options=[{'label': client, 'value': client} for client in available_clients],
        value=available_clients[0] if available_clients else None,
        clearable=False,
        # The chosen client survives the page reload that applying a language
        # needs (sessionStorage, keyed by user so another account starts clean).
        persistence=(user_data.get('username') or True) if admin else False,
        persistence_type='session',
        style={"width": "140px", "fontSize": "0.85rem"},
        className="client-compact-selector",
    )

    if not admin:
        return html.Div(html.Div(selector, hidden=True, style={"display": "none"}), className="topbar-client")

    return html.Div(
        html.Div(
            [
                html.Span(
                    [
                        html.I(className="fas fa-building topbar-client-icon"),
                        html.Span(t("nav.client_label"), className="topbar-client-label"),
                    ],
                    className="text-white-50 me-2",
                    title=t("nav.client_switch"),
                ),
                selector,
            ],
            className="d-flex align-items-center",
        ),
        className="topbar-client",
    )


def _brand_lockup() -> html.Div:
    """Product name + tagline. "CODDI" is not repeated here: the platform mark already says it."""
    return html.Div(
        [
            html.H5(t("app.product_name"), className="topbar-brand-title mb-0"),
            html.Small(t("app.platform_subtitle"), className="topbar-brand-tagline"),
        ],
        className="ms-3 topbar-brand-text",
    )


def _user_display(user_data: dict) -> html.Div:
    """Avatar + name + role: a plain display, not a control."""
    username = user_data.get('username', 'Unknown')
    return html.Div(
        [
            html.Span(_user_initials(username), className="user-display-avatar", **{"aria-hidden": "true"}),
            html.Span(
                [
                    html.Span(username, className="user-display-name"),
                    html.Span(user_data.get('role', 'N/A').title(), className="user-display-role"),
                ],
                className="user-display-text",
            ),
        ],
        className="user-display",
    )


def _logout_button() -> dbc.Button:
    """Direct, one-click logout. A routine action, so a neutral button like the other bar controls."""
    return dbc.Button(
        [html.I(className="fas fa-sign-out-alt me-2"), html.Span(t("nav.logout"), className="topbar-logout-label")],
        id='logout-button',
        color="outline-light",
        size="sm",
        n_clicks=0,
        className="topbar-logout",
    )


def create_navbar(user_data: dict, available_clients: list[str] = None) -> html.Div:
    """
    Create the top bar: platform mark + client logo + product name on the left, global
    controls on the right.

    The client logo is shown to every user; only the selector that changes it is admin-only
    (see _client_switcher).

    Args:
        user_data: User information dictionary
        available_clients: List of clients user has access to

    Returns:
        Modern header with integrated global controls
    """
    if available_clients is None:
        available_clients = user_data.get('clients', [])

    return html.Div([
        # Main header bar
        html.Div([
            dbc.Container([
                dbc.Row([
                    # Platform mark | client logo, then the product name
                    dbc.Col([
                        html.Div([
                            html.Img(
                                src='https://raw.githubusercontent.com/coddi-ai/tds_alerts_dashboard/refs/heads/dev/dashboard/assets/logo.svg',
                                alt='CODDI',
                                className="topbar-brand-logo",
                            ),
                            html.Span(className="topbar-brand-divider", **{"aria-hidden": "true"}),
                            _client_logo(available_clients[0] if available_clients else None),
                            _brand_lockup(),
                        ], className="d-flex align-items-center")
                    ], width="auto", className="topbar-brand"),

                    # Admin-only client switcher
                    dbc.Col(
                        _client_switcher(user_data, available_clients),
                        width="auto",
                        className="ms-auto me-4",
                    ),

                    # Language selector (Español / English)
                    dbc.Col(create_language_selector(), width="auto", className="me-4"),

                    # Account: who is signed in, and the way out
                    dbc.Col(
                        html.Div([_user_display(user_data), _logout_button()], className="d-flex align-items-center"),
                        width="auto",
                        className="topbar-user",
                    ),
                ], align="center", className="g-0 py-3 topbar-row")
            ], fluid=True)
        ], style={
            "backgroundColor": "#1a252f",
            "borderBottom": "3px solid #3498db",
            "boxShadow": "0 2px 8px rgba(0,0,0,0.15)",
            "position": "fixed",
            "top": 0,
            "left": 0,
            "right": 0,
            "zIndex": 1000,
            "height": "80px"
        })
    ])


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
                    html.H3(t("placeholder.title"), className="text-muted"),
                    html.P(
                        t("placeholder.working_on", section=section_name),
                        className="text-muted mb-2"
                    ),
                    html.P(
                        t("placeholder.coming_soon"),
                        className="text-muted small"
                    )
                ], className="text-center py-5")
            ])
        ])
    ], className="mt-4")


def build_navigation_items(selected_client: str, user_data: dict) -> list:
    """
    Build the nav-section/subsection data for the CURRENTLY SELECTED client.

    Visibility is keyed on the active client (not "any client the user has"),
    so it always matches exactly what dashboard/callbacks/access_control_callbacks.py
    will actually let the user reach - a disabled service is never shown, and
    switching clients in the navbar updates this immediately (see
    dashboard/callbacks/sidebar_callbacks.py, which re-renders on
    client-selector change).
    """
    def _enabled(service_id: str) -> bool:
        # Campbell AI additionally sits behind a global kill switch, on top of
        # the per-client service registry - so it can be pulled everywhere
        # (e.g. an OpenAI outage) without editing client_services.yaml.
        if service_id == "agents-campbell-ai" and not _campbell_ai_enabled():
            return False
        # Troubleshooting links out to another deployment: without a usable
        # agent URL (TROUBLESHOOTING_AGENT_URL set empty) the tab is pulled.
        if service_id == "agents-troubleshooting" and not troubleshooting_agent_configured():
            return False
        return is_service_enabled(selected_client, service_id)

    # Each predictive component is its own service id (predictive-<component>),
    # so a client can be granted some components but not others. Statically-known
    # component list for navigation (data availability checked at runtime).
    predictive_nav_components = [
        comp for comp in PREDICTIVE_NAV_COMPONENTS
        if _enabled(f'predictive-{comp}')
    ]

    # Build navigation from the central services registry, keeping only the
    # services enabled for the selected client - a disabled service is
    # omitted entirely, never shown as an inactive tab. A section with zero
    # visible services is skipped. Predictive is spliced in after
    # 'monitoring' (its historical position) since its subsections are
    # discovered dynamically rather than listed in SERVICE_SECTIONS. Campbell
    # AI's own global kill switch is folded into _enabled() above, so its
    # 'agents' section is omitted the same way a disabled client service is.
    navigation_items = []
    for section_def in SERVICE_SECTIONS:
        subsections = [
            {'id': service_id, 'label': service_label(service_id), 'icon': nav_icon(service_id)}
            for service_id in section_def['services']
            if _enabled(service_id)
        ]
        if subsections:
            navigation_items.append({
                'section': section_def['section'],
                'label': section_label(section_def['section']),
                'icon': section_def['icon'],
                'subsections': subsections,
            })

        if section_def['section'] == 'monitoring' and predictive_nav_components:
            navigation_items.append({
                'section': 'predictive',
                'label': section_label('predictive'),
                'icon': 'fas fa-brain',
                'subsections': [
                    {
                        'id': f'predictive-{comp}',
                        'label': t(f'nav.service.predictive-{comp}.short'),
                        'icon': nav_icon(f'predictive-{comp}'),
                    }
                    for comp in predictive_nav_components
                ]
            })

    # Admin section: controlled by role, independent of client service availability.
    if is_admin(user_data):
        navigation_items.append({
            'section': 'admin',
            'label': section_label('admin'),
            'icon': 'fas fa-user-shield',
            'subsections': [
                {'id': 'admin-main', 'label': service_label('admin-main'), 'icon': nav_icon('admin-main')},
                {
                    'id': 'admin-user-registry',
                    'label': service_label('admin-user-registry'),
                    'icon': nav_icon('admin-user-registry'),
                },
            ]
        })

    return navigation_items


def build_menu_items(navigation_items: list, active_nav_id: Optional[str] = None) -> list:
    """
    Render navigation_items (see build_navigation_items) into sidebar components.

    Each section is a header button plus its links. Expanding/collapsing a section, the
    icon-only rail and its flyouts are all driven in the browser by
    dashboard/assets/sidebar_nav.js off the classes and data-* attributes set here.
    `active_nav_id` (see services_registry.nav_id_for_pathname) marks the link of the
    current page, and tints the section that holds it so the rail still shows where you are.
    """
    menu_items = []
    for section in navigation_items:
        section_id = section['section']
        links_id = f"nav-links-{section_id}"
        is_active_section = any(sub['id'] == active_nav_id for sub in section['subsections'])

        links = [html.Div(section['label'], className="nav-flyout-title")]
        for subsection in section['subsections']:
            is_active = subsection['id'] == active_nav_id
            links.append(
                dbc.NavLink(
                    [
                        html.I(className=f"{subsection['icon']} nav-link-icon"),
                        html.Span(subsection['label'], className="nav-link-label"),
                    ],
                    href=dash.get_relative_path(_nav_path(subsection['id'])),
                    active=is_active,
                    className="nav-menu-item text-start w-100",
                )
            )

        menu_items.append(
            html.Div(
                [
                    html.Button(
                        [
                            html.I(className=f"{section['icon']} nav-section-icon"),
                            html.Span(section['label'], className="nav-section-label"),
                            html.I(className="fas fa-chevron-down nav-section-chevron"),
                        ],
                        type="button",
                        className="nav-section-header",
                        title=section['label'],
                        **{
                            "data-section": section_id,
                            "aria-expanded": "true",
                            "aria-controls": links_id,
                        },
                    ),
                    html.Div(links, id=links_id, className="nav-section-links"),
                ],
                className="nav-section nav-section--active" if is_active_section else "nav-section",
                **{"data-section": section_id},
            )
        )
    return menu_items


def create_main_dashboard(user_data: dict) -> html.Div:
    """
    Create main dashboard layout with redesigned navigation and unified shell.

    Args:
        user_data: User information dictionary

    Returns:
        Professional dashboard layout with full-height sidebar and integrated header
    """
    # Get clients user has access to
    available_clients = user_data.get('clients', [])

    # Initial render uses the client-selector's own default (its first
    # option) - dashboard/callbacks/sidebar_callbacks.py takes over from
    # here and re-renders #sidebar-nav-menu whenever the selector changes.
    default_client = available_clients[0] if available_clients else None
    navigation_items = build_navigation_items(default_client, user_data)
    menu_items = build_menu_items(navigation_items)

    # Full-height sidebar with no gaps
    left_menu = html.Div([
        # Sidebar header
        html.Div([
            html.Div([
                html.I(className="fas fa-bars me-3", style={"fontSize": "1.2rem"}),
                html.Span(
                    t("nav.sidebar_title"),
                    style={
                        "fontSize": "1.1rem",
                        "fontWeight": "700",
                        "letterSpacing": "0.5px"
                    }
                )
            ], className="text-white d-flex align-items-center")
        ], className="sidebar-header", style={
            "padding": "24px 20px",
            "backgroundColor": "rgba(0,0,0,0.2)",
            "borderBottom": "2px solid rgba(255,255,255,0.1)"
        }),

        # Menu items container - re-rendered by dashboard/callbacks/sidebar_callbacks.py
        # whenever client-selector changes, so it always reflects the
        # currently selected client's enabled services.
        html.Div(
            id='sidebar-nav-menu',
            children=menu_items,
            className="p-3 sidebar-menu",
            style={"overflowY": "auto", "height": "calc(100vh - 142px)"}
        )
    ], id='app-sidebar', style={
        "width": "260px",
        "backgroundColor": "#2c3e50",
        "height": "100vh",
        "position": "fixed",
        "left": 0,
        "top": "80px",
        "boxShadow": "2px 0 8px rgba(0,0,0,0.1)",
        "zIndex": 999
    })

    # Floating toggle button - lives outside the sidebar so it stays
    # reachable (to re-expand) even while the sidebar is collapsed. Its
    # position and icon direction are driven purely by CSS off the
    # 'sidebar-collapsed' class on #dashboard-shell (see
    # dashboard/assets/custom_layout.css), toggled by the clientside
    # callback in dashboard/callbacks/sidebar_callbacks.py.
    sidebar_toggle_button = html.Button(
        html.I(id='sidebar-toggle-icon', className="fas fa-chevron-left"),
        id='sidebar-toggle-btn',
        title=t("nav.sidebar_toggle"),
        n_clicks=0,
        className='sidebar-toggle-btn'
    )

    # Content area with proper spacing from header and sidebar
    content_area = html.Div([
        # Routed page content
        dash.page_container
    ], id='app-content-wrapper', style={
        "marginLeft": "260px",
        "marginTop": "80px",
        "padding": "28px",
        "backgroundColor": "#f8f9fa",
        "minHeight": "calc(100vh - 80px)"
    })

    return html.Div([
        create_navbar(user_data, available_clients),
        left_menu,
        sidebar_toggle_button,
        content_area
    ], id='dashboard-shell')


def create_app_layout() -> html.Div:
    """
    Create the complete application layout.
    
    Returns:
        Root layout with stores and page content
    """
    return html.Div([
        # Identidad del usuario, sembrada desde la sesion de Flask en cada render en vez de
        # nacer en None. El store es `session`, o sea sessionStorage, que es por pestana: una
        # pestana nueva o un enlace directo llegan sin nada, y `display_page` exige el proof
        # firmado para mostrar el dashboard, asi que sin esto alguien con sesion valida en el
        # servidor ve el login. Devuelve None cuando no hay sesion, y entonces un visitante
        # sigue viendo el login, que es lo correcto.
        #
        # Solo funciona porque `dashboard/app.py` asigna el callable `create_app_layout` y no
        # su resultado; evaluado al importar no hay request desde el cual leer la sesion.
        #
        # Ojo con el alcance: cuando sessionStorage ya tiene un valor, `dcc.Store` le da
        # precedencia a ese y pisa esto. Por eso `display_page` reemite el proof por su
        # cuenta -- sembrar aca cubre la pestana nueva, no la que arrastra un valor viejo.
        dcc.Store(
            id='user-info-store',
            storage_type='session',
            data=current_dashboard_user_data(),
        ),

        # Session-scoped operator name for ERP notice validation (Validación de Avisos)
        dcc.Store(id='erp-validator-operator-store', storage_type='session', data=None),

        # Store navigation state for cross-page navigation
        dcc.Store(id='navigation-state', storage_type='memory', data=None),
        
        # Store for active tab
        dcc.Store(id='active-tab-store', storage_type='memory', data=None),
        
        # Store for alerts internal navigation
        dcc.Store(id='alerts-navigation-state', storage_type='memory', data=None),

        # Sidebar collapsed/expanded preference - persisted across page
        # navigation and browser sessions (see dashboard/callbacks/sidebar_callbacks.py).
        dcc.Store(id='sidebar-collapsed-store', storage_type='local', data=False),

        # Sink for the language selector's clientside callback (see
        # dashboard/components/language_selector.py); it holds no data.
        dcc.Store(id=LANGUAGE_SYNC_STORE_ID, storage_type='memory', data=None),

        # Page content (initialized with login page, will be replaced by callback)
        html.Div(id='page-content', children=create_login_page())
    ])
