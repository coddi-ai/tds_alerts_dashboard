"""TR-7 UI: Actividad de Usuarios. Layouts build from a store, links are real, palette is neutral, admin-only."""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dash_bootstrap_components as dbc
import pytest
from dash import dcc, html

from src.auth_events import data_access, settings
from src.auth_events.events import build_event, build_page_view_event, raw_key
from src.auth_events.registry import reset_registry_cache
from src.auth_events.storage import LocalStorage

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "config" / "auth_registry"
CSS = (ROOT / "dashboard" / "assets" / "user_registry.css").read_text(encoding="utf-8")


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None and not isinstance(children, str):
        yield from _walk(children)


def _luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _put(storage, event):
    storage.put(raw_key(event), json.dumps(event).encode())


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_EVENTS_LOCAL_DIR", str(tmp_path))
    storage = LocalStorage(tmp_path)
    storage.put(settings.REGISTRY_CLIENTS_KEY, (SEED / "clients.json").read_bytes())
    storage.put(settings.REGISTRY_USERS_KEY, (SEED / "users.json").read_bytes())
    storage.put(settings.REGISTRY_PAGES_KEY, (SEED / "pages.json").read_bytes())
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    for i, user in enumerate(("cda_user", "cda_user", "emin_user")):
        _put(storage, build_event(user, "client", user.split("_")[0], "production", moment=base + timedelta(seconds=i), event_id=f"v{i}"))
    # nine page views of cda_user (alerts x5, oil x3, one page missing from the registry), one of emin_user
    paths = ["/monitoring/alerts"] * 5 + ["/monitoring/oil"] * 3 + ["/not/in/registry"]
    for i, path in enumerate(paths):
        tab = "general" if path == "/monitoring/alerts" else None
        page_id = {"/monitoring/alerts": "monitoreo.alertas.general", "/monitoring/oil": "unregistered"}.get(path, "unregistered")
        _put(storage, build_page_view_event("cda_user", "client", "cda", "production", page_id, path, tab,
                                            moment=base + timedelta(minutes=1 + i), event_id=f"p{i}"))
    _put(storage, build_page_view_event("emin_user", "client", "emin", "production", "unregistered", "/monitoring/oil", None,
                                        moment=base + timedelta(minutes=20), event_id="pe"))
    reset_registry_cache()
    data_access.clear_cache()
    yield storage
    reset_registry_cache()
    data_access.clear_cache()


def _content(period="7", env="all", internal=True, metric="views"):
    from dashboard.callbacks.admin_callbacks import _context
    from dashboard.components import user_registry_views as v
    from src.auth_events import metrics as m

    registry, events, now, kind, resolved, _, capture = _context(period, None, None, env)
    ov = m.build_overview(events, registry, resolved, internal, capture)
    filters = {"now": now, "nav": {"period": kind, "start": None, "end": None, "env": env, "internal": internal}}
    return ov, v.overview_content(ov, filters, metric), filters


def test_heatmap_levels_meet_text_contrast():
    levels = {m[0]: (m[1], m[2]) for m in re.findall(r"\.ur-heat-(\d) \{ background: (#[0-9a-f]{6}); color: (#[0-9a-f]{6});", CSS)}
    assert len(levels) == 5
    for level, (background, text) in levels.items():
        assert _contrast(background, text) >= 4.5, level


def test_palette_has_no_severity_colors_and_chips_meet_contrast():
    forbidden = ("#dc2626", "#b91c1c", "#ef4444", "#f59e0b", "#16a34a", "#15803d", "#dcfce7", "#fee2e2", "#fef3c7")
    assert not [c for c in forbidden if c in CSS.lower()]
    from dashboard.components import user_registry_charts as charts
    assert not [c for c in forbidden if c in repr(vars(charts)).lower()]
    assert "border-left" not in CSS
    for name in ("page", "login"):
        background, text = re.search(rf"\.ur-chip-{name} \{{ background: (#[0-9a-f]{{6}}); color: (#[0-9a-f]{{6}});", CSS).groups()
        assert _contrast(background, text) >= 4.5, name


