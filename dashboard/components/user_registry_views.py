"""Building blocks of "Registro de Usuarios": Resumen de Clientes, Detalle de Cliente, full log.

Everything here turns the plain results of `src.auth_events.metrics` into Dash components.
Colors are the neutral blue palette: these are activity counts, never severity, and the sign
or arrow of a change always travels with its color.
"""

from datetime import datetime
from urllib.parse import quote, urlencode

import dash_bootstrap_components as dbc
import pandas as pd
from dash import dcc, html

from dashboard.components.user_registry_charts import (
    ENV_BORDER, ENV_COLORS, create_daily_chart, create_stacked_chart,
)
from dashboard.services_registry import relative_path
from src.auth_events import metrics as m
from src.i18n import t

PAGE_PATH = "/admin/registro-usuarios"
PAGE_SIZE = 25
RECENT_LOG_SIZE = 6
ENV_ORDER = ("production", "development", "unknown")
SPARK_SIZE = (96, 28)


# ---------------------------------------------------------------------------------------------
# URLs: every link is a real <a href> that carries Período and Ambiente

def page_href(client: str | None = None, period: str | None = None, start: str | None = None,
              end: str | None = None, env: str | None = None, internal: bool = False,
              view: str | None = None, page: int | None = None) -> str:
    params = {"client": client, "period": period, "env": env}
    if period == "custom":
        params.update(start=start, end=end)
    if internal:
        params["internal"] = "1"
    if view:
        params["view"] = view
    if page and page > 1:
        params["page"] = page
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return relative_path(PAGE_PATH) + (f"?{query}" if query else "")


# ---------------------------------------------------------------------------------------------
# Labels

def env_label(env: str) -> str:
    return t(f"user_registry.env.{env}")


def env_swatch(env: str) -> html.Span:
    return html.Span(className="ur-swatch", style={
        "background": ENV_COLORS[env], "borderColor": ENV_BORDER[env]}, **{"aria-hidden": "true"})


def period_options() -> list[dict]:
    return [{"label": t(f"user_registry.period.{key}"), "value": key} for key in m.PERIOD_CHOICES]


def env_options() -> list[dict]:
    return [{"label": t("user_registry.env.all"), "value": "all"}] + [
        {"label": env_label(env), "value": env} for env in ENV_ORDER]


def client_name(row_or_name, is_internal: bool = False) -> str:
    return t("user_registry.internal_team") if is_internal else row_or_name


def when_text(moment: datetime | None) -> str:
    return m.fmt_datetime(moment) if moment else "–"


# ---------------------------------------------------------------------------------------------
# Header and filters

def _field(label_key: str, control_id: str, control) -> html.Div:
    return html.Div([html.Label(t(label_key), htmlFor=control_id, className="ur-label"), control], className="ur-field")


def period_filters(period: str, start: str | None, end: str | None, env: str) -> list:
    custom = period == "custom"
    return [
        _field("user_registry.filter.period", "ur-period",
               dbc.Select(id="ur-period", options=period_options(), value=period)),
        html.Div(
            [
                _field("user_registry.filter.start", "ur-start", dbc.Input(id="ur-start", type="date", value=start or "")),
                _field("user_registry.filter.end", "ur-end", dbc.Input(id="ur-end", type="date", value=end or "")),
            ],
            id="ur-custom-range", className="ur-custom" + ("" if custom else " ur-hidden"),
        ),
        _field("user_registry.filter.env", "ur-env", dbc.Select(id="ur-env", options=env_options(), value=env)),
    ]


def breadcrumb(*items: tuple[str, str | None, str | None]) -> html.Nav:
    """items: (text, href or None, component id of the link or None). Without an href the last
    item is the current page and the others are plain text."""
    parts = []
    for index, (text, href, link_id) in enumerate(items):
        if index:
            parts.append(html.Span("›", className="ur-crumb-sep", **{"aria-hidden": "true"}))
        if href is not None:
            parts.append(dcc.Link(text, href=href, id=link_id, className="ur-crumb") if link_id
                         else dcc.Link(text, href=href, className="ur-crumb"))
        elif index == len(items) - 1:
            parts.append(html.Span(text, className="ur-crumb-current", **{"aria-current": "page"}))
        else:
            parts.append(html.Span(text, className="ur-crumb-plain"))
    return html.Nav(parts, className="ur-breadcrumb", **{"aria-label": t("user_registry.breadcrumb_label")})


