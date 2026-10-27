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
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional

import pandas as pd
from dash import dcc, html

from config.client_services import KNOWN_SERVICE_IDS, is_service_enabled
from config.estado_rules import (
    NO_STATUS_TECHNIQUES,
    RISK_RANK,
    STATUS_PRIORITY,
    band_for_priority,
    technique_estado,
    unit_estado,
)
from config.freshness_thresholds import FRESHNESS_CRITERIA
from dashboard.callbacks.data_freshness_callbacks import (
    calculate_freshness_status,
    convert_utc_to_chile,
    load_data_freshness,
)
from dashboard.components.labels import localize_elapsed, status_label
from dashboard.components.status_chip import STATUS_SOLID_COLORS, canonical_status, status_chip
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

# Worst-of priority (STATUS_PRIORITY) and the Estado rule itself live in
# config/estado_rules.py, imported above; this module only applies them.

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
# Tint of each band's icon badge (assets/status_chip.css).
_BAND_CSS = {"Anormal": "anormal", "Alerta": "alerta", "Normal": "normal", "Sin Datos": "nodata"}


def status_color(status: str, default: str) -> str:
    """Public: the solid severity color of `status` - the same tier colors the status
    chips (dashboard/components/status_chip.py) draw from. Charts inside a card that
    carries a chip must color their severity elements through this, never from a mapping
    of their own, so the two can't drift apart (10_unit_summary_monitoreo_polish_and_
    component_source_fix.md, Functional Rules). `default` is for statuses with no
    severity color (the no-data tone is a CSS variable, which a chart can't use)."""
    from dashboard.components.status_chip import canonical_status

    canonical = canonical_status(status)
    return STATUS_SOLID_COLORS[canonical] if canonical != "Sin Datos" else default


# ── max_risk: one shared severity ranking for label and estado_datos ────────
# The rule (worse of the technique's status and its data age, on Normal < Alerta <
# Anormal) is `config.estado_rules.technique_estado`; `max_risk` wraps its outcome with
# the data a cell needs to show and explain itself (08_fleet_overview_table_format.md,
# Functional Rules).
# What each freshness tier is called in the tooltip's plain-language text.
_DATA_STATE_TEXT_KEYS = {
    "Ok": "fleet_overview.data_state_ok", "Atención": "fleet_overview.data_state_attention",
    "Preocupante": "fleet_overview.data_state_concerning", "Sin Datos": "fleet_overview.data_state_no_data",
}


def _data_state_text(estado_datos: str) -> str:
    return _t(_DATA_STATE_TEXT_KEYS[estado_datos])


def _shown_status(label) -> str:
    """A technique's own status as the General tab names it: Crítico (Alertas) is Anormal,
    Atención is Alerta. Anything else is left as it is."""
    canonical = canonical_status(label)
    return canonical if canonical != "Sin Datos" or str(label).strip().casefold() == "sin datos" else label


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
    # Alerts only: (last week, last 4 weeks, last 8 weeks) alert counts.
    alert_counts: Optional[tuple] = None

    @property
    def explanation(self) -> str:
        return _t(
            self.explanation_key,
            label=status_label(_shown_status(self.label)),
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
            _t("fleet_overview.tooltip_technique_status", label=status_label(_shown_status(self.label))),
            _t("fleet_overview.tooltip_data_status", data_text=data_text),
        ]
        if self.score is not None and not pd.isna(self.score):
            lines.append(
                _t("fleet_overview.tooltip_severity_value")
                + (f"{self.score:.1f}" if isinstance(self.score, float) else str(self.score))
            )
        if self.alert_counts is not None:
            week, four_weeks, eight_weeks = self.alert_counts
            lines.append(_t(
                "fleet_overview.tooltip_alert_counts",
                week=week, four_weeks=four_weeks, eight_weeks=eight_weeks,
            ))
        lines.append(self.explanation)
        return "\n".join(lines)


def max_risk(label, estado_datos, elapsed: Optional[str] = None, score=None) -> MergedCell:
    """The worse of a technique's own status `label` and its data-freshness
    `estado_datos` (rule: `config.estado_rules.technique_estado`), as a cell.

    The technique's own `score` is kept only while it still explains the shown value:
    stale data that overrides the status takes it away.
    """
    label = str(label) if label else "Sin Datos"
    estado_datos = str(estado_datos) if estado_datos else "Sin Datos"
    resolution = technique_estado(label, estado_datos)
    return MergedCell(
        resolution.value, label, estado_datos, resolution.driver, resolution.explanation_key,
        elapsed, score if resolution.label_kept else None,
    )


