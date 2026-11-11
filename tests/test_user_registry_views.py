"""TR-2 / TR-3 UI: layouts build from a store, links are real, palette is neutral, admin-only."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dash import dcc, html

from src.auth_events import data_access, settings
from src.auth_events.events import build_event, raw_key
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


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_EVENTS_LOCAL_DIR", str(tmp_path))
    storage = LocalStorage(tmp_path)
    storage.put(settings.REGISTRY_CLIENTS_KEY, (SEED / "clients.json").read_bytes())
    storage.put(settings.REGISTRY_USERS_KEY, (SEED / "users.json").read_bytes())
    for i, user in enumerate(("cda_user", "cda_user", "emin_user")):
        event = build_event(user, "client", user.split("_")[0], "production",
                            moment=datetime.now(timezone.utc), event_id=f"v{i}")
        storage.put(raw_key(event), json.dumps(event).encode())
    reset_registry_cache()
    data_access.clear_cache()
    yield storage
    reset_registry_cache()
    data_access.clear_cache()


def test_heatmap_levels_meet_text_contrast():
    levels = dict(re.findall(r"\.ur-heat-(\d) \{ background: (#[0-9a-f]{6}); color: (#[0-9a-f]{6});", CSS) and
                  [(m[0], (m[1], m[2])) for m in re.findall(r"\.ur-heat-(\d) \{ background: (#[0-9a-f]{6}); color: (#[0-9a-f]{6});", CSS)])
    assert len(levels) == 5
    for level, (background, text) in levels.items():
        assert _contrast(background, text) >= 4.5, level


def test_palette_has_no_severity_colors():
    forbidden = ("#dc2626", "#b91c1c", "#ef4444", "#f59e0b", "#16a34a", "#15803d", "#dcfce7", "#fee2e2", "#fef3c7")
    assert not [c for c in forbidden if c in CSS.lower()]
    from dashboard.components import user_registry_charts as charts
    assert not [c for c in forbidden if c in repr(vars(charts)).lower()]
    assert "border-left" not in CSS


def test_overview_layout_has_labelled_controls(store):
    from dashboard.tabs.tab_user_registry import create_layout
    layout = create_layout()
    nodes = list(_walk(layout))
    labels = {n.htmlFor for n in nodes if isinstance(n, html.Label)}
    assert {"ur-period", "ur-env"} <= labels
    ids = {getattr(n, "id", None) for n in nodes}
    assert {"ur-period", "ur-env", "ur-internal", "ur-ov-content"} <= ids
    defaults = {n.id: n.value for n in nodes if getattr(n, "id", None) in ("ur-period", "ur-env", "ur-internal")}
    assert defaults == {"ur-period": "30", "ur-env": "all", "ur-internal": False}


def test_overview_content_links_are_real_and_keep_filters(store):
    from dashboard.callbacks.admin_callbacks import _context
    from dashboard.components import user_registry_views as v
    from src.auth_events import metrics as m

    registry, events, now, kind, period, _ = _context("7", None, None, "production")
    ov = m.build_overview(events, registry, period, include_internal=True)
    content = v.overview_content(ov, {"now": now, "nav": {"period": kind, "start": None, "end": None, "env": "production", "internal": True}})
    links = [n for n in _walk(html.Div(content)) if isinstance(n, dcc.Link)]
    hrefs = {n.href for n in links}
    assert any("client=cda" in h and "period=7" in h and "env=production" in h for h in hrefs)
    assert any("client=internal" in h for h in hrefs)
    text = repr(content)
    assert "Equipo Interno" in text and "Clientes Activos" in text


def test_detail_and_unknown_client_layouts(store):
    from dashboard.tabs.tab_user_registry import create_layout
    detail = create_layout(client="cda")
    ids = {getattr(n, "id", None) for n in _walk(detail)}
    assert {"ur-client", "ur-cd-content", "ur-back-link"} <= ids
    missing = create_layout(client="nope")
    texts = repr(missing)
    assert "Cliente no encontrado" in texts and "ur-cd-content" not in texts
    assert "Equipo Interno" in repr(create_layout(client="internal"))


def test_full_log_is_paginated_newest_first(store):
    from dashboard.tabs.tab_user_registry import create_layout
    page = create_layout(client="cda", view="log", page="1")
    assert "Mostrando 1–2 de 2 registros" in repr(page)


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


# --- TR-A / TR-5: as-built amendments and narrow-screen labels ----------------------------------

def _overview_for(events_specs, include_internal=False):
    from datetime import date
    from src.auth_events import metrics as m
    from src.auth_events.data_access import _frame
    from src.auth_events.registry import parse_registry
    registry = parse_registry(
        b'[{"client_id":"cda","display_name":"CDA","active":true},{"client_id":"old","display_name":"Old","active":false}]',
        b'[{"username":"cda_user","user_type":"client","client_id":"cda"}]')
    events = [build_event(*spec[:4], moment=spec[4], event_id=f"x{i}") for i, spec in enumerate(events_specs)]
    frame = _frame(events, "America/Santiago")
    return m.build_overview(frame, registry, m.resolve_period("30", frame["date"].max()), include_internal)


def test_inactive_client_events_are_excluded_and_footnoted_only_when_present():
    from dashboard.components import user_registry_views as v
    now = datetime.now(timezone.utc)
    with_orphan = _overview_for([("cda_user", "client", "cda", "production", now),
                                 ("old_user", "client", "old", "production", now),
                                 ("ghost_user", "client", "nowhere", "production", now)])
    assert with_orphan.logins == 1 and with_orphan.orphan_client_logins == 2
    filters = {"now": now.astimezone(), "nav": {"period": "30", "env": "all", "internal": False}}
    assert "2 inicios de sesión de clientes inactivos" in repr(v.overview_content(with_orphan, filters))
    clean = _overview_for([("cda_user", "client", "cda", "production", now)])
    assert clean.orphan_client_logins == 0
    assert "inactivos" not in repr(v.overview_content(clean, filters))


def test_english_ui_keeps_es_cl_numbers_and_has_no_spanish_words():
    from datetime import date
    from dashboard.components import user_registry_views as v
    from src.auth_events import metrics as m
    from src.i18n import forced_language
    ov = m.Overview(period=m.Period(date(2026, 10, 12), date(2026, 11, 10)), include_internal=False,
                    logins=1450, previous_logins=1282, logins_change=m.change_vs_previous(1450, 1282),
                    registered_clients=5, registered_users=8, buckets=m.build_buckets(m.Period(date(2026, 10, 12), date(2026, 11, 10))),
                    chart_counts=[1] * 30)
    now = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)
    with forced_language("en"):
        text = repr(v.overview_content(ov, {"now": now, "nav": {}}))
        assert "1.450" in text and "▲ +13,1%" in text and "Client Logins" in text
        assert "Inicios de Sesión" not in text and "user_registry." not in text
        assert m.relative_access(None, now) == "No logins"
        assert m.change_vs_previous(3, 0).text == "New"
        assert m.relative_access(datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc), now) == "3 h ago"
    assert m.relative_access(datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc), now) == "Hace 3 h"


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
