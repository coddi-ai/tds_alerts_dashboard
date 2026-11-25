"""Callbacks of Monitoreo > Operación y rendimiento (registered on import, like oil_callbacks).

client -> weeks (latest selected) -> fleets -> the page. Two selections tie the page together:

- the unit under analysis (`opp-unit`): chosen in its dropdown or by clicking a bar of the ranking.
  It redraws the ranking (outlined), its side card, the ramp boxes and the map's "unidad" coloring,
  restarts the curve's unit selector (`opp-curve-units`, where other units of the same model can be
  added to compare) on it, and moves the ramp selection to the ramp where that unit loses most;
- the ramp (`opp-ramp-select`): chosen in its dropdown, by clicking a ramp on the map or one of the
  unit's worst ramps. It redraws the ramp boxes and outlines the ramp on the map.

Those controls are created with the page, so their callbacks run when it is rendered and read the
page filters as State. Every read goes through src/data/operation_performance.py, which caches each
parquet (and the map paths) by (mtime, size).
"""

from __future__ import annotations

from typing import Optional

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
)
def render_opp_page(client, folder, fleet):
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
        return tab.build_page(data, all_fleets=fleet in (None, "all"))
    except Exception:
        logger.exception("Operación y rendimiento: could not render the page for %s / %s", client, folder)
        return views.empty_state(t("opp.empty.error_title"), t("opp.empty.error_text"), icon="fa-circle-exclamation")


# ------------------------------------------------------------------------------------------------
# The unit under analysis
# ------------------------------------------------------------------------------------------------

@callback(
    Output("opp-unit", "value"),
    Input("opp-ranking-graph", "clickData"),
    State("opp-unit", "options"),
    prevent_initial_call=True,
)
def select_unit_from_ranking(click, options):
    """A click on a bar of the ranking selects its unit (customdata[5] of the bar)."""
    try:
        unit = click["points"][0]["customdata"][5]
    except (TypeError, KeyError, IndexError):
        raise PreventUpdate
    if unit not in {o["value"] for o in options or []}:
        raise PreventUpdate
    return unit


@callback(
    Output("opp-ranking-graph", "figure"),
    Input("opp-unit", "value"),
    *PAGE_STATE,
)
def update_ranking(unit, client, folder, fleet):
    data = week_data(client, folder, fleet)
    if data is None:
        raise PreventUpdate
    show_fleet = fleet in (None, "all") and len(data.fleets) > 1
    return charts.ranking_figure(data.camiones, show_fleet, selected=unit)


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
    Output("opp-curve-units", "value"),
    Input("opp-unit", "value"),
    prevent_initial_call=True,
)
def curve_follows_unit(unit):
    """A new unit under analysis restarts the curve on it (the user may then add others)."""
    return [unit] if unit else []


@callback(
    Output("opp-curve-graph", "figure"),
    Output("opp-curve-caption", "children"),
    Output("opp-curve-units", "options"),
    Input("opp-curve-units", "value"),
    *PAGE_STATE,
)
def update_curve(units, client, folder, fleet):
    """The curve of the first selected unit's model, with up to MAX_CURVE_UNITS units of that model
    over the rest of the fleet. Units of another model are disabled in the selector."""
    data = week_data(client, folder, fleet)
    if data is None:
        raise PreventUpdate
    per_unit = op.unit_climbs(data.pasadas)
    models = dict(zip(per_unit["unidad"], per_unit["modelo"]))
    units = [u for u in (units or []) if u in models]
    model = models[units[0]] if units else (data.models[0] if data.models else None)
    units = [u for u in units if models[u] == model][:charts.MAX_CURVE_UNITS]
    climbs = dict(zip(per_unit["unidad"], per_unit["pasadas"]))
    caption = t("opp.panel.curve.caption", modelo=model or "—", unidad=", ".join(units) or "—",
                n=sum(int(climbs[u]) for u in units))
    figure = charts.curve_figure(data.pasadas, data.curvas, model, units)
    return figure, caption, views.curve_unit_options(per_unit, model, units)


# ------------------------------------------------------------------------------------------------
# The ramp and the map
# ------------------------------------------------------------------------------------------------

@callback(
    Output("opp-ramp-select", "value"),
    Input("opp-unit", "value"),
    Input("opp-map", "clickData"),
    Input({"type": "opp-worst-ramp", "rampa": ALL}, "n_clicks"),
    State("opp-ramp-select", "options"),
    *PAGE_STATE,
    prevent_initial_call=True,
)
def select_ramp(unit, map_click, _worst_clicks, options, client, folder, fleet):
    """Map click -> that ramp; one of the unit's worst ramps -> that ramp; a new unit -> the ramp where
    it loses most. Only ramps offered in the dropdown (climb ramps with full-throttle climbs) are taken."""
    offered = {o["value"] for o in options or []}
    trigger = ctx.triggered_id
    ramp = None
    if trigger == "opp-map":
        try:
            ramp = map_click["points"][0]["customdata"][0]
        except (TypeError, KeyError, IndexError):
            ramp = None
    elif isinstance(trigger, dict) and trigger.get("type") == "opp-worst-ramp":
        if ctx.triggered and ctx.triggered[0].get("value"):     # a real click, not the buttons appearing
            ramp = trigger.get("rampa")
    elif trigger == "opp-unit":
        data = week_data(client, folder, fleet)
        ramps = op.unit_ramps(data.pasadas, data.rampas, unit) if data is not None else None
        if ramps is not None and not ramps.empty:
            ramp = next((r for r in ramps["rampa_id"] if r in offered), None)
    if not ramp or ramp not in offered:
        return no_update
    return ramp


@callback(
    Output("opp-ramp-graph", "figure"),
    Output("opp-ramp-caption", "children"),
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
    return charts.ramp_box_figure(climbs, data.camiones, metric or "hp_pendiente", selected=unit), caption


@callback(
    Output("opp-map", "figure"),
    Output("opp-map-caption", "children"),
    Input("opp-map-color", "value"),
    Input("opp-map-base", "value"),
    Input("opp-unit", "value"),
    Input("opp-ramp-select", "value"),
    *PAGE_STATE,
)
def update_map(mode, base, unit, rampa_id, client, folder, fleet):
    week = _week(folder)
    if not client or week is None:
        raise PreventUpdate
    points, segments = op.ramp_map_data(client, week, fleet)
    unit_speed = op.unit_segment_speed(points, unit) if mode == "unidad" else None
    figure = charts.ramp_map_figure(segments, mode or "pendiente", base or "satelite", unit_speed, unit, rampa_id)
    caption = t("opp.panel.map.caption", n=segments["rampa_id"].nunique()) if not segments.empty else ""
    return figure, caption


# ------------------------------------------------------------------------------------------------
# Decision table
# ------------------------------------------------------------------------------------------------

@callback(
    Output("opp-decision-table", "data"),
    Output("opp-decision-count", "children"),
    Input("opp-decision-filter", "value"),
    *PAGE_STATE,
)
def filter_decision_table(decisions, client, folder, fleet):
    data = week_data(client, folder, fleet)
    if data is None:
        raise PreventUpdate
    rows = views.decision_rows(data.camiones, decisions or [])
    return rows, t("opp.panel.decision.count", n=len(rows), total=len(data.camiones))
