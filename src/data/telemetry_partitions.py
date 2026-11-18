"""Partitioned alert telemetry: on-disk layout and the dashboard's read path.

The per-alert telemetry (sensor readings, limits and GPS of the window around each alert) is
published as one wide CSV per client. A scheduled job (``scripts/partition_alerts.py``) splits it
into Parquet files that live **beside the alerts partitions**, with their own file names::

    data/alerts/golden/{client}/{week}/telemetry.parquet
    data/alerts/golden/{client}/_telemetry_index.parquet

Every reader of that telemetry (the *Evidencia de Telemetría* section of *Vista Detallada*, the
data-source freshness chip, the Campbell AI assistant) goes through this module. Nothing at runtime
opens the source CSV: only the partitioning script does, and it is the one place that knows its name.

Layout
------
* ``{week}`` is the ISO date of the **Monday** that starts the week of the telemetry's **alert**
  (``alert_partitions.week_starts`` on the alert's UTC-naive ``Timestamp``), *not* of the
  telemetry row. All the rows of one alert therefore live in one file even when the event crosses a
  Sunday/Monday boundary. One file holds every unit of the week (measured on capstone: 24 files /
  53 MB, against 315 files / 72 MB with a ``{unit}`` level, with no difference in the time to read
  one alert; see ``change_summary.md``).
* ``undated/`` holds the telemetry of alerts whose timestamp cannot be parsed, as for the alerts.
* ``unmatched/`` holds the rows that belong to **no** alert. They are never dropped: they keep
  the row totals equal to the source and the script reports their count. No reader asks for that
  folder by alert, but a full-history read (limits across all units) includes it, like the CSV did.

The key that links telemetry to alerts
--------------------------------------
``telemetry.AlertID`` equals the alert's ``TelemetryID`` **or** its ``FusionID`` (capstone keys on
the FusionID, CDA on the per-unit ``TelemetryID``), and ``telemetry.Unit`` equals the alert's
``UnitId``. Both comparisons are on the stripped text, exactly as the dashboard always matched them
(``AlertID`` is only unique within a unit).

The index
---------
``_telemetry_index.parquet`` has one light row per distinct
``(AlertID, Unit, Trigger, Alert_TimeStart)`` of the source, in order of first appearance, with the
source's own values and dtypes plus ``week``, ``rows`` (telemetry rows of the group), ``first_row``
(position of its first row in the source) and ``part_sha`` (a hash of the partition file that
holds it). It lets a reader find which week holds an alert **without reading any partition**, answers
"which signals/units exist" without reading rows, and — because ``part_sha`` changes whenever a
partition's content does — changes (file size/mtime) whenever any partition changes, so caches keyed
on the index file never serve a stale generation.

Partition files are replaced atomically (temp name, then ``os.replace``); a reader opens exactly
``{week}/telemetry.parquet`` and never globs, so it sees a complete old file or a complete new one.
A missing week, an alert without telemetry, or a client without partitions is simply empty.
"""

from __future__ import annotations

import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional, Sequence

import pandas as pd
import pyarrow.parquet as pq

from src.data import alert_partitions as alerts_layout
from src.data.alert_partitions import (  # noqa: F401  (re-exported: one import for callers)
    UNDATED_WEEK,
    AlertPartitionError,
    client_dir,
    data_root,
    is_week_name,
    week_of,
    week_starts,
)

TELEMETRY_FILE = "telemetry.parquet"
INDEX_FILE = "_telemetry_index.parquet"
BACKFILL_MARKER_FILE = "_telemetry_backfill_complete.json"
UNMATCHED_WEEK = "unmatched"

# Footer entry holding the position each row of a partition had in the source CSV: it restores the
# source's row order across files without adding a column the source does not have.
ROW_IDS_KEY = b"telemetry.source_row_ids"

_READ_RETRIES = 4


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def is_telemetry_week(name: str) -> bool:
    return is_week_name(name) or name == UNMATCHED_WEEK


def partition_relpath(week: str) -> str:
    return f"{week}/{TELEMETRY_FILE}"


def partition_path(directory: Path, week: str) -> Path:
    return directory / week / TELEMETRY_FILE


def index_path(directory: Path) -> Path:
    return directory / INDEX_FILE


def _week_order(name: str) -> tuple[int, str]:
    # Dated weeks oldest first, then ``undated``, then ``unmatched``.
    return (2 if name == UNMATCHED_WEEK else 1 if name == UNDATED_WEEK else 0, name)


