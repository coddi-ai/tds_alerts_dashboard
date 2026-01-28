# Dashboard Documentation

**Multi-Technical-Alerts - Complete Dashboard Specification**

---

## 📋 Table of Contents

1. [Dashboard Overview](#dashboard-overview)
2. [Tab 1: Limit Visualization](#tab-1--limit-visualization)
3. [Tab 2: Machine Status](#tab-2--machine-status)
4. [Tab 3: Report Detail](#tab-3--report-detail)
5. [Data Requirements](#data-requirements)
6. [Technical Implementation](#technical-implementation)
7. [User Workflows](#user-workflows)

---

## 🎯 Dashboard Overview

### **Purpose**

Provide interactive, multi-perspective visualization of fleet health for mining equipment based on oil analysis data.

### **Framework**

- **Frontend**: Dash (Python web framework)
- **Visualization**: Plotly (interactive charts)
- **Styling**: Dash Bootstrap Components
- **Deployment**: Local server or cloud deployment (Azure/AWS)

### **Access Control**

**Critical Requirement**: Client data isolation

```python
# Pre-filter data before dashboard rendering
if selected_client == 'CDA':
    df_dashboard = load_gold_layer('data/oil/to_consume/cda/')
elif selected_client == 'EMIN':
    df_dashboard = load_gold_layer('data/oil/to_consume/emin/')

# NEVER mix client data in queries or visualizations
```

### **Dashboard Layout**

```
┌─────────────────────────────────────────────────────────┐
│  Multi-Technical-Alerts - Fleet Oil Analysis Dashboard │
│  Client: [CDA ▼]                        Last Update: ... │
├─────────────────────────────────────────────────────────┤
│  [ 📊 Limit Visualization ]  [ 🚜 Machine Status ]     │
│  [ 📝 Report Detail ]                                   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│                 TAB CONTENT AREA                        │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 📊 Tab 1: 📊 Limit Visualization

### **Purpose**

Display Stewart Limits thresholds for transparency, audit, and threshold verification by engineers and technicians.

### **Primary Users**

- **Engineers**: Verify threshold calculations are reasonable
- **Quality Assurance**: Audit limit values
- **Technicians**: Understand why samples were flagged

---

### **Layout**

```
┌─────────────────────────────────────────────────────────┐
│  📊 Visualización de Límites de Stewart                 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Seleccionar Máquina: [camion ▼]                       │
│  Seleccionar Componente: [motor diesel ▼]              │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  Límites de Ensayos - camion - motor diesel            │
│                                                         │
│  ┌───────────────────────────────────────────────────┐ │
│  │ Essay               │ Normal │ Alerta │ Crítico  │ │
│  ├─────────────────────┼────────┼────────┼──────────┤ │
│  │ Hierro              │  30.0  │  45.0  │   60.0   │ │
│  │ Cobre               │  15.0  │  25.0  │   35.0   │ │
│  │ Silicio             │  17.0  │  30.0  │   45.0   │ │
│  │ Aluminio            │  10.0  │  18.0  │   25.0   │ │
│  │ Viscosidad @ 40°C   │ 135.0  │ 138.0  │  142.0   │ │
│  │ Contenido de Agua   │   0.1  │   0.3  │    0.5   │ │
│  │ ... (more essays)                                 │ │
│  └───────────────────────────────────────────────────┘ │
│                                                         │
│  Total Essays Monitored: 24                             │
│  Data Points Used for Calculation: 1,245 samples       │
│  Last Calculated: 2026-01-20 14:30:00                  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

### **Components**

#### **1. Machine Dropdown Filter**

```python
dcc.Dropdown(
    id='machine-dropdown',
    options=[{'label': m, 'value': m} for m in unique_machines],
    value=unique_machines[0],
    placeholder="Seleccionar máquina..."
)
```

**Data Source**: 
```python
unique_machines = list(stewart_limits[client].keys())
# Example: ['camion', 'pala', 'bulldozer']
```

---

#### **2. Component Dropdown Filter**

**Behavior**: Updates dynamically based on selected machine

```python
@app.callback(
    Output('component-dropdown', 'options'),
    Input('machine-dropdown', 'value')
)
def update_components(selected_machine):
    components = list(stewart_limits[client][selected_machine].keys())
    return [{'label': c, 'value': c} for c in components]
```

**Data Source**:
```python
components = stewart_limits['CDA']['camion'].keys()
# Example: ['motor diesel', 'transmision', 'hidraulico', 'mando final']
```

---

#### **3. Stewart Limits Table**

**Interactive Plotly Table**:

```python
import plotly.graph_objects as go

fig = go.Figure(data=[go.Table(
    header=dict(
        values=['Essay', 'Normal', 'Alerta', 'Crítico'],
        fill_color='paleturquoise',
        align='left',
        font=dict(size=14, color='black', family='Arial')
    ),
    cells=dict(
        values=[
            df_limits['essayName'].tolist(),
            df_limits['threshold_normal'].tolist(),
            df_limits['threshold_alert'].tolist(),
            df_limits['threshold_critic'].tolist()
        ],
        fill_color='lavender',
        align='left',
        font=dict(size=12),
        format=[None, '.1f', '.1f', '.1f']  # 1 decimal place
    )
)])

fig.update_layout(
    title=f"Stewart Limits - {machine} - {component}",
    height=600
)
```

**Columns**:
- **Essay**: Essay name (e.g., "Hierro", "Cobre", "Viscosidad @ 40°C")
- **Normal**: 90th percentile threshold
- **Alerta**: 95th percentile threshold
- **Crítico**: 98th percentile threshold

**Sorting**: Alphabetical by essay name (default), allow user to sort by any column

---

### **Data Requirements**

**Primary File**: `processed/stewart_limits.json`

**Access Pattern**:
```python
limits = stewart_limits[client][machine][component]
# Returns: {'Hierro': {'threshold_normal': 30, ...}, 'Cobre': {...}, ...}

# Convert to DataFrame for table display
df_limits = pd.DataFrame([
    {
        'essayName': essay,
        'threshold_normal': data['threshold_normal'],
        'threshold_alert': data['threshold_alert'],
        'threshold_critic': data['threshold_critic']
    }
    for essay, data in limits.items()
])
```

**Alternative**: If using Parquet format (recommended)
```python
df_limits = pd.read_parquet('processed/stewart_limits.parquet')
df_limits = df_limits[
    (df_limits['client'] == selected_client) &
    (df_limits['machineName'] == selected_machine) &
    (df_limits['componentName'] == selected_component)
]
```

---

### **Interactions**

1. **User selects machine** → Component dropdown updates
2. **User selects component** → Table updates with limits
3. **User hovers over row** → Highlight row (Plotly default)
4. **Optional**: Export to Excel button

---

## 🚜 Tab 2: 🚜 Machine Status

### **Purpose**

Provide fleet-wide health monitoring, prioritization, and actionable insights for maintenance planning.

### **Primary Users**

- **Executives**: Fleet health overview
- **Maintenance Managers**: Prioritization for work orders
- **Operations**: Daily readiness assessment

---

### **Layout Overview**

```
┌─────────────────────────────────────────────────────────┐
│  🚜 Estado General de la Flota                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  SECTION 1: Distribución Estado General por Máquina    │
│  (Pie Chart + Priority Table)                           │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  SECTION 2: Detalle Estado General por Máquina         │
│  (Detailed Machine Table)                               │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  SECTION 3: Distribución de Estados por Componente     │
│  (Report-level Pie + Histogram)                         │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  SECTION 4: Detalle Estado General por Componente      │
│  (Component Detail Table)                               │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

### **Section 1: Distribución del Estado General por Máquina**

#### **Purpose**: High-level fleet health summary at machine level

#### **Layout**:

```
┌──────────────────────────────────────┬────────────────────────┐
│  📊 Estado de Máquinas              │  🔴 Máquinas Prioritarias│
│                                      │                        │
│       ┌─────────────┐                │  Rank │ ID  │ Puntos  │
│       │   Normal    │                │  ───────────────────── │
│       │    65%      │                │   1   │ CDA_003 │  8  │
│       ├─────────────┤                │   2   │ CDA_012 │  6  │
│       │   Alerta    │                │   3   │ CDA_007 │  5  │
│       │    25%      │                │   4   │ CDA_019 │  4  │
│       ├─────────────┤                │   5   │ CDA_001 │  4  │
│       │   Anormal   │                │   6   │ CDA_015 │  3  │
│       │    10%      │                │   7   │ CDA_022 │  3  │
│       └─────────────┘                │   8   │ CDA_009 │  2  │
│                                      │   9   │ CDA_011 │  2  │
│  Total: 100 máquinas                │  10   │ CDA_005 │  2  │
│                                      │                        │
└──────────────────────────────────────┴────────────────────────┘
```

#### **Component 1A: Pie Chart - Machine Status Distribution**

```python
import plotly.express as px

# Data preparation
status_counts = df_machine_status['machineStatus'].value_counts()

fig = px.pie(
    values=status_counts.values,
    names=status_counts.index,
    title="Distribución de Estado por Máquina",
    color=status_counts.index,
    color_discrete_map={
        'Normal': '#28a745',   # Green
        'Alerta': '#ffc107',   # Yellow
        'Anormal': '#dc3545'   # Red
    },
    hole=0.4  # Donut chart
)

fig.update_traces(
    textposition='inside',
    textinfo='percent+label',
    hovertemplate='<b>%{label}</b><br>Máquinas: %{value}<br>Porcentaje: %{percent}<extra></extra>'
)

fig.update_layout(
    height=400,
    showlegend=True,
    legend=dict(orientation="v", x=1.1, y=0.5)
)
```

**Data Source**: `to_consume/{client}/machine_status_current.parquet`

```python
df_machine_status = pd.read_parquet(
    f'to_consume/{client}/machine_status_current.parquet'
)
status_counts = df_machine_status['machineStatus'].value_counts()
```

---

#### **Component 1B: Priority Table**

**Purpose**: Identify machines requiring immediate attention

```python
# Sort by totalNumericStatus (descending) and get top 10
df_priority = df_machine_status.nlargest(10, 'totalNumericStatus')[
    ['unitId', 'totalNumericStatus', 'machineStatus']
]

fig = go.Figure(data=[go.Table(
    header=dict(
        values=['Rank', 'ID Equipo', 'Puntos', 'Estado'],
        fill_color='#dc3545',  # Red header
        font=dict(color='white', size=14),
        align='left'
    ),
    cells=dict(
        values=[
            list(range(1, len(df_priority) + 1)),
            df_priority['unitId'].tolist(),
            df_priority['totalNumericStatus'].tolist(),
            df_priority['machineStatus'].tolist()
        ],
        fill_color=[
            ['#ffebee'] * len(df_priority),  # Light red background
        ],
        align='left',
        font=dict(size=12)
    )
)])
```

**Interactive Feature**: Click row → Navigate to Machine Detail or Report Detail tab

---

### **Section 2: Detalle Estado General por Máquina**

#### **Purpose**: Complete inventory of all machines with status details

#### **Layout**:

```
┌───────────────────────────────────────────────────────────────────────────────┐
│  🎯 Detalle Completo de Máquinas                                              │
│  Filter: [All Statuses ▼]   Search: [___________]                            │
├───────────────────────────────────────────────────────────────────────────────┤
│  ID      │ Máquina │ Estado  │ #Comp │ Última Muestra │ Resumen              │
├──────────┼─────────┼─────────┼───────┼────────────────┼──────────────────────┤
│ CDA_001  │ camion  │ Anormal │   4   │ 2026-01-25     │ 2 Anormal: [motor   │
│          │         │         │       │                │ diesel, transmision] │
│          │         │         │       │                │ 1 Alerta: [hidraul.] │
│          │         │         │       │                │ 1 Normal: [mando f.] │
├──────────┼─────────┼─────────┼───────┼────────────────┼──────────────────────┤
│ CDA_002  │ camion  │ Normal  │   3   │ 2026-01-24     │ 3 Normal: [motor    │
│          │         │         │       │                │ diesel, transmision, │
│          │         │         │       │                │ hidraulico]          │
├──────────┼─────────┼─────────┼───────┼────────────────┼──────────────────────┤
│ ... (paginated, 20 rows per page)                                             │
└───────────────────────────────────────────────────────────────────────────────┘
```

#### **Table Implementation**:

```python
import dash_table

dash_table.DataTable(
    id='machine-detail-table',
    columns=[
        {'name': 'ID Equipo', 'id': 'unitId'},
        {'name': 'Tipo Máquina', 'id': 'machineName'},
        {'name': 'Estado', 'id': 'machineStatus'},
        {'name': '# Componentes', 'id': 'componentsTotal'},
        {'name': 'Última Muestra', 'id': 'lastSampleDate'},
        {'name': 'Resumen', 'id': 'componentSummary'}
    ],
    data=df_machine_detail.to_dict('records'),
    
    # Styling
    style_data_conditional=[
        {
            'if': {'filter_query': '{machineStatus} = "Anormal"'},
            'backgroundColor': '#ffebee',  # Light red
            'color': '#c62828'
        },
        {
            'if': {'filter_query': '{machineStatus} = "Alerta"'},
            'backgroundColor': '#fff8e1',  # Light yellow
            'color': '#f57f17'
        }
    ],
    
    # Features
    filter_action='native',  # Enable column filtering
    sort_action='native',    # Enable sorting
    page_size=20,            # Pagination
    
    # Export
    export_format='xlsx',
    export_headers='display'
)
```

#### **Data Preparation**:

```python
# Create componentSummary field
def create_component_summary(unitId):
    components = df_classified[df_classified['unitId'] == unitId]
    latest_components = components.loc[components.groupby('componentName')['sampleDate'].idxmax()]
    
    summary_parts = []
    for status in ['Anormal', 'Alerta', 'Normal']:
        comps = latest_components[latest_components['reportStatus'] == status]['componentName'].tolist()
        if comps:
            summary_parts.append(f"{len(comps)} {status}: [{', '.join(comps)}]")
    
    return ' | '.join(summary_parts)

df_machine_detail['componentSummary'] = df_machine_detail['unitId'].apply(create_component_summary)
```

**Data Source**: `to_consume/{client}/machine_status_current.parquet` + join with `classified_reports.parquet` for component details

---

### **Section 3: Distribución de Estados por Componente**

#### **Purpose**: Report-level distribution (vs. machine-level in Section 1)

#### **Layout**:

```
┌──────────────────────────────────────┬────────────────────────────────┐
│  📈 Estado de Reportes              │  📊 Reportes por Componente    │
│                                      │                                │
│       ┌─────────────┐                │    motor diesel ████████░░░    │
│       │   Normal    │                │    transmision  ████████░░░    │
│       │    70%      │                │    hidraulico   ████████░░░    │
│       ├─────────────┤                │    mando final  ████████░░░    │
│       │   Alerta    │                │                                │
│       │    20%      │                │    ████ Anormal                │
│       ├─────────────┤                │    ████ Alerta                 │
│       │   Anormal   │                │    ████ Normal                 │
│       │    10%      │                │                                │
│       └─────────────┘                │                                │
│                                      │                                │
│  Total: 500 reportes                │                                │
│                                      │                                │
└──────────────────────────────────────┴────────────────────────────────┘
```

#### **Component 3A: Pie Chart - Report Status Distribution**

```python
# Count reports by status
report_counts = df_classified['reportStatus'].value_counts()

fig = px.pie(
    values=report_counts.values,
    names=report_counts.index,
    title="Distribución de Reportes por Estado",
    color=report_counts.index,
    color_discrete_map={
        'Normal': '#28a745',
        'Alerta': '#ffc107',
        'Anormal': '#dc3545'
    }
)
```

**Data Source**: `to_consume/{client}/classified_reports.parquet`

---

#### **Component 3B: Stacked Histogram - Reports per Component**

```python
import plotly.graph_objects as go

# Aggregate data
df_component_status = df_classified.groupby(['componentName', 'reportStatus']).size().reset_index(name='count')

# Pivot for stacking
df_pivot = df_component_status.pivot(index='componentName', columns='reportStatus', values='count').fillna(0)

fig = go.Figure()

# Add bars for each status
for status in ['Normal', 'Alerta', 'Anormal']:
    if status in df_pivot.columns:
        fig.add_trace(go.Bar(
            name=status,
            x=df_pivot.index,
            y=df_pivot[status],
            marker_color={'Normal': '#28a745', 'Alerta': '#ffc107', 'Anormal': '#dc3545'}[status]
        ))

fig.update_layout(
    barmode='stack',
    title="Distribución de Reportes por Componente y Estado",
    xaxis_title="Componente",
    yaxis_title="Número de Reportes",
    legend_title="Estado",
    height=500,
    xaxis_tickangle=-45
)
```

**Interactivity**: 
- Click component bar → Filter Section 4 table
- Hover → Show exact counts

---

### **Section 4: Detalle Estado General por Componente**

#### **Purpose**: Latest status and AI recommendations for each component

#### **Layout**:

```
┌───────────────────────────────────────────────────────────────────────────────┐
│  🎯 Detalle por Componente                                                    │
│  Filter Component: [All ▼]   Status: [All ▼]                                 │
├───────────────────────────────────────────────────────────────────────────────┤
│  ID      │ Componente     │ Última Muestra │ Estado  │ Recomendación AI      │
├──────────┼────────────────┼────────────────┼─────────┼───────────────────────┤
│ CDA_001  │ motor diesel   │ 2026-01-25     │ Anormal │ Se detecta concentra- │
│          │                │                │         │ ción de metales de    │
│          │                │                │         │ desgaste por Fierro...│
│          │                │                │         │ [View Full ⤢]         │
├──────────┼────────────────┼────────────────┼─────────┼───────────────────────┤
│ CDA_001  │ transmision    │ 2026-01-25     │ Alerta  │ Niveles de desgaste...│
│          │                │                │         │ [View Full ⤢]         │
├──────────┼────────────────┼────────────────┼─────────┼───────────────────────┤
│ ... (paginated, expandable rows)                                              │
└───────────────────────────────────────────────────────────────────────────────┘
```

#### **Table with Expandable Rows**:

```python
dash_table.DataTable(
    id='component-detail-table',
    columns=[
        {'name': 'ID Equipo', 'id': 'unitId'},
        {'name': 'Componente', 'id': 'componentName'},
        {'name': 'Última Muestra', 'id': 'lastSampleDate'},
        {'name': 'Estado', 'id': 'reportStatus'},
        {'name': 'Recomendación (preview)', 'id': 'aiRecommendationPreview'}
    ],
    data=df_component_detail.to_dict('records'),
    
    # Row expansion for full recommendation
    row_selectable='single',
    
    style_data_conditional=[
        {
            'if': {'filter_query': '{reportStatus} = "Anormal"'},
            'backgroundColor': '#ffebee'
        },
        {
            'if': {'filter_query': '{reportStatus} = "Alerta"'},
            'backgroundColor': '#fff8e1'
        }
    ],
    
    page_size=20,
    filter_action='native',
    sort_action='native'
)

# Callback for row expansion
@app.callback(
    Output('recommendation-modal', 'is_open'),
    Output('recommendation-modal', 'children'),
    Input('component-detail-table', 'selected_rows')
)
def show_full_recommendation(selected_rows):
    if selected_rows:
        row_data = df_component_detail.iloc[selected_rows[0]]
        return True, dcc.Markdown(row_data['aiRecommendation'])
    return False, ""
```

#### **Data Preparation**:

```python
# Get latest report per component
df_component_detail = df_classified.loc[
    df_classified.groupby(['unitId', 'componentName'])['sampleDate'].idxmax()
][['unitId', 'componentName', 'sampleDate', 'reportStatus', 'aiRecommendation']]

# Create preview (first 100 chars)
df_component_detail['aiRecommendationPreview'] = df_component_detail['aiRecommendation'].str[:100] + '...'
```

**Data Source**: `to_consume/{client}/classified_reports.parquet`

---

### **Data Requirements for Tab 2**

| Section | Primary File | Columns Needed |
|---------|-------------|----------------|
| Section 1 | `machine_status_current.parquet` | `machineStatus`, `totalNumericStatus`, `unitId` |
| Section 2 | `machine_status_current.parquet` + `classified_reports.parquet` | All columns + component details |
| Section 3 | `classified_reports.parquet` | `reportStatus`, `componentName` |
| Section 4 | `classified_reports.parquet` | `unitId`, `componentName`, `sampleDate`, `reportStatus`, `aiRecommendation` |

---

## 📝 Tab 3: 📝 Report Detail

### **Purpose**

Deep-dive analysis of individual oil samples with multi-dimensional visualizations and AI insights.

### **Primary Users**

- **Technicians**: Understand specific sample issues
- **Engineers**: Analyze essay patterns and trends
- **Maintenance planners**: Historical comparison for intervention timing

---

### **Layout Overview**

```
┌─────────────────────────────────────────────────────────┐
│  📝 Detalle de Reporte                                   │
│  Seleccionar Equipo: [CDA_001 ▼]                        │
│  Seleccionar Muestra: [LAB123456 - 2026-01-25 ▼]       │
├─────────────────────────────────────────────────────────┤
│  SECTION 1: Análisis del Reporte                        │
│  (Radar Charts + Raw Values Table)                      │
├─────────────────────────────────────────────────────────┤
│  SECTION 2: Recomendaciones de Mantenimiento            │
│  (AI Text Display)                                       │
├─────────────────────────────────────────────────────────┤
│  SECTION 3: Evolución Temporal                          │
│  (Time Series Charts)                                    │
├─────────────────────────────────────────────────────────┤
│  SECTION 4: Comparación con Reportes Anteriores         │
│  (Comparison Table)                                      │
└─────────────────────────────────────────────────────────┘
```

---

### **Section 1: Análisis del Reporte**

#### **Component 1A: Radar Charts by GroupElement**

**Purpose**: Visualize essay values against thresholds, grouped by essay category

**GroupElement Categories** (from `essays_elements.xlsx`):
- **Metales de Desgaste**: Hierro, Cobre, Cromo, Aluminio, Estaño, Plomo
- **Contaminantes**: Silicio, Sodio, Potasio
- **Aditivos**: Zinc, Bario, Boro, Calcio, Molibdeno, Magnesio, Fósforo
- **Propiedades Físicas**: Viscosidad @ 40°C, Viscosidad @ 100°C, TBN, TAN
- **Contaminación Fluidos**: Contenido de Agua, Dilución por Combustible

**Layout**: One radar chart per GroupElement

```
┌─────────────────────────────────────────────────────────┐
│  Metales de Desgaste          │  Contaminantes          │
│                               │                         │
│        Hierro                 │        Silicio          │
│          /\                   │          /\             │
│         /  \                  │         /  \            │
│     Estaño  Cobre             │     Sodio   Potasio     │
│        |    |                 │        |    |           │
│     Aluminio-Cromo            │                         │
│                               │                         │
├───────────────────────────────┴─────────────────────────┤
│  Propiedades Físicas          │  Contaminación Fluidos  │
│                               │                         │
│     Viscosidad@40             │    Agua  Combustible    │
│          /\                   │      \    /             │
│         /  \                  │       \  /              │
│      TBN    TAN               │                         │
│        \    /                 │                         │
│    Viscosidad@100             │                         │
│                               │                         │
└─────────────────────────────────────────────────────────┘
```

#### **Radar Chart Implementation**:

```python
import plotly.graph_objects as go

def create_radar_chart(sample_data, limits, group_element, essays_in_group):
    """
    Create radar chart for one GroupElement
    
    Args:
        sample_data: Series with essay values for one sample
        limits: Dict with Stewart Limits
        group_element: Category name (e.g., "Metales de Desgaste")
        essays_in_group: List of essay names in this category
    """
    # Filter essays that have values in this sample
    essays_with_data = [e for e in essays_in_group if pd.notna(sample_data.get(e))]
    
    if not essays_with_data:
        return None  # Skip empty categories
    
    # Extract values and limits
    values = [sample_data[e] for e in essays_with_data]
    normal_limits = [limits.get(e, {}).get('threshold_normal', 0) for e in essays_with_data]
    alert_limits = [limits.get(e, {}).get('threshold_alert', 0) for e in essays_with_data]
    critic_limits = [limits.get(e, {}).get('threshold_critic', 0) for e in essays_with_data]
    
    # Create figure
    fig = go.Figure()
    
    # Add threshold lines
    fig.add_trace(go.Scatterpolar(
        r=normal_limits + [normal_limits[0]],  # Close the loop
        theta=essays_with_data + [essays_with_data[0]],
        fill='toself',
        fillcolor='rgba(40, 167, 69, 0.1)',  # Light green
        line=dict(color='#28a745', dash='dot'),
        name='Límite Normal'
    ))
    
    fig.add_trace(go.Scatterpolar(
        r=alert_limits + [alert_limits[0]],
        theta=essays_with_data + [essays_with_data[0]],
        fill='toself',
        fillcolor='rgba(255, 193, 7, 0.1)',  # Light yellow
        line=dict(color='#ffc107', dash='dot'),
        name='Límite Alerta'
    ))
    
    fig.add_trace(go.Scatterpolar(
        r=critic_limits + [critic_limits[0]],
        theta=essays_with_data + [essays_with_data[0]],
        fill='toself',
        fillcolor='rgba(220, 53, 69, 0.1)',  # Light red
        line=dict(color='#dc3545', dash='dot'),
        name='Límite Crítico'
    ))
    
    # Add actual values
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]],
        theta=essays_with_data + [essays_with_data[0]],
        fill='toself',
        fillcolor='rgba(0, 123, 255, 0.3)',  # Blue
        line=dict(color='#007bff', width=3),
        name='Valores Actuales',
        marker=dict(size=8)
    ))
    
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, max(max(critic_limits), max(values)) * 1.1]
            )
        ),
        showlegend=True,
        title=f"{group_element}",
        height=400
    )
    
    return fig

