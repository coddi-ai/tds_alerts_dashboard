"""
Data loaders for Multi-Technical-Alerts.

Load data from different layers:
- Bronze layer: Raw data (data/oil/bronze/{client}/)
- Silver layer: Harmonized data (data/oil/silver/{CLIENT}.parquet)
- Golden layer: Analysis-ready outputs (data/oil/golden/{client}/)
"""

import pandas as pd
import json
import warnings
from pathlib import Path
from typing import Dict, List, Optional

from src.utils.logger import get_logger
from src.utils.file_utils import list_excel_files, safe_read_excel, safe_read_parquet

logger = get_logger(__name__)


def load_essays_mapping(file_path: str | Path = "essays_elements.xlsx") -> pd.DataFrame:
    """
    Load essays mapping table for harmonizing column names.
    
    Args:
        file_path: Path to essays mapping Excel file
    
    Returns:
        DataFrame with Element → ElementNameSpanish mapping
    """
    logger.info(f"Loading essays mapping from {file_path}")
    
    df = pd.read_excel(file_path, engine='openpyxl')
    # Drop rows with incomplete mappings
    df = df.dropna()
    
    logger.info(f"Loaded {len(df)} essay mappings")
    return df


def load_cda_data(raw_folder: str | Path) -> pd.DataFrame:
    """
    Load CDA data from Finning lab Excel files.
    
    Args:
        raw_folder: Path to raw/cda directory
    
    Returns:
        Concatenated DataFrame from all Excel files
    """
    import warnings
    warnings.filterwarnings("ignore", message="Workbook contains no default style")
    
    raw_folder = Path(raw_folder)
    logger.info(f"Loading CDA data from {raw_folder}")
    
    excel_files = list_excel_files(raw_folder)
    
    if not excel_files:
        logger.warning(f"No Excel files found in {raw_folder}")
        return pd.DataFrame()
    
    logger.info(f"Found {len(excel_files)} Excel files to process")
    
    dataframes = []
    for file in excel_files:
        logger.debug(f"Reading {file.name}")
        df = safe_read_excel(file, engine='openpyxl')
        if not df.empty:
            dataframes.append(df)
    
    if not dataframes:
        logger.warning("No valid dataframes loaded from CDA files")
        return pd.DataFrame()
    
    # Concatenate all dataframes
    df_combined = pd.concat(dataframes, ignore_index=True)
    
    # Drop completely empty rows
    df_combined = df_combined.dropna(how='all')
    
    logger.info(f"Loaded {len(df_combined)} rows from CDA data")
    return df_combined


def load_emin_data(file_path: str | Path) -> pd.DataFrame:
    """
    Load EMIN data from ALS lab Parquet file.
    
    Args:
        file_path: Path to EMIN parquet file (e.g., raw/emin/muestrasAlsHistoricos.parquet)
    
    Returns:
        DataFrame with EMIN data
    """
    file_path = Path(file_path)
    logger.info(f"Loading EMIN data from {file_path}")
    
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning(f"No data loaded from {file_path}")
        return df
    
    logger.info(f"Loaded {len(df)} rows from EMIN data")
    return df


def load_stewart_limits(file_path: str | Path) -> Dict:
    """
    Load pre-computed Stewart Limits from Parquet file.
    
    Args:
        file_path: Path to stewart_limits.parquet
    
    Returns:
        Dictionary with limits structure: {client: {machine: {component: {essay: {threshold_normal, threshold_alert, threshold_critic}}}}}
    """
    file_path = Path(file_path)
    logger.info(f"Loading Stewart Limits from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Stewart Limits file not found: {file_path}")
        return {}
    
    # Read Parquet file
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning("Stewart Limits dataframe is empty")
        return {}
    
    # Convert dataframe to nested dictionary structure
    limits = {}
    for _, row in df.iterrows():
        client = row['client']
        machine = row['machine']
        component = row['component']
        essay = row['essay']
        
        if client not in limits:
            limits[client] = {}
        if machine not in limits[client]:
            limits[client][machine] = {}
        if component not in limits[client][machine]:
            limits[client][machine][component] = {}
        
        limits[client][machine][component][essay] = {
            'threshold_normal': row.get('threshold_normal', 0),
            'threshold_alert': row.get('threshold_alert', 0),
            'threshold_critic': row.get('threshold_critic', 0),
            'percentile_marginal': row.get('percentile_marginal', 90),
            'percentile_condenatorio': row.get('percentile_condenatorio', 95),
            'percentile_critico': row.get('percentile_critico', 98),
            'sample_count': row.get('sample_count', 0)
        }
    
    logger.info(f"Loaded Stewart Limits for {len(limits)} clients")
    return limits


