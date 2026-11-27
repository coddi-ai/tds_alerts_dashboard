"""Callbacks of Monitoreo > Operación y rendimiento (registered on import, like oil_callbacks).

client -> weeks (latest selected) -> fleets -> the page (the week's figures and two views: Flota and
Evidencia por unidad). Three selections tie the views together:

- the unit under analysis (`opp-unit`, the one selector at the top left of the unit's view): chosen
  there, or by clicking a unit on the fleet view's scatter or heat map, which also opens the unit's
  view. It redraws the unit's card, weeks, curve, ramp list and map, outlines it in the ramp boxes,
  and moves the fleet's ramp selection to the ramp where it loses most;
- the fleet's ramp (`opp-ramp-select`, in the fleet view): chosen in its dropdown or by clicking the
  fleet map. It redraws the ramp boxes and outlines the ramp on the fleet map;
- the unit's ramp (`opp-unit-ramp`, a store in the unit's view): chosen in the unit's ramp list or by
  clicking its map; None (every ramp) again with "Todas las rampas" or a new unit.

Both views are built with the page (dcc.Tabs keeps the hidden one in the layout), so their callbacks
run when it is rendered and read the page filters as State. The open view is kept in `opp-view`, so
a change of week or fleet rebuilds the page on the same view. Every read goes through
src/data/operation_performance.py, which caches each parquet (and the map paths) by (mtime, size).
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from dash import ALL, Input, Output, State, callback, ctx, html, no_update
from dash.exceptions import PreventUpdate

from dashboard.components import operation_performance_charts as charts
from dashboard.components import operation_performance_views as views
from dashboard.components.source_status import render_service_data_sources
from dashboard.tabs import tab_operation_performance as tab
from src.data import operation_performance as op
from src.i18n import t
from src.utils.logger import get_logger

logger = get_logger(__name__)

SERVICE_ID = "monitoring-operation-performance"
PAGE_STATE = (State("client-selector", "value"), State("opp-week", "value"), State("opp-fleet", "value"))


def _week(folder: Optional[str]) -> Optional[op.Week]:
    return op.Week.parse(folder) if folder else None


def week_data(client: Optional[str], folder: Optional[str], fleet: Optional[str] = None) -> Optional[op.WeekData]:
    """The selected week of the client, restricted to the selected fleet; None when there is none."""
    week = _week(folder)
    if not client or week is None:
        return None
    return op.filter_fleet(op.load_week(client, week), fleet)


def _date(value) -> str:
    return value.strftime("%d-%m-%Y")


def week_label(week: op.Week) -> str:
    return t("opp.week_option", n=week.number, start=week.monday.strftime("%d-%m"), end=_date(week.sunday))


# ------------------------------------------------------------------------------------------------
# Page filters
# ------------------------------------------------------------------------------------------------

@callback(Output("opp-source-status", "children"), Input("client-selector", "value"))
def update_opp_source_status(client):
    if not client:
        return None
    try:
        return render_service_data_sources(client, SERVICE_ID)
    except Exception:
        logger.exception("Operación y rendimiento: could not resolve the data sources of %s", client)
        return None


@callback(
    Output("opp-week", "options"),
    Output("opp-week", "value"),
    Input("client-selector", "value"),
)
def populate_weeks(client):
    """Complete weeks, newest first; the newest one is selected."""
    weeks = list(reversed(op.available_weeks(client))) if client else []
    options = [{"label": week_label(w), "value": w.folder} for w in weeks]
    return options, (weeks[0].folder if weeks else None)


@callback(
    Output("opp-fleet", "options"),
    Output("opp-fleet", "value"),
    Output("opp-fleet", "disabled"),
    Input("client-selector", "value"),
    Input("opp-week", "value"),
    State("opp-fleet", "value"),
)
def populate_fleets(client, folder, current):
    """"Todas las flotas" plus each fleet of the week; a client with one fleet shows just it."""
    week = _week(folder)
    camiones = op.load_table(client, week, "camiones", columns=("flota",)) if client and week else None
    fleets = sorted(camiones["flota"].dropna().unique().tolist()) if camiones is not None else []
    if len(fleets) <= 1:
        options = [{"label": fleets[0] if fleets else t("opp.filter.all_fleets"), "value": "all"}]
        return options, "all", True
    options = [{"label": t("opp.filter.all_fleets"), "value": "all"}] + [{"label": f, "value": f} for f in fleets]
    return options, (current if current in fleets else "all"), False


@callback(
    Output("opp-week-caption", "children"),
    Input("client-selector", "value"),
    Input("opp-week", "value"),
)
def update_week_caption(client, folder):
    week = _week(folder)
    if not client or week is None:
        return ""
    manifest = op.read_manifest(client, week)
    parts = [t("opp.caption.period", start=_date(week.monday), end=_date(week.sunday))]
    generated = str(manifest.get("generado_utc") or "")[:10]
    if generated:
        parts.append(t("opp.caption.generated", date="-".join(reversed(generated.split("-")))))
    pasadas = op.load_table(client, week, "pasadas_eval", columns=("payload_t_media", "modelo"))
    if pasadas is not None:
        models = ", ".join(sorted(pasadas["modelo"].dropna().unique()))
        load = t("opp.caption.load_measured" if "payload_t_media" in pasadas.columns else "opp.caption.load_nominal")
        parts.append(f"{models} · {load}")
    return [html.I(className="fas fa-calendar-week me-2", **{"aria-hidden": "true"}), " · ".join(parts)]


@callback(
    Output("opp-page-content", "children"),
    Input("client-selector", "value"),
    Input("opp-week", "value"),
    Input("opp-fleet", "value"),
    State("opp-view", "data"),
)
def render_opp_page(client, folder, fleet, view=None):
    if not client:
        raise PreventUpdate
    if not op.available_weeks(client):
        return tab.no_data_state(client)
    if not folder:
        raise PreventUpdate
    try:
        data = week_data(client, folder, fleet)
        if data is None or data.camiones is None:
            return views.empty_state(t("opp.empty.week_incomplete_title"), t("opp.empty.week_incomplete_text"),
                                     icon="fa-calendar-xmark")
        return tab.build_page(data, all_fleets=fleet in (None, "all"), view=view)
    except Exception:
        logger.exception("Operación y rendimiento: could not render the page for %s / %s", client, folder)
        return views.empty_state(t("opp.empty.error_title"), t("opp.empty.error_text"), icon="fa-circle-exclamation")


@callback(Output("opp-view", "data"), Input("opp-view-tabs", "value"), prevent_initial_call=True)
def remember_view(view):
    if view not in tab.VIEWS:
        raise PreventUpdate
    return view


# ------------------------------------------------------------------------------------------------
# The unit under analysis
# ------------------------------------------------------------------------------------------------

def _clicked_unit(click, index: int = 0) -> Optional[str]:
    try:
        custom = click["points"][0]["customdata"]
    except (TypeError, KeyError, IndexError):
        return None
    if isinstance(custom, (list, tuple)):
        return custom[index] if len(custom) > index else None
    return custom     # a heat map cell carries the unit alone


@callback(
    Output("opp-unit", "value"),
    Output("opp-view-tabs", "value"),
    Input("opp-fleet-graph", "clickData"),
    State("opp-unit", "options"),
    prevent_initial_call=True,
)
def select_unit(click, options):
    """A unit clicked on the fleet card (a cell of the heat map: its customdata; a bubble of the scatter:
    customdata[0]) becomes the unit under analysis and its evidence opens."""
    unit = _clicked_unit(click)
    if not unit or unit not in {o["value"] for o in options or []}:
        raise PreventUpdate
    return unit, "unidad"


@callback(
    Output("opp-unit-focus", "children"),
    Input("opp-unit", "value"),
    *PAGE_STATE,
    prevent_initial_call=True,
)
def update_unit_focus(unit, client, folder, fleet):
    """The page is rendered with the default unit's card; this redraws it when the unit changes."""
    data = week_data(client, folder, fleet)
    if data is None:
        raise PreventUpdate
    return views.unit_focus(data, unit)


