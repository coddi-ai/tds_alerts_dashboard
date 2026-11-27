"""
Callbacks of Análisis por Componente (Monitor de Aceite).

Client + Flota + the selected option -> `ca-source` (one record per unit + component, from its latest
sample) -> header, KPI tiles and the three cards. `ca-source` + "Mostrar" -> `ca-data` (how many rows the
matrix lists) -> `ca-view` (sort, page) -> the matrix, so "Mostrar" and the essay checkbox never read the
data file again. A click on a unit or an essay cell opens that row's Detalle de Reporte through the same
navigation as a cell of Visión de Flota, resolved from the unit and component written in the clicked
button's own id (never from the row's position in the page).
"""

from dash import ALL, Input, Output, State, ctx
from dash.exceptions import PreventUpdate

from dashboard.callbacks.machines_callbacks import report_navigation
from dashboard.components.oil_component_analysis import (
    BUTTON_TYPE,
    COMPONENT_ID,
    FIRST_DIRS,
    OPEN_TYPE,
    SOURCE_ID,
    TABLE,
    TABLE_ID,
    build_source,
    control_data,
    criticality_text,
    filter_options,
    render_age_card,
    render_anomaly_card,
    render_essay_card,
    render_header,
    render_kpis,
    render_matrix,
)
from dashboard.components.oil_table import register_view_controller
from dashboard.tabs.tab_component_analysis import (
    CRITICALITY_ID,
    FLEET_ID,
    HEADER_ID,
    INCLUDE_ID,
    SHOW_ID,
)
from src.data import component_analysis as ca
from src.utils.dash_ids import from_id_text
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _clicked():
    """The id of the button that was really clicked, or None. A table that was just re-rendered hands the
    callback fresh buttons with no clicks: that is not a click."""
    triggered = ctx.triggered_id
    if not isinstance(triggered, dict) or not ctx.triggered or not ctx.triggered[0].get("value"):
        return None
    return triggered


def resolve_report(client, clicked):
    """`(internal tab, navigation state)` that opens the report of the clicked button's row. The unit and
    component are read back from the button's own id (written with `id_text`), never from a position."""
    if not clicked or not client:
        raise PreventUpdate
    return report_navigation(client, from_id_text(clicked.get("unit", "")), from_id_text(clicked.get("component", "")))


def register_component_analysis_callbacks(app):
    """Register every callback of Análisis por Componente."""

    # Componente selector -> the selected option, the buttons' aria-pressed and the criticality chip
    @app.callback(
        [Output(COMPONENT_ID, "data"),
         Output({"type": BUTTON_TYPE, "key": ALL}, "aria-pressed"),
         Output(CRITICALITY_ID, "children")],
        Input({"type": BUTTON_TYPE, "key": ALL}, "n_clicks"),
        State(COMPONENT_ID, "data"),
        prevent_initial_call=True,
    )
    def select_component(_clicks, current):
        clicked = _clicked()
        if not clicked or clicked.get("key") == current:
            raise PreventUpdate
        try:
            config = ca.load_config()
        except ca.ComponentAnalysisConfigError:
            raise PreventUpdate
        key = clicked["key"]
        if key not in config.components:
            raise PreventUpdate
        order = [spec["id"]["key"] for spec in ctx.outputs_list[1]]
        return key, ["true" if option == key else "false" for option in order], criticality_text(config, key)

    # Flota options: every machine type of the client; a single one is selected for the user
    @app.callback(
        [Output(FLEET_ID, "options"),
         Output(FLEET_ID, "value")],
        Input("client-selector", "value"),
    )
    def populate_fleets(client):
        fleets = filter_options(client)
        return [{"label": f.title(), "value": f} for f in fleets], (fleets[0] if len(fleets) == 1 else None)

    # Client + Flota + option -> the records
    @app.callback(
        Output(SOURCE_ID, "data"),
        [Input("client-selector", "value"),
         Input(FLEET_ID, "value"),
         Input(COMPONENT_ID, "data")],
    )
    def update_source(client, fleet, component):
        return build_source(client, fleet, component)

    # Records -> header, KPI tiles and cards. The checkbox only changes which essays the essay card counts.
    @app.callback(
        [Output(HEADER_ID, "children"),
         Output("ca-kpis", "children"),
         Output("ca-age", "children"),
         Output("ca-anomalies", "children"),
         Output("ca-essays", "children")],
        [Input(SOURCE_ID, "data"),
         Input(INCLUDE_ID, "value")],
    )
    def render_summary(source, include_all):
        header = render_header(source)
        if not source or source.get("message"):          # no client / no fleet / nothing to summarize
            return header, None, None, None, None
        return (header, render_kpis(source), render_age_card(source), render_anomaly_card(source),
                render_essay_card(source, bool(include_all)))

    # Records + "Mostrar" + checkbox -> the matrix's paging state; sort / page controller
    @app.callback(
        Output(f"{TABLE}-data", "data"),
        [Input(SOURCE_ID, "data"),
         Input(SHOW_ID, "value"),
         Input(INCLUDE_ID, "value")],
    )
    def update_control(source, show, _include_all):
        return control_data(source, show)

    register_view_controller(app, TABLE, FIRST_DIRS, rows_of=lambda data: (data or {}).get("n_rows", 0))

    @app.callback(
        [Output("ca-matrix-title", "children"),
         Output("ca-count-chip", "children"),
         Output(TABLE_ID, "children")],
        Input(f"{TABLE}-view", "data"),
        [State(SOURCE_ID, "data"),
         State(SHOW_ID, "value"),
         State(INCLUDE_ID, "value")],
    )
    def render_table(view, source, show, include_all):
        return render_matrix(source, view, show, bool(include_all))

    # A unit or an essay cell -> Detalle de Reporte of that row's latest sample
    @app.callback(
        [Output("oil-internal-tabs", "value", allow_duplicate=True),
         Output("navigation-state", "data", allow_duplicate=True)],
        Input({"type": OPEN_TYPE, "unit": ALL, "component": ALL, "cell": ALL}, "n_clicks"),
        State("client-selector", "value"),
        prevent_initial_call=True,
    )
    def open_report(_n_clicks, client):
        return resolve_report(client, _clicked())
