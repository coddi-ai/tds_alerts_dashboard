"""Productive Mantenciones view.

The page keeps the auditable activity breakdown from the client reports and
uses source-defined maintenance intervals for out-of-service time.
"""

from __future__ import annotations

from src.i18n import t
import colorsys
import hashlib

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import dash_table, dcc, html
import dash_bootstrap_components as dbc


PARETO_BAR_COLOR = "#355c7d"
PARETO_LINE_COLOR = "#d08c60"
EQUIPMENT_COLORS = (
    "#355c7d",
    "#4f8a8b",
    "#d08c60",
    "#7b6ea8",
    "#6f8fb3",
    "#b56b78",
    "#5f9e7a",
    "#9a7b4f",
    "#778899",
    "#c47f3f",
    "#5b6d8a",
    "#cc79a7",
    "#86bc86",
    "#e07b91",
    "#8c6bb1",
    "#72b7b2",
    "#e58606",
    "#5d8aa8",
    "#a05d56",
    "#7a9e9f",
    "#c29a5b",
    "#6b7c93",
    "#9c755f",
    "#4d908e",
)
SYSTEM_COLORS = (
    "#4e79a7",
    "#59a14f",
    "#f28e2b",
    "#e15759",
    "#b07aa1",
    "#76b7b2",
    "#edc949",
    "#af7aa1",
)
SYSTEM_COLOR_ORDER = (
    "Sistema de Motor",
    "Sistema Hidráulico",
    "Tren de Fuerza",
    "Sistema de Frenado",
    "Sistema de Dirección",
    "Sin sistema",
)

# Generic source labels that are not actionable maintenance systems in the
# executive charts.  They remain available in the detail payload, but should
# not dominate the visual activity breakdown.
EXCLUDED_ACTIVITY_SYSTEMS = frozenset(
    {
        "equipo",
        "cabina",
        "estacion del operador - cabina",
        "estación del operador - cabina",
    }
)

# Font Awesome is loaded from a remote stylesheet in the dashboard shell. A
# missing webfont must not turn the executive view into a grid of tofu boxes,
# so Mantenciones uses plain Unicode fallbacks for decorative icons.
ICON_GLYPHS = {
    "fa-gauge-high": "●",
    "fa-hourglass-half": "◷",
    "fa-arrows-rotate": "↻",
    "fa-screwdriver-wrench": "⚒",
    "fa-truck": "▣",
    "fa-wrench": "◆",
    "fa-clipboard-list": "≡",
    "fa-sitemap": "⌘",
    "fa-calendar-day": "□",
    "fa-percentage": "%",
    "fa-chart-bar": "▥",
    "fa-chart-line": "╱",
    "fa-truck-loading": "▤",
    "fa-th": "▦",
    "fa-comment-alt": "▰",
    "fa-calendar-week": "□",
}


def _icon_glyph(icon: str) -> str:
    return ICON_GLYPHS.get(icon, "•")


def _is_excluded_activity_system(value) -> bool:
    normalized = " ".join(str(value or "").strip().lower().split())
    return normalized in EXCLUDED_ACTIVITY_SYSTEMS or normalized.endswith(" - cabina")


def _equipment_color_map(values) -> dict[str, str]:
    """Return stable equipment colors for every chart in the Summary."""
    equipment = sorted({str(value) for value in values if value is not None})
    colors = {}
    used_indexes = set()
    unassigned = []
    for value in equipment:
        suffix = value.rsplit("_", 1)[-1]
        if suffix.isdigit() and 1 <= int(suffix) <= len(EQUIPMENT_COLORS):
            index = int(suffix) - 1
            colors[value] = EQUIPMENT_COLORS[index]
            used_indexes.add(index)
        else:
            unassigned.append(value)
    available = [index for index in range(len(EQUIPMENT_COLORS)) if index not in used_indexes]
    for value, index in zip(unassigned, available):
        colors[value] = EQUIPMENT_COLORS[index]
    for value in unassigned[len(available):]:
        digest = hashlib.sha256(value.casefold().encode("utf-8")).digest()
        hue = int.from_bytes(digest[:2], "big") % 360 / 360
        saturation = 0.52 + digest[2] / 255 * 0.16
        lightness = 0.42 + digest[3] / 255 * 0.12
        red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
        colors[value] = f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"
    return colors


def _system_color_map(values) -> dict[str, str]:
    systems = {str(value) for value in values if value is not None}
    colors = {}
    used_indexes = set()
    for index, system in enumerate(SYSTEM_COLOR_ORDER):
        if system in systems and index < len(SYSTEM_COLORS):
            colors[system] = SYSTEM_COLORS[index]
            used_indexes.add(index)
    available = [index for index in range(len(SYSTEM_COLORS)) if index not in used_indexes]
    remaining = sorted(systems - set(colors))
    for system, index in zip(remaining, available):
        colors[system] = SYSTEM_COLORS[index]
    for system in remaining[len(available):]:
        digest = hashlib.sha256(system.casefold().encode("utf-8")).digest()
        hue = int.from_bytes(digest[:2], "big") % 360 / 360
        saturation = 0.52 + digest[2] / 255 * 0.16
        lightness = 0.42 + digest[3] / 255 * 0.12
        red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
        colors[system] = f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"
    return colors


