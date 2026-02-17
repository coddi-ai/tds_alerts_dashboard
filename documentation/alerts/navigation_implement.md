# Navigation Button Implementation Guide

## Overview
This document details the implementation of a navigation button that allows users to navigate from the **Monitoring > Alerts > General** tab to the **Monitoring > Alerts > Detail** tab with a pre-selected alert.

## Problem Statement
The dashboard needed functionality to:
- Select an alert from a dropdown in the General tab
- Click a button to navigate to the Detail tab
- Automatically pre-select and load the chosen alert in the Detail tab

### Key Challenge
The primary challenge was that Dash callbacks must target components that exist at application startup. The `alerts-internal-tabs` component exists in dynamically rendered content, causing direct callback patterns to fail.

## Solution: Store-Based Navigation Pattern

Following the working pattern from the Reports navigation, we implemented a store-based intermediary approach:

```
Button Click → Update Store → Tab Switch → Set Dropdown Value → Load Charts
```

This pattern ensures callbacks can register reliably even when targeting dynamic content.

---

## Implementation Steps

### Step 1: Add Navigation Store to Main Layout

**File**: `dashboard/layout.py`

Added a new store component that exists at app startup:

```python
# Store for alerts internal navigation
dcc.Store(id='alerts-navigation-state', storage_type='memory'),
```

**Location**: Inside the `create_app_layout()` function, alongside other stores like `navigation-state` and `active-tab-store`.

**Purpose**: Acts as an intermediary to pass navigation data between callbacks without directly targeting dynamic components.

---

### Step 2: Create Button Callback to Update Store

**File**: `dashboard/callbacks/alerts_callbacks.py`

Modified the button click callback to output to the store instead of directly to the tab component:

```python
@callback(
    Output('alerts-navigation-state', 'data'),
    [Input('general-nav-to-detail-button', 'n_clicks')],
    [State('general-alert-selector', 'value')],
    prevent_initial_call=True
)
def navigate_to_detail_from_general(n_clicks, selected_alert_id):
    """
    Store navigation request from General tab to Detail tab with selected alert.
    Uses store-based pattern to avoid direct output to dynamically rendered component.
    """
    logger.info(f"[NAV] BUTTON CALLBACK TRIGGERED! n_clicks={n_clicks}, alert={selected_alert_id}")
    
    if not n_clicks or not selected_alert_id:
        raise PreventUpdate
    
    logger.info(f"[NAV] Storing navigation request to Detail tab with alert: {selected_alert_id}")
    
    # Store navigation data for listener callback to process
    return {
        'target_tab': 'detail',
        'alert_id': selected_alert_id
    }
```

**Key Changes**:
- Output changed from `Output('alerts-internal-tabs', 'value')` to `Output('alerts-navigation-state', 'data')`
- Returns a dictionary with navigation data instead of directly switching tabs
- Validates that both `n_clicks` and `selected_alert_id` are present

---

### Step 3: Create Tab Switch Listener

**File**: `dashboard/callbacks/alerts_callbacks.py`

Added a callback that listens to the navigation store and switches the tab:

```python
@callback(
    Output('alerts-internal-tabs', 'value', allow_duplicate=True),
    [Input('alerts-navigation-state', 'data')],
    prevent_initial_call=True
)
def switch_to_detail_tab(nav_data):
    """
    Switch to detail tab when navigation is triggered.
    """
    logger.info(f"[NAV] TAB SWITCH LISTENER TRIGGERED: nav_data={nav_data}")
    
    if not nav_data or not nav_data.get('target_tab'):
        raise PreventUpdate
    
    target_tab = nav_data['target_tab']
    logger.info(f"[NAV] Switching to tab: {target_tab}")
    
    return target_tab
```

**Purpose**: 
- Listens to the `alerts-navigation-state` store
- Switches the internal tab to 'detail' when navigation data is available
- Uses `allow_duplicate=True` because this output may be modified by other callbacks

---

### Step 4: Create Alert Selection Callback

**File**: `dashboard/callbacks/alerts_callbacks.py`