# Generate all radar charts
df_essays_grouped = essays.groupby('GroupElement')['ElementNameSpanish'].apply(list).to_dict()

radar_charts = []
for group, essays_list in df_essays_grouped.items():
    fig = create_radar_chart(
        sample_data=selected_sample,
        limits=limits[client][machine][component],
        group_element=group,
        essays_in_group=essays_list
    )
    if fig:
        radar_charts.append(dcc.Graph(figure=fig))

# Layout in grid (2 columns)
layout = html.Div([
    html.Div(radar_charts, style={'display': 'grid', 'grid-template-columns': '1fr 1fr', 'gap': '20px'})
])
```

---

#### **Component 1B: Raw Values Table**

**Purpose**: Detailed numeric view of all essays

```
┌───────────────────────────────────────────────────────────────────┐
│  Essay                        │ Valor │ Normal │ Alerta │ Crítico │
├───────────────────────────────┼───────┼────────┼────────┼─────────┤
│ Hierro                        │ 55.2  │  30.0  │  45.0  │   60.0  │ ⚠️
│ Cobre                         │ 28.1  │  15.0  │  25.0  │   35.0  │ ⚠️
│ Silicio                       │ 12.5  │  17.0  │  30.0  │   45.0  │ ✅
│ Viscosidad cinemática @ 40°C  │ 152.3 │ 135.0  │ 138.0  │  142.0  │ 🔴
│ Contenido de Agua             │  0.4  │   0.1  │   0.3  │    0.5  │ ⚠️
│ ... (all essays with values)                                       │
└───────────────────────────────────────────────────────────────────┘