def natural_key(unit) -> list:
    """Sort key for natural ascending order of unit IDs: CA-2 before CA-10, T_9 before T_10.
    The ID is split into text and number runs, so numbers compare as numbers; the split always
    alternates text, number, text... so two keys are comparable position by position."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(unit))]


def _normalize_unit_id(uid) -> str:
    """T_09 -> T_9, so Predictivo's zero-padded ids join cleanly against the
    other techniques' unit ids (same normalization tab_predictive_overview.py
    uses internally)."""
    m = re.match(r"^([A-Za-z]+_)0*(\d+)$", str(uid))
    return f"{m.group(1)}{m.group(2)}" if m else str(uid)


def _band_for_priority(priority: int) -> str:
    """Band of a resolved (non-zero) worst-of priority (config.estado_rules). Priority 0
    ("every applicable technique is Sin Datos/Sin Fuente/InsufficientData") is deliberately
    not handled by it - callers special-case it to the "Sin Datos" band
    (06_fleet_overview_revision_2.md, Required Changes #4) rather than let it fall through
    to "Normal": priority 1 is an actually-observed Normal reading, priority 0 is the
    absence of any reading at all, and those are not the same fact."""
    return band_for_priority(priority)


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


def _alerts_window_counts(client: str) -> dict:
    """{unit: (last week, last 4 weeks, last 8 weeks)} alert counts - what
    breaks ties between units with the same Alertas status (see the sort key in
    `_compute_unit_entries`) and what the Alertas tooltip lists. {} when the
    client has no alert feed."""
    from dashboard.callbacks.overview_general_callbacks import count_alerts_by_window

    return count_alerts_by_window(load_alerts_data(client))


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
    """Public: the tinted status chip. Unit Detail draws every technique and section
    status with it, so a status reads the same in both views."""
    return status_chip(status)


def _unit_link(unit: str):
    """The row's link to the unit's Unit Detail: a real `<a href>` (a `dcc.Link`, so
    navigating goes through Dash Pages' client-side router)."""
    return dcc.Link(unit, href=relative_path(unit_summary_path(unit)), className="fleet-unit-link")


def _estado_tooltip(overall_status: str, cells: dict) -> str:
    if overall_status == "Sin Datos":
        return _t("fleet_overview.estado_tooltip_no_data")
    drivers = [
        technique_label(tech) for tech, c in cells.items()
        if tech not in NO_STATUS_TECHNIQUES and c.value == overall_status
    ]
    return _t("fleet_overview.estado_tooltip", overall_status=status_label(overall_status), drivers=", ".join(drivers))


def chip_button(chip, tip: str, label: str) -> html.Button:
    """A status chip that explains itself: a real `<button>` whose explanation opens on hover,
    focus and click/Enter (assets/chip_popover.js) - never on hover alone. `label` is its
    accessible name."""
    return html.Button(
        chip, type="button", className="chip-button",
        **{"data-tip": tip, "aria-label": label},
    )


def _technique_cell(technique: str, cell: MergedCell):
    label = f"{technique_label(technique)}: {status_label(cell.value)}. {_t('fleet_overview.show_explanation')}"
    return html.Td(chip_button(status_chip(cell.value), cell.tooltip, label), className="fleet-table-cell")


def _unit_row(entry: dict):
    unit = entry["unit"]
    estado = entry["overall_status"]
    cells = entry["cells"]
    return html.Tr(
        [
            html.Td(_unit_link(unit), className="fleet-table-unit"),
            html.Td(
                chip_button(
                    status_chip(estado, solid=True), _estado_tooltip(estado, cells),
                    f"{_t('fleet_overview.col_status')}: {status_label(estado)}. {_t('fleet_overview.show_explanation')}",
                ),
                className="fleet-table-cell fleet-table-estado",
            ),
        ]
        + [_technique_cell(t, cells[t]) for t in entry["techniques"]],
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


def matching_entries(entries: list, query) -> list:
    """The entries whose unit ID contains `query` (case-insensitive); all of them when the
    query is empty."""
    needle = str(query or "").strip().casefold()
    if not needle:
        return entries
    return [e for e in entries if needle in str(e["unit"]).casefold()]


def get_band_rows_chunk(client: str, band: str, page: int, query=None) -> tuple:
    """Public: `(rows, remaining)` for chunk number `page` (0 is the first,
    already rendered with the band) of a band - `remaining` counts the units
    still not shown after this chunk. With a `query`, the band is the units matching it."""
    entries = matching_entries(_band_snapshot(client).get(band, []), query)
    start = PAGE_SIZE * page
    chunk = entries[start:start + PAGE_SIZE]
    return [_unit_row(e) for e in chunk], max(len(entries) - (start + len(chunk)), 0)


def _band_table(band: str, entries: list, techniques: list):
    """One table per status band, first page only. Columns come from the
    client's technique availability alone, so every row has a cell for every
    column - never hidden or blank for some rows (08, Required Changes #1)."""
    header = html.Thead(html.Tr(
        [
            html.Th(_t("fleet_overview.col_unit"), scope="col", className="fleet-table-unit"),
            html.Th(_t("fleet_overview.col_status"), scope="col"),
        ]
        + [html.Th(technique_label(tech), scope="col") for tech in techniques]
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

def build_fleet_overview(client: str, query=None, refresh: bool = True) -> html.Div:
    """Build the full Fleet Overview: bands (Anormal/Alerta/Normal), each
    containing a table of units (one row per unit, one column per applicable
    technique) sorted per the confirmed ranking rule (§3.3)."""
    if not client:
        return html.Div(html.P(_t("fleet_overview.select_client"), className="text-muted text-center p-4"))
    try:
        return _build_fleet_overview(client, query, refresh)
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

    This reads the exact same per-unit `max_risk` cells the table renders - for
    Mantención, which has no column, its cell is computed only for this signal -
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
    alerts_counts = _alerts_window_counts(client) if applicable["alerts"] else {}

    # ── Union of units across every technique that carries a status: a unit only
    # Maintenance knows about has no severity to show or rank, so it is dropped (here
    # and from the Unit Detail's unit list) rather than listed as an empty "Sin Datos"
    # row. ──
    units = set()
    units.update(alerts_status.keys())
    units.update(telemetry_status.keys())
    units.update(oil_status.keys())
    units.update(predictive_status.keys())

    if not units:
        return []

    # ── One pass per unit: compute each technique's merged cell, the overall
    # band and the §3.3 sort key. ──
    techniques = [t for t in TECHNIQUE_LABELS if applicable[t] and t not in NO_STATUS_TECHNIQUES]
    entries = []
    for unit in units:
        unit_norm = _normalize_unit_id(unit)
        # {technique: MergedCell} - what the table renders: max_risk(label,
        # estado_datos) per technique (08, Required Changes #3). Every
        # applicable technique always gets a cell, even for a unit with no
        # record (that reads Sin Datos through max_risk, never blank).
        cells: dict[str, MergedCell] = {}
        # Per-technique status keyed the same as TECHNIQUE_LABELS - what the
        # Unit Detail reads its status tiles and card chips from. It is the
        # table's merged value, never recomputed: the Fleet Overview and the
        # Unit Detail are one rule applied to one set of inputs, so they
        # stay consistent whatever state the upstream pipelines are in.
        # Techniques without a status (Mantención) are not in it.
        technique_status: dict[str, str] = {}

        def add(technique, raw_status, fresh_label, fresh_elapsed, score=None):
            cells[technique] = max_risk(raw_status, fresh_label, fresh_elapsed, score)
            if technique not in NO_STATUS_TECHNIQUES:
                technique_status[technique] = cells[technique].value

        # (last week, last 4 weeks, last 8 weeks); zeros for a unit with no
        # alert at all, None when the client has no alert feed to count from.
        unit_alert_counts = alerts_counts.get(unit, (0, 0, 0)) if alerts_counts else None

        if applicable["alerts"]:
            add("alerts", alerts_status.get(unit, "Sin Datos"), alerts_fresh_label,
                alerts_fresh_elapsed, alerts_value.get(unit))
            if unit_alert_counts is not None:
                cells["alerts"] = replace(cells["alerts"], alert_counts=unit_alert_counts)

        if applicable["telemetry"]:
            label, elapsed = telem_tribo_freshness.get(("telemetry", unit), ("Sin Datos", "N/A"))
            # The unit's telemetry score is not shown in the General tab: the Estado says it.
            add("telemetry", telemetry_status.get(unit, "Sin Datos"), label, elapsed)

        if applicable["oil"]:
            label, elapsed = telem_tribo_freshness.get(("oil", unit), ("Sin Datos", "N/A"))
            add("oil", oil_status.get(unit, "Sin Datos"), label, elapsed, oil_value.get(unit))

        if applicable["maintenance"]:
            # Data-availability signal only (see `technique_availability`): Mantención
            # has no status in the General tab.
            add("maintenance", maintenance_status.get(unit, "Sin Datos"), maint_fresh_label, maint_fresh_elapsed)

        if applicable["predictive"]:
            add(
                "predictive",
                predictive_status.get(unit_norm, predictive_status.get(unit, "Sin Datos")),
                predictive_fresh_label, predictive_fresh_elapsed,
                predictive_value.get(unit_norm, predictive_value.get(unit)),
            )

        # Overall status = worst-of the merged cells (config.estado_rules.unit_estado,
        # which leaves Maintenance out), so the Estado column is always consistent with
        # the cells next to it. "Sin Datos" means every applicable cell is Sin Datos -
        # never a resolved Normal reading - and must not band/label as "Normal"
        # (06_fleet_overview_revision_2.md, Required Changes #4).
        band, _worst, _alerta_or_worse = unit_estado({t: c.value for t, c in cells.items()})
        # Within a band, units go in natural ascending ID order (CA-2 before CA-10): a
        # stable place for every unit, whatever its readings.
        sort_key = natural_key(unit)

        entries.append({
            "unit": unit,
            "band": band,
            "sort_key": sort_key,
            "overall_status": band,  # band label doubles as the overall status name
            "technique_status": technique_status,
            "techniques": techniques,
            "cells": cells,
        })

    entries.sort(key=lambda e: (_BAND_ORDER.index(e["band"]), e["sort_key"]))
    return entries


def get_ordered_units(client: str) -> list:
    """Ordered `{unit, band, overall_status, technique_status}` list, in
    the same order the Fleet Overview renders units - used by the Unit
    Detail navigation bar for prev/next lateral navigation and its unit
    switcher, and for the banner's current status. Returns [] if the client
    has no applicable techniques or no units."""
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
            "technique_status": e["technique_status"],
        }
        for e in entries
    ]


def get_unit_snapshot(client: str, unit: str):
    """A single unit's `{unit, band, overall_status, technique_status}`,
    or None if that unit isn't found for this client (Unit Detail's banner)."""
    for entry in get_ordered_units(client):
        if entry["unit"] == unit:
            return entry
    return None


def _band_slug(band: str) -> str:
    return band.lower().replace(" ", "-")


def _band_section(band: str, band_entries: list, matches: list, techniques: list, expanded: bool) -> html.Div:
    """One status band: a toggle button (tinted icon badge, title, unit count) and the
    band's table. The toggle is a real `<button aria-expanded aria-controls>`. `band_entries`
    is the whole band (the count in the header never changes with a search); `matches` is what
    the table lists. `expanded` is the state it is rendered in; the user's own choice is kept
    client-side afterwards (assets/fleet_overview_state.js)."""
    css = _BAND_CSS[band]
    body_id = f"fleet-band-body-{_band_slug(band)}"
    return html.Div([
        html.Button([
            html.Span(html.I(className=_BAND_ICONS[band]), className=f"icon-badge icon-badge--{css}",
                      **{"aria-hidden": "true"}),
            html.Span(_t(_BAND_LABEL_KEYS[band]), className="fleet-band-title"),
            html.Span(f"({len(band_entries)})", className="fleet-band-count"),
            html.I(className="fas fa-chevron-down fleet-band-chevron", **{"aria-hidden": "true"}),
        ], type="button", className="fleet-band-header" + ("" if expanded else " fleet-band-collapsed"),
            **{"data-fleet-band-toggle": "true", "aria-expanded": "true" if expanded else "false",
               "aria-controls": body_id}),
        html.Div(
            _band_table(band, matches, techniques),
            id=body_id,
            className="fleet-table-wrap",
            style=None if expanded else {"display": "none"},
            **{"data-fleet-band-body": "true"},
        ),
    ], **{"data-fleet-band": band.lower()})


def _build_fleet_overview(client: str, query=None, refresh: bool = True) -> html.Div:
    """The bands. `refresh=False` lays them out from the last full build instead of reading the
    data again (what a search does while typing). With a `query`, every band lists only the
    units whose ID contains it, the bands with matches are open and the others keep their
    place; without one only Anormal starts open."""
    if refresh or client not in _SNAPSHOTS:
        entries = _compute_unit_entries(client)
        entries_by_band = _group_by_band(entries)
        _SNAPSHOTS[client] = entries_by_band
    else:
        entries_by_band = _SNAPSHOTS[client]
        entries = [e for band in _BAND_ORDER for e in entries_by_band[band]]
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
    query = str(query or "").strip()

    sections = []
    any_match = False
    for band in _BAND_ORDER:
        band_entries = entries_by_band[band]
        if not band_entries:
            continue
        matches = matching_entries(band_entries, query)
        any_match = any_match or bool(matches)
        expanded = bool(matches) if query else band == "Anormal"
        sections.append(_band_section(band, band_entries, matches, techniques, expanded))

    if query and not any_match:
        sections.insert(0, html.P(_t("fleet_overview.search_no_results", query=query),
                                  className="text-muted p-2", role="status"))
    return html.Div(sections, **({"data-fleet-search": "active"} if query else {}))
