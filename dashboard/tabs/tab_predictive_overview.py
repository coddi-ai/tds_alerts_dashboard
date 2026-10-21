"""
Predictive Overview Tab - Fleet status, KPIs, priority cards, failure mode table.
Supports multi-component model: auto-discovers component CSVs (motor, transmision, etc.)
"""

from src.i18n import t
from dash import html, dcc
import numpy as np
import pandas as pd
import re
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple
from src.utils.logger import get_logger
from dashboard.components.predictive_config import (
    get_failure_modes_dict,
    resolve_failure_modes,
)
from src.data import predictive_v2
from dashboard.components.predictive_kpis import create_kpi_card, create_kpi_row
from dashboard.components.predictive_charts import (
    SCATTER_AXIS_FIELDS,
    create_empty_selection_figure,
    create_fleet_scatter,
    classify_criticidad,
    create_long_view_chart,
    get_mode_thresholds,
    scatter_axis_columns,
)
from dashboard.components.predictive_state import STATE_COLORS, combine_states, normalize_state
from dashboard.components import predictive_long_selection as long_sel
from config.settings import get_settings
from src.data.loaders import get_latest_analisis_inteligente, get_model_run_date
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

    # 7-day mean of the daily ranking (Short View's x axis): the real calendar days
    # up to each unit's own last reading - the same anchoring unit_status_summary
    # uses for media_30d. The upstream tables publish no 7-day figure, so this is
    # computed here; a day with no row is skipped, never counted as zero.
    last_day = df_sorted.groupby("Unit")["Fecha"].transform("max")
    last_week = df_sorted[df_sorted["Fecha"] > last_day - pd.Timedelta(days=7)]
    new_cols["avg_ranking_7d"] = df_latest["Unit"].map(last_week.groupby("Unit")["ranking"].mean()).astype(float).values

    # Same 7-day window per failure mode (Evidence's Perfil de riesgo, aligned with
    # the Calendario de estado's trailing 7-day mean).
    week_by_mode = last_week.groupby("Unit")[[c for c in fm_keys if c in last_week.columns]].mean()
    for col in week_by_mode.columns:
        new_cols[f"{col}_7d"] = df_latest["Unit"].map(week_by_mode[col]).astype(float).values

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


def load_active_curve(client: str, component: str):
    """Active-cycle rows of `cumulative_risk_curve` for this client/component,
    read with the metadata-preserving reader, or None when the client has no
    curve data (the Long View's "working on it" case)."""
    if not client:
        return None
    return predictive_v2.load_active_cycle_curve(client, component)


def load_latest_component_meter(client: str, component: str, units) -> dict | None:
    """Component hours of each unit in `units` ({Unit: hours}; a unit with no
    reading is absent), from the Predictivo section's single source:
    `cumulative_risk_curve.componentHours_filled` at the last point of the
    unit's active cycle. The same value feeds the table's Component Hour
    column, the Long View's X axis and the fleet scatter's tooltip. None when
    the client has no curve, so callers can leave the figure out altogether."""
    active = load_active_curve(client, component)
    if active is None:
        return None
    by_norm = {_norm_unit_id(u): h for u, h in predictive_v2.active_cycle_component_hours(active).items()}
    return {u: by_norm[_norm_unit_id(u)] for u in units if _norm_unit_id(u) in by_norm}


def load_unit_component_hours(client: str, component: str, unit):
    """(hours, date) of `unit`'s last active-cycle reading in the same single
    source as `load_latest_component_meter`, for the Evidence unit banner. None
    when the client has no curve or the unit has no reading."""
    active = load_active_curve(client, component)
    if active is None:
        return None
    rows = active[active["Unit"].map(_norm_unit_id) == _norm_unit_id(unit)].dropna(subset=["componentHours_filled"])
    if rows.empty:
        return None
    last = rows.sort_values(["Fecha", "componentHours_filled"]).iloc[-1]
    return float(last["componentHours_filled"]), last["Fecha"]


