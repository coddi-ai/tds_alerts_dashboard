# Implementation vs Design - Gap Analysis

**Document Purpose**: Identifies all differences between the designed specifications and the actual implementation of the Alerts Dashboard.

**Original Comparison Date**: February 17, 2026  
**Last Updated**: February 17, 2026 (Sections 2, 3, 4 resolved)  
**Design Documents**: `dashboard_overview.md`, `data_contracts.md`  
**Implementation Document**: `alerts_dashboard_implementation_notes.md`

---

## Change Log

### February 17, 2026
- **RESOLUTION**: Updated `dashboard_overview.md` to match actual implementation for:
  - Section 2: UI Structure Differences (12 items) - All differences documented in design
  - Section 3: Functionality Differences (6 items) - All features documented in design
  - Section 4: Navigation Differences (3 items) - All navigation patterns documented in design
- Removed references to non-existent helper functions (`visualizations.py`)
- Updated time window M1 from 90 to 60 minutes
- Updated GPS map colorscale from 'Aggrnyl' to 'Reds'
- Updated GPS map style to 'satellite-streets'
- Added interactive chart filtering documentation
- Added navigation card documentation
- Removed future features that don't match current scope

---

## Summary

This document contains **31 identified differences** between design and implementation, categorized into:
- Data Schema Differences (7) - **OPEN**
- UI Structure Differences (12) - **✅ RESOLVED** (Updated dashboard_overview.md on Feb 17, 2026)
- Functionality Differences (6) - **✅ RESOLVED** (Updated dashboard_overview.md on Feb 17, 2026)
- Navigation Differences (3) - **✅ RESOLVED** (Updated dashboard_overview.md on Feb 17, 2026)
- Data Processing Differences (3) - **OPEN**

**Status Legend**:
- ✅ **RESOLVED**: Design documentation updated to match implementation
- **OPEN**: Design still differs from implementation

---

## 1. Data Schema Differences

### 1.1 FusionID Format

**Location**: Data Contracts - Consolidated Alerts Schema

**Design Specification**:
- Format: `FUS-{sequential_number}`
- Example: `FUS-001`, `FUS-045`, `FUS-1023`
- Generation: Auto-increment starting from 001

**Actual Implementation**:
- Format: Not specified/enforced in code
- Treated as generic string identifier
- No auto-increment logic visible

**Impact**: FusionID may not follow the designed naming convention

**Found in**:
- Design: `data_contracts.md` - Field Definitions section
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1

---

### 1.2 Trigger_type Values

**Location**: Data Contracts - Field Definitions

**Design Specification**:
- Values: `'telemetry'` | `'oil'`
- Future: May support correlation alerts
- All lowercase

**Actual Implementation**:
- Values: `'Telemetria'`, `'Tribologia'`, `'Mixto'`
- Already supports mixed/correlation alerts (Mixto)
- Title case (capitalized)

**Impact**: Different value set and casing; "Mixto" type already implemented (not in future)

**Found in**:
- Design: `data_contracts.md` - Field Definitions
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1, Table

---

### 1.3 Oil Reference Column Name

**Location**: Data Contracts - Consolidated Alerts Schema

**Design Specification**:
- Column name: `TribologyID`
- Type: string (nullable)
- Description: Reference to oil sample number

**Actual Implementation**:
- Column name: `OilReportNumber`
- Type: string (nullable)
- Same purpose but different name

**Impact**: Different column name in actual data

**Found in**:
- Design: `data_contracts.md` - Table schema
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1, Table

---

### 1.4 System Hierarchy Column Names

**Location**: Data Contracts - Field Definitions

**Design Specification**:
- Column names: `System`, `SubSystem`, `Component`
- Title case with capital S

**Actual Implementation**:
- Column names: `sistema`, `subsistema`, `componente`
- All lowercase, Spanish naming

**Impact**: Different casing and column naming convention

**Found in**:
- Design: `data_contracts.md` - Schema table
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1, Table

---

### 1.5 Telemetry Alert Reference

**Location**: Data Contracts - Field Definitions

**Design Specification**:
- Source reference: `telemetry/golden/{client}/alerts_data.csv -> AlertID`
- Column type specified

**Actual Implementation**:
- Same source but implementation shows `TelemetryID` stored as string
- Confirms nullable behavior

**Impact**: Minor - implementation matches design intent

**Found in**:
- Design: `data_contracts.md` - Field Definitions
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1

---

