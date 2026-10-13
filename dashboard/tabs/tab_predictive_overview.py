"""
Predictive Overview Tab - Fleet status, KPIs, priority cards, failure mode table.
Supports multi-component model: auto-discovers component CSVs (motor, transmision, etc.)
"""

from src.i18n import t
from dash import html, dcc
import pandas as pd
import re
from functools import lru_cache
from pathlib import Path
from src.utils.logger import get_logger
from dashboard.components.predictive_config import (
    get_failure_modes_dict,
    resolve_failure_modes,
)
from src.data import predictive_v2
from dashboard.components.predictive_kpis import create_kpi_card, create_kpi_row
from dashboard.components.predictive_charts import create_fleet_scatter
from config.settings import get_settings
from src.data.loaders import get_latest_analisis_inteligente, get_model_run_date, load_component_hours
from src.data.fast_io import read_csv as fast_read_csv
from dashboard.components.labels import NO_DATA_BG, NO_DATA_TEXT, status_label

logger = get_logger(__name__)

# Data Contract v2.1 (documentation/predictive/predictive_data_contracts.md §6)
# explains what was previously reported as upstream `estado` being
# "mis-computed": `estado` is derived from the cumulative curve's last-point
# zone for the unit's current cycle, not the flat 30/50/60/80 rule this
# module used to apply client-side - the two were never the same criterion.
# The old rule now travels alongside it as `estado_umbral` (fallback when a
# unit has no curve, audit trail otherwise). Flip back to True only if a
# fresh data sync shows `estado`/`estado_origen`/`estado_umbral` are missing
# or nonsensical (e.g. every unit's `estado_origen` reading "umbral", which
# would mean no unit actually has a curve). Feeds attach_status() below,
# which every status call site (this tab, tab_predictive_evidence.py,
# predictive_callbacks.py) goes through.
COMPUTE_STATUS = False


# ── Data Loading (Multi-Component) ────────────────────────────────────────────

def _discover_components(client: str) -> dict:
    """Auto-discover available components for a client (Change 1: single
    shared discovery function, backed by predictive_v2.discover_predictive_layout).

    Returns {component: Path} where Path is the new-layout `risk_scores`
    partition directory when it exists (preferred - richer data), else the
    legacy CSV file. `_load_component_data` below branches on which kind of
    path it received. This keeps every existing call site working unchanged
    (`components.get(component)` / `if not filepath` / `_load_component_data
    (filepath, component, client)`).
    """
    layout = predictive_v2.discover_predictive_layout(client)
    components = {}
    for component, availability in layout.items():
        if availability.risk_scores:
            components[component] = predictive_v2.risk_scores_base_path(client, component)
        elif availability.legacy_csv is not None:
            components[component] = availability.legacy_csv
    return components


