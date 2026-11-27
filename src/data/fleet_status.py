"""Golden layer of the General tab (Resumen de Flota): one row per unit, final.

    data/general/golden/{client}/fleet_status.parquet

`scripts/build_fleet_status.py` (scheduled by the app at 10:30, `src/data/partition_scheduler.py`) is the
only code that reads the raw sources of this view - alerts, telemetry, oil, maintenance and predictive
files - and decides every state. The dashboard reads the file this module writes and draws it
(`dashboard/components/fleet_overview.py`); it never processes raw data, and it does not fall back to it
when the file is missing or unreadable (:class:`FleetStatusUnavailable`).

What a run does, per client:

1. reads each applicable technique's own per-unit status (layer 1, upstream) and how old its data is;
2. gives each technique its Estado: the worse of its status and what the data age forces
   (`config.estado_rules.technique_estado`). **A unit with no alert in the alert window is Normal** - not
   "Sin Datos": that is only for a feed with nothing to evaluate (the client has no alerts, or none is dated);
3. merges the spellings of one unit (`CT-184` / `CT_184`, `T_09` / `T_9`: `src.data.unit_ids`) so every unit has
   one row, then takes its overall Estado from the merged techniques (`config.estado_rules.unit_estado`);
4. writes the file atomically.

The file is the finished answer, so its ages are the ones at the time of the run: a technique whose data
turns stale after 10:30 changes state at the next run, not before.

File columns: ``unit_id`` (hyphenated name), ``estado`` (overall), ``generated_at`` and, per applicable
technique `t` (``alerts``, ``telemetry``, ``oil``, ``maintenance``, ``predictive``; a technique's columns exist
only when the client has it): ``t_estado`` (the technique's Estado), ``t_status`` (its own status), ``t_data_state``
(Ok / Atención / Preocupante / Sin Datos), ``t_driver``, ``t_explanation_key``, ``t_elapsed`` (age of the data,
for the tooltip), ``t_score`` (its severity value while it still explains ``t_estado``) and ``t_source_unit``
(how that source spells the unit, for links into the technique's own page); Alertas also has
``alerts_count_{7,28,56}d``. Maintenance carries no status in the tab: it is stored only so the "Fuentes de
datos" banner can tell whether the technique has data.

No Dash import here: the script runs outside the web app.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple, Optional

import pandas as pd

from config.client_services import KNOWN_SERVICE_IDS, is_service_enabled
from config.estado_rules import (
    ALERTS_ALERTA_MAX_SCORE,
    ALERTS_COMPONENT_WEIGHT,
    ALERTS_WINDOW_DAYS,
    BANDS,
    STATUS_PRIORITY,
    technique_estado,
    unit_estado,
)
from config.freshness_thresholds import FRESHNESS_CRITERIA
from src.data.catalog import dashboard_data_root
from src.data.loaders import (
    client_has_alert_partitions,
    latest_alert_timestamp,
    load_alert_units,
    load_alerts_since,
    load_machine_status_for_client,
    load_maintenance_equipment_status,
    load_telemetry_unit_health,
)
from src.data.unit_ids import normalize_unit_id, unit_key

logger = logging.getLogger(__name__)

GOLDEN_FILE = "fleet_status.parquet"

# Row order of every technique list (the order of the table's columns).
TECHNIQUES = ("alerts", "telemetry", "oil", "maintenance", "predictive")

# Service id gate per technique (§2.4/§3.1). Predictive has no single service id - it is applicable if any
# predictive-<component> id is enabled.
TECHNIQUE_SERVICE_ID = {
    "alerts": "monitoring-alerts",
    "telemetry": "monitoring-telemetry",
    "oil": "monitoring-oil",
    "maintenance": "monitoring-mantenciones",
}

# Freshness config key per technique (config/freshness_thresholds.py).
TECHNIQUE_FRESHNESS_KEY = {
    "alerts": "Alertas",
    "telemetry": "Telemetria",
    "oil": "Tribologia",
    "maintenance": "Mantenciones",
    "predictive": "Predictivo",
}

# Trailing windows of the alert counts the Alertas tooltip lists: last week, 4 weeks, 8 weeks.
ALERT_WINDOW_DAYS = (7, 28, 56)

_TIERS = ("Ok", "Atención", "Preocupante", "Sin Datos")  # best to worst


class FleetStatusUnavailable(RuntimeError):
    """The golden file of a client is missing, empty or unreadable. The view says so; it does not
    rebuild the answer from the raw sources."""


class EmptyFleetError(RuntimeError):
    """A run found no unit for a client that has techniques. Nothing is published, so the previous
    file (if any) keeps being the one the view shows."""


# ── Applicability ────────────────────────────────────────────────────────────

def enabled_predictive_components(client: str) -> list:
    """The predictive components (`motor`, `transmision`...) enabled for a client."""
    return [
        sid.split("predictive-", 1)[1]
        for sid in KNOWN_SERVICE_IDS
        if sid.startswith("predictive-") and is_service_enabled(client, sid)
    ]


def applicable_techniques(client: str) -> dict:
    """{technique: bool}: which techniques a client has (§3.1 gate) - shared by the table and the
    Unit Detail, so both agree on which technique sections exist at all."""
    applicable = {
        technique: is_service_enabled(client, service_id)
        for technique, service_id in TECHNIQUE_SERVICE_ID.items()
    }
    applicable["predictive"] = bool(enabled_predictive_components(client))
    return {technique: applicable[technique] for technique in TECHNIQUES}


# ── One cell: the technique's own status x its data age ──────────────────────

class Cell(NamedTuple):
    """The outcome of one `resolve_cell`: what a technique shows for a unit and why."""
    value: str
    label: str
    estado_datos: str
    driver: str  # "label" | "data" | "both" | "none"
    explanation_key: str
    elapsed: Optional[str] = None
    score: Optional[float] = None


def resolve_cell(label, estado_datos, elapsed: Optional[str] = None, score=None) -> Cell:
    """The worse of a technique's own status `label` and its data-freshness `estado_datos` (rule:
    `config.estado_rules.technique_estado`). The technique's own `score` is kept only while it still
    explains the shown value: stale data that overrides the status takes it away."""
    label = str(label) if label else "Sin Datos"
    estado_datos = str(estado_datos) if estado_datos else "Sin Datos"
    resolution = technique_estado(label, estado_datos)
    return Cell(
        resolution.value, label, estado_datos, resolution.driver, resolution.explanation_key,
        elapsed, score if resolution.label_kept else None,
    )


# ── Freshness ────────────────────────────────────────────────────────────────

def _freshness_from_naive_timestamp(last_update, technique: str) -> tuple[str, str]:
    """Freshness for techniques whose reference clock is a plain (tz-naive, day/week-scale) timestamp:
    Alertas (max feed Timestamp), Predictivo (model run date), Mantenciones (query_10 reference_date).
    Distinct from Telemetria/Tribologia's tz-aware, CSV-sourced freshness below (§3.2: "unchanged")."""
    if last_update is None or pd.isna(last_update):
        return "Sin Datos", "N/A"
    ts = pd.Timestamp(last_update)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    elapsed = datetime.now() - ts.to_pydatetime()
    if elapsed.days > 0:
        elapsed_str = f"{elapsed.days} día" if elapsed.days == 1 else f"{elapsed.days} días"
    else:
        hours = elapsed.seconds // 3600
        elapsed_str = f"{hours}h" if hours else f"{elapsed.seconds // 60}m"

    criteria = FRESHNESS_CRITERIA.get(TECHNIQUE_FRESHNESS_KEY.get(technique, technique), [])
    for threshold, label, _ in criteria:
        if elapsed < threshold:
            return label, elapsed_str
    if criteria:
        return criteria[-1][1], elapsed_str
    return "Sin Datos", elapsed_str


