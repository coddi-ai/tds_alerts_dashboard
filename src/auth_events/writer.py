"""Capture of one login event (TR-1, items 2 and 3).

`record_login` is called from the successful-authentication path. It returns immediately: the
event's identity and timestamp are fixed on the calling thread, and everything that can be slow
(loading the registry, the PUT with its retries) happens on a background thread. It never
raises, so capturing can never fail or noticeably slow a login.

The PUT goes to a new unique key; nothing under `auth_events/` is read, listed or overwritten.
"""

import json
import threading
import time
import uuid
from datetime import datetime, timezone

from src.auth_events import settings
from src.auth_events.events import build_event, encode, format_timestamp, raw_key, validate_event
from src.auth_events.registry import get_registry_or_none, resolve_user
from src.auth_events.storage import Storage, get_storage
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_RETRIES = 3
BACKOFF_SECONDS = (0.5, 1.0, 2.0)


def record_login(username: str) -> None:
    """Fire-and-forget: store one `login` event for `username`."""
    try:
        moment = datetime.now(timezone.utc)
        event_id = str(uuid.uuid4())
        threading.Thread(
            target=write_login_event,
            args=(username, moment, event_id),
            name="auth-event-writer",
            daemon=True,
        ).start()
    except Exception as exc:  # noqa: BLE001 - capture must never affect the login
        logger.error("Could not start the login-event writer for user %r: %s: %s", username, type(exc).__name__, exc)


def write_login_event(username: str, moment: datetime, event_id: str, *,
                      storage: Storage | None = None, sleep=time.sleep) -> dict | None:
    """Build and store the event. Returns it on success, None after the final failure."""
    event = None
    try:
        user_type, client_id = resolve_user(get_registry_or_none(), username)
        event = validate_event(build_event(
            username, user_type, client_id, settings.current_environment(),
            moment=moment, event_id=event_id,
        ))
        storage = storage if storage is not None else get_storage()
        if storage is None:
            logger.warning("Login event not stored (no storage configured): %s", json.dumps(event, ensure_ascii=False))
            return None

        key = raw_key(event)
        body = encode(event)
        for attempt in range(MAX_RETRIES + 1):
            try:
                storage.put(key, body, "application/json")
                return event
            except Exception as exc:  # noqa: BLE001
                if attempt == MAX_RETRIES:
                    logger.error(
                        "Login event NOT stored after %d retries (%s: %s); replay it with this payload: %s",
                        MAX_RETRIES, type(exc).__name__, exc, json.dumps(event, ensure_ascii=False),
                    )
                    return None
                sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
    except Exception as exc:  # noqa: BLE001
        payload = json.dumps(event, ensure_ascii=False) if event else json.dumps(
            {"username": username, "event_id": event_id, "timestamp_utc": format_timestamp(moment)})
        logger.error("Login event could not be built or stored (%s: %s); payload: %s", type(exc).__name__, exc, payload)
    return None
