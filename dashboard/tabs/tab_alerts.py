"""
Unified Alerts Tab with Internal Tabs (General and Detail).

This tab combines the General and Detail views into a single navigation entry
with internal tabs for switching between views.
"""

from src.i18n import t
from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create unified alerts tab layout with internal tabs.
    
    Returns:
        Dash HTML Div with tabbed interface
    """
    logger.info("Creating unified Alerts Tab layout with internal tabs")
    
    layout = html.Div([
        # Header
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-exclamation-triangle me-3"),
                    t("tab_alerts.resumen_de_alertas")
                ], className="text-primary mb-1"),
                html.P(
                    t("tab_alerts.identifique_unidades_afectadas_causa_evide"),
                    className="text-muted"
                )
            ])
        ], className="mb-4"),
        html.Div(id="alerts-source-status"),
        
        # Internal Tabs
        dcc.Tabs(
            id='alerts-internal-tabs',
            value='general',
            children=[
                dcc.Tab(
                    label=t("tab_alerts.vista_general"),
                    value='general',
                    className='custom-tab',
                    selected_className='custom-tab--selected'
                ),
                dcc.Tab(
                    label=t("tab_alerts.vista_detallada"),
                    value='detail',
                    className='custom-tab',
                    selected_className='custom-tab--selected'
                )
            ],
            className='mb-4'
        ),
        
        # Tab content container
        html.Div(id='alerts-tab-content'),
        
        # Store for filters (used in General tab)
        dcc.Store(id='alerts-filter-store', storage_type='memory', data={}),

        # Trigger used by the clientside scroll-to-top callback when a new
        # alert detail has finished rendering.
        dcc.Store(id='alerts-detail-scroll-trigger', storage_type='memory', data=0)
        
    ], className="container-fluid p-4")
    
    logger.info("Unified Alerts Tab layout created successfully")
    return layout
