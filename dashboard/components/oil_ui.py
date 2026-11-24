"""Building blocks of the Monitor de Aceite tabs, following ui_notes_improved.md.

Every color derived from a value comes from `shared/severity.py` (one classifier, no per-card
palettes); color is never the only signal (each colored element carries its word); and clickable
things are real buttons. Labels arrive already translated: callers own the wording.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple

import dash_bootstrap_components as dbc
from dash import html

from dashboard.components.labels import status_label
from shared.severity import (
    SEVERITY_TIER_BY_ESTADO,
    SEVERITY_TIERS,
    STATUS_TIER_BY_ESTADO,
    STATUS_TIERS,
)
from src.status_scale import get_status

# The neutral tone of a KPI that has no severity threshold (and of "no data").
NEUTRAL = {"bg": "#f1f5f9", "text": "#475569", "border": "#e2e8f0", "fill": "#64748b"}


def canonical_estado(value) -> Optional[str]:
    """Normal / Alerta / Anormal for any spelling of a machine or report status; None when it is
    not one of them (no reading, Sin Datos...)."""
    name = get_status(value).name
    return name if name in STATUS_TIER_BY_ESTADO else None


def estado_surface(estado) -> dict:
    """Inline style of a surface (banner, cell) for a status: the status tier's background, text and
    border. Normal is quiet white, Alerta the orange tier, Anormal the deep red one (§1.2)."""
    canonical = canonical_estado(estado)
    if canonical is None:
        return {"background": NEUTRAL["bg"], "color": NEUTRAL["text"], "border": f"1px solid {NEUTRAL['border']}"}
    tier = STATUS_TIERS[STATUS_TIER_BY_ESTADO[canonical]]
    return {"background": tier["bg"], "color": tier["text"], "border": f"1px solid {tier['border']}"}


def estado_badge(estado, label: Optional[str] = None) -> html.Span:
    """The status word with its shape (circle / triangle / diamond), colored from the same status tier
    as the surface it sits on, so a banner and its badge cannot drift apart."""
    canonical = canonical_estado(estado)
    if canonical is None:
        return html.Span(label or status_label(estado) or "—", className="kpi-chip oil-neutral-chip")
    tier = STATUS_TIERS[STATUS_TIER_BY_ESTADO[canonical]]
    border = tier["badge_text"] if canonical == "Normal" else "rgba(255,255,255,.7)"
    return html.Span(
        [
            html.Span(className="status-chip__shape", **{"aria-hidden": "true"}),
            html.Span(label if label is not None else status_label(canonical), className="status-chip__text"),
        ],
        className=f"status-chip status-chip--{get_status(canonical).css}",
        style={"background": tier["badge_bg"], "color": tier["badge_text"], "borderColor": border, "fontWeight": 700},
        **{"data-status": canonical},
    )


def severity_style(tier_key: Optional[str]) -> dict:
    """Inline style (tinted background, text, border) of a severity tier; neutral for None."""
    tone = SEVERITY_TIERS[tier_key] if tier_key else NEUTRAL
    return {"background": tone["bg"], "color": tone["text"], "borderColor": tone["border"]}


def severity_chip(tier_key: Optional[str], label: str, **attrs) -> html.Span:
    """Small pill with the tier's tint and a word. `tier_key=None` is the neutral pill."""
    tone = SEVERITY_TIERS[tier_key] if tier_key else NEUTRAL
    return html.Span(
        label,
        className="kpi-chip",
        style={"background": tone["bg"], "color": tone["text"]},
        **attrs,
    )


def estado_severity_tier(estado) -> Optional[str]:
    """The severity tier of the tinted component cells: Normal -> bajo, Alerta -> atencion, Anormal -> alto."""
    canonical = canonical_estado(estado)
    return SEVERITY_TIER_BY_ESTADO.get(canonical) if canonical else None


def gauge(pct: float, tier_key: Optional[str], label: str) -> html.Div:
    """Thin gauge showing `pct` (0-100, capped). `label` names it for assistive technology."""
    shown = max(0.0, min(100.0, float(pct)))
    tone = SEVERITY_TIERS[tier_key] if tier_key else NEUTRAL
    return html.Div(
        html.Div(className="kpi-gauge-fill", style={"width": f"{shown:.1f}%", "background": tone["fill"]}),
        className="kpi-gauge-track",
        role="progressbar",
        **{"aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": f"{shown:.0f}", "aria-label": label},
    )