@callback(
    Output("opp-curve-graph", "figure"),
    Output("opp-curve-caption", "children"),
    Input("opp-unit", "value"),
    *PAGE_STATE,
)
def update_curve(unit, client, folder, fleet):
    """The unit's loaded full-throttle climbs over its model's curve, the rest of the fleet in gray."""
    data = week_data(client, folder, fleet)
    if data is None:
        raise PreventUpdate
    per_unit = op.unit_climbs(data.pasadas)
    models = dict(zip(per_unit["unidad"], per_unit["modelo"]))
    climbs = dict(zip(per_unit["unidad"], per_unit["pasadas"]))
    units = [unit] if unit in models else []
    model = models[unit] if units else (data.models[0] if data.models else None)
    caption = t("opp.panel.curve.caption", modelo=model or "—", unidad=unit or "—",
                n=int(climbs.get(unit, 0)) if units else 0)
    figure = charts.curve_figure(data.pasadas, data.curvas, model, units, height=tab.EVIDENCE_HEIGHT)
    return figure, caption


@callback(
    Output("opp-history-graph", "figure"),
    Output("opp-history-caption", "children"),
    Input("opp-unit", "value"),
    *PAGE_STATE,
)
def update_history(unit, client, folder, fleet):
    """The unit's days up to the selected week: 3-day moving mean of its relative IV against its fleet's."""
    week = _week(folder)
    if not client or week is None:
        raise PreventUpdate
    weekly = op.load_weekly_history(client, week, fleet)
    daily = op.load_history(client, fleet)
    if not daily.empty:
        daily = daily[daily["dia"] <= pd.Timestamp(week.sunday)]
    figure = charts.unit_history_figure(weekly, daily, unit, charts.HISTORY_METRIC, current=week)
    figure.update_layout(height=tab.EVIDENCE_HEIGHT)
    mine = weekly[weekly["unidad"] == unit] if not weekly.empty and unit else weekly
    if mine is None or mine.empty:
        return figure, ""
    caption = t("opp.panel.history.caption", n=len(mine), unidad=unit,
                ok=int((mine["decision"] == op.CONFORME).sum()),
                review=int((mine["decision"] == op.REVISAR).sum()))
    return figure, caption


