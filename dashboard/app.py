"""
Main Dash application for Multi-Technical-Alerts dashboard.

Run this file to start the dashboard server.
"""

import sys
from pathlib import Path
import logging

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/dashboard.log')
    ]
)

logger = logging.getLogger(__name__)

import dash
import dash_bootstrap_components as dbc
from dashboard.layout import create_app_layout
from dashboard.callbacks.auth_callbacks import register_auth_callbacks
from dashboard.callbacks.limits_callbacks import register_limits_callbacks
from dashboard.callbacks.machines_callbacks import register_machines_callbacks
from dashboard.callbacks.reports_callbacks import register_reports_callbacks


# Initialize Dash app with Bootstrap theme
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME],
    suppress_callback_exceptions=True,
    title="Multi-Technical Alerts"
)

# Set app layout
app.layout = create_app_layout()

# Register all callbacks
register_auth_callbacks(app)
register_limits_callbacks(app)
register_machines_callbacks(app)
register_reports_callbacks(app)


if __name__ == '__main__':
    # Run server
    # For production, use a WSGI server like Gunicorn instead
    logger.info("Starting Multi-Technical-Alerts Dashboard...")
    logger.info(f"Dashboard accessible at http://127.0.0.1:8050")
    
    app.run_server(
        host='127.0.0.1',  # Use localhost instead of 0.0.0.0 for Windows compatibility
        port=8050,
        debug=True  # Set to False in production
    )
