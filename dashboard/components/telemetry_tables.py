"""
Table components for Telemetry Dashboard.

Functions to build DataTables and parse JSON data structures
for telemetry fleet, machine, component, and limits views.
"""

import pandas as pd
import numpy as np
import json
from typing import Dict, List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


# ========================================
# JSON PARSING HELPERS
# ========================================

def parse_component_details(component_details_raw) -> List[Dict]:
    """
    Parse component_details JSON field from machine_status.
    
    Args:
        component_details_raw: JSON string, list, or numpy array
    
    Returns:
        List of component dictionaries
    """
    try:
        if component_details_raw is None:
            return []
        if isinstance(component_details_raw, float) and pd.isna(component_details_raw):
            return []
        if isinstance(component_details_raw, str):
            return json.loads(component_details_raw)
        if isinstance(component_details_raw, (list, np.ndarray)):
            return list(component_details_raw)
        logger.warning(f"Unexpected component_details type: {type(component_details_raw)}")
        return []
    except Exception as e:
        logger.error(f"Error parsing component_details: {e}")
        return []


def parse_signals_evaluation(signals_eval_raw) -> Dict:
    """
    Parse signals_evaluation JSON field from classified.
    
    Args:
        signals_eval_raw: JSON string or dict
    
    Returns:
        Dictionary of signal evaluations {signal_name: eval_dict}
    """
    try:
        if signals_eval_raw is None:
            return {}
        if isinstance(signals_eval_raw, float) and pd.isna(signals_eval_raw):
            return {}
        if isinstance(signals_eval_raw, str):
            return json.loads(signals_eval_raw)
        if isinstance(signals_eval_raw, dict):
            return signals_eval_raw
        logger.warning(f"Unexpected signals_evaluation type: {type(signals_eval_raw)}")
        return {}
    except Exception as e:
        logger.error(f"Error parsing signals_evaluation: {e}")
        return {}


# ========================================
# FLEET STATUS TABLE
# ========================================

