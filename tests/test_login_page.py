"""Login page: split card with hero image, welcome text per language, auth ids untouched."""

from __future__ import annotations

import re
from pathlib import Path

from config.settings import APP_VERSION
from dashboard.layout import create_login_page
from src.i18n import load_catalog

ASSETS = Path(__file__).resolve().parents[1] / "dashboard" / "assets"


def _walk(component):
    yield component
    if isinstance(component, str):
        return
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None:
        yield from _walk(children)


def _classes(component) -> str:
    return str(getattr(component, "className", "") or "")


def _find(component, cls):
    return next(c for c in _walk(component) if cls in _classes(c).split())


def test_authentication_ids_are_unchanged():
    ids = {getattr(c, "id", None) for c in _walk(create_login_page())}
    assert {"username-input", "password-input", "login-button", "login-alert", "login-spinner", "language-selector"} <= ids


def test_card_is_a_hero_image_beside_the_form_panel():
    page = create_login_page()
    card = _find(page, "login-card")
    hero, panel = card.children
    assert "login-hero" in _classes(hero) and "login-panel" in _classes(panel)
    img = hero.children
    assert img.src.endswith("login_image.png") and img.alt == ""  # decorative
    # Branding and language selector share the header row; welcome text and form follow.
    header, body = panel.children
    brand, lang = header.children
    assert "login-brand" in _classes(brand) and "login-lang" in _classes(lang)
    assert any(getattr(c, "id", None) == "language-selector" for c in _walk(lang))
    assert "login-form-area" in _classes(body)
    assert [type(c).__name__ for c in body.children[:2]] == ["H1", "P"]


def test_version_label_is_on_the_page():
    label = _find(create_login_page(), "login-version")
    assert label.children == f"v{APP_VERSION}"


def test_branding_uses_the_product_name_and_subtitle():
    from src.i18n import t

    brand = _find(create_login_page(), "login-brand")
    texts = [c for c in _walk(brand) if isinstance(c, str)]
    assert t("app.product_name") in texts and t("app.platform_subtitle") in texts
    assert "CODDI ASSET HEALTH" not in texts
    assert any(getattr(c, "alt", None) == "CODDI" for c in _walk(brand))


def test_welcome_text_is_translated_in_every_language():
    expected = {
        "es": ("Bienvenid@ de vuelta", "Tecnología que impulsa la industria minera hacia el futuro"),
        "en": ("Welcome back", "Technology driving the mining industry into the future"),
    }
    for language, (heading, tagline) in expected.items():
        catalog = load_catalog(language)
        assert catalog["login.welcome_title"] == heading
        assert catalog["login.welcome_tagline"] == tagline


def test_assets_exist_and_css_implements_the_layout():
    assert (ASSETS / "login_image.png").stat().st_size > 0
    waves = (ASSETS / "login_waves.svg").read_text(encoding="utf-8")
    assert "<svg" in waves and "<path" in waves

    css = (ASSETS / "login.css").read_text(encoding="utf-8")
    assert "11fr 9fr" in css  # ~55 / 45
    assert "object-fit: cover" in css
    assert 'url("login_waves.svg")' in css
    assert not re.search(r"#00173b", css, re.I)  # the old flat navy is gone
    # Under the tablet breakpoint the hero goes and the form panel fills the card.
    mobile = css[css.index("@media (max-width: 991px)"):]
    assert re.search(r"\.login-hero\s*\{\s*display: none;", mobile)
    assert "grid-template-columns: 1fr" in mobile
