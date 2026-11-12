"""
In-process scheduler for the automatic summaries.

One daemon thread wakes every `poll_seconds`, asks which clients are due *right now in
Chilean local time* and runs them. Nothing here decides who sends: the persisted marker in
`state.claim` does, so several workers (or a restart around 08:00) cannot double-send.

On by default; `MAILING_SCHEDULER_ENABLED=false` turns it off.
"""

from __future__ import annotations

import threading
from datetime import date, datetime
from typing import Callable, Optional, Set, Tuple

from src.utils.logger import get_logger

from . import config, periods, service

logger = get_logger(__name__)


class MailingScheduler:
    def __init__(
        self,
        poll_seconds: float = config.DEFAULT_SCHEDULER_POLL_SECONDS,
        runner: Callable[[str, date], str] = None,
        clock: Callable[[], datetime] = periods.now_local,
    ):
        self.poll_seconds = poll_seconds
        self._runner = runner or (lambda client, day: service.run_scheduled(client, day))
        self._clock = clock
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._handled: Set[Tuple[str, date]] = set()
        self._workers: list = []

    # -- one evaluation ----------------------------------------------------
    def tick(self, now: Optional[datetime] = None) -> list:
        """Start a run for every client due at `now`. Returns the `(client, date)` started."""
        now = now or self._clock()
        started = []
        for client, schedule in config.MAILING_SCHEDULES.items():
            day = periods.due_scheduled_date(schedule, now)
            if day is None or (client, day) in self._handled:
                continue
            self._handled.add((client, day))
            # A thread per client: one client's retry waits must not delay another's send.
            worker = threading.Thread(
                target=self._run_one, args=(client, day), name=f"mailing-{client}", daemon=True
            )
            self._workers.append(worker)
            worker.start()
            started.append((client, day))
        self._workers = [w for w in self._workers if w.is_alive()]
        # Forget old dates so the set does not grow forever.
        self._handled = {(c, d) for (c, d) in self._handled if (now.date() - d).days <= 2}
        return started

    def _run_one(self, client: str, day: date) -> None:
        try:
            self._runner(client, day)
        except Exception:  # noqa: BLE001
            logger.exception("mailing: scheduled run crashed (client=%s date=%s)", client, day)

    # -- lifecycle ---------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the loop must keep going
                logger.exception("mailing: scheduler tick failed")
            self._stop.wait(self.poll_seconds)

    def start(self) -> "MailingScheduler":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="mailing-scheduler", daemon=True)
        self._thread.start()
        logger.info(
            "mailing scheduler started (tz=%s, clients=%s)",
            config.MAILING_TIMEZONE, sorted(config.MAILING_SCHEDULES),
        )
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)


_SCHEDULER: Optional[MailingScheduler] = None
_LOCK = threading.Lock()


def start_mailing_scheduler() -> Optional[MailingScheduler]:
    """Start the scheduler in this process if enabled. Idempotent; None when disabled."""
    global _SCHEDULER
    with _LOCK:
        if _SCHEDULER is not None:
            return _SCHEDULER
        if not config.scheduler_enabled():
            logger.info("mailing scheduler disabled by MAILING_SCHEDULER_ENABLED")
            return None
        _SCHEDULER = MailingScheduler().start()
        return _SCHEDULER


def stop_mailing_scheduler() -> None:
    global _SCHEDULER
    with _LOCK:
        if _SCHEDULER is not None:
            _SCHEDULER.stop()
        _SCHEDULER = None
