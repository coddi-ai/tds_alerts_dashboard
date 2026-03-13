"""
Telemetry callbacks for Multi-Technical Alerts Dashboard.

This module provides all interactive callbacks for telemetry tabs:
- Tab Switching: Handle internal tab navigation
- Fleet Overview: Load fleet data, update KPIs, table, and pie chart
- Machine Detail: Select machine, update components table and radar chart
- Component Detail: Select component, update signals table and boxplots
- Limits: Display baseline thresholds with filtering
"""

import pandas as pd
import json
from datetime import datetime, timedelta
from dash import callback, Input, Output, State, no_update, html
from dash.exceptions import PreventUpdate

from src.data.loaders import (
    load_telemetry_machine_status,
    load_telemetry_classified,
    load_telemetry_baselines,
    load_silver_telemetry_week
)
from dashboard.components.telemetry_charts import (
    build_fleet_kpi_cards,
    build_fleet_pie_chart,
    build_component_radar_chart,
    build_weekly_boxplots
)
from dashboard.components.telemetry_tables import (
    build_fleet_status_table,
    build_component_table,
    build_signal_evaluation_table,
    build_baseline_thresholds_table,
    parse_component_details,
    parse_signals_evaluation
)
from dashboard.tabs.tab_telemetry_fleet import create_telemetry_fleet_layout
from dashboard.tabs.tab_telemetry_machine import create_telemetry_machine_layout, create_machine_header_card
from dashboard.tabs.tab_telemetry_component import create_telemetry_component_layout, create_component_header_card
from dashboard.tabs.tab_telemetry_limits import create_telemetry_limits_layout, create_baseline_info_card
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ===================================================================
# TAB SWITCHING CALLBACK
# ===================================================================

@callback(
    Output('telemetry-tab-content', 'children'),
    Input('telemetry-tabs', 'value')
)
def render_telemetry_tab_content(active_tab):
    """
    Render the appropriate telemetry tab content based on selection.
    
    Args:
        active_tab: Selected tab value ('fleet', 'machine', 'component', 'limits')
    
    Returns:
        Tab content layout
    """
    if active_tab == 'fleet':
        return create_telemetry_fleet_layout()
    elif active_tab == 'machine':
        return create_telemetry_machine_layout()
    elif active_tab == 'component':
        return create_telemetry_component_layout()
    elif active_tab == 'limits':
        return create_telemetry_limits_layout()
    else:
        return html.Div("Invalid tab selection")


# ===================================================================
# FLEET OVERVIEW CALLBACKS
# ===================================================================

@callback(
    [
        Output("telemetry-fleet-kpi-cards", "figure"),
        Output("telemetry-fleet-status-table", "data"),
        Output("telemetry-fleet-status-pie", "figure"),
    ],
    Input("client-selector", "value")
)
def update_fleet_overview(client):
    """
    Update fleet overview tab with machine status data.
    
    Args:
        client: Selected client identifier
    
    Returns:
        Tuple of (KPI cards figure, table data, pie chart figure)
    """
    if not client:
        raise PreventUpdate
    
    try:
        # Load machine status data
        machine_df = load_telemetry_machine_status(client)
        
        if machine_df.empty:
            logger.warning(f"No telemetry machine status data for client {client}")
            return {}, [], {}
        
        # Filter to latest evaluation week
        latest_year = machine_df['evaluation_year'].max()
        latest_week = machine_df[machine_df['evaluation_year'] == latest_year]['evaluation_week'].max()
        
        machine_df_latest = machine_df[
            (machine_df['evaluation_year'] == latest_year) &
            (machine_df['evaluation_week'] == latest_week)
        ].copy()
        
        logger.info(f"Fleet Overview: Loaded {len(machine_df_latest)} machines for Week {latest_week:02d}/{latest_year}")
        
        # Build visualizations
        kpi_cards_fig = build_fleet_kpi_cards(machine_df_latest)
        fleet_table_df = build_fleet_status_table(machine_df_latest)
        pie_chart_fig = build_fleet_pie_chart(machine_df_latest)
        
        return kpi_cards_fig, fleet_table_df.to_dict('records'), pie_chart_fig
    
    except Exception as e:
        logger.error(f"Error updating fleet overview: {e}")
        return {}, [], {}


# ===================================================================
# MACHINE DETAIL CALLBACKS
# ===================================================================

