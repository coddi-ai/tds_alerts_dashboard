"""
Navbar callbacks for multi-section dashboard.

Section routing itself is now handled by Dash Pages (dash.page_container +
dbc.NavLink hrefs in dashboard/layout.py). This module only keeps the
client-logo callback, which reacts to the global client-selector dropdown
and is unrelated to page routing.
"""

from dash import Input, Output
import dash

from dashboard.layout import _client_mark
from src.utils.logger import get_logger

logger = get_logger(__name__)


def register_navigation_callbacks(app: dash.Dash) -> None:
    """
    Register navbar-related callbacks (client logo).

    Args:
        app: Dash application instance
    """

    # Update client logo when client selector changes. Nothing else confirms a switch to an
    # admin, so this must follow the selector with no intermediate state.
    @app.callback(
        [Output('client-logo-img', 'src'),
         Output('client-logo-img', 'style'),
         Output('client-logo-img', 'className'),
         Output('client-logo-img', 'alt'),
         Output('client-logo-placeholder', 'children')],
        [Input('client-selector', 'value')],
        prevent_initial_call=False
    )
    def update_client_logo(selected_client):
        """
        Update client logo based on selected client.

        Args:
            selected_client: Client selected in the dropdown

        Returns:
            Tuple of (logo_src, logo_style, logo_className, logo_alt, placeholder_text). The
            placeholder is what client_logo_handler.js shows if the image cannot be loaded.
        """
        # Size and padding come from .topbar-client-logo (custom_layout.css); the callback
        # only toggles visibility, and must keep that class when it rewrites className.
        if not selected_client:
            # No client selected - hide logo
            return '', {"display": "none"}, 'topbar-client-logo', '', ''

        # Construct logo URL - use GitHub raw content URL for production reliability
        client_lower = selected_client.lower()

        # Try PNG first, fallback to JPEG if needed
        # GitHub raw content URL format for direct image access
        base_url = 'https://raw.githubusercontent.com/coddi-ai/tds_alerts_dashboard/dev/dashboard/logos'
        logo_url = f'{base_url}/{client_lower}.png'

        logger.info(f"Updating client logo for {selected_client}: {logo_url}")

        # Add client-specific class for conditional styling
        # ENEX logo doesn't need white background, others do
        client_class = f'topbar-client-logo client-logo client-logo-{client_lower}'

        # Return URL, style, and className
        return logo_url, {"display": "block"}, client_class, selected_client, _client_mark(selected_client)
