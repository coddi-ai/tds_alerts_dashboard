"""Seguimiento de Avisos page layout (Conexión ERP).

KPI cards, lifecycle charts, and a filterable/sortable table over every
warning for the globally-selected client (client-selector in the navbar).
Reactive logic lives in dashboard/callbacks/integration_avisos_callbacks.py.
"""
from __future__ import annotations

from src.i18n import t
import dash_bootstrap_components as dbc
from dash import dash_table, dcc, html

from src.data.erp_schemas import (
    CONDITION_LABEL_LABELS,
    ConditionLabel,
    Severity,
    SEVERITY_LABELS,
    Source,
    SOURCE_LABELS,
    STATUS_LABELS,
    System,
    SYSTEM_LABELS,
    WarningStatus,
)


def _kpi_card(icon: str, label: str, value_id: str, text_color: str, bg: str) -> dbc.Col:
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                html.Div(
                    [
                        html.I(className=f"fas {icon} fa-2x {text_color} mb-2"),
                        html.H6(
                            label,
                            className="text-muted mb-2",
                            style={"fontSize": "0.85rem", "letterSpacing": "0.5px"},
                        ),
                        html.H2(id=value_id, className=f"{text_color} mb-0 fw-bold"),
                    ],
                    className="text-center",
                )
            ),
            className="shadow-sm border-0",
            style={"backgroundColor": bg},
        ),
        md=2,
    )


def _filter_dropdown(id_, label, icon, options=None, clearable=True, **kwargs):
    return dbc.Col(
        [
            html.Label([html.I(className=f"fas {icon} me-1"), f" {label}"], className="fw-bold mb-2"),
            dcc.Dropdown(id=id_, options=options or [], clearable=clearable, **kwargs),
        ],
        md=2,
    )