def list_weeks(directory: Path) -> list[str]:
    """Folders that hold a telemetry partition (directory listings only: no data is read)."""
    weeks = [
        name for name in alerts_layout._subdirs(directory)
        if is_telemetry_week(name) and partition_path(directory, name).is_file()
    ]
    return sorted(weeks, key=_week_order)


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def index_signature(directory: Path) -> Optional[tuple[int, int]]:
    """``(mtime_ns, size)`` of the index (it changes with every regenerated partition), or None
    when the client has no telemetry partitions."""
    try:
        stat = index_path(directory).stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def has_telemetry(directory: Path) -> bool:
    return index_signature(directory) is not None


@lru_cache(maxsize=16)
def _read_index_cached(path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    last_error: Optional[Exception] = None
    for attempt in range(_READ_RETRIES):
        try:
            return pq.read_table(path).to_pandas()
        except OSError as exc:  # e.g. a transient sharing violation on Windows
            last_error = exc
            time.sleep(0.05 * (2 ** attempt))
    raise AlertPartitionError(f"Could not read telemetry index {path}: {last_error}") from last_error


def read_index(directory: Path) -> pd.DataFrame:
    """The telemetry index (see the module docstring); empty when the client has none."""
    path = index_path(directory)
    try:
        stat = path.stat()
    except OSError:
        return pd.DataFrame()
    try:
        return _read_index_cached(str(path), stat.st_mtime_ns, stat.st_size).copy()
    except AlertPartitionError:
        if not path.is_file():  # replaced or removed between the stat and the read: empty
            return pd.DataFrame()
        raise


def weeks_of(index: pd.DataFrame) -> list[str]:
    """The distinct weeks of (a selection of) the index, in storage order."""
    if index.empty or "week" not in index.columns:
        return []
    return sorted(set(index["week"].dropna()), key=_week_order)


def text_key(values: pd.Series) -> pd.Series:
    """The stripped text a value is compared as (alert ids are strings such as ``CAP-...`` or
    small integers; never coerce them to numbers)."""
    return values.astype(str).str.strip()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def read_weeks(
    directory: Path,
    weeks: Iterable[str],
    columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Every row of the given weeks, in the source's row order. A week without a partition is
    skipped; nothing here raises for something missing."""
    paths = [partition_path(directory, week) for week in dict.fromkeys(weeks)]
    paths = [path for path in paths if path.is_file()]
    return alerts_layout.read_paths(paths, columns, row_ids_key=ROW_IDS_KEY)


def read_alert(directory: Path, alert_ids: Sequence[str], unit_id: str) -> pd.DataFrame:
    """The telemetry rows of one alert of one unit, read from the week(s) that hold it.

    ``alert_ids`` are the identifiers the telemetry may be keyed by (the alert's ``TelemetryID``
    and ``FusionID``). The week is found in the index, so no other partition is opened. The rows
    are the source's, in source order, matched on stripped text for ``AlertID`` and ``Unit``.
    Empty when the alert has no telemetry (or the week's file is not there yet).
    """
    keys = tuple(dict.fromkeys(str(value).strip() for value in alert_ids if str(value).strip()))
    unit = str(unit_id or "").strip()
    if not keys or not unit:
        return pd.DataFrame()
    index = read_index(directory)
    if index.empty or not {"AlertID", "Unit", "week"} <= set(index.columns):
        return pd.DataFrame()
    hits = text_key(index["AlertID"]).isin(keys) & text_key(index["Unit"]).eq(unit)
    frame = read_weeks(directory, weeks_of(index[hits]))
    if frame.empty:
        return pd.DataFrame()
    rows = text_key(frame["AlertID"]).isin(keys) & text_key(frame["Unit"]).eq(unit)
    return frame[rows].reset_index(drop=True)


def schema_columns(directory: Path) -> list[str]:
    """Column names of the telemetry, read from one partition's footer (every partition has the
    same schema). Empty when there are no partitions."""
    for week in list_weeks(directory):
        try:
            return [str(name) for name in pq.read_schema(partition_path(directory, week)).names]
        except OSError:
            continue
    return []


def total_rows(directory: Path) -> int:
    """Telemetry rows of the whole history, from the index (no partition is opened)."""
    index = read_index(directory)
    if index.empty or "rows" not in index.columns:
        return 0
    return int(index["rows"].sum())