### 1.6 Default Values for Missing Data

**Location**: Data Loading Logic

**Design Specification**:
- Not explicitly specified how to handle missing sistema/subsistema/componente

**Actual Implementation**:
- Missing values filled with `'Desconocido'`
- Explicit fill logic: `df['sistema'] = df['sistema'].fillna('Desconocido')`

**Impact**: Implementation adds default handling not in design

**Found in**:
- Design: `data_contracts.md` - No mention
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1, load_alerts_data

---

### 1.7 Derived Columns Logic

**Location**: Data Contracts vs Implementation

**Design Specification**:
- `has_telemetry`: True if `TelemetryID` is not null
- `has_tribology`: True if `TribologyID` is not null

**Actual Implementation**:
- `has_telemetry`: Derived from `Trigger_type in ['Telemetria', 'Mixto']`
- `has_tribology`: Derived from `Trigger_type in ['Tribologia', 'Mixto']`
- Logic based on Trigger_type value, not null checks on ID columns

**Impact**: Different derivation logic; implementation doesn't check ID columns

**Found in**:
- Design: `dashboard_overview.md` - Section 3.2
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 3.1, Table

---

## 2. UI Structure Differences - ✅ RESOLVED

**Status**: Design documentation updated to match implementation (February 17, 2026)

### 2.1 General Tab Sections Count

**Location**: General Tab Layout

**Design Specification**:
- 2 sections total:
  - Section 1: Data Analysis (3 Figures)
  - Section 2: Alerts Table

**Actual Implementation**:
- 4 sections total:
  - Section 1: Summary Statistics (4 KPI cards)
  - Section 2: Analytics Charts (3 charts)
  - Section 3: Table + System Distribution
  - Section 4: Navigation Card

**Impact**: Significant structural difference; implementation has 2 additional sections

**Found in**:
- Design: `dashboard_overview.md` - Section 3 (General Tab)
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 4.2

---

### 2.2 Summary Statistics Section (Not in Design)

**Location**: General Tab - Top Section

**Design Specification**:
- Not present
- No mention of summary KPI cards

**Actual Implementation**:
- Added as first section (`alerts-summary-stats`)
- Displays 4 KPI cards:
  - Total Alertas
  - Unidades Afectadas
  - % con Telemetría
  - % con Tribología
- Function: `create_summary_stats_display()`

**Impact**: Addition not in original design; provides overview metrics

**Found in**:
- Design: `dashboard_overview.md` - Not mentioned
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 4.2.1

---

### 2.3 System Distribution Chart Addition

**Location**: General Tab - Section 3

**Design Specification**:
- Section 2: Only Alerts Table (full width)
- No pie/donut chart for system distribution

**Actual Implementation**:
- Table: 8 columns (md=8)
- System Distribution Pie Chart: 4 columns (md=4)
- Chart shows distribution by `sistema`
- Interactive (click to filter)

**Impact**: Major addition; chart not in original design

**Found in**:
- Design: `dashboard_overview.md` - Section 3, "Section 2: Alerts Table"
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 4.2.3

---

### 2.4 Navigation Card Section (Not in Design)

**Location**: General Tab - Bottom Section

**Design Specification**:
- Not present
- No navigation UI from General to Detail tab
- Only row click navigation mentioned

**Actual Implementation**:
- Complete navigation card at bottom
- Components:
  - Alert selector dropdown (`general-alert-selector`)
  - "Ver Detalle" button (`general-nav-to-detail-button`)
- Store-based navigation pattern

**Impact**: Major addition; provides explicit navigation mechanism

**Found in**:
- Design: `dashboard_overview.md` - Not mentioned in General Tab
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 4.2.4

---

### 2.5 Chart Type for Unit Distribution

**Location**: General Tab - Analytics Charts

**Design Specification**:
- Type: Horizontal Bar Chart (Histogram)
- Uses `plotly.express.histogram()`
- Orientation: 'h'

**Actual Implementation**:
- Type: Horizontal bar chart
- Uses `plotly.express.bar()` (not histogram)
- Groups data explicitly before plotting
- Different implementation approach

**Impact**: Different Plotly method; same visual result but different data processing

**Found in**:
- Design: `dashboard_overview.md` - Section 3.2, Figure 1
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 7.1.1

---

### 2.6 Table Columns Displayed

**Location**: General Tab - Alerts Table