def create_layout() -> dbc.Container:
    def _options(enum_cls, labels=None):
        labels = labels or {}
        return [{"label": labels.get(v, v.value), "value": v.value} for v in enum_cls]

    return dbc.Container(
        [
            html.Div(
                [
                    html.H3(
                        [html.I(className="fas fa-chart-bar me-2"), t("nav.service.integration-seguimiento-avisos")],
                        className="text-primary mb-2",
                    ),
                    html.P(
                        t("tab_integration_seguimiento_avisos.vision_global_del_ciclo_de_vida"),
                        className="text-muted",
                    ),
                ],
                className="mb-4",
            ),
            dbc.Card(
                [
                    dbc.CardHeader(
                        html.H5([html.I(className="fas fa-filter me-2"), t("tab_integration_seguimiento_avisos.filtros")], className="mb-0"),
                        className="bg-light",
                    ),
                    dbc.CardBody(
                        [
                            dbc.Row(
                                [
                                    _filter_dropdown(
                                        "erp-viewer-filter-source",
                                        t("tab_integration_validacion_avisos.fuente"),
                                        "fa-cogs",
                                        _options(Source, SOURCE_LABELS),
                                        placeholder=t("tab_integration_seguimiento_avisos.todas_las_fuentes"),
                                    ),
                                    _filter_dropdown(
                                        "erp-viewer-filter-system",
                                        t("alerts_general.filter_system"),
                                        "fa-cog",
                                        _options(System, SYSTEM_LABELS),
                                        placeholder=t("tab_alerts_detail.todos_los_sistemas"),
                                    ),
                                    _filter_dropdown(
                                        "erp-viewer-filter-label",
                                        t("tab_integration_validacion_avisos.clasificacion"),
                                        "fa-tag",
                                        _options(ConditionLabel, CONDITION_LABEL_LABELS),
                                        placeholder=t("tab_integration_seguimiento_avisos.todas"),
                                    ),
                                    _filter_dropdown(
                                        "erp-viewer-filter-severity",
                                        t("tab_integration_seguimiento_avisos.severidad"),
                                        "fa-tachometer-alt",
                                        _options(Severity, SEVERITY_LABELS),
                                        placeholder=t("tab_integration_seguimiento_avisos.todas"),
                                    ),
                                    _filter_dropdown(
                                        "erp-viewer-filter-status",
                                        t("tab_telemetry_fleet.estado"),
                                        "fa-info-circle",
                                        _options(WarningStatus, STATUS_LABELS),
                                        placeholder=t("tab_integration_seguimiento_avisos.todos"),
                                    ),
                                    _filter_dropdown(
                                        "erp-viewer-filter-asset",
                                        t("tab_integration_validacion_avisos.id_del_activo"),
                                        "fa-truck",
                                        [],
                                        placeholder=t("tab_integration_seguimiento_avisos.todos_los_equipos"),
                                    ),
                                ],
                                className="g-3",
                            ),
                            dbc.Row(
                                dbc.Col(
                                    [
                                        html.Label(
                                            [html.I(className="fas fa-calendar-alt me-1"), t("tab_integration_seguimiento_avisos.rango_de_fechas")],
                                            className="fw-bold mb-2",
                                        ),
                                        dcc.DatePickerRange(id="erp-viewer-filter-dates", display_format="DD/MM/YYYY"),
                                    ],
                                    md=4,
                                ),
                                className="g-3 mt-1",
                            ),
                        ]
                    ),
                ],
                className="shadow-sm mb-4",
            ),
            dbc.Row(
                [
                    _kpi_card("fa-bell", t("tab_integration_seguimiento_avisos.total_avisos"), "erp-viewer-kpi-total", "text-primary", "#f0f8ff"),
                    _kpi_card("fa-clock", t("tab_integration_seguimiento_avisos.pendientes"), "erp-viewer-kpi-pending", "text-warning", "#fffcf0"),
                    _kpi_card(
                        "fa-check-circle", t("tab_integration_seguimiento_avisos.validados_y_enviados"), "erp-viewer-kpi-sent", "text-success", "#f0fff4"
                    ),
                    _kpi_card("fa-times-circle", t("tab_integration_seguimiento_avisos.rechazados"), "erp-viewer-kpi-rejected", "text-danger", "#fff5f5"),
                    _kpi_card(
                        "fa-hourglass-half",
                        t("tab_integration_seguimiento_avisos.horas_prom_a_validacion"),
                        "erp-viewer-kpi-avg-hours",
                        "text-info",
                        "#f0f8ff",
                    ),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                html.H5(
                                    [html.I(className="fas fa-chart-line me-2"), t("tab_integration_seguimiento_avisos.avisos_en_el_tiempo")],
                                    className="mb-0",
                                ),
                                className="bg-light",
                            ),
                            dbc.CardBody(
                                dcc.Loading(
                                    dcc.Graph(id="erp-viewer-chart-over-time", config={"displayModeBar": False}),
                                    type="circle",
                                )
                            ),
                        ],
                        className="shadow-sm mb-4",
                    ),
                    md=12,
                ),
                className="gx-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.H5(
                                        [html.I(className="fas fa-tag me-2"), t("tab_integration_seguimiento_avisos.avisos_por_clasificacion")],
                                        className="mb-0",
                                    ),
                                    className="bg-light",
                                ),
                                dbc.CardBody(
                                    dcc.Loading(
                                        dcc.Graph(id="erp-viewer-chart-by-label", config={"displayModeBar": False}),
                                        type="circle",
                                    )
                                ),
                            ],
                            className="shadow-sm mb-4 h-100",
                        ),
                        md=4,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.H5(
                                        [html.I(className="fas fa-tachometer-alt me-2"), t("tab_integration_seguimiento_avisos.avisos_por_severidad")],
                                        className="mb-0",
                                    ),
                                    className="bg-light",
                                ),
                                dbc.CardBody(
                                    dcc.Loading(
                                        dcc.Graph(id="erp-viewer-chart-by-severity", config={"displayModeBar": False}),
                                        type="circle",
                                    )
                                ),
                            ],
                            className="shadow-sm mb-4 h-100",
                        ),
                        md=4,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.H5(
                                        [html.I(className="fas fa-cogs me-2"), t("tab_integration_seguimiento_avisos.avisos_por_sistema")],
                                        className="mb-0",
                                    ),
                                    className="bg-light",
                                ),
                                dbc.CardBody(
                                    dcc.Loading(
                                        dcc.Graph(id="erp-viewer-chart-by-system", config={"displayModeBar": False}),
                                        type="circle",
                                    )
                                ),
                            ],
                            className="shadow-sm mb-4 h-100",
                        ),
                        md=4,
                    ),
                ],
                className="gx-3",
            ),
            dbc.Card(
                [
                    dbc.CardHeader(
                        html.H5(
                            [html.I(className="fas fa-percentage me-2"), t("tab_integration_seguimiento_avisos.tendencia_de_tasa_de_validacion")],
                            className="mb-0",
                        ),
                        className="bg-light",
                    ),
                    dbc.CardBody(
                        dcc.Loading(
                            dcc.Graph(id="erp-viewer-chart-validation-rate", config={"displayModeBar": False}),
                            type="circle",
                        )
                    ),
                ],
                className="shadow-sm mb-4",
            ),
            html.Div(
                [
                    html.H4(
                        [html.I(className="fas fa-table me-2"), t("tab_integration_seguimiento_avisos.registro_de_avisos")],
                        className="text-primary mb-3 mt-4 pb-2 border-bottom",
                    ),
                    html.P(t("tab_integration_seguimiento_avisos.historial_completo_de_avisos_generados_por"), className="text-muted mb-3"),
                ]
            ),
            dbc.Card(
                dbc.CardBody(
                    dcc.Loading(
                        dash_table.DataTable(
                            id="erp-viewer-table",
                            columns=[
                                {"name": "ID", "id": "warning_id"},
                                {"name": t("tab_integration_seguimiento_avisos.asset"), "id": "asset_id"},
                                {"name": t("tab_integration_validacion_avisos.fuente"), "id": "source"},
                                {"name": t("alerts_general.filter_system"), "id": "system"},
                                {"name": t("tab_integration_validacion_avisos.clasificacion"), "id": "condition_label"},
                                {"name": t("tab_integration_seguimiento_avisos.severidad"), "id": "severity"},
                                {"name": t("tab_telemetry_fleet.estado"), "id": "status"},
                                {"name": t("tab_integration_validacion_avisos.generado"), "id": "generated_at"},
                                {"name": t("tab_integration_seguimiento_avisos.validado_por"), "id": "validated_by"},
                                {"name": t("tab_integration_seguimiento_avisos.ref_erp"), "id": "erp_reference"},
                            ],
                            data=[],
                            style_table={"overflowX": "auto", "overflowY": "auto", "maxHeight": "500px"},
                            style_cell={
                                "textAlign": "left",
                                "padding": "10px",
                                "fontFamily": "Arial, sans-serif",
                                "fontSize": "14px",
                                "minWidth": "100px",
                                "maxWidth": "400px",
                                "whiteSpace": "normal",
                                "height": "auto",
                            },
                            style_header={
                                "backgroundColor": "#2c3e50",
                                "color": "white",
                                "fontWeight": "bold",
                                "textAlign": "center",
                            },
                            style_data_conditional=[
                                {"if": {"row_index": "odd"}, "backgroundColor": "#f8f9fa"},
                                {
                                    "if": {"state": "active"},
                                    "backgroundColor": "#3498db",
                                    "color": "white",
                                    "border": "2px solid #2980b9",
                                    "cursor": "pointer",
                                },
                            ],
                            cell_selectable=True,
                            filter_action="native",
                            sort_action="native",
                            sort_mode="multi",
                            page_action="native",
                            page_size=20,
                        ),
                        type="circle",
                    )
                ),
                className="shadow-sm mb-4",
            ),
            html.Div(id="erp-viewer-row-detail"),
        ],
        fluid=True,
        className="p-4",
    )
