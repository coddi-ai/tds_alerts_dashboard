"""
Data exporters for Multi-Technical-Alerts.

Export processed data from Silver and Gold layers.
"""

import pandas as pd
import json
from pathlib import Path
from typing import Dict, List
from src.utils.logger import get_logger

logger = get_logger(__name__)


def export_to_parquet(
    df: pd.DataFrame,
    output_path: str | Path,
    compression: str = 'snappy'
) -> None:
    """
    Export DataFrame to Parquet format.
    
    Args:
        df: DataFrame to export
        output_path: Path to output file
        compression: Compression algorithm ('snappy', 'gzip', 'brotli')
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Exporting {len(df)} rows to {output_path}")
    
    df.to_parquet(output_path, compression=compression, index=False)
    
    logger.info(f"Export complete: {output_path.stat().st_size / 1024:.2f} KB")


def export_to_excel(
    df: pd.DataFrame,
    output_path: str | Path,
    sheet_name: str = 'Data'
) -> None:
    """
    Export DataFrame to Excel format (Phase 1: export functionality).
    
    Args:
        df: DataFrame to export
        output_path: Path to output file
        sheet_name: Name of Excel sheet
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Exporting {len(df)} rows to Excel: {output_path}")
    
    # Excel doesn't support timezone-aware datetimes - convert to timezone-naive
    df_export = df.copy()
    for col in df_export.select_dtypes(include=['datetimetz']).columns:
        df_export[col] = df_export[col].dt.tz_localize(None)
        logger.debug(f"Removed timezone from column: {col}")
    
    df_export.to_excel(output_path, sheet_name=sheet_name, index=False, engine='openpyxl')
    
    logger.info(f"Excel export complete: {output_path.stat().st_size / 1024:.2f} KB")


def export_to_json(
    data: Dict | List,
    output_path: str | Path,
    indent: int = 2
) -> None:
    """
    Export data to JSON format.
    
    Args:
        data: Dictionary or list to export
        output_path: Path to output file
        indent: JSON indentation (None for compact)
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Exporting to JSON: {output_path}")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent, ensure_ascii=False, default=str)
    
    logger.info(f"JSON export complete: {output_path.stat().st_size / 1024:.2f} KB")


def export_classified_reports(
    df: pd.DataFrame,
    output_dir: str | Path,
    client: str
) -> None:
    """
    Export classified reports (Gold layer) in multiple formats.
    
    Args:
        df: DataFrame with classified reports
        output_dir: Directory for output files
        client: Client name
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Exporting classified reports for {client}")
    
    # Export as Parquet
    parquet_path = output_dir / f"{client.lower()}_classified.parquet"
    export_to_parquet(df, parquet_path)
    
    # Export as Excel (Phase 1)
    excel_path = output_dir / f"{client.lower()}_classified.xlsx"
    export_to_excel(df, excel_path, sheet_name='Classified Reports')
    
    # Export summary as JSON
    summary = {
        'client': client,
        'total_samples': len(df),
        'status_distribution': df['report_status'].value_counts().to_dict() if 'report_status' in df.columns else {},
        'total_units': df['unitId'].nunique() if 'unitId' in df.columns else 0,
        'date_range': {
            'min': df['sampleDate'].min().isoformat() if 'sampleDate' in df.columns else None,
            'max': df['sampleDate'].max().isoformat() if 'sampleDate' in df.columns else None
        }
    }
    
    json_path = output_dir / f"{client.lower()}_summary.json"
    export_to_json(summary, json_path)
    
    logger.info(f"Classified reports exported to {output_dir}")


def export_machine_status(
    df: pd.DataFrame,
    output_path: str | Path
) -> None:
    """
    Export machine status aggregation.
    
    Args:
        df: DataFrame with machine status
        output_path: Path to output file
    """
    export_to_parquet(df, output_path)
    
    # Also export as Excel for easy viewing
    excel_path = Path(output_path).with_suffix('.xlsx')
    export_to_excel(df, excel_path, sheet_name='Machine Status')


def export_component_summary(
    df: pd.DataFrame,
    output_path: str | Path
) -> None:
    """
    Export component-level summary.
    
    Args:
        df: DataFrame with component summary
        output_path: Path to output file
    """
    export_to_parquet(df, output_path)
    
    # Also export as Excel
    excel_path = Path(output_path).with_suffix('.xlsx')
    export_to_excel(df, excel_path, sheet_name='Component Summary')


def export_stewart_limits_parquet(
    limits: Dict,
    output_path: str | Path
) -> pd.DataFrame:
    """
    Export Stewart Limits to Parquet format (Phase 1 enhancement).
    
    Converts nested dict structure to flat DataFrame for easier querying.
    
    Args:
        limits: Stewart Limits dictionary
        output_path: Path to output parquet file
    
    Returns:
        DataFrame with flattened limits
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info("Converting Stewart Limits to DataFrame")
    
    # Flatten nested dictionary
    rows = []
    for client, machines in limits.items():
        for machine, components in machines.items():
            for component, essays in components.items():
                for essay, thresholds in essays.items():
                    # Thresholds should be a dict with threshold_normal/alert/critic keys
                    if isinstance(thresholds, dict) and 'threshold_normal' in thresholds:
                        rows.append({
                            'client': client,
                            'machine': machine,
                            'component': component,
                            'essay': essay,
                            'threshold_normal': thresholds.get('threshold_normal'),
                            'threshold_alert': thresholds.get('threshold_alert'),
                            'threshold_critic': thresholds.get('threshold_critic')
                        })
                    else:
                        # Skip metadata or invalid entries (e.g., 'count' fields)
                        logger.debug(f"Skipping non-threshold entry {client}/{machine}/{component}/{essay}")
    
    df = pd.DataFrame(rows)
    
    logger.info(f"Exporting {len(df)} limit thresholds to {output_path}")
    export_to_parquet(df, output_path)
    
    # Also export as Excel for easy viewing
    excel_path = output_path.with_suffix('.xlsx')
    export_to_excel(df, excel_path, sheet_name='Stewart Limits')
    
    return df
