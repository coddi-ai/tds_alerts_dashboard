"""Executive alerts overview layout."""

from src.i18n import t, t_or
from datetime import date, timedelta
from dash import html, dcc
import dash_bootstrap_components as dbc

from dashboard.components.alerts_charts import FEATURE_NAMES_ES, NO_SIGNAL_KEY
from dashboard.components.labels import MULTITECHNICAL_KPI_COLOR, SOURCE_STYLE, source_style, light_tint


# Fixed heights for the three weekly-analysis cards (Distribución por unidad /
# Evolución temporal / Distribución por sistema) so the row's height stays
# constant regardless of fleet size (the unit chart folds all but its top N
# units into one bar rather than growing).
ALERTS_CHART_CARD_HEIGHT = 500
ALERTS_CHART_CARD_BODY_HEIGHT = 420


ALERTS_DEFAULT_WINDOW = timedelta(weeks=4)


def default_alert_dates() -> tuple[str, str]:
    """Rolling four-week window ending today: the initial value of the Desde / Hasta
    inputs and what "Restablecer últimas 4 semanas" puts back."""
    today = date.today()
    return (today - ALERTS_DEFAULT_WINDOW).isoformat(), today.isoformat()


def _date_field(component_id: str, label_key: str, value: str) -> html.Div:
    """One independently editable date input with its own label."""
    return html.Div([
        html.Span(t(label_key), className="alerts-date-field__label"),
        dcc.DatePickerSingle(
            id=component_id,
            date=value,
            display_format="DD/MM/YYYY",
            placeholder="DD/MM/YYYY",
            clearable=False,
        ),
    ], className="alerts-date-field")


def _build_source_legend() -> html.Div:
    """Color legend for the alert source (Trigger_type) — decodes the same
    colors the table's Mixto row-highlight and the "Alertas multitécnicas"
    KPI card use, all read from labels.py's SOURCE_STYLE (W34-04)."""
    canonical_keys = ("Telemetria", "Tribologia", "Mixto")  # one entry per concept, not per alias
    swatches = []
    for raw in canonical_keys:
        label, color = source_style(raw)
        swatches.append(
            html.Span([
                html.Span(style={
                    "display": "inline-block", "width": "10px", "height": "10px",
                    "borderRadius": "2px", "backgroundColor": color, "marginRight": "6px",
                }),
                label,
            ], className="d-inline-flex align-items-center me-3")
        )
    return html.Div(
        [html.Small(t("tab_alerts_general.fuente"), className="text-muted fw-bold me-2")] + swatches,
        className="d-flex flex-wrap align-items-center mt-2",
    )


def create_layout() -> html.Div:
    start_date, end_date = default_alert_dates()
    return html.Div([
        dcc.Store(id="alerts-selected-alert-id"),
        dcc.Store(id="alerts-general-active-filters", data={}),
        html.Div(id="alerts-summary-stats", className="mb-3"),
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.I(className="fas fa-filter me-2"),
                            html.Span(t("tab_alerts_general.filtro_temporal"), className="fw-bold"),
                        ], className="d-flex align-items-center pb-1"),
                    ], width="auto"),
                    dbc.Col(_date_field("alerts-date-start", "tab_alerts_general.fecha_desde", start_date), width="auto"),
                    dbc.Col(_date_field("alerts-date-end", "tab_alerts_general.fecha_hasta", end_date), width="auto"),
                    dbc.Col([
                        dbc.Button(
                            [html.I(className="fas fa-undo me-1"), t("tab_alerts_general.restablecer_ultimas_4_semanas")],
                            id="alerts-date-range-clear",
                            color="outline-secondary",
                            size="sm",
                        )
                    ], width="auto"),
                ], align="end", className="g-3"),
                html.Div(id="alerts-general-filter-summary", className="small text-muted mt-2"),
                # Filled by a callback: stays empty (nothing rendered) while no chart filter is active.
                html.Div(id="alerts-general-active-filters-bar"),
            ])
        ], className="shadow-sm mb-3"),
        html.H4([html.I(className="fas fa-chart-bar me-2"), t("tab_alerts_general.analisis_semanal_de_alertas")], className="text-primary mb-3 mt-4"),
        html.P(
            t("tab_alerts_general.haga_clic_en_una_barra_o"),
            className="small text-muted mb-3",
        ),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H5([html.I(className="fas fa-truck me-2"), t("tab_alerts_general.distribucion_por_unidad")], className="mb-0"), className="bg-light"),
                    dbc.CardBody(
                        dcc.Loading(
                            dcc.Graph(id="alerts-unit-distribution-chart", config={"displayModeBar": False}),
                            type="circle",
                        ),
                        style={"height": f"{ALERTS_CHART_CARD_BODY_HEIGHT}px", "overflow": "hidden"},
                    ),
                ], className="shadow-sm mb-4", style={"height": f"{ALERTS_CHART_CARD_HEIGHT}px"}),
            ], lg=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H5([html.I(className="fas fa-calendar-week me-2"), t("tab_alerts_general.evolucion_temporal")], className="mb-0"), className="bg-light"),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id="alerts-month-distribution-chart", config={"displayModeBar": False}), type="circle"),
                        style={"height": f"{ALERTS_CHART_CARD_BODY_HEIGHT}px", "overflow": "hidden"},
                    ),
                ], className="shadow-sm mb-4", style={"height": f"{ALERTS_CHART_CARD_HEIGHT}px"}),
            ], lg=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H5([html.I(className="fas fa-sitemap me-2"), t("tab_alerts_general.distribucion_por_sistema")], className="mb-0"), className="bg-light"),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id="alerts-system-distribution-chart", config={"displayModeBar": False}), type="circle"),
                        style={"height": f"{ALERTS_CHART_CARD_BODY_HEIGHT}px", "overflow": "hidden"},
                    ),
                ], className="shadow-sm mb-4", style={"height": f"{ALERTS_CHART_CARD_HEIGHT}px"}),
            ], lg=4),
        ], className="g-3"),
        html.H4([html.I(className="fas fa-database me-2"), t("tab_alerts_general.listado_de_alertas")], className="text-primary mb-3 mt-4"),
        dbc.Card([
            dbc.CardHeader([
                html.H5([html.I(className="fas fa-table me-2"), t("tab_alerts_general.alertas_del_periodo")], className="mb-0"),
                html.Small(t("tab_alerts_general.seleccione_una_fila_para_leer_el"), className="text-muted"),
                _build_source_legend(),
            ], className="bg-light"),
            dbc.CardBody([
                dcc.Loading(html.Div(id="alerts-table-container"), type="circle"),
                html.Div(id="alerts-general-selected-alert", className="mt-3 px-2 pb-2"),
            ], className="p-2"),
        ], className="shadow-sm mb-4"),
    ], className="p-4")


