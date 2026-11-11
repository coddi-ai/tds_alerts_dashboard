"""
Configuration for the mailing service: recipient registry, schedules and environment.

Everything a person may need to edit lives here: who receives what, and when.
Nothing in this module talks to the network.

Client keys match the identifiers of the per-client configuration (``config/clients/*.yaml``
``client_id``), lower-case. The dashboard's selector uses upper-case values (``EMIN``,
``CAPSTONE``); every public operation normalises with :func:`normalize_client`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Recipients (hardcoded on purpose: no database)
# ---------------------------------------------------------------------------

MAILING_RECIPIENTS: Dict[str, List[dict]] = {
    "emin": [
        {"name": "Diego Contreras", "email": "dcontrerasr@emin.cl", "send_email": True},
        {"name": "Felipe Cubillos", "email": "fcubillos@emin.cl", "send_email": True},
        {"name": "Sergio Suarez", "email": "ssuarezp@emin.cl", "send_email": True},
    ],
    "capstone": [
        {"name": "Martina Olivares", "email": "Martina.Olivares@capstonecopper.com", "send_email": True},
        {"name": "Rodrigo Gonzalez", "email": "rodrigo.gonzalez@capstonecopper.com", "send_email": True},
        {"name": "Michael Rojas", "email": "michael.rojas@capstonecopper.com", "send_email": True},
        {"name": "Juan Avello", "email": "juan.avello@capstonecopper.com", "send_email": True},
        {"name": "Hector Sanchez", "email": "hector.sanchez@capstonecopper.com", "send_email": True},
        {"name": "Marco Chanes", "email": "Marco.Chanes@capstonecopper.com", "send_email": True},
        {"name": "Kevin Tapia", "email": "Kevin.Tapia@capstonecopper.com", "send_email": True},
        {"name": "Robert Lobos", "email": "Robert.Lobos@capstonecopper.com", "send_email": True},
        {"name": "Benito Gonzalez", "email": "Benito.Gonzalez@capstonecopper.com", "send_email": True},
        {"name": "Milya Bordones", "email": "milya.bordones@capstonecopper.com", "send_email": True},
    ],
}

CODDI_RECIPIENTS: Dict[str, List[dict]] = {
    "technical": [
        {"name": "Equipo Técnico", "email": "tds@coddi.ai", "send_email": True},
        {"name": "Warren", "email": "warren@coddi.ai", "send_email": True},
    ],
    "management": [
        {"name": "Eduardo", "email": "eduardo@coddi.ai", "send_email": True},
        {"name": "Pedro", "email": "pedro@coddi.ai", "send_email": True},
    ],
}

# Recipient groups, in display order. The value is the label shown in the admin screen.
GROUP_CLIENT = "client"
GROUP_TECHNICAL = "coddi_technical"
GROUP_MANAGEMENT = "coddi_management"
GROUP_ORDER = (GROUP_CLIENT, GROUP_TECHNICAL, GROUP_MANAGEMENT)

# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

MAILING_TIMEZONE = "America/Santiago"

# The real schedules (Emin daily, Capstone weekly on Wednesday, both at 08:00 Chile time).
PRODUCTION_SCHEDULES: Dict[str, dict] = {
    "emin": {"frequency": "daily", "time": "08:00"},
    "capstone": {"frequency": "weekly", "weekday": "wednesday", "time": "08:00"},
}

# >>> TEMPORARY DEPLOYED TEST (Tuesday 2026-11-10): both clients fire at 22:10 Chile time, and the
# >>> scheduled email goes ONLY to tds@coddi.ai and warren@coddi.ai even in production (see SCHEDULED_RECIPIENTS_OVERRIDE).
# >>> AFTER THE TEST, replace the three blocks marked TEMPORARY with:
# >>>     MAILING_SCHEDULES = PRODUCTION_SCHEDULES   and   SCHEDULED_RECIPIENTS_OVERRIDE = None
MAILING_SCHEDULES: Dict[str, dict] = {
    "emin": {"frequency": "daily", "time": "22:10"},
    "capstone": {"frequency": "weekly", "weekday": "tuesday", "time": "22:10"},
}

# TEMPORARY: when not None, EVERY scheduled send goes only to these addresses, whatever the
# environment (production would otherwise add the client contacts and management). It does not
# affect the manual send, which has its own validation.
SCHEDULED_RECIPIENTS_OVERRIDE: Optional[List[str]] = ["tds@coddi.ai", "warren@coddi.ai"]
# <<< END TEMPORARY DEPLOYED TEST

WEEKDAYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)  # index == datetime.weekday()

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

# Public base URL of the dashboard (prefix included). The email button points at its Alertas page.
DASHBOARD_URL = "https://poc.tds.coddi.ai/alerts-dashboard"

# The app's existing environment flag is DEPLOY_STATUS ("POC" = production, "test" =
# development; see src/utils/auth_event_logger.py and user_registry_charts.py). Anything
# else, or unset, is NON-production, so a missing variable can never email a client.
PRODUCTION_DEPLOY_STATUSES = frozenset({"poc", "production"})

DEFAULT_RETRY_DELAYS: Tuple[float, ...] = (30.0, 120.0, 300.0)  # 3 retries, growing waits
DEFAULT_MANUAL_COOLDOWN_SECONDS = 5.0
DEFAULT_SCHEDULER_POLL_SECONDS = 30.0
DEFAULT_SCHEDULER_GRACE_MINUTES = 15
DEFAULT_LAMBDA_TIMEOUT = (5.0, 60.0)  # (connect, read) seconds


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_dotenv_once() -> None:
    """Make `.env` visible to `os.environ` when the process was not started with it."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from dotenv import load_dotenv

        load_dotenv(_project_root() / ".env")  # never overrides variables already set
    except Exception:  # noqa: BLE001 - optional convenience
        pass


