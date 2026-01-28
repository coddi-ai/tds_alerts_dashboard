"""
Data transformers for Multi-Technical-Alerts.

Transform raw data (Bronze layer) into harmonized schema (Silver layer).
Includes Phase 1 enhancements: previous sample reference, GroupElement.
"""

import pandas as pd
import numpy as np
from typing import Dict
from src.utils.logger import get_logger
from src.processing.name_normalization import normalize_dataframe_names

logger = get_logger(__name__)


def transform_cda_data(df: pd.DataFrame, essays_mapping_df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform CDA (Finning lab) data to harmonized schema.
    
    Args:
        df: Raw CDA DataFrame
        essays_mapping_df: Essays mapping DataFrame
    
    Returns:
        Transformed DataFrame
    """
    logger.info(f"Transforming CDA data: {len(df)} rows")
    
    df = df.copy()
    
    # Rename main columns
    df = df.rename(columns={
        'ID de equipo': 'unitId',
        'No. de control de laboratorio': 'sampleNumber',
        'No. de serie del equipo': 'machineSerialNumber',
        'Component Serial Number': 'componentSerialNumber',
        'Compartimento': 'componentName',
        'Model': 'machineModel',
        'Horas': 'machineHours',
        'Component Meter': 'componentHours',
        'Meter on Fluid': 'oilMeter',
        'Fluid Brand': 'oilBrand',
        'Fluid Type': 'oilType',
        'Fluid Weight': 'oilWeight',
        'Fecha de Toma de Muestra': 'sampleDate'
    })
    
    # Rename essay columns using mapping
    essays_mapping = dict(zip(essays_mapping_df['Element'], essays_mapping_df['ElementNameSpanish']))
    df = df.rename(columns=essays_mapping)
    
    # Convert oilWeight to string
    df['oilWeight'] = df['oilWeight'].astype(str)
    
    # Convert sampleDate to datetime
    df['sampleDate'] = pd.to_datetime(df['sampleDate'], errors='coerce')
    
    # Map model to machine name
    model_to_machine = {
        '789C': 'camion',
        '789D': 'camion',
    }
    df['machineName'] = df['machineModel'].map(model_to_machine)
    df['machineBrand'] = 'caterpillar'
    
    # Lowercase componentName and replace '-' with '_' in unitId
    df['componentName'] = df['componentName'].str.lower()
    df['unitId'] = df['unitId'].str.replace('-', '_', regex=False)
    
    # Add client column
    df['client'] = 'CDA'
    
    # Select valid columns
    valid_columns = [
        'client', 'sampleNumber', 'sampleDate',
        'unitId', 'machineName', 'machineModel', 'machineBrand', 'machineHours', 'machineSerialNumber',
        'componentName', 'componentHours', 'componentSerialNumber',
        'oilMeter', 'oilBrand', 'oilType', 'oilWeight'
    ] + list(essays_mapping_df['ElementNameSpanish'])
    
    # Filter to valid columns that exist
    valid_columns = [col for col in valid_columns if col in df.columns]
    df = df[valid_columns].copy()
    
    logger.info(f"Transformed CDA data: {len(df)} rows, {len(df.columns)} columns")
    return df


def transform_emin_data(df: pd.DataFrame, essays_mapping_df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform EMIN (ALS lab) data to harmonized schema.
    
    ALS data has nested structure: testElementName1/testElementValue1, testElementName2/testElementValue2, etc.
    This function melts and pivots to create one column per essay.
    
    Args:
        df: Raw EMIN DataFrame
        essays_mapping_df: Essays mapping DataFrame
    
    Returns:
        Transformed DataFrame
    """
    logger.info(f"Transforming EMIN data: {len(df)} rows")
    
    df = df.copy()
    
    # Rename main columns
    df = df.rename(columns={
        'equipment_tag': 'unitId',
        'collectionData_dateSampled': 'sampleDate',
        'equipment_family_name': 'machineName',
        'equipment_model': 'machineModel',
        'equipment_maker_name': 'machineBrand',
        'equipment_time': 'machineHours',
        'equipment_serial': 'machineSerialNumber',
        'compartment_name': 'componentName',
        'compartment_id': 'componentSerialNumber',
        'collectionData_fluidTime': 'oilMeter',
        'collectionData_oil_manufacturer_name': 'oilBrand',
        'collectionData_oil_viscosity_name': 'oilType',
    })
    
    # Add missing columns
    df['componentHours'] = None
    df['oilWeight'] = None
    
    # Extract essay columns
    name_cols = [col for col in df.columns if '_test_translation_name' in col]
    value_cols = [col for col in df.columns if '_resultValue' in col]
    unique_col = ['sampleNumber']
    
    # Melt and pivot to transform nested structure
    df_names = df.melt(
        id_vars=unique_col,
        value_vars=name_cols,
        value_name='testName'
    )
    df_names['test_number'] = df_names['variable'].str.extract(r'(\d+)')
    
    df_values = df.melt(
        id_vars=unique_col,
        value_vars=value_cols,
        value_name='testValue'
    )
    df_values['test_number'] = df_values['variable'].str.extract(r'(\d+)')
    
    # Clean test values
    df_values['testValue'] = df_values['testValue'].str.replace('-', '', regex=False)
    df_values['testValue'] = df_values['testValue'].str.replace(',', '.', regex=False)
    df_values['testValue'] = df_values['testValue'].str.replace('<0.05', '0', regex=False)
    df_values['testValue'] = df_values['testValue'].str.replace('>0.05', '0.1', regex=False)
    
    # Convert to numeric
    df_values['testValue'] = pd.to_numeric(df_values['testValue'], errors='coerce')
    df_values = df_values.dropna(subset=['testValue'])
    
    # Merge names and values
    df_melted = pd.merge(
        df_names[unique_col + ['test_number', 'testName']],
        df_values[unique_col + ['test_number', 'testValue']],
        on=unique_col + ['test_number'],
    )
    
    df_melted = df_melted.drop(columns=['test_number'])
    df_melted = df_melted.dropna()
    df_melted = df_melted.sort_values(by=['sampleNumber', 'testName'])
    df_melted = df_melted.reset_index(drop=True)
    
    # Pivot to create essay columns
    df_pivoted = df_melted.pivot(index='sampleNumber', columns='testName', values='testValue')
    
    # Merge back to main dataframe
    df = pd.merge(df, df_pivoted, on='sampleNumber', how='left')
    
    # Convert sampleDate to datetime
    df['sampleDate'] = pd.to_datetime(df['sampleDate'], errors='coerce')
    
    # Lowercase componentName and replace '-' with '_' in unitId
    df['componentName'] = df['componentName'].str.lower()
    df['unitId'] = df['unitId'].str.replace('-', '_', regex=False)
    
    # Add client column
    df['client'] = 'EMIN'
    
    # Select valid columns
    valid_columns = [
        'client', 'sampleNumber', 'sampleDate',
        'unitId', 'machineName', 'machineModel', 'machineBrand', 'machineHours', 'machineSerialNumber',
        'componentName', 'componentHours', 'componentSerialNumber',
        'oilMeter', 'oilBrand', 'oilType', 'oilWeight'
    ] + list(essays_mapping_df['ElementNameSpanish'])
    
    # Filter to valid columns that exist
    valid_columns = [col for col in valid_columns if col in df.columns]
    df = df[valid_columns].copy()
    
    logger.info(f"Transformed EMIN data: {len(df)} rows, {len(df.columns)} columns")
    return df


def add_group_elements(df: pd.DataFrame, essays_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add GroupElement column for radar chart performance visualization (Phase 1 enhancement).
    
    Groups essays into categories like "Desgaste", "Contaminacion", "Condicion", etc.
    
    Args:
        df: DataFrame with essay columns
        essays_df: Essays mapping DataFrame with GroupElement column
    
    Returns:
        DataFrame with GroupElement mapping added
    """
    logger.info("Adding GroupElement column for radar charts")
    
    df = df.copy()
    
    # Check if essays_df has GroupElement column
    if 'GroupElement' not in essays_df.columns:
        logger.warning("GroupElement column not found in essays mapping, skipping")
        return df
    
    # Create mapping of ElementNameSpanish → GroupElement
    element_to_group = dict(zip(
        essays_df['ElementNameSpanish'],
        essays_df['GroupElement']
    ))
    
    # Add as metadata (could be used for filtering/grouping in dashboard)
    df.attrs['element_groups'] = element_to_group
    
    logger.info(f"Added {len(element_to_group)} element-to-group mappings")
    return df


def add_previous_sample_reference(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add previous sample reference columns (Phase 1 enhancement).
    
    For each unit/component combination, find the previous sample and calculate days since.
    
    Args:
        df: DataFrame with sampleNumber, unitId, componentName, sampleDate
    
    Returns:
        DataFrame with previousSampleNumber, previousSampleDate, daysSincePrevious columns
    """
    logger.info("Adding previous sample references")
    
    df = df.copy()
    
    # Sort by unit, component, and date
    df = df.sort_values(['unitId', 'componentName', 'sampleDate'])
    
    # Group by unit and component
    df['previousSampleNumber'] = df.groupby(['unitId', 'componentName'])['sampleNumber'].shift(1)
    df['previousSampleDate'] = df.groupby(['unitId', 'componentName'])['sampleDate'].shift(1)
    
    # Calculate days since previous sample
    df['daysSincePrevious'] = (df['sampleDate'] - df['previousSampleDate']).dt.days
    
    # Fill NaN for first samples
    df['previousSampleNumber'] = df['previousSampleNumber'].fillna('')
    df['daysSincePrevious'] = df['daysSincePrevious'].fillna(0).astype(int)
    
    logger.info(f"Added previous sample references for {df['previousSampleNumber'].notna().sum()} samples")
    return df


def apply_full_transformation(
    df: pd.DataFrame,
    client: str,
    essays_mapping_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Apply complete transformation pipeline: harmonization + normalization + Phase 1 enhancements.
    
    Args:
        df: Raw DataFrame
        client: Client name ('CDA' or 'EMIN')
        essays_mapping_df: Essays mapping DataFrame
    
    Returns:
        Fully transformed DataFrame (Silver layer)
    """
    logger.info(f"Applying full transformation for {client}")
    
    # Transform based on client
    if client.upper() == 'CDA':
        df = transform_cda_data(df, essays_mapping_df)
    elif client.upper() == 'EMIN':
        df = transform_emin_data(df, essays_mapping_df)
    else:
        raise ValueError(f"Unknown client: {client}")
    
    # Normalize names
    df = normalize_dataframe_names(df)
    
    # Add Phase 1 enhancements
    df = add_group_elements(df, essays_mapping_df)
    df = add_previous_sample_reference(df)
    
    logger.info(f"Full transformation complete: {len(df)} rows")
    return df