def _telemetry_tribologia_freshness_map(client: str) -> dict:
    """Per-unit freshness for Telemetria/Tribologia, sourced from Data_Date_Last_Update.csv exactly as
    before (§3.2: thresholds unchanged). Returns {(technique, unit): (label, elapsed_str)}."""
    from dashboard.callbacks.data_freshness_callbacks import (
        calculate_freshness_status,
        convert_utc_to_chile,
        load_data_freshness,
    )

    result: dict[tuple[str, str], tuple[str, str]] = {}
    df_freshness = load_data_freshness(client)
    if df_freshness is None or df_freshness.empty:
        return result

    import pytz
    chile_tz = pytz.timezone("America/Santiago")
    current_time_chile = datetime.now(chile_tz)

    for technique, data_label in (("telemetry", "Telemetria"), ("oil", "Tribologia")):
        rows = df_freshness[df_freshness["Data"] == data_label]
        for _, row in rows.iterrows():
            unit_id = row.get("Unit_Id", "")
            last_update = row.get("Ultima Fecha de Actualizacion")
            if pd.isna(last_update):
                continue
            last_update = pd.to_datetime(last_update)
            last_update_chile = convert_utc_to_chile(last_update)
            label, _color, elapsed_str = calculate_freshness_status(
                last_update_chile, data_label, current_time_chile
            )
            result[(technique, str(unit_id))] = (label, elapsed_str)
    return result