Legend: ✅ Normal  ⚠️ Alerta/Marginal  🔴 Crítico
```

```python
# Add status icon column
def get_status_icon(value, normal, alert, critic):
    if pd.isna(value):
        return ''
    elif value >= critic:
        return '🔴'
    elif value >= alert:
        return '⚠️'
    elif value >= normal:
        return '⚠️'
    else:
        return '✅'

df_essay_table['Status'] = df_essay_table.apply(
    lambda row: get_status_icon(row['Valor'], row['Normal'], row['Alerta'], row['Crítico']),
    axis=1
)

dash_table.DataTable(
    columns=[
        {'name': 'Essay', 'id': 'essayName'},
        {'name': 'Valor', 'id': 'value', 'type': 'numeric', 'format': {'specifier': '.2f'}},
        {'name': 'Normal', 'id': 'normal', 'type': 'numeric', 'format': {'specifier': '.1f'}},
        {'name': 'Alerta', 'id': 'alert', 'type': 'numeric', 'format': {'specifier': '.1f'}},
        {'name': 'Crítico', 'id': 'critic', 'type': 'numeric', 'format': {'specifier': '.1f'}},
        {'name': 'Estado', 'id': 'status'}
    ],
    data=df_essay_table.to_dict('records'),
    
    style_data_conditional=[
        {'if': {'filter_query': '{status} = "🔴"'}, 'backgroundColor': '#ffebee'},
        {'if': {'filter_query': '{status} = "⚠️"'}, 'backgroundColor': '#fff8e1'}
    ],
    
    sort_action='native'
)
```

---

### **Section 2: Recomendaciones de Mantenimiento**

#### **Layout**:

```
┌─────────────────────────────────────────────────────────┐
│  🤖 Recomendación del Sistema Experto                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Estado del Reporte: [Anormal]                          │
│  Severidad: 8 puntos  │  Essays Afectados: 3            │
│                                                         │
│  ─────────────────────────────────────────────────────  │
│                                                         │
│  Se detecta concentración de metales de desgaste por    │
│  Fierro 55.2 ppm y Cobre 28.1 ppm, evidenciando        │
│  posible abrasión excesiva en cojinetes y bujes de      │
│  turbo. Silicio 12.5 ppm señala niveles normales.      │
│  Análisis fisicoquímico detecta Viscosidad cinemática   │
│  @ 40°C de 152.3 cSt sobre límite crítico,              │
│  evidenciando posible degradación térmica del           │
│  lubricante o contaminación con fluido de mayor         │
│  viscosidad.                                            │
│                                                         │
│  Se recomienda priorizar cambio de lubricante y         │
│  elementos filtrantes, evaluar presiones en sistema     │
│  de lubricación y saturación temprana de filtros,       │
│  mantener seguimiento riguroso cada 50 hrs.             │
│                                                         │
│  ─────────────────────────────────────────────────────  │
│                                                         │
│  Generado: 2026-01-25 14:30:00  │  Modelo: gpt-4o-mini │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

