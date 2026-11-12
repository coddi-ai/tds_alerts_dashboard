"""
Pure aggregation rules of the alert summary email (02 + 02.1 change request).

No pandas, no I/O, no HTML: functions over plain `AlertRecord`s, so every rule (individual
top and compressed tail, cumulative percentages, the 80% sentence, the featured alerts) is
testable on its own. The records come from the same prepared frame the Alertas page uses,
so the totals match.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Sequence, Tuple

MAX_UNIT_ROWS = 15
MAX_FEATURED = 5
MAX_NAMED_UNITS = 5
DIAGNOSIS_MAX_CHARS = 120
CONCENTRATION_PCT = 80
MISSING = "—"


@dataclass(frozen=True)
class AlertRecord:
    unit: str
    when: datetime            # alert instant, tz-aware America/Santiago
    system: str               # display label ("" when unknown)
    component: str
    source: str               # display label: Telemetría / Tribología / Multitécnica
    is_multi: bool            # Multitécnica
    diagnosis: str


@dataclass(frozen=True)
class UnitRow:
    label: str
    count: int                # alerts per unit (what the bar is drawn from)
    shown: str                # "18" or "3 c/u"
    bar_pct: int              # 0-100
    cumulative_pct: int
    units: int                # how many units the row stands for
    is_other: bool = False


@dataclass(frozen=True)
class SystemRow:
    name: str
    count: int
    bar_pct: int
    pct: int


# --------------------------------------------------------------------------- helpers


def natural_key(value: str) -> list:
    """`CA-9` before `CA-81`."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(value))]


def round_half_up_pct(part: int, whole: int) -> int:
    """`100 * part / whole` rounded half-up to an integer (integer maths: no float surprises)."""
    if whole <= 0:
        return 0
    return (200 * part + whole) // (2 * whole)


