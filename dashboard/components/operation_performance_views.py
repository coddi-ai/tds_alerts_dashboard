"""Building blocks of Monitoreo > Operación y rendimiento: panel cards, KPI tiles, the decision table
and empty states. Figures come from operation_performance_charts.py; data rules from
src/data/operation_performance.py.

Follows the Monitor de Aceite conventions (ui_notes_improved.md): KPI tiles are `oil_ui.kpi_tile`,
color is never the only signal (every decision chip carries its word) and metadata is a caption.
"""

from __future__ import annotations

from typing import Optional

import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
from dash import dash_table, dcc, html

from dashboard.components.oil_ui import NEUTRAL, kpi_tile, severity_chip
from dashboard.components.operation_performance_charts import DEMAND_BANDS, MAX_CURVE_UNITS, demand_band, fmt
from shared.severity import SEVERITY_TIERS
from src.data import operation_performance as op
from src.i18n import t

GRAPH_CONFIG = {"displaylogo": False, "responsive": True,
                "modeBarButtonsToRemove": ["lasso2d", "select2d"]}


# Tall figures (a row per unit: 44 in Capstone) scroll inside their card instead of stretching the row.
SCROLL_HEIGHT = 620


def graph(graph_id: Optional[str] = None, figure=None, scroll: Optional[str] = None, config: Optional[dict] = None):
    """A figure (or an empty slot a callback fills) with the dashboard's loading spinner. `scroll="y"`
    keeps a tall figure inside SCROLL_HEIGHT px; `scroll="x"` lets a wide one (its minWidth set by its
    callback) scroll sideways. `config` adds to (or overrides) GRAPH_CONFIG."""
    props = {"config": {**GRAPH_CONFIG, **(config or {})}}
    if graph_id:
        props["id"] = graph_id
    if figure is not None:
        props["figure"] = figure
    loading = dcc.Loading(dcc.Graph(**props), type="circle", delay_show=250)
    if scroll == "y":
        return html.Div(loading, className="opp-scroll-y", style={"maxHeight": f"{SCROLL_HEIGHT}px"})
    if scroll == "x":
        return html.Div(loading, className="opp-scroll-x")
    return loading


def panel_card(title: str, question: str, body, *, how_to_read: Optional[str] = None, controls=None,
               caption=None, icon: str = "fa-chart-bar", panel_id: Optional[str] = None) -> dbc.Card:
    """A panel: its title and the question it answers, optional controls above the figure, and a
    "Cómo se lee" note below it."""
    header = html.Div([
        html.Div([
            html.Span(html.I(className=f"fas {icon}", **{"aria-hidden": "true"}), className="opp-panel__icon"),
            html.Div([
                html.H5(title, className="opp-panel__title mb-0"),
                html.P(question, className="opp-panel__question mb-0"),
            ]),
        ], className="opp-panel__heading"),
        html.Div(caption, className="opp-panel__caption") if caption is not None else None,
    ], className="opp-panel__header")
    children = [header]
    if controls is not None:
        children.append(html.Div(controls, className="opp-panel__controls"))
    children.append(body)
    # `is not None`: a component a callback fills (an empty Span) is falsy, Dash components count children.
    if how_to_read is not None and how_to_read != "":
        children.append(html.P([
            html.I(className="fas fa-circle-info me-2", **{"aria-hidden": "true"}),
            html.Strong(t("opp.how_to_read") + " "), how_to_read,
        ], className="opp-panel__howto mb-0"))
    attrs = {"id": panel_id} if panel_id else {}
    return dbc.Card(dbc.CardBody(children), className="shadow-sm mb-4 opp-panel", **attrs)


def control(label: str, component, control_id: str, *, width: Optional[int] = None) -> html.Div:
    """A panel control with its real <label for>."""
    style = {"minWidth": f"{width}px"} if width else None
    return html.Div([html.Label(label, htmlFor=control_id, className="oil-filter-label"), component],
                    className="opp-control", style=style)


def empty_state(title: str, text: str, icon: str = "fa-truck-moving") -> html.Div:
    return html.Div([
        html.I(className=f"fas {icon} opp-empty__icon", **{"aria-hidden": "true"}),
        html.H5(title, className="mt-3 mb-1"),
        html.P(text, className="text-muted mb-0"),
    ], className="opp-empty")