#### **Implementation**:

```python
html.Div([
    html.H3("🤖 Recomendación del Sistema Experto", className="mb-3"),
    
    # Status badges
    html.Div([
        dbc.Badge(f"Estado: {sample['reportStatus']}", color='danger' if sample['reportStatus'] == 'Anormal' else 'warning', className="me-2"),
        dbc.Badge(f"Severidad: {sample['severityScore']} puntos", color='info', className="me-2"),
        dbc.Badge(f"Essays Afectados: {sample['essaysBreached']}", color='secondary')
    ], className="mb-3"),
    
    html.Hr(),
    
    # AI recommendation
    dcc.Markdown(
        sample['aiRecommendation'],
        style={
            'backgroundColor': '#f8f9fa',
            'padding': '20px',
            'borderRadius': '5px',
            'fontSize': '14px',
            'lineHeight': '1.6'
        }
    ),
    
    html.Hr(),
    
    # Metadata
    html.Div([
        html.Small(f"Generado: {sample['classificationTimestamp'].strftime('%Y-%m-%d %H:%M:%S')}", className="text-muted me-3"),
        html.Small(f"Modelo: gpt-4o-mini", className="text-muted")
    ])
])
```

---

### **Section 3: Evolución Temporal**

#### **Purpose**: Show essay trends over time for the selected unit

