"""The login event: schema, construction, validation and storage keys (TR-1, items 2 and 3)."""

import json
import re
import uuid
from datetime import datetime, timezone

from src.auth_events import settings

SCHEMA_VERSION = 1
EVENT_TYPE_LOGIN = "login"
USER_TYPES = ("client", "internal", "unmapped")
ENVIRONMENTS = ("production", "development", "unknown")
SOURCES = ("live", "legacy_migration")

EVENT_COLUMNS = (
    "schema_version", "event_id", "event_type", "timestamp_utc", "username",
    "user_type", "client_id", "environment", "source",
)

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
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": EVENT_TYPE_LOGIN,
        "timestamp_utc": format_timestamp(moment),
        "username": username,
        "user_type": user_type,
        "client_id": client_id if user_type == "client" else None,
        "environment": environment,
        "source": source,
    }


def validate_event(event) -> dict:
    """Return the event restricted to the schema's columns, or raise InvalidEvent."""
    if not isinstance(event, dict):
        raise InvalidEvent("event is not a JSON object")
    missing = [c for c in EVENT_COLUMNS if c not in event]
    if missing:
        raise InvalidEvent(f"missing fields: {missing}")
    clean = {c: event[c] for c in EVENT_COLUMNS}
    if clean["schema_version"] != SCHEMA_VERSION:
        raise InvalidEvent(f"unsupported schema_version: {clean['schema_version']!r}")
    for name in ("event_id", "event_type", "username", "user_type", "environment", "source"):
        if not isinstance(clean[name], str) or not clean[name]:
            raise InvalidEvent(f"{name} must be a non-empty string")
    if clean["user_type"] not in USER_TYPES:
        raise InvalidEvent(f"invalid user_type: {clean['user_type']!r}")
    if clean["environment"] not in ENVIRONMENTS:
        raise InvalidEvent(f"invalid environment: {clean['environment']!r}")
    if clean["client_id"] is not None and not isinstance(clean["client_id"], str):
        raise InvalidEvent("client_id must be a string or null")
    parse_timestamp(clean["timestamp_utc"])
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
