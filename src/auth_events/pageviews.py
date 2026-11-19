"""Capture of page views (TR-6, items 3, 4 and 7).

`record_page_view` is what the Dash hook calls for every detected page or tab opening. It is made
for the request path: it only appends a small record to an in-memory buffer (no S3 call, no registry
lookup, no JSON) and returns. A background thread does everything that can be slow:

  * every `flush_seconds` (default 20 minutes) or as soon as the buffer holds `flush_size` records,
    but only inside the flush window (default 07:00-22:00 display time; views recorded outside it
    wait in the buffer for the window to open), and always once more on graceful shutdown, it resolves each record into a full `page_view` event (user type and client
    from `users.json`, `page_id` from `pages.json`), groups them by the UTC date of their
    timestamp and writes one JSON Lines object per date with a single PUT to a new unique key
    (`auth_events/raw/dt=<day>/pv_<stamp>_<batch_id>.jsonl`). Nothing under `auth_events/` is ever
    read, listed or overwritten.
  * a failed PUT is retried 3 times with backoff; after the last failure the whole payload is
    logged at ERROR so it can be replayed.
  * the buffer is capped: past `buffer_cap` records the oldest are dropped, with an ERROR.

Capture is best-effort. Nothing here raises into the caller, and with `AUTH_EVENTS_PAGE_VIEWS`
off (the default) nothing is recorded and no thread is started.
"""

import atexit
import json
import os
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.auth_events import settings
from src.auth_events.events import (
    UNREGISTERED_PAGE_ID, build_page_view_event, batch_key, encode_batch, format_timestamp, validate_event,
)
from src.auth_events.registry import (
    get_pages_or_none, get_registry_or_none, normalize_path, resolve_user,
)
from src.auth_events.storage import Storage, get_storage
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_RETRIES = 3
BACKOFF_SECONDS = (0.5, 1.0, 2.0)
_DEDUP_PRUNE_AT = 2048


