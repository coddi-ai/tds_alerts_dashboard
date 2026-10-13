"""Hierarchical telemetry unit detail layout."""

from src.i18n import t
from dashboard.components.labels import status_label
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc


def _state_rules(column: str = "system_status") -> list:
    """Row styling by status. The tables hold the translated status text, so the rules match
    the label of the language being served (computed per render, not at import)."""
    return [
        {"if": {"filter_query": '{%s} = "%s"' % (column, status_label("Anormal"))}, "backgroundColor": "rgba(220,53,69,.10)", "color": "#b42318", "fontWeight": "600"},
        {"if": {"filter_query": '{%s} = "%s"' % (column, status_label("Alerta"))}, "backgroundColor": "rgba(245,158,11,.12)", "color": "#8a5a00", "fontWeight": "600"},
        {"if": {"filter_query": '{%s} = "%s"' % (column, status_label("InsufficientData"))}, "backgroundColor": "rgba(149,165,166,.15)", "color": "#657174"},
        {"if": {"filter_query": '{%s} = "%s"' % (column, status_label("Normal"))}, "color": "#247a3d"},
    ]


def create_telemetry_unit_detail_layout() -> html.Div:
    """Create the unit -> system -> signal report flow."""
    return html.Div([
        dbc.Card([
            dbc.CardHeader([
                html.H5([html.I(className="fas fa-fingerprint me-2"), t("tab_telemetry_unit_detail.resumen_de_la_unidad")], className="mb-0")
            ], className="bg-light"),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label(t("tab_alerts_detail.unidad"), className="fw-bold small"),
                        dcc.Dropdown(
                            id="telemetry-detail-unit-selector",
                            placeholder=t("tab_telemetry_unit_detail.seleccione_una_unidad"),
                            clearable=False,
                            searchable=True,
                        ),
                    ], md=4),
                    dbc.Col([
                        html.Div(t("tab_telemetry_unit_detail.caso_seleccionado"), className="small text-muted fw-bold"),
                        html.Div(t("tab_telemetry_unit_detail.el_estado_y_la_recomendacion_corresponden"), className="small text-muted mt-1"),
                    ], md=8),
                ]),
                html.Div(id="telemetry-detail-ai-comment", className="mt-3"),
            ]),
        ], className="shadow-sm mb-4"),

        html.Div([
            html.H4([html.I(className="fas fa-cogs me-2"), t("tab_telemetry_unit_detail.estado_por_sistema")], className="text-primary mb-2 mt-4 pb-2 border-bottom"),
            html.P(t("tab_telemetry_unit_detail.revise_el_estado_de_todos_los"), className="text-muted mb-3"),
        ]),
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col(html.Label(t("tab_telemetry_unit_detail.sistema_seleccionado"), className="small fw-bold"), md=3),
                    dbc.Col(dcc.Dropdown(id="telemetry-detail-system-selector", placeholder=t("tab_telemetry_unit_detail.seleccione_un_sistema"), clearable=False), md=9),
                ], className="align-items-center mb-3"),
                dcc.Loading(
                    dash_table.DataTable(
                        id="telemetry-detail-system-table",
                        columns=[
                            {"name": t("tab_alerts_detail.sistema"), "id": "system"},
                            {"name": t("tab_telemetry_fleet.estado"), "id": "system_status"},
                            {"name": t("tab_telemetry_unit_detail.senales_afectadas"), "id": "signals_in_alert", "type": "numeric"},
                            {"name": t("tab_telemetry_unit_detail.senal_principal"), "id": "top_signal_display"},
                        ],
                        data=[],
                        row_selectable="single",
                        selected_rows=[],
                        sort_action="native",
                        page_size=10,
                        style_table={"overflowX": "auto"},
                        style_header={"backgroundColor": "#34495e", "color": "white", "fontWeight": "bold", "textAlign": "center"},
                        style_cell={"textAlign": "center", "padding": "10px", "fontSize": "14px", "whiteSpace": "normal", "height": "auto"},
                        style_cell_conditional=[
                            {"if": {"column_id": "system"}, "textAlign": "left", "fontWeight": "600"},
                            {"if": {"column_id": "top_signal_display"}, "textAlign": "left"},
                        ],
                        style_data_conditional=_state_rules() + [{"if": {"state": "active"}, "border": "2px solid #2f80ed"}],
                    ),
                    type="circle",
                ),
            ]),
        ], className="shadow-sm mb-3"),
        dcc.Loading(html.Div(id="telemetry-detail-system-analysis"), type="circle"),

        html.Div([
            html.H4([html.I(className="fas fa-wave-square me-2"), t("tab_telemetry_unit_detail.senales_del_sistema")], className="text-primary mb-2 mt-4 pb-2 border-bottom"),
            html.P(t("tab_telemetry_unit_detail.seleccione_una_senal_para_abrir_unicamente"), className="text-muted mb-3"),
        ]),
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col(html.Label(t("tab_telemetry_unit_detail.senal_seleccionada"), className="small fw-bold"), md=3),
                    dbc.Col(dcc.Dropdown(id="telemetry-detail-signal-selector", placeholder=t("tab_telemetry_unit_detail.seleccione_una_senal"), clearable=False), md=9),
                ], className="align-items-center mb-3"),
                dcc.Loading(
                    dash_table.DataTable(
                        id="telemetry-detail-signal-table",
                        columns=[
                            {"name": t("tab_telemetry_unit_detail.senal"), "id": "signal"},
                            {"name": t("tab_telemetry_fleet.estado"), "id": "status"},
                            {"name": t("tab_telemetry_unit_detail.fuera_de_rango"), "id": "abnormal_pct_display"},
                            {"name": t("tab_telemetry_unit_detail.eventos"), "id": "total_events", "type": "numeric"},
                            {"name": t("tab_telemetry_unit_detail.episodio_max_min"), "id": "longest_episode", "type": "numeric"},
                            {"name": t("tab_telemetry_unit_detail.tendencia"), "id": "trend_direction"},
                            {"name": "signal_raw", "id": "signal_raw"},
                        ],
                        data=[],
                        row_selectable="single",
                        selected_rows=[],
                        sort_action="native",
                        page_size=15,
                        style_table={"overflowX": "auto"},
                        style_header={"backgroundColor": "#34495e", "color": "white", "fontWeight": "bold", "textAlign": "center"},
                        style_cell={"textAlign": "center", "padding": "9px", "fontSize": "13px", "whiteSpace": "normal", "height": "auto"},
                        style_cell_conditional=[
                            {"if": {"column_id": "signal"}, "textAlign": "left", "fontWeight": "600"},
                            {"if": {"column_id": "signal_raw"}, "display": "none"},
                        ],
                        style_data_conditional=[
                            *[rule for rule in _state_rules("status") if "color" in rule and "backgroundColor" in rule],
                            {"if": {"state": "active"}, "border": "2px solid #2f80ed"},
                        ],
                    ),
                    type="circle",
                ),
            ]),
        ], className="shadow-sm mb-3"),
        html.Div([
            html.H4([html.I(className="fas fa-chart-line me-2"), t("tab_telemetry_unit_detail.evidencia_de_la_senal_seleccionada")], className="text-primary mb-2 mt-4 pb-2 border-bottom"),
            # W34-09: simplified view — starts at 1 day, no event overlays;
            # the buttons below only change the window width, never
            # unit/sistema/señal.
            html.P(t("tab_telemetry_unit_detail.serie_temporal_con_limites_y_tendencia"), className="text-muted mb-2"),
            dbc.RadioItems(
                id="telemetry-detail-window-days",
                options=[
                    {"label": t("tab_telemetry_unit_detail.1_dia"), "value": 1},
                    {"label": t("tab_telemetry_unit_detail.7_dias"), "value": 7},
                    {"label": t("tab_telemetry_unit_detail.30_dias"), "value": 30},
                ],
                value=1,
                inline=True,
                className="btn-group mb-3",
                inputClassName="btn-check",
                labelClassName="btn btn-outline-primary btn-sm",
                labelCheckedClassName="active",
            ),
        ]),
        dcc.Loading(html.Div(id="telemetry-detail-signal-cards"), type="circle"),
    ])
