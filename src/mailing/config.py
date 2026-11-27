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
import socket
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
        # `optional`: selected by default and always in the scheduled send, but the admin can uncheck
        # it for a manual send. The contacts without it are locked (always included).
        {"name": "Warren", "email": "warren@coddi.ai", "send_email": True, "optional": True},
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

# The schedules live in code ON PURPOSE: they cannot be overridden from `.env`, the UI or a local
# file. A temporary test schedule must never be committed (manual send is the way to test; a test
# in tests/test_mailing.py guards these exact values).
MAILING_SCHEDULES: Dict[str, dict] = {
    "emin": {"frequency": "daily", "time": "12:00"},
    # 08:30: the weekly partitioner runs at 08:00, one hour after the 07:00 alert creation
    # (src/data/partition_scheduler.py). The time leaves the partitioner time to finish; it is NOT what
    # keeps the order: see MAILING_PARTITION_DEPENDENCY.
    "capstone": {"frequency": "weekly", "weekday": "wednesday", "time": "08:30"},
}

# The partitioner job whose run each client's scheduled e-mail needs. Before building, the scheduled
# send checks that this period's run finished OK (the status the partitioner records); if it failed,
# is still running or never ran, the e-mail is NOT sent and the reason is logged as an error. No retry.
#   weekly: the run of the week of the send date; daily: the run of the send date itself.
# A client missing here has no dependency (the check is not made).
MAILING_PARTITION_DEPENDENCY: Dict[str, str] = {
    "emin": "daily",
    "capstone": "weekly",
}

# Clients whose scheduled e-mail also needs ALERTS to exist: before building, the period's partitions must hold
# at least one alert of the client, otherwise the e-mail is NOT sent (error logged, no retry): the weekly
# alert creation (07:00) either did not run or did not reach the partitions, and an e-mail built on that
# would be the incomplete one of 25/11. Capstone only. EMIN is NOT here on purpose: it generates alerts
# daily and not every day has alerts, so an empty day is normal and still gets its (empty) e-mail.
# The cost: a week in which capstone truly has zero alerts sends nothing (an error is logged instead).
MAILING_REQUIRE_ALERTS: frozenset = frozenset({"capstone"})

# >>> TEMPORARY, EMIN IN TEST: the SCHEDULED email of these clients goes ONLY to the Coddi technical
# >>> contacts (CODDI_RECIPIENTS["technical"]); no client contact and no Gerencia. Capstone keeps the
# >>> real audience. To put Emin live, make this `frozenset()`. It never affects the manual send,
# >>> where the admin picks the recipients (any registry contact, every environment).
SCHEDULED_TECHNICAL_ONLY_CLIENTS = frozenset({"emin"})

# Refresh `data/` from S3 (the app's own startup sync) right before a scheduled email is built, so a
# process that has been up for days does not send a summary from stale files. Failure never blocks
# the email. The app-wide `SYNC_DATA=false` switch also turns it off. See data_sync.py.
SYNC_DATA_BEFORE_SCHEDULED_SEND = True

WEEKDAYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)  # index == datetime.weekday()

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

# Public base URL of the dashboard (prefix included). The email button points at its Alertas page.
DASHBOARD_URL = "https://poc.tds.coddi.ai/alerts-dashboard"

# The app's existing environment flag is DEPLOY_STATUS ("POC" = production, anything else or
# unset = non-production). It only changes the default selection of the manual screen, the
# confirmation in the front and the `environment` field of the logs. It never changes who
# receives a scheduled email or who an admin may select.
PRODUCTION_DEPLOY_STATUSES = frozenset({"poc", "production"})

DEFAULT_RETRY_DELAYS: Tuple[float, ...] = (30.0, 120.0, 300.0)  # 3 retries, growing waits
DEFAULT_MANUAL_COOLDOWN_SECONDS = 5.0
DEFAULT_SCHEDULER_POLL_SECONDS = 30.0
DEFAULT_SCHEDULER_GRACE_MINUTES = 15
DEFAULT_LAMBDA_TIMEOUT = (5.0, 60.0)  # (connect, read) seconds; read must stay below the Lambda timeout


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


def get_lambda_function_name() -> Optional[str]:
    """ARN of the email Lambda (`LAMBDA_FUNCTION_NAME`). Never log it or put it in an error."""
    return get_env("LAMBDA_FUNCTION_NAME")


def is_production() -> bool:
    return (get_env("DEPLOY_STATUS", "") or "").lower() in PRODUCTION_DEPLOY_STATUSES


def environment_name() -> str:
    return "production" if is_production() else "development"


def scheduler_disabled_reason() -> Optional[str]:
    """Why the automatic send does not run on this machine, or None when it does.

    The automatic send runs ONLY in production (`DEPLOY_STATUS` = POC / production). Anywhere else
    (a local machine, a development or test server) it never starts, whatever else is configured, so
    a non-production run can never email real people on schedule. In production,
    `MAILING_SCHEDULER_ENABLED=false` still switches it off on that machine.
    """
    if not is_production():
        return "the environment is not production"
    if not env_flag("MAILING_SCHEDULER_ENABLED", True):
        return "MAILING_SCHEDULER_ENABLED=false"
    return None


def scheduler_enabled() -> bool:
    """True only in production (and not switched off). See `scheduler_disabled_reason`."""
    return scheduler_disabled_reason() is None


def get_hostname() -> str:
    """Machine name, logged with every send attempt so the origin of an email can be traced."""
    try:
        return socket.gethostname() or "unknown"
    except OSError:
        return "unknown"


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
