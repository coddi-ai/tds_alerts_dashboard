# Telemetry Analysis Pipeline - Project Overview

**Version**: 1.0.0  
**Last Updated**: February 23, 2026  
**Component**: Telemetry Analysis System

---

## 📋 Table of Contents

1. [Repository Scope](#repository-scope)
2. [Evaluation Chain Architecture](#evaluation-chain-architecture)
3. [Scoring Methodology](#scoring-methodology)
4. [Baseline Strategy](#baseline-strategy)
5. [Output Schemas](#output-schemas)
6. [Dashboard Integration](#dashboard-integration)

---

## 🎯 Repository Scope

This repository implements the **Telemetry Analysis Pipeline**, a specialized component of the Multi-Technical Alerts Dashboard platform focused exclusively on processing sensor telemetry data from mining equipment.

### Primary Objectives

1. **Data Transformation**: Convert raw telemetry from Silver layer → enriched analytics in Golden layer
2. **Anomaly Detection**: Identify deviations from normal operational patterns using statistical scoring
3. **Status Evaluation**: Generate machine and component-level health assessments
4. **Dashboard Enablement**: Produce structured outputs consumable by visualization layers

### What This Repository Does

✅ Reads weekly telemetry partitions from Silver layer  
✅ Applies Severity-Weighted Percentile Window Scoring  
✅ Aggregates signal scores → component evaluations → machine status  
✅ Writes structured Golden layer outputs (`machine_status.parquet`, `classified.parquet`)  
✅ Provides traceability from raw signals to final machine health status  

### What This Repository Does NOT Do

❌ Dashboard visualization (handled by separate Dash application)  
❌ Oil analysis or maintenance records processing  
❌ Alert consolidation across techniques  
❌ Real-time streaming analytics (batch-oriented weekly evaluation)  

---

## 🔄 Evaluation Chain Architecture

The telemetry analysis follows a **hierarchical evaluation chain** that aggregates information from individual sensor readings to overall machine health:

```
┌─────────────────────────────────────────────────────────────┐
│                    RAW TELEMETRY DATA                       │
│              (Silver Layer: Weekly Parquet)                 │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  SIGNAL EVALUATION (Level 1)                                │
│  • Each sensor signal evaluated independently               │
│  • Compare readings against historical baseline percentiles │
│  • Score each observation: 0 (normal), 1 (alert), 3 (alarm) │
│  • Compute window_score_normalized per signal               │
│  • Label: Normal | Alerta | Anormal                         │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  COMPONENT AGGREGATION (Level 2)                            │
│  • Group signals by component (e.g., Engine, Transmission)  │
│  • Aggregate signal scores to component-level status        │
│  • Apply component criticality weighting                    │
│  • Generate component_score and component_status            │
│  • Document supporting evidence (which signals triggered)   │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  MACHINE EVALUATION (Level 3)                               │
│  • Aggregate all component statuses                         │
│  • Compute machine_score (sum of component criticality)     │
│  • Determine overall_status (worst component drives status) │
│  • Calculate priority_score for fleet ranking               │
│  • Package component_details for drill-down                 │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              GOLDEN LAYER OUTPUTS                           │
│  • machine_status.parquet (machine-level summary)           │
│  • classified.parquet (component-level detail)              │
└─────────────────────────────────────────────────────────────┘
```

### Evaluation Cadence

- **Frequency**: Once per week
- **Window**: Full 7-day evaluation window per run
- **Scope**: All units in the client fleet
- **Outputs**: Overwrite previous week's Golden layer files

---

## 📊 Scoring Methodology

### Severity-Weighted Percentile Window Scoring

The core algorithm evaluates the **full distribution** of sensor readings within the evaluation window using historical percentile-based thresholds.

#### Phase A: Build Historical Baseline

For each `(client, unit, signal)` triplet, compute historical percentile thresholds using a **training window** (e.g., last 90 days of historical data):

$$
\begin{aligned}
P_2 &= \text{2nd percentile (extreme lower bound)} \\
P_5 &= \text{5th percentile (alert lower bound)} \\
P_{95} &= \text{95th percentile (alert upper bound)} \\
P_{98} &= \text{98th percentile (extreme upper bound)}
\end{aligned}
$$

**Important**: Baselines are computed **per operational state** when possible:

- `EstadoMaquina = 'Operacional'` → Higher thresholds expected
- `EstadoMaquina = 'Ralenti'` → Lower thresholds expected
- `EstadoMaquina = 'Apagada'` → Near-zero thresholds expected

If insufficient data exists for state-specific baselines, fall back to aggregate percentiles across all states.

#### Phase B: Score Each Reading

For each observation $x$ in the current evaluation window, assign a **severity score**:

$$
\text{score}(x) = 
\begin{cases}
0 & \text{if } P_5 \leq x \leq P_{95} \quad \text{(Normal)} \\
1 & \text{if } P_2 \leq x < P_5 \text{ or } P_{95} < x \leq P_{98} \quad \text{(Alert)} \\
3 & \text{if } x < P_2 \text{ or } x > P_{98} \quad \text{(Alarm)}
\end{cases}
$$

**Rationale**:
- Score `0`: Value within central 90% of historical distribution
- Score `1`: Value in outer tails (5-2% or 95-98%) - early warning
- Score `3`: Value in extreme tails (<2% or >98%) - critical deviation

#### Phase C: Aggregate Window Score

Compute the **window-normalized anomaly score** for the signal:

$$
\text{window\_score\_normalized} = \frac{\sum_{i=1}^{n} \text{score}(x_i)}{n}
$$

Where $n$ is the number of observations in the evaluation window.

**Interpretation**:
- If all readings are normal (score=0) → window_score_normalized = 0
- If 20% of readings are in alert zone → window_score_normalized ≈ 0.2
- If 50% of readings are in alarm zone → window_score_normalized ≈ 1.5

#### Phase D: Signal Status Labeling

Apply thresholds to classify signal health:

$$
\text{signal\_status} = 
\begin{cases}
\text{Normal} & \text{if } \text{window\_score\_normalized} < T_1 \\
\text{Alerta} & \text{if } T_1 \leq \text{window\_score\_normalized} < T_2 \\
\text{Anormal} & \text{if } \text{window\_score\_normalized} \geq T_2
\end{cases}
$$

**MVP Thresholds**:
- $T_1 = 0.2$ (more than 20% of readings deviate → Alert)
- $T_2 = 0.4$ (more than 40% of readings deviate, or 13%+ in alarm zone → Abnormal)

**Threshold Tuning**: These values may be adjusted per signal type during calibration phase based on false positive/negative rates.

---

### Component Aggregation Logic

Once all signals in a component are evaluated, aggregate to component-level status using a **weighted severity-based approach**:

#### 1. Severity Mapping (Non-Linear)

Map signal statuses to severity scores to reflect risk:

$$
\text{severity}(\text{status}) = 
\begin{cases}
0.0 & \text{if status = Normal} \\
0.3 & \text{if status = Alerta} \\
1.0 & \text{if status = Anormal}
\end{cases}
$$

**Rationale**: Anormal conditions (1.0) are far more critical than Alerta conditions (0.3), requiring non-linear weighting.

#### 2. Signal Weighting (Coverage-Based)

Assign weights based on signal data quality:

$$
w_s = 
\begin{cases}
1.0 & \text{if signal has sufficient valid readings (≥50\% of window)} \\
0.0 & \text{if signal has insufficient data (<50\% of window)}
\end{cases}
$$

**Note**: Signals with too many missing values are excluded from component score calculation but tracked separately.

#### 3. Component Score Calculation (Weighted Average)

Compute normalized component score:

$$
\text{component\_score} = \frac{\sum_{s \in S_c} w_s \cdot \text{severity}(\text{signal\_status}_s)}{\sum_{s \in S_c} w_s}
$$

Where:
- $S_c$ is the set of signals belonging to component $c$
- $w_s$ is the weight for signal $s$ (based on data quality)
- $\text{severity}(\cdot)$ is the non-linear severity mapping

**Rationale**: Weighted average provides balanced assessment across multiple signals while penalizing data quality issues.

#### 4. Coverage Guardrail

Ensure sufficient signal coverage for reliable component evaluation:

$$
\text{component\_coverage} = \frac{\#\{s \in S_c : w_s > 0\}}{|S_c|}
$$

**Coverage Rules**:
- If $\text{component\_coverage} < 0.5$ → Mark component as `InsufficientData` or conservative `Alerta`
- Log warning: "Component evaluation based on limited signal coverage"

#### 5. Component Status Classification

Apply thresholds to component score:

$$
\text{component\_status} = 
\begin{cases}
\text{Normal} & \text{if } \text{component\_score} < 0.15 \\
\text{Alerta} & \text{if } 0.15 \leq \text{component\_score} < 0.45 \\
\text{Anormal} & \text{if } \text{component\_score} \geq 0.45 \\
\text{InsufficientData} & \text{if } \text{component\_coverage} < 0.5 \text{ (optional)}
\end{cases}
$$

**Threshold Rationale**:
- **Normal (< 0.15)**: All signals normal, or minor isolated alerts
- **Alerta (0.15-0.45)**: Multiple signals in alert, or single signal with elevated concerns
- **Anormal (≥ 0.45)**: One or more signals anormal, or many signals alerting

**Example Scenarios**:
- All 5 signals Normal → score = 0.0 → **Normal**
- 4 signals Normal, 1 Alerta → score = 0.3/5 = 0.06 → **Normal**
- 3 signals Normal, 2 Alerta → score = 0.6/5 = 0.12 → **Normal**
- 2 signals Normal, 3 Alerta → score = 0.9/5 = 0.18 → **Alerta**
- 4 signals Normal, 1 Anormal → score = 1.0/5 = 0.20 → **Alerta**
- 3 signals Normal, 1 Alerta, 1 Anormal → score = 1.3/5 = 0.26 → **Alerta**
- 2 signals Alerta, 3 Anormal → score = (0.6 + 3.0)/5 = 0.72 → **Anormal**

#### 6. Supporting Evidence

Track which signals triggered the component status:
- `triggering_signals`: List of signal names with status ≠ Normal
- `signal_scores`: Dict of {signal_name: window_score_normalized}
- `signal_statuses`: Dict of {signal_name: status}
- `signal_weights`: Dict of {signal_name: weight} (data quality indicator)
- `component_coverage`: Fraction of signals with sufficient data

---

### Machine Aggregation Logic

Final machine-level evaluation combines all components:

#### 1. Machine Score

Use weighted sum of component severity scores:

$$
\text{machine\_score} = \sum_{c \in C} w_c \cdot \text{component\_score}_c
$$

Where:
- $C$ is the set of components in the machine
- $w_c$ is the criticality weight of component $c$ (typical values: 1-3)
- $\text{component\_score}_c$ is the weighted severity score (0.0-1.0 range)

**Interpretation**:
- Machine score scales with number and criticality of affected components
- Higher criticality components (e.g., Engine=3) contribute more than lower criticality (e.g., Electrical=1)
- Score reflects cumulative risk across all systems

#### 2. Overall Status

$$
\text{overall\_status} = 
\begin{cases}
\text{Anormal} & \text{if any component is Anormal} \\
\text{Alerta} & \text{if any component is Alerta and none are Anormal} \\
\text{Normal} & \text{if all components are Normal}
\end{cases}
$$

#### 3. Priority Score

For fleet-level ranking (higher = worse condition):

$$
\text{priority\_score} = 100 \cdot N_{\text{anormal}} + 10 \cdot N_{\text{alerta}} + \text{machine\_score}
$$

Where:
- $N_{\text{anormal}}$ = count of components with Anormal status
- $N_{\text{alerta}}$ = count of components with Alerta status

---

## 🧮 Baseline Strategy

### Historical Window Selection

**Training Window**: 90 days (approximately 13 weeks) of historical data

**Rationale**:
- Captures seasonal operational patterns
- Sufficient sample size for percentile stability
- Not too long to include outdated equipment configurations
- Balances adaptability vs. stability

### Handling Operational States

Operational state segmentation is **critical** for accurate baseline calculation:

| State | Typical Behavior | Baseline Strategy |
|-------|------------------|-------------------|
| `Operacional` | High RPM, temperatures, pressures | State-specific percentiles |
| `Ralenti` | Low RPM, moderate temperatures | State-specific percentiles |
| `Apagada` | Near-zero readings | State-specific percentiles |
| `Unknown` | Mixed/transitional | Exclude from baseline calculation |

**Implementation**:
1. Filter training data by `EstadoMaquina`
2. Compute percentiles per state group
3. During evaluation, match current state to corresponding baseline
4. If state-specific baseline unavailable (insufficient data), use aggregate baseline with warning flag

### Baseline Update Strategy

**Update Frequency**: Monthly (every 4 weekly runs)

**Update Method**:
1. **Rolling Window**: Drop oldest 4 weeks, add newest 4 weeks
2. **Recompute Percentiles**: Recalculate $P_2, P_5, P_{95}, P_{98}$
3. **Version Tracking**: Store baseline version ID with outputs for traceability

**Baseline Invalidation Triggers**:
- Component replacement (major maintenance event)
- Significant operational profile change
- Calibration event recorded in maintenance logs

**Baseline Storage**:
```
data/telemetry/golden/{client}/baselines/
  ├── baseline_YYYYMMDD.parquet  (historical percentiles)
  └── baseline_metadata.json     (version, training window, update history)
```

**Schema**: `baseline_YYYYMMDD.parquet`
```
unit_id | signal | state | p2 | p5 | p95 | p98 | sample_count | training_start | training_end
```

---

## 📦 Output Schemas

### 1. `machine_status.parquet`

**Purpose**: Machine-level status summary (one row per unit)

**Location**: `data/telemetry/golden/{client}/machine_status.parquet`

**Schema**:

| Column | Type | Description |
|--------|------|-------------|
| `unit_id` | string | Unit identifier |
| `client` | string | Client identifier |
| `evaluation_week` | int | Week number evaluated (WW) |
| `evaluation_year` | int | Year evaluated (YYYY) |
| `latest_sample_date` | datetime | Most recent timestamp in evaluation window |
| `overall_status` | string | Machine health: Normal \| Alerta \| Anormal |
| `machine_score` | float | Aggregate severity score |
| `total_components` | int | Number of components evaluated |
| `components_normal` | int | Count with Normal status |
| `components_alerta` | int | Count with Alerta status |
| `components_anormal` | int | Count with Anormal status |
| `priority_score` | float | Fleet ranking score (higher = worse) |
| `component_details` | list[dict] | Per-component evaluation details (JSON) |
| `baseline_version` | string | Baseline file used (YYYYMMDD) |

**Example**:
```python
{
    "unit_id": "CAT797-001",
    "client": "cda",
    "evaluation_week": 8,
    "evaluation_year": 2026,
    "latest_sample_date": "2026-02-22 23:59:00",
    "overall_status": "Alerta",
    "machine_score": 1.86,  # Sum of weighted component scores
    "total_components": 12,
    "components_normal": 9,
    "components_alerta": 2,
    "components_anormal": 1,
    "priority_score": 120.86,
    "component_details": [
        {
            "component": "Engine",
            "status": "Anormal",
            "score": 0.52,  # Weighted severity score (0.0-1.0)
            "coverage": 0.85,
            "triggering_signals": ["EngCoolTemp", "EngOilPres"],
            "signal_details": {...}
        },
        {
            "component": "Transmission",
            "status": "Alerta",
            "score": 0.18,
            "coverage": 1.0,
            "triggering_signals": ["TransOilTemp"],
            "signal_details": {...}
        },
        ...
    ],
    "baseline_version": "20260201"
}
```

### 2. `classified.parquet`

**Purpose**: Component-level evaluation detail (one row per unit-component pair)

**Location**: `data/telemetry/golden/{client}/classified.parquet`

**Schema**:

| Column | Type | Description |
|--------|------|-------------|
| `unit` | string | Unit identifier |
| `client` | string | Client identifier |
| `evaluation_week` | int | Week number evaluated |
| `evaluation_year` | int | Year evaluated |
| `date` | datetime | Evaluation timestamp |
| `component` | string | Component name (e.g., "Engine", "Transmission") |
| `component_status` | string | Component health: Normal \| Alerta \| Anormal \| InsufficientData |
| `component_score` | float | Weighted severity score (0.0-1.0 range) |
| `component_coverage` | float | Fraction of signals with sufficient data (0.0-1.0) |
| `signals_evaluation` | dict | Per-signal scores and statuses (JSON) |
| `triggering_signals` | list[string] | Signals that triggered non-Normal status |
| `signal_weights` | dict | Per-signal data quality weights (JSON) |
| `ai_recommendation` | string | LLM-generated maintenance advice (Phase 2) |
| `baseline_version` | string | Baseline file used |

**Example**:
```python
{
    "unit": "CAT797-001",
    "client": "cda",
    "evaluation_week": 8,
    "evaluation_year": 2026,
    "date": "2026-02-22 23:59:00",
    "component": "Engine",
    "component_status": "Anormal",
    "component_score": 0.52,  # Weighted severity score (0.0-1.0)
    "component_coverage": 0.85,  # 85% of mapped signals have valid data
    "signals_evaluation": {
        "EngCoolTemp": {
            "status": "Anormal",
            "window_score": 1.2,
            "severity": 1.0,  # Mapped severity
            "weight": 1.0,  # Full weight (sufficient data)
            "baseline": {"p2": 75, "p5": 78, "p95": 95, "p98": 98},
            "observed_range": [92, 102],
            "anomaly_percentage": 45.2
        },
        "EngOilPres": {
            "status": "Alerta",
            "window_score": 0.3,
            "severity": 0.3,
            "weight": 1.0,
            ...
        }
    },
    "triggering_signals": ["EngCoolTemp", "EngOilPres"],
    "signal_weights": {"EngCoolTemp": 1.0, "EngOilPres": 1.0, "EngSpeed": 0.0},
    "ai_recommendation": null,  # Phase 2
    "baseline_version": "20260201"
}
```

---

## 🔗 Dashboard Integration

### How Outputs Are Consumed

The Golden layer files produced by this pipeline feed into the **Monitoring → Telemetry** section of the Multi-Technical Alerts Dashboard:

#### 1. Fleet Overview Tab
- **Data Source**: `machine_status.parquet`
- **Visualization**: 
  - Table of all units sorted by `priority_score`
  - Color-coded status indicators
  - Summary KPIs (% Normal, % Alerta, % Anormal)

#### 2. Machine Detail View
- **Data Source**: `machine_status.parquet` → `component_details` field
- **Visualization**:
  - Component health table
  - Radar chart of component scores
  - Timeline of status changes over weeks

#### 3. Component Drill-Down
- **Data Source**: `classified.parquet` → `signals_evaluation` field
- **Visualization**:
  - Signal distribution plots (boxplot: observed vs baseline percentiles)
  - Time series of signal readings with percentile bands
  - Anomaly heatmap (signals × time)

#### 4. Signal Inspection
- **Data Source**: Original Silver layer + baseline files
- **Visualization**:
  - Interactive time series plot
  - Overlayed percentile thresholds ($P_2, P_5, P_{95}, P_{98}$)
  - Highlighted anomaly regions
  - State transitions markers

### Traceability Chain

Users can drill down through the hierarchy:

```
Fleet Overview → Select Unit → Machine Status → 
Select Component → Component Detail → 
Select Signal → Signal Time Series + Baseline Comparison
```

Each level provides supporting evidence for the evaluation at the next level up.

---

## 🎯 Design Principles

### 1. Determinism
- Same input data + same baseline → same output
- No randomness in scoring logic
- Reproducible runs for auditing

### 2. Interpretability
- Every score traces back to specific sensor readings
- Thresholds based on historical percentiles (explainable)
- No black-box models in MVP (Phase 1)

### 3. Scalability
- Vectorized pandas operations (avoid row-level loops)
- Weekly batch processing (not real-time)
- Parquet columnar format for efficient I/O

### 4. Maintainability
- Clear separation: Silver (input) → Golden (output)
- Version-tracked baselines
- Structured logging for debugging

### 5. Extensibility
- Phase 2 can replace/augment scoring with ML models
- Component mapping easily updated via JSON
- Threshold tuning without code changes

---

## 📚 Related Documentation

- [Dashboard Proposal](dashboard_proposal.md) - Dashboard layout and visualizations
- [Integration Plan](integration_plan.md) - Step-by-step implementation phases
- [Programming Rules](programming_rules.md) - Engineering standards and conventions
- [Dashboard Overview](../general/dashboard_overview.md) - Platform architecture

---

## 📝 Version History

### Version 1.0.0 (February 2026)
- Initial telemetry analysis pipeline specification
- Severity-Weighted Percentile Window Scoring methodology
- Machine/component/signal evaluation hierarchy
- Golden layer output schemas defined
