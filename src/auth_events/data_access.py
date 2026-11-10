"""The dashboard's single door to login events and the registry (TR-1, item 6).

Nothing else may read `auth_events/` or `auth_registry/`.

    events = get_events(start, end, environment)   # dates are display-timezone days, inclusive
    all_events = get_events()                      # full history (used for "Ultimo Acceso")
    registry = get_registry()
    when = last_loaded_at()                        # for "Ultima actualizacion"

Compacted days come from the daily parquet, days not yet compacted from the raw JSON objects.
For a range, UTC partitions covering the range +-1 day are loaded and the result is then cut
by the display-timezone range. Every read deduplicates by `event_id`. Results are cached in
memory (default 60 s); days old enough to be final are cached longer.
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from src.auth_events import settings
from src.auth_events.compaction import daily_key, group_raw_by_day
from src.auth_events.events import (
    EVENT_COLUMNS, InvalidEvent, day_from_key, event_id_from_raw_key, validate_event,
)
from src.auth_events.parquet_io import parquet_bytes_to_events
from src.auth_events.registry import Registry, RegistryUnavailable, get_registry_or_none
from src.auth_events.storage import ObjectNotFound, Storage, get_storage
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Days this far back can no longer receive late events from the compactor's 3-day window.
SETTLED_AFTER_DAYS = 4
SETTLED_TTL_SECONDS = 3600.0
_READ_WORKERS = 8


class AuthDataUnavailable(Exception):
    """Events or registry cannot be read (storage missing or unreachable)."""


_lock = threading.RLock()
_partitions: dict[str, tuple[float, list[dict]]] = {}
_listing: tuple[float, set[str]] | None = None
_last_loaded: datetime | None = None
_storage_override: Storage | None = None


def set_storage_for_tests(storage: Storage | None) -> None:
    global _storage_override
    _storage_override = storage
    clear_cache()


def clear_cache() -> None:
    global _listing, _last_loaded
    with _lock:
        _partitions.clear()
        _listing = None
        _last_loaded = None


def _storage() -> Storage:
    storage = _storage_override or get_storage()
    if storage is None:
        raise AuthDataUnavailable("no storage configured (BUCKET_NAME or AUTH_EVENTS_LOCAL_DIR)")
    return storage


def last_loaded_at() -> datetime | None:
    """UTC time of the last successful load of events (None before the first load)."""
    return _last_loaded


def get_registry() -> Registry:
    registry = get_registry_or_none()
    if registry is None:
        raise AuthDataUnavailable("the client/user registry could not be loaded")
    return registry


def _known_days(storage: Storage, now: float) -> set[str]:
    """UTC days that have a daily file or raw objects."""
    global _listing
    ttl = settings.events_cache_ttl()
    if _listing is not None and now - _listing[0] < ttl:
        return _listing[1]
    days = set()
    for key in storage.list(settings.DAILY_PREFIX):
        day = day_from_key(key)
        if day and day != "legacy" and key.endswith("events.parquet"):
            days.add(day)
    days.update(d for d in group_raw_by_day(storage) if d != "legacy")
    _listing = (now, days)
    return days


def _load_partition(storage: Storage, day: str) -> list[dict]:
    """All events of one UTC day: daily parquet U raw objects not already in it."""
    events: dict[str, dict] = {}
    try:
        for event in parquet_bytes_to_events(storage.get(daily_key(day))):
            events[event["event_id"]] = event
    except ObjectNotFound:
        pass

    for key in storage.list(f"{settings.RAW_PREFIX}dt={day}/"):
        key_event_id = event_id_from_raw_key(key)
        if key_event_id is None or key_event_id in events:
            continue  # the daily file already has it: skip the read
        try:
            event = validate_event(json.loads(storage.get(key).decode("utf-8")))
        except ObjectNotFound:
            continue  # compacted and pruned between the listing and the read
        except (InvalidEvent, ValueError, UnicodeDecodeError) as exc:
            logger.warning("Skipping malformed login event %s: %s", key, exc)
            continue
        events.setdefault(event["event_id"], event)
    return list(events.values())


def _partitions_for(days: list[str]) -> list[dict]:
    global _last_loaded
    storage = _storage()
    now = time.monotonic()
    today = datetime.now(timezone.utc).date()
    ttl = settings.events_cache_ttl()

    with _lock:
        try:
            known = _known_days(storage, now)
        except Exception as exc:  # noqa: BLE001
            raise AuthDataUnavailable(f"cannot list login events: {type(exc).__name__}: {exc}") from exc

        wanted = [d for d in days if d in known]
        stale = []
        for day in wanted:
            cached = _partitions.get(day)
            settled = date.fromisoformat(day) < today - timedelta(days=SETTLED_AFTER_DAYS)
            limit = SETTLED_TTL_SECONDS if settled else ttl
            if cached is None or now - cached[0] >= limit:
                stale.append(day)

        if stale:
            try:
                with ThreadPoolExecutor(max_workers=_READ_WORKERS) as pool:
                    loaded = list(pool.map(lambda d: _load_partition(storage, d), stale))
            except Exception as exc:  # noqa: BLE001
                raise AuthDataUnavailable(f"cannot read login events: {type(exc).__name__}: {exc}") from exc
            for day, events in zip(stale, loaded):
                _partitions[day] = (now, events)
            _last_loaded = datetime.now(timezone.utc)
        elif _last_loaded is None:
            _last_loaded = datetime.now(timezone.utc)

        rows: list[dict] = []
        for day in wanted:
            rows.extend(_partitions[day][1])
        return rows


def _frame(rows: list[dict], tz: str) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=list(EVENT_COLUMNS))
    frame = frame.drop_duplicates(subset="event_id", keep="first")
    frame["client_id"] = frame["client_id"].astype(object).where(frame["client_id"].notna(), None)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, format="ISO8601")
    frame["timestamp"] = frame["timestamp_utc"].dt.tz_convert(tz)
    frame["date"] = frame["timestamp"].dt.date
    frame = frame.sort_values(["timestamp_utc", "event_id"], kind="stable").reset_index(drop=True)
    return frame


def _day_range(first: date, last: date) -> list[str]:
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def get_events(start: date | None = None, end: date | None = None,
               environment: str | None = None) -> pd.DataFrame:
    """Normalized login events, newest data included.

    Args:
        start, end: inclusive dates in the display timezone; both None = full history.
        environment: `production` | `development` | `unknown`, or None for all.

    Returns:
        DataFrame with the event columns plus `timestamp` (display timezone), `date` (the
        display-timezone calendar day). `timestamp_utc` is a UTC datetime. Sorted by time.
    """
    tz = settings.display_timezone()
    if (start is None) != (end is None):
        raise ValueError("start and end must both be given or both omitted")

    if start is None:
        storage = _storage()
        with _lock:
            try:
                days = sorted(_known_days(storage, time.monotonic()))
            except Exception as exc:  # noqa: BLE001
                raise AuthDataUnavailable(f"cannot list login events: {type(exc).__name__}: {exc}") from exc
        rows = _partitions_for(days)
        frame = _frame(rows, tz)
    else:
        rows = _partitions_for(_day_range(start - timedelta(days=1), end + timedelta(days=1)))
        frame = _frame(rows, tz)
        frame = frame[(frame["date"] >= start) & (frame["date"] <= end)].reset_index(drop=True)

    if environment:
        frame = frame[frame["environment"] == environment].reset_index(drop=True)
    return frame


def display_timezone() -> str:
    return settings.display_timezone()


__all__ = [
    "AuthDataUnavailable", "RegistryUnavailable", "clear_cache", "display_timezone",
    "get_events", "get_registry", "last_loaded_at", "set_storage_for_tests",
]
