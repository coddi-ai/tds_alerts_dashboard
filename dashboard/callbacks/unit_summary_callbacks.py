"""
Callbacks for the Unit Summary navigation shell (Phase 2, dashboard/pages/
overview_unit_summary.py + dashboard/components/unit_summary.py).

Mirrors dashboard/callbacks/overview_general_callbacks.py's pattern: the page
module renders a static shell, this callback fills it in reactively. The
`unit_id` path param is stashed by the page's `layout()` into
`unit-summary-current-unit` - Dash re-runs `layout()` server-side on every
Pages navigation (including prev/next and the unit switcher, both plain
`dcc.Link`s), so this Input fires on unit switches too, without a browser
reload.
"""

from src.i18n import t
from dash import ALL, Input, Output, State, callback, ctx, html
from dash.exceptions import PreventUpdate

from dashboard.components.fleet_overview import enabled_predictive_components
from dashboard.components.unit_summary import build_unit_summary
from dashboard.components.unit_summary_content import (
    PREDICTIVE_PANEL_ID,
    PREDICTIVE_TAB_TYPE,
    predictive_card,
    predictive_tab_states,
)


def register_unit_summary_callbacks(app):
    """Register the client/unit-driven Unit Summary content callback."""

    @callback(
        Output("unit-summary-content", "children"),
        [Input("client-selector", "value"), Input("unit-summary-current-unit", "data")],
    )
    def update_unit_summary(client, unit_id):
        if not unit_id:
            return html.Div(html.P(t("unit_summary_callbacks.unidad_no_especificada"), className="text-muted text-center p-4"))
        return build_unit_summary(client, unit_id)

    @callback(
        [
            Output(PREDICTIVE_PANEL_ID, "children"),
            Output({"type": PREDICTIVE_TAB_TYPE, "component": ALL}, "className"),
            Output({"type": PREDICTIVE_TAB_TYPE, "component": ALL}, "aria-selected"),
            Output({"type": PREDICTIVE_TAB_TYPE, "component": ALL}, "tabIndex"),
        ],
        Input({"type": PREDICTIVE_TAB_TYPE, "component": ALL}, "n_clicks"),
        [State("client-selector", "value"), State("unit-summary-current-unit", "data")],
        prevent_initial_call=True,
    )
    def select_predictive_component(_clicks, client, unit_id):
        """A Predictivo component tab was chosen: show that component's card only."""
        if not isinstance(ctx.triggered_id, dict) or not any(_clicks or []) or not client or not unit_id:
            raise PreventUpdate
        component = ctx.triggered_id["component"]
        components = enabled_predictive_components(client)
        states = predictive_tab_states(client, unit_id, components, component)
        return (
            predictive_card(client, unit_id, component),
            [state[0] for state in states],
            [state[1] for state in states],
            [state[2] for state in states],
        )