def decision_chip(decision) -> html.Span:
    """The decision word on its severity tint (neutral for "Sin datos suficientes")."""
    tier = op.DECISION_TIER.get(decision)
    tone = SEVERITY_TIERS[tier] if tier else NEUTRAL
    return html.Span(decision or "—", className="kpi-chip", style={"background": tone["bg"], "color": tone["text"]})


# ------------------------------------------------------------------------------------------------
# Ranking and the unit under analysis
# ------------------------------------------------------------------------------------------------

def decision_counts(camiones: Optional[pd.DataFrame]) -> html.Div:
    """"23 Conforme · 12 Seguimiento · 9 Revisar": one chip per decision present."""
    if camiones is None or camiones.empty:
        return html.Div()
    counts = camiones["decision"].value_counts()
    chips = [html.Span([html.Strong(f"{int(counts[d])} "), decision_chip(d)], className="opp-count")
             for d in op.DECISIONS if d in counts]
    return html.Div(chips, className="opp-counts")


def unit_options(camiones: Optional[pd.DataFrame]) -> list:
    """Every unit of the week in natural order (letters, then the number ascending), labelled with
    its decision."""
    if camiones is None or camiones.empty:
        return []
    decisions = dict(zip(camiones["unidad"], camiones["decision"]))
    return [{"label": f"{u} · {decisions[u]}", "value": u} for u in op.sort_units(decisions)]


def curve_unit_options(per_unit: pd.DataFrame, model: Optional[str], selected) -> list:
    """Units with loaded full-throttle climbs, in natural order. A unit of another model than the
    curve's, or any new one once MAX_CURVE_UNITS are selected, is listed but disabled."""
    selected = set(selected or [])
    several_models = per_unit["modelo"].nunique() > 1
    full = len(selected) >= MAX_CURVE_UNITS
    options = []
    for row in per_unit.itertuples():
        label = t("opp.curve.unit_option", unidad=row.unidad, n=int(row.pasadas))
        if several_models:
            label += f" · {row.modelo}"
        other_model = model is not None and row.modelo != model
        options.append({"label": label, "value": row.unidad,
                        "disabled": row.unidad not in selected and (other_model or full)})
    return options


def _leveled(value, level: Optional[str]):
    """A figure's value in its level's color (op.kpi_level: green good, amber watch, red bad); plain
    when the figure has no range of its own."""
    if not level:
        return value
    return html.Span(value, className=f"opp-level opp-level--{level}",
                     style={"color": SEVERITY_TIERS[level]["text"]})


def _stat(label: str, value, caption: Optional[str] = None, trend: Optional[tuple] = None,
          level: Optional[str] = None) -> html.Div:
    """A figure of the unit's card: its value in the color of its own range (`level`), and `trend` =
    (tier, text) from _trend: its change against the earlier weeks, a chip colored by that change
    alone (green better, amber / red worse, neutral about the same)."""
    tier, text = trend or (None, None)
    return html.Div([
        html.Div(label, className="opp-stat__label"),
        html.Div(_leveled(value, level), className="opp-stat__value"),
        html.Div(severity_chip(tier, text), className="opp-stat__trend") if text else None,
        html.Div(caption, className="opp-stat__caption") if caption else None,
    ], className="opp-stat")