def kpi_tile(
    label: str,
    value,
    *,
    icon: Optional[str] = None,
    tier: Optional[str] = None,
    chip: Optional[str] = None,
    gauge_pct: Optional[float] = None,
    caption=None,
    label_id: Optional[str] = None,
    value_id: Optional[str] = None,
) -> dbc.Card:
    """KPI tile (§3). The color lives in the icon badge, the chip and the gauge, never in a colored
    edge (§2). `tier=None` is the neutral tile; `h-100` keeps a row of tiles level."""
    tone = SEVERITY_TIERS[tier] if tier else NEUTRAL
    badge = (
        html.Span(
            html.I(className=f"fas {icon}", **{"aria-hidden": "true"}),
            className="oil-icon-badge",
            style={"background": tone["bg"], "color": tone["text"]},
        )
        if icon else None
    )
    head = html.Div(
        [badge, html.Div(label, className="kpi-label", **({"id": label_id} if label_id else {}))],
        className="oil-kpi-title",
    )
    # The chip sits on the value's row: a long chip ("Solicitar muestra") never squeezes the label.
    value_row = html.Div(
        [html.Div(value, className="kpi-value", **({"id": value_id} if value_id else {})),
         severity_chip(tier, chip) if chip else None],
        className="oil-kpi-valuerow",
    )
    body = [head, value_row]
    if gauge_pct is not None:
        body.append(gauge(gauge_pct, tier, label))
    if caption is not None:
        body.append(html.Div(caption, className="kpi-caption"))
    return dbc.Card(dbc.CardBody(body), className="shadow-sm h-100")


def status_banner(
    estado,
    *,
    title,
    eyebrow: Optional[str] = None,
    subtitle=None,
    icon: str = "fa-oil-can",
    fields: Sequence[Tuple[str, object]] = (),
    badge_label: Optional[str] = None,
    **attrs,
) -> html.Div:
    """Banner / hero header whose background, text and badge all come from one status value (§4)."""
    surface = estado_surface(estado)
    identity = html.Div(
        [
            html.Span(html.I(className=f"fas {icon}", **{"aria-hidden": "true"}), className="oil-banner__icon"),
            html.Div(
                [
                    html.Div(eyebrow, className="oil-banner__eyebrow") if eyebrow else None,
                    html.Div(title, className="oil-banner__title"),
                    html.Div(subtitle, className="oil-banner__subtitle") if subtitle else None,
                ]
            ),
        ],
        className="oil-banner__identity",
    )
    shown_fields = [
        html.Div([html.Span(name, className="oil-banner__field-label"),
                  html.Span(value, className="oil-banner__field-value")])
        for name, value in fields
    ]
    right = html.Div([*shown_fields, estado_badge(estado, badge_label)], className="oil-banner__fields")
    return html.Div([identity, right], className="oil-banner", style=surface, **attrs)


def page_header(title: str, subtitle: Optional[str] = None, caption=None, *, tag: str = "h3") -> html.Div:
    """Page title, its subtitle and, below, a metadata caption (record counts, data freshness...):
    metadata is a caption, never a tile competing for attention (§5)."""
    heading = html.H3(title, className="mt-4 mb-1") if tag == "h3" else html.H4(title, className="mt-4 mb-1")
    return html.Div(
        [
            heading,
            html.P(subtitle, className="text-muted mb-0") if subtitle else None,
            html.P(caption, className="oil-caption") if caption is not None else None,
        ],
        className="mb-3",
    )


def filter_field(label: str, control, control_id: str, *, md: int = 4, lg: Optional[int] = None) -> dbc.Col:
    """A filter: its real <label for> and the control it names."""
    return dbc.Col([html.Label(label, htmlFor=control_id, className="oil-filter-label"), control], md=md, lg=lg)


def action_checklist(items: Iterable[str], list_id: str, empty_text: str) -> html.Div:
    """The "Acciones" of an AI recommendation as a checklist (§6); `empty_text` when there are none."""
    items = [item for item in items if item]
    if not items:
        return html.P(empty_text, className="mb-0 text-muted")
    return html.Div(
        dbc.Checklist(
            id=list_id,
            options=[{"label": item, "value": index} for index, item in enumerate(items)],
            value=[],
        ),
        className="oil-actions",
    )