class PageViewRecorder:
    def __init__(self, storage_factory=get_storage, sleep=time.sleep, monotonic=time.monotonic, clock=None):
        self._storage_factory = storage_factory
        self._sleep = sleep
        self._monotonic = monotonic
        self._clock = clock or (lambda: datetime.now(ZoneInfo(settings.display_timezone())))
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._buffer: list[dict] = []
        self._recent: "OrderedDict[tuple, float]" = OrderedDict()
        self._thread: threading.Thread | None = None
        self._pid = os.getpid()

    # -- request path ---------------------------------------------------------------------------

    def record(self, username: str, path: str, tab: str | None = None) -> bool:
        """Buffer one page view. True when it was recorded (not disabled, not a duplicate)."""
        try:
            if not settings.page_views_enabled() or not username or not path:
                return False
            path = normalize_path(path)
            now = self._monotonic()
            pending = {
                "event_id": str(uuid.uuid4()),
                "moment": datetime.now(timezone.utc),
                "username": username,
                "path": path,
                "tab": tab or None,
                "environment": settings.current_environment(),
            }
            with self._lock:
                self._reset_after_fork()
                if self._is_duplicate(username, path, pending["tab"], now):
                    return False
                self._buffer.append(pending)
                dropped = len(self._buffer) - settings.page_view_buffer_cap()
                if dropped > 0:
                    del self._buffer[:dropped]
                    logger.error("Page-view buffer is full (cap %d): dropped the %d oldest events",
                                 settings.page_view_buffer_cap(), dropped)
                full = len(self._buffer) >= settings.page_view_flush_size()
                self._ensure_thread()
            if full:
                self._wake.set()
            return True
        except Exception as exc:  # noqa: BLE001 - capture must never affect navigation
            logger.error("Could not record a page view: %s: %s", type(exc).__name__, exc)
            return False

    def _is_duplicate(self, username: str, path: str, tab: str | None, now: float) -> bool:
        window = settings.page_view_dedup_seconds()
        key = (username, path, tab)
        last = self._recent.get(key)
        self._recent[key] = now
        self._recent.move_to_end(key)
        if len(self._recent) > _DEDUP_PRUNE_AT:
            for stale in [k for k, t in self._recent.items() if now - t > max(window, 1.0)]:
                del self._recent[stale]
        return last is not None and now - last < window

    def _reset_after_fork(self) -> None:
        """A forked worker inherits the parent's buffer and thread handle; neither is its own."""
        if self._pid != os.getpid():
            self._pid = os.getpid()
            self._buffer = []
            self._recent = OrderedDict()
            self._thread = None
            self._stop = threading.Event()
            self._wake = threading.Event()

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="page-view-flusher", daemon=True)
        self._thread.start()

    # -- background flush -----------------------------------------------------------------------

    def _run(self) -> None:
        stop, wake = self._stop, self._wake
        while not stop.is_set():
            wake.wait(timeout=settings.page_view_flush_seconds())
            wake.clear()
            if stop.is_set():
                break
            if not self.in_flush_window():
                continue  # outside 07:00-22:00 the views wait in the buffer (shutdown still flushes them)
            try:
                self.flush()
            except Exception as exc:  # noqa: BLE001
                logger.error("Page-view flush failed unexpectedly: %s: %s", type(exc).__name__, exc)

    def in_flush_window(self) -> bool:
        window = settings.page_view_flush_window()
        if window is None:
            return True
        start, end = window
        now = self._clock()
        minute = now.hour * 60 + now.minute
        return start <= minute < end if start <= end else (minute >= start or minute < end)

    def pending(self) -> int:
        with self._lock:
            return len(self._buffer)

    def flush(self) -> list[str]:
        """Write the buffered views now. Returns the keys that were stored."""
        with self._lock:
            batch, self._buffer = self._buffer, []
        if not batch:
            return []

        events = self._resolve(batch)
        by_day: dict[str, list[dict]] = {}
        for event in events:
            by_day.setdefault(event["timestamp_utc"][:10], []).append(event)
        if not by_day:
            return []

        try:
            storage = self._storage_factory()
        except Exception as exc:  # noqa: BLE001
            logger.error("Page-view storage is unavailable (%s: %s)", type(exc).__name__, exc)
            storage = None
        flushed_at = datetime.now(timezone.utc)
        batch_id = uuid.uuid4().hex[:12]
        stored: list[str] = []
        for day in sorted(by_day):
            day_events = sorted(by_day[day], key=lambda e: (e["timestamp_utc"], e["event_id"]))
            body = encode_batch(day_events)
            if storage is None:
                logger.error("Page views NOT stored (no storage configured); replay them with this payload: %s",
                             body.decode("utf-8").strip())
                continue
            key = batch_key(day, flushed_at, batch_id)
            if self._put_with_retry(storage, key, body, len(day_events)):
                stored.append(key)
        return stored

    def _resolve(self, batch: list[dict]) -> list[dict]:
        registry = get_registry_or_none()
        pages = get_pages_or_none()
        events = []
        for item in batch:
            try:
                user_type, client_id = resolve_user(registry, item["username"])
                entry = pages.match(item["path"], item["tab"]) if pages is not None else None
                events.append(validate_event(build_page_view_event(
                    item["username"], user_type, client_id, item["environment"],
                    entry["page_id"] if entry else UNREGISTERED_PAGE_ID, item["path"], item["tab"],
                    moment=item["moment"], event_id=item["event_id"],
                )))
            except Exception as exc:  # noqa: BLE001
                logger.error("Page view could not be built (%s: %s); payload: %s", type(exc).__name__, exc,
                             json.dumps({"username": item.get("username"), "path": item.get("path"),
                                         "tab": item.get("tab"), "event_id": item.get("event_id"),
                                         "timestamp_utc": format_timestamp(item["moment"])}, ensure_ascii=False))
        return events

    def _put_with_retry(self, storage: Storage, key: str, body: bytes, count: int) -> bool:
        for attempt in range(MAX_RETRIES + 1):
            try:
                storage.put(key, body, "application/x-ndjson")
                return True
            except Exception as exc:  # noqa: BLE001
                if attempt == MAX_RETRIES:
                    logger.error(
                        "%d page views NOT stored after %d retries (%s: %s); replay them with this payload for %s: %s",
                        count, MAX_RETRIES, type(exc).__name__, exc, key, body.decode("utf-8").strip(),
                    )
                    return False
                self._sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
        return False

    def shutdown(self) -> None:
        """Graceful shutdown: stop the thread and write what is still buffered."""
        try:
            self._stop.set()
            self._wake.set()
            self.flush()
        except Exception as exc:  # noqa: BLE001
            logger.error("Page-view flush on shutdown failed: %s: %s", type(exc).__name__, exc)


_recorder = PageViewRecorder()
atexit.register(lambda: _recorder.shutdown())


def get_recorder() -> PageViewRecorder:
    return _recorder


def record_page_view(username: str, path: str, tab: str | None = None) -> bool:
    return _recorder.record(username, path, tab)


def set_recorder_for_tests(recorder: PageViewRecorder | None) -> PageViewRecorder:
    global _recorder
    _recorder = recorder or PageViewRecorder()
    return _recorder
