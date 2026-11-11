"""Admin-only "Registro de Usuarios": Resumen de Clientes, Detalle de Cliente and the full log.

One route (/admin/registro-usuarios); the query string picks the view:
    (none)                 Resumen de Clientes
    ?client=<id>           Detalle de Cliente   (`internal` = Equipo Interno)
    ?client=<id>&view=log  Registro completo (paginated)
Período, Ambiente and "Incluir Usuarios Internos" travel in the query string too
(`period`, `start`, `end`, `env`, `internal`), so links keep them and views can be bookmarked.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard.components import user_registry_views as v
from dashboard.components.source_status import render_service_data_sources
from src.auth_events import metrics as m
from src.auth_events.data_access import AuthDataUnavailable, display_timezone, get_events, get_registry, last_loaded_at
from src.i18n import t

ENV_VALUES = ("all", "production", "development", "unknown")


def parse_query(query: dict) -> dict:
    period = m.normalize_period_kind(query.get("period"), query.get("start"), query.get("end"))
    env = query.get("env") if query.get("env") in ENV_VALUES else "all"
    try:
        page = max(int(query.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1
    return {
        "client": (query.get("client") or "").strip() or None,
        "period": period,
        "start": query.get("start") if period == "custom" else None,
        "end": query.get("end") if period == "custom" else None,
        "env": env,
        "internal": str(query.get("internal", "")).lower() in ("1", "true", "on"),
        "view": query.get("view"),
        "page": page,
    }


def nav_params(q: dict) -> dict:
    return {"period": q["period"], "start": q["start"], "end": q["end"], "env": q["env"], "internal": q["internal"]}


def header_title(title: str, subtitle_id: str | None = None, subtitle: str = "") -> html.Div:
    return html.Div([
        html.H1(title, className="ur-title"),
        html.P(subtitle, id=subtitle_id, className="ur-subtitle") if subtitle_id else html.P(subtitle, className="ur-subtitle"),
    ])


def _shell(children: list) -> html.Div:
    return html.Div(children, className="ur-page")


def _crumbs(*extra) -> html.Nav:
    return v.breadcrumb((t("user_registry.breadcrumb.admin"), None, None), *extra)


def _unavailable() -> html.Div:
    return _shell([
        _crumbs((t("user_registry.title"), None, None)),
        header_title(t("user_registry.title")),
        v.error_alert("user_registry.error.unavailable"),
    ])


def overview_layout(q: dict) -> html.Div:
    return _shell([
        dcc.Store(id="ur-ov-url-sync"),
        _crumbs((t("user_registry.title"), None, None)),
        html.Div(
            [
                header_title(t("user_registry.title"), "ur-ov-subtitle", t("user_registry.subtitle.loading")),
                # "Fuentes de Datos" button + popover: the login-event store does not depend on the client.
                html.Div(render_service_data_sources("", "admin-user-registry"), className="ds-header-slot"),
            ],
            className="d-flex flex-wrap justify-content-between align-items-start gap-3",
        ),
        html.Div([
            *v.period_filters(q["period"], q["start"], q["end"], q["env"]),
            html.Div(dbc.Checkbox(id="ur-internal", label=t("user_registry.filter.internal"), value=q["internal"], className="ur-check"),
                     className="ur-field ur-field-check"),
        ], className="ur-filters", role="group", **{"aria-label": t("user_registry.filters_label")}),
        dcc.Loading(html.Div(id="ur-ov-content"), type="circle"),
    ])


def client_options(registry=None) -> list[dict]:
    registry = registry or get_registry()
    options = [{"label": c["display_name"], "value": c["client_id"]} for c in registry.active_clients()]
    return options + [{"label": t("user_registry.internal_team"), "value": m.INTERNAL_ID}]


def _not_found(q: dict) -> html.Div:
    overview = v.page_href(**nav_params(q))
    return _shell([
        _crumbs((t("user_registry.title"), overview, "ur-crumb-link")),
        header_title(t("user_registry.not_found.title")),
        html.P(t("user_registry.not_found.text"), className="ur-subtitle"),
        dcc.Link(t("user_registry.back_to_overview"), href=overview, className="ur-back"),
    ])


def detail_layout(q: dict) -> html.Div:
    try:
        options = client_options()
    except AuthDataUnavailable:
        return _unavailable()

    client_id = q["client"]
    known = {o["value"]: o["label"] for o in options}
    if client_id not in known:
        return _not_found(q)

    name = known[client_id]
    overview = v.page_href(**nav_params(q))
    return _shell([
        dcc.Store(id="ur-cd-url-sync"),
        dcc.Store(id="ur-current-client", data=client_id),
        dcc.Store(id="ur-carry", data={"internal": q["internal"]}),
        _crumbs((t("user_registry.title"), overview, "ur-crumb-link"), (name, None, None)),
        html.Div([
            header_title(name, "ur-cd-subtitle", t("user_registry.subtitle.loading")),
            dcc.Link(t("user_registry.back_to_overview"), href=overview, id="ur-back-link", className="ur-back"),
        ], className="ur-title-row"),
        html.Div([
            v._field("user_registry.filter.client", "ur-client", dbc.Select(id="ur-client", options=options, value=client_id)),
            *v.period_filters(q["period"], q["start"], q["end"], q["env"]),
        ], className="ur-filters", role="group", **{"aria-label": t("user_registry.filters_label")}),
        dcc.Loading(html.Div(id="ur-cd-content"), type="circle"),
    ])


def full_log_layout(q: dict) -> html.Div:
    try:
        registry = get_registry()
        known = {o["value"]: o["label"] for o in client_options(registry)}
        if q["client"] not in known:
            return _not_found(q)
        now = datetime.now(ZoneInfo(display_timezone()))
        period = m.resolve_period(q["period"], now.date(), q["start"], q["end"])
        events = get_events(environment=None if q["env"] == "all" else q["env"])
        detail = m.build_detail(events, registry, q["client"], period)
        loaded = last_loaded_at()
    except AuthDataUnavailable:
        return _unavailable()

    name = known[q["client"]]
    back = v.page_href(client=q["client"], **nav_params(q))
    overview = v.page_href(**nav_params(q))
    filters = {"now": now, "nav": nav_params(q), "env_text": t(f"user_registry.env.{q['env']}")}
    subtitle = t("user_registry.subtitle.client", when=m.fmt_datetime(loaded.astimezone(now.tzinfo)) if loaded else "–")
    return _shell([
        _crumbs((t("user_registry.title"), overview, "ur-crumb-link"), (name, back, "ur-crumb-client")),
        html.Div([
            header_title(t("user_registry.log.full_heading", name=name), None, subtitle),
            dcc.Link(t("user_registry.log.back_to_client"), href=back, className="ur-back"),
        ], className="ur-title-row"),
        *v.full_log_content(detail, q["page"], name, filters),
    ])


def create_layout(**query) -> html.Div:
    q = parse_query(query)
    if q["client"] is None:
        return overview_layout(q)
    if q["view"] == "log":
        return full_log_layout(q)
    return detail_layout(q)
