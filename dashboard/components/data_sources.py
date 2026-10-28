"""Shared "Fuentes de datos" indicator: one chip per data source.

Purely presentational. The component is handed a list of `DataSource` and draws it; it
does not know which page it is on, probe files or fetch anything. Which sources a tab has
is configuration (`config/service_data_sources.py`) and how a source's status is resolved
lives in `dashboard/components/source_status.py`, so adding or renaming a source never
touches this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from dash import html

from src.i18n import t

AVAILABLE = "available"
UNAVAILABLE = "unavailable"
PARTIAL = "partial"  # partial or out of date; `reason` says which

# Icon per status. Color alone is not enough to tell a chip apart, so the icon and the
# status word carry the state too.
_ICONS = {
    AVAILABLE: "fa-check-circle",
    UNAVAILABLE: "fa-exclamation-circle",
    PARTIAL: "fa-exclamation-triangle",
}


@dataclass(frozen=True)
class DataSource:
    """One source to show. `reason` is a short visible note (e.g. "Desactualizado desde
    14:20") that replaces the generic status word; `detail` is the hover text.
    `days_since_update` is shown next to the status and never changes it; ``None`` (not
    known) shows no freshness text."""

    key: str
    label: str
    status: str
    reason: Optional[str] = None
    detail: Optional[str] = None
    days_since_update: Optional[int] = None


def _freshness_text(days: int) -> str:
    if days <= 0:
        return t("source_status.updated_today")
    if days == 1:
        return t("source_status.updated_one_day_ago")
    return t("source_status.updated_days_ago", days=days)


def _chip(source: DataSource) -> html.Span:
    # An unknown status is shown as unavailable, never as healthy.
    status = source.status if source.status in _ICONS else UNAVAILABLE
    status_text = source.reason or t(f"source_status.status_{status}")
    props = {"data-source": source.key, "data-status": status}
    if source.detail:
        props["title"] = source.detail
    children = [
        html.I(className=f"fas {_ICONS[status]} source-chip__icon"),
        html.Span(source.label, className="source-chip__label"),
        html.Span(status_text, className="source-chip__status"),
    ]
    if source.days_since_update is not None:
        children.append(
            html.Span(f"· {_freshness_text(source.days_since_update)}", className="source-chip__freshness")
        )
    return html.Span(
        children,
        className=f"source-chip source-chip--{status}",
        **props,
    )


def render_data_sources(sources: Sequence[DataSource]) -> Optional[html.Div]:
    """A horizontal, wrapping row of status chips, or ``None`` (nothing rendered) when the
    page has no data sources configured."""
    if not sources:
        return None
    return html.Div(
        [
            html.Span(t("source_status.data_sources_title"), className="source-chips__title"),
            *[_chip(source) for source in sources],
        ],
        className="source-chips mb-3",
    )
