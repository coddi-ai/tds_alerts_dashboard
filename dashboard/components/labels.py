"""Client-facing label normalization for dashboard entities."""

from __future__ import annotations

import re
from typing import Any

from src.i18n import t, t_or


_COMPONENT_LABELS = {
    "engine": "Motor",
    "motor": "Motor",
    "post_engine": "Posterior al motor",
    "posterior_al_motor": "Posterior al motor",
    "rifle": "Conducto principal de aceite",
    "crankcase": "Cárter",
    "carter": "Cárter",
    "cárter": "Cárter",
    "lubrication": "Lubricación",
    "lubricacion": "Lubricación",
    "lubricación": "Lubricación",
}


# Alias -> canonical id, so one catalog entry serves every spelling of a component.
_COMPONENT_ALIASES = {
    "motor": "engine",
    "posterior_al_motor": "post_engine",
    "carter": "crankcase",
    "cárter": "crankcase",
    "lubricacion": "lubrication",
    "lubricación": "lubrication",
}


def _normalized_component_key(key: str) -> str:
    return _COMPONENT_ALIASES.get(key, key)


def translate_component_label(value: Any) -> str:
    """Return a stable Spanish label while preserving unknown values.

    Source contracts may use English, Spanish, title case, spaces, or hyphens.
    The normalization is display-only; raw component values remain unchanged
    in the loaded data and are still used for joins and filters.

    W34-01: this is the single label function for components across General
    and Alertas (General's dropdown used to build its own label with
    `.title()` on the raw, uppercased-for-dedup value instead of calling
    this). A component not yet in `_COMPONENT_LABELS` below falls back to a
    readable reformatting of whatever text it was given — title case, with
    underscores/hyphens turned into spaces — rather than echoing raw
    ``SCREAMING_SNAKE_CASE`` or a bare identifier: no translation is
    invented, only the same text reformatted.
    """
    label = str(value or "").strip()
    if not label:
        return t("labels.no_component")

    key = re.sub(r"[\s-]+", "_", label.casefold())
    # Critical-review follow-up: check key presence, not truthiness — a
    # `.get(key)` truthy-check can't tell "not catalogued" from "catalogued
    # with a falsy value" (mirrors the None/NaN-vs-zero distinction the rest
    # of this diff is careful about elsewhere, e.g. tab_predictive_overview's
    # _score_cell_style).
    if key in _COMPONENT_LABELS:
        # `_COMPONENT_LABELS` holds the Spanish source text; the catalog entry
        # (label.component.<normalized key>) carries the translation.
        return t_or(f"label.component.{_normalized_component_key(key)}", _COMPONENT_LABELS[key])
    return label.replace("_", " ").replace("-", " ").strip().title()


# Status vocabulary produced by the data pipeline (raw values are Spanish and are
# also what filters, sorting and styling key off). `status_label` is display-only:
# it translates the text a user reads without ever touching the raw value.
_STATUS_KEYS = {
    "normal": "normal",
    "alerta": "alert",
    "anormal": "abnormal",
    "sin datos": "no_data",
    "sin fuente": "no_source",
    "insufficientdata": "insufficient_data",
    "crítico": "critical",
    "critico": "critical",
    "condenatorio": "condemnatory",
    "marginal": "marginal",
    "precaución": "caution",
    "saludable": "healthy",
    "sano": "operational",
    "detenido": "stopped",
    "ok": "ok",
    "atención": "attention",
    "preocupante": "concerning",
    "inferior marginal": "lower_marginal",
    "superior marginal": "upper_marginal",
    "inferior condenatorio": "lower_condemnatory",
    "superior condenatorio": "upper_condemnatory",
}


def status_label(value: Any) -> str:
    """Display text for a raw status value; unknown values are returned unchanged."""
    raw = "" if value is None else str(value)
    key = _STATUS_KEYS.get(raw.strip().casefold())
    if key is None:
        return raw
    return t_or(f"status.{key}", raw)


def localize_elapsed(text: Any) -> str:
    """Translate an elapsed-time string produced by the freshness helpers ("3 días",
    "1 día", "5h", "12m", "N/A"). Those helpers emit Spanish text and their results are
    cached/shared, so the text is localized here, at display time."""
    raw = "" if text is None else str(text)
    return re.sub(
        r"(\d+) día(s?)\b",
        lambda m: t("labels.elapsed_days", count=m.group(1)) if m.group(2) else t("labels.elapsed_day", count=m.group(1)),
        raw,
    )