@callback(
    Output("telemetry-machine-selector", "options"),
    Input("client-selector", "value")
)
def update_machine_selector_options(client):
    """
    Update machine selector dropdown with available units.
    
    Args:
        client: Selected client identifier
    
    Returns:
        List of dropdown options
    """
    if not client:
        raise PreventUpdate
    
    try:
        # Load machine status data
        machine_df = load_telemetry_machine_status(client)
        
        if machine_df.empty:
            return []
        
        # Filter to latest evaluation week
        latest_year = machine_df['evaluation_year'].max()
        latest_week = machine_df[machine_df['evaluation_year'] == latest_year]['evaluation_week'].max()
        
        machine_df_latest = machine_df[
            (machine_df['evaluation_year'] == latest_year) &
            (machine_df['evaluation_week'] == latest_week)
        ].copy()
        
        # Sort by priority score (highest first)
        machine_df_latest = machine_df_latest.sort_values('priority_score', ascending=False)
        
        # Create options with status badges
        options = [
            {
                'label': f"{row['unit_id']} - {row['overall_status']} (Score: {row['priority_score']:.2f})",
                'value': row['unit_id']
            }
            for _, row in machine_df_latest.iterrows()
        ]
        
        return options
    
    except Exception as e:
        logger.error(f"Error updating machine selector options: {e}")
        return []


@callback(
    [
        Output("telemetry-machine-header", "children"),
        Output("telemetry-component-status-table", "data"),
        Output("telemetry-component-radar-chart", "figure"),
    ],
    [
        Input("telemetry-machine-selector", "value"),
        Input("client-selector", "value")
    ]
)
def update_machine_detail(selected_unit, client):
    """
    Update machine detail tab when unit is selected.
    
    Args:
        selected_unit: Selected unit ID
        client: Selected client identifier
    
    Returns:
        Tuple of (header card, component table data, radar chart figure)
    """
    if not selected_unit or not client:
        raise PreventUpdate
    
    try:
        # Load machine status data
        machine_df = load_telemetry_machine_status(client)
        
        if machine_df.empty:
            return None, [], {}
        
        # Filter to latest evaluation week and selected unit
        latest_year = machine_df['evaluation_year'].max()
        latest_week = machine_df[machine_df['evaluation_year'] == latest_year]['evaluation_week'].max()
        
        machine_row = machine_df[
            (machine_df['unit_id'] == selected_unit) &
            (machine_df['evaluation_year'] == latest_year) &
            (machine_df['evaluation_week'] == latest_week)
        ]
        
        if machine_row.empty:
            logger.warning(f"No data for unit {selected_unit}")
            return None, [], {}
        
        machine_row = machine_row.iloc[0]
        
        # Parse component_details
        component_details = parse_component_details(machine_row['component_details'])
        
        # Build header card
        header_card = create_machine_header_card(
            unit_id=machine_row['unit_id'],
            overall_status=machine_row['overall_status'],
            priority_score=machine_row['priority_score'],
            machine_score=machine_row['machine_score'],
            evaluation_week=machine_row['evaluation_week'],
            evaluation_year=machine_row['evaluation_year']
        )
        
        # Build component table
        component_table_df = build_component_table(component_details)
        
        # Build radar chart
        radar_chart_fig = build_component_radar_chart(component_details)
        
        return header_card, component_table_df.to_dict('records'), radar_chart_fig
    
    except Exception as e:
        logger.error(f"Error updating machine detail: {e}")
        return None, [], {}


# ===================================================================
# COMPONENT DETAIL CALLBACKS
# ===================================================================

@callback(
    Output("telemetry-component-unit-selector", "options"),
    Input("client-selector", "value")
)
def update_component_unit_selector(client):
    """
    Update component detail unit selector dropdown.
    
    Args:
        client: Selected client identifier
    
    Returns:
        List of dropdown options
    """
    if not client:
        raise PreventUpdate
    
    try:
        # Load machine status data
        machine_df = load_telemetry_machine_status(client)
        
        if machine_df.empty:
            return []
        
        # Filter to latest evaluation week
        latest_year = machine_df['evaluation_year'].max()
        latest_week = machine_df[machine_df['evaluation_year'] == latest_year]['evaluation_week'].max()
        
        machine_df_latest = machine_df[
            (machine_df['evaluation_year'] == latest_year) &
            (machine_df['evaluation_week'] == latest_week)
        ].copy()
        
        # Sort by priority score
        machine_df_latest = machine_df_latest.sort_values('priority_score', ascending=False)
        
        options = [{'label': unit_id, 'value': unit_id} for unit_id in machine_df_latest['unit_id'].tolist()]
        
        return options
    
    except Exception as e:
        logger.error(f"Error updating component unit selector: {e}")
        return []


