"""
Loader functions for maintenance/mantenciones data from parquet files.
"""

import pandas as pd
from pathlib import Path
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def load_maintenance_actions_all_equipment(base_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Load detailed maintenance actions for all equipment from query_3_actions_all_equipment.parquet.
    
    Args:
        base_path: Base path where parquet files are located. If None, uses project root.
        
    Returns:
        DataFrame with maintenance actions (659 rows, 21 columns)
        Columns: action_id, job_id, record_id, machine_id, machine_code, event_ts, 
                 change_date, action_type_name, job_system_name, job_subsystem_name,
                 action_subsystem_name, action_system_name, component_names, component_count,
                 target_level, action_detail_raw, action_detail_clean, action_detail_source,
                 action_detail_version, source_system, record_original_text
    """
    if base_path is None:
        base_path = Path(__file__).parent.parent.parent
    
    file_path = base_path / "query_3_actions_all_equipment.parquet"
    
    try:
        logger.info(f"Loading maintenance actions from {file_path}")
        df = pd.read_parquet(file_path)
        
        # Convert date strings to datetime
        df['event_ts'] = pd.to_datetime(df['event_ts'])
        df['change_date'] = pd.to_datetime(df['change_date'])
        
        logger.info(f"Loaded {len(df)} maintenance actions for {df['machine_code'].nunique()} machines")
        return df
    except FileNotFoundError:
        logger.error(f"Maintenance actions file not found: {file_path}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Error loading maintenance actions: {e}")
        return pd.DataFrame()


def load_business_kpis(base_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Load pre-calculated business KPIs from query_4_business_kpis.parquet.
    
    Args:
        base_path: Base path where parquet files are located. If None, uses project root.
        
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
        base_path = Path(__file__).parent.parent.parent
    
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