# W34-04 — single source of truth for a Trigger_type's (label, color), so the
# same pair is used in the alerts table's row-highlight, the color legend,
# the executive KPI card and the detail header, instead of four
# independently maintained spots (a hardcoded hex on the table's border
# rule, a *different* hardcoded hex on the KPI card, a plain-text label with
# no color anywhere else). Lives here (not in alerts_report.py, which is a
# more natural conceptual home) because alerts_report.py already imports
# from alerts_tables.py — putting it there would make alerts_tables.py
# import back from alerts_report.py, a circular import. labels.py has no
# dependency on either, matching how translate_component_label above is
# already shared the same way.
#
# "Multitécnica" is the confirmed client-facing label for Trigger_type ==
# "Mixto" (raw value unchanged — only alerts corroborated by more than one
# technical discipline, e.g. telemetry + tribology, ever carry it). Every
# consumer reads the label from here, so it only needed a one-line change.
SOURCE_STYLE: dict[str, tuple[str, str]] = {
    "Telemetria": ("Telemetría", "#2980b9"),
    "Telemetría": ("Telemetría", "#2980b9"),
    "Tribologia": ("Tribología", "#b8860b"),
    "Tribología": ("Tribología", "#b8860b"),
    "Mixto": ("Multitécnica", "#6f42c1"),
}
_DEFAULT_SOURCE_COLOR = "#95a5a6"
_SOURCE_CANONICAL = {
    "Telemetria": "telemetry",
    "Telemetría": "telemetry",
    "Tribologia": "tribology",
    "Tribología": "tribology",
    "Mixto": "multi",
}


def source_style(value: Any) -> tuple[str, str]:
    """(label, color) for a raw Trigger_type value.

    An unrecognized value keeps its own text (never invents a translation)
    with a neutral gray — the same "don't fabricate, don't crash" rule
    translate_component_label above follows.
    """
    raw = str(value).strip() if value is not None else ""
    if not raw:
        return t("labels.no_source"), _DEFAULT_SOURCE_COLOR
    if raw in SOURCE_STYLE:
        label, color = SOURCE_STYLE[raw]
        # SOURCE_STYLE holds the Spanish source text; the catalog carries the translation.
        return t_or(f"label.source.{_SOURCE_CANONICAL.get(raw, raw)}", label), color
    return raw, _DEFAULT_SOURCE_COLOR


def source_color(value: Any) -> str:
    return source_style(value)[1]


def light_tint(hex_color: str, amount: float = 0.9) -> str:
    """Blend a hex color toward white, for a soft card/badge background that
    visually pairs with its own accent color instead of an independently
    hand-picked tint that can drift from it (W34-04).

    Shared by the executive KPI card (tab_alerts_general.py) and the alert
    detail header's Fuente badge (alerts_callbacks.py) — both show the same
    SOURCE_STYLE accent as saturated text over this tint, rather than one of
    them using a solid fill with implied white text (a different, one-off
    treatment introduced only for that single consumer)."""
    raw = hex_color.lstrip("#")
    channels = (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    blended = (round(c + (255 - c) * amount) for c in channels)
    return "#{:02x}{:02x}{:02x}".format(*blended)


# Quality-review follow-up: three tables (Estado de Datos, Estado x Unidad,
# Predictivo) each independently hardcoded the same icon/background/text for
# a "no data available" badge or cell, kept in sync only by a comment
# cross-referencing the other two — exactly the divergence-by-copy this
# session already fixed for SOURCE_STYLE/SIGNAL_LABELS, just missed for this
# concept. One real source now: dashboard/callbacks/data_freshness_callbacks.py
# (FRESHNESS_STATUS_STYLE['Sin Datos']), dashboard/callbacks/
# overview_general_callbacks.py (STATUS_STYLE['Sin Datos']/['Sin Fuente']) and
# dashboard/tabs/tab_predictive_overview.py (_score_cell_style's null branch)
# all read these three names instead of retyping the same literals.
NO_DATA_ICON = "⚪"
NO_DATA_BG = "var(--surface-2)"
NO_DATA_TEXT = "var(--text-muted)"
