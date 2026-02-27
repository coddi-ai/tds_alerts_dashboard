"""
Unified Telemetry Tab with Internal Tabs.

This tab combines Fleet Overview (with Machine Detail) and Component Detail (with Limits)
into a single navigation entry with internal tabs for switching between views.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
from dashboard.tabs.tab_telemetry_fleet import create_telemetry_fleet_layout
from dashboard.tabs.tab_telemetry_component import create_telemetry_component_layout
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create unified telemetry tab layout with internal tabs.
    
    Returns:
        Dash HTML Div with tabbed interface
    """
    logger.info("Creating unified Telemetry Tab layout with internal tabs")
    
    layout = html.Div([
        # Header
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-satellite-dish me-3"),
                    "Telemetry Monitoring"
                ], className="text-primary mb-1"),
                html.P(
                    "Real-time sensor monitoring and anomaly detection system",
                    className="text-muted"
                )
            ])
        ], className="mb-4"),
        
        # Client restriction notice (only shown if not CDA)
        html.Div(
            id='telemetry-client-notice',
            children=[
                dbc.Alert([
                    html.I(className="fas fa-info-circle me-2"),
                    "Este módulo está disponible únicamente para el cliente CDA"
                ], color="info", className="mb-4")
            ]
        ),
        
        # Internal Tabs
        dcc.Tabs(
            id='telemetry-tabs',
            value='fleet',
            children=[
                dcc.Tab(
                    label='Fleet Overview',
                    value='fleet',
                    className='custom-tab',
                    selected_className='custom-tab-selected'
                ),
                dcc.Tab(
                    label='Component Detail',
                    value='component',
                    className='custom-tab',
                    selected_className='custom-tab-selected'
                )
            ],
            className='mb-3'
        ),
        
        # Tab content
        html.Div(id='telemetry-tab-content')
    ])
    
    return layout