#### **Layout**:

```
┌─────────────────────────────────────────────────────────┐
│  📈 Evolución Temporal de Ensayos                        │
│  Componente: motor diesel  │  Período: [Last 12 months▼]│
├─────────────────────────────────────────────────────────┤
│                                                         │
│   Essay Values Over Time                                │
│   60 ┤                                                  │
│   55 ┤              ●━━━━━━━━━━━━━━━━●  Hierro         │
│   50 ┤            ╱                                     │
│   45 ┤ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  (Alert Limit) │
│   40 ┤          ╱                                       │
│   35 ┤        ●                                         │
│   30 ┤ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  (Normal Limit)│
│   25 ┤    ●━━━●━━━━━●━━━━━━━━━━━●  Cobre               │
│   20 ┤                                                  │
│   15 ┤ ━━━●━━━━━━━━━●━━━━━━━━━━●━━●  Silicio          │
│    0 └┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬   │
│       Oct Nov Dec Jan Feb Mar Apr May Jun Jul Aug Sep   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

#### **Multi-Line Time Series**:

```python
import plotly.graph_objects as go

# Get historical data for this component
df_history = df_classified[
    (df_classified['unitId'] == selected_unitId) &
    (df_classified['componentName'] == selected_component)
].sort_values('sampleDate')

# Select key essays to plot (user can toggle)
key_essays = ['Hierro', 'Cobre', 'Silicio', 'Viscosidad cinemática @ 40°C']

