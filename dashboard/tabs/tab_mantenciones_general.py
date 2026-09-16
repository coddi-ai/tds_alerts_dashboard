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
                    html.I(className=f"fas {icon} fa-2x mb-2 text-{color}"),
                    html.H3(value, id=value_id, className="mb-0"),
                    html.P(title, className="text-muted mb-0"),
                    html.P(scope_label, className="text-muted small mb-0 fst-italic") if scope_label else None,
                ],
                className="text-center",
            )
        ),
        className="shadow-sm h-100",
    )


def _card(title: str, child, icon: str = "fa-chart-bar"):
    return dbc.Card(
        [
            dbc.CardHeader([html.I(className=f"fas {icon} me-2"), title]),
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
            html.Div(id="maintenance-month-status"),
            dbc.Row(
                [
                    dbc.Col(create_kpi_card("Disponibilidad ESTIMADA", component_id="maintenance-kpi-availability-est", icon="fa-gauge-high", color="success", scope_label="proxy · cobertura en banner"), md=3),
                    dbc.Col(create_kpi_card("Downtime ESTIMADO", component_id="maintenance-kpi-downtime-est", icon="fa-hourglass-half", color="danger", scope_label="proxy · cobertura en banner"), md=3),
                    dbc.Col(create_kpi_card("MTBF ESTIMADO", component_id="maintenance-kpi-mtbf-est", icon="fa-arrows-rotate", color="info", scope_label="proxy · cobertura en banner"), md=3),
                    dbc.Col(create_kpi_card("MTTR ESTIMADO", component_id="maintenance-kpi-mttr-est", icon="fa-screwdriver-wrench", color="warning", scope_label="proxy · cobertura en banner"), md=3),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(create_kpi_card("Equipos con actividad", component_id="maintenance-kpi-equipment", icon="fa-truck", color="info"), md=3),
                    dbc.Col(create_kpi_card("Acciones registradas", component_id="maintenance-kpi-actions", icon="fa-wrench", color="primary"), md=3),
                    dbc.Col(create_kpi_card("Registros de mantenimiento", component_id="maintenance-kpi-records", icon="fa-clipboard-list", color="success"), md=3),
                    dbc.Col(create_kpi_card("Sistemas intervenidos", component_id="maintenance-kpi-systems", icon="fa-sitemap", color="warning"), md=3),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(create_kpi_card("Días con actividad", component_id="maintenance-kpi-days", icon="fa-calendar-day", color="secondary", scope_label="fecha operacional"), md=3),
                    dbc.Col(create_kpi_card("Actividad en Motor", component_id="maintenance-kpi-motor-share", icon="fa-percentage", color="danger", scope_label="% de acciones"), md=3),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(_card("Actividad diaria", dcc.Graph(id="maintenance-chart-daily", config={"displayModeBar": False}, style={"height": "310px"}), "fa-chart-line"), md=6),
                    dbc.Col(_card("Actividad registrada por sistema", dcc.Graph(id="maintenance-chart-system-mix", config={"displayModeBar": False}, style={"height": "310px"}), "fa-sitemap"), md=6),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(_card("Pareto de actividad por equipo · Sistema Motor", dcc.Graph(id="maintenance-chart-pareto", config={"displayModeBar": False}, style={"height": "320px"}), "fa-chart-bar"), md=6),
                    dbc.Col(_card("Equipos con mayor actividad", dcc.Graph(id="maintenance-chart-equipment", config={"displayModeBar": False}, style={"height": "320px"}), "fa-truck-loading"), md=6),
                ],
                className="g-3",
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
                            html.H2([html.I(className="fas fa-wrench me-2"), "Mantenciones"]),
                            html.P("Actividad de mantenimiento y evidencia semanal", className="text-muted mb-0"),
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
            html.Div(id="maintenance-source-alert"),
            dbc.Row(
                [
                    dbc.Col([html.Label("Mes de análisis", className="small text-muted"), dcc.Dropdown(id="maintenance-month", clearable=False, placeholder="Seleccione un mes")], md=6),
                    dbc.Col([html.Label("Semana de evidencia", className="small text-muted"), dcc.Dropdown(id="maintenance-week", clearable=False, placeholder="Seleccione una semana")], md=6),
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


def create_equipment_pareto_chart(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return create_empty_figure("Sin actividad de Motor por equipo")
    # ``system_name`` is accepted as a compatibility fallback for cached
    # payloads from the previous contract; new payloads use ``equipment``.
    dimension = "equipment" if "equipment" in df.columns else "system_name"
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=df[dimension], y=df["count"], name="Acciones Motor", marker_color=PARETO_BAR_COLOR, text=df["count"].astype(int), textposition="outside", cliponaxis=False), secondary_y=False)
    fig.add_trace(go.Scatter(x=df[dimension], y=df["cumulative_pct"], name="% acumulado", mode="lines+markers", line={"color": PARETO_LINE_COLOR, "width": 2}, marker={"color": PARETO_LINE_COLOR}), secondary_y=True)
    fig.update_yaxes(title_text="Acciones", rangemode="tozero", secondary_y=False)
    fig.update_yaxes(title_text="% acumulado", range=[0, 100], ticksuffix="%", secondary_y=True)
    fig.update_xaxes(title_text="Equipo", tickangle=-35)
    fig.update_layout(template="plotly_white", showlegend=False, margin={"l": 45, "r": 45, "t": 20, "b": 85}, hovermode="x unified")
    return fig


# Compatibility alias for callers importing the previous builder name.
create_system_pareto_chart = create_equipment_pareto_chart


def create_system_activity_chart(df: pd.DataFrame) -> go.Figure:
    """Render recorded action volume by system, not failure frequency."""
    if df.empty:
        return create_empty_figure("Sin actividad por sistema")
    data = df.sort_values(["count", "system_name"], ascending=[False, True])
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
        margin={"l": 45, "r": 20, "t": 20, "b": 85},
        showlegend=False,
    )
    fig.update_xaxes(tickangle=-35)
    return fig


def create_equipment_activity_chart(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return create_empty_figure("Sin actividad por equipo")
    data = df.sort_values("count", ascending=True)
    fig = go.Figure(go.Bar(x=data["count"], y=data["machine_code"], orientation="h", marker_color="#4f8a8b", text=data["count"].astype(int), textposition="outside", cliponaxis=False))
    fig.update_layout(template="plotly_white", xaxis_title="Acciones", yaxis_title="Equipo", margin={"l": 60, "r": 45, "t": 20, "b": 45})
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