def error_alert(message_key: str) -> dbc.Alert:
    return dbc.Alert(t(message_key), color="danger", className="ur-alert")


# ---------------------------------------------------------------------------------------------
# Small pieces

def chip(change: m.Change, tone: str | None = None) -> html.Span:
    tone = tone or {"up": "up", "down": "down"}.get(change.kind, "flat")
    return html.Span(change.text, className=f"ur-chip ur-chip-{tone}")


def info_chip(text: str) -> html.Span:
    return html.Span(text, className="ur-chip ur-chip-info")


def kpi_tile(icon: str, label: str, value: str, chip_el, caption: str) -> dbc.Col:
    return dbc.Col(
        dbc.Card(
            dbc.CardBody([
                html.Div([
                    html.Span(html.I(className=f"fas {icon}"), className="ur-badge", **{"aria-hidden": "true"}),
                    html.Span(label, className="ur-kpi-label"),
                ], className="ur-kpi-head"),
                html.Div(value, className="ur-kpi-value"),
                html.Div([chip_el, html.Span(caption, className="ur-kpi-caption")], className="ur-kpi-foot"),
            ]),
            className="shadow-sm h-100 ur-kpi",
        ),
        xs=12, sm=6, lg=True, className="mb-3",
    )


def pct_chip(part: int, whole: int) -> html.Span:
    return info_chip("–" if whole == 0 else m.fmt_pct_int(part / whole * 100))


def sparkline(values: list[int], label: str) -> html.Img:
    width, height = SPARK_SIZE
    peak = max(values) if values and max(values) > 0 else 1
    step = width / max(len(values) - 1, 1)
    points = " ".join(f"{i * step:.1f},{height - 3 - (v / peak) * (height - 6):.1f}" for i, v in enumerate(values))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
           f'<polyline fill="none" stroke="#2563eb" stroke-width="1.6" stroke-linejoin="round" points="{points}"/></svg>')
    return html.Img(src="data:image/svg+xml;utf8," + quote(svg), alt=label, width=width, height=height, className="ur-spark")


def bar_cell(value: int, maximum: int) -> html.Div:
    width = 0 if maximum <= 0 else max(2, round(value / maximum * 100)) if value else 0
    return html.Div([
        html.Span(m.fmt_int(value), className="ur-bar-num"),
        html.Div(html.Div(className="ur-bar-fill", style={"width": f"{width}%"}), className="ur-bar-track", **{"aria-hidden": "true"}),
    ], className="ur-bar-cell")


def table_wrap(table: html.Table) -> html.Div:
    return html.Div(table, className="ur-table-wrap")


def card(title: str, body, caption: str | None = None, subtitle: str | None = None, footer=None, class_name: str = "") -> dbc.Card:
    head = [html.H2(title, className="ur-card-title")]
    if subtitle:
        head.append(html.Span(subtitle, className="ur-card-sub"))
    children = [html.Div(head, className="ur-card-head"), body]
    if caption:
        children.append(html.Div(caption, className="ur-caption"))
    if footer is not None:
        children.append(footer)
    return dbc.Card(dbc.CardBody(children), className=f"shadow-sm mb-3 {class_name}".strip())


def graph(figure, graph_id: str | None = None) -> dcc.Graph:
    return dcc.Graph(figure=figure, config={"displayModeBar": False, "responsive": True}, className="ur-graph",
                     **({"id": graph_id} if graph_id else {}))


def empty_note(key: str = "user_registry.empty.no_logins") -> html.P:
    return html.P(t(key), className="ur-empty", role="status")


# ---------------------------------------------------------------------------------------------
# Resumen de Clientes

