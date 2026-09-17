"""Productive Mantenciones view.

The page keeps the auditable activity breakdown from the client reports and
adds clearly labelled ESTIMADO reliability proxies. The proxies are derived
from action activity only; they are never presented as measured downtime or
failure metrics.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import dash_table, dcc, html
import dash_bootstrap_components as dbc


PARETO_BAR_COLOR = "#355c7d"
PARETO_LINE_COLOR = "#d08c60"

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
                    dbc.Col(create_kpi_card("Disponibilidad", component_id="maintenance-kpi-availability-est", icon="fa-gauge-high", color="success"), md=3),
                    dbc.Col(create_kpi_card("Downtime", component_id="maintenance-kpi-downtime-est", icon="fa-hourglass-half", color="danger"), md=3),
                    dbc.Col(create_kpi_card("MTBF", component_id="maintenance-kpi-mtbf-est", icon="fa-arrows-rotate", color="info"), md=3),
                    dbc.Col(create_kpi_card("MTTR", component_id="maintenance-kpi-mttr-est", icon="fa-screwdriver-wrench", color="warning"), md=3),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(_card("Pareto de actividad de mantenimiento · Motor por equipo", dcc.Graph(id="maintenance-chart-pareto", config={"displayModeBar": False}, style={"height": "360px"}), "fa-chart-bar"), md=7),
                    dbc.Col(_card("Tendencia diaria de acciones", dcc.Graph(id="maintenance-chart-daily", config={"displayModeBar": False}, style={"height": "360px"}), "fa-chart-line"), md=5),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        _card(
                            "Pareto de actividad de mantenimiento · Tren de Fuerza por equipo",
                            dcc.Graph(id="maintenance-chart-pareto-tren-fuerza", config={"displayModeBar": False}, style={"height": "360px"}),
                            "fa-chart-bar",
                        ),
                        md=7,
                    ),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(_card("Mix de actividad por sistema", dcc.Graph(id="maintenance-chart-system-mix", config={"displayModeBar": False}, style={"height": "340px"}), "fa-sitemap"), md=6),
                    dbc.Col(_card("Equipos con mayor actividad", dcc.Graph(id="maintenance-chart-equipment", config={"displayModeBar": False}, style={"height": "320px"}), "fa-truck-loading"), md=6),
                ],
                className="g-3 mb-4",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span("Indicadores de Interés", className="fw-semibold"),
                            html.Span("Agregados del período seleccionado", className="text-muted small ms-2"),
                        ],
                        className="mb-2",
                    ),
                    dbc.Row(
                        [
                            dbc.Col(create_context_metric("Equipos con actividad", "maintenance-kpi-equipment", "fa-truck", "info"), xs=6, md=2),
                            dbc.Col(create_context_metric("Acciones registradas", "maintenance-kpi-actions", "fa-wrench", "primary"), xs=6, md=2),
                            dbc.Col(create_context_metric("Registros", "maintenance-kpi-records", "fa-clipboard-list", "success"), xs=6, md=2),
                            dbc.Col(create_context_metric("Sistemas intervenidos", "maintenance-kpi-systems", "fa-sitemap", "warning"), xs=6, md=2),
                            dbc.Col(create_context_metric("Días con actividad", "maintenance-kpi-days", "fa-calendar-day", "secondary", "fecha operacional"), xs=6, md=2),
                            dbc.Col(create_context_metric("Actividad en Motor", "maintenance-kpi-motor-share", "fa-percentage", "danger", "% de acciones"), xs=6, md=2),
                        ],
                        className="g-1",
                    ),
                ],
                className="border rounded bg-white shadow-sm p-3",
            ),
        ]
    )

    activity_tab = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col([html.Label("Sistema", className="small text-muted"), dcc.Dropdown(id="maintenance-activity-system", multi=True, placeholder="Todos los sistemas")], md=4),
                    dbc.Col([html.Label("Subsistema", className="small text-muted"), dcc.Dropdown(id="maintenance-activity-subsystem", multi=True, placeholder="Todos los subsistemas")], md=4),
                    dbc.Col([html.Label("Equipo", className="small text-muted"), dcc.Dropdown(id="maintenance-activity-equipment", multi=True, placeholder="Todos los equipos")], md=4),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row([dbc.Col(_card("Matriz de acciones por equipo y sistema", dcc.Graph(id="maintenance-chart-matrix", config={"displayModeBar": False}, style={"height": "420px"}), "fa-th"), md=12)], className="g-3 mb-4"),
            _card("Detalle de acciones registradas", html.Div(id="maintenance-activity-table"), "fa-table"),
        ]
    )

    weekly_tab = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col([html.Label("Equipo", className="small text-muted"), dcc.Dropdown(id="maintenance-week-equipment", multi=True, placeholder="Todos los equipos")], md=6),
                ],
                className="g-3 mb-4",
            ),
            html.Div(id="maintenance-week-status"),
            dbc.Row([dbc.Col(_card("Resumen semanal por equipo", html.Div(id="maintenance-week-summary-table"), "fa-comment-alt"), md=12)], className="g-3 mb-4"),
            dbc.Row([dbc.Col(_card("Actividades por día y sistema", html.Div(id="maintenance-week-task-table"), "fa-calendar-week"), md=12)], className="g-3"),
        ]
    )

    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H2([html.Span("◆", className="maintenance-icon me-2", **{"aria-hidden": "true"}), "Mantenciones"]),
                            html.P("Resumen ejecutivo · confiabilidad estimada y actividad de mantenimiento", className="text-muted mb-0"),
                        ],
                        md=7,
                    ),
                    dbc.Col(
                        dbc.Button([html.I(className="fas fa-sync-alt me-2"), "Refrescar"], id="btn-refresh-maintenance", color="primary"),
                        md=5,
                        className="d-flex justify-content-end align-items-center",
                    ),
                ],
                className="mb-3",
            ),
            html.Div(id="maintenance-source-alert", style={"display": "none"}),
            dbc.Row(
                [
                    dbc.Col([html.Label("Mes de análisis", className="small text-muted"), dcc.Dropdown(id="maintenance-month", clearable=False, placeholder="Seleccione un mes")], md=12),
                    # The weekly selector remains mounted for its disabled tab's
                    # callback contract, but is intentionally not exposed while
                    # Evidencia semanal is hidden from the product shell.
                    dbc.Col([html.Label("Semana de evidencia", className="small text-muted"), dcc.Dropdown(id="maintenance-week", clearable=False, placeholder="Seleccione una semana")], md=6, style={"display": "none"}),
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
                    dcc.Tab(label="Resumen", value="summary", children=summary_tab, className="pt-3"),
                    # Keep the future views mounted for callback/layout
                    # compatibility, but do not expose them in the product
                    # shell until their next UX iteration is approved.
                    dcc.Tab(
                        label="Actividad",
                        value="activity",
                        children=activity_tab,
                        className="pt-3",
                        disabled=True,
                        style={"display": "none"},
                    ),
                    dcc.Tab(
                        label="Evidencia semanal",
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


def create_empty_figure(message: str = "Sin datos para este período") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font={"size": 14, "color": "#6c757d"})
    fig.update_layout(template="plotly_white", xaxis={"visible": False}, yaxis={"visible": False}, margin={"l": 20, "r": 20, "t": 20, "b": 20})
    return fig


def create_daily_activity_chart(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return create_empty_figure()
    fig = go.Figure(go.Scatter(x=df["date"], y=df["count"], mode="lines+markers", name="Acciones", line={"color": "#2f80ed", "width": 3}, marker={"size": 7}, fill="tozeroy", fillcolor="rgba(47,128,237,0.12)"))
    fig.update_layout(template="plotly_white", xaxis_title="Fecha operacional", yaxis_title="Acciones", hovermode="x unified", margin={"l": 45, "r": 20, "t": 20, "b": 45})
    return fig


def create_equipment_pareto_chart(df: pd.DataFrame, system_label: str = "Motor") -> go.Figure:
    if df.empty:
        return create_empty_figure(f"Sin actividad de {system_label} por equipo")
    # ``system_name`` is accepted as a compatibility fallback for cached
    # payloads from the previous contract; new payloads use ``equipment``.
    dimension = "equipment" if "equipment" in df.columns else "system_name"
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=df[dimension],
            y=df["count"],
            name=f"Acciones {system_label}",
            marker_color=PARETO_BAR_COLOR,
            text=df["count"].astype(int),
            textposition="outside",
            cliponaxis=False,
            hovertemplate=f"<b>%{{x}}</b><br>Acciones {system_label}: %{{y}}<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=df[dimension],
            y=df["cumulative_pct"],
            name="% acumulado",
            mode="lines+markers",
            line={"color": PARETO_LINE_COLOR, "width": 2},
            marker={"color": PARETO_LINE_COLOR},
            hovertemplate="<b>%{x}</b><br>Acumulado: %{y:.1f}%<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.update_yaxes(title_text="Acciones", rangemode="tozero", secondary_y=False)
    fig.update_yaxes(title_text="% acumulado", range=[0, 100], ticksuffix="%", secondary_y=True)
    fig.update_xaxes(title_text="Equipo", tickangle=-35)
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


def create_system_activity_chart(df: pd.DataFrame) -> go.Figure:
    """Render recorded action volume by system, not failure frequency."""
    if df.empty:
        return create_empty_figure("Sin actividad por sistema")
    if "equipment" in df.columns:
        data = df.loc[~df["system_name"].map(_is_excluded_activity_system)].copy()
        if data.empty:
            return create_empty_figure("Sin sistemas elegibles para este período")
        systems = (
            data.groupby("system_name", as_index=False)["count"]
            .sum()
            .sort_values(["count", "system_name"], ascending=[False, True])["system_name"]
            .tolist()
        )
        equipment = sorted(data["equipment"].dropna().astype(str).unique().tolist())
        pivot = data.pivot_table(index="system_name", columns="equipment", values="count", aggfunc="sum", fill_value=0).reindex(systems)
        palette = ["#355c7d", "#4f8a8b", "#d08c60", "#7b6ea8", "#6f8fb3", "#b56b78", "#5f9e7a", "#9a7b4f", "#778899", "#c47f3f", "#5b6d8a"]
        fig = go.Figure()
        for index, unit in enumerate(equipment):
            values = pivot[unit] if unit in pivot.columns else [0] * len(systems)
            fig.add_trace(
                go.Bar(
                    x=systems,
                    y=values,
                    name=unit,
                    marker_color=palette[index % len(palette)],
                    hovertemplate=f"<b>%{{x}}</b><br>Equipo: {unit}<br>Acciones: %{{y}}<extra></extra>",
                )
            )
        fig.update_layout(
            template="plotly_white",
            barmode="stack",
            xaxis_title="Sistema",
            yaxis_title="Acciones únicas",
            margin={"l": 45, "r": 20, "t": 20, "b": 115},
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        )
        fig.update_xaxes(tickangle=-35, automargin=True, tickfont={"size": 10})
        return fig
    data = df.loc[~df["system_name"].map(_is_excluded_activity_system)].copy()
    if data.empty:
        return create_empty_figure("Sin sistemas elegibles para este período")
    data = data.sort_values(["count", "system_name"], ascending=[False, True])
    fig = go.Figure(
        go.Bar(
            x=data["system_name"],
            y=data["count"],
            name="Acciones registradas",
            marker_color="#6f8fb3",
            text=data["count"].astype(int),
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig.update_layout(
        template="plotly_white",
        xaxis_title="Sistema",
        yaxis_title="Acciones únicas",
        margin={"l": 45, "r": 20, "t": 20, "b": 115},
        showlegend=False,
    )
    fig.update_xaxes(tickangle=-35, automargin=True, tickfont={"size": 10})
    return fig


def create_equipment_activity_chart(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return create_empty_figure("Sin actividad por equipo")

    # Detailed equipment × system data enables a stacked horizontal chart:
    # equipment remain the y-axis entities while eligible systems become the
    # color/legend categories.  Equipo/Cabina are omitted from the visual but
    # do not remove the equipment rows themselves.
    if "system_name" in df.columns:
        raw = df.copy()
        raw["machine_code"] = raw["machine_code"].astype(str)
        eligible = raw.loc[~raw["system_name"].map(_is_excluded_activity_system)].copy()
        equipment_totals = raw.groupby("machine_code", as_index=False)["count"].sum().sort_values(
            ["count", "machine_code"], ascending=[False, True]
        )
        equipment = equipment_totals["machine_code"].tolist()
        if eligible.empty:
            return create_empty_figure("Sin sistemas elegibles para este período")
        systems = sorted(eligible["system_name"].dropna().astype(str).unique().tolist())
        pivot = eligible.pivot_table(
            index="machine_code", columns="system_name", values="count", aggfunc="sum", fill_value=0
        ).reindex(index=equipment, columns=systems, fill_value=0).fillna(0)
        palette = ["#355c7d", "#4f8a8b", "#d08c60", "#7b6ea8", "#6f8fb3", "#b56b78", "#5f9e7a", "#9a7b4f", "#778899", "#c47f3f", "#5b6d8a"]
        fig = go.Figure()
        for index, system in enumerate(systems):
            values = pivot[system].astype(int)
            fig.add_trace(
                go.Bar(
                    x=values,
                    y=equipment,
                    orientation="h",
                    name=system,
                    marker_color=palette[index % len(palette)],
                    customdata=values,
                    hovertemplate=f"<b>%{{y}}</b><br>Sistema: {system}<br>Acciones: %{{x}}<extra></extra>",
                )
            )
        fig.update_layout(
            template="plotly_white",
            barmode="stack",
            xaxis_title="Acciones",
            yaxis_title="Equipo",
            margin={"l": 65, "r": 45, "t": 45, "b": 65},
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        )
        fig.update_yaxes(categoryorder="array", categoryarray=equipment, autorange="reversed")
        return fig

    data = df.sort_values("count", ascending=True).copy()
    systems = data.get("primary_system", pd.Series("Sin sistema", index=data.index)).fillna("Sin sistema").astype(str)
    short_systems = systems.str.replace("Sistema de ", "", regex=False).str.replace("Sistema ", "", regex=False)
    labels = data["machine_code"].astype(str) + " · " + short_systems
    fig = go.Figure(
        go.Bar(
            x=data["count"],
            y=labels,
            orientation="h",
            marker_color="#4f8a8b",
            text=data["count"].astype(int),
            textposition="outside",
            cliponaxis=False,
            customdata=systems,
            hovertemplate="<b>%{y}</b><br>Sistema: %{customdata}<br>Acciones: %{x}<extra></extra>",
        )
    )
    fig.update_layout(template="plotly_white", xaxis_title="Acciones", yaxis_title="Equipo · sistema predominante", margin={"l": 105, "r": 45, "t": 20, "b": 45})
    return fig


def create_activity_matrix(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return create_empty_figure("Sin actividad para la matriz")
    matrix = df.pivot(index="machine_code", columns="system_name", values="count").fillna(0)
    fig = go.Figure(go.Heatmap(z=matrix.values, x=matrix.columns.tolist(), y=matrix.index.tolist(), colorscale="Blues", hovertemplate="Equipo %{y}<br>Sistema %{x}<br>Acciones %{z}<extra></extra>"))
    fig.update_layout(template="plotly_white", xaxis_title="Sistema", yaxis_title="Equipo", margin={"l": 65, "r": 20, "t": 20, "b": 100})
    return fig


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
        [("date", "Fecha"), ("timestamp_utc", "Timestamp UTC"), ("equipment", "Equipo"), ("system_name", "Sistema"), ("subsystem_name", "Subsistema"), ("action_type", "Tipo de acción"), ("detail", "Detalle")],
        "Sin acciones para los filtros seleccionados",
        page_size=15,
    )


def create_week_summary_table(data):
    return _table(data, [("equipment", "Equipo"), ("summary", "Resumen")], "Sin resumen semanal disponible", page_size=11)


def create_week_task_table(data):
    return _table(data, [("equipment", "Equipo"), ("day", "Día"), ("system_name", "Sistema"), ("task", "Actividad")], "Sin tareas estructuradas para esta semana", page_size=15)


# Compatibility aliases for callers that still import the old chart helpers.
create_downtime_trend_chart = create_daily_activity_chart


def create_detentions_table(df_detentions: pd.DataFrame):
    return _table(df_detentions.to_dict("records"), [(c, c) for c in df_detentions.columns], "Sin registros", page_size=10)


def create_jobs_table(df_jobs: pd.DataFrame):
    return _table(df_jobs.to_dict("records"), [(c, c) for c in df_jobs.columns], "Sin acciones", page_size=10)
