"""
Telemetry callbacks for Multi-Technical Alerts Dashboard (Restructured).

This module provides all interactive callbacks for telemetry tabs:
- Tab Switching: Handle internal tab navigation (Fleet Overview / Component Detail)
- Fleet Overview: Load fleet data, KPIs, table, pie chart, machine detail section
- Component Detail: Select component, signals table, boxplots, daily timeseries, and limits
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
    build_weekly_boxplots,
    build_daily_timeseries
)
from dashboard.components.telemetry_tables import (
    build_fleet_status_table,
    build_component_table,
    build_signal_evaluation_table,
    build_baseline_thresholds_table,
    parse_component_details,
    parse_signals_evaluation
)
from dashboard.tabs.tab_telemetry_fleet import create_telemetry_fleet_layout, create_machine_header_card
from dashboard.tabs.tab_telemetry_component import create_telemetry_component_layout, create_component_header_card
from dashboard.tabs.tab_telemetry_limits import create_baseline_info_card
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
        active_tab: Selected tab value ('fleet' or 'component')
    
    Returns:
        Tab content layout
    """
    if active_tab == 'fleet':
        return create_telemetry_fleet_layout()
    elif active_tab == 'component':
        return create_telemetry_component_layout()
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
        Output("telemetry-machine-selector", "options"),
    ],
    Input("client-selector", "value")
)
def update_fleet_overview(client):
    """
    Update fleet overview tab with machine status data and machine selector options.
    
    Args:
        client: Selected client identifier
    
    Returns:
        Tuple of (KPI cards figure, table data, pie chart figure, machine selector options)
    """
    if not client:
        raise PreventUpdate
    
    try:
        # Load machine status data
        machine_df = load_telemetry_machine_status(client)
        
        if machine_df.empty:
            logger.warning(f"No telemetry machine status data for client {client}")
            return {}, [], {}, []
        
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
        
        # Build machine selector options (sorted by priority)
        machine_df_sorted = machine_df_latest.sort_values('priority_score', ascending=False)
        machine_options = [
            {
                'label': f"{row['unit_id']} - {row['overall_status']} (Score: {row['priority_score']:.2f})",
                'value': row['unit_id']
            }
            for _, row in machine_df_sorted.iterrows()
        ]
        
        return kpi_cards_fig, fleet_table_df.to_dict('records'), pie_chart_fig, machine_options
    
    except Exception as e:
        logger.error(f"Error updating fleet overview: {e}")
        return {}, [], {}, []


# ===================================================================
# MACHINE DETAIL CALLBACKS (in Fleet Tab)
# ===================================================================

