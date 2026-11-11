"""Refresh the local data folder from S3 right before a scheduled email is built.

The app syncs `data/` only once, when it starts (`dashboard/app.py`, via
`src.data.s3_downloader.main`). A process that has been running for days would otherwise build the
08:00 summary from stale files. A scheduled send therefore runs the SAME function first.

Rules:
- Once per scheduled date per process: Emin and Capstone fire at the same minute and share the
  folder, so the second one waits for the first and reuses its result.
- Never blocks the email: any failure (no bucket configured, no network, a read-only data volume)
  is logged and the summary is built from the data already on disk, exactly as before.
- Honors the app's own `SYNC_DATA=false` switch and `config.SYNC_DATA_BEFORE_SCHEDULED_SEND`.
- Only scheduled sends sync. A manual send answers an admin who is waiting, and the admin sees the
  preview; it uses the data the dashboard is showing.
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Callable, Dict, Optional

from src.utils.logger import get_logger

from . import config

logger = get_logger(__name__)

_LOCK = threading.Lock()
_DONE: Dict[date, bool] = {}  # scheduled date -> did the sync succeed


def sync_enabled() -> bool:
    """The code constant AND the app-wide `SYNC_DATA` switch (default on) must both allow it."""
    return bool(config.SYNC_DATA_BEFORE_SCHEDULED_SEND) and config.env_flag("SYNC_DATA", True)


def _s3_sync() -> None:
    """The proper function: the one the app runs at startup."""
    from src.data.s3_downloader import main as s3_sync

    s3_sync()


def sync_before_send(scheduled_date: date, runner: Optional[Callable[[], None]] = None) -> bool:
    """Run the data sync once for `scheduled_date`. Returns True when it ran and succeeded.

    Never raises. `runner` replaces the real sync (tests).
    """
    if not sync_enabled():
        logger.info("mailing: data sync before send is disabled")
        return False
    with _LOCK:
        if scheduled_date in _DONE:
            return _DONE[scheduled_date]
        logger.info("mailing: syncing data before the scheduled send (date=%s)", scheduled_date)
        try:
            (runner or _s3_sync)()
            ok = True
            logger.info("mailing: data sync before send finished")
        except Exception as exc:  # noqa: BLE001 - the email must still go out
            ok = False
            # Class name only: an S3 error can carry bucket names or URLs.
            logger.warning(
                "mailing: data sync before send failed (%s); building the summary from the data on disk",
                type(exc).__name__,
            )
            logger.debug("mailing: data sync failure detail", exc_info=True)
        _DONE[scheduled_date] = ok
        for old in [d for d in _DONE if (scheduled_date - d).days > 2]:
            del _DONE[old]  # do not grow forever
        return ok