def attach_component_hours(latest: pd.DataFrame, active) -> pd.DataFrame:
    """Add `component_hours` (NaN where the unit has no reading, or the client no
    curve) to the per-unit frame, from the same source as the Long View."""
    by_norm = {_norm_unit_id(u): h for u, h in predictive_v2.active_cycle_component_hours(active).items()}
    latest = latest.copy()
    latest["component_hours"] = latest["Unit"].map(lambda u: by_norm.get(_norm_unit_id(u))).astype(float)
    return latest


def make_fleet_scatter(latest, client: str, component: str, selected_unit, status_colors, height=380):
    """`create_fleet_scatter` with this client/component's configured axes, quadrant
    thresholds (None -> plain scatter) and each unit's component hours in the tooltip.
    A pair with no configured axes has nothing to plot: a "not configured" message
    figure, never a default pairing."""
    axes = get_settings().get_fleet_scatter_axes(client, component)
    if axes is None:
        logger.warning("No fleet_scatter_axes configured for %s/%s; Short View scatter not drawn", client, component)
        return create_empty_selection_figure("predictive_charts.ejes_sin_configurar")
    return create_fleet_scatter(
        latest, selected_unit, status_colors, axes=axes,
        thresholds=get_settings().get_fleet_scatter_threshold(client, component),
        meter_by_unit=load_latest_component_meter(client, component, latest["Unit"]),
        height=height,
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

# Fleet scatter point colors by status (the palette every Predictivo chart shares)
_SCATTER_STATUS_COLORS = STATE_COLORS


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


def general_states(latest: pd.DataFrame, active) -> pd.Series:
    """Per-unit "general state": the worse of the short-view `status`
    (`unit_status_summary.estado`) and the long-view `estado` of the unit's
    active cycle. Only for the KPI card counts - neither source value is
    overwritten (`latest["status"]` stays the short view's own).

    A unit missing from the curve contributes only its short-view state; with no
    curve at all the general state is just the short view's. None where neither
    source has the unit.
    """
    long_by_unit = {_normalize_unit_id(u): e for u, e in predictive_v2.active_cycle_estado(active).items()}
    return pd.Series(
        [combine_states(s, long_by_unit.get(_normalize_unit_id(u))) for u, s in zip(latest["Unit"], latest["status"])],
        index=latest.index, dtype=object,
    )


def attach_general_status(latest: pd.DataFrame, active) -> pd.DataFrame:
    """Add `general_status`: the worse of the short-view `status` and the long-view
    estado of the unit's active cycle (see `general_states`). It is the Estado the
    failure-mode table and the Evidencia banner show, so both cross-reference the
    two views. `status` stays the short view's own (the Short View scatter keys off
    it); a unit with no curve, or a client with none, keeps its short-view state."""
    latest = latest.copy()
    latest["general_status"] = general_states(latest, active).fillna(latest["status"])
    return latest


def units_missing_from_curve(units, active) -> list:
    """Units with no active-cycle row in the curve - true missing data, not the
    same thing as `evaluable = False` (those arrive as Normal and are trusted)."""
    if active is None:
        return []
    present = {_normalize_unit_id(u) for u in active["Unit"].unique()}
    return sorted(u for u in units if _normalize_unit_id(u) not in present)


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


# Cell tones of the four criticidad bands (Saludable, Monitoreo, Prioridad alta,
# Crítico), the light-background counterparts of the Calendario de estado's colours.
_BAND_CELL_STYLES = (
    {"background": "#eaf3de", "text": "#3b6d11"},
    {"background": "#fdf3c4", "text": "#7a5f00"},
    {"background": "#fde4cf", "text": "#9a4a0a"},
    {"background": "#fcebeb", "text": "#a32d2d"},
)


def _mode_cell_style(value, edges=None) -> dict:
    """Cell style of a failure-mode score. With the mode's calibrated `edges`
    (P75/P90/P98, see predictive_charts.get_mode_thresholds) the cell takes its
    criticidad band; without them it keeps the fixed 40/70 style."""
    if edges is None or value is None or pd.isna(value):
        return _score_cell_style(value)
    return _BAND_CELL_STYLES[classify_criticidad(value, edges)]


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

# Window the bottom table opens on (dropdown value, first sort and stored state)
FAILURE_TABLE_DEFAULT_WINDOW = "ranking_acum_90d"

# Failure modes the data scores but the bottom table does not show a column for
FAILURE_TABLE_HIDDEN_MODES = frozenset({"early_oil_change_risk"})


def _failure_table(sorted_df, window, sort_by, ascending, failure_modes, client=None):
    """Bottom ranking table: one ranking column driven by `window`, plus one
    column per failure mode. `sort_by` is either `window` itself or a failure
    mode key - clicking a failure-mode header sorts by that column (REQ-PR-10)
    while the ranking column stays a single value driven by the window
    dropdown (REQ-PR-09, option ii).

    A failure-mode cell is coloured by the mode's calibrated criticidad edges
    for `client` when it has them (same ones as the Calendario de estado),
    applied to the value shown for the chosen window.
    """
    thresholds = get_mode_thresholds(client)
    shown = {k: lbl for k, lbl in failure_modes.items() if k not in FAILURE_TABLE_HIDDEN_MODES}
    fm_keys = list(shown.keys())
    fm_labels = list(shown.values())
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
        html.Th(t("tab_predictive_overview.component_hour"), className="fm-th"),
        *[_fm_th(lbl, key) for key, lbl in zip(fm_keys, fm_labels)],
    ]))

    rows = []
    for _, r in sorted_df.iterrows():
        # Estado is the general state (short + long view) when the caller attached it
        status = r["general_status"] if "general_status" in r.index else r["status"]
        colors = _status_colors(status)
        # W34-10: `pd.notna` before the cast, not a bare `.get(key, 0)` —
        # that only defaults when the KEY is absent, not when the row's
        # VALUE is NaN. A present-but-NaN ranking used to sail through as
        # the literal string "nan", styled green by _score_cell_style's old
        # fall-through. `None` here (never `0.0`) keeps the null
        # distinguishable all the way to render time.
        ranking_val = float(r[window]) if window in r.index and pd.notna(r[window]) else None

        hours = r["component_hours"] if "component_hours" in r.index else None
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
            html.Td(f"{hours:,.0f}" if pd.notna(hours) else "—", className="fm-td fm-td-score"),
        ]

        for key in fm_keys:
            col_name = f"{key}{fm_suffix}" if fm_suffix else key
            # W34-10: None (not 0.0) when the column is absent or the value
            # is NaN — a missing failure-mode score must not render "0" in
            # the same green a genuinely healthy 0 score gets.
            val = float(r[col_name]) if col_name in r.index and pd.notna(r[col_name]) else None
            fm_style = _mode_cell_style(val, thresholds.get(key))
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