@lru_cache(maxsize=16)
def _load_component_data_cached(
    filepath: str,
    component: str,
    client: str,
    mtime_ns: int,
    size: int,
):
    """Load and precompute predictive data for a single component.

    Cached per (filepath, component, client): this CSV can be 20+MB and the
    rolling-window computation below isn't cheap, so re-parsing it on every
    callback firing (filter change, tab switch) is wasted work. Cache clears
    on process restart, matching the data-refresh boundary already used for
    the other client-keyed loaders in src/data/loaders.py. The only current
    caller treats the returned DataFrames as read-only (copies before any
    mutation) — any future caller that needs to mutate df/df_latest must copy
    first, since these objects are shared across calls.
    """
    filepath = Path(filepath)
    is_legacy_csv = filepath.suffix == ".csv"

    if is_legacy_csv:
        if not filepath.exists():
            logger.warning(f"Predictive data not found: {filepath}")
            return None, None, {}

        df = fast_read_csv(filepath)
        df["Fecha"] = pd.to_datetime(df["Fecha"])
        df = df.copy()  # defragment after column assignment

        # Get component-specific failure modes
        failure_modes = get_failure_modes_dict(component, client)
        fm_keys = list(failure_modes.keys())
    else:
        # New Data Contract v2.0 layout (Change 1/2): `filepath` is the
        # risk_scores partition directory. Pivot the long-format table into
        # the same wide shape the legacy CSV produced (one column per mode
        # + "ranking") so the rolling-window computation below - already
        # written generically off fm_keys/score_cols, not hardcoded column
        # names - keeps working unchanged. fm_keys comes from whatever modes
        # are actually present in this component's data, not from config
        # (Change 3: no hardcoded mode count).
        df_long = predictive_v2.load_risk_scores(client, component)
        if df_long.empty:
            logger.warning(f"No risk_scores data found for {client}/{component}")
            return None, None, {}
        df = predictive_v2.risk_scores_to_wide(df_long)
        fm_keys = [c for c in df.columns if c not in ("Unit", "Fecha", "ranking")]

    score_cols = [c for c in fm_keys if c in df.columns] + ["ranking"]

    # Sort once by Unit+Fecha. Every per-unit "last row" / rolling computation
    # below reuses this ordering instead of re-sorting the full frame again —
    # each Unit's rows are already chronological within their block, which is
    # all groupby("Unit").last()/rolling() need.
    df_sorted = df.sort_values(["Unit", "Fecha"]).copy()

    # Latest snapshot per unit
    df_latest = df_sorted.groupby("Unit").last().reset_index()

    # Rolling averages - compute all at once to avoid fragmentation
    rolling_cols = {}
    for col in score_cols:
        if col in df_sorted.columns:
            grouped = df_sorted.groupby("Unit")[col]
            rolling_cols[f"{col}_30d"] = grouped.transform(
                lambda x: x.rolling(30, min_periods=1).mean()
            )
            rolling_cols[f"{col}_60d"] = grouped.transform(
                lambda x: x.rolling(60, min_periods=1).mean()
            )
            rolling_cols[f"{col}_90d"] = grouped.transform(
                lambda x: x.rolling(90, min_periods=1).mean()
            )

    if rolling_cols:
        df_sorted = pd.concat([df_sorted, pd.DataFrame(rolling_cols, index=df_sorted.index)], axis=1)

    # Get latest rolling values (df_sorted is still Unit+Fecha ordered here —
    # concat above doesn't reorder rows, so no re-sort is needed)
    latest_rolling = df_sorted.groupby("Unit").last().reset_index()

    # Merge rolling into df_latest (all at once to avoid fragmentation)
    new_cols = {}
    new_cols["avg_ranking_30d"] = latest_rolling["ranking_30d"].values if "ranking_30d" in latest_rolling.columns else df_latest["ranking"].values
    new_cols["avg_ranking_60d"] = latest_rolling["ranking_60d"].values if "ranking_60d" in latest_rolling.columns else df_latest["ranking"].values
    new_cols["ranking_acum_90d"] = latest_rolling["ranking_90d"].values if "ranking_90d" in latest_rolling.columns else df_latest["ranking"].values

    # Compute max failure mode 30d average per unit (for status classification)
    fm_30d_cols = [f"{col}_30d" for col in fm_keys if f"{col}_30d" in latest_rolling.columns]
    if fm_30d_cols:
        new_cols["max_fm_30d"] = latest_rolling[fm_30d_cols].max(axis=1).values
        # Also merge individual FM rolling columns (30d, 60d, 90d) for display
        for col in fm_keys:
            for suffix in ["_30d", "_60d", "_90d"]:
                col_name = f"{col}{suffix}"
                if col_name in latest_rolling.columns:
                    new_cols[col_name] = latest_rolling[col_name].values
    else:
        new_cols["max_fm_30d"] = 0.0

    df_latest = df_latest.assign(**new_cols)

    # Previous ranking (second-to-last date)
    dates = sorted(df["Fecha"].unique())
    prev_ranking = {}
    if len(dates) >= 2:
        prev_date = dates[-2]
        df_prev = df[df["Fecha"] == prev_date]
        prev_ranking = dict(zip(df_prev["Unit"], df_prev["ranking"]))

    if not is_legacy_csv:
        # Change 5: the overall ranking's 30d average is precomputed
        # upstream - overwrite the client-side rolling value with
        # unit_status_summary.media_30d wherever that table exists for this
        # client/component, carrying dias_media_30d alongside for coverage.
        # Per-mode 30/60/90d columns (driver bars, sort dropdown) stay
        # client-side rolling - there's no upstream per-mode equivalent and
        # 60d/90d are explicitly out of scope.
        df_status = predictive_v2.load_unit_status_summary(client, component)
        if not df_status.empty and "media_30d" in df_status.columns:
            media_map = dict(zip(df_status["Unit"], df_status["media_30d"]))
            df_latest["avg_ranking_30d"] = (
                df_latest["Unit"].map(media_map).combine_first(df_latest["avg_ranking_30d"])
            )
            if "dias_media_30d" in df_status.columns:
                dias_map = dict(zip(df_status["Unit"], df_status["dias_media_30d"]))
                df_latest["dias_media_30d"] = df_latest["Unit"].map(dias_map)

    return df, df_latest, prev_ranking


