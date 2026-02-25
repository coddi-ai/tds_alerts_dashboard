# Data Contracts - Consolidated Alerts Data Product

**Version**: 1.1  
**Last Updated**: February 17, 2026  
**Owner**: Alerts Fusion Data Product Team  
**Status**: ✅ Aligned with implementation (Implementation is ground truth)

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Data Layer Architecture](#data-layer-architecture)
3. [Golden Layer](#golden-layer)
4. [Alert Fusion Logic](#alert-fusion-logic)
5. [Data Quality Rules](#data-quality-rules)

---

## 🎯 Overview

This document defines the data contracts for the Consolidated Alerts Data Product, which **fuses alerts from multiple monitoring techniques** (Telemetry and Oil) with maintenance context to provide a unified view of equipment health issues.

**Data Product Purpose**: Create contextualized, cross-technique alerts with AI-generated diagnosis that combine sensor data, tribology analysis, and maintenance history.

**Primary Consumers**:
- Multi-Technical Alerts Dashboard
- Maintenance planning systems
- Alert management platforms
- Predictive maintenance models

**Key Innovation**: Correlates alerts across techniques to identify systemic issues and provide comprehensive diagnosis.

---

## 🏗️ Data Layer Architecture

### Local Storage Structure

```
data/
└── alerts/
    └── golden/                        # Consolidated alerts
        └── {client}/
            └── consolidated_alerts.csv  # Unified alert stream
```

---

## 🏆 Golden Layer

**Purpose**: Unified alert view with cross-technique correlation and AI diagnosis  
**Update Frequency**: Real-time / Continuous  
**Retention**: Full historical archive  
**Format**: CSV

### Location

```
Local: data/alerts/golden/{client}/consolidated_alerts.csv
```

---

### Consolidated Alerts (`consolidated_alerts.csv`)

**Purpose**: Unified alert repository combining telemetry and oil alerts with contextual enrichment

**Schema**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `FusionID` | string | Unique consolidated alert identifier | `'FUS-001'`, `'FUS-002'` |
| `TelemetryID` | string (nullable) | Reference to telemetry alert ID | `'1'`, `'2'`, `null` |
| `OilReportNumber` | string (nullable) | Reference to oil sample number | `'CDA-2024-001'`, `null` |
| `Semana_Resumen_Mantencion` | string | Maintenance week reference | `'32-2025'` |
| `Fecha` | datetime64[ns] | Alert generation timestamp | `2025-01-01 00:00:00` |
| `UnitId` | string | Equipment unit identifier | `'CAT-001'` |
| `Trigger_type` | string | Alert source technique | `'Telemetria'`, `'Tribologia'`, `'Mixto'` |
| `mensaje_ia` | string | AI-generated diagnosis | `'Se observa que...'` |
| `sistema` | string | Affected equipment system | `'Engine'`, `'Transmission'` |
| `subsistema` | string (nullable) | Affected subsystem | `'Radiator'`, `'Lubrication'` |
| `componente` | string (nullable) | Specific component | `'Coolant Pump'`, `'Oil Filter'` |

---

### Field Definitions

#### `FusionID`
- **Type**: String
- **Purpose**: Unique identifier for each consolidated alert
- **Format**: String identifier (implementation-specific format)
- **Note**: While a format like `FUS-{sequential_number}` was originally designed, the actual implementation may use a different format
- **Example**: `'FUS-001'`, `'FUS-045'`, `'alert_123'`
- **Requirement**: Must be unique across all alerts

#### `TelemetryID` (Nullable)
- **Type**: String (can be null)
- **Purpose**: Links to telemetry alert if applicable
- **Source**: `telemetry/golden/{client}/alerts_data.csv -> AlertID`
- **Null when**: Alert is oil-only
- **Example**: `'15'`, `'234'`, `null`

#### `OilReportNumber` (Nullable)
- **Type**: String (can be null)
- **Purpose**: Links to oil sample if applicable
- **Source**: `oil/golden/{client}/classified.parquet -> sampleNumber`
- **Null when**: Alert is telemetry-only
- **Example**: `'CDA-2024-001'`, `'EMIN-2025-145'`, `null`

#### `Semana_Resumen_Mantencion`
- **Format**: `ww-yyyy`
- **Purpose**: Reference to maintenance report week
- **Source**: Maps to `mantentions/golden/{client}/ww-yyyy.csv` filename
- **Usage**: Correlate alerts with maintenance activities
- **Example**: `'32-2025'` → file `32-2025.csv`

#### `Fecha`
- **Type**: datetime64[ns]
- **Purpose**: Alert generation timestamp
- **Format**: ISO datetime format
- **Example**: `2025-01-01 00:00:00`
- **Note**: Spanish for "Date", used for consistency with Spanish column naming convention

#### `UnitId`
- **Type**: String
- **Purpose**: Equipment unit identifier
- **Source**: Fleet registry
- **Example**: `'CAT-001'`, `'EMIN-H45'`
- **Note**: Must match valid unit in fleet database

#### `Trigger_type`
- **Values**: `'Telemetria'` | `'Tribologia'` | `'Mixto'`
- **Purpose**: Identify the monitoring technique that generated the alert
- **Logic**:
  - `'Telemetria'`: When alert originates from telemetry sensor data
  - `'Tribologia'`: When alert originates from oil analysis reports
  - `'Mixto'`: When alert combines both telemetry and oil analysis evidence (correlation alert)
- **Note**: Values are capitalized Spanish terms for consistency with dashboard UI

#### `mensaje_ia`
- **Purpose**: AI-generated contextual diagnosis
- **Format**: Natural language text (Spanish)
- **Content**: Explains the issue, potential causes, and severity
- **Generation**: Uses LLM with context from:
  - Alert data
  - Historical patterns
  - System knowledge base
  - Recent maintenance activities

**Example Messages**:
```
"Se observa temperatura elevada en el sistema de enfriamiento del motor 
(105°C). Posible falla en radiador o termostato. Se recomienda 
inspección inmediata del sistema de refrigeración."

"Análisis de aceite muestra niveles críticos de hierro (85 ppm) en 
motor diesel. Indica desgaste acelerado de componentes internos. 
Requiere análisis detallado y posible overhaul."
```

#### System Hierarchy

The alert includes three levels of component hierarchy:

1. **sistema**: High-level equipment system (lowercase Spanish)
   - Examples: `Engine`, `Transmission`, `Hydraulic`, `Electrical`
   - Special value: `'Desconocido'` when system cannot be determined

2. **subsistema**: Specific subsystem within the system (lowercase Spanish, nullable)
   - Examples: `Radiator`, `Lubrication`, `Cooling`, `Power Supply`
   - Can be null for high-level alerts

3. **componente**: Specific component when identifiable (lowercase Spanish, nullable)
   - Examples: `Coolant Pump`, `Oil Filter`, `Thermostat`, `Battery`
   - Can be null for system-level or subsystem-level alerts

**Missing Value Handling**:
- If `sistema` is null or empty, it is filled with `'Desconocido'`
- `subsistema` and `componente` can remain null for high-level alerts

**Mapping Examples**:

| Trigger Source | sistema | subsistema | componente |
|----------------|---------|------------|------------|
| EngCoolTemp (Telemetry) | Engine | Radiator | Coolant Pump |
| EngOilPres (Telemetry) | Engine | Lubrication | Oil Pump |
| Hierro (Oil) | Engine | Internal | Piston Rings |
| Cobre (Oil) | Engine | Bearings | Main Bearings |
| TransOilTemp (Telemetry) | Transmission | Cooling | Transmission Cooler |

---

## 🔄 Alert Fusion Logic

### Alert Generation Flow

```
┌─────────────────┐         ┌──────────────────┐
│  Telemetry      │         │   Oil Analysis   │
│  Alert System   │         │   Alert System   │
└────────┬────────┘         └────────┬─────────┘
         │                           │
         │  TelemetryID              │  OilReportNumber
         │                           │
         └───────────┬───────────────┘
                     ↓
         ┌───────────────────────────┐
         │   Alert Fusion Engine     │
         │  - Correlate by UnitId    │
         │  - Add maintenance context│
         │  - Generate AI diagnosis  │
         │  - Map system hierarchy   │
         └───────────┬───────────────┘
                     ↓
         ┌───────────────────────────┐
         │  Consolidated Alerts      │
         │  (Golden Layer)           │
         └───────────────────────────┘
```

### Fusion Rules

#### 1. Telemetry-Only Alerts
```
Condition: Telemetry alert generated
Action:
  - Create FusionID
  - Set TelemetryID = alert.AlertID
  - Set OilReportNumber = null
  - Set Trigger_type = 'Telemetria'
  - Extract sistema/subsistema from telemetry
  - Generate AI diagnosis using sensor context
```

#### 2. Oil-Only Alerts
```
Condition: Oil report status = 'Alerta' or 'Anormal'
Action:
  - Create FusionID
  - Set TelemetryID = null
  - Set OilReportNumber = sample.sampleNumber
  - Set Trigger_type = 'Tribologia'
  - Extract sistema/subsistema from component
  - Generate AI diagnosis using oil analysis context
```

#### 3. Mixed/Correlation Alerts
```
Condition: Both telemetry and oil alerts for same unit/system within time window
Action:
  - Create FusionID
  - Set both TelemetryID and OilReportNumber
  - Set Trigger_type = 'Mixto'
  - Enhanced AI diagnosis combining both contexts
  - Provides comprehensive view of equipment health issue
```

### Maintenance Context Enrichment

For each alert:
1. Determine the week of alert generation
2. Map to `Semana_Resumen_Mantencion` (format: `ww-yyyy`)
3. AI diagnosis considers recent maintenance activities from that week

---

## ✅ Data Quality Rules

### Required Fields
- ✅ `FusionID`: Unique, non-null
- ✅ `Fecha`: Valid datetime
- ✅ `UnitId`: Valid, matches fleet registry
- ✅ `Trigger_type`: In {'Telemetria', 'Tribologia', 'Mixto'}
- ✅ `mensaje_ia`: Non-empty, coherent text
- ✅ `sistema`: Non-null (filled with 'Desconocido' if missing)
- ✅ `Semana_Resumen_Mantencion`: Valid week format

### Conditional Rules
- ✅ If `Trigger_type` = 'Telemetria', then `TelemetryID` is not null and `OilReportNumber` is null
- ✅ If `Trigger_type` = 'Tribologia', then `OilReportNumber` is not null and `TelemetryID` is null
- ✅ If `Trigger_type` = 'Mixto', then both `TelemetryID` and `OilReportNumber` are not null
- ✅ At least one of `TelemetryID` or `OilReportNumber` must be non-null
- ✅ `subsistema` and `componente` can be null for high-level alerts

### Derived Display Columns

The dashboard creates these derived boolean columns for display purposes:
- `has_telemetry`: True if `Trigger_type` in ['Telemetria', 'Mixto']
- `has_tribology`: True if `Trigger_type` in ['Tribologia', 'Mixto']

These are NOT part of the data file schema, but are computed at display time.

### Referential Integrity
- ✅ `TelemetryID` references valid record in `telemetry/golden/{client}/alerts_data.csv`
- ✅ `OilReportNumber` references valid sample in `oil/golden/{client}/classified.parquet`
- ✅ `Semana_Resumen_Mantencion` corresponds to existing file in `mantentions/golden/{client}/`

---

## 📊 Data Volume Estimates

### Per Client Daily Volume

| Metric | Typical Range |
|--------|---------------|
| Total alerts | 50-200 |
| Telemetry-only | 40-150 |
| Oil-only | 10-50 |
| File size | 100-500 KB |

**Note**: Oil alerts are periodic (weekly/monthly), while telemetry alerts are continuous.

---

## 🔗 Cross-Technique Integration

### Querying Alerts with Full Context

**Get alert with all related data**:
```python
import pandas as pd

# Load all datasets
alerts = pd.read_csv('data/alerts/golden/client/consolidated_alerts.csv')
telemetry_alerts = pd.read_csv('data/telemetry/golden/client/alerts_data.csv')
oil_classified = pd.read_parquet('data/oil/golden/client/classified.parquet')
maintenance = pd.read_csv('data/mantentions/golden/client/32-2025.csv')

# Join telemetry context
alerts_with_telemetry = alerts.merge(
    telemetry_alerts,
    left_on='TelemetryID',
    right_on='AlertID',
    how='left'
)

# Join oil context
alerts_with_oil = alerts_with_telemetry.merge(
    oil_classified,
    left_on='OilReportNumber',
    right_on='sampleNumber',
    how='left'
)

# Join maintenance context
alerts_full = alerts_with_oil.merge(
    maintenance,
    left_on=['UnitId', 'Semana_Resumen_Mantencion'],
    right_on=['UnitId', 'week_number'],
    how='left'
)
```

---

## 📈 Use Cases

### 1. Alert Priority Ranking
Combine severity from multiple sources:
```python
# Oil severity: report_status weights
oil_weights = {'Normal': 0, 'Alerta': 5, 'Anormal': 10}

# Telemetry severity: by system criticality
system_weights = {'Engine': 10, 'Transmission': 8, 'Hydraulic': 6}

alerts['priority_score'] = (
    alerts['OilReportNumber'].map(lambda x: oil_weights.get(oil_status, 0)) +
    alerts['sistema'].map(system_weights)
)
```

### 2. Pattern Detection
Identify recurring issues:
```python
# Group by unit and system to find patterns
recurring_issues = alerts.groupby(['UnitId', 'sistema']).agg({
    'FusionID': 'count',
    'Fecha': ['min', 'max']
}).reset_index()

recurring_issues.columns = ['UnitId', 'sistema', 'alert_count', 'first_alert', 'last_alert']
recurring_issues[recurring_issues['alert_count'] >= 3]  # Units with 3+ alerts
```

### 3. Maintenance Effectiveness
Evaluate if maintenance resolved alerts:
```python
# Check alerts before and after maintenance
pre_maintenance = alerts[alerts['Fecha'] < maintenance_date]
post_maintenance = alerts[alerts['Fecha'] >= maintenance_date]

effectiveness = len(post_maintenance) / len(pre_maintenance)
```

---

## 📝 Change Log

### Version 1.1 (February 17, 2026) - Final
- **TEAM DECISION**: Implementation declared as ground truth
- **BREAKING CHANGES**: Updated to match actual implementation
  - Changed `Timestamp` → `Fecha` (Spanish naming)
  - Changed `TribologyID` → `OilReportNumber` (clearer naming)
  - Changed `System`, `SubSystem`, `Component` → `sistema`, `subsistema`, `componente` (lowercase Spanish)
  - Changed `Trigger_type` values: `'telemetry'`, `'oil'` → `'Telemetria'`, `'Tribologia'`, `'Mixto'`
  - Updated `FusionID` documentation to reflect implementation-specific format (not enforced)
  - Moved correlation alerts from "future" to standard as `'Mixto'` type
  - Added missing value handling: `'Desconocido'` for missing sistema values
  - Documented derived display columns (has_telemetry, has_tribology)
  - Added field definitions for `Fecha` and `UnitId`
- Updated all code examples to use implementation column names
- Updated data quality rules to match implementation logic
- **STATUS**: All documentation now aligned with actual implementation ✅

### Version 1.0 (February 4, 2026)
- Initial consolidated alerts data contract
- Multi-technique fusion logic
- AI diagnosis integration
- Maintenance context enrichment
- System hierarchy mapping
