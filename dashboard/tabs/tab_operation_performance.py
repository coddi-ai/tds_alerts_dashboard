"""Monitoreo > Operación y rendimiento: rimpull and performance of haul trucks (OP-PE).

Each truck is compared with its manufacturer curve to decide which trucks go to the bottom of the
pit and which ones are reviewed, and why. Two views:

    Flota (the decision for the whole fleet)
        1. the week in figures that tie performance to the operation (minutes lost, engine hours at
           high load, IV per km climbed, km climbed loaded);
        2. load against IV (payload, or the distance on ramps for clients without payload), one bubble
           per unit, next to the heat map of who goes to the bottom of the pit: decision, load and
           relative IV per unit, other operation figures on demand. A click on a unit in either opens
           its evidence;
        3. the map, demand and performance in one figure: the real GPS path of the busiest climb
           ramps over satellite imagery, a band as steep as each 100 m (wider and darker = more
           demanding) under the path colored by the fleet's IV on that ramp (a click selects the
           ramp), next to the power of every truck on the selected ramp.

    Evidencia por unidad (why a unit got its decision)
        the unit's card (decision, IVs, what it operated, probable cause, worst ramps), its weeks
        (weekly value against the band of its fleet), then its climbs over the manufacturer curve
        next to the map of where along each ramp it is slower than the fleet.

Tall or wide figures (a row or a box per unit: 44 in Capstone) scroll inside their card, and the
cards of a row share its height.

The week and fleet filters apply to both views. Left out of the page for now, their figures kept in
operation_performance_charts.py: the ranking per unit and the decision table (replaced by the scatter
and the heat map), the other stress readings (performance by load bins, bars of one figure) and the
diagnosis, trend, descent and data-quality panels of the OP-PE specification. Callbacks: dashboard/callbacks/operation_performance_callbacks.py;
data: src/data/operation_performance.py.
"""

from __future__ import annotations

from typing import Optional

import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard.components import operation_performance_charts as charts
from dashboard.components import operation_performance_views as views
from src.data import operation_performance as op
from src.i18n import t

MAP_BASES = ("satelite", "calles")
VIEWS = ("flota", "unidad")


def create_layout() -> html.Div:
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.H2([html.I(className="fas fa-truck-moving me-3"), t("opp.title")], className="text-primary mb-1"),
                html.P(t("opp.subtitle"), className="text-muted mb-0"),
            ], xs=12, sm=True),
            # "Fuentes de Datos" button + popover (update_opp_source_status).
            dbc.Col(html.Div(id="opp-source-status"), xs=12, sm="auto", className="ds-header-slot"),
        ], className="mb-3"),

        # Page filters: they apply to both views.
        dbc.Row([
            dbc.Col(views.control(t("opp.filter.week"), dcc.Dropdown(id="opp-week", clearable=False,
                                                                       placeholder=t("opp.filter.week_placeholder")),
                                  "opp-week"), xs=12, md=4, lg=3),
            dbc.Col(views.control(t("opp.filter.fleet"), dcc.Dropdown(id="opp-fleet", clearable=False, value="all"),
                                  "opp-fleet"), xs=12, md=4, lg=3),
            dbc.Col(html.Div(id="opp-week-caption", className="opp-week-caption"), xs=12, md=4, lg=6,
                    className="d-flex align-items-end"),
        ], className="mb-4 p-3 bg-light rounded g-3"),

        # The open view survives a change of week or fleet (the page is rebuilt then).
        dcc.Store(id="opp-view", storage_type="memory", data=VIEWS[0]),
        dcc.Loading(html.Div(id="opp-page-content"), type="circle", delay_show=300),
    ], className="container-fluid p-4 opp-page")


def no_data_state(client: str | None) -> html.Div:
    return views.empty_state(t("opp.empty.no_weeks_title"), t("opp.empty.no_weeks_text", client=client or "—"))


