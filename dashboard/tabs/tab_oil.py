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


def create_layout(unit: str | None = None, component: str | None = None) -> html.Div:
    """
    Create unified oil tab layout with internal tabs.

    Tab A — Fleet Overview: machine-level status, priority, component distributions.
    Tab B — Report Detail: sample-level analysis with radar charts and time series.

    Args:
        unit, component: when both are given the tab opens on Report Detail for that unit's
            component (on its latest sample), by seeding the navigation store the heat-map's
            cell click uses (see dashboard/callbacks/oil_callbacks.py::seed_report_from_url).

    Returns:
        Dash HTML Div with tabbed interface
    """
    logger.info("Creating unified Oil Tab layout with internal tabs")
    to_report = bool(unit and component)

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
            ], xs=12, sm=True),
            # "Fuentes de Datos" button + popover, filled by update_oil_source_status.
            dbc.Col(html.Div(id="oil-source-status"), xs=12, sm="auto", className="ds-header-slot"),
        ], className="mb-4"),

        # Internal Tabs
        dcc.Tabs(
            id='oil-internal-tabs',
            value='report-detail' if to_report else 'fleet-overview',
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

        # What the URL asked this tab to open with; read once by seed_report_from_url.
        dcc.Store(id='oil-url-seed', storage_type='memory', data={'unit': unit, 'component': component} if to_report else None),

    ], className="container-fluid p-4")

    logger.info("Unified Oil Tab layout created successfully")
    return layout
