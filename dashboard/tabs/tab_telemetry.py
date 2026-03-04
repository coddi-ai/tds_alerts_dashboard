"""
Main Telemetry Tab with Internal Tabs.

Provides a unified entry point with tabs for Fleet Overview,
Machine Detail, Component Detail, and Limits.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
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
                    "Monitor de Telemetría"
                ], className="text-primary mb-1"),
                html.P(
                    "Monitoreo jerárquico de sensores: Flota → Máquina → Componente → Señal",
                    className="text-muted"
                )
            ])
        ], className="mb-4"),

        # Client restriction notice
        html.Div(
            id='telemetry-client-notice',
            children=[
                dbc.Alert([
                    html.I(className="fas fa-info-circle me-2"),
                    "Este módulo está disponible únicamente para el cliente CDA"
                ], color="info", className="mb-4")
            ]
        ),

        # Persistent store for cross-tab navigation (fleet → component)
        dcc.Store(id='telemetry-nav-store', data=None),

        # Internal Tabs
        dcc.Tabs(
            id='telemetry-tabs',
            value='fleet',
            children=[
                dcc.Tab(
                    label='Vista Flota',
                    value='fleet',
                    className='custom-tab',
                    selected_className='custom-tab--selected'
                ),
                dcc.Tab(
                    label='Detalle Componente',
                    value='component',
                    className='custom-tab',
                    selected_className='custom-tab--selected'
                )
            ],
            className='mb-4'
        ),

        # Tab content container
        html.Div(id='telemetry-tab-content')

    ], className="container-fluid p-4")

    logger.info("Unified Telemetry Tab layout created successfully")
    return layout