def build_page(data: op.WeekData, all_fleets: bool, view: Optional[str] = None) -> html.Div:
    """The whole page for one week (already restricted to the selected fleet): what IV and the
    decision mean, and the two views, opened on `view` ("flota" by default)."""
    unit = op.default_unit(data.camiones)
    tabs = dcc.Tabs(id="opp-view-tabs", value=view if view in VIEWS else VIEWS[0], className="mb-4", children=[
        _tab(t("opp.view.fleet"), "flota", _fleet_view(data, unit, all_fleets)),
        _tab(t("opp.view.unit"), "unidad", _unit_view(data, unit)),
    ])
    return html.Div([views.method_accordion(data.measured_payload), tabs])


def _tab(label: str, value: str, children) -> dcc.Tab:
    return dcc.Tab(label=label, value=value, children=html.Div(children, className="pt-4"),
                   className="custom-tab pred-tab oil-tab", selected_className="custom-tab--selected pred-tab--selected")


# ------------------------------------------------------------------------------------------------
# Flota
# ------------------------------------------------------------------------------------------------

def _fleet_view(data: op.WeekData, unit: Optional[str], all_fleets: bool = True) -> list:
    # The week's figures, the fleet card (heat map or scatter, chosen in its selector) across the whole
    # width, then the map next to the ramp boxes. A unit clicked on the fleet card opens its evidence.
    stress = op.unit_stress(data.pasadas, data.camiones)
    fleet = None if all_fleets or not data.fleets else data.fleets[0]
    baseline = op.kpi_baseline(data.client, data.week, fleet)
    children = [
        views.kpi_row(op.week_kpis(data.camiones, data.pasadas), data.measured_payload, baseline),
        _fleet_card(data, stress),
        dbc.Row([
            dbc.Col(_map_card(), xs=12, xl=6),
            dbc.Col(_ramp_card(data, unit), xs=12, xl=6),
        ], className="opp-row"),
    ]
    if not data.measured_payload:
        children.append(views.low_efficiency_card(data.camiones))
    return children


# Two ways to read the fleet: load against IV (scatter, the main one) and who goes to the bottom of the
# pit (heat map).
FLEET_VIEWS = ("dispersion", "mapa_calor")
# Horizontal axis of the scatter: the measured payload when the client weighs every cycle (CDA), and
# always the distance on ramps (Capstone has no payload).
SCATTER_X = ("carga_t", "km_rampa")
# The scatter's vertical axis is the IV against the manufacturer curve: how the truck performs against
# what it should. (The relative IV, against the fleet, decides in the heat map.)
SCATTER_Y = "iv_p50"


def scatter_x_options(data: op.WeekData) -> list:
    return [x for x in SCATTER_X if x != "carga_t" or data.measured_payload]


def heatmap_default_columns(stress, measured_payload: bool = True) -> list:
    """The measured payload (or, without it, the distance on ramps) and the relative IV that decides."""
    load = "carga_t" if measured_payload and "carga_t" in getattr(stress, "columns", []) else "km_rampa"
    return [load, "iv_rel_p50"]


def heatmap_extra_options(stress, measured_payload: bool = True) -> list:
    """Columns the heat map can add to decision, load (or distance) and relative IV."""
    base = set(heatmap_default_columns(stress, measured_payload))
    candidates = [*op.stress_metrics(stress), "iv_p50", "s_perdidos_viaje", "indice_estres"]
    return [c for c in candidates if c not in base and c in stress.columns]