**Design Specification**:
- 6 columns:
  1. Timestamp
  2. UnitId
  3. Component
  4. mensaje_ia
  5. has_telemetry
  6. has_tribology

**Actual Implementation**:
- 9 columns:
  1. ID (FusionID)
  2. Fecha (Timestamp)
  3. Unidad (UnitId)
  4. Sistema (sistema)
  5. Componente (componente)
  6. Fuente (Trigger_type)
  7. Diagnóstico IA (mensaje_ia)
  8. Telemetría (has_telemetry)
  9. Tribología (has_tribology)

**Impact**: Implementation shows more columns (ID, Sistema, Fuente)

**Found in**:
- Design: `dashboard_overview.md` - Section 3.2
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 4.2.3, Section 7.2.1

---

### 2.7 Detail Tab Filter Section (Not in Design)

**Location**: Detail Tab - Top Section

**Design Specification**:
- No filters section
- Detail tab starts with Alert Specification

**Actual Implementation**:
- Filters section as first component
- 4 filter dropdowns:
  - Unit Filter (multi-select)
  - System Filter (multi-select)
  - Telemetry Filter (single-select)
  - Tribology Filter (single-select)
- Filters affect dropdown options

**Impact**: Major addition; filtering capability not in design

**Found in**:
- Design: `dashboard_overview.md` - Section 4
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 4.3.1

---

### 2.8 Detail Tab Alert Selector

**Location**: Detail Tab - Alert Selection

**Design Specification**:
- Not explicitly shown as separate component
- Alert selected is passed via navigation from General tab

**Actual Implementation**:
- Dedicated "Alert Selector" card
- Dropdown component (`alert-selector-dropdown`)
- User can manually select/change alert
- Hint text about General tab selection

**Impact**: Implementation provides manual selection capability

**Found in**:
- Design: `dashboard_overview.md` - Section 4 (not mentioned)
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 4.3.2

---

### 2.9 Telemetry Evidence Layout

**Location**: Detail Tab - Telemetry Evidence Section

**Design Specification**:
- Layout: 3 equal-width columns
- Column 1: Sensor Trends
- Column 2: GPS Location
- Column 3: Alert Context (KPIs)

**Actual Implementation**:
- Different structure:
  - Row 1: Sensor Trends (6 cols) | GPS Map (6 cols)
  - Row 2: KPIs Card (12 cols full width)
- KPIs in separate full-width row, not side column

**Impact**: Different visual layout; KPIs more prominent

**Found in**:
- Design: `dashboard_overview.md` - Section 4.3.2, "Subsection: Telemetry Evidence"
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 4.3.3

---

### 2.10 Oil Evidence Layout

**Location**: Detail Tab - Oil Evidence Section

**Design Specification**:
- Chart Type: Radar Chart only
- Shows essay levels with thresholds

**Actual Implementation**:
- Layout: Row with 2 columns
  - Column 1 (8 cols): Radar Chart
  - Column 2 (4 cols): Oil Report Status display
- Status display shows:
  - Report status badge
  - Breached essays list
  - AI recommendation

**Impact**: Implementation adds status display column not in design

**Found in**:
- Design: `dashboard_overview.md` - Section 4.3.2, "Subsection: Oil Evidence"
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 4.3.3

---

### 2.11 GPS Map Style

**Location**: Detail Tab - Telemetry Evidence

**Design Specification**:
- Map Style: Satellite view
- No specific Mapbox style mentioned

**Actual Implementation**:
- Map Style: "satellite-streets" (Mapbox style)
- Specific style name hard-coded

**Impact**: Minor; implementation specifies exact Mapbox style

**Found in**:
- Design: `dashboard_overview.md` - Section 4.3.2, Column 2
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 7.1.6

---

### 2.12 GPS Map Color Scheme

**Location**: Detail Tab - GPS Route Visualization

**Design Specification**:
- Point Color: Time-based gradient using `colorscale='Aggrnyl'`
- Specific color scale name

**Actual Implementation**:
- Point Color: Time-based gradient using `colorscale='Reds'`
- Different color scale

**Impact**: Different color scheme; visual difference

**Found in**:
- Design: `dashboard_overview.md` - Section 4.3.2, Column 2
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 7.1.6

---

## 3. Functionality Differences - ✅ RESOLVED

**Status**: Design documentation updated to match implementation (February 17, 2026)

### 3.1 Interactive Chart Filtering (Not in Design)

**Location**: General Tab - Chart Interactions

