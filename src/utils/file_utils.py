"""
File utility functions for reading data files safely.
"""

import pandas as pd
from pathlib import Path
from typing import List
import logging

logger = logging.getLogger(__name__)


def ensure_directory(path: Path) -> None:
    """
    Create directory if it doesn't exist.
    
    Args:
        path: Directory path to create
    """
    path.mkdir(parents=True, exist_ok=True)


def list_files(directory: Path, pattern: str = "*") -> List[Path]:
    """
    List files in directory matching pattern.
    
    Args:
        directory: Directory to search
        pattern: Glob pattern (default: all files)
    
    Returns:
        List of matching file paths
    """
    if not directory.exists():
        return []
    
    return sorted(directory.glob(pattern))


def list_excel_files(directory: Path) -> List[Path]:
    """
    List all Excel files in directory.
    
    Args:
        directory: Directory to search
    
    Returns:
        List of .xlsx and .xls file paths
    """
    xlsx_files = list_files(directory, "*.xlsx")
    xls_files = list_files(directory, "*.xls")
    return sorted(xlsx_files + xls_files)


def list_parquet_files(directory: Path) -> List[Path]:
    """
    List all Parquet files in directory.
    
    Args:
        directory: Directory to search
    
    Returns:
        List of .parquet file paths
    """
    return list_files(directory, "*.parquet")


def get_latest_file(directory: Path, pattern: str = "*") -> Path | None:
    """
    Get the most recently modified file matching pattern.
    
    Args:
        directory: Directory to search
        pattern: Glob pattern
    
    Returns:
        Path to latest file or None if no files found
    """
    files = list_files(directory, pattern)
    if not files:
        return None
    
    return max(files, key=lambda p: p.stat().st_mtime)


def safe_read_excel(file_path: Path, **kwargs) -> pd.DataFrame:
    """
    Safely read Excel file with error handling.
    
    Args:
        file_path: Path to Excel file
        **kwargs: Additional arguments for pd.read_excel
    
    Returns:
        DataFrame or empty DataFrame if error
    """
    try:
        return pd.read_excel(file_path, **kwargs)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return pd.DataFrame()


def safe_read_parquet(file_path: Path, **kwargs) -> pd.DataFrame:
    """
    Safely read Parquet file with error handling.
    
    Args:
        file_path: Path to Parquet file
        **kwargs: Additional arguments for pd.read_parquet
    
    Returns:
        DataFrame or empty DataFrame if error
    """
    try:
        return pd.read_parquet(file_path, **kwargs)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return pd.DataFrame()