@callback(
    [
        Output("telemetry-machine-header", "children"),
        Output("telemetry-machine-component-table", "data"),
        Output("telemetry-machine-component-radar", "figure"),
    ],
    [
        Input("telemetry-machine-selector", "value"),
        State("client-selector", "value")
    ]
)
def update_machine_detail(selected_unit, client):
    """
    Update machine detail section when unit is selected in fleet tab.
    
    Args:
        selected_unit: Selected unit ID
        client: Selected client identifier
    
    Returns:
        Tuple of (header card, component table data, radar chart figure)
    """
    if not selected_unit or not client:
        return html.Div(), [], {}
    
    try:
        # Load machine status data
        machine_df = load_telemetry_machine_status(client)
        
        if machine_df.empty:
            return html.Div("No data available"), [], {}
        
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
            return html.Div(f"No data for unit {selected_unit}"), [], {}
        
        machine_row = machine_row.iloc[0]
        
        # Parse component_details
        component_details = parse_component_details(machine_row['component_details'])
        
        if not component_details:
            return html.Div("No component details available"), [], {}
        
        # Count components by status
        anormal_count = sum(1 for c in component_details if c.get('component_status') == 'Anormal')
        alerta_count = sum(1 for c in component_details if c.get('component_status') == 'Alerta')
        normal_count = sum(1 for c in component_details if c.get('component_status') == 'Normal')
        
        # Build header card
        header_card = create_machine_header_card(
            unit_id=machine_row['unit_id'],
            overall_status=machine_row['overall_status'],
            priority_score=machine_row['priority_score'],
            machine_score=machine_row['machine_score'],
            evaluation_week=int(machine_row['evaluation_week']),
            evaluation_year=int(machine_row['evaluation_year']),
            anormal_count=anormal_count,
            alerta_count=alerta_count,
            normal_count=normal_count
        )
        
        # Build component table
        component_table_df = build_component_table(component_details)
        
        # Build radar chart
        radar_chart_fig = build_component_radar_chart(component_details, selected_unit)
        
        return header_card, component_table_df.to_dict('records'), radar_chart_fig
    
    except Exception as e:
        logger.error(f"Error updating machine detail: {e}")
        import traceback
        traceback.print_exc()
        return html.Div("Error loading machine detail"), [], {}


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
        Output("telemetry-component-selector", "value"),
    ],
    [
        Input("telemetry-component-unit-selector", "value"),
        State("client-selector", "value")
    ]
)
def update_component_selector(selected_unit, client):
    """
    Update component selector dropdown based on selected unit with default selection.
    
    Args:
        selected_unit: Selected unit ID
        client: Selected client identifier
    
    Returns:
        Tuple of (component options, disabled state, default value)
    """
    if not selected_unit or not client:
        return [], True, None
    
    try:
        # Load machine status data
        machine_df = load_telemetry_machine_status(client)
        
        if machine_df.empty:
            return [], True, None
        
        # Filter to latest evaluation week and selected unit
        latest_year = machine_df['evaluation_year'].max()
        latest_week = machine_df[machine_df['evaluation_year'] == latest_year]['evaluation_week'].max()
        
        machine_row = machine_df[
            (machine_df['unit_id'] == selected_unit) &
            (machine_df['evaluation_year'] == latest_year) &
            (machine_df['evaluation_week'] == latest_week)
        ]
        
        if machine_row.empty:
            return [], True, None
        
        # Parse component_details
        component_details = parse_component_details(machine_row.iloc[0]['component_details'])
        
        if not component_details:
            return [], True, None
        
        # Create options sorted by score (highest first)
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
        
        # Default to highest score component
        default_value = component_df.iloc[0]['component'] if not component_df.empty else None
        
        return options, False, default_value
    
    except Exception as e:
        logger.error(f"Error updating component selector: {e}")
        return [], True, None