**Design Specification**:
- No mention of chart interactivity
- Charts described as display-only

**Actual Implementation**:
- All 4 charts in General tab are interactive
- Click-to-filter functionality
- Toggle behavior (click again to clear)
- Filter store (`alerts-filter-store`) manages state
- Callback: `update_filters_from_clicks()`

**Impact**: Major feature addition; significantly enhances interactivity

**Found in**:
- Design: `dashboard_overview.md` - Section 3 (not mentioned)
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 5.2

---

### 3.2 Time Window Configuration

**Location**: Detail Tab - Telemetry Evidence

**Design Specification**:
- M1 (Before): 90 minutes
- M2 (After): 10 minutes
- Described as "configurable in settings"

**Actual Implementation**:
- M1 (Before): 60 minutes (hard-coded constant)
- M2 (After): 10 minutes (hard-coded constant)
- Constants defined in `alerts_callbacks.py`
- Not configurable through settings

**Impact**: Different time window; shorter before-alert period

**Found in**:
- Design: `dashboard_overview.md` - Section 4.3.2, Column 1
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 8.1

---

### 3.3 Dropdown Options Sorting

**Location**: Alert Selector Dropdowns

**Design Specification**:
- Not specified

**Actual Implementation**:
- Sorted by timestamp descending (newest first)
- Format: `{FusionID} | {Timestamp} | {UnitId} | {componente}`
- Consistent across both General and Detail tabs

**Impact**: Implementation adds sorting logic not specified in design

**Found in**:
- Design: Not mentioned
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 5.4

---

### 3.4 Filter Preservation in Detail View

**Location**: Detail Tab - Alert Selection

**Design Specification**:
- Not specified

**Actual Implementation**:
- `filter_alert_dropdown_by_criteria()` preserves current selection
- If current alert still in filtered list, keeps it selected
- State parameter: `current_value`

**Impact**: Smart filtering behavior not in design

**Found in**:
- Design: Not specified
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 5.4.3

---

### 3.5 Table Interaction Features

**Location**: General Tab - Alerts Table

**Design Specification**:
- Clickable rows
- Redirect to Detail tab

**Actual Implementation**:
- Clickable rows (active cell detection)
- Native filtering
- Native sorting (multi-column)
- Pagination (20 rows per page)
- Hover and active styling

**Impact**: Implementation adds filtering, sorting, pagination not in design

**Found in**:
- Design: `dashboard_overview.md` - Section 3.2
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 7.2.1

---

### 3.6 AI Message Handling

**Location**: General Tab - Alerts Table

**Design Specification**:
- Display `mensaje_ia` (truncated for display)
- No specific truncation length mentioned

**Actual Implementation**:
- Truncation: First 80 characters + "..."
- Column: `mensaje_ia_short`
- Full message shown in Detail view

**Impact**: Implementation specifies exact truncation length

**Found in**:
- Design: `dashboard_overview.md` - Section 3.2
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 7.2.1

---

## 4. Navigation Differences - ✅ RESOLVED

**Status**: Design documentation updated to match implementation (February 17, 2026)

### 4.1 Navigation Methods

**Location**: General to Detail Navigation

**Design Specification**:
- Only one method: Table row click
- State management: Selected `FusionID` stored in callback state

**Actual Implementation**:
- Two methods:
  1. Table row click (direct)
  2. Button navigation (via dropdown selection)
- Store-based pattern using `alerts-navigation-state`

**Impact**: Implementation adds button navigation not in design

**Found in**:
- Design: `dashboard_overview.md` - Section 6
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 5.5, 5.6

---

### 4.2 Navigation Store Pattern

**Location**: Cross-Tab Navigation Architecture

**Design Specification**:
- State management: "callback state"
- No store mentioned

**Actual Implementation**:
- Store-based intermediary pattern
- Store: `alerts-navigation-state` (memory)
- Structure: `{'target_tab': str, 'alert_id': str}`
- Three-step callback chain:
  1. Button → Store
  2. Store → Tab switch
  3. Tab + Store → Dropdown

**Impact**: Different architectural approach; more complex but more reliable

**Found in**:
- Design: `dashboard_overview.md` - Section 6
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 5.5, Section 6.2

---

### 4.3 Row Click Navigation Logic

**Location**: Table Interaction

**Design Specification**:
- Captures `FusionID` of selected alert
- Navigates to Detail tab

