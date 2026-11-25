"""Monitoreo > Operación y rendimiento: rimpull and performance of haul trucks (OP-PE), on one page.

Each truck is compared with its manufacturer curve to decide which trucks go to the bottom of the
pit and which ones are reviewed, and why. The page reads top to bottom as one analysis:

    1. the week in four figures (and what IV and the decision mean);
    2. the climb performance ranking per unit, next to the unit under analysis (a click on a bar
       selects it): its decision, IVs, probable cause and the ramps where it loses most;
    3. the map: the real GPS path of the busiest climb ramps over satellite imagery, colored by how
       demanding each 100 m is, how the fleet performs there, or where the selected unit is slower
       than the fleet (a click on a ramp selects it);
    4. climbs over the manufacturer curve (the unit under analysis, plus other units of its model to
       compare), and the power of every truck on the selected ramp;
    5. the decision per truck (table).

The week and fleet filters apply to the whole page. The diagnosis, trend, descent and data-quality
panels of the OP-PE specification are left out of the page for now (their figures stay in
operation_performance_charts.py). Callbacks: dashboard/callbacks/operation_performance_callbacks.py;
data: src/data/operation_performance.py.
"""

from __future__ import annotations

from typing import Optional

import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard.components import operation_performance_views as views
from src.data import operation_performance as op
from src.i18n import t

MAP_MODES = ("pendiente", "flota", "unidad")
MAP_BASES = ("satelite", "calles")


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

        # Page filters: they apply to the whole page.
        dbc.Row([
            dbc.Col(views.control(t("opp.filter.week"), dcc.Dropdown(id="opp-week", clearable=False,
                                                                       placeholder=t("opp.filter.week_placeholder")),
                                  "opp-week"), xs=12, md=4, lg=3),
            dbc.Col(views.control(t("opp.filter.fleet"), dcc.Dropdown(id="opp-fleet", clearable=False, value="all"),
                                  "opp-fleet"), xs=12, md=4, lg=3),
            dbc.Col(html.Div(id="opp-week-caption", className="opp-week-caption"), xs=12, md=4, lg=6,
                    className="d-flex align-items-end"),
        ], className="mb-4 p-3 bg-light rounded g-3"),

        dcc.Loading(html.Div(id="opp-page-content"), type="circle", delay_show=300),
    ], className="container-fluid p-4 opp-page")


def no_data_state(client: str | None) -> html.Div:
    return views.empty_state(t("opp.empty.no_weeks_title"), t("opp.empty.no_weeks_text", client=client or "—"))


def build_page(data: op.WeekData, all_fleets: bool) -> html.Div:
    """The whole page for one week (already restricted to the selected fleet)."""
    unit = op.default_unit(data.camiones)
    children = [
        views.kpi_row(op.week_kpis(data.camiones, data.pasadas), data.measured_payload),
        views.method_accordion(data.measured_payload),
        dbc.Row([
            dbc.Col(_ranking_card(data), xs=12, xl=8),
            dbc.Col(_focus_card(data, unit), xs=12, xl=4),
        ], className="opp-ranking-row"),
        _map_card(),
        dbc.Row([
            dbc.Col(_curve_card(data, unit), xs=12, xl=6),
            dbc.Col(_ramp_card(data, unit), xs=12, xl=6),
        ]),
        _decision_card(data, all_fleets),
    ]
    if not data.measured_payload:
        children.append(views.low_efficiency_card(data.camiones))
    return html.Div(children)


def _ranking_card(data: op.WeekData) -> dbc.Card:
    return views.panel_card(
        t("opp.panel.ranking.title"), t("opp.panel.ranking.question"),
        html.Div([
            html.P([html.I(className="fas fa-hand-pointer me-2", **{"aria-hidden": "true"}),
                    t("opp.panel.ranking.hint")], className="opp-hint"),
            views.graph("opp-ranking-graph"),
        ]),
        caption=views.decision_counts(data.camiones),
        how_to_read=t("opp.panel.ranking.how"), icon="fa-ranking-star", panel_id="opp-ranking-card",
    )


def _focus_card(data: op.WeekData, unit: str | None) -> html.Div:
    selector = views.control(
        t("opp.focus.select"),
        dcc.Dropdown(id="opp-unit", options=views.unit_options(data.camiones), value=unit, clearable=False,
                     placeholder=t("opp.focus.select_placeholder")),
        "opp-unit",
    )
    card = dbc.Card(dbc.CardBody([
        html.Div([
            html.Span(html.I(className="fas fa-crosshairs", **{"aria-hidden": "true"}), className="opp-panel__icon"),
            html.H5(t("opp.focus.title"), className="opp-panel__title mb-0"),
        ], className="opp-panel__heading mb-3"),
        selector,
        html.Div(views.unit_focus(data, unit), id="opp-unit-focus", className="mt-3"),
    ]), className="shadow-sm mb-4 opp-panel opp-focus-card")
    return html.Div(card, className="opp-sticky")


