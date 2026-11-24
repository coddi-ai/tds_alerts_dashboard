"""
Machines Overview callbacks — July 2026 v3.

Filter chain: Site → Fleet → Status (dynamic dependencies).
Heatmap requires fleet selection when multiple fleets exist.
Default components: all with ≥1 sample for the selected fleet.
"""

from src.i18n import t
from dash import ALL, Input, Output, State, html, ctx, no_update
from dash.exceptions import PreventUpdate
import pandas as pd
from config.settings import get_settings
from dashboard.components.oil_fleet_matrix import (
    FIRST_DIRS,
    TABLE as FLEET_TABLE,
    build_fleet_matrix_data,
    infer_machine_status,
    render_fleet_matrix,
)
from dashboard.components.oil_table import register_view_controller
from src.data.loaders import load_oil_classified, load_machine_status_for_client
from src.utils.logger import get_logger
from dashboard.components.oil_machine_detail import build_machine_detail
from shared.severity import STATUS_TIER_BY_ESTADO

logger = get_logger(__name__)


def report_navigation(client, unit_id, component):
    """What opens Detalle de Reporte on one unit's component (its latest sample): the internal tab and
    the navigation state the report selectors read. The machine type ("familia") is looked up from the
    unit's own rows. Raises PreventUpdate when the unit has no such component.

    Shared by the fleet matrix cells and the frequency panel's "Última Muestra" links, so both open
    the report the same way.
    """
    if not unit_id or not component or not client:
        raise PreventUpdate
    if not get_settings().get_classified_reports_path(client.lower()).exists():
        raise PreventUpdate
    try:
        df = load_oil_classified(client)
        unit_df = df[(df['unitId'] == unit_id) & (df['componentName'] == component)]
    except Exception:
        logger.exception("Could not open the report of %s / %s for %s", unit_id, component, client)
        raise PreventUpdate
    if unit_df.empty:
        raise PreventUpdate
    nav = {'equipo': unit_id, 'component': component}
    familia = unit_df.iloc[0].get('machineName', None)
    if familia:
        nav['familia'] = familia
    return 'report-detail', nav


def _clicked():
    """The id of the button that was really clicked, or None. A table that was just re-rendered hands
    the callback fresh buttons with no clicks: that is not a click."""
    triggered = ctx.triggered_id
    if not isinstance(triggered, dict) or not ctx.triggered or not ctx.triggered[0].get('value'):
        return None
    return triggered


