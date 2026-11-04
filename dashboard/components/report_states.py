"""Etiquetas, colores y chip del estado combinado de Reportabilidad.

No define colores propios: lee la escala unica del dashboard (src/status_scale.py), la misma de
`status_chip` y `status_chip.css`, y las etiquetas de `labels.status_label`. Cada elemento recibe su
paleta como variables CSS en linea (`--rp-bg`, `--rp-text`, `--rp-dot`, `--rp-edge`) y
`assets/reporting.css` solo pone la forma.

El color nunca es la unica senal: todo estado lleva su etiqueta de texto junto al punto o el tinte.
"""

from __future__ import annotations

from typing import Dict, Optional

from dash import html

from dashboard.components.labels import status_label
from src.data.report_health import NO_DATA, STATE_ORDER, STATES_BY_SEVERITY, STATE_RANK, normalize_state
from src.status_scale import SCALE, get_status

STATE_STYLES: Dict[str, Dict[str, str]] = {
    status.key: {"bg": status.bg, "text": status.text, "dot": status.solid, "border": status.border}
    for status in SCALE
}

# Estados que piden atencion (seccion "Requieren atencion") y los que no.
ATTENTION_STATES = ("anormal", "alerta")
CLEAR_STATES = ("normal", NO_DATA)


def state_key(value: Optional[str]) -> str:
    """Clave de la escala para cualquier valor; `sin_datos` si no es un estado."""
    return normalize_state(value) or NO_DATA


def state_rank(value: Optional[str]) -> int:
    return STATE_RANK[state_key(value)]


def state_label(value: Optional[str]) -> str:
    """Etiqueta del estado, la misma que usa el resto del dashboard (`Anormal`, `Sin Datos`...)."""
    return status_label(get_status(value).name)


def state_vars(value: Optional[str]) -> Dict[str, str]:
    """Variables CSS en linea con la paleta del estado."""
    style = STATE_STYLES[state_key(value)]
    return {"--rp-bg": style["bg"], "--rp-text": style["text"], "--rp-dot": style["dot"],
            "--rp-edge": style["border"]}


def state_dot(value: Optional[str]) -> html.Span:
    return html.Span(className="rp-dot", style=state_vars(value), **{"aria-hidden": "true"})


def state_chip(value: Optional[str], title: Optional[str] = None, className: str = "") -> html.Span:
    """Chip tintado con punto y etiqueta (`Anormal`, `Alerta`, ...)."""
    key = state_key(value)
    return html.Span(
        [html.Span(className="rp-dot", **{"aria-hidden": "true"}), state_label(key)],
        className=f"rp-chip rp-chip--{key} {className}".strip(),
        style=state_vars(key),
        title=title,
    )


__all__ = [
    "ATTENTION_STATES", "CLEAR_STATES", "NO_DATA", "STATE_ORDER", "STATE_STYLES", "STATES_BY_SEVERITY",
    "state_chip", "state_dot", "state_key", "state_label", "state_rank", "state_vars",
]