def overview_content(ov: m.Overview, filters: dict) -> list:
    n = ov.period.days
    first_label = t("user_registry.kpi.logins_with_internal" if ov.include_internal else "user_registry.kpi.client_logins")
    tiles = dbc.Row([
        kpi_tile("fa-right-to-bracket", first_label, m.fmt_int(ov.logins), chip(ov.logins_change),
                 t("user_registry.kpi.vs_previous", n=n, count=m.fmt_int(ov.previous_logins))),
        kpi_tile("fa-building", t("user_registry.kpi.active_clients"), m.fmt_int(ov.active_clients),
                 pct_chip(ov.active_clients, ov.registered_clients),
                 t("user_registry.kpi.of_clients", m=m.fmt_int(ov.registered_clients))),
        kpi_tile("fa-user-check", t("user_registry.kpi.active_users"), m.fmt_int(ov.active_users),
                 pct_chip(ov.active_users, ov.registered_users),
                 t("user_registry.kpi.of_client_users", k=m.fmt_int(ov.registered_users))),
    ], className="ur-kpi-row")

    rows = m.sort_rows_by_logins(ov.rows)
    maximum = max((r.logins for r in rows), default=0)
    now = filters["now"]
    body_rows = []
    for row in rows:
        name = client_name(row.name, row.is_internal)
        href = page_href(client=row.client_id, **filters["nav"])
        body_rows.append(html.Tr([
            html.Th(dcc.Link(name, href=href, className="ur-link"), scope="row"),
            html.Td(bar_cell(row.logins, maximum)),
            html.Td(chip(row.change)),
            html.Td(t("user_registry.table.active_of", active=m.fmt_int(row.active_users), registered=m.fmt_int(row.registered_users))),
            html.Td(sparkline(row.spark, t("user_registry.table.spark_alt", name=name, count=m.fmt_int(row.logins)))),
            html.Td(m.relative_access(row.last_access, now), className="ur-nowrap"),
            html.Td(dcc.Link([t("user_registry.table.view_detail"),
                              html.Span(t("user_registry.table.view_detail_for", name=name), className="ur-sr-only")],
                             href=href, className="ur-link ur-nowrap")),
        ]))
    table = html.Table([
        html.Thead(html.Tr([
            html.Th(t("user_registry.table.client"), scope="col"),
            html.Th(t("user_registry.table.logins"), scope="col"),
            html.Th(t("user_registry.table.vs_previous_days", n=n), scope="col"),
            html.Th(t("user_registry.table.active_users"), scope="col"),
            html.Th(t("user_registry.table.trend"), scope="col"),
            html.Th(t("user_registry.table.last_access"), scope="col"),
            html.Th(html.Span(t("user_registry.table.action"), className="ur-sr-only"), scope="col"),
        ])),
        html.Tbody(body_rows),
    ], className="ur-table")
    clients_card = card(t("user_registry.clients_title"), table_wrap(table), subtitle=ov.period.caption(),
                        footer=html.Div(t("user_registry.clients_footer"), className="ur-caption"))

    chart_body = graph(create_daily_chart(ov.buckets, ov.chart_counts))
    chart_card = card(t("user_registry.chart.client_title"), chart_body, caption=t("user_registry.chart.client_caption"))

    notes = []
    if ov.internal_hidden_logins:
        notes.append(html.P(t("user_registry.note.internal_excluded", n=m.fmt_int(ov.internal_hidden_logins)), className="ur-footnote"))
    if ov.unmapped_logins:
        notes.append(html.P(t("user_registry.note.unmapped", n=m.fmt_int(ov.unmapped_logins), users=", ".join(ov.unmapped_usernames)), className="ur-footnote"))
    if ov.orphan_client_logins:
        notes.append(html.P(t("user_registry.note.orphan_clients", n=m.fmt_int(ov.orphan_client_logins)), className="ur-footnote"))
    return [tiles, clients_card, chart_card, html.Div(notes, className="ur-notes")]


# ---------------------------------------------------------------------------------------------
# Detalle de Cliente

