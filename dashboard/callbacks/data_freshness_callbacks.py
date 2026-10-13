"""
Data freshness loading + calculation helpers, shared by the Fleet Overview
(dashboard/components/fleet_overview.py) for the Telemetria/Tribologia rows,
whose per-unit freshness still comes from Data_Date_Last_Update.csv.

The Data Summary tab this module used to back was retired in Phase 1
(documentation/general/general_specs/01_fleet_overview_unified_view.md) -
its freshness rows now live inside each unit's Fleet Overview card instead of
a separate page, and its two-technique threshold table moved to
config/freshness_thresholds.py (covers all 5 techniques now).
"""

import pandas as pd
import pytz
from functools import lru_cache

from src.utils.logger import get_logger
from src.data.catalog import resolve_data_file
from config.freshness_thresholds import FRESHNESS_CRITERIA, FRESHNESS_STATUS_STYLE

logger = get_logger(__name__)


@lru_cache(maxsize=16)
def _load_data_freshness_cached(client: str, path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    """Read one freshness source generation and keep the cached frame immutable."""
    try:
        df = pd.read_csv(path)
        required_cols = ['Cliente', 'Unit_Id', 'Data', 'Ultima Fecha de Actualizacion']
        if not all(col in df.columns for col in required_cols):
            logger.error(f"Missing required columns. Found: {df.columns.tolist()}")
            return pd.DataFrame()
        df['Ultima Fecha de Actualizacion'] = pd.to_datetime(
            df['Ultima Fecha de Actualizacion'], errors='coerce', utc=True
        )
        logger.info(f"Loaded {len(df)} data freshness records from {path}")
        return df
    except Exception as e:
        logger.error(f"Error loading data freshness: {e}")
        return pd.DataFrame()


def load_data_freshness(client: str = "cda") -> pd.DataFrame:
    """
    Load data freshness information from Data_Date_Last_Update.csv

    Args:
        client: Client identifier (e.g., 'cda')

    Returns:
        DataFrame with data freshness information
    """
    try:
        file_path = resolve_data_file("auxiliar", client, "Data_Date_Last_Update.csv")
        if file_path is None:
            logger.warning(
                "Data freshness file not found for %s in compatible auxiliary paths",
                client,
            )
            return pd.DataFrame()
        stat = file_path.stat()
        return _load_data_freshness_cached(
            client.lower(), str(file_path), stat.st_mtime_ns, stat.st_size
        ).copy(deep=True)
        
    except Exception as e:
        logger.error(f"Error loading data freshness: {e}")
        return pd.DataFrame()


def convert_utc_to_chile(utc_datetime):
    """
    Convert UTC datetime to Chile timezone (UTC-3 or UTC-4 depending on DST)

    Args:
        utc_datetime: datetime in UTC

    Returns:
        datetime in Chile timezone

    Quality-review follow-up: this predates and duplicates
    src/utils/date_utils.py::to_local_naive, which W34-06 introduced as the
    single place for UTC->Chile conversion. Deliberately NOT switched to call
    it here: to_local_naive returns a tz-NAIVE Timestamp, but every caller of
    this function (calculate_freshness_status, both in this file and in
    overview_general_callbacks.py) subtracts its result from a tz-AWARE
    `current_time_chile` (`datetime.now(chile_tz)`) — swapping the return
    type would raise `TypeError: can't subtract offset-naive and
    offset-aware datetimes` at every call site. Changing that arithmetic to
    naive-throughout is a real, separate fix (touching both freshness call
    sites together), not a drop-in rename — left as a known, intentional
    duplication rather than risking a silent behavior change here.

    Second critical-review pass: a lower-risk fix path exists without
    touching the naive-vs-aware arithmetic at all — add a tz-AWARE sibling
    (e.g. `to_local_aware`) to date_utils.py, mirroring `to_local_naive`
    exactly except it skips the final `.tz_localize(None)` strip, and have
    this function delegate to it. Not applied in this pass: the "already
    tz-aware input" branch below (`if utc_datetime.tzinfo is None`) implies a
    caller once passed an aware value, and there is no full audit here
    confirming every current caller only ever passes naive — a delegating
    rewrite should preserve that defensive branch exactly, verified against
    real call sites, not assumed.
    """
    if pd.isna(utc_datetime):
        return None
    
    # Define UTC and Chile timezones
    utc_tz = pytz.UTC
    chile_tz = pytz.timezone('America/Santiago')
    
    # Localize to UTC if naive
    if utc_datetime.tzinfo is None:
        utc_datetime = utc_tz.localize(utc_datetime)
    
    # Convert to Chile timezone
    chile_datetime = utc_datetime.astimezone(chile_tz)
    
    return chile_datetime


def calculate_freshness_status(last_update, data_type, current_time_chile):
    """
    Calculate freshness status based on time elapsed since last update.
    Uses modular criteria defined in FRESHNESS_CRITERIA.
    
    Args:
        last_update: datetime of last update (in Chile timezone)
        data_type: 'Telemetria' or 'Tribologia'
        current_time_chile: current datetime in Chile timezone
        
    Returns:
        tuple: (status, color, time_diff_str)
    """
    if pd.isna(last_update):
        return 'Sin Datos', FRESHNESS_STATUS_STYLE['Sin Datos']['accent'], 'N/A'
    
    # Calculate time difference
    time_diff = current_time_chile - last_update
    
    # Format time difference string
    if time_diff.days > 0:
        if time_diff.days == 1:
            time_diff_str = "1 día"
        else:
            time_diff_str = f"{time_diff.days} días"
    else:
        hours = time_diff.seconds // 3600
        minutes = (time_diff.seconds % 3600) // 60
        if hours > 0:
            time_diff_str = f"{hours}h {minutes}m"
        else:
            time_diff_str = f"{minutes}m"
    
    # Look up criteria for this data type
    criteria = FRESHNESS_CRITERIA.get(data_type)
    if not criteria:
        return 'Desconocido', '#808080', time_diff_str
    
    # Evaluate thresholds in order
    for threshold, label, color in criteria:
        if time_diff < threshold:
            return label, color, time_diff_str
    
    # Exceeded all thresholds → return worst status
    _, worst_label, worst_color = criteria[-1]
    return worst_label, worst_color, time_diff_str
