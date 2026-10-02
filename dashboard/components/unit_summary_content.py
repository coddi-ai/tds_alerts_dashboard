"""
Unit Summary — per-technique content (Phase 3, restructured by
documentation/general/general_specs/
05_unit_summary_restructure_and_predictive_comparison.md, revised again by
07_unit_summary_revision_2.md).

Implements 03_unit_summary_content.md as revised by 05_...md and 07_...md on
top of the Phase 2 navigation shell (dashboard/components/unit_summary.py):
Componentes Monitoreados at the top, then a Monitoreo section (Alerts/
Telemetry/Oil + the maintenance Pareto - the standalone Mantenciones summary
card was dropped by 07_...md Required Changes #3, the record-count/systems-
involved data it showed remains available in the Mantenciones module itself)
and a Predictivo section (fleet-relative comparisons per sub-model), stacked
one above the other on a single vertical scroll rather than behind tabs
(07_...md Required Changes #2). Each section header is a plain visual
divider, not a clickable tab.

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
existing "most recent week/sample/run" convention, Maintenance keeps its
month-to-date convention (also reused by the Pareto card) - and every
section labels its own reference period on screen.

Every card's status label (05_...md Required Changes #2) is read from
`technique_status`, passed in by the caller (unit_summary.py) from
`fleet_overview.get_unit_snapshot()` - the same per-technique computation
that drives the Fleet Overview cards and the sticky header's badges - never
recalculated independently here.
"""

from src.i18n import t as _t
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from dashboard.components.alerts_charts import create_alerts_per_week_chart
from dashboard.components.fleet_overview import (
    STATUS_PRIORITY,
    applicable_techniques,
    enabled_predictive_components,
    get_predictive_component_status,
    status_badge,
    status_color,
)
from dashboard.components.labels import status_label, translate_component_label
from dashboard.components.oil_machine_detail import build_machine_compact_table
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

# Only Alerts' 30-day window and Maintenance's month-to-date window are
# anchored to wall-clock "now" (Telemetry/Oil/Predictivo already anchor to
# their own latest partition/sample/run, so they never hit this). When a
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

# Neutral bar color for a status with no severity color (e.g. InsufficientData).
# Severity colors themselves come from fleet_overview.status_color(), the same
# mapping the card's status badge uses (10_...md Required Changes #1).
_STATUS_BAR_DEFAULT = "#9ca3af"

# Tribología card default view: the N worst components by severity, the rest
# one click away (10_...md Required Changes #4).
OIL_TOP_COMPONENTS = 4

# Pareto x-axis labels are shortened past this length (full name on hover) so
# they stay inside the card whatever the number of systems (10_...md #5).
PARETO_TICK_MAX_CHARS = 14
PARETO_HEIGHT = 420

# Card-header icon per section, following ui_notes.md's icon table (Alerts /
# Telemetry / Oil already documented there; Maintenance/Predictive/Components
# extend the same "one recognizable icon per concept" convention).
_SECTION_ICONS = {
    "Alertas": "fas fa-exclamation-triangle",
    "Telemetría": "fas fa-signal",
    "Tribología (Aceite)": "fas fa-oil-can",
    "Mantenciones": "fas fa-tools",
    "Componentes Monitoreados": "fas fa-cogs",
}
# Catalog key of each section title above. `_section_card` receives the already-translated
# title, so the icon is found by comparing against the translation, not the Spanish key.
_SECTION_TITLE_KEYS = {
    "Alertas": "unit_summary_content.section_alerts",
    "Telemetría": "unit_summary_content.section_telemetry",
    "Tribología (Aceite)": "unit_summary_content.section_oil",
    "Componentes Monitoreados": "unit_summary_content.section_components",
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

# Shared with tab_predictive_evidence.py's own STATUS_COLORS - the fleet
# scatter/comparative-bars charts reused below (create_fleet_scatter) key
# their status legend off exactly this vocabulary.
_PREDICTIVE_STATUS_COLORS = {"Anormal": "#e24b4a", "Alerta": "#ef9f27", "Normal": "#1d9e75"}


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
                   period_icon: str = "fas fa-calendar-alt", status: str = None) -> dbc.Card:
    """Standard card structure (ui_notes.md "Card Components"): CardHeader
    with an H5 + icon on a light background, shadow-sm on the card itself.
    The reference-period label + optional stale-data note sit at the top of
    the body, right above the chart/content, styled like the guide's Info
    Tooltip pattern (small, muted, calendar icon by default - `period_icon`
    swaps it for sections whose label isn't a time period, e.g. a count).

    `status`, when given, renders `fleet_overview.status_badge()` next to the
    title (05_unit_summary_restructure_and_predictive_comparison.md,
    Required Changes #2) - the exact same badge/colors the Fleet Overview
    cards use, so a technique's status can never be read differently between
    the two views."""
    icon = icon or _section_icon(title)
    header_children = [
        html.H5([html.I(className=f"{icon} me-2"), title], className="mb-0 d-inline-block me-2"),
    ]
    if status is not None:
        header_children.append(status_badge(status))
    period_row = [
        html.I(className=f"{period_icon} me-1"),
        html.Span(period_label, className="text-muted small"),
    ]
    if note is not None:
        period_row.append(note)
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
    ], className="shadow-sm mb-0 h-100")