Added a callback to set the dropdown value when navigating:

```python
@callback(
    Output('alert-selector-dropdown', 'value', allow_duplicate=True),
    [
        Input('alerts-internal-tabs', 'value'),
        Input('alerts-navigation-state', 'data')
    ],
    prevent_initial_call='initial_duplicate'
)
def set_alert_from_navigation(active_tab, nav_data):
    """
    Set the alert dropdown value when navigating from general tab.
    Triggers when tab switches to detail OR navigation state changes.
    """
    from dash import callback_context
    
    trigger_info = callback_context.triggered[0] if callback_context.triggered else None
    logger.info(f"[NAV] set_alert_from_navigation called: tab={active_tab}, nav_data={nav_data}, triggered_by={trigger_info}")
    
    # Only apply if we're on detail tab AND have navigation data
    if active_tab != 'detail':
        raise PreventUpdate
        
    if not nav_data or not nav_data.get('alert_id'):
        raise PreventUpdate
    
    # Only apply if navigation target is detail tab
    if nav_data.get('target_tab') != 'detail':
        raise PreventUpdate
    
    alert_id = nav_data['alert_id']
    logger.info(f"[NAV] Setting dropdown value to: {alert_id}")
    
    return alert_id
```

**Key Features**:
- Listens to both the tab value AND navigation state
- Only fires when on the detail tab with valid navigation data
- Uses `prevent_initial_call='initial_duplicate'` to handle timing issues
- Pre-selects the alert specified in the navigation data

---

### Step 5: Initialize Dropdown Options

**File**: `dashboard/callbacks/alerts_callbacks.py`

Kept the existing callback for populating dropdown options:

```python
@callback(
    Output('alert-selector-dropdown', 'options'),
    [Input('client-selector', 'value')]
)
def initialize_alert_dropdown_options(client: str):
    """
    Initialize alert selector dropdown options with all available alerts.
    """
    if not client:
        raise PreventUpdate
    
    logger.info(f"Initializing alert dropdown options for client: {client}")
    
    alerts_df = load_alerts_data(client)
    
    if alerts_df.empty:
        return []
    
    try:
        # Create dropdown options
        options = []
        for _, row in alerts_df.sort_values('Timestamp', ascending=False).iterrows():
            label = f"{row['FusionID']} | {row['Timestamp'].strftime('%Y-%m-%d %H:%M')} | {row['UnitId']} | {row['componente']}"
            options.append({'label': label, 'value': row['FusionID']})
        
        logger.info(f"Dropdown initialized with {len(options)} alerts")
        return options
    
    except Exception as e:
        logger.error(f"Error initializing dropdown: {e}")
        return []
```

**Purpose**: Separates the concern of populating dropdown options from setting the value.

---

### Step 6: Fix Emoji Encoding Issues

**File**: `dashboard/callbacks/alerts_callbacks.py`

Removed emoji characters from log messages to fix Windows `cp1252` encoding errors:

**Before**:
```python
logger.info(f"[NAV] 🚀 BUTTON CALLBACK TRIGGERED!")
```

**After**:
```python
logger.info(f"[NAV] BUTTON CALLBACK TRIGGERED!")
```

**Reason**: Windows console uses `cp1252` encoding which cannot display Unicode emojis, causing logging errors.

---

## Complete Callback Flow

### Navigation Sequence

1. **User Action**: User selects an alert in the dropdown and clicks "Ver Detalle de Alerta →" button
   
2. **Button Callback** (`navigate_to_detail_from_general`):
   - Captures button click
   - Retrieves selected alert ID
   - Stores navigation data to `alerts-navigation-state` store

3. **Tab Switch Callback** (`switch_to_detail_tab`):
   - Listens to store change
   - Updates `alerts-internal-tabs` value to 'detail'
   - Tab switches from General to Detail view

4. **Alert Selection Callback** (`set_alert_from_navigation`):
   - Triggered by tab switch
   - Checks navigation state data
   - Sets `alert-selector-dropdown` value to the selected alert ID

