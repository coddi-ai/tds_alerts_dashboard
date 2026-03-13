# Alerts Dashboard - Implementation Side Notes

**Document Purpose**: Documents implementation-specific details, algorithms, and features that enhance the dashboard beyond the core design specifications.

**Related Documents**: 
- Core Design: `dashboard_overview.md`
- Implementation Details: `alerts_dashboard_implementation_notes.md`
- Remaining Gaps: `implementation_vs_design_gaps.md`
- Telemetry Golden Layer: `../telemetry/telemetry_golden_layer.md`

**Last Updated**: February 18, 2026

---

## 🎯 Major Refactoring - Telemetry Golden Layer (Feb 2026)

### Overview

The dashboard was refactored to use pre-processed telemetry data from the **golden layer** instead of loading and merging large silver layer files. This significantly improves performance and simplifies code.

### Key Changes

#### Before (Silver Layer Approach)
- **Data Load**: ~500MB silver layer files
- **Files Loaded**: `telemetry_values_wide.parquet`, `telemetry_states.parquet`, `limits_config.parquet`, `component_mapping.parquet`
- **Processing**: Complex filtering, merging, and component mapping logic
- **Code Complexity**: ~150 lines per chart
- **Performance**: Slow initial load, heavy memory usage

#### After (Golden Layer Approach)
- **Data Load**: ~2MB golden layer file
- **File Loaded**: `alerts_detail_wide_with_gps.csv`
- **Processing**: Simple filter by AlertID, drop NaN columns
- **Code Complexity**: ~50 lines per chart
- **Performance**: Fast load, minimal memory usage

### Reference Notebooks

Two notebooks demonstrate the comparison:
- `notebooks/old_telemetry_charts.ipynb`: OLD silver layer approach
- `notebooks/new_telemetry_charts.ipynb`: NEW golden layer approach

### Deprecated Functions

The following functions are now deprecated (marked in code but kept for reference):
- `create_sensor_trends_chart()` → Replaced by `create_sensor_trends_chart_golden()`
- `create_gps_route_map()` → Replaced by `create_gps_route_map_golden()`
- `create_context_kpis_cards()` → Replaced by `create_context_kpis_cards_golden()`

### Benefits

1. **Performance**: 10x faster data loading
2. **Simplicity**: 70% less code to maintain
3. **Scalability**: Can handle larger time windows without memory issues
4. **Maintainability**: No complex merging logic to debug
5. **Extensibility**: Adding new sensors requires no dashboard code changes

---

## 1. Data Processing Algorithms

### 1.1 Sensor Selection Logic

**Context**: Detail Tab - Telemetry Evidence Display

**Implementation Approach**: Two-path logic for determining which sensors to display

#### Primary Path: Component Mapping
1. Extract `Trigger` field from telemetry alerts metadata
2. Lookup trigger in component mapping dictionary
3. Display mapped sensors:
   - `PrimaryFeature`: Main sensor for the component
   - `RelatedFeatures`: Additional relevant sensors

#### Fallback Path: Auto-Detection
If component mapping is not available:
- Select first 3 non-metadata columns from telemetry data
- Exclude columns: 'Fecha', 'Unit', 'Estado', 'EstadoCarga', and all GPS columns

**Code Reference**: `alerts_dashboard_implementation_notes.md` - Section 8.2

---

### 1.2 Oil Essay Column Detection

**Context**: Detail Tab - Oil Evidence Radar Chart

**Implementation Approach**: Automatic essay column identification by naming convention

**Algorithm**:
```python
essay_cols = [col for col in oil_report.index if col.endswith('_ppm')]
```

