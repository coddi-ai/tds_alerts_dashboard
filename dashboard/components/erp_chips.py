"""Chips and colors of Conexión ERP (Validación de Avisos / Seguimiento de Avisos).

The one place these colors are defined: the pending list, the detail panel, the KPI icon
badges, the bar charts and the Registro de Avisos table all read them from here, so a
severity or an Estado never gets a color chosen per component (ui_notes_improved.md §1.1).

Three vocabularies, three palettes that never borrow from each other:

* Severidad (Medio / Alto / Crítico): the amber -> orange -> red escalation of §1.2, as a tinted
  chip with a dot. Severity is categorical here, so `classify_severity` (0-100) is not used.
* Clasificación (Anormal / Alerta): neutral slate only - solid dark vs outlined - so it cannot
  be mistaken for a severity.
* Estado (Pendiente / Enviado / Rechazado): blue / green / gray, never the severity palette.

Color is never the only signal (§1.3): every chip carries its text label, and a severity chip
a dot as well. Chip colors are inline styles from the dicts below; `assets/erp_avisos.css`
holds only the shape.
"""
from __future__ import annotations

from enum import Enum

from dash import html

from src.data.erp_schemas import (
    CONDITION_LABEL_LABELS,
    SEVERITY_LABELS,
    STATUS_LABELS,
    ConditionLabel,
    Severity,
    WarningStatus,
)
from src.i18n import t

# Severidad: chip background / text / dot. `low` is not part of the Medio-Alto-Crítico scale
# but the pipeline schema still allows it, so it gets a neutral chip rather than a severity color.
SEVERITY_STYLES = {
    "critical": {"bg": "#fee2e2", "text": "#991b1b", "dot": "#dc2626"},
    "high": {"bg": "#ffedd5", "text": "#9a3412", "dot": "#ea580c"},
    "medium": {"bg": "#fef3c7", "text": "#78350f", "dot": "#d97706"},
    "low": {"bg": "#f1f5f9", "text": "#334155", "dot": "#64748b"},
}
# Worst first: the order severity bars and selects list them in.
SEVERITY_ORDER = ("critical", "high", "medium", "low")

# Clasificación: Anormal is the solid dark chip, Alerta the outlined one. `fill`/`border` are
# what a bar segment of that classification uses.
CLASSIFICATION_STYLES = {
    "anormal": {"bg": "#1e293b", "text": "#ffffff", "border": "#1e293b", "fill": "#1e293b"},
    "alerta": {"bg": "#ffffff", "text": "#334155", "border": "#94a3b8", "fill": "#ffffff"},
}
# Outline of an Alerta bar segment (the fill alone would vanish into the track).
CLASSIFICATION_SEGMENT_OUTLINE = "#64748b"

# Estado: chip background / text, plus a darker `fill` for the lifecycle bar (white-on-fill
# stays above 4.5:1). "validated" (approved, not yet confirmed by the ERP) reads as Enviado,
# the same grouping the "Validados y Enviados" KPI uses.
ESTADO_STYLES = {
    "pending": {"bg": "#dbeafe", "text": "#1e40af", "fill": "#2563eb"},
    "sent": {"bg": "#dcfce7", "text": "#166534", "fill": "#15803d"},
    "rejected": {"bg": "#e5e7eb", "text": "#374151", "fill": "#6b7280"},
}
ESTADO_STYLES["validated"] = ESTADO_STYLES["sent"]

# KPI icon badges: the Estado tiles reuse the Estado palette; Total and Tiempo are neutral.
KPI_ICON_STYLES = {
    "total": {"bg": "#e0e7ff", "text": "#3730a3"},
    "pending": ESTADO_STYLES["pending"],
    "sent": ESTADO_STYLES["sent"],
    "rejected": ESTADO_STYLES["rejected"],
    "avg_hours": {"bg": "#f1f5f9", "text": "#334155"},
}


def _key(value) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _label(labels, enum_cls, value) -> str:
    """Declared label of an enum value; title-case for anything the schema doesn't know."""
    try:
        return labels[enum_cls(_key(value))]
    except (ValueError, KeyError):
        return _key(value).title()


def severity_label(value) -> str:
    return _label(SEVERITY_LABELS, Severity, value)


def classification_label(value) -> str:
    return _label(CONDITION_LABEL_LABELS, ConditionLabel, value)


def estado_label(value) -> str:
    return _label(STATUS_LABELS, WarningStatus, value)


def severity_chip(value, **attrs) -> html.Span:
    """Dot + word, tinted. Unknown values fall back to the neutral tier."""
    style = SEVERITY_STYLES.get(_key(value), SEVERITY_STYLES["low"])
    return html.Span(
        [
            html.Span(className="erp-chip__dot", style={"background": style["dot"]}, **{"aria-hidden": "true"}),
            html.Span(severity_label(value)),
        ],
        className="erp-chip erp-chip--severity",
        style={"background": style["bg"], "color": style["text"]},
        **attrs,
    )


def classification_chip(value, **attrs) -> html.Span:
    style = CLASSIFICATION_STYLES.get(_key(value), CLASSIFICATION_STYLES["alerta"])
    return html.Span(
        classification_label(value),
        className="erp-chip erp-chip--classification",
        style={"background": style["bg"], "color": style["text"], "borderColor": style["border"]},
        **attrs,
    )


def estado_chip(value, **attrs) -> html.Span:
    style = ESTADO_STYLES.get(_key(value), ESTADO_STYLES["rejected"])
    return html.Span(
        estado_label(value),
        className="erp-chip erp-chip--estado",
        style={"background": style["bg"], "color": style["text"]},
        **attrs,
    )


def kpi_icon_badge(kpi: str, icon: str) -> html.Span:
    style = KPI_ICON_STYLES[kpi]
    return html.Span(
        html.I(className=f"fas {icon}"),
        className="erp-icon-badge",
        style={"background": style["bg"], "color": style["text"]},
        **{"aria-hidden": "true"},
    )


def nav_badge_children(count: int) -> list:
    """Content of the pending-count badge on the Validación de Avisos sidebar link: the number
    for sighted users, the full phrase for screen readers."""
    return [
        html.Span(str(count), className="nav-link-badge__count", **{"aria-hidden": "true"}),
        html.Span(t("nav.erp_pending_badge_label", count=count), className="visually-hidden"),
    ]
