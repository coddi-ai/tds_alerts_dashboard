"""Maintenance time and reliability KPIs, with the formulas of Monitoreo > Mantenciones.

The chat must report the numbers a user sees on that tab, so these functions reproduce
`src/data/maintenance_repository.py` rather than inventing a second definition:

- **Downtime** is the sum of `intervention_hours` from query 8 (hours already deduplicated per
  equipment and day upstream).
- **Availability** is calendar availability, ``(calendar - downtime) / calendar``. The
  denominator is ``calendar_hours_month`` of the equipment-months in query 8, except for the
  fleet of the clients in ``FLEET_DAILY_CLIENTS``, where the tab divides by the whole fleet's
  calendar from query 9 (``calendar_hours_fleet``). That difference is the tab's, kept here on
  purpose so both screens agree; it is not a choice made by this module.
- **MTBF** is ``sum(mtbf_hours * n_mtbf_intervals) / sum(n_mtbf_intervals)`` over query 5 rows
  with a valid MTBF, and **MTTR** is ``sum(total_downtime_hours) / sum(n_failures)``.

These are pure functions over frames, so the repository keeps its injected data root and the
parity test can drive them against the tab over the same files. A missing or invalid value is
reported as ``None``, never as a zero.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import pandas as pd

# Clients whose fleet availability the tab computes from query 9 instead of query 8. Mirrors
# the `self.client == "emin"` branch of MaintenanceRepository.get_monthly_payload.
FLEET_DAILY_CLIENTS = frozenset({"emin"})

HOURS_PER_DAY = 24
MAX_MONTHS = 24
MONTH_PATTERN = r"\d{4}-\d{2}"


def _for_client(frame: Optional[pd.DataFrame], client: str) -> pd.DataFrame:
    """Rows of this client only, as the tab filters `source_system`."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    frame = frame.copy()
    if "source_system" in frame.columns:
        frame = frame[frame["source_system"].astype("string").str.upper().eq(client.upper())]
    if "year_month" in frame.columns:
        frame["year_month"] = frame["year_month"].astype("string").str.strip()
    return frame


