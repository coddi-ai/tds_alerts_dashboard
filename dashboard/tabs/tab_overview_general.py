"""
Fleet Overview — unified landing view (Phase 1).

Replaces the old "Summary" (two-column Telemetría/Tribología table) and the
separate "Data Summary" tab with one view: units grouped into Anormal/Alerta/
Normal bands, each rendered as a table - one row per unit, one column per
applicable technique, each cell the merged status/freshness value
(08_fleet_overview_table_format.md; dashboard/components/fleet_overview.py
does the aggregation and rendering; this module is just the page shell).
"""

from src.i18n import t
from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """Create layout for the Fleet Overview page."""
    logger.info("Creating Fleet Overview layout")

    layout = html.Div([
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-chart-pie me-3"),
                    t("tab_overview_general.resumen_de_flota")
                ], className="text-primary mb-1"),
                html.P(
                    t("tab_overview_general.estado_y_frescura_de_datos_de"),
                    className="text-muted mb-0"
                ),
                html.Small([
                    t("tab_overview_general.ultima_actualizacion"),
                    html.Span(id='overview-last-update', children=t("common.loading"))
                ], className="text-muted")
            ], md=12),
        ], className="mb-3"),
        html.Div(id="overview-source-status"),

        dcc.Loading(
            id="loading-overview-fleet-cards",
            type="circle",
            children=[
                html.Div(id='overview-fleet-cards')
            ]
        ),
    ], className="container-fluid p-4")

    logger.info("Fleet Overview layout created successfully")
    return layout