# ── Layer 2: Short View / Long View ───────────────────────────────────────────

LAYER2_TABS_ID = "predictive-layer2-tabs"
LAYER2_CONTENT_ID = "predictive-layer2-content"
LAYER2_SHORT, LAYER2_LONG = "short", "long"
CHART_ASPECT_CLASS = "predictive-chart-ratio"  # predictive_styles.css: aspect-ratio 5 / 2 (2.5:1)


class SelectionPanel(NamedTuple):
    """Component ids of one unit-selection panel: the dropdown, the risk badges, the
    risk-grouped chips and the chart they drive, plus the store holding its
    selection. Short View and Long View each get their own, so selecting units on
    one never touches the other (see `register_selection_callback`)."""
    graph_id: str
    state_id: str
    dropdown_id: str
    chip: str    # pattern-matching `type` of the chips
    badge: str   # pattern-matching `type` of the risk badges

    @property
    def risk_id(self) -> str:
        """Id of the container holding the badges and chips (see `RISK_IDLE_CLASS`)."""
        return f"{self.state_id}-risk"


LONG_PANEL = SelectionPanel(
    "predictive-long-view-graph", "predictive-long-state", "predictive-long-units",
    "predictive-long-chip", "predictive-long-badge",
)
# The Short View's graph keeps its original id: click-to-Evidence listens to it.
SHORT_PANEL = SelectionPanel(
    "predictive-fleet-scatter", "predictive-short-state", "predictive-short-units",
    "predictive-short-chip", "predictive-short-badge",
)
LONG_GRAPH_ID, LONG_STATE_ID, LONG_DROPDOWN_ID, LONG_CHIP, LONG_BADGE = LONG_PANEL
SHORT_GRAPH_ID, SHORT_STATE_ID, SHORT_DROPDOWN_ID, SHORT_CHIP, SHORT_BADGE = SHORT_PANEL