def _load_component_data(filepath: Path, component: str, client: str = "cda"):
    """Load a predictive component with invalidation on file generation."""
    filepath = Path(filepath)
    if filepath.suffix == ".csv":
        if not filepath.exists():
            return None, None, {}
        stat = filepath.stat()
        mtime_ns, size = stat.st_mtime_ns, stat.st_size
    else:
        if not filepath.is_dir():
            return None, None, {}
        mtime_ns, size = predictive_v2.risk_scores_generation(client, component)
    result = _load_component_data_cached(
        str(filepath), component, client, mtime_ns, size
    )
    # The cached frames are treated as immutable by the presentation layer.
    # Avoid copying tens of MB when Resumen and Evidencia mount together.
    return result[0], result[1], result[2]


def _norm_unit_id(uid) -> str:
    """T_09 and T_9 are the same unit across sources."""
    m = re.match(r'^([A-Za-z]+_)0*(\d+)$', str(uid))
    return f"{m.group(1)}{m.group(2)}" if m else str(uid)


@lru_cache(maxsize=16)
def _latest_component_meter_cached(client: str, component: str, mtime_ns: int, size: int) -> dict:
    settings = get_settings()
    hours = load_component_hours(settings.get_component_hours_path(client.lower()))
    if hours.empty:
        return {}
    hours = hours[
        (hours["componentName"] == settings.get_component_hours_name(client, component))
        & hours["componentHours_cleaned"].notna()
    ]
    latest = hours.sort_values("sampleDate").groupby("unitId").tail(1)
    return {_norm_unit_id(u): float(h) for u, h in zip(latest["unitId"], latest["componentHours_cleaned"])}


def load_latest_component_meter(client: str, component: str, units) -> dict | None:
    """Latest `componentHours_cleaned` (horómetro) of each unit in `units` for this
    predictive component, from `cleaned_component_hours` of the client's oil golden
    layer ({Unit: hours}; a unit with no reading is absent). None when the client
    has no such source, so callers can leave the meter out altogether."""
    settings = get_settings()
    if not client or str(client).upper() not in [c.upper() for c in settings.component_hours_allowed_clients]:
        return None
    path = settings.get_component_hours_path(client.lower())
    if not path.exists():
        return None
    stat = path.stat()
    by_norm = _latest_component_meter_cached(client, component, stat.st_mtime_ns, stat.st_size)
    return {u: by_norm[_norm_unit_id(u)] for u in units if _norm_unit_id(u) in by_norm}


def make_fleet_scatter(latest, client: str, component: str, selected_unit, status_colors):
    """`create_fleet_scatter` with this client/component's configured quadrant
    thresholds (None -> plain scatter) and each unit's horómetro in the tooltip."""
    return create_fleet_scatter(
        latest, selected_unit, status_colors,
        thresholds=get_settings().get_fleet_scatter_threshold(client, component),
        meter_by_unit=load_latest_component_meter(client, component, latest["Unit"]),
    )


# ── Color helpers ─────────────────────────────────────────────────────────────

def _status_colors(status: str) -> dict:
    return {
        "Anormal": {"border": "#e24b4a", "bg": "#fcebeb", "text": "#a32d2d"},
        "Alerta":  {"border": "#ef9f27", "bg": "#faeeda", "text": "#854f0b"},
        "Normal":  {"border": "#1d9e75", "bg": "#eaf3de", "text": "#3b6d11"},
    }.get(status, {"border": "#888", "bg": "#f0f0f0", "text": "#444"})


# Status sort order: Anormal, then Alerta, then Normal (REQ-PR-07)
_STATUS_RANK = {"Anormal": 0, "Alerta": 1, "Normal": 2}

# Fleet scatter point colors by status (same palette Evidence used for it)
_SCATTER_STATUS_COLORS = {"Anormal": "#e24b4a", "Alerta": "#ef9f27", "Normal": "#1d9e75"}


