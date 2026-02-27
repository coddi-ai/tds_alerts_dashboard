# Telemetry Dashboard Restructuring Summary

**Date**: February 26, 2026  
**Purpose**: Improve telemetry dashboard aesthetics and usability by consolidating tabs

---

## Overview of Changes

The telemetry dashboard has been restructured to match the aesthetics of other tabs (alerts, machines) and improve user experience by consolidating related functionality.

### Key Changes

1. **Reduced from 4 tabs to 2 tabs**:
   - ✅ **Fleet Overview** (includes Machine Detail at bottom)
   - ✅ **Component Detail** (includes Daily Timeseries and Limits at bottom)
   - ❌ ~~Machine Detail~~ (moved to Fleet Overview bottom section)
   - ❌ ~~Limits~~ (moved to Component Detail bottom section)

2. **Improved aesthetics**:
   - Added dbc.Card components with headers and icons (matching alerts tabs)
   - Better visual hierarchy with proper spacing and dividers
   - Consistent use of Font Awesome icons
   - Bootstrap badge styling for status indicators

3. **Enhanced functionality**:
   - Default component selection (highest score component auto-selected)
   - Daily timeseries chart added to Component Detail
   - Limits section filtered by selected component
   - Machine selector dropdown in Fleet Overview

---

## Files Modified

### 1. `dashboard/tabs/tab_telemetry.py`
**Changes**:
- Removed imports for `tab_telemetry_machine` and `tab_telemetry_limits`
- Updated internal tabs from 4 to 2 (Fleet Overview, Component Detail)
- Updated docstring to reflect new structure

**Lines changed**: ~30 lines

---

### 2. `dashboard/tabs/tab_telemetry_fleet.py`
**Changes**:
- Added dbc.Card wrappers around all sections with headers/icons
- Restructured layout to have Table (8 cols) + Pie Chart (4 cols)
- Added horizontal divider (`html.Hr`)
- Added Machine Detail section at bottom:
  - Machine selector dropdown
  - Machine header card (with status badge, scores, component counts)
  - Component table (7 cols) + Radar chart (5 cols)
- Moved `create_machine_header_card` function from `tab_telemetry_machine.py`

**New IDs**:
- `telemetry-machine-selector` - Dropdown for machine selection
- `telemetry-machine-header` - Machine summary card
- `telemetry-machine-component-table` - Component status table
- `telemetry-machine-component-radar` - Component radar chart

**Lines changed**: ~168 lines (complete restructure)

---

### 3. `dashboard/tabs/tab_telemetry_component.py`
**Changes**:
- Added dbc.Card wrappers around all sections
- Added Daily Time Series section (NEW):
  - Card with header/icon
  - Graph component: `telemetry-daily-timeseries`
  - Loads 4 weeks of data showing day-by-day evolution
- Added Baseline Limits section at bottom (NEW):
  - Horizontal divider
  - Section header with icon
  - Limits info card: `telemetry-component-limits-info-card`
  - Thresholds table: `telemetry-component-baseline-table`
  - Filtered by selected component and estado
- Updated page sizes for tables (12 for signals, 20 for limits)
- Improved component header card with better layout

**New IDs**:
- `telemetry-daily-timeseries` - Daily time series graph
- `telemetry-component-limits-info-card` - Baseline metadata card
- `telemetry-component-baseline-table` - Component thresholds table

**Lines changed**: ~242 lines (complete restructure)

---

### 4. `dashboard/callbacks/telemetry_callbacks.py`
**Major restructure** - complete rewrite with new callback structure.

**Removed callbacks**:
- `update_machine_detail` (old version)
- `update_limits_unit_filter_options`
- `update_limits_tab`

**Modified callbacks**:

#### `render_telemetry_tab_content`
- Now only handles 'fleet' and 'component' tabs
- Removed 'machine' and 'limits' routing

#### `update_fleet_overview`
- **New output**: `telemetry-machine-selector` options
- Returns 4 values instead of 3
- Auto-generates machine selector options

#### `update_machine_detail` (NEW - in Fleet tab)
- Triggered by `telemetry-machine-selector` dropdown
- Returns machine header card, component table, and radar chart
- Uses `create_machine_header_card` from `tab_telemetry_fleet.py`

#### `update_component_selector`
- **New output**: `value` (default selection)
- Auto-selects highest score component
- Returns tuple of (options, disabled, default_value)

#### `update_component_detail` (EXPANDED)
- **New inputs**: 
  - `telemetry-signal-evaluation-table.selected_rows` (for timeseries)
  - `telemetry-signal-evaluation-table.data` (State)
- **New outputs**:
  - `telemetry-daily-timeseries` (figure)
  - `telemetry-component-limits-info-card` (children)
  - `telemetry-component-baseline-table` (data)