def test_overview_layout_has_labelled_controls_and_notice_slot(store):
    from dashboard.tabs.tab_user_registry import create_layout
    layout = create_layout()
    nodes = list(_walk(layout))
    labels = {n.htmlFor for n in nodes if isinstance(n, html.Label)}
    assert {"ur-period", "ur-env"} <= labels
    ids = {getattr(n, "id", None) for n in nodes}
    assert {"ur-period", "ur-env", "ur-internal", "ur-ov-content", "ur-ov-notice", "ur-ov-metric-state"} <= ids
    defaults = {n.id: n.value for n in nodes if getattr(n, "id", None) in ("ur-period", "ur-env", "ur-internal")}
    assert defaults == {"ur-period": "30", "ur-env": "all", "ur-internal": False}
    assert next(n for n in nodes if getattr(n, "id", None) == "ur-ov-metric-state").data == "views"   # toggle resets per view
    assert "Actividad de Usuarios" in repr(layout) and "Registro de Usuarios" not in repr(layout)


def test_overview_kpis_in_order_and_client_table_matches_them(store):
    ov, content, _ = _content(internal=False)
    text = repr(content)
    order = [text.index(label) for label in ("Vistas de Página", "Inicios de Sesión", "Usuarios Activos", "Clientes Activos")]
    assert order == sorted(order)
    assert "de 5 usuarios de clientes registrados" in text or "usuarios de clientes registrados" in text
    assert ov.page_views == 10 and ov.logins == 3
    assert sum(r.page_views for r in ov.rows) == ov.page_views and sum(r.logins for r in ov.rows) == ov.logins
    assert "Equipo Interno" not in text
    assert "Una vista de página es la apertura de una página o pestaña. Seleccione un cliente para ver el detalle." in text


def test_overview_content_links_are_real_keep_filters_and_internal_row_is_last(store):
    ov, content, _ = _content(period="7", env="production", internal=True)
    links = [n for n in _walk(html.Div(content)) if isinstance(n, dcc.Link)]
    hrefs = {n.href for n in links}
    assert any("client=cda" in h and "period=7" in h and "env=production" in h for h in hrefs)
    assert any("client=internal" in h for h in hrefs)
    from dashboard.services_registry import relative_path
    assert all(h.startswith(relative_path("/admin/actividad-usuarios")) for h in hrefs)
    rows = [n for n in _walk(html.Div(content)) if isinstance(n, html.Tr)]
    last_row_text = repr(rows[-1])
    assert "Equipo Interno" in last_row_text and "client=internal" in last_row_text
    text = repr(content)
    assert "Clientes Activos" in text and "Última Actividad" in text and "Último Acceso" not in text
    assert "de 8 usuarios registrados" in text or "usuarios registrados" in text


def test_overview_toggle_is_a_labelled_radio_group_defaulting_to_page_views(store):
    _, content, _ = _content()
    nodes = list(_walk(html.Div(content)))
    radios = next(n for n in nodes if isinstance(n, dbc.RadioItems) and n.id == "ur-ov-metric")
    assert radios.value == "views"
    assert [(o["label"], o["value"]) for o in radios.options] == [("Vistas de Página", "views"), ("Inicios de Sesión", "logins")]
    group = next(n for n in nodes if isinstance(n, html.Div) and getattr(n, "role", None) == "radiogroup")
    assert group.to_plotly_json()["props"]["aria-label"]
    store_node = next(n for n in nodes if isinstance(n, dcc.Store) and n.id == "ur-ov-figs")
    assert set(store_node.data) == {"views", "logins"}
    assert "páginas o pestañas abiertas por día" in store_node.data["views"]["caption"]
    assert "inicios de sesión por día" in store_node.data["logins"]["caption"]
    _, logins_view, _ = _content(metric="logins")
    graph = next(n for n in _walk(html.Div(logins_view)) if isinstance(n, dcc.Graph) and n.id == "ur-ov-graph")
    assert "inicios de sesión" in graph.figure.data[0].hovertemplate


