"""
Loader functions for maintenance/mantenciones data from parquet files.
"""

import pandas as pd
from pathlib import Path
from typing import Optional
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)


def _get_mantentions_data_path(client: str = "cda") -> Path:
    """
    Get the path to the mantentions data directory following production architecture.
    
    Args:
        client: Client name (default: "cda"). Can be overridden by CLIENT_NAME env var.
        
    Returns:
        Path to data/mantentions/golden/{client}/Maintance_Labeler_Views/
    """
    # Get client from environment variable if available
    client = os.getenv("CLIENT_NAME", client)
    
    # Get project root (3 levels up from this file)
    base_path = Path(__file__).parent.parent.parent
    
    # Production structure: data/mantentions/golden/{client}/Maintance_Labeler_Views/
    data_path = base_path / "data" / "mantentions" / "golden" / client / "Maintance_Labeler_Views"
    
    # Fallback: check if files are in project root (for local development)
    if not data_path.exists():
        logger.warning(f"Production path not found: {data_path}. Falling back to project root.")
        return base_path
    
    logger.info(f"Using mantentions data path: {data_path}")
    return data_path


def load_maintenance_actions_all_equipment(client: str = "cda", base_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Load detailed maintenance actions for all equipment from query_3_actions_all_equipment.parquet.
    
    Args:
        client: Client name (default: "cda")
        base_path: Base path override. If None, uses production structure.
        
    Returns:
        DataFrame with maintenance actions (659 rows, 21 columns)
        Columns: action_id, job_id, record_id, machine_id, machine_code, event_ts, 
                 change_date, action_type_name, job_system_name, job_subsystem_name,
                 action_subsystem_name, action_system_name, component_names, component_count,
                 target_level, action_detail_raw, action_detail_clean, action_detail_source,
                 action_detail_version, source_system, record_original_text
    """
    if base_path is None:
        base_path = _get_mantentions_data_path(client)
    
    file_path = base_path / "query_3_actions_all_equipment.parquet"
    
    try:
        logger.info(f"Loading maintenance actions from {file_path}")
        df = pd.read_parquet(file_path)
        
        # Convert date strings to datetime (UTC to handle mixed timezones)
        df['event_ts'] = pd.to_datetime(df['event_ts'], utc=True)
        df['change_date'] = pd.to_datetime(df['change_date'], utc=True)
        
        logger.info(f"Loaded {len(df)} maintenance actions for {df['machine_code'].nunique()} machines")
        return df
    except FileNotFoundError:
        logger.error(f"Maintenance actions file not found: {file_path}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Error loading maintenance actions: {e}")
        return pd.DataFrame()


def load_business_kpis(client: str = "cda", base_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Load pre-calculated business KPIs from query_4_business_kpis.parquet.
    
    Args:
        client: Client name (default: "cda")
        base_path: Base path override. If None, uses production structure.
        
    Returns:
        DataFrame with business KPIs (11 rows - one per machine, 18 columns)
        Columns: machine_code, machine_id, equipment_status, has_ongoing_maintenance,
                 last_ongoing_date, days_since_last_maintenance, last_action_date,
                 total_actions_70d, ongoing_actions_70d, downtime_hours_70d,
                 maintenance_frequency_per_day, action_types_70d, top_3_components,
                 inspections_70d, replacements_70d, repairs_70d, maintenances_70d,
                 reference_date
    """
    if base_path is None:
        base_path = _get_mantentions_data_path(client)
    
    file_path = base_path / "query_4_business_kpis.parquet"
    
    try:
        logger.info(f"Loading business KPIs from {file_path}")
        df = pd.read_parquet(file_path)
        
        # Convert date columns to datetime
        if 'last_action_date' in df.columns:
            df['last_action_date'] = pd.to_datetime(df['last_action_date'])
        if 'reference_date' in df.columns:
            df['reference_date'] = pd.to_datetime(df['reference_date'])
        if 'last_ongoing_date' in df.columns:
            df['last_ongoing_date'] = pd.to_datetime(df['last_ongoing_date'])
        
        logger.info(f"Loaded KPIs for {len(df)} machines")
        return df
    except FileNotFoundError:
        logger.error(f"Business KPIs file not found: {file_path}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Error loading business KPIs: {e}")
        return pd.DataFrame()