def create_kpi_card(
    title: str,
    value: str = "—",
    icon: str = "fa-info-circle",
    color: str = "primary",
    scope_label: str | None = None,
    component_id: str | None = None,
):
    """Create a KPI card with an explicit, stable component id."""
    value_id = component_id or f"kpi-{title.lower().replace(' ', '-')}"
    return dbc.Card(
        dbc.CardBody(
            html.Div(
                [
                    html.Span(
                        _icon_glyph(icon),
                        className=f"maintenance-icon maintenance-kpi-icon text-{color}",
                        role="img",
                        style={"display": "inline-block", "fontSize": "1.65rem", "lineHeight": 1, "marginBottom": "0.5rem"},
                        **{"aria-label": title},
                    ),
                    html.H3(value, id=value_id, className="mb-0"),
                    html.P(title, className="text-muted mb-0"),
                    html.P(scope_label, className="text-muted small mb-0 fst-italic") if scope_label else None,
                ],
                className="text-center",
            )
        ),
        className="shadow-sm h-100",
    )


def create_context_metric(
    title: str,
    component_id: str,
    icon: str,
    color: str = "secondary",
    scope_label: str | None = None,
):
    """Render a compact secondary metric inside the activity context block."""
    return html.Div(
        [
            html.Span(
                _icon_glyph(icon),
                className=f"maintenance-icon text-{color}",
                role="img",
                **{"aria-label": title},
            ),
            html.P(title, className="text-muted small mb-1"),
            html.H4("—", id=component_id, className="mb-0"),
            html.P(scope_label, className="text-muted small mb-0 fst-italic") if scope_label else None,
        ],
        className="text-center px-2 py-2 h-100",
    )


def _card(title: str, child, icon: str = "fa-chart-bar"):
    return dbc.Card(
        [
            dbc.CardHeader([
                html.Span(_icon_glyph(icon), className="maintenance-icon me-2", **{"aria-hidden": "true"}),
                title,
            ]),
            dbc.CardBody(child),
        ],
        className="shadow-sm h-100",
    )


