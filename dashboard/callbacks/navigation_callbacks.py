"""
Navigation callbacks for multi-section dashboard.

Handles switching between sections and subsections via left menu.
"""

from dash import Input, Output, State, html, callback_context
from dash.dependencies import ALL
import dash

from dashboard.tabs.tab_limits import create_limits_tab
from dashboard.tabs.tab_machines import create_machines_tab
from dashboard.tabs.tab_reports import create_reports_tab
from dashboard.layout import create_placeholder_content


def register_navigation_callbacks(app: dash.Dash) -> None:
    """
    Register callbacks for dashboard navigation.
    
    Args:
        app: Dash application instance
    """
    
    # Map subsection IDs to their content generators
    SECTION_CONTENT_MAP = {
        'overview-general': create_machines_tab,
        'monitoring-alerts-general': lambda: create_placeholder_content('Alerts - General'),
        'monitoring-alerts-detail': lambda: create_placeholder_content('Alerts - Detail'),
        'monitoring-telemetry': lambda: create_placeholder_content('Telemetry'),
        'monitoring-mantentions': lambda: create_placeholder_content('Mantentions'),
        'monitoring-oil': create_reports_tab,
        'limits-oil': create_limits_tab,
        'limits-telemetry': lambda: create_placeholder_content('Telemetry Limits')
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
        [Input('active-section-store', 'data')],
        [State({'type': 'nav-button', 'index': ALL}, 'id')]
    )
    def update_section_content(active_section, button_ids):
        """
        Update content when active section changes.
        
        Args:
            active_section: Currently active section ID
            button_ids: List of all button IDs
        
        Returns:
            Tuple of (content, button_classes)
        """
        # Default to overview if no section specified
        if not active_section:
            active_section = 'overview-general'
        # Default to overview if no section specified
        if not active_section:
            active_section = 'overview-general'
        
        # Get content for active section
        content_generator = SECTION_CONTENT_MAP.get(
            active_section,
            lambda: create_placeholder_content('Unknown Section')
        )
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
