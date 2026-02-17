# Alerts Dashboard - Implementation Documentation

**Document Purpose**: This document describes the **actual implementation** of the Alerts Dashboard as built in the codebase. It serves as a reference to compare against original specifications and identify any gaps or deviations.

**Last Updated**: February 17, 2026  
**Scope**: CDA Client Only  
**Implementation Location**: `dashboard/tabs/tab_alerts.py`, `dashboard/callbacks/alerts_callbacks.py`, `dashboard/components/alerts_*.py`

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Data Contracts](#data-contracts)
4. [User Interface Structure](#user-interface-structure)
5. [Functionality Implementation](#functionality-implementation)
6. [Navigation Patterns](#navigation-patterns)
7. [Component Specifications](#component-specifications)
8. [Data Processing Logic](#data-processing-logic)
9. [Limitations and Constraints](#limitations-and-constraints)

---

## 1. Overview

### Purpose
The Alerts Dashboard is a unified monitoring and analysis system that consolidates alerts from multiple sources (Telemetry and Tribology/Oil Analysis) into a single interface with drill-down capabilities.

### Client Availability
**CDA Client Only**: The entire alerts feature is restricted to the CDA client. All data loading functions include explicit checks:
- `if client.lower() != 'cda': return pd.DataFrame()`
- A client notice alert is displayed in the UI

### Key Features Implemented
- **Unified Tab Interface**: Two internal tabs (General View and Detail View)
- **Multi-Source Alert Fusion**: Combines telemetry-based and tribology-based alerts
- **Interactive Filtering**: Click-to-filter on charts with toggle behavior
- **Cross-Navigation**: Navigate from General view to Detail view with alert pre-selection
- **Contextual Evidence**: Shows relevant data based on alert trigger type
- **AI-Generated Insights**: Displays AI recommendations and diagnoses

---

## 2. Architecture

### Module Structure

```
dashboard/
├── tabs/
│   ├── tab_alerts.py              # Main unified tab container
│   ├── tab_alerts_general.py      # General view layout
│   └── tab_alerts_detail.py       # Detail view layout
├── callbacks/
│   └── alerts_callbacks.py        # All interactivity logic (1344 lines)
└── components/
    ├── alerts_charts.py           # Chart generation functions
    └── alerts_tables.py           # Table and card components

src/data/
├── loaders.py                     # Data loading functions (alerts-specific: lines 318-617)
└── schemas.py                     # Pydantic models for data validation
```

### Application Integration

The Alerts tab is registered in `dashboard/app.py`:
- Imports: `import dashboard.callbacks.alerts_callbacks` (auto-registers @callback decorators)
- No explicit registration needed (uses Dash @callback pattern)

### Store-Based State Management

**Stores Used**:
1. **`alerts-filter-store`** (memory): Stores active filters from chart clicks
   - Structure: `{'unit': str, 'month': str, 'trigger': str, 'sistema': str}`
   - Used by General tab for interactive filtering

2. **`alerts-navigation-state`** (memory): Handles cross-tab navigation
   - Structure: `{'target_tab': str, 'alert_id': str}`
   - Created in `dashboard/layout.py` line ~256

---

## 3. Data Contracts

### 3.1 Consolidated Alerts Data

**Source**: `data/alerts/golden/CDA/consolidated_alerts.csv`

**Loader**: `load_alerts_data(client: str) -> pd.DataFrame`

**Schema** (as implemented):

| Column Name | Type | Description | Derived/Source |
|------------|------|-------------|----------------|
| `FusionID` | str | Unique alert identifier | Primary Key |
| `Timestamp` | datetime | Alert timestamp | Parsed from CSV |
| `UnitId` | str | Equipment unit identifier | Source |
| `sistema` | str | System (e.g., "Motor", "Transmision") | Filled 'Desconocido' if missing |
| `subsistema` | str | Subsystem | Filled 'Desconocido' if missing |
| `componente` | str | Component name | Filled 'Desconocido' if missing |
| `Trigger_type` | str | Alert source: 'Telemetria', 'Tribologia', 'Mixto' | Source |
| `TelemetryID` | str/null | Telemetry alert ID (if applicable) | Source |
| `OilReportNumber` | str/null | Oil report ID (if applicable) | Source |
| `mensaje_ia` | str | AI-generated diagnostic message | Source |
| `Semana_Resumen_Mantencion` | str/null | Maintenance week reference (e.g., '01-2025') | Source |
| `has_telemetry` | bool | Derived flag | `Trigger_type in ['Telemetria', 'Mixto']` |
| `has_tribology` | bool | Derived flag | `Trigger_type in ['Tribologia', 'Mixto']` |
| `Month` | Period | Month period | `Timestamp.dt.to_period('M')` |

**Implementation Location**: `src/data/loaders.py` lines 318-373

### 3.2 Telemetry Supporting Data

#### Telemetry Values (Wide Format)
**Source**: `data/telemetry/silver/CDA/telemetry_values_wide.parquet`

**Schema**:
- `Fecha` (datetime): Timestamp
- `Unit` (str): Unit identifier
- Multiple sensor columns (dynamic): e.g., `EngSpd`, `OilPressure`, `CoolantTemp`, etc.

**Loader**: `load_telemetry_values(client: str)` - lines 376-399

#### Telemetry States
**Source**: `data/telemetry/silver/CDA/telemetry_states.parquet`

**Schema**:
- `Fecha` (datetime): Timestamp
- `Unit` (str): Unit identifier
- `Estado` (str): Operational state ('Operacional', 'Ralenti', 'ND')
- `EstadoCarga` (str): Payload state ('Cargado', 'Vacío', 'ND')

**Loader**: `load_telemetry_states(client: str)` - lines 402-424

#### Telemetry Limits Configuration
**Source**: `data/telemetry/silver/CDA/limits_config.parquet`

**Schema**:
- `Unit` (str): Unit identifier
- `Feature` (str): Sensor feature name
- `Estado` (str): Operational state
- `EstadoCarga` (str): Payload state
- `Limit_Lower` (float): Lower threshold
- `Limit_Upper` (float): Upper threshold

**Loader**: `load_telemetry_limits(client: str)` - lines 427-449

#### Telemetry Alerts Metadata
**Source**: `data/telemetry/golden/CDA/alerts_data.csv`

**Schema**:
- `AlertID` (str): Telemetry alert identifier
- `Trigger` (str): Feature that triggered the alert
- Additional metadata columns

**Loader**: `load_telemetry_alerts_metadata(client: str)` - lines 452-476

#### Component Mapping
**Source**: `data/telemetry/golden/CDA/component_mapping.parquet`

**Schema**:
- `Component` (str): Component name
- `PrimaryFeature` (str): Main sensor for this component
- `System` (str): System classification
- `SubSystem` (str): Subsystem classification
- `Meaning` (str): Description
- `RelatedFeatures` (list): List of related sensor features

**Loader**: `load_component_mapping(client: str)` - lines 479-502

#### Feature Names Mapping
**Source**: `data/telemetry/golden/CDA/feature_names.csv`

**Schema**:
- `Feature` (str): Feature code
- `Name` (str): Spanish display name

**Returns**: Dict[str, str] mapping feature codes to Spanish names

**Loader**: `load_feature_names(client: str)` - lines 505-529

### 3.3 Tribology (Oil Analysis) Data

#### Classified Oil Reports
**Source**: `data/oil/golden/CDA/classified.parquet`

**Schema** (relevant columns):
- `sampleNumber` (str): Oil sample identifier
- Essay columns ending in `_ppm`: e.g., `Hierro_ppm`, `Cobre_ppm`, `Silicio_ppm`
- `report_status` (str): Overall report status
- `breached_essays` (list): Essays exceeding thresholds
- `ai_recommendation` (str): AI-generated recommendation

**Loader**: `load_oil_classified(client: str)` - lines 532-554

### 3.4 Maintenance Data

**Source**: `data/mantentions/golden/CDA/{week}.csv` (e.g., `01-2025.csv`)

**Schema**:
- `UnitId` (str): Unit identifier
- `Semana` (str): Week identifier
- `Summary` (str): Summary of maintenance activities
- `Tasks_List` (str): JSON-encoded tasks dictionary

**Tasks_List Structure** (JSON string):
```json
{
  "2025-01-05": {
    "Motor": ["Task 1", "Task 2"],
    "Transmision": ["Task 3"]
  }
}
```

**Loader**: `load_maintenance_week(client: str, week: str)` - lines 557-583

---

## 4. User Interface Structure

### 4.1 Main Tab Container

**File**: `dashboard/tabs/tab_alerts.py`

**Components**:
1. **Header Section**:
   - Title: "Monitor de Alertas"
   - Subtitle: "Sistema integral de análisis y seguimiento de alertas"

2. **Client Notice** (`alerts-client-notice`):
   - Info alert: "Este módulo está disponible únicamente para el cliente CDA"

3. **Internal Tabs** (`alerts-internal-tabs`):
   - Tab 1: "Vista General" (value='general')
   - Tab 2: "Vista Detallada" (value='detail')
   - Custom styling with CSS classes

4. **Tab Content Container** (`alerts-tab-content`):
   - Dynamically renders content based on selected tab

5. **Filter Store** (`alerts-filter-store`):
   - Memory store for click-based filters

### 4.2 General View Layout

**File**: `dashboard/tabs/tab_alerts_general.py`

**Structure** (top to bottom):

#### 1. Summary Statistics (`alerts-summary-stats`)
Displays 4 KPI cards:
- Total Alertas (primary color)
- Unidades Afectadas (info color)
- % con Telemetría (success color)
- % con Tribología (warning color)

**Function**: `create_summary_stats_display(total_alerts, total_units, telemetry_pct, oil_pct)`

#### 2. Analytics Charts Row (3 columns, md=4 each)

**Chart 1: Distribution per Unit** (`alerts-unit-distribution-chart`)
- Type: Horizontal bar chart
- Groups by: `UnitId` and `sistema`
- Interactive: Click to filter
- Icon: `fas fa-truck`

**Chart 2: Distribution per Month** (`alerts-month-distribution-chart`)
- Type: Vertical bar chart
- Groups by: `Month` and `sistema`
- Interactive: Click to filter
- Icon: `fas fa-calendar-alt`

**Chart 3: Trigger Distribution** (`alerts-trigger-distribution-chart`)
- Type: Treemap
- Shows: `Trigger_type` distribution
- Interactive: Click to filter
- Icon: `fas fa-signal`

#### 3. Table and System Distribution Row

**Left Column (md=8): Alerts Table** (`alerts-datatable`)
- Interactive DataTable with:
  - Columns: ID, Fecha, Unidad, Sistema, Componente, Fuente, Diagnóstico IA, Telemetría, Tribología
  - Row click navigation to Detail view
  - Native filtering and sorting
  - Pagination (20 rows per page)
  - Hint text: "→ Haga clic en cualquier fila para ver detalles completos"

**Right Column (md=4): System Distribution** (`alerts-system-distribution-chart`)
- Type: Donut/Pie chart
- Shows: Distribution by `sistema`
- Interactive: Click to filter
- Icon: `fas fa-cogs`

#### 4. Navigation Card (bottom)
**Components**:
- **Alert Selector Dropdown** (`general-alert-selector`):
  - Populated with all alerts
  - Format: `{FusionID} | {Timestamp} | {UnitId} | {componente}`
  - Searchable and clearable

- **Navigation Button** (`general-nav-to-detail-button`):
  - Label: "Ver Detalle →"
  - Color: Primary
  - Triggers store-based navigation

### 4.3 Detail View Layout

**File**: `dashboard/tabs/tab_alerts_detail.py`

**Structure** (top to bottom):

#### 1. Filters Section
Card with 4 filter dropdowns (md=3 each):
- **Unit Filter** (`detail-filter-unit`): Multi-select
- **System Filter** (`detail-filter-sistema`): Multi-select
- **Telemetry Filter** (`detail-filter-telemetry`): Single-select (Sí/No/Todos)
- **Tribology Filter** (`detail-filter-tribology`): Single-select (Sí/No/Todos)

#### 2. Alert Selector
Card with:
- **Alert Dropdown** (`alert-selector-dropdown`):
  - Searchable and clearable
  - Options filtered by above filters
  - Hint: "También puede seleccionar una alerta desde la Vista General"

#### 3. Detail Content Container (`alert-detail-content`)
Conditional rendering based on alert trigger type.

**Default State** (no alert selected):
- Info alert: "Por favor, seleccione una alerta para ver los detalles"

**When Alert Selected**:
Content is dynamically generated by `create_telemetry_evidence_section()`, `create_oil_evidence_section()`, and `create_maintenance_evidence_section()`.

---

## 5. Functionality Implementation

### 5.1 Tab Switching

**Callback**: `render_tab_content(active_tab)`
- **Input**: `alerts-internal-tabs.value`
- **Output**: `alerts-tab-content.children`
- **Logic**: 
  - If `active_tab == 'general'`: Return `create_general_layout()`
  - If `active_tab == 'detail'`: Return `create_detail_layout()`
  - Else: Return error message

**Location**: `dashboard/callbacks/alerts_callbacks.py` lines 62-76

### 5.2 Interactive Filtering (General View)

**Callback**: `update_filters_from_clicks(unit_click, month_click, trigger_click, system_click, current_filters)`

**Inputs** (clickData from 4 charts):
1. `alerts-unit-distribution-chart.clickData`
2. `alerts-month-distribution-chart.clickData`
3. `alerts-trigger-distribution-chart.clickData`
4. `alerts-system-distribution-chart.clickData`

**State**: `alerts-filter-store.data`

**Output**: `alerts-filter-store.data`

**Behavior** (Toggle Pattern):
- First click: Sets filter
- Second click on same value: Clears filter
- Click on different value: Updates filter

**Filter Keys**:
- `unit`: Unit identifier
- `month`: Month string (YYYY-MM format)
- `trigger`: Trigger type
- `sistema`: System name

**Location**: `dashboard/callbacks/alerts_callbacks.py` lines 85-169

### 5.3 General View Update

**Callback**: `update_general_tab(client, filters)`

**Inputs**:
1. `client-selector.value`
2. `alerts-filter-store.data`

**Outputs** (6 components):
1. `alerts-unit-distribution-chart.figure`
2. `alerts-month-distribution-chart.figure`
3. `alerts-trigger-distribution-chart.figure`
4. `alerts-system-distribution-chart.figure`
5. `alerts-summary-stats.children`
6. `alerts-table-container.children`

**Processing Logic**:
1. Load alerts data: `load_alerts_data(client)`
2. Apply filters if present:
   - Unit filter: Match `UnitId`
   - Month filter: Match first 7 chars of `Month` (YYYY-MM)
   - Trigger filter: Match `Trigger_type`
   - Sistema filter: Match `sistema`
3. Create visualizations using filtered data
4. Calculate summary statistics
5. Render DataTable

**Location**: `dashboard/callbacks/alerts_callbacks.py` lines 177-267

### 5.4 Dropdown Population

#### General Tab Alert Selector

**Callback**: `populate_general_alert_selector(client)`
- **Input**: `client-selector.value`
- **Output**: `general-alert-selector.options`
- **Logic**: Load all alerts, create dropdown options sorted by timestamp (descending)

**Location**: `dashboard/callbacks/alerts_callbacks.py` lines 362-395

#### Detail Tab Alert Selector (Initial)

**Callback**: `initialize_alert_dropdown(client)`
- **Input**: `client-selector.value`
- **Output**: `alert-selector-dropdown.options`
- **Logic**: Same as general selector

**Location**: `dashboard/callbacks/alerts_callbacks.py` lines 269-306

#### Detail Tab Alert Selector (Filtered)

**Callback**: `filter_alert_dropdown_by_criteria(units, sistemas, has_telemetry, has_tribology, client, current_value)`

**Inputs**:
1. `detail-filter-unit.value`
2. `detail-filter-sistema.value`
3. `detail-filter-telemetry.value`
4. `detail-filter-tribology.value`
5. `client-selector.value`

**State**: `alert-selector-dropdown.value` (current selection)

**Output**: `alert-selector-dropdown.options` (allow_duplicate=True)

**Logic**:
- Apply filters to alerts DataFrame
- Regenerate dropdown options with filtered alerts
- Preserves current selection if it's still in filtered list

**Location**: `dashboard/callbacks/alerts_callbacks.py` lines 544-614

### 5.5 Cross-Tab Navigation

**Implementation Pattern**: Store-based intermediary (avoids targeting dynamic components)

#### Step 1: Button Click → Store Update

**Callback**: `navigate_to_detail_from_general(n_clicks, selected_alert_id)`
- **Input**: `general-nav-to-detail-button.n_clicks`
- **State**: `general-alert-selector.value`
- **Output**: `alerts-navigation-state.data`
- **Returns**: `{'target_tab': 'detail', 'alert_id': selected_alert_id}`

**Location**: `dashboard/callbacks/alerts_callbacks.py` lines 398-424

#### Step 2: Store Change → Tab Switch

**Callback**: `switch_to_detail_tab(nav_data)`
- **Input**: `alerts-navigation-state.data`
- **Output**: `alerts-internal-tabs.value` (allow_duplicate=True)
- **Logic**: Switches to 'detail' tab when navigation data present

**Location**: `dashboard/callbacks/alerts_callbacks.py` lines 427-446

#### Step 3: Tab + Store → Set Dropdown

**Callback**: `set_alert_from_navigation(active_tab, nav_data)`
- **Inputs**: 
  - `alerts-internal-tabs.value`
  - `alerts-navigation-state.data`
- **Output**: `alert-selector-dropdown.value` (allow_duplicate=True, prevent_initial_call='initial_duplicate')
- **Logic**: Sets dropdown value when on detail tab with valid navigation data

**Location**: `dashboard/callbacks/alerts_callbacks.py` lines 449-480

### 5.6 Row Click Navigation (Table)

**Callback**: `navigate_to_detail_on_row_click(active_cell, derived_data)`
- **Input**: `alerts-datatable.active_cell`
- **State**: `alerts-datatable.derived_virtual_data`
- **Outputs**:
  1. `alerts-internal-tabs.value` (allow_duplicate=True)
  2. `alert-selector-dropdown.value` (allow_duplicate=True)
- **Logic**:
  - Gets row index from `active_cell`
  - Retrieves `FusionID` from `derived_virtual_data` (handles pagination/filtering)
  - Switches tab to 'detail' and sets dropdown value

**Location**: `dashboard/callbacks/alerts_callbacks.py` lines 309-359

### 5.7 Detail View Update

**Main Callback**: `update_detail_view(dropdown_value, client)`

**Inputs**:
1. `alert-selector-dropdown.value`
2. `client-selector.value`

**Output**: `alert-detail-content.children`

**Processing Logic**:
1. Validate inputs (client and alert selected)
2. Load alerts data
3. Find selected alert by `FusionID`
4. Determine evidence sections based on `Trigger_type`:
   - **Telemetry**: If 'telemetria' or 'mixto' in trigger_type (case-insensitive)
   - **Oil**: If 'tribologia', 'oil', or 'mixto' in trigger_type
   - **Maintenance**: If `Semana_Resumen_Mantencion` is not null
5. Build sections array:
   - Alert Specification Card (always)
   - Telemetry Evidence Section (conditional)
   - Oil Evidence Section (conditional)
   - Maintenance Evidence Section (conditional)
6. Return combined sections

**Location**: `dashboard/callbacks/alerts_callbacks.py` lines 617-712

---

## 6. Navigation Patterns

### 6.1 Navigation Flow Summary

```
General View → Detail View Navigation:

Path 1: Button Navigation
User selects alert → Clicks "Ver Detalle" button → Store updated → Tab switches → Dropdown set → Detail loads

Path 2: Table Row Click
User clicks table row → Tab switches + Dropdown set (simultaneously) → Detail loads
```

### 6.2 Store-Based Pattern Rationale

**Problem**: `alerts-internal-tabs` is rendered dynamically, so callbacks can't directly target child components during registration.

**Solution**: Use intermediary store (`alerts-navigation-state`) that exists at app startup:
1. Button callback outputs to store (not dynamic component)
2. Listener callback reads store and updates tab value
3. Alert selection callback reads tab + store to set dropdown

**Benefits**:
- Reliable callback registration
- Clean separation of concerns
- Predictable execution flow

---

## 7. Component Specifications

### 7.1 Chart Components

**File**: `dashboard/components/alerts_charts.py`

#### 1. `create_alerts_per_unit_chart(alerts_df)`
- **Type**: Horizontal bar chart (Plotly Express)
- **Data**: Groups by `UnitId` and `sistema`
- **Color**: By `sistema` using `plotly.colors.qualitative.Set1`
- **Sort**: By count (ascending)
- **Height**: 500px
- **Returns**: `go.Figure`

**Location**: Lines 24-83

#### 2. `create_alerts_per_month_chart(alerts_df)`
- **Type**: Vertical bar chart (Plotly Express)
- **Data**: Groups by `Month` and `sistema`
- **Color**: By `sistema` using `plotly.colors.qualitative.Set1`
- **X-axis**: Month as string, rotated -45°
- **Height**: 500px
- **Hover**: X unified mode

**Location**: Lines 86-150

#### 3. `create_trigger_distribution_treemap(alerts_df)`
- **Type**: Treemap (Plotly Express)
- **Data**: Counts by `Trigger_type`
- **Color**: Continuous scale 'Blues' based on frequency
- **Text**: Label + value + percent parent
- **Height**: 500px

**Location**: Lines 153-194

#### 4. `create_system_distribution_pie_chart(alerts_df)`
- **Type**: Donut chart (Plotly Express, hole=0.3)
- **Data**: Counts by `sistema`
- **Color**: `plotly.colors.qualitative.Set1`
- **Sort**: Reverse alphabetical (for consistency)
- **Height**: 500px
- **Legend**: Vertical, positioned right

**Location**: Lines 654-695

#### 5. `create_sensor_trends_chart(...)`
**Parameters**:
- `telemetry_values`: Wide-format telemetry data
- `telemetry_states`: Operational states
- `limits_config`: Sensor limits
- `unit_id`: Unit identifier
- `sensor_columns`: List of sensors to plot
- `alert_time`: Alert timestamp
- `window_start`, `window_end`: Time window
- `feature_names`: Sensor name mapping

**Type**: Multi-panel subplots (Plotly subplots)
- One subplot per sensor
- Data points colored by operational state:
  - 'Operacional': Green (#2ecc71)
  - 'Ralenti': Orange (#f39c12)
  - 'ND': Gray (#95a5a6)
- Red dashed lines for upper/lower limits
- Orange vertical line at alert time
- Shared X-axis
- Height: 300px × number of sensors

**Location**: Lines 210-461

#### 6. `create_gps_route_map(...)`
**Parameters**:
- `telemetry_values`: GPS data (GPSLat, GPSLon)
- `unit_id`: Unit identifier
- `alert_time`: Alert timestamp
- `window_start`, `window_end`: Time window
- `mapbox_token`: Mapbox access token

**Type**: Mapbox scatter plot
- Gray route line
- Colored points (time gradient, 'Reds' colorscale)
- Black marker at alert location
- Satellite-streets style
- Auto-centered and zoomed
- Height: 600px

**Location**: Lines 464-550

#### 7. `create_oil_radar_chart(oil_report, essay_cols)`
**Parameters**:
- `oil_report`: Series with oil report data
- `essay_cols`: List of essay column names (ending with _ppm)

**Type**: Radar/Polar chart (Scatterpolar)
- Fills to self (blue #3498db)
- Theta values: Essay names (formatted from column names)
- R values: PPM readings
- Radial axis scaled to max value × 1.2
- Height: 500px

**Location**: Lines 553-607

### 7.2 Table Components

**File**: `dashboard/components/alerts_tables.py`

#### 1. `create_alerts_datatable(alerts_df)`
**Displays Columns**:
- ID, Fecha, Unidad, Sistema, Componente, Fuente, Diagnóstico IA, Telemetría, Tribología

**Features**:
- Truncates AI message to 80 characters
- Converts booleans to ✓/✗ symbols
- Formats timestamp to YYYY-MM-DD HH:MM:SS
- Native filtering, sorting, pagination (20 rows/page)
- Row hover and active styling
- Cell-selectable for navigation

**Styling**:
- Header: Dark (#2c3e50), white text, centered
- Odd rows: Light gray (#f8f9fa)
- Active row: Blue (#3498db), white text, 2px border

**Location**: Lines 14-131

#### 2. `create_alert_detail_card(alert_row)`
**Displays**:
- **Header Section** (2 columns):
  - Left: Fecha, Unidad, Sistema
  - Right: SubSistema, Componente, Fuente
- **Diagnosis Section**:
  - Icon: Robot (fas fa-robot)
  - Full AI message with pre-wrap whitespace

**Colors**: Warning header (yellow), white text

**Location**: Lines 134-205

#### 3. `create_context_kpis_cards(alert_row, telemetry_data, alert_time)`
**Returns**: Row with 3 KPI cards:

**KPI 1: Elevation Status**
- Calculates: 5-point averages before/after alert
- Gradient > 0.05: "⬆️ Subiendo" (info)
- Gradient < -0.05: "⬇️ Bajando" (warning)
- Else: "➡️ Plano" (secondary)

**KPI 2: Payload Status**
- From `EstadoCarga` column
- "✅ Cargado" (success) or "❌ Vacío" (danger)

**KPI 3: Engine RPM**
- Finds RPM column (contains 'rpm' or 'engspd')
- Rounds to nearest 100
- Displays: "{value} RPM" (primary color)

**Location**: Lines 208-308

#### 4. `create_maintenance_display(maintenance_data, alert_system)`
**Displays**:
- Unit identifier
- Week identifier
- System of interest (from alert)
- Summary of activities
- **Filtered Tasks**: Only shows tasks for the alert system
  - Parses `Tasks_List` JSON
  - Case-insensitive system matching
  - Groups by date

**Location**: Lines 311-444

---

## 8. Data Processing Logic

### 8.1 Time Window Calculation

**Constants** (defined in `alerts_callbacks.py`):
- `M1 = 60`: Minutes before alert
- `M2 = 10`: Minutes after alert

**Usage**:
```python
alert_time = alert_row['Timestamp']
window_start = alert_time - timedelta(minutes=M1)
window_end = alert_time + timedelta(minutes=M2)
```

### 8.2 Sensor Selection Logic

**For Telemetry Evidence**:

1. **Primary Path** (if TelemetryID and mapping available):
   - Get `Trigger` from telemetry alerts metadata
   - Lookup in component mapping to find `PrimaryFeature` and `RelatedFeatures`
   - Display: Primary + Related features

2. **Fallback Path**:
   - Select first 3 non-metadata columns from telemetry values
   - Excludes: 'Fecha', 'Unit', 'Estado', 'EstadoCarga', 'GPSLat', 'GPSLon', 'GPSElevation'

**Implementation**: `create_telemetry_evidence_section()` lines 767-802

### 8.3 Essay Columns Detection

**For Oil Evidence**:

Identifies essay columns by suffix:
```python
essay_cols = [col for col in oil_report.index if col.endswith('_ppm')]
```

Excludes metadata columns like `sampleNumber`, `sampleDate`, `unitId`, etc.

**Implementation**: `create_oil_evidence_section()` lines 877-882

### 8.4 Trigger Type Normalization

**Logic**:
```python
trigger_type = alert_row['Trigger_type']
trigger_lower = str(trigger_type).lower()
show_telemetry = 'telemetria' in trigger_lower or 'mixto' in trigger_lower
show_oil = 'tribologia' in trigger_lower or 'oil' in trigger_lower or 'mixto' in trigger_lower
show_maintenance = pd.notna(alert_row.get('Semana_Resumen_Mantencion'))
```

**Supported Values** (case-insensitive):
- **Telemetria**: Shows telemetry evidence
- **Tribologia/Oil**: Shows oil evidence
- **Mixto**: Shows both telemetry and oil evidence

### 8.5 Filter Application Sequence

**In General View**:
1. Load full alerts dataset
2. Apply filters in order:
   - Unit filter (exact match on `UnitId`)
   - Month filter (first 7 chars of `Month` string: YYYY-MM)
   - Trigger filter (exact match on `Trigger_type`)
   - Sistema filter (exact match on `sistema`)
3. Use filtered data for all visualizations

**In Detail View**:
1. Load full alerts dataset
2. Apply detail filters:
   - Unit filter (multi-select: `UnitId.isin(units)`)
   - Sistema filter (multi-select: `sistema.isin(sistemas)`)
   - Telemetry filter: `has_telemetry == True/False`
   - Tribology filter: `has_tribology == True/False`
3. Generate dropdown options from filtered data

---

## 9. Limitations and Constraints

### 9.1 Client Restrictions

- **Hard-coded CDA check**: All loaders return empty DataFrames for non-CDA clients
- **No multi-client support**: Cannot view multiple clients simultaneously
- **UI alert**: Displays info notice about CDA-only availability

### 9.2 Data Dependencies

**Required Files**:
1. `data/alerts/golden/CDA/consolidated_alerts.csv` (core)
2. `data/telemetry/silver/CDA/telemetry_values_wide.parquet` (for telemetry evidence)
3. `data/telemetry/silver/CDA/telemetry_states.parquet` (for telemetry evidence)
4. `data/telemetry/silver/CDA/limits_config.parquet` (for telemetry evidence)
5. `data/telemetry/golden/CDA/alerts_data.csv` (for trigger identification)
6. `data/telemetry/golden/CDA/component_mapping.parquet` (for sensor selection)
7. `data/telemetry/golden/CDA/feature_names.csv` (for Spanish names)
8. `data/oil/golden/CDA/classified.parquet` (for oil evidence)
9. `data/mantentions/golden/CDA/{week}.csv` (for maintenance evidence)

**Missing File Behavior**:
- Loaders return empty DataFrames with warning logs
- UI shows "No data available" alerts
- Does not crash application

### 9.3 Time Window Constraints

- **Fixed window**: M1=60 min before, M2=10 min after
- **Not configurable**: Users cannot adjust time window
- **GPS data dependency**: Map requires GPS coordinates within window

### 9.4 Maintenance Data Limitations

- **Week-based lookup**: Requires exact week identifier (e.g., '01-2025')
- **JSON parsing**: Relies on specific JSON structure in `Tasks_List`
- **Case-sensitive system matching**: System names must match (but implementation uses case-insensitive comparison)

### 9.5 Navigation Constraints

- **Single alert selection**: Cannot compare multiple alerts side-by-side
- **No back button**: Users must manually switch tabs to return to General view
- **Store not cleared**: Navigation state persists until overwritten

### 9.6 Performance Considerations

- **Full data load**: Loads entire alerts dataset on every client change
- **No caching**: Repeated data loading for same client
- **Filter recalculation**: All charts regenerate on every filter change
- **Large datasets**: 20 rows per page in table helps, but initial load processes all rows

### 9.7 UI/UX Limitations

- **Chart interaction**: Only click-to-filter, no brush selection or zoom persistence
- **Toggle-only filtering**: Cannot multi-select filters (except in detail view dropdowns)
- **No filter summary**: Users don't see which filters are active (except by chart highlighting)
- **AI message truncation**: Table shows only first 80 characters of diagnostic

### 9.8 Mapbox Dependency

- **API Key Required**: `MAPBOX_TOKEN` must be set in environment
- **Satellite view only**: Hard-coded to "satellite-streets" style
- **Internet connection**: Requires external API calls for map tiles

### 9.9 Data Consistency Assumptions

**The implementation assumes**:
1. `FusionID` is unique across all alerts
2. `UnitId` exists in both alerts and telemetry data (consistent naming)
3. `TelemetryID` matches `AlertID` in telemetry alerts metadata
4. `OilReportNumber` matches `sampleNumber` in classified oil reports
5. `Semana_Resumen_Mantencion` matches maintenance file names (e.g., '01-2025.csv')
6. Timestamp formats are consistent and parseable
7. Column names are standardized (e.g., essay columns end with '_ppm')

---

## Summary

This implementation documentation describes a comprehensive alerts monitoring dashboard with:

- **Unified interface**: Two-tab system (General + Detail views)
- **Multi-source fusion**: Combines telemetry and tribology alerts
- **Rich interactivity**: Click-to-filter, row-click navigation, button navigation
- **Contextual evidence**: Shows relevant data based on alert source
- **CDA-exclusive**: Hard-coded client restriction with explicit checks
- **Store-based architecture**: Uses Dash stores for state management and cross-component communication

The implementation follows Dash best practices with clear separation between layout (`tabs/`), interaction logic (`callbacks/`), and visualization components (`components/`).

**Total Lines of Code**:
- Callbacks: ~1,344 lines
- Charts: ~695 lines
- Tables: ~444 lines
- Layouts: ~641 lines (combined)
- **Total**: ~3,124 lines of alerts-specific code

---

**End of Implementation Documentation**
