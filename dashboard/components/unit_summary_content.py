"""
Unit Detail — per-technique content (Phase 3, restructured by
documentation/general/general_specs/
05_unit_summary_restructure_and_predictive_comparison.md, revised again by
07_unit_summary_revision_2.md and by the Unit Detail requirements of
ui_notes_improved.md).

Below the unit banner (dashboard/components/unit_summary.py) the page is: an
"Estado por Técnica" row of status tiles (one per monitored technique that has a status,
each linking to its section), then a Monitoreo section (Telemetry/Alerts/Oil + the
maintenance Pareto) and a Predictivo section (fleet-relative comparisons per sub-model),
stacked on a single vertical scroll rather than behind tabs. Mantención has no status here:
no tile, no chip; its Pareto card is information only.

Conditional rendering mirrors the Fleet Overview's rule (Phase 1, §3.1 of
00_implementation_guide.md): a technique unavailable for the client renders
no section at all here, via `applicable_techniques()`/`enabled_predictive_
components()` (dashboard/components/fleet_overview.py) - the same gate Fleet
Overview uses, so both views always agree on which techniques exist for a
client. A technique that *is* applicable but has no data in its own recent
window still renders its section, with an explicit empty-state body instead
of a chart (Functional Rules: distinct from an omitted, inapplicable
technique).

Each technique keeps its own "recent" window rather than a forced shared one
(§3.5) - Alerts standardizes on 30 days, Telemetry/Oil/Predictivo keep their
existing "most recent week/sample/run" convention - and every section labels its
own reference period on screen.

Every status (tile, card chip, section divider) is read from `technique_status`, passed
in by the caller (unit_summary.py) from `fleet_overview.get_unit_snapshot()` - the same
per-technique computation that drives the Fleet Overview table and the unit Estado, which
config/estado_rules.py defines - never recalculated independently here.

Telemetría and Tribología share one behavior for their rows: components in Alerta or
Anormal (and those without a reading) are always visible, worst first; Normal ones sit
below and collapse behind a toggle only when there are more than `MAX_VISIBLE_NORMAL`.
"""

from datetime import datetime, timedelta
from typing import Optional, Sequence

from src.i18n import t as _t
import dash_bootstrap_components as dbc
import pandas as pd
from dash import dcc, html