def layout_mantenciones_general():
    """Build the productive Mantenciones page.

    ``Actividad`` and ``Evidencia semanal`` remain mounted and disabled so
    their callback contracts and component IDs stay available for a future
    reactivation.  Only ``Resumen`` is exposed in the current product shell.
    """
    summary_tab = html.Div(
        [
            # The callback target remains mounted for backwards compatibility,
            # but period/source banners are intentionally not part of the
            # productive summary surface.
            html.Div(id="maintenance-month-status", style={"display": "none"}),
            dbc.Row(
                [
                    dbc.Col(create_kpi_card(t("tab_mantenciones_general.disponibilidad"), component_id="maintenance-kpi-availability-est", icon="fa-gauge-high", color="success"), md=3),
                    dbc.Col(create_kpi_card(t("tab_mantenciones_general.downtime"), component_id="maintenance-kpi-downtime-est", icon="fa-hourglass-half", color="danger"), md=3),
                    dbc.Col(create_kpi_card("MTBF", component_id="maintenance-kpi-mtbf-est", icon="fa-arrows-rotate", color="info"), md=3),
                    dbc.Col(create_kpi_card("MTTR", component_id="maintenance-kpi-mttr-est", icon="fa-screwdriver-wrench", color="warning"), md=3),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(_card(t("tab_mantenciones_general.tendencia_diaria_de_horas_equipo_fuera"), dcc.Graph(id="maintenance-chart-daily", config={"displayModeBar": False}, style={"height": "300px"}), "fa-chart-line"), md=6),
                    dbc.Col(_card(t("tab_mantenciones_general.equipos_intervenidos_por_dia"), dcc.Graph(id="maintenance-chart-daily-equipment", config={"displayModeBar": False}, style={"height": "300px"}), "fa-truck-loading"), md=6),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(_card(t("tab_mantenciones_general.mix_de_actividad_por_sistema"), dcc.Graph(id="maintenance-chart-system-mix", config={"displayModeBar": False}, style={"height": "340px"}), "fa-sitemap"), md=6),
                    dbc.Col(_card(t("tab_mantenciones_general.equipos_con_mayor_actividad"), dcc.Graph(id="maintenance-chart-equipment", config={"displayModeBar": False}, style={"height": "320px"}), "fa-truck-loading"), md=6),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(_card(html.Span(t("tab_mantenciones_general.pareto_de_actividad_de_mantenimiento_motor"), id="maintenance-chart-pareto-title"), dcc.Graph(id="maintenance-chart-pareto", config={"displayModeBar": False}, style={"height": "340px"}), "fa-chart-bar"), md=6),
                    dbc.Col(_card(html.Span(t("tab_mantenciones_general.pareto_de_actividad_de_mantenimiento_tren"), id="maintenance-chart-pareto-tren-fuerza-title"), dcc.Graph(id="maintenance-chart-pareto-tren-fuerza", config={"displayModeBar": False}, style={"height": "340px"}), "fa-chart-bar"), md=6),
                ],
                className="g-3 mb-4",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(t("tab_mantenciones_general.indicadores_de_interes"), className="fw-semibold"),
                            html.Span(t("tab_mantenciones_general.agregados_del_periodo_seleccionado"), className="text-muted small ms-2"),
                        ],
                        className="mb-2",
                    ),
                    dbc.Row(
                        [
                            dbc.Col(create_context_metric(t("tab_mantenciones_general.equipos_con_actividad"), "maintenance-kpi-equipment", "fa-truck", "info"), xs=6, md=2),
                            dbc.Col(create_context_metric(t("tab_mantenciones_general.acciones_registradas"), "maintenance-kpi-actions", "fa-wrench", "primary"), xs=6, md=2),
                            dbc.Col(create_context_metric(t("tab_mantenciones_general.registros"), "maintenance-kpi-records", "fa-clipboard-list", "success"), xs=6, md=2),
                            dbc.Col(create_context_metric(t("tab_mantenciones_general.sistemas_intervenidos"), "maintenance-kpi-systems", "fa-sitemap", "warning"), xs=6, md=2),
                            dbc.Col(create_context_metric(t("tab_mantenciones_general.dias_con_actividad"), "maintenance-kpi-days", "fa-calendar-day", "secondary", t("tab_mantenciones_general.fecha_operacional")), xs=6, md=2),
                            dbc.Col(create_context_metric(t("tab_mantenciones_general.actividad_en_motor"), "maintenance-kpi-motor-share", "fa-percentage", "danger", t("tab_mantenciones_general.de_acciones")), xs=6, md=2),
                        ],
                        className="g-1",
                    ),
                ],
                className="border rounded bg-white shadow-sm p-3",
            ),
            html.Div(
                _card(
                    t("tab_mantenciones_general.detalle_de_actividades_realizadas"),
                    html.Div(
                        [
                            html.P(
                                t("tab_mantenciones_general.hasta_250_actividades_del_periodo_para"),
                                className="text-muted small mb-3",
                            ),
                            html.Div(id="maintenance-summary-detail-table"),
                        ]
                    ),
                    "fa-clipboard-list",
                ),
                className="mt-4",
            ),
        ]
    )

    activity_tab = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col([html.Label(t("alerts_general.filter_system"), className="small text-muted"), dcc.Dropdown(id="maintenance-activity-system", multi=True, placeholder=t("tab_telemetry_fleet.todos_los_sistemas"))], md=4),
                    dbc.Col([html.Label(t("tab_mantenciones_general.subsistema"), className="small text-muted"), dcc.Dropdown(id="maintenance-activity-subsystem", multi=True, placeholder=t("tab_mantenciones_general.todos_los_subsistemas"))], md=4),
                    dbc.Col([html.Label(t("tab_mantenciones_general.equipo"), className="small text-muted"), dcc.Dropdown(id="maintenance-activity-equipment", multi=True, placeholder=t("tab_mantenciones_general.todos_los_equipos"))], md=4),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row([dbc.Col(_card(t("tab_mantenciones_general.matriz_de_acciones_por_equipo_y"), dcc.Graph(id="maintenance-chart-matrix", config={"displayModeBar": False}, style={"height": "420px"}), "fa-th"), md=12)], className="g-3 mb-4"),
            _card(t("tab_mantenciones_general.detalle_de_acciones_registradas"), html.Div(id="maintenance-activity-table"), "fa-table"),
        ]
    )

    weekly_tab = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col([html.Label(t("tab_mantenciones_general.equipo"), className="small text-muted"), dcc.Dropdown(id="maintenance-week-equipment", multi=True, placeholder=t("tab_mantenciones_general.todos_los_equipos"))], md=6),
                ],
                className="g-3 mb-4",
            ),
            html.Div(id="maintenance-week-status"),
            dbc.Row([dbc.Col(_card(t("tab_mantenciones_general.resumen_semanal_por_equipo"), html.Div(id="maintenance-week-summary-table"), "fa-comment-alt"), md=12)], className="g-3 mb-4"),
            dbc.Row([dbc.Col(_card(t("tab_mantenciones_general.actividades_por_dia_y_sistema"), html.Div(id="maintenance-week-task-table"), "fa-calendar-week"), md=12)], className="g-3"),
        ]
    )

    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H2([html.Span("◆", className="maintenance-icon me-2", **{"aria-hidden": "true"}), t("tab_mantenciones_general.informe_de_confiabilidad")]),
                            html.P(t("tab_mantenciones_general.resumen_ejecutivo_horas_fuera_de_servicio"), className="text-muted mb-0"),
                        ],
                        md=7,
                    ),
                    dbc.Col(
                        dbc.Button([html.I(className="fas fa-sync-alt me-2"), t("tab_mantenciones_general.refrescar")], id="btn-refresh-maintenance", color="primary"),
                        md=5,
                        className="d-flex justify-content-end align-items-center",
                    ),
                ],
                className="mb-3",
            ),
            html.Div(id="maintenance-source-alert", style={"display": "none"}),
            dbc.Row(
                [
                    dbc.Col([html.Label(t("tab_mantenciones_general.mes_de_analisis"), className="small text-muted"), dcc.Dropdown(id="maintenance-month", clearable=False, placeholder=t("tab_mantenciones_general.seleccione_un_mes"))], md=4),
                    dbc.Col([html.Label(t("tab_mantenciones_general.flota_tipo_de_equipo"), className="small text-muted"), dcc.Dropdown(id="maintenance-summary-fleet", multi=True, value=[], placeholder=t("tab_mantenciones_general.todas_las_flotas")), html.Small(t("tab_mantenciones_general.catalogo_de_tribologia_sin_coincidencia_ot"), className="text-muted")], md=4),
                    dbc.Col([html.Label(t("alerts_general.filter_unit"), className="small text-muted"), dcc.Dropdown(id="maintenance-summary-equipment", clearable=False, options=[{"label": t("tab_health_index.todas"), "value": "__all__"}], value="__all__", placeholder=t("tab_health_index.todas"))], md=4),
                    # The weekly selector remains mounted for its disabled tab's
                    # callback contract, but is intentionally not exposed while
                    # Evidencia semanal is hidden from the product shell.
                    dbc.Col([html.Label(t("tab_mantenciones_general.semana_de_evidencia"), className="small text-muted"), dcc.Dropdown(id="maintenance-week", clearable=False, placeholder=t("tab_mantenciones_general.seleccione_una_semana"))], md=6, style={"display": "none"}),
                ],
                className="g-3 mb-4",
            ),
            dcc.Store(id="maintenance-metadata-store"),
            dcc.Store(id="maintenance-monthly-store"),
            dcc.Store(id="maintenance-weekly-store"),
            dcc.Store(id="maintenance-load-timestamp"),
            dcc.Tabs(
                id="maintenance-tabs",
                value="summary",
                children=[
                    dcc.Tab(label=t("tab_mantenciones_general.informe_de_confiabilidad"), value="summary", children=summary_tab, className="pt-3"),
                    # Keep the future views mounted for callback/layout
                    # compatibility, but do not expose them in the product
                    # shell until their next UX iteration is approved.
                    dcc.Tab(
                        label=t("tab_mantenciones_general.actividad"),
                        value="activity",
                        children=activity_tab,
                        className="pt-3",
                        disabled=True,
                        style={"display": "none"},
                    ),
                    dcc.Tab(
                        label=t("tab_mantenciones_general.evidencia_semanal"),
                        value="weekly",
                        children=weekly_tab,
                        className="pt-3",
                        disabled=True,
                        style={"display": "none"},
                    ),
                ],
            ),
        ],
        className="p-4",
    )


