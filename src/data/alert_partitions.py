"""Partitioned alert storage: on-disk layout and the dashboard's read path.

``data/alerts/golden/{client}/consolidated_alerts.csv`` is the *source*. A scheduled job
(``scripts/partition_alerts.py``) splits it into Parquet files::

    data/alerts/golden/{client}/{week}/file.parquet
    data/alerts/golden/{client}/_alert_index.parquet

* ``{week}`` is the ISO date (``YYYY-MM-DD``) of the **Monday** that starts the alert's week,
  computed on the UTC-naive ``Timestamp`` with the same ``W-SUN`` period the *Evolución
  temporal* chart uses, so a partition is exactly one bar of that chart. Alerts whose
  timestamp cannot be parsed go to ``undated``. One file holds every unit of the week: a week is
  small (about a hundred alerts for the largest client), so splitting it further by unit only
  multiplied files and object requests without saving reads. Unit selection is a row filter.
* ``_alert_index.parquet`` holds one light row per alert (id, unit, system, trigger signal,
  week, source row number). It feeds the filter options (which are offered from the whole
  history) and locates one alert by id, without reading any partition.

This module is the *read* half and imports nothing S3-related: the dashboard resolves
partitions below the same data root it already uses for every other file (locally, or the
folder synced from S3), so it needs no extra configuration. The write half lives in
`src.data.alert_partition_builder`, which imports the layout helpers from here so both sides
agree on names.

Partition files are replaced atomically (write to a temp name, then ``os.replace``) and a
reader opens exactly ``{week}/file.parquet`` — it never globs — so it can only ever see
a complete old file or a complete new one. A missing week is simply empty.
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, Optional, Sequence

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

PARTITION_FILE = "file.parquet"
INDEX_FILE = "_alert_index.parquet"
BACKFILL_MARKER_FILE = "_backfill_complete.json"
SOURCE_FILE = "consolidated_alerts.csv"
UNDATED_WEEK = "undated"

# Parquet key-value metadata: the position each row of the partition had in the source CSV.
# It lets the reader restore the source's row order (and with it the order of alerts that
# share a timestamp) without adding a column the CSV does not have.
ROW_IDS_KEY = b"alerts.source_row_ids"

_WEEK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_READ_RETRIES = 4
_MAX_READ_WORKERS = 8


class AlertPartitionError(RuntimeError):
    """A partition that exists could not be read (never raised for a missing one)."""


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def data_root(root: str | os.PathLike | None = None) -> Path:
    """The dashboard's data root, resolved like `src.data.loaders._data_path`."""
    if root is not None:
        return Path(root).expanduser()
    return Path(os.getenv("DASHBOARD_DATA_ROOT", "data")).expanduser()


def client_dir(client: str, root: str | os.PathLike | None = None) -> Path:
    return data_root(root) / "alerts" / "golden" / (client or "").lower()


def week_starts(timestamps: pd.Series) -> pd.Series:
    """``YYYY-MM-DD`` of the Monday of each (UTC-naive) timestamp's week; ``undated`` for NaT.

    The expression is the one `create_alerts_per_week_chart` uses for its bars
    (``to_period('W-SUN').start_time``), so the partition a row lands in and the week bar
    it is counted in can never disagree.
    """
    text = timestamps.dt.to_period("W-SUN").dt.start_time.dt.strftime("%Y-%m-%d")
    return text.where(timestamps.notna(), UNDATED_WEEK)


def week_of(timestamp: pd.Timestamp) -> str:
    """`week_starts` for one UTC-naive timestamp."""
    return pd.Timestamp(timestamp).to_period("W-SUN").start_time.strftime("%Y-%m-%d")


def partition_relpath(week: str) -> str:
    return f"{week}/{PARTITION_FILE}"


def is_week_name(name: str) -> bool:
    return name == UNDATED_WEEK or bool(_WEEK_RE.match(name))


# ---------------------------------------------------------------------------
# Discovery (directory listings only: no data is read)
# ---------------------------------------------------------------------------

def _subdirs(path: Path) -> list[str]:
    try:
        with os.scandir(path) as entries:
            return sorted(entry.name for entry in entries if entry.is_dir())
    except OSError:
        return []


def list_weeks(directory: Path) -> list[str]:
    """Weeks that have a partition for a client, oldest first (``undated`` last)."""
    weeks = [
        name for name in _subdirs(directory)
        if is_week_name(name) and (directory / name / PARTITION_FILE).is_file()
    ]
    return sorted(weeks, key=lambda name: (name == UNDATED_WEEK, name))


def has_partitions(directory: Path) -> bool:
    return bool(list_weeks(directory))


