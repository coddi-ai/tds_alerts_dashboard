"""Seguimiento de Avisos page layout (Conexión ERP).

Filters, KPI tiles, lifecycle bar, lifecycle charts and a paginated table over every
warning for the globally-selected client (client-selector in the navbar).
Reactive logic lives in dashboard/callbacks/integration_avisos_callbacks.py; chip colors in
dashboard/components/erp_chips.py, the bar visuals in erp_bars.py, shape in assets/erp_avisos.css.

The Registro de Avisos is a plain HTML table (static header, `erp-viewer-table-body` filled by a
callback) rather than a dash_table: the chips, the truncated ID with its tooltip and the
"Mostrando x–y de N" pager aren't something a DataTable cell can render.
"""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard.components.erp_chips import kpi_icon_badge
from src.data.erp_schemas import (
    CONDITION_LABEL_LABELS,
    SEVERITY_LABELS,
    SOURCE_LABELS,
    STATUS_LABELS,
    SYSTEM_LABELS,
    ConditionLabel,
    Severity,
    Source,
    System,
    WarningStatus,
)
from src.i18n import t

PAGE_SIZE = 20

# Value of every filter's "Todas / Todos" option. Not "": dbc.Select always renders its own hidden
# blank option with value "", so an empty-valued option would never show its label.
ALL_OPTION = "all"

# Registro de Avisos columns, in display order: (row key, header translation key).
# The key is the field name of a table row (erp_warning_store.TABLE_COLUMNS).
TABLE_HEADERS = (
    ("warning_id", None),
    ("asset_id", "tab_integration_seguimiento_avisos.activo"),
    ("source", "tab_integration_validacion_avisos.fuente"),
    ("system", "alerts_general.filter_system"),
    ("condition_label", "tab_integration_validacion_avisos.clasificacion"),
    ("severity", "tab_integration_seguimiento_avisos.severidad"),
    ("status", "tab_telemetry_fleet.estado"),
    ("generated_at", "tab_integration_validacion_avisos.generado"),
    ("validated_by", "tab_integration_seguimiento_avisos.validado_por"),
    ("erp_reference", "tab_integration_seguimiento_avisos.ref_erp"),
)

FILTER_IDS = {
    "source": "erp-viewer-filter-source",
    "system": "erp-viewer-filter-system",
    "label": "erp-viewer-filter-label",
    "severity": "erp-viewer-filter-severity",
    "status": "erp-viewer-filter-status",
    "asset": "erp-viewer-filter-asset",
}
DATES_ID = "erp-viewer-filter-dates"


def _options(enum_cls, labels):
    return [{"label": labels.get(v, v.value), "value": v.value} for v in enum_cls]


def _select_field(component_id: str, label: str, options: list, all_label: str) -> html.Div:
    """Label over a native <select>; ALL_OPTION means no filter (the refresh callback drops it)."""
    return html.Div(
        [
            html.Label(label, htmlFor=component_id, className="erp-field-label"),
            dbc.Select(
                id=component_id,
                options=[{"label": all_label, "value": ALL_OPTION}, *options],
                value=ALL_OPTION,
                className="erp-input erp-input--compact",
            ),
        ],
        className="erp-filter",
    )


def _date_field() -> html.Div:
    start_id, end_id = f"{DATES_ID}-start", f"{DATES_ID}-end"
    return html.Div(
        [
            html.Label(
                t("tab_integration_seguimiento_avisos.rango_de_fechas").strip(),
                htmlFor=start_id,
                className="erp-field-label",
            ),
            html.Label(t("tab_integration_seguimiento_avisos.fecha_hasta"), htmlFor=end_id, className="visually-hidden"),
            dcc.DatePickerRange(
                id=DATES_ID,
                start_date_id=start_id,
                end_date_id=end_id,
                display_format="DD/MM/YYYY",
                start_date_placeholder_text=t("tab_integration_seguimiento_avisos.fecha_inicial"),
                end_date_placeholder_text=t("tab_integration_seguimiento_avisos.fecha_hasta"),
                className="erp-date-range",
            ),
        ],
        className="erp-filter erp-filter--dates",
    )