def create_empty_figure(message: str | None = None) -> go.Figure:
    if message is None:
        message = t("mantenciones.no_data_for_period")
    fig = go.Figure()
    fig.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font={"size": 14, "color": "#6c757d"})
    fig.update_layout(template="plotly_white", xaxis={"visible": False}, yaxis={"visible": False}, margin={"l": 20, "r": 20, "t": 20, "b": 20})
    return fig


def create_daily_activity_chart(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return create_empty_figure()
    fig = go.Figure(go.Scatter(x=df["date"], y=df["count"], mode="lines+markers", name=t("tab_mantenciones_general.acciones"), line={"color": "#2f80ed", "width": 3}, marker={"size": 7}, fill="tozeroy", fillcolor="rgba(47,128,237,0.12)"))
    fig.update_layout(template="plotly_white", xaxis_title=t("tab_mantenciones_general.fecha_operacional_2"), yaxis_title=t("tab_mantenciones_general.acciones"), hovermode="x unified", margin={"l": 45, "r": 20, "t": 20, "b": 45})
    return fig


def create_daily_intervention_hours_chart(df: pd.DataFrame) -> go.Figure:
    """Render source-defined daily equipment out-of-service hours."""
    if df.empty:
        return create_empty_figure(t("tab_mantenciones_general.sin_horas_de_equipo_fuera_de"))
    # This is a time series, so it keeps operational-date order rather than
    # being ranked by value like the categorical activity charts below.
    data = df.sort_values("date", kind="mergesort").copy()
    if "hours_out_of_service" not in data.columns:
        return create_empty_figure(t("tab_mantenciones_general.la_fuente_no_trae_intervalos_de"))
    hours = pd.to_numeric(data["hours_out_of_service"], errors="coerce")
    if hours.notna().sum() == 0:
        return create_empty_figure(t("tab_mantenciones_general.la_fuente_no_trae_intervalos_de"))
    fig = go.Figure(
        go.Bar(
            x=data["date"],
            y=hours,
            orientation="v",
            name=t("tab_mantenciones_general.horas_equipo_fuera_de_servicio"),
            marker_color="#6f8fb3",
            hovertemplate=t("tab_mantenciones_general.b_b_br_horas_equipo_fuera"),
        )
    )
    fig.update_yaxes(title_text=t("tab_mantenciones_general.horas_equipo_fuera_de_servicio"), rangemode="tozero")
    fig.update_xaxes(title_text=t("tab_mantenciones_general.fecha_operacional_2"))
    fig.update_layout(
        template="plotly_white",
        margin={"l": 55, "r": 25, "t": 25, "b": 48},
        showlegend=False,
    )
    return fig


def create_daily_equipment_chart(df: pd.DataFrame) -> go.Figure:
    """Render the daily count of distinct equipment with an intervention."""
    if df.empty:
        return create_empty_figure(t("tab_mantenciones_general.sin_equipos_intervenidos_por_dia"))
    if "equipment_count" not in df.columns:
        return create_empty_figure(t("tab_mantenciones_general.sin_equipos_intervenidos_por_dia"))
    fig = go.Figure(
        go.Scatter(
            x=df["date"],
            y=df["equipment_count"],
            mode="lines+markers",
            name=t("tab_mantenciones_general.equipos_intervenidos"),
            line={"color": "#4f8a8b", "width": 3},
            marker={"color": "#4f8a8b", "size": 7},
            fill="tozeroy",
            fillcolor="rgba(79,138,139,0.14)",
            hovertemplate=t("tab_mantenciones_general.b_b_br_equipos_intervenidos_extra"),
        )
    )
    fig.update_layout(
        template="plotly_white",
        xaxis_title=t("tab_mantenciones_general.fecha_operacional_2"),
        yaxis_title=t("tab_mantenciones_general.equipos_intervenidos"),
        yaxis={"rangemode": "tozero", "tick0": 0, "dtick": 5},
        margin={"l": 55, "r": 25, "t": 25, "b": 48},
        showlegend=False,
    )
    return fig


def create_equipment_pareto_chart(df: pd.DataFrame, system_label: str | None = None) -> go.Figure:
    if system_label is None:
        system_label = t("mantenciones.system_engine")
    if df.empty:
        return create_empty_figure(t("tab_mantenciones_general.sin_actividad_de_por_equipo", system_label=system_label))
    # ``system_name`` is accepted as a compatibility fallback for cached
    # payloads from the previous contract; new payloads use ``equipment``.
    dimension = "equipment" if "equipment" in df.columns else "system_name"
    df = df.sort_values(["count", dimension], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    counts = pd.to_numeric(df["count"], errors="coerce").fillna(0)
    total = counts.sum()
    df["cumulative_pct"] = counts.cumsum() / total * 100 if total else 0.0
    if not df.empty and total:
        df.loc[df.index[-1], "cumulative_pct"] = 100.0
    dimension_values = df[dimension].astype(str)
    dimension_colors = _equipment_color_map(dimension_values) if dimension == "equipment" else _system_color_map(dimension_values)
    dimension_title = t("tab_mantenciones_general.equipo") if dimension == "equipment" else t("alerts_general.filter_system")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=df[dimension],
            y=df["count"],
            orientation="v",
            name=t("tab_mantenciones_general.acciones_2", system_label=system_label),
            marker_color=[dimension_colors[str(value)] for value in df[dimension]],
            text=df["count"].astype(int),
            textposition="outside",
            cliponaxis=False,
            hovertemplate=t("tab_mantenciones_general.b_b_br_acciones_extra_extra", system_label=system_label),
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=df[dimension],
            y=df["cumulative_pct"],
            name=t("tab_mantenciones_general.acumulado"),
            mode="lines",
            line={"color": PARETO_LINE_COLOR, "width": 2},
            hovertemplate=t("tab_mantenciones_general.b_b_br_acumulado_extra_extra"),
        ),
        secondary_y=True,
    )
    fig.update_yaxes(title_text=t("tab_mantenciones_general.acciones"), rangemode="tozero", secondary_y=False)
    fig.update_yaxes(title_text=t("tab_mantenciones_general.acumulado"), range=[0, 100], ticksuffix="%", secondary_y=True)
    fig.update_xaxes(title_text=dimension_title, tickangle=-35)
    fig.update_layout(
        template="plotly_white",
        showlegend=True,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        margin={"l": 45, "r": 45, "t": 48, "b": 85},
        hovermode="x unified",
    )
    return fig