def _normalize_unit_id(uid) -> str:
    """T_09 -> T_9. Component CSVs zero-pad unit ids; analisis_inteligente.parquet
    doesn't, so lookups against it must normalize both sides first."""
    m = re.match(r"^([A-Za-z]+_)0*(\d+)$", str(uid))
    return f"{m.group(1)}{m.group(2)}" if m else str(uid)


def _classify_status_from_scores(row: pd.Series) -> str:
    """Client-side status classification (temporary, see COMPUTE_STATUS):
    - Anormal: media_30d >= 60 or some mode >= 80 or ranking_of_the_day >= 70
    - Alerta:  media_30d >= 35 or some mode >= 50 or ranking_of_the_day >= 40
    - Normal:  otherwise
    `max_fm_30d` is already the max across per-mode 30d rolling averages
    (computed in _load_component_data_cached), so both mode thresholds check
    against it. `ranking` is the overall ranking's latest (most recent day's
    raw, non-rolling) value.
    """
    media_30d = row.get("avg_ranking_30d")
    max_fm_30d = row.get("max_fm_30d")
    ranking_today = row.get("ranking")
    media_hit = pd.notna(media_30d) and media_30d >= 60
    mode_hit_80 = pd.notna(max_fm_30d) and max_fm_30d >= 80
    today_hit_70 = pd.notna(ranking_today) and ranking_today >= 70
    if media_hit or mode_hit_80 or today_hit_70:
        return "Anormal"
    media_hit = pd.notna(media_30d) and media_30d >= 35
    mode_hit_50 = pd.notna(max_fm_30d) and max_fm_30d >= 50
    today_hit_40 = pd.notna(ranking_today) and ranking_today >= 40
    if media_hit or mode_hit_50 or today_hit_40:
        return "Alerta"
    return "Normal"


def attach_status(latest: pd.DataFrame, client: str, component: str) -> pd.DataFrame:
    """Attach `estado` as `status` (REQ-PR-04).

    Change 4: prefers `unit_status_summary.estado` (Data Contract v2.1 -
    curve-derived, see module-level COMPUTE_STATUS comment) when that table
    exists for this client/component; falls back to
    analisis_inteligente.parquet's `estado` for components not yet migrated
    (e.g. cda/transmision). Units with no row in either show "Sin Datos"
    (Confirmed §3.1, documentation/general/general_specs/00_implementation_guide.md) -
    an absent/no-record unit must never be silently reported as a healthy
    "Normal".

    When COMPUTE_STATUS is True (safety-net override, see module-level
    comment), the estado sources above are bypassed entirely and status is
    instead classified from the 30d scores already present in `latest` via
    _classify_status_from_scores.
    """
    latest = latest.copy()

    if COMPUTE_STATUS:
        latest["status"] = latest.apply(_classify_status_from_scores, axis=1)
        latest["_status_rank"] = latest["status"].map(_STATUS_RANK).fillna(3)
        return latest

    def _estado_map(df, unit_col="Unit", estado_col="estado"):
        if df.empty or estado_col not in df.columns:
            return {}
        # Title-case the raw value: casing isn't guaranteed across sources
        # ("Normal" vs "normal"), but status/color/sort lookups below key
        # off the exact capitalized labels "Normal"/"Alerta"/"Anormal".
        return {
            _normalize_unit_id(u): str(e).strip().title()
            for u, e in zip(df[unit_col], df[estado_col])
        }

    estado_map = {}
    if client:
        status_df = predictive_v2.load_unit_status_summary(client, component)
        estado_map = _estado_map(status_df)
    if not estado_map and client:
        estado_map = _estado_map(get_latest_analisis_inteligente(client, component))

    latest["status"] = latest["Unit"].apply(
        lambda u: estado_map.get(_normalize_unit_id(u), "Sin Datos")
    )
    latest["_status_rank"] = latest["status"].map(_STATUS_RANK).fillna(3)
    return latest


