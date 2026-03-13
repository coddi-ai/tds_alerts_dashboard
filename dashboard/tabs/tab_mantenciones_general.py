"""
Tab: Mantenciones General
Vista general consolidada de mantenciones con KPIs, gráficos y tablas.
"""

import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime


def create_kpi_card(title: str, value: str, icon: str = "fa-info-circle", color: str = "primary"):
    """
    Create a KPI card component.
    
    Args:
        title: Card title
        value: Card value to display
        icon: FontAwesome icon class
        color: Bootstrap color theme
        
    Returns:
        dbc.Card component
    """
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.I(className=f"fas {icon} fa-2x mb-2 text-{color}"),
                html.H3(value, className="mb-0", id=f"kpi-{title.lower().replace(' ', '-')}"),
                html.P(title, className="text-muted mb-0"),
            ], className="text-center")
        ])
    ], className="shadow-sm h-100")


def layout_mantenciones_general():
    """
    Create the Mantenciones General tab layout.
    
    Returns:
        html.Div with complete layout
    """
    return html.Div([
        # Header
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-wrench me-2"),
                    "Mantenciones - Ventana General"
                ]),
                html.P("Vista consolidada de estado de equipos y trabajos de mantenimiento", 
                       className="text-muted")
            ], width=8),
            dbc.Col([
                dbc.Button([
                    html.I(className="fas fa-sync-alt me-2"),
                    "Refrescar"
                ], id="btn-refresh-general", color="primary", className="float-end")
            ], width=4)
        ], className="mb-4"),
        
        # Hidden stores for data caching
        dcc.Store(id="store-general-data"),
        dcc.Store(id="store-general-timestamp"),
        dcc.Store(id="store-general-loaded", data=False),  # Track if data is loaded
        
        # Loading overlay
        dcc.Loading(
            id="loading-general",
            type="default",
            children=[
                # Row 1: KPIs
                dbc.Row([
                    dbc.Col(create_kpi_card(
                        "Equipos Totales", 
                        "0", 
                        "fa-industry", 
                        "info"
                    ), width=3),
                    dbc.Col(create_kpi_card(
                        "Equipos Sanos", 
                        "0", 
                        "fa-check-circle", 
                        "success"
                    ), width=3),
                    dbc.Col(create_kpi_card(
                        "Equipos Detenidos", 
                        "0", 
                        "fa-exclamation-triangle", 
                        "danger"
                    ), width=3),
                    dbc.Col(create_kpi_card(
                        "Horas Detenidas MTD", 
                        "0", 
                        "fa-clock", 
                        "warning"
                    ), width=3),
                ], className="mb-4", id="row-kpis"),
                
                # Row 2: Visualizations
                dbc.Row([
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.I(className="fas fa-chart-pie me-2"),
                                "Estado de Equipos"
                            ]),
                            dbc.CardBody([
                                dcc.Graph(
                                    id="chart-status-distribution",
                                    config={"displayModeBar": False},
                                    style={"height": "300px"}
                                )
                            ])
                        ], className="shadow-sm h-100")
                    ], width=6),
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.I(className="fas fa-chart-line me-2"),
                                "Horas Detenidas por Día (MTD)"
                            ]),
                            dbc.CardBody([
                                dcc.Graph(
                                    id="chart-downtime-trend",
                                    config={"displayModeBar": False},
                                    style={"height": "300px"}
                                )
                            ])
                        ], className="shadow-sm h-100")
                    ], width=6),
                ], className="mb-4"),
                
                # Row 3: Tables
                dbc.Row([
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.I(className="fas fa-history me-2"),
                                "Últimos Periodos de Detención por Equipo"
                            ]),
                            dbc.CardBody([
                                html.Div(id="table-last-detentions")
                            ])
                        ], className="shadow-sm")
                    ], width=12),
                ], className="mb-4"),
                
                dbc.Row([
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.I(className="fas fa-tasks me-2"),
                                "Trabajos Realizados - Última Semana"
                            ]),
                            dbc.CardBody([
                                html.Div(id="table-jobs-last-week")
                            ])
                        ], className="shadow-sm")
                    ], width=12),
                ], className="mb-4"),
            ]
        ),
        
        # Footer with last update time
        dbc.Row([
            dbc.Col([
                html.P([
                    html.I(className="fas fa-info-circle me-2"),
                    html.Span("Última actualización: ", className="text-muted"),
                    html.Span("N/A", id="text-last-update", className="text-muted fw-bold")
                ], className="text-end mb-0")
            ])
        ])
        
    ], className="p-4")


def create_empty_figure(message: str = "No hay datos disponibles"):
    """
    Create an empty plotly figure with a message.
    
    Args:
        message: Message to display
        
    Returns:
        plotly.graph_objects.Figure
    """
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=14, color="gray")
    )
    fig.update_layout(
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        plot_bgcolor="white",
        margin=dict(l=20, r=20, t=20, b=20)
    )
    return fig