def test_pages_panel_counts_equal_the_kpi_and_unregistered_pages_show_their_path(store):
    ov, content, _ = _content()
    assert sum(p.views for p in ov.pages) == ov.page_views
    text = repr(content)
    assert "Páginas Más Visitadas" in text and "/not/in/registry" in text and "Alertas › Vista General" in text
    assert "usuarios" in text and "usuario" in text


def test_overview_footer_reports_hidden_internal_activity(store):
    storage = store
    _put(storage, build_event("admin", "internal", None, "production", moment=datetime.now(timezone.utc), event_id="a1"))
    _put(storage, build_page_view_event("admin", "internal", None, "production", "unregistered", "/admin", None,
                                        moment=datetime.now(timezone.utc), event_id="a2"))
    data_access.clear_cache()
    _, hidden, _ = _content(internal=False)
    assert "Excluye 1 inicios de sesión y 1 vistas de página de usuarios internos." in repr(hidden)
    _, shown, _ = _content(internal=True)
    assert "Excluye" not in repr(shown)


def test_detail_layout_unknown_client_and_internal(store):
    from dashboard.tabs.tab_user_registry import create_layout
    detail = create_layout(client="cda")
    ids = {getattr(n, "id", None) for n in _walk(detail)}
    assert {"ur-client", "ur-cd-content", "ur-back-link", "ur-cd-notice", "ur-cd-metric-state"} <= ids
    missing = create_layout(client="nope")
    texts = repr(missing)
    assert "Cliente no encontrado" in texts and "ur-cd-content" not in texts
    assert "Equipo Interno" in repr(create_layout(client="internal"))


def _detail(client="cda", metric="views"):
    from dashboard.callbacks.admin_callbacks import _context
    from dashboard.components import user_registry_views as v
    from src.auth_events import metrics as m

    registry, events, now, kind, resolved, _, capture = _context("30", None, None, "all")
    d = m.build_detail(events, registry, client, resolved, capture)
    filters = {"now": now, "nav": {"period": kind, "start": None, "end": None, "env": "all", "internal": False}}
    return d, v.detail_content(d, filters, metric), filters


def test_detail_content_blocks_columns_and_recent_activity(store):
    d, content, _ = _detail()
    text = repr(content)
    order = [text.index(label) for label in ("Vistas de Página", "Inicios de Sesión", "Usuarios Activos", "Última Actividad")]
    assert order == sorted(order)
    for expected in ("Actividad por Día", "Páginas Más Visitadas", "Usuarios del Cliente", "Días Activos",
                     "Último Inicio de Sesión", "Actividad por Día y Hora", "Actividad Reciente",
                     "Vistas de página por bloque de 2 horas · Hora local", "Ver Registro Completo"):
        assert expected in text, expected
    assert "cda_user · " in text                                    # last-activity caption: <username> · <detail>
    # every registered user of the client is listed, active or not
    registered = {u["username"] for u in data_access.get_registry().users_of_client("cda")}
    assert registered <= {u.username for u in d.users}
    table = next(n for n in _walk(html.Div(content)) if getattr(n, "id", None) == "ur-users-table")
    assert "Sin inicios de sesión" in repr(table)                    # a registered user who never logged in
    # recent activity: the 7 newest events of both types, chips carry the label
    assert "Mostrando 7 de 11 registros" in text
    assert "Página" in text and "Inicio de Sesión" in text
    heat = next(n for n in _walk(html.Div(content)) if getattr(n, "id", None) == "ur-heatmap")
    assert sum(int(c.children) for c in _walk(heat) if isinstance(c, html.Td) and c.children) == d.page_views == 9


def test_detail_chart_daily_totals_match_series(store):
    d, content, _ = _detail(metric="views")
    for series, total in ((d.series_views, d.page_views), (d.series_logins, d.logins)):
        assert sum(sum(counts) for _, counts in series) == total
    graph = next(n for n in _walk(html.Div(content)) if isinstance(n, dcc.Graph) and n.id == "ur-cd-graph")
    assert graph.figure.layout.legend.title.text == "Usuario" and graph.figure.layout.barmode == "stack"


