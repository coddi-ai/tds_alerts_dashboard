"""Partition ``consolidated_alerts.csv`` and the alert telemetry into Parquet files by week.

    data/alerts/golden/{client}/consolidated_alerts.csv      (source, never modified)
 -> data/alerts/golden/{client}/{week}/file.parquet          ({week} = ISO date of the Monday)
    data/alerts/golden/{client}/_alert_index.parquet

    data/telemetry/golden/{client}/<wide telemetry CSV>      (source, never modified)
 -> data/alerts/golden/{client}/{week}/telemetry.parquet     ({week} = the week of the row's ALERT)
    data/alerts/golden/{client}/_telemetry_index.parquet

The dashboard reads only those partitions (see ``src/data/alert_partitions.py`` and
``src/data/telemetry_partitions.py``); this script is the only code that opens the source files.
The two datasets share the run, the schedule and the time zone, but are built, validated, swapped
and synced independently: each has its own S3 keys and its own backfill marker. A client with no
telemetry source (EMIN publishes none) simply has no telemetry partitions.

Telemetry rows with no matching alert are kept (``unmatched/``), never dropped, and their count is
logged on every run.

Modes
-----
Weekly run (default)
    Regenerates every partition whose content changed — including the current, in-progress
    week — for every client under ``data/alerts/golden/``, then syncs them to S3. The sync is
    part of the run: a failed upload is logged and the exit status is 2; local files stay valid
    and the next run retries. Refuses to sync a client whose history was never backfilled to S3
    (alerts and telemetry are checked separately: the alerts marker does not unlock telemetry).

``--backfill``
    The first execution: partitions for *all* historical data. Local only unless ``--sync-s3``
    is passed explicitly. Validate the local output first (``--validate`` runs by default),
    then re-run with ``--sync-s3`` to push the full history and unlock the weekly sync.
    ``--dataset telemetry`` runs only the telemetry half (the alerts one is unchanged).

``--schedule``
    Stay in the foreground. Every client is run every Wednesday 04:00 in the configured time
    zone (``ALERT_PARTITIONS_TIMEZONE``, default ``America/Santiago``). The *daily clients*
    (``ALERT_PARTITIONS_DAILY_CLIENTS``, default ``emin``: its data updates every day, the
    others' weekly) are also run at the same time on every other day of the week.

``--verify-s3``
    Compare S3 with the local partitions (keys, sizes, hashes, row counts). Writes nothing.

Exit status: 0 ok, 1 build/validation error, 2 S3 sync error.

Examples
--------
    python scripts/partition_alerts.py --backfill                       # local only
    python scripts/partition_alerts.py --backfill --client capstone     # one client
    python scripts/partition_alerts.py --backfill --dataset telemetry   # only the telemetry
    python scripts/partition_alerts.py --backfill --sync-s3             # after validating
    python scripts/partition_alerts.py --verify-s3
    python scripts/partition_alerts.py                                  # one weekly run now
    python scripts/partition_alerts.py --schedule                       # Wed 04:00, forever

Environment: ``DASHBOARD_DATA_ROOT`` (data root), ``ALERT_PARTITIONS_S3_BUCKET`` (falls back to
``BUCKET_NAME``), ``ALERT_PARTITIONS_S3_PREFIX`` (default ``MultiTechnique Alerts/alerts/golden``),
``ALERT_PARTITIONS_WEEKDAY`` (default ``wednesday``), ``ALERT_PARTITIONS_TIME`` (``04:00``),
``ALERT_PARTITIONS_TIMEZONE`` (``America/Santiago``), ``ALERT_PARTITIONS_DAILY_CLIENTS``
(comma-separated, default ``emin``; ``none`` for no daily client), ``ACCESS_KEY``/``SECRET_KEY`` (optional;
the task role is used otherwise).
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from threading import Event
from zoneinfo import ZoneInfo

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.data import alert_partition_builder as builder  # noqa: E402
from src.data import alert_partition_s3 as s3_sync  # noqa: E402
from src.data import telemetry_partition_builder as telemetry_builder  # noqa: E402
from src.data import telemetry_partitions as telemetry_layout  # noqa: E402

logger = logging.getLogger("partition_alerts")

DATASETS = ("alerts", "telemetry")
# The per-alert telemetry published for each client. This script is the only code that names (and
# opens) it; the dashboard reads the partitions built from it.
TELEMETRY_SOURCE_FILE = "alerts_detail_wide_with_gps.csv"
DEFAULT_WEEKDAY = "wednesday"
DEFAULT_TIME = "04:00"
DEFAULT_TIMEZONE = "America/Santiago"
# Clients whose data is published every day: they are partitioned (and synced) on every day of the
# schedule, not only on the weekly day, so their sections and e-mail do not wait for Wednesday.
DEFAULT_DAILY_CLIENTS = "emin"
EXIT_OK, EXIT_BUILD_ERROR, EXIT_S3_ERROR = 0, 1, 2

_WEEKDAYS = {
    "monday": 0, "lunes": 0, "tuesday": 1, "martes": 1, "wednesday": 2, "miercoles": 2,
    "thursday": 3, "jueves": 3, "friday": 4, "viernes": 4, "saturday": 5, "sabado": 5,
    "sunday": 6, "domingo": 6,
}
_STOP = Event()


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

def parse_weekday(value: str) -> int:
    text = value.strip().lower()
    if text.isdigit() and 0 <= int(text) <= 6:
        return int(text)
    if text in _WEEKDAYS:
        return _WEEKDAYS[text]
    raise ValueError(f"weekday must be a day name or 0..6, got {value!r}")


def parse_time(value: str) -> day_time:
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"time must be HH:MM, got {value!r}")
    return day_time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) == 3 else 0)


def next_run(now: datetime, weekday: int, run_time: day_time) -> datetime:
    """The next ``weekday`` at ``run_time`` strictly after ``now`` (``now`` carries the zone)."""
    candidate = now.replace(hour=run_time.hour, minute=run_time.minute,
                            second=run_time.second, microsecond=0)
    candidate += timedelta(days=(weekday - now.weekday()) % 7)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def next_daily_run(now: datetime, run_time: day_time) -> datetime:
    """The next ``run_time`` (today or tomorrow) strictly after ``now``."""
    candidate = now.replace(hour=run_time.hour, minute=run_time.minute,
                            second=run_time.second, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def parse_clients(value: str | None) -> list[str]:
    """``"emin, cda"`` -> ``["emin", "cda"]``; empty or ``none`` -> no client."""
    text = (value or "").strip().lower()
    if text in ("", "none", "-"):
        return []
    return [name.strip() for name in text.split(",") if name.strip()]


def clients_for_cycle(
    when: datetime,
    weekday: int,
    daily_clients: list[str],
    requested: list[str] | None,
) -> list[str] | None:
    """Which clients a scheduled cycle runs. ``None`` means every client found.

    On the weekly day every requested client runs. On any other day only the daily clients do
    (limited to the requested ones, if ``--client`` was given); the result may be empty.
    """
    if when.weekday() == weekday:
        return requested
    daily = [name.lower() for name in daily_clients]
    return [name for name in daily if requested is None or name in requested]


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def _process(
    label: str,
    name: str,
    result,
    *,
    validate_fn,
    dataset,
    backfill: bool,
    sync_s3: bool,
    validate: bool,
    verify_s3: bool,
    config,
    client,
) -> int:
    """Validate, verify and sync one client's freshly built partitions of one dataset."""
    status = EXIT_OK
    if validate:
        report = validate_fn(name)
        if report.ok:
            logger.info("%s: %s validation OK (%d rows in %d partitions == source)",
                        name, label, report.partition_rows, report.partitions)
        else:
            for problem in report.problems:
                logger.error("%s: %s validation: %s", name, label, problem)
            return EXIT_BUILD_ERROR  # never push a partition set that does not match its source

    if verify_s3:
        problems = s3_sync.verify_client(client, config, result, dataset=dataset)
        for problem in problems:
            logger.error("%s: %s S3 verification: %s", name, label, problem)
        if problems:
            status = max(status, EXIT_S3_ERROR)
        else:
            logger.info("%s: S3 matches the local %s partitions (%d files)", name, label, len(result.files))

    if sync_s3:
        try:
            s3_sync.sync_client(
                client, config, result,
                require_backfill_marker=not backfill,
                write_backfill_marker=backfill,
                dataset=dataset,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("%s: %s S3 sync failed: %s", name, label, exc)
            status = max(status, EXIT_S3_ERROR)
    return status


def run(
    *,
    root: str | None,
    clients: list[str] | None,
    backfill: bool,
    sync_s3: bool,
    validate: bool,
    verify_s3: bool = False,
    s3_options: dict | None = None,
    s3_client=None,
    datasets: tuple[str, ...] = DATASETS,
) -> int:
    """Build (and validate / sync) every requested client. Returns the exit status.

    Per client the alerts partitions are handled first and the telemetry partitions second; a
    failure of one never prevents the other (each has its own exit status contribution, validation
    gate, backfill marker and S3 keys).
    """
    names = clients or builder.discover_clients(root)
    if not names:
        logger.error("No client with a consolidated_alerts.csv under data/alerts/golden/")
        return EXIT_BUILD_ERROR

    status = EXIT_OK
    config = client = None
    if sync_s3 or verify_s3:
        try:
            config = s3_sync.S3Config.from_env(**(s3_options or {}))
            client = s3_client or s3_sync.make_s3_client(config)
        except Exception as exc:  # noqa: BLE001
            logger.error("S3 is not usable: %s", exc)
            status = EXIT_S3_ERROR
            sync_s3 = verify_s3 = False

    common = dict(backfill=backfill, sync_s3=sync_s3, validate=validate, verify_s3=verify_s3,
                  config=config, client=client)
    for name in names:
        if "alerts" in datasets:
            try:
                result = builder.build_client(name, root)
            except Exception:  # noqa: BLE001 - one broken client must not stop the others
                logger.exception("%s: partitioning failed", name)
                status = max(status, EXIT_BUILD_ERROR)
            else:
                status = max(status, _process(
                    "alerts", name, result, validate_fn=lambda n: builder.validate_client(n, root),
                    dataset=s3_sync.ALERTS_DATASET, **common,
                ))
        if "telemetry" in datasets:
            status = max(status, _run_telemetry(name, root, common))
    return status


def _run_telemetry(name: str, root: str | None, common: dict) -> int:
    """Telemetry partitions of one client. A client with no telemetry source (EMIN publishes
    none) has nothing to partition; one whose source vanished while partitions exist is an error
    (a missing mount must not look like "no telemetry")."""
    if not telemetry_builder.has_source(name, TELEMETRY_SOURCE_FILE, root):
        existing = telemetry_layout.list_weeks(telemetry_layout.client_dir(name, root))
        if existing:
            logger.error("%s: telemetry source missing but %d telemetry partitions exist; left untouched",
                         name, len(existing))
            return EXIT_BUILD_ERROR
        logger.info("%s: no telemetry source file; no telemetry partitions to build", name)
        return EXIT_OK
    try:
        result = telemetry_builder.build_client(name, TELEMETRY_SOURCE_FILE, root)
    except Exception:  # noqa: BLE001
        logger.exception("%s: telemetry partitioning failed", name)
        return EXIT_BUILD_ERROR
    return _process(
        "telemetry", name, result, validate_fn=lambda n: telemetry_builder.validate_client(n, TELEMETRY_SOURCE_FILE, root),
        dataset=s3_sync.TELEMETRY_DATASET, **common,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Partition consolidated_alerts.csv and the alert telemetry into weekly Parquet files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Modes")[0],
    )
    parser.add_argument("--data-root", default=os.getenv("DASHBOARD_DATA_ROOT") or None,
                        help="Data root (default: $DASHBOARD_DATA_ROOT or ./data).")
    parser.add_argument("--client", action="append", dest="clients",
                        help="Only this client (repeatable). Default: every client found.")
    parser.add_argument("--dataset", choices=("all", *DATASETS), default="all",
                        help="Which partitions to build: the alerts, the telemetry, or both (default).")
    parser.add_argument("--backfill", action="store_true",
                        help="First execution over the whole history; S3 sync off unless --sync-s3.")
    parser.add_argument("--sync-s3", action="store_true",
                        help="With --backfill: also push the partitions to S3 and mark the history complete.")
    parser.add_argument("--validate", action=argparse.BooleanOptionalAction, default=None,
                        help="Compare partitions with the CSV (default: on for --backfill).")
    parser.add_argument("--verify-s3", action="store_true",
                        help="Compare S3 with the local partitions; writes nothing.")
    parser.add_argument("--schedule", action="store_true",
                        help="Run on schedule, in the foreground: every client weekly, the daily clients every day.")
    parser.add_argument("--run-on-start", action="store_true", help="With --schedule: run once immediately.")
    parser.add_argument("--daily-clients", default=_env("ALERT_PARTITIONS_DAILY_CLIENTS", DEFAULT_DAILY_CLIENTS),
                        help="With --schedule: clients also run on every non-weekly day (comma-separated, "
                             "'none' for no one).")
    parser.add_argument("--weekday", default=_env("ALERT_PARTITIONS_WEEKDAY", DEFAULT_WEEKDAY))
    parser.add_argument("--time", default=_env("ALERT_PARTITIONS_TIME", DEFAULT_TIME),
                        help="Local run time HH:MM.")
    parser.add_argument("--timezone", default=_env("ALERT_PARTITIONS_TIMEZONE", DEFAULT_TIMEZONE),
                        help="IANA zone the schedule is expressed in.")
    parser.add_argument("--bucket", default=None, help="S3 bucket (default: $ALERT_PARTITIONS_S3_BUCKET or $BUCKET_NAME).")
    parser.add_argument("--s3-prefix", default=None,
                        help=f"S3 prefix (default: $ALERT_PARTITIONS_S3_PREFIX or {s3_sync.DEFAULT_S3_PREFIX!r}).")
    parser.add_argument("--region", default=None)
    args = parser.parse_args(argv)
    if args.sync_s3 and not args.backfill:
        parser.error("--sync-s3 only applies to --backfill (the weekly run always syncs)")
    if args.schedule and (args.backfill or args.verify_s3):
        parser.error("--schedule runs the weekly mode; do not combine it with --backfill/--verify-s3")
    return args


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(REPOSITORY_ROOT / ".env")
    except ImportError:
        pass


def _run_from_args(args: argparse.Namespace, clients: list[str] | None = None) -> int:
    weekly = not args.backfill and not args.verify_s3
    return run(
        root=args.data_root,
        clients=clients if clients is not None else ([c.lower() for c in args.clients] if args.clients else None),
        backfill=args.backfill,
        sync_s3=weekly or args.sync_s3,
        validate=args.validate if args.validate is not None else args.backfill,
        verify_s3=args.verify_s3,
        s3_options={"bucket": args.bucket, "prefix": args.s3_prefix, "region": args.region},
        datasets=DATASETS if args.dataset == "all" else (args.dataset,),
    )


def schedule_forever(args: argparse.Namespace) -> int:
    zone = ZoneInfo(args.timezone)
    weekday, run_time = parse_weekday(args.weekday), parse_time(args.time)
    daily_clients = parse_clients(args.daily_clients)
    requested = [c.lower() for c in args.clients] if args.clients else None
    logger.info("Scheduled: every client on weekday=%s, daily clients %s every other day, time=%s timezone=%s",
                args.weekday, daily_clients or "(none)", run_time.isoformat(), args.timezone)
    signal.signal(signal.SIGTERM, lambda *_: _STOP.set())
    signal.signal(signal.SIGINT, lambda *_: _STOP.set())
    if args.run_on_start:
        _log_cycle(_run_from_args(args))
    while not _STOP.is_set():
        now = datetime.now(zone)
        following = next_daily_run(now, run_time)
        clients = clients_for_cycle(following, weekday, daily_clients, requested)
        if clients is not None and not clients:
            # Nothing is due that day (no daily client): sleep to the next day, do not run.
            logger.info("Next run: %s (no client due; skipped)", following.isoformat())
            if _STOP.wait(max(0.0, (following - now).total_seconds())):
                break
            continue
        logger.info("Next run: %s (%s)", following.isoformat(), "every client" if clients is None else ", ".join(clients))
        if _STOP.wait(max(0.0, (following - now).total_seconds())):
            break
        try:
            _log_cycle(_run_from_args(args, clients))
        except Exception:  # noqa: BLE001 - a failed run must not end the schedule
            logger.exception("Scheduled run crashed; the next one retries")
    return EXIT_OK


def _log_cycle(status: int) -> None:
    if status == EXIT_OK:
        logger.info("Scheduled run finished OK")
    else:
        logger.error("Scheduled run finished with exit status %d (see errors above); next run retries", status)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.getenv("ALERT_PARTITIONS_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _load_env()
    args = parse_args(argv)
    if args.schedule:
        return schedule_forever(args)
    return _run_from_args(args)


if __name__ == "__main__":
    raise SystemExit(main())