def create_status_donut_chart(df_status: pd.DataFrame) -> go.Figure:
    """
    Create a donut chart for machine status distribution.
    
    Args:
        df_status: DataFrame with columns machine_status, n_machines
        
    Returns:
        plotly.graph_objects.Figure
    """
    if df_status.empty:
        return create_empty_figure()
    
    colors = {
        "SANO": "#28a745",
        "DETENIDO": "#dc3545"
    }
    
    fig = go.Figure(data=[go.Pie(
        labels=df_status["machine_status"],
        values=df_status["n_machines"],
        hole=0.4,
        marker=dict(colors=[colors.get(status, "#6c757d") for status in df_status["machine_status"]]),
        textinfo="label+value+percent",
        textposition="auto"
    )])
    
    fig.update_layout(
        showlegend=True,
        margin=dict(l=20, r=20, t=20, b=20),
        height=300
    )
    
    return fig


def create_downtime_trend_chart(df_trend: pd.DataFrame) -> go.Figure:
    """
    Create a line chart for downtime trend by day.
    
    Args:
        df_trend: DataFrame with columns date, downtime_hours
        
    Returns:
        plotly.graph_objects.Figure
    """
    if df_trend.empty:
        return create_empty_figure()
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=df_trend["date"],
        y=df_trend["downtime_hours"],
        mode="lines+markers",
        name="Horas Detenidas",
        line=dict(color="#ffc107", width=3),
        marker=dict(size=8),
        fill="tozeroy",
        fillcolor="rgba(255, 193, 7, 0.2)"
    ))
    
    fig.update_layout(
        xaxis_title="Fecha",
        yaxis_title="Horas Detenidas",
        hovermode="x unified",
        margin=dict(l=40, r=20, t=20, b=40),
        height=300,
        plot_bgcolor="white"
    )
    
    fig.update_xaxes(showgrid=True, gridcolor="lightgray")
    fig.update_yaxes(showgrid=True, gridcolor="lightgray")
    
    return fig


def create_detentions_table(df_detentions: pd.DataFrame) -> dash_table.DataTable:
    """
    Create a DataTable for last detentions.
    
    Args:
        df_detentions: DataFrame with detention data
        
    Returns:
        dash_table.DataTable
    """
    if df_detentions.empty:
        return html.P("No hay datos de detenciones disponibles", className="text-muted text-center p-3")
    
    # Format data
    df = df_detentions.copy()
    df["start_date"] = pd.to_datetime(df["start_date"]).dt.strftime("%Y-%m-%d %H:%M")
    df["end_date"] = df.apply(
        lambda row: "En curso" if row["ongoing"] else pd.to_datetime(row["end_date"]).strftime("%Y-%m-%d %H:%M"),
        axis=1
    )
    df["duration_hours"] = df["duration_hours"].round(2)
    
    return dash_table.DataTable(
        data=df.to_dict("records"),
        columns=[
            {"name": "Equipo", "id": "machine_code"},
            {"name": "Inicio", "id": "start_date"},
            {"name": "Fin", "id": "end_date"},
            {"name": "Duración (hrs)", "id": "duration_hours"},
            {"name": "Tipos de Trabajo", "id": "job_types"},
        ],
        style_table={"overflowX": "auto"},
        style_cell={
            "textAlign": "left",
            "padding": "10px",
            "fontSize": "14px"
        },
        style_header={
            "backgroundColor": "#f8f9fa",
            "fontWeight": "bold"
        },
        style_data_conditional=[
            {
                "if": {"row_index": "odd"},
                "backgroundColor": "#f8f9fa"
            }
        ],
        page_size=10,
        sort_action="native",
        filter_action="native"
    )


def create_jobs_table(df_jobs: pd.DataFrame) -> dash_table.DataTable:
    """
    Create a DataTable for recent jobs.
    
    Args:
        df_jobs: DataFrame with jobs data
        
    Returns:
        dash_table.DataTable
    """
    if df_jobs.empty:
        return html.P("No hay trabajos registrados en la última semana", className="text-muted text-center p-3")
    
    # Format data
    df = df_jobs.copy()
    df["start_date"] = pd.to_datetime(df["start_date"]).dt.strftime("%Y-%m-%d %H:%M")
    df["subsystem_name"] = df["subsystem_name"].fillna("N/A")
    
    return dash_table.DataTable(
        data=df.to_dict("records"),
        columns=[
            {"name": "Equipo", "id": "machine_code"},
            {"name": "Sistema", "id": "system_name"},
            {"name": "Subsistema", "id": "subsystem_name"},
            {"name": "Tipo", "id": "job_type"},
            {"name": "Inicio", "id": "start_date"},
            {"name": "Notas", "id": "notes"},
        ],
        style_table={"overflowX": "auto"},
        style_cell={
            "textAlign": "left",
            "padding": "10px",
            "fontSize": "14px"
        },
        style_header={
            "backgroundColor": "#f8f9fa",
            "fontWeight": "bold"
        },
        style_data_conditional=[
            {
                "if": {"row_index": "odd"},
                "backgroundColor": "#f8f9fa"
            }
        ],
        page_size=10,
        sort_action="native",
        filter_action="native"
    )
