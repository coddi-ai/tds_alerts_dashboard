"""The event schema: login (TR-1) and page_view (TR-6), construction, validation and storage keys.

Schema version 2 adds `page_id`, `path` and `tab`, which are null on logins. Login events keep
being written as version-1 objects (nine fields, exactly as before); readers fill the missing page
columns with null. A page view is always a version-2 event.
"""

import json
import re
import uuid
from datetime import datetime, timezone

from src.auth_events import settings

LOGIN_SCHEMA_VERSION = 1
SCHEMA_VERSION = 2                  # current version: page views, and the daily parquet columns
SUPPORTED_SCHEMA_VERSIONS = (1, 2)
EVENT_TYPE_LOGIN = "login"
EVENT_TYPE_PAGE_VIEW = "page_view"
EVENT_TYPES = (EVENT_TYPE_LOGIN, EVENT_TYPE_PAGE_VIEW)
UNREGISTERED_PAGE_ID = "unregistered"
USER_TYPES = ("client", "internal", "unmapped")
ENVIRONMENTS = ("production", "development", "unknown")
SOURCES = ("live", "legacy_migration")

V1_COLUMNS = (
    "schema_version", "event_id", "event_type", "timestamp_utc", "username",
    "user_type", "client_id", "environment", "source",
)
PAGE_COLUMNS = ("page_id", "path", "tab")
EVENT_COLUMNS = V1_COLUMNS + PAGE_COLUMNS

_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")


class InvalidEvent(ValueError):
    pass


def format_timestamp(moment: datetime) -> str:
    """ISO-8601 UTC with milliseconds: 2026-11-10T20:30:15.123Z."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_timestamp(value) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP_RE.match(value):
        raise InvalidEvent(f"timestamp_utc is not ISO-8601 UTC: {value!r}")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_event(username: str, user_type: str, client_id: str | None, environment: str,
                moment: datetime | None = None, source: str = "live",
                event_id: str | None = None) -> dict:
    moment = moment or datetime.now(timezone.utc)
    return {
        "schema_version": LOGIN_SCHEMA_VERSION,
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": EVENT_TYPE_LOGIN,
        "timestamp_utc": format_timestamp(moment),
        "username": username,
        "user_type": user_type,
        "client_id": client_id if user_type == "client" else None,
        "environment": environment,
        "source": source,
    }


def build_page_view_event(username: str, user_type: str, client_id: str | None, environment: str,
                          page_id: str, path: str, tab: str | None, moment: datetime | None = None,
                          event_id: str | None = None) -> dict:
    moment = moment or datetime.now(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": EVENT_TYPE_PAGE_VIEW,
        "timestamp_utc": format_timestamp(moment),
        "username": username,
        "user_type": user_type,
        "client_id": client_id if user_type == "client" else None,
        "environment": environment,
        "source": "live",
        "page_id": page_id,
        "path": path,
        "tab": tab,
    }


def validate_event(event) -> dict:
    """Return the event restricted to the schema's columns (page columns null when absent), or
    raise InvalidEvent."""
    if not isinstance(event, dict):
        raise InvalidEvent("event is not a JSON object")
    missing = [c for c in V1_COLUMNS if c not in event]
    if missing:
        raise InvalidEvent(f"missing fields: {missing}")
    clean = {c: event.get(c) for c in EVENT_COLUMNS}
    if clean["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS or isinstance(clean["schema_version"], bool):
        raise InvalidEvent(f"unsupported schema_version: {clean['schema_version']!r}")
    for name in ("event_id", "event_type", "username", "user_type", "environment", "source"):
        if not isinstance(clean[name], str) or not clean[name]:
            raise InvalidEvent(f"{name} must be a non-empty string")
    if clean["event_type"] not in EVENT_TYPES:
        raise InvalidEvent(f"invalid event_type: {clean['event_type']!r}")
    if clean["user_type"] not in USER_TYPES:
        raise InvalidEvent(f"invalid user_type: {clean['user_type']!r}")
    if clean["environment"] not in ENVIRONMENTS:
        raise InvalidEvent(f"invalid environment: {clean['environment']!r}")
    if clean["client_id"] is not None and not isinstance(clean["client_id"], str):
        raise InvalidEvent("client_id must be a string or null")
    parse_timestamp(clean["timestamp_utc"])
    if clean["event_type"] == EVENT_TYPE_PAGE_VIEW:
        for name in ("page_id", "path"):
            if not isinstance(clean[name], str) or not clean[name]:
                raise InvalidEvent(f"a page_view needs a non-empty {name}")
        if clean["tab"] is not None and not isinstance(clean["tab"], str):
            raise InvalidEvent("tab must be a string or null")
    else:
        for name in PAGE_COLUMNS:       # logins carry no page: tolerate empty values, store null
            clean[name] = None
    return clean


def utc_date(event: dict) -> str:
    return parse_timestamp(event["timestamp_utc"]).strftime("%Y-%m-%d")


def raw_key(event: dict) -> str:
    """auth_events/raw/dt=YYYY-MM-DD/<YYYYMMDDTHHMMSSmmmZ>_<event_id>.json"""
    moment = parse_timestamp(event["timestamp_utc"])
    stamp = moment.strftime("%Y%m%dT%H%M%S") + f"{moment.microsecond // 1000:03d}Z"
    return f"{settings.RAW_PREFIX}dt={utc_date(event)}/{stamp}_{event['event_id']}.json"


def event_id_from_raw_key(key: str) -> str | None:
    name = key.rsplit("/", 1)[-1]
    if not name.endswith(".json") or "_" not in name:
        return None
    return name[:-5].split("_", 1)[1]


def day_from_key(key: str) -> str | None:
    match = re.search(r"/dt=([^/]+)/", "/" + key)
    return match.group(1) if match else None


def encode(event: dict) -> bytes:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------------------------
# Batched page views (TR-6 item 4): one JSON Lines object per flush and UTC date

BATCH_SUFFIX = ".jsonl"


def batch_key(day: str, moment: datetime, batch_id: str) -> str:
    """auth_events/raw/dt=YYYY-MM-DD/pv_<YYYYMMDDTHHMMSSmmmZ>_<batch_id>.jsonl"""
    moment = moment.astimezone(timezone.utc)
    stamp = moment.strftime("%Y%m%dT%H%M%S") + f"{moment.microsecond // 1000:03d}Z"
    return f"{settings.RAW_PREFIX}dt={day}/pv_{stamp}_{batch_id}{BATCH_SUFFIX}"


def is_batch_key(key: str) -> bool:
    return key.endswith(BATCH_SUFFIX)


def encode_batch(events: list[dict]) -> bytes:
    lines = (json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in events)
    return (chr(10).join(lines) + chr(10)).encode("utf-8")


def decode_batch(data: bytes) -> tuple[list[dict], list[str]]:
    """(valid events, one message per rejected line). A bad line never hides the good ones."""
    events: list[dict] = []
    rejected: list[str] = []
    for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append(validate_event(json.loads(line)))
        except (InvalidEvent, ValueError) as exc:
            rejected.append(f"line {number}: {exc}")
    return events, rejected
