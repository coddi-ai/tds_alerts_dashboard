"""
Estado vocabulary shared by every Predictivo chart and the Resumen KPI cards.

Two independent classifications exist for a unit (Data Contract §6): the short
view's `unit_status_summary.estado` (lowercase) and the long view's
`cumulative_risk_curve.estado` (Title Case). Each chart styles its points with
its own `estado`; only the KPI aggregate uses `combine_states`.
"""

import unicodedata
from typing import Optional

import pandas as pd

from src.i18n import t

# ── Per-failure-mode status: `risk_scores.risk_level` ────────────────────────
#
# The status of a failure mode (unit x day x mode) is the `risk_level` that
# `risk_scores` delivers - never anything computed from `risk_value`, a ranking
# or a threshold in consumer code. The values are the data contract's spelling
# (note `Critico` has no accent). This table is the one place a level gets its
# color and label, so every Predictivo surface that draws a mode status agrees.
#
# Palette: the previous Calendario de estado colors. The technical lead's
# canonical palette is not in the repo yet; swap the values here when it lands.
RISK_LEVELS = ("Saludable", "Monitoreo", "Prioridad alta", "Critico")  # low -> high
RISK_LEVEL_STYLE = {
    # color: solid (calendar cell, legend); cell_bg / cell_text: light table-cell tone
    "Saludable":      {"color": "#1d9e75", "cell_bg": "#eaf3de", "cell_text": "#3b6d11",
                       "label_key": "predictive_charts.band_healthy"},
    "Monitoreo":      {"color": "#f2d04b", "cell_bg": "#fdf3c4", "cell_text": "#7a5f00",
                       "label_key": "predictive_charts.band_monitoring"},
    "Prioridad alta": {"color": "#ef7f27", "cell_bg": "#fde4cf", "cell_text": "#9a4a0a",
                       "label_key": "predictive_charts.band_high_priority"},
    "Critico":        {"color": "#e24b4a", "cell_bg": "#fcebeb", "cell_text": "#a32d2d",
                       "label_key": "predictive_charts.band_critical"},
}
# A mode/day with no `risk_scores` row: "no data", never implicitly Saludable.
RISK_LEVEL_NO_DATA_COLOR = "#e5e7eb"


def _fold(text: str) -> str:
    """Case- and accent-insensitive key: `Crítico` / `Critico` / `CRITICO` -> `critico`."""
    decomposed = unicodedata.normalize("NFKD", str(text).strip())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


_RISK_LEVEL_BY_FOLDED = {_fold(level): level for level in RISK_LEVELS}


def normalize_risk_level(value) -> Optional[str]:
    """The contract spelling of a `risk_level` value, or None when it is missing or
    not one of the four known levels (an unknown value is never guessed)."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return _RISK_LEVEL_BY_FOLDED.get(_fold(value))


def risk_level_label(value) -> str:
    """Display text of a `risk_level` (translated); "Sin datos" when it has none."""
    level = normalize_risk_level(value)
    if level is None:
        return t("oil_machine_detail.sin_datos")
    return t(RISK_LEVEL_STYLE[level]["label_key"])


# ── Unit state (`estado`) ─────────────────────────────────────────────────────

# Severity order, low -> high: Normal < Alerta < Anormal.
STATE_ORDER = ("Normal", "Alerta", "Anormal")
STATE_SEVERITY = {state: rank for rank, state in enumerate(STATE_ORDER)}

# The one color rule of every Predictivo scatter-style chart: red Anormal, yellow
# Alerta, green Normal. Color encodes the state and nothing else - two units in
# the same state share their color and are told apart by their label.
STATE_COLORS = {"Anormal": "#e24b4a", "Alerta": "#eab308", "Normal": "#1d9e75"}

# Background zone tints (Short View quadrants, Long View reference band) in the
# same red/yellow/green language, and the dark shade of each used for zone text.
STATE_ZONE_FILL = {
    "Anormal": "rgba(239,68,68,0.27)",
    "Alerta": "rgba(250,204,21,0.30)",
    "Normal": "rgba(29,158,117,0.20)",
}
STATE_ZONE_TEXT = {"Anormal": "#8a1f1e", "Alerta": "#7a5a05", "Normal": "#0b5a43"}

# Marker size relative to the Normal (baseline) marker of the same chart.
STATE_SIZE_FACTOR = {"Normal": 1.0, "Alerta": 1.2, "Anormal": 1.5}


def normalize_state(value) -> Optional[str]:
    """`normal` / "Normal " / `ANORMAL` -> `Normal`. Anything that is not one of
    the three states ("Sin Datos", None, NaN) -> None."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    title = str(value).strip().title()
    return title if title in STATE_SEVERITY else None


def state_marker_size(state, base: float) -> float:
    """`base` scaled by the state's factor (Anormal 1.5x, Alerta 1.2x, Normal 1x);
    a missing/unknown state keeps the baseline."""
    return base * STATE_SIZE_FACTOR.get(normalize_state(state), 1.0)


def combine_states(short_state, long_state) -> Optional[str]:
    """The worse of the short-view and long-view `estado`.

    A side that is missing (unit absent from that table) contributes nothing, so
    it is never read as Normal; None when both are missing. Only for the KPI
    aggregate - it must not replace either source `estado` anywhere else.
    """
    states = [s for s in (normalize_state(short_state), normalize_state(long_state)) if s]
    return max(states, key=STATE_SEVERITY.__getitem__) if states else None