def unit_focus(data: op.WeekData, unit: Optional[str]) -> html.Div:
    """What the selected unit's week looks like: decision and rank in its fleet, then its figures: IVs,
    climbs, minutes lost and what it operated (trips, seconds lost per trip, engine load against its
    fleet, hours climbing)."""
    row = op.unit_row(data.camiones, unit)
    if row is None:
        return html.P(t("opp.focus.none"), className="text-muted mb-0")
    fleet_size = int((data.camiones["flota"] == row["flota"]).sum())
    operation = op.unit_operation(data.pasadas, data.camiones)
    mine = operation[operation["unidad"] == unit].iloc[0]
    fleet_units = set(data.camiones.loc[data.camiones["flota"] == row["flota"], "unidad"])
    fleet_ops = operation[operation["unidad"].isin(fleet_units)]
    fleet_load = fleet_ops["carga_motor"].median()
    fleet_loss = fleet_ops["s_perdidos_viaje"].median()
    shares = op.unit_lost_shares(data.camiones, data.pasadas)
    fleet_share = shares.reindex(list(fleet_units)).median()
    rank = t("opp.focus.rank", n=int(row["ranking"]), total=fleet_size, flota=row["flota"])
    # Each figure against the unit's own earlier weeks (up to BASELINE_WEEKS).
    figures = op.unit_figures(data.camiones, data.pasadas, unit) or {}
    baseline = op.unit_baseline(data.client, data.week, unit)

    def trend(key, figure=None):
        return _trend(key, figures.get(figure or key), baseline)

    def level(key):
        reference = {"s_perdidos_viaje": fleet_loss, "lost_share": fleet_share}.get(key)
        return op.kpi_level(key, figures.get(key), reference)

    # One horizontal strip: who (decision, rank) · the figures.
    head = html.Div([
        html.Div(unit, className="opp-focus__unit"),
        html.Div(rank, className="opp-focus__rank mb-2"),
        decision_chip(row["decision"]),
    ], className="opp-focus__who")
    return dbc.Row([
        dbc.Col(head, xs=12, lg=3, xl=2, className="mb-3"),
        dbc.Col(html.Div([
            _stat(t("opp.focus.iv_rel"), fmt(row["iv_rel_p50"]), t("opp.focus.iv_rel_caption"), trend("iv_rel_p50"),
                  level("iv_rel_p50")),
            _stat(t("opp.focus.iv_curve"), fmt(row["iv_p50"]), t("opp.focus.iv_curve_caption"), trend("iv_p50"),
                  level("iv_p50")),
            _stat(t("opp.focus.climbs"), fmt(row["pasadas_capacidad"], 0), trend=trend("pasadas_capacidad")),
            # Minutes grow with how much it climbed: compared as a share of its time climbing at full throttle.
            _stat(t("opp.focus.lost"), fmt(row["min_perdidos_flota"], 0), t("opp.focus.lost_caption"),
                  trend("lost_share"), level("lost_share")),
            _stat(t("opp.focus.trips"), fmt(mine["viajes"], 0),
                  t("opp.focus.trips_caption", km=fmt(mine["km_subida"], 0)), trend("viajes")),
            _stat(t("opp.focus.loss_per_trip"), _seconds(mine["s_perdidos_viaje"]),
                  t("opp.focus.fleet_value", value=_seconds(fleet_loss)), trend("s_perdidos_viaje"),
                  level("s_perdidos_viaje")),
            _stat(t("opp.focus.engine_load"), _percent(mine["carga_motor"]),
                  t("opp.focus.fleet_value", value=_percent(fleet_load)), trend("carga_motor")),
            _stat(t("opp.focus.hours"), fmt(mine["h_subida"], 1), t("opp.focus.hours_caption"), trend("h_subida")),
        ], className="opp-stats opp-stats--wide"), xs=12, lg=9, xl=10, className="mb-3"),
    ], className="opp-focus g-3")


def unit_ramp_list(ramps: pd.DataFrame, selected: Optional[str]) -> html.Div:
    """The unit's ramps, most demanding first, next to its map: each a button (pattern id
    `opp-unit-ramp-btn`) with the ramp's demand band color, its grade and length, and the unit's IV
    against the curve and against its fleet there (flagged when it loses: relative IV < 0,97). A first
    button shows every ramp again. The selected one is marked."""
    all_button = html.Button(
        [html.I(className="fas fa-layer-group me-2", **{"aria-hidden": "true"}), t("opp.unit_ramps.all")],
        id={"type": "opp-unit-ramp-btn", "rampa": ""}, n_clicks=0,
        className="opp-ramp-btn opp-ramp-btn--all" + (" is-active" if not selected else ""),
    )
    if ramps is None or ramps.empty:
        return html.Div([all_button, html.P(t("opp.focus.no_ramps", n=op.MIN_UNIT_RAMP_CLIMBS),
                                            className="text-muted small mt-2 mb-0")], className="opp-ramp-list")
    buttons = [all_button]
    for r in ramps.itertuples():
        _low, _key, color, _width = DEMAND_BANDS[demand_band(r.pend_pct)]
        loses = pd.notna(r.iv_rel) and r.iv_rel < op.IV_REL_REVIEW
        buttons.append(html.Button([
            html.Span(className="opp-ramp-btn__swatch", style={"background": color}),
            html.Span([html.Span(r.rampa_id, className="opp-ramp-btn__id"),
                       html.Span(t("opp.unit_ramps.grade", pend=fmt(r.pend_pct, 1), km=fmt(r.km, 1)),
                                 className="opp-ramp-btn__name")]),
            html.Span([
                t("opp.unit_ramps.iv", iv=fmt(r.iv), rel=fmt(r.iv_rel), n=int(r.pasadas)),
                html.Span(t("opp.unit_ramps.loses"), className="opp-ramp-btn__flag") if loses else None,
            ], className="opp-ramp-btn__value"),
        ], id={"type": "opp-unit-ramp-btn", "rampa": r.rampa_id}, n_clicks=0,
            className="opp-ramp-btn" + (" is-active" if r.rampa_id == selected else ""),
            title=t("opp.unit_ramps.button_title")))
    return html.Div(buttons, className="opp-ramp-list")


