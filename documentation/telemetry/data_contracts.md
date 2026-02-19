# Data Contracts - Telemetry Data Product

**Version**: 1.1  
**Last Updated**: February 18, 2026  
**Owner**: Telemetry Data Product Team

---

## 📋 Important Updates - February 2026

### NEW: Golden Layer Alert Detail File

A new golden layer file has been added: **`alerts_detail_wide_with_gps.csv`**

**Purpose**: Pre-processed telemetry data for alert visualization, eliminating the need to load large silver layer files in the dashboard.

**Key Benefits**:
- ✅ 10x faster data loading (2MB vs 500MB)
- ✅ 70% less code complexity  
- ✅ No complex merging operations needed
- ✅ All signals, limits, and GPS pre-integrated

**Full Documentation**: See `telemetry_golden_layer.md`

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Data Layer Architecture](#data-layer-architecture)
3. [Silver Layer](#silver-layer)
4. [Golden Layer](#golden-layer)
5. [Data Quality Rules](#data-quality-rules)

---

## 🎯 Overview

This document defines the data contracts for the Telemetry Data Product, which processes real-time sensor data from mining equipment to detect operational anomalies and generate alerts.

**Data Product Purpose**: Monitor equipment sensor data in real-time, apply state-aware thresholds, and generate contextualized alerts for maintenance teams.

**Primary Consumers**:
- Multi-Technical Alerts Dashboard
- Real-time monitoring systems
- Predictive maintenance models
- Fleet management applications

---

## 🏗️ Data Layer Architecture

### Local Storage Structure

```
data/
└── telemetry/
    ├── silver/                              # Harmonized sensor data
    │   └── {client}/
    │       ├── telemetry_values_wide.parquet  # Sensor values (wide format)
    │       ├── telemetry_states.parquet       # Equipment states (long format)
    │       └── limits_config.parquet          # Alert trigger rules & thresholds
    └── golden/                              # Analysis-ready outputs
        └── {client}/
            ├── alerts_data.csv              # Generated alerts
            └── component_mapping.parquet    # Component-to-feature mapping
```

---

## 🔄 Silver Layer

**Purpose**: Harmonized sensor data with GPS tracking, states, and alert thresholds  
**Update Frequency**: Real-time / Continuous  
**Retention**: Rolling window (configurable)  
**Format**: Parquet (columnar, compressed)

### Location

```
Local: data/telemetry/silver/{client}/
```

---

### 1. Main Telemetry Values Table (`telemetry_values_wide.parquet`)

**Purpose**: Wide-format sensor readings with GPS data for efficient querying

**Schema**:

| Column   | Type           | Description                      | Example           |
|----------|----------------|----------------------------------|-------------------|
| `Fecha`  | datetime64[ns] | Timestamp of the record          | `2024-02-05 12:00:00` |
| `Unit`   | category       | Machine or unit identifier       | `'Frankie_V2'`    |
| `Feature1` | float32      | Sensor value for Feature1        | `12.5`            |
| `Feature2` | float32      | Sensor value for Feature2        | `7.8`             |
| `...`    | float32        | Additional sensor values         | `...`             |
| `FeatureN` | float32      | Sensor value for FeatureN        | `3.2`             |
| `GPSLat` | float32        | Latitude coordinate              | `-30.2`           |
| `GPSLon` | float32        | Longitude coordinate             | `-71.1`           |
| `GPSElevation` | float32  | Elevation in meters              | `900.1`           |

**Common Features** (sensor columns):
- `EngCoolTemp`: Engine coolant temperature
- `EngOilPres`: Engine oil pressure

**Quality Rules**:
- ✅ Valid datetime format
- ✅ Unit is categorical (memory optimized)
- ✅ All sensor values are float32 (memory optimized)
- ✅ GPS coordinates within valid ranges (Lat: -31 to -30, Lon: -72 to -70)
- ✅ No duplicate (Fecha, Unit) combinations

**Use Cases**:
- Time-series analysis of sensor data
- Multi-variable correlation analysis
- Equipment location tracking
- Efficient filtering and aggregations

---

### 2. States Table (`telemetry_states.parquet`)

**Purpose**: Lightweight table tracking equipment operational and load states

**Schema**:

| Column      | Type           | Description                          | Example           |
|-------------|----------------|--------------------------------------|-------------------|
| `Fecha`     | datetime64[ns] | Timestamp of the record              | `2024-02-05 12:00:00` |
| `Unit`      | category       | Machine or unit identifier           | `'Frankie_V2'`    |
| `Estado`    | category       | Operational state                    | `'Operacional'`   |
| `EstadoCarga` | category     | Load state                           | `'Cargado'`       |

**Operational States** (`Estado`):
- `Ralenti`: Idle state (engine running, no load)
- `Operacional`: Active operation (engine running with load)
- `Apagado`: Shut down
- `Mantencion`: Under maintenance

**Payload States** (`EstadoCarga`):
- `Sin Carga`: Empty / No payload
- `Cargado`: Loaded with payload
- `Cargando`: Loading in progress
- `Descargando`: Unloading in progress

**Quality Rules**:
- ✅ Valid datetime format
- ✅ All string columns stored as categorical (memory optimized)
- ✅ Estado and EstadoCarga from predefined lists
- ✅ No duplicate (Fecha, Unit) combinations
- ✅ Non-null values for all columns

**Use Cases**:
- Join with values table to get state context
- Filter data by operational mode
- State transition analysis
- Equipment availability reporting

---

### 3. Limits Configuration Table (`limits_config.parquet`)

**Purpose**: Static reference table defining alert thresholds per feature, unit, and state combination

**Schema**:

| Column       | Type     | Description                        | Example           |
|--------------|----------|------------------------------------|-------------------|
| `Unit`       | category | Machine or unit identifier         | `'CAT_001'`       |
| `Feature`    | category | Variable name (sensor feature)     | `'EngCoolTemp'`   |
| `Estado`     | category | Operational state                  | `'Operacional'`   |
| `EstadoCarga` | category | Load state                        | `'Cargado'`       |
| `Limit_Lower` | float32 | Lower threshold for the feature    | `80.0`            |
| `Limit_Upper` | float32 | Upper threshold for the feature    | `110.0`           |

**Alert Logic**:
```
Alert Generated = TRUE IF Feature_Value < Limit_Lower OR Feature_Value > Limit_Upper
Alert Generated = FALSE OTHERWISE
```

**Example Configuration**:

| Unit | Feature | Estado | EstadoCarga | Limit_Lower | Limit_Upper |
|------|---------|--------|-------------|-------------|-------------|
| Frankie_V2 | EngCoolTemp | Operacional | Cargado | 75.0 | 105.0 |
| Frankie_V2 | EngCoolTemp | Ralenti | Sin Carga | 70.0 | 95.0 |
| Frankie_V2 | EngOilPres | Operacional | Cargado | 40.0 | 80.0 |
| Frankie_V2 | EngOilPres | Ralenti | Sin Carga | 30.0 | 70.0 |

**Quality Rules**:
- ✅ Unique combination of (Unit, Feature, Estado, EstadoCarga)
- ✅ `Limit_Lower` < `Limit_Upper`
- ✅ All categorical columns stored as category dtype
- ✅ All features from values table have rules defined
- ✅ Coverage for all state combinations per unit

**Use Cases**:
- Real-time alert evaluation alongside sensor values
- State-aware threshold checking
- Dynamic limit visualization in dashboards
- Alert configuration management

---

## 🏆 Golden Layer

**Purpose**: Processed alerts and reference mappings  
**Update Frequency**: Real-time for alerts, static for mappings  
**Retention**: Historical archive  
**Format**: CSV / Parquet

### Location

```
Local: data/telemetry/golden/{client}/
```

---

### 1. Alerts Data (`alerts_data.csv`)

**Purpose**: Generated telemetry alerts with system context

**Schema**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `AlertID` | int | Unique alert identifier | `1`, `2`, `3` |
| `Fecha` | datetime64[ns] | Alert timestamp | `2025-01-01 00:00:00` |
| `Unit` | string | Equipment unit identifier | `'CAT-001'` |
| `Trigger` | string | Sensor that triggered alert | `'EngCoolTemp'`, `'EngOilPres'` |
| `System` | string | Affected system | `'Engine'`, `'Transmission'` |
| `SubSystem` | string | Affected subsystem | `'Radiator'`, `'Lubrication'` |

**System Hierarchy Examples**:

| Trigger | System | SubSystem |
|---------|--------|-----------|
| `EngCoolTemp` | `Engine` | `Radiator` |
| `EngOilPres` | `Engine` | `Lubrication` |
| `TransOilTemp` | `Transmission` | `Cooling` |
| `HydOilTemp` | `Hydraulic` | `Cooling` |
| `BatteryVolt` | `Electrical` | `Power Supply` |

**Quality Rules**:
- ✅ Unique AlertID (auto-increment)
- ✅ Valid datetime format
- ✅ System/SubSystem mapping consistent with Trigger
- ✅ No duplicate alerts (same Unit, Fecha, Trigger)

**Sample Count**: ~100-500 alerts per day per client (varies by fleet size)

---

### 2. Component Mapping Table (`component_mapping.parquet`)

**Purpose**: Reference table mapping components to their monitoring features and system hierarchy

**Schema**:

| Column       | Type     | Description                        | Example           |
|--------------|----------|------------------------------------|-------------------|
| `Component`  | category | Component name                     | `'Refrigerante'`  |
| `PrimaryFeature` | string | Main sensor/variable monitoring the component | `'EngCoolTemp'` |
| `System`     | category | High-level equipment system        | `'Motor'`         |
| `SubSystem`  | category | Specific subsystem                 | `'Refrigeracion'` |
| `Meaning`    | string   | Human-readable description         | `'Temperatura del Refrigerante de Motor'` |
| `RelatedFeatures` | list | List of related features for contextual analysis | `['EngOilPres', 'RAftrclrTemp']` |

**Use Cases**:
- Map alert triggers to component hierarchy
- Retrieve contextual features for multi-variable analysis
- Generate comprehensive system diagnostics
- Support AI diagnosis with related sensor context

**Example Configuration**:

| Component | PrimaryFeature | System | SubSystem | RelatedFeatures |
|-----------|----------------|--------|-----------|-----------------|
| Refrigerante | EngCoolTemp | Motor | Refrigeracion | ['EngOilPres', 'RAftrclrTemp', 'DiffTemp'] |
| PostRefrigerante | RAftrclrTemp | Motor | Refrigeracion | ['RtExhTemp', 'LtExhTemp', 'AirFltr'] |
| Motor | EngOilPres | Motor | Motor | ['EngCoolTemp', 'EngSpd', 'EngOilFltr'] |
| Filtro Aceite de Motor | EngOilFltr | Motor | Motor | ['EngCoolTemp', 'EngOilPres', 'CnkcasePres'] |

**Quality Rules**:
- ✅ Unique PrimaryFeature per row
- ✅ All categorical columns stored as category dtype
- ✅ RelatedFeatures stored as list type
- ✅ System/SubSystem hierarchy consistency
- ✅ Complete coverage of all monitored features

**Source**: `CDA_CM_ModularDeploy.xlsx` (VariablesMonitoreo sheet)

---

## ✅ Data Quality Rules

### Silver Layer

**Telemetry Values (Wide)**:
- ✅ Timestamps are sequential per unit
- ✅ Valid geographic coordinates (GPS)
- ✅ All sensor values within expected ranges
- ✅ No missing critical fields
- ✅ Categorical columns optimized for memory

**States Table**:
- ✅ States from predefined vocabulary
- ✅ No duplicate (Fecha, Unit) combinations
- ✅ All categorical fields properly typed

**Limits Configuration**:
- ✅ Unique combination of (Unit, Feature, Estado, EstadoCarga)
- ✅ `Limit_Lower` < `Limit_Upper`
- ✅ All categorical columns stored as category dtype
- ✅ All features from values table have rules defined
- ✅ Coverage for all state combinations per unit

### Golden Layer

**Alerts Data**:
- ✅ All alerts have complete system mapping
- ✅ No orphaned alerts (must match telemetry records)
- ✅ Timestamps align with source data

**Component Mapping**:
- ✅ Unique PrimaryFeature per row
- ✅ All categorical columns stored as category dtype
- ✅ RelatedFeatures stored as list type
- ✅ System/SubSystem hierarchy consistency
- ✅ Complete coverage of all monitored features

---

## 📊 Data Volume Estimates

### Per Client Daily Volume

| Dataset | Records/Day | File Size (Compressed) |
|---------|-------------|------------------------|
| Telemetry Values (Wide) | ~100K | ~8-12 MB |
| States | ~100K | ~1-2 MB |
| Limits Config | ~200 (static) | ~20 KB |
| Alerts | ~100-500 | ~50 KB |
| Component Mapping | ~60 (static) | ~10 KB |

**Note**: Volumes vary significantly based on:
- Fleet size
- Sampling frequency
- Number of monitored sensors
- Alert generation rate

---

## 🔄 Data Flow

```
Raw Sensor Streams (GPS + Telemetry)
       ↓
  Silver Layer
  ├── Telemetry Values (Wide Format)
  ├── States (Long Format)
  └── Limits Configuration (Thresholds)
       ↓
  Alert Detection (using Limits Config)
       ↓
  Golden Layer
  ├── Alerts Data
  └── Component Mapping (Reference)
       ↓
  Dashboard / Analytics
```

---

## 📝 Change Log

### Version 1.3 (February 2026)
- **BREAKING CHANGE**: Moved limits_config from Golden to Silver layer
- Limits now co-located with sensor data for real-time evaluation
- Updated purpose descriptions for clarity

### Version 1.2 (February 2026)
- Added Component Mapping table to Golden layer
- Maps components to monitoring features and system hierarchy
- Includes related features for contextual analysis
- Enables multi-variable diagnostics in dashboard

### Version 1.1 (February 2026)
- **BREAKING CHANGE**: Optimized data structure for memory efficiency
- Introduced wide-format telemetry values table (combines GPS + sensor data)
- Separated states into lightweight table
- Moved limits configuration to Golden layer as reference data
- All categorical columns now use category dtype
- Reduced memory footprint by ~60-70%

### Version 1.0 (February 2026)
- Initial telemetry data contracts
- GPS and sensor data schemas
- State-aware alert logic
- System/subsystem mapping
