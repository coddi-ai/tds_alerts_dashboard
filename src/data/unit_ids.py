"""One spelling per unit across every technique.

The same machine is written differently by different sources: EMIN's alert feed says ``CT-184``,
its oil report says ``CT_184``, and Predictivo zero-pads (``T_09``) where the others do not (``T_9``).
Read as plain text they are different units, so a unit shows up once per spelling.

Two functions, two jobs:

* :func:`normalize_unit_id` is the unit's **name** (what the General tab shows, links to and stores):
  separators become a hyphen, ``CT_184`` -> ``CT-184``. Nothing else about the text changes (case,
  inner spaces and zero padding are kept as they come).
* :func:`unit_key` is the unit's **identity** (what two spellings are compared by): the name, with the
  zero padding of the number dropped (``T_09`` and ``T_9`` are one unit).

:func:`unit_matches` applies the identity to a column, so a view can find a unit's rows in a source
that still spells it its own way.

No Dash import here: data modules use it too.
"""

from __future__ import annotations

import re

import pandas as pd

_SEPARATORS = re.compile(r"[-_]+")
# `T-09`, `BULL-027`: letters, a hyphen, a zero-padded number. Anything else has no padding to drop.
_PADDED_NUMBER = re.compile(r"^([A-Za-z]+-)0*(\d+)$")


def normalize_unit_id(unit) -> str:
    """The unit's name, hyphenated: ``CT_184`` -> ``CT-184``; ``CT-184`` is already there."""
    return _SEPARATORS.sub("-", str(unit))


def unit_key(unit) -> str:
    """What two spellings of a unit are compared by: ``T_09``, ``T-9`` and ``T_9`` all give ``T-9``."""
    name = normalize_unit_id(unit)
    match = _PADDED_NUMBER.match(name)
    return f"{match.group(1)}{match.group(2)}" if match else name


def unit_matches(column: pd.Series, unit) -> pd.Series:
    """Boolean mask of the rows of `column` that spell `unit` in any way (see :func:`unit_key`).

    Spellings are resolved once per distinct value, so a long alert column costs one pass."""
    text = column.astype(str)
    target = unit_key(unit)
    spellings = [value for value in text.unique() if unit_key(value) == target]
    return text.isin(spellings)