def _filters_card() -> html.Section:
    all_f, all_m = t("tab_integration_seguimiento_avisos.opcion_todas"), t("tab_integration_seguimiento_avisos.opcion_todos")
    return html.Section(
        html.Div(
            [
                _select_field(
                    FILTER_IDS["source"], t("tab_integration_validacion_avisos.fuente"), _options(Source, SOURCE_LABELS), all_f
                ),
                _select_field(
                    FILTER_IDS["system"], t("alerts_general.filter_system"), _options(System, SYSTEM_LABELS), all_m
                ),
                _select_field(
                    FILTER_IDS["label"],
                    t("tab_integration_validacion_avisos.clasificacion"),
                    _options(ConditionLabel, CONDITION_LABEL_LABELS),
                    all_f,
                ),
                _select_field(
                    FILTER_IDS["severity"],
                    t("tab_integration_seguimiento_avisos.severidad"),
                    _options(Severity, SEVERITY_LABELS),
                    all_f,
                ),
                _select_field(
                    FILTER_IDS["status"], t("tab_telemetry_fleet.estado"), _options(WarningStatus, STATUS_LABELS), all_m
                ),
                # Options are the client's own assets, filled by a callback.
                _select_field(FILTER_IDS["asset"], t("tab_integration_validacion_avisos.id_del_activo"), [], all_m),
                _date_field(),
                html.Div(
                    dbc.Button(
                        [html.I(className="fas fa-eraser me-2", **{"aria-hidden": "true"}), t("tab_integration_seguimiento_avisos.limpiar_filtros")],
                        id="erp-viewer-clear-filters",
                        color="secondary",
                        outline=True,
                        type="button",
                        className="erp-input--compact",
                    ),
                    className="erp-filter erp-filter--action",
                ),
            ],
            className="erp-filter-row",
        ),
        className="erp-card erp-card--filters",
        **{"aria-label": t("tab_integration_seguimiento_avisos.filtros")},
    )


def _kpi_tile(kpi: str, icon: str, label: str, value_id: str, caption: str = "", caption_id: str | None = None) -> html.Div:
    """White card, tinted icon badge, no tinted background and no left border (ui_notes_improved.md §2).
    The grid stretches every tile to the row's height."""
    return html.Div(
        [
            html.Div([kpi_icon_badge(kpi, icon), html.Span(label, className="erp-kpi__label")], className="erp-kpi__head"),
            html.Div(id=value_id, className="erp-kpi__value"),
            html.Div(caption, id=caption_id, className="erp-kpi__caption") if caption_id else html.Div(caption, className="erp-kpi__caption"),
        ],
        className="erp-kpi",
    )


def _kpi_row() -> html.Div:
    return html.Div(
        [
            _kpi_tile(
                "total", "fa-bell", t("tab_integration_seguimiento_avisos.total_avisos"), "erp-viewer-kpi-total",
                t("tab_integration_seguimiento_avisos.con_los_filtros_aplicados"),
            ),
            _kpi_tile(
                "pending", "fa-clock", t("tab_integration_seguimiento_avisos.pendientes"), "erp-viewer-kpi-pending",
                caption_id="erp-viewer-kpi-pending-share",
            ),
            _kpi_tile(
                "sent", "fa-check-circle", t("tab_integration_seguimiento_avisos.validados_y_enviados"), "erp-viewer-kpi-sent",
                caption_id="erp-viewer-kpi-sent-share",
            ),
            _kpi_tile(
                "rejected", "fa-times-circle", t("tab_integration_seguimiento_avisos.rechazados"), "erp-viewer-kpi-rejected",
                caption_id="erp-viewer-kpi-rejected-share",
            ),
            _kpi_tile(
                "avg_hours", "fa-hourglass-half", t("tab_integration_seguimiento_avisos.tiempo_prom_a_validacion"),
                "erp-viewer-kpi-avg-hours", t("tab_integration_seguimiento_avisos.desde_la_generacion_del_aviso"),
            ),
        ],
        className="erp-kpi-row",
    )


def _card(title: str, body, *, extra_class: str = "") -> html.Section:
    return html.Section(
        [html.H2(title, className="erp-card__title"), body],
        className=f"erp-card {extra_class}".strip(),
    )


