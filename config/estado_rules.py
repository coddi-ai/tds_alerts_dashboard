"""
Estado rule: how a technique's status and a unit's Estado are decided.

This is the one place to read or change that rule on the dashboard side. Fleet Overview
(`dashboard/components/fleet_overview.py`) and Unit Detail (`unit_summary*.py`) both get
their Estado from the functions below, so the two views cannot disagree about a unit.
Full write-up with real examples: documentation/general/estado_rule.md.

The rule has three layers; only the last two are computed by the dashboard:

1. **Components -> technique status (upstream, not here).** The data pipelines publish
   the roll-up already done: Tribologia's `machine_status.overall_status` (weighted sum of
   component points, thresholds in documentation/oil/oil_data_contracts.md), Telemetria's
   `unit_health.overall_status`, Alertas' criticality score
   (`calculate_alert_criticality_score`) and Predictivo's `unit_status_summary.estado`.
   The dashboard reads those values as they come.
2. **Technique status x data age -> technique Estado (`technique_estado`).** The worse of
   the technique's own status and what its data age implies. How old is "too old" per
   technique lives in `config/freshness_thresholds.py` (`FRESHNESS_CRITERIA`); what each
   age tier forces is `STALENESS_FLOOR` below. To stop stale data from forcing Anormal,
   edit `STALENESS_FLOOR` (e.g. map "Preocupante" to "Alerta") or the thresholds.
3. **Technique Estados -> unit Estado (`unit_estado`).** The worst technique wins.
   Techniques in `NO_STATUS_TECHNIQUES` never take part.

Mantencion is operational information (SANO / DETENIDO), not severity: it has no status in
the General tab and never contributes to any Estado.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Mapping, NamedTuple, Optional

from config.freshness_thresholds import FRESHNESS_CRITERIA

# ── Vocabulary ───────────────────────────────────────────────────────────────

# Worst-of priority shared by every technique's status vocabulary. "Critico" (Alertas) is
# a synonym of Anormal. A missing reading (Sin Datos / Sin Fuente / InsufficientData) is
# priority 0: it is never confused with a checked-and-healthy one.
STATUS_PRIORITY = {
    "Anormal": 3, "Crítico": 3,
    "Alerta": 2, "Atención": 2,
    "Normal": 1,
    "Sin Datos": 0, "Sin Fuente": 0, "InsufficientData": 0,
}

# The three levels a status can end up at: Normal < Alerta < Anormal.
RISK_RANK = {"Normal": 1, "Alerta": 2, "Anormal": 3}

# A technique's own status label -> level. SANO / DETENIDO (Mantencion) rank as Normal:
# operational, never severity.
LABEL_TO_RISK = {
    "Normal": "Normal", "SANO": "Normal", "DETENIDO": "Normal",
    "Alerta": "Alerta", "Atención": "Alerta",
    "Anormal": "Anormal", "Crítico": "Anormal",
}

# ── Staleness rule ───────────────────────────────────────────────────────────

# What each data-age tier forces as a floor on the technique's Estado. Age tiers come from
# `FRESHNESS_CRITERIA` (Ok / Atención / Preocupante). With the values below, data past the
# last threshold of its technique forces Anormal and data past the first one forces Alerta.
STALENESS_FLOOR = {"Ok": "Normal", "Atención": "Alerta", "Preocupante": "Anormal"}

# Techniques with no status in the General tab: no column, no tile, and they never enter
# the unit Estado. Their data availability is still reported in "Fuentes de datos".
NO_STATUS_TECHNIQUES = ("maintenance",)


class Resolution(NamedTuple):
    """Outcome of `technique_estado`.

    `value`: the Estado to show. `driver`: what decided it - "label" (the technique's own
    status), "data" (data age), "both" (same level) or "none" (no reading). `explanation_key`
    is the catalog key of the sentence that says so; `label_kept` is False when the
    technique's own value (score, ranking) no longer explains `value`.
    """
    value: str
    driver: str
    explanation_key: str
    label_kept: bool


def technique_estado(label, data_age_tier) -> Resolution:
    """Estado of one technique for one unit: the worse of its own status `label` and what
    `data_age_tier` (Ok / Atención / Preocupante / Sin Datos) forces through `STALENESS_FLOOR`.

    - No reading (label Sin Datos / Sin Fuente / InsufficientData / empty) is "Sin Datos"
      whatever the data age: there is no status to degrade, and a fresh client-wide feed
      must not turn a missing reading into a healthy-looking one.
    - A data age that cannot be determined leaves the technique's own label in force.
    - Ties show the technique's own label (so SANO / DETENIDO stay readable).
    """
    label = str(label) if label else "Sin Datos"
    data_age_tier = str(data_age_tier) if data_age_tier else "Sin Datos"
    label_risk = LABEL_TO_RISK.get(label)
    data_risk = STALENESS_FLOOR.get(data_age_tier)
    operational = label in ("SANO", "DETENIDO")

    if label_risk is None:
        return Resolution("Sin Datos", "none", "fleet_overview.explain_none", False)
    if data_risk is None:
        return Resolution(label if operational else label_risk, "label", "fleet_overview.explain_label_only", True)

    label_rank, data_rank = RISK_RANK[label_risk], RISK_RANK[data_risk]
    if data_rank > label_rank:
        return Resolution(data_risk, "data", "fleet_overview.explain_data_wins", False)
    shown = label if operational else label_risk
    if label_rank > data_rank:
        return Resolution(shown, "label", "fleet_overview.explain_label_wins", True)
    return Resolution(shown, "both", "fleet_overview.explain_both", True)


# ── Unit Estado ──────────────────────────────────────────────────────────────

BANDS = ("Anormal", "Alerta", "Normal", "Sin Datos")


def priority_of(value) -> int:
    return STATUS_PRIORITY.get(value, 0)


def band_for_priority(priority: int) -> str:
    """Band of a resolved (non-zero) worst-of priority. Priority 0 (every technique without
    a reading) is "Sin Datos", never "Normal": see `unit_estado`."""
    if priority >= 3:
        return "Anormal"
    if priority >= 2:
        return "Alerta"
    return "Normal"


def unit_estado(technique_values: Mapping[str, str]) -> tuple[str, int, int]:
    """`(estado, worst_priority, techniques_in_alerta_or_worse)` of a unit from its
    techniques' Estados `{technique: value}`.

    The worst technique wins; techniques in `NO_STATUS_TECHNIQUES` are skipped. When no
    technique has a reading the Estado is "Sin Datos".
    """
    priorities = [priority_of(v) for tech, v in technique_values.items() if tech not in NO_STATUS_TECHNIQUES]
    worst = max(priorities, default=0)
    estado = "Sin Datos" if worst == 0 else band_for_priority(worst)
    return estado, worst, sum(1 for p in priorities if p >= 2)


# ── Plain-language description of the staleness rule ─────────────────────────

def freshness_limits(freshness_key: str) -> Optional[tuple[timedelta, timedelta]]:
    """`(limit for Ok, limit for Atención)` of a technique's data age, from
    `FRESHNESS_CRITERIA`: data older than the first is Atención, older than the second is
    Preocupante. None when the technique has no criteria."""
    criteria = FRESHNESS_CRITERIA.get(freshness_key)
    if not criteria:
        return None
    return criteria[0][0], criteria[1][0]


def staleness_floor_limits(freshness_key: str) -> dict[str, timedelta]:
    """`{Estado forced: age beyond which it is forced}` for a technique, e.g. Telemetria
    -> {"Alerta": 2h, "Anormal": 24h}. Derived from `STALENESS_FLOOR` and the thresholds,
    so any text built from it stays true to the rule."""
    limits = freshness_limits(freshness_key)
    if limits is None:
        return {}
    ok_limit, attention_limit = limits
    by_tier = {"Atención": ok_limit, "Preocupante": attention_limit}
    forced: dict[str, timedelta] = {}
    for tier, age in by_tier.items():
        estado = STALENESS_FLOOR.get(tier)
        if estado in ("Alerta", "Anormal") and estado not in forced:
            forced[estado] = age
    return forced

