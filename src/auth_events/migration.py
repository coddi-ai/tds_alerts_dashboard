"""One-off migration of the legacy login log into the new event store (TR-1, item 7).

    python -m src.auth_events.migration            # dry run: report only
    python -m src.auth_events.migration --apply    # write daily parquet + archive the legacy objects

Legacy sources found under the S3 root (see documentation/general/registro_usuarios/):
  * `authentication_register/**/*.json`   one object per login (the writer that is being removed)
  * `authentication_register.csv` / `.parquet`   the older single-file logs, if still present

Rules:
  * `event_id` is deterministic (UUIDv5 of the legacy id, or of the row content + position), so a
    second run produces the same events and the result is idempotent.
  * `user_type` / `client_id` come from the registry at migration time; `environment` is kept as
    stored (`POC` -> production, `test` -> development, anything else -> unknown).
  * Rows without a usable timestamp go to `auth_events/daily/dt=legacy/events.parquet`; the
    dashboard's time-based views ignore that partition.
  * Failed attempts (`success = false` in the oldest file) are not logins and are skipped.
    IP addresses are not carried over.
  * The legacy objects are copied unchanged under `auth_events/legacy/` and never deleted.
"""

import argparse
import csv
import io
import json
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pyarrow.parquet as pq

from src.auth_events import settings
from src.auth_events.compaction import daily_key
from src.auth_events.events import build_event, validate_event
from src.auth_events.parquet_io import events_to_parquet_bytes, parquet_bytes_to_events
from src.auth_events.registry import Registry, load_registry, resolve_user
from src.auth_events.storage import ObjectNotFound, Storage, get_storage

NAMESPACE = uuid.UUID("5d0a8d7e-3b62-4a53-9d0e-6c2d1a7f4b11")
LEGACY_FILES = ("authentication_register.csv", "authentication_register.parquet")


@dataclass
class MigrationReport:
    sources: dict[str, int] = field(default_factory=dict)
    legacy_rows: int = 0
    skipped_failed: int = 0
    migrated: int = 0
    undated: int = 0
    by_user: Counter = field(default_factory=Counter)
    by_environment: Counter = field(default_factory=Counter)
    archived: list[str] = field(default_factory=list)
    days_written: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def deterministic_event_id(legacy_id: str | None, source: str, position: int, content: str) -> str:
    seed = f"id:{legacy_id}" if legacy_id else f"row:{source}:{position}:{content}"
    return str(uuid.uuid5(NAMESPACE, seed))


def _parse_legacy_time(value) -> datetime | None:
    """Legacy timestamps: ISO-8601 with Z, or naive (the server's clock, which is UTC)."""
    if value is None or value == "":
        return None
    try:
        text = value.isoformat() if hasattr(value, "isoformat") else str(value)
        moment = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _is_failure(value) -> bool:
    return str(value).strip().lower() in ("false", "0", "no", "failed")


def _read_rows(storage: Storage, report: MigrationReport) -> list[tuple[str, int, dict]]:
    """(source key, position, row) for every legacy row found."""
    rows: list[tuple[str, int, dict]] = []

    json_keys = sorted(k for k in storage.list(settings.LEGACY_S3_PREFIX) if k.endswith(".json"))
    for position, key in enumerate(json_keys):
        try:
            row = json.loads(storage.get(key).decode("utf-8"))
            if not isinstance(row, dict):
                raise ValueError("not a JSON object")
            rows.append((key, position, row))
        except (ValueError, UnicodeDecodeError) as exc:
            report.problems.append(f"{key}: unreadable ({exc})")
    report.sources["authentication_register/*.json"] = len(json_keys)

    for name in LEGACY_FILES:
        try:
            data = storage.get(name)
        except ObjectNotFound:
            continue
        try:
            if name.endswith(".csv"):
                parsed = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
            else:
                parsed = pq.read_table(io.BytesIO(data)).to_pylist()
        except Exception as exc:  # noqa: BLE001
            report.problems.append(f"{name}: unreadable ({type(exc).__name__}: {exc})")
            continue
        report.sources[name] = len(parsed)
        rows.extend((name, position, row) for position, row in enumerate(parsed))
    return rows


def _row_to_event(source: str, position: int, row: dict, registry: Registry, report: MigrationReport):
    """(event | None, dated). Returns (None, _) for rows that are skipped."""
    if "success" in row and _is_failure(row["success"]):
        report.skipped_failed += 1
        return None, True
    username = str(row.get("username") or "").strip()
    if not username:
        report.problems.append(f"{source}#{position}: row without username skipped")
        return None, True

    moment = _parse_legacy_time(row.get("timestamp"))
    environment = settings.normalize_environment(row.get("deploy_status") or row.get("environment"))
    user_type, client_id = resolve_user(registry, username)
    event_id = deterministic_event_id(
        row.get("event_id"), source, position, json.dumps(row, sort_keys=True, default=str))
    event = build_event(
        username, user_type, client_id, environment,
        moment=moment or datetime(1970, 1, 1, tzinfo=timezone.utc),
        source="legacy_migration", event_id=event_id,
    )
    return validate_event(event), moment is not None