@callback(
    [
        Output("telemetry-component-header", "children"),
        Output("telemetry-signal-evaluation-table", "data"),
        Output("telemetry-weekly-boxplots", "figure"),
        Output("telemetry-daily-timeseries", "figure"),
        Output("telemetry-component-limits-info-card", "children"),
        Output("telemetry-component-baseline-table", "data"),
    ],
    [
        Input("telemetry-component-selector", "value"),
        Input("telemetry-estado-filter", "value"),
        Input("telemetry-signal-evaluation-table", "selected_rows"),
        State("telemetry-component-unit-selector", "value"),
        State("client-selector", "value"),
        State("telemetry-signal-evaluation-table", "data"),
    ]
)
def update_component_detail(selected_component, estado_filter, selected_rows, selected_unit, client, signals_table_data):
    """
    Update component detail tab when component is selected.
    
    Args:
        selected_component: Selected component name
        estado_filter: Machine state filter
        selected_rows: Selected rows in signals table
        selected_unit: Selected unit ID
        client: Selected client identifier
        signals_table_data: Current signals table data
    
    Returns:
        Tuple of (header card, signals table data, boxplots figure, timeseries figure, limits info card, limits table data)
    """
    if not selected_component or not selected_unit or not client:
        return html.Div(), [], {}, {}, html.Div(), []
    
    try:
        # Load classified data
        classified_df = load_telemetry_classified(client)
        
        if classified_df.empty:
            return html.Div("No classified data"), [], {}, {}, html.Div(), []
        
        # Filter for selected unit and component
        component_eval = classified_df[
            (classified_df['unit_id'] == selected_unit) &
            (classified_df['component'] == selected_component)
        ]
        
        if component_eval.empty:
            logger.warning(f"No evaluation found for {selected_unit} - {selected_component}")
            return html.Div(f"No evaluation for {selected_component}"), [], {}, {}, html.Div(), []
        
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
            return html.Div("No signal evaluations"), [], {}, {}, html.Div(), []
        
        # Build signals table
        signals_table_df = build_signal_evaluation_table(signals_eval)
        
        # Build header card
        num_anormal = sum(1 for s in signals_eval.values() if s and s.get('status') == 'Anormal')
        num_alerta = sum(1 for s in signals_eval.values() if s and s.get('status') == 'Alerta')
        
        header_card = create_component_header_card(
            component=selected_component,
            component_status=latest_eval.get('component_status', 'Unknown'),
            component_score=latest_eval.get('component_score', 0.0),
            num_signals=len(signals_eval),
            num_anormal=num_anormal,
            num_alerta=num_alerta,
            coverage=latest_eval.get('coverage', 0.0),
            unit_id=selected_unit
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
            timeseries_fig = {}
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
            
            # Build daily timeseries for selected signal (or highest score signal)
            if selected_rows and signals_table_data:
                # Get selected signal from table
                selected_signal = signals_table_data[selected_rows[0]]['signal']
            else:
                # Default to highest score signal
                if 'score' in signals_table_df.columns:
                    selected_signal = signals_table_df.sort_values('score', ascending=False).iloc[0]['signal']
                else:
                    selected_signal = signals_table_df.iloc[0]['signal']
            
            # Load 4 weeks for timeseries
            weeks_for_timeseries = weeks_to_load[:4]  # Most recent 4 weeks
            timeseries_data = []
            for week, year in weeks_for_timeseries:
                week_df = load_silver_telemetry_week(client, week, year)
                if not week_df.empty:
                    week_df = week_df[week_df['Unit'] == selected_unit].copy()
                    if estado_filter and estado_filter != 'all' and 'EstadoMaquina' in week_df.columns:
                        week_df = week_df[week_df['EstadoMaquina'] == estado_filter]
                    if not week_df.empty:
                        timeseries_data.append(week_df)
            
            if timeseries_data:
                timeseries_combined = pd.concat(timeseries_data, ignore_index=True)
                timeseries_fig = build_daily_timeseries(
                    unit_id=selected_unit,
                    component=selected_component,
                    signal=selected_signal,
                    combined_df=timeseries_combined,
                    baseline_df=baseline_df
                )
            else:
                timeseries_fig = {}
        
        # Build limits section
        baseline_df = load_telemetry_baselines(client)
        
        if not baseline_df.empty:
            # Filter for selected unit and component signals
            component_signals = signals_table_df['signal'].tolist()
            component_baseline = baseline_df[
                (baseline_df['Unit'] == selected_unit) &
                (baseline_df['Signal'].isin(component_signals))
            ].copy()
            
            # Apply estado filter
            if estado_filter and estado_filter != 'all' and 'EstadoMaquina' in component_baseline.columns:
                component_baseline = component_baseline[component_baseline['EstadoMaquina'] == estado_filter]
            
            # Build limits info card
            num_records = len(component_baseline)
            num_signals = component_baseline['Signal'].nunique() if not component_baseline.empty else 0
            num_states = component_baseline['EstadoMaquina'].nunique() if 'EstadoMaquina' in component_baseline.columns else 0
            baseline_filename = "baseline_latest.parquet"
            
            limits_info_card = create_baseline_info_card(
                baseline_filename=baseline_filename,
                num_records=num_records,
                num_units=1,
                num_signals=num_signals,
                num_states=num_states
            )
            
            # Build limits table
            limits_table_df = build_baseline_thresholds_table(component_baseline)
            limits_table_data = limits_table_df.to_dict('records') if not limits_table_df.empty else []
        else:
            limits_info_card = html.Div("No baseline data available")
            limits_table_data = []
        
        return (
            header_card,
            signals_table_df.to_dict('records'),
            boxplots_fig,
            timeseries_fig,
            limits_info_card,
            limits_table_data
        )
    
    except Exception as e:
        logger.error(f"Error updating component detail: {e}")
        import traceback
        traceback.print_exc()
        return html.Div("Error loading component detail"), [], {}, {}, html.Div(), []
