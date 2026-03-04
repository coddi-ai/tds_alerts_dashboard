"""
Callbacks for the unified Oil Tab.

Handles switching between internal tabs (Fleet Overview / Report Detail).
"""

from dash import callback, Input, Output
from dashboard.tabs.tab_machines import create_machines_tab
from dashboard.tabs.tab_reports import create_reports_tab
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ========================================
# TAB SWITCHING CALLBACK
# ========================================

@callback(
    Output('oil-tab-content', 'children'),
    [Input('oil-internal-tabs', 'value')]
)
def render_oil_tab_content(active_tab):
    """
    Render content for the selected oil internal tab.

    Args:
        active_tab: 'fleet-overview' or 'report-detail'

    Returns:
        Tab content layout
    """
    logger.info(f"Oil tab switch: active_tab={active_tab}")

    if active_tab == 'report-detail':
        return create_reports_tab()

    # Default: fleet overview (same as former overview > general)
    return create_machines_tab()