# ── Alertas: the only technique the dashboard classifies itself ──────────────

def _empty_scores() -> pd.DataFrame:
    return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])


def calculate_alert_criticality_score(df_alerts: pd.DataFrame, days: int = ALERTS_WINDOW_DAYS) -> pd.DataFrame:
    """Equipment criticality score of the units that had alerts in the last `days` days.

    More alerts for the same equipment/component = higher criticality. This is Alerts' only per-unit
    severity concept (documentation/general/general_specs/00_implementation_guide.md §1.1) - there is no
    severity/priority field in the raw alert data itself. The limits are the ones the page prints
    (`config.estado_rules`): score = alerts x (1 + 0.5 x components with alerts); up to 15 is Alerta,
    above it Crítico (= Anormal). A unit with no alert in the window has no row here: it is Normal, which
    the caller decides (it knows whether the feed could have shown one).

    Args:
        df_alerts: DataFrame with alert data (UnitId, componente, Timestamp)
        days: Number of days to consider recent alerts

    Returns:
        DataFrame with equipo, alert_count, component_count, criticality_score, status
    """
    if df_alerts.empty:
        return _empty_scores()

    if 'Timestamp' not in df_alerts.columns:
        logger.warning(f"Column 'Timestamp' not found. Available: {df_alerts.columns.tolist()}")
        return _empty_scores()

    cutoff_date = datetime.now() - timedelta(days=days)

    df_alerts = df_alerts.copy()
    df_alerts['Timestamp'] = pd.to_datetime(df_alerts['Timestamp'])

    recent = df_alerts[df_alerts['Timestamp'] >= cutoff_date].copy()

    if recent.empty:
        return _empty_scores()

    if 'UnitId' not in recent.columns or 'componente' not in recent.columns:
        logger.warning(f"Required columns not found. Available: {recent.columns.tolist()}")
        return _empty_scores()

    grouped = recent.groupby(['UnitId', 'componente']).size().reset_index(name='alerts_per_component')

    equipment_stats = grouped.groupby('UnitId').agg({
        'alerts_per_component': 'sum',
        'componente': 'nunique'
    }).reset_index()

    equipment_stats.columns = ['equipo', 'alert_count', 'component_count']

    equipment_stats['criticality_score'] = (
        equipment_stats['alert_count'] *
        (1 + equipment_stats['component_count'] * ALERTS_COMPONENT_WEIGHT)
    ).round(1)

    equipment_stats['status'] = equipment_stats['criticality_score'].apply(
        lambda score: 'Normal' if score == 0 else 'Alerta' if score <= ALERTS_ALERTA_MAX_SCORE else 'Crítico'
    )

    return equipment_stats.sort_values('criticality_score', ascending=False)


def count_alerts_by_window(df_alerts: pd.DataFrame, windows_days: tuple = ALERT_WINDOW_DAYS) -> dict:
    """Number of alerts per unit in each trailing window (default: last week, last 4 weeks, last 8 weeks).

    Returns {unit: (count_in_window_1, count_in_window_2, ...)} in the order of `windows_days`. Only
    units with at least one alert row appear; the windows are nested, so counts never decrease from one
    window to the next.
    """
    if df_alerts is None or df_alerts.empty:
        return {}
    if not {'UnitId', 'Timestamp'}.issubset(df_alerts.columns):
        logger.warning(f"Required columns not found. Available: {df_alerts.columns.tolist()}")
        return {}

    now = datetime.now()
    alerts = df_alerts[['UnitId', 'Timestamp']].copy()
    alerts['Timestamp'] = pd.to_datetime(alerts['Timestamp'], errors='coerce')
    alerts = alerts.dropna(subset=['Timestamp'])
    if alerts.empty:
        return {}

    counts = pd.DataFrame({
        days: alerts['Timestamp'].ge(now - timedelta(days=days)).groupby(alerts['UnitId']).sum()
        for days in windows_days
    }).astype(int)
    return {str(unit): tuple(int(c) for c in row) for unit, row in counts.iterrows()}


