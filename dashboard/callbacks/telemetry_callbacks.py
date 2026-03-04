"""
Telemetry callbacks for Multi-Technical Alerts Dashboard.

This module provides all interactive callbacks for telemetry tabs:
- Tab Switching: Handle internal tab navigation (Fleet, Component)
- Fleet Overview: Load fleet data, update KPIs, table, pie chart, and inline machine detail
- Component Detail: Select component, update signals table, boxplots, and daily timeseries
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
    build_weekly_boxplots,
    build_daily_timeseries
)
from dashboard.components.telemetry_tables import (
    build_fleet_status_table,
    build_component_table,
    build_signal_evaluation_table,
    parse_component_details,
    parse_signals_evaluation
)
from dashboard.tabs.tab_telemetry_fleet import create_telemetry_fleet_layout
from dashboard.tabs.tab_telemetry_machine import (
    create_machine_header_card,
    create_ai_recommendation_card,
    create_machine_detail_inline
)
from dashboard.tabs.tab_telemetry_component import create_telemetry_component_layout, create_component_header_card
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
        active_tab: Selected tab value ('fleet', 'component')
    
    Returns:
        Tab content layout
    """
    if active_tab == 'fleet':
        return create_telemetry_fleet_layout()
    elif active_tab == 'component':
        return create_telemetry_component_layout()
    else:
        return html.Div("Selección de pestaña inválida")


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
# FLEET ROW CLICK → INLINE MACHINE DETAIL
# ===================================================================