def save_stewart_limits(limits: Dict, file_path: str | Path) -> None:
    """
    Save Stewart Limits to Parquet file.
    
    Args:
        limits: Dictionary with limits structure
        file_path: Path to save Parquet file
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Saving Stewart Limits to {file_path}")
    
    # Convert nested dict to dataframe
    rows = []
    for client, machines in limits.items():
        for machine, components in machines.items():
            for component, essays in components.items():
                for essay, thresholds in essays.items():
                    rows.append({
                        'client': client,
                        'machine': machine,
                        'component': component,
                        'essay': essay,
                        'threshold_normal': thresholds.get('threshold_normal', 0),
                        'threshold_alert': thresholds.get('threshold_alert', 0),
                        'threshold_critic': thresholds.get('threshold_critic', 0),
                        'percentile_marginal': thresholds.get('percentile_marginal', 90),
                        'percentile_condenatorio': thresholds.get('percentile_condenatorio', 95),
                        'percentile_critico': thresholds.get('percentile_critico', 98),
                        'sample_count': thresholds.get('sample_count', 0)
                    })
    
    df = pd.DataFrame(rows)
    df.to_parquet(file_path, index=False, engine='pyarrow', compression='zstd')
    
    logger.info("Stewart Limits saved successfully")

# ========================================
# GOLDEN LAYER LOADERS
# ========================================

def load_classified_reports(file_path: str | Path) -> pd.DataFrame:
    """
    Load classified oil analysis reports from Golden layer.
    
    Args:
        file_path: Path to golden/{client}/classified.parquet
    
    Returns:
        DataFrame with classified reports including essay_status columns,
        report_status, ai_recommendation, etc.
    """
    file_path = Path(file_path)
    logger.info(f"Loading classified reports from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Classified reports file not found: {file_path}")
        return pd.DataFrame()
    
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning("Classified reports dataframe is empty")
        return df
    
    logger.info(f"Loaded {len(df)} classified reports")
    return df


def load_machine_status(file_path: str | Path) -> pd.DataFrame:
    """
    Load machine status aggregations from Golden layer.
    
    Args:
        file_path: Path to golden/{client}/machine_status.parquet
    
    Returns:
        DataFrame with machine-level status aggregations
    """
    file_path = Path(file_path)
    logger.info(f"Loading machine status from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Machine status file not found: {file_path}")
        return pd.DataFrame()
    
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning("Machine status dataframe is empty")
        return df
    
    logger.info(f"Loaded {len(df)} machine status records")
    return df


def load_stewart_limits_for_client(file_path: str | Path) -> pd.DataFrame:
    """
    Load Stewart Limits for a specific client from Golden layer.
    
    Args:
        file_path: Path to golden/{client}/stewart_limits.parquet
    
    Returns:
        DataFrame with Stewart Limits for the client
    """
    file_path = Path(file_path)
    logger.info(f"Loading Stewart Limits from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Stewart Limits file not found: {file_path}")
        return pd.DataFrame()
    
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning("Stewart Limits dataframe is empty")
        return df
    
    logger.info(f"Loaded {len(df)} Stewart Limit records")
    return df


def load_silver_data(file_path: str | Path) -> pd.DataFrame:
    """
    Load harmonized silver layer data for a client.
    
    Args:
        file_path: Path to silver/{CLIENT}.parquet
    
    Returns:
        DataFrame with harmonized oil sample data
    """
    file_path = Path(file_path)
    logger.info(f"Loading silver data from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Silver data file not found: {file_path}")
        return pd.DataFrame()
    
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning("Silver data dataframe is empty")
        return df
    
    logger.info(f"Loaded {len(df)} silver layer records")
    return df