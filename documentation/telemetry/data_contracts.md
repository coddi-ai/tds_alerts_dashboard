# Data Contracts - Telemetry Data Product

**Version**: 1.0  
**Last Updated**: February 4, 2026  
**Owner**: Telemetry Data Product Team

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
    │       └── telemetry_states.parquet       # Equipment states (long format)
    └── golden/                              # Analysis-ready outputs
        └── {client}/
            ├── alerts_data.csv              # Generated alerts
            └── limits_config.parquet        # Alert trigger rules & thresholds
```

---

## 🔄 Silver Layer

**Purpose**: Harmonized sensor data with GPS tracking and alert evaluation  
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

## 🏆 Golden Layer

**Purpose**: Processed alerts and configuration rules  
**Update Frequency**: Real-time for alerts, periodic for rules  
**Retention**: Historical archive  
**Format**: CSV

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

### 2. Limits Configuration Table (`limits_config.parquet`)

**Purpose**: Static reference table defining alert thresholds per feature, unit, and state combination

**Schema**:

| Column       | Type     | Description                        | Example           |
|--------------|----------|------------------------------------|-------------------|
| `Unit`       | category | Machine or unit identifier         | `'Frankie_V2'`    |
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

### Golden Layer

**Alerts Data**:
- ✅ All alerts have complete system mapping
- ✅ No orphaned alerts (must match telemetry records)
- ✅ Timestamps align with source data

**Limits Configuration**:
- ✅ Complete coverage of all features
- ✅ Rules defined for all operational states
- ✅ No conflicting threshold definitions
- ✅ All limits properly validated (Lower < Upper)

---

## 📊 Data Volume Estimates

### Per Client Daily Volume

| Dataset | Records/Day | File Size (Compressed) |
|---------|-------------|------------------------|
| Telemetry Values (Wide) | ~100K | ~8-12 MB |
| States | ~100K | ~1-2 MB |
| Alerts | ~100-500 | ~50 KB |
| Limits Config | ~200 (static) | ~20 KB |

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
  └── States (Long Format)
       ↓
  Alert Detection (using Limits Config)
       ↓
  Golden Layer
  ├── Alerts Data
  └── Limits Configuration
       ↓
  Dashboard / Analytics
```

---

## 📝 Change Log

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
