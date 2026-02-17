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

The General tab is divided into **4 sections**:

#### Section 1: Summary Statistics (4 KPI Cards)

**Purpose**: Display high-level alert metrics at a glance

**KPI Cards** (displayed horizontally):
1. **Total Alertas** - Total count of alerts (primary color)
2. **Unidades Afectadas** - Number of unique units with alerts (info color)
3. **% con Telemetría** - Percentage of alerts with telemetry evidence (success color)
4. **% con Tribología** - Percentage of alerts with oil analysis evidence (warning color)

---

#### Section 2: Analytics Charts (3 Figures)

All figures are equal width, displayed horizontally across the screen.

##### Figure 1: Distribution of Alerts per Unit
- **Type**: Horizontal Bar Chart
- **Y-axis**: `UnitId`
- **X-axis**: Count of `FusionID` per Unit
- **Color**: `sistema` (colored by affected system)
- **Purpose**: Identify units with highest alert frequency
- **Sort**: Ascending by count
- **Interactive**: Click to filter by unit (toggle behavior)

**Visual Specifications**:
```python
plotly.express.bar(
    data,
    y='UnitId',
    x='Count',
    color='sistema',
    orientation='h'
)
```

##### Figure 2: Distribution of Alerts per Month
- **Type**: Vertical Bar Chart
- **Y-axis**: Count of `FusionID` per Month
- **X-axis**: Month (chronological)
- **Color**: `sistema` (colored by affected system)
- **Purpose**: Identify temporal patterns in alert generation
- **Interactive**: Click to filter by month (toggle behavior)

**Visual Specifications**:
```python
plotly.express.bar(
    data,
    x='Month_str',
    y='Count',
    color='sistema'
)
```

##### Figure 3: Distribution of Alert Trigger
- **Type**: Treemap
- **Names**: `Trigger_type` (Telemetria/Tribologia/Mixto)
- **Values**: Frequency count
- **Purpose**: Show proportion of alert sources
- **Interactive**: Click to filter by trigger type (toggle behavior)

**Visual Specifications**:
```python
plotly.express.treemap(
    data,
    path=['Trigger_type'],
    values='Frequency'
)
```

---

#### Section 3: Table and System Distribution

**Layout**: Two columns
- Left column (8/12 width): Alerts Table
- Right column (4/12 width): System Distribution Chart

##### Alerts Table

**Purpose**: Comprehensive alert listing with key details

**Columns**:
1. **ID** - `FusionID` (Unique alert identifier)
2. **Fecha** - `Timestamp` (Alert generation time, formatted YYYY-MM-DD HH:MM:SS)
3. **Unidad** - `UnitId` (Equipment identifier)
4. **Sistema** - `sistema` (Affected system)
5. **Componente** - `componente` (Specific component)
6. **Fuente** - `Trigger_type` (Alert source)
7. **Diagnóstico IA** - `mensaje_ia` (AI diagnosis, truncated to 80 characters + "...")
8. **Telemetría** - `has_telemetry` (Boolean indicator ✓/✗)
9. **Tribología** - `has_tribology` (Boolean indicator ✓/✗)

**Features**:
- **Sorting**: `Timestamp` (newest to oldest)
- **Pagination**: 20 rows per page
- **Filtering**: Native column filtering
- **Multi-column sorting**: Enabled
- **Interaction**: Each row is clickable and navigates to the Detail tab with the selected alert's `FusionID`

**Derived Columns**:
- `has_telemetry`: True if `Trigger_type` in ['Telemetria', 'Mixto']
- `has_tribology`: True if `Trigger_type` in ['Tribologia', 'Mixto']

##### System Distribution Chart

- **Type**: Donut/Pie Chart (hole=0.3)
- **Shows**: Distribution by `sistema`
- **Purpose**: Visualize alert distribution across systems
- **Interactive**: Click to filter by system (toggle behavior)

---

#### Section 4: Navigation Card

**Purpose**: Provide explicit navigation from General to Detail view with alert pre-selection