def create_summary_stats_display(total_alerts: int, total_units: int, telemetry_pct: float = 0, oil_pct: float = 0, mixed_count: int = 0) -> html.Div:
    """Render only the three client-facing alert KPIs."""
    # Not the Multitécnica Fuente color (SOURCE_STYLE["Mixto"]): the card is a count, and
    # next to the Fuente chips in the table and legend the same purple read as a fourth chip.
    mixto_color = MULTITECHNICAL_KPI_COLOR
    cards = [
        (t("tab_alerts_general.total_de_alertas"), total_alerts, "fas fa-exclamation-triangle", "#355c7d", "#eef4f8"),
        (t("tab_alerts_general.unidades_afectadas"), total_units, "fas fa-truck", "#4f8a8b", "#edf7f6"),
        (t("tab_alerts_general.alertas_multitecnicas"), mixed_count, "fas fa-layer-group", mixto_color, light_tint(mixto_color)),
    ]
    return html.Div([
        html.H4([html.I(className="fas fa-chart-line me-2"), t("tab_alerts_general.resumen_ejecutivo")], className="text-primary mb-3"),
        dbc.Row([
            dbc.Col(
                dbc.Card(dbc.CardBody([
                    html.Div([
                        html.I(className=f"{icon} fa-2x mb-2", style={"color": color}),
                        html.H6(label, className="text-muted text-uppercase mb-2", style={"fontSize": "0.82rem", "letterSpacing": "0.4px"}),
                        html.H2(f"{value:,}", className="mb-0 fw-bold", style={"color": color}),
                    ], className="text-center")
                ]), className="shadow-sm border-0", style={"backgroundColor": background}), md=4
            ) for label, value, icon, color, background in cards
        ], className="g-3"),
    ])


def _format_active_filter_value(key: str, value: str) -> str:
    if key == "week":
        try:
            return date.fromisoformat(value).strftime("%d/%m/%Y")
        except (TypeError, ValueError):
            return str(value)
    if key == "trigger":
        # The filter holds the raw signal code; the chip shows the same label as the treemap.
        if value == NO_SIGNAL_KEY:
            return t("alerts_report.sin_senal_registrada")
        return FEATURE_NAMES_ES.get(value, str(value))
    return str(value)


def _active_filter_chip(key: str, value: str) -> html.Span:
    label = t_or(f"alerts_general.filter_{key}", key.title())
    return html.Span(
        [
            html.Span(
                [html.Span(f"{label}:", className="alerts-filter-chip__key"), _format_active_filter_value(key, value)],
                className="alerts-filter-chip__text",
            ),
            html.Button(
                "×",
                id={"type": "alerts-general-filter-chip", "key": key},
                type="button",
                className="alerts-filter-chip__clear",
                title=t("tab_alerts_general.quitar_filtro", filter=label),
                **{"aria-label": t("tab_alerts_general.quitar_filtro", filter=label)},
            ),
        ],
        className="alerts-filter-chip",
    )


def create_active_filters_bar(active_filters: dict | None) -> html.Div | None:
    """The "Filtros activos" bar: one chip per active chart filter, each with its own ×,
    plus one "Limpiar todo". One bar for every chart on the view.

    Returns None - nothing rendered - while no filter is active. Both the × buttons and
    "Limpiar todo" use pattern-matching ids, so they exist only while the bar does and
    the callback that reads them needs no always-present placeholder component.
    """
    chips = [_active_filter_chip(key, value) for key, value in (active_filters or {}).items() if value]
    if not chips:
        return None
    return html.Div(
        [
            html.Span(t("tab_alerts_general.filtros_activos"), className="alerts-filters-bar__label"),
            html.Div(chips, className="alerts-filters-bar__chips"),
            dbc.Button(
                [html.I(className="fas fa-eraser me-1"), t("tab_alerts_general.limpiar_todo")],
                id={"type": "alerts-general-filter-clear-all", "index": 0},
                color="link",
                size="sm",
                className="alerts-filters-bar__clear-all",
            ),
        ],
        className="alerts-filters-bar",
    )