def test_full_log_is_paginated_at_25_with_both_event_types(store):
    from dashboard.tabs.tab_user_registry import create_layout
    for i in range(20):
        _put(store, build_page_view_event("cda_user", "client", "cda", "production", "unregistered", "/extra", None,
                                          moment=datetime.now(timezone.utc) - timedelta(seconds=i), event_id=f"x{i}"))
    data_access.clear_cache()
    first = repr(create_layout(client="cda", view="log", page="1"))
    assert "Mostrando 1–25 de 31 registros" in first and "Página 1 de 2" in first and "Volver al Cliente" in first
    assert "Tipo" in first and "Detalle" in first and "Exportar" not in first
    assert "Mostrando 26–31 de 31 registros" in repr(create_layout(client="cda", view="log", page="2"))


def test_empty_period_shows_zeros_and_empty_messages(store):
    from dashboard.callbacks.admin_callbacks import _context
    from dashboard.components import user_registry_views as v
    from src.auth_events import metrics as m

    registry, events, now, kind, _, _, capture = _context("30", None, None, "all")
    period = m.Period((now - timedelta(days=400)).date(), (now - timedelta(days=380)).date())
    filters = {"now": now, "nav": {"period": kind, "start": None, "end": None, "env": "all", "internal": False}}
    ov = m.build_overview(events, registry, period, False, capture)
    text = repr(v.overview_content(ov, filters))
    assert ov.empty and "Sin vistas de página en el período" in text and "Sin actividad en el período" in repr(
        [n for n in _walk(html.Div(v.overview_content(ov, filters))) if isinstance(n, dcc.Graph)][0].figure.layout.annotations)
    d = m.build_detail(events, registry, "cda", period, capture)
    detail_text = repr(v.detail_content(d, {**filters, "now": now}))
    assert d.empty and detail_text.count("Sin actividad en el período") >= 2 and "Mostrando 0 de 0 registros" in detail_text


def test_capture_notice_lines(store):
    from dashboard.components import user_registry_views as v
    from src.auth_events import metrics as m
    from datetime import date
    period = m.Period(date(2026, 10, 1), date(2026, 10, 30))
    assert v.capture_notice_text(m.capture_notice(date(2026, 10, 15), period)) == "Las vistas de página se registran desde el 15 Oct 2026."
    assert v.capture_notice_text(m.capture_notice(None, period)) == "Aún no hay vistas de página registradas."
    assert v.capture_notice_text(m.capture_notice(date(2026, 9, 1), period)) == ""


def test_layout_without_storage_shows_error_not_crash(monkeypatch):
    monkeypatch.delenv("AUTH_EVENTS_LOCAL_DIR", raising=False)
    monkeypatch.delenv("BUCKET_NAME", raising=False)
    monkeypatch.setattr("src.auth_events.storage.load_dotenv", lambda *a, **k: None)
    reset_registry_cache()
    data_access.clear_cache()
    from dashboard.tabs.tab_user_registry import create_layout
    assert "No se pudo cargar" in repr(create_layout(client="cda"))


def test_page_is_admin_only_on_the_server(monkeypatch):
    import dash
    monkeypatch.setattr(dash, "register_page", lambda *a, **k: None)
    from dashboard.pages import admin_user_registry
    out = admin_user_registry.layout()          # no request/session: nobody is signed in
    assert "permisos" in repr(out)


