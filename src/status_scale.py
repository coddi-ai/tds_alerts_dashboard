"""
The dashboard's one status scale: Normal / Alerta / Anormal, plus Sin Datos for "no reading".

Every place that needs to know what a status is - its canonical name, how critical it is, which
colors it takes - asks here, so the same word is never given two meanings or two colors:

    from src.status_scale import get_status
    status = get_status("anormal")      # also "Anormal", "ANORMAL ", "Crítico", "Atención"...
    status.name, status.rank, status.key, status.css, status.solid, status.bg, status.text, status.border

`get_status` accepts any spelling of a status and never fails: anything it does not recognise
(None, NaN, "InsufficientData", "Sin Fuente", ...) is Sin Datos. There is no separate "Crítico" /
"Atención" tier: they are aliases of Anormal / Alerta (as dashboard/components/status_chip.py has
always shown them).

Colors are the tokens of dashboard/assets/status_chip.css (`--st-*`); a test keeps the two in step.
`solid` is the strong tier color (dots, solid chips, chart marks that must match a chip), `bg` /
`text` / `border` are the tinted chip (text on bg is >= 4.5:1).

No Dash import here: data modules (src/data/report_health.py) use it too.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class Status:
    key: str      # lowercase identifier used in records, CSS-free ("anormal", "sin_datos")
    name: str     # canonical display name, also the i18n lookup text ("Anormal", "Sin Datos")
    css: str      # suffix of the status_chip.css classes ("anormal", "nodata")
    rank: int     # 0 = Sin Datos ... 3 = Anormal; higher is more critical
    solid: str
    bg: str
    text: str
    border: str


SIN_DATOS = Status("sin_datos", "Sin Datos", "nodata", 0, "#4b5563", "#f3f4f6", "#374151", "#9ca3af")
NORMAL = Status("normal", "Normal", "normal", 1, "#15803d", "#dcfce7", "#166534", "#86efac")
ALERTA = Status("alerta", "Alerta", "alerta", 2, "#c2410c", "#ffedd5", "#9a3412", "#fdba74")
ANORMAL = Status("anormal", "Anormal", "anormal", 3, "#b91c1c", "#fee2e2", "#991b1b", "#fca5a5")

# Least to most critical.
SCALE: Tuple[Status, ...] = (SIN_DATOS, NORMAL, ALERTA, ANORMAL)

BY_KEY: Dict[str, Status] = {status.key: status for status in SCALE}

# Other spellings of a status, already normalized (see `_normalize`).
_ALIASES: Dict[str, Status] = {
    "normal": NORMAL,
    "alerta": ALERTA, "atencion": ALERTA,
    "anormal": ANORMAL, "critico": ANORMAL,
    "sin_datos": SIN_DATOS,
}


def _normalize(value) -> str:
    """`Crítico ` -> `critico`, `Sin Datos` -> `sin_datos`; non-strings (None, NaN) -> ""."""
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", "_", text.strip().casefold())


def get_status(value) -> Status:
    """The Status for any spelling of a status; Sin Datos when it is not one."""
    return _ALIASES.get(_normalize(value), SIN_DATOS)


def worst(*values) -> Status:
    """The most critical of the given statuses; Sin Datos when none is a status."""
    return max((get_status(v) for v in values), key=lambda s: s.rank, default=SIN_DATOS)
