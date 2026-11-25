"""Building blocks of Monitoreo > Operación y rendimiento: panel cards, KPI tiles, the decision table
and empty states. Figures come from operation_performance_charts.py; data rules from
src/data/operation_performance.py.

Follows the Monitor de Aceite conventions (ui_notes_improved.md): KPI tiles are `oil_ui.kpi_tile`,
color is never the only signal (every decision chip carries its word) and metadata is a caption.
"""

from __future__ import annotations

from typing import Optional

import dash_bootstrap_components as dbc
import pandas as pd
from dash import dash_table, dcc, html

from dashboard.components.oil_ui import NEUTRAL, kpi_tile
from dashboard.components.operation_performance_charts import MAX_CURVE_UNITS, fmt
from shared.severity import SEVERITY_TIERS
from src.data import operation_performance as op
from src.i18n import t

GRAPH_CONFIG = {"displaylogo": False, "responsive": True,
                "modeBarButtonsToRemove": ["lasso2d", "select2d"]}


def graph(graph_id: Optional[str] = None, figure=None) -> dcc.Loading:
    """A figure (or an empty slot a callback fills) with the dashboard's loading spinner."""
    props = {"config": GRAPH_CONFIG}
    if graph_id:
        props["id"] = graph_id
    if figure is not None:
        props["figure"] = figure
    return dcc.Loading(dcc.Graph(**props), type="circle", delay_show=250)


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
    if how_to_read:
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


def _stat(label: str, value, caption: Optional[str] = None) -> html.Div:
    return html.Div([
        html.Div(label, className="opp-stat__label"),
        html.Div(value, className="opp-stat__value"),
        html.Div(caption, className="opp-stat__caption") if caption else None,
    ], className="opp-stat")


def unit_focus(data: op.WeekData, unit: Optional[str]) -> html.Div:
    """What the selected unit's week looks like: decision, rank in its fleet, IVs, climbs, minutes lost,
    probable cause, and the ramps where it loses most (each one a button that opens that ramp)."""
    row = op.unit_row(data.camiones, unit)
    if row is None:
        return html.P(t("opp.focus.none"), className="text-muted mb-0")
    fleet_size = int((data.camiones["flota"] == row["flota"]).sum())
    rank = t("opp.focus.rank", n=int(row["ranking"]), total=fleet_size, flota=row["flota"])
    cause = row["causa_principal"] if isinstance(row["causa_principal"], str) and row["causa_principal"] else None
    ramps = op.unit_ramps(data.pasadas, data.rampas, unit).head(3)
    if ramps.empty:
        ramp_list = html.P(t("opp.focus.no_ramps", n=op.MIN_UNIT_RAMP_CLIMBS), className="text-muted mb-0 small")
    else:
        ramp_list = html.Div([
            html.Button([
                html.Span(r.rampa_id, className="opp-ramp-btn__id"),
                html.Span(r.nombre, className="opp-ramp-btn__name"),
                html.Span(t("opp.focus.ramp_value", iv=fmt(r.iv_rel), n=int(r.pasadas)), className="opp-ramp-btn__value"),
            ], id={"type": "opp-worst-ramp", "rampa": r.rampa_id}, n_clicks=0, className="opp-ramp-btn",
                title=t("opp.focus.ramp_button_title"))
            for r in ramps.itertuples()
        ], className="opp-ramp-list")
    return html.Div([
        html.Div([
            html.Div([html.Div(unit, className="opp-focus__unit"), html.Div(rank, className="opp-focus__rank")]),
            decision_chip(row["decision"]),
        ], className="opp-focus__head"),
        html.Div([
            _stat(t("opp.focus.iv_rel"), fmt(row["iv_rel_p50"]), t("opp.focus.iv_rel_caption")),
            _stat(t("opp.focus.iv_curve"), fmt(row["iv_p50"]), t("opp.focus.iv_curve_caption")),
            _stat(t("opp.focus.climbs"), fmt(row["pasadas_capacidad"], 0)),
            _stat(t("opp.focus.lost"), fmt(row["min_perdidos_flota"], 0), t("opp.focus.lost_caption")),
        ], className="opp-stats"),
        html.Div([html.Span(t("opp.focus.cause"), className="opp-stat__label d-block"),
                  html.Span(cause or t("opp.focus.no_cause"), className="opp-focus__cause")], className="mb-3"),
        html.Div(t("opp.focus.worst_ramps"), className="opp-stat__label mb-2"),
        ramp_list,
    ], className="opp-focus")


# ------------------------------------------------------------------------------------------------
# Resumen
# ------------------------------------------------------------------------------------------------

