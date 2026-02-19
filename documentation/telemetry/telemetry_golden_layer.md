# Telemetry Golden Layer - Alert Detail Data

**Version**: 1.0  
**Created**: February 18, 2026  
**Owner**: Telemetry Data Product Team  
**Status**: ✅ Production Ready

---

## 📋 Overview

This document describes the pre-processed telemetry alert detail data in the golden layer, which significantly simplifies dashboard implementation by providing all required signals, limits, and GPS data for alert visualization in a single file.

**Purpose**: Eliminate the need for complex silver layer data merging and filtering in the dashboard by pre-computing and isolating alert-specific telemetry data.

**Performance Benefits**:
- **OLD Approach**: ~500MB silver layer load + complex merging operations
- **NEW Approach**: ~2MB golden layer load + simple filtering

---

## 📊 Golden Layer File

### Location

```
Local: data/telemetry/golden/{client}/alerts_detail_wide_with_gps.csv
```

### File Structure

**Format**: CSV (Wide Format)  
**Size**: ~2-5 MB (compared to 500MB silver layer)  
**Rows**: Multiple rows per alert (time series data)  
**Update Frequency**: Batch processing after alert generation

---

## 🏗️ Schema

### Metadata Columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `AlertID` | int | Unique telemetry alert identifier | `1`, `2`, `3` |
| `Unit` | string | Equipment unit identifier | `'CAT-001'` |
| `TimeStart` | datetime64[ns] | Timestamp of each data point | `2025-01-01 10:30:00` |
| `Trigger` | string | Sensor that triggered the alert | `'EngCoolTemp'`, `'EngOilPres'` |

### GPS Columns

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `GPSLat` | float | GPS Latitude | `-33.4372` |
| `GPSLon` | float | GPS Longitude | `-70.6506` |
| `GPSElevation` | float | GPS Elevation (meters) | `650.5` |

### Operational State Column

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `State` | string | Operational state | `'Operacional'`, `'Ralenti'`, `'ND'` |

### Signal Columns (Dynamic)

For each monitored signal, there are up to 3 columns:

| Column Pattern | Type | Description | Example Column |
|----------------|------|-------------|----------------|
| `{Feature}_Value` | float | Actual sensor value | `EngCoolTemp_Value` |
| `{Feature}_Upper_Limit` | float | Upper threshold limit | `EngCoolTemp_Upper_Limit` |
| `{Feature}_Lower_Limit` | float | Lower threshold limit | `EngOilPres_Lower_Limit` |

**Common Features**:
- `CnkCasePres`: Crankcase Pressure
- `DiffLubePres`: Differential Lube Pressure
- `DiffTemp`: Differential Temperature
- `EngCoolTemp`: Engine Coolant Temperature
- `EngOilPres`: Engine Oil Pressure
- `EngSpd`: Engine Speed
- `LtFBrkTemp`, `LtRBrkTemp`: Left Front/Rear Brake Temperature
- `RAftrclrTemp`: Right Aftercooler Temperature
- `RtFBrkTemp`, `RtRBrkTemp`: Right Front/Rear Brake Temperature
- `StrgOilTemp`: Steering Oil Temperature
- `TCOutTemp`: Turbocharger Outlet Temperature
- `TrnLubeTemp`: Transmission Lube Temperature

---

## 🔄 Data Processing Logic

### Pre-Processing Steps

1. **Alert Identification**: Identify all alerts from telemetry alerts metadata
2. **Time Window Extraction**: For each alert, extract data from:
   - M1 = 60 minutes before alert
   - M2 = 10 minutes after alert
3. **Feature Selection**: Include all relevant signals for the alert's trigger component
4. **Limit Enrichment**: Merge applicable upper/lower limits based on operational state
5. **GPS Integration**: Include GPS position data for each timestamp
6. **State Integration**: Add operational state information
7. **Wide Format Conversion**: Pivot data to wide format with one row per timestamp
8. **Export**: Save as CSV in golden layer

### Query Example

To retrieve data for a specific alert:

```python
import pandas as pd

# Load golden layer data
alerts_detail = pd.read_csv('data/telemetry/golden/cda/alerts_detail_wide_with_gps.csv')
alerts_detail['TimeStart'] = pd.to_datetime(alerts_detail['TimeStart'])

# Filter for specific alert
alert_id = 15
alert_data = alerts_detail[alerts_detail['AlertID'] == alert_id].copy()

# Drop columns with all NaN values (signals not relevant to this alert)
alert_data_clean = alert_data.dropna(axis=1, how='all')

# Identify features to plot (columns ending with _Value)
value_cols = [col for col in alert_data_clean.columns if col.endswith('_Value')]
feature_names = [col.replace('_Value', '') for col in value_cols]

print(f"Alert {alert_id} has {len(feature_names)} signals:")
print(feature_names)
```

---

## 📈 Dashboard Integration

### OLD Approach (Silver Layer)

**Complexity**: High  
**Data Load**: ~500 MB  
**Operations**:
1. Load telemetry_values (full dataset)
2. Load telemetry_states
3. Load limits_config
4. Load component_mapping
5. Filter by unit and time window
6. Merge states
7. Merge limits based on state/load
8. Select relevant signals
9. Create charts

**Code Volume**: ~150 lines per chart

### NEW Approach (Golden Layer)

**Complexity**: Low  
**Data Load**: ~2 MB  
**Operations**:
1. Load alerts_detail_wide_with_gps
2. Filter by AlertID
3. Drop NaN columns
4. Create charts

**Code Volume**: ~50 lines per chart

**Performance Improvement**: ~10x faster

---

## 🔧 Dashboard Usage

The dashboard uses the following functions to display telemetry evidence:

### Function: `create_sensor_trends_chart_golden()`

**Purpose**: Create time series charts for sensor values with limits

**Input**:
- `alert_data`: Filtered golden layer data for specific alert
- `feature_names`: List of features to plot
- `unit_id`: Unit identifier
- `alert_time`: Alert timestamp

**Output**: Plotly Figure with multi-panel time series

### Function: `create_gps_route_map_golden()`

**Purpose**: Create GPS route visualization

**Input**:
- `alert_data`: Filtered golden layer data for specific alert
- `unit_id`: Unit identifier
- `alert_time`: Alert timestamp
- `mapbox_token`: Mapbox API token

**Output**: Plotly Figure with GPS map

### Function: `create_context_kpis_cards_golden()`

**Purpose**: Create KPI cards with context information

**Input**:
- `alert_data`: Filtered golden layer data for specific alert
- `alert_time`: Alert timestamp
- `trigger`: Trigger feature name

**Output**: Bootstrap Row with KPI cards

---

## 🚀 Implementation Notes

### Column Selection Logic

**Automatic Feature Detection**:
- The dashboard automatically identifies relevant features by detecting columns ending with `_Value`
- For each feature, it looks for corresponding `_Upper_Limit` and `_Lower_Limit` columns
- Columns with all NaN values are dropped (signals not relevant to the alert)

### Missing Data Handling

**NaN Values**:
- **All NaN in column**: Column is dropped (signal not relevant)
- **Partial NaN in column**: Values are plotted where available
- **GPS NaN**: Map section is hidden
- **State NaN**: Data plotted without state coloring

### Extensibility

**Adding New Sensors**:
1. Include sensor in backend pre-processing
2. Add columns: `{NewSensor}_Value`, `{NewSensor}_Upper_Limit`, `{NewSensor}_Lower_Limit`
3. Dashboard automatically detects and displays the new sensor

**No Dashboard Code Changes Required!**

---

## 🔍 Data Quality Checks

### Pre-Processing Validations

1. ✅ **AlertID uniqueness**: No duplicate AlertID-TimeStart combinations
2. ✅ **Time window consistency**: All data points within M1-M2 window
3. ✅ **Limit consistency**: Upper limits always >= Lower limits
4. ✅ **GPS validity**: Lat/Lon within valid ranges when present
5. ✅ **State validity**: State values in allowed set

### Dashboard Validations

1. ✅ **Non-empty data**: Check for empty DataFrames before plotting
2. ✅ **Feature presence**: Verify at least one `_Value` column exists
3. ✅ **Alert time presence**: Verify alert timestamp is within data range
4. ✅ **GPS availability**: Check for GPS columns before creating map

---

## 📝 Change Log

### Version 1.0 (February 18, 2026)
- Initial documentation
- Golden layer file structure defined
- Dashboard integration completed
- Old silver layer approach marked as deprecated

---

**Maintained by**: Data Engineering Team  
**Contact**: data-team@company.com  
**Last Review**: February 18, 2026