**Actual Implementation**:
- Uses `active_cell` and `derived_virtual_data`
- Handles pagination and filtering
- Simultaneously sets tab value AND dropdown value
- Two outputs in one callback

**Impact**: More sophisticated handling of pagination/filtering

**Found in**:
- Design: `dashboard_overview.md` - Section 6
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 5.6

---

## 5. Data Processing Differences

### 5.1 Sensor Selection Logic

**Location**: Detail Tab - Telemetry Evidence

**Design Specification**:
- Variables: "Sensors related to `Component` or `System` of alert"
- No specific logic described

**Actual Implementation**:
- Two-path logic:
  - **Primary Path**: Use component mapping
    1. Get `Trigger` from telemetry alerts metadata
    2. Lookup in component mapping
    3. Display `PrimaryFeature` + `RelatedFeatures`
  - **Fallback Path**: First 3 non-metadata columns
- Excludes: 'Fecha', 'Unit', 'Estado', 'EstadoCarga', GPS columns

**Impact**: Implementation has detailed selection algorithm not in design

**Found in**:
- Design: `dashboard_overview.md` - Section 4.3.2, Column 1
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 8.2

---

### 5.2 Oil Essay Column Detection

**Location**: Detail Tab - Oil Evidence

**Design Specification**:
- Not specified

**Actual Implementation**:
- Identifies by suffix: columns ending with `_ppm`
- Excludes metadata columns
- Code: `essay_cols = [col for col in oil_report.index if col.endswith('_ppm')]`

**Impact**: Implementation adds specific detection logic

**Found in**:
- Design: Not specified
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 8.3

---

### 5.3 Trigger Type Normalization

**Location**: Detail View Logic

**Design Specification**:
- Not specified

**Actual Implementation**:
- Case-insensitive comparison
- Logic converts to lowercase for checking
- Code: `trigger_lower = str(trigger_type).lower()`
- Checks for substrings: 'telemetria', 'tribologia', 'oil', 'mixto'

**Impact**: Implementation adds case handling not in design

**Found in**:
- Design: Not specified
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 8.4

---

## 6. Additional Implementation Features Not in Design

### 6.1 Client Restriction Enforcement

**Location**: All Data Loaders

**Design Specification**:
- Data contracts mention CDA client
- No enforcement mechanism described

**Actual Implementation**:
- Hard-coded checks in all loaders: `if client.lower() != 'cda': return pd.DataFrame()`
- UI displays info alert about CDA-only availability
- Prevents data loading for other clients

**Impact**: Strong enforcement not specified in design

**Found in**:
- Design: `data_contracts.md` - Mentions CDA but no enforcement
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 1, Section 9.1

---

### 6.2 Loading States and Spinners

**Location**: All Dynamic Content Components

**Design Specification**:
- Not mentioned

**Actual Implementation**:
- Loading indicators on all charts and data components
- `dcc.Loading` components with "circle" type
- IDs: `loading-unit-chart`, `loading-sensor-trends`, etc.

**Impact**: UX enhancement not in design

**Found in**:
- Design: Not mentioned
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 4.2, 4.3

---

### 6.3 Error Handling and Empty States

**Location**: All Chart and Display Components

**Design Specification**:
- Missing data handling: Display warning message
- Format: "⚠️ No hay evidencia de {source} disponible para esta alerta"

**Actual Implementation**:
- Comprehensive error handling in all chart functions
- Empty DataFrame checks
- Error annotations in charts
- Alert components for missing data
- Placeholder when no alert selected

**Impact**: More robust error handling than design specifies

**Found in**:
- Design: `dashboard_overview.md` - Section 4.3.2
- Implementation: `alerts_dashboard_implementation_notes.md` - Multiple sections (7.1, 7.2)

---

### 6.4 Logging Implementation

**Location**: Throughout Callbacks and Loaders

**Design Specification**:
- Not mentioned

**Actual Implementation**:
- Extensive logging using `get_logger(__name__)`
- Log levels: info, warning, error
- Logs: data loading, filtering, navigation, errors
- Examples: "[NAV] BUTTON CALLBACK TRIGGERED!", "[ROW-NAV] Row clicked!"

**Impact**: Debugging/monitoring capability not in design

**Found in**:
- Design: Not mentioned
- Implementation: `alerts_dashboard_implementation_notes.md` - Throughout all sections

---

### 6.5 DataTable Styling

**Location**: General Tab - Alerts Table

**Design Specification**:
- Not specified

