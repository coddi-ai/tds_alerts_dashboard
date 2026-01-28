# Data Contracts Documentation

**Multi-Technical-Alerts - Oil Analysis Data Specifications**

---

## 📋 Table of Contents

1. [Data Architecture Overview](#data-architecture-overview)
2. [Data Layers](#data-layers)
3. [Schema Definitions](#schema-definitions)
4. [Data Transformations](#data-transformations)
5. [Aggregation Logic](#aggregation-logic)
6. [File Usage Guide](#file-usage-guide)
7. [Auxiliary Data Files](#auxiliary-data-files)

---

## 🏗️ Data Architecture Overview

The system implements a **medallion architecture** (Bronze → Silver → Gold) for data processing:

```
Raw Lab Reports (Bronze)
    ↓ [Harmonization & Validation]
Unified Oil Samples (Silver)
    ↓ [Classification & AI Analysis]
Dashboard-Ready Data (Gold)
```

**Key Principle**: Each layer serves a specific purpose with increasing levels of refinement and business value.

---

## 📂 Data Layers

### **Bronze Layer: Raw Data** (`data/oil/raw/`)

**Purpose**: Immutable archive of original laboratory reports

**Structure**:
```
data/oil/raw/
├── cda/                    # Client: CDA (Finning Laboratory)
│   ├── {unitId}_YYYYMM.xlsx
│   └── metadata.json       # Ingestion tracking
└── emin/                   # Client: EMIN (ALS Laboratory)
    ├── muestrasAlsHistoricos.parquet
    └── metadata.json
```

**Characteristics**:
- **Immutable**: Never modified after ingestion
- **Source-specific**: Maintains original lab format
- **Complete**: Contains all columns from lab reports

**Key Differences Between Sources**:

| Aspect | CDA (Finning) | EMIN (ALS) |
|--------|---------------|------------|
| Format | Excel (.xlsx) | Parquet |
| File Organization | One file per unit | Consolidated file |
| Essay Structure | Wide format (one column per essay) | Nested format (testName1, testValue1, ...) |
| Completeness | Missing `componentHours`, `oilWeight` | Missing `oilWeight` |

---

### **Silver Layer: Processed Data** (`data/oil/processed/`)

**Purpose**: Harmonized, validated, standardized data ready for analysis

**Structure**:
```
data/oil/processed/
├── cda.parquet              # Standardized CDA data
├── emin.parquet             # Standardized EMIN data
└── stewart_limits.json      # Statistical thresholds
```

**Schema**: See [Silver Schema Definition](#silver-schema-oil-samples)

**Transformations Applied**:
1. Column renaming to standard schema
2. Essay name normalization (via `essays_elements.xlsx`)
3. Name standardization (lowercase, no accents)
4. Cardinality reduction (mapping similar names)
5. Date parsing and validation
6. Client tagging

---

### **Gold Layer: Analytics-Ready Data** (`data/oil/to_consume/`)

**Purpose**: Pre-classified, AI-enhanced data optimized for dashboards

**Structure**:
```
data/oil/to_consume/
├── cda/
│   ├── classified_reports.parquet       # Reports with AI recommendations
│   ├── machine_status_current.parquet   # Latest machine health
│   └── component_summary.parquet        # Component-level aggregates
└── emin/
    ├── classified_reports.parquet
    ├── machine_status_current.parquet
    └── component_summary.parquet
```

**Schema**: See [Gold Schema Definitions](#gold-schema-classified-reports)

---

## 📐 Schema Definitions

### **Silver Schema: Oil Samples**

This is the **standardized schema** used across all clients after preprocessing.

```python
{
    # ========== Identifiers ==========
    "sampleNumber": str,              # Unique sample identifier from lab
    "client": str,                    # "CDA" or "EMIN"
    
    # ========== Temporal ==========
    "sampleDate": datetime,           # When sample was collected
    
    # ========== Equipment Hierarchy ==========
    "unitId": str,                    # Business unit / Equipment ID (e.g., "CDA_001")
    "machineName": str,               # Standardized machine type (e.g., "camion", "pala")
    "machineModel": str,              # Model designation (e.g., "789D", "D11T")
    "machineBrand": str,              # Manufacturer (e.g., "caterpillar")
    "machineSerialNumber": str,       # Factory serial number
    "machineHours": float,            # Operating hours at sample time
    
    # ========== Component ==========
    "componentName": str,             # Standardized component name (e.g., "motor diesel", "transmision")
    "componentSerialNumber": str,     # Component serial number
    "componentHours": float,          # Component-specific operating hours (may be null for some sources)
    
    # ========== Oil Information ==========
    "oilMeter": float,                # Oil operating hours
    "oilBrand": str,                  # Oil manufacturer
    "oilType": str,                   # Oil specification (e.g., "SAE 15W-40")
    "oilWeight": str,                 # Viscosity grade (may be null for some sources)
    
    # ========== Chemical Essays ==========
    # One column per essay element (e.g., "Hierro", "Cobre", "Silicio")
    # Values are float (ppm or percentage)
    # Column names are standardized Spanish names from essays_elements.xlsx
    "Hierro": float,
    "Cobre": float,
    "Silicio": float,
    # ... (30+ additional essay columns)
}
```

**Important Notes**:
- All name fields (`machineName`, `componentName`, `machineBrand`) are **lowercase, no accents**
- `unitId` uses **underscore** instead of hyphen (e.g., "CDA_001" not "CDA-001")
- Essay columns are **dynamic** based on `essays_elements.xlsx` mapping
- Missing values are represented as `NaN` or `None`

---

### **Gold Schema: Classified Reports**

This schema extends the Silver schema with classification and AI-generated insights.

```python
{
    # ========== All Silver Schema Fields ==========
    # (All fields from Silver schema are preserved)
    
    # ========== Classification Results ==========
    "reportStatus": str,              # "Normal", "Alerta", or "Anormal"
    "severityScore": int,             # Sum of essay points (0-15+)
    "essaysBreached": int,            # Count of essays exceeding limits
    "requiresAction": bool,           # True if status != "Normal"
    
    # ========== AI Analysis ==========
    "aiPrompt": str or None,          # Prompt sent to GPT-4 (None for Normal reports)
    "aiRecommendation": str,          # AI-generated maintenance recommendation
    "classificationTimestamp": datetime,  # When classification was performed
    
    # ========== Report-Level Metadata ==========
    "numericReportStatus": int,       # 0=Normal, 1=Alerta, 2=Anormal (for aggregation)
}
```

---

### **Gold Schema: Machine Status Current**

Aggregated view of the latest status for each machine.

```python
{
    # ========== Machine Identification ==========
    "unitId": str,                    # Equipment identifier
    "client": str,                    # "CDA" or "EMIN"
    "machineName": str,               # Standardized machine type
    
    # ========== Machine Status ==========
    "machineStatus": str,             # "Normal", "Alerta", or "Anormal"
    "totalNumericStatus": int,        # Sum of all component numeric statuses
    
    # ========== Component Breakdown ==========
    "componentsTotal": int,           # Total monitored components
    "componentsNormal": int,          # Components in Normal status
    "componentsAlerta": int,          # Components in Alerta status
    "componentsAnormal": int,         # Components in Anormal status
    
    # ========== Temporal Metadata ==========
    "lastSampleDate": datetime,       # Most recent sample across all components
    "daysInactive": int,              # Days since last sample
    
    # ========== Actions ==========
    "priorityActions": list[str],     # List of recommended actions
    "updatedAt": datetime,            # When this summary was generated
}
```

---

## 🔄 Data Transformations

### **Step 1: Bronze → Silver (Harmonization)**

#### **Transformation: CDA Data (Finning Lab)**

**Input Format**: Excel files with wide-format essays
```
| ID de equipo | No. de control | Fecha | Hierro | Cobre | Silicio | ...
|--------------|----------------|-------|--------|-------|---------|----
| CDA-001      | LAB123456      | ...   | 25.3   | 12.1  | 8.5     | ...
```

**Process**:
1. **Column Renaming**: Map Spanish column names to standard schema
   ```python
   'ID de equipo' → 'unitId'
   'No. de control de laboratorio' → 'sampleNumber'
   'Compartimento' → 'componentName'
   # ... (see notebook for full mapping)
   ```

2. **Essay Name Standardization**: Apply `essays_elements.xlsx` mapping
   ```python
   'Fe' → 'Hierro'
   'Cu' → 'Cobre'
   'Si' → 'Silicio'
   ```

3. **Name Normalization**:
   ```python
   # Apply nameProtocol function
   - Remove accents: "Transmisión" → "transmision"
   - Lowercase: "MOTOR DIESEL" → "motor diesel"
   ```

4. **Cardinality Reduction**:
   ```python
   # Apply reduceCardinalityNames function
   "mando final izquierdo" → "mando final"
   "mando final derecho" → "mando final"
   "CAT" → "caterpillar"
   ```

5. **Client Tagging**: Add `client = 'CDA'`

6. **ID Format Standardization**: Replace hyphens with underscores
   ```python
   "CDA-001" → "CDA_001"
   ```

**Output**: Parquet file at `processed/cda.parquet`

---

#### **Transformation: EMIN Data (ALS Lab)**

**Input Format**: Parquet with nested essay structure
```
| sampleNumber | equipment_tag | testName1 | testValue1 | testName2 | testValue2 | ...
|--------------|---------------|-----------|------------|-----------|------------|----
| ALS987654    | EMIN-120      | Hierro    | 28.5       | Cobre     | 10.2       | ...
```

**Process**:
1. **Column Renaming**: Map ALS-specific names to standard schema
   ```python
   'equipment_tag' → 'unitId'
   'collectionData_dateSampled' → 'sampleDate'
   'compartment_name' → 'componentName'
   # ... (see notebook for full mapping)
   ```

2. **Essay Unpivoting**: Transform nested testName/testValue pairs to columns
   ```python
   # Melt testName columns
   df_names = melt(id_vars=['sampleNumber'], value_vars=[testName1, testName2, ...])
   
   # Melt testValue columns  
   df_values = melt(id_vars=['sampleNumber'], value_vars=[testValue1, testValue2, ...])
   
   # Merge and pivot
   df_essays = merge(df_names, df_values).pivot(index='sampleNumber', columns='testName', values='testValue')
   ```

3. **Value Cleaning**:
   ```python
   # Remove hyphens indicating null: '-' → NaN
   # Replace commas with periods: '12,5' → '12.5'
   # Handle detection limits: '<0.05' → 0, '>0.05' → 0.1
   # Convert to numeric, coerce errors to NaN
   ```

4. **Name Normalization**: Same `nameProtocol` and `reduceCardinalityNames` as CDA

5. **Client Tagging**: Add `client = 'EMIN'`

**Output**: Parquet file at `processed/emin.parquet`

---

### **Step 2: Compute Stewart Limits (Silver → Silver)**

**Input**: Combined processed data from all clients
**Output**: `processed/stewart_limits.json`

**Process**:
1. **Group by**: `client → machineName → componentName → essayName`

2. **Filter**: Only include essays with >3 unique values

3. **Calculate Percentiles**:
   ```python
   normal_threshold = ceil(quantile(0.90))    # 90th percentile
   alert_threshold = ceil(quantile(0.95))     # 95th percentile
   critic_threshold = ceil(quantile(0.98))    # 98th percentile
   ```

4. **Enforce Monotonicity**:
   ```python
   if alert <= normal:
       alert = normal + 1
   if critic <= alert:
       critic = alert + 1
   ```

**Output Structure**:
```json
{
  "CDA": {
    "camion": {
      "motor diesel": {
        "Hierro": {
          "threshold_normal": 30.0,
          "threshold_alert": 45.0,
          "threshold_critic": 60.0
        },
        "Cobre": { ... }
      }
    }
  },
  "EMIN": { ... }
}
```

---

### **Step 3: Silver → Gold (Classification & AI)**

#### **Transformation: Essay-Level Thresholding**

**Process**:
1. For each essay in a report, compare value against Stewart Limits:
   ```python
   if value >= critic_threshold:
       status = 'Critico'
       points = 5
   elif value >= alert_threshold:
       status = 'Condenatorio'
       points = 3
   elif value >= normal_threshold:
       status = 'Marginal'
       points = 1
   else:
       status = None
       points = 0
   ```

2. Create `essays_broken` DataFrame with all essays exceeding `threshold_normal`

---

#### **Transformation: Report-Level Classification**

**Process**:
1. Sum essay points: `essaySum = Σ(essay_points)`

2. Apply thresholds:
   ```python
   if essaySum < 3:
       reportStatus = 'Normal'
   elif essaySum >= 5:
       reportStatus = 'Anormal'
   else:
       reportStatus = 'Alerta'
   ```

3. Count breached essays: `essaysBreached = len(essays_broken)`

---

#### **Transformation: AI Recommendation Generation**

**Process**:
1. **Skip Normal Reports**: If `reportStatus == 'Normal'`, skip AI call (cost optimization)

2. **Construct Prompt**:
   ```python
   prompt = f"""
   Analiza una muestra para el siguiente equipo:
   Componente: {componentName}
   Máquina: {machineName} - {machineModel}
   
   Los valores de la muestra son:
   {essays_broken}  # Table of elemento, valor, limite transgredido, valor_limite
   """
   ```

3. **Call OpenAI API**:
   - Model: `gpt-4o-mini`
   - Temperature: `0.9`
   - Context: System prompt defining expert mechanical engineer role
   - Few-shot examples: 3 example analyses for calibration

4. **Store Response**: Save prompt and recommendation in Gold layer

**Parallelization**: Uses `ThreadPoolExecutor` with 18 workers for concurrent processing

---

## 📊 Aggregation Logic

### **Machine Status Aggregation**

**Goal**: Determine overall machine health from component-level reports

**Process**:
1. **Get Latest Reports**: For each `(unitId, componentName)` pair, select most recent `sampleDate`

2. **Map to Numeric**:
   ```python
   numericReportStatus = {
       'Normal': 0,
       'Alerta': 1,
       'Anormal': 2
   }
   ```

3. **Sum Across Components**:
   ```python
   totalNumericStatus = Σ(numericReportStatus for each component)
   ```

4. **Classify Machine**:
   ```python
   if totalNumericStatus < 2:
       machineStatus = 'Normal'
   elif totalNumericStatus >= 4:
       machineStatus = 'Anormal'
   else:
       machineStatus = 'Alerta'
   ```

**Example**:
- Machine CDA_001 has 3 components:
  - Motor Diesel: Anormal (2 points)
  - Transmision: Normal (0 points)
  - Hidraulico: Alerta (1 point)
- Total: 2 + 0 + 1 = 3 points → **machineStatus = 'Alerta'**

---

## 📖 File Usage Guide

### **When to Use Each Layer**

| Use Case | Layer | File | Reason |
|----------|-------|------|--------|
| Audit original data | Bronze | `raw/cda/*.xlsx` | Immutable source of truth |
| Reprocess from scratch | Bronze | `raw/emin/*.parquet` | Start pipeline fresh |
| Train new Stewart Limits | Silver | `processed/{client}.parquet` | Clean, standardized data |
| Query historical essays | Silver | `processed/{client}.parquet` | Fast columnar access |
| Build new dashboard | Gold | `to_consume/{client}/classified_reports.parquet` | Pre-classified, ready to visualize |
| Fleet health summary | Gold | `to_consume/{client}/machine_status_current.parquet` | Aggregated view |
| Component filtering | Gold | `to_consume/{client}/component_summary.parquet` | Fast filter dropdowns |

---

### **Column Availability by Layer**

| Column Category | Bronze (Raw) | Silver (Processed) | Gold (Classified) |
|-----------------|--------------|-------------------|-------------------|
| Equipment metadata | ✅ | ✅ | ✅ |
| Essay values | ✅ | ✅ | ✅ |
| Standardized names | ❌ | ✅ | ✅ |
| Stewart Limits | ❌ | ❌ (separate file) | ❌ (separate file) |
| reportStatus | ❌ | ❌ | ✅ |
| AI recommendations | ❌ | ❌ | ✅ |
| Machine status | ❌ | ❌ | ✅ (separate file) |

---

## 📎 Auxiliary Data Files

### **essays_elements.xlsx**

**Location**: `data/oil/essays_elements.xlsx`

**Purpose**: Master mapping for chemical essay names across different lab formats

**Schema**:
```python
{
    "Element": str,                # Short code (e.g., "Fe", "Cu", "Si")
    "ElementNameSpanish": str,     # Standardized Spanish name (e.g., "Hierro", "Cobre")
    "ElementNameEnglish": str,     # English translation (e.g., "Iron", "Copper")
    "GroupElement": str,           # Category for visualization grouping (e.g., "Metales de Desgaste")
}
```

**Usage**:
1. **Harmonization**: Map lab-specific essay names to `ElementNameSpanish`
2. **Validation**: Ensure only mapped essays are included in Silver layer
3. **Dashboard Grouping**: Use `GroupElement` to organize radar charts

**Example Rows**:
| Element | ElementNameSpanish | ElementNameEnglish | GroupElement |
|---------|-------------------|-------------------|--------------|
| Fe | Hierro | Iron | Metales de Desgaste |
| Cu | Cobre | Copper | Metales de Desgaste |
| Si | Silicio | Silicon | Contaminantes |
| Vis40 | Viscosidad cinemática @ 40°C | Kinematic Viscosity @ 40°C | Propiedades Físicas |

**Important**: Rows with `NaN` values are dropped during processing (incomplete mappings)

---

### **stewart_limits.json**

**Location**: `data/oil/processed/stewart_limits.json`

**Purpose**: Statistical thresholds for essay breach detection

**Structure**: See [Step 2: Compute Stewart Limits](#step-2-compute-stewart-limits-silver--silver)

**Usage**:
1. **Classification Pipeline**: Compare essay values against thresholds
2. **Dashboard Visualizations**: Display limit lines on charts
3. **Threshold Management**: Update when new data significantly changes distributions

**Access Pattern**:
```python
# Get limits for specific context
limits = stewart_limits[client][machineName][componentName][essayName]
normal = limits['threshold_normal']
alert = limits['threshold_alert']
critic = limits['threshold_critic']
```

---

## 🔄 Data Update Workflow

### **Incremental Update Process**

1. **Ingest New Raw Data**:
   - Add new Excel/Parquet files to `raw/{client}/`
   - Update `metadata.json` with file hash and row count

2. **Reprocess Silver Layer**:
   - Re-run harmonization on all raw files
   - Validate schema compliance
   - Overwrite `processed/{client}.parquet`

3. **Recalculate Stewart Limits** (Optional):
   - Only if new data significantly changes distributions
   - Recalculate from full Silver layer
   - Overwrite `stewart_limits.json`

4. **Regenerate Gold Layer**:
   - Run classification on new Silver data
   - Call AI for non-Normal reports
   - Append to `classified_reports.parquet` (with deduplication by `sampleNumber`)
   - Recalculate `machine_status_current.parquet`

5. **Refresh Dashboards**:
   - Dashboards automatically read latest Gold layer files

---

## 🛡️ Data Quality Rules

### **Validation Checks**

1. **Sample Validity**:
   - Filter machines with <100 total samples (insufficient data for limits)
   - Filter components with <100 total samples

2. **Essay Validity**:
   - Only process essays mapped in `essays_elements.xlsx`
   - Ignore essays with ≤3 unique values (not enough variance)

3. **Temporal Validity**:
   - Ensure `sampleDate` is valid datetime
   - Flag samples with `sampleDate` in future

4. **Value Validity**:
   - Essay values must be numeric
   - Negative values flagged for review (except specific cases)

---

## 📏 Data Retention

- **Bronze Layer**: **Permanent** (historical archive)
- **Silver Layer**: **Retained** until superseded by reprocessing
- **Gold Layer**: **Rolling** (retain last 2 years for dashboards, archive older data)

---

## 🔐 Client Isolation

**Critical Rule**: All processing maintains strict client separation

- Bronze: Separate directories
- Silver: Separate files
- Gold: Separate directories
- Stewart Limits: Separate nested dictionaries
- Dashboards: Pre-filtered by client before rendering

**No cross-client data sharing or comparison is permitted**.

---

## 📞 Support

For schema questions or data issues, refer to:
- **[Project Documentation](project_documentation.md)**: Business logic details
- **[Dashboard Documentation](dashboard_documentation.md)**: Consumption patterns