@callback(
    [
        Output("telemetry-component-selector", "options"),
        Output("telemetry-component-selector", "disabled"),
    ],
    [
        Input("telemetry-component-unit-selector", "value"),
        Input("client-selector", "value")
    ]
)
def update_component_selector(selected_unit, client):
    """
    Update component selector dropdown based on selected unit.
    
    Args:
        selected_unit: Selected unit ID
        client: Selected client identifier
    
    Returns:
        Tuple of (component options, disabled state)
    """
    if not selected_unit or not client:
        return [], True
    
    try:
        # Load machine status data
        machine_df = load_telemetry_machine_status(client)
        
        if machine_df.empty:
            return [], True
        
        # Filter to latest evaluation week and selected unit
        latest_year = machine_df['evaluation_year'].max()
        latest_week = machine_df[machine_df['evaluation_year'] == latest_year]['evaluation_week'].max()
        
        machine_row = machine_df[
            (machine_df['unit_id'] == selected_unit) &
            (machine_df['evaluation_year'] == latest_year) &
            (machine_df['evaluation_week'] == latest_week)
        ]
        
        if machine_row.empty:
            return [], True
        
        # Parse component_details
        component_details = parse_component_details(machine_row.iloc[0]['component_details'])
        
        if not component_details:
            return [], True
        
        # Create options sorted by score
        component_df = pd.DataFrame(component_details)
        if 'component_score' in component_df.columns:
            component_df = component_df.sort_values('component_score', ascending=False)
        
        options = [
            {
                'label': f"{row['component']} - {row.get('component_status', 'N/A')}",
                'value': row['component']
            }
            for _, row in component_df.iterrows()
        ]
        
        return options, False
    
    except Exception as e:
        logger.error(f"Error updating component selector: {e}")
        return [], True


@callback(
    [
        Output("telemetry-component-header", "children"),
        Output("telemetry-signal-evaluation-table", "data"),
        Output("telemetry-weekly-boxplots", "figure"),
    ],
    [
        Input("telemetry-component-selector", "value"),
        Input("telemetry-estado-filter", "value"),
        State("telemetry-component-unit-selector", "value"),
        State("client-selector", "value")
    ]
)
def update_component_detail(selected_component, estado_filter, selected_unit, client):
    """
    Update component detail tab when component is selected.
    
    Args:
        selected_component: Selected component name
        estado_filter: Machine state filter
        selected_unit: Selected unit ID
        client: Selected client identifier
    
    Returns:
        Tuple of (header card, signals table data, boxplots figure)
    """
    if not selected_component or not selected_unit or not client:
        raise PreventUpdate
    
    try:
        # Load classified data
        classified_df = load_telemetry_classified(client)
        
        if classified_df.empty:
            return None, [], {}
        
        # Filter for selected unit and component
        component_eval = classified_df[
            (classified_df['unit_id'] == selected_unit) &
            (classified_df['component'] == selected_component)
        ]
        
        if component_eval.empty:
            logger.warning(f"No evaluation found for {selected_unit} - {selected_component}")
            return None, [], {}
        
        # Get latest evaluation
        latest_eval = component_eval.sort_values(
            ['evaluation_year', 'evaluation_week'], ascending=False
        ).iloc[0]
        
        current_week = int(latest_eval['evaluation_week'])
        current_year = int(latest_eval['evaluation_year'])
        
        # Parse signals_evaluation
        signals_eval = parse_signals_evaluation(latest_eval['signals_evaluation'])
        
        if not signals_eval:
            logger.warning("No signal evaluations available")
            return None, [], {}
        
        # Build signals table
        signals_table_df = build_signal_evaluation_table(signals_eval)
        
        # Build header card
        header_card = create_component_header_card(
            unit_id=selected_unit,
            component=selected_component,
            component_status=latest_eval.get('component_status', 'Unknown'),
            component_score=latest_eval.get('component_score', 0.0),
            num_signals=len(signals_eval),
            coverage=latest_eval.get('coverage', 0.0)
        )
        
        # Load weekly data for boxplots (last 6 weeks)
        weeks_to_load = []
        temp_date = datetime.strptime(f'{current_year}-W{current_week:02d}-1', '%Y-W%W-%w')
        
        for i in range(6):
            target_date = temp_date - timedelta(weeks=i)
            week_num = int(target_date.strftime('%W'))
            year_num = target_date.year
            weeks_to_load.append((week_num, year_num))
        
        # Load silver data for all weeks
        all_weeks_data = []
        for week, year in weeks_to_load:
            week_df = load_silver_telemetry_week(client, week, year)
            if not week_df.empty:
                # Filter for selected unit
                week_df = week_df[week_df['Unit'] == selected_unit].copy()
                if not week_df.empty:
                    week_df['week_label'] = f'Week {week:02d}/{year}'
                    week_df['week_num'] = week
                    week_df['year'] = year
                    
                    # Apply estado filter if specified
                    if estado_filter and estado_filter != 'all' and 'EstadoMaquina' in week_df.columns:
                        week_df = week_df[week_df['EstadoMaquina'] == estado_filter]
                    
                    if not week_df.empty:
                        all_weeks_data.append(week_df)
        
        if not all_weeks_data:
            logger.warning("No weekly data available for boxplots")
            boxplots_fig = {}
        else:
            # Concatenate all weeks
            combined_df = pd.concat(all_weeks_data, ignore_index=True)
            
            # Load baselines
            baseline_df = load_telemetry_baselines(client)
            
            # Build weekly boxplots
            boxplots_fig = build_weekly_boxplots(
                unit_id=selected_unit,
                component=selected_component,
                signals_table=signals_table_df,
                combined_df=combined_df,
                baseline_df=baseline_df,
                current_week=current_week,
                current_year=current_year
            )
        
        return header_card, signals_table_df.to_dict('records'), boxplots_fig
    
    except Exception as e:
        logger.error(f"Error updating component detail: {e}")
        import traceback
        traceback.print_exc()
        return None, [], {}


