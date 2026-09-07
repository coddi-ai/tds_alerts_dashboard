"""Optional bridge to the independent ETL_Dashboard_SQLite repository.

The bridge is deliberately lazy: the production dashboard can keep its file
backend and test suite without importing the ETL package. When SQLite is
selected, a missing database returns an empty contract instead of touching the
``data/`` tree.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd


logger = logging.getLogger(__name__)


def sqlite_backend_enabled() -> bool:
    return os.getenv("DASHBOARD_DATA_BACKEND", "files").strip().lower() == "sqlite"


def _load_repository_class():
    try:
        module = importlib.import_module("etl_dashboard_sqlite.repository")
        return module.DashboardDataRepository
    except ImportError:
        configured = os.getenv("DASHBOARD_SQLITE_ETL_ROOT", "").strip()
        if configured:
            root = Path(configured).expanduser().resolve()
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            module = importlib.import_module("etl_dashboard_sqlite.repository")
            return module.DashboardDataRepository
        raise


def sqlite_load(client: str, method: str, *args: Any, **kwargs: Any):
    """Call a SQLite contract method, returning ``None`` for file mode."""

    if not sqlite_backend_enabled():
        return None
    try:
        repository_class = _load_repository_class()
        repository = repository_class.from_environment(client)
        reader = getattr(repository, method)
        return reader(*args, **kwargs)
    except (FileNotFoundError, ModuleNotFoundError, ImportError) as exc:
        logger.warning("SQLite backend unavailable for %s/%s: %s", client, method, exc)
        if method.startswith("load_"):
            return pd.DataFrame()
        return None
    except Exception:
        logger.exception("SQLite contract failed for %s/%s", client, method)
        if method.startswith("load_"):
            return pd.DataFrame()
        return None


def sqlite_capabilities(client: str) -> dict[str, Any] | None:
    if not sqlite_backend_enabled():
        return None
    try:
        repository_class = _load_repository_class()
        return repository_class.from_environment(client).capabilities()
    except Exception:
        logger.exception("Could not read SQLite capabilities for %s", client)
        return {}
