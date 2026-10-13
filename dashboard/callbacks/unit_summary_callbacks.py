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
from dash import Input, Output, callback, html

from dashboard.components.unit_summary import build_unit_summary


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