def _fleet_card(data: op.WeekData, stress) -> dbc.Card:
    label = lambda m: charts.stress_label(m, data.measured_payload)  # noqa: E731
    xs = scatter_x_options(data)

    def wrap(control_id, component, title, width=None):
        return html.Div(views.control(title, component, control_id, width=width), id=f"{control_id}-wrap")

    controls = [
        views.control(t("opp.fleet.view"), dbc.RadioItems(
            id="opp-fleet-view", value=FLEET_VIEWS[0], inline=True,
            options=[{"label": t(f"opp.fleet.view.{v}"), "value": v} for v in FLEET_VIEWS]), "opp-fleet-view"),
        wrap("opp-heatmap-extra", dcc.Dropdown(
            id="opp-heatmap-extra", multi=True, value=[], placeholder=t("opp.heatmap.extra_placeholder"),
            options=[{"label": label(c), "value": c} for c in heatmap_extra_options(stress, data.measured_payload)]),
            t("opp.heatmap.extra"), width=360),
        # A dropdown, so it is never mistaken for the view selector (radio buttons) next to it.
        wrap("opp-scatter-x", dcc.Dropdown(
            id="opp-scatter-x", value=xs[0], clearable=False, searchable=False,
            options=[{"label": label(x), "value": x} for x in xs]), t("opp.scatter.x"), width=260),
    ]
    body = html.Div([
        html.P([html.I(className="fas fa-hand-pointer me-2", **{"aria-hidden": "true"}), t("opp.fleet.click_hint")],
               className="opp-hint"),
        views.graph("opp-fleet-graph", scroll="y", config={"scrollZoom": False, "displayModeBar": False}),
    ])
    return views.panel_card(
        t("opp.panel.heatmap.title"), t("opp.panel.fleet.question"), body, controls=controls,
        caption=views.decision_counts(data.camiones), how_to_read=html.Span(id="opp-fleet-how"),
        icon="fa-table-cells", panel_id="opp-fleet-card",
    )


def _base_control(control_id: str) -> html.Div:
    return views.control(t("opp.map.base"), dbc.RadioItems(
        id=control_id, value="satelite", inline=True,
        options=[{"label": t(f"opp.map.base.{b}"), "value": b} for b in MAP_BASES]), control_id)


def _map_card() -> dbc.Card:
    return views.panel_card(
        t("opp.panel.map.title"), t("opp.panel.map.question"),
        views.graph("opp-map"), controls=[_base_control("opp-map-base")],
        caption=html.Span(id="opp-map-caption"),
        how_to_read=t("opp.panel.map.how"), icon="fa-map-location-dot", panel_id="opp-map-card",
    )


def _ramp_card(data: op.WeekData, unit: str | None) -> dbc.Card:
    ramps = op.ramp_options(data.pasadas, data.rampas)
    # Open on the ramp where the unit under analysis loses most (the first one its card lists), so
    # the card, the maps and this panel start on the same ramp; else the ramp with most climbs.
    offered = [r["rampa_id"] for r in ramps]
    worst = [r for r in op.unit_ramps(data.pasadas, data.rampas, unit)["rampa_id"] if r in offered]
    initial = worst[0] if worst else (offered[0] if offered else None)
    controls = [
        views.control(t("opp.control.ramp"), dcc.Dropdown(
            id="opp-ramp-select", clearable=False, value=initial,
            options=[{"label": t("opp.control.ramp_option", rampa=r["rampa_id"], nombre=r["nombre"], n=r["pasadas"]),
                      "value": r["rampa_id"]} for r in ramps]), "opp-ramp-select", width=300),
        views.control(t("opp.control.metric"), dbc.RadioItems(
            id="opp-ramp-metric", value="hp_pendiente", inline=True,
            options=[{"label": t("opp.metric.hp_pendiente"), "value": "hp_pendiente"},
                     {"label": t("opp.metric.iv"), "value": "iv"}]), "opp-ramp-metric"),
    ]
    return views.panel_card(
        t("opp.panel.ramp.title"), t("opp.panel.ramp.question"),
        views.graph("opp-ramp-graph", scroll="x"), controls=controls, caption=html.Span(id="opp-ramp-caption"),
        how_to_read=t("opp.panel.ramp.how"), icon="fa-mountain",
    )


# ------------------------------------------------------------------------------------------------
# Evidencia por unidad
# ------------------------------------------------------------------------------------------------