def _recent_alerts(client: str) -> pd.DataFrame:
    """The alerts of the widest window any alert figure looks back on, with each unit under its identity
    (`unit_key`): the spellings of one unit pile up as one."""
    since = datetime.now() - timedelta(days=max((ALERTS_WINDOW_DAYS, *ALERT_WINDOW_DAYS)))
    df = load_alerts_since(client, since)
    if "UnitId" in df.columns:
        df = df.assign(UnitId=df["UnitId"].astype(str).map(unit_key))
    return df


def _alerts_status_map(client: str, days: int = ALERTS_WINDOW_DAYS) -> tuple[dict, dict, str, str]:
    """Returns ({unit_key: status}, {unit_key: criticality_score}, freshness_label, freshness_elapsed) for
    the units that had alerts in the last `days` days. Status vocabulary: Alerta/Crítico (Crítico ==
    Anormal, §3.1). Freshness is client-wide (max Timestamp across the client's alert feed, §1.1), applied
    identically to every unit's Alertas row; "Sin Datos" when the client has no (dated) alerts to look at."""
    if not client_has_alert_partitions(client):
        return {}, {}, "Sin Datos", "N/A"
    df_alerts = _recent_alerts(client)
    if "UnitId" not in df_alerts.columns:
        return {}, {}, "Sin Datos", "N/A"

    scores = calculate_alert_criticality_score(df_alerts, days)
    status_map = dict(zip(scores["equipo"], scores["status"])) if not scores.empty else {}
    value_map = dict(zip(scores["equipo"], scores["criticality_score"])) if not scores.empty else {}

    # Freshness is the newest alert of the whole feed, read from the newest partition alone.
    freshness_label, elapsed = _freshness_from_naive_timestamp(latest_alert_timestamp(client), "alerts")
    return status_map, value_map, freshness_label, elapsed


def _alerts_window_counts(client: str) -> dict:
    """{unit_key: (last week, last 4 weeks, last 8 weeks)} alert counts - what the Alertas tooltip lists.
    A unit with no alert in them still appears, with zeros: the unit list is the whole history's. {} when
    the client has no alert feed."""
    recent = count_alerts_by_window(_recent_alerts(client))
    no_recent_alerts = (0,) * len(ALERT_WINDOW_DAYS)
    return {
        unit_key(unit): recent.get(unit_key(unit), no_recent_alerts)
        for unit in load_alert_units(client, dated_only=True)
    }


def _alerts_source_units(client: str) -> dict:
    """{unit_key: how the alert feed spells the unit}: what the Alertas page filters by."""
    spellings: dict = {}
    for unit in load_alert_units(client):
        spellings.setdefault(unit_key(unit), str(unit))
    return spellings


# ── The other techniques' per-unit status ────────────────────────────────────

def _telemetry_status_map(client: str) -> tuple[dict, dict]:
    """Returns ({unit: status}, {unit: unit_score}) from Telemetry's unit health (§1.2)."""
    df = load_telemetry_unit_health(client)
    if df.empty:
        return {}, {}
    unit_col = "unit_id" if "unit_id" in df.columns else ("unit" if "unit" in df.columns else None)
    if not unit_col or "overall_status" not in df.columns:
        return {}, {}
    status_map = dict(zip(df[unit_col].astype(str), df["overall_status"]))
    value_map = (
        dict(zip(df[unit_col].astype(str), df["unit_score"]))
        if "unit_score" in df.columns else {}
    )
    return status_map, value_map


def _oil_status_map(client: str) -> tuple[dict, dict]:
    """Returns ({unit: status}, {unit: machine_score}) from Oil's machine status - the weighted
    per-machine score (§1.3) behind the status color."""
    df = load_machine_status_for_client(client)
    if df is None or df.empty:
        return {}, {}
    unit_col = "unit_id" if "unit_id" in df.columns else ("equipo" if "equipo" in df.columns else None)
    status_col = "overall_status" if "overall_status" in df.columns else ("estado" if "estado" in df.columns else None)
    if not unit_col or not status_col:
        return {}, {}
    status_map = dict(zip(df[unit_col].astype(str), df[status_col]))
    value_map = (
        dict(zip(df[unit_col].astype(str), df["machine_score"]))
        if "machine_score" in df.columns else {}
    )
    return status_map, value_map


