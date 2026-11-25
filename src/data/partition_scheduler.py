"""
In-app schedule of the alert partitioner (the only scheduler it has).

``scripts/partition_alerts.py`` builds the weekly Parquet partitions and syncs them to S3; it is the
only code that does, and it stays a manual tool (``--backfill``, ``--validate``, ``--sync-s3``,
``--verify-s3``). THIS module decides *when* the app runs it, the same way ``src/mailing`` decides
when it sends: one daemon thread wakes every ``POLL_SECONDS``, asks which job is due *right now in
the configured time zone* and starts it. Nothing here decides who runs: the persisted marker
(:func:`claim`) does, so several workers (or a restart around the scheduled time) cannot run a job
twice.

Jobs (``America/Santiago``; every value is an environment variable, defaults below)
    weekly  Wednesday 08:00   every client            ``ALERT_PARTITIONS_WEEKDAY`` / ``_TIME``
    daily   every day 11:30   the daily clients       ``ALERT_PARTITIONS_DAILY_CLIENTS`` (default
                              ``emin``; ``none`` = no daily job) / ``ALERT_PARTITIONS_DAILY_TIME``
The upstream alert creation runs at 07:00, so the weekly job leaves it an hour; the alert-summary
e-mail of each client leaves the partitioner at least 30 minutes (``src/mailing/config.py``).

Why a subprocess. The job runs ``python scripts/partition_alerts.py`` in its own process: the
existing logic is reused untouched, its exit status (0 ok, 1 build/validation error, 2 S3 error) is
the run's outcome, and the CSV rebuild (hundreds of MB of telemetry) neither holds the GIL of, nor
adds to the memory of, the process that serves the dashboard. The web request threads are never
blocked.

Run status. The marker of a run records ``running`` -> ``ok`` / ``failed`` (with the exit code). The
e-mail reads it through :func:`partition_run_problem` and is NOT sent unless this period's run
finished ``ok``. Nothing retries: a failed run is logged as an error and waits for the next
scheduled one (or a manual script run).

Runs only in production (``DEPLOY_STATUS``); ``ALERT_PARTITIONS_SCHEDULER_ENABLED=false`` also turns
it off there.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import date, datetime, time as day_time, timedelta, timezone
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

from src.mailing import config as env_config
from src.utils.logger import get_logger

logger = get_logger(__name__)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "partition_alerts.py"

JOB_WEEKLY = "weekly"
JOB_DAILY = "daily"

STATUS_RUNNING = "running"
STATUS_OK = "ok"
STATUS_FAILED = "failed"

DEFAULT_TIMEZONE = "America/Santiago"
DEFAULT_WEEKDAY = "wednesday"
DEFAULT_TIME = "08:00"
DEFAULT_DAILY_CLIENTS = "emin"
# EMIN's CSV reaches S3 around 11:10 (24/11: 11:12 Chile), so the daily run waits until 11:30 and leaves the
# 12:00 e-mail 30 minutes. A run at 10:30 always read the previous day's file.
DEFAULT_DAILY_TIME = "11:30"
DEFAULT_GRACE_MINUTES = 15
DEFAULT_TIMEOUT_SECONDS = 3600.0
POLL_SECONDS = 30.0

_WEEKDAYS = {
    "monday": 0, "lunes": 0, "tuesday": 1, "martes": 1, "wednesday": 2, "miercoles": 2,
    "thursday": 3, "jueves": 3, "friday": 4, "viernes": 4, "saturday": 5, "sabado": 5,
    "sunday": 6, "domingo": 6,
}


# ---------------------------------------------------------------------------
# Settings (read from the environment on every use, so a test or a redeploy changes them)
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


def parse_clients(value: Optional[str]) -> List[str]:
    """``"emin, cda"`` -> ``["emin", "cda"]``; empty or ``none`` -> no client."""
    text = (value or "").strip().lower()
    if text in ("", "none", "-"):
        return []
    return [name.strip() for name in text.split(",") if name.strip()]


@dataclass(frozen=True)
class Settings:
    timezone: str
    weekday: int
    weekly_time: day_time
    daily_clients: Tuple[str, ...]
    daily_time: day_time
    grace_minutes: int
    timeout_seconds: float


def load_settings() -> Settings:
    def number(name: str, default: float) -> float:
        try:
            return max(0.0, float(env_config.get_env(name, str(default))))
        except ValueError:
            return default

    return Settings(
        timezone=env_config.get_env("ALERT_PARTITIONS_TIMEZONE", DEFAULT_TIMEZONE),
        weekday=parse_weekday(env_config.get_env("ALERT_PARTITIONS_WEEKDAY", DEFAULT_WEEKDAY)),
        weekly_time=parse_time(env_config.get_env("ALERT_PARTITIONS_TIME", DEFAULT_TIME)),
        daily_clients=tuple(parse_clients(env_config.get_env("ALERT_PARTITIONS_DAILY_CLIENTS", DEFAULT_DAILY_CLIENTS))),
        daily_time=parse_time(env_config.get_env("ALERT_PARTITIONS_DAILY_TIME", DEFAULT_DAILY_TIME)),
        grace_minutes=int(number("ALERT_PARTITIONS_GRACE_MINUTES", DEFAULT_GRACE_MINUTES)),
        timeout_seconds=number("ALERT_PARTITIONS_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
    )


def disabled_reason() -> Optional[str]:
    """Why the schedule does not run on this machine, or None when it does (same rule as the mailer)."""
    if not env_config.is_production():
        return "the environment is not production"
    if not env_config.env_flag("ALERT_PARTITIONS_SCHEDULER_ENABLED", True):
        return "ALERT_PARTITIONS_SCHEDULER_ENABLED=false"
    return None


def get_state_dir() -> Path:
    """Where the run markers live. Must survive restarts and be shared by the workers (``logs/`` is a
    mounted volume)."""
    configured = env_config.get_env("ALERT_PARTITIONS_STATE_DIR")
    return Path(configured) if configured else REPOSITORY_ROOT / "logs" / "partitions"


def now_local(settings: Optional[Settings] = None) -> datetime:
    return datetime.now(ZoneInfo((settings or load_settings()).timezone))


# ---------------------------------------------------------------------------
# Run markers: exactly-once per (job, date) and the run status the e-mail reads
# ---------------------------------------------------------------------------

def _marker_path(job: str, day: date) -> Path:
    return get_state_dir() / f"partitions_{job}_{day.isoformat()}.json"


def claim(job: str, day: date) -> bool:
    """Atomically take ownership of a run (``O_CREAT | O_EXCL``). True for exactly one caller.

    The claim is made BEFORE running: if the process dies mid-run nothing re-runs it (the marker
    stays ``running`` and the e-mail refuses to send until a run finishes ``ok``).
    """
    path = _marker_path(job, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"job": job, "date": day.isoformat(), "status": STATUS_RUNNING, "pid": os.getpid(),
                   "started_at": datetime.now(timezone.utc).isoformat()}, handle)
    return True


def finish(job: str, day: date, status: str, exit_code: Optional[int] = None, detail: Optional[str] = None) -> None:
    """Record the outcome of the run. Written atomically; best effort (the claim holds)."""
    path = _marker_path(job, day)
    data = read(job, day) or {"job": job, "date": day.isoformat()}
    data.update(status=status, finished_at=datetime.now(timezone.utc).isoformat())
    if exit_code is not None:
        data["exit_code"] = exit_code
    if detail:
        data["detail"] = detail
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logger.warning("partitioner: could not write the run status %s", path.name)


def read(job: str, day: date) -> Optional[dict]:
    try:
        return json.loads(_marker_path(job, day).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def partition_run_problem(job: str, send_date: date) -> Optional[str]:
    """Why the e-mail of ``send_date`` must NOT be built from this period's partitions, or None.

    ``weekly``: the run of the ISO week of ``send_date`` (Monday through the send date).
    ``daily``: the run of ``send_date`` itself. The newest run in that range decides. It must exist
    (otherwise "never ran") and be ``ok`` (otherwise "failed" / "still running").
    """
    first = send_date - timedelta(days=send_date.weekday()) if job == JOB_WEEKLY else send_date
    runs = [(day, read(job, day)) for day in (first + timedelta(days=i) for i in range((send_date - first).days + 1))]
    runs = [(day, data) for day, data in runs if data]
    label = f"{job} partitioner run of {first.isoformat()}..{send_date.isoformat()}"
    if not runs:
        return f"no {label} was found: it did not run"
    day, data = max(runs, key=lambda item: item[0])
    status = data.get("status")
    if status == STATUS_OK:
        return None
    if status == STATUS_FAILED:
        return f"the {job} partitioner run of {day.isoformat()} failed (exit status {data.get('exit_code')})"
    return f"the {job} partitioner run of {day.isoformat()} has not finished (status {status!r}): still running or interrupted"


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

_RUN_LOCK = threading.Lock()  # one partitioner at a time in this process (weekly and daily never overlap)

Runner = Callable[[Sequence[str], float], int]


def build_command(job: str, settings: Optional[Settings] = None) -> List[str]:
    """The weekly job runs every client; the daily one only the daily clients. Both are the normal
    (non ``--backfill``) run of the script: rebuild what changed, then sync to S3."""
    settings = settings or load_settings()
    command = [sys.executable, str(SCRIPT_PATH)]
    if job == JOB_DAILY:
        for client in settings.daily_clients:
            command += ["--client", client]
    return command


def _run_subprocess(command: Sequence[str], timeout_seconds: float) -> int:
    """Run the script, stream its log lines into the app log, return its exit status."""
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    process = subprocess.Popen(
        list(command), cwd=str(REPOSITORY_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    timer = threading.Timer(timeout_seconds, process.kill) if timeout_seconds > 0 else None
    if timer:
        timer.start()
    try:
        for line in process.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line:
                (logger.error if " ERROR " in line or "Traceback" in line else logger.info)("partitioner | %s", line)
        return process.wait()
    finally:
        if timer:
            timer.cancel()
        if process.poll() is None:
            process.kill()


def run_job(job: str, day: Optional[date] = None, runner: Optional[Runner] = None) -> str:
    """Run one scheduled partitioner job. Returns ``ok``, ``failed`` or ``skipped``.

    ``skipped``: another worker (or an earlier run) already owns the marker of ``(job, day)``.
    A failure is logged as an error and recorded in the marker; nothing retries it.
    """
    settings = load_settings()
    day = day or now_local(settings).date()
    if job == JOB_DAILY and not settings.daily_clients:
        return "skipped"
    if not claim(job, day):
        logger.info("partitioner: %s run already claimed (date=%s)", job, day)
        return "skipped"

    command = build_command(job, settings)
    with _RUN_LOCK:
        logger.info("partitioner: %s run started (date=%s clients=%s)", job, day,
                    list(settings.daily_clients) if job == JOB_DAILY else "all")
        started = datetime.now(timezone.utc)
        try:
            code = (runner or _run_subprocess)(command, settings.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - a scheduler thread must survive anything
            logger.exception("partitioner: %s run crashed (date=%s)", job, day)
            finish(job, day, STATUS_FAILED, detail=type(exc).__name__)
            return "failed"
    seconds = (datetime.now(timezone.utc) - started).total_seconds()
    if code == 0:
        finish(job, day, STATUS_OK, exit_code=0)
        logger.info("partitioner: %s run finished OK in %.0fs (date=%s)", job, seconds, day)
        return "ok"
    finish(job, day, STATUS_FAILED, exit_code=code)
    logger.error(
        "partitioner: %s run FAILED with exit status %s after %.0fs (date=%s): 1 = build/validation error, "
        "2 = S3 sync error; the e-mail that depends on it will not be sent", job, code, seconds, day,
    )
    return "failed"


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

def due_job_dates(now: datetime, settings: Optional[Settings] = None) -> List[Tuple[str, date]]:
    """The ``(job, date)`` due right now: from the scheduled moment until ``grace_minutes`` later
    (absorbs scheduler jitter and a quick restart; a longer outage is a missed run, not a catch-up).
    The wall-clock time is built in the zone, so it holds across daylight-saving changes."""
    settings = settings or load_settings()
    zone = ZoneInfo(settings.timezone)
    local = now.astimezone(zone)
    day = local.date()
    grace = timedelta(minutes=settings.grace_minutes)
    due: List[Tuple[str, date]] = []
    candidates = [(JOB_WEEKLY, day.weekday() == settings.weekday, settings.weekly_time),
                  (JOB_DAILY, bool(settings.daily_clients), settings.daily_time)]
    for job, on_day, at in candidates:
        if not on_day:
            continue
        start = datetime.combine(day, at, tzinfo=zone)
        if start <= local < start + grace:
            due.append((job, day))
    return due


class PartitionScheduler:
    def __init__(
        self,
        poll_seconds: float = POLL_SECONDS,
        runner: Optional[Callable[[str, date], str]] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.poll_seconds = poll_seconds
        self._runner = runner or (lambda job, day: run_job(job, day))
        self._clock = clock or now_local
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._handled: Set[Tuple[str, date]] = set()
        self._workers: list = []

    def tick(self, now: Optional[datetime] = None) -> list:
        """Start every job due at ``now`` in its own thread. Returns the ``(job, date)`` started."""
        now = now or self._clock()
        started = []
        for job, day in due_job_dates(now):
            if (job, day) in self._handled:
                continue
            self._handled.add((job, day))
            worker = threading.Thread(target=self._run_one, args=(job, day), name=f"partitioner-{job}", daemon=True)
            self._workers.append(worker)
            worker.start()
            started.append((job, day))
        self._workers = [w for w in self._workers if w.is_alive()]
        self._handled = {(j, d) for (j, d) in self._handled if (now.date() - d).days <= 2}
        return started

    def _run_one(self, job: str, day: date) -> None:
        try:
            self._runner(job, day)
        except Exception:  # noqa: BLE001
            logger.exception("partitioner: scheduled run crashed (job=%s date=%s)", job, day)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the loop must keep going
                logger.exception("partitioner: scheduler tick failed")
            self._stop.wait(self.poll_seconds)

    def start(self) -> "PartitionScheduler":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="partitioner-scheduler", daemon=True)
        self._thread.start()
        settings = load_settings()
        logger.info(
            "partitioner scheduler started (tz=%s, weekly: weekday=%d %s all clients; daily: %s %s)",
            settings.timezone, settings.weekday, settings.weekly_time.strftime("%H:%M"),
            list(settings.daily_clients) or "none", settings.daily_time.strftime("%H:%M"),
        )
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)


_SCHEDULER: Optional[PartitionScheduler] = None
_LOCK = threading.Lock()


def start_partition_scheduler() -> Optional[PartitionScheduler]:
    """Start the schedule in this process if enabled. Idempotent; None when disabled."""
    global _SCHEDULER
    with _LOCK:
        if _SCHEDULER is not None:
            return _SCHEDULER
        reason = disabled_reason()
        if reason is not None:
            logger.info("partitioner scheduler not started: %s", reason)
            return None
        _SCHEDULER = PartitionScheduler().start()
        return _SCHEDULER


def stop_partition_scheduler() -> None:
    global _SCHEDULER
    with _LOCK:
        if _SCHEDULER is not None:
            _SCHEDULER.stop()
        _SCHEDULER = None