# ------------------------------------------------------------------------------------------------
# The ramps and the maps
# ------------------------------------------------------------------------------------------------

def _clicked_ramp(click) -> Optional[str]:
    try:
        return click["points"][0]["customdata"][0]
    except (TypeError, KeyError, IndexError):
        return None


@callback(
    Output("opp-ramp-select", "value"),
    Input("opp-unit", "value"),
    Input("opp-map", "clickData"),
    State("opp-ramp-select", "options"),
    *PAGE_STATE,
    prevent_initial_call=True,
)
def select_ramp(unit, map_click, options, client, folder, fleet):
    """Fleet view: a click on the fleet map -> that ramp; a new unit -> the ramp where it loses most.
    Only ramps offered in the dropdown (climb ramps with full-throttle climbs) are taken."""
    offered = {o["value"] for o in options or []}
    ramp = None
    if ctx.triggered_id == "opp-map":
        ramp = _clicked_ramp(map_click)
    elif ctx.triggered_id == "opp-unit":
        data = week_data(client, folder, fleet)
        ramps = op.unit_ramps(data.pasadas, data.rampas, unit) if data is not None else None
        if ramps is not None and not ramps.empty:
            ramp = next((r for r in ramps["rampa_id"] if r in offered), None)
    if not ramp or ramp not in offered:
        return no_update
    return ramp


def _unit_map_data(unit, client, folder, fleet):
    """(segments, the unit's stretches, the unit's ramps on the map) for the unit's view."""
    week = _week(folder)
    data = week_data(client, folder, fleet)
    if week is None or data is None:
        return None
    points, segments = op.ramp_map_data(client, week, fleet)
    stretches = op.unit_stretches(points, unit, data.curvas)
    ramps = op.unit_ramp_table(data.pasadas, data.rampas, unit)
    on_map = set(stretches["rampa_id"]) & set(segments["rampa_id"])
    return segments, stretches, ramps[ramps["rampa_id"].isin(on_map)].reset_index(drop=True)


@callback(
    Output("opp-unit-ramp", "data"),
    Input({"type": "opp-unit-ramp-btn", "rampa": ALL}, "n_clicks"),
    Input("opp-unit-map", "clickData"),
    Input("opp-unit", "value"),
    prevent_initial_call=True,
)
def select_unit_ramp(_clicks, map_click, _unit):
    """Unit view: a ramp of its list or a click on its map -> only that ramp; "Todas las rampas" or a
    new unit -> every ramp."""
    trigger = ctx.triggered_id
    if trigger == "opp-unit":
        return None
    if trigger == "opp-unit-map":
        return _clicked_ramp(map_click) or no_update
    if isinstance(trigger, dict) and trigger.get("type") == "opp-unit-ramp-btn":
        if not (ctx.triggered and ctx.triggered[0].get("value")):     # the list redrawn, not a click
            raise PreventUpdate
        return trigger.get("rampa") or None
    raise PreventUpdate


@callback(
    Output("opp-unit-ramps", "children"),
    Input("opp-unit", "value"),
    Input("opp-unit-ramp", "data"),
    *PAGE_STATE,
)
def update_unit_ramps(unit, selected, client, folder, fleet):
    found = _unit_map_data(unit, client, folder, fleet)
    if found is None:
        raise PreventUpdate
    return views.unit_ramp_list(found[2], selected)


BOX_PX_PER_UNIT = 30        # below this a box is unreadable: the boxes figure then scrolls sideways


@callback(
    Output("opp-ramp-graph", "figure"),
    Output("opp-ramp-caption", "children"),
    Output("opp-ramp-graph", "style"),
    Input("opp-ramp-select", "value"),
    Input("opp-ramp-metric", "value"),
    Input("opp-unit", "value"),
    *PAGE_STATE,
)
def update_ramp(rampa_id, metric, unit, client, folder, fleet):
    data = week_data(client, folder, fleet)
    if data is None:
        raise PreventUpdate
    climbs = op.ramp_climbs(data.pasadas, rampa_id)
    caption = t("opp.panel.ramp.caption", n=charts.fmt(len(climbs), 0), trucks=climbs["unidad"].nunique()) if rampa_id else ""
    figure = charts.ramp_box_figure(climbs, data.camiones, metric or "hp_pendiente", selected=unit,
                                    height=charts.MAP_HEIGHT)
    style = {"minWidth": f"{BOX_PX_PER_UNIT * climbs['unidad'].nunique() + 120}px"}
    return figure, caption, style


