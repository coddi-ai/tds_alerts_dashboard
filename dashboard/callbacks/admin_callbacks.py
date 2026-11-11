"""Admin-only callbacks of "Registro de Usuarios" (Resumen de Clientes and Detalle de Cliente).

Data comes only from `src.auth_events.data_access`. Every callback re-checks, from the server
session, that the caller is an admin: a callback can be invoked without ever loading the page.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import dash
from dash import Input, Output, State
from dash.exceptions import PreventUpdate

from config.users import is_admin
from dashboard.auth import resolve_authenticated_username
from dashboard.components import user_registry_views as v
from dashboard.tabs.tab_user_registry import ENV_VALUES
from src.auth_events import metrics as m
from src.auth_events.data_access import AuthDataUnavailable, display_timezone, get_events, get_registry, last_loaded_at
from src.i18n import t
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Mirrors the filters into the address bar without navigating (replaceState), so a reload or a
# shared link keeps them. Links inside the page are rebuilt from the same values on every render.
_URL_SYNC_JS = """
function(period, start, end, env, internal) {
    try {
        var p = new URLSearchParams(window.location.search);
        var put = function(k, val) { if (val === null || val === undefined || val === '' || val === false) { p.delete(k); } else { p.set(k, val); } };
        put('period', period);
        put('start', period === 'custom' ? start : null);
        put('end', period === 'custom' ? end : null);
        put('env', env);
        put('internal', internal ? '1' : null);
        var query = p.toString();
        window.history.replaceState(window.history.state, '', window.location.pathname + (query ? '?' + query : ''));
    } catch (e) {}
    return window.dash_clientside.no_update;
}
"""


def _is_admin(user_data) -> bool:
    username = resolve_authenticated_username(user_data)
    return bool(username and is_admin(username))


def _context(period, start, end, env):
    """Everything a render needs: full history for the chosen Ambiente, registry, 'now'."""
    registry = get_registry()
    env_value = env if env in ENV_VALUES and env != "all" else None
    events = get_events(environment=env_value)
    now = datetime.now(ZoneInfo(display_timezone()))
    kind = m.normalize_period_kind(period, start, end)
    resolved = m.resolve_period(kind, now.date(), start, end)
    return registry, events, now, kind, resolved, last_loaded_at()


def _subtitle(key: str, loaded, now) -> str:
    when = m.fmt_datetime(loaded.astimezone(now.tzinfo)) if loaded else m.fmt_datetime(now)
    return t(key, when=when)


def register_admin_callbacks(app: dash.Dash) -> None:
    """Register the Registro de Usuarios callbacks."""

    @app.callback(
        Output("ur-custom-range", "className"),
        Input("ur-period", "value"),
    )
    def toggle_custom_range(period):
        return "ur-custom" + ("" if period == "custom" else " ur-hidden")

    app.clientside_callback(
        _URL_SYNC_JS,
        Output("ur-ov-url-sync", "data"),
        Input("ur-period", "value"), Input("ur-start", "value"), Input("ur-end", "value"),
        Input("ur-env", "value"), Input("ur-internal", "value"),
    )

    app.clientside_callback(
        _URL_SYNC_JS.replace("function(period, start, end, env, internal)", "function(period, start, end, env)").replace(
            "put('internal', internal ? '1' : null);", ""),
        Output("ur-cd-url-sync", "data"),
        Input("ur-period", "value"), Input("ur-start", "value"), Input("ur-end", "value"), Input("ur-env", "value"),
    )

    @app.callback(
        Output("ur-ov-content", "children"),
        Output("ur-ov-subtitle", "children"),
        Input("ur-period", "value"), Input("ur-start", "value"), Input("ur-end", "value"),
        Input("ur-env", "value"), Input("ur-internal", "value"),
        State("user-info-store", "data"),
    )
    def render_overview(period, start, end, env, internal, user_data):
        if not _is_admin(user_data):
            raise PreventUpdate
        try:
            registry, events, now, kind, resolved, loaded = _context(period, start, end, env)
        except AuthDataUnavailable as exc:
            logger.error("Registro de Usuarios: data unavailable: %s", exc)
            return v.error_alert("user_registry.error.unavailable"), t("user_registry.subtitle.unavailable")
        overview = m.build_overview(events, registry, resolved, bool(internal))
        filters = {"now": now, "nav": {"period": kind, "start": start, "end": end, "env": env, "internal": bool(internal)}}
        return v.overview_content(overview, filters), _subtitle("user_registry.subtitle.overview", loaded, now)

    @app.callback(
        Output("ur-cd-content", "children"),
        Output("ur-cd-subtitle", "children"),
        Output("ur-back-link", "href"),
        Output("ur-crumb-link", "href"),
        Input("ur-period", "value"), Input("ur-start", "value"), Input("ur-end", "value"), Input("ur-env", "value"),
        State("ur-current-client", "data"), State("ur-carry", "data"), State("user-info-store", "data"),
    )
    def render_detail(period, start, end, env, client_id, carry, user_data):
        if not _is_admin(user_data):
            raise PreventUpdate
        internal = bool((carry or {}).get("internal"))
        kind = m.normalize_period_kind(period, start, end)
        back = v.page_href(period=kind, start=start, end=end, env=env, internal=internal)
        try:
            registry, events, now, kind, resolved, loaded = _context(period, start, end, env)
        except AuthDataUnavailable as exc:
            logger.error("Registro de Usuarios: data unavailable: %s", exc)
            return v.error_alert("user_registry.error.unavailable"), t("user_registry.subtitle.unavailable"), back, back
        detail = m.build_detail(events, registry, client_id, resolved)
        filters = {"now": now, "nav": {"period": kind, "start": start, "end": end, "env": env, "internal": internal}}
        return (v.detail_content(detail, filters), _subtitle("user_registry.subtitle.client", loaded, now), back, back)

    @app.callback(
        Output("_pages_location", "search"),
        Input("ur-client", "value"),
        State("ur-current-client", "data"), State("ur-period", "value"), State("ur-start", "value"),
        State("ur-end", "value"), State("ur-env", "value"), State("ur-carry", "data"), State("user-info-store", "data"),
        prevent_initial_call=True,
    )
    def change_client(selected, current, period, start, end, env, carry, user_data):
        if not selected or selected == current or not _is_admin(user_data):
            raise PreventUpdate
        href = v.page_href(client=selected, period=m.normalize_period_kind(period, start, end), start=start, end=end,
                           env=env, internal=bool((carry or {}).get("internal")))
        return href[href.index("?"):]
