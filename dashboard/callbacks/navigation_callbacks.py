"""
Navigation callbacks for multi-section dashboard.

Handles switching between sections and subsections via left menu.
"""

from dash import Input, Output, State, html, callback_context
from dash.dependencies import ALL
import dash
from pathlib import Path

from dashboard.tabs.tab_limits import create_limits_tab
from dashboard.tabs.tab_machines import create_machines_tab
from dashboard.tabs.tab_reports import create_reports_tab
from dashboard.tabs.tab_alerts import create_layout as create_alerts_tab
from dashboard.tabs.tab_mantenciones_general import layout_mantenciones_general
from dashboard.layout import create_placeholder_content
from config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


def has_alerts_data(client: str) -> bool:
    """
    Check if a client has alerts data available.
    
    Args:
        client: Client identifier
        
    Returns:
        True if alerts data exists, False otherwise
    """
    try:
        settings = get_settings()
        alerts_path = settings.data_root / "alerts" / "golden" / client.lower()
        
        if not alerts_path.exists():
            logger.warning(f"Alerts path does not exist for client {client}: {alerts_path}")
            return False
        
        # Check for AI-enhanced CSV files first
        csv_files = list(alerts_path.glob("*.csv"))
        ai_files = [f for f in csv_files if '_AI' in f.name.upper()]
        
        has_data = len(csv_files) > 0
        logger.info(f"Client {client} alerts data check: {has_data} (found {len(csv_files)} CSV files, {len(ai_files)} AI files)")
        
        return has_data
    except Exception as e:
        logger.error(f"Error checking alerts data for client {client}: {e}")
        return False


def register_navigation_callbacks(app: dash.Dash) -> None:
    """
    Register callbacks for dashboard navigation.
    
    Args:
        app: Dash application instance
    """
    
    def get_alerts_content(client: str):
        """
        Get alerts content or 'In Progress' placeholder based on data availability.
        
        Args:
            client: Client identifier (not used directly, alerts tabs get client from callbacks)
            
        Returns:
            Dashboard content (unified alerts tab with internal tabs)
        """
        logger.info(f"Getting alerts content for client={client}")
        
        # Alerts subsystem is CDA-only
        if client.lower() != 'cda':
            logger.warning(f"Alerts subsystem is only available for CDA client, requested: {client}")
            return create_placeholder_content('Alertas (Solo disponible para CDA)')
        
        logger.info("Creating unified alerts tab with internal tabs")
        return create_alerts_tab()
    
    # Map subsection IDs to their content generators
    SECTION_CONTENT_MAP = {
        'overview-general': create_machines_tab,
        'monitoring-alerts': lambda client: get_alerts_content(client),
        'monitoring-telemetry': lambda client: create_placeholder_content('Telemetry'),
        'monitoring-mantentions': lambda client: layout_mantenciones_general(),
        'monitoring-oil': create_reports_tab,
        'limits-oil': create_limits_tab,
        'limits-telemetry': lambda client: create_placeholder_content('Telemetry Limits')
    }
    
    # Callback 1: Handle button clicks and update store
    @app.callback(
        Output('active-section-store', 'data'),
        [Input({'type': 'nav-button', 'index': ALL}, 'n_clicks')],
        [State('active-section-store', 'data'),
         State({'type': 'nav-button', 'index': ALL}, 'id')],
        prevent_initial_call=True
    )
    def update_active_section(n_clicks_list, current_section, button_ids):
        """
        Update active section when navigation button is clicked.
        """
        ctx = callback_context
        
        if not ctx.triggered:
            return current_section or 'overview-general'
        
        triggered_prop = ctx.triggered[0]['prop_id']
        
        try:
            import json
            id_dict = json.loads(triggered_prop.split('.')[0])
            return id_dict['index']
        except:
            return current_section or 'overview-general'
    
    # Callback 2: Update content and button styles based on active section
    @app.callback(
        [Output('section-content', 'children'),
         Output({'type': 'nav-button', 'index': ALL}, 'className')],
        [Input('active-section-store', 'data'),
         Input('user-info-store', 'data')],
        [State({'type': 'nav-button', 'index': ALL}, 'id')]
    )
    def update_section_content(active_section, user_data, button_ids):
        """
        Update content when active section changes.
        
        Args:
            active_section: Currently active section ID
            user_data: User information from session
            button_ids: List of all button IDs
        
        Returns:
            Tuple of (content, button_classes)
        """
        # Default to overview if no section specified
        if not active_section:
            active_section = 'overview-general'
        
        # Get client from user data or use default
        if user_data and 'clients' in user_data and user_data['clients']:
            client = user_data['clients'][0].lower()
            logger.info(f"Using client from user data: {client}")
        else:
            settings = get_settings()
            client = settings.clients[0].lower() if settings.clients else 'cda'
            logger.info(f"Using default client: {client}")
        
        logger.info(f"Updating section content: section={active_section}, client={client}")
        
        # Get content for active section
        content_generator = SECTION_CONTENT_MAP.get(
            active_section,
            lambda c: create_placeholder_content('Unknown Section')
        )
        
        # Call content generator with client parameter
        # Some generators need client, others don't
        try:
            if active_section in ['monitoring-alerts', 
                                 'monitoring-telemetry', 'monitoring-mantentions', 'limits-telemetry']:
                content = content_generator(client)
            else:
                content = content_generator()
        except TypeError:
            # Fallback if function doesn't accept client parameter
            content = content_generator()
        
        # Update button classes to highlight active button
        button_classes = []
        for button_id in button_ids:
            section_id = button_id['index']
            if section_id == active_section:
                # Active button style
                button_classes.append(
                    "text-start text-white w-100 mb-1 ps-4 active"
                )
            else:
                # Inactive button style
                button_classes.append(
                    "text-start text-white-50 w-100 mb-1 ps-4"
                )
        
        return content, button_classes
