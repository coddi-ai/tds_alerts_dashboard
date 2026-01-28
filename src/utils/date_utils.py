"""
Date utility functions for Multi-Technical-Alerts.

Provides helpers for date parsing and calculations.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional


def parse_date(date_str: any, format: Optional[str] = None) -> pd.Timestamp:
    """
    Parse date from various formats to Timestamp.
    
    Args:
        date_str: Date string or datetime object
        format: Optional date format string
    
    Returns:
        Parsed Timestamp
    """
    if pd.isna(date_str):
        return pd.NaT
    
    if isinstance(date_str, pd.Timestamp):
        return date_str
    
    if isinstance(date_str, datetime):
        return pd.Timestamp(date_str)
    
    if format:
        try:
            return pd.to_datetime(date_str, format=format)
        except:
            pass
    
    # Try automatic parsing
    return pd.to_datetime(date_str, errors='coerce')


def days_between(date1: pd.Timestamp, date2: pd.Timestamp) -> int:
    """
    Calculate days between two dates.
    
    Args:
        date1: First date
        date2: Second date
    
    Returns:
        Number of days (absolute value)
    """
    if pd.isna(date1) or pd.isna(date2):
        return 0
    
    delta = abs(date1 - date2)
    return delta.days


def format_date_spanish(date: pd.Timestamp) -> str:
    """
    Format date in Spanish style (DD/MM/YYYY).
    
    Args:
        date: Timestamp to format
    
    Returns:
        Formatted date string
    """
    if pd.isna(date):
        return "N/A"
    
    return date.strftime("%d/%m/%Y")


def get_month_name_spanish(date: pd.Timestamp) -> str:
    """
    Get Spanish month name from date.
    
    Args:
        date: Timestamp
    
    Returns:
        Spanish month name
    """
    months = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
    }
    
    if pd.isna(date):
        return "N/A"
    
    return months.get(date.month, "N/A")


def filter_by_date_range(
    df: pd.DataFrame,
    date_column: str,
    start_date: Optional[pd.Timestamp] = None,
    end_date: Optional[pd.Timestamp] = None
) -> pd.DataFrame:
    """
    Filter DataFrame by date range.
    
    Args:
        df: DataFrame to filter
        date_column: Name of date column
        start_date: Optional start date (inclusive)
        end_date: Optional end date (inclusive)
    
    Returns:
        Filtered DataFrame
    """
    result = df.copy()
    
    if start_date is not None:
        result = result[result[date_column] >= start_date]
    
    if end_date is not None:
        result = result[result[date_column] <= end_date]
    
    return result


def get_recent_months(n_months: int = 6) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Get date range for last N months.
    
    Args:
        n_months: Number of months to look back
    
    Returns:
        Tuple of (start_date, end_date)
    """
    end_date = pd.Timestamp.now()
    start_date = end_date - pd.DateOffset(months=n_months)
    
    return start_date, end_date
