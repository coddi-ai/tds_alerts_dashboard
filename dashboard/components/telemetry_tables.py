"""
Telemetry table building functions for Multi-Technical Alerts Dashboard.

This module provides reusable table functions for telemetry data display.
All functions return DataFrames formatted for Dash DataTable display.
"""

import pandas as pd
import numpy as np
import json
from typing import Dict, List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


def parse_component_details(component_details_raw) -> List[Dict]:
    """
    Parse component_details JSON field into list of dictionaries.
    
    Args:
        component_details_raw: Raw component_details value (string, list, or numpy array)
    
    Returns:
        List of component detail dictionaries
    """
    # Check if value is None or NaN
    if component_details_raw is None or (isinstance(component_details_raw, float) and pd.isna(component_details_raw)):
        return []
    
    # Handle different types
    if isinstance(component_details_raw, str):
        # JSON string - parse it
        try:
            return json.loads(component_details_raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse component_details JSON string")
            return []
    elif isinstance(component_details_raw, (list, np.ndarray)):
        # Already a list or numpy array - convert to list
        return list(component_details_raw)
    else:
        logger.warning(f"Unexpected component_details type: {type(component_details_raw)}")
        return []


def parse_signals_evaluation(signals_eval_raw) -> Dict:
    """
    Parse signals_evaluation JSON field into dictionary.
    
    Args:
        signals_eval_raw: Raw signals_evaluation value (string or dict)
    
    Returns:
        Dictionary of signal evaluations
    """
    if pd.isna(signals_eval_raw):
        return {}
    
    if isinstance(signals_eval_raw, str):
        try:
            return json.loads(signals_eval_raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse signals_evaluation JSON string")
            return {}
    elif isinstance(signals_eval_raw, dict):
        return signals_eval_raw
    else:
        logger.warning(f"Unexpected signals_evaluation type: {type(signals_eval_raw)}")
        return {}


def build_fleet_status_table(machine_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build fleet status table for display.
    
    Args:
        machine_df: DataFrame with machine status data
    
    Returns:
        DataFrame formatted for DataTable display with columns:
        - unit_id, overall_status, priority_score, machine_score,
        - components (formatted as "A/L/N"), evaluation_week, evaluation_year
    """
    if machine_df.empty:
        logger.warning("Empty machine dataframe provided to build_fleet_status_table")
        return pd.DataFrame()
    
    # Parse component_details to count components by status
    def count_component_status(component_details_json):
        """Parse component_details JSON and count by status."""
        details = parse_component_details(component_details_json)
        
        if not details:
            return 0, 0, 0
        
        anormal = sum(1 for c in details if c.get('component_status') == 'Anormal')
        alerta = sum(1 for c in details if c.get('component_status') == 'Alerta')
        normal = sum(1 for c in details if c.get('component_status') == 'Normal')
        
        return anormal, alerta, normal
    
    # Apply to dataframe
    df = machine_df.copy()
    df[['anormal_components', 'alerta_components', 'normal_components']] = \
        df['component_details'].apply(
            lambda x: pd.Series(count_component_status(x))
        )
    
    # Create display table
    fleet_table = df[[
        'unit_id', 'overall_status', 'priority_score', 'machine_score',
        'anormal_components', 'alerta_components', 'normal_components',
        'evaluation_week', 'evaluation_year'
    ]].copy()
    
    # Sort by priority (descending)
    fleet_table = fleet_table.sort_values('priority_score', ascending=False)
    
    # Format component counts as "A/L/N"
    fleet_table['components'] = fleet_table.apply(
        lambda row: f"{int(row['anormal_components'])}/{int(row['alerta_components'])}/{int(row['normal_components'])}",
        axis=1
    )
    
    # Round numeric columns
    fleet_table['priority_score'] = fleet_table['priority_score'].round(2)
    fleet_table['machine_score'] = fleet_table['machine_score'].round(3)
    
    # Select final columns
    display_df = fleet_table[[
        'unit_id', 'overall_status', 'priority_score', 'machine_score',
        'components', 'evaluation_week', 'evaluation_year'
    ]].copy()
    
    return display_df


def build_component_table(component_details: List[Dict]) -> pd.DataFrame:
    """
    Build component status table for a machine.
    
    Args:
        component_details: List of component detail dictionaries
    
    Returns:
        DataFrame formatted for DataTable display with columns:
        - component, component_status, component_score, num_signals,
        - num_anormal, num_alerta, coverage
    """
    if not component_details:
        logger.warning("Empty component_details provided to build_component_table")
        return pd.DataFrame()
    
    # Convert to DataFrame
    component_table = pd.DataFrame(component_details)
    
    # Check for required columns and create them if needed
    if 'component' not in component_table.columns:
        logger.warning("Missing 'component' column in component_details")
        return pd.DataFrame()
    
    # Map potential different column names
    column_mapping = {
        'status': 'component_status',
        'score': 'component_score',
        'signal_coverage': 'coverage'
    }
    
    for old_col, new_col in column_mapping.items():
        if old_col in component_table.columns and old_col != new_col:
            component_table.rename(columns={old_col: new_col}, inplace=True)
    
    # Add missing columns with default values if needed
    if 'num_signals' not in component_table.columns:
        if 'triggering_signals' in component_table.columns:
            component_table['num_signals'] = component_table['triggering_signals'].apply(
                lambda x: len(x) if isinstance(x, (list, np.ndarray)) else 0
            )
        else:
            component_table['num_signals'] = 0
    
    if 'num_anormal' not in component_table.columns:
        component_table['num_anormal'] = component_table.get('component_status', 'Normal').apply(
            lambda x: 1 if x == 'Anormal' else 0
        )
    
    if 'num_alerta' not in component_table.columns:
        component_table['num_alerta'] = component_table.get('component_status', 'Normal').apply(
            lambda x: 1 if x == 'Alerta' else 0
        )
    
    # Select display columns
    display_cols = []
    for col in ['component', 'component_status', 'component_score', 'num_signals', 
                'num_anormal', 'num_alerta', 'coverage']:
        if col in component_table.columns:
            display_cols.append(col)
    
    display_df = component_table[display_cols].copy()
    
    # Round numeric columns
    if 'component_score' in display_df.columns:
        display_df['component_score'] = display_df['component_score'].round(3)
    if 'coverage' in display_df.columns:
        display_df['coverage'] = display_df['coverage'].round(3)
    
    # Sort by score
    if 'component_score' in display_df.columns:
        display_df = display_df.sort_values('component_score', ascending=False)
    
    return display_df


def build_signal_evaluation_table(signals_evaluation: Dict) -> pd.DataFrame:
    """
    Build signal evaluation table for a component.
    
    Args:
        signals_evaluation: Dictionary of signal evaluations
    
    Returns:
        DataFrame formatted for DataTable display with columns:
        - signal, signal_status, score, samples, anomaly_%
    """
    if not signals_evaluation:
        logger.warning("Empty signals_evaluation provided to build_signal_evaluation_table")
        return pd.DataFrame()
    
    # Restructure dictionary: keys are signal names, values are evaluation dicts
    signals_list = []
    for signal_name, eval_data in signals_evaluation.items():
        if eval_data is not None:  # Skip signals with no evaluation
            row = {'signal': signal_name}
            row.update(eval_data)
            signals_list.append(row)
    
    if not signals_list:
        logger.warning("All signals have null evaluations")
        return pd.DataFrame()
    
    # Convert to DataFrame
    signals_table = pd.DataFrame(signals_list)
    
    # Map actual columns to display (use what's available)
    col_mapping = {
        'status': 'signal_status',
        'window_score': 'score',
        'sample_count': 'samples',
        'anomaly_percentage': 'anomaly_%'
    }
    
    # Build display columns from available data
    display_cols = []
    for actual_col, display_name in col_mapping.items():
        if actual_col in signals_table.columns:
            if actual_col != display_name and display_name not in signals_table.columns:
                signals_table.rename(columns={actual_col: display_name}, inplace=True)
            display_cols.append(display_name)
    
    # Always include 'signal' column first
    if 'signal' not in display_cols:
        display_cols.insert(0, 'signal')
    
    display_df = signals_table[display_cols].copy()
    
    # Round numeric columns
    if 'score' in display_df.columns:
        display_df['score'] = display_df['score'].round(3)
    if 'anomaly_%' in display_df.columns:
        display_df['anomaly_%'] = display_df['anomaly_%'].round(2)
    
    # Sort by score if available
    if 'score' in display_df.columns:
        display_df = display_df.sort_values('score', ascending=False)
    
    return display_df


def build_baseline_thresholds_table(baseline_df: pd.DataFrame, unit_id: Optional[str] = None) -> pd.DataFrame:
    """
    Build baseline thresholds table for display.
    
    Args:
        baseline_df: DataFrame with baseline thresholds
        unit_id: Optional unit ID to filter by
    
    Returns:
        DataFrame formatted for DataTable display with columns:
        - Unit, Signal, EstadoMaquina, P2, P5, P95, P98
    """
    if baseline_df.empty:
        logger.warning("Empty baseline_df provided to build_baseline_thresholds_table")
        return pd.DataFrame()
    
    df = baseline_df.copy()
    
    # Filter for specific unit if provided
    if unit_id is not None and 'Unit' in df.columns:
        df = df[df['Unit'] == unit_id]
    
    # Select display columns
    display_cols = ['Unit', 'Signal', 'EstadoMaquina', 'P2', 'P5', 'P95', 'P98']
    existing_cols = [col for col in display_cols if col in df.columns]
    
    if not existing_cols:
        logger.warning("Required columns not found in baseline_df")
        return pd.DataFrame()
    
    display_df = df[existing_cols].copy()
    
    # Round percentile columns
    for col in ['P2', 'P5', 'P95', 'P98']:
        if col in display_df.columns:
            display_df[col] = display_df[col].round(2)
    
    return display_df