fig = go.Figure()

for essay in key_essays:
    if essay in df_history.columns:
        # Add essay line
        fig.add_trace(go.Scatter(
            x=df_history['sampleDate'],
            y=df_history[essay],
            mode='lines+markers',
            name=essay,
            line=dict(width=2),
            marker=dict(size=8)
        ))
        
        # Add threshold lines
        normal = limits[client][machine][component][essay]['threshold_normal']
        alert = limits[client][machine][component][essay]['threshold_alert']
        
        fig.add_trace(go.Scatter(
            x=df_history['sampleDate'],
            y=[normal] * len(df_history),
            mode='lines',
            name=f'{essay} - Normal',
            line=dict(color='green', dash='dash', width=1),
            showlegend=False,
            hoverinfo='skip'
        ))

fig.update_layout(
    title=f"Evolución Temporal - {selected_component}",
    xaxis_title="Fecha de Muestra",
    yaxis_title="Valor (ppm / cSt / %)",
    hovermode='x unified',
    height=500,
    legend=dict(orientation="h", y=-0.2)
)
```

**Features**:
- Toggle essays on/off (clickable legend)
- Hover shows all values at that date
- Threshold lines for context
- Period filter (last 6/12/24 months)

---

### **Section 4: Comparación con Reportes Anteriores**

#### **Purpose**: Quantify changes from previous sample

#### **Layout**:

```
┌───────────────────────────────────────────────────────────────────┐
│  🔄 Comparación con Reporte Anterior                              │
│  Muestra Actual: LAB123456 (2026-01-25)                           │
│  Muestra Anterior: LAB123450 (2025-12-20)  │  Δ Tiempo: 36 días   │
├───────────────────────────────────────────────────────────────────┤
│  Essay          │ Anterior │ Actual │ Cambio Abs │ Cambio % │ Trend│
├─────────────────┼──────────┼────────┼────────────┼──────────┼──────┤
│ Hierro          │   35.2   │  55.2  │   +20.0    │  +56.8%  │  ⬆️  │
│ Cobre           │   22.1   │  28.1  │    +6.0    │  +27.1%  │  ⬆️  │
│ Silicio         │   14.5   │  12.5  │    -2.0    │  -13.8%  │  ⬇️  │
│ Viscosidad@40°C │  138.5   │ 152.3  │   +13.8    │  +10.0%  │  ⬆️  │
│ Agua            │    0.2   │   0.4  │    +0.2    │ +100.0%  │  ⬆️⚠️│
│ ... (all essays with changes)                                     │
└───────────────────────────────────────────────────────────────────┘