# ------------------------------------------------------------------------------------------------
# Fleet view: who goes to the bottom of the pit (heat map) or load against IV (scatter)
# ------------------------------------------------------------------------------------------------

HIDDEN = {"display": "none"}
# The selectors each way of reading the fleet uses: (heat map columns, scatter x).
FLEET_CONTROLS = {"mapa_calor": (True, False), "dispersion": (False, True)}


@callback(
    Output("opp-fleet-graph", "figure"),
    Output("opp-fleet-how", "children"),
    Output("opp-heatmap-extra-wrap", "style"),
    Output("opp-scatter-x-wrap", "style"),
    Input("opp-fleet-view", "value"),
    Input("opp-heatmap-extra", "value"),
    Input("opp-scatter-x", "value"),
    *PAGE_STATE,
)
def update_fleet(view, extra, x, client, folder, fleet):
    data = week_data(client, folder, fleet)
    if data is None:
        raise PreventUpdate
    view = view if view in tab.FLEET_VIEWS else tab.FLEET_VIEWS[0]
    measured = data.measured_payload
    stress = op.unit_stress(data.pasadas, data.camiones)
    if view == "dispersion":
        xs = tab.scatter_x_options(data)
        x = x if x in xs else xs[0]
        figure = charts.stress_scatter_figure(stress, x, tab.SCATTER_Y, measured)
        how = t("opp.panel.scatter.how")
    else:
        allowed = tab.heatmap_extra_options(stress, measured)
        columns = tab.heatmap_default_columns(stress, measured) + [c for c in (extra or []) if c in allowed]
        figure = charts.fleet_heatmap_figure(stress, columns, measured)
        how = t("opp.panel.heatmap.how" if measured else "opp.panel.heatmap.how_nominal")
    styles = [None if shown else HIDDEN for shown in FLEET_CONTROLS[view]]
    return (figure, how, *styles)


def _map_caption(segments) -> str:
    """How many ramps are drawn, and the most demanding ones (median grade of their stretches)."""
    if segments.empty:
        return ""
    ramps = charts.ramp_demand(segments).head(charts.DEMANDING_RAMPS)
    hardest = ", ".join(f"{r.rampa_id} ({charts.fmt(r.pend_pct, 1)} %)" for r in ramps.itertuples())
    return t("opp.panel.map.caption", n=segments["rampa_id"].nunique(), hardest=hardest)


@callback(
    Output("opp-map", "figure"),
    Output("opp-map-caption", "children"),
    Input("opp-map-base", "value"),
    Input("opp-ramp-select", "value"),
    *PAGE_STATE,
)
def update_map(base, rampa_id, client, folder, fleet):
    """Fleet view: demand (band) and the fleet's performance (path color) on one map."""
    week = _week(folder)
    if not client or week is None:
        raise PreventUpdate
    _points, segments = op.ramp_map_data(client, week, fleet)
    return charts.fleet_ramp_map_figure(segments, base or "satelite", rampa_id), _map_caption(segments)


@callback(
    Output("opp-unit-map", "figure"),
    Output("opp-unit-map-caption", "children"),
    Input("opp-unit-map-color", "value"),
    Input("opp-unit", "value"),
    Input("opp-unit-ramp", "data"),
    *PAGE_STATE,
)
def update_unit_map(color_by, unit, rampa_id, client, folder, fleet):
    """Unit view: the unit on its ramps, each ramp colored by how demanding it is and each 100 m by
    the unit's IV against the curve (or its engine effort); one ramp alone when one is selected."""
    found = _unit_map_data(unit, client, folder, fleet)
    if found is None:
        raise PreventUpdate
    segments, stretches, ramps = found
    figure = charts.unit_ramp_map_figure(segments, stretches, ramps, unit, color_by or "iv", rampa_id)
    shown = stretches[stretches["rampa_id"].isin(set(ramps["rampa_id"]))]
    if rampa_id in set(ramps["rampa_id"]):
        shown = shown[shown["rampa_id"] == rampa_id]
    if shown.empty or shown["iv"].notna().sum() == 0:
        return figure, ""
    caption = t("opp.panel.unit_map.caption", unidad=unit, n=shown["rampa_id"].nunique(),
                below=int((shown["iv"] < 1).sum()), total=int(shown["iv"].notna().sum()),
                iv=charts.fmt(shown["iv"].median()))
    return figure, caption
