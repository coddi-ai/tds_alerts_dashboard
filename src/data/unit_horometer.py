"""Unit-level horómetro (machine hours) for the Unit Detail banner.

Source: `data/oil/golden/{client}/cleaned_component_hours.parquet`, which holds hours per
component (`componentHours_cleaned`, one reading per unit + component per sample date).
There is no unit-level row in it, so the unit value has to be derived. The rule used
(PENDING TEAM CONFIRMATION, see HOROMETER_RULE below): the unit's horómetro is the largest
of the latest hours reading of each of its components.

Why: a component that was replaced restarts its count, while chassis-level systems (e.g.
hidráulico, dirección) carry the machine's own hours. On CDA T_10 the latest readings run
from 2,120 h (transmisión) to 116,846 h (hidráulico, dirección); the machine has run
116,846 h, which is the maximum, not the average or the motor's 13,785 h. On a client with
a single component (CAPSTONE: motor diesel) it is that component's hours.

When the unit has no reading, or the client has no file, the value is None and the banner
shows "—".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

from config.settings import get_settings
from src.data.loaders import get_latest_component_hours
from src.utils.logger import get_logger

logger = get_logger(__name__)

# The single place that says how a unit's horómetro is derived. Change the aggregation in
# `unit_horometer` if the team confirms another field or row.
HOROMETER_RULE = "max of the latest componentHours_cleaned reading across the unit's components"


@dataclass(frozen=True)
class UnitHorometer:
    hours: float
    as_of: Optional[date]  # sample date of the reading that gave `hours`


def unit_horometer(client: str, unit: str) -> Optional[UnitHorometer]:
    """The unit's horómetro, or None when there is no reading for it (see module docstring)."""
    if not client or not unit:
        return None
    try:
        path = get_settings().get_component_hours_path(client.lower())
        if not path.exists():
            return None
        latest = get_latest_component_hours(path)
    except Exception:
        logger.exception("Could not read the horómetro for client=%s unit=%s", client, unit)
        return None
    if latest.empty or "componentHours_cleaned" not in latest.columns:
        return None

    rows = latest[latest["unitId"].astype(str) == str(unit)]
    rows = rows[pd.to_numeric(rows["componentHours_cleaned"], errors="coerce").notna()]
    if rows.empty:
        return None
    best = rows.loc[pd.to_numeric(rows["componentHours_cleaned"]).idxmax()]
    sample_date = pd.to_datetime(best.get("sampleDate"), errors="coerce")
    return UnitHorometer(
        hours=float(best["componentHours_cleaned"]),
        as_of=None if pd.isna(sample_date) else sample_date.date(),
    )
