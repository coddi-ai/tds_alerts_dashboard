"""
Data loaders for Multi-Technical-Alerts.

Load raw data from Bronze layer (data/oil/raw/).
"""

import pandas as pd
import json
import warnings
from pathlib import Path
from typing import Dict, List

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
    Load pre-computed Stewart Limits from JSON file.
    
    Args:
        file_path: Path to stewart_limits.json
    
    Returns:
        Dictionary with limits structure: {client: {machine: {component: {essay: {threshold_normal, threshold_alert, threshold_critic}}}}}
    """
    file_path = Path(file_path)
    logger.info(f"Loading Stewart Limits from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Stewart Limits file not found: {file_path}")
        return {}
    
    with open(file_path, 'r', encoding='utf-8') as f:
        limits = json.load(f)
    
    logger.info(f"Loaded Stewart Limits for {len(limits)} clients")
    return limits


def save_stewart_limits(limits: Dict, file_path: str | Path) -> None:
    """
    Save Stewart Limits to JSON file.
    
    Args:
        limits: Dictionary with limits structure
        file_path: Path to save JSON file
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Saving Stewart Limits to {file_path}")
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(limits, f, indent=4, ensure_ascii=False)
    
    logger.info("Stewart Limits saved successfully")
