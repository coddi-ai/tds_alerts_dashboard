# Telemetry Dashboard - Implementation Notes

**Version**: 1.0.0  
**Last Updated**: February 26, 2026  
**Component**: Dashboard Implementation Guide

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Data Sources Summary](#data-sources-summary)
3. [Fleet Overview Figures](#fleet-overview-figures)
4. [Machine Detail Figures](#machine-detail-figures)
5. [Component Detail Figures](#component-detail-figures)
6. [Limits Tab Figures](#limits-tab-figures)
7. [Helper Functions](#helper-functions)

---

## 🎯 Overview

This document provides **pseudo-code and implementation guidance** for building the telemetry dashboard visualizations. It focuses on how to query and structure data from the Golden layer for each figure type.

### Implementation Stack

```python
# Core libraries
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from dash import Dash, dcc, html, dash_table as ddt
import dash_bootstrap_components as dbc
from pathlib import Path
```

### Key Principles

1. **Load data once**: Cache Golden layer files in `dcc.Store`
2. **Filter dynamically**: Use Dash callbacks for interactivity
3. **Optimize queries**: Filter dataframes before passing to Plotly
4. **Handle missing data**: Gracefully handle units with `InsufficientData`

---

## 📂 Data Sources Summary

```python
# Golden Layer data paths
BASE_DIR = Path('data/telemetry/golden/{client}')

# Primary data sources
MACHINE_STATUS_PATH = BASE_DIR / 'machine_status.parquet'
CLASSIFIED_PATH = BASE_DIR / 'classified.parquet'
BASELINE_PATH = BASE_DIR / 'baselines' / 'baseline_{YYYYMMDD}.parquet'

# Silver Layer (for time-series and detail views)
SILVER_DIR = Path('data/telemetry/silver/{client}/Telemetry_Wide_With_States')
```

**Schema Quick Reference**:

| File | Key Columns | Grain |
|------|-------------|-------|
| `machine_status.parquet` | `unit_id`, `overall_status`, `machine_score`, `priority_score`, `component_details` (JSON) | One row per unit (latest evaluation) |
| `classified.parquet` | `unit_id`, `component`, `component_status`, `component_score`, `signals_evaluation` (JSON), `evaluation_week`, `evaluation_year` | One row per unit-component-week (time-series) |
| `baseline_{date}.parquet` | `Unit`, `Signal`, `EstadoMaquina`, `P2`, `P5`, `P95`, `P98` | One row per unit-signal-state combination |

---

## 📊 Fleet Overview Figures

### 1. KPI Cards

**Purpose**: Show fleet-wide health summary (Total, Normal, Alerta, Anormal)

**Data Source**: `machine_status.parquet`

```python
# Pseudo-code
def build_kpi_cards(machine_df):
    """
    Build KPI indicator cards for fleet overview.
    
    Args:
        machine_df: DataFrame from machine_status.parquet
    
    Returns:
        List of dbc.Card or dcc.Graph with Indicator traces
    """
    # Count by status
    total_units = len(machine_df)
    status_counts = machine_df['overall_status'].value_counts()
    
    normal_count = status_counts.get('Normal', 0)
    alerta_count = status_counts.get('Alerta', 0)
    anormal_count = status_counts.get('Anormal', 0)
    
    # Calculate percentages
    normal_pct = (normal_count / total_units) * 100 if total_units > 0 else 0
    alerta_pct = (alerta_count / total_units) * 100 if total_units > 0 else 0
    anormal_pct = (anormal_count / total_units) * 100 if total_units > 0 else 0
    
    # Create indicator figures (Plotly)
    kpi_cards = []
    
    # Card 1: Total Units
    fig_total = go.Figure(go.Indicator(
        mode="number",
        value=total_units,
        title={"text": "Total Units"},
        domain={'x': [0, 1], 'y': [0, 1]}
    ))
    kpi_cards.append(dcc.Graph(figure=fig_total))
    
    # Card 2: Normal
    fig_normal = go.Figure(go.Indicator(
        mode="number+delta",
        value=normal_count,
        delta={'reference': total_units, 'valueformat': '.0%', 'relative': True},
        title={"text": "Normal"},
        number={'suffix': f" ({normal_pct:.1f}%)"},
        domain={'x': [0, 1], 'y': [0, 1]}
    ))
    fig_normal.update_traces(delta_increasing_color='green')
    kpi_cards.append(dcc.Graph(figure=fig_normal))
    
    # Card 3: Alerta
    fig_alerta = go.Figure(go.Indicator(
        mode="number",
        value=alerta_count,
        title={"text": "Alerta"},
        number={'suffix': f" ({alerta_pct:.1f}%)"},
        domain={'x': [0, 1], 'y': [0, 1]}
    ))
    fig_alerta.update_traces(number_font_color='orange')
    kpi_cards.append(dcc.Graph(figure=fig_alerta))
    
    # Card 4: Anormal
    fig_anormal = go.Figure(go.Indicator(
        mode="number",
        value=anormal_count,
        title={"text": "Anormal"},
        number={'suffix': f" ({anormal_pct:.1f}%)"},
        domain={'x': [0, 1], 'y': [0, 1]}
    ))
    fig_anormal.update_traces(number_font_color='red')
    kpi_cards.append(dcc.Graph(figure=fig_anormal))
    
    return kpi_cards
```

---

### 2. Fleet Status Table

**Purpose**: Interactive sortable table of all units with status and priority

**Data Source**: `machine_status.parquet`

```python
# Pseudo-code
def build_fleet_table(machine_df):
    """
    Build interactive fleet status table.
    
    Args:
        machine_df: DataFrame from machine_status.parquet
    
    Returns:
        dash_table.DataTable component
    """
    # Prepare display dataframe
    display_df = machine_df[[
        'unit_id',
        'overall_status',
        'priority_score',
        'components_anormal',
        'components_alerta',
        'components_normal'
    ]].copy()
    
    # Create component summary column
    display_df['components'] = display_df.apply(
        lambda row: f"{row['components_anormal']}/{row['components_alerta']}/{row['components_normal']}",
        axis=1
    )
    
    # Sort by priority (highest first)
    display_df = display_df.sort_values('priority_score', ascending=False)
    
    # Create Dash DataTable
    table = ddt.DataTable(
        id='fleet-status-table',
        columns=[
            {'name': 'Unit ID', 'id': 'unit_id'},
            {'name': 'Status', 'id': 'overall_status'},
            {'name': 'Priority Score', 'id': 'priority_score', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'Components (A/L/N)', 'id': 'components'},
        ],
        data=display_df.to_dict('records'),
        
        # Styling
        style_data_conditional=[
            {
                'if': {'filter_query': '{overall_status} = "Anormal"'},
                'backgroundColor': '#ffe6e6',  # Light red
                'color': 'darkred'
            },
            {
                'if': {'filter_query': '{overall_status} = "Alerta"'},
                'backgroundColor': '#fff9e6',  # Light yellow
                'color': 'darkorange'
            },
            {
                'if': {'filter_query': '{overall_status} = "Normal"'},
                'backgroundColor': '#e6ffe6',  # Light green
                'color': 'darkgreen'
            }
        ],
        
        # Interaction
        sort_action='native',
        filter_action='native',
        page_size=20,
        row_selectable='single',
        selected_rows=[],
        
        style_table={'overflowX': 'auto'},
        style_cell={'textAlign': 'left', 'padding': '10px'},
        style_header={'fontWeight': 'bold', 'backgroundColor': '#f0f0f0'}
    )
    
    return table
```

**Callback for row selection** (navigate to Machine Detail):

```python
@app.callback(
    Output('url', 'pathname'),
    Input('fleet-status-table', 'selected_rows'),
    State('fleet-status-table', 'data')
)
def navigate_to_machine_detail(selected_rows, table_data):
    """Navigate to Machine Detail tab when row is clicked."""
    if selected_rows:
        selected_unit = table_data[selected_rows[0]]['unit_id']
        return f'/telemetry/machine/{selected_unit}'
    return '/telemetry/fleet'
```

---

### 3. Status Distribution Pie Chart

**Purpose**: Visual breakdown of fleet health distribution

**Data Source**: `machine_status.parquet`

```python
# Pseudo-code
def build_status_pie_chart(machine_df):
    """
    Build pie chart showing fleet status distribution.
    
    Args:
        machine_df: DataFrame from machine_status.parquet
    
    Returns:
        plotly.graph_objects.Figure
    """
    # Count by status
    status_counts = machine_df['overall_status'].value_counts()
    
    # Prepare data
    labels = status_counts.index.tolist()
    values = status_counts.values.tolist()
    
    # Define colors
    color_map = {
        'Normal': '#28a745',    # Green
        'Alerta': '#ffc107',    # Yellow/Amber
        'Anormal': '#dc3545',   # Red
        'InsufficientData': '#6c757d'  # Gray
    }
    colors = [color_map.get(label, '#cccccc') for label in labels]
    
    # Create pie chart
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        marker=dict(colors=colors),
        textinfo='label+percent+value',
        textposition='auto',
        hovertemplate='<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>'
    )])
    
    fig.update_layout(
        title='Fleet Health Distribution',
        showlegend=True,
        height=400
    )
    
    return fig
```

---

## 🔧 Machine Detail Figures

### 4. Machine Info Header

**Purpose**: Display selected machine metadata

**Data Source**: `machine_status.parquet` (single row)

```python
# Pseudo-code
def build_machine_info_header(machine_row):
    """
    Build info header for selected machine.
    
    Args:
        machine_row: Single row from machine_status.parquet (as dict or Series)
    
    Returns:
        dbc.Card or html.Div with formatted info
    """
    unit_id = machine_row['unit_id']
    status = machine_row['overall_status']
    evaluation_week = machine_row['evaluation_week']
    evaluation_year = machine_row['evaluation_year']
    latest_sample = machine_row['latest_sample_date']
    baseline_version = machine_row['baseline_version']
    machine_score = machine_row['machine_score']
    
    # Status badge color
    status_color = {
        'Normal': 'success',
        'Alerta': 'warning',
        'Anormal': 'danger',
        'InsufficientData': 'secondary'
    }.get(status, 'secondary')
    
    # Build header card
    header = dbc.Card([
        dbc.CardBody([
            html.H4(f"Unit: {unit_id}", className="card-title"),
            html.Div([
                dbc.Badge(status, color=status_color, className="me-2"),
                html.Span(f"Week {evaluation_week}/{evaluation_year}"),
                html.Span(f" | Machine Score: {machine_score:.2f}", className="ms-3"),
            ]),
            html.Hr(),
            html.Small([
                f"Last Sample: {latest_sample} | Baseline: {baseline_version}"
            ])
        ])
    ])
    
    return header
```

---

### 5. Component Status Table

**Purpose**: Show component-level health for selected machine

**Data Source**: `machine_status.parquet` → `component_details` field (JSON)

```python
# Pseudo-code
import json

def build_component_table(machine_row):
    """
    Build component status table from machine_status component_details.
    
    Args:
        machine_row: Single row from machine_status.parquet
    
    Returns:
        dash_table.DataTable
    """
    # Parse component_details JSON
    component_details = json.loads(machine_row['component_details'])
    
    # Convert to DataFrame
    components_df = pd.DataFrame(component_details)
    
    # Expected columns: component, status, score, triggering_signals, total_signals, ...
    
    # Sort by score (worst first)
    components_df = components_df.sort_values('score', ascending=False)
    
    # Create table
    table = ddt.DataTable(
        id='component-status-table',
        columns=[
            {'name': 'Component', 'id': 'component'},
            {'name': 'Status', 'id': 'status'},
            {'name': 'Score', 'id': 'score', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'Triggering Signals', 'id': 'triggering_signals'},
            {'name': 'Total Signals', 'id': 'total_signals', 'type': 'numeric'},
        ],
        data=components_df.to_dict('records'),
        
        # Styling
        style_data_conditional=[
            {
                'if': {'filter_query': '{status} = "Anormal"'},
                'backgroundColor': '#ffe6e6',
                'color': 'darkred',
                'fontWeight': 'bold'
            },
            {
                'if': {'filter_query': '{status} = "Alerta"'},
                'backgroundColor': '#fff9e6',
                'color': 'darkorange'
            },
            {
                'if': {'filter_query': '{status} = "Normal"'},
                'backgroundColor': '#e6ffe6',
                'color': 'darkgreen'
            }
        ],
        
        row_selectable='single',
        selected_rows=[],
        style_cell={'textAlign': 'left', 'padding': '10px'},
        style_header={'fontWeight': 'bold', 'backgroundColor': '#f0f0f0'}
    )
    
    return table
```

---

### 6. Component Radar Chart

**Purpose**: Visual representation of component scores

**Data Source**: `machine_status.parquet` → `component_details` field

```python
# Pseudo-code
def build_component_radar_chart(machine_row):
    """
    Build radar chart showing component scores.
    
    Args:
        machine_row: Single row from machine_status.parquet
    
    Returns:
        plotly.graph_objects.Figure
    """
    # Parse component_details
    component_details = json.loads(machine_row['component_details'])
    components_df = pd.DataFrame(component_details)
    
    # Extract component names and scores
    components = components_df['component'].tolist()
    scores = components_df['score'].tolist()
    
    # Create radar chart
    fig = go.Figure()
    
    fig.add_trace(go.Scatterpolar(
        r=scores,
        theta=components,
        fill='toself',
        name='Component Scores',
        hovertemplate='<b>%{theta}</b><br>Score: %{r:.2f}<extra></extra>'
    ))
    
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, max(scores) * 1.2] if scores else [0, 1]
            )
        ),
        showlegend=False,
        title='Component Health Scores',
        height=400
    )
    
    return fig
```

---

## 🔬 Component Detail Figures

### 7. Signal Evaluation Table

**Purpose**: Show signal-level evaluations for selected component

**Data Source**: `classified.parquet` → filter by `unit_id` and `component`, then parse `signals_evaluation` JSON field

```python
# Pseudo-code
def build_signal_evaluation_table(unit_id, component_name, evaluation_week, evaluation_year):
    """
    Build signal evaluation table for specific unit-component.
    
    Args:
        unit_id: Unit identifier
        component_name: Component name (e.g., 'Engine')
        evaluation_week: Week number
        evaluation_year: Year
    
    Returns:
        dash_table.DataTable
    """
    # Load classified data
    classified_df = pd.read_parquet(CLASSIFIED_PATH)
    
    # Filter to specific unit-component-week
    component_row = classified_df[
        (classified_df['unit_id'] == unit_id) &
        (classified_df['component'] == component_name) &
        (classified_df['evaluation_week'] == evaluation_week) &
        (classified_df['evaluation_year'] == evaluation_year)
    ]
    
    if component_row.empty:
        return html.Div("No data available for this component")
    
    # Parse signals_evaluation JSON
    signals_evaluation = json.loads(component_row.iloc[0]['signals_evaluation'])
    signals_df = pd.DataFrame(signals_evaluation)
    
    # Expected columns: signal_name, signal_status, window_score_normalized, 
    #                   severity, weight, anomaly_percentage, sample_count, ...
    
    # Sort by window_score_normalized (worst first)
    signals_df = signals_df.sort_values('window_score_normalized', ascending=False)
    
    # Create table
    table = ddt.DataTable(
        id='signal-evaluation-table',
        columns=[
            {'name': 'Signal', 'id': 'signal_name'},
            {'name': 'Status', 'id': 'signal_status'},
            {'name': 'Window Score', 'id': 'window_score_normalized', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'Severity', 'id': 'severity', 'type': 'numeric', 'format': {'specifier': '.1f'}},
            {'name': 'Weight', 'id': 'weight', 'type': 'numeric', 'format': {'specifier': '.1f'}},
            {'name': 'Anomaly %', 'id': 'anomaly_percentage', 'type': 'numeric', 'format': {'specifier': '.1f'}},
            {'name': 'Samples', 'id': 'sample_count', 'type': 'numeric'},
        ],
        data=signals_df.to_dict('records'),
        
        # Styling
        style_data_conditional=[
            {
                'if': {'filter_query': '{signal_status} = "Anormal"'},
                'backgroundColor': '#ffe6e6',
                'color': 'darkred'
            },
            {
                'if': {'filter_query': '{signal_status} = "Alerta"'},
                'backgroundColor': '#fff9e6',
                'color': 'darkorange'
            },
            {
                'if': {'filter_query': '{signal_status} = "Normal"'},
                'backgroundColor': '#e6ffe6',
                'color': 'darkgreen'
            },
            {
                'if': {'filter_query': '{weight} = 0.0'},
                'backgroundColor': '#f0f0f0',
                'color': '#999999',
                'fontStyle': 'italic'
            }
        ],
        
        sort_action='native',
        row_selectable='single',
        selected_rows=[],
        style_cell={'textAlign': 'left', 'padding': '10px'},
        style_header={'fontWeight': 'bold', 'backgroundColor': '#f0f0f0'}
    )
    
    return table
```

---

### 8. Weekly Distribution Boxplots (NEW)

**Purpose**: Show signal distributions across multiple weeks for comparison

**Data Source**: `silver` layer (multiple week files) + `classified.parquet` (for status)

```python
# Pseudo-code
from datetime import datetime, timedelta

def build_weekly_boxplots(unit_id, component_name, evaluation_week, evaluation_year, 
                          num_weeks=6, estado_filter='All'):
    """
    Build horizontal boxplots showing signal distributions over multiple weeks.
    
    Args:
        unit_id: Unit identifier
        component_name: Component name
        evaluation_week: Current evaluation week (highlighted)
        evaluation_year: Current evaluation year
        num_weeks: Number of historical weeks to show (default: 6)
        estado_filter: Filter by EstadoMaquina ('All', 'Operacional', 'Ralenti', 'Apagada')
    
    Returns:
        plotly.graph_objects.Figure with subplots (one per signal)
    """
    # Step 1: Get list of signals for this component
    component_mapping = load_component_mapping(CLIENT)
    signal_list = component_mapping[component_name]['signals']
    
    # Step 2: Load signal evaluation to get current status
    classified_df = pd.read_parquet(CLASSIFIED_PATH)
    component_eval = classified_df[
        (classified_df['unit_id'] == unit_id) &
        (classified_df['component'] == component_name) &
        (classified_df['evaluation_week'] == evaluation_week) &
        (classified_df['evaluation_year'] == evaluation_year)
    ]
    
    if component_eval.empty:
        return html.Div("No evaluation data available")
    
    signals_evaluation = json.loads(component_eval.iloc[0]['signals_evaluation'])
    signals_status_map = {
        s['signal_name']: s['signal_status'] 
        for s in signals_evaluation
    }
    
    # Step 3: Calculate week range (current week + N previous weeks)
    weeks_to_load = []
    current_date = datetime.strptime(f'{evaluation_year}-W{evaluation_week:02d}-1', '%Y-W%W-%w')
    for i in range(num_weeks):
        target_date = current_date - timedelta(weeks=i)
        week_num = target_date.isocalendar()[1]
        year_num = target_date.year
        weeks_to_load.append((week_num, year_num))
    
    # Step 4: Load silver layer data for all weeks
    all_weeks_data = []
    for week, year in weeks_to_load:
        try:
            week_file = SILVER_DIR / f'Week{week:02d}Year{year}.parquet'
            week_df = pd.read_parquet(week_file)
            
            # Filter to specific unit
            week_df = week_df[week_df['Unit'] == unit_id].copy()
            
            # Apply estado filter if not 'All'
            if estado_filter != 'All':
                week_df = week_df[week_df['EstadoMaquina'] == estado_filter]
            
            # Add week identifier
            week_df['week_label'] = f'Week {week:02d}/{year}'
            week_df['is_current'] = (week == evaluation_week and year == evaluation_year)
            
            all_weeks_data.append(week_df)
        except FileNotFoundError:
            print(f"Warning: Week {week}/{year} data not found")
            continue
    
    if not all_weeks_data:
        return html.Div("No historical data available")
    
    # Concatenate all weeks
    combined_df = pd.concat(all_weeks_data, ignore_index=True)
    
    # Step 5: Build boxplots (one subplot per signal)
    from plotly.subplots import make_subplots
    
    num_signals = len(signal_list)
    fig = make_subplots(
        rows=num_signals,
        cols=1,
        subplot_titles=signal_list,
        vertical_spacing=0.05,
        row_heights=[1] * num_signals
    )
    
    # Color gradient for historical weeks (blue shades)
    from plotly.colors import n_colors
    week_labels_sorted = sorted(combined_df['week_label'].unique())
    colors = n_colors('rgb(200, 220, 240)', 'rgb(30, 80, 150)', len(week_labels_sorted), colortype='rgb')
    
    # Build each signal's boxplot
    for idx, signal_name in enumerate(signal_list, start=1):
        # Check if signal exists in data
        if signal_name not in combined_df.columns:
            print(f"Warning: Signal {signal_name} not found in data")
            continue
        
        # Get signal status for current week (for color coding)
        signal_status = signals_status_map.get(signal_name, 'Normal')
        current_week_color = {
            'Normal': 'rgb(40, 167, 69)',      # Green
            'Alerta': 'rgb(255, 193, 7)',      # Yellow
            'Anormal': 'rgb(220, 53, 69)'      # Red
        }.get(signal_status, 'rgb(100, 100, 100)')
        
        # Add boxplot trace for each week
        for week_idx, week_label in enumerate(week_labels_sorted):
            week_data = combined_df[combined_df['week_label'] == week_label][signal_name].dropna()
            
            if len(week_data) == 0:
                continue
            
            is_current = combined_df[combined_df['week_label'] == week_label]['is_current'].iloc[0]
            
            # Choose color
            box_color = current_week_color if is_current else colors[week_idx]
            
            fig.add_trace(
                go.Box(
                    x=week_data,
                    name=week_label,
                    orientation='h',
                    marker=dict(color=box_color),
                    line=dict(width=2 if is_current else 1),
                    showlegend=(idx == 1),  # Only show legend for first signal
                    hovertemplate=(
                        f'<b>{week_label}</b><br>'
                        f'Q1: %{{q1:.2f}}<br>'
                        f'Median: %{{median:.2f}}<br>'
                        f'Q3: %{{q3:.2f}}<br>'
                        f'Min: %{{min:.2f}}<br>'
                        f'Max: %{{max:.2f}}<br>'
                        f'Count: {len(week_data)}<extra></extra>'
                    )
                ),
                row=idx,
                col=1
            )
        
        # Add mean reference line
        overall_mean = combined_df[signal_name].mean()
        fig.add_vline(
            x=overall_mean,
            line_dash="dash",
            line_color="black",
            line_width=1,
            row=idx,
            col=1,
            annotation=dict(
                text=f"Mean: {overall_mean:.1f}",
                yshift=10
            )
        )
    
    # Update layout
    fig.update_xaxes(title_text="Value", showgrid=True)
    fig.update_yaxes(showticklabels=False)
    
    fig.update_layout(
        title=f'Signal Distributions by Week - {component_name} (Unit: {unit_id})',
        height=150 * num_signals,  # Dynamic height based on number of signals
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    return fig
```

**Callback for Estado Filter**:

```python
@app.callback(
    Output('weekly-boxplot', 'figure'),
    [Input('estado-filter', 'value'),
     State('unit-selector', 'value'),
     State('component-selector', 'value'),
     State('evaluation-week', 'data'),
     State('evaluation-year', 'data')]
)
def update_boxplot_by_estado(estado_filter, unit_id, component_name, eval_week, eval_year):
    """Update boxplots when estado filter changes."""
    if not all([unit_id, component_name, eval_week, eval_year]):
        return go.Figure()
    
    return build_weekly_boxplots(
        unit_id=unit_id,
        component_name=component_name,
        evaluation_week=eval_week,
        evaluation_year=eval_year,
        estado_filter=estado_filter
    )
```

---

## 📏 Limits Tab Figures

### 9. Baseline Thresholds Table

**Purpose**: Display all baseline percentile thresholds

**Data Source**: `baselines/baseline_{YYYYMMDD}.parquet`

```python
# Pseudo-code
def build_baseline_table(baseline_version='latest'):
    """
    Build table showing baseline thresholds.
    
    Args:
        baseline_version: Baseline file version (YYYYMMDD) or 'latest'
    
    Returns:
        dash_table.DataTable
    """
    # Load baseline
    if baseline_version == 'latest':
        baseline_files = sorted(BASELINE_PATH.parent.glob('baseline_*.parquet'))
        baseline_path = baseline_files[-1]
    else:
        baseline_path = BASELINE_PATH.parent / f'baseline_{baseline_version}.parquet'
    
    baseline_df = pd.read_parquet(baseline_path)
    
    # Expected columns: Unit, Signal, EstadoMaquina, P2, P5, P95, P98, sample_count
    
    # Create table
    table = ddt.DataTable(
        id='baseline-thresholds-table',
        columns=[
            {'name': 'Unit', 'id': 'Unit'},
            {'name': 'Signal', 'id': 'Signal'},
            {'name': 'State', 'id': 'EstadoMaquina'},
            {'name': 'P2', 'id': 'P2', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'P5', 'id': 'P5', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'P95', 'id': 'P95', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'P98', 'id': 'P98', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'Samples', 'id': 'sample_count', 'type': 'numeric'},
        ],
        data=baseline_df.to_dict('records'),
        
        # Interaction
        filter_action='native',
        sort_action='native',
        page_size=50,
        
        style_table={'overflowX': 'auto'},
        style_cell={'textAlign': 'left', 'padding': '8px', 'fontSize': '12px'},
        style_header={'fontWeight': 'bold', 'backgroundColor': '#f0f0f0'},
        
        export_format='csv'
    )
    
    return table
```

---

### 10. Threshold Distribution Histogram

**Purpose**: Show distribution of training data with percentile thresholds

**Data Source**: `silver` layer (training window) + `baseline` file (thresholds)

```python
# Pseudo-code
def build_threshold_histogram(unit_id, signal_name, estado_filter='All'):
    """
    Build histogram showing signal distribution with threshold lines.
    
    Args:
        unit_id: Unit identifier
        signal_name: Signal name
        estado_filter: Operational state filter
    
    Returns:
        plotly.graph_objects.Figure
    """
    # Load baseline to get thresholds
    baseline_df = pd.read_parquet(BASELINE_PATH)
    baseline_row = baseline_df[
        (baseline_df['Unit'] == unit_id) &
        (baseline_df['Signal'] == signal_name) &
        (baseline_df['EstadoMaquina'] == estado_filter)
    ]
    
    if baseline_row.empty and estado_filter != 'All':
        # Fallback to aggregate baseline
        baseline_row = baseline_df[
            (baseline_df['Unit'] == unit_id) &
            (baseline_df['Signal'] == signal_name) &
            (baseline_df['EstadoMaquina'] == 'All')
        ]
    
    if baseline_row.empty:
        return html.Div("No baseline data available")
    
    # Get thresholds
    P2 = baseline_row.iloc[0]['P2']
    P5 = baseline_row.iloc[0]['P5']
    P95 = baseline_row.iloc[0]['P95']
    P98 = baseline_row.iloc[0]['P98']
    
    # Load training data from silver layer
    # (This would require loading the training window used for baseline computation)
    # For simplicity, assume we have a helper function
    training_df = load_baseline_training_data(unit_id, signal_name, estado_filter)
    
    if training_df.empty:
        return html.Div("No training data available")
    
    signal_values = training_df[signal_name].dropna()
    
    # Create histogram
    fig = go.Figure()
    
    fig.add_trace(go.Histogram(
        x=signal_values,
        nbinsx=50,
        marker=dict(color='lightblue', line=dict(color='darkblue', width=1)),
        name='Training Data',
        hovertemplate='Value: %{x:.2f}<br>Count: %{y}<extra></extra>'
    ))
    
    # Add percentile threshold lines
    fig.add_vline(x=P2, line_dash="solid", line_color="red", line_width=2,
                  annotation_text=f"P2: {P2:.2f}", annotation_position="top left")
    fig.add_vline(x=P5, line_dash="dash", line_color="orange", line_width=2,
                  annotation_text=f"P5: {P5:.2f}", annotation_position="top left")
    fig.add_vline(x=P95, line_dash="dash", line_color="orange", line_width=2,
                  annotation_text=f"P95: {P95:.2f}", annotation_position="top right")
    fig.add_vline(x=P98, line_dash="solid", line_color="red", line_width=2,
                  annotation_text=f"P98: {P98:.2f}", annotation_position="top right")
    
    # Add shaded regions
    fig.add_vrect(x0=signal_values.min(), x1=P2, fillcolor="red", opacity=0.2, line_width=0)
    fig.add_vrect(x0=P2, x1=P5, fillcolor="orange", opacity=0.2, line_width=0)
    fig.add_vrect(x0=P95, x1=P98, fillcolor="orange", opacity=0.2, line_width=0)
    fig.add_vrect(x0=P98, x1=signal_values.max(), fillcolor="red", opacity=0.2, line_width=0)
    
    fig.update_layout(
        title=f'{signal_name} Distribution - {unit_id} ({estado_filter})',
        xaxis_title=f'{signal_name} Value',
        yaxis_title='Frequency',
        showlegend=True,
        height=400
    )
    
    return fig
```

---

## 🔧 Helper Functions

### Load Component Mapping

```python
def load_component_mapping(client):
    """Load component-signal mapping configuration."""
    mapping_path = Path('data/telemetry/component_signals_mapping.json')
    with open(mapping_path, 'r') as f:
        mapping = json.load(f)
    return mapping.get(client, {})
```

### Get Signal Columns

```python
def get_signal_columns(df):
    """Extract signal columns from telemetry dataframe."""
    exclude_cols = ['Unit', 'Fecha', 'EstadoMaquina', 'GPSLat', 'GPSLon', 'GPSElevation']
    signal_cols = [col for col in df.columns if col not in exclude_cols]
    return signal_cols
```

### Format Week Label

```python
def format_week_label(week, year):
    """Format week/year as readable label."""
    return f"Week {week:02d}/{year}"
```

---

## 📝 Notes

### Performance Considerations

1. **Lazy Loading**: Only load `classified.parquet` when Component Detail tab is accessed
2. **Caching**: Use `dcc.Store` to cache frequently accessed data (machine_status)
3. **Pagination**: Use pagination in tables to avoid rendering thousands of rows
4. **Filtering**: Apply filters in pandas before passing to Plotly (not in Plotly)

### Error Handling

```python
# Example pattern for safe data loading
try:
    machine_df = pd.read_parquet(MACHINE_STATUS_PATH)
    if machine_df.empty:
        return html.Div("No machine status data available")
except FileNotFoundError:
    return html.Div("Machine status file not found. Please run the pipeline first.")
```

### Estado Filter Values

```python
ESTADO_OPTIONS = [
    {'label': 'All States', 'value': 'All'},
    {'label': 'Operacional', 'value': 'Operacional'},
    {'label': 'Ralenti (Idle)', 'value': 'Ralenti'},
    {'label': 'Apagada (Off)', 'value': 'Apagada'}
]
```

---

## 🎯 Implementation Priority

**Phase 1 (MVP)**:
1. Fleet Overview: KPI Cards, Status Table, Pie Chart
2. Machine Detail: Info Header, Component Table
3. Component Detail: Signal Table, Weekly Boxplots (basic)

**Phase 2**:
4. Machine Detail: Component Radar Chart
5. Component Detail: Weekly Boxplots (advanced with estado filter)
6. Limits Tab: Thresholds Table, Histogram

**Phase 3**:
7. Signal Detail Modal
8. Time-series plots
9. Export functionality
10. URL routing & breadcrumbs

---

**End of Implementation Notes**