def build_events(storage: Storage, registry: Registry, report: MigrationReport) -> tuple[list[dict], list[dict]]:
    """(dated events, undated events), deduplicated by event_id."""
    dated: dict[str, dict] = {}
    undated: dict[str, dict] = {}
    for source, position, row in _read_rows(storage, report):
        report.legacy_rows += 1
        event, has_time = _row_to_event(source, position, row, registry, report)
        if event is None:
            continue
        (dated if has_time else undated).setdefault(event["event_id"], event)
    return list(dated.values()), list(undated.values())


def _merge_into_day(storage: Storage, day_key: str, events: list[dict]) -> int:
    existing = {}
    try:
        existing = {e["event_id"]: e for e in parquet_bytes_to_events(storage.get(day_key))}
    except ObjectNotFound:
        pass
    merged = dict(existing)
    for event in events:
        merged.setdefault(event["event_id"], event)
    if set(merged) != set(existing):
        storage.put(day_key, events_to_parquet_bytes(list(merged.values())))
    return len(merged)


def archive_legacy(storage: Storage, report: MigrationReport) -> None:
    keys = [k for k in storage.list(settings.LEGACY_S3_PREFIX)] + [
        n for n in LEGACY_FILES if _exists(storage, n)]
    for key in keys:
        target = f"{settings.LEGACY_PREFIX}{key}"
        body = storage.get(key)
        try:
            if storage.get(target) == body:
                report.archived.append(target)
                continue
            report.problems.append(f"{target} exists and differs from the legacy object; left untouched")
            continue
        except ObjectNotFound:
            pass
        storage.put(target, body)
        report.archived.append(target)


def _exists(storage: Storage, key: str) -> bool:
    try:
        storage.get(key)
        return True
    except ObjectNotFound:
        return False


def migrate(storage: Storage, apply: bool = False) -> MigrationReport:
    report = MigrationReport()
    registry = load_registry(storage)
    dated, undated = build_events(storage, registry, report)

    for event in dated + undated:
        report.by_user[event["username"]] += 1
        report.by_environment[event["environment"]] += 1
    report.migrated = len(dated) + len(undated)
    report.undated = len(undated)
    if undated:
        report.problems.append(
            f"{len(undated)} legacy rows have no usable timestamp; they go to dt=legacy and are "
            "excluded from time-based views")

    if not apply:
        return report

    by_day: dict[str, list[dict]] = {}
    for event in dated:
        by_day.setdefault(event["timestamp_utc"][:10], []).append(event)
    for day, events in sorted(by_day.items()):
        _merge_into_day(storage, daily_key(day), events)
        report.days_written.append(day)
    if undated:
        _merge_into_day(storage, daily_key("legacy"), undated)
        report.days_written.append("legacy")

    archive_legacy(storage, report)
    return report


def format_report(report: MigrationReport, applied: bool) -> str:
    lines = [f"Legacy login migration ({'APPLIED' if applied else 'dry run'})"]
    for source, count in report.sources.items():
        lines.append(f"  source {source}: {count} rows/objects")
    lines += [
        f"  legacy rows read: {report.legacy_rows}",
        f"  failed attempts skipped: {report.skipped_failed}",
        f"  events migrated: {report.migrated} (undated: {report.undated})",
        "  per environment: " + ", ".join(f"{k}={v}" for k, v in sorted(report.by_environment.items())),
        "  per user: " + ", ".join(f"{k}={v}" for k, v in sorted(report.by_user.items())),
    ]
    if applied:
        lines.append(f"  daily partitions written: {len(report.days_written)}; legacy objects archived: {len(report.archived)}")
    lines += [f"  PROBLEM: {p}" for p in report.problems]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the migrated data (default: dry run)")
    args = parser.parse_args(argv)
    storage = get_storage()
    if storage is None:
        print("No storage configured (set BUCKET_NAME or AUTH_EVENTS_LOCAL_DIR).", file=sys.stderr)
        return 2
    try:
        report = migrate(storage, apply=args.apply)
    except ObjectNotFound as exc:
        print(f"Registry file missing ({exc}); upload auth_registry/clients.json and users.json first.", file=sys.stderr)
        return 2
    print(format_report(report, args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