Trends: ⬆️ Increasing  ⬇️ Decreasing  ⬌ Stable (<5% change)
```

#### **Implementation**:

```python
# Get previous sample
df_unit_history = df_classified[
    (df_classified['unitId'] == selected_unitId) &
    (df_classified['componentName'] == selected_component)
].sort_values('sampleDate', ascending=False)

if len(df_unit_history) >= 2:
    current_sample = df_unit_history.iloc[0]
    previous_sample = df_unit_history.iloc[1]
    
    # Calculate changes
    comparison_data = []
    for essay in key_essays:
        if essay in current_sample.index and essay in previous_sample.index:
            prev_val = previous_sample[essay]
            curr_val = current_sample[essay]
            
            if pd.notna(prev_val) and pd.notna(curr_val):
                abs_change = curr_val - prev_val
                pct_change = (abs_change / prev_val * 100) if prev_val != 0 else 0
                
                # Determine trend
                if abs(pct_change) < 5:
                    trend = '⬌'
                elif pct_change > 0:
                    trend = '⬆️' if pct_change < 20 else '⬆️⚠️'
                else:
                    trend = '⬇️'
                
                comparison_data.append({
                    'Essay': essay,
                    'Anterior': prev_val,
                    'Actual': curr_val,
                    'Cambio Abs': abs_change,
                    'Cambio %': pct_change,
                    'Trend': trend
                })
    
    df_comparison = pd.DataFrame(comparison_data)
    
    # Render table with color coding
    dash_table.DataTable(
        columns=[
            {'name': 'Essay', 'id': 'Essay'},
            {'name': 'Anterior', 'id': 'Anterior', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'Actual', 'id': 'Actual', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'Cambio Abs', 'id': 'Cambio Abs', 'type': 'numeric', 'format': {'specifier': '+.2f'}},
            {'name': 'Cambio %', 'id': 'Cambio %', 'type': 'numeric', 'format': {'specifier': '+.1f'}},
            {'name': 'Trend', 'id': 'Trend'}
        ],
        data=df_comparison.to_dict('records'),
        
        style_data_conditional=[
            {'if': {'filter_query': '{Trend} contains "⬆️⚠️"'}, 'backgroundColor': '#ffebee'},
            {'if': {'filter_query': '{Cambio %} > 20'}, 'color': '#dc3545', 'fontWeight': 'bold'}
        ]
    )
else:
    html.P("No hay reporte anterior disponible para comparación.")