def detail_content(d: m.Detail, filters: dict) -> list:
    n = d.period.days
    now = filters["now"]
    last_chip = info_chip(m.fmt_weekday_datetime(d.last_access)) if d.last_access else info_chip("–")
    last_caption = t("user_registry.kpi.user_caption", username=d.last_access_user) if d.last_access_user else t("user_registry.kpi.no_access_caption")
    tiles = dbc.Row([
        kpi_tile("fa-right-to-bracket", t("user_registry.kpi.logins"), m.fmt_int(d.logins), chip(d.logins_change),
                 t("user_registry.kpi.vs_previous", n=n, count=m.fmt_int(d.previous_logins))),
        kpi_tile("fa-user-check", t("user_registry.kpi.active_users"), m.fmt_int(d.active_users),
                 pct_chip(d.active_users, d.registered_users),
                 t("user_registry.kpi.of_registered_users", k=m.fmt_int(d.registered_users))),
        kpi_tile("fa-calendar-check", t("user_registry.kpi.active_days"), m.fmt_int(d.active_days),
                 pct_chip(d.active_days, n), t("user_registry.kpi.of_days", n=m.fmt_int(n))),
        kpi_tile("fa-clock", t("user_registry.kpi.last_access"), m.relative_access(d.last_access, now) if d.last_access else t("user_registry.relative.never"),
                 last_chip, last_caption),
    ], className="ur-kpi-row ur-kpi-row-4")

    chart_card = card(t("user_registry.chart.detail_title"), graph(create_stacked_chart(d.buckets, d.series)),
                      caption=t("user_registry.chart.detail_caption"))

    users_card = card(t("user_registry.users_title"), _users_table(d, now), footer=html.Div(
        t("user_registry.users_footer", active=m.fmt_int(d.active_users), registered=m.fmt_int(d.registered_users)),
        className="ur-caption"))

    heat_card = card(t("user_registry.heatmap.title"), _heatmap(d), caption=t("user_registry.heatmap.caption"),
                     footer=_heatmap_legend() if not d.empty else None, class_name="h-100")

    shown = d.log.head(RECENT_LOG_SIZE)
    log_footer = html.Div([
        html.Span(t("user_registry.log.showing", shown=m.fmt_int(len(shown)), total=m.fmt_int(len(d.log))), className="ur-caption"),
        dcc.Link(t("user_registry.log.view_full"), href=page_href(client=d.client_id, view="log", **filters["nav"]), className="ur-link"),
    ], className="ur-log-footer")
    log_card = card(t("user_registry.log.title"), _log_table(shown) if len(shown) else empty_note(), footer=log_footer, class_name="h-100")

    return [tiles, chart_card, users_card, dbc.Row([dbc.Col(heat_card, lg=7, className="mb-3"), dbc.Col(log_card, lg=5, className="mb-3")])]


def _users_table(d: m.Detail, now: datetime) -> html.Div:
    if not d.users:
        return empty_note("user_registry.empty.no_users")
    maximum = max(u.total for u in d.users)
    env_headers = [html.Th([env_swatch(env), env_label(env)], scope="col", className="ur-num") for env in ("production", "development")]
    if d.show_unknown:
        env_headers.append(html.Th([env_swatch("unknown"), env_label("unknown")], scope="col", className="ur-num"))
    head = html.Tr([html.Th(t("user_registry.users.user"), scope="col"), *env_headers,
                    html.Th(t("user_registry.users.total"), scope="col"),
                    html.Th(t("user_registry.users.active_days"), scope="col", className="ur-num"),
                    html.Th(t("user_registry.table.last_access"), scope="col")])
    body = []
    for u in d.users:
        cells = [html.Th(u.username, scope="row"),
                 html.Td(m.fmt_int(u.production) if u.production else "–", className="ur-num"),
                 html.Td(m.fmt_int(u.development) if u.development else "–", className="ur-num")]
        if d.show_unknown:
            cells.append(html.Td(m.fmt_int(u.unknown) if u.unknown else "–", className="ur-num"))
        cells += [html.Td(bar_cell(u.total, maximum)),
                  html.Td(m.fmt_int(u.active_days), className="ur-num"),
                  html.Td(m.relative_access(u.last_access, now) if u.last_access else t("user_registry.relative.never"), className="ur-nowrap")]
        body.append(html.Tr(cells))
    return table_wrap(html.Table([html.Thead(head), html.Tbody(body)], className="ur-table", id="ur-users-table"))