**Logic**:
- Identifies all columns ending with `_ppm` suffix
- Automatically excludes metadata columns (they don't have this suffix)
- Dynamic detection allows for variable essay types without code changes

**Code Reference**: `alerts_dashboard_implementation_notes.md` - Section 8.3

---

### 1.3 Trigger Type Normalization

**Context**: Detail View Conditional Logic

**Implementation Approach**: Case-insensitive comparison for robust trigger type matching

**Algorithm**:
```python
trigger_lower = str(trigger_type).lower()
# Check for substrings: 'telemetria', 'tribologia', 'oil', 'mixto'
```

**Rationale**:
- Protects against data casing inconsistencies
- Allows flexible matching (e.g., "Telemetria", "telemetria", "TELEMETRIA")
- Handles both Spanish ('Tribologia') and English ('oil') variants

**Code Reference**: `alerts_dashboard_implementation_notes.md` - Section 8.4

---

## 2. Additional Implementation Features

### 2.1 Client Restriction Enforcement

**Context**: All Data Loaders

**Implementation**: Hard-coded CDA client restriction

**Mechanism**:
```python
if client.lower() != 'cda':
    return pd.DataFrame()
```

**User Experience**:
- UI displays info alert: "Dashboard only available for CDA client"
- Prevents data loading attempts for other clients
- Returns empty DataFrames to avoid errors

**Rationale**: Current data contracts and processing pipelines are CDA-specific

**Code Reference**: `alerts_dashboard_implementation_notes.md` - Section 1, Section 9.1

---

### 2.2 Loading States and Spinners

**Context**: All Dynamic Content Components

**Implementation**: Visual feedback during data loading operations

**Components**:
- `dcc.Loading` wrappers with "circle" type spinner
- Applied to all charts and dynamic data displays

**Component IDs**:
- `loading-unit-chart`
- `loading-sensor-trends`
- `loading-gps-map`
- `loading-oil-radar`
- And more...

**User Experience**:
- Prevents perception of "frozen" application
- Provides visual feedback during data fetching
- Improves perceived performance

**Code Reference**: `alerts_dashboard_implementation_notes.md` - Section 4.2, 4.3

---

### 2.3 Error Handling and Empty States

**Context**: All Chart and Display Components

**Implementation**: Comprehensive error handling strategy

**Empty State Handling**:
- Check for empty DataFrames before chart generation
- Display friendly alert messages: "⚠️ No hay evidencia de {source} disponible para esta alerta"
- Placeholder components when no alert is selected

**Error Annotation**:
- Charts display error annotations when data is missing or invalid
- Prevents application crashes from bad data

**Components**:
- Empty state checks in all chart creation functions
- Try-except blocks around data transformations
- Friendly error messages for users

**Examples**:
- No telemetry data: Info alert with message
- No oil report: Warning alert with explanation
- Invalid alert ID: Placeholder with selection prompt

**Code Reference**: `alerts_dashboard_implementation_notes.md` - Multiple sections (7.1, 7.2, 8.2, 8.3)

---

### 2.4 Logging Implementation

**Context**: Throughout Callbacks and Loaders

**Implementation**: Structured logging for debugging and monitoring

**Logger Setup**:
```python
logger = get_logger(__name__)
```

**Log Levels**:
- **INFO**: Data loading success, navigation events, filter changes
- **WARNING**: Missing data, fallback logic triggered, empty results
- **ERROR**: Data loading failures, processing errors, exceptions

**Example Log Messages**:
- `"[NAV] BUTTON CALLBACK TRIGGERED!"`
- `"[ROW-NAV] Row clicked!"`
- `"[FILTER] Filtering alerts based on user selections"`
- `"Loading alerts data for client: CDA"`

**Benefits**:
- Debugging callback execution flow
- Monitoring data loading performance
- Identifying production issues
- Understanding user interaction patterns

**Code Reference**: `alerts_dashboard_implementation_notes.md` - Throughout all sections

---

### 2.5 DataTable Styling

**Context**: General Tab - Alerts Table

**Implementation**: Custom CSS styling for enhanced readability

**Styling Specifications**:

#### Header Style
```python
'header': {
    'backgroundColor': '#2c3e50',
    'color': 'white',
    'fontWeight': 'bold'
}
```

#### Cell Styles
- **Odd rows**: Light gray background `#f8f9fa`
- **Active cell**: Blue background `#3498db`, white text, 2px border
- **Hover effect**: Visual feedback on row hover
- **Cell height**: Controlled for compact display
- **Text wrapping**: Enabled for long content

**User Experience**:
- Improved readability through alternating row colors
- Clear visual feedback for selected row
- Professional appearance
- Optimized for dense data display

**Code Reference**: `alerts_dashboard_implementation_notes.md` - Section 7.2.1

---

### 2.6 Mapbox Token Configuration

**Context**: GPS Map Display in Detail Tab

**Implementation**: External API token requirement

**Configuration**:
```python
mapbox_token = settings.mapbox_token
```

**Requirements**:
- Valid Mapbox access token
- Internet connection for map tile loading
- Token stored in settings/environment configuration

**Map Features Enabled**:
- Satellite-streets view
- Interactive zoom and pan
- Route visualization
- Location markers

**Fallback**: If token is invalid or missing, map component may not render properly

**Code Reference**: `alerts_dashboard_implementation_notes.md` - Section 9.8

---

## 3. Implementation Optimizations

### 3.1 Data Caching Strategy

**Context**: Expensive data operations

**Implementation**:
- Callback outputs cached where appropriate
- Prevents redundant data loading
- Improves dashboard responsiveness

### 3.2 Filter Store Pattern

**Context**: Interactive chart filtering

**Implementation**:
- Centralized filter state in `alerts-filter-store`
- All components read from single source of truth
- Toggle behavior implemented through state comparison
- Efficient updates without full data reload

### 3.3 Navigation Store Pattern

**Context**: Cross-tab navigation

**Implementation**:
- `alerts-navigation-state` store acts as intermediary
- Solves dynamic component targeting issues
- Three-callback chain ensures reliable navigation:
  1. Button click → Store update
  2. Store update → Tab change
  3. Store update → Alert selector update

**Rationale**: Direct targeting of dynamically rendered components is unreliable in Dash

---

## 4. Code Organization

### 4.1 File Structure

**Actual Implementation**:
- `alerts_charts.py`: Chart creation functions
- `alerts_tables.py`: Table and display components
- `alerts_callbacks.py`: All interaction logic (1344 lines)
- `tab_alerts_general.py`: General tab layout
- `tab_alerts_detail.py`: Detail tab layout

**Note**: Design referenced `visualizations.py` which doesn't exist in this structure

### 4.2 Function Naming Conventions

**Chart Functions**:
- `create_sensor_trends_chart()` - Time series plots
- `create_gps_route_map()` - GPS visualization
- `create_context_kpis_cards()` - KPI displays
- `create_oil_radar_chart()` - Polar/radar chart

**Table Functions**:
- `create_alerts_table()` - Main alerts table
- `create_summary_stats_display()` - KPI cards

**Callback Functions**:
- Prefixed with action: `update_`, `navigate_`, `filter_`, `set_`
- Descriptive names indicating purpose

---

## 5. Design Decisions Rationale

### 5.1 Why Two Navigation Methods?

**Problem**: Users need both quick (table row click) and explicit (button navigation) methods

**Solution**:
1. **Table Row Click**: Fast navigation for users familiar with data
2. **Navigation Card**: Explicit selection with preview, better for new users

**Benefit**: Accommodates different user preferences and skill levels

### 5.2 Why Store-Based Navigation?

**Problem**: Direct callback targeting of dynamically rendered components fails

**Solution**: Store acts as reliable intermediary that persists across tab switches

**Technical Detail**: When switching tabs, components re-render. Store ensures state is available when Detail tab mounts.

### 5.3 Why Toggle Filtering?

**Problem**: Users need to explore data, not just filter it

**Solution**: Click same element again to clear filter

**Benefit**: Intuitive interaction, reduces need for explicit "Clear Filter" button

### 5.4 Why 4 Sections in General Tab?

**Problem**: Users need overview metrics, analytics, data table, and navigation

**Solution**: Logical grouping by function:
1. Summary Stats: High-level metrics
2. Analytics: Visual patterns
3. Data + Distribution: Detailed list + system view
4. Navigation: Explicit action area

**Benefit**: Progressive disclosure of information, clear visual hierarchy

---

## 6. Performance Considerations

### 6.1 Time Window Limits

**M1 = 60 minutes** (Before alert)
- Balanced between context and data volume
- Typical operational patterns visible
- Manageable data loading time

**M2 = 10 minutes** (After alert)
- Captures immediate aftermath
- Minimal data overhead
- Quick loading

### 6.2 Table Pagination

**Implementation**: 20 rows per page
- Balance between overview and performance
- Fast rendering even with large datasets
- Native DataTable pagination prevents memory issues

### 6.3 Chart Rendering

**Strategy**: Load data once, filter in memory
- Initial load fetches all filtered data
- Chart interactions update without re-fetch
- Smooth user experience

---

## 7. Known Limitations

### 7.1 Client Restriction

**Current**: Only CDA client supported
**Reason**: Data contracts and processing pipelines are CDA-specific
**Future**: May extend to other clients with adapted data contracts

### 7.2 Mapbox Dependency

**Current**: Requires external API token and internet connection
**Impact**: GPS maps won't work in offline environments
**Alternative**: Could implement fallback with static plots

### 7.3 No Real-Time Updates

**Current**: Data is loaded on dashboard initialization
**Impact**: New alerts require manual refresh
**Future**: Could implement polling or WebSocket updates

---

**End of Side Notes**
