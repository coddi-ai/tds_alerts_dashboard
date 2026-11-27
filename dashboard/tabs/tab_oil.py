"""
Unified Oil Tab with Internal Tabs (Fleet Overview, Report Detail, Lab Compliance, Frequency Panel,
Component Analysis).

This tab combines the Fleet Overview (former overview > general) and
Report Detail (former monitoring > oil) views into a single navigation
entry with internal tabs for switching between views. The active-tab
indicator sits under the tab's own label (pred-tab, ui_notes_improved.md §8)
and assets/oil_tabs_a11y.js makes the tabs reachable with the keyboard.
"""

from src.i18n import t
from dash import html, dcc
import dash_bootstrap_components as dbc
from dashboard.components.oil_ui import tab_label
from src.utils.logger import get_logger

logger = get_logger(__name__)

# The tab bar, left to right: (dcc.Tab value, i18n key of its label).
OIL_TABS = (
    ('fleet-overview', 'tab_oil.vision_de_flota'),
    ('report-detail', 'tab_oil.detalle_de_reporte'),
    ('lab-compliance', 'tab_oil.cumplimiento_laboratorio'),
    ('frequency', 'tab_oil.panel_de_frecuencia'),
    ('component-analysis', 'tab_oil.analisis_por_componente'),
)


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

        # Internal Tabs. A tab listed in oil_ui.PREVIEW_TABS gets the "Preview" pill after its label.
        dcc.Tabs(
            id='oil-internal-tabs',
            value='report-detail' if to_report else 'fleet-overview',
            children=[
                dcc.Tab(
                    label=tab_label(t(label_key), tab_value),
                    value=tab_value,
                    className='custom-tab pred-tab oil-tab',
                    selected_className='custom-tab--selected pred-tab--selected'
                )
                for tab_value, label_key in OIL_TABS
            ] + [
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