def pluralize(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _bar_pct(value: int, highest: int) -> int:
    if highest <= 0 or value <= 0:
        return 0
    return max(1, min(100, round_half_up_pct(value, highest)))  # a visible sliver at least


# --------------------------------------------------------------------------- ranking


def unit_counts(records: Sequence[AlertRecord]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for record in records:
        counts[record.unit] += 1
    return dict(counts)


def ranked_units(records: Sequence[AlertRecord]) -> List[Tuple[str, int]]:
    """Units by alert count (desc); equal counts in natural unit ID order."""
    counts = unit_counts(records)
    order = sorted(counts, key=lambda unit: (-counts[unit], natural_key(unit)))
    return [(unit, counts[unit]) for unit in order]


def units_for_concentration(ranked: Sequence[Tuple[str, int]]) -> int:
    """X: the smallest number of top units whose alerts reach at least 80% of the total."""
    total = sum(count for _, count in ranked)
    accumulated = 0
    for position, (_, count) in enumerate(ranked, start=1):
        accumulated += count
        if accumulated * 100 >= CONCENTRATION_PCT * total:
            return position
    return len(ranked)


def top_units(ranked: Sequence[Tuple[str, int]]) -> List[str]:
    """The units in the top 3 positions, plus every unit tied with the 3rd (never dropped)."""
    if not ranked:
        return []
    cutoff = ranked[min(3, len(ranked)) - 1][1]
    return [unit for unit, count in ranked if count >= cutoff]


def individual_threshold(ranked: Sequence[Tuple[str, int]]) -> int:
    """Alert count from which a unit gets its own row.

    The count of the X-th unit, so a group of ties at the 80% boundary is never split. It is
    lowered, if needed, to the count of the 3rd unit so every unit the summary sentence names
    also appears as its own row.
    """
    needed = units_for_concentration(ranked)
    return min(ranked[needed - 1][1], ranked[min(3, len(ranked)) - 1][1])


# --------------------------------------------------------------------------- unit rows


@dataclass(frozen=True)
class _Entry:
    units: Tuple[str, ...]
    count: int  # alerts per unit

    @property
    def alerts(self) -> int:
        return self.count * len(self.units)


def _entries(ranked: Sequence[Tuple[str, int]]) -> List[_Entry]:
    """Individual top first (one entry per unit), then the tail grouped by identical count."""
    threshold = individual_threshold(ranked)
    entries = [_Entry((unit,), count) for unit, count in ranked if count >= threshold]
    tail: Dict[int, List[str]] = defaultdict(list)
    for unit, count in ranked:
        if count < threshold:
            tail[count].append(unit)
    for count in sorted(tail, reverse=True):
        entries.append(_Entry(tuple(sorted(tail[count], key=natural_key)), count))
    return entries


def _label_and_shown(entry: _Entry) -> Tuple[str, str]:
    if len(entry.units) == 1:
        return entry.units[0], str(entry.count)
    label = ", ".join(entry.units) if len(entry.units) <= 3 else f"{len(entry.units)} unidades"
    return label, f"{entry.count} c/u"


def unit_rows(records: Sequence[AlertRecord]) -> List[UnitRow]:
    """Alertas por Unidad: the units that concentrate 80% of the alerts one per row, the
    low-activity tail grouped by equal count, at most 15 rows plus `Otras (N)`."""
    ranked = ranked_units(records)
    total = sum(count for _, count in ranked)
    if not total:
        return []
    highest = ranked[0][1]
    entries = _entries(ranked)

    visible, merged = entries[:MAX_UNIT_ROWS], entries[MAX_UNIT_ROWS:]
    # A group of tied units is never split between visible rows and `Otras`.
    while merged and visible and visible[-1].count == merged[0].count:
        merged.insert(0, visible.pop())

    rows: List[UnitRow] = []
    accumulated = 0
    for entry in visible:
        accumulated += entry.alerts
        label, shown = _label_and_shown(entry)
        rows.append(UnitRow(label, entry.count, shown, _bar_pct(entry.count, highest),
                            round_half_up_pct(accumulated, total), len(entry.units)))
    if merged:
        merged_units = sum(len(entry.units) for entry in merged)
        merged_alerts = sum(entry.alerts for entry in merged)
        rows.append(UnitRow(f"Otras ({merged_units})", merged_alerts, str(merged_alerts),
                            _bar_pct(merged_alerts, highest), 100, merged_units, is_other=True))
    # The last row is always 100% (rounding can never leave it short).
    last = rows[-1]
    rows[-1] = UnitRow(last.label, last.count, last.shown, last.bar_pct, 100, last.units, last.is_other)
    return rows


def has_compressed_rows(rows: Sequence[UnitRow]) -> bool:
    return any(row.units > 1 and not row.is_other for row in rows)


# --------------------------------------------------------------------------- systems


def system_rows(records: Sequence[AlertRecord]) -> List[SystemRow]:
    """Alertas por Sistema: count desc (ties alphabetical); percentages add up to 100."""
    counts: Dict[str, int] = defaultdict(int)
    for record in records:
        counts[record.system or MISSING] += 1
    total = sum(counts.values())
    if not total:
        return []
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    highest = ordered[0][1]
    pcts = [round_half_up_pct(count, total) for _, count in ordered]
    pcts[0] += 100 - sum(pcts)  # rounding drift goes to the largest row
    return [SystemRow(name, count, _bar_pct(count, highest), pct)
            for (name, count), pct in zip(ordered, pcts)]


# --------------------------------------------------------------------------- headline


def join_es(items: Sequence[str]) -> str:
    """`A`, `A y B`, `A, B y C`."""
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def headline(total: int, units: int) -> str:
    return f"{pluralize(total, 'alerta', 'alertas')} en {pluralize(units, 'unidad', 'unidades')}"


def named_units(records: Sequence[AlertRecord]) -> str:
    """`CA-81, CA-92 y CA-93`; every unit tied at the top is named (max 5, then `y N más`)."""
    qualifying = top_units(ranked_units(records))
    if len(qualifying) <= MAX_NAMED_UNITS:
        return join_es(qualifying)
    return f"{', '.join(qualifying[:MAX_NAMED_UNITS])} y {len(qualifying) - MAX_NAMED_UNITS} más"


def summary_sentence(records: Sequence[AlertRecord]) -> str:
    """`X de M unidades concentran el 80% ... Analice las unidades ...: U1, U2 y U3.`"""
    ranked = ranked_units(records)
    units = len(ranked)
    if units == 1:
        return f"Analice la unidad {ranked[0][0]}."
    needed = units_for_concentration(ranked)
    verb = "concentra" if needed == 1 else "concentran"
    return (
        f"{needed} de {units} unidades {verb} el {CONCENTRATION_PCT}% de las alertas. "
        f"Analice las unidades con más alertas: {named_units(records)}."
    )


# --------------------------------------------------------------------------- featured


def truncate_diagnosis(text: str, limit: int = DIAGNOSIS_MAX_CHARS) -> str:
    """Plain text, cut at a word boundary with `…` so it fits about two lines."""
    text = re.sub(r"\*+", "", text or "")  # the model sometimes answers in markdown
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return MISSING
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut and text[limit - 1] != " ":
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:.") + "…"


def featured_alerts(records: Sequence[AlertRecord]) -> List[AlertRecord]:
    """Up to 5: Multitécnica first, then busier units, then most recent."""
    counts = unit_counts(records)
    ordered = sorted(
        records,
        key=lambda r: (not r.is_multi, -counts[r.unit], -r.when.timestamp(), natural_key(r.unit)),
    )
    return ordered[:MAX_FEATURED]
