"""Configuration of the login-event pipeline (TR-1). Everything is read from the environment
at call time so tests and deployments can change it without re-importing."""

import os
from pathlib import Path

from src.utils.date_utils import DEFAULT_DISPLAY_TZ

# Everything lives below this S3 prefix: the bucket and prefix the legacy user log used
# ("MultiTechnique Alerts/auxiliar/authentication_register/..."), one level up.
DEFAULT_S3_ROOT = "MultiTechnique Alerts/auxiliar/"

RAW_PREFIX = "auth_events/raw/"
DAILY_PREFIX = "auth_events/daily/"
LEGACY_PREFIX = "auth_events/legacy/"
LEGACY_PARTITION = "dt=legacy"
REGISTRY_CLIENTS_KEY = "auth_registry/clients.json"
REGISTRY_USERS_KEY = "auth_registry/users.json"

# Where the legacy writer put its objects (see documentation/general/registro_usuarios/).
LEGACY_S3_PREFIX = "authentication_register/"


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return float(default)


def s3_root() -> str:
    root = os.getenv("AUTH_EVENTS_S3_ROOT", DEFAULT_S3_ROOT)
    return root if not root or root.endswith("/") else root + "/"


def local_dir() -> Path | None:
    """Optional directory standing in for S3 (local development and tests)."""
    value = os.getenv("AUTH_EVENTS_LOCAL_DIR", "").strip()
    return Path(value).expanduser() if value else None


def display_timezone() -> str:
    return os.getenv("AUTH_EVENTS_DISPLAY_TZ", "").strip() or DEFAULT_DISPLAY_TZ


def registry_cache_ttl() -> float:
    return _float("AUTH_REGISTRY_CACHE_TTL_SECONDS", 300)


def events_cache_ttl() -> float:
    return _float("AUTH_EVENTS_CACHE_TTL_SECONDS", 60)


def raw_retention_days() -> int:
    return int(_float("AUTH_EVENTS_RAW_RETENTION_DAYS", 7))


_ENVIRONMENT_ALIASES = {
    "poc": "production", "prod": "production", "production": "production",
    "test": "development", "dev": "development", "development": "development",
}


def normalize_environment(raw: str | None) -> str:
    return _ENVIRONMENT_ALIASES.get((raw or "").strip().lower(), "unknown")


def current_environment() -> str:
    """`production` / `development` / `unknown`, from the deployment configuration only.

    `DEPLOY_STATUS` is the app's existing flag (`POC` = production, `test` = development; the
    mailing module reads the same one). `AUTH_EVENTS_ENVIRONMENT` overrides it when set.
    """
    return normalize_environment(os.getenv("AUTH_EVENTS_ENVIRONMENT") or os.getenv("DEPLOY_STATUS"))
