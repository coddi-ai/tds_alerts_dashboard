"""
Estado vocabulary shared by every Predictivo chart and the Resumen KPI cards.

Two independent classifications exist for a unit (Data Contract §6): the short
view's `unit_status_summary.estado` (lowercase) and the long view's
`cumulative_risk_curve.estado` (Title Case). Each chart styles its points with
its own `estado`; only the KPI aggregate uses `combine_states`.
"""

from typing import Optional

import pandas as pd

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
