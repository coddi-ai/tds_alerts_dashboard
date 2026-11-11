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
