"""
Callbacks for the unified Oil Tab.

Handles switching between internal tabs (Fleet Overview / Report Detail / Lab Compliance / Frequency Panel / Component Hours).
"""

from src.i18n import t
from dash import callback, Input, Output, State
from dash.exceptions import PreventUpdate
from dashboard.tabs.tab_machines import create_machines_tab
from dashboard.tabs.tab_reports import create_reports_tab
from dashboard.tabs.tab_component_hours import create_component_hours_tab
from dashboard.tabs.tab_lab_compliance import create_lab_compliance_tab
from dashboard.tabs.tab_frequency import create_frequency_tab
from config.settings import get_settings
from src.data.loaders import load_oil_classified
from dash import html
from src.utils.logger import get_logger
from dashboard.components.source_status import render_service_data_sources

logger = get_logger(__name__)


@callback(
    Output('oil-source-status', 'children'),
    Input('client-selector', 'value'),
)
def update_oil_source_status(client):
    if not client:
        return None
    return render_service_data_sources(client, "monitoring-oil")


# ========================================
# TAB SWITCHING CALLBACK
# ========================================

@callback(
    Output('navigation-state', 'data', allow_duplicate=True),
    Input('oil-url-seed', 'data'),
    State('client-selector', 'value'),
    prevent_initial_call='initial_duplicate',
)
def seed_report_from_url(url_seed, client):
    """`?unit=&component=`: point Report Detail at that unit's component the way a click on the
    fleet heat-map does - through the navigation store its selectors read (machine type, unit, then
    component), which also leaves the sample date on the latest one for that unit and component."""
    unit, component = (url_seed or {}).get('unit'), (url_seed or {}).get('component')
    if not unit or not component or not client:
        raise PreventUpdate
    nav = {'equipo': unit, 'component': component}
    try:
        df = load_oil_classified(client)
        rows = df[(df['unitId'] == unit) & (df['componentName'] == component)]
        if not rows.empty and rows.iloc[0].get('machineName'):
            nav['familia'] = rows.iloc[0]['machineName']
    except Exception:
        logger.exception("Could not resolve the machine type of %s / %s for %s", unit, component, client)
    return nav


@callback(
    Output('oil-tab-content', 'children'),
    [Input('oil-internal-tabs', 'value'),
     Input('client-selector', 'value')]
)
def render_oil_tab_content(active_tab, client):
    """
    Render content for the selected oil internal tab.

    Args:
        active_tab: 'fleet-overview', 'report-detail', 'lab-compliance', 'frequency', or 'component-hours'
        client: Selected client

    Returns:
        Tab content layout
    """
    logger.info(f"Oil tab switch: active_tab={active_tab}, client={client}")

    if active_tab == 'report-detail':
        return create_reports_tab()

    if active_tab == 'lab-compliance':
        return create_lab_compliance_tab()

    if active_tab == 'frequency':
        return create_frequency_tab()

    if active_tab == 'component-hours':
        # Check if client has access to component hours
        settings = get_settings()
        allowed = [c.upper() for c in settings.component_hours_allowed_clients]
        if client and client.upper() in allowed:
            return create_component_hours_tab()
        else:
            return html.Div([
                html.H4(t("oil_callbacks.modulo_no_disponible"), className="mt-4 text-warning"),
                html.P(
                    t("oil_callbacks.el_horometro_de_componentes_no_esta", join_allowed=', '.join(allowed)),
                    className="text-muted"
                )
            ], className="p-4")

    # Default: fleet overview (same as former overview > general)
    return create_machines_tab()
