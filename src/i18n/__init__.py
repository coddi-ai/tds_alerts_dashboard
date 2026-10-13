"""
UI internationalization (Spanish / English).

Every static UI string lives in a catalog (`locales/es.json`, `locales/en.json`)
and is rendered through `t("some.key")`. Spanish is the source and the fallback
language: a key missing in English renders its Spanish text, and a key missing
everywhere renders the key itself, so a gap is visible instead of blank.

The language is chosen per request from the `app_language` cookie, which the
language selector in the top bar writes (see dashboard/assets/i18n_language.js).
The cookie, not a Dash store, is what makes the choice reach the server: the
whole UI is built server-side - layouts and callback outputs alike - so `t()`
has to be able to read the language from inside any of them. Outside a request
(tests, scripts, import time) `t()` returns Spanish, which is the unchanged
pre-i18n behaviour.

Only static interface text goes through here. Data, database values, and
anything the backend or an LLM produces is never translated.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Dict

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "es"
LANGUAGE_COOKIE = "app_language"

# code -> the language's own name. Each language is always listed in itself, so a
# user who landed on the wrong one can still read the way back.
LANGUAGES: Dict[str, str] = {"es": "Español", "en": "English"}

_LOCALES_DIR = Path(__file__).parent / "locales"
_reported_missing: set = set()


@lru_cache(maxsize=None)
def load_catalog(language: str) -> Dict[str, str]:
    """Load one language's flat `key -> text` catalog (cached for the process)."""
    path = _LOCALES_DIR / f"{language}.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def normalize_language(value) -> str:
    """Map anything (a cookie value, None, garbage) onto a supported language code."""
    code = str(value or "").strip().lower()[:2]
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def current_language() -> str:
    """Language of the request being served; Spanish when there is no request."""
    try:
        from flask import has_request_context, request
    except ImportError:  # pragma: no cover - flask always ships with dash
        return DEFAULT_LANGUAGE
    if not has_request_context():
        return DEFAULT_LANGUAGE
    return normalize_language(request.cookies.get(LANGUAGE_COOKIE))


def t(key: str, **params) -> str:
    """Translate `key` into the current language.

    `params` fill `{name}` placeholders (str.format). Without params the text is
    returned verbatim, so a literal brace in a catalog entry needs no escaping.
    """
    language = current_language()
    text = load_catalog(language).get(key)
    if text is None and language != DEFAULT_LANGUAGE:
        text = load_catalog(DEFAULT_LANGUAGE).get(key)
    if text is None:
        if key not in _reported_missing:
            _reported_missing.add(key)
            logger.warning("Missing translation key: %s", key)
        return key
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        logger.warning("Bad placeholders for translation key %s (params=%s)", key, sorted(params))
        return text


JS_KEY_PREFIX = "js."


def js_messages(language: str | None = None) -> Dict[str, str]:
    """Catalog entries the browser needs for clientside callbacks (keys under `js.`).

    The JS runs in the page and cannot call `t()`, so these are served as a small script
    (see dashboard/app.py `/_i18n/messages.js`) and read through `window.appI18n.t`.
    """
    language = normalize_language(language) if language else current_language()
    messages = {k: v for k, v in load_catalog(DEFAULT_LANGUAGE).items() if k.startswith(JS_KEY_PREFIX)}
    if language != DEFAULT_LANGUAGE:
        messages.update({k: v for k, v in load_catalog(language).items() if k.startswith(JS_KEY_PREFIX)})
    return messages


VOCAB_PREFIX = "vocab."


def vocab(text):
    """Translate a piece of static *domain vocabulary* by its exact Spanish text.

    Failure-mode names, oil-variable labels and signal descriptions are defined once, in
    Spanish, in shared catalogs that other consumers (Campbell AI's backend) read as-is. They
    are translated here at display time, keyed by the Spanish text itself
    (`vocab.<text>`), so no consumer has to know which table a label came from. Text that has
    no entry - including anything that came from data - is returned unchanged.
    """
    if not isinstance(text, str) or not text:
        return text
    key = VOCAB_PREFIX + text
    if current_language() != DEFAULT_LANGUAGE:
        translated = load_catalog(current_language()).get(key)
        if translated is not None:
            return translated
    return text


class VocabMapping(Mapping):
    """Read-only view of a `{key: spanish label}` table whose values are `vocab()`-translated
    on every access. Used for module-level label tables that cannot call `t()` at import time."""

    def __init__(self, data):
        self._data = data

    def __getitem__(self, item):
        return vocab(self._data[item])

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return f"VocabMapping({dict(self.items())!r})"


class NestedVocabMapping(Mapping):
    """`{client: {key: spanish label}}` with every inner table wrapped in a VocabMapping."""

    def __init__(self, data):
        self._data = data

    def __getitem__(self, item):
        return VocabMapping(self._data[item])

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)


class LazyLabels(Mapping):
    """Read-only `{value: translated label}` mapping that translates on every access.

    For module-level label tables (enum -> display text) that would otherwise freeze
    their text in Spanish at import time. Behaves like the dict it replaces for
    `[]`, `.get`, `in`, iteration and `.items()`; each lookup resolves `t(key)` for
    the language of the request being served.
    """

    def __init__(self, keys: Dict[Any, str]):
        self._keys = dict(keys)

    def __getitem__(self, item):
        return t(self._keys[item])

    def __iter__(self):
        return iter(self._keys)

    def __len__(self):
        return len(self._keys)

    def __repr__(self):
        return f"LazyLabels({dict(self.items())!r})"


def t_or(key: str, default: str) -> str:
    """`t(key)`, or `default` when the key is not in the catalog (e.g. a label for a
    data-driven identifier that has no translation entry)."""
    if key in load_catalog(DEFAULT_LANGUAGE):
        return t(key)
    return default


def page_title(key: str, suffix: str = " | Multi-Technical Alerts"):
    """Browser-tab title for `dash.register_page(title=...)`.

    Dash accepts a callable and evaluates it on every page load and navigation, which
    is what lets the tab title follow the language; a plain string would be frozen at
    import time, in Spanish.
    """

    def title(**_path_variables) -> str:
        return t(key) + suffix

    return title


__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGES",
    "JS_KEY_PREFIX",
    "LANGUAGE_COOKIE",
    "LazyLabels",
    "current_language",
    "js_messages",
    "load_catalog",
    "normalize_language",
    "page_title",
    "t",
    "t_or",
    "NestedVocabMapping",
    "VOCAB_PREFIX",
    "VocabMapping",
    "vocab",
]