**Actual Implementation**:
- Custom styling:
  - Header: Dark background (#2c3e50), white text
  - Odd rows: Light gray (#f8f9fa)
  - Active row: Blue (#3498db), white text, 2px border
  - Row hover effects
- Cell height and text wrapping

**Impact**: Detailed styling not in design

**Found in**:
- Design: Not mentioned
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 7.2.1

---

### 6.6 Mapbox Token Configuration

**Location**: GPS Map Display

**Design Specification**:
- Not mentioned

**Actual Implementation**:
- Requires `MAPBOX_TOKEN` from settings
- Configuration: `settings.mapbox_token`
- Internet connection required

**Impact**: External dependency not in design

**Found in**:
- Design: Not mentioned
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 9.8

---

## 7. Missing Design Features (Not Implemented)

### 7.1 Correlation Alerts

**Location**: Data Contracts - Trigger_type

**Design Specification**:
- Future feature: Correlation alerts
- Trigger_type = 'correlation'
- Both TelemetryID and TribologyID set
- Enhanced AI diagnosis combining contexts

**Actual Implementation**:
- 'Mixto' type exists but not explicitly documented as correlation
- No special logic for combined diagnosis mentioned

**Impact**: Future feature may be partially implemented but not fully realized

**Found in**:
- Design: `data_contracts.md` - Section 4.2 (Fusion Rules)
- Implementation: Not mentioned in `alerts_dashboard_implementation_notes.md`

---

### 7.2 Configurable Time Windows

**Location**: Settings Configuration

**Design Specification**:
- M1 and M2 described as "configurable in settings"
- Implies user or admin can adjust

**Actual Implementation**:
- Hard-coded constants
- No configuration interface
- Not exposed in settings

**Impact**: Configurability not implemented

**Found in**:
- Design: `dashboard_overview.md` - Section 4.3.2
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 9.2

---

### 7.3 Helper Function References

**Location**: Chart Implementation

**Design Specification**:
- References to helper functions in `visualizations.py`:
  - `create_timeseries_chart()`
  - `create_gps_map()`
  - `create_kpi_card()`
  - `create_radar_chart()` (implied by oil dashboard reuse)

**Actual Implementation**:
- Functions exist in `alerts_charts.py` and `alerts_tables.py`
- Different file structure
- Function names slightly different:
  - `create_sensor_trends_chart()`
  - `create_gps_route_map()`
  - `create_context_kpis_cards()`
  - `create_oil_radar_chart()`

**Impact**: Different module organization; functions exist but in different locations with different names

**Found in**:
- Design: `dashboard_overview.md` - Multiple "Implementation Note" sections
- Implementation: `alerts_dashboard_implementation_notes.md` - Section 2, Section 7

---

## Summary Table

| Category | Differences Found | Critical | Major | Minor |
|----------|-------------------|----------|-------|-------|
| Data Schema | 7 | 2 | 3 | 2 |
| UI Structure | 12 | 0 | 6 | 6 |
| Functionality | 6 | 0 | 2 | 4 |
| Navigation | 3 | 0 | 1 | 2 |
| Data Processing | 3 | 0 | 1 | 2 |
| Additional Features | 6 | 0 | 0 | 6 |
| Missing Features | 3 | 0 | 1 | 2 |
| **Total** | **40** | **2** | **14** | **24** |

### Severity Definitions:
- **Critical**: Data schema mismatches that could cause integration issues
- **Major**: Functional or structural differences that significantly change user experience
- **Minor**: Implementation details, enhancements, or styling differences

---

## Recommendations

### High Priority (Critical + Major):

1. **Standardize Trigger_type values**: Align design and implementation on casing and value set
2. **Document column name changes**: Update design docs to reflect `OilReportNumber` and lowercase sistema/subsistema/componente
3. **Clarify interactive filtering**: Update design to document implemented click-to-filter feature
4. **Document navigation enhancements**: Add button navigation to design specifications
5. **Specify time window values**: Update design with actual M1=60 (not 90)
6. **Document additional UI sections**: Update layout diagrams for General tab structure

### Medium Priority:

7. Update design color schemes (GPS map uses 'Reds' not 'Aggrnyl')
8. Document filter functionality in Detail view
9. Document System Distribution chart addition
10. Clarify Mixto vs correlation alert relationship

### Low Priority:

11. Document styling specifications
12. Document logging implementation patterns
13. Update helper function references to actual file structure
14. Document client restriction enforcement

---

**End of Gap Analysis**