# Badges and chips are relative events ("toggle this unit", "this group"): each is
# applied to the selection stored when its callback starts, so a click made while the
# previous one is still being answered would overwrite it. The container holding them
# is therefore locked (RISK_BUSY_CLASS) for exactly as long as the panel's callback is
# running, so those clicks cannot overlap. The dropdown is not locked: it always sends
# the whole selection, which makes it safe at any speed.
RISK_IDLE_CLASS = "unit-sel-risk"
RISK_BUSY_CLASS = "unit-sel-risk unit-sel-risk--busy"


def _chip_class(selected: bool, state) -> str:
    """A chip is colored by the risk group (state) it sits in; filled when selected."""
    return f"unit-chip unit-chip--{str(state).lower()}" + (" unit-chip--on" if selected else "")


def _badge_class(badge: str, active: bool) -> str:
    return f"unit-badge unit-badge--{badge.lower()}" + (" unit-badge--active" if active else "")


def _selection_controls(panel: SelectionPanel, universe, groups, sel, note_key: str):
    """Dropdown, risk badges and risk-grouped chips, all rendered from one
    `Selection`. Badge counts and group headings are fleet-wide totals: they are
    built once here and never touched by a selection change. `note_key` is the
    i18n key of the note saying the grouping is this chart's own state."""
    selected = set(sel.selected)
    dropdown = dcc.Dropdown(
        id=panel.dropdown_id, options=[{"label": u, "value": u} for u in universe],
        value=list(sel.selected), multi=True, searchable=True, clearable=True,
        placeholder=t("tab_predictive_overview.sel_dd_search"),
        labels={
            "select_all": t("tab_predictive_overview.sel_dd_select_all"),
            "deselect_all": t("tab_predictive_overview.sel_dd_deselect_all"),
            "selected_count": t("tab_predictive_overview.sel_dd_selected_count"),
            "search": t("tab_predictive_overview.sel_dd_search"),
            "clear_search": t("tab_predictive_overview.sel_dd_clear_search"),
            "clear_selection": t("tab_predictive_overview.sel_dd_clear_selection"),
            "no_options_found": t("tab_predictive_overview.sel_dd_no_options"),
        },
    )

    def heading(badge):
        return t("tab_predictive_overview.sel_group_heading", state=status_label(badge), count=len(groups[badge]))

    badges = html.Div([
        html.Button(heading(badge), id={"type": panel.badge, "badge": badge}, n_clicks=0,
                    className=_badge_class(badge, sel.badge == badge))
        for badge in long_sel.DEFAULT_BADGE_ORDER
    ], className="unit-sel-badges")
    chip_groups = html.Div([
        html.Div([
            html.Div(heading(badge), className="unit-chip-heading"),
            html.Div([
                html.Button(u, id={"type": panel.chip, "unit": u}, n_clicks=0,
                            className=_chip_class(u in selected, badge))
                for u in groups[badge]
            ], className="unit-chip-row"),
        ], className="unit-chip-group")
        for badge in long_sel.DEFAULT_BADGE_ORDER if groups[badge]
    ], className="unit-chip-groups")
    return html.Div([
        html.Div([html.Label(t("tab_predictive_overview.sel_units_label"), className="unit-sel-label"), dropdown]),
        html.Div([
            badges,
            html.Div(t(note_key), className="unit-sel-note"),
            chip_groups,
        ], id=panel.risk_id, className=RISK_IDLE_CLASS),
    ], className="unit-sel")


def _apply_selection_event(event, state, universe, groups):
    """One interaction -> the new `Selection`. `event` is ("dropdown", values) |
    ("chip", unit) | ("badge", badge) | None (None just reads `state`). Every
    path goes through the same rules, so the dropdown, chips, badges and chart come
    out of one value and cannot disagree."""
    sel = long_sel.from_dict(state, universe)
    kind, arg = event if event else (None, None)
    if kind == "dropdown":
        sel = long_sel.pick_from_dropdown(sel, arg, universe)
    elif kind == "chip":
        sel = long_sel.toggle_unit(sel, arg, universe)
    elif kind == "badge":
        sel = long_sel.click_badge(sel, arg, groups, universe)
    return sel