def _maintenance_status_map(client: str) -> tuple[dict, str, str]:
    """Returns ({machine_code: 'SANO'/'DETENIDO'}, freshness_label, elapsed). Freshness comes from query_10's
    own `reference_date`: the max available for the client (§1.4: "inferred from the max available period")."""
    df = load_maintenance_equipment_status(client)
    if df is None or df.empty or "machine_code" not in df.columns:
        return {}, "Sin Datos", "N/A"

    status_col = "equipment_status" if "equipment_status" in df.columns else None
    if not status_col:
        return {}, "Sin Datos", "N/A"

    status_map = {}
    for _, row in df.iterrows():
        raw = str(row.get(status_col, "")).strip().upper()
        status_map[str(row["machine_code"])] = "SANO" if raw == "OPERATIVO" else "DETENIDO" if raw else "Sin Datos"

    ref_date = None
    if "reference_date" in df.columns:
        ref_date = pd.to_datetime(df["reference_date"], errors="coerce").max()
    freshness_label, elapsed = _freshness_from_naive_timestamp(ref_date, "maintenance")
    return status_map, freshness_label, elapsed


def _component_predictive_status_maps(client: str, component: str) -> tuple[dict, dict]:
    """Per-unit {unit_key: estado}/{unit_key: ranking} for a single predictive component - shared by the
    merged Predictivo cell and by the Unit Detail's per-sub-model status
    (`get_predictive_component_status`), so a sub-model can never diverge from what fed into the merged
    row for the same unit/component."""
    from dashboard.components.predictive_state import published_state
    from src.data import predictive_v2

    df_status = predictive_v2.load_unit_status_summary(client, component)
    estado_map: dict[str, str] = {}
    ranking_map: dict[str, float] = {}
    if not df_status.empty and "estado" in df_status.columns:
        # `estado` is upstream's final state since 1.3; `sin_datos` -> "Sin Datos"
        # (STATUS_PRIORITY 0: never read as a checked-and-healthy unit).
        estado_map = {
            unit_key(u): published_state(e) or str(e).strip().title()
            for u, e in zip(df_status["Unit"], df_status["estado"])
        }
        if "ranking" in df_status.columns:
            ranking_map = {unit_key(u): r for u, r in zip(df_status["Unit"], df_status["ranking"])}
    return estado_map, ranking_map


def get_predictive_component_status(client: str, unit: str, component: str) -> tuple:
    """A single unit's status/ranking for one predictive sub-model (e.g. Motor, Transmisión), from the same
    per-component computation the merged Predictivo cell is built from. Returns `(None, None)` when the
    unit has no record for this component's latest run - the caller applies the confirmed no-data fallback
    (00_implementation_guide.md §3.1, never a silent default).

    The status is the same `resolve_cell(estado, freshness)` merge the table applies to the merged
    Predictivo cell (against this component's own model run date), so a sub-model's status can never
    disagree with the table for the same data."""
    from src.data.loaders import get_model_run_date

    estado_map, ranking_map = _component_predictive_status_maps(client, component)
    key = unit_key(unit)
    estado = estado_map.get(key)
    if estado is None:
        return None, None

    freshness_label, elapsed = _freshness_from_naive_timestamp(get_model_run_date(client, component), "predictive")
    cell = resolve_cell(estado, freshness_label, elapsed)
    # The ranking only explains the status while the model's own estado is what's being shown; stale
    # data that overrides it takes the ranking away.
    ranking = ranking_map.get(key) if cell.driver in ("label", "both") else None
    return cell.value, ranking


def _predictive_status_map(client: str, components: list) -> tuple[dict, dict, str, str]:
    """Worst-of status per unit across every enabled predictive component. A unit absent from every
    component's estado map is left out here - the caller applies "Sin Datos" for it (§3.1's confirmed
    attach_status() fix: an absent unit is never silently defaulted to Normal).

    Also returns {unit: ranking} - the component's today-ranking value that drove the worst status.
    Freshness uses the oldest (worst) model run date across components."""
    from src.data.loaders import get_model_run_date

    status_map: dict[str, str] = {}
    value_map: dict[str, float] = {}
    run_dates = []
    for component in components:
        estado_map, ranking_map = _component_predictive_status_maps(client, component)
        for unit, estado in estado_map.items():
            existing = status_map.get(unit)
            if existing is None or STATUS_PRIORITY.get(estado, 0) > STATUS_PRIORITY.get(existing, 0):
                status_map[unit] = estado
                if unit in ranking_map:
                    value_map[unit] = ranking_map[unit]

        run_date = get_model_run_date(client, component)
        if run_date is not None:
            run_dates.append(run_date)

    worst_run_date = min(run_dates) if run_dates else None
    freshness_label, elapsed = _freshness_from_naive_timestamp(worst_run_date, "predictive")
    return status_map, value_map, freshness_label, elapsed


