"""
Unit selection of the Long View (curva acumulada): one state shared by the
dropdown, the chips, the risk badges and the chart.

Pure functions over an immutable `Selection`, so every interaction path
(dropdown pick, chip click, badge click, re-click of the active badge) goes
through the same rules and the four views cannot disagree.
"""

from typing import Iterable, NamedTuple, Optional

DEFAULT_BADGE_ORDER = ("Anormal", "Alerta", "Normal")  # most severe first


class Selection(NamedTuple):
    """`selected`: visible units, in fleet order. `badge`: the risk badge that
    produced this selection, None once the user edits it by hand. `restore`: the
    selection from before ANY badge was clicked - what re-clicking the active
    badge returns to, however many badges were hopped through in between."""
    selected: tuple
    badge: Optional[str] = None
    restore: Optional[tuple] = None


def initial_selection(universe: Iterable[str]) -> Selection:
    return Selection(tuple(universe))


def _ordered(units: Optional[Iterable[str]], universe: Iterable[str]) -> tuple:
    """`units` restricted to the fleet and in fleet order (unknown units dropped)."""
    wanted = set(units or ())
    return tuple(u for u in universe if u in wanted)


def pick_from_dropdown(sel: Selection, values: Optional[Iterable[str]], universe) -> Selection:
    """The dropdown's value changed. Same set as now = an echo of our own update,
    ignored; anything else is a manual edit, which switches the badge off and
    forgets the pre-badge snapshot (the next badge click takes a fresh one)."""
    new = _ordered(values, universe)
    if set(new) == set(sel.selected):
        return sel
    return Selection(new)


def toggle_unit(sel: Selection, unit: str, universe) -> Selection:
    """A chip was clicked: toggle that unit. A manual edit, like the dropdown."""
    if unit not in set(universe):
        return sel
    return Selection(_ordered(set(sel.selected) ^ {unit}, universe))


def click_badge(sel: Selection, badge: str, groups: dict, universe) -> Selection:
    """A risk badge was clicked. `groups` is {badge: units} fleet-wide.

    - The active badge again: back to the selection from before any badge.
    - Another badge while one is active: that group, still remembering the
      selection from before the FIRST badge (not the previous badge's group).
    - No badge active: exactly that group, remembering the current selection.
    """
    if sel.badge == badge:
        back = _ordered(sel.restore, universe) if sel.restore is not None else tuple(universe)
        return Selection(back)
    restore = sel.restore if sel.badge is not None else sel.selected
    return Selection(_ordered(groups.get(badge, ()), universe), badge, tuple(restore))


def to_dict(sel: Selection) -> dict:
    return {"selected": list(sel.selected), "badge": sel.badge,
            "restore": None if sel.restore is None else list(sel.restore)}


def from_dict(data: Optional[dict], universe) -> Selection:
    """Store contents back into a Selection; a missing/invalid store starts from
    the whole fleet, and units no longer in the fleet are dropped."""
    if not isinstance(data, dict) or "selected" not in data:
        return initial_selection(universe)
    restore = data.get("restore")
    return Selection(
        _ordered(data.get("selected"), universe),
        data.get("badge"),
        None if restore is None else _ordered(restore, universe),
    )
