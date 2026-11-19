"""Server-side detection of page and tab openings (TR-6, items 3 and 7).

In Dash, moving between pages and tabs is done by callbacks, not by page requests, so there is no
request to log. This module installs one Flask `before_request` hook on Dash's callback endpoint
(`/_dash-update-component`) and inspects each callback request:

  * Page opening: the Dash Pages router callback (output `_pages_content.children`) fired because
    `_pages_location.pathname` changed. This covers navigating, reloading and landing after login.
    A change of the query string alone (`?client=...`, filters) is not a page opening.
  * Tab opening: a watched tab component's `value` is among the request's changed inputs. Only the
    list in `TAB_COMPONENTS` is watched; clicking the already-active tab never reaches the server.

A page that shows a default tab is recorded once, with that tab (`TabComponent.default`).
Everything else (filter and toggle changes, intervals, clicks inside a page) changes other inputs
and is ignored. Only `username`, the path (no query string, no fragment, no deployment prefix),
and the tab value are taken from the request. The hook costs a JSON parse and a few comparisons and
never raises; the work that can be slow happens in `src.auth_events.pageviews`' background flusher.

Pages need no edits. To watch a new tab strip, add one `TabComponent` below.
"""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from flask import request

from config.users import is_admin
from dashboard.auth import resolve_authenticated_username
from src.auth_events import settings
from src.auth_events.pageviews import record_page_view
from src.auth_events.registry import normalize_path, template_matches
from src.utils.logger import get_logger

logger = get_logger(__name__)

CALLBACK_ENDPOINT = "_dash-update-component"
PAGES_OUTPUT = "_pages_content.children"
LOCATION_PATHNAME = "_pages_location.pathname"


@dataclass(frozen=True)
class TabComponent:
    component_id: str
    path: str           # the page that shows it; `<name>` stands for one path segment
    default: str        # the tab that is active when the page opens


# The one place that lists the tab strips whose openings count as page views.
TAB_COMPONENTS = (
    TabComponent("alerts-internal-tabs", "/monitoring/alerts", "general"),
    TabComponent("oil-internal-tabs", "/monitoring/oil", "fleet-overview"),
    TabComponent("telemetry-health-tabs", "/monitoring/telemetry", "fleet-overview"),
    TabComponent("predictive-component-internal-tabs", "/predictive/<component>", "resumen"),
)

# Routes that only redirect somewhere else: the real page is recorded after the redirect.
REDIRECT_PATHS = frozenset({"/", "/admin/registro-usuarios"})


def strip_prefix(path: str, prefix: str) -> str:
    """Drop the deployment prefix (`DASH_PATH_PREFIX`, e.g. `/alerts-dashboard/`) from a pathname."""
    prefix = "/" + prefix.strip("/") if prefix and prefix.strip("/") else ""
    path = "/" + (path or "").lstrip("/")
    if prefix and (path == prefix or path.startswith(prefix + "/")):
        path = path[len(prefix):] or "/"
    return path


def _flatten(items):
    for item in items or []:
        if isinstance(item, dict):
            yield item
        elif isinstance(item, (list, tuple)):
            yield from _flatten(item)


def _value_of(payload: dict, component_id: str, prop: str):
    for item in _flatten(payload.get("inputs")):
        if item.get("id") == component_id and item.get("property") == prop:
            return item.get("value"), True
    for item in _flatten(payload.get("state")):
        if item.get("id") == component_id and item.get("property") == prop:
            return item.get("value"), True
    return None, False


def default_tab_for(path: str) -> str | None:
    for comp in TAB_COMPONENTS:
        if comp.path == path or ("<" in comp.path and template_matches(comp.path, path)):
            return comp.default
    return None


def detect_view(payload, referer_path: str | None, prefix: str = "") -> tuple[str, str | None] | None:
    """`(path, tab)` when this callback request is a page or tab opening, else None."""
    if not isinstance(payload, dict):
        return None
    changed = payload.get("changedPropIds") or []

    if PAGES_OUTPUT in str(payload.get("output", "")):
        if LOCATION_PATHNAME not in changed:
            return None  # only the query string changed: a filter or a drill-down inside the page
        pathname, found = _value_of(payload, "_pages_location", "pathname")
        if not found or not isinstance(pathname, str):
            return None
        path = normalize_path(strip_prefix(pathname, prefix))
        if path in REDIRECT_PATHS:
            return None
        return path, default_tab_for(path)

    for comp in TAB_COMPONENTS:
        if f"{comp.component_id}.value" not in changed:
            continue
        value, found = _value_of(payload, comp.component_id, "value")
        if not found or not isinstance(value, str) or not value:
            continue
        if not referer_path:
            return None
        path = normalize_path(strip_prefix(referer_path, prefix))
        if path != comp.path and not ("<" in comp.path and template_matches(comp.path, path)):
            continue  # the request does not come from the page that owns this tab strip
        return path, value
    return None


def _referer_path() -> str | None:
    referer = request.headers.get("Referer") or request.referrer
    return urlsplit(referer).path if referer else None


def _signed_in_user(payload) -> str | None:
    user_data, found = (_value_of(payload, "user-info-store", "data") if isinstance(payload, dict) else (None, False))
    return resolve_authenticated_username(user_data if found and isinstance(user_data, dict) else None)


def capture_page_view():
    """Flask before_request hook. Always returns None so the request goes on untouched."""
    try:
        if (request.method != "POST" or not request.path.endswith(CALLBACK_ENDPOINT)
                or not settings.page_views_enabled()):
            return None
        payload = request.get_json(silent=True)
        view = detect_view(payload, _referer_path(), os.getenv("DASH_PATH_PREFIX", ""))
        if view is None:
            return None
        username = _signed_in_user(payload)
        if not username:
            return None  # unauthenticated: nothing is recorded
        path, tab = view
        if path.startswith("/admin") and not is_admin(username):
            return None  # the route guard bounces them; they never saw this page
        record_page_view(username, path, tab)
    except Exception as exc:  # noqa: BLE001 - capture is best-effort and must never block navigation
        logger.error("Page-view capture failed: %s: %s", type(exc).__name__, exc)
    return None


def register_page_view_capture(app) -> None:
    """Install the hook. It stays inert until `AUTH_EVENTS_PAGE_VIEWS` is turned on."""
    app.server.before_request(capture_page_view)