def select_weeks(
    directory: Path,
    lower_utc: Optional[pd.Timestamp] = None,
    upper_utc_exclusive: Optional[pd.Timestamp] = None,
) -> list[str]:
    """Existing weeks that overlap ``[lower, upper)``; an open side is unbounded.

    Whole weeks are returned: a range that starts or ends mid-week selects that week too, and
    the caller then filters the rows by the exact range. ``undated`` is selected only when the
    range is completely open (a date bound would drop its rows anyway).
    """
    weeks = list_weeks(directory)
    first = week_of(lower_utc) if lower_utc is not None and not pd.isna(lower_utc) else None
    last = (
        week_of(upper_utc_exclusive - pd.Timedelta(microseconds=1))
        if upper_utc_exclusive is not None and not pd.isna(upper_utc_exclusive)
        else None
    )
    selected = []
    for week in weeks:
        if week == UNDATED_WEEK:
            if first is None and last is None:
                selected.append(week)
            continue
        if (first is None or week >= first) and (last is None or week <= last):
            selected.append(week)
    return selected


def partition_paths(directory: Path, weeks: Sequence[str]) -> list[Path]:
    """Existing ``{week}/file.parquet`` paths for the weeks; a week without one is skipped."""
    paths = [directory / week / PARTITION_FILE for week in weeks]
    return [path for path in paths if path.is_file()]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _read_one(path: Path, columns: Optional[Sequence[str]]) -> pa.Table:
    last_error: Optional[Exception] = None
    for attempt in range(_READ_RETRIES):
        try:
            return pq.read_table(path, columns=list(columns) if columns is not None else None)
        except FileNotFoundError:
            # Replaced or removed between the listing and the read: empty, not an error.
            return pa.table({})
        except (pa.ArrowInvalid, KeyError):
            if columns is None:
                raise
            # A requested column this file does not have (an optional CSV column): return the
            # ones it has, like a frame read from the CSV that lacks them.
            present = set(pq.read_schema(path).names)
            return pq.read_table(path, columns=[name for name in columns if name in present])
        except OSError as exc:  # e.g. a transient sharing violation on Windows
            last_error = exc
            time.sleep(0.05 * (2 ** attempt))
    raise AlertPartitionError(f"Could not read alert partition {path}: {last_error}") from last_error


def _with_row_ids(table: pa.Table) -> pa.Table:
    metadata = table.schema.metadata or {}
    raw = metadata.get(ROW_IDS_KEY)
    row_ids = json.loads(raw) if raw else list(range(table.num_rows))
    return table.replace_schema_metadata(None).append_column("__source_row", pa.array(row_ids, pa.int64()))


def read_paths(paths: Sequence[Path], columns: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """Concatenate partition files into one frame, in the source CSV's row order.

    No normalization happens here: the values are the CSV's (strings stay strings, nulls stay
    null), so the loaders can apply the same post-processing the CSV path always did.
    """
    if not paths:
        return pd.DataFrame()
    if len(paths) > 3:
        with ThreadPoolExecutor(max_workers=min(_MAX_READ_WORKERS, len(paths))) as pool:
            tables = list(pool.map(lambda path: _read_one(path, columns), paths))
    else:
        tables = [_read_one(path, columns) for path in paths]
    tables = [_with_row_ids(table) for table in tables if table.num_columns]
    if not tables:
        return pd.DataFrame()
    combined = pa.concat_tables(tables, promote_options="permissive")
    frame = combined.to_pandas()
    frame = frame.sort_values("__source_row", kind="stable").drop(columns="__source_row")
    return frame.reset_index(drop=True)


def read_scope(
    directory: Path,
    weeks: Sequence[str],
    columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Every unit's rows of the given weeks, in the source's row order."""
    return read_paths(partition_paths(directory, weeks), columns)


# ---------------------------------------------------------------------------
# Alert index
# ---------------------------------------------------------------------------

def index_path(directory: Path) -> Path:
    return directory / INDEX_FILE


def index_signature(directory: Path) -> Optional[tuple[int, int]]:
    """``(mtime_ns, size)`` of the index, which changes with every regenerated history."""
    try:
        stat = index_path(directory).stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def read_alert_index(directory: Path) -> pd.DataFrame:
    """One row per alert: FusionID, UnitId, sistema, Trigger_Var, week, row_id."""
    path = index_path(directory)
    if not path.is_file():
        return pd.DataFrame()
    last_error: Optional[Exception] = None
    for attempt in range(_READ_RETRIES):
        try:
            return pq.read_table(path).to_pandas()
        except OSError as exc:
            last_error = exc
            time.sleep(0.05 * (2 ** attempt))
    raise AlertPartitionError(f"Could not read alert index {path}: {last_error}") from last_error


def locate_alert(directory: Path, fusion_id) -> Optional[str]:
    """The week whose partition holds the alert, or None.

    Duplicated ids resolve to the first one in the source, like ``frame[frame.id == x].iloc[0]``.
    """
    index = read_alert_index(directory)
    if index.empty or "FusionID" not in index.columns:
        return None
    hits = index[index["FusionID"] == fusion_id]
    if hits.empty:
        return None
    first = hits.sort_values("row_id", kind="stable").iloc[0]
    return str(first["week"])
