"""
Unified Oil Tab with Internal Tabs (Fleet Overview and Report Detail).

This tab combines the Fleet Overview (former overview > general) and
Report Detail (former monitoring > oil) views into a single navigation
entry with internal tabs for switching between views.
"""

from src.i18n import t
from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create unified oil tab layout with internal tabs.

    Tab A — Fleet Overview: machine-level status, priority, component distributions.
    Tab B — Report Detail: sample-level analysis with radar charts and time series.

    Returns:
        Dash HTML Div with tabbed interface
    """
    logger.info("Creating unified Oil Tab layout with internal tabs")

    layout = html.Div([
        # Header
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-oil-can me-3"),
                    t("tab_oil.monitor_de_aceite")
                ], className="text-primary mb-1"),
                html.P(
                    t("tab_oil.analisis_de_aceite_vision_de_flota"),
                    className="text-muted"
                )
            ])
        ], className="mb-4"),
        html.Div(id="oil-source-status"),

        # Internal Tabs
        dcc.Tabs(
            id='oil-internal-tabs',
            value='fleet-overview',
            children=[
                dcc.Tab(
                    label=t("tab_oil.vision_de_flota"),
                    value='fleet-overview',
                    className='custom-tab',
                    selected_className='custom-tab--selected'
                ),
                dcc.Tab(
                    label=t("tab_oil.detalle_de_reporte"),
                    value='report-detail',
                    className='custom-tab',
                    selected_className='custom-tab--selected'
                ),
                dcc.Tab(
                    label=t("tab_oil.cumplimiento_laboratorio"),
                    value='lab-compliance',
                    className='custom-tab',
                    selected_className='custom-tab--selected'
                ),
                # dcc.Tab(
                #     label='Horómetro de Componentes',
                #     value='component-hours',
                #     className='custom-tab',
                #     selected_className='custom-tab--selected',
                #     id='oil-tab-component-hours'
                # )
            ],
            className='mb-4'
        ),

        # Tab content container
        html.Div(id='oil-tab-content'),

    ], className="container-fluid p-4")

    logger.info("Unified Oil Tab layout created successfully")
    return layout