**Components**:
1. **Alert Selector Dropdown** (`general-alert-selector`):
   - Populated with all alerts
   - Format: `{FusionID} | {Timestamp} | {UnitId} | {componente}`
   - Sorted by timestamp (newest first)
   - Searchable and clearable

2. **Navigation Button** (`general-nav-to-detail-button`):
   - Label: "Ver Detalle →"
   - Color: Primary
   - Action: Navigate to Detail tab with selected alert pre-loaded

**Navigation Pattern**: Uses store-based intermediary (`alerts-navigation-state`) to ensure reliable cross-tab navigation

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

The Detail tab is divided into **4 main sections**:

---

#### Section 1: Filters Section

**Purpose**: Filter available alerts before selection

**Filter Components** (4 dropdowns, equal width):
1. **Unit Filter** (`detail-filter-unit`):
   - Type: Multi-select
   - Options: All unique units from alerts

2. **System Filter** (`detail-filter-sistema`):
   - Type: Multi-select
   - Options: All unique systems from alerts

3. **Telemetry Filter** (`detail-filter-telemetry`):
   - Type: Single-select
   - Options: Sí / No / Todos
   - Filters alerts with/without telemetry evidence

4. **Tribology Filter** (`detail-filter-tribology`):
   - Type: Single-select
   - Options: Sí / No / Todos
   - Filters alerts with/without oil analysis evidence

**Behavior**: Filters dynamically update the Alert Selector dropdown options

---

#### Section 2: Alert Selector

**Purpose**: Select specific alert to view details

**Components**:
- **Alert Dropdown** (`alert-selector-dropdown`):
  - Searchable and clearable
  - Options filtered by Section 1 filters
  - Format: `{FusionID} | {Timestamp} | {UnitId} | {componente}`
  - Sorted by timestamp (newest first)
  - Can be pre-populated via navigation from General tab
- **Hint Text**: "También puede seleccionar una alerta desde la Vista General"

**Default State**: Info alert "Por favor, seleccione una alerta para ver los detalles"

---

#### Section 3: Alert Specification

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

#### Section 4: Evidence of the Alert

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

**Display Condition**: `Trigger_type` in ['Telemetria', 'Mixto']

**Layout**: 2 rows

---

#### Row 1: Sensor Trends

**Chart Type**: Time Series (Multiple Subplots)

**Goal**: Show sensor values for components related to the alert

**Data Requirements**:
- Filter telemetry data for `Unit` = alert's `UnitId`
- Time window: M1 minutes before alert, M2 minutes after alert
  - **M1** (Before): 60 minutes
  - **M2** (After): 10 minutes
- Variables: Sensors related to `componente` or `sistema` of alert

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

---

#### Row 2: GPS Location and Alert Context

**Layout**: Two columns
- Left column (8/12 width): GPS Map
- Right column (4/12 width): Alert Context KPIs

##### GPS Location

**Chart Type**: Scattermapbox (Route Visualization)

**Goal**: Show machine route and position when alert triggered

**Data Requirements**:
- Filter GPS data for same time window as sensor trends
- Coordinates: `GPSLat`, `GPSLon`
- Elevation: `GPSElevation`

**Visual Specifications**:
- **Route Line**: Gray line connecting points
- **Point Color**: Time-based gradient using `colorscale='Reds'`
  - Start of window: Light red
  - Alert timestamp: Dark red marker (large)
  - End of window: Darker red
- **Map Style**: `satellite-streets`
- **Hover Info**: Timestamp, elevation, coordinates, state

##### Alert Context

**Chart Type**: KPI Cards (Boxes with Numbers)

**Goal**: Provide operational context at moment of alert

**3 KPI Values**:

1. **Elevation Status**
   - **Metric**: Gradient/Slope at alert time
   - **Display**: 
     - "Subiendo" (gradient > 0.05)
     - "Bajando" (gradient < -0.05)
     - "Plano" (|gradient| ≤ 0.05)
   - **Source**: `GPSElevation` derivative