# ------------------------------------------------------------------------------------------------
# Resumen
# ------------------------------------------------------------------------------------------------

def _seconds(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{fmt(value, 0)} s"


def _percent(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{fmt(value, 0)} %"


def _high_load_caption(kpis: dict) -> str:
    share, top = kpis.get("high_load_share"), kpis.get("high_load_top")
    text = t("opp.kpi.high_load_caption", pct=fmt(100 * share, 0) if share is not None else "—",
             load=fmt(op.HIGH_ENGINE_LOAD, 0), n=fmt(kpis.get("trips"), 0))
    if top:
        text += " · " + t("opp.kpi.high_load_top", unidad=top[0], h=fmt(top[1], 1))
    return text


def _weeks_label(baseline: Optional[dict]) -> str:
    weeks = (baseline or {}).get("weeks") or []
    if not weeks:
        return ""
    if len(weeks) == 1:
        return t("opp.kpi.vs_week", n=weeks[0].number)
    return t("opp.kpi.vs_weeks", first=weeks[0].number, last=weeks[-1].number)


def _trend(key: str, value, baseline: Optional[dict]):
    """(tier, chip text) of a figure's change against the earlier weeks: "▲ 12 % vs S43–S46", or
    "▼ 0,3 %" for an index. The tier is that change alone (op.kpi_trend): better green, worse amber /
    red, about the same (or a figure without a judgement) neutral. (None, None) without an earlier
    week. Where the figure itself stands is the value's color (_leveled), not the chip's."""
    trend = op.kpi_trend(key, value, (baseline or {}).get(key))
    if trend is None:
        return None, None
    change = trend["change"]
    if op.KPI_TREND[key]["relative"]:
        # An index moves by tenths of a percent: one decimal; other figures whole percents.
        decimals = 1 if key.startswith("iv") else 0
        shown = round(abs(100 * change), decimals)
        amount = f"{fmt(shown, decimals)} %"
    elif key == "carga_motor":
        shown = round(abs(change))
        amount = t("opp.kpi.points", n=fmt(shown, 0))       # percentage points of engine load
    else:
        shown = round(abs(change), 2)
        amount = fmt(shown)
    if shown == 0:
        # A change that rounds to nothing reads "0 %" (or "0 pts"): no arrow, no decimals.
        zero = t("opp.kpi.points", n="0") if key == "carga_motor" else "0 %"
        return trend["tier"], f"{zero} {_weeks_label(baseline)}"
    arrow = "▲" if change > 0 else "▼"
    return trend["tier"], f"{arrow} {amount} {_weeks_label(baseline)}"


def kpi_row(kpis: dict, measured_payload: bool, baseline: Optional[dict] = None) -> dbc.Row:
    """Minutes lost · the fleet's speed index · engine hours at high load · km climbed loaded. Each tile
    takes the color of how it compares with the mean of the earlier weeks (better green, worse amber or
    red, about the same neutral), with the change in its chip."""
    share = kpis.get("lost_share")
    lost_caption = (t("opp.kpi.lost_minutes_share", pct=fmt(100 * share, 1)) if share is not None
                    else t("opp.kpi.lost_minutes_caption"))
    if measured_payload and kpis.get("tonnes"):
        distance_caption = t("opp.kpi.distance_caption_tonnes", h=fmt(kpis["hours_loaded"], 0),
                             kt=fmt(kpis["tonnes"] / 1000, 1))
    else:
        per_trip = kpis["km_loaded"] / kpis["trips"] if kpis.get("trips") else None
        distance_caption = t("opp.kpi.distance_caption", h=fmt(kpis["hours_loaded"], 0), km=fmt(per_trip, 1))
    figures = [
        # Compared as their share of the climbing time: fewer minutes in a quieter week is not better.
        ("lost_share", t("opp.kpi.lost_minutes"), fmt(kpis["lost_minutes"], 0), "fa-clock", lost_caption),
        ("iv_weighted", t("opp.kpi.iv_fleet"), fmt(kpis.get("iv_weighted")), "fa-gauge-high",
         t("opp.kpi.iv_weighted_caption" if measured_payload else "opp.kpi.iv_weighted_caption_nominal",
           km=fmt(kpis.get("km_base"), 0), iv=fmt(kpis.get("iv_median")))),
        # Hours depend on how much the fleet worked: they are compared as a share of the time on ramps.
        ("high_load_share", t("opp.kpi.high_load"), f'{fmt(kpis.get("high_load_hours"), 0)} h', "fa-gauge-simple-high",
         _high_load_caption(kpis)),
        ("km_loaded", t("opp.kpi.distance"), f'{fmt(kpis.get("km_loaded"), 0)} km', "fa-mountain", distance_caption),
    ]
    tiles = []
    for key, label, value, icon, caption in figures:
        tier, chip = _trend(key, kpis.get(key), baseline)
        value = _leveled(value, op.kpi_level(key, kpis.get(key)))
        tiles.append(kpi_tile(label, value, icon=icon, tier=tier, chip=chip, caption=caption))
    return dbc.Row([dbc.Col(tile, xs=12, sm=6, xl=3, className="mb-3") for tile in tiles], className="mb-1")


# The fleet view's table: who goes to the bottom of the pit. The cause and the climbs are in the
# unit's evidence; here, performance and what each truck operated.
DECISION_TABLE_COLUMNS = (
    ("ranking", "opp.col.ranking"), ("unidad", "opp.col.unit"), ("flota", "opp.col.fleet"),
    ("iv_rel_p50", "opp.col.iv_rel"), ("iv_p50", "opp.col.iv_curve"), ("viajes", "opp.col.trips"),
    ("s_perdidos_viaje", "opp.col.loss_per_trip"), ("decision", "opp.col.decision"),
)
NUMERIC_COLUMNS = ("ranking", "iv_rel_p50", "iv_p50", "viajes", "s_perdidos_viaje")


def decision_rows(camiones: Optional[pd.DataFrame], decisions=None,
                  operation: Optional[pd.DataFrame] = None) -> list:
    """Rows of the decision table, by fleet and ranking (best first); IVs with 2 decimals. Each row's
    `id` is its unit, so a click on the row selects it."""
    if camiones is None or camiones.empty:
        return []
    df = camiones.copy()
    if operation is not None and not operation.empty:
        df = df.merge(operation[["unidad", "viajes", "s_perdidos_viaje"]], on="unidad", how="left")
    for column in ("viajes", "s_perdidos_viaje"):
        if column not in df:
            df[column] = np.nan
    if decisions:
        df = df[df["decision"].isin(decisions)]
    df = df.sort_values(["flota", "ranking"])
    rows = []
    for row in df.itertuples():
        rows.append({
            "id": row.unidad,
            "ranking": int(row.ranking) if pd.notna(row.ranking) else None,
            "unidad": row.unidad, "flota": row.flota,
            "iv_rel_p50": round(float(row.iv_rel_p50), 2) if pd.notna(row.iv_rel_p50) else None,
            "iv_p50": round(float(row.iv_p50), 2) if pd.notna(row.iv_p50) else None,
            "viajes": int(row.viajes) if pd.notna(row.viajes) else None,
            "s_perdidos_viaje": round(float(row.s_perdidos_viaje), 1) if pd.notna(row.s_perdidos_viaje) else None,
            "decision": row.decision,
        })
    return rows


def decision_table(table_id: str, rows: list, show_fleet: bool) -> dash_table.DataTable:
    """Sortable table; the decision cell takes its decision's tint (and keeps its word)."""
    columns = [
        {"name": t(label), "id": key, "type": "numeric" if key in NUMERIC_COLUMNS else "text"}
        for key, label in DECISION_TABLE_COLUMNS if show_fleet or key != "flota"
    ]
    conditional = [
        {"if": {"filter_query": f'{{decision}} = "{decision}"', "column_id": "decision"},
         "backgroundColor": (SEVERITY_TIERS[tier] if tier else NEUTRAL)["bg"],
         "color": (SEVERITY_TIERS[tier] if tier else NEUTRAL)["text"], "fontWeight": 700}
        for decision, tier in op.DECISION_TIER.items()
    ]
    return dash_table.DataTable(
        # Every truck on one scrolling list, the header kept in view (operation_performance.css), level
        # with the ranking next to it.
        id=table_id, columns=columns, data=rows, sort_action="native", page_action="none",
        style_as_list_view=True, cell_selectable=True,
        style_table={"overflowX": "auto", "overflowY": "auto", "maxHeight": f"{SCROLL_HEIGHT}px"},
        style_header={"backgroundColor": "#1e293b", "color": "#ffffff", "fontWeight": 600, "fontSize": 12,
                      "border": "none", "whiteSpace": "normal"},
        style_cell={"fontFamily": "inherit", "fontSize": 13, "padding": "8px 10px", "textAlign": "left",
                    "border": "none", "borderBottom": "1px solid #e2e8f0", "whiteSpace": "normal", "height": "auto"},
        style_cell_conditional=[{"if": {"column_id": c}, "textAlign": "right"} for c in NUMERIC_COLUMNS]
        + [{"if": {"column_id": "unidad"}, "fontWeight": 700, "cursor": "pointer"}],
        style_data_conditional=conditional + [
            {"if": {"state": "active"}, "backgroundColor": "#e0ecff", "border": "1px solid #2563eb"},
        ],
    )


def low_efficiency_card(camiones: Optional[pd.DataFrame]) -> Optional[dbc.Card]:
    """Clients without payload (Capstone): trucks whose median IV is below 1 at nominal load."""
    rows = op.low_efficiency(camiones)
    if rows.empty:
        body = html.P(t("opp.low_eff.none"), className="text-muted mb-0")
    else:
        body = html.Ul([
            html.Li([
                html.Strong(row.unidad), html.Span(f" · {row.flota}", className="text-muted"),
                html.Span(t("opp.low_eff.item", iv=fmt(row.iv_p50), pct=fmt(100 * row.pasadas_bajo_1, 0)),
                          className="ms-2"),
            ]) for row in rows.itertuples()
        ], className="opp-list mb-0")
    return panel_card(
        t("opp.low_eff.title"), t("opp.low_eff.question"), body,
        how_to_read=t("opp.low_eff.how"), icon="fa-weight-hanging",
    )


def method_accordion(measured_payload: bool) -> dbc.Accordion:
    """What IV, relative IV and the decision mean, collapsed by default."""
    load = t("opp.method.load_measured" if measured_payload else "opp.method.load_nominal")
    ok, review = fmt(op.IV_REL_OK), fmt(op.IV_REL_REVIEW)
    items = [
        html.Li([html.Strong(t("opp.method.iv_label") + " · "), t("opp.method.iv")]),
        html.Li([html.Strong(t("opp.method.iv_rel_label") + " · "), t("opp.method.iv_rel")]),
        html.Li([html.Strong(t("opp.method.base_label") + " · "), t("opp.method.base")]),
        html.Li([html.Strong(t("opp.method.load_label") + " · "), load]),
        html.Li([html.Strong(t("opp.method.decision_label") + " · "),
                 decision_chip(op.CONFORME), f" ≥ {ok} · ", decision_chip(op.SEGUIMIENTO), f" {review} – {ok} · ",
                 decision_chip(op.REVISAR), f" < {review} · ", decision_chip(op.SIN_DATOS), " ",
                 t("opp.method.min_climbs", n=op.MIN_CLIMBS)]),
    ]
    return dbc.Accordion(
        dbc.AccordionItem(html.Ul(items, className="opp-list mb-0"), title=t("opp.method.title"), item_id="method"),
        start_collapsed=True, className="mb-4 opp-method",
    )
