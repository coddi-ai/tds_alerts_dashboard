# Alerts Dashboard - Overview Documentation

**Version**: 1.0  
**Created**: February 5, 2026  
**Owner**: Alerts Integration Team  
**Status**: Phase 1 - In Development

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Navigation Structure](#navigation-structure)
3. [General Tab](#general-tab)
4. [Detail Tab](#detail-tab)
5. [Data Sources](#data-sources)
6. [Interaction Flow](#interaction-flow)

---

## 🎯 Overview

The Alerts Dashboard provides a unified monitoring interface for equipment health alerts consolidated from multiple technical sources (Telemetry and Oil Analysis). The dashboard is organized into two primary tabs:

1. **General Tab**: Synthetic overview with aggregated insights
2. **Detail Tab**: Deep-dive evidence and context for individual alerts

**Primary Goal**: Enable fleet managers and maintenance teams to quickly identify critical equipment issues and access detailed diagnostic evidence for action planning.

---

## 🧭 Navigation Structure

```
Dashboard
└── Monitoring Section
    └── Alerts
        ├── General (Alert overview and analytics)
        └── Detail (Individual alert inspection)
```

**Note**: In the current implementation, these tabs are implemented as different subsections in the code, but function as tabs in the UI.

---

## 📊 General Tab

### Purpose
Provide high-level insights into alert patterns across the fleet, enabling identification of:
- Units with highest alert frequency
- Temporal trends in alert generation
- Distribution of alert sources (telemetry vs oil)

### Data Source

**Golden Layer - Consolidated Alerts**

```
URI: data/alerts/golden/{client}/consolidated_alerts.csv
```

**Columns Used**:
- `FusionID`: Unique alert identifier
- `Timestamp`: Alert generation time
- `UnitId`: Equipment unit
- `System`: Affected system
- `Trigger_type`: Alert source (telemetry/oil)
- `Component`: Specific component
- `mensaje_ia`: AI diagnosis

---

### Layout Structure

The General tab is divided into **2 sections**:

#### Section 1: Data Analysis (3 Figures)

All figures are equal width, displayed horizontally across the screen.

##### Figure 1: Distribution of Alerts per Unit
- **Type**: Horizontal Bar Chart (Histogram)
- **Y-axis**: `UnitId`
- **X-axis**: Count of `FusionID` per Unit
- **Color**: `System` (colored by affected system)
- **Purpose**: Identify units with highest alert frequency
- **Sort**: Descending by count

**Visual Specifications**:
```python
plotly.express.histogram(
    data,
    y='UnitId',
    color='System',
    orientation='h'
)
```

##### Figure 2: Distribution of Alerts per Month
- **Type**: Vertical Bar Chart (Histogram)
- **Y-axis**: Count of `FusionID` per Month
- **X-axis**: Month (chronological)
- **Color**: `System` (colored by affected system)
- **Purpose**: Identify temporal patterns in alert generation

**Visual Specifications**:
```python
plotly.express.histogram(
    data,
    x='Month',  # Extracted from Timestamp
    color='System'
)
```

##### Figure 3: Distribution of Alert Trigger
- **Type**: Treemap
- **Names**: `Trigger_type` (telemetry/oil)
- **Values**: Frequency count
- **Purpose**: Show proportion of alert sources

**Visual Specifications**:
```python
plotly.express.treemap(
    data,
    path=['Trigger_type'],
    values='frequency'
)
```

---

#### Section 2: Alerts Table

**Purpose**: Comprehensive alert listing with key details

**Columns**:
1. `Timestamp` - Alert generation time
2. `UnitId` - Equipment identifier
3. `Component` - Specific component
4. `mensaje_ia` - AI diagnosis (truncated for display)
5. `has_telemetry` - Boolean indicator (✓/✗)
6. `has_tribology` - Boolean indicator (✓/✗)

**Sorting**: `Timestamp` (newest to oldest)

**Interaction**: Each row is clickable and redirects to the Detail tab with the selected alert's `FusionID`

**Derived Columns**:
- `has_telemetry`: True if `TelemetryID` is not null
- `has_tribology`: True if `TribologyID` is not null

---

## 🔍 Detail Tab

### Purpose
Provide comprehensive diagnostic evidence for a specific alert, including:
- Alert specifications
- Telemetry sensor trends (if applicable)
- GPS location context (if applicable)
- Oil analysis results (if applicable)
- Maintenance history context

### Data Sources

The Detail tab uses **multiple data sources** based on the alert's `Trigger_type`:

#### 1. Alert Data (Always Required)
```
URI: data/alerts/golden/{client}/consolidated_alerts.csv
```

**Columns Used**:
- `FusionID`: Unique alert identifier (user selection parameter)
- `TelemetryID`: Reference to telemetry alert (nullable)
- `TribologyID`: Reference to oil sample (nullable)
- `Semana_Resumen_Mantencion`: Maintenance week reference
- `Timestamp`: Alert timestamp
- `UnitId`: Equipment identifier
- `Trigger_type`: Source technique
- `mensaje_ia`: AI diagnosis
- `System`: Affected system
- `SubSystem`: Affected subsystem
- `Component`: Specific component

#### 2. Telemetry Data (Conditional)
**Used when**: `Trigger_type` in ['telemetry', 'mixto']

**Silver Layer - Telemetry Values**
```
URI: data/telemetry/silver/{client}/telemetry_values_wide.parquet
```

**Columns**:
- `Fecha`: Timestamp
- `Unit`: Machine identifier
- `Feature1...FeatureN`: Sensor values
- `GPSLat`, `GPSLon`, `GPSElevation`: GPS data

**Silver Layer - Telemetry States**
```
URI: data/telemetry/silver/{client}/telemetry_states.parquet
```

**Columns**:
- `Fecha`: Timestamp
- `Unit`: Machine identifier
- `Estado`: Operational state (Operacional/Ralenti/ND)
- `EstadoCarga`: Load state

**Golden Layer - Alerts Data**
```
URI: data/telemetry/golden/{client}/alerts_data.csv
```

**Columns**:
- `AlertID`: Unique alert identifier
- `Fecha`: Alert timestamp
- `Unit`: Equipment identifier
- `Trigger`: Sensor that triggered alert
- `System`, `SubSystem`: System hierarchy

**Silver Layer - Limits Configuration**
```
URI: data/telemetry/silver/{client}/limits_config.parquet
```

**Columns**:
- `Unit`, `Feature`, `Estado`, `EstadoCarga`
- `Limit_Lower`, `Limit_Upper`: Thresholds

**Usage in Dashboard**:
- Display threshold lines in sensor trend charts
- Real-time alert evaluation

**Golden Layer - Component Mapping**
```
URI: data/telemetry/golden/{client}/component_mapping.parquet
```

**Purpose**: Maps components to their monitoring features for multi-variable analysis

**Columns**:
- `Component`: Component name
- `PrimaryFeature`: Main sensor monitoring the component
- `System`, `SubSystem`: System hierarchy
- `Meaning`: Feature description
- `RelatedFeatures`: List of contextual features

**Usage in Dashboard**:
- Display all related features when showing sensor trends
- Map alert triggers to component hierarchy
- Enable comprehensive multi-variable diagnostics

#### 3. Oil Analysis Data (Conditional)
**Used when**: `Trigger_type` in ['oil', 'mixto']

**Golden Layer - Classified Reports**
```
URI: data/oil/golden/{client}/classified.parquet
```

**Columns**:
- `sampleNumber`: Oil sample identifier (matches `TribologyID`)
- `essay_status_{essay}`: Essay classifications
- `breached_essays`: Essays exceeding thresholds
- `report_status`: Overall status
- `ai_recommendation`: AI maintenance advice

#### 4. Maintenance Data (Always Loaded)
**Used for**: Contextual maintenance history

**Golden Layer - Weekly Maintenance**
```
URI: data/mantentions/golden/{client}/{Semana_Resumen_Mantencion}.csv
```

**Columns**:
- `UnitId`: Equipment identifier
- `Tasks_List`: Nested activities by day/system
- `Summary`: AI-generated summary

---

### Layout Structure

The Detail tab is divided into **2 main sections**:

---

#### Section 1: Alert Specification

**Purpose**: Display core alert information at a glance

**Display Format**: KPI-style cards or table

**Fields Displayed**:
1. **Date**: `Timestamp` (formatted)
2. **Unit**: `UnitId`
3. **Trigger Type**: `Trigger_type`
4. **System**: `System`
5. **SubSystem**: `SubSystem`
6. **Component**: `Component`
7. **AI Diagnosis**: `mensaje_ia` (full text)

**Visual Style**: Highlighted banner or card layout to distinguish alert metadata

---

#### Section 2: Evidence of the Alert

**Purpose**: Provide multi-source diagnostic evidence

**Dynamic Behavior**: Subsections are displayed conditionally based on data availability

**Subsection Order** (Always maintained):
1. Telemetry Evidence
2. Oil Evidence
3. Maintenance Evidence

**Missing Data Handling**: If a subsection has no data, display message:
> "⚠️ No hay evidencia de {source} disponible para esta alerta"

---

### Subsection: Telemetry Evidence

**Display Condition**: `Trigger_type` in ['telemetry', 'mixto']

**Layout**: 3 equal-width columns

---

#### Column 1: Sensor Trends

**Chart Type**: Time Series (Multiple Subplots)

**Goal**: Show sensor values for components related to the alert

**Data Requirements**:
- Filter telemetry data for `Unit` = alert's `UnitId`
- Time window: M1 minutes before alert, M2 minutes after alert
  - **M1** (Before): 90 minutes (configurable in settings)
  - **M2** (After): 10 minutes (configurable in settings)
- Variables: Sensors related to `Component` or `System` of alert

**Visual Specifications**:
- **Multiple Subplots**: One per sensor variable (shared x-axis)
- **Color**: Based on `Estado` (operational state)
  ```python
  STATE_COLORS = {
      'Operacional': '#2ecc71',    # Green
      'Ralenti': '#f39c12',         # Orange
      'ND': '#95a5a6'                # Gray
  }
  ```
- **Limits**: Display `Limit_Lower` and `Limit_Upper` as dashed red lines
- **Alert Marker**: Vertical line at alert `Timestamp` (orange, dotted)
- **Hover Info**: Timestamp, value, state

**Implementation Note**: Use `create_timeseries_chart()` from `visualizations.py` as helper

---

#### Column 2: GPS Location

**Chart Type**: Scattermapbox (Route Visualization)

**Goal**: Show machine route and position when alert triggered

**Data Requirements**:
- Filter GPS data for same time window as sensor trends
- Coordinates: `GPSLat`, `GPSLon`
- Elevation: `GPSElevation`

**Visual Specifications**:
- **Route Line**: Gray line connecting points
- **Point Color**: Time-based gradient using `colorscale='Aggrnyl'`
  - Start of window: Light color
  - Alert timestamp: Red marker (large)
  - End of window: Dark color
- **Map Style**: Satellite view
- **Hover Info**: Timestamp, elevation, coordinates, state

**Implementation Note**: Use `create_gps_map()` from `visualizations.py` as helper

---

#### Column 3: Alert Context

**Chart Type**: KPI Cards (Boxes with Numbers)

**Goal**: Provide operational context at moment of alert

**3 KPI Values**:

1. **Elevation Status**
   - **Metric**: Gradient/Slope at alert time
   - **Display**: 
     - "⬆️ Subiendo" (gradient > 0.05)
     - "⬇️ Bajando" (gradient < -0.05)
     - "➡️ Plano" (|gradient| ≤ 0.05)
   - **Source**: `GPSElevation` derivative

2. **Payload Status**
   - **Metric**: `EstadoCarga` at alert time
   - **Display**: 
     - "✅ Cargado" 
     - "❌ Vacío"
     - "❓ Desconocido"
   - **Source**: `EstadoCarga` column

3. **Engine RPM**
   - **Metric**: Engine speed at alert time
   - **Display**: Numeric value with unit (e.g., "1,850 RPM")
   - **Source**: Sensor feature `EngineSpeed` or equivalent

**Implementation Note**: Use `create_kpi_card()` from `visualizations.py` as helper

---

### Subsection: Oil Evidence

**Display Condition**: `Trigger_type` in ['oil', 'mixto']

**Chart Type**: Radar Chart (Polar Chart)

**Goal**: Visualize oil essay levels against thresholds

**Data Requirements**:
- Filter classified reports for `sampleNumber` = alert's `TribologyID`
- Essay values and thresholds

**Visual Specifications**:
- **Axes**: One per essay (Hierro, Cobre, Aluminio, etc.)
- **Traces**:
  1. Actual essay values (filled area)
  2. Normal threshold (dashed line)
  3. Alert threshold (dashed line, different color)
- **Highlight**: Breached essays in red

**Implementation Note**: Reuse radar chart logic from oil dashboard

---

### Subsection: Maintenance Evidence

**Display Condition**: Always (if maintenance file exists)

**Chart Type**: Text Box with Structured Data

**Goal**: Show recent maintenance activities on affected system

**Data Requirements**:
- Load maintenance file: `{Semana_Resumen_Mantencion}.csv`
- Filter for `UnitId` = alert's `UnitId`
- Extract activities related to alert's `System`

**Display Format**:

```
📅 Semana de Mantención: 32-2025

🔧 Actividades en Sistema: Engine

Día 1 (Lunes):
  - Cambio de filtro de aceite
  - Inspección de radiador

Día 3 (Miércoles):
  - Revisión de niveles de refrigerante

📝 Resumen de la Semana:
Se realizaron 3 intervenciones en el sistema de motor...
```

**Missing Data Handling**: 
- If no maintenance file exists: "⚠️ No hay registro de mantención para esta semana"
- If no activities for the system: "ℹ️ No se registraron actividades en el sistema {System} durante esta semana"

---

## 🔄 Interaction Flow

### General Tab → Detail Tab Navigation

1. User views General tab with alert analytics
2. User clicks on a row in the Alerts Table
3. System captures `FusionID` of selected alert
4. System navigates to Detail tab
5. Detail tab loads with `FusionID` as parameter
6. Detail tab queries all relevant data sources
7. Evidence subsections render based on data availability

**State Management**: Selected `FusionID` is stored in callback state

---

## 📐 Design Specifications

### General Tab Layout

```
┌────────────────────────────────────────────────────────────────┐
│                       GENERAL TAB                               │
├────────────────────────────────────────────────────────────────┤
│  SECTION 1: DATA ANALYSIS                                      │
│  ┌─────────────────┬─────────────────┬─────────────────┐      │
│  │  Alerts per     │  Alerts per     │  Alert Trigger  │      │
│  │  Unit           │  Month          │  Distribution   │      │
│  │  (Bar Chart)    │  (Bar Chart)    │  (Treemap)      │      │
│  └─────────────────┴─────────────────┴─────────────────┘      │
├────────────────────────────────────────────────────────────────┤
│  SECTION 2: ALERTS TABLE                                       │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Timestamp │ Unit │ Component │ Diagnosis │ Telem │ Oil  │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │ 2025-01-15│CAT-01│ Radiator  │ Se observa│   ✓   │  ✗   │ │
│  │ 2025-01-14│CAT-02│ Oil Filter│ Análisis  │   ✗   │  ✓   │ │
│  │     ...   │ ...  │   ...     │   ...     │  ...  │ ...  │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

### Detail Tab Layout

```
┌────────────────────────────────────────────────────────────────┐
│                       DETAIL TAB                                │
├────────────────────────────────────────────────────────────────┤
│  SECTION 1: ALERT SPECIFICATION                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ 📅 2025-01-15 14:30 │ 🚜 CAT-001 │ 🔧 Engine-Radiator   │ │
│  │ AI Diagnosis: Se observa temperatura elevada...          │ │
│  └──────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────┤
│  SECTION 2: EVIDENCE                                           │
│                                                                 │
│  🔹 TELEMETRY EVIDENCE                                         │
│  ┌─────────────────┬─────────────────┬─────────────────┐      │
│  │  Sensor Trends  │  GPS Location   │  Alert Context  │      │
│  │  (Time Series)  │  (Map)          │  (KPIs)         │      │
│  │                 │                 │                 │      │
│  │  [Chart]        │  [Map]          │  ⬆️ Subiendo     │      │
│  │  [Chart]        │                 │  ✅ Cargado      │      │
│  │  [Chart]        │                 │  1,850 RPM      │      │
│  └─────────────────┴─────────────────┴─────────────────┘      │
│                                                                 │
│  🔹 OIL EVIDENCE                                               │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  [Radar Chart showing essay levels]                      │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
│  🔹 MAINTENANCE EVIDENCE                                       │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  📅 Semana 32-2025                                        │ │
│  │  🔧 Actividades en Engine: ...                           │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

---

## ⚙️ Configuration Settings

### Telemetry Time Windows

```python
# Default values (configurable in settings)
TELEMETRY_WINDOW_BEFORE = 90  # minutes before alert
TELEMETRY_WINDOW_AFTER = 10   # minutes after alert
```

### Color Schemes

```python
# Operational state colors
STATE_COLORS = {
    'Operacional': '#2ecc71',    # Green
    'Ralenti': '#f39c12',         # Orange
    'ND': '#95a5a6'                # Gray
}

# System colors (auto-assigned by Plotly)
SYSTEM_COLORS = 'Plotly'  # Default categorical palette
```

---

## 🔍 Data Quality Considerations

### General Tab
- **Empty State**: If no alerts exist, display message: "No hay alertas para mostrar"
- **Missing Systems**: If `System` is null, group as "Sin Sistema"

### Detail Tab
- **Missing Telemetry**: Display "⚠️ No hay evidencia de telemetría disponible"
- **Missing Oil**: Display "⚠️ No hay evidencia de tribología disponible"
- **Missing Maintenance**: Display "⚠️ No hay registro de mantención para esta semana"
- **Invalid Time Windows**: If alert timestamp is too recent (< M2 minutes ago), adjust window accordingly

---

## 📊 Performance Optimization

### General Tab
- Load only required columns from consolidated alerts
- Cache aggregated metrics (refreshed on data update)
- Limit table to 100 most recent alerts (paginate for more)

### Detail Tab
- Lazy-load evidence subsections (load only when visible)
- Cache telemetry time windows per alert
- Prefilter large datasets before loading into memory

---

## 🚀 Future Enhancements

1. **Correlation Alerts**: Support for `Trigger_type = 'mixto'` with combined evidence
2. **Custom Time Windows**: User-adjustable M1 and M2 parameters
3. **Export Functionality**: Download alert evidence as PDF report
4. **Alert Annotations**: Add user comments and follow-up actions
5. **Real-time Updates**: Auto-refresh when new alerts arrive

---

## 📝 Notes

- Current implementation treats tabs as subsections in code structure
- Helper functions from `visualizations.py` are reused where applicable
- GPS visualization requires Mapbox token (already configured)
- AI diagnosis text may be long; implement truncation with "Show More" option

---

**Last Updated**: February 5, 2026  
**Next Review**: After Phase 1 Step 1.2 completion