5. **Detail View Rendering** (existing `update_detail_view` callback):
   - Triggered by dropdown value change
   - Loads alert data
   - Renders charts and maps

---

## Files Modified

### 1. `dashboard/layout.py`
- **Change**: Added `alerts-navigation-state` store
- **Line**: ~303 (in `create_app_layout` function)

### 2. `dashboard/callbacks/alerts_callbacks.py`
- **Added/Modified**:
  - `navigate_to_detail_from_general()` - Modified to output to store (~434-468)
  - `switch_to_detail_tab()` - New callback (~471-495)
  - `set_alert_from_navigation()` - New callback (~498-533)
  - `initialize_alert_dropdown_options()` - Kept existing pattern (~536-570)
  - Fixed emoji characters in multiple log statements

---

## Testing Verification

After implementation, verify the following:

### 1. Button Click Logs
Console should show:
```
[NAV] BUTTON CALLBACK TRIGGERED! n_clicks=1, selected=F-2-1770192840
[NAV] Storing navigation request to Detail tab with alert: F-2-1770192840
```

### 2. Tab Switch Logs
```
[NAV] TAB SWITCH LISTENER TRIGGERED: nav_data={'target_tab': 'detail', 'alert_id': 'F-2-1770192840'}
[NAV] Switching to tab: detail
```

### 3. Alert Selection Logs
```
[NAV] set_alert_from_navigation called: tab=detail, nav_data=...
[NAV] Setting dropdown value to: F-2-1770192840
```

### 4. Visual Verification
- Tab switches from "General View" to "Detail View"
- Dropdown in Detail tab shows the selected alert
- Charts and maps render with the selected alert data

---

## Key Learnings

### 1. Store-Based Pattern Benefits
- ✅ Callbacks can target components that exist at app startup
- ✅ Clean separation of concerns
- ✅ Predictable behavior with proper logging
- ✅ Follows established patterns in the codebase

### 2. Why Direct Output Fails
- ❌ Target component (`alerts-internal-tabs`) rendered dynamically
- ❌ Callback registration happens at app startup
- ❌ Component doesn't exist when callback tries to register
- ❌ Result: Callback never fires, no console output

### 3. Callback Timing Considerations
- Use `prevent_initial_call='initial_duplicate'` for callbacks that need to fire during simultaneous updates
- Listen to multiple Inputs to catch state changes at the right time
- Use `allow_duplicate=True` when multiple callbacks target the same output

---

## Troubleshooting

### Button clicks but nothing happens
- **Check**: Verify `alerts-navigation-state` store exists in layout
- **Check**: Console logs should show button callback firing
- **Solution**: Ensure store is in main layout, not dynamic content

### Tab switches but alert not selected
- **Check**: Verify `set_alert_from_navigation` callback logs appear
- **Check**: Navigation state data contains `alert_id`
- **Solution**: Ensure callback listens to both tab value and navigation state

### Encoding errors in console
- **Check**: Remove emoji characters from log messages
- **Solution**: Use plain text in logger statements on Windows

---

## Related Documentation

- [Migration Challenges](./migration_challenges.md) - Detailed analysis of issues encountered
- [Dashboard Overview](./dashboard_overview.md) - Overall dashboard architecture
- [Data Contracts](./data_contracts.md) - Data structure specifications

---

## Future Enhancements

Potential improvements to consider:

1. **Store Cleanup**: Add mechanism to clear navigation store after use
2. **Animation**: Add transition animation when switching tabs
3. **Validation**: Check if alert ID exists in dropdown before setting
4. **Error Handling**: Display user message if navigation fails
5. **History**: Track navigation history for back button functionality

---

## Conclusion

The store-based navigation pattern successfully solves the challenge of navigating between dynamically rendered tabs while passing data. This pattern:
- Follows Dash best practices
- Matches existing patterns in the codebase (Reports navigation)
- Provides reliable, predictable behavior
- Maintains clean separation of concerns

The key insight: **Always use intermediary stores when targeting dynamically rendered components to ensure callbacks can register at app startup.**