# Compatibility alias for callers importing the previous builder name.
create_system_pareto_chart = create_equipment_pareto_chart


def create_system_activity_chart(df: pd.DataFrame, include_all_systems: bool = False) -> go.Figure:
    """Render recorded action volume by system, not failure frequency."""
    if df.empty:
        return create_empty_figure(t("tab_mantenciones_general.sin_actividad_por_sistema"))
    data = df.copy()
    if not include_all_systems:
        data = data.loc[~data["system_name"].map(_is_excluded_activity_system)].copy()
    if data.empty:
        return create_empty_figure(t("tab_mantenciones_general.sin_sistemas_elegibles_para_este_periodo"))
    data = (
        data.groupby("system_name", as_index=False)["count"]
        .sum()
        .sort_values(["count", "system_name"], ascending=[False, True], kind="mergesort")
        .reset_index(drop=True)
    )
    palette = _system_color_map(data["system_name"])
    fig = go.Figure(
        go.Bar(
            x=data["system_name"],
            y=data["count"],
            orientation="v",
            name=t("tab_mantenciones_general.acciones_registradas"),
            marker_color=[palette[str(system)] for system in data["system_name"]],
            text=data["count"].astype(int),
            textposition="outside",
            cliponaxis=False,
            hovertemplate=t("tab_mantenciones_general.b_b_br_acciones_unicas_extra"),
        )
    )
    fig.update_layout(
        template="plotly_white",
        xaxis_title=t("alerts_general.filter_system"),
        yaxis_title=t("tab_mantenciones_general.acciones_unicas"),
        margin={"l": 45, "r": 20, "t": 20, "b": 85},
        showlegend=False,
    )
    fig.update_xaxes(tickangle=-35, automargin=True, tickfont={"size": 10})
    return fig