# ── Merging the spellings of a unit ──────────────────────────────────────────

def _fold(status_map: dict, value_map: dict) -> tuple[dict, dict, dict]:
    """`(status, value, spelling)` keyed by unit identity. When one source spells a unit two ways, the worst
    status stands (ties: the first spelling in text order) - never the better one."""
    status: dict = {}
    value: dict = {}
    spelling: dict = {}
    for raw in sorted(status_map, key=str):
        key = unit_key(raw)
        current = status.get(key)
        if current is None or STATUS_PRIORITY.get(status_map[raw], 0) > STATUS_PRIORITY.get(current, 0):
            status[key] = status_map[raw]
            spelling[key] = str(raw)
            if raw in value_map:
                value[key] = value_map[raw]
            else:
                value.pop(key, None)
    return status, value, spelling


def _fold_freshness(freshness: dict) -> dict:
    """{(technique, unit_key): (label, elapsed)}: where a unit has freshness under two spellings, the fresher."""
    folded: dict = {}
    for (technique, raw), (label, elapsed) in freshness.items():
        key = (technique, unit_key(raw))
        if key not in folded or _TIERS.index(label if label in _TIERS else "Sin Datos") < _TIERS.index(
            folded[key][0] if folded[key][0] in _TIERS else "Sin Datos"
        ):
            folded[key] = (label, elapsed)
    return folded


# ── Build ────────────────────────────────────────────────────────────────────

def _nullable(value):
    return None if value is None or (isinstance(value, float) and pd.isna(value)) else value


