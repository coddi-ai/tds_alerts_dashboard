# Telemetry Dashboard - Proposal

**Version**: 1.0.0  
**Last Updated**: February 23, 2026  
**Component**: Telemetry Dashboard Design

---

## 📋 Table of Contents

1. [Dashboard Story](#dashboard-story)
2. [User Journey](#user-journey)
3. [Dashboard Layout](#dashboard-layout)
4. [Visualization Specifications](#visualization-specifications)
5. [Interaction Patterns](#interaction-patterns)
6. [Technical Implementation Notes](#technical-implementation-notes)

---

## 📖 Dashboard Story

The telemetry dashboard tells a **hierarchical diagnostic story** that guides users from fleet-wide awareness to component-level root cause analysis:

### The Narrative Arc

```
1. "What is the current health of my fleet?"
   → Fleet Overview: See all units and their status at a glance

2. "Which machines need attention?"
   → Machine Ranking: Sort by priority to focus on worst performers

3. "What's wrong with this machine?"
   → Component Health: Identify which systems are problematic

4. "Why is this component flagged?"
   → Signal Analysis: See which sensors are out of range

5. "Is this really abnormal?"
   → Evidence Validation: Compare current readings to historical baselines
```

### Key Questions Answered

| User Question | Dashboard Answer | Data Source |
|---------------|------------------|-------------|
| How many machines are in trouble? | KPI cards: X Anormal, Y Alerta | `machine_status.parquet` |
| Which machine is the highest priority? | Sorted table by `priority_score` | `machine_status.parquet` |
| What components are affected? | Component status table with drill-down | `component_details` (nested) |
| Which sensors triggered the alert? | Signal evaluation table | `classified.parquet` → `signals_evaluation` |
| How far from normal are the readings? | Boxplot: observed vs. baseline percentiles | Silver layer + baselines |
| Is this a recent issue or ongoing? | Time series over evaluation window | Silver layer (week partition) |

---

## 👤 User Journey

### Persona: Maintenance Engineer

**Goal**: Identify and prioritize maintenance interventions for the fleet

**Typical Workflow**:

1. **Monday Morning: Fleet Check**
   - Open dashboard → Fleet Overview tab
   - Scan KPI cards for new alerts since last week
   - Notice CAT797-001 now shows "Anormal" status

2. **Priority Assessment**
   - Sort machine table by priority_score (descending)
   - CAT797-001 ranks #2 → high priority
   - Click on CAT797-001 row → navigate to Machine Detail

3. **Component Diagnosis**
   - View component health table
   - Engine shows "Anormal", Transmission shows "Alerta"
   - Component radar chart shows Engine score = 1.2 (highest)
   - Click "Engine" → navigate to Component Detail

4. **Signal Investigation**
   - Signal status table shows:
     - `EngCoolTemp`: Anormal (window_score: 1.2)
     - `EngOilPres`: Alerta (window_score: 0.3)
   - Click "EngCoolTemp" → open Signal Drill-Down modal

5. **Evidence Validation**
   - Boxplot shows current readings consistently above P98
   - Time series reveals temperature spike started Day 3 of week
   - Baseline percentile bands show readings in red zone (>98°C)
   - **Decision**: Schedule immediate engine cooling system inspection

6. **Action Taken**
   - Note findings in maintenance system
   - Export plots for maintenance report
   - Set reminder to check next week's evaluation

---

## 🎨 Dashboard Layout

### Section: Monitoring → Telemetry

The telemetry dashboard is organized into **4 tabs**, each supporting a level of the diagnostic hierarchy:

```
┌─────────────────────────────────────────────────────────────────┐
│  MONITORING > Telemetry                                         │
├─────────────────────────────────────────────────────────────────┤
│  [Fleet Overview] [Machine Detail] [Component Detail] [Limits]  │
└─────────────────────────────────────────────────────────────────┘
```

---

### Tab 1: Fleet Overview

**Purpose**: High-level fleet health snapshot

**Layout**:

```
┌────────────────────────────────────────────────────────────┐
│  KPI Cards Row                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Total   │  │  Normal  │  │  Alerta  │  │ Anormal  │  │
│  │  Units   │  │   75%    │  │   18%    │  │    7%    │  │
│  │   120    │  │    90    │  │    22    │  │    8     │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  Fleet Status Table                                        │
│  [Search Box] [Status Filter ▼] [Export CSV]              │
│                                                            │
│  Unit ID    │ Status   │ Priority │ Components │ Actions │
│  ──────────────────────────────────────────────────────── │
│  CAT797-001 │ Anormal  │  120.8   │  1/2/9     │  View   │
│  CAT795-034 │ Anormal  │  115.2   │  2/1/11    │  View   │
│  KOM930-012 │ Alerta   │   25.4   │  0/2/10    │  View   │
│  ...                                                       │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  Fleet Status Distribution (Pie Chart)                    │
│  • Normal: 75% (90 units)                                  │
│  • Alerta: 18% (22 units)                                  │
│  • Anormal: 7% (8 units)                                   │
└────────────────────────────────────────────────────────────┘
```

**Components**:
1. **KPI Cards** (Plotly Indicator/Card)
   - Total units evaluated
   - % and count per status category
   - Color-coded: Green (Normal), Yellow (Alerta), Red (Anormal)

2. **Fleet Status Table** (Dash DataTable)
   - Columns:
     - `Unit ID`: Clickable link to Machine Detail
     - `Status`: Badge with color
     - `Priority Score`: Numeric sorter
     - `Components`: Format as "Anormal/Alerta/Normal"
     - `Actions`: "View" button
   - Features:
     - Sortable columns
     - Filter by status
     - Search by unit ID
     - Export to CSV
   - Default sort: `priority_score` descending

3. **Status Distribution Pie Chart** (Plotly Pie)
   - Visual breakdown of fleet health
   - Clickable segments filter table

---

### Tab 2: Machine Detail

**Purpose**: Deep dive into a specific unit's health

**Layout**:

```
┌────────────────────────────────────────────────────────────┐
│  Machine Selection & Info                                  │
│  Unit: [CAT797-001 ▼]  Status: Anormal  Week: 08/2026    │
│  Last Sample: 2026-02-22 23:59  Baseline: 20260201        │
└────────────────────────────────────────────────────────────┘

┌─────────────────────────────┐  ┌─────────────────────────┐
│  Component Status Table     │  │  Component Radar Chart  │
│  Component  │ Status │ Score│  │                         │
│  ─────────────────────────  │  │      Engine (1.2)       │
│  Engine     │ Anormal│ 1.2 │  │         ╱│╲             │
│  Transmiss. │ Alerta │ 0.3 │  │    Trans│   Hydraulic   │
│  Hydraulic  │ Normal │ 0.0 │  │         │               │
│  Brakes     │ Normal │ 0.0 │  │    Elec.│   Brakes      │
│  ...                        │  │         │               │
│                             │  │                         │
└─────────────────────────────┘  └─────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  Component Details Panel (Expandable)                      │
│  ► Engine (Anormal)                                        │
│    Triggering Signals: EngCoolTemp, EngOilPres            │
│    [View Component Detail] [View Time Series]             │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  Weekly Status Timeline (Optional - Phase 2)               │
│  Week 04 │ Week 05 │ Week 06 │ Week 07 │ Week 08         │
│  Normal  │ Normal  │ Alerta  │ Alerta  │ Anormal         │
└────────────────────────────────────────────────────────────┘
```

**Components**:
1. **Machine Selector** (Dash Dropdown)
   - Populated from `machine_status.parquet`
   - Shows unit ID + current status
   - Updates all visualizations on selection

2. **Machine Info Header**
   - Display key metadata from `machine_status` row
   - Status badge, evaluation week, timestamps

3. **Component Status Table** (Dash DataTable)
   - Source: `component_details` field
   - Columns: Component name, Status, Score
   - Sortable by score (default: descending)
   - Clickable rows → navigate to Component Detail tab
   - Color-coded status badges

4. **Component Radar Chart** (Plotly Scatterpolar)
   - Each axis = component
   - Radial value = component_score (normalized 0-3)
   - Color zones: Green (0-0.2), Yellow (0.2-0.4), Red (0.4+)
   - Hover: Show component name, score, status

5. **Component Details Accordion** (Dash Accordion/Collapse)
   - Expandable panels per component
   - Show `triggering_signals` list
   - Quick navigation buttons:
     - "View Component Detail" → Tab 3
     - "View Time Series" → Signal modal

---

### Tab 3: Component Detail

**Purpose**: Analyze specific component's signal evaluations

**Layout**:

```
┌────────────────────────────────────────────────────────────┐
│  Component Selection                                       │
│  Unit: [CAT797-001 ▼]  Component: [Engine ▼]             │
│  Status: Anormal  Score: 0.52  Coverage: 85%  Week: 08/26│
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  Signal Evaluation Table                                   │
│  Signal      │ Status │ Window │ Severity │ Weight │ ... │
│  ──────────────────────────────────────────────────────── │
│  EngCoolTemp │ Anormal│  1.20  │   1.0    │  1.0   │ 🔍 │
│  EngOilPres  │ Alerta │  0.30  │   0.3    │  1.0   │ 🔍 │
│  EngSpeed    │ Normal │  0.05  │   0.0    │  1.0   │ 🔍 │
│  EngOilTemp  │ Normal │  0.08  │   0.0    │  0.0   │ 🔍 │
│  ...                                                       │
│  🔍 = View Signal Detail (opens modal)                     │
│  Weight: 1.0 = Sufficient data, 0.0 = Insufficient        │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  Signal Distribution by Week (Horizontal Boxplots)         │
│  State Filter: [All ▼] [Operacional] [Ralenti] [Apagada] │
│  Showing all signals for: Engine                           │
│                                                            │
│  EngCoolTemp          EngOilPres          EngSpeed        │
│                                                            │
│  Week 50 (Current) ████████████──┼                        │
│  Week 49           ██████████──┼                          │
│  Week 48           ████████──┼                            │
│  Week 47           █████████──┼                           │
│  Week 46           ████████──┼                            │
│  Week 45           ██████████──┼                          │
│                    ┼ Mean                                  │
│                                                            │
│  • Current week highlighted in color (Red/Yellow/Green)   │
│  • Historical weeks in gradient (recent → older)          │
│  • Black dashed line shows overall mean                   │
│  • Hover: Show Q1, Median, Q3, Min, Max for each week    │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  AI Recommendation (Phase 2)                               │
│  🤖 "Engine coolant temperature consistently exceeds       │
│      normal range. Recommend inspection of:                │
│      • Coolant pump functionality                          │
│      • Radiator blockage                                   │
│      • Thermostat operation"                               │
└────────────────────────────────────────────────────────────┘
```

**Components**:
1. **Component Selector** (Cascading Dropdowns)
   - First dropdown: Unit ID
   - Second dropdown: Component (populated from selected unit's components)
   - Auto-load on selection

2. **Signal Evaluation Table** (Dash DataTable)
   - Source: `classified.parquet` → `signals_evaluation` field
   - Columns:
     - Signal name
     - Status badge
     - Window score (numeric, 2 decimals)
     - Severity (mapped: 0.0, 0.3, 1.0)
     - Weight (data quality: 0.0 or 1.0)
     - Anomaly percentage (% of readings outside P5-P95)
     - Action icon (🔍 for detail modal)
   - Sortable by window score or severity
   - Conditional formatting:
     - Row color by status
     - Gray out signals with weight=0.0 (insufficient data)

3. **Weekly Distribution Boxplots** (Plotly Box - Horizontal)
   - By default, show **all signals** for the selected component
   - Multiple facets/subplots (one per signal)
   - Each signal shows historical weekly distributions:
     - Last 5-8 weeks displayed as horizontal boxes
     - Current evaluation week highlighted with status color
     - Historical weeks in gradient color (recent → older)
   - **State Filter** (Radio buttons or Dropdown):
     - Filter: `All`, `Operacional`, `Ralenti`, `Apagada`
     - Filters data shown in boxplots by `EstadoMaquina`
   - Reference Line:
     - Black dashed vertical line at overall mean across all weeks
   - Color scheme:
     - Current week: Red (Anormal), Orange (Alerta), Green (Normal)
     - Historical weeks: Blue gradient (darker = more recent)
   - Hover: Show week label, Q1, Median, Q3, Min, Max, Sample count
   - Layout: Horizontal orientation for better week comparison

4. **AI Recommendation Panel** (Phase 2)
   - Display LLM-generated maintenance recommendation
   - Collapsible panel
   - Copy-to-clipboard button

---

### Tab 4: Limits

**Purpose**: Display sensor thresholds and baseline percentiles

**Layout**:

```
┌────────────────────────────────────────────────────────────┐
│  Baseline Configuration                                    │
│  Baseline Version: [20260201 ▼]  Training Window: 90 days │
│  Training Period: 2025-11-03 to 2026-02-01                │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  Percentile Thresholds Table                               │
│  [Filter: Unit ▼] [Signal ▼] [State ▼]  [Export CSV]     │
│                                                            │
│  Unit  │ Signal     │ State  │ P2  │ P5  │ P95 │ P98 │N  │
│  ──────────────────────────────────────────────────────── │
│  CAT797│EngCoolTemp │ Oper.  │ 75  │ 78  │ 95  │ 98  │850│
│  CAT797│EngCoolTemp │ Ralenti│ 65  │ 68  │ 85  │ 88  │420│
│  CAT797│EngOilPres  │ Oper.  │ 45  │ 48  │ 72  │ 75  │850│
│  ...                                                       │
│  N = Sample count in training window                      │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│  Threshold Distribution Histogram                          │
│  Signal: [EngCoolTemp ▼]  State: [Operacional ▼]         │
│                                                            │
│  Count                                                     │
│    │                                                       │
│ 80 │        ███████                                        │
│ 60 │    ███████████████                                    │
│ 40 │  █████████████████████                                │
│ 20 │██████████████████████████████                         │
│  0 │────────────────────────────────────                  │
│       P2  P5         P95 P98                              │
│       65  70   ...   90  95  (°C)                         │
│                                                            │
│  Shaded regions: Red (<P2, >P98), Yellow (P2-P5, P95-P98)│
└────────────────────────────────────────────────────────────┘
```

**Components**:
1. **Baseline Metadata Display**
   - Show active baseline version
   - Training window parameters
   - Date range used for percentile calculation

2. **Thresholds Table** (Dash DataTable)
   - Source: `baselines/baseline_YYYYMMDD.parquet`
   - All columns visible
   - Filters: Unit, Signal, Operational State
   - Export functionality
   - Pagination for large datasets

3. **Distribution Histogram** (Plotly Histogram)
   - Show actual distribution of training data
   - Overlay percentile lines (P2, P5, P95, P98)
   - Color-coded zones:
     - Red: <P2 and >P98 (Alarm)
     - Yellow: P2-P5 and P95-P98 (Alert)
     - Green: P5-P95 (Normal)
   - Single signal selection

---

## 📊 Visualization Specifications

### 1. Fleet Status Table
**Library**: Dash DataTable  
**Data**: `machine_status.parquet`

```python
ddt.DataTable(
    id='fleet-status-table',
    columns=[
        {'name': 'Unit ID', 'id': 'unit_id', 'presentation': 'markdown'},
        {'name': 'Status', 'id': 'overall_status'},
        {'name': 'Priority', 'id': 'priority_score', 'type': 'numeric'},
        {'name': 'Anormal', 'id': 'components_anormal', 'type': 'numeric'},
        {'name': 'Alerta', 'id': 'components_alerta', 'type': 'numeric'},
        {'name': 'Normal', 'id': 'components_normal', 'type': 'numeric'},
    ],
    data=df.to_dict('records'),
    sort_action='native',
    filter_action='native',
    page_size=20,
    style_data_conditional=[
        {
            'if': {'filter_query': '{overall_status} = "Anormal"'},
            'backgroundColor': '#ffcccc',
            'color': 'darkred'
        },
        {
            'if': {'filter_query': '{overall_status} = "Alerta"'},
            'backgroundColor': '#fff4cc',
            'color': 'darkorange'
        },
    ],
)
```

---

### 2. Component Radar Chart
**Library**: Plotly Scatterpolar  
**Data**: `component_details` from `machine_status.parquet`

```python
fig = go.Figure(data=go.Scatterpolar(
    r=[comp['score'] for comp in component_details],
    theta=[comp['component'] for comp in component_details],
    fill='toself',
    name='Component Scores',
    line=dict(color='crimson'),
    marker=dict(size=8)
))

fig.update_layout(
    polar=dict(
        radialaxis=dict(
            visible=True,
            range=[0, 1.0],  # Updated range for severity-based scoring
            tickvals=[0.0, 0.15, 0.45, 0.7, 1.0],
            ticktext=['Normal', 'Threshold', 'Alerta', 'Critical', 'Max']
        )
    ),
    showlegend=True
)
```

**Key Features**:
- Radial axis: 0 (center) to 1.0 (outer edge)
- Color zones via shape annotations:
  - Green circle: 0-0.15 (Normal range)
  - Yellow ring: 0.15-0.45 (Alerta range)
  - Red ring: 0.45-1.0 (Anormal range)
- Hoverlabel: Show component name, exact score, status, coverage%

---

### 3. Signal Distribution Boxplot
**Library**: Plotly Box  
**Data**: Silver layer (week partition) + baseline percentiles

```python
fig = go.Figure()

# Baseline box (historical)
fig.add_trace(go.Box(
    name='Baseline',
    q1=[baseline['p5']],
    median=[(baseline['p5'] + baseline['p95']) / 2],
    q3=[baseline['p95']],
    lowerfence=[baseline['p2']],
    upperfence=[baseline['p98']],
    marker_color='lightblue',
    width=0.4
))

# Current week box (observed)
fig.add_trace(go.Box(
    name='Current Week',
    y=current_week_readings,
    marker_color='crimson' if status == 'Anormal' else 'orange' if status == 'Alerta' else 'green',
    width=0.4
))

fig.update_layout(
    title=f'{signal_name} Distribution: Baseline vs. Current Week',
    yaxis_title='Signal Value',
    showlegend=True
)

# Add horizontal lines for P2, P5, P95, P98
for percentile, value, color in [('P2', baseline['p2'], 'red'), 
                                   ('P5', baseline['p5'], 'orange'),
                                   ('P95', baseline['p95'], 'orange'),
                                   ('P98', baseline['p98'], 'red')]:
    fig.add_hline(y=value, line_dash='dash', line_color=color, 
                  annotation_text=percentile, annotation_position='right')
```

**Key Features**:
- Side-by-side comparison
- Baseline box uses percentiles as quartiles (visual approximation)
- Current week box uses actual readings
- Threshold lines clearly marked
- Color indicates severity

---

### 4. Signal Time Series with Thresholds
**Library**: Plotly Scatter  
**Data**: Silver layer (week partition) + baseline percentiles

```python
fig = go.Figure()

# Add threshold bands as filled areas
fig.add_hrect(y0=baseline['p98'], y1=max_value, fillcolor='red', opacity=0.2, layer='below', line_width=0)
fig.add_hrect(y0=baseline['p95'], y1=baseline['p98'], fillcolor='orange', opacity=0.2, layer='below', line_width=0)
fig.add_hrect(y0=baseline['p5'], y1=baseline['p95'], fillcolor='green', opacity=0.1, layer='below', line_width=0)
fig.add_hrect(y0=baseline['p2'], y1=baseline['p5'], fillcolor='orange', opacity=0.2, layer='below', line_width=0)
fig.add_hrect(y0=min_value, y1=baseline['p2'], fillcolor='red', opacity=0.2, layer='below', line_width=0)

# Add actual readings
fig.add_trace(go.Scatter(
    x=df['Fecha'],
    y=df[signal_name],
    mode='lines+markers',
    name='Readings',
    line=dict(color='blue', width=2),
    marker=dict(size=4)
))

# Add percentile lines
for p, val in [('P98', baseline['p98']), ('P95', baseline['p95']), 
               ('P5', baseline['p5']), ('P2', baseline['p2'])]:
    fig.add_hline(y=val, line_dash='dot', line_color='gray', annotation_text=p)

fig.update_layout(
    title=f'{signal_name} Time Series - Week {week}/{year}',
    xaxis_title='Date',
    yaxis_title='Value',
    hovermode='x unified'
)
```

**Key Features**:
- Colored background zones for threshold bands
- Clear visual indication of when readings cross thresholds
- Time axis shows full evaluation window
- Hover shows exact timestamp and value

---

### 5. KPI Cards
**Library**: Plotly Indicator  
**Data**: Aggregated from `machine_status.parquet`

```python
fig = go.Figure(go.Indicator(
    mode='number+delta',
    value=components_anormal_count,
    title={'text': 'Anormal<br><span style="font-size:0.8em">Components</span>'},
    delta={'reference': previous_week_count, 'relative': False},
    domain={'x': [0, 1], 'y': [0, 1]},
    number={'font': {'size': 48, 'color': 'darkred'}}
))

fig.update_layout(
    height=150,
    margin=dict(t=30, b=0, l=10, r=10)
)
```

**Key Features**:
- Large number for immediate impact
- Delta shows change from previous week (Phase 2)
- Color-coded by severity
- Compact layout for dashboard header

---

## 🖱️ Interaction Patterns

### Navigation Flow

```
Fleet Overview (Tab 1)
  │
  ├─→ Click unit row ─────────→ Machine Detail (Tab 2)
  │                                  │
  │                                  ├─→ Click component ──→ Component Detail (Tab 3)
  │                                  │                            │
  │                                  │                            └─→ Click signal icon ──→ Signal Modal
  │                                  │
  │                                  └─→ Click "View Time Series" ──→ Signal Modal
  │
  └─→ Click "Limits" menu ──→ Limits (Tab 4)
```

### Signal Detail Modal

**Trigger**: Click 🔍 icon in Component Detail table

**Content**:
- Signal name and current status
- **Time series plot** with threshold bands (P2, P5, P95, P98)
- **Weekly boxplot distribution**:
  - Horizontal boxplots for last 8-12 weeks
  - Current week highlighted by status color
  - State filter available (All/Operacional/Ralenti/Apagada)
  - Overall mean reference line
- **Summary statistics table**:
  - Current week: Min/Max/Mean/Median/Std
  - Historical weeks: Mean trend, variability
  - Baseline percentiles (P2, P5, P95, P98)
  - Anomaly percentage
  - Window score

**Actions**:
- Close modal
- Export plot as PNG
- Download data as CSV

### Filtering & Drill-Down

**Global Filters** (persist across tabs):
- Client selection (if multi-client)
- Week/Year selection (for historical review)

**Tab-Specific Filters**:
- Fleet Overview: Status filter, search box
- Machine Detail: Unit selector
- Component Detail: Unit + Component selector
- Limits: Unit, Signal, State filters

**Breadcrumb Navigation**:
```
Home > Monitoring > Telemetry > Machine Detail > CAT797-001 > Engine
```
- Clickable breadcrumbs for quick back-navigation

---

## 🛠️ Technical Implementation Notes

### Plotly + Dash Stack

**Core Libraries**:
```python
dash==2.14.2
dash-bootstrap-components==1.5.0
plotly==5.18.0
pandas==2.1.4
```

**Layout Framework**:
- Use Dash Bootstrap Components for responsive grid
- 12-column layout system
- Mobile-friendly (collapsed tables on small screens)

### Performance Optimization

**Data Loading Strategy**:
1. Load `machine_status.parquet` once on dashboard init
2. Cache in dcc.Store component
3. Load `classified.parquet` only when Component Detail tab accessed
4. Load Silver layer data only for Signal Modal (on-demand)

**Callback Optimization**:
- Use `prevent_initial_call=True` where appropriate
- Implement `@dash.callback` with `Input`/`Output`/`State` carefully
- Avoid circular callbacks

**Large Dataset Handling**:
- Pagination in tables (page_size=20)
- Lazy loading for drill-downs
- Client-side sorting/filtering where possible

### State Management

**Use dcc.Store for**:
- Currently selected unit
- Currently selected component
- Current week/year filter
- Cached machine_status dataframe

**URL Routing**:
- Implement `dcc.Location` for shareable links
- Example: `/telemetry/machine/CAT797-001`
- Parse URL params to pre-select unit/component

### Styling

**Color Palette**:
- Normal: `#28a745` (green)
- Alerta: `#ffc107` (yellow/amber)
- Anormal: `#dc3545` (red)
- Background: `#f8f9fa` (light gray)
- Cards: `#ffffff` (white)

**Typography**:
- Headers: Roboto Bold, 18-24px
- Body: Roboto Regular, 14px
- Tables: Monospace for numeric columns

**Bootstrap Theme**:
- Use `dbc.themes.FLATLY` or `COSMO` for clean, professional look

### Accessibility

- Color-blind friendly palette (use patterns in addition to colors)
- Alt text for all plots
- Keyboard navigation support
- ARIA labels for interactive elements

---

## 📈 Success Metrics

**Dashboard Performance**:
- Page load time: <2 seconds for Fleet Overview
- Drill-down latency: <1 second for Machine/Component Detail
- Data refresh: <30 seconds for full pipeline run

**User Engagement**:
- Time to identify high-priority machine: <30 seconds
- Click depth to root cause signal: ≤3 clicks
- False positive feedback rate: <10%

**Business Impact**:
- Reduction in unplanned downtime
- Faster Mean Time To Repair (MTTR)
- Increased proactive maintenance interventions

---

## 🚀 Phased Rollout

### Phase 1 - MVP (Current Scope)
✅ Fleet Overview with sortable table  
✅ Machine Detail with component radar chart  
✅ Component Detail with signal evaluation table  
✅ Boxplot comparison for baseline validation  
✅ Limits tab with threshold display  

### Phase 2 - Enhanced Features
🔄 AI Recommendations per component  
🔄 Weekly status timeline (historical trend)  
🔄 Delta indicators in KPI cards (week-over-week)  
🔄 Export functionality for all visualizations  
🔄 Maintenance action logging integration  

### Phase 3 - Advanced Analytics
🔮 Predictive alerts (forecasting)  
🔮 Anomaly heatmaps (signals × time)  
🔮 Component health scores over time  
🔮 Fleet-wide signal correlation matrix  

---

## 📚 Related Documentation

- [Project Overview](project_overview.md) - Scoring methodology and architecture
- [Integration Plan](integration_plan.md) - Implementation phases
- [Programming Rules](programming_rules.md) - Code standards
- [Dashboard Overview](../general/dashboard_overview.md) - Platform architecture

---

## 📝 Version History

### Version 1.0.0 (February 2026)
- Initial dashboard proposal
- 4-tab layout design
- Plotly + Dash visualization specifications
- User journey and interaction patterns defined