from config.estado_rules import priority_of, staleness_floor_limits
from config.settings import get_settings
from dashboard.components.alerts_charts import create_alerts_per_week_chart
from dashboard.components.fleet_overview import (
    applicable_techniques,
    enabled_predictive_components,
    get_predictive_component_status,
    status_badge,
    technique_label,
)
from dashboard.components.labels import display_component_name, display_system_name, status_label
from dashboard.components.oil_machine_detail import OilComponentRow, unit_oil_components
from dashboard.components.predictive_state import STATE_COLORS
from dashboard.components.status_chip import canonical_status, status_chip
from dashboard.tabs.tab_predictive_overview import (
    CHART_ASPECT_CLASS,
    load_status_frame,
    short_view_chart,
)
from src.data.loaders import (
    load_alerts_data,
    load_machine_status_for_client,
    load_telemetry_system_health,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

ALERTS_WINDOW_DAYS = 30  # §3.5: Alerts standardized on 30 days.

# 09_unit_summary_monitoreo_grid_and_oil_overview.md: with all 4 Monitoreo
# cards present they form a 2x2 grid. The layout for 1-3 cards is NOT yet
# confirmed by the business; until it is, those cases keep the previous
# auto-fit grid (same cards, new order).
MONITOREO_GRID_TECHNIQUES = 4

# Only Alerts' 30-day window is anchored to wall-clock "now" (Telemetry/Oil/Predictivo
# already anchor to their own latest partition/sample/run, so they never hit this). When a
# client's feed hasn't produced new data in this long, "now" is re-anchored
# to that feed's own latest timestamp instead, so a stale (test/demo/staging)
# dataset still shows its real most-recent activity rather than a permanent
# empty state. This deliberately does NOT touch freshness badges/status
# elsewhere (Fleet Overview) - those must keep reporting genuine staleness,
# since that is the dashboard's only signal that a client's pipeline has
# actually stopped in production. Every section that uses this shows a
# visible note (`_fallback_note`) when it fires, so old data is never
# mistaken for live data.
STALE_DATA_FALLBACK_WEEKS = 4

# Telemetría / Tribología: Normal rows collapse behind a toggle only past this many.
MAX_VISIBLE_NORMAL = 3

PARETO_HEIGHT = 460

# Anchor of each technique's section, target of its status tile.
SECTION_IDS = {
    "telemetry": "unit-section-telemetry",
    "alerts": "unit-section-alerts",
    "oil": "unit-section-oil",
    "predictive": "unit-section-predictive",
}

# Card-header icon per section, following ui_notes.md's icon table (Alerts /
# Telemetry / Oil already documented there; Maintenance/Predictive extend the same "one
# recognizable icon per concept" convention).
_SECTION_ICONS = {
    "Alertas": "fas fa-exclamation-triangle",
    "Telemetría": "fas fa-signal",
    "Tribología (Aceite)": "fas fa-oil-can",
    "Mantenciones": "fas fa-tools",
}
# Catalog key of each section title above. `_section_card` receives the already-translated
# title, so the icon is found by comparing against the translation, not the Spanish key.
_SECTION_TITLE_KEYS = {
    "Alertas": "unit_summary_content.section_alerts",
    "Telemetría": "unit_summary_content.section_telemetry",
    "Tribología (Aceite)": "unit_summary_content.section_oil",
}


def _section_icon(title: str) -> str:
    for spanish_title, icon in _SECTION_ICONS.items():
        key = _SECTION_TITLE_KEYS.get(spanish_title)
        if title == spanish_title or (key is not None and title == _t(key)):
            return icon
    return "fas fa-info-circle"


_PREDICTIVE_ICON = "fas fa-chart-line"

# Icons for the two stacked section dividers (07_unit_summary_revision_2.md
# Required Changes #2/#6) - Predictivo reuses _PREDICTIVE_ICON above so a
# sub-model card's icon and its section's icon are visibly the same concept.
_MONITOREO_ICON = "fas fa-desktop"

# Icon of each technique's status tile.
_TILE_ICONS = {
    "telemetry": _SECTION_ICONS["Telemetría"],
    "alerts": _SECTION_ICONS["Alertas"],
    "oil": _SECTION_ICONS["Tribología (Aceite)"],
    "predictive": _PREDICTIVE_ICON,
}

# The fleet scatter reused below (create_fleet_scatter) colors its points with the
# same red / yellow / green state rule as Resumen's charts, so its quadrant fills
# (also state-colored) never clash with the points.
_PREDICTIVE_STATUS_COLORS = STATE_COLORS


def _reference_time(latest_ts) -> tuple:
    """Reference "now" for a wall-clock-anchored recent window.

    Returns `(reference, is_fallback)`. `reference` is real wall-clock now,
    unless `latest_ts` (the feed's own most recent timestamp) is more than
    `STALE_DATA_FALLBACK_WEEKS` behind it - in which case `reference` becomes
    `latest_ts` itself, so a window computed as `reference - N days` lands on
    real data instead of an empty gap. `is_fallback` tells the caller to show
    `_fallback_note`.
    """
    now = pd.Timestamp.now()
    if latest_ts is not None and pd.notna(latest_ts):
        latest_ts = pd.Timestamp(latest_ts)
        if latest_ts.tzinfo is not None:
            latest_ts = latest_ts.tz_localize(None)
        if now - latest_ts > pd.Timedelta(weeks=STALE_DATA_FALLBACK_WEEKS):
            return latest_ts, True
    return now, False


def _fallback_note(reference: pd.Timestamp) -> html.Span:
    """Visible marker for when `_reference_time` fell back to stale data -
    never let old data pass as live without saying so on screen."""
    return html.Span([
        html.I(className="fas fa-flask me-1"),
        _t("unit_summary_content.sin_datos_nuevos_hace_semanas_mostrando", STALE_DATA_FALLBACK_WEEKS=STALE_DATA_FALLBACK_WEEKS, reference_strftime=reference.strftime('%d/%m/%Y')),
    ], title=(
        _t("unit_summary_content.no_se_han_recibido_datos_nuevos", STALE_DATA_FALLBACK_WEEKS=STALE_DATA_FALLBACK_WEEKS)
    ), style={
        "fontSize": "10px", "color": "#854f0b", "background": "#faeeda",
        "padding": "2px 6px", "borderRadius": "3px", "whiteSpace": "nowrap",
    })


def _section_card(title: str, period_label: str, body, note=None, icon: str = None,
                   period_icon: str = "fas fa-calendar-alt", status: str = None,
                   section_id: str = None, summary: str = None, freshness: str = None) -> dbc.Card:
    """Standard card structure (ui_notes.md "Card Components"): CardHeader
    with an H5 + icon on a light background, shadow-sm on the card itself.
    The reference-period label + optional stale-data note sit at the top of
    the body, right above the chart/content, styled like the guide's Info
    Tooltip pattern (small, muted, calendar icon by default - `period_icon`
    swaps it for sections whose label isn't a time period, e.g. a count).

    `status`, when given, renders the status chip next to the title
    (05_unit_summary_restructure_and_predictive_comparison.md, Required Changes #2) - the
    same chip the Fleet Overview and the tiles draw, so a technique's status can never be
    read differently between them. `summary` is a short line next to it (e.g. "4 en
    Alerta · 6 Normal"); `section_id` is the anchor the technique's status tile links to;
    `freshness` is the "Datos al [fecha] · hace N días" line of a card that shows technique
    data. A card is as tall as its content: only the status tiles are forced to equal height."""
    icon = icon or _section_icon(title)
    header_children = [
        html.H5([html.I(className=f"{icon} me-2"), title], className="mb-0 d-inline-block me-2"),
    ]
    if status is not None:
        header_children.append(status_badge(status))
    if summary:
        header_children.append(html.Span(summary, className="unit-muted small unit-card-summary"))
    period_row = [
        html.I(className=f"{period_icon} me-1"),
        html.Span(period_label, className="unit-muted small"),
    ]
    if note is not None:
        period_row.append(note)
    if freshness:
        period_row.append(html.Span([html.I(className="far fa-clock me-1", **{"aria-hidden": "true"}), freshness],
                                    className="unit-muted small unit-freshness"))
    return dbc.Card([
        dbc.CardHeader(
            html.Div(header_children, style={"display": "flex", "alignItems": "center", "gap": "8px", "flexWrap": "wrap"}),
            className="bg-light",
        ),
        dbc.CardBody([
            html.Div(period_row, className="mb-2", style={
                "display": "flex", "alignItems": "center", "gap": "6px", "flexWrap": "wrap",
            }),
            body,
        ]),
    ], className="shadow-sm mb-0 unit-card", **({"id": section_id} if section_id else {}))


def _empty_body(message: str) -> html.Div:
    return html.Div([
        html.I(className="fas fa-info-circle mb-2 text-muted d-block", style={"fontSize": "20px"}),
        message,
    ], className="unit-muted text-center small", style={"padding": "28px 8px"})


def _grid(cards: list) -> html.Div:
    return html.Div(cards, style={
        "display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(340px, 1fr))",
        "gap": "16px", "marginBottom": "16px",
    })


# ── Rows by severity (Telemetría and Tribología) ─────────────────────────────

_COUNT_SUMMARY_KEYS = (
    ("Anormal", "unit_summary_content.count_abnormal"),
    ("Alerta", "unit_summary_content.count_alert"),
    ("Sin Datos", "unit_summary_content.count_no_data"),
    ("Normal", "unit_summary_content.count_normal"),
)


def _count_summary(statuses: Sequence[str]) -> str:
    """"4 en Alerta · 6 Normal": how many components sit in each status, worst first,
    leaving out the statuses nobody is in."""
    canonical = [canonical_status(s) for s in statuses]
    parts = [
        _t(key, count=canonical.count(status))
        for status, key in _COUNT_SUMMARY_KEYS if canonical.count(status)
    ]
    return " · ".join(parts)


def _severity_order(rows: list) -> list:
    """`(status, cells)` rows worst-first; the sort is stable, so ties keep the caller's order."""
    return sorted(rows, key=lambda row: -priority_of(canonical_status(row[0])))


def _status_table(columns: Sequence[str], widths: Sequence[str], rows: list, show_header: bool = True) -> html.Table:
    """A table with fixed column widths (so the visible and the collapsed Normal tables
    line up). With `show_header=False` the header stays for screen readers only."""
    header = html.Thead(
        html.Tr([html.Th(c, scope="col") for c in columns]),
        className=None if show_header else "visually-hidden",
    )
    return html.Table(
        [
            html.Colgroup([html.Col(style={"width": w}) for w in widths]),
            header,
            html.Tbody([html.Tr([html.Td(cell) for cell in row]) for row in rows]),
        ],
        className="unit-rows-table",
    )


def _rows_by_severity(columns: Sequence[str], widths: Sequence[str], rows: list) -> html.Div:
    """`(raw status, cells)` rows, worst-first, as a table; the Normal ones go behind a
    native `<details>` toggle - keyboard operable - when there are more than
    `MAX_VISIBLE_NORMAL`, otherwise every row is visible. Alerta, Anormal and rows without a
    reading are never hidden."""
    normal = [cells for status, cells in rows if canonical_status(status) == "Normal"]
    shown = [cells for status, cells in rows if canonical_status(status) != "Normal"]
    if len(normal) <= MAX_VISIBLE_NORMAL:
        return html.Div(_status_table(columns, widths, [cells for _status, cells in rows]))
    children = []
    if shown:
        children.append(_status_table(columns, widths, shown))
    children.append(html.Details(
        [
            html.Summary(_t("unit_summary_content.show_normal", count=len(normal)), className="unit-normal-toggle"),
            _status_table(columns, widths, normal, show_header=not shown),
        ],
        className="unit-normal-details",
    ))
    return html.Div(children)


# ── Freshness ────────────────────────────────────────────────────────────────

def _age_ago(then: pd.Timestamp) -> str:
    days = (datetime.now().date() - then.date()).days
    if days <= 0:
        return _t("unit_summary_content.ago_today")
    if days == 1:
        return _t("unit_summary_content.ago_one_day")
    return _t("unit_summary_content.ago_days", count=days)


def _freshness_caption(data_date: Optional[pd.Timestamp]) -> Optional[str]:
    """"Datos al 03/08/2026 · hace 84 días": what every card and tile that shows technique data
    says about how old that data is. None when there is no date."""
    if data_date is None or pd.isna(data_date):
        return None
    data_date = pd.Timestamp(data_date)
    return _t("unit_summary_content.data_as_of_ago", date=data_date.strftime("%d/%m/%Y"), age=_age_ago(data_date))


# ── Alerts ───────────────────────────────────────────────────────────────────

def _alerts_section(client: str, unit: str, status: str = None) -> dbc.Card:
    df = load_alerts_data(client)
    timestamps = pd.Series(dtype="datetime64[ns]")
    if not df.empty and "UnitId" in df.columns:
        timestamps = pd.to_datetime(df["Timestamp"], errors="coerce")

    reference, is_fallback = _reference_time(timestamps.max() if not timestamps.empty else None)

    period_label = _t("unit_summary_content.ultimos_dias", ALERTS_WINDOW_DAYS=ALERTS_WINDOW_DAYS)
    note = _fallback_note(reference) if is_fallback else None

    unit_df = pd.DataFrame()
    if not df.empty and "UnitId" in df.columns:
        cutoff = reference - pd.Timedelta(days=ALERTS_WINDOW_DAYS)
        unit_df = df[(df["UnitId"].astype(str) == unit) & (timestamps >= cutoff)]

    if unit_df.empty:
        # On a stale feed the window is anchored to `reference`, so the empty
        # state must name that same date as the banner above it - otherwise
        # "no alerts in the last 30 days" reads as a claim about today that the
        # banner contradicts (10_...md Required Changes #3).
        if is_fallback:
            message = _t(
                "unit_summary_content.sin_alertas_registradas_con_referencia",
                ALERTS_WINDOW_DAYS=ALERTS_WINDOW_DAYS, reference_strftime=reference.strftime('%d/%m/%Y'),
            )
        else:
            message = _t("unit_summary_content.sin_alertas_registradas_en_los_ultimos", ALERTS_WINDOW_DAYS=ALERTS_WINDOW_DAYS)
        body = _empty_body(message)
    else:
        body = dcc.Graph(figure=create_alerts_per_week_chart(unit_df), config={"displayModeBar": False})
    return _section_card(_t("unit_summary_content.section_alerts"), period_label, body, note=note, status=status,
                         section_id=SECTION_IDS["alerts"], freshness=_freshness_caption(_alerts_data_date(client)))


# ── Telemetry ────────────────────────────────────────────────────────────────

def _age_text(age: timedelta) -> str:
    """"2 h", "24 h", "40 días", "3 semanas": a threshold age the way a person says it."""
    if age >= timedelta(weeks=2) and age % timedelta(weeks=1) == timedelta(0):
        return _t("unit_summary_content.age_weeks", count=age // timedelta(weeks=1))
    if age >= timedelta(days=2):
        return _t("unit_summary_content.age_days", count=age.days)
    return _t("unit_summary_content.age_hours", count=int(age.total_seconds() // 3600))


def _telemetry_rule_note() -> html.Div:
    """Why a technique can read Anormal while none of its systems does. The thresholds in
    the text are the ones the rule uses (config/estado_rules.py + config/freshness_thresholds.py),
    so the sentence cannot drift from the logic."""
    sentences = [_t("unit_summary_content.telemetry_rule")]
    limits = staleness_floor_limits("Telemetria")
    for estado, key in (("Alerta", "unit_summary_content.stale_to_alert"), ("Anormal", "unit_summary_content.stale_to_abnormal")):
        if estado in limits:
            sentences.append(_t(key, age=_age_text(limits[estado])))
    return html.Div(
        [html.I(className="fas fa-info-circle me-1"), " ".join(sentences)],
        className="text-muted small mb-2 unit-rule-note",
    )


def _telemetry_data_date(client: str, unit: str) -> Optional[pd.Timestamp]:
    df = load_telemetry_system_health(client)
    unit_col = "unit" if "unit" in df.columns else ("unit_id" if "unit_id" in df.columns else None)
    if df.empty or not unit_col or "evaluation_timestamp" not in df.columns:
        return None
    stamps = pd.to_datetime(df.loc[df[unit_col].astype(str) == unit, "evaluation_timestamp"], errors="coerce").dropna()
    return None if stamps.empty else stamps.max()


def _telemetry_section(client: str, unit: str, status: str = None) -> dbc.Card:
    df = load_telemetry_system_health(client)
    unit_col = "unit" if "unit" in df.columns else ("unit_id" if "unit_id" in df.columns else None)
    unit_df = pd.DataFrame()
    if not df.empty and unit_col:
        unit_df = df[df[unit_col].astype(str) == unit]

    period_label = _t("unit_summary_content.semana_mas_reciente")
    if not unit_df.empty and {"week", "year"}.issubset(unit_df.columns):
        try:
            period_label += f" ({_t('unit_summary_content.semana', int_unit_df_week_i=int(unit_df['week'].iloc[0]), int_unit_df_year_i=int(unit_df['year'].iloc[0]))})"
        except (TypeError, ValueError):
            pass

    status_col = "system_status" if "system_status" in unit_df.columns else "status"
    if unit_df.empty or status_col not in unit_df.columns or "system" not in unit_df.columns:
        body = _empty_body(_t("unit_summary_content.sin_evaluacion_de_telemetria_disponible_pa"))
        summary = None
    else:
        # One row per system with its status, worst first. The system score still orders
        # rows inside a status, but it is not shown: the status says it.
        ordered = unit_df.assign(_score=pd.to_numeric(unit_df.get("system_score"), errors="coerce")).sort_values(
            "_score", ascending=False, na_position="last", kind="stable",
        )
        rows = _severity_order([
            (r[status_col], [display_system_name(r["system"]), status_chip(r[status_col])]) for _, r in ordered.iterrows()
        ])
        body = html.Div([
            _telemetry_rule_note(),
            _rows_by_severity([_t("unit_summary_content.col_system"), _t("fleet_overview.col_status")], ["190px", "auto"], rows),
        ])
        summary = _count_summary([raw for raw, _cells in rows])
    return _section_card(_t("unit_summary_content.section_telemetry"), period_label, body, status=status,
                         section_id=SECTION_IDS["telemetry"], summary=summary,
                         freshness=_freshness_caption(_telemetry_data_date(client, unit)))


# ── Oil ──────────────────────────────────────────────────────────────────────

def _oil_data_date(rows: Optional[Sequence[OilComponentRow]]) -> Optional[pd.Timestamp]:
    dates = [r.sample_date for r in rows or [] if r.sample_date is not None]
    return max(dates) if dates else None


def _diagnosis_toggle(row: OilComponentRow) -> html.Details:
    """The row's "Ver Diagnóstico" toggle: a native `<details>`, so it opens by click,
    Enter or Space on the summary and not by hovering."""
    return html.Details(
        [
            html.Summary(_t("unit_summary_content.ver_diagnostico"), className="unit-diagnosis-toggle"),
            html.P(row.diagnosis or _t("oil_machine_detail.sin_recomendacion"), className="unit-diagnosis-text"),
        ],
        className="unit-diagnosis",
    )


def _oil_section(client: str, unit: str, status: str = None) -> dbc.Card:
    components = unit_oil_components(client, unit)

    period_label = _t("unit_summary_content.muestra_mas_reciente")
    latest = _oil_data_date(components)

    summary = None
    if not components:
        body = _empty_body(_t("unit_summary_content.sin_muestras_de_aceite_registradas_para"))
    else:
        rows = [
            (c.status, [c.component, status_chip(c.status), c.anomaly or "—", _diagnosis_toggle(c)])
            for c in components
        ]
        body = _rows_by_severity(
            [
                _t("unit_summary_content.col_component"), _t("fleet_overview.col_status"),
                _t("oil_machine_detail.anomalia"), _t("unit_summary_content.col_diagnosis"),
            ],
            ["210px", "110px", "190px", "auto"], rows,
        )
        summary = _count_summary([c.status for c in components])
    return _section_card(_t("unit_summary_content.section_oil"), period_label, body, status=status,
                         section_id=SECTION_IDS["oil"], summary=summary, freshness=_freshness_caption(latest))


# ── Predictive Models ────────────────────────────────────────────────────────

def _predictive_run_date(client: str, components: list) -> Optional[pd.Timestamp]:
    """Oldest model run date across the enabled components: the one the technique's
    freshness (and so its Estado) is judged by."""
    from src.data.loaders import get_model_run_date

    dates = [d for d in (get_model_run_date(client, c) for c in components) if d is not None]
    return pd.Timestamp(min(dates)) if dates else None


def _fleet_position_title(client: str, component: str) -> str:
    """"Posición en la flota" plus the two metrics the scatter really plots: the axes
    configured for this client and component (Settings.get_fleet_scatter_axes), named as
    the chart names them."""
    from dashboard.components.predictive_charts import SCATTER_AXIS_FIELDS

    title = _t("tab_predictive_overview.posicion_en_la_flota")
    axes = get_settings().get_fleet_scatter_axes(client, component)
    if not axes:
        return title
    x_title, y_title = (_t(SCATTER_AXIS_FIELDS[field][1]) for field in axes)
    return _t("unit_summary_content.fleet_position_axes", title=title, x=x_title, y=y_title)


def _unit_row_in(latest: pd.DataFrame, unit: str) -> Optional[pd.Series]:
    """The unit's row of the Predictivo tab's per-unit frame (zero-padded ids match too)."""
    from dashboard.tabs.tab_predictive_overview import _normalize_unit_id

    rows = latest[latest["Unit"] == unit]
    if rows.empty:
        rows = latest[latest["Unit"].map(_normalize_unit_id) == _normalize_unit_id(unit)]
    return None if rows.empty else rows.iloc[0]


def _predictive_card(client: str, unit: str, component: str) -> dbc.Card:
    """One predictive component's card. The two charts come from the same code and the same
    per-unit frame as the Predictivo tab: the fleet scatter is `short_view_chart` (the Short
    View's drawable units, axes, thresholds and zones, with this unit highlighted) and the risk
    profile is `create_comparative_bars` on the Evidence frame. Every metric name shown (the
    ranking, the scatter's axes) is the predictive layer's own."""
    from dashboard.components.predictive_charts import SCATTER_AXIS_FIELDS, create_comparative_bars
    from dashboard.components.predictive_config import resolve_failure_modes
    from src.data.loaders import get_model_run_date

    title = _t("unit_summary_content.predictivo", translate_componen=display_component_name(component))
    run_date = get_model_run_date(client, component)
    freshness = _freshness_caption(pd.Timestamp(run_date)) if run_date else None
    period_label = _t("unit_summary_content.ejecucion_del_modelo") if run_date else _t("unit_summary_content.sin_fecha_de_ejecucion")

    status, _ranking = get_predictive_component_status(client, unit, component)

    # Two distinct "no data" cases collapse to the same no-charts state
    # (07_unit_summary_revision_2.md Required Changes #5): `status is None` is the confirmed
    # no-data fallback (00_implementation_guide.md §3.1 - an absent/no-record unit for this
    # component's latest run, e.g. Predictivo · Transmisión for T_11), and `status == "Sin
    # Datos"` is the "no reading" result. Stale data is NOT one of them: it keeps its real
    # record and charts and is flagged through the merged status (same rule as the Fleet
    # Overview), so the card stays consistent with the table once the pipeline is current.
    if status is None or status == "Sin Datos":
        return _section_card(title, period_label, _empty_body(
            _t("unit_summary_content.sin_datos_de_modelo_para_esta")
        ), icon=_PREDICTIVE_ICON, status="Sin Datos", freshness=freshness)

    latest = load_status_frame(client, component)
    row = _unit_row_in(latest, unit) if latest is not None else None

    # "Ranking hoy": the latest daily value of the predictive data, "—" when there is none; the
    # same label for every component. (The status above may be worsened by stale data; the
    # value is not: it is what the model last said.)
    today = row.get("ranking") if row is not None else None
    ranking_header = html.Div([
        html.Span(f"{_t(SCATTER_AXIS_FIELDS['ranking_today'][1])}: ", className="unit-muted small"),
        html.Strong(f"{today:.0f}" if isinstance(today, (int, float)) and pd.notna(today) else "—"),
    ], className="mb-3")

    if row is None:
        comparison = _empty_body(_t("unit_summary_content.sin_datos_de_comparacion_de_flota"))
    else:
        scatter_fig = short_view_chart(latest, client, component, selected_unit=row["Unit"])
        bar_fig = create_comparative_bars(row, latest, resolve_failure_modes(component, client))
        comparison = html.Div([
            html.Div([
                html.Div(_fleet_position_title(client, component), className="unit-muted small mb-1"),
                dcc.Graph(figure=scatter_fig, className=CHART_ASPECT_CLASS, responsive=True,
                          config={"displayModeBar": False}),
            ]),
            html.Div([
                html.Div(_t("unit_summary_content.perfil_de_riesgo_por_modo_de"), className="unit-muted small mb-1"),
                dcc.Graph(figure=bar_fig, config={"displayModeBar": False}),
            ]),
        ], className="unit-predictive-charts")
    return _section_card(title, period_label, html.Div([ranking_header, comparison]), icon=_PREDICTIVE_ICON,
                         status=status, freshness=freshness)


PREDICTIVE_TAB_TYPE = "unit-predictive-tab"
PREDICTIVE_PANEL_ID = "unit-predictive-panel"


def _predictive_tab_label(component: str, status: str) -> str:
    return f"{display_component_name(component)} · {status_label(status)}"


def _predictive_tab(component: str, status: str, selected: bool) -> html.Button:
    """One component's tab: a real `<button role="tab">`. The selected one is the only tab stop;
    the arrow keys move between them (assets/client_nav.js)."""
    return html.Button(
        _predictive_tab_label(component, status),
        id={"type": PREDICTIVE_TAB_TYPE, "component": component},
        type="button", n_clicks=0, tabIndex=0 if selected else -1,
        className="unit-tab" + (" unit-tab--selected" if selected else ""),
        role="tab", **{"aria-selected": "true" if selected else "false", "aria-controls": PREDICTIVE_PANEL_ID},
    )


def predictive_tab_states(client: str, unit: str, components: list, selected: str) -> list:
    """`(className, aria-selected, tabIndex)` of each component's tab, `selected` being the open one."""
    return [
        ("unit-tab" + (" unit-tab--selected" if component == selected else ""),
         "true" if component == selected else "false", 0 if component == selected else -1)
        for component in components
    ]


def predictive_card(client: str, unit: str, component: str) -> dbc.Card:
    """The card of one predictive component (what a tab opens)."""
    return _predictive_card(client, unit, component)


def _predictive_sections(client: str, unit: str, components: list) -> list:
    """The Predictivo content: the component's card when there is one component, otherwise a
    tab per component labeled with its name and status ("Motor · Anormal"). Only the selected
    component's charts exist in the page: choosing a tab renders that component's card
    (dashboard/callbacks/unit_summary_callbacks.py)."""
    if len(components) <= 1:
        return [_predictive_card(client, unit, c) for c in components]
    tabs = [
        _predictive_tab(c, get_predictive_component_status(client, unit, c)[0] or "Sin Datos", c == components[0])
        for c in components
    ]
    return [html.Div([
        html.Div(tabs, className="unit-tablist", role="tablist", **{"aria-label": _t("unit_summary_content.predictive_tabs")}),
        html.Div(_predictive_card(client, unit, components[0]), id=PREDICTIVE_PANEL_ID, role="tabpanel", className="unit-tabpanel"),
    ], className="unit-tabs")]


# ── Maintenance ──────────────────────────────────────────────────────────────
# The standalone Mantenciones summary card (record count + "Sistemas
# involucrados") was dropped from this view by 07_unit_summary_revision_2.md
# Required Changes #3 - judged redundant next to the Pareto chart below, which
# already conveys that information with more analytical value. That
# record-count/systems-involved data still lives in the Mantenciones module
# itself (Functional Rules: "removes it from this view only"). The Pareto is
# information, not a status: its card has no chip.

def _fit_pareto_figure(fig):
    """Keep the Mantenciones Pareto inside this card at any number of systems: one color for
    every bar (a system is not a category here), every axis label written out in full - the
    axis is `automargin`, so the plot area shrinks to whatever room the labels need instead of
    drawing past the card's edge - and the figure height fixed to the container
    (`PARETO_HEIGHT`)."""
    from dashboard.tabs.tab_mantenciones_general import PARETO_BAR_COLOR

    names = [str(x) for x in (fig.data[0].x if fig.data else [])]
    if fig.data:
        fig.data[0].marker.color = PARETO_BAR_COLOR
    if names:
        fig.update_xaxes(tickmode="array", tickvals=names, ticktext=names)
    fig.update_xaxes(automargin=True, tickangle=-35, tickfont={"size": 11}, title_standoff=8)
    fig.update_yaxes(automargin=True)
    fig.update_layout(height=PARETO_HEIGHT, margin={"l": 45, "r": 45, "t": 48, "b": 20})
    return fig


def _pareto_period(months: Sequence[str]) -> tuple:
    """`(period, is_current_month)`: the current month when there is data for it, otherwise
    the latest month with data. `(None, False)` when there is none."""
    if not months:
        return None, False
    current = datetime.now().strftime("%Y-%m")
    if current in months:
        return current, True
    return months[-1], False


def _maintenance_pareto_section(client: str, unit: str) -> dbc.Card:
    """Pareto of this unit's corrections by system (05_...md Required
    Changes #4), reusing Mantenciones' own chart function and repository
    query - not a reimplementation. `create_equipment_pareto_chart`
    (dashboard/tabs/tab_mantenciones_general.py) already auto-detects a
    "system_name" dimension and computes the Pareto bars + cumulative-%
    line itself; it's handed `equipment_system_mix`
    (src/data/maintenance_repository.py), the same per-equipment×system
    breakdown the Mantenciones summary page's own equipment chart is built
    from, pre-filtered to this unit via `get_monthly_payload(equipment=
    [unit])`. The card always states its period and whether it is the current month
    or only the latest one with data."""
    from src.data.maintenance_repository import get_repository
    from dashboard.tabs.tab_mantenciones_general import create_equipment_pareto_chart

    period = None
    is_current = False
    payload = None
    try:
        repo = get_repository(mode="parquet", client=client)
        period, is_current = _pareto_period(repo.get_available_months())
        if period:
            payload = repo.get_monthly_payload(period, equipment=[unit])
    except Exception:
        logger.exception("Error loading maintenance Pareto for client=%s unit=%s", client, unit)

    if period:
        period_label = _t(
            "unit_summary_content.periodo_mes_en_curso" if is_current else "unit_summary_content.periodo_ultimo_con_datos",
            period=period,
        )
    else:
        period_label = _t("oil_machine_detail.sin_datos")
    mix = pd.DataFrame(payload["data"].get("equipment_system_mix", [])) if payload and payload.get("status") == "ok" else pd.DataFrame()

    if mix.empty or "system_name" not in mix.columns:
        body = _empty_body(_t("unit_summary_content.sin_correcciones_registradas_para_esta_uni"))
    else:
        fig = _fit_pareto_figure(
            create_equipment_pareto_chart(mix[["system_name", "count"]], system_label=_t("unit_summary_content.sistemas"))
        )
        body = dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"height": f"{PARETO_HEIGHT}px"})
    return _section_card(_t("unit_summary_content.pareto_de_correcciones_por_sistema"), period_label, body, icon="fas fa-chart-bar")


# ── Monitored components (banner) ────────────────────────────────────────────

def _oil_component_details(row) -> list:
    raw = row.get("component_details")
    if isinstance(raw, list):
        return [d for d in raw if isinstance(d, dict)]
    if hasattr(raw, "tolist"):
        return [d for d in raw.tolist() if isinstance(d, dict)]
    return []


def monitored_components(client: str, unit: str) -> list:
    """Components monitored for this unit, sourced from the Oil dataset only (10_...md
    Required Changes #6, superseding the Alerts + Oil union of 03_...md §3.4): Alerts'
    `componente` is deliberately not read, and this reads `load_machine_status_for_client`
    directly rather than any shared component-vocabulary helper, so an Alerts-derived entry
    can't come back through one. Uppercased, deduplicated and labeled via
    `display_component_name()`. The banner shows how many there are."""
    components = set()
    df_oil = load_machine_status_for_client(client)
    unit_col = "unit_id" if "unit_id" in df_oil.columns else ("equipo" if "equipo" in df_oil.columns else None)
    if not df_oil.empty and unit_col:
        match = df_oil[df_oil[unit_col].astype(str) == unit]
        for _, row in match.iterrows():
            for detail in _oil_component_details(row):
                comp = str(detail.get("component", "")).strip()
                if comp:
                    components.add(comp.upper())
    return sorted({display_component_name(c) for c in components})


def last_sample_date(client: str, unit: str) -> Optional[pd.Timestamp]:
    """Date of the unit's most recent oil sample (the banner's "Última muestra"), or None."""
    return _oil_data_date(unit_oil_components(client, unit))


# ── Status tiles ─────────────────────────────────────────────────────────────

def _alerts_data_date(client: str) -> Optional[pd.Timestamp]:
    df = load_alerts_data(client)
    if df.empty or "Timestamp" not in df.columns:
        return None
    latest = pd.to_datetime(df["Timestamp"], errors="coerce").max()
    return None if pd.isna(latest) else pd.Timestamp(latest)


def _technique_data_date(client: str, unit: str, technique: str, predictive_components: list) -> Optional[pd.Timestamp]:
    """The date of the data behind a technique's status: the alert feed's latest
    timestamp, the unit's latest telemetry evaluation, its latest oil sample, or the oldest
    model run across the enabled predictive components."""
    try:
        if technique == "alerts":
            return _alerts_data_date(client)
        if technique == "telemetry":
            return _telemetry_data_date(client, unit)
        if technique == "oil":
            return _oil_data_date(unit_oil_components(client, unit))
        if technique == "predictive":
            return _predictive_run_date(client, predictive_components)
    except Exception:
        logger.exception("Could not resolve the data date of %s for client=%s unit=%s", technique, client, unit)
    return None


def _status_tile(technique: str, status: str, data_date: Optional[pd.Timestamp]) -> html.A:
    """One technique's tile: name, status chip, data date, and a link to its section."""
    date_text = _freshness_caption(data_date) or _t("unit_summary_content.tile_no_date")
    return html.A(
        [
            html.Div([
                html.Span(html.I(className=_TILE_ICONS[technique]), className="icon-badge icon-badge--nodata", **{"aria-hidden": "true"}),
                html.Span(technique_label(technique), className="unit-tile__name"),
            ], className="unit-tile__head"),
            status_chip(status),
            html.Div(date_text, className="unit-tile__date unit-muted"),
            html.Span([_t("unit_summary_content.tile_go_to_section"), html.I(className="fas fa-arrow-down ms-1", **{"aria-hidden": "true"})],
                      className="unit-tile__link"),
        ],
        href=f"#{SECTION_IDS[technique]}",
        className="unit-tile",
    )


def build_status_tiles(client: str, unit: str, technique_status: dict) -> Optional[html.Section]:
    """"Estado por Técnica": one tile per monitored technique that has a status - Telemetría
    (when the client has it), Alertas, Tribología, Predictivo - in that order, all the same
    height. Mantención has none. `technique_status` is the unit's snapshot, so each tile
    shows exactly the status of the same technique in the Fleet Overview."""
    applicable = applicable_techniques(client)
    predictive_components = enabled_predictive_components(client)
    tiles = []
    for technique in ("telemetry", "alerts", "oil", "predictive"):
        if not applicable.get(technique):
            continue
        tiles.append(_status_tile(
            technique,
            technique_status.get(technique) or "Sin Datos",
            _technique_data_date(client, unit, technique, predictive_components),
        ))
    if not tiles:
        return None
    return html.Section(
        [
            html.H2(_t("unit_summary_content.status_tiles_title"), className="unit-block-title", id="unit-status-tiles-title"),
            html.Div(tiles, className="unit-tiles"),
        ],
        **{"aria-labelledby": "unit-status-tiles-title"},
    )


# ── Top-level orchestration ──────────────────────────────────────────────────

def _worst_status(statuses: list):
    """Worst-of across already-computed per-technique statuses, using the same
    priority ranking Fleet Overview aggregates with - used only to
    label the Monitoreo section header below, never to recompute an
    individual card's own status.

    `None` means "this technique doesn't apply" and is skipped; anything else
    takes part, "Sin Datos" included (priority 0, §3.1): it never outranks a
    real reading, but when it is all there is the result is "Sin Datos" itself,
    not a raw vocabulary leak (InsufficientData/Sin Fuente) and not omitted
    (10_...md Required Changes #2)."""
    present = [s for s in statuses if s is not None]
    if not present:
        return None
    worst = max(present, key=priority_of)
    return worst if priority_of(worst) > 0 else "Sin Datos"


def _section_divider(title: str, icon: str, status) -> html.Div:
    """Visual divider between the stacked Monitoreo/Predictivo sections
    (07_unit_summary_revision_2.md Required Changes #2/#6) - plain text +
    icon + status chip, not a clickable tab. `status` is read from the same
    `technique_status`-derived computation as every card underneath it
    (Functional Rules: "never computed independently"); passing `None` omits
    the chip entirely instead of rendering a fabricated "Sin Datos"."""
    heading = html.H2([html.I(className=f"{icon} me-2"), title],
                      className=f"unit-block-title mb-0 d-inline-block{' me-2' if status is not None else ''}")
    children = [heading, status_badge(status)] if status is not None else [heading]
    return html.Div(children, className="unit-summary-section-divider", style={
        "display": "flex", "alignItems": "center", "gap": "8px", "flexWrap": "wrap",
        "borderBottom": "2px solid var(--border-strong, #dee2e6)", "paddingBottom": "8px",
        "margin": "24px 0 16px",
    })


def _section_body(cards: list, empty_message: str, stacked: bool) -> html.Div:
    if not cards:
        return html.Div(dbc.Alert(
            [html.I(className="fas fa-info-circle me-2"), empty_message], color="info", className="text-center",
        ))
    if stacked:
        # Predictive cards are full width, one under the other (07_...md Required Changes #4):
        # each card's own charts must stay fully legible (Functional Rules).
        return html.Div(cards, style={"display": "flex", "flexDirection": "column", "gap": "16px"},
                        id=SECTION_IDS["predictive"])
    return html.Div(cards, className="unit-stack")


def build_unit_summary_content(client: str, unit: str, technique_status: dict = None) -> html.Div:
    """Build the body of the Unit Detail below the banner:

    1. "Estado por Técnica": one status tile per monitored technique with a status.
    2. A Monitoreo section (Telemetry/Alerts/Oil + the maintenance Pareto) followed by a
       Predictivo section (fleet-comparison per sub-model, stacked vertically when
       there's more than one), stacked one above the other on a single vertical scroll
       instead of behind tabs (07_...md Required Changes #2/#4). With all 4 Monitoreo
       cards present they form a 2x2 grid, Telemetría + Alertas on top, Tribología + the
       Pareto below (09_...md).

    A technique inapplicable for this client contributes no card at all
    (Required Changes #4 of 03_unit_summary_content.md, unchanged here).
    `technique_status` (from fleet_overview.get_unit_snapshot(), passed in by
    unit_summary.py) is the single source every tile's, card's and section divider's
    status is read from - never recalculated independently here (Functional Rules)."""
    technique_status = technique_status or {}
    applicable = applicable_techniques(client)

    # Telemetría and Alertas have similar content (a few status rows, a short chart), so they
    # sit side by side; Tribología and the Pareto are wide and each take the full width. No
    # card is stretched to match a neighbor's height.
    pair = []
    if applicable.get("telemetry"):
        pair.append(_telemetry_section(client, unit, technique_status.get("telemetry")))
    if applicable.get("alerts"):
        pair.append(_alerts_section(client, unit, technique_status.get("alerts")))
    monitoreo_cards = [html.Div(pair, className="unit-pair")] if pair else []
    if applicable.get("oil"):
        monitoreo_cards.append(_oil_section(client, unit, technique_status.get("oil")))
    if applicable.get("maintenance"):
        monitoreo_cards.append(_maintenance_pareto_section(client, unit))

    predictive_components = enabled_predictive_components(client)
    predictivo_cards = _predictive_sections(client, unit, predictive_components) if predictive_components else []

    # Explicit section-level status decision (07_...md Required Changes #6):
    # Monitoreo and Predictivo are functionally distinct domains (observed current state
    # vs. forward-looking model output), so each section divider carries its own worst-of
    # status - both read from the same `technique_status` source, never a third
    # independent computation (Functional Rules). An applicable technique with no status
    # entry counts as "Sin Datos"; only an inapplicable one is left out.
    monitoreo_status = _worst_status([
        technique_status.get(t) or "Sin Datos" for t in ("alerts", "telemetry", "oil") if applicable.get(t)
    ])
    predictivo_status = technique_status.get("predictive")

    return html.Div([
        build_status_tiles(client, unit, technique_status),

        _section_divider(_t("nav.section.monitoring"), _MONITOREO_ICON, monitoreo_status),
        _section_body(monitoreo_cards, _t("unit_summary_content.no_hay_tecnicas_de_monitoreo_habilitadas"), stacked=False),

        _section_divider(_t("fleet_overview.technique_predictive"), _PREDICTIVE_ICON, predictivo_status),
        _section_body(predictivo_cards, _t("unit_summary_content.no_hay_modelos_predictivos_habilitados_par"), stacked=True),
    ])