def create_equipment_activity_chart(df: pd.DataFrame, include_all_systems: bool = False) -> go.Figure:
    if df.empty:
        return create_empty_figure(t("tab_mantenciones_general.sin_actividad_por_equipo"))

    # Detailed equipment × system data enables a stacked vertical chart:
    # equipment remain the x-axis entities while systems become the
    # color/legend categories.
    if "system_name" in df.columns:
        raw = df.copy()
        raw["machine_code"] = raw["machine_code"].astype(str)
        eligible = raw.copy()
        if not include_all_systems:
            eligible = eligible.loc[~eligible["system_name"].map(_is_excluded_activity_system)].copy()
        if eligible.empty:
            return create_empty_figure(t("tab_mantenciones_general.sin_sistemas_elegibles_para_este_periodo"))
        # Rank only the systems actually shown; the x-axis then reads
        # left-to-right from highest to lowest total activity.
        equipment_totals = (
            eligible.groupby("machine_code", as_index=False)["count"]
            .sum()
            .sort_values(["count", "machine_code"], ascending=[False, True], kind="mergesort")
            .reset_index(drop=True)
        )
        equipment = equipment_totals["machine_code"].tolist()
        systems = sorted(eligible["system_name"].dropna().astype(str).unique().tolist())
        pivot = eligible.pivot_table(
            index="machine_code", columns="system_name", values="count", aggfunc="sum", fill_value=0
        ).reindex(index=equipment, columns=systems, fill_value=0).fillna(0)
        palette = _system_color_map(systems)
        fig = go.Figure()
        for index, system in enumerate(systems):
            values = pivot[system].astype(int)
            fig.add_trace(
                go.Bar(
                    x=equipment,
                    y=values,
                    orientation="v",
                    name=system,
                    marker_color=palette[system],
                    customdata=values,
                    hovertemplate=t("tab_mantenciones_general.b_b_br_sistema_br_acciones", system=system),
                )
            )
        fig.update_layout(
            template="plotly_white",
            barmode="stack",
            xaxis_title=t("tab_mantenciones_general.equipo"),
            yaxis_title=t("tab_mantenciones_general.acciones"),
            margin={"l": 55, "r": 30, "t": 45, "b": 90},
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        )
        fig.update_xaxes(categoryorder="array", categoryarray=equipment, tickangle=-35, automargin=True)
        return fig

    data = df.copy()
    data["machine_code"] = data["machine_code"].astype(str)
    data = data.sort_values(["count", "machine_code"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    systems = data.get("primary_system", pd.Series("Sin sistema", index=data.index)).fillna("Sin sistema").astype(str)
    palette = _system_color_map(systems)
    fig = go.Figure(
        go.Bar(
            x=data["machine_code"],
            y=data["count"],
            orientation="v",
            marker_color=[palette[str(system)] for system in systems],
            text=data["count"].astype(int),
            textposition="outside",
            cliponaxis=False,
            customdata=systems,
            hovertemplate=t("tab_mantenciones_general.b_b_br_sistema_predominante_br"),
        )
    )
    fig.update_layout(template="plotly_white", xaxis_title=t("tab_mantenciones_general.equipo"), yaxis_title=t("tab_mantenciones_general.acciones"), margin={"l": 55, "r": 30, "t": 20, "b": 90}, showlegend=False)
    fig.update_xaxes(categoryorder="array", categoryarray=data["machine_code"].tolist(), tickangle=-35, automargin=True)
    return fig


def _confidence_label(value) -> str:
    return t("tab_mantenciones_general.confianza_baja") if bool(value) else t("tab_mantenciones_general.confianza_suficiente")


def create_reliability_mtbf_mttf_chart(df: pd.DataFrame) -> go.Figure:
    """Render monthly MTBF/MTTF, preserving missing values and confidence flags."""
    required = {"year_month", "machine_code", "mtbf_hours", "mttf_hours"}
    if df.empty or not required.issubset(df.columns):
        return create_empty_figure(t("tab_mantenciones_general.sin_datos_suficientes_de_mtbf_mttf"))
    data = df.copy()
    data["machine_code"] = data["machine_code"].astype(str)
    data = data.sort_values(["year_month", "machine_code"], kind="mergesort")
    fig = go.Figure()
    palette = _equipment_color_map(data["machine_code"])
    traces = 0
    low_without_value_months = set()
    for equipment in sorted(data["machine_code"].unique()):
        equipment_rows = data[data["machine_code"].eq(equipment)]
        for metric, label, dash in (("mtbf_hours", "MTBF", "solid"), ("mttf_hours", "MTTF", "dash")):
            values = pd.to_numeric(equipment_rows[metric], errors="coerce")
            valid = values.notna()
            if not valid.any():
                continue
            confidence = equipment_rows.get("low_confidence", pd.Series(False, index=equipment_rows.index)).fillna(False).astype(bool)
            customdata = confidence.map(_confidence_label)
            fig.add_trace(
                go.Scatter(
                    x=equipment_rows.loc[valid, "year_month"],
                    y=values.loc[valid],
                    mode="lines+markers",
                    name=f"{equipment} · {label}",
                    legendgroup=equipment,
                    line={"color": palette[equipment], "dash": dash, "width": 2},
                    marker={"color": palette[equipment], "size": 7},
                    customdata=customdata.loc[valid].tolist(),
                    hovertemplate=t("tab_mantenciones_general.b_b_br_equipo_br_h", equipment=equipment, label=label),
                )
            )
            low = valid & confidence
            if low.any():
                fig.add_trace(
                    go.Scatter(
                        x=equipment_rows.loc[low, "year_month"],
                        y=values.loc[low],
                        mode="markers",
                        name=t("tab_mantenciones_general.baja_confianza", equipment=equipment, label=label),
                        legendgroup=equipment,
                        showlegend=False,
                        marker={"color": palette[equipment], "symbol": "diamond-open", "size": 12, "line": {"width": 2}},
                        hovertemplate=t("tab_mantenciones_general.b_b_br_equipo_br_h_2", equipment=equipment, label=label),
                    )
                )
            low_without_value_months.update(
                equipment_rows.loc[confidence & ~valid, "year_month"].astype(str).tolist()
            )
            traces += 1
    if not traces:
        return create_empty_figure(t("tab_mantenciones_general.sin_datos_suficientes_de_mtbf_mttf"))
    for month in sorted(low_without_value_months):
        fig.add_annotation(
            x=month,
            y=1.02,
            yref="paper",
            text="⚠",
            showarrow=False,
            font={"color": "#b7791f", "size": 16},
            hovertext=t("tab_mantenciones_general.confianza_baja_mtbf_mttf_sin_dato"),
        )
    fig.update_layout(
        template="plotly_white",
        title=t("tab_mantenciones_general.mtbf_y_mttf_mensual_por_equipo"),
        xaxis_title=t("tab_mantenciones_general.mes"),
        yaxis_title=t("tab_mantenciones_general.horas"),
        hovermode="x unified",
        margin={"l": 55, "r": 30, "t": 55, "b": 48},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    )
    fig.update_yaxes(rangemode="tozero")
    return fig


def create_reliability_mttr_downtime_chart(df: pd.DataFrame) -> go.Figure:
    """Render monthly MTTR and total downtime with a secondary hours axis."""
    required = {"year_month", "machine_code", "mttr_hours", "total_downtime_hours"}
    if df.empty or not required.issubset(df.columns):
        return create_empty_figure(t("tab_mantenciones_general.sin_datos_suficientes_de_mttr_downtime"))
    data = df.copy()
    data["machine_code"] = data["machine_code"].astype(str)
    data = data.sort_values(["year_month", "machine_code"], kind="mergesort")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    palette = _equipment_color_map(data["machine_code"])
    traces = 0
    for equipment in sorted(data["machine_code"].unique()):
        rows = data[data["machine_code"].eq(equipment)]
        color = palette[equipment]
        downtime = pd.to_numeric(rows["total_downtime_hours"], errors="coerce")
        if downtime.notna().any():
            fig.add_trace(
                go.Bar(
                    x=rows["year_month"], y=downtime, name=t("tab_mantenciones_general.downtime_2", equipment=equipment),
                    legendgroup=equipment, marker_color=color,
                    hovertemplate=t("tab_mantenciones_general.b_b_br_equipo_br_downtime", equipment=equipment),
                ),
                secondary_y=True,
            )
            traces += 1
        mttr = pd.to_numeric(rows["mttr_hours"], errors="coerce")
        valid = mttr.notna()
        if valid.any():
            confidence = rows.get("low_confidence", pd.Series(False, index=rows.index)).fillna(False).astype(bool)
            fig.add_trace(
                go.Scatter(
                    x=rows.loc[valid, "year_month"], y=mttr.loc[valid], mode="lines+markers",
                    name=t("tab_mantenciones_general.mttr", equipment=equipment), legendgroup=equipment,
                    line={"color": color, "width": 2}, marker={"color": color, "size": 7},
                    hovertemplate=t("tab_mantenciones_general.b_b_br_equipo_br_mttr", equipment=equipment),
                    customdata=[_confidence_label(value) for value in confidence.loc[valid]],
                ),
                secondary_y=False,
            )
            low = valid & confidence
            if low.any():
                fig.add_trace(
                    go.Scatter(
                        x=rows.loc[low, "year_month"], y=mttr.loc[low], mode="markers",
                        name=t("tab_mantenciones_general.mttr_baja_confianza", equipment=equipment), legendgroup=equipment,
                        showlegend=False,
                        marker={"color": color, "symbol": "diamond-open", "size": 12, "line": {"width": 2}},
                        hovertemplate=t("tab_mantenciones_general.b_b_br_equipo_br_mttr_2", equipment=equipment),
                    ),
                    secondary_y=False,
                )
            traces += 1
    if not traces:
        return create_empty_figure(t("tab_mantenciones_general.sin_datos_suficientes_de_mttr_downtime"))
    fig.update_layout(
        template="plotly_white",
        title=t("tab_mantenciones_general.mttr_y_downtime_mensual_por_equipo"),
        xaxis_title=t("tab_mantenciones_general.mes"),
        hovermode="x unified",
        barmode="group",
        margin={"l": 55, "r": 55, "t": 55, "b": 48},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    )
    fig.update_yaxes(title_text=t("tab_mantenciones_general.mttr_h"), rangemode="tozero", secondary_y=False)
    fig.update_yaxes(title_text=t("tab_mantenciones_general.downtime_total_h"), rangemode="tozero", secondary_y=True)
    return fig


def create_activity_matrix(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return create_empty_figure(t("tab_mantenciones_general.sin_actividad_para_la_matriz"))
    matrix = df.pivot(index="machine_code", columns="system_name", values="count").fillna(0)
    fig = go.Figure(go.Heatmap(z=matrix.values, x=matrix.columns.tolist(), y=matrix.index.tolist(), colorscale="Blues", hovertemplate=t("tab_mantenciones_general.equipo_br_sistema_br_acciones_extra")))
    fig.update_layout(template="plotly_white", xaxis_title=t("alerts_general.filter_system"), yaxis_title=t("tab_mantenciones_general.equipo"), margin={"l": 65, "r": 20, "t": 20, "b": 100})
    return fig


def create_component_failure_table(data):
    return _table(
        data,
        [
            ("machine_code", t("tab_mantenciones_general.equipo")),
            ("component_name", t("tab_mantenciones_general.componente")),
            ("n_failure_records", t("tab_mantenciones_general.registros_de_falla")),
            ("n_failure_actions", t("tab_mantenciones_general.acciones_de_falla")),
        ],
        t("tab_mantenciones_general.sin_componentes_con_fallas_para_los"),
        page_size=12,
    )


def _table(data, columns, empty_message: str, page_size: int = 12):
    if not data:
        return html.P(empty_message, className="text-muted text-center p-3")
    return dash_table.DataTable(
        data=data,
        columns=[{"name": label, "id": key} for key, label in columns],
        page_size=page_size,
        sort_action="native",
        filter_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "left", "padding": "8px", "fontSize": "13px", "maxWidth": "420px", "whiteSpace": "normal"},
        style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"},
        style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#f8f9fa"}],
    )


def create_activity_table(data):
    return _table(
        data,
        [("date", t("tab_mantenciones_general.fecha")), ("timestamp_utc", t("tab_mantenciones_general.timestamp_utc")), ("equipment", t("tab_mantenciones_general.equipo")), ("system_name", t("alerts_general.filter_system")), ("subsystem_name", t("tab_mantenciones_general.subsistema")), ("action_type", t("tab_mantenciones_general.tipo_de_accion")), ("detail", t("tab_mantenciones_general.detalle"))],
        t("tab_mantenciones_general.sin_acciones_para_los_filtros_seleccionado"),
        page_size=15,
    )


def create_week_summary_table(data):
    return _table(data, [("equipment", t("tab_mantenciones_general.equipo")), ("summary", t("tab_mantenciones_general.resumen"))], t("tab_mantenciones_general.sin_resumen_semanal_disponible"), page_size=11)


def create_week_task_table(data):
    return _table(data, [("equipment", t("tab_mantenciones_general.equipo")), ("day", t("tab_mantenciones_general.dia")), ("system_name", t("alerts_general.filter_system")), ("task", t("tab_mantenciones_general.actividad"))], t("tab_mantenciones_general.sin_tareas_estructuradas_para_esta_semana"), page_size=15)


# Compatibility aliases for callers that still import the old chart helpers.
create_downtime_trend_chart = create_daily_activity_chart


def create_detentions_table(df_detentions: pd.DataFrame):
    return _table(df_detentions.to_dict("records"), [(c, c) for c in df_detentions.columns], t("tab_mantenciones_general.sin_registros"), page_size=10)


def create_jobs_table(df_jobs: pd.DataFrame):
    return _table(df_jobs.to_dict("records"), [(c, c) for c in df_jobs.columns], t("tab_mantenciones_general.sin_acciones"), page_size=10)