def register_machines_callbacks(app):
    """Register all Fleet Overview callbacks."""

    # ========================================
    # Filter Chain: Site options (from client)
    # ========================================
    @app.callback(
        Output('fleet-site-filter', 'options'),
        [Input('client-selector', 'value')]
    )
    def populate_site_filter(client):
        if not client:
            return []
        settings = get_settings()
        path = settings.get_classified_reports_path(client.lower())
        if not path.exists():
            return []
        try:
            df = load_oil_classified(client)
            sites = sorted(df['site'].dropna().unique().tolist())
            return [{'label': s, 'value': s} for s in sites]
        except Exception as e:
            logger.error(f"Error loading sites: {e}")
            return []

    # ========================================
    # Filter Chain: Fleet options (depends on site)
    # ========================================
    @app.callback(
        [Output('fleet-machine-type-filter', 'options'),
         Output('fleet-machine-type-filter', 'value')],
        [Input('client-selector', 'value'),
         Input('fleet-site-filter', 'value')]
    )
    def populate_fleet_filter(client, site):
        """Populate fleet options based on selected site. Auto-select if only one."""
        if not client:
            return [], None
        settings = get_settings()
        path = settings.get_classified_reports_path(client.lower())
        if not path.exists():
            return [], None
        try:
            df = load_oil_classified(client)
            if site:
                df = df[df['site'] == site]
            fleets = sorted(df['machineName'].dropna().unique().tolist())
            options = [{'label': f.title(), 'value': f} for f in fleets]
            # Auto-select if only one fleet
            value = fleets[0] if len(fleets) == 1 else None
            return options, value
        except Exception as e:
            logger.error(f"Error loading fleets: {e}")
            return [], None

    # ========================================
    # KPIs (reactive to all filters)
    # ========================================
    @app.callback(
        [Output('kpi-total-machines', 'children'),
         Output('kpi-normal-machines', 'children'),
         Output('kpi-alerta-machines', 'children'),
         Output('kpi-anormal-machines', 'children'),
         Output('machine-detail-selector', 'options'),
         Output('nav-equipment-selector', 'options')],
        [Input('client-selector', 'value'),
         Input('fleet-site-filter', 'value'),
         Input('fleet-machine-type-filter', 'value'),
         Input('fleet-status-filter', 'value')]
    )
    def update_kpis(client, site, fleet, statuses):
        empty = ("0", "0", "0", "0", [], [])
        if not client:
            return empty
        settings = get_settings()
        path = settings.get_classified_reports_path(client.lower())
        if not path.exists():
            return empty
        try:
            df = load_oil_classified(client)
            if site:
                df = df[df['site'] == site]
            if fleet:
                df = df[df['machineName'] == fleet]
            if df.empty:
                return empty

            df['sampleDate'] = pd.to_datetime(df['sampleDate'])
            latest = df.loc[df.groupby(['unitId', 'componentName'])['sampleDate'].idxmax()]

            # Machine statuses
            machine_file = settings.get_machine_status_path(client.lower())
            ms_map = {}
            if machine_file.exists():
                ms_df = load_machine_status_for_client(client)
                ms_map = dict(zip(ms_df['unit_id'], ms_df['overall_status']))

            pivot = latest.pivot_table(index='unitId', columns='componentName',
                                       values='report_status', aggfunc='first')
            pivot['__ms__'] = pivot.index.map(
                lambda u: ms_map.get(u) if isinstance(ms_map.get(u), str)
                else infer_machine_status(pivot.loc[u].drop('__ms__', errors='ignore')))

            if statuses:
                pivot = pivot[pivot['__ms__'].isin(statuses)]

            total = len(pivot)
            sc = pivot['__ms__'].value_counts()
            machines = sorted(pivot.index.tolist())
            opts = [{'label': m, 'value': m} for m in machines]
            return (str(total), str(sc.get('Normal', 0)), str(sc.get('Alerta', 0)),
                    str(sc.get('Anormal', 0)), opts, opts)
        except Exception as e:
            logger.error(f"KPI error: {e}")
            return empty

    # ========================================
    # Component column options (depends on fleet)
    # ========================================
    @app.callback(
        [Output('fleet-component-columns-selector', 'options'),
         Output('fleet-component-columns-selector', 'value')],
        [Input('client-selector', 'value'),
         Input('fleet-site-filter', 'value'),
         Input('fleet-machine-type-filter', 'value')]
    )
    def update_component_options(client, site, fleet):
        """Component options from selected fleet. Default = all with ≥1 sample."""
        if not client or not fleet:
            return [], []
        settings = get_settings()
        path = settings.get_classified_reports_path(client.lower())
        if not path.exists():
            return [], []
        try:
            df = load_oil_classified(client)
            if site:
                df = df[df['site'] == site]
            df = df[df['machineName'] == fleet]
            if df.empty:
                return [], []

            df['sampleDate'] = pd.to_datetime(df['sampleDate'])
            latest = df.loc[df.groupby(['unitId', 'componentName'])['sampleDate'].idxmax()]
            comps = latest['componentName'].value_counts()
            # All components with at least 1 sample
            all_comps = comps[comps >= 1].index.tolist()
            options = [{'label': c.title(), 'value': c} for c in all_comps]
            return options, all_comps
        except Exception as e:
            logger.error(f"Component options error: {e}")
            return [], []

    # ========================================
    # Fleet matrix: data (filters) -> view (sort, page) -> table
    # ========================================
    @app.callback(
        Output(f'{FLEET_TABLE}-data', 'data'),
        [Input('client-selector', 'value'),
         Input('fleet-site-filter', 'value'),
         Input('fleet-machine-type-filter', 'value'),
         Input('fleet-status-filter', 'value'),
         Input('fleet-component-columns-selector', 'value')]
    )
    def update_fleet_matrix_data(client, site, fleet, statuses, selected_components):
        """Apply the filters. The component columns come back ordered by how many of the filtered
        units have data for them (see oil_fleet_matrix.order_components_by_coverage)."""
        return build_fleet_matrix_data(client, site, fleet, statuses, selected_components)

    register_view_controller(app, FLEET_TABLE, FIRST_DIRS)

    @app.callback(
        [Output('fleet-heatmap-table-container', 'children'),
         Output('table-filter-badge', 'children')],
        [Input(f'{FLEET_TABLE}-view', 'data'),
         Input('machine-detail-selector', 'value')],
        [State(f'{FLEET_TABLE}-data', 'data')]
    )
    def update_fleet_heatmap_table(view, selected_unit, data):
        return render_fleet_matrix(data, view, selected_unit)

    # ========================================
    # Machine Detail
    # ========================================
    @app.callback(
        [Output('machine-selection-indicator', 'children'),
         Output('machine-recommendation-container', 'children'),
         Output('machine-detail-table-container', 'children')],
        [Input('machine-detail-selector', 'value'),
         Input('client-selector', 'value')]
    )
    def update_machine_detail(unit_id, client):
        """The unit comes from the selector, which the matrix's unit and row-select buttons fill from
        the clicked row's own id (never from a row position)."""
        if not client:
            return t("tab_machines.ninguna_maquina_seleccionada"), html.Div(), t("fleet_overview.select_client")

        if not unit_id:
            return t("tab_machines.ninguna_maquina_seleccionada"), html.Div(),                    t("machines_callbacks.seleccione_una_maquina_de_la_tabla")

        # Shared with the Unit Summary's Tribología card (spec 09_...md).
        indicator, _color, recommendation, table = build_machine_detail(client, unit_id)
        return indicator, recommendation, table

    # ========================================
    # Unit / row-select click -> machine detail
    # ========================================
    @app.callback(
        [Output('machine-detail-selector', 'value'),
         Output('nav-equipment-selector', 'value'),
         Output('heatmap-click-data', 'data')],
        [Input({'type': f'{FLEET_TABLE}-unit', 'unit': ALL}, 'n_clicks'),
         Input({'type': f'{FLEET_TABLE}-select', 'unit': ALL}, 'n_clicks')],
        prevent_initial_call=True
    )
    def handle_unit_click(_unit_clicks, _select_clicks):
        """Clicking a unit, or its row selector, opens that unit's Detalle de Máquina."""
        clicked = _clicked()
        if not clicked or not clicked.get('unit'):
            raise PreventUpdate
        uid = clicked['unit']
        return uid, uid, {'unit_id': uid}

    # ========================================
    # Cell click -> navigate to Report Detail
    # ========================================
    @app.callback(
        [Output('oil-internal-tabs', 'value', allow_duplicate=True),
         Output('navigation-state', 'data', allow_duplicate=True)],
        [Input({'type': f'{FLEET_TABLE}-cell', 'unit': ALL, 'component': ALL}, 'n_clicks')],
        [State('client-selector', 'value')],
        prevent_initial_call=True
    )
    def handle_cell_click_to_report(_n_clicks, client):
        """Click on a unit/component cell -> Detalle de Reporte for that sample. Unit and component
        are the clicked button's own id, so the right row opens on any page, sort or filter."""
        clicked = _clicked()
        if not clicked or not client:
            raise PreventUpdate
        return report_navigation(client, clicked.get('unit'), clicked.get('component'))

    # ========================================
    # Compat: component grouping toggle
    # ========================================
    @app.callback(
        Output('component-grouping-state', 'data'),
        [Input('toggle-component-grouping', 'n_clicks')],
        [State('component-grouping-state', 'data')],
        prevent_initial_call=True
    )
    def toggle_component_grouping(n_clicks, state):
        if n_clicks:
            return {'use_normalized': not state.get('use_normalized', False)}
        return state

    # ========================================
    # Quick Navigation
    # ========================================
    @app.callback(
        [Output('nav-component-selector', 'options'),
         Output('nav-component-selector', 'disabled'),
         Output('nav-to-report-button', 'disabled')],
        [Input('nav-equipment-selector', 'value'), Input('client-selector', 'value')]
    )
    def update_nav_options(unit_id, client):
        if not unit_id or not client:
            return [], True, True
        settings = get_settings()
        path = settings.get_classified_reports_path(client.lower())
        if not path.exists():
            return [], True, True
        try:
            df = load_oil_classified(client)
            comps = sorted(df[df['unitId'] == unit_id]['componentName'].unique().tolist())
            return [{'label': c.title(), 'value': c} for c in comps], False, False
        except:
            return [], True, True

    @app.callback(
        [Output('oil-internal-tabs', 'value'),
         Output('navigation-state', 'data', allow_duplicate=True)],
        [Input('nav-to-report-button', 'n_clicks')],
        [State('nav-equipment-selector', 'value'),
         State('nav-component-selector', 'value'),
         State('client-selector', 'value')],
        prevent_initial_call=True
    )
    def navigate_to_report_detail(n_clicks, equipo, component, client):
        if not n_clicks or not equipo or not component or not client:
            raise PreventUpdate
        settings = get_settings()
        path = settings.get_classified_reports_path(client.lower())
        familia = None
        if path.exists():
            try:
                df = load_oil_classified(client)
                md = df[df['unitId'] == equipo]
                if not md.empty:
                    familia = md.iloc[0]['machineName']
            except:
                pass
        nav = {'equipo': equipo, 'component': component}
        if familia:
            nav['familia'] = familia
        return 'report-detail', nav