def _empty_body(message: str) -> html.Div:
    return html.Div([
        html.I(className="fas fa-info-circle mb-2 text-muted d-block", style={"fontSize": "20px"}),
        message,
    ], className="text-muted text-center small", style={"padding": "28px 8px"})


def _grid(cards: list) -> html.Div:
    return html.Div(cards, style={
        "display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(340px, 1fr))",
        "gap": "16px", "marginBottom": "16px",
    })


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
    return _section_card(_t("unit_summary_content.section_alerts"), period_label, body, note=note, status=status)


# ── Telemetry ────────────────────────────────────────────────────────────────

def _telemetry_section(client: str, unit: str, status: str = None) -> dbc.Card:
    df = load_telemetry_system_health(client)
    unit_col = "unit" if "unit" in df.columns else ("unit_id" if "unit_id" in df.columns else None)
    unit_df = pd.DataFrame()
    if not df.empty and unit_col:
        unit_df = df[df[unit_col].astype(str) == unit]

    period_label = _t("unit_summary_content.semana_mas_reciente")
    if not unit_df.empty and {"week", "year"}.issubset(unit_df.columns):
        try:
            period_label = _t("unit_summary_content.semana", int_unit_df_week_i=int(unit_df['week'].iloc[0]), int_unit_df_year_i=int(unit_df['year'].iloc[0]))
        except (TypeError, ValueError):
            pass

    if unit_df.empty or "system_score" not in unit_df.columns:
        body = _empty_body(_t("unit_summary_content.sin_evaluacion_de_telemetria_disponible_pa"))
    else:
        sorted_df = unit_df.sort_values("system_score", ascending=True)
        status_col = "system_status" if "system_status" in sorted_df.columns else "status"
        statuses = sorted_df[status_col] if status_col in sorted_df.columns else pd.Series("", index=sorted_df.index)
        colors = [status_color(s, _STATUS_BAR_DEFAULT) for s in statuses]
        fig = go.Figure(go.Bar(
            x=sorted_df["system_score"], y=sorted_df["system"], orientation="h",
            marker=dict(color=colors),
            text=sorted_df["system_score"].round(1),
            textposition="auto",
            hovertemplate=_t("unit_summary_content.b_b_br_score_extra_extra"),
        ))
        fig.update_layout(
            template="plotly_white", height=max(220, 42 * len(sorted_df)),
            margin=dict(l=10, r=10, t=10, b=30), xaxis_title=_t("unit_summary_content.score_de_sistema"),
        )
        graph = dcc.Graph(figure=fig, config={"displayModeBar": False})
        # The badge is the unit-level merged status (the unit's overall
        # telemetry status vs. data freshness), while the bars are per-system
        # statuses, so a badge worse than every bar has no bar to explain it.
        # Say so rather than leave a red badge above all-green bars.
        worst_bar = max((STATUS_PRIORITY.get(s, 0) for s in statuses), default=0)
        if status is not None and STATUS_PRIORITY.get(status, 0) > worst_bar:
            body = html.Div([
                html.Div(
                    [html.I(className="fas fa-info-circle me-1"),
                     _t("unit_summary_content.estado_tarjeta_no_proviene_de_un_sistema", status=status_label(status))],
                    className="text-muted small mb-2",
                ),
                graph,
            ])
        else:
            body = graph
    return _section_card(_t("unit_summary_content.section_telemetry"), period_label, body, status=status)


