# Alerts Dashboard - Migration Complete

## Summary

Successfully migrated the alerts visualization from Jupyter notebook to the Dash dashboard (Phase 1, Step 1.3 of the migration plan).

## Implementation Details

### Files Created

1. **Data Loaders** (`src/data/loaders.py`)
   - `load_alerts_data()` - Load consolidated alerts with CDA client check
   - `load_telemetry_values()` - Load telemetry sensor data
   - `load_telemetry_states()` - Load operational states
   - `load_telemetry_limits()` - Load sensor limits configuration
   - `load_telemetry_alerts_metadata()` - Load alert trigger information
   - `load_component_mapping()` - Load sensor-to-component mapping
   - `load_feature_names()` - Load feature name translations
   - `load_oil_classified()` - Load classified oil reports
   - `load_maintenance_week()` - Load weekly maintenance data
   - ✅ All loaders include CDA-only client checks
   - ✅ All loaders include comprehensive logging

2. **Chart Components** (`dashboard/components/alerts_charts.py`)
   - `create_alerts_per_unit_chart()` - Horizontal bar chart for unit distribution
   - `create_alerts_per_month_chart()` - Vertical bar chart for month distribution
   - `create_trigger_distribution_treemap()` - Treemap for trigger sources
   - `create_sensor_trends_chart()` - Multi-panel time series with limits
   - `create_gps_route_map()` - GPS route visualization with alert marker
   - `create_oil_radar_chart()` - Radar chart for oil essay levels

3. **Table Components** (`dashboard/components/alerts_tables.py`)
   - `create_alerts_datatable()` - Interactive DataTable with sorting/filtering
   - `create_alert_detail_card()` - Alert specification display
   - `create_context_kpis_cards()` - Context KPI cards (elevation, payload, RPM)
   - `create_maintenance_display()` - Maintenance summary with task filtering

4. **Tab Layouts**
   - `dashboard/tabs/tab_alerts_general.py` - General analytics view
   - `dashboard/tabs/tab_alerts_detail.py` - Detailed alert view with conditional sections

5. **Callbacks** (`dashboard/callbacks/alerts_callbacks.py`)
   - `update_general_tab()` - Populate all general tab components
   - `update_alert_dropdown()` - Populate alert selector
   - `update_detail_view()` - Load detail view with conditional evidence
   - `create_telemetry_evidence_section()` - Build telemetry evidence dynamically
   - `create_oil_evidence_section()` - Build oil evidence dynamically
   - `create_maintenance_evidence_section()` - Build maintenance evidence

6. **Navigation Updates** (`dashboard/callbacks/navigation_callbacks.py`)
   - Updated to enforce CDA-only restriction for alerts subsystem
   - Integrated alerts tabs into navigation flow

## Key Features Implemented

### General Tab
✅ Distribution of Alerts per Unit (horizontal bar chart)
✅ Distribution of Alerts per Month (vertical bar chart)
✅ Distribution of Alert Trigger (treemap)
✅ Summary statistics (total alerts, units, telemetry %, tribology %)
✅ Interactive alerts table with sorting, filtering, and selection

### Detail Tab
✅ Alert specification card with full metadata
✅ **Conditional Telemetry Evidence** (if Trigger_type in ['Telemetria', 'Mixto']):
   - Sensor trends (multi-panel time series with state-based coloring)
   - Continuous limit lines that adjust based on operational state
   - GPS route map with alert location marker
   - Context KPIs (elevation status, payload, engine RPM)
✅ **Conditional Oil Evidence** (if Trigger_type in ['Tribologia', 'Mixto']):
   - Radar chart showing essay levels
   - Report status with breached essays
   - AI recommendation display
✅ **Maintenance Evidence** (always displayed if available):
   - Weekly maintenance summary
   - Tasks filtered by alert system

### Backend Infrastructure
✅ Multi-datasource integration (alerts + telemetry + oil + maintenance)
✅ Comprehensive logging at INFO and ERROR levels
✅ CDA-only client restriction with user-friendly messaging
✅ Graceful error handling for missing data files
✅ Time window calculation (M1=90 min before, M2=10 min after)
✅ Component-aware sensor selection using mapping files

## Configuration

### Time Windows
- **M1**: 90 minutes before alert
- **M2**: 10 minutes after alert

### Mapbox Token
- Token is configured in `alerts_callbacks.py` (line 30)
- Used for GPS satellite map visualization

### Client Restriction
- Alerts dashboard is **CDA-only**
- All data loaders check for client='cda' (case-insensitive)
- Navigation callback enforces this restriction
- Non-CDA clients see placeholder message

## Data Requirements

The dashboard expects the following data structure:

```
data/
├── alerts/golden/cda/
│   └── consolidated_alerts.csv
├── telemetry/
│   ├── silver/cda/
│   │   ├── telemetry_values_wide.parquet
│   │   ├── telemetry_states.parquet
│   │   └── limits_config.parquet
│   └── golden/cda/
│       ├── alerts_data.csv
│       ├── component_mapping.parquet
│       └── feature_names.csv
├── oil/golden/cda/
│   └── classified.parquet
└── mantentions/golden/cda/
    └── {week}.csv  (e.g., 01-2025.csv)
```

## Testing Instructions

### 1. Start the Dashboard

```powershell
cd c:\Users\patri\Coddi\Proyectos\alerts_dashboard_production
python dashboard/app.py
```

### 2. Access the Dashboard
- Open browser: `http://localhost:8050`
- Login with credentials from `config/users.py`

### 3. Navigate to Alerts
- Select **CDA** client from dropdown (if not already selected)
- Click **Monitoring > Alerts > General** in left navigation menu

### 4. Test General Tab
- Verify all 3 charts load correctly
- Check summary statistics display
- Verify alerts table is populated
- Test table sorting (click column headers)
- Test table filtering (type in column filters)
- Try selecting a row from the table

### 5. Test Detail Tab
- Navigate to **Monitoring > Alerts > Detail**
- Select an alert from the dropdown OR
- Go back to General tab and click a row (should navigate to Detail)
- **Verify Conditional Rendering**:
  - If alert has Telemetria/Mixto trigger → see telemetry evidence section
  - If alert has Tribologia/Mixto trigger → see oil evidence section
  - Check that maintenance section appears if data exists

### 6. Test CDA-Only Restriction
- Switch client to non-CDA (e.g., 'emin' if available)
- Navigate to Alerts tabs
- Should see placeholder: "Alertas (Solo disponible para CDA)"

### 7. Check Logging
- Monitor console output for INFO/ERROR messages
- Check `logs/dashboard.log` for detailed logging

## Expected Behavior

### Successful Load
- All charts render without errors
- Table displays 20 rows per page with pagination
- Detail view shows alert specification card
- Conditional sections appear/hide based on trigger type
- GPS map shows satellite imagery with route and alert marker
- Sensor trends show color-coded states (green=Operacional, orange=Ralenti, gray=ND)
- Limit lines adjust dynamically based on operational state

### Error Scenarios
- Missing data files → Warning alert with descriptive message
- Non-CDA client → Placeholder message
- No alert selected → Info message prompting selection
- Empty dataframes → "No data available" messages

## Architecture Highlights

### Multi-Source Data Flow
```
User selects alert → Callbacks triggered → Data loaders check CDA client
                                        ↓
                    Multiple data sources loaded in parallel:
                    - alerts_df (primary)
                    - telemetry_values (if needed)
                    - telemetry_states (if needed)
                    - oil_classified (if needed)
                    - maintenance_df (if needed)
                                        ↓
                    Evidence sections built conditionally
                                        ↓
                    Layout rendered with all visualizations
```

### Callback Pattern
- Uses `@callback` decorator for automatic registration
- All callbacks log operations for debugging
- State management via dropdown values and table selections
- Cross-tab communication via shared stores

## Next Steps (Phase 1.4)

- [ ] Integrate with authentication system
- [ ] Add export functionality for alerts table
- [ ] Implement alert annotation/notes feature
- [ ] Add filtering by date range in General tab
- [ ] Create alert comparison view (side-by-side)
- [ ] Add email notification integration

## Known Limitations

1. **Mapbox Token**: Hardcoded in callbacks file (consider environment variable)
2. **CDA-Only**: Currently restricted to single client (could be extended)
3. **Data Files**: Assumes specific file names and locations
4. **Component Mapping**: Generated in notebook, needs to be pre-computed
5. **Maintenance Week Format**: Expects format like "01-2025"

## Troubleshooting

### Issue: Charts not loading
- Check console for errors
- Verify data files exist in expected locations
- Confirm CDA client is selected
- Check `logs/dashboard.log` for detailed error messages

### Issue: GPS map not displaying
- Verify Mapbox token is valid
- Check that GPS columns exist in telemetry data
- Confirm GPS data exists in time window

### Issue: No telemetry evidence showing
- Verify Trigger_type is 'Telemetria' or 'Mixto'
- Check that TelemetryID field is populated
- Confirm telemetry files exist in silver/golden layers

### Issue: Sensor trends show wrong sensors
- Check component_mapping.parquet exists
- Verify Trigger field exists in telemetry alerts_data.csv
- Confirm feature names mapping is correct

## Migration Status

✅ **Phase 1.1**: Layout Proposal (Completed)
✅ **Phase 1.2**: Jupyter Notebook Prototyping (Completed)
✅ **Phase 1.3**: Dash Migration (Completed - Current)
⏳ **Phase 1.4**: Dashboard Integration (Next)

---

**Created**: 2025
**Author**: GitHub Copilot
**Framework**: Dash + Plotly + Pandas
**Python Version**: 3.x