2. **Payload Status**
   - **Metric**: `EstadoCarga` at alert time
   - **Display**: 
     - "Cargado" 
     - "Vacío"
     - "Desconocido"
   - **Source**: `EstadoCarga` column

3. **Engine RPM**
   - **Metric**: Engine speed at alert time
   - **Display**: Numeric value with unit (e.g., "1,850 RPM")
   - **Source**: Sensor feature `EngineSpeed` or equivalent

---

### Subsection: Oil Evidence

**Display Condition**: `Trigger_type` in ['Tribologia', 'Mixto']

**Layout**: Two columns
- Left column: Radar Chart
- Right column: Oil Report Status Table

##### Radar Chart (Polar Chart)

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

##### Oil Report Status Table

**Purpose**: Display oil report metadata and status

**Columns**:
1. **Sample Number** - Unique report identifier
2. **Sample Date** - Date of oil sample collection
3. **Report Status** - Classification status
4. **Laboratory** - Lab that analyzed the sample
5. **Component** - Component analyzed
6. **Hours** - Equipment hours at sample time

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

The dashboard provides **two navigation methods** from General to Detail tab:

#### Method 1: Direct Table Row Click

1. User views General tab with alert analytics
2. User clicks on a row in the Alerts Table
3. System captures `FusionID` of selected alert
4. System navigates to Detail tab
5. Detail tab loads with `FusionID` as parameter
6. Detail tab queries all relevant data sources
7. Evidence subsections render based on data availability

**Technical Implementation**: Uses `Input` from table's `active_cell` property

#### Method 2: Navigation Card (Explicit Selection)

1. User views General tab
2. User selects an alert from the dropdown in Section 4: Navigation Card
3. User clicks "Ver Detalle →" button
4. System writes selected `FusionID` to `alerts-navigation-state` store
5. Store triggers Detail tab's `alert-selector-dropdown` update
6. System switches to Detail tab
7. Detail tab loads evidence for selected alert

**Technical Implementation**: Uses store-based intermediary pattern
- **Store**: `alerts-navigation-state` (memory store with data property)
- **Callback Chain**: 
  1. `navigate_to_detail_from_general`: Button click → writes to store
  2. `switch_to_detail_tab`: Store update → changes active tab
  3. `set_alert_from_navigation`: Store update → sets alert selector value

**Why Store-Based Pattern**: Direct targeting of dynamically rendered components (like the alert selector in Detail tab) is unreliable. The store acts as a reliable intermediary that ensures the navigation state is available when the Detail tab renders.

**State Management**: Selected `FusionID` is stored in both callback state and memory store

---

### Interactive Chart Filtering

Charts in the General tab support click-to-filter with **toggle behavior**:

1. User clicks on a chart element (e.g., a bar for a specific unit)
2. System filters all components (table and other charts) to show only data for that selection
3. User clicks the same element again to toggle off the filter
4. System resets to show all data

**Supported Charts**:
- Distribution of Alerts per Unit
- Distribution of Alerts per Month
- Distribution of Alert Trigger
- System Distribution (donut chart)

**Filter Indicator**: Active filters are stored in `alerts-filter-store` and can be cleared with a reset button

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
# Default values
TELEMETRY_WINDOW_BEFORE = 60  # minutes before alert
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

1. **Export Functionality**: Download alert evidence as PDF report
2. **Alert Annotations**: Add user comments and follow-up actions
3. **Real-time Updates**: Auto-refresh when new alerts arrive
4. **Advanced Filtering**: Multi-level filter combinations in General tab
5. **Alert Comparison**: Side-by-side comparison of multiple alerts

---

## 📝 Notes

- Current implementation treats tabs as subsections in code structure
- GPS visualization requires Mapbox token (already configured)
- AI diagnosis text in table is truncated to 80 characters with "..." suffix
- Interactive chart filtering uses toggle behavior for intuitive user experience

---

**Last Updated**: February 6, 2025  
**Next Review**: After Phase 1 Step 1.2 completion
