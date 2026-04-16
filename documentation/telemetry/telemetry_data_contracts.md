# Telemetry Data Contracts

**Version**: 1.1.0  
**Last Updated**: April 15, 2026  
**Component**: Telemetry Analysis System

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Layer Architecture](#layer-architecture)
3. [Silver Layer Schemas](#silver-layer-schemas)
4. [Golden Layer Schemas](#golden-layer-schemas)
5. [Data Quality Rules](#data-quality-rules)
6. [Validation Requirements](#validation-requirements)
7. [Change Management](#change-management)

---

## 🎯 Overview

This document defines the **data contracts** for the Telemetry Analysis Pipeline, specifying the schema, data types, constraints, and quality requirements for data flowing through the Silver → Golden layer transformation.

### Contract Scope

- **Silver Layer**: Raw telemetry data ingested from operational systems (input to pipeline)
- **Golden Layer**: Enriched, evaluated, and classified telemetry outputs (consumable by dashboards)

### Design Principles

1. **Backward Compatibility**: Schema changes must not break existing consumers
2. **Explicit Typing**: All columns have defined data types and nullability rules
3. **Validation Gates**: Data quality checks enforce contracts at layer boundaries
4. **Traceability**: Each golden layer row traces back to silver layer sources

---

## 🏗️ Layer Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     BRONZE LAYER (S3)                        │
│              Raw sensor streams from equipment               │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                     SILVER LAYER                             │
│  Cleaned, normalized telemetry with operational states       │
│  Location: data/telemetry/silver/{client}/                   │
│  Format: Parquet (partitioned by week)                       │
│  Schema: [DEFINED BELOW]                                     │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
                ┌────────────────┐
                │  PIPELINE      │
                │  • Scoring     │
                │  • Aggregation │
                │  • Evaluation  │
                └────────┬───────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                     GOLDEN LAYER                             │
│  Evaluated telemetry with health assessments                 │
│  Location: data/telemetry/golden/{client}/                   │
│  Files:                                                       │
│    • machine_status.parquet (machine-level summary)          │
│    • classified.parquet (component-level detail)             │
│    • alerts_data.csv (alert records with system mapping)     │
│    • alerts_detail_wide_with_gps.csv (wide format alerts)    │
└──────────────────────────────────────────────────────────────┘
```

---

## 📥 Silver Layer Schemas

### File Organization

```
data/telemetry/silver/{client}/
├── week_01_2026.parquet
├── week_02_2026.parquet
├── week_03_2026.parquet
└── ...
```

**Partition Strategy**: One file per week (Monday 00:00 to Sunday 23:59)

---

### Schema: `week_{WW}_{YYYY}.parquet`

**Purpose**: Cleaned, normalized telemetry readings with operational context

**Update Frequency**: Daily append (within current week file)

**Retention**: 365 days (52 weeks)

#### Core Columns

| Column | Type | Nullable | Description | Constraints |
|--------|------|----------|-------------|-------------|
| `client` | string | No | Client identifier | Must match `{client}` in path |
| `unit_id` | string | No | Equipment unit identifier | Format: `[A-Z0-9\-]+` |
| `timestamp` | datetime64[ns] | No | Reading timestamp (UTC) | ISO 8601 format |
| `EstadoMaquina` | string | Yes | Operational state | Values: `'Operacional'`, `'Ralenti'`, `'Apagada'`, `'ND'` |

#### GPS Columns

| Column | Type | Nullable | Description | Constraints |
|--------|------|----------|-------------|-------------|
| `GPSLat` | float64 | Yes | GPS Latitude | Range: -90.0 to 90.0 |
| `GPSLon` | float64 | Yes | GPS Longitude | Range: -180.0 to 180.0 |
| `GPSElevation` | float64 | Yes | Elevation (meters) | Range: -500.0 to 7000.0 |

#### Signal Columns (Dynamic)

For each monitored sensor signal:

| Column Pattern | Type | Nullable | Description | Example |
|----------------|------|----------|-------------|---------|
| `{SignalName}` | float64 | Yes | Sensor reading value | `EngCoolTemp`, `EngOilPres` |

**Standard Signals** (may vary by equipment model):

- **Engine**:
  - `EngCoolTemp`: Engine Coolant Temperature (°C)
  - `EngOilPres`: Engine Oil Pressure (kPa)
  - `EngSpd`: Engine Speed (RPM)
  - `TCOutTemp`: Turbocharger Outlet Temperature (°C)
  - `CnkCasePres`: Crankcase Pressure (kPa)

- **Transmission**:
  - `TrnLubeTemp`: Transmission Lube Temperature (°C)
  - `TrnOilPres`: Transmission Oil Pressure (kPa)

- **Brakes**:
  - `LtFBrkTemp`: Left Front Brake Temperature (°C)
  - `LtRBrkTemp`: Left Rear Brake Temperature (°C)
  - `RtFBrkTemp`: Right Front Brake Temperature (°C)
  - `RtRBrkTemp`: Right Rear Brake Temperature (°C)

- **Hydraulics**:
  - `StrgOilTemp`: Steering Oil Temperature (°C)
  - `StrgOilPres`: Steering Oil Pressure (kPa)

- **Differential**:
  - `DiffTemp`: Differential Temperature (°C)
  - `DiffLubePres`: Differential Lube Pressure (kPa)

- **Cooling System**:
  - `RAftrclrTemp`: Right Aftercooler Temperature (°C)
  - `LAftrclrTemp`: Left Aftercooler Temperature (°C)

#### Data Quality Metadata (Optional)

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `data_quality_flag` | string | Yes | Quality indicator: `'valid'`, `'suspicious'`, `'imputed'` |
| `source_system` | string | Yes | Originating data source |

#### Example Row

```python
{
    "client": "cda",
    "unit_id": "CAT797-001",
    "timestamp": "2026-02-15 14:30:00",
    "EstadoMaquina": "Operacional",
    "GPSLat": -23.4372,
    "GPSLon": -69.6506,
    "GPSElevation": 2450.5,
    "EngCoolTemp": 88.5,
    "EngOilPres": 425.0,
    "EngSpd": 1850.0,
    "TrnLubeTemp": 72.3,
    "LtFBrkTemp": 145.2,
    "RtFBrkTemp": 148.7,
    "StrgOilTemp": 65.8,
    "DiffTemp": 68.5,
    "TCOutTemp": 320.5,
    "data_quality_flag": "valid"
}
```

#### Nullability Rules

- **Nullable Signals**: Missing sensor readings are marked as `null` (not `0.0` or `-999.0`)
- **State Handling**: If `EstadoMaquina` is `null`, default to `'ND'` (Not Determined)
- **GPS Handling**: GPS fields may be `null` for units without GPS hardware or indoor operation

---

## 📤 Golden Layer Schemas

### 1. Machine Status Summary

#### File: `machine_status.parquet`

**Purpose**: Machine-level health evaluation (one row per unit per evaluation period)

**Location**: `data/telemetry/golden/{client}/machine_status.parquet`

**Update Frequency**: Weekly (append mode with deduplication)

**Retention**: Historical time-series (all evaluation periods preserved)

**Use Case**: Fleet health monitoring, trend analysis, offline unit detection

**Deduplication**: Records are deduplicated on `(unit_id, evaluation_week, evaluation_year)` - latest evaluation wins

**Edge Case Handling**: Units with no data in evaluation week are included with `overall_status='InsufficientData'`

#### Schema

| Column | Type | Nullable | Description | Constraints |
|--------|------|----------|-------------|-------------|
| `unit_id` | string | No | Unit identifier | Matches silver layer `unit_id` |
| `evaluation_week` | int32 | No | ISO week number | Range: 1-53 |
| `evaluation_year` | int32 | No | Year | Format: YYYY |
| `overall_status` | string | No | Machine health classification | Values: `'Normal'`, `'Alerta'`, `'Anormal'`, `'InsufficientData'` |
| `machine_score` | float64 | No | Aggregate severity score | Range: ≥ 0.0 (no upper limit) |
| `priority_score` | float64 | No | Fleet ranking score (higher = worse) | Range: ≥ 0.0 |
| `components_normal` | int32 | No | Count with Normal status | Range: 0 to total_components |
| `components_alerta` | int32 | No | Count with Alerta status | Range: 0 to total_components |
| `components_anormal` | int32 | No | Count with Anormal status | Range: 0 to total_components |
| `components_insufficient` | int32 | No | Count with InsufficientData status | Range: 0 to total_components |
| `total_components` | int32 | No | Number of components evaluated | Range: ≥ 1 |
| `baseline_version` | string | No | Baseline file identifier | Format: `YYYYMMDD` |
| `component_details` | string (JSON) | No | Per-component evaluation details | Valid JSON array (empty if InsufficientData) |

#### Component Details JSON Schema

The `component_details` column contains a JSON array of component evaluation objects:

```json
[
  {
    "component": "Engine",
    "status": "Anormal",
    "score": 0.52,
    "coverage": 0.85,
    "criticality_weight": 3,
    "signals_count": 6,
    "triggering_signals": ["EngCoolTemp", "EngOilPres"],
    "signal_details": {
      "EngCoolTemp": {
        "status": "Anormal",
        "window_score_normalized": 1.2,
        "severity": 1.0,
        "weight": 1.0
      }
    }
  }
]
```

#### Example Rows

**Unit with data:**
```python
{
    "unit_id": "CAT797-001",
    "evaluation_week": 8,
    "evaluation_year": 2026,
    "overall_status": "Alerta",
    "machine_score": 1.86,
    "priority_score": 120.86,
    "components_normal": 9,
    "components_alerta": 2,
    "components_anormal": 1,
    "components_insufficient": 0,
    "total_components": 12,
    "baseline_version": "20260201",
    "component_details": "[{...}]"  # JSON string
}
```

**Unit without data (offline/missing):**
```python
{
    "unit_id": "CAT797-002",
    "evaluation_week": 8,
    "evaluation_year": 2026,
    "overall_status": "InsufficientData",
    "machine_score": 0.0,
    "priority_score": 0.0,
    "components_normal": 0,
    "components_alerta": 0,
    "components_anormal": 0,
    "components_insufficient": 12,
    "total_components": 12,
    "baseline_version": "20260201",
    "component_details": "[]"  # Empty array
}
```

#### Time-Series Queries

Since `machine_status.parquet` contains historical records, you can track fleet health evolution:

```python
import pandas as pd

# Load historical data
machine_df = pd.read_parquet('data/telemetry/golden/cda/machine_status.parquet')

# Track overall status for specific unit over time
unit_history = machine_df[
    machine_df['unit_id'] == 'CAT797-001'
].sort_values(['evaluation_year', 'evaluation_week'])

# Identify units that went offline
offline_units = machine_df[
    (machine_df['overall_status'] == 'InsufficientData') &
    (machine_df['evaluation_week'] == 8) &
    (machine_df['evaluation_year'] == 2026)
]['unit_id'].tolist()

# Fleet health trend
fleet_trend = machine_df.groupby(['evaluation_year', 'evaluation_week']).agg({
    'overall_status': lambda x: (x == 'Anormal').sum(),
    'unit_id': 'count'
}).rename(columns={'overall_status': 'anormal_count', 'unit_id': 'total_units'})
```

---

### 2. Component Classification

#### File: `classified.parquet`

**Purpose**: Component-level evaluation detail (one row per unit-component-week)

**Location**: `data/telemetry/golden/{client}/classified.parquet`

**Update Frequency**: Weekly (append mode with deduplication)

**Retention**: Historical time-series (all evaluation periods preserved)

**Use Case**: Trend analysis, forecasting, component health evolution tracking

**Deduplication**: Records are deduplicated on `(unit_id, component, evaluation_week, evaluation_year)` - latest evaluation wins

#### Schema

| Column | Type | Nullable | Description | Constraints |
|--------|------|----------|-------------|-------------|
| `unit_id` | string | No | Unit identifier | Matches silver layer `unit_id` |
| `component` | string | No | Component name | Example: `'Engine'`, `'Transmission'` |
| `evaluation_week` | int32 | No | ISO week number | Range: 1-53 |
| `evaluation_year` | int32 | No | Year | Format: YYYY |
| `component_status` | string | No | Component health classification | Values: `'Normal'`, `'Alerta'`, `'Anormal'`, `'InsufficientData'` |
| `component_score` | float64 | No | Weighted severity score | Range: 0.0-1.0 |
| `triggering_signals` | string (JSON) | No | Signals with non-Normal status | Valid JSON array |
| `signals_evaluation` | string (JSON) | No | Per-signal scores and statuses | Valid JSON object |
| `signal_coverage` | float64 | No | Fraction of signals with sufficient data | Range: 0.0-1.0 |
| `sample_count_avg` | float64 | Yes | Average sample count across signals | Range: ≥ 0 |
| `criticality` | int32 | No | Component criticality factor | Range: 1-3 |
| `baseline_version` | string | No | Baseline file identifier | Format: `YYYYMMDD` |

#### Signals Evaluation JSON Schema

```json
{
  "EngCoolTemp": {
    "status": "Anormal",
    "window_score_normalized": 1.2,
    "severity": 1.0,
    "weight": 1.0,
    "baseline": {
      "p2": 75.0,
      "p5": 78.0,
      "p95": 95.0,
      "p98": 98.0
    },
    "observed_range": [92.0, 102.0],
    "anomaly_percentage": 45.2,
    "sample_count": 1008
  }
}
```

#### Example Row

```python
{
    "unit_id": "CAT797-001",
    "component": "Engine",
    "evaluation_week": 8,
    "evaluation_year": 2026,
    "component_status": "Anormal",
    "component_score": 0.52,
    "triggering_signals": '["EngCoolTemp", "EngOilPres"]',  # JSON string
    "signals_evaluation": "{...}",  # JSON string
    "signal_coverage": 0.85,
    "sample_count_avg": 1008.0,
    "criticality": 3,
    "baseline_version": "20260201"
}
```

#### Time-Series Queries

Since `classified.parquet` contains historical records, you can track component health evolution:

```python
import pandas as pd

# Load historical data
classified_df = pd.read_parquet('data/telemetry/golden/cda/classified.parquet')

# Track engine health for specific unit over time
unit_engine_history = classified_df[
    (classified_df['unit'] == 'CAT797-001') & 
    (classified_df['component'] == 'Engine')
].sort_values(['evaluation_year', 'evaluation_week'])

# Identify degradation trends (comparing recent 4 weeks vs older 4 weeks)
degrading_components = classified_df.groupby(['unit', 'component']).apply(
    lambda x: x.sort_values(['evaluation_year', 'evaluation_week'])
                .tail(4)['component_score'].mean() > 
              x.sort_values(['evaluation_year', 'evaluation_week'])
                .head(4)['component_score'].mean()
)
```

---

### 3. Alerts Data

#### File: `alerts_data.csv`

**Purpose**: Generated telemetry alerts with system/subsystem mapping

**Location**: `data/telemetry/golden/{client}/alerts_data.csv`

**Update Frequency**: Weekly (overwrite)

**Retention**: Historical files archived with date suffix

#### Schema

| Column | Type | Nullable | Description | Constraints |
|--------|------|----------|-------------|-------------|
| `AlertID` | int64 | No | Unique alert identifier | Auto-incrementing, unique within file |
| `Unit` | string | No | Equipment unit identifier | Matches silver layer `unit_id` |
| `Trigger` | string | No | Sensor that triggered alert | Must be valid signal name |
| `Context` | string | Yes | Additional context information | Free text |
| `Engineer` | string | Yes | Assigned engineer | Name or ID |
| `Technician` | string | Yes | Assigned technician | Name or ID |
| `Fecha` | datetime64[ns] | No | Alert generation timestamp | ISO 8601 format |
| `System` | string | Yes | Affected system | Example: `'Engine'`, `'Transmission'`, `'Hydraulics'` |
| `SubSystem` | string | Yes | Affected subsystem | Example: `'Radiator'`, `'Lubrication'`, `'Cooling'` |

#### System/SubSystem Mapping

| Trigger Signal | System | SubSystem |
|----------------|--------|-----------|
| `EngCoolTemp` | Engine | Cooling |
| `EngOilPres` | Engine | Lubrication |
| `EngSpd` | Engine | Combustion |
| `TCOutTemp` | Engine | Turbocharger |
| `TrnLubeTemp` | Transmission | Lubrication |
| `TrnOilPres` | Transmission | Hydraulics |
| `LtFBrkTemp`, `LtRBrkTemp`, `RtFBrkTemp`, `RtRBrkTemp` | Brakes | Friction |
| `StrgOilTemp`, `StrgOilPres` | Steering | Hydraulics |
| `DiffTemp`, `DiffLubePres` | Differential | Lubrication |

#### Example Rows

```csv
AlertID,Unit,Trigger,Context,Engineer,Technician,Fecha,System,SubSystem
1,CAT797-001,EngCoolTemp,High temp detected,John Doe,Jane Smith,2026-02-15 14:30:00,Engine,Cooling
2,CAT797-001,EngOilPres,Low pressure,John Doe,Jane Smith,2026-02-15 16:45:00,Engine,Lubrication
3,CAT797-002,TrnLubeTemp,Elevated temp,Mike Wilson,Sarah Connor,2026-02-16 09:15:00,Transmission,Lubrication
```

---

### 4. Alerts Detail Wide Format

#### File: `alerts_detail_wide_with_gps.csv`

**Purpose**: Wide format alert records with GPS coordinates and sensor readings

**Location**: `data/telemetry/golden/{client}/alerts_detail_wide_with_gps.csv`

**Update Frequency**: Weekly (overwrite)

**Retention**: Historical files archived with date suffix

#### Schema

##### Metadata Columns

| Column | Type | Nullable | Description | Constraints |
|--------|------|----------|-------------|-------------|
| `AlertID` | int64 | No | Unique telemetry alert identifier | Links to `alerts_data.csv` |
| `Alert_TimeStart` | datetime64[ns] | Yes | Alert start timestamp | ISO 8601 format |
| `Alert_Index` | int64 | Yes | Alert sequence index | Sequential number |
| `Trigger` | string | No | Sensor that triggered the alert | Must be valid signal name |
| `TimeStart` | datetime64[ns] | No | Alert data point timestamp | ISO 8601 format |
| `Unit` | string | No | Equipment unit identifier | Matches silver layer `unit_id` |
| `Payload_Value` | float64 | Yes | Triggering signal value | Sensor reading |

##### GPS Columns

| Column | Type | Nullable | Description | Constraints |
|--------|------|----------|-------------|-------------|
| `GPSLat` | float64 | Yes | GPS Latitude | Range: -90.0 to 90.0 |
| `GPSLon` | float64 | Yes | GPS Longitude | Range: -180.0 to 180.0 |
| `GPSElevation` | float64 | Yes | GPS Elevation (meters) | Range: -500.0 to 7000.0 |

##### Operational State Column

| Column | Type | Nullable | Description | Constraints |
|--------|------|----------|-------------|-------------|
| `State` | string | Yes | Operational state | Values: `'Operacional'`, `'Ralenti'`, `'Apagada'`, `'ND'` |
| `SubState` | string | Yes | Sub-operational state | Additional state detail |
| `PayloadState` | string | Yes | Payload-specific state | State when alert occurred |

##### Signal Columns (Dynamic)

For each monitored signal, there are up to **3 columns**:

| Column Pattern | Type | Nullable | Description | Example |
|----------------|------|----------|-------------|---------|
| `{Feature}_Value` | float64 | Yes | Actual sensor reading | `EngCoolTemp_Value` |
| `{Feature}_Upper_Limit` | float64 | Yes | Upper threshold (P98) | `EngCoolTemp_Upper_Limit` |
| `{Feature}_Lower_Limit` | float64 | Yes | Lower threshold (P2) | `EngOilPres_Lower_Limit` |

**Common Feature Columns**:
- `CnkCasePres_Value`, `CnkCasePres_Upper_Limit`, `CnkCasePres_Lower_Limit`
- `DiffLubePres_Value`, `DiffLubePres_Upper_Limit`, `DiffLubePres_Lower_Limit`
- `DiffTemp_Value`, `DiffTemp_Upper_Limit`, `DiffTemp_Lower_Limit`
- `EngCoolTemp_Value`, `EngCoolTemp_Upper_Limit`, `EngCoolTemp_Lower_Limit`
- `EngOilPres_Value`, `EngOilPres_Upper_Limit`, `EngOilPres_Lower_Limit`
- `EngSpd_Value`, `EngSpd_Upper_Limit`, `EngSpd_Lower_Limit`
- `LtFBrkTemp_Value`, `LtFBrkTemp_Upper_Limit`, `LtFBrkTemp_Lower_Limit`
- `LtRBrkTemp_Value`, `LtRBrkTemp_Upper_Limit`, `LtRBrkTemp_Lower_Limit`
- `RAftrclrTemp_Value`, `RAftrclrTemp_Upper_Limit`, `RAftrclrTemp_Lower_Limit`
- `RtFBrkTemp_Value`, `RtFBrkTemp_Upper_Limit`, `RtFBrkTemp_Lower_Limit`
- `RtRBrkTemp_Value`, `RtRBrkTemp_Upper_Limit`, `RtRBrkTemp_Lower_Limit`
- `StrgOilTemp_Value`, `StrgOilTemp_Upper_Limit`, `StrgOilTemp_Lower_Limit`
- `TCOutTemp_Value`, `TCOutTemp_Upper_Limit`, `TCOutTemp_Lower_Limit`
- `TrnLubeTemp_Value`, `TrnLubeTemp_Upper_Limit`, `TrnLubeTemp_Lower_Limit`

#### Limit Calculation

- **Upper_Limit**: Corresponds to **P98** baseline percentile for the signal
- **Lower_Limit**: Corresponds to **P2** baseline percentile for the signal
- Limits are **state-specific** when possible (based on `State` column)

#### Example Row

```csv
AlertID,Alert_TimeStart,Alert_Index,Trigger,TimeStart,Unit,Payload_Value,GPSLat,GPSLon,GPSElevation,State,SubState,PayloadState,EngCoolTemp_Value,EngCoolTemp_Upper_Limit,EngCoolTemp_Lower_Limit,EngOilPres_Value,EngOilPres_Upper_Limit,EngOilPres_Lower_Limit,...
1,2026-02-15 14:25:00,0,EngCoolTemp,2026-02-15 14:30:00,CAT797-001,102.5,-23.4372,-69.6506,2450.5,Operacional,SubState1,PayloadState1,102.5,98.0,75.0,425.0,550.0,320.0,...
```

---

## ✅ Data Quality Rules

### Silver Layer Quality Gates

Before data enters the Silver layer, enforce these rules:

1. **Timestamp Validity**
   - No future timestamps (must be ≤ current time)
   - No duplicate `(unit_id, timestamp)` pairs within same file
   - Timestamps must be in UTC timezone

2. **Unit Identifier Consistency**
   - Must match known fleet registry
   - Format validation: alphanumeric + hyphens only

3. **Signal Range Validation**
   - All numeric signals must be within physically plausible ranges
   - Example: `EngCoolTemp` ∈ [-50, 200]°C, `EngOilPres` ∈ [0, 1000] kPa
   - Out-of-range values → `null` (not coerced to bounds)

4. **State Consistency**
   - If `EstadoMaquina = 'Apagada'`, expect near-zero readings for most signals
   - If `EngSpd = 0`, state should not be `'Operacional'`

5. **GPS Consistency**
   - If GPS fields provided, all three (`GPSLat`, `GPSLon`, `GPSElevation`) should be populated together
   - GPS changes > 100km between consecutive readings → flag for manual review

### Golden Layer Quality Gates

Before writing Golden layer outputs:

1. **Completeness**
   - Every `unit_id` in Silver must have corresponding rows in Golden layer
   - `component_details` JSON must be parseable and valid
   - No `null` values in non-nullable columns

2. **Referential Integrity**
   - `alerts_data.csv` → `AlertID` must match `alerts_detail_wide_with_gps.csv`
   - `classified.parquet` → `component` names must match `component_signals_mapping.json`
   - `machine_status.parquet` → Sum of `components_{normal|alerta|anormal|insufficient_data}` = `total_components`

3. **Score Consistency**
   - `component_score` ∈ [0.0, 1.0]
   - `machine_score` ≥ 0.0 (no upper limit, scales with affected components)
   - `priority_score` = `100 * components_anormal + 10 * components_alerta + machine_score`

4. **Status Logic**
   - If `overall_status = 'Anormal'` → `components_anormal` ≥ 1
   - If `overall_status = 'Normal'` → `components_alerta = 0` AND `components_anormal = 0`

5. **Baseline Traceability**
   - `baseline_version` must reference existing baseline file in `data/telemetry/golden/{client}/baselines/`

---

## 🔍 Validation Requirements

### Automated Validation Checks

Implement the following validation tests in `src/data/validator.py`:

#### Silver Layer Validation

```python
def validate_silver_layer(df: pd.DataFrame, client: str) -> ValidationReport:
    """
    Validates silver layer telemetry data.
    
    Checks:
    - No missing values in required columns (unit_id, timestamp, client)
    - Timestamps are in valid range (past dates only)
    - No duplicate (unit_id, timestamp) pairs
    - Signal values within plausible physical ranges
    - GPS coordinates within valid geographic bounds
    - Client identifier matches directory path
    
    Returns:
        ValidationReport with passed/failed checks and violation details
    """
```

#### Golden Layer Validation

```python
def validate_golden_layer_machine_status(df: pd.DataFrame) -> ValidationReport:
    """
    Validates machine_status.parquet schema and business rules.
    
    Checks:
    - All required columns present with correct dtypes
    - Status values in allowed enum: {'Normal', 'Alerta', 'Anormal'}
    - Score ranges: component_score ∈ [0,1], machine_score ≥ 0
    - Component count consistency
    - priority_score formula correctness
    - JSON fields are parseable
    - baseline_version references existing file
    
    Returns:
        ValidationReport with passed/failed checks
    """

def validate_golden_layer_classified(df: pd.DataFrame) -> ValidationReport:
    """
    Validates classified.parquet schema and business rules.
    
    Checks:
    - Component names match component_signals_mapping.json
    - component_score ∈ [0.0, 1.0]
    - component_coverage ∈ [0.0, 1.0]
    - JSON fields are valid and parseable
    - Triggering signals exist in signals_evaluation
    
    Returns:
        ValidationReport with passed/failed checks
    """

def validate_alerts_referential_integrity(
    alerts_data_df: pd.DataFrame,
    alerts_detail_df: pd.DataFrame
) -> ValidationReport:
    """
    Validates referential integrity between alerts files.
    
    Checks:
    - Every AlertID in alerts_data exists in alerts_detail
    - Every AlertID in alerts_detail exists in alerts_data
    - Matching Unit and Trigger values for same AlertID
    
    Returns:
        ValidationReport with orphaned records
    """
```

### Validation Report Format

```python
@dataclass
class ValidationReport:
    dataset_name: str
    validation_timestamp: datetime
    total_checks: int
    passed_checks: int
    failed_checks: int
    violations: List[ValidationViolation]
    
    @property
    def is_valid(self) -> bool:
        return self.failed_checks == 0

@dataclass
class ValidationViolation:
    check_name: str
    severity: str  # 'ERROR' | 'WARNING'
    message: str
    affected_rows: Optional[List[int]]
    sample_values: Optional[List[Any]]
```

### Validation Execution Points

1. **Pre-Pipeline**: Validate Silver layer before processing
2. **Post-Pipeline**: Validate Golden layer before writing files
3. **On-Demand**: Manual validation via CLI command

```bash
# Validate silver layer for week 08-2026
python -m src.data.validator --layer silver --client cda --week 08 --year 2026

# Validate golden layer outputs
python -m src.data.validator --layer golden --client cda --week 08 --year 2026

# Validate all layers
python -m src.data.validator --layer all --client cda --week 08 --year 2026
```

---

## 🔄 Change Management

### Schema Evolution Policy

#### Adding New Columns

✅ **Allowed** (Backward Compatible):
- Add nullable columns to end of schema
- Add new signal columns to Silver layer (equipment upgrades)
- Add new fields to JSON objects in Golden layer

**Requirements**:
- Update this contract document
- Add validation rules for new columns
- Ensure existing consumers ignore unknown columns

#### Modifying Existing Columns

⚠️ **Requires Deprecation Period**:
- Changing column data types
- Changing column names
- Making nullable columns non-nullable

**Process**:
1. Add new column with desired schema
2. Populate both old and new columns for **4 weeks** (deprecation period)
3. Update all consumers to use new column
4. Remove old column after deprecation period
5. Publish migration guide

#### Removing Columns

❌ **Forbidden** (unless deprecated):
- Cannot remove columns without 4-week deprecation notice
- Must verify no active consumers before removal

### Versioning Strategy

#### Contract Version Format

`<major>.<minor>.<patch>`

- **Major**: Breaking changes (column removal, type changes)
- **Minor**: Additive changes (new columns)
- **Patch**: Documentation updates, clarifications

#### Current Version: 1.0.0

**Change Log**:
- `1.0.0` (2026-02-24): Initial telemetry data contracts specification

### Communication Process

When contract changes are proposed:

1. **RFC Document**: Create Request for Comments with:
   - Motivation for change
   - Proposed schema modifications
   - Impact analysis (affected consumers)
   - Migration strategy

2. **Review Period**: 1 week minimum for stakeholder feedback

3. **Approval**: Requires sign-off from:
   - Pipeline maintainer
   - Dashboard team
   - Data engineering lead

4. **Implementation**:
   - Update contract document (this file)
   - Update validation rules
   - Publish migration guide
   - Execute deprecation process if needed

5. **Monitoring**: Track adoption and rollback plan for 2 weeks post-deployment

---

## 📚 Related Documentation

- [Project Overview](project_overview.md) - Architecture and methodology
- [Integration Plan](integration_plan.md) - Implementation roadmap
- [Programming Rules](programming_rules.md) - Code standards
- [Dashboard Proposal](dashboard_proposal.md) - Visualization layer

---

## 📝 Version History

### Version 1.1.0 (April 15, 2026)
- **Updated schemas to match actual data implementation**:
  - `machine_status.parquet`: Removed `client`, `evaluation_start`, `evaluation_end`, `latest_sample_date`, `total_signals_evaluated`, `total_signals_triggered`; renamed `components_insufficient_data` to `components_insufficient`
  - `classified.parquet`: Added `unit_id` and `sample_count_avg`; removed `client`, `date`, `signal_weights`, `ai_recommendation`; renamed `component_coverage` to `signal_coverage`, `criticality_weight` to `criticality`
  - `alerts_data.csv`: Added `Context`, `Engineer`, `Technician` columns
  - `alerts_detail_wide_with_gps.csv`: Added `Alert_TimeStart`, `Alert_Index`, `Payload_Value`, `SubState`, `PayloadState` columns
- **Documentation now reflects production data schemas as of April 2026**

### Version 1.0.0 (February 24, 2026)
- Initial data contracts specification
- Silver layer schema: weekly telemetry parquet files
- Golden layer schemas:
  - `machine_status.parquet` (machine-level summary)
  - `classified.parquet` (component-level detail)
  - `alerts_data.csv` (alert records with system mapping)
  - `alerts_detail_wide_with_gps.csv` (wide format alerts with GPS)
- Data quality rules and validation requirements
- Schema evolution and change management policies
