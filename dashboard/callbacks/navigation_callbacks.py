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
    
    @app.callback(
        [Output('section-content', 'children'),
         Output('active-section-store', 'data'),
         Output({'type': 'nav-button', 'index': ALL}, 'className')],
        [Input({'type': 'nav-button', 'index': ALL}, 'n_clicks')],
        [State('active-section-store', 'data'),
         State({'type': 'nav-button', 'index': ALL}, 'id')]
    )
    def update_section_content(n_clicks_list, current_section, button_ids):
        """
        Update content when navigation button is clicked.
        
        Args:
            n_clicks_list: List of click counts for all nav buttons
            current_section: Currently active section ID
            button_ids: List of all button IDs
        
        Returns:
            Tuple of (content, active_section_id, button_classes)
        """
        # Get triggered button
        ctx = callback_context
        
        # Determine which button was clicked
        if not ctx.triggered or not any(n_clicks_list):
            # Initial load - show Overview > General
            active_section = current_section or 'overview-general'
        else:
            # Extract the button ID from triggered prop_id
            triggered_prop = ctx.triggered[0]['prop_id']
            
            # Parse the button index from prop_id
            # Format: {"index":"overview-general","type":"nav-button"}.n_clicks
            try:
                import json
                id_dict = json.loads(triggered_prop.split('.')[0])
                active_section = id_dict['index']
            except:
                # Fallback to current section if parsing fails
                active_section = current_section or 'overview-general'
        
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
        
        return content, active_section, button_classes
