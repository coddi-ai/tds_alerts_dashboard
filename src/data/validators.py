"""
Data validators for Multi-Technical-Alerts.

Quality checks and filtering for Silver layer data.
"""

import pandas as pd
from typing import List
from src.utils.logger import get_logger

logger = get_logger(__name__)


def filter_invalid_samples(
    df: pd.DataFrame,
    min_machine_samples: int = 5,
    min_component_samples: int = 3
) -> pd.DataFrame:
    """
    Filter out machines/components with insufficient sample history.
    
    Args:
        df: DataFrame with unitId, componentName, machineName
        min_machine_samples: Minimum samples required per machine
        min_component_samples: Minimum samples required per component
    
    Returns:
        Filtered DataFrame
    """
    logger.info(f"Filtering samples: min_machine={min_machine_samples}, min_component={min_component_samples}")
    
    initial_rows = len(df)
    
    # Count samples per machine
    machine_counts = df.groupby('unitId').size()
    valid_machines = machine_counts[machine_counts >= min_machine_samples].index
    
    # Count samples per component (within each machine)
    component_counts = df.groupby(['unitId', 'componentName']).size()
    valid_components = component_counts[component_counts >= min_component_samples].index
    
    # Filter
    df = df[df['unitId'].isin(valid_machines)].copy()
    df = df[df.set_index(['unitId', 'componentName']).index.isin(valid_components)].copy()
    
    final_rows = len(df)
    removed = initial_rows - final_rows
    
    logger.info(f"Filtered {removed} samples ({removed/initial_rows*100:.1f}%): {final_rows} samples remaining")
    return df


def validate_schema(df: pd.DataFrame, required_columns: List[str]) -> bool:
    """
    Validate that DataFrame has all required columns.
    
    Args:
        df: DataFrame to validate
        required_columns: List of column names that must be present
    
    Returns:
        True if valid, False otherwise
    """
    missing = set(required_columns) - set(df.columns)
    
    if missing:
        logger.error(f"Schema validation failed: missing columns {missing}")
        return False
    
    logger.info("Schema validation passed")
    return True


def validate_date_range(df: pd.DataFrame, date_column: str = 'sampleDate') -> pd.DataFrame:
    """
    Remove samples with invalid dates (NaT or future dates).
    
    Args:
        df: DataFrame with date column
        date_column: Name of date column
    
    Returns:
        Filtered DataFrame
    """
    logger.info(f"Validating date range for column '{date_column}'")
    
    initial_rows = len(df)
    
    # Remove NaT dates
    df = df[df[date_column].notna()].copy()
    
    # Remove future dates (convert to timezone-naive for comparison)
    current_date = pd.Timestamp.now().tz_localize(None)
    # Ensure date column is timezone-naive
    if df[date_column].dt.tz is not None:
        df[date_column] = df[date_column].dt.tz_localize(None)
    df = df[df[date_column] <= current_date].copy()
    
    final_rows = len(df)
    removed = initial_rows - final_rows
    
    if removed > 0:
        logger.warning(f"Removed {removed} samples with invalid dates")
    
    return df


def validate_numeric_essays(df: pd.DataFrame, essay_columns: List[str]) -> pd.DataFrame:
    """
    Ensure essay columns contain numeric values.
    
    Args:
        df: DataFrame with essay columns
        essay_columns: List of essay column names
    
    Returns:
        DataFrame with numeric essay values
    """
    logger.info(f"Validating {len(essay_columns)} essay columns")
    
    df = df.copy()
    
    for col in essay_columns:
        if col in df.columns:
            # Convert to numeric, coercing errors to NaN
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    logger.info("Numeric validation complete")
    return df


def get_data_quality_report(df: pd.DataFrame) -> dict:
    """
    Generate data quality report.
    
    Args:
        df: DataFrame to analyze
    
    Returns:
        Dictionary with quality metrics
    """
    report = {
        'total_rows': len(df),
        'total_columns': len(df.columns),
        'missing_values': df.isnull().sum().to_dict(),
        'duplicate_samples': df['sampleNumber'].duplicated().sum() if 'sampleNumber' in df.columns else 0,
        'unique_units': df['unitId'].nunique() if 'unitId' in df.columns else 0,
        'unique_components': df['componentName'].nunique() if 'componentName' in df.columns else 0,
        'date_range': {
            'min': df['sampleDate'].min().isoformat() if 'sampleDate' in df.columns else None,
            'max': df['sampleDate'].max().isoformat() if 'sampleDate' in df.columns else None
        }
    }
    
    logger.info(f"Data quality report: {report['total_rows']} rows, {report['unique_units']} units, {report['unique_components']} components")
    
    return report