# ── Oil ──────────────────────────────────────────────────────────────────────

def _oil_component_details(row) -> list:
    raw = row.get("component_details")
    if isinstance(raw, list):
        return [d for d in raw if isinstance(d, dict)]
    if hasattr(raw, "tolist"):
        return [d for d in raw.tolist() if isinstance(d, dict)]
    return []


def _oil_section(client: str, unit: str, status: str = None) -> dbc.Card:
    df = load_machine_status_for_client(client)
    unit_col = "unit_id" if "unit_id" in df.columns else ("equipo" if "equipo" in df.columns else None)
    row = None
    if not df.empty and unit_col:
        match = df[df[unit_col].astype(str) == unit]
        if not match.empty:
            row = match.iloc[0]

    period_label = _t("unit_summary_content.muestra_mas_reciente")
    details = []
    if row is not None:
        sample_date = row.get("latest_sample_date")
        if pd.notna(sample_date):
            period_label = _t("unit_summary_content.muestra_del", pd_timestamp_sampl=pd.Timestamp(sample_date).strftime('%d/%m/%Y'))
        details = _oil_component_details(row)

    if not details:
        body = _empty_body(_t("unit_summary_content.sin_muestras_de_aceite_registradas_para"))
    else:
        # Compact, transposed version of Monitoring > Oil > General's unit
        # detail (same data source, shared module): components as columns,
        # Estado/Anomalía as rows, AI recommendation as hover text.
        table = build_machine_compact_table(client, unit, top_n=OIL_TOP_COMPONENTS)
        body = table if table is not None else _empty_body(_t("unit_summary_content.sin_muestras_de_aceite_registradas_para"))
    return _section_card(_t("unit_summary_content.section_oil"), period_label, body, status=status)


# ── Predictive Models ────────────────────────────────────────────────────────

