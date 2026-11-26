"""
Callbacks for the Fleet Overview page (dashboard/tabs/tab_overview_general.py).

The per-technique status/freshness aggregation, the banding and the merge of a unit's spellings happen in
the scheduled run that writes the golden file (src/data/fleet_status.py); the table is drawn from that file
by dashboard/components/fleet_overview.py. This module only wires that into Dash and keeps
`build_component_filter_options` (component dedup precedent kept for Phase 2/3's Unit Summary content per
documentation/general/general_specs/00_implementation_guide.md §3.4, even though Phase 1's Fleet Overview
cards don't expose a component filter).
"""

from dash import MATCH, Input, Output, Patch, State, callback, ctx, html, no_update
from dash.exceptions import PreventUpdate
from datetime import datetime
import logging

from dashboard.components.fleet_overview import (
    build_fleet_overview,
    get_band_rows_chunk,
    more_button_label,
)
from dashboard.components.fleet_criteria import render_fleet_criteria
from dashboard.components.labels import translate_component_label
from dashboard.components.source_status import render_fleet_overview_data_sources

logger = logging.getLogger(__name__)


def build_component_filter_options(data: dict) -> list:
    """Component options deduplicated across alerts and oil sources, labeled
    with the same function Alertas uses.

    `value` stays the raw, uppercased-for-dedup component (the join key a
    future per-component filter would match against); only `label` goes
    through `translate_component_label`.
    """
    if not data:
        return []

    components = set()

    alerts = data.get("alerts", [])
    for row in alerts:
        comp = row.get("componente", "")
        if comp and comp != "Desconocido":
            components.add(comp.upper())

    oil = data.get("oil", [])
    for row in oil:
        details = row.get("component_details", [])
        if isinstance(details, list):
            for d in details:
                if isinstance(d, dict):
                    comp = d.get("component", "")
                    if comp:
                        components.add(comp.upper())

    if not components:
        return []

    return [{"label": translate_component_label(c), "value": c} for c in sorted(components)]


def register_overview_general_callbacks(app):
    """Register callbacks for the Fleet Overview page."""

    @callback(
        Output("overview-source-status", "children"),
        [Input("client-selector", "value")],
    )
    def update_overview_source_status(client):
        if not client:
            return None
        return render_fleet_overview_data_sources(client)

    @callback(
        Output("overview-criteria", "children"),
        [Input("client-selector", "value")],
    )
    def update_overview_criteria(client):
        """The criteria every state of this client follows (collapsed panel under the search)."""
        if not client:
            return None
        return render_fleet_criteria(client)

    @callback(
        [
            Output("overview-fleet-cards", "children"),
            Output("overview-last-update", "children"),
            Output("fleet-search", "value"),
        ],
        [Input("client-selector", "value"), Input("fleet-search", "value")],
    )
    def update_fleet_overview(client, query):
        """Draws the bands from the client's golden file. A new client clears the search; typing in the
        search lays the same file out again, filtered."""
        if not client:
            return build_fleet_overview(None), "N/A", no_update
        if ctx.triggered_id == "fleet-search":
            return build_fleet_overview(client, query), no_update, no_update
        return build_fleet_overview(client), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ""

    @callback(
        [
            Output({"type": "fleet-rows", "band": MATCH}, "children"),
            Output({"type": "fleet-more", "band": MATCH}, "children"),
            Output({"type": "fleet-more", "band": MATCH}, "hidden"),
        ],
        Input({"type": "fleet-more", "band": MATCH}, "n_clicks"),
        [State("client-selector", "value"), State("fleet-search", "value")],
        prevent_initial_call=True,
    )
    def load_more_fleet_rows(n_clicks, client, query):
        """Append the band's next chunk of rows (50 per click) - only the new
        rows travel to the browser; the ones already shown are not resent."""
        if not n_clicks or not client:
            raise PreventUpdate
        band = ctx.triggered_id["band"]
        rows, remaining = get_band_rows_chunk(client, band, n_clicks, query)
        patch = Patch()
        patch.extend(rows)
        return patch, more_button_label(remaining) if remaining else "", not remaining