def _map_card() -> dbc.Card:
    controls = [
        views.control(t("opp.map.color_by"), dbc.RadioItems(
            id="opp-map-color", value="pendiente", inline=True,
            options=[{"label": t(f"opp.map.mode.{m}"), "value": m} for m in MAP_MODES]), "opp-map-color"),
        views.control(t("opp.map.base"), dbc.RadioItems(
            id="opp-map-base", value="satelite", inline=True,
            options=[{"label": t(f"opp.map.base.{b}"), "value": b} for b in MAP_BASES]), "opp-map-base"),
    ]
    return views.panel_card(
        t("opp.panel.map.title"), t("opp.panel.map.question"),
        views.graph("opp-map"), controls=controls, caption=html.Span(id="opp-map-caption"),
        how_to_read=t("opp.panel.map.how"), icon="fa-map-location-dot", panel_id="opp-map-card",
    )


def _curve_card(data: op.WeekData, unit: Optional[str]) -> dbc.Card:
    # Starts on the unit under analysis (and follows it); other units of the same model can be added.
    per_unit = op.unit_climbs(data.pasadas)
    selected = [unit] if unit in set(per_unit["unidad"]) else []
    model = per_unit.loc[per_unit["unidad"] == unit, "modelo"].iloc[0] if selected else None
    selector = views.control(t("opp.curve.units"), dcc.Dropdown(
        id="opp-curve-units", multi=True, value=selected, placeholder=t("opp.curve.units_placeholder"),
        options=views.curve_unit_options(per_unit, model, selected)), "opp-curve-units", width=320)
    return views.panel_card(
        t("opp.panel.curve.title"), t("opp.panel.curve.question"),
        views.graph("opp-curve-graph"),
        controls=[selector, html.P(t("opp.curve.units_hint"), className="opp-hint mb-0 align-self-end")],
        caption=html.Span(id="opp-curve-caption"),
        how_to_read=t("opp.panel.curve.how" if data.measured_payload else "opp.panel.curve.how_nominal"),
        icon="fa-chart-line",
    )


def _ramp_card(data: op.WeekData, unit: str | None) -> dbc.Card:
    ramps = op.ramp_options(data.pasadas, data.rampas)
    # Open on the ramp where the unit under analysis loses most (the first one its card lists), so
    # the card, the map and this panel start on the same ramp; else the ramp with most climbs.
    offered = [r["rampa_id"] for r in ramps]
    worst = [r for r in op.unit_ramps(data.pasadas, data.rampas, unit)["rampa_id"] if r in offered]
    initial = worst[0] if worst else (offered[0] if offered else None)
    controls = [
        views.control(t("opp.control.ramp"), dcc.Dropdown(
            id="opp-ramp-select", clearable=False, value=initial,
            options=[{"label": t("opp.control.ramp_option", rampa=r["rampa_id"], nombre=r["nombre"], n=r["pasadas"]),
                      "value": r["rampa_id"]} for r in ramps]), "opp-ramp-select", width=320),
        views.control(t("opp.control.metric"), dbc.RadioItems(
            id="opp-ramp-metric", value="hp_pendiente", inline=True,
            options=[{"label": t("opp.metric.hp_pendiente"), "value": "hp_pendiente"},
                     {"label": t("opp.metric.iv"), "value": "iv"}]), "opp-ramp-metric"),
    ]
    return views.panel_card(
        t("opp.panel.ramp.title"), t("opp.panel.ramp.question"),
        views.graph("opp-ramp-graph"), controls=controls, caption=html.Span(id="opp-ramp-caption"),
        how_to_read=t("opp.panel.ramp.how"), icon="fa-mountain",
    )


def _decision_card(data: op.WeekData, all_fleets: bool) -> dbc.Card:
    show_fleet = all_fleets and len(data.fleets) > 1
    decision_options = [{"label": views.decision_chip(d), "value": d} for d in op.DECISIONS]
    return views.panel_card(
        t("opp.panel.decision.title"), t("opp.panel.decision.question"),
        html.Div(views.decision_table("opp-decision-table", views.decision_rows(data.camiones), show_fleet),
                 id="opp-decision-table-wrap"),
        controls=views.control(
            t("opp.panel.decision.filter"),
            dbc.Checklist(id="opp-decision-filter", options=decision_options, value=list(op.DECISIONS),
                          inline=True, className="opp-decision-filter"),
            "opp-decision-filter",
        ),
        caption=html.Span(id="opp-decision-count", className="oil-caption"),
        how_to_read=t("opp.panel.decision.how" if data.measured_payload else "opp.panel.decision.how_nominal"),
        icon="fa-clipboard-check",
    )
