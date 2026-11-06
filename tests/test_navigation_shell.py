"""Top bar (client logo/selector, product lockup, account) and sidebar (icons, sections, active link, rail)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dashboard import layout
from dashboard.layout import (
    build_menu_items,
    build_navigation_items,
    create_navbar,
)
from dashboard.services_registry import (
    NAV_ICONS,
    NAV_PATHS,
    SERVICE_SECTIONS,
    nav_id_for_pathname,
)

ASSETS = Path(__file__).resolve().parents[1] / "dashboard" / "assets"

ADMIN = {"username": "admin", "role": "admin", "clients": ["CDA", "EMIN"]}
CLIENT = {"username": "someone", "role": "client", "clients": ["CDA"]}


def _walk(component, ancestors=()):
    """Yield (component, ancestors) over a Dash tree, `children` only."""
    yield component, ancestors
    if isinstance(component, str):
        return
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child, ancestors + (component,))
    elif children is not None:
        yield from _walk(children, ancestors + (component,))


def _by_id(tree, component_id):
    return next(((c, a) for c, a in _walk(tree) if getattr(c, "id", None) == component_id), (None, ()))


def _classes(component) -> str:
    return str(getattr(component, "className", "") or "") + " " + str(getattr(component, "class_name", "") or "")


@pytest.fixture
def full_nav(monkeypatch):
    """Every service enabled, so the menu holds all 15 links; links resolve without a Dash app."""
    monkeypatch.setattr(layout, "is_service_enabled", lambda client, service: True)
    monkeypatch.setattr(layout, "_campbell_ai_enabled", lambda: True)
    monkeypatch.setattr(layout, "troubleshooting_agent_configured", lambda: True)
    monkeypatch.setattr(layout.dash, "get_relative_path", lambda path: path)
    return build_navigation_items("CDA", ADMIN)


# ── Top bar: client identity ─────────────────────────────────────────────────

def _brand(navbar):
    return next(c for c, _ in _walk(navbar) if "topbar-brand" in _classes(c).split())


def test_client_logo_sits_on_the_left_next_to_the_platform_mark_with_a_divider():
    for user in (ADMIN, CLIENT):  # every role sees it
        navbar = create_navbar(user, user["clients"])
        brand = _brand(navbar)
        row = next(c for c, _ in _walk(brand) if "d-flex" in _classes(c).split())
        order = [
            "mark" if "topbar-brand-logo" in _classes(c)
            else "divider" if "topbar-brand-divider" in _classes(c)
            else "logo" if getattr(c, "id", None) == "client-logo"
            else "text" if "topbar-brand-text" in _classes(c)
            else "?"
            for c in row.children
        ]
        assert order == ["mark", "divider", "logo", "text"]
        assert _by_id(brand, "client-logo-img")[0] is not None
        # ...and no longer on the right with the controls.
        switcher = next(c for c, _ in _walk(navbar) if "topbar-client" in _classes(c).split())
        assert _by_id(switcher, "client-logo")[0] is None


def test_client_logo_is_a_read_only_display():
    navbar = create_navbar(CLIENT, ["CDA"])
    wrap, _ = _by_id(navbar, "client-logo")
    assert type(wrap).__name__ == "Div"
    for component, _ in _walk(wrap):
        assert type(component).__name__ not in {"A", "Button", "Link", "NavLink"}
        assert getattr(component, "n_clicks", None) is None and getattr(component, "href", None) is None


def test_logo_has_an_initials_placeholder_for_missing_assets():
    navbar = create_navbar(CLIENT, ["CAPSTONE"])
    placeholder, _ = _by_id(navbar, "client-logo-placeholder")
    assert placeholder.children == "CAP"
    css = (ASSETS / "custom_layout.css").read_text(encoding="utf-8")
    assert 'topbar-client-logo-wrap[data-logo-state="fallback"] .topbar-client-logo-placeholder' in css
    assert 'data-logo-state="fallback"] #client-logo-img' in css
    js = (ASSETS / "client_logo_handler.js").read_text(encoding="utf-8")
    assert "addEventListener('error'" in js and "addEventListener('load'" in js and "data-logo-state" in js


def test_logo_callback_follows_the_selector_with_image_and_placeholder():
    import dash

    from dashboard.callbacks.navigation_callbacks import register_navigation_callbacks

    captured = {}

    class _App:
        def callback(self, outputs, inputs, **kwargs):
            captured["outputs"], captured["inputs"] = outputs, inputs
            return lambda fn: captured.setdefault("fn", fn) or fn

    register_navigation_callbacks(_App())
    assert [o.component_id for o in captured["outputs"]] == ["client-logo-img"] * 4 + ["client-logo-placeholder"]
    assert [i.component_id for i in captured["inputs"]] == ["client-selector"]

    src, style, class_name, alt, mark = captured["fn"]("EMIN")
    assert src.endswith("/emin.png") and style["display"] == "block" and "client-logo-emin" in class_name
    assert alt == "EMIN" and mark == "EMI"
    assert captured["fn"]("ENEX")[0].endswith("/enex.png")  # a switch is just the next call: no extra state
    assert captured["fn"](None) == ("", {"display": "none"}, "topbar-client-logo", "", "")


def test_admin_sees_the_client_selector_with_a_building_icon():
    navbar = create_navbar(ADMIN, ["CDA", "EMIN"])
    selector, ancestors = _by_id(navbar, "client-selector")
    assert selector is not None and [o["value"] for o in selector.options] == ["CDA", "EMIN"]
    assert not any(getattr(a, "hidden", False) for a in ancestors)
    icons = [_classes(c) for c, _ in _walk(navbar) if "topbar-client-icon" in _classes(c)]
    assert icons and all("fa-building" in c for c in icons)
    assert not any("fa-desktop" in _classes(c) or "fa-tv" in _classes(c) for c, _ in _walk(navbar))


def test_non_admin_does_not_get_a_visible_selector():
    navbar = create_navbar(CLIENT, ["CDA"])
    selector, ancestors = _by_id(navbar, "client-selector")
    # Still in the tree (page callbacks read it as the client context) but hidden by the server...
    assert selector is not None and selector.value == "CDA"
    assert any(getattr(a, "hidden", False) for a in ancestors)
    # ...with no switching UI and nothing persisted client-side.
    assert selector.persistence is False
    assert not any("fa-building" in _classes(c) for c, _ in _walk(navbar))
    assert not any("topbar-client-label" in _classes(c) for c, _ in _walk(navbar))


# ── Top bar: product name lockup ─────────────────────────────────────────────

def _contrast(foreground: str, background: str = "#1a252f") -> float:
    def luminance(hex_color: str) -> float:
        channels = [int(hex_color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    hi, lo = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_product_name_block_is_one_plain_title_over_a_readable_tagline():
    from src.i18n import t

    brand = _brand(create_navbar(ADMIN, ["CDA"]))
    title = next(c for c, _ in _walk(brand) if "topbar-brand-title" in _classes(c))
    tagline = next(c for c, _ in _walk(brand) if "topbar-brand-tagline" in _classes(c))
    # No repeated "CODDI" (the mark carries it); a single text node, not a multi-style lockup.
    assert title.children == "ASSET HEALTH" == t("app.product_name")
    assert "CODDI" not in " ".join(c for c, _ in _walk(brand) if isinstance(c, str))
    assert tagline.children == t("app.platform_subtitle")
    # The login page keeps the full product title.
    assert t("app.platform_title") == "CODDI ASSET HEALTH"

    css = (ASSETS / "custom_layout.css").read_text(encoding="utf-8")

    def rule(selector):
        return re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css).group(1)

    title_css, tagline_css = rule(".topbar-brand-title"), rule(".topbar-brand-tagline")
    assert "font-weight: 400" in title_css and "font-family: inherit" in title_css
    title_color = re.search(r"color: (#[0-9a-f]{6}|#fff)", title_css).group(1)
    tagline_color = re.search(r"color: (#[0-9a-f]{6})", tagline_css).group(1)
    assert _contrast("#ffffff" if title_color == "#fff" else title_color) >= 4.5
    assert _contrast(tagline_color) >= 4.5
    # Larger than the previous 0.65rem tagline, yet secondary to the title.
    assert 0.65 < float(re.search(r"font-size: ([\d.]+)rem", tagline_css).group(1)) < float(
        re.search(r"font-size: ([\d.]+)rem", title_css).group(1)
    )
    assert "text-transform: uppercase" in tagline_css and "text-overflow: ellipsis" in tagline_css
    assert "white-space: nowrap" in title_css and "white-space: nowrap" in tagline_css


# ── Top bar: account ─────────────────────────────────────────────────────────

def test_account_is_a_plain_display_plus_a_direct_logout_button():
    navbar = create_navbar(ADMIN, ["CDA"])
    assert not any(type(c).__name__ in {"DropdownMenu", "DropdownMenuItem"} for c, _ in _walk(navbar))

    display, _ = next((c, a) for c, a in _walk(navbar) if "user-display" in _classes(c).split())
    text = " ".join(c for c, _ in _walk(display) if isinstance(c, str))
    assert ADMIN["username"] in text and "Admin" in text
    for component, _ in _walk(display):  # not a button, link or trigger
        assert type(component).__name__ not in {"A", "Button", "Link"}
        assert getattr(component, "n_clicks", None) is None

    logout, ancestors = _by_id(navbar, "logout-button")
    assert type(logout).__name__ == "Button" and logout.n_clicks == 0
    # Always visible: not nested in anything that hides it, and a sibling of the display.
    assert not any(getattr(a, "hidden", False) for a in ancestors)
    assert display in ancestors[-1].children and logout in ancestors[-1].children


def test_logout_button_is_neutral_not_a_danger_action():
    navbar = create_navbar(ADMIN, ["CDA"])
    logout, _ = _by_id(navbar, "logout-button")
    assert logout.color == "outline-light"  # same family as the bar's other controls
    assert "danger" not in _classes(logout)
    css = (ASSETS / "custom_layout.css").read_text(encoding="utf-8")
    start = css.rindex("/*", 0, css.index("Account: a plain display"))
    account_css = re.sub(r"/\*.*?\*/", "", css[start:css.index("/* Alert detail selector")], flags=re.S)
    assert not re.search(r"(?i)\bred\b|danger|#(dc|e7|c0|b9)[0-9a-f]{4}|#d9534f", account_css)


# ── Sidebar: icons ───────────────────────────────────────────────────────────

def test_every_section_and_link_has_its_own_icon(full_nav):
    sections = {s["section"]: s["icon"] for s in full_nav}
    links = {sub["id"]: sub["icon"] for s in full_nav for sub in s["subsections"]}

    assert list(sections) == ["overview", "monitoring", "predictive", "agents", "integration", "reporting", "admin"]
    assert len(set(sections.values())) == len(sections) == 7
    assert len(links) == 15 and set(links) == set(NAV_PATHS)
    assert len(set(links.values())) == 15
    # A link never reuses a section's icon either, so the rail and the flyout read apart.
    assert not set(sections.values()) & set(links.values())
    assert all(icon for icon in [*sections.values(), *links.values()])
    assert set(NAV_ICONS) == set(NAV_PATHS)


# ── Sidebar: sections, active link, rail markup ──────────────────────────────

def _links(menu):
    return [c for item in menu for c, _ in _walk(item) if type(c).__name__ == "NavLink"]


def test_each_section_is_a_header_button_over_its_own_links(full_nav):
    menu = build_menu_items(full_nav)
    assert len(menu) == 7
    for section, node in zip(full_nav, menu):
        header, panel = node.children
        assert type(header).__name__ == "Button" and header.type == "button"
        assert getattr(header, "data-section") == section["section"] == getattr(node, "data-section")
        assert getattr(header, "aria-expanded") == "true"  # all expanded on load
        assert getattr(header, "aria-controls") == panel.id
        assert len(_links([panel])) == len(section["subsections"])


@pytest.mark.parametrize("nav_id", sorted(NAV_PATHS))
def test_each_page_activates_exactly_its_own_link(full_nav, nav_id):
    menu = build_menu_items(full_nav, nav_id_for_pathname(NAV_PATHS[nav_id]))
    active = [link for link in _links(menu) if link.active]
    assert [link.href for link in active] == [NAV_PATHS[nav_id]]
    # The rail icon of the section that holds it is the only one tinted.
    tinted = [n for n in menu if "nav-section--active" in _classes(n)]
    assert len(tinted) == 1 and any(link.active for link in _links([tinted[0]]))


@pytest.mark.parametrize(
    "pathname, expected",
    [
        ("/overview/unit/CA-83", "overview-general"),  # drill-down: keeps its parent view lit
        ("/overview/unit/CA%2083", "overview-general"),
        ("/predictive/motor/", "predictive-motor"),
        ("/sin-servicios", None),
        ("/", None),
        (None, None),
    ],
)
def test_pages_outside_the_sidebar_resolve_sensibly(pathname, expected):
    assert nav_id_for_pathname(pathname) == expected


def test_no_link_is_active_without_a_matching_page(full_nav):
    menu = build_menu_items(full_nav, None)
    assert not [link for link in _links(menu) if link.active]
    assert not [n for n in menu if "nav-section--active" in _classes(n)]


# ── Sidebar: the browser-side pieces the markup depends on ───────────────────

def test_sidebar_script_covers_sections_rail_and_flyouts():
    js = (ASSETS / "sidebar_nav.js").read_text(encoding="utf-8")
    # Per-section, independent state; session-only (no storage) until persistence is decided.
    assert "collapsedSections" in js and "new Set()" in js
    assert "localStorage" not in js and "sessionStorage" not in js
    # One flyout at a time, closed by a link, an outside click and Escape; the rail is never toggled.
    assert "openFlyout" in js and "'Escape'" in js and ".nav-menu-item" in js
    assert not re.search(r"classList\.(add|remove|toggle)\(['\"]sidebar-collapsed", js)


def test_rail_css_shows_icons_only_and_a_flyout_per_section():
    css = (ASSETS / "custom_layout.css").read_text(encoding="utf-8")
    assert "#dashboard-shell.sidebar-collapsed #app-sidebar" in css and "width: 68px" in css
    rail = css[css.index("Collapsed state: the sidebar becomes"):css.index("Floating toggle button")]
    assert ".nav-section-label" in rail and ".nav-section--active" in rail
    assert "position: fixed" in rail  # the flyout
    # The master toggle stays reachable in both states and clears the rail's edge.
    assert "#dashboard-shell.sidebar-collapsed .sidebar-toggle-btn" in css


# ── Server-side client authorization ─────────────────────────────────────────

def test_allowed_clients_come_from_the_registry_not_from_the_browser():
    from flask import Flask, session

    from config.users import USERS
    from dashboard.auth import allowed_clients

    client_user = next(n for n, u in USERS.items() if u.get("role") != "admin" and len(u.get("clients", [])) == 1)
    app = Flask(__name__)
    app.secret_key = "test-secret-key-with-enough-entropy"
    with app.test_request_context("/"):
        assert allowed_clients({"username": client_user}) == []  # no session, no proof
        session["dashboard_user"] = client_user
        tampered = {"username": client_user, "role": "admin", "clients": ["CDA", "EMIN", "ENEX"]}
        assert allowed_clients(tampered) == USERS[client_user]["clients"]
