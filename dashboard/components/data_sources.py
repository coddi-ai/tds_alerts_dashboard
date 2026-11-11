"""Shared "Fuentes de Datos" popover: a header button with an `n/total` badge that opens one entry
per data source of the page.

Purely presentational. The component is handed a list of `DataSource` and draws it; it does not
know which page it is on, probe files or fetch anything. Which sources a tab has is configuration
(`config/service_data_sources.py`) and how a source's status is resolved lives in
`dashboard/components/source_status.py`, so adding or renaming a source never touches this module.

Opening, closing (close button, Escape, outside click), `aria-expanded`, returning focus to the
trigger and keeping the popover inside the viewport are done by `assets/data_sources_popover.js`,
delegated on `document` so they survive the callback that renders this component being re-run.
"""

from __future__ import annotations

import re
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
    `days_since_update` is shown as "Última actualización" and never changes the status;
    ``None`` (not known) shows "—"."""

    key: str
    label: str
    status: str
    reason: Optional[str] = None
    detail: Optional[str] = None
    days_since_update: Optional[int] = None


def _status_of(source: DataSource) -> str:
    # An unknown status is shown as unavailable, never as healthy.
    return source.status if source.status in _ICONS else UNAVAILABLE


def _freshness_value(days: Optional[int]) -> str:
    """The "Hace N días" text of a source, or "—" when its date is not known."""
    if days is None:
        return "—"
    if days <= 0:
        return t("data_sources_popover.today")
    if days == 1:
        return t("source_status.updated_one_day_ago")
    return t("source_status.updated_days_ago", days=days)


def _chip(status: str, source: DataSource) -> html.Span:
    status_text = source.reason or t(f"data_sources_popover.status_{status}")
    return html.Span(
        [
            html.I(className=f"fas {_ICONS[status]} ds-chip__icon", **{"aria-hidden": "true"}),
            html.Span(status_text, className="ds-chip__text"),
        ],
        className=f"ds-chip ds-chip--{status}",
    )


def _entry(source: DataSource) -> html.Li:
    status = _status_of(source)
    props = {"data-source": source.key, "data-status": status}
    if source.detail:
        props["title"] = source.detail
    return html.Li(
        [
            html.Div(
                [html.Span(source.label, className="ds-source__name"), _chip(status, source)],
                className="ds-source__head",
            ),
            html.Div(
                t("data_sources_popover.last_update", value=_freshness_value(source.days_since_update)),
                className="ds-source__updated",
            ),
        ],
        className="ds-source",
        **props,
    )


def render_data_sources(sources: Sequence[DataSource], scope: str = "page") -> Optional[html.Div]:
    """The trigger button (label + `n/total` badge) and its popover, or ``None`` (nothing
    rendered) when the page has no data sources configured. `scope` keeps the element ids of two
    popovers on one document apart."""
    if not sources:
        return None
    scope = re.sub(r"[^A-Za-z0-9_-]", "-", scope) or "page"
    total = len(sources)
    available = sum(1 for source in sources if _status_of(source) == AVAILABLE)
    popover_id, title_id = f"ds-popover-{scope}", f"ds-title-{scope}"
    summary = t("data_sources_popover.summary", available=available, total=total)
    title = t("data_sources_popover.title")

    trigger = html.Button(
        [
            html.I(className="fas fa-database ds-trigger__icon", **{"aria-hidden": "true"}),
            html.Span(title, className="ds-trigger__label"),
            html.Span(
                f"{available}/{total}",
                className=f"ds-badge ds-badge--{'ok' if available == total else 'warn'}",
            ),
        ],
        type="button",
        className="ds-trigger",
        # The visible label comes first in the accessible name (WCAG 2.5.3), then the count.
        **{
            "aria-haspopup": "dialog",
            "aria-expanded": "false",
            "aria-controls": popover_id,
            "aria-label": f"{title}: {summary}",
        },
    )
    popover = html.Div(
        [
            html.Span(className="ds-popover__caret", **{"aria-hidden": "true"}),
            html.Div(
                [
                    html.H2(title, id=title_id, className="ds-popover__title"),
                    html.Button(
                        html.I(className="fas fa-times", **{"aria-hidden": "true"}),
                        type="button",
                        className="ds-close",
                        **{"aria-label": t("data_sources_popover.close")},
                    ),
                ],
                className="ds-popover__header",
            ),
            html.Ul([_entry(source) for source in sources], className="ds-popover__list"),
        ],
        id=popover_id,
        className="ds-popover",
        hidden=True,
        role="dialog",
        tabIndex=-1,
        **{"aria-labelledby": title_id},
    )
    return html.Div([trigger, popover], className="ds", **{"data-ds": scope})
