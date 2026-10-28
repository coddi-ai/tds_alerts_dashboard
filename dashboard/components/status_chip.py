"""Status chip: the one way the General tab draws Normal / Alerta / Anormal / Sin Datos.

Color is never the only signal (ui_notes_improved.md §1.3): every chip carries the status
word and a shape that differs per status (circle = Normal, triangle = Alerta, diamond =
Anormal, dash = Sin Datos). Alerta uses the orange tier and Anormal the deep-red
tier of §1.2; there is no separate "Crítico", it is shown as Anormal.

`solid=True` is the stronger variant for a unit's Estado; the default tinted chip is for
per-technique and per-component statuses. Colors live in `assets/status_chip.css`; the
solid hex values in `STATUS_SOLID_COLORS` mirror it for charts that must match a chip.
"""

from __future__ import annotations

from typing import Optional

from dash import html

from dashboard.components.labels import status_label

# Raw statuses (several vocabularies) -> the four shown in the General tab.
_CANONICAL = {
    "normal": "Normal",
    "alerta": "Alerta", "atención": "Alerta",
    "anormal": "Anormal", "crítico": "Anormal", "critico": "Anormal",
}
_CSS_KEY = {"Normal": "normal", "Alerta": "alerta", "Anormal": "anormal", "Sin Datos": "nodata"}

# Solid tier colors, same values as the CSS tokens (guide §1.2: Alerta = orange tier,
# Anormal = deep red).
STATUS_SOLID_COLORS = {
    "Normal": "#15803d",
    "Alerta": "#c2410c",
    "Anormal": "#b91c1c",
    "Sin Datos": "#4b5563",
}


def canonical_status(status) -> str:
    """The status as one of Normal / Alerta / Anormal / Sin Datos. Anything without a
    reading or not recognised (InsufficientData, Sin Fuente, None...) is Sin Datos."""
    return _CANONICAL.get(str(status or "").strip().casefold(), "Sin Datos")


def status_chip(status, *, solid: bool = False, on_dark: bool = False, label: Optional[str] = None, **attrs) -> html.Span:
    """Chip for `status`: shape + text, tinted, `solid`, or `on_dark` (translucent white, for a
    tier-colored surface). `label` replaces the status word (e.g. a localized one); `attrs` are
    extra HTML attributes of the span."""
    canonical = canonical_status(status)
    css = _CSS_KEY[canonical]
    classes = f"status-chip status-chip--{css}" + (" status-chip--solid" if solid else "") + (" status-chip--on-dark" if on_dark else "")
    return html.Span(
        [
            html.Span(className="status-chip__shape", **{"aria-hidden": "true"}),
            html.Span(label if label is not None else status_label(status), className="status-chip__text"),
        ],
        className=classes,
        **{"data-status": canonical, **attrs},
    )
