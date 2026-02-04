"""
Component name normalization for Stewart Limits calculation.

Normalizes component names by removing positional indicators (left/right, izquierdo/derecho)
while preserving original granularity in componentName field.
"""

import pandas as pd
import re
from src.utils.logger import get_logger

logger = get_logger(__name__)


def normalize_component_name(component_name: str) -> str:
    """
    Normalize component name by removing positional indicators.
    
    Examples:
        'mando final izquierdo' -> 'mando final'
        'mando final derecho' -> 'mando final'
        'maza izquierda' -> 'maza'
        'maza derecha' -> 'maza'
        'motor diesel' -> 'motor diesel' (no change)
        'transmision' -> 'transmision' (no change)
    
    Args:
        component_name: Original component name
    
    Returns:
        Normalized component name
    """
    if not isinstance(component_name, str):
        return component_name
    
    # Convert to lowercase
    normalized = component_name.lower().strip()
    
    # Remove positional indicators (left/right)
    # Spanish: izquierdo, izquierda, derecho, derecha
    # English: left, right
    patterns_to_remove = [
        r'\bizquierd[oa]s?\b',  # izquierdo, izquierda, izquierdos, izquierdas
        r'\bderech[oa]s?\b',     # derecho, derecha, derechos, derechas
        r'\bleft\b',
        r'\bright\b',
        r'\b(#\s*)?[12]\b',      # #1, #2, 1, 2 (for numbered positions)
    ]
    
    for pattern in patterns_to_remove:
        normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE)
    
    # Clean up multiple spaces and trim
    normalized = ' '.join(normalized.split())
    
    return normalized


def add_component_normalization(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add componentNameNormalized column to DataFrame.
    
    This preserves the original componentName (with left/right positions)
    while creating a normalized version for Stewart Limits grouping.
    
    Args:
        df: DataFrame with componentName column
    
    Returns:
        DataFrame with componentNameNormalized column added
    """
    if 'componentName' not in df.columns:
        logger.warning("componentName column not found, skipping normalization")
        return df
    
    logger.info("Adding componentNameNormalized column")
    df = df.copy()
    
    # Apply normalization
    df['componentNameNormalized'] = df['componentName'].apply(normalize_component_name)
    
    # Log some examples for verification
    if len(df) > 0:
        unique_mappings = df[['componentName', 'componentNameNormalized']].drop_duplicates()
        logger.info(f"Component normalization created {len(unique_mappings)} unique mappings")
        
        # Log a few examples
        sample = unique_mappings.head(10)
        for _, row in sample.iterrows():
            if row['componentName'] != row['componentNameNormalized']:
                logger.debug(f"  '{row['componentName']}' -> '{row['componentNameNormalized']}'")
    
    return df
