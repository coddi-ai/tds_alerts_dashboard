"""How recent the data inside a source is.

Reads the date column a source is configured with (`config/service_data_sources.py::
SOURCE_DATE_FIELDS`) and returns the date closest to today without being in the future.
This is the date of the data, not the file's last-modified time: a file rewritten today
with old rows is old data.

Reading never raises: a missing file, missing column or unparseable values give ``None``.
Only the one column is read, and the distinct days are cached until the files change.
"""

from __future__ import annotations

import bisect
import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from config.service_data_sources import DateField
from src.utils.logger import get_logger

logger = get_logger(__name__)

DISPLAY_TIMEZONE = "America/Santiago"


def _zone() -> Optional[ZoneInfo]:
    try:
        return ZoneInfo(DISPLAY_TIMEZONE)
    except ZoneInfoNotFoundError:
        return None


def today_local() -> date:
    return datetime.now(_zone()).date()


def _days_of(values: pd.Series) -> set[date]:
    """Distinct calendar days of a column. Timestamps with an offset are read in Chile
    time; naive ones already are local and keep their own date."""
    try:
        parsed = pd.to_datetime(values, errors="coerce")
    except (ValueError, TypeError):
        parsed = pd.to_datetime(values, errors="coerce", utc=True)
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_convert(_zone() or "UTC")
    return set(parsed.dropna().dt.date)


def _read_column(path: Path, column: str) -> pd.Series:
    if path.suffix == ".parquet":
        return pd.read_parquet(path, columns=[column])[column]
    if path.suffix == ".csv":
        return pd.read_csv(path, usecols=[column], dtype=str)[column]
    if path.suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8")).get(column)
        return pd.Series([] if value is None else [value])
    raise ValueError(f"unsupported source file type: {path.suffix}")


@lru_cache(maxsize=64)
def _distinct_days(files: tuple[tuple[str, int, int], ...], column: str) -> tuple[date, ...]:
    """Sorted distinct days found in `column` across `files`, keyed by (path, mtime, size)
    so a rewritten file is read again and an untouched one never is."""
    days: set[date] = set()
    for file, _mtime, _size in files:
        try:
            days |= _days_of(_read_column(Path(file), column))
        except Exception:
            logger.warning("Could not read date column %r from %s", column, file, exc_info=True)
    return tuple(sorted(days))


def latest_data_date(source_path: Optional[str], field: DateField, today: Optional[date] = None) -> Optional[date]:
    """The date in the source's data closest to `today` that is not after it, or ``None``
    when it cannot be resolved."""
    if not source_path:
        return None
    root = Path(source_path)
    try:
        paths = sorted(root.glob(field.glob)) if field.glob else [root]
        files = tuple(
            (str(p), stat.st_mtime_ns, stat.st_size)
            for p in paths
            if p.is_file()
            for stat in (p.stat(),)
        )
    except OSError:
        return None
    if not files:
        return None
    days = _distinct_days(files, field.column)
    cut = bisect.bisect_right(days, today or today_local())
    return days[cut - 1] if cut else None


def days_since(data_date: Optional[date], today: Optional[date] = None) -> Optional[int]:
    if data_date is None:
        return None
    return ((today or today_local()) - data_date).days
