"""
Persisted exactly-once marker for scheduled sends, keyed by `(client, scheduled date)`.

A marker is a file created atomically (`O_CREAT | O_EXCL`): whichever process or thread
creates it owns that scheduled run, every other one gets `False` from :func:`claim`. The
file lives on disk (default `logs/mailing`, a mounted volume), so it is shared by all
workers and survives restarts. The claim is made BEFORE sending, which makes the run
at-most-once: if the process dies mid-send, nothing re-sends it (that would be the
catch-up flow, out of scope).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from . import config


def _marker_path(client: str, scheduled_date: date) -> Path:
    client = config.normalize_client(client)
    return config.get_state_dir() / f"scheduled_{client}_{scheduled_date.isoformat()}.json"


def claim(client: str, scheduled_date: date) -> bool:
    """Atomically take ownership of a scheduled run. True for exactly one caller."""
    path = _marker_path(client, scheduled_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "client": config.normalize_client(client),
                "scheduled_date": scheduled_date.isoformat(),
                "claimed_at": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "status": "sending",
            },
            handle,
        )
    return True


def finish(client: str, scheduled_date: date, status: str, detail: Optional[str] = None) -> None:
    """Record the outcome (`sent` / `failed`) in the marker. Best effort: the claim holds."""
    path = _marker_path(client, scheduled_date)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"client": config.normalize_client(client), "scheduled_date": scheduled_date.isoformat()}
    data.update(status=status, finished_at=datetime.now(timezone.utc).isoformat())
    if detail:
        data["detail"] = detail
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def read(client: str, scheduled_date: date) -> Optional[dict]:
    try:
        return json.loads(_marker_path(client, scheduled_date).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
