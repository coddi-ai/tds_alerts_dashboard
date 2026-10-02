"""UI internationalization (Spanish / English).

Covers the catalogs (they must stay in step), the `t()` lookup (default language, fallback,
cookie-driven selection), the language selector wiring, and the static guarantee that every
translation key used in the code exists in the catalog.
"""

import ast
import json
import re
from pathlib import Path

import pytest
from flask import Flask

from src import i18n
from src.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_COOKIE,
    LANGUAGES,
    LazyLabels,
    current_language,
    js_messages,
    load_catalog,
    normalize_language,
    page_title,
    t,
    t_or,
)

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "src" / "i18n" / "locales"
PLACEHOLDER = re.compile(r"\{(\w+)")


def _request_in(language):
    """A Flask request context carrying the language cookie, as the browser would send it."""
    app = Flask(__name__)
    headers = {"Cookie": f"{LANGUAGE_COOKIE}={language}"} if language else {}
    return app.test_request_context("/", headers=headers)


# ── Catalogs ─────────────────────────────────────────────────────────────────

def test_catalogs_cover_the_same_keys():
    es, en = load_catalog("es"), load_catalog("en")
    assert set(es) == set(en), {
        "only_es": sorted(set(es) - set(en))[:10],
        "only_en": sorted(set(en) - set(es))[:10],
    }


def test_catalog_entries_are_never_empty():
    for language in LANGUAGES:
        empty = [key for key, text in load_catalog(language).items() if not str(text).strip() and str(text) != text]
        assert not empty
        assert all(isinstance(text, str) and text != "" for text in load_catalog(language).values())


def test_translations_keep_the_same_placeholders():
    es, en = load_catalog("es"), load_catalog("en")
    mismatched = {
        key: (PLACEHOLDER.findall(es[key].replace("{{", "")), PLACEHOLDER.findall(en[key].replace("{{", "")))
        for key in es
        if sorted(PLACEHOLDER.findall(es[key].replace("{{", ""))) != sorted(PLACEHOLDER.findall(en[key].replace("{{", "")))
    }
    assert not mismatched


def test_translations_keep_the_same_surrounding_whitespace():
    """Fragments such as "Total: " or " Normal" sit next to icons/values, so a translation that
    loses (or gains) the edge space glues words together on screen."""
    es, en = load_catalog("es"), load_catalog("en")
    bad = {
        key: (es[key], en[key])
        for key in es
        if es[key][: len(es[key]) - len(es[key].lstrip())] != en[key][: len(en[key]) - len(en[key].lstrip())]
        or es[key][len(es[key].rstrip()):] != en[key][len(en[key].rstrip()):]
    }
    assert not bad, dict(list(bad.items())[:10])


def test_catalog_files_are_flat_sorted_json():
    for language in LANGUAGES:
        raw = json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))
        assert list(raw) == sorted(raw)
        assert all(isinstance(value, str) for value in raw.values())


def _translation_keys_used_in_code():
    """Every constant first argument of t()/t_or()/page_title() in the UI code."""
    names = {"t", "_t", "t_or", "_t_or", "page_title"}
    used = {}
    for folder in ("dashboard", "src", "config"):
        for path in (ROOT / folder).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - reported by the import tests
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in names
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    used.setdefault(node.args[0].value, f"{path.relative_to(ROOT)}:{node.lineno}")
    return used