def build_fleet_status(client: str) -> pd.DataFrame:
    """The golden frame of a client: one row per unit, every state decided (see the module docstring for
    the columns). Empty when the client has no technique with a status, or no unit. This is the only place
    that reads the raw sources and the only place that classifies."""
    applicable = applicable_techniques(client)
    techniques = [t for t in TECHNIQUES if applicable[t]]
    if not techniques:
        return pd.DataFrame(columns=["unit_id", "estado"])

    predictive_components = enabled_predictive_components(client)

    alerts_raw, alerts_value_raw, alerts_label, alerts_elapsed = (
        _alerts_status_map(client) if applicable["alerts"] else ({}, {}, "Sin Datos", "N/A")
    )
    alerts_status, alerts_value, _ = _fold(alerts_raw, alerts_value_raw)  # already per identity: keeps one spelling each
    telemetry_status, _telemetry_value, telemetry_spelling = _fold(*(_telemetry_status_map(client) if applicable["telemetry"] else ({}, {})))
    oil_status, oil_value, oil_spelling = _fold(*(_oil_status_map(client) if applicable["oil"] else ({}, {})))
    maintenance_raw, maint_label, maint_elapsed = (
        _maintenance_status_map(client) if applicable["maintenance"] else ({}, "Sin Datos", "N/A")
    )
    maintenance_status, _, maintenance_spelling = _fold(maintenance_raw, {})
    predictive_status, predictive_value, predictive_label, predictive_elapsed = (
        _predictive_status_map(client, predictive_components) if applicable["predictive"] else ({}, {}, "Sin Datos", "N/A")
    )
    freshness = _fold_freshness(_telemetry_tribologia_freshness_map(client))
    alert_counts = _alerts_window_counts(client) if applicable["alerts"] else {}
    alerts_spelling = _alerts_source_units(client) if applicable["alerts"] else {}

    # The alert feed can say "no alert" only when it can be read at all (its newest alert is known).
    alerts_evaluable = alerts_label != "Sin Datos"

    # Every unit that some technique with a status knows. A unit only Maintenance knows has no severity
    # to show or rank, so it is left out rather than listed as an empty "Sin Datos" row.
    spellings = {
        "alerts": alerts_spelling, "telemetry": telemetry_spelling, "oil": oil_spelling,
        "predictive": {},
    }
    keys = set(alerts_status) | set(telemetry_status) | set(oil_status) | set(predictive_status)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows = []
    for key in keys:
        cells: dict[str, Cell] = {}
        sources: dict[str, Optional[str]] = {}

        if applicable["alerts"]:
            status = alerts_status.get(key) or ("Normal" if alerts_evaluable else "Sin Datos")
            cells["alerts"] = resolve_cell(status, alerts_label, alerts_elapsed, alerts_value.get(key))
            sources["alerts"] = alerts_spelling.get(key)
        if applicable["telemetry"]:
            label, elapsed = freshness.get(("telemetry", key), ("Sin Datos", "N/A"))
            cells["telemetry"] = resolve_cell(telemetry_status.get(key, "Sin Datos"), label, elapsed)
            sources["telemetry"] = telemetry_spelling.get(key)
        if applicable["oil"]:
            label, elapsed = freshness.get(("oil", key), ("Sin Datos", "N/A"))
            cells["oil"] = resolve_cell(oil_status.get(key, "Sin Datos"), label, elapsed, oil_value.get(key))
            sources["oil"] = oil_spelling.get(key)
        if applicable["maintenance"]:
            # Data-availability signal only: Mantención has no status in the General tab.
            cells["maintenance"] = resolve_cell(maintenance_status.get(key, "Sin Datos"), maint_label, maint_elapsed)
            sources["maintenance"] = maintenance_spelling.get(key)
        if applicable["predictive"]:
            cells["predictive"] = resolve_cell(
                predictive_status.get(key, "Sin Datos"), predictive_label, predictive_elapsed, predictive_value.get(key),
            )

        # The unit's name: how the first technique that knows it spells it (alerts, telemetry, oil), hyphenated.
        name_from = next((spellings[t][key] for t in ("alerts", "telemetry", "oil") if key in spellings[t]), key)
        estado, _worst, _alerta_or_worse = unit_estado({t: c.value for t, c in cells.items()})

        row = {"unit_id": normalize_unit_id(name_from), "estado": estado, "generated_at": generated_at}
        for technique, cell in cells.items():
            row.update({
                f"{technique}_estado": cell.value,
                f"{technique}_status": cell.label,
                f"{technique}_data_state": cell.estado_datos,
                f"{technique}_driver": cell.driver,
                f"{technique}_explanation_key": cell.explanation_key,
                f"{technique}_elapsed": cell.elapsed,
                f"{technique}_score": _nullable(cell.score),
                f"{technique}_source_unit": sources.get(technique),
            })
        if applicable["alerts"]:
            counts = alert_counts.get(key, (0,) * len(ALERT_WINDOW_DAYS)) if alert_counts else (None,) * len(ALERT_WINDOW_DAYS)
            for days, count in zip(ALERT_WINDOW_DAYS, counts):
                row[f"alerts_count_{days}d"] = count
        rows.append(row)

    frame = pd.DataFrame(rows, columns=_columns(techniques, applicable["alerts"]))
    if frame.empty:
        return frame
    for technique in techniques:
        frame[f"{technique}_score"] = pd.to_numeric(frame[f"{technique}_score"], errors="coerce").astype("float64")
    if applicable["alerts"]:
        for days in ALERT_WINDOW_DAYS:
            frame[f"alerts_count_{days}d"] = frame[f"alerts_count_{days}d"].astype("Int64")
    return frame.sort_values("unit_id", kind="stable").reset_index(drop=True)


_CELL_FIELDS = ("estado", "status", "data_state", "driver", "explanation_key", "elapsed", "score", "source_unit")


def _columns(techniques: list, with_alert_counts: bool) -> list:
    columns = ["unit_id", "estado", "generated_at"]
    for technique in techniques:
        columns += [f"{technique}_{field}" for field in _CELL_FIELDS]
    if with_alert_counts:
        columns += [f"alerts_count_{days}d" for days in ALERT_WINDOW_DAYS]
    return columns


# ── The golden file ──────────────────────────────────────────────────────────

def golden_path(client: str, root=None) -> Path:
    """`data/general/golden/{client}/fleet_status.parquet`."""
    return dashboard_data_root(root) / "general" / "golden" / client.lower() / GOLDEN_FILE


def techniques_in(frame: pd.DataFrame) -> list:
    """The techniques a golden frame carries, in table order (the client's applicable ones)."""
    return [t for t in TECHNIQUES if f"{t}_estado" in frame.columns]


