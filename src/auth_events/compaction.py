"""Daily compaction of raw events (TR-1, item 5).

    python -m src.auth_events.compaction            # compact and prune
    python -m src.auth_events.compaction --dry-run  # report only

For each UTC day that has raw objects (every day before today, plus the last 3 days):
existing daily rows  U  raw rows  ->  dedupe by event_id  ->  validate  ->  sort by timestamp
-> one PUT of `auth_events/daily/dt=<day>/events.parquet`. Raw objects are deleted only once
the daily file has been read back and its row count equals the unique event count, and only
after the raw retention window. Running it twice for the same day yields the same file.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from src.auth_events import settings
from src.auth_events.events import (
    InvalidEvent, day_from_key, event_id_from_raw_key, validate_event,
)
from src.auth_events.parquet_io import events_to_parquet_bytes, parquet_bytes_to_events
from src.auth_events.storage import ObjectNotFound, Storage, get_storage
from src.utils.logger import get_logger

logger = get_logger(__name__)

RECOMPACT_LAST_DAYS = 3


@dataclass
class DayReport:
    day: str
    rows: int = 0
    new_events: int = 0
    wrote: bool = False
    raw_deleted: int = 0
    invalid_raw: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class CompactionReport:
    days: list[DayReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(d.error is None for d in self.days)


def daily_key(day: str) -> str:
    return f"{settings.DAILY_PREFIX}dt={day}/events.parquet"


def _days_to_compact(raw_by_day: dict[str, list[str]], today: date) -> list[str]:
    recent_from = today - timedelta(days=RECOMPACT_LAST_DAYS - 1)
    days = []
    for day in sorted(raw_by_day):
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            logger.warning("Ignoring raw partition with an invalid date: %s", day)
            continue
        if parsed < today or parsed >= recent_from:
            days.append(day)
    return days


def group_raw_by_day(storage: Storage) -> dict[str, list[str]]:
    by_day: dict[str, list[str]] = {}
    for key in storage.list(settings.RAW_PREFIX):
        day = day_from_key(key)
        if day and key.endswith(".json"):
            by_day.setdefault(day, []).append(key)
    return by_day


def compact_day(storage: Storage, day: str, raw_keys: list[str], today: date,
                retention_days: int, dry_run: bool = False) -> DayReport:
    report = DayReport(day=day)
    target = daily_key(day)

    existing: dict[str, dict] = {}
    try:
        for event in parquet_bytes_to_events(storage.get(target)):
            existing[event["event_id"]] = event
    except ObjectNotFound:
        pass

    merged = dict(existing)
    raw_event_ids: dict[str, str] = {}  # raw key -> event_id, for the objects that validated
    for key in raw_keys:
        key_event_id = event_id_from_raw_key(key)
        if key_event_id in existing:
            raw_event_ids[key] = key_event_id  # already compacted: no need to read it again
            continue
        try:
            event = validate_event(json.loads(storage.get(key).decode("utf-8")))
        except (InvalidEvent, ValueError, UnicodeDecodeError) as exc:
            logger.warning("Raw event %s is invalid and was left in place: %s", key, exc)
            report.invalid_raw.append(key)
            continue
        raw_event_ids[key] = event["event_id"]
        if event["event_id"] not in merged:
            merged[event["event_id"]] = event
            report.new_events += 1

    report.rows = len(merged)
    if dry_run:
        return report

    if report.new_events or (merged and not existing):
        storage.put(target, events_to_parquet_bytes(list(merged.values())), "application/octet-stream")
        report.wrote = True

    # Verify before anything is deleted: read the file back, compare with the unique events.
    verified = {e["event_id"] for e in parquet_bytes_to_events(storage.get(target))} if merged else set()
    if not merged or len(verified) != len(merged) or verified != set(merged):
        if merged:
            report.error = f"verification failed for dt={day}: {len(verified)} rows vs {len(merged)} unique events"
            logger.error(report.error)
        return report

    if date.fromisoformat(day) < today - timedelta(days=retention_days):
        for key, event_id in raw_event_ids.items():
            if event_id in verified:
                storage.delete(key)
                report.raw_deleted += 1
    return report


def compact(storage: Storage, today: date | None = None, retention_days: int | None = None,
            dry_run: bool = False) -> CompactionReport:
    today = today or datetime.now(timezone.utc).date()
    retention_days = settings.raw_retention_days() if retention_days is None else retention_days
    raw_by_day = group_raw_by_day(storage)

    report = CompactionReport()
    for day in _days_to_compact(raw_by_day, today):
        try:
            day_report = compact_day(storage, day, raw_by_day[day], today, retention_days, dry_run)
        except Exception as exc:  # noqa: BLE001 - one bad day must not stop the others
            logger.error("Compaction of dt=%s failed: %s: %s", day, type(exc).__name__, exc)
            day_report = DayReport(day=day, error=f"{type(exc).__name__}: {exc}")
        report.days.append(day_report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Compact raw login events into daily parquet files.")
    parser.add_argument("--dry-run", action="store_true", help="report what would change without writing or deleting")
    args = parser.parse_args(argv)

    storage = get_storage()
    if storage is None:
        print("No storage configured (set BUCKET_NAME or AUTH_EVENTS_LOCAL_DIR).", file=sys.stderr)
        return 2
    report = compact(storage, dry_run=args.dry_run)
    for d in report.days:
        status = d.error or ("written" if d.wrote else "unchanged")
        print(f"dt={d.day}: {d.rows} rows, {d.new_events} new, {status}, {d.raw_deleted} raw deleted"
              + (f", {len(d.invalid_raw)} invalid raw kept" if d.invalid_raw else ""))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