@callback(
    Output("telemetry-machine-detail-container", "children"),
    [
        Input("telemetry-fleet-status-table", "selected_rows"),
        State("telemetry-fleet-status-table", "data"),
        State("client-selector", "value")
    ]
)
def update_inline_machine_detail(selected_rows, table_data, client):
    """
    Show machine detail inline below fleet table when a row is selected.
    
    Args:
        selected_rows: List of selected row indices
        table_data: Fleet table data (list of dicts)
        client: Selected client identifier
    
    Returns:
        Machine detail layout or empty div
    """
    if not selected_rows or not table_data or not client:
        return html.Div()

    try:
        row_idx = selected_rows[0]
        if row_idx >= len(table_data):
            return html.Div()

        selected_unit = table_data[row_idx]['Unidad']
        logger.info(f"Fleet row clicked: unit={selected_unit}")

        # Load machine data
        machine_df = load_telemetry_machine_status(client)
        if machine_df.empty:
            return html.Div()

        # Filter to latest week + selected unit
        latest_year = machine_df['evaluation_year'].max()
        latest_week = machine_df[machine_df['evaluation_year'] == latest_year]['evaluation_week'].max()

        machine_row = machine_df[
            (machine_df['unit_id'] == selected_unit) &
            (machine_df['evaluation_year'] == latest_year) &
            (machine_df['evaluation_week'] == latest_week)
        ]

        if machine_row.empty:
            return html.Div()

        machine_row = machine_row.iloc[0]

        # Build header card
        header_card = create_machine_header_card(
            unit_id=machine_row['unit_id'],
            overall_status=machine_row['overall_status'],
            priority_score=machine_row['priority_score'],
            machine_score=machine_row['machine_score'],
            evaluation_week=machine_row['evaluation_week'],
            evaluation_year=machine_row['evaluation_year']
        )

        # Parse component_details and build table
        component_details = parse_component_details(machine_row['component_details'])
        component_table_df = build_component_table(component_details)

        # Build AI recommendation card
        ai_text = None
        if 'ai_recommendation' in machine_row.index and pd.notna(machine_row.get('ai_recommendation')):
            ai_text = str(machine_row['ai_recommendation'])

        ai_card = create_ai_recommendation_card(ai_text)

        # Build inline detail
        return create_machine_detail_inline(
            header_card=header_card,
            component_table_data=component_table_df.to_dict('records'),
            ai_recommendation_card=ai_card,
            unit_id=selected_unit
        )

    except Exception as e:
        logger.error(f"Error updating inline machine detail: {e}")
        return html.Div()


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
                'label': f"{row['component']} - {row.get('component_status', row.get('status', 'N/A'))}",
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
        Output("telemetry-daily-signal-selector", "options"),
        Output("telemetry-daily-signal-selector", "disabled"),
        Output("telemetry-daily-signal-selector", "value"),
    ],
    [
        Input("telemetry-component-selector", "value"),
        State("telemetry-component-unit-selector", "value"),
        State("client-selector", "value")
    ]
)
def update_component_detail(selected_component, selected_unit, client):
    """
    Update component detail tab when component is selected.
    Also populates the daily signal selector options.
    
    Args:
        selected_component: Selected component name
        selected_unit: Selected unit ID
        client: Selected client identifier
    
    Returns:
        Tuple of (header card, signals table data, boxplots figure,
                  signal selector options, selector disabled, selector value)
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
                    week_df['week_label'] = f'Sem {week:02d}/{year}'
                    week_df['week_num'] = week
                    week_df['year'] = year

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

        # Build signal selector options for daily timeseries
        signal_options = []
        if 'signal' in signals_table_df.columns:
            sig_list = signals_table_df['signal'].tolist()
            # Sort by score if available
            if 'score' in signals_table_df.columns:
                sorted_df = signals_table_df.sort_values('score', ascending=False)
                sig_list = sorted_df['signal'].tolist()

            signal_options = [{'label': s, 'value': s} for s in sig_list]

        default_signal = sig_list[0] if sig_list else None

        return (
            header_card,
            signals_table_df.to_dict('records'),
            boxplots_fig,
            signal_options,
            False,  # enable selector
            default_signal
        )

    except Exception as e:
        logger.error(f"Error updating component detail: {e}")
        import traceback
        traceback.print_exc()
        return None, [], {}, [], True, None


# ===================================================================
# DAILY TIME SERIES CALLBACK
# ===================================================================

@callback(
    [
        Output("telemetry-daily-timeseries", "figure"),
        Output("telemetry-daily-timeseries", "style"),
    ],
    [
        Input("telemetry-daily-signal-selector", "value"),
        State("telemetry-component-unit-selector", "value"),
        State("telemetry-component-selector", "value"),
        State("client-selector", "value")
    ]
)
def update_daily_timeseries(selected_signal, selected_unit, selected_component, client):
    """
    Update daily time series chart when a signal is selected.
    
    Loads 4 weeks of silver data and renders daily violin+box distribution.
    
    Args:
        selected_signal: Signal name to plot
        selected_unit: Selected unit ID
        selected_component: Selected component name
        client: Selected client identifier
    
    Returns:
        Tuple of (figure, style dict for visibility)
    """
    if not selected_signal or not selected_unit or not selected_component or not client:
        raise PreventUpdate

    try:
        logger.info(f"Loading daily timeseries for signal={selected_signal}, unit={selected_unit}")

        # Get current evaluation week from classified data
        classified_df = load_telemetry_classified(client)
        if classified_df.empty:
            return {}, {'display': 'none'}

        component_eval = classified_df[
            (classified_df['unit_id'] == selected_unit) &
            (classified_df['component'] == selected_component)
        ]

        if component_eval.empty:
            return {}, {'display': 'none'}

        latest_eval = component_eval.sort_values(
            ['evaluation_year', 'evaluation_week'], ascending=False
        ).iloc[0]

        current_week = int(latest_eval['evaluation_week'])
        current_year = int(latest_eval['evaluation_year'])

        # Load 4 weeks of silver data
        weeks_to_load = []
        temp_date = datetime.strptime(f'{current_year}-W{current_week:02d}-1', '%Y-W%W-%w')

        for i in range(4):
            target_date = temp_date - timedelta(weeks=i)
            week_num = int(target_date.strftime('%W'))
            year_num = target_date.year
            weeks_to_load.append((week_num, year_num))

        # Load and combine data
        all_weeks_daily = []
        for week, year in weeks_to_load:
            week_df = load_silver_telemetry_week(client, week, year)
            if not week_df.empty:
                week_df = week_df[week_df['Unit'] == selected_unit].copy()
                if not week_df.empty:
                    all_weeks_daily.append(week_df)

        if not all_weeks_daily:
            logger.warning("No daily data available for timeseries")
            return {}, {'display': 'none'}

        combined_daily = pd.concat(all_weeks_daily, ignore_index=True)

        # Load baselines
        baseline_df = load_telemetry_baselines(client)

        # Build daily timeseries figure
        fig = build_daily_timeseries(
            selected_signal=selected_signal,
            unit_id=selected_unit,
            component=selected_component,
            combined_daily=combined_daily,
            baseline_df=baseline_df
        )

        return fig, {'display': 'block'}

    except Exception as e:
        logger.error(f"Error updating daily timeseries: {e}")
        return {}, {'display': 'none'}


# ===================================================================
# NAVIGATION: FLEET → COMPONENT
# ===================================================================

@callback(
    Output('telemetry-tabs', 'value', allow_duplicate=True),
    Output('telemetry-nav-store', 'data', allow_duplicate=True),
    Input('telemetry-nav-to-component', 'n_clicks'),
    State('telemetry-nav-unit-store', 'data'),
    State('telemetry-component-status-table', 'selected_rows'),
    State('telemetry-component-status-table', 'data'),
    prevent_initial_call=True
)
def navigate_to_component_tab(n_clicks, unit_id, selected_rows, table_data):
    """
    Navigate from fleet machine detail to component analysis tab.
    Stores unit and (optionally) selected component in nav store
    so chained callbacks can apply the pre-selection after the
    component tab renders.
    """
    if not n_clicks:
        raise PreventUpdate

    component = None
    if selected_rows and table_data:
        row = table_data[selected_rows[0]]
        component = row.get('Componente')

    nav_data = {'unit_id': unit_id, 'component': component}
    return 'component', nav_data


@callback(
    Output('telemetry-component-unit-selector', 'value', allow_duplicate=True),
    Input('telemetry-component-unit-selector', 'options'),
    State('telemetry-nav-store', 'data'),
    prevent_initial_call=True
)
def apply_nav_unit_preselection(options, nav_data):
    """
    After the component tab renders and unit options are populated,
    pre-select the unit if navigation data exists.
    """
    if not nav_data or not options:
        raise PreventUpdate

    unit_id = nav_data.get('unit_id')
    if not unit_id:
        raise PreventUpdate

    valid = [o['value'] for o in options]
    if unit_id not in valid:
        raise PreventUpdate

    return unit_id


@callback(
    Output('telemetry-component-selector', 'value', allow_duplicate=True),
    Output('telemetry-nav-store', 'data', allow_duplicate=True),
    Input('telemetry-component-selector', 'options'),
    State('telemetry-nav-store', 'data'),
    prevent_initial_call=True
)
def apply_nav_component_preselection(options, nav_data):
    """
    After component options are populated, pre-select the component
    if navigation data exists, then clear the nav store.
    """
    if not nav_data or not options:
        raise PreventUpdate

    component = nav_data.get('component')

    # Always clear the store after consuming
    if not component:
        return no_update, None

    valid = [o['value'] for o in options]
    if component not in valid:
        return no_update, None

    return component, None