- Now builds daily timeseries for selected signal (or default to highest score)
- Filters baseline limits by component signals and estado
- Returns 6 values instead of 3

**Lines changed**: ~618 lines (complete rewrite)

---

## New Component Integration

### Daily Timeseries Chart
- **Function**: `build_daily_timeseries()` (already existed in `telemetry_charts.py`)
- **Data source**: Silver layer (4 weeks)
- **Features**:
  - Vertical boxplots by date (MM/DD format)
  - P5-P95 baseline band (light green)
  - P2/P98 extreme bounds (dashed red lines)
  - Violin plots for distribution visualization
  - Current week color-coded by evaluation status

### Limits Integration
- **Function**: `create_baseline_info_card()` (from `tab_telemetry_limits.py`)
- **Function**: `build_baseline_thresholds_table()` (already existed)
- **Features**:
  - Filtered by selected unit and component signals
  - Respects estado filter (Operacional, Ralenti, Apagada, All)
  - Shows P2/P5/P95/P98 percentiles
  - Metadata card with signal/estado counts

---

## Testing Checklist

### Fleet Overview Tab
- [ ] KPI cards display correctly (Total, Normal, Alerta, Anormal)
- [ ] Fleet status table loads with sorting/filtering
- [ ] Pie chart shows status distribution
- [ ] Machine selector dropdown populates with units sorted by priority
- [ ] Selecting a machine displays:
  - [ ] Machine header card with correct status badge
  - [ ] Component table with A/L/N counts
  - [ ] Radar chart with component scores

### Component Detail Tab
- [ ] Unit selector populates correctly
- [ ] Component selector populates when unit selected
- [ ] **Default component is auto-selected (highest score)**
- [ ] Component header card displays correctly
- [ ] Signal evaluation table loads with status colors
- [ ] Weekly boxplots display with P5-P95 bands
- [ ] **Daily timeseries displays for default signal**
- [ ] **Selecting a signal in table updates timeseries**
- [ ] Estado filter affects boxplots and timeseries
- [ ] **Limits section displays at bottom**:
  - [ ] Info card shows correct metadata
  - [ ] Thresholds table filtered by component signals
  - [ ] Estado filter affects limits table

### Edge Cases
- [ ] Empty data handling (no machines, no components, no signals)
- [ ] Missing baseline data
- [ ] Missing silver layer weeks
- [ ] Estado filter with no matching data

---

## Known Issues & Future Enhancements

### Current Limitations
1. **Baseline filename**: Hardcoded to "baseline_latest.parquet" (should extract from loader)
2. **Signal selection**: Daily timeseries defaults to highest score if no row selected
3. **Estado filter**: Not persisted across tab switches

### Future Enhancements
1. **Cross-navigation**: Link from Alerts Detail to Component Detail (unit + component parameters)
2. **Signal drill-down modal**: Detailed analysis with multiple visualizations
3. **Export functionality**: Download limits as CSV
4. **Performance**: Lazy loading for large datasets
5. **Caching**: Store silver layer data to avoid re-loading

---

## Rollback Instructions

If issues occur, the old callbacks file is backed up as:
```
dashboard/callbacks/telemetry_callbacks_old.py
```

To rollback:
```powershell
Move-Item -Path "dashboard/callbacks/telemetry_callbacks_old.py" -Destination "dashboard/callbacks/telemetry_callbacks.py" -Force
```

And restore old tab files from git history:
```bash
git checkout HEAD -- dashboard/tabs/tab_telemetry.py
git checkout HEAD -- dashboard/tabs/tab_telemetry_fleet.py
git checkout HEAD -- dashboard/tabs/tab_telemetry_component.py
```

---

## Screenshots/Examples

### Before (4 tabs)
```
[Fleet Overview] [Machine Detail] [Component Detail] [Limits]
```

### After (2 tabs)
```
[Fleet Overview]                    [Component Detail]
  ├─ KPIs                             ├─ Selectors (Unit, Component, Estado)
  ├─ Table + Pie Chart                ├─ Component Header
  └─ Machine Detail (bottom)          ├─ Signal Evaluation Table
      ├─ Machine Selector             ├─ Weekly Boxplots
      ├─ Machine Header               ├─ Daily Timeseries (NEW)
      ├─ Component Table              └─ Baseline Limits (NEW)
      └─ Radar Chart                      ├─ Info Card
                                          └─ Thresholds Table
```

---

## Summary

✅ **All changes completed successfully**  
✅ **No linting errors**  
✅ **Aesthetics now match alerts tabs**  
✅ **User experience improved with consolidation**  
✅ **Default component selection added**  
✅ **Daily timeseries integrated**  
✅ **Limits contextually displayed**

The restructured telemetry dashboard provides a more intuitive and visually consistent experience while reducing navigation complexity.