def test_every_translation_key_used_in_code_exists():
    catalog = load_catalog("es")
    used = _translation_keys_used_in_code()
    # `t_or("x", default)` deliberately tolerates a missing key; everything else must exist.
    optional = set()
    for folder in ("dashboard", "src", "config"):
        for path in (ROOT / folder).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in {"t_or", "_t_or"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    optional.add(node.args[0].value)
    missing = {key: where for key, where in used.items() if key not in catalog and key not in optional}
    assert not missing, dict(list(missing.items())[:15])


def test_every_call_supplies_the_placeholders_its_text_needs():
    """`t("key", a=1)` must pass every `{name}` the catalog text contains; a miss would
    render the raw placeholder to the user instead of raising."""
    catalog = load_catalog("es")
    problems = {}
    for folder in ("dashboard", "src", "config"):
        for path in (ROOT / folder).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in {"t", "_t"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    continue
                key = node.args[0].value
                # Without params the text is returned verbatim (e.g. Plotly's "%{x}"), so only
                # calls that format are checked.
                if key not in catalog or not node.keywords or any(kw.arg is None for kw in node.keywords):
                    continue
                needed = set(PLACEHOLDER.findall(catalog[key].replace("{{", "")))
                given = {kw.arg for kw in node.keywords}
                if needed - given:
                    problems[f"{path.relative_to(ROOT)}:{node.lineno}"] = (key, sorted(needed - given))
    assert not problems, dict(list(problems.items())[:10])


def test_js_message_keys_exist_in_both_languages():
    for language in LANGUAGES:
        assert js_messages(language), "the browser needs at least the Campbell AI status strings"
    assert set(js_messages("es")) == set(js_messages("en"))


# ── Lookup ───────────────────────────────────────────────────────────────────

def test_outside_a_request_the_language_is_spanish():
    assert current_language() == DEFAULT_LANGUAGE == "es"
    assert t("nav.logout") == "Cerrar Sesión"


def test_no_cookie_defaults_to_spanish():
    with _request_in(None):
        assert current_language() == "es"
        assert t("nav.logout") == "Cerrar Sesión"


@pytest.mark.parametrize(
    "cookie,expected",
    [("es", "Cerrar Sesión"), ("en", "Sign Out"), ("EN", "Sign Out"), ("fr", "Cerrar Sesión"), ("", "Cerrar Sesión")],
)
def test_cookie_selects_the_language(cookie, expected):
    with _request_in(cookie):
        assert t("nav.logout") == expected


def test_normalize_language_never_returns_an_unsupported_code():
    assert normalize_language(None) == "es"
    assert normalize_language("en-US") == "en"
    assert normalize_language("pt") == "es"


def test_missing_english_key_falls_back_to_spanish(monkeypatch):
    original = i18n.load_catalog

    def only_spanish_has_it(language):
        catalog = dict(original(language))
        if language == "en":
            catalog.pop("nav.logout", None)
        return catalog

    monkeypatch.setattr(i18n, "load_catalog", only_spanish_has_it)
    with _request_in("en"):
        assert i18n.t("nav.logout") == "Cerrar Sesión"


def test_missing_everywhere_returns_the_key_not_blank_text():
    with _request_in("en"):
        assert t("definitely.not.a.key") == "definitely.not.a.key"


def test_placeholders_are_filled_and_text_without_params_is_verbatim():
    with _request_in("en"):
        assert t("placeholder.working_on", section="Oil") == "We are working on the Oil section."
    assert t("placeholder.working_on", section="Aceite") == "Estamos trabajando en la sección Aceite."
    # A literal brace in an entry that takes no params must not be treated as a placeholder:
    # Plotly hover templates such as "%{x}" go through t() unformatted.
    es = load_catalog("es")
    key = next(k for k, v in es.items() if "%{x}" in v and "{{" not in v and not PLACEHOLDER.findall(v.replace("%{", "")))
    assert t(key) == es[key]


def test_t_or_uses_the_default_for_unknown_keys_only():
    assert t_or("definitely.not.a.key", "fallback") == "fallback"
    with _request_in("en"):
        assert t_or("nav.logout", "fallback") == "Sign Out"


def test_page_title_is_evaluated_per_request():
    title = page_title("page.title.monitoring_oil")
    assert title() == "Aceite | Multi-Technical Alerts"
    with _request_in("en"):
        assert title() == "Oil | Multi-Technical Alerts"
        assert title(unit_id="T_1") == "Oil | Multi-Technical Alerts"


def test_lazy_labels_follow_the_request_language():
    labels = LazyLabels({"a": "status.alert", "b": "status.abnormal"})
    assert labels["a"] == "Alerta" and dict(labels) == {"a": "Alerta", "b": "Anormal"}
    with _request_in("en"):
        assert labels["a"] == "Alert" and labels.get("b") == "Abnormal"
        assert labels.get("zzz", "-") == "-"


def test_domain_helpers_translate_for_display_only():
    from dashboard.components.labels import localize_elapsed, status_label, translate_component_label

    assert status_label("Alerta") == "Alerta"
    assert status_label("algo desconocido") == "algo desconocido"
    assert localize_elapsed("3 días") == "3 días"
    with _request_in("en"):
        assert status_label("Anormal") == "Abnormal"
        assert status_label("algo desconocido") == "algo desconocido"
        assert status_label(None) == ""
        assert localize_elapsed("3 días") == "3 days"
        assert localize_elapsed("1 día") == "1 day"
        assert localize_elapsed("5h 2m") == "5h 2m"
        assert translate_component_label("engine") == "Engine"
        # Unknown component values are data, not UI text: never "translated".
        assert translate_component_label("some_custom_part") == "Some Custom Part"


def test_nav_labels_exist_for_every_registered_service():
    from dashboard.services_registry import NAV_PATHS, SERVICE_LABELS, SERVICE_SECTIONS

    es = load_catalog("es")
    for service_id, label in SERVICE_LABELS.items():
        assert es[f"nav.service.{service_id}"] == label, service_id
    for section in SERVICE_SECTIONS:
        assert es[f"nav.section.{section['section']}"] == section["label"]
    for nav_id in NAV_PATHS:
        assert f"nav.service.{nav_id}" in es, nav_id


# ── Language selector ────────────────────────────────────────────────────────

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


def _selector(component):
    return next(
        (item for item in _walk(component) if getattr(item, "id", None) == "language-selector"), None
    )


def test_selector_lists_both_languages_in_their_own_name():
    from dashboard.components.language_selector import create_language_selector

    selector = _selector(create_language_selector())
    assert [(o["value"], o["label"]) for o in selector.options] == [("es", "Español"), ("en", "English")]
    assert selector.value == "es" and selector.clearable is False
    with _request_in("en"):
        assert _selector(create_language_selector()).value == "en"


def test_selector_is_in_the_top_bar_and_on_the_login_page():
    from dashboard.layout import create_login_page, create_navbar

    assert _selector(create_login_page()) is not None
    navbar = create_navbar({"username": "u", "role": "admin", "clients": ["CDA"]}, ["CDA"])
    assert _selector(navbar) is not None


def test_switching_language_does_not_change_any_navigation_target():
    import dashboard.app  # noqa: F401  (initialises Dash, which `dash.get_relative_path` needs)
    from dashboard.layout import build_menu_items, build_navigation_items

    user = {"username": "u", "role": "admin", "clients": ["CDA"]}

    def hrefs():
        return [item.href for item in build_menu_items(build_navigation_items("CDA", user)) if hasattr(item, "href")]

    spanish = hrefs()
    with _request_in("en"):
        assert hrefs() == spanish


def test_navbar_and_login_render_in_the_selected_language():
    from dashboard.layout import create_login_page, create_navbar

    def texts(component):
        out = []
        for item in _walk(component):
            if isinstance(item, str):
                out.append(item)
            elif isinstance(getattr(item, "placeholder", None), str):
                out.append(item.placeholder)
        return " | ".join(out)

    user = {"username": "u", "role": "admin", "clients": ["CDA"]}
    spanish = texts(create_login_page()) + texts(create_navbar(user, ["CDA"]))
    assert "Iniciar Sesión" in spanish and "Cerrar Sesión" in spanish
    with _request_in("en"):
        english = texts(create_login_page()) + texts(create_navbar(user, ["CDA"]))
    assert "Sign In" in english and "Sign Out" in english
    assert "Iniciar Sesión" not in english and "Cerrar Sesión" not in english


# ── Browser-side pieces ──────────────────────────────────────────────────────

def test_language_script_persists_in_a_cookie_and_reloads():
    script = (ROOT / "dashboard" / "assets" / "i18n_language.js").read_text(encoding="utf-8")
    assert f'var COOKIE = "{LANGUAGE_COOKIE}"' in script
    assert "max-age" in script and "window.location.reload()" in script
    assert 'DEFAULT = "es"' in script
    # `t` merges onto what /_i18n/messages.js already put on window.appI18n.
    assert "Object.assign(window.appI18n || {}" in script


def test_messages_script_is_served_in_the_cookie_language():
    from dashboard.app import app

    client = app.server.test_client()
    spanish = client.get("/_i18n/messages.js")
    assert spanish.status_code == 200 and spanish.mimetype == "application/javascript"
    assert '"es"' in spanish.get_data(as_text=True)
    client.set_cookie(LANGUAGE_COOKIE, "en")
    english = client.get("/_i18n/messages.js").get_data(as_text=True)
    assert 'window.appI18n.language = "en"' in english
    assert "Thinking" in english and "Pensando" not in english


def test_the_layout_endpoint_renders_in_the_cookie_language():
    from dashboard.app import app

    client = app.server.test_client()
    client.set_cookie(LANGUAGE_COOKIE, "en")
    body = client.get("/_dash-layout").get_data(as_text=True)
    assert "Sign In" in body and "language-selector" in body
