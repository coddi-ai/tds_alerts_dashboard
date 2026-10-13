"""
Fleet Overview — unified per-unit table (Phase 1, table format per 08).

Revised by documentation/general/general_specs/08_fleet_overview_table_format.md:
the per-unit KPI cards are replaced by one table per status band - rows =
units, columns = Unidad, Estado and one column per technique applicable to
the client. Each technique cell shows `max_risk(label, estado_datos)` (see
`max_risk` below) and its hover tooltip is generated from that same
evaluation. Cell colors reuse the Monitoring > Oil table's scheme
(dashboard/callbacks/machines_callbacks.py). The card-specific items of
04/06 (card grid, freshness pill, severity chip) are retired; their
data-correctness rules are satisfied in table form. The history below
describes the original card design and the rules that still apply.

Implements documentation/general/general_specs/01_fleet_overview_unified_view.md,
built on the Confirmed business rules from
documentation/general/general_specs/00_implementation_guide.md §3.1-3.3:

- §3.1 Overall status = worst-of across applicable techniques, Maintenance
  fully excluded (own operational badge instead), per-client applicability
  gated via config.client_services.is_service_enabled.
- §3.2 Freshness thresholds per technique (config/freshness_thresholds.py).
- §3.3 Ranking = worst status priority, tiebreak = count of Alerta/Anormal
  techniques, then alphabetical unit id.

Replaces the old two-column ("Telemetría"/"Tribología") table in
dashboard/tabs/tab_overview_general.py and the separate Data Summary tab
(dashboard/tabs/tab_data_freshness.py, retired).

Revised by documentation/general/general_specs/
04_fleet_overview_status_and_freshness_revision.md (card-specific parts
superseded by 08): distinctly labeled overall/Maintenance badges, and a
technique's status never shown as trustworthy beside stale data - now done by
`max_risk` instead of the old "stale == Sin Datos" override.

Revised again by documentation/general/general_specs/
06_fleet_overview_revision_2.md: a unit whose every applicable technique is
"Sin Datos" now bands/labels as "Sin Datos" instead of silently reading
"Normal" (`_compute_unit_entries`'s zero-priority branch), the per-card
freshness text is a compact fragment instead of a full sentence
(`_freshness_badge`), and `technique_availability()` exposes the exact
per-technique data-availability signal the "Fuentes de datos" banner
(dashboard/components/source_status.py) now reads instead of an independent
file-existence probe.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd
from dash import dcc, html

from config.client_services import KNOWN_SERVICE_IDS, is_service_enabled
from config.freshness_thresholds import FRESHNESS_CRITERIA
from dashboard.callbacks.data_freshness_callbacks import (
    calculate_freshness_status,
    convert_utc_to_chile,
    load_data_freshness,
)
# Monitoring > Oil's table colors (light cell fill for per-component cells,
# solid fill for the machine-status column) - reused as-is so the Fleet
# Overview introduces no palette of its own (08, Required Changes #5).
from dashboard.callbacks.machines_callbacks import (
    _MACHINE_STATUS_BG,
    _MACHINE_STATUS_FG,
    _STATUS_BG,
    _STATUS_FG,
)
from dashboard.components.labels import NO_DATA_BG, NO_DATA_TEXT, localize_elapsed, status_label
from src.i18n import t as _t, t_or as _t_or
from dashboard.services_registry import relative_path, unit_summary_path
from src.data.loaders import (
    load_alerts_data,
    load_machine_status_for_client,
    load_maintenance_equipment_status,
    load_telemetry_unit_health,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Technique registry ──────────────────────────────────────────────────────
# Row order on every card matches the spec's order: Alerts, Telemetry, Oil,
# Maintenance, Predictive Models.

TECHNIQUE_LABELS = {
    "alerts": "Alertas",
    "telemetry": "Telemetría",
    "oil": "Tribología",
    "maintenance": "Mantención",
    "predictive": "Predictivo",
}

def technique_label(technique: str) -> str:
    """Display label of a technique in the current language (TECHNIQUE_LABELS holds the Spanish source)."""
    return _t_or(f"fleet_overview.technique_{technique}", TECHNIQUE_LABELS[technique])


# Service id gate per technique (§2.4/§3.1). Predictive has no single service
# id - it's applicable if any predictive-<component> id is enabled.
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

# Worst-of priority order shared by every technique's status vocabulary.
# Crítico (Alerts) is a confirmed synonym for Anormal (§3.1). InsufficientData
# (Telemetry) and Sin Datos/Sin Fuente all sit at priority 0 - a missing
# signal is never confused with a checked-and-healthy one (§3.1).
STATUS_PRIORITY = {
    "Anormal": 3, "Crítico": 3,
    "Alerta": 2, "Atención": 2,
    "Normal": 1,
    "Sin Datos": 0, "Sin Fuente": 0, "InsufficientData": 0,
}

_STATUS_COLORS = {
    "Anormal": {"border": "#e24b4a", "bg": "#fcebeb", "text": "#a32d2d"},
    "Alerta":  {"border": "#ef9f27", "bg": "#faeeda", "text": "#854f0b"},
    "Normal":  {"border": "#1d9e75", "bg": "#eaf3de", "text": "#3b6d11"},
    "Crítico": {"border": "#e24b4a", "bg": "#fcebeb", "text": "#a32d2d"},
    "DETENIDO": {"border": "#e24b4a", "bg": "#fcebeb", "text": "#a32d2d"},
    "SANO":     {"border": "#1d9e75", "bg": "#eaf3de", "text": "#3b6d11"},
}
_NO_DATA_COLORS = {"border": "var(--border-strong)", "bg": NO_DATA_BG, "text": NO_DATA_TEXT}

# "Sin Datos" is appended after the three severity bands, never inserted
# between them - 06_fleet_overview_revision_2.md's Functional Rules keep the
# existing Anormal -> Alerta -> Normal grouping/order intact. It exists
# because "every applicable technique reported Sin Datos" is not the same
# fact as "every applicable technique reported Normal", and conflating the
# two is exactly the contradiction that revision fixes (Required Changes #4).
_BAND_ORDER = ["Anormal", "Alerta", "Normal", "Sin Datos"]
_BAND_LABEL_KEYS = {
    "Anormal": "fleet_overview.band_abnormal",
    "Alerta": "fleet_overview.band_alert",
    "Normal": "fleet_overview.band_normal",
    "Sin Datos": "fleet_overview.band_no_data",
}
# Icon-driven scannability (ui_notes.md): one recognizable icon per band,
# consistent with the status vocabulary used across every technique card.
_BAND_ICONS = {
    "Anormal": "fas fa-exclamation-circle",
    "Alerta": "fas fa-exclamation-triangle",
    "Normal": "fas fa-check-circle",
    "Sin Datos": "fas fa-question-circle",
}


def _status_colors(status: str) -> dict:
    return _STATUS_COLORS.get(status, _NO_DATA_COLORS)


def status_color(status: str, default: str) -> str:
    """Public: the solid severity color of `status` - the same mapping
    `status_badge()` draws from. Charts inside a card that carries a badge
    must color their severity elements through this, never from a mapping of
    their own, so the two can't drift apart (10_unit_summary_monitoreo_polish_
    and_component_source_fix.md, Functional Rules). `default` is for statuses
    with no severity color (the no-data tone is a CSS variable, which a chart
    can't use)."""
    colors = _STATUS_COLORS.get(status)
    return colors["border"] if colors else default


# ── max_risk: one shared severity ranking for label and estado_datos ────────
# (08_fleet_overview_table_format.md, Functional Rules). Both inputs are
# mapped onto Normal < Alerta < Anormal. Freshness tiers map one-to-one onto
# the Normal/Alerta/Anormal columns of 00_implementation_guide.md §3.2
# (Ok/Atención/Preocupante); technique labels use their confirmed synonyms
# (Crítico == Anormal, §3.1). Maintenance's operational SANO/DETENIDO is not
# a severity gradient (§3.1), so it ranks as Normal here: it can be degraded
# by stale data but never contributes severity of its own.
RISK_RANK = {"Normal": 1, "Alerta": 2, "Anormal": 3}
_LABEL_TO_RISK = {
    "Normal": "Normal", "SANO": "Normal", "DETENIDO": "Normal",
    "Alerta": "Alerta", "Atención": "Alerta",
    "Anormal": "Anormal", "Crítico": "Anormal",
}
_DATA_TO_RISK = {"Ok": "Normal", "Atención": "Alerta", "Preocupante": "Anormal"}
# What each freshness tier is called in the tooltip's plain-language text.
_DATA_STATE_TEXT_KEYS = {
    "Ok": "fleet_overview.data_state_ok", "Atención": "fleet_overview.data_state_attention",
    "Preocupante": "fleet_overview.data_state_concerning", "Sin Datos": "fleet_overview.data_state_no_data",
}


def _data_state_text(estado_datos: str) -> str:
    return _t(_DATA_STATE_TEXT_KEYS[estado_datos])


@dataclass(frozen=True)
class MergedCell:
    """Result of one `max_risk` evaluation - the cell's displayed value and
    the tooltip, both derived from the same rule application so the
    explanation can never drift from the logic (08, Functional Rules)."""
    value: str
    label: str
    estado_datos: str
    driver: str  # "label" | "data" | "both" | "none"
    # Catalog key of the explanation. The text itself is rendered on demand (see
    # `explanation`): cells are cached in `_SNAPSHOTS` and shared across requests, so
    # storing the sentence would freeze it in the language of whoever built the cache.
    explanation_key: str
    elapsed: Optional[str] = None
    score: Optional[float] = None

    @property
    def explanation(self) -> str:
        return _t(
            self.explanation_key,
            label=status_label(self.label),
            estado_datos=status_label(self.estado_datos),
            data_state=_data_state_text(self.estado_datos) if self.estado_datos in _DATA_STATE_TEXT_KEYS else "",
            shown=status_label(self.value),
        )

    @property
    def tooltip(self) -> str:
        data_text = status_label(self.estado_datos)
        if self.elapsed and self.elapsed != "N/A":
            data_text += _t("fleet_overview.tooltip_last_update", elapsed=localize_elapsed(self.elapsed))
        lines = [
            _t("fleet_overview.tooltip_technique_status", label=status_label(self.label)),
            _t("fleet_overview.tooltip_data_status", data_text=data_text),
        ]
        if self.score is not None and not pd.isna(self.score):
            lines.append(
                _t("fleet_overview.tooltip_severity_value")
                + (f"{self.score:.1f}" if isinstance(self.score, float) else str(self.score))
            )
        lines.append(self.explanation)
        return "\n".join(lines)


def max_risk(label, estado_datos, elapsed: Optional[str] = None, score=None) -> MergedCell:
    """The worse of a technique's own status `label` and its data-freshness
    `estado_datos`, on the shared Normal < Alerta < Anormal ranking.

    - A technique with no reading for the unit (label Sin Datos/Sin Fuente/
      InsufficientData/None) is "Sin Datos" whatever its freshness: there is
      no status to degrade, and a client-wide fresh feed must not turn a
      missing reading into a healthy-looking cell (Functional Rules: never
      "Normal" without supporting data).
    - A freshness state that can't be determined (Sin Datos) leaves the
      technique's own label in force; the tooltip says so.
    - Ties show the technique's own label (so Maintenance keeps SANO/
      DETENIDO while its data is as fresh as the status is benign).
    """
    label = str(label) if label else "Sin Datos"
    estado_datos = str(estado_datos) if estado_datos else "Sin Datos"
    label_risk = _LABEL_TO_RISK.get(label)
    data_risk = _DATA_TO_RISK.get(estado_datos)

    if label_risk is None:
        return MergedCell(
            "Sin Datos", label, estado_datos, "none",
            "fleet_overview.explain_none",
            elapsed, score,
        )
    if data_risk is None:
        return MergedCell(
            label_risk if label not in ("SANO", "DETENIDO") else label,
            label, estado_datos, "label",
            "fleet_overview.explain_label_only",
            elapsed, score,
        )

    label_rank, data_rank = RISK_RANK[label_risk], RISK_RANK[data_risk]
    if data_rank > label_rank:
        return MergedCell(
            data_risk, label, estado_datos, "data",
            "fleet_overview.explain_data_wins",
            elapsed, None,  # the technique's own score no longer explains the cell
        )
    shown = label if label in ("SANO", "DETENIDO") else label_risk
    if label_rank > data_rank:
        why = "fleet_overview.explain_label_wins"
        driver = "label"
    else:
        why = "fleet_overview.explain_both"
        driver = "both"
    return MergedCell(shown, label, estado_datos, driver, why, elapsed, score)


def _normalize_unit_id(uid) -> str:
    """T_09 -> T_9, so Predictivo's zero-padded ids join cleanly against the
    other techniques' unit ids (same normalization tab_predictive_overview.py
    uses internally)."""
    m = re.match(r"^([A-Za-z]+_)0*(\d+)$", str(uid))
    return f"{m.group(1)}{m.group(2)}" if m else str(uid)


def _band_for_priority(priority: int) -> str:
    """Maps a resolved (non-zero) worst-of priority to its band. Priority 0
    ("every applicable technique is Sin Datos/Sin Fuente/InsufficientData")
    is deliberately not handled here - callers must special-case it to the
    "Sin Datos" band themselves (06_fleet_overview_revision_2.md, Required
    Changes #4) rather than let it fall through to "Normal": priority 1 is
    an actually-observed Normal reading, priority 0 is the absence of any
    reading at all, and those are not the same fact."""
    if priority >= 3:
        return "Anormal"
    if priority >= 2:
        return "Alerta"
    return "Normal"


# ── Freshness helpers ────────────────────────────────────────────────────────

def _freshness_from_naive_timestamp(last_update, technique: str) -> tuple[str, str]:
    """Freshness for techniques whose reference clock is a plain (tz-naive,
    day/week-scale) timestamp: Alertas (max feed Timestamp), Predictivo
    (model run date), Mantenciones (query_10 reference_date). Distinct from
    Telemetria/Tribologia's tz-aware, CSV-sourced freshness below, which
    predates this module and is left untouched (§3.2: "unchanged")."""
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
    """Per-unit freshness for Telemetria/Tribologia, sourced from
    Data_Date_Last_Update.csv exactly as before (§3.2: thresholds unchanged).
    Returns {(technique, normalized_unit): (label, elapsed_str)}."""
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


# ── Per-technique per-unit status builders ──────────────────────────────────

def _alerts_status_map(client: str, days: int = 30) -> tuple[dict, dict, str, str]:
    """Returns ({unit: status}, {unit: criticality_score}, freshness_label,
    freshness_elapsed). Status vocabulary: Normal/Alerta/Crítico (Crítico ==
    Anormal, §3.1). Freshness is client-wide (max Timestamp across the
    client's alert feed, §1.1), applied identically to every unit's Alertas
    row. `criticality_score` is Alerts' only per-unit severity concept
    (§1.1) - restores the underlying value behind the status color
    (04_..._revision.md, Required Changes #4)."""
    from dashboard.callbacks.overview_general_callbacks import calculate_alert_criticality_score

    df_alerts = load_alerts_data(client)
    if df_alerts.empty or "UnitId" not in df_alerts.columns:
        return {}, {}, "Sin Datos", "N/A"

    scores = calculate_alert_criticality_score(df_alerts, days)
    status_map = dict(zip(scores["equipo"], scores["status"])) if not scores.empty else {}
    value_map = dict(zip(scores["equipo"], scores["criticality_score"])) if not scores.empty else {}

    max_ts = pd.to_datetime(df_alerts["Timestamp"], errors="coerce").max()
    freshness_label, elapsed = _freshness_from_naive_timestamp(max_ts, "alerts")
    return status_map, value_map, freshness_label, elapsed


def _telemetry_status_map(client: str) -> tuple[dict, dict]:
    """Returns ({unit: status}, {unit: unit_score}). `unit_score` is
    Telemetry's per-unit health score (§1.2's `unit_health` fields) -
    restores the underlying value behind the status color (04_..._revision.md,
    Required Changes #4)."""
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
    """Returns ({unit: status}, {unit: machine_score}). `machine_score` is
    Oil's documented weighted per-machine score (§1.3) - restores the
    underlying value behind the status color (04_..._revision.md, Required
    Changes #4)."""
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
    """Returns ({machine_code: 'SANO'/'DETENIDO'}, freshness_label, elapsed).
    Freshness comes from query_10's own `reference_date`, per machine when
    present - falls back to the max available reference_date for the client
    otherwise (§1.4: "inferred from the max available period")."""
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


def _enabled_predictive_components(client: str) -> list:
    return [
        sid.split("predictive-", 1)[1]
        for sid in KNOWN_SERVICE_IDS
        if sid.startswith("predictive-") and is_service_enabled(client, sid)
    ]


def _component_predictive_status_maps(client: str, component: str) -> tuple[dict, dict]:
    """Per-unit {normalized_unit: estado}/{normalized_unit: ranking} for a
    single predictive component - factored out of `_predictive_status_map`
    below so the Unit Summary Predictivo tab's per-sub-model status
    (Required Changes #5 of documentation/general/general_specs/
    05_unit_summary_restructure_and_predictive_comparison.md) can share the
    exact same estado/ranking computation as the Fleet Overview's
    multi-component worst-of aggregation - a sub-model card's status can
    never diverge from what fed into the merged Predictivo row for the same
    unit/component (Functional Rules: "never recalculated independently")."""
    from src.data import predictive_v2
    from src.data.loaders import get_latest_analisis_inteligente

    df_status = predictive_v2.load_unit_status_summary(client, component)
    estado_map: dict[str, str] = {}
    ranking_map: dict[str, float] = {}
    if not df_status.empty and "estado" in df_status.columns:
        estado_map = {
            _normalize_unit_id(u): str(e).strip().title()
            for u, e in zip(df_status["Unit"], df_status["estado"])
        }
        if "ranking" in df_status.columns:
            ranking_map = {
                _normalize_unit_id(u): r
                for u, r in zip(df_status["Unit"], df_status["ranking"])
            }
    if not estado_map:
        df_legacy = get_latest_analisis_inteligente(client, component)
        if not df_legacy.empty and "estado" in df_legacy.columns:
            estado_map = {
                _normalize_unit_id(u): str(e).strip().title()
                for u, e in zip(df_legacy["Unit"], df_legacy["estado"])
            }
            if "ranking" in df_legacy.columns:
                ranking_map = {
                    _normalize_unit_id(u): r
                    for u, r in zip(df_legacy["Unit"], df_legacy["ranking"])
                }
    return estado_map, ranking_map


def get_predictive_component_status(client: str, unit: str, component: str) -> tuple:
    """Public: a single unit's status/ranking for one predictive sub-model
    (e.g. Motor, Transmisión), sourced from the same per-component
    computation the Fleet Overview's merged Predictivo row is built from
    (`_component_predictive_status_maps` above) - used by the Unit Summary
    Predictivo tab (Required Changes #5). Returns `(None, None)` when the
    unit has no record for this component's latest run - the caller applies
    the confirmed no-data fallback (00_implementation_guide.md §3.1:
    `attach_status()`'s "Sin Datos", never a silent default).

    The status is the same `max_risk(estado, freshness)` merge the Fleet
    Overview table applies to the merged Predictivo cell (against this
    component's own model run date), so a sub-model's status can never
    disagree with the table for the same data - including once the upstream
    pipeline is fixed and the data stops being stale."""
    from src.data.loaders import get_model_run_date

    estado_map, ranking_map = _component_predictive_status_maps(client, component)
    unit_norm = _normalize_unit_id(unit)
    estado = estado_map.get(unit_norm)
    if estado is None:
        return None, None

    run_date = get_model_run_date(client, component)
    freshness_label, elapsed = _freshness_from_naive_timestamp(run_date, "predictive")
    cell = max_risk(estado, freshness_label, elapsed)
    # The ranking only explains the status while the model's own estado is
    # what's being shown; stale data that overrides it takes the ranking away.
    ranking = ranking_map.get(unit_norm) if cell.driver in ("label", "both") else None
    return cell.value, ranking


def _predictive_status_map(client: str, components: list) -> tuple[dict, dict, str, str]:
    """Worst-of status per unit across every enabled predictive component.
    A unit absent from every component's estado map is left out here - the
    caller applies "Sin Datos" for it (§3.1's confirmed attach_status() fix:
    an absent unit is never silently defaulted to Normal).

    Also returns {unit: ranking} - the component's today-ranking value that
    drove the worst status, matching what the original Predictive Models KPI
    card showed alongside status (`_priority_card`'s `score=r["ranking"]`,
    dashboard/tabs/tab_predictive_overview.py) - restores the underlying
    value behind the status color (04_..._revision.md, Required Changes #4).

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


# ── Table rendering ──────────────────────────────────────────────────────────

def status_badge(status: str):
    """Public: reused by the Unit Summary navigation shell's sticky header
    (Phase 2) so both views render the same overall/maintenance badge."""
    colors = _status_colors(status)
    return html.Span(status_label(status), className="status-badge", style={
        "background": colors["bg"], "color": colors["text"],
    })


def _cell_colors(value: str) -> dict:
    """Light cell fill/text for a technique cell - Monitoring > Oil's
    per-component cell scheme (`_STATUS_BG`/`_STATUS_FG`). Maintenance's
    operational values borrow the same scheme (SANO as Normal, DETENIDO as
    Anormal, matching how they were colored on the cards)."""
    key = {"SANO": "Normal", "DETENIDO": "Anormal"}.get(value, value)
    if key in _STATUS_BG:
        return {"bg": _STATUS_BG[key], "text": _STATUS_FG[key]}
    return {"bg": NO_DATA_BG, "text": NO_DATA_TEXT}


def _estado_colors(status: str) -> dict:
    """Solid fill for the Estado column - Monitoring > Oil's machine-status
    column scheme (`_MACHINE_STATUS_BG`/`_MACHINE_STATUS_FG`)."""
    if status in _MACHINE_STATUS_BG:
        return {"bg": _MACHINE_STATUS_BG[status], "text": _MACHINE_STATUS_FG[status]}
    return {"bg": NO_DATA_BG, "text": NO_DATA_TEXT}


def _row_link(unit: str, child, title: Optional[str] = None, style: Optional[dict] = None):
    """Every cell's content is a link to the unit's Unit Summary, so the
    whole row is clickable (08, Required Changes #6; Phase 2's entry point,
    02_unit_summary_navigation_shell.md #1). A `dcc.Link` (not `html.A`) so
    navigating goes through Dash Pages' client-side router."""
    return dcc.Link(
        child,
        href=relative_path(unit_summary_path(unit)),
        title=title,
        className="fleet-cell-link",
        style=style,
    )


def _estado_tooltip(overall_status: str, cells: dict) -> str:
    if overall_status == "Sin Datos":
        return _t("fleet_overview.estado_tooltip_no_data")
    drivers = [
        technique_label(tech) for tech, c in cells.items()
        if tech != "maintenance" and c.value == overall_status
    ]
    return _t("fleet_overview.estado_tooltip", overall_status=status_label(overall_status), drivers=", ".join(drivers))


def _technique_cell(unit: str, cell: MergedCell):
    colors = _cell_colors(cell.value)
    return html.Td(
        _row_link(unit, status_label(cell.value), title=cell.tooltip),
        className="fleet-table-cell",
        style={"backgroundColor": colors["bg"], "color": colors["text"]},
    )


def _unit_row(entry: dict):
    unit = entry["unit"]
    estado = entry["overall_status"]
    estado_colors = _estado_colors(estado)
    cells = entry["cells"]
    return html.Tr(
        [
            html.Td(_row_link(unit, unit), className="fleet-table-unit"),
            html.Td(
                _row_link(unit, status_label(estado), title=_estado_tooltip(estado, cells)),
                className="fleet-table-cell fleet-table-estado",
                style={"backgroundColor": estado_colors["bg"], "color": estado_colors["text"]},
            ),
        ]
        + [_technique_cell(unit, cells[t]) for t in entry["techniques"]],
        className="fleet-table-row",
    )


# ── Pagination ───────────────────────────────────────────────────────────────
# A band renders its first PAGE_SIZE rows; further chunks are fetched on demand
# (`get_band_rows_chunk`, appended by the "Mostrar siguientes" callback in
# dashboard/callbacks/overview_general_callbacks.py). Fleets like EMIN have
# ~870 units, which as full tables meant ~2 MB / ~10k components shipped and
# built on every visit.
PAGE_SIZE = 50

# {client: {band: [entry, ...]}} from the last Fleet Overview build, so
# "load more" serves rows from the very ordering the user is looking at
# instead of recomputing (and possibly reordering) between clicks. A worker
# that never built this client's page simply recomputes - same data, same
# order.
_SNAPSHOTS: dict = {}


def _group_by_band(entries: list) -> dict:
    grouped: dict = {band: [] for band in _BAND_ORDER}
    for entry in entries:
        grouped[entry["band"]].append(entry)
    return grouped


def _band_snapshot(client: str) -> dict:
    snapshot = _SNAPSHOTS.get(client)
    if snapshot is None:
        snapshot = _SNAPSHOTS[client] = _group_by_band(_compute_unit_entries(client))
    return snapshot


def more_button_label(remaining: int) -> str:
    return _t("fleet_overview.show_more", count=min(PAGE_SIZE, remaining), remaining=remaining)


def get_band_rows_chunk(client: str, band: str, page: int) -> tuple:
    """Public: `(rows, remaining)` for chunk number `page` (0 is the first,
    already rendered with the band) of a band - `remaining` counts the units
    still not shown after this chunk."""
    entries = _band_snapshot(client).get(band, [])
    start = PAGE_SIZE * page
    chunk = entries[start:start + PAGE_SIZE]
    return [_unit_row(e) for e in chunk], max(len(entries) - (start + len(chunk)), 0)


def _band_table(band: str, entries: list, techniques: list):
    """One table per status band, first page only. Columns come from the
    client's technique availability alone, so every row has a cell for every
    column - never hidden or blank for some rows (08, Required Changes #1)."""
    header = html.Thead(html.Tr(
        [html.Th(_t("fleet_overview.col_unit"), className="fleet-table-unit"), html.Th(_t("fleet_overview.col_status"))]
        + [html.Th(technique_label(tech)) for tech in techniques]
    ))
    table = html.Table(
        [header, html.Tbody(
            [_unit_row(e) for e in entries[:PAGE_SIZE]],
            id={"type": "fleet-rows", "band": band},
        )],
        className="fleet-table",
    )
    remaining = max(len(entries) - PAGE_SIZE, 0)
    if not remaining:
        return table
    button = html.Button(
        more_button_label(remaining),
        id={"type": "fleet-more", "band": band},
        n_clicks=0,
        className="fleet-more-btn",
    )
    return html.Div([table, button])


# ── Top-level orchestration ─────────────────────────────────────────────────

def build_fleet_overview(client: str) -> html.Div:
    """Build the full Fleet Overview: bands (Anormal/Alerta/Normal), each
    containing a table of units (one row per unit, one column per applicable
    technique) sorted per the confirmed ranking rule (§3.3)."""
    if not client:
        return html.Div(html.P(_t("fleet_overview.select_client"), className="text-muted text-center p-4"))
    try:
        return _build_fleet_overview(client)
    except Exception:
        logger.exception("Error building Fleet Overview for client=%s", client)
        return html.Div(html.P(_t("fleet_overview.build_error"), className="text-danger text-center p-4"))


def _applicable_techniques(client: str) -> dict:
    applicable = {
        technique: is_service_enabled(client, service_id)
        for technique, service_id in TECHNIQUE_SERVICE_ID.items()
    }
    applicable["predictive"] = bool(_enabled_predictive_components(client))
    return applicable


def applicable_techniques(client: str) -> dict:
    """Public: which techniques are applicable for a client (§3.1 gate) -
    shared by the Fleet Overview table and the Unit Summary content (Phase 3,
    dashboard/components/unit_summary_content.py), so both views agree on
    which technique sections render at all."""
    return _applicable_techniques(client)


def enabled_predictive_components(client: str) -> list:
    """Public: enabled predictive components for a client - shared with the
    Unit Summary content (Phase 3)."""
    return _enabled_predictive_components(client)


def technique_availability(client: str) -> dict:
    """Public: {technique: bool} - whether a technique has at least one unit
    with a real reading (a merged table cell that isn't Sin Datos), for every
    technique applicable to this client (§3.1 gate; inapplicable techniques
    are omitted, matching how they get no column at all in the table).

    This reads the exact same per-unit `max_risk` cells the table renders -
    used by the "Fuentes de datos" banner
    (dashboard/components/source_status.py) instead of an independent raw
    file-existence probe, so the banner can never claim "Disponible" for a
    technique whose column the user is looking at right below it all reads
    "Sin Datos" (06_fleet_overview_revision_2.md, Required Changes #5, kept
    by 08's Functional Rules)."""
    if not client:
        return {}
    try:
        applicable = _applicable_techniques(client)
        entries = _compute_unit_entries(client)
    except Exception:
        logger.exception("Error computing technique availability for client=%s", client)
        return {}
    return {
        technique: any(
            e["cells"][technique].value != "Sin Datos"
            for e in entries if technique in e["cells"]
        )
        for technique, enabled in applicable.items()
        if enabled
    }


def _compute_unit_entries(client: str) -> list:
    """Per-unit status/band/ranking data, one entry per unit visible on the
    Fleet Overview, already ordered exactly as the Fleet Overview renders
    them (band, then the §3.3 ranking key). Shared by `_build_fleet_overview`
    (table) and the Unit Summary navigation shell - Phase 2,
    documentation/general/general_specs/02_unit_summary_navigation_shell.md -
    which needs the same ordering for its prev/next lateral navigation and
    unit switcher, and the same overall/maintenance status for its sticky
    header, without duplicating the per-technique aggregation rules
    (§3.1-§3.3). Returns [] if the client has no applicable techniques or no
    units."""
    applicable = _applicable_techniques(client)
    if not any(applicable.values()):
        return []

    predictive_components = _enabled_predictive_components(client)

    alerts_status, alerts_value, alerts_fresh_label, alerts_fresh_elapsed = (
        _alerts_status_map(client) if applicable["alerts"] else ({}, {}, "Sin Datos", "N/A")
    )
    telemetry_status, telemetry_value = (
        _telemetry_status_map(client) if applicable["telemetry"] else ({}, {})
    )
    oil_status, oil_value = _oil_status_map(client) if applicable["oil"] else ({}, {})
    maintenance_status, maint_fresh_label, maint_fresh_elapsed = (
        _maintenance_status_map(client) if applicable["maintenance"] else ({}, "Sin Datos", "N/A")
    )
    predictive_status, predictive_value, predictive_fresh_label, predictive_fresh_elapsed = (
        _predictive_status_map(client, predictive_components) if applicable["predictive"] else ({}, {}, "Sin Datos", "N/A")
    )
    telem_tribo_freshness = _telemetry_tribologia_freshness_map(client)

    # ── Union of units across every technique actually enabled for this client ──
    units = set()
    units.update(alerts_status.keys())
    units.update(telemetry_status.keys())
    units.update(oil_status.keys())
    units.update(maintenance_status.keys())
    units.update(predictive_status.keys())

    if not units:
        return []

    # ── One pass per unit: compute each technique's merged cell, the overall
    # band and the §3.3 sort key. ──
    techniques = [t for t in TECHNIQUE_LABELS if applicable[t]]
    entries = []
    for unit in units:
        unit_norm = _normalize_unit_id(unit)
        # {technique: MergedCell} - what the table renders: max_risk(label,
        # estado_datos) per technique (08, Required Changes #3). Every
        # applicable technique always gets a cell, even for a unit with no
        # record (that reads Sin Datos through max_risk, never blank).
        cells: dict[str, MergedCell] = {}
        # Per-technique status keyed the same as TECHNIQUE_LABELS - what the
        # Unit Summary content (documentation/general/general_specs/
        # 05_unit_summary_restructure_and_predictive_comparison.md, Required
        # Changes #2) reads its per-card status labels from. It is the
        # table's merged value, never recomputed: the Fleet Overview and the
        # Unit Summary are one rule applied to one set of inputs, so they
        # stay consistent whatever state the upstream pipelines are in.
        technique_status: dict[str, str] = {}

        def add(technique, raw_status, fresh_label, fresh_elapsed, score=None):
            cells[technique] = max_risk(raw_status, fresh_label, fresh_elapsed, score)
            technique_status[technique] = cells[technique].value

        if applicable["alerts"]:
            add("alerts", alerts_status.get(unit, "Sin Datos"), alerts_fresh_label,
                alerts_fresh_elapsed, alerts_value.get(unit))

        if applicable["telemetry"]:
            label, elapsed = telem_tribo_freshness.get(("telemetry", unit), ("Sin Datos", "N/A"))
            add("telemetry", telemetry_status.get(unit, "Sin Datos"), label, elapsed,
                telemetry_value.get(unit))

        if applicable["oil"]:
            label, elapsed = telem_tribo_freshness.get(("oil", unit), ("Sin Datos", "N/A"))
            add("oil", oil_status.get(unit, "Sin Datos"), label, elapsed, oil_value.get(unit))

        maintenance_badge_status = None
        if applicable["maintenance"]:
            raw_maintenance_status = maintenance_status.get(unit, "Sin Datos")
            add("maintenance", raw_maintenance_status, maint_fresh_label, maint_fresh_elapsed)
            maintenance_badge_status = technique_status["maintenance"]

        if applicable["predictive"]:
            add(
                "predictive",
                predictive_status.get(unit_norm, predictive_status.get(unit, "Sin Datos")),
                predictive_fresh_label, predictive_fresh_elapsed,
                predictive_value.get(unit_norm, predictive_value.get(unit)),
            )

        # Overall status = worst-of the merged cells, Maintenance excluded
        # (§3.1/§3.3) - so the Estado column is always consistent with the
        # cells next to it. Priority 0 means every applicable (non-
        # Maintenance) cell is Sin Datos - or there was no applicable
        # technique to evaluate at all - never a resolved Normal reading
        # (that would be priority 1); it must not band/label as "Normal"
        # (06_fleet_overview_revision_2.md, Required Changes #4).
        priorities = [
            STATUS_PRIORITY.get(cell.value, 0)
            for technique, cell in cells.items() if technique != "maintenance"
        ]
        overall_priority = max(priorities) if priorities else 0
        band = "Sin Datos" if overall_priority == 0 else _band_for_priority(overall_priority)
        # §3.3: worst-priority (implicit - band already sorts on it), then
        # count of Alerta/Anormal techniques (desc), then alphabetical.
        alerta_anormal_count = sum(1 for p in priorities if p >= 2)
        sort_key = (-alerta_anormal_count, unit)

        entries.append({
            "unit": unit,
            "band": band,
            "sort_key": sort_key,
            "overall_status": band,  # band label doubles as the overall status name
            "maintenance_status": maintenance_badge_status,
            "technique_status": technique_status,
            "techniques": techniques,
            "cells": cells,
        })

    entries.sort(key=lambda e: (_BAND_ORDER.index(e["band"]), e["sort_key"]))
    return entries


def get_ordered_units(client: str) -> list:
    """Ordered `{unit, band, overall_status, maintenance_status}` list, in
    the same order the Fleet Overview renders units - used by the Unit
    Summary navigation shell (Phase 2) for prev/next lateral navigation and
    its unit switcher, and for the sticky header's current status. Returns
    [] if the client has no applicable techniques or no units."""
    if not client:
        return []
    try:
        entries = _compute_unit_entries(client)
    except Exception:
        logger.exception("Error computing unit order for client=%s", client)
        return []
    return [
        {
            "unit": e["unit"],
            "band": e["band"],
            "overall_status": e["overall_status"],
            "maintenance_status": e["maintenance_status"],
            "technique_status": e["technique_status"],
        }
        for e in entries
    ]


def get_unit_snapshot(client: str, unit: str):
    """A single unit's `{unit, band, overall_status, maintenance_status}`,
    or None if that unit isn't found for this client (Unit Summary's sticky
    header, Phase 2)."""
    for entry in get_ordered_units(client):
        if entry["unit"] == unit:
            return entry
    return None


def _build_fleet_overview(client: str) -> html.Div:
    entries = _compute_unit_entries(client)
    if not entries:
        if not any(_applicable_techniques(client).values()):
            return html.Div(html.P(
                _t("fleet_overview.no_techniques"),
                className="text-muted text-center p-4",
            ))
        return html.Div(html.P(_t("fleet_overview.no_units"), className="text-muted text-center p-4"))

    # Columns depend only on the client's technique availability, so every
    # band's table shares the same set (08, Required Changes #1).
    techniques = entries[0]["techniques"]
    entries_by_band = _group_by_band(entries)
    _SNAPSHOTS[client] = entries_by_band

    sections = []
    for band in _BAND_ORDER:
        band_entries = entries_by_band[band]
        if not band_entries:
            continue
        colors = _status_colors(band)
        sections.append(html.Div([
            html.Div([
                html.I(className="fas fa-chevron-down me-2 fleet-band-chevron"),
                html.I(className=f"{_BAND_ICONS[band]} me-2", style={"color": colors["text"]}),
                html.Span(f"{_t(_BAND_LABEL_KEYS[band])} ({len(band_entries)})", style={
                    "fontWeight": "700", "fontSize": "13px", "color": colors["text"],
                    "textTransform": "uppercase", "letterSpacing": "0.04em",
                }),
            ], className="fleet-band-header", style={
                "borderLeft": f"3px solid {colors['border']}",
                "paddingLeft": "10px", "margin": "18px 0 10px",
                "display": "flex", "alignItems": "center", "cursor": "pointer", "userSelect": "none",
            }, **{"data-fleet-band-toggle": "true"}),
            # Collapse/expand + scroll position are persisted client-side
            # (dashboard/assets/fleet_overview_state.js) via the
            # data-fleet-band* hooks above/below - state preservation on
            # return-to-Fleet-Overview, Phase 2 §Required Changes #5.
            html.Div(
                _band_table(band, band_entries, techniques),
                className="fleet-table-wrap",
                **{"data-fleet-band-body": "true"},
            ),
        ], **{"data-fleet-band": band.lower()}))

    return html.Div(sections)
