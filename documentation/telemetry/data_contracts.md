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
    ├── silver/                    # Harmonized sensor data
    │   └── {client}/
    │       ├── gps.parquet        # GPS location data
    │       └── telemetry.parquet  # Sensor readings & alerts
    └── golden/                    # Analysis-ready outputs
        └── {client}/
            ├── alerts_data.csv    # Generated alerts
            └── data_rules.csv     # Alert trigger rules
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

### 1. GPS Data (`gps.parquet`)

**Purpose**: Equipment location tracking

**Schema**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `TimeStart` | datetime64[ns] | Timestamp of GPS reading | `2025-01-01 00:00:00` |
| `unitId` | string | Equipment unit identifier | `'CAT-001'` |
| `GPSLat` | float | Latitude coordinate | `-30.2` |
| `GPSLon` | float | Longitude coordinate | `-71.1` |
| `GPSElevation` | float | Elevation in meters | `900.1` |

**Quality Rules**:
- ✅ Valid datetime format
- ✅ Latitude: -90 to 90
- ✅ Longitude: -180 to 180
- ✅ Elevation: reasonable range for mining operations
- ✅ No duplicate timestamps per unit

**Use Cases**:
- Equipment location mapping
- Geofencing and zone monitoring
- Route optimization
- Availability tracking

---

### 2. Telemetry Data (`telemetry.parquet`)

**Purpose**: Sensor readings with alert evaluation

**Schema**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `Fecha` | datetime64[ns] | Timestamp of sensor reading | `2025-01-01 00:00:00` |
| `Unit` | string | Equipment unit identifier | `'CAT-001'` |
| `Estado` | string | Operational state | `'Ralenti'`, `'Operacional'` |
| `EstadoCarga` | string | Payload state | `'Sin Carga'`, `'Cargado'` |
| `Trigger` | string | Monitored sensor/feature | `'EngCoolTemp'`, `'EngOilPres'` |
| `Valor_Tendencia` | float | Sensor value at timestamp | `95.0` |
| `Alerta_Generada` | int | Alert flag (0 or 1) | `0`, `1` |
| `Limit_Lower` | float | Lower threshold for trigger | `80.0` |
| `Limit_Upper` | float | Upper threshold for trigger | `110.0` |

**Operational States**:
- `Ralenti`: Idle state (engine running, no load)
- `Operacional`: Active operation (engine running with load)
- `Apagado`: Shut down
- `Mantencion`: Under maintenance

**Payload States**:
- `Sin Carga`: Empty / No payload
- `Cargado`: Loaded with payload
- `Cargando`: Loading in progress
- `Descargando`: Unloading in progress

**Common Triggers** (Examples):
- `EngCoolTemp`: Engine coolant temperature
- `EngOilPres`: Engine oil pressure
- `TransOilTemp`: Transmission oil temperature
- `HydOilTemp`: Hydraulic oil temperature
- `FuelLevel`: Fuel level
- `BatteryVolt`: Battery voltage

**Alert Logic**:
```
Alerta_Generada = 1 IF Valor_Tendencia < Limit_Lower OR Valor_Tendencia > Limit_Upper
Alerta_Generada = 0 OTHERWISE
```

**Quality Rules**:
- ✅ Valid datetime format
- ✅ `Alerta_Generada` in {0, 1}
- ✅ `Limit_Lower` <= `Limit_Upper`
- ✅ Non-null values for critical columns
- ✅ Estado and EstadoCarga from predefined lists

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

### 2. Data Rules (`data_rules.csv`)

**Purpose**: Configuration of alert thresholds per trigger and state

**Schema**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `Trigger` | string | Sensor/feature name | `'EngCoolTemp'` |
| `Estado` | string | Operational state | `'Operacional'`, `'Ralenti'` |
| `EstadoCarga` | string | Payload state | `'Cargado'`, `'Sin Carga'` |
| `Limit_Lower` | float | Lower threshold | `80.0` |
| `Limit_Upper` | float | Upper threshold | `110.0` |
| `System` | string | Associated system | `'Engine'` |
| `SubSystem` | string | Associated subsystem | `'Radiator'` |

**Example Rules**:

```csv
Trigger,Estado,EstadoCarga,Limit_Lower,Limit_Upper,System,SubSystem
EngCoolTemp,Operacional,Cargado,75,105,Engine,Radiator
EngCoolTemp,Ralenti,Sin Carga,70,95,Engine,Radiator
EngOilPres,Operacional,Cargado,40,80,Engine,Lubrication
EngOilPres,Ralenti,Sin Carga,30,70,Engine,Lubrication
```

**Quality Rules**:
- ✅ Unique combination of (Trigger, Estado, EstadoCarga)
- ✅ `Limit_Lower` < `Limit_Upper`
- ✅ All Triggers have rules defined
- ✅ System/SubSystem mapping is consistent

---

## ✅ Data Quality Rules

### Silver Layer

**GPS Data**:
- ✅ Timestamps are sequential per unit
- ✅ Valid geographic coordinates
- ✅ No missing critical fields

**Telemetry Data**:
- ✅ All sensor values within expected ranges
- ✅ States from predefined vocabulary
- ✅ Limits properly defined for each state
- ✅ Alert flags correctly computed

### Golden Layer

**Alerts Data**:
- ✅ All alerts have complete system mapping
- ✅ No orphaned alerts (must match telemetry records)
- ✅ Timestamps align with source data

**Data Rules**:
- ✅ Complete coverage of all triggers
- ✅ Rules defined for all operational states
- ✅ No conflicting threshold definitions
- ✅ System hierarchy is complete

---

## 📊 Data Volume Estimates

### Per Client Daily Volume

| Dataset | Records/Day | File Size |
|---------|-------------|-----------|
| GPS | ~100K | ~5 MB |
| Telemetry | ~500K | ~25 MB |
| Alerts | ~100-500 | ~50 KB |
| Rules | ~200 | ~20 KB |

**Note**: Volumes vary significantly based on:
- Fleet size
- Sampling frequency
- Number of monitored sensors
- Alert generation rate

---

## 🔄 Data Flow

```
Raw Sensor Streams
       ↓
  Silver Layer
  (GPS + Telemetry with evaluation)
       ↓
  Alert Detection
       ↓
  Golden Layer
  (Alerts + Rules)
       ↓
  Dashboard / Analytics
```

---

## 📝 Change Log

### Version 1.0 (February 2026)
- Initial telemetry data contracts
- GPS and sensor data schemas
- State-aware alert logic
- System/subsystem mapping
