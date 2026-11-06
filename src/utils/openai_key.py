"""Resolve the OpenAI API key from the environment.

A single environment variable is supported:

* ``OPENAI_API_KEY`` — the plain key in the environment (or ``.env``).

Having it defined means "an OpenAI connection is configured". Callers that only need to
know whether a key is available should use :func:`openai_key_configured`; callers that
need the key itself should use :func:`resolve_openai_api_key`.
"""

from __future__ import annotations

import os

from src.utils.logger import get_logger

logger = get_logger(__name__)

ENV_KEY = "OPENAI_API_KEY"


def openai_key_configured() -> bool:
    """True when ``OPENAI_API_KEY`` is set."""
    return bool(os.getenv(ENV_KEY, "").strip())


def resolve_openai_api_key() -> str | None:
    """The OpenAI API key, or ``None`` when ``OPENAI_API_KEY`` is not configured."""
    return os.getenv(ENV_KEY, "").strip() or None