def _selection_result(sel, groups, figure) -> dict:
    """What the front end needs after a selection change: `state` (store contents),
    `selected`, `badge`, the className of every chip and badge, and `figure`."""
    selected = set(sel.selected)
    group_of = {u: badge for badge, units in groups.items() for u in units}
    return {
        "state": long_sel.to_dict(sel),
        "selected": list(sel.selected),
        "badge": sel.badge,
        "chip_classes": {u: _chip_class(u in selected, badge) for u, badge in group_of.items()},
        "badge_classes": {b: _badge_class(b, sel.badge == b) for b in long_sel.DEFAULT_BADGE_ORDER},
        "figure": figure,
    }


# ── Short View ──

def _short_view_model(latest, client: str, component: str):
    """What the Short View's panel and chart work from, fleet-wide: the units it can
    actually draw (a recognised `unit_status_summary` state and a value on both
    configured axis fields), their fleet order and the risk group per badge. A unit
    outside this set has no point on the chart, so it is not offered in the panel
    either. With no axes configured for the pair nothing can be drawn."""
    axes = get_settings().get_fleet_scatter_axes(client, component)
    ok = latest["status"].map(normalize_state).notna() & (axes is not None)
    for column in (scatter_axis_columns(axes) if axes is not None else ()):
        ok &= np.isfinite(latest[column].astype(float))
    drawable = latest[ok].sort_values("Unit")
    universe = list(drawable["Unit"])
    groups = {
        badge: [u for u, s in zip(drawable["Unit"], drawable["status"].map(normalize_state)) if s == badge]
        for badge in long_sel.DEFAULT_BADGE_ORDER
    }
    return drawable, universe, groups


def _short_view_figure(drawable, selected, client: str, component: str):
    """The fleet scatter of exactly the `selected` units (axes fit to them); an empty
    selection is an empty chart, never the whole fleet."""
    if not selected:
        return create_empty_selection_figure()
    return make_fleet_scatter(
        drawable[drawable["Unit"].isin(set(selected))], client, component, None, _SCATTER_STATUS_COLORS, height=None,
    )


def short_view_update(event, state, latest, client: str, component: str) -> dict:
    """One interaction on the Short View's panel -> everything that must change with
    it (see `_selection_result`)."""
    drawable, universe, groups = _short_view_model(latest, client, component)
    sel = _apply_selection_event(event, state, universe, groups)
    return _selection_result(sel, groups, _short_view_figure(drawable, sel.selected, client, component))


def load_status_frame(client: str, component: str):
    """Per-unit frame of the Short View (`status` = `unit_status_summary.estado`
    attached), or None when the client/component has no data."""
    filepath = _discover_components(client).get(component) if client else None
    if not filepath:
        return None
    _, df_latest, _ = _load_component_data(filepath, component, client)
    if df_latest is None or df_latest.empty:
        return None
    return attach_status(df_latest, client, component)