def _score_cell_style(value) -> dict:
    """Cell style for a ranking/score value. `None`/NaN get their own
    neutral style (W34-10) — a missing value must never look like the
    healthiest possible score, which is what green at 0 read as before."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        # Same shared NO_DATA_* tokens the Estado x Unidad and Estado de
        # Datos tables' "no data" badges use (dashboard/components/labels.py)
        # — quality-review follow-up: this used to be its own independent
        # literal, a third copy of the same two values kept in sync only by
        # a comment.
        return {"background": NO_DATA_BG, "text": NO_DATA_TEXT}
    if value >= 70:
        return {"background": "#fcebeb", "text": "#a32d2d"}
    if value >= 40:
        return {"background": "#faeeda", "text": "#854f0b"}
    return {"background": "#eaf3de", "text": "#3b6d11"}


# ── Components ────────────────────────────────────────────────────────────────

# Ranking window options for the bottom table's single ranking column (REQ-PR-09)
_WINDOW_LABEL_KEYS = {
    "ranking": "predictive_overview.window_today",
    "avg_ranking_30d": "predictive_overview.window_avg_30d",
    "avg_ranking_60d": "predictive_overview.window_avg_60d",
    "ranking_acum_90d": "predictive_overview.window_avg_90d",
}
WINDOW_SUFFIX = {
    "ranking": "",
    "avg_ranking_30d": "_30d",
    "avg_ranking_60d": "_60d",
    "ranking_acum_90d": "_90d",
}


def _failure_table(sorted_df, window, sort_by, ascending, failure_modes):
    """Bottom ranking table: one ranking column driven by `window`, plus one
    column per failure mode. `sort_by` is either `window` itself or a failure
    mode key - clicking a failure-mode header sorts by that column (REQ-PR-10)
    while the ranking column stays a single value driven by the window
    dropdown (REQ-PR-09, option ii).
    """
    fm_keys = list(failure_modes.keys())
    fm_labels = list(failure_modes.values())
    fm_suffix = WINDOW_SUFFIX.get(window, "_30d")

    def _arrow(is_active):
        return ("↑" if ascending else "↓") if is_active else ""

    def _th_label(label, is_active):
        return html.Div([
            html.Span(label),
            html.Span(_arrow(is_active), style={
                "marginLeft": "4px", "fontSize": "10px", "opacity": "0.6",
            }),
        ], style={"display": "flex", "alignItems": "center", "gap": "2px"})

    ranking_active = sort_by == window
    ranking_th = html.Th(
        _th_label(t(_WINDOW_LABEL_KEYS.get(window, "predictive_overview.window_avg_30d")), ranking_active),
        className="fm-th fm-th-active" if ranking_active else "fm-th",
    )

    def _fm_th(label, key):
        is_active = key == sort_by
        return html.Th(
            html.Button(
                _th_label(label, is_active),
                id={"type": "predictive-fm-col-header", "key": key},
                n_clicks=0,
                style={
                    "background": "none", "border": "none", "padding": 0, "margin": 0,
                    "font": "inherit", "color": "inherit", "cursor": "pointer", "width": "100%",
                },
            ),
            className="fm-th fm-th-active" if is_active else "fm-th",
        )

    header = html.Thead(html.Tr([
        html.Th(t("alerts_general.filter_unit"), className="fm-th fm-th-unit"),
        ranking_th,
        html.Th(t("tab_telemetry_fleet.estado"), className="fm-th"),  # W34-10: was "Status" (English)
        *[_fm_th(lbl, key) for key, lbl in zip(fm_keys, fm_labels)],
    ]))

    rows = []
    for _, r in sorted_df.iterrows():
        status = r["status"]
        colors = _status_colors(status)
        # W34-10: `pd.notna` before the cast, not a bare `.get(key, 0)` —
        # that only defaults when the KEY is absent, not when the row's
        # VALUE is NaN. A present-but-NaN ranking used to sail through as
        # the literal string "nan", styled green by _score_cell_style's old
        # fall-through. `None` here (never `0.0`) keeps the null
        # distinguishable all the way to render time.
        ranking_val = float(r[window]) if window in r.index and pd.notna(r[window]) else None

        style = _score_cell_style(ranking_val)
        cells = [
            html.Td(r["Unit"], className="fm-td fm-td-unit"),
            html.Td(
                f"{ranking_val:.1f}" if ranking_val is not None else "—",
                className="fm-td fm-td-score fm-td-active" if ranking_active else "fm-td fm-td-score",
                style={"background": style["background"], "color": style["text"],
                       "fontWeight": "600" if ranking_active else "500"},
            ),
            html.Td(
                html.Span(status_label(status), className="status-badge",
                          style={"background": colors["bg"], "color": colors["text"]}),
                className="fm-td",
            ),
        ]

        for key in fm_keys:
            col_name = f"{key}{fm_suffix}" if fm_suffix else key
            # W34-10: None (not 0.0) when the column is absent or the value
            # is NaN — a missing failure-mode score must not render "0" in
            # the same green a genuinely healthy 0 score gets.
            val = float(r[col_name]) if col_name in r.index and pd.notna(r[col_name]) else None
            fm_style = _score_cell_style(val)
            is_sort = key == sort_by
            cells.append(html.Td(
                f"{val:.0f}" if val is not None else "—",
                className="fm-td fm-td-score fm-td-active" if is_sort else "fm-td fm-td-score",
                style={"background": fm_style["background"], "color": fm_style["text"],
                       "fontWeight": "600" if is_sort else "500"},
            ))

        # Clicking the row opens that unit in Evidence (navigate_to_evidence_from_overview)
        rows.append(html.Tr(
            cells, className="fm-tr",
            id={"type": "predictive-fm-row", "unit": r["Unit"]}, n_clicks=0,
        ))

    return html.Div([
        html.Table([header, html.Tbody(rows)], className="fm-table"),
    ], className="fm-table-wrapper")


# ── Component Overview Renderer ───────────────────────────────────────────────

def _render_component_overview(df_latest, prev_ranking, component: str,
                              client: str = None, df=None):
    """
    Render overview content for a specific component.

    Status (Anormal / Alerta / Normal) comes from `estado` - unit_status_summary
    when it exists for this client/component, else analisis_inteligente.parquet
    (REQ-PR-04/05, Change 4). Three layers: KPI hero, the fleet-wide
    ranking-today vs ranking-30d scatter, and the failure-mode table.

    `prev_ranking` and `df` are no longer read (they fed the removed priority
    cards and accumulated curve); they stay in the signature so the existing
    callers don't change.
    """
    failure_modes = resolve_failure_modes(component, client)

    latest = attach_status(df_latest, client, component)
    avg_ranking = float(latest["ranking"].mean())

    counts = latest["status"].value_counts()
    n_anormal = counts.get("Anormal", 0)
    n_alert = counts.get("Alerta", 0)
    n_normal = counts.get("Normal", 0)

    model_run_date = get_model_run_date(client, component) if client else None
    model_run_date_str = model_run_date.strftime("%d %b %Y") if model_run_date is not None else "—"

    hero = html.Div([
        html.Div([
            html.Div([
                html.I(className="fas fa-chart-bar me-2"),
                t("tab_predictive_overview.estado_de_flota", component_title=component.title())
            ], className="page-title", style={"display": "flex", "alignItems": "center"}),
            html.Div(t("tab_predictive_overview.resumen_de_riesgo_operacional_por_unidad", component=component), className="page-subtitle"),
        ], style={"marginBottom": "16px"}),
        create_kpi_row([
            create_kpi_card(f"{avg_ranking:.1f}", t("tab_predictive_overview.ranking_flota"), "fas fa-tachometer-alt", "primary", t("tab_predictive_overview.promedio_actual")),
            create_kpi_card(n_anormal, t("tab_predictive_overview.unidades_anormales"), "fas fa-exclamation-triangle", "danger"),
            create_kpi_card(n_alert, t("tab_predictive_overview.unidades_en_alerta"), "fas fa-exclamation-circle", "warning"),
            create_kpi_card(n_normal, t("tab_predictive_overview.unidades_normales"), "fas fa-check-circle", "success"),
            create_kpi_card(model_run_date_str, t("tab_predictive_overview.fecha_ejecucion_modelo"), "fas fa-calendar-check", "info"),
        ])
    ])

    # Layer 2: the fleet-wide scatter (one point per unit) that used to live in
    # Evidence's "Comparación Flota" - same figure builder, same data, no unit
    # highlighted since no unit is selected on this page.
    scatter_fig = make_fleet_scatter(latest, client, component, None, _SCATTER_STATUS_COLORS)
    risk_section = html.Div([
        html.H4([
            html.I(className="fas fa-shield-alt me-2"),
            t("tab_predictive_overview.analisis_de_riesgo")
        ], className="text-primary mb-3 mt-4"),
        html.Div([
            html.Div([
                html.Span([html.I(className="fas fa-dot-circle me-1"), t("tab_predictive_overview.posicion_en_la_flota")],
                          className="card-subtitle fw-500"),
                html.Span(t("tab_predictive_overview.ranking_actual_vs_riesgo_acumulado_30"),
                          style={"fontSize": "11px", "color": "var(--text-light)"}),
            ], style={"marginBottom": "8px"}),
            # Clicking a point opens that unit in Evidence (navigate_to_evidence_from_overview)
            dcc.Graph(id="predictive-fleet-scatter", figure=scatter_fig, config={"displayModeBar": False}),
        ], className="card shadow-sm", style={"padding": "16px"}),
    ])

    # Failure mode table
    # W34-10: "Unit" as a secondary key makes tie order deterministic across
    # renders — plain `sort_values` on one column falls back to an unstable
    # quicksort for ties, so two identical-input renders could otherwise show
    # tied units in a different order.
    sorted_df = latest.sort_values(["avg_ranking_30d", "Unit"], ascending=[False, True])
    table_section = html.Div([
        html.Div([
            html.Div([
                html.H4([
                    html.I(className="fas fa-table me-2"),
                    t("tab_predictive_overview.riesgo_por_modo_de_falla")
                ], className="text-primary mb-0"),
                html.Div([
                    html.Span(t("tab_predictive_overview.ordenar_por"), className="text-muted me-2",
                              style={"fontSize": "0.85rem", "fontWeight": "500"}),
                    dcc.Dropdown(
                        id="predictive-fm-sort-selector",
                        options=[
                            {"label": t("tab_predictive_overview.hoy"), "value": "ranking"},
                            {"label": t("tab_telemetry_unit_detail.30_dias"), "value": "avg_ranking_30d"},
                            {"label": t("tab_predictive_overview.60_dias"), "value": "avg_ranking_60d"},
                            {"label": t("tab_predictive_overview.90_dias"), "value": "ranking_acum_90d"},
                        ],
                        value="avg_ranking_30d",
                        clearable=False,
                        style={"width": "140px", "fontSize": "0.85rem"},
                    ),
                ], style={"display": "flex", "alignItems": "center"}),
            ], style={
                "display": "flex", "justifyContent": "space-between",
                "alignItems": "center", "borderBottom": "1px solid #dee2e6",
                "paddingBottom": "12px", "marginBottom": "12px",
            }),
            html.P(t("tab_predictive_overview.vista_de_modos_de_falla_por"),
                   className="text-muted mb-3", style={"fontSize": "0.85rem"}),
        ]),
        html.Div(
            _failure_table(sorted_df, "avg_ranking_30d", "avg_ranking_30d", False, failure_modes),
            id="predictive-fm-table-container",
        ),
        dcc.Store(
            id="predictive-fm-table-state",
            data={"window": "avg_ranking_30d", "sort_by": "avg_ranking_30d", "ascending": False},
        ),
    ], className="card", style={"marginTop": "16px"})

    children = [hero, risk_section, table_section]
    return html.Div(children)


# ── Component Icon Map ────────────────────────────────────────────────────────

COMPONENT_ICONS = {
    "motor": "fas fa-cog",
    "transmision": "fas fa-exchange-alt",
    "engine": "fas fa-cog",
}


# ── Main Layout ───────────────────────────────────────────────────────────────

def layout(client: str, component: str):
    """
    Render the predictive overview for a specific component.
    Called by navigation_callbacks with client and component.
    """
    components = _discover_components(client)
    filepath = components.get(component)

    if not filepath:
        return html.Div([
            html.Div([
                html.I(className="fas fa-brain me-3"),
                t("tab_predictive_overview.predictivo_resumen", component_title=component.title())
            ], className="page-title", style={"display": "flex", "alignItems": "center"}),
            html.P(t("tab_predictive_component.no_hay_datos_predictivos_disponibles_para", component=component),
                   className="text-muted", style={"padding": "40px", "textAlign": "center"})
        ])

    df, df_latest, prev_ranking = _load_component_data(filepath, component, client)

    if df_latest is None or df_latest.empty:
        return html.Div([
            html.Div([
                html.I(className="fas fa-brain me-3"),
                t("tab_predictive_overview.predictivo_resumen", component_title=component.title())
            ], className="page-title", style={"display": "flex", "alignItems": "center"}),
            html.P(t("tab_predictive_overview.no_hay_datos_disponibles_para", component=component),
                   className="text-muted", style={"padding": "40px", "textAlign": "center"})
        ])

    return _render_component_overview(df_latest, prev_ranking, component, client)
