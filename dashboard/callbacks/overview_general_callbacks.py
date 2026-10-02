"""
Callbacks for the Fleet Overview page (dashboard/tabs/tab_overview_general.py).

The heavy lifting - per-technique status/freshness aggregation, banding and
card rendering - lives in dashboard/components/fleet_overview.py. This module
wires that into Dash and keeps the handful of helpers other code/tests still
depend on: `calculate_alert_criticality_score` (Alerts' only per-unit
severity concept, reused by fleet_overview.py) and
`build_component_filter_options` (component dedup precedent kept for
Phase 2/3's Unit Summary content per
documentation/general/general_specs/00_implementation_guide.md §3.4, even
though Phase 1's Fleet Overview cards don't expose a component filter).
"""

from dash import MATCH, Input, Output, Patch, State, callback, ctx, html
from dash.exceptions import PreventUpdate
from datetime import datetime, timedelta
import logging

import pandas as pd

from dashboard.components.fleet_overview import (
    build_fleet_overview,
    get_band_rows_chunk,
    more_button_label,
)
from dashboard.components.labels import translate_component_label
from dashboard.components.source_status import render_fleet_overview_source_status

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


def calculate_alert_criticality_score(df_alerts: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    """
    Calculate equipment criticality score based on recent alerts.

    Formula: More alerts for same equipment/component = higher criticality.
    This is Alerts' only per-unit severity concept (documentation/general/
    general_specs/00_implementation_guide.md §1.1) - there is no
    severity/priority field in the raw alert data itself.

    Args:
        df_alerts: DataFrame with alert data (UnitId, componente, Timestamp)
        days: Number of days to consider recent alerts

    Returns:
        DataFrame with equipo, alert_count, component_count, criticality_score, status
    """
    if df_alerts.empty:
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])

    if 'Timestamp' not in df_alerts.columns:
        logger.warning(f"Column 'Timestamp' not found. Available: {df_alerts.columns.tolist()}")
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])

    cutoff_date = datetime.now() - timedelta(days=days)

    df_alerts = df_alerts.copy()
    df_alerts['Timestamp'] = pd.to_datetime(df_alerts['Timestamp'])

    recent = df_alerts[df_alerts['Timestamp'] >= cutoff_date].copy()

    if recent.empty:
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])

    if 'UnitId' not in recent.columns or 'componente' not in recent.columns:
        logger.warning(f"Required columns not found. Available: {recent.columns.tolist()}")
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])

    grouped = recent.groupby(['UnitId', 'componente']).size().reset_index(name='alerts_per_component')

    equipment_stats = grouped.groupby('UnitId').agg({
        'alerts_per_component': 'sum',
        'componente': 'nunique'
    }).reset_index()

    equipment_stats.columns = ['equipo', 'alert_count', 'component_count']

    equipment_stats['criticality_score'] = (
        equipment_stats['alert_count'] *
        (1 + equipment_stats['component_count'] * 0.5)
    ).round(1)

    def categorize_status(score):
        if score == 0:
            return 'Normal'
        elif score <= 15:
            return 'Alerta'
        else:
            return 'Crítico'

    equipment_stats['status'] = equipment_stats['criticality_score'].apply(categorize_status)

    return equipment_stats.sort_values('criticality_score', ascending=False)


def register_overview_general_callbacks(app):
    """Register callbacks for the Fleet Overview page."""

    @callback(
        Output("overview-source-status", "children"),
        [Input("client-selector", "value")],
    )
    def update_overview_source_status(client):
        if not client:
            return html.Div()
        return render_fleet_overview_source_status(client)

    @callback(
        [
            Output("overview-fleet-cards", "children"),
            Output("overview-last-update", "children"),
        ],
        [Input("client-selector", "value")],
    )
    def update_fleet_overview(client):
        if not client:
            return build_fleet_overview(None), "N/A"
        return build_fleet_overview(client), datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @callback(
        [
            Output({"type": "fleet-rows", "band": MATCH}, "children"),
            Output({"type": "fleet-more", "band": MATCH}, "children"),
            Output({"type": "fleet-more", "band": MATCH}, "hidden"),
        ],
        Input({"type": "fleet-more", "band": MATCH}, "n_clicks"),
        State("client-selector", "value"),
        prevent_initial_call=True,
    )
    def load_more_fleet_rows(n_clicks, client):
        """Append the band's next chunk of rows (50 per click) - only the new
        rows travel to the browser; the ones already shown are not resent."""
        if not n_clicks or not client:
            raise PreventUpdate
        band = ctx.triggered_id["band"]
        rows, remaining = get_band_rows_chunk(client, band, n_clicks)
        patch = Patch()
        patch.extend(rows)
        return patch, more_button_label(remaining) if remaining else "", not remaining