def render_short_view(latest, client: str, component: str):
    """Short View Analysis: the fleet scatter (the ranking fields configured as its
    axes for this client/component, with its thresholds), points colored/sized by
    `unit_status_summary.estado`,
    with its own unit selection (dropdown, risk-grouped chips, risk badges) that
    picks which units are drawn. Clicking a point opens that unit in Evidence
    (navigate_to_evidence_from_overview)."""
    drawable, universe, groups = _short_view_model(latest, client, component)
    axes = get_settings().get_fleet_scatter_axes(client, component)
    subtitle = t("tab_predictive_overview.short_view_subtitle",
                 x_label=t(SCATTER_AXIS_FIELDS[axes[0]][1]), y_label=t(SCATTER_AXIS_FIELDS[axes[1]][1]).lower()
                 ) if axes is not None else ""
    sel = long_sel.initial_selection(universe)
    if universe:
        fig = _short_view_figure(drawable, sel.selected, client, component)
    else:  # nothing drawable: the plain (empty) scatter, not the "select a unit" message
        fig = make_fleet_scatter(drawable, client, component, None, _SCATTER_STATUS_COLORS, height=None)
    return html.Div([
        html.Div([
            html.Span([html.I(className="fas fa-dot-circle me-1"), t("tab_predictive_overview.posicion_en_la_flota")],
                      className="card-subtitle fw-500"),
            html.Span(subtitle,
                      style={"fontSize": "11px", "color": "var(--text-light)", "marginLeft": "8px"}),
        ], style={"marginBottom": "8px"}),
        dcc.Store(id=SHORT_STATE_ID, data=long_sel.to_dict(sel)),
        _selection_controls(SHORT_PANEL, universe, groups, sel, "tab_predictive_overview.short_risk_note") if universe else None,
        dcc.Graph(id=SHORT_GRAPH_ID, figure=fig, className=CHART_ASPECT_CLASS,
                  responsive=True, config={"displayModeBar": False}),
        html.Div(t("tab_predictive_overview.short_view_color_note"),
                 style={"fontSize": "11px", "color": "var(--text-light)", "marginTop": "4px"}),
    ], className="card shadow-sm", style={"padding": "16px"})


# ── Long View ──

def _long_view_model(active):
    """What the Long View's controls need, all fleet-wide (independent of the
    current selection): fleet order and the risk group per badge."""
    universe = sorted(active["Unit"].unique())
    states = {u: normalize_state(e) for u, e in predictive_v2.active_cycle_estado(active).items()}
    groups = {badge: [u for u in universe if states.get(u) == badge] for badge in long_sel.DEFAULT_BADGE_ORDER}
    return universe, groups


def long_view_update(event, state, active) -> dict:
    """One interaction on the Long View's panel -> everything that must change with
    it (see `_selection_result`)."""
    universe, groups = _long_view_model(active)
    sel = _apply_selection_event(event, state, universe, groups)
    return _selection_result(sel, groups, create_long_view_chart(active, list(sel.selected)))