def _finite(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.notna() & numeric.map(lambda value: math.isfinite(float(value)) if pd.notna(value) else False)


def _round(value: Optional[float], digits: int = 1) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def available_months(hours: pd.DataFrame) -> list[str]:
    if hours.empty or "year_month" not in hours.columns:
        return []
    months = hours.loc[hours["year_month"].str.fullmatch(MONTH_PATTERN, na=False), "year_month"]
    return sorted(months.dropna().unique().tolist())


def reference_day(fleet_daily: pd.DataFrame) -> Optional[pd.Timestamp]:
    """Newest day covered by the source: the "today" of the data, not of the clock."""
    if fleet_daily.empty or "day" not in fleet_daily.columns:
        return None
    days = pd.to_datetime(fleet_daily["day"], errors="coerce").dropna()
    return days.max().normalize() if not days.empty else None


def is_partial_month(period: str, reference: Optional[pd.Timestamp]) -> bool:
    """A month the source has not finished covering cannot be compared with full months."""
    if reference is None:
        return False
    month = pd.Period(period, freq="M")
    return reference.to_period("M") == month and reference.day < month.days_in_month


def default_period(months: list[str], reference: Optional[pd.Timestamp]) -> Optional[str]:
    """The latest complete month; the latest month only when it is the only one there is."""
    if not months:
        return None
    latest = months[-1]
    if is_partial_month(latest, reference) and len(months) > 1:
        return months[-2]
    return latest


def month_window(period: str, months: int) -> list[str]:
    end = pd.Period(period, freq="M")
    count = max(1, min(int(months), MAX_MONTHS))
    return [str(value) for value in pd.period_range(end - (count - 1), end, freq="M")]


def time_kpis(
    client: str,
    hours: pd.DataFrame,
    fleet_daily: pd.DataFrame,
    window: list[str],
    unit_id: str = "",
) -> dict[str, Any]:
    """Downtime and calendar availability for the months in `window`."""
    hours = _for_client(hours, client)
    rows = hours[hours["year_month"].isin(window)] if not hours.empty else hours
    if unit_id and not rows.empty:
        rows = rows[rows["machine_code"].astype(str).eq(unit_id)]

    use_fleet = not unit_id and client.lower() in FLEET_DAILY_CLIENTS and not fleet_daily.empty
    if use_fleet:
        fleet = _for_client(fleet_daily, client)
        fleet["day"] = pd.to_datetime(fleet["day"], errors="coerce")
        fleet = fleet[fleet["day"].dt.strftime("%Y-%m").isin(window)]
        valid = _finite(fleet["intervention_hours"]) & _finite(fleet["calendar_hours_fleet"])
        fleet = fleet[valid]
        downtime = float(pd.to_numeric(fleet["intervention_hours"]).sum())
        calendar = float(pd.to_numeric(fleet["calendar_hours_fleet"]).sum())
        machines = pd.to_numeric(fleet.get("n_machines_fleet"), errors="coerce").dropna()
        equipment = int(machines.max()) if not machines.empty else None
        source = "query_9_fleet_intervention_daily (flota completa × días observados)"
    else:
        if rows.empty:
            return {"availability_pct": None, "downtime_hours": None, "calendar_hours": None,
                    "equipment": 0, "source": "query_8_intervention_hours_monthly"}
        valid = (_finite(rows["intervention_hours"]) & _finite(rows["calendar_hours_month"])
                 & pd.to_numeric(rows["calendar_hours_month"], errors="coerce").gt(0))
        rows = rows[valid]
        downtime = float(pd.to_numeric(rows["intervention_hours"]).sum())
        calendar = float(pd.to_numeric(rows["calendar_hours_month"]).sum())
        equipment = int(rows["machine_code"].nunique())
        source = "query_8_intervention_hours_monthly (equipos con historia en el mes)"

    availability = (calendar - downtime) / calendar * 100 if calendar > 0 and downtime <= calendar else None
    return {
        "availability_pct": _round(availability),
        "downtime_hours": _round(downtime) if calendar > 0 else None,
        "calendar_hours": _round(calendar),
        "equipment": equipment,
        "source": source,
    }


def reliability_kpis(
    client: str,
    reliability: pd.DataFrame,
    window: list[str],
    unit_id: str = "",
) -> dict[str, Any]:
    """Weighted MTBF and MTTR, exactly as the tab's cards weight query 5."""
    empty = {"mtbf_hours": None, "mttr_hours": None, "failures": 0, "mtbf_intervals": 0,
             "low_confidence_rows": 0, "rows": 0}
    frame = _for_client(reliability, client)
    if frame.empty:
        return empty
    frame = frame[frame["year_month"].isin(window)]
    if unit_id:
        frame = frame[frame["machine_code"].astype(str).eq(unit_id)]
    if frame.empty:
        return empty

    failures = pd.to_numeric(frame["n_failures"], errors="coerce")
    intervals = pd.to_numeric(frame["n_mtbf_intervals"], errors="coerce")
    mtbf = pd.to_numeric(frame["mtbf_hours"], errors="coerce")
    downtime = pd.to_numeric(frame["total_downtime_hours"], errors="coerce")

    valid_mtbf = intervals.gt(0) & _finite(intervals) & _finite(mtbf) & mtbf.ge(0)
    weight = intervals.where(valid_mtbf, 0.0)
    mtbf_value = (mtbf.where(valid_mtbf, 0.0) * weight).sum() / weight.sum() if weight.sum() > 0 else None

    valid_mttr = failures.gt(0) & _finite(failures) & _finite(downtime) & downtime.ge(0)
    failure_weight = failures.where(valid_mttr, 0.0)
    mttr_value = (
        downtime.where(valid_mttr, 0.0).sum() / failure_weight.sum() if failure_weight.sum() > 0 else None
    )
    low = frame["low_confidence"].fillna(False).astype(bool) if "low_confidence" in frame.columns else None
    return {
        "mtbf_hours": _round(mtbf_value),
        "mttr_hours": _round(mttr_value),
        "failures": int(failures.where(valid_mttr, 0).sum()),
        "mtbf_intervals": int(weight.sum()),
        "low_confidence_rows": int(low.sum()) if low is not None else 0,
        "rows": int(len(frame)),
    }


def unit_ranking(
    client: str,
    hours: pd.DataFrame,
    reliability: pd.DataFrame,
    window: list[str],
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Equipment ordered by downtime in the window, with their own availability and failures.

    Per-equipment availability always uses query 8, the only source with a calendar per unit.
    """
    frame = _for_client(hours, client)
    if frame.empty:
        return []
    frame = frame[frame["year_month"].isin(window)]
    valid = _finite(frame["intervention_hours"]) & _finite(frame["calendar_hours_month"])
    frame = frame[valid].copy()
    frame["intervention_hours"] = pd.to_numeric(frame["intervention_hours"])
    frame["calendar_hours_month"] = pd.to_numeric(frame["calendar_hours_month"])
    totals = frame.groupby("machine_code")[["intervention_hours", "calendar_hours_month"]].sum()
    totals = totals[totals["intervention_hours"] > 0].sort_values("intervention_hours", ascending=False)
    grand_total = float(totals["intervention_hours"].sum())

    rows: list[dict[str, Any]] = []
    cumulative = 0.0
    for unit, values in totals.head(max(1, int(top_n))).iterrows():
        cumulative += float(values["intervention_hours"])
        calendar = float(values["calendar_hours_month"])
        reliability_unit = reliability_kpis(client, reliability, window, unit_id=str(unit))
        rows.append({
            "unit_id": str(unit),
            "downtime_hours": _round(values["intervention_hours"]),
            "share_pct": _round(100 * float(values["intervention_hours"]) / grand_total),
            "cumulative_pct": _round(100 * cumulative / grand_total),
            "availability_pct": _round((calendar - values["intervention_hours"]) / calendar * 100) if calendar else None,
            "failures": reliability_unit["failures"],
            "mtbf_hours": reliability_unit["mtbf_hours"],
            "mttr_hours": reliability_unit["mttr_hours"],
        })
    return rows


def units_with_downtime(client: str, hours: pd.DataFrame, window: list[str]) -> int:
    frame = _for_client(hours, client)
    if frame.empty:
        return 0
    frame = frame[frame["year_month"].isin(window)]
    return int((frame.groupby("machine_code")["intervention_hours"].sum() > 0).sum())