def _table_header() -> html.Thead:
    cells = [
        html.Th(t(key) if key else "ID", scope="col", className=f"erp-table__{field}")
        for field, key in TABLE_HEADERS
    ]
    return html.Thead(html.Tr(cells))


def _table_card() -> html.Section:
    return html.Section(
        [
            html.Div(
                [
                    html.H2(t("tab_integration_seguimiento_avisos.registro_de_avisos"), className="erp-card__title"),
                    html.P(
                        t("tab_integration_seguimiento_avisos.historial_completo_de_avisos_generados_por"),
                        className="erp-card__hint",
                    ),
                ]
            ),
            dcc.Loading(
                html.Div(
                    html.Table(
                        [_table_header(), html.Tbody(id="erp-viewer-table-body")],
                        className="erp-table",
                    ),
                    className="erp-table-wrap",
                    # A scrollable region has to be reachable by keyboard to be scrollable at all.
                    tabIndex=0,
                    role="region",
                    **{"aria-label": t("tab_integration_seguimiento_avisos.registro_de_avisos")},
                ),
                type="circle",
            ),
            html.Div(
                [
                    html.Span(id="erp-viewer-table-label", className="erp-pager__label", role="status"),
                    html.Div(
                        [
                            dbc.Button(
                                [html.I(className="fas fa-chevron-left me-2", **{"aria-hidden": "true"}), t("tab_integration_seguimiento_avisos.anterior")],
                                id="erp-viewer-page-prev",
                                color="secondary",
                                outline=True,
                                type="button",
                                className="erp-input--compact",
                            ),
                            html.Span(id="erp-viewer-page-indicator", className="erp-pager__page"),
                            dbc.Button(
                                [t("tab_integration_seguimiento_avisos.siguiente"), html.I(className="fas fa-chevron-right ms-2", **{"aria-hidden": "true"})],
                                id="erp-viewer-page-next",
                                color="secondary",
                                outline=True,
                                type="button",
                                className="erp-input--compact",
                            ),
                        ],
                        className="erp-pager__buttons",
                    ),
                ],
                className="erp-pager",
            ),
            dcc.Store(id="erp-viewer-table-rows", data=[]),
            dcc.Store(id="erp-viewer-table-page", data=0),
        ],
        className="erp-card",
    )


def create_layout() -> dbc.Container:
    return dbc.Container(
        [
            html.Header(
                [
                    html.H1(t("nav.service.integration-seguimiento-avisos"), className="erp-page-title"),
                    html.P(
                        t("tab_integration_seguimiento_avisos.vision_global_del_ciclo_de_vida"),
                        className="erp-page-subtitle",
                    ),
                ],
                className="erp-page-header",
            ),
            _filters_card(),
            _kpi_row(),
            _card(
                t("tab_integration_seguimiento_avisos.ciclo_de_vida_de_los_avisos"),
                dcc.Loading(html.Div(id="erp-viewer-lifecycle"), type="circle"),
            ),
            _card(
                t("tab_integration_seguimiento_avisos.avisos_en_el_tiempo"),
                dcc.Loading(
                    [
                        html.Div(id="erp-viewer-over-time"),
                        html.P(id="erp-viewer-over-time-caption", className="erp-chart-caption"),
                    ],
                    type="circle",
                ),
            ),
            html.Div(
                [
                    _card(
                        t("tab_integration_seguimiento_avisos.avisos_por_fuente_y_clasificacion"),
                        dcc.Loading(html.Div(id="erp-viewer-by-source"), type="circle"),
                    ),
                    _card(
                        t("tab_integration_seguimiento_avisos.avisos_por_severidad"),
                        dcc.Loading(html.Div(id="erp-viewer-by-severity"), type="circle"),
                    ),
                    _card(
                        t("tab_integration_seguimiento_avisos.avisos_por_sistema"),
                        dcc.Loading(html.Div(id="erp-viewer-by-system"), type="circle"),
                    ),
                ],
                className="erp-chart-grid",
            ),
            _card(
                t("tab_integration_seguimiento_avisos.tendencia_de_tasa_de_validacion"),
                dcc.Loading(html.Div(id="erp-viewer-validation-rate"), type="circle"),
            ),
            _table_card(),
            html.Div(id="erp-viewer-row-detail"),
        ],
        fluid=True,
        className="erp-page erp-page--tracking",
    )