def _heatmap(d: m.Detail):
    if d.empty:
        return empty_note()
    head = html.Tr([html.Th(html.Span(t("user_registry.heatmap.day"), className="ur-sr-only"), scope="col")] + [
        html.Th(f"{block * 2:02d}", scope="col", className="ur-heat-head") for block in range(m.HEATMAP_BLOCKS)])
    body = []
    for weekday, counts in enumerate(d.heatmap):
        cells = [html.Th(m.WEEKDAYS[weekday], scope="row", className="ur-heat-day")]
        for block, count in enumerate(counts):
            level = m.heatmap_level(count, d.heatmap_max)
            tip = t("user_registry.heatmap.tooltip", day=m.WEEKDAYS[weekday], start=f"{block * 2:02d}:00", end=f"{block * 2 + 2:02d}:00", n=m.fmt_int(count))
            cells.append(html.Td(m.fmt_int(count) if count else "", className=f"ur-heat ur-heat-{level}", title=tip, **{"aria-label": tip}))
        body.append(html.Tr(cells))
    return table_wrap(html.Table([html.Thead(head), html.Tbody(body)], className="ur-heatmap", id="ur-heatmap"))


def _heatmap_legend() -> html.Div:
    return html.Div([html.Span(t("user_registry.heatmap.less"), className="ur-caption")] + [
        html.Span(className=f"ur-heat-key ur-heat-{level}", **{"aria-hidden": "true"}) for level in range(5)] + [
        html.Span(t("user_registry.heatmap.more"), className="ur-caption")], className="ur-heat-legend")


def _log_table(log: pd.DataFrame) -> html.Div:
    rows = []
    for event in log.itertuples():
        rows.append(html.Tr([
            html.Td(m.fmt_datetime(event.timestamp), className="ur-nowrap"),
            html.Td(event.username),
            html.Td([env_swatch(event.environment), env_label(event.environment)], className="ur-nowrap"),
        ]))
    return table_wrap(html.Table([
        html.Thead(html.Tr([html.Th(t("user_registry.log.when"), scope="col"), html.Th(t("user_registry.log.user"), scope="col"),
                            html.Th(t("user_registry.log.env"), scope="col")])),
        html.Tbody(rows)], className="ur-table ur-table-compact"))


# ---------------------------------------------------------------------------------------------
# Full log

def full_log_content(d: m.Detail, page: int, name: str, filters: dict) -> list:
    total = len(d.log)
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(max(page, 1), pages)
    chunk = d.log.iloc[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    def link(target: int, text: str):
        return dcc.Link(text, href=page_href(client=d.client_id, view="log", page=target, **filters["nav"]), className="ur-link")

    pager = html.Nav([
        link(page - 1, t("user_registry.log.previous")) if page > 1 else html.Span(t("user_registry.log.previous"), className="ur-disabled"),
        html.Span(t("user_registry.log.page_of", page=page, pages=pages), className="ur-caption"),
        link(page + 1, t("user_registry.log.next")) if page < pages else html.Span(t("user_registry.log.next"), className="ur-disabled"),
    ], className="ur-pager", **{"aria-label": t("user_registry.log.pager_label")})

    scope = html.Div([
        html.Span(t("user_registry.log.scope_client", client=name), className="ur-chip ur-chip-flat"),
        html.Span(d.period.caption(), className="ur-chip ur-chip-flat"),
        html.Span(filters["env_text"], className="ur-chip ur-chip-flat"),
    ], className="ur-scope")
    body = [_log_table(chunk) if total else empty_note(), pager if total else html.Div()]
    footer = html.Div(t("user_registry.log.range", first=m.fmt_int((page - 1) * PAGE_SIZE + 1 if total else 0),
                        last=m.fmt_int(min(page * PAGE_SIZE, total)), total=m.fmt_int(total)), className="ur-caption")
    return [scope, card(t("user_registry.log.full_title"), html.Div(body), footer=footer)]
