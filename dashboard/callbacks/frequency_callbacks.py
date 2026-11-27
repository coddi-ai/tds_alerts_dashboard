"""
Callbacks of the Panel de Frecuencia (Monitor de Aceite).

Filters -> `freq-data` (components, units, KPI counts, group summaries) -> KPI tiles and criticality
card; `freq-data` + `freq-view` (sort, page) -> unit list. Opening a unit's detail is done in the
browser (assets/oil_expandable_rows.js). A click on "Última Muestra" opens that sample's Detalle de
Reporte through the same navigation as a cell of Visión de Flota, resolved from the unit and component
written in the clicked button's own id (never from the row's position in the page).
"""

from dash import ALL, Input, Output, State, ctx, html
from dash.exceptions import PreventUpdate

from dashboard.callbacks.machines_callbacks import report_navigation
from dashboard.components.labels import display_component_name
from dashboard.components.oil_frequency import (
    FIRST_DIRS,
    TABLE,
    build_frequency_data,
    filter_options,
    render_criteria_card,
    render_frequency_table,
    render_kpis,
)
from dashboard.components.oil_table import register_view_controller
from src.i18n import t
from src.utils.dash_ids import from_id_text
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _as_filter(value):
    """The dropdowns' "all" option means no restriction."""
    return None if value in (None, "", "all") else value


def register_frequency_callbacks(app):
    """Register every callback of the Panel de Frecuencia."""

    # Filter cascade: client -> site -> fleet -> component
    @app.callback(
        Output('freq-site-filter', 'options'),
        Input('client-selector', 'value'),
    )
    def populate_sites(client):
        return [{'label': s, 'value': s} for s in filter_options(client)['sites']]

    @app.callback(
        [Output('freq-fleet-filter', 'options'),
         Output('freq-fleet-filter', 'value')],
        [Input('client-selector', 'value'),
         Input('freq-site-filter', 'value')],
    )
    def populate_fleets(client, site):
        """Fleet options for the site; a single fleet is selected for the user."""
        fleets = filter_options(client, site)['fleets']
        options = [{'label': f.title(), 'value': f} for f in fleets]
        return options, (fleets[0] if len(fleets) == 1 else None)

    @app.callback(
        [Output('freq-component-filter', 'options'),
         Output('freq-component-filter', 'value')],
        [Input('client-selector', 'value'),
         Input('freq-site-filter', 'value'),
         Input('freq-fleet-filter', 'value')],
    )
    def populate_components(client, site, fleet):
        components = filter_options(client, site, fleet)['components']
        return [{'label': display_component_name(c), 'value': c} for c in components], None

    # Filters -> data
    @app.callback(
        Output(f'{TABLE}-data', 'data'),
        [Input('client-selector', 'value'),
         Input('freq-site-filter', 'value'),
         Input('freq-fleet-filter', 'value'),
         Input('freq-component-filter', 'value'),
         Input('freq-group-filter', 'value'),
         Input('freq-status-filter', 'value')],
    )
    def update_frequency_data(client, site, fleet, component, group, status):
        return build_frequency_data(client, site, fleet, component, _as_filter(group), _as_filter(status))

    # Data -> KPI tiles, criticality card, freshness line
    @app.callback(
        [Output('freq-kpis', 'children'),
         Output('freq-groups', 'children'),
         Output('freq-data-as-of', 'children')],
        Input(f'{TABLE}-data', 'data'),
    )
    def render_summary(data):
        if not data:
            return html.Div(), html.Div(), ""
        as_of = t("frequency.datos_al", fecha=data["as_of"]) if data.get("as_of") else ""
        if data.get("counts") is None:       # nothing to summarize (no client / no fleet / error)
            return html.Div(), html.Div(), as_of
        return render_kpis(data), render_criteria_card(data), as_of

    # Sort / page controller and unit list (the list pages by unit, not by component)
    register_view_controller(app, TABLE, FIRST_DIRS, rows_of=lambda data: len((data or {}).get("units", [])))

    @app.callback(
        [Output('freq-table-container', 'children'),
         Output('freq-sort-note', 'children'),
         Output('freq-count-chip', 'children')],
        Input(f'{TABLE}-view', 'data'),
        State(f'{TABLE}-data', 'data'),
    )
    def render_table(view, data):
        return render_frequency_table(data, view)

    # Última Muestra -> Detalle de Reporte
    @app.callback(
        [Output('oil-internal-tabs', 'value', allow_duplicate=True),
         Output('navigation-state', 'data', allow_duplicate=True)],
        Input({'type': f'{TABLE}-open', 'unit': ALL, 'component': ALL}, 'n_clicks'),
        State('client-selector', 'value'),
        prevent_initial_call=True,
    )
    def open_report(_n_clicks, client):
        clicked = ctx.triggered_id
        if not isinstance(clicked, dict) or not ctx.triggered or not ctx.triggered[0].get('value') or not client:
            raise PreventUpdate
        return report_navigation(client, from_id_text(clicked.get('unit', '')), from_id_text(clicked.get('component', '')))