EVIDENCE_HEIGHT = 460       # the weeks and the curve share a row at this height


def _unit_view(data: op.WeekData, unit: Optional[str]) -> list:
    # Top to bottom: the unit (its one selector, top left, and its figures); its weeks next to its
    # climbs over the curve; then its ramps, most demanding first, next to the map of the unit on them.
    return [
        _focus_card(data, unit),
        dbc.Row([
            dbc.Col(_history_card(), xs=12, xl=6),
            dbc.Col(_curve_card(data), xs=12, xl=6),
        ], className="opp-row"),
        _unit_map_card(data),
    ]


def _focus_card(data: op.WeekData, unit: Optional[str]) -> dbc.Card:
    # The only unit selector of the page: every panel of this view follows it.
    selector = views.control(
        t("opp.focus.title"),
        dcc.Dropdown(id="opp-unit", options=views.unit_options(data.camiones), value=unit, clearable=False,
                     placeholder=t("opp.focus.select_placeholder")),
        "opp-unit", width=280,
    )
    return dbc.Card(dbc.CardBody([
        html.Div([selector, html.P(t("opp.focus.trend_hint"), className="opp-hint mb-0")],
                 className="opp-focus-card__top"),
        html.Div(views.unit_focus(data, unit), id="opp-unit-focus", className="mt-3"),
    ]), className="shadow-sm mb-4 opp-panel opp-focus-card")


def _curve_card(data: op.WeekData) -> dbc.Card:
    return views.panel_card(
        t("opp.panel.curve.title"), t("opp.panel.curve.question"),
        views.graph("opp-curve-graph"), caption=html.Span(id="opp-curve-caption"),
        how_to_read=t("opp.panel.curve.how" if data.measured_payload else "opp.panel.curve.how_nominal"),
        icon="fa-chart-line",
    )


def _history_card() -> dbc.Card:
    return views.panel_card(
        t("opp.panel.history.title"), t("opp.panel.history.question"),
        views.graph("opp-history-graph"), caption=html.Span(id="opp-history-caption"),
        how_to_read=t("opp.panel.history.how"), icon="fa-clock-rotate-left",
    )


def unit_map_colors(data: op.WeekData) -> list:
    """How the unit's map can color each 100 m: IV, and the engine signals this client records."""
    present = {"carga_motor": "carga_motor_pct_media", "rpm": "rpm_media", "potencia_hp": "potencia_hp_media"}
    columns = set(data.pasadas.columns) if data.pasadas is not None else set()
    return ["iv"] + [key for key, column in present.items() if column in columns]


def _unit_map_card(data: op.WeekData) -> dbc.Card:
    color = views.control(t("opp.unit_map.color"), dbc.RadioItems(
        id="opp-unit-map-color", value="iv", inline=True,
        options=[{"label": t(f"opp.unit_map.color.{c}"), "value": c} for c in unit_map_colors(data)]),
        "opp-unit-map-color")
    body = dbc.Row([
        dbc.Col([
            html.Div(t("opp.unit_ramps.title"), className="opp-stat__label mb-1"),
            html.P(t("opp.unit_ramps.hint"), className="opp-hint mb-2"),
            html.Div(id="opp-unit-ramps", className="opp-scroll-y opp-unit-ramps",
                     style={"maxHeight": f"{charts.MAP_HEIGHT - 60}px"}),
        ], xs=12, lg=4, xl=3, className="mb-3"),
        dbc.Col(views.graph("opp-unit-map"), xs=12, lg=8, xl=9),
    ], className="g-3")
    return views.panel_card(
        t("opp.panel.unit_map.title"), t("opp.panel.unit_map.question"),
        html.Div([dcc.Store(id="opp-unit-ramp", storage_type="memory", data=None), body]),
        controls=[color], caption=html.Span(id="opp-unit-map-caption"),
        how_to_read=t("opp.panel.unit_map.how"), icon="fa-map-location-dot", panel_id="opp-unit-map-card",
    )