def build_fleet_status_table(machine_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build fleet status table data from machine_status DataFrame.
    
    Parses component_details JSON to count components by status (A/L/N format).
    
    Args:
        machine_df: DataFrame with machine status (filtered to latest week)
    
    Returns:
        DataFrame formatted for display in DataTable
    """
    if machine_df.empty:
        return pd.DataFrame()

    try:
        result = machine_df.copy()

        # Parse component details and count by status
        # Note: raw parquet stores 'status' key, not 'component_status'
        def count_component_status(component_details_json):
            details = parse_component_details(component_details_json)
            anormal = sum(1 for c in details if c.get('component_status', c.get('status')) == 'Anormal')
            alerta = sum(1 for c in details if c.get('component_status', c.get('status')) == 'Alerta')
            normal = sum(1 for c in details if c.get('component_status', c.get('status')) == 'Normal')
            return anormal, alerta, normal

        result[['anormal_comp', 'alerta_comp', 'normal_comp']] = result['component_details'].apply(
            lambda x: pd.Series(count_component_status(x))
        )

        # Format components as A/L/N
        result['componentes'] = result.apply(
            lambda row: f"{int(row['anormal_comp'])}/{int(row['alerta_comp'])}/{int(row['normal_comp'])}",
            axis=1
        )

        # Select and rename columns for display
        display_cols = {
            'unit_id': 'Unidad',
            'overall_status': 'Estado',
            'priority_score': 'Prioridad',
            'machine_score': 'Score',
            'componentes': 'Componentes (A/L/N)',
            'evaluation_week': 'Semana',
            'evaluation_year': 'Año'
        }

        table_df = result[list(display_cols.keys())].rename(columns=display_cols)

        # Sort by priority (descending)
        table_df = table_df.sort_values('Prioridad', ascending=False)

        # Round numeric columns
        table_df['Prioridad'] = table_df['Prioridad'].round(2)
        table_df['Score'] = table_df['Score'].round(3)

        return table_df

    except Exception as e:
        logger.error(f"Error building fleet status table: {e}")
        return pd.DataFrame()


# ========================================
# COMPONENT STATUS TABLE
# ========================================

def build_component_table(component_details: List[Dict]) -> pd.DataFrame:
    """
    Build component status table from parsed component_details.
    
    Args:
        component_details: List of component dictionaries
    
    Returns:
        DataFrame formatted for display in DataTable
    """
    if not component_details:
        return pd.DataFrame()

    try:
        df = pd.DataFrame(component_details)

        # Normalize column names
        column_mapping = {
            'status': 'component_status',
            'score': 'component_score',
            'signal_coverage': 'coverage'
        }
        for old_col, new_col in column_mapping.items():
            if old_col in df.columns and old_col != new_col:
                df.rename(columns={old_col: new_col}, inplace=True)

        # Derive num_signals if not present
        if 'num_signals' not in df.columns:
            if 'triggering_signals' in df.columns:
                df['num_signals'] = df['triggering_signals'].apply(
                    lambda x: len(x) if isinstance(x, (list, np.ndarray)) else 0
                )
            else:
                df['num_signals'] = 0

        # Select display columns
        display_mapping = {
            'component': 'Componente',
            'component_status': 'Estado',
            'component_score': 'Score',
            'num_signals': 'Señales',
            'coverage': 'Cobertura'
        }

        available_cols = {k: v for k, v in display_mapping.items() if k in df.columns}
        result = df[list(available_cols.keys())].rename(columns=available_cols)

        # Format numeric columns
        if 'Score' in result.columns:
            result['Score'] = result['Score'].round(3)
        if 'Cobertura' in result.columns:
            result['Cobertura'] = (result['Cobertura'] * 100).round(1).astype(str) + '%'

        # Sort by score descending
        if 'Score' in result.columns:
            result = result.sort_values('Score', ascending=False)

        return result

    except Exception as e:
        logger.error(f"Error building component table: {e}")
        return pd.DataFrame()


# ========================================
# SIGNAL EVALUATION TABLE
# ========================================

def build_signal_evaluation_table(signals_eval: Dict) -> pd.DataFrame:
    """
    Build signal evaluation table from parsed signals_evaluation dict.
    
    Args:
        signals_eval: Dictionary of signal evaluations {signal_name: eval_dict}
    
    Returns:
        DataFrame formatted for display with signal metrics
    """
    if not signals_eval:
        return pd.DataFrame()

    try:
        signals_list = []
        for signal_name, eval_data in signals_eval.items():
            if eval_data is not None:
                row = {'signal': signal_name}
                row.update(eval_data)
                signals_list.append(row)

        if not signals_list:
            return pd.DataFrame()

        df = pd.DataFrame(signals_list)

        # Normalize column names
        col_mapping = {
            'status': 'signal_status',
            'window_score': 'score',
            'sample_count': 'samples',
            'anomaly_percentage': 'anomaly_%'
        }

        for actual_col, display_name in col_mapping.items():
            if actual_col in df.columns and display_name not in df.columns:
                df.rename(columns={actual_col: display_name}, inplace=True)

        # Rename for display
        display_mapping = {
            'signal': 'Señal',
            'signal_status': 'Estado',
            'score': 'Score',
            'samples': 'Muestras',
            'anomaly_%': 'Anomalía %'
        }

        available_cols = {k: v for k, v in display_mapping.items() if k in df.columns}
        result = df[list(available_cols.keys())].rename(columns=available_cols)

        # Format
        if 'Score' in result.columns:
            result['Score'] = result['Score'].round(4)
        if 'Anomalía %' in result.columns:
            result['Anomalía %'] = result['Anomalía %'].round(2)

        # Sort by score descending
        if 'Score' in result.columns:
            result = result.sort_values('Score', ascending=False)

        # Also return the original df with original column names for chart building
        # We keep the raw signal name for boxplot matching
        return df

    except Exception as e:
        logger.error(f"Error building signal evaluation table: {e}")
        return pd.DataFrame()


# ========================================
# BASELINE THRESHOLDS TABLE
# ========================================

def build_baseline_thresholds_table(baseline_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build baseline thresholds table for display.
    
    Args:
        baseline_df: DataFrame with baseline data (Unit, Signal, EstadoMaquina, P2, P5, P95, P98)
    
    Returns:
        DataFrame formatted for DataTable display
    """
    if baseline_df.empty:
        return pd.DataFrame()

    try:
        # Select and rename columns
        display_mapping = {
            'Unit': 'Unidad',
            'Signal': 'Señal',
            'EstadoMaquina': 'Estado',
            'P2': 'P2',
            'P5': 'P5',
            'P95': 'P95',
            'P98': 'P98'
        }

        available_cols = {k: v for k, v in display_mapping.items() if k in baseline_df.columns}
        result = baseline_df[list(available_cols.keys())].rename(columns=available_cols).copy()

        # Round percentile values
        for col in ['P2', 'P5', 'P95', 'P98']:
            if col in result.columns:
                result[col] = result[col].round(4)

        # Sort
        sort_cols = [c for c in ['Unidad', 'Señal', 'Estado'] if c in result.columns]
        if sort_cols:
            result = result.sort_values(sort_cols)

        return result

    except Exception as e:
        logger.error(f"Error building baseline thresholds table: {e}")
        return pd.DataFrame()
