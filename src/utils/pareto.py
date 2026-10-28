"""Cumulative-percentage cutoff shared by every Pareto chart.

A Pareto chart exists to show how concentrated activity is. A fixed "top N" cutoff
hides that when activity is spread flat: the few bars drawn are tiny next to an
"Otras" bar holding most of the total. So the cutoff is a *share of the total*:
bars are drawn, in descending order, until their running total reaches
``target_pct`` of the grand total, then the rest is folded into one aggregate bar.
``max_bars`` caps the individual bars so a genuinely flat distribution cannot draw
an unreadable number of them; when the cap, not the target, ended the walk the
reported share is the one actually reached.

One function, one set of parameters: callers pass their own target and cap, but the
rule itself lives only here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from src.i18n import t

DEFAULT_TARGET_PCT = 80.0
DEFAULT_MAX_BARS = 15


@dataclass(frozen=True)
class ParetoSplit:
    """Outcome of one cutoff.

    ``shown`` holds the rows drawn as their own bar (descending order, including any
    ``keep`` rows past the cutoff) and ``rest`` the rows folded into the aggregate bar.
    ``rule_units`` and ``reached_pct`` describe the cutoff rule itself, ignoring ``keep``.
    """

    shown: pd.DataFrame
    rest: pd.DataFrame
    total_units: int
    rule_units: int
    reached_pct: float
    target_pct: float
    capped: bool

    @property
    def has_others(self) -> bool:
        return not self.rest.empty

    @property
    def others_count(self) -> int:
        return len(self.rest)


def rule_unit_count(values: Iterable[float], target_pct: float, max_bars: int) -> tuple[int, float, bool]:
    """How many leading values the rule draws, the share they reach, and whether the cap
    (rather than the target) stopped the walk. ``values`` must already be descending."""
    series = pd.to_numeric(pd.Series(list(values), dtype="float64"), errors="coerce").fillna(0.0).clip(lower=0.0)
    count = len(series)
    if count == 0:
        return 0, 0.0, False
    total = float(series.sum())
    if total <= 0:
        shown = min(count, max_bars)
        return shown, 0.0, False
    running = series.cumsum() / total * 100.0
    # Small tolerance so an exact 80% is not missed to float drift.
    reaching = running.index[running >= target_pct - 1e-9]
    needed = int(reaching[0]) + 1 if len(reaching) else count
    shown = min(needed, max_bars)
    capped = needed > max_bars
    reached = 100.0 if shown >= count else float(running.iloc[shown - 1])
    return shown, reached, capped


def split_pareto(
    frame: pd.DataFrame,
    value_column: str,
    label_column: str,
    *,
    target_pct: float = DEFAULT_TARGET_PCT,
    max_bars: int = DEFAULT_MAX_BARS,
    keep: Iterable = (),
) -> ParetoSplit:
    """Apply the cutoff to ``frame`` (one row per unit, any order).

    Rows are ranked by ``value_column`` descending, ties broken by ``label_column`` so
    the order is stable between renders. Labels in ``keep`` (a current selection) are
    always drawn on their own bar, even past the cutoff, so a selected unit is never
    hidden inside the aggregate.
    """
    ranked = frame.copy()
    ranked[value_column] = pd.to_numeric(ranked[value_column], errors="coerce").fillna(0.0)
    ranked = ranked.sort_values([value_column, label_column], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    max_bars = max(1, int(max_bars))
    rule_units, reached, capped = rule_unit_count(ranked[value_column], target_pct, max_bars)
    in_shown = ranked.index < rule_units
    keep = list(keep)
    if keep:
        in_shown = in_shown | ranked[label_column].isin(keep).to_numpy()
    shown = ranked[in_shown].reset_index(drop=True)
    rest = ranked[~in_shown].reset_index(drop=True)
    return ParetoSplit(
        shown=shown,
        rest=rest,
        total_units=len(ranked),
        rule_units=rule_units,
        reached_pct=reached,
        target_pct=float(target_pct),
        capped=capped,
    )


def with_others(split: ParetoSplit, value_column: str, label_column: str, others_label: str) -> pd.DataFrame:
    """``split.shown`` plus one aggregate row (labelled ``others_label``) holding the
    folded total, with ``units`` counting the units each bar stands for."""
    shown = split.shown.assign(units=1)
    if not split.has_others:
        return shown
    others = {label_column: others_label, value_column: split.rest[value_column].sum(), "units": split.others_count}
    return pd.concat([shown, pd.DataFrame([others])], ignore_index=True)


def format_pct(value: float) -> str:
    """A share as a whole-number percentage, rounded *down*: a figure that falls short of
    a threshold must never be rounded up onto it (79.6% reads "79%", not "80%")."""
    return f"{math.floor(float(value) + 1e-9):d}%"


def stated_share(split: ParetoSplit) -> str:
    """The share the chart claims for its individual bars, as text ("80%"). Normally the
    target; when every unit was needed, 100%; and when the cap ended the walk first, the
    share actually reached, never the target. The sentence and the marker both read this."""
    if split.capped:
        return format_pct(split.reached_pct)
    if split.rule_units >= split.total_units:
        return "100%"
    return f"{split.target_pct:g}%"


@dataclass(frozen=True)
class CutoffMarker:
    """The point of the cumulative line where the individual bars end.

    ``index`` is the position of the last individually drawn bar and ``pct`` the share
    actually reached there, which is where the point is plotted. ``label`` is what the
    chart states about it (:func:`stated_share`)."""

    index: int
    pct: float
    label: str


def cutoff_marker(split: ParetoSplit) -> CutoffMarker | None:
    """Where to emphasise the cumulative line, or None when there is nothing to rank."""
    if split.rule_units <= 0 or split.reached_pct <= 0:
        return None
    return CutoffMarker(index=split.rule_units - 1, pct=split.reached_pct, label=stated_share(split))


def summary_text(split: ParetoSplit, noun: str) -> str:
    """One sentence stating the finding in words. ``noun`` is the translated thing counted
    ("acciones", "horas"...). When the cap, not the target, ended the walk the share
    actually reached is reported, never the target."""
    if split.total_units == 0:
        return ""
    key = "pareto.summary_capped" if split.capped else "pareto.summary_target"
    return t(key, shown=split.rule_units, total=split.total_units, pct=stated_share(split)[:-1], noun=noun)