def test_route_is_renamed_and_the_old_one_redirects_with_its_query(monkeypatch):
    import dash
    from dashboard.callbacks import access_control_callbacks
    from dashboard.services_registry import LEGACY_USER_ACTIVITY_PATH, NAV_PATHS

    assert NAV_PATHS["admin-user-registry"] == "/admin/actividad-usuarios"
    assert LEGACY_USER_ACTIVITY_PATH == "/admin/registro-usuarios"

    class FakeApp:
        callbacks = []

        def callback(self, *args, **kwargs):
            def register(fn):
                self.callbacks.append(fn)
                return fn
            return register

    app = FakeApp()
    access_control_callbacks.register_access_control_callbacks(app)
    guard = app.callbacks[0]
    monkeypatch.setattr(access_control_callbacks, "is_admin", lambda user_data: bool(user_data.get("admin")))
    monkeypatch.setattr(access_control_callbacks, "allowed_clients", lambda user_data: ["cda"])
    monkeypatch.setattr(dash, "strip_relative_path", lambda p: p.strip("/"))
    monkeypatch.setattr(dash, "get_relative_path", lambda p: p)
    # an admin hitting the old route lands on the new pathname (Location keeps `search`: ?client=cda survives)
    assert guard("/admin/registro-usuarios", {"admin": True, "username": "a"}, "cda") == "/admin/actividad-usuarios"
    from dash.exceptions import PreventUpdate
    with pytest.raises(PreventUpdate):
        guard("/admin/actividad-usuarios", {"admin": True, "username": "a"}, "cda")
    # a non-admin is bounced from both routes, never redirected into the admin page
    assert guard("/admin/registro-usuarios", {"admin": False, "username": "u"}, "cda") != "/admin/actividad-usuarios"


# --- language and narrow-screen labels ----------------------------------------------------------

def test_english_ui_keeps_es_cl_numbers_and_has_no_spanish_words_or_raw_keys(store):
    from src.auth_events import metrics as m
    from src.i18n import forced_language
    with forced_language("en"):
        ov, content, filters = _content(internal=False)
        text = repr(content)
        for expected in ("Page Views", "Logins", "Active Users", "Active Clients", "Last Activity", "Most Visited Pages",
                         "Activity by Day", "A page view is the opening of a page or tab."):
            assert expected in text, expected
        for spanish in ("Vistas de Página", "Inicios de Sesión", "Última Actividad", "Páginas Más Visitadas"):
            assert spanish not in text, spanish
        assert "user_registry." not in text
        assert m.relative_access(None, filters["now"], never=None) == "No access"
        assert m.change_vs_previous(3, 0).text == "New"
        from dashboard.components import user_registry_views as v
        assert v.capture_notice_text(("none", None)) == "No page views have been recorded yet."
        d, detail, _ = _detail()
        assert "user_registry." not in repr(detail) and "Last Login" in repr(detail) and "Recent Activity" in repr(detail)
    from datetime import date
    assert m.fmt_int(1450) == "1.450" and m.fmt_decimal(13.1) == "13,1"


def test_charts_ship_every_label_and_the_desktop_interval_for_thinning():
    from datetime import date
    from dashboard.components.user_registry_charts import create_daily_chart
    from src.auth_events import metrics as m
    daily = m.build_buckets(m.Period(date(2026, 10, 12), date(2026, 11, 10)))
    meta = create_daily_chart(daily, [1] * 30).layout.meta["urTicks"]
    assert meta["step"] == 5 and len(meta["vals"]) == len(meta["text"]) == 30 and meta["text"][-1] == "10 Nov"
    weekly = m.build_buckets(m.Period(date(2026, 1, 1), date(2026, 6, 30)))
    assert create_daily_chart(weekly, [1] * len(weekly)).layout.meta["urTicks"]["step"] >= 1
    assert (ROOT / "dashboard" / "assets" / "user_registry_axis.js").exists()


def test_daily_chart_tooltip_and_integer_axis_for_both_metrics():
    from datetime import date
    from dashboard.components.user_registry_charts import create_daily_chart
    from src.auth_events import metrics as m
    daily = m.build_buckets(m.Period(date(2026, 11, 1), date(2026, 11, 10)))
    views = create_daily_chart(daily, [0, 3, 1, 0, 0, 0, 2, 0, 0, 1], "views")
    logins = create_daily_chart(daily, [0, 3, 1, 0, 0, 0, 2, 0, 0, 1], "logins")
    assert views.data[0].hovertemplate == "%{x} · %{y} vistas de página<extra></extra>"
    assert logins.data[0].hovertemplate == "%{x} · %{y} inicios de sesión<extra></extra>"
    assert views.layout.yaxis.tickformat == "d" and views.data[0].x[0] == "Dom 1 Nov"