```

---

### **Data Requirements for Tab 3**

| Section | Primary File | Additional Data |
|---------|-------------|-----------------|
| Section 1 | `classified_reports.parquet` | `stewart_limits.json`, `essays_elements.xlsx` |
| Section 2 | `classified_reports.parquet` | None (uses `aiRecommendation` field) |
| Section 3 | `classified_reports.parquet` (historical) | `stewart_limits.json` |
| Section 4 | `classified_reports.parquet` (current + previous) | None |

---

## 📊 Data Requirements

### **Complete File Dependency Matrix**

| Dashboard Tab | Section | Required Files | Required Columns |
|---------------|---------|----------------|------------------|
| **Tab 1** | Limits Table | `stewart_limits.json` or `.parquet` | `client`, `machineName`, `componentName`, `essayName`, `threshold_*` |
| **Tab 2.1** | Machine Pie + Priority | `machine_status_current.parquet` | `machineStatus`, `totalNumericStatus`, `unitId` |
| **Tab 2.2** | Machine Detail | `machine_status_current.parquet` + `classified_reports.parquet` | All machine columns + component status details |
| **Tab 2.3** | Report Distribution | `classified_reports.parquet` | `reportStatus`, `componentName` |
| **Tab 2.4** | Component Detail | `classified_reports.parquet` | `unitId`, `componentName`, `sampleDate`, `reportStatus`, `aiRecommendation` |
| **Tab 3.1** | Radar Charts | `classified_reports.parquet` + `stewart_limits.json` + `essays_elements.xlsx` | All essay columns, limits, `GroupElement` |
| **Tab 3.2** | AI Recommendations | `classified_reports.parquet` | `aiRecommendation`, `reportStatus`, `severityScore`, `essaysBreached` |
| **Tab 3.3** | Time Series | `classified_reports.parquet` (historical) + `stewart_limits.json` | Essay columns, `sampleDate`, `unitId`, `componentName` |
| **Tab 3.4** | Historical Comparison | `classified_reports.parquet` (current + previous) | Essay columns, `sampleDate` |

---

## 🛠️ Technical Implementation

### **Technology Stack**

```python
# requirements.txt
dash>=2.14.0
dash-bootstrap-components>=1.5.0
plotly>=5.17.0
pandas>=2.1.0
numpy>=1.24.0
pyarrow>=14.0.0  # For Parquet support
```

### **Application Structure**

```python
# app.py
import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd

# Initialize app
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True
)

# Load data
@app.server.before_first_request
def load_data():
    global df_classified, df_machine_status, stewart_limits, essays
    
    # Select client (from environment or config)
    client = 'CDA'  # TODO: Make configurable
    
    df_classified = pd.read_parquet(f'data/oil/to_consume/{client.lower()}/classified_reports.parquet')
    df_machine_status = pd.read_parquet(f'data/oil/to_consume/{client.lower()}/machine_status_current.parquet')
    
    with open('data/oil/processed/stewart_limits.json') as f:
        stewart_limits = json.load(f)
    
    essays = pd.read_excel('data/oil/essays_elements.xlsx').dropna()

# Layout
app.layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H1("Multi-Technical-Alerts", className="mb-2"),
            html.P(f"Cliente: {client}  |  Última Actualización: {datetime.now().strftime('%Y-%m-%d %H:%M')}", className="text-muted")
        ])
    ]),
    
    dbc.Tabs([
        dbc.Tab(label="📊 Límites", tab_id="tab-limits"),
        dbc.Tab(label="🚜 Estado de Máquinas", tab_id="tab-machines"),
        dbc.Tab(label="📝 Detalle de Reporte", tab_id="tab-report")
    ], id="tabs", active_tab="tab-limits"),
    
    html.Div(id="tab-content", className="mt-4")
], fluid=True)

# Callbacks
@app.callback(
    Output("tab-content", "children"),
    Input("tabs", "active_tab")
)
def render_tab_content(active_tab):
    if active_tab == "tab-limits":
        return render_limits_tab()
    elif active_tab == "tab-machines":
        return render_machines_tab()
    elif active_tab == "tab-report":
        return render_report_tab()

# Run app
if __name__ == '__main__':
    app.run_server(debug=True, host='0.0.0.0', port=8050)
```

### **Deployment Considerations**

1. **Client Separation**: Deploy separate instances or implement authentication-based filtering
2. **Data Refresh**: Schedule data pipeline to update Gold layer files (cron job or Airflow)
3. **Performance**: Use Parquet partitioning for large datasets
4. **Caching**: Implement Dash caching for expensive computations
5. **Monitoring**: Add logging and error tracking (Sentry)

---

## 👥 User Workflows

### **Workflow 1: Executive Daily Check**

1. Open dashboard → Tab 2 (Machine Status)
2. View Section 1 pie chart → "10% Anormal, action needed"
3. Check Priority Table → Top 3 machines identified
4. Export table → Send to maintenance manager

**Time**: 2 minutes

---

### **Workflow 2: Maintenance Manager Work Planning**

1. Tab 2, Section 2 → Filter "Anormal" or "Alerta" machines
2. Review `componentSummary` column → Identify patterns
3. Tab 3 (Report Detail) → Deep dive on critical machines
4. Section 2 → Read AI recommendations
5. Create work orders based on recommendations

**Time**: 15 minutes for 10 machines

---

### **Workflow 3: Technician Sample Investigation**

1. Tab 3 (Report Detail) → Select unit from dropdown
2. Select specific sample from date dropdown
3. Section 1 → View radar charts → Identify breached essays
4. Section 1B → Check exact values in table
5. Section 2 → Read AI diagnosis
6. Section 4 → Compare with previous sample → Confirm trend
7. Report findings to supervisor

**Time**: 5 minutes per sample

---

### **Workflow 4: Engineer Threshold Verification**

1. Tab 1 (Limits) → Select machine and component
2. Review threshold values → Verify reasonableness
3. If needed: Re-run Stewart Limits calculation with adjusted percentiles
4. Update `stewart_limits.json`
5. Refresh dashboard

**Time**: 10 minutes per machine-component pair

---

## 📞 Support

For implementation assistance:
- **[Data Contracts](data_contracts.md)**: Data file specifications
- **[Project Documentation](project_documentation.md)**: Business logic
- **[Future Reviews](future_reviews.md)**: Planned enhancements