def kpi_row(kpis: dict, measured_payload: bool) -> dbc.Row:
    """Camiones evaluados · IV mediano · Camiones a revisar (highlighted) · Minutos perdidos."""
    review = kpis["to_review"]
    iv_caption = t("opp.kpi.iv_caption_measured" if measured_payload else "opp.kpi.iv_caption_nominal",
                   n=fmt(kpis["climbs"], 0))
    tiles = [
        kpi_tile(t("opp.kpi.evaluated"), fmt(kpis["evaluated"], 0), icon="fa-truck",
                 caption=t("opp.kpi.evaluated_caption", total=kpis["trucks"])),
        kpi_tile(t("opp.kpi.iv_median"), fmt(kpis["iv_median"]), icon="fa-gauge-high", caption=iv_caption),
        kpi_tile(t("opp.kpi.to_review"), fmt(review, 0), icon="fa-triangle-exclamation",
                 tier="alto" if review else "bajo",
                 chip=t("opp.kpi.chip_review") if review else t("opp.kpi.chip_none"),
                 caption=t("opp.kpi.follow_up_caption", n=kpis["follow_up"])),
        kpi_tile(t("opp.kpi.lost_minutes"), fmt(kpis["lost_minutes"], 0), icon="fa-clock",
                 caption=t("opp.kpi.lost_minutes_caption")),
    ]
    return dbc.Row([dbc.Col(tile, xs=12, sm=6, xl=3, className="mb-3") for tile in tiles], className="mb-1")


DECISION_TABLE_COLUMNS = (
    ("ranking", "opp.col.ranking"), ("unidad", "opp.col.unit"), ("flota", "opp.col.fleet"),
    ("iv_rel_p50", "opp.col.iv_rel"), ("iv_p50", "opp.col.iv_curve"), ("pasadas_capacidad", "opp.col.climbs"),
    ("min_perdidos_flota", "opp.col.lost_min"), ("decision", "opp.col.decision"), ("causa_principal", "opp.col.cause"),
)


def decision_rows(camiones: Optional[pd.DataFrame], decisions=None) -> list:
    """Rows of the decision table, by fleet and ranking; IVs with 2 decimals, minutes rounded."""
    if camiones is None or camiones.empty:
        return []
    df = camiones.copy()
    if decisions:
        df = df[df["decision"].isin(decisions)]
    df = df.sort_values(["flota", "ranking"])
    rows = []
    for row in df.itertuples():
        rows.append({
            "ranking": int(row.ranking) if pd.notna(row.ranking) else None,
            "unidad": row.unidad, "flota": row.flota,
            "iv_rel_p50": round(float(row.iv_rel_p50), 2) if pd.notna(row.iv_rel_p50) else None,
            "iv_p50": round(float(row.iv_p50), 2) if pd.notna(row.iv_p50) else None,
            "pasadas_capacidad": int(row.pasadas_capacidad),
            "min_perdidos_flota": round(float(row.min_perdidos_flota)) if pd.notna(row.min_perdidos_flota) else None,
            "decision": row.decision,
            "causa_principal": row.causa_principal if isinstance(row.causa_principal, str) and row.causa_principal else "—",
        })
    return rows


def decision_table(table_id: str, rows: list, show_fleet: bool) -> dash_table.DataTable:
    """Sortable table; the decision cell takes its decision's tint (and keeps its word)."""
    columns = [
        {"name": t(label), "id": key, "type": "numeric" if key in ("ranking", "iv_rel_p50", "iv_p50",
                                                                  "pasadas_capacidad", "min_perdidos_flota") else "text"}
        for key, label in DECISION_TABLE_COLUMNS if show_fleet or key != "flota"
    ]
    conditional = [
        {"if": {"filter_query": f'{{decision}} = "{decision}"', "column_id": "decision"},
         "backgroundColor": (SEVERITY_TIERS[tier] if tier else NEUTRAL)["bg"],
         "color": (SEVERITY_TIERS[tier] if tier else NEUTRAL)["text"], "fontWeight": 700}
        for decision, tier in op.DECISION_TIER.items()
    ]
    return dash_table.DataTable(
        id=table_id, columns=columns, data=rows, sort_action="native", page_size=15, page_action="native",
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": "#1e293b", "color": "#ffffff", "fontWeight": 600, "fontSize": 12,
                      "border": "none", "whiteSpace": "normal"},
        style_cell={"fontFamily": "inherit", "fontSize": 13, "padding": "8px 10px", "textAlign": "left",
                    "border": "none", "borderBottom": "1px solid #e2e8f0", "whiteSpace": "normal", "height": "auto"},
        style_cell_conditional=[
            {"if": {"column_id": c}, "textAlign": "right"}
            for c in ("ranking", "iv_rel_p50", "iv_p50", "pasadas_capacidad", "min_perdidos_flota")
        ] + [{"if": {"column_id": "causa_principal"}, "minWidth": "220px"}],
        style_data_conditional=conditional,
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