def render_long_view(client: str, component: str, units=()):
    """Long View Analysis: the fleet's active-cycle accumulated risk curves from
    `cumulative_risk_curve`, with a unit selection (dropdown, risk-grouped chips,
    risk badges) that picks which curves are drawn. Points are colored/sized by
    that table's own `estado`, which is also what the badges and chips group by.

    A client with no curve data gets a "working on it" placeholder instead of an
    empty chart. `units` (the fleet shown in Resumen) only feeds the note listing
    units that are missing from the curve."""
    placeholder = html.Div([
        html.I(className="fas fa-tools fa-2x mb-3"),
        html.P(t("tab_predictive_overview.long_view_working"), className="mb-0"),
    ], className="card shadow-sm text-center text-muted", style={"padding": "40px"})

    active = load_active_curve(client, component)
    if active is None:
        return placeholder
    try:
        universe, groups = _long_view_model(active)
        sel = long_sel.initial_selection(universe)
        fig = create_long_view_chart(active, list(sel.selected))
        controls = _selection_controls(LONG_PANEL, universe, groups, sel, "tab_predictive_overview.long_risk_note")
    except Exception:  # noqa: BLE001 - one bad curve must not take the whole tab down
        logger.exception("No se pudo construir la vista larga de %s/%s", client, component)
        return html.Div(html.P(t("tab_predictive_overview.long_view_error"), className="mb-0"),
                        className="card shadow-sm text-center text-muted", style={"padding": "40px"})
    if fig is None:
        return placeholder

    missing = units_missing_from_curve(units, active)
    if missing:
        logger.warning("Vista larga %s/%s: %d unidades sin curva: %s", client, component, len(missing), missing)
    return html.Div([
        html.Div([
            html.Span([html.I(className="fas fa-chart-line me-1"), t("tab_predictive_overview.long_view_header")],
                      className="card-subtitle fw-500"),
            html.Span(t("tab_predictive_overview.long_view_subtitle"),
                      style={"fontSize": "11px", "color": "var(--text-light)", "marginLeft": "8px"}),
        ], style={"marginBottom": "8px"}),
        dcc.Store(id=LONG_STATE_ID, data=long_sel.to_dict(sel)),
        controls,
        dcc.Graph(id=LONG_GRAPH_ID, figure=fig, className=CHART_ASPECT_CLASS, responsive=True,
                  config={"displayModeBar": False}),
        html.Div(t("tab_predictive_overview.long_view_color_note"),
                 style={"fontSize": "11px", "color": "var(--text-light)", "marginTop": "4px"}),
        html.Div(t("tab_predictive_overview.long_view_missing_units", count=len(missing), units=", ".join(missing)),
                 style={"fontSize": "11px", "color": "var(--text-light)", "marginTop": "2px"}) if missing else None,
    ], className="card shadow-sm", style={"padding": "16px"})


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

    active = load_active_curve(client, component)
    latest = attach_general_status(
        attach_component_hours(attach_status(df_latest, client, component), active), active
    )
    avg_ranking = float(latest["ranking"].mean())

    # KPI counts and the table's Estado use the "general state" (worse of short and
    # long view); the per-unit `status` column keeps the short view's own estado.
    counts = latest["general_status"].value_counts()
    n_anormal = counts.get("Anormal", 0)
    n_alert = counts.get("Alerta", 0)
    n_normal = counts.get("Normal", 0)

    model_run_date = get_model_run_date(client, component) if client else None
    model_run_date_str = model_run_date.strftime("%d %b %Y") if model_run_date is not None else "—"

    # Only labelled as combined when a long view actually contributes to it.
    state_sub = t("tab_predictive_overview.estado_general_subtitle") if active is not None else None

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
            create_kpi_card(n_anormal, t("tab_predictive_overview.unidades_anormales"), "fas fa-exclamation-triangle", "danger", state_sub),
            create_kpi_card(n_alert, t("tab_predictive_overview.unidades_en_alerta"), "fas fa-exclamation-circle", "warning", state_sub),
            create_kpi_card(n_normal, t("tab_predictive_overview.unidades_normales"), "fas fa-check-circle", "success", state_sub),
            create_kpi_card(model_run_date_str, t("tab_predictive_overview.fecha_ejecucion_modelo"), "fas fa-calendar-check", "info"),
        ])
    ])

    # Layer 2: Short View / Long View submenu. The Short View is the fleet-wide
    # scatter that used to be this layer on its own; the Long View is rendered on
    # demand by switch_layer2_view (predictive_callbacks) when its tab is picked.
    tab_kwargs = dict(className="custom-tab", selected_className="custom-tab--selected")
    risk_section = html.Div([
        html.H4([
            html.I(className="fas fa-shield-alt me-2"),
            t("tab_predictive_overview.analisis_de_riesgo")
        ], className="text-primary mb-3 mt-4"),
        dcc.Tabs(
            id=LAYER2_TABS_ID,
            value=LAYER2_SHORT,
            children=[
                dcc.Tab(label=t("tab_predictive_overview.short_view_tab"), value=LAYER2_SHORT, **tab_kwargs),
                dcc.Tab(label=t("tab_predictive_overview.long_view_tab"), value=LAYER2_LONG, **tab_kwargs),
            ],
            className="mb-3",
        ),
        html.Div(render_short_view(latest, client, component), id=LAYER2_CONTENT_ID),
    ])

    # Failure mode table
    # W34-10: "Unit" as a secondary key makes tie order deterministic across
    # renders — plain `sort_values` on one column falls back to an unstable
    # quicksort for ties, so two identical-input renders could otherwise show
    # tied units in a different order.
    sorted_df = latest.sort_values([FAILURE_TABLE_DEFAULT_WINDOW, "Unit"], ascending=[False, True])
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
                        value=FAILURE_TABLE_DEFAULT_WINDOW,
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
            _failure_table(sorted_df, FAILURE_TABLE_DEFAULT_WINDOW, FAILURE_TABLE_DEFAULT_WINDOW, False, failure_modes, client),
            id="predictive-fm-table-container",
        ),
        dcc.Store(
            id="predictive-fm-table-state",
            data={"window": FAILURE_TABLE_DEFAULT_WINDOW, "sort_by": FAILURE_TABLE_DEFAULT_WINDOW, "ascending": False},
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