def _problem(frame: pd.DataFrame) -> Optional[str]:
    """Why a frame is not a publishable / readable golden file, or None."""
    if frame is None or frame.empty:
        return "it has no unit"
    missing = {"unit_id", "estado"} - set(frame.columns)
    if missing:
        return f"it lacks the columns {sorted(missing)}"
    techniques = techniques_in(frame)
    if not techniques:
        return "it has no technique"
    for technique in techniques:
        absent = [f"{technique}_{field}" for field in _CELL_FIELDS if f"{technique}_{field}" not in frame.columns]
        if absent:
            return f"it lacks the columns {absent}"
    if frame["unit_id"].isna().any() or not frame["unit_id"].map(lambda u: bool(str(u).strip())).all():
        return "a unit has no id"
    if frame["unit_id"].duplicated().any():
        return f"a unit appears twice ({frame.loc[frame['unit_id'].duplicated(), 'unit_id'].iloc[0]})"
    if not frame["estado"].isin(BANDS).all():
        return "a unit has an Estado that is not Anormal / Alerta / Normal / Sin Datos"
    return None


def write_golden(client: str, frame: pd.DataFrame, root=None) -> Path:
    """Publish `frame` as the client's golden file, all or nothing.

    The frame is validated, written beside the target, read back and checked, and only then swapped
    in with one atomic replace. Any failure leaves the previous file exactly as it was and no partial
    file behind. A successful run overwrites the previous output."""
    reason = _problem(frame)
    if reason:
        raise EmptyFleetError(f"{client}: nothing to publish: {reason}")
    path = golden_path(client, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        frame.to_parquet(temporary, index=False)
        written = pd.read_parquet(temporary)
        reason = _problem(written)
        if reason or len(written) != len(frame):
            raise OSError(f"{client}: the file written does not read back as the frame ({reason or 'row count'})")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return path


def refresh_client(client: str, root=None) -> Optional[Path]:
    """Build and publish one client. None when the client has no technique to show (nothing is written);
    raises (`EmptyFleetError` or whatever the sources raised) when the run fails - the previous file stays."""
    if not any(applicable_techniques(client).values()):
        return None
    return write_golden(client, build_fleet_status(client), root)


@lru_cache(maxsize=16)
def _read_cached(path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    """One generation of the file. Keyed by what identifies the generation, so the next run is picked up
    without a restart; the cached frame is read-only by convention."""
    frame = pd.read_parquet(path)
    reason = _problem(frame)
    if reason:
        raise FleetStatusUnavailable(f"{path} is not a valid fleet status file: {reason}")
    return frame


def load_fleet_status(client: str, root=None) -> pd.DataFrame:
    """The client's golden frame, as the last successful run left it. Raises :class:`FleetStatusUnavailable`
    when there is none or it cannot be read: callers say so and do not rebuild it from raw data."""
    path = golden_path(client, root)
    try:
        stat = path.stat()
    except OSError as exc:
        raise FleetStatusUnavailable(f"the fleet status of {client} has not been generated ({path})") from exc
    try:
        return _read_cached(str(path), stat.st_mtime_ns, stat.st_size)
    except FleetStatusUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - a corrupt / half-synced file is "unavailable", whatever pyarrow says
        raise FleetStatusUnavailable(f"the fleet status of {client} cannot be read ({path}): {exc}") from exc


def missing_clients(clients, root=None) -> list:
    """Of `clients`, those that have techniques to show and no golden file yet."""
    return [
        client for client in clients
        if any(applicable_techniques(client).values()) and not golden_path(client, root).is_file()
    ]


def source_units(client: str, unit: str) -> dict:
    """{technique: how that technique's own source spells `unit`}, from the golden file. The Unit Detail
    asks each technique's page for the unit by the spelling that page knows; {} when the file is not there."""
    try:
        frame = load_fleet_status(client)
    except FleetStatusUnavailable:
        return {}
    match = frame[frame["unit_id"] == normalize_unit_id(unit)]
    if match.empty:
        key = unit_key(unit)
        match = frame[frame["unit_id"].map(unit_key) == key]
    if match.empty:
        return {}
    row = match.iloc[0]
    return {
        technique: str(row[f"{technique}_source_unit"])
        for technique in techniques_in(frame)
        if f"{technique}_source_unit" in frame.columns and pd.notna(row[f"{technique}_source_unit"])
    }


__all__ = [
    "ALERT_WINDOW_DAYS", "Cell", "EmptyFleetError", "FleetStatusUnavailable", "TECHNIQUES", "applicable_techniques", "build_fleet_status", "calculate_alert_criticality_score",
    "count_alerts_by_window", "enabled_predictive_components", "get_predictive_component_status",
    "golden_path", "load_fleet_status", "missing_clients", "refresh_client", "resolve_cell",
    "source_units", "techniques_in", "write_golden",
]