# ===================================================================
# LIMITS TAB CALLBACKS
# ===================================================================

@callback(
    Output("telemetry-limits-unit-filter", "options"),
    Input("client-selector", "value")
)
def update_limits_unit_filter_options(client):
    """
    Update limits unit filter dropdown.
    
    Args:
        client: Selected client identifier
    
    Returns:
        List of dropdown options
    """
    if not client:
        raise PreventUpdate
    
    try:
        # Load baselines
        baseline_df = load_telemetry_baselines(client)
        
        if baseline_df.empty or 'Unit' not in baseline_df.columns:
            return [{'label': 'All Units', 'value': 'all'}]
        
        # Get unique units
        units = sorted(baseline_df['Unit'].unique().tolist())
        
        options = [{'label': 'All Units', 'value': 'all'}]
        options.extend([{'label': unit, 'value': unit} for unit in units])
        
        return options
    
    except Exception as e:
        logger.error(f"Error updating limits unit filter: {e}")
        return [{'label': 'All Units', 'value': 'all'}]


@callback(
    [
        Output("telemetry-limits-info-card", "children"),
        Output("telemetry-baseline-thresholds-table", "data"),
    ],
    [
        Input("client-selector", "value"),
        Input("telemetry-limits-unit-filter", "value"),
        Input("telemetry-limits-estado-filter", "value"),
    ]
)
def update_limits_tab(client, unit_filter, estado_filter):
    """
    Update limits tab with baseline thresholds.
    
    Args:
        client: Selected client identifier
        unit_filter: Unit filter value
        estado_filter: Estado filter value
    
    Returns:
        Tuple of (info card, baseline table data)
    """
    if not client:
        raise PreventUpdate
    
    try:
        # Load baselines
        baseline_df = load_telemetry_baselines(client)
        
        if baseline_df.empty:
            logger.warning(f"No telemetry baselines for client {client}")
            return None, []
        
        # Get baseline metadata
        num_records = len(baseline_df)
        num_units = baseline_df['Unit'].nunique() if 'Unit' in baseline_df.columns else 0
        num_signals = baseline_df['Signal'].nunique() if 'Signal' in baseline_df.columns else 0
        num_states = baseline_df['EstadoMaquina'].nunique() if 'EstadoMaquina' in baseline_df.columns else 0
        baseline_filename = "baseline_latest.parquet"  # This could be extracted from loader
        
        # Build info card
        info_card = create_baseline_info_card(
            baseline_filename=baseline_filename,
            num_records=num_records,
            num_units=num_units,
            num_signals=num_signals,
            num_states=num_states
        )
        
        # Apply filters
        filtered_df = baseline_df.copy()
        
        if unit_filter and unit_filter != 'all' and 'Unit' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['Unit'] == unit_filter]
        
        if estado_filter and estado_filter != 'all' and 'EstadoMaquina' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['EstadoMaquina'] == estado_filter]
        
        # Build baseline table
        baseline_table_df = build_baseline_thresholds_table(filtered_df)
        
        return info_card, baseline_table_df.to_dict('records')
    
    except Exception as e:
        logger.error(f"Error updating limits tab: {e}")
        return None, []