_DOTENV_LOADED = False


def get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read a setting, tolerating stray whitespace and quotes around the value."""
    _load_dotenv_once()
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().strip('"').strip("'").strip()
    return value if value else default


def env_flag(name: str, default: bool = False) -> bool:
    value = get_env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on", "si", "sí"}


def get_lambda_url() -> Optional[str]:
    """The Lambda endpoint. A secret: never log it, echo it or put it in an error."""
    return get_env("LAMBDA_URL")


def is_production() -> bool:
    return (get_env("DEPLOY_STATUS", "") or "").lower() in PRODUCTION_DEPLOY_STATUSES


def environment_name() -> str:
    return "production" if is_production() else "development"


def scheduler_enabled() -> bool:
    """On by default; `MAILING_SCHEDULER_ENABLED=false` switches it off.

    Safe to leave on in development: outside production a scheduled send only reaches
    `tds@coddi.ai` (see recipients.scheduled_emails).
    """
    return env_flag("MAILING_SCHEDULER_ENABLED", True)


def get_state_dir() -> Path:
    """Where scheduled-send markers live. Must survive restarts and be shared by workers.

    Defaults to ``logs/mailing``: ``logs/`` is a mounted volume in docker-compose.
    """
    configured = get_env("MAILING_STATE_DIR")
    path = Path(configured) if configured else _project_root() / "logs" / "mailing"
    return path


def _float_list(raw: Optional[str], default: Tuple[float, ...]) -> Tuple[float, ...]:
    if not raw:
        return default
    try:
        values = tuple(float(part) for part in raw.split(",") if part.strip())
    except ValueError:
        return default
    return values or default


def get_retry_delays() -> Tuple[float, ...]:
    """Seconds to wait before each retry of a scheduled send (its length = retries)."""
    return _float_list(get_env("MAILING_RETRY_DELAYS"), DEFAULT_RETRY_DELAYS)


def get_manual_cooldown_seconds() -> float:
    raw = get_env("MAILING_MANUAL_COOLDOWN_SECONDS")
    try:
        return max(0.0, float(raw)) if raw is not None else DEFAULT_MANUAL_COOLDOWN_SECONDS
    except ValueError:
        return DEFAULT_MANUAL_COOLDOWN_SECONDS


def get_scheduler_grace_minutes() -> int:
    raw = get_env("MAILING_SCHEDULER_GRACE_MINUTES")
    try:
        return max(0, int(raw)) if raw is not None else DEFAULT_SCHEDULER_GRACE_MINUTES
    except ValueError:
        return DEFAULT_SCHEDULER_GRACE_MINUTES


CLIENT_DISPLAY_NAMES = {"emin": "Emin", "capstone": "Capstone"}


def client_display_name(client: Optional[str]) -> str:
    """`emin` -> `Emin`; a client without a nice name keeps the dashboard's upper-case id."""
    key = normalize_client(client)
    return CLIENT_DISPLAY_NAMES.get(key, key.upper())


def normalize_client(client: Optional[str]) -> str:
    """`EMIN`, ` emin ` and `emin` are the same client."""
    return (client or "").strip().lower()


def get_schedule(client: str) -> Optional[dict]:
    return MAILING_SCHEDULES.get(normalize_client(client))