def _predictive_sections(client: str, unit: str, components: list) -> list:
    """Per-sub-model Predictivo cards (05_...md Required Changes #5):
    ranking value/label at the top, then the same fleet-comparison
    visualizations already implemented in Predictivo > Evidence - reused
    directly (`create_fleet_scatter`/`create_comparative_bars`,
    dashboard/components/predictive_charts.py), not reimplemented - in place
    of the old raw failure-mode bar chart."""
    from dashboard.components.predictive_charts import create_comparative_bars, create_fleet_scatter
    from dashboard.components.predictive_config import resolve_failure_modes
    from dashboard.tabs.tab_predictive_overview import _discover_components, _load_component_data, attach_status
    from src.data.loaders import get_model_run_date

    filepaths = _discover_components(client)
    cards = []
    for component in components:
        title = _t("unit_summary_content.predictivo", translate_componen=translate_component_label(component))

        run_date = get_model_run_date(client, component)
        period_label = _t("unit_summary_content.ejecucion_del_modelo", pd_timestamp_run_d=pd.Timestamp(run_date).strftime('%d/%m/%Y')) if run_date else _t("unit_summary_content.sin_fecha_de_ejecucion")

        status, ranking = get_predictive_component_status(client, unit, component)

        # Two distinct "no data" cases collapse to the same no-charts state
        # here (07_unit_summary_revision_2.md Required Changes #5):
        # `status is None` is the confirmed no-data fallback
        # (00_implementation_guide.md §3.1, attach_status() - an absent/
        # no-record unit for this component's latest run, e.g. Predictivo ·
        # Transmisión for T_11), and `status == "Sin Datos"` is max_risk's
        # "no reading" result. Stale data is NOT one of them: it keeps its
        # real record and charts and is flagged through the merged status
        # (same `max_risk` rule as the Fleet Overview table), so the card
        # stays consistent with the table once the pipeline is current. A
        # card's status must be computed from the same data that feeds its
        # own charts.
        if status is None or status == "Sin Datos":
            cards.append(_section_card(title, period_label, _empty_body(
                _t("unit_summary_content.sin_datos_de_modelo_para_esta")
            ), icon=_PREDICTIVE_ICON, status="Sin Datos"))
            continue

        ranking_header = html.Div([
            html.Span(_t("unit_summary_content.ranking_general"), className="text-muted small"),
            html.Strong(f"{ranking:.0f}" if isinstance(ranking, (int, float)) and pd.notna(ranking) else "—"),
            html.Span(f" · {status}", className="text-muted small ms-1"),
        ], className="mb-3")

        comparison = None
        filepath = filepaths.get(component)
        if filepath:
            df, df_latest, _extra = _load_component_data(filepath, component, client)
            if df_latest is not None and not df_latest.empty:
                latest = attach_status(df_latest, client, component)
                row_match = latest[latest["Unit"] == unit]
                if not row_match.empty:
                    row = row_match.iloc[0]
                    failure_modes = resolve_failure_modes(component, client)
                    scatter_fig = create_fleet_scatter(latest, unit, _PREDICTIVE_STATUS_COLORS)
                    bar_fig = create_comparative_bars(row, latest, failure_modes)
                    comparison = html.Div([
                        html.Div([
                            html.Div(_t("tab_predictive_overview.posicion_en_la_flota"), className="text-muted small mb-1"),
                            dcc.Graph(figure=scatter_fig, config={"displayModeBar": False}),
                        ]),
                        html.Div([
                            html.Div(_t("unit_summary_content.perfil_de_riesgo_por_modo_de"), className="text-muted small mb-1"),
                            dcc.Graph(figure=bar_fig, config={"displayModeBar": False}),
                        ]),
                    ], style={
                        "display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(320px, 1fr))", "gap": "12px",
                    })

        if comparison is None:
            comparison = _empty_body(_t("unit_summary_content.sin_datos_de_comparacion_de_flota"))

        cards.append(_section_card(
            title, period_label, html.Div([ranking_header, comparison]), icon=_PREDICTIVE_ICON, status=status,
        ))
    return cards


# ── Maintenance ──────────────────────────────────────────────────────────────
# The standalone Mantenciones summary card (record count + "Sistemas
# involucrados") was dropped from this view by 07_unit_summary_revision_2.md
# Required Changes #3 - judged redundant next to the Pareto chart below, which
# already conveys that information with more analytical value. That
# record-count/systems-involved data still lives in the Mantenciones module
# itself (Functional Rules: "removes it from this view only").

