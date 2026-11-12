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

# Ids of the explicit filter controls. They are views of the one shared filter store,
# `alerts-general-active-filters`, never state of their own.
UNIT_TOGGLE_ID = "alerts-filter-unit-toggle"
UNIT_CHECKLIST_ID = "alerts-filter-unit-checklist"
UNIT_CLEAR_ID = "alerts-filter-unit-clear"
SYSTEM_DROPDOWN_ID = "alerts-filter-system"
TRIGGER_DROPDOWN_ID = "alerts-filter-trigger"

# Value of the disabled option that heads each system's group in the trigger dropdown.
TRIGGER_GROUP_PREFIX = "__group__"


def default_alert_dates() -> tuple[str, str]:
    """Rolling four-week window ending today: the initial value of the Desde / Hasta
    inputs and what "Restablecer últimas 4 semanas" puts back."""
    today = date.today()
    return (today - ALERTS_DEFAULT_WINDOW).isoformat(), today.isoformat()


def unit_filter_summary(units) -> str:
    """Text on the closed Unidad control: all units, the one unit's id, or a count."""
    units = list(units or [])
    if not units:
        return t("tab_alerts_general.todas_las_unidades")
    if len(units) == 1:
        return str(units[0])
    return t("tab_alerts_general.unidades_seleccionadas", count=len(units))


def trigger_label(key: str) -> str:
    """Display label of a raw trigger signal code (the treemap's and the chips' label)."""
    if key == NO_SIGNAL_KEY:
        return t("alerts_report.sin_senal_registrada")
    return FEATURE_NAMES_ES.get(key, str(key))


def trigger_options(trigger_systems: dict, system: str | None = None) -> list[dict]:
    """Options of the Señal / Trigger dropdown.

    ``trigger_systems`` maps each trigger code to ``{system label: alert count}``. With a
    ``system`` selected only that system's triggers are listed, flat. Without one every
    trigger is listed once, under the system it fires in most (a trigger seen in several
    systems must not repeat: a repeated value would select all its copies at once), each
    group headed by a disabled option naming the system.
    """
    if system:
        keys = sorted((key for key, systems in trigger_systems.items() if system in systems), key=trigger_label)
        return [{"label": trigger_label(key), "value": key} for key in keys]
    groups: dict[str, list[str]] = {}
    for key, systems in trigger_systems.items():
        owner = min(systems, key=lambda name: (-systems[name], name))
        groups.setdefault(owner, []).append(key)
    options: list[dict] = []
    for owner in sorted(groups):
        options.append({"label": owner, "value": f"{TRIGGER_GROUP_PREFIX}{owner}", "disabled": True})
        options.extend({"label": trigger_label(key), "value": key} for key in sorted(groups[owner], key=trigger_label))
    return options


def _filter_field(label: str, control, label_extra=None) -> html.Div:
    """One cell of the filter row: a label over its control. ``label_extra`` sits on the
    label line, after the label (the date reset next to "Hasta")."""
    controls = control if isinstance(control, list) else [control]
    return html.Div(
        [
            html.Div([html.Span(label, className="alerts-filter-field__label"), label_extra], className="alerts-filter-field__head"),
            *controls,
        ],
        className="alerts-filter-field",
    )


def _date_field(component_id: str, label_key: str, value: str, label_extra=None) -> html.Div:
    """Desde / Hasta: each its own cell of the filter row, independently editable."""
    return _filter_field(t(label_key), dcc.DatePickerSingle(
        id=component_id,
        date=value,
        display_format="DD/MM/YYYY",
        placeholder="DD/MM/YYYY",
        clearable=False,
    ), label_extra)


def _build_unit_filter() -> html.Div:
    """Unidad: a button that opens a checklist of every unit (multi-select). Its text is
    set by a callback, so it always summarises the shared filter state."""
    return _filter_field(t("alerts_general.filter_unit"), [
        dbc.Button(
            t("tab_alerts_general.todas_las_unidades"), id=UNIT_TOGGLE_ID,
            color="light", size="sm", className="alerts-unit-toggle",
        ),
        dbc.Popover(
            dbc.PopoverBody([
                html.Div(
                    dbc.Checklist(id=UNIT_CHECKLIST_ID, options=[], value=[], className="alerts-unit-checklist"),
                    className="alerts-unit-checklist-scroll",
                ),
                dbc.Button(
                    [html.I(className="fas fa-eraser me-1"), t("tab_alerts_general.limpiar_unidades")],
                    id=UNIT_CLEAR_ID, color="link", size="sm", className="alerts-unit-clear p-0 mt-2",
                ),
            ]),
            target=UNIT_TOGGLE_ID, trigger="legacy", placement="bottom-start", className="alerts-unit-popover",
        ),
    ])


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
                html.Div([
                    html.I(className="fas fa-filter me-2"),
                    html.Span(t("tab_alerts_general.filtros"), className="fw-bold"),
                ], className="d-flex align-items-center"),
                html.Div(id="alerts-general-filter-summary", className="small text-muted mb-2"),
                html.Div([
                    _build_unit_filter(),
                    _date_field("alerts-date-start", "tab_alerts_general.fecha_desde", start_date),
                    _date_field("alerts-date-end", "tab_alerts_general.fecha_hasta", end_date, dbc.Button(
                        f"↺ {t('tab_alerts_general.ultimas_4_semanas')}",
                        id="alerts-date-range-clear",
                        color="link",
                        size="sm",
                        className="alerts-date-reset",
                    )),
                    _filter_field(t("alerts_general.filter_system"), dcc.Dropdown(
                        id=SYSTEM_DROPDOWN_ID, options=[], value=None, clearable=True,
                        placeholder=t("tab_alerts_general.todos_los_sistemas"), maxHeight=320,
                    )),
                    _filter_field(t("alerts_general.filter_trigger"), dcc.Dropdown(
                        id=TRIGGER_DROPDOWN_ID, options=[], value=None, clearable=True,
                        placeholder=t("tab_alerts_general.todas_las_senales"), maxHeight=320,
                    )),
                ], className="alerts-filter-row"),
                # Filled by a callback: stays empty (nothing rendered) while no filter is active.
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
        return trigger_label(value)
    return str(value)


def _active_filter_chip(key: str, value: str) -> html.Span:
    """One chip for one filter value; a multi-value filter (unit) gets one chip per value."""
    label = t_or(f"alerts_general.filter_{key}", key.title())
    return html.Span(
        [
            html.Span(
                [html.Span(f"{label}:", className="alerts-filter-chip__key"), _format_active_filter_value(key, value)],
                className="alerts-filter-chip__text",
            ),
            html.Button(
                "×",
                id={"type": "alerts-general-filter-chip", "key": key, "value": str(value)},
                type="button",
                className="alerts-filter-chip__clear",
                title=t("tab_alerts_general.quitar_filtro", filter=label),
                **{"aria-label": t("tab_alerts_general.quitar_filtro", filter=label)},
            ),
        ],
        className="alerts-filter-chip",
    )


def create_active_filters_bar(active_filters: dict | None) -> html.Div | None:
    """The "Filtros activos" bar: one chip per active filter value (a unit filter holding
    three units shows three chips), each with its own ×, plus one "Limpiar todo". One bar
    for the explicit controls and every chart alike.

    Returns None - nothing rendered - while no filter is active. Both the × buttons and
    "Limpiar todo" use pattern-matching ids, so they exist only while the bar does and
    the callback that reads them needs no always-present placeholder component.
    """
    chips = [
        _active_filter_chip(key, item)
        for key, value in (active_filters or {}).items() if value
        for item in (value if isinstance(value, (list, tuple)) else [value])
    ]
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