def _fit_pareto_figure(fig: go.Figure) -> go.Figure:
    """Keep the Mantenciones Pareto inside this card at any number of systems.

    The shared chart reserves a fixed bottom margin (`b=85`) for its x labels,
    which long system names overflow. Here the labels are shortened (the full
    name stays in the hover, since the bar's x values are untouched) and the
    axis is set to `automargin`, so the plot area shrinks to whatever room the
    labels and axis title need instead of drawing past the card's edge. The
    figure height is fixed to match the container (`PARETO_HEIGHT`)."""
    names = [str(x) for x in (fig.data[0].x if fig.data else [])]
    if names:
        short = [n if len(n) <= PARETO_TICK_MAX_CHARS else n[:PARETO_TICK_MAX_CHARS - 1].rstrip() + "…" for n in names]
        fig.update_xaxes(tickmode="array", tickvals=names, ticktext=short)
    fig.update_xaxes(automargin=True, tickangle=-45, tickfont={"size": 10}, title_standoff=8)
    fig.update_yaxes(automargin=True)
    fig.update_layout(height=PARETO_HEIGHT, margin={"l": 45, "r": 45, "t": 48, "b": 20})
    return fig


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
    [unit])`. Same month-to-date "recent window" §3.5 confirmed rule used
    across this page's other Maintenance-derived sections - the latest
    available month, not a separately invented window."""
    from src.data.maintenance_repository import get_repository
    from dashboard.tabs.tab_mantenciones_general import create_equipment_pareto_chart

    period = None
    payload = None
    try:
        repo = get_repository(mode="parquet", client=client)
        months = repo.get_available_months()
        period = months[-1] if months else None
        if period:
            payload = repo.get_monthly_payload(period, equipment=[unit])
    except Exception:
        logger.exception("Error loading maintenance Pareto for client=%s unit=%s", client, unit)

    period_label = _t("unit_summary_content.mes_en_curso", period=period) if period else _t("oil_machine_detail.sin_datos")
    mix = pd.DataFrame(payload["data"].get("equipment_system_mix", [])) if payload and payload.get("status") == "ok" else pd.DataFrame()

    if mix.empty or "system_name" not in mix.columns:
        body = _empty_body(_t("unit_summary_content.sin_correcciones_registradas_para_esta_uni"))
    else:
        fig = _fit_pareto_figure(
            create_equipment_pareto_chart(mix[["system_name", "count"]], system_label=_t("unit_summary_content.sistemas"))
        )
        body = dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"height": f"{PARETO_HEIGHT}px"})
    return _section_card(_t("unit_summary_content.pareto_de_correcciones_por_sistema"), period_label, body, icon="fas fa-chart-bar")


# ── Monitored components ─────────────────────────────────────────────────────

def _monitored_components_section(client: str, unit: str) -> dbc.Card:
    """Component list for this unit, sourced from the Oil dataset only
    (10_...md Required Changes #6, superseding the Alerts + Oil union of
    03_...md §3.4). Alerts' `componente` is deliberately not read here, and
    this reads `load_machine_status_for_client` directly rather than any
    shared component-vocabulary helper, so an Alerts-derived entry can't come
    back through one. Uppercased and deduplicated, then labeled via
    `translate_component_label()`."""
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

    if not components:
        body = _empty_body(_t("unit_summary_content.sin_componentes_con_datos_de_tribologia"))
        period_label = _t("unit_summary_content.0_componentes")
    else:
        labels = sorted({translate_component_label(c) for c in components})
        period_label = _t("unit_summary_content.componente_s", len_labels=len(labels))
        body = html.Div([
            html.Span(label, className="badge bg-light text-dark border me-1 mb-1")
            for label in labels
        ])
    return _section_card(_t("unit_summary_content.section_components"), period_label, body, period_icon="fas fa-database")


# ── Top-level orchestration ──────────────────────────────────────────────────

def _worst_status(statuses: list):
    """Worst-of across already-computed per-technique statuses, using the same
    STATUS_PRIORITY ranking Fleet Overview aggregates with - used only to
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
    worst = max(present, key=lambda s: STATUS_PRIORITY.get(s, 0))
    return worst if STATUS_PRIORITY.get(worst, 0) > 0 else "Sin Datos"


def _section_divider(title: str, icon: str, status) -> html.Div:
    """Visual divider between the stacked Monitoreo/Predictivo sections
    (07_unit_summary_revision_2.md Required Changes #2/#6) - plain text +
    icon + status badge, not a clickable tab. `status` is read from the same
    `technique_status`-derived computation as every card underneath it
    (Functional Rules: "never computed independently"); passing `None` omits
    the badge entirely instead of rendering a fabricated "Sin Datos"."""
    heading = html.H5([html.I(className=f"{icon} me-2"), title],
                       className=f"mb-0 d-inline-block{' me-2' if status is not None else ''}")
    children = [heading, status_badge(status)] if status is not None else [heading]
    return html.Div(children, className="unit-summary-section-divider", style={
        "display": "flex", "alignItems": "center", "gap": "8px", "flexWrap": "wrap",
        "borderBottom": "2px solid var(--border-strong, #dee2e6)", "paddingBottom": "8px",
        "margin": "24px 0 16px",
    })


def _section_body(cards: list, empty_message: str, stacked: bool, grid_2x2: bool = False) -> html.Div:
    if not cards:
        return html.Div(dbc.Alert(
            [html.I(className="fas fa-info-circle me-2"), empty_message], color="info", className="text-center",
        ))
    if stacked:
        # Predictive sub-model cards stack vertically rather than side by
        # side (07_...md Required Changes #4) - multiple Motor/Transmisión
        # cards are harder to compare when compressed into grid columns, and
        # each card's own charts must stay fully legible (Functional Rules).
        return html.Div(cards, style={"display": "flex", "flexDirection": "column", "gap": "16px"})
    if grid_2x2:
        return html.Div(cards, className="unit-summary-grid-2x2")
    return _grid(cards)


def build_unit_summary_content(client: str, unit: str, technique_status: dict = None) -> html.Div:
    """Build the Phase 3 body for the Unit Summary, as restructured by
    05_unit_summary_restructure_and_predictive_comparison.md and revised by
    07_unit_summary_revision_2.md:

    1. Componentes Monitoreados first, above everything else (Required
       Changes #1 of 05_...md).
    2. A Monitoreo section (Alerts/Telemetry/Oil + the maintenance Pareto)
       followed by a Predictivo section (fleet-comparison per sub-model,
       stacked vertically when there's more than one), stacked one above the
       other on a single vertical scroll instead of behind tabs
       (07_...md Required Changes #2/#4). The standalone Mantenciones
       summary card no longer appears here (07_...md Required Changes #3).
       With all 4 Monitoreo cards present they form a 2x2 grid, Telemetría +
       Alertas on top, Tribología (the Oil > General unit detail, shared via
       oil_machine_detail.py) + Pareto below (09_...md).

    A technique inapplicable for this client contributes no card at all
    (Required Changes #4 of 03_unit_summary_content.md, unchanged here).
    `technique_status` (from fleet_overview.get_unit_snapshot(), passed in by
    unit_summary.py) is the single source every card's status badge and both
    section dividers' status are read from - never recalculated
    independently here (Functional Rules)."""
    technique_status = technique_status or {}
    applicable = applicable_techniques(client)

    # Order is the 2x2 reading order (09_...md Required Changes #2): top row
    # Telemetría then Alertas, bottom row Tribología then Mantención/Pareto.
    monitoreo_cards = []
    if applicable.get("telemetry"):
        monitoreo_cards.append(_telemetry_section(client, unit, technique_status.get("telemetry")))
    if applicable.get("alerts"):
        monitoreo_cards.append(_alerts_section(client, unit, technique_status.get("alerts")))
    if applicable.get("oil"):
        monitoreo_cards.append(_oil_section(client, unit, technique_status.get("oil")))
    if applicable.get("maintenance"):
        monitoreo_cards.append(_maintenance_pareto_section(client, unit))

    predictive_components = enabled_predictive_components(client)
    predictivo_cards = _predictive_sections(client, unit, predictive_components) if predictive_components else []

    # Explicit section-level status badge decision (07_...md Required
    # Changes #6): the sticky header built by unit_summary.py keeps its
    # existing unit-wide overall/Maintenance badges (global, unchanged) -
    # that's the single "is this unit OK at all" signal used for prev/next
    # and the unit switcher. On top of that, Monitoreo and Predictivo are
    # functionally distinct domains (observed current state vs. forward-
    # looking model output), so each section divider additionally carries its
    # own worst-of status - both read from the same `technique_status`
    # source, never a third independent computation (Functional Rules).
    # An applicable technique with no status entry counts as "Sin Datos"; only
    # an inapplicable one is left out (Maintenance never aggregates, §3.1).
    monitoreo_status = _worst_status([
        technique_status.get(t) or "Sin Datos" for t in ("alerts", "telemetry", "oil") if applicable.get(t)
    ])
    predictivo_status = technique_status.get("predictive")

    return html.Div([
        html.Div(_monitored_components_section(client, unit), style={"marginBottom": "20px"}),

        _section_divider(_t("nav.section.monitoring"), _MONITOREO_ICON, monitoreo_status),
        _section_body(monitoreo_cards, _t("unit_summary_content.no_hay_tecnicas_de_monitoreo_habilitadas"), stacked=False,
                      grid_2x2=len(monitoreo_cards) == MONITOREO_GRID_TECHNIQUES),

        _section_divider(_t("fleet_overview.technique_predictive"), _PREDICTIVE_ICON, predictivo_status),
        _section_body(predictivo_cards, _t("unit_summary_content.no_hay_modelos_predictivos_habilitados_par"), stacked=True),
    ])
