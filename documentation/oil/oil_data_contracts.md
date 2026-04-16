# Data Contracts - Oil Analysis Data Product

**Version**: 2.1  
**Last Updated**: April 15, 2026  
**Owner**: Oil Analysis Data Product Team

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Data Layer Architecture](#data-layer-architecture)
3. [Bronze Layer](#bronze-layer)
4. [Silver Layer](#silver-layer)
5. [Golden Layer](#golden-layer)
6. [Schema Definitions](#schema-definitions)
7. [S3 Storage](#s3-storage)
8. [Data Quality Rules](#data-quality-rules)

---

## 🎯 Overview

This document defines the data contracts for the Oil Analysis Data Product, specifying the schema, format, and location of data at each processing layer (Bronze → Silver → Golden). These contracts ensure consistent data structure for downstream consumers.

**Data Product Purpose**: Process raw oil analysis laboratory results into actionable maintenance insights with AI-powered recommendations.

**Primary Consumers**:
- S3-based data consumers
- Business Intelligence tools
- Data analysts
- Fusion Service (aggregates multiple data products)

**Processing Modes**:
1. **Historical**: One-time bulk processing with Stewart Limits calculation
2. **Incremental**: Daily processing using existing Stewart Limits

---

## 🏗️ Data Layer Architecture

### Local Storage

```
data/
├── bronze/                       # Bronze Layer (Immutable source data)
│   ├── cda/                      # CDA client raw files
│   │   ├── T-09.xlsx             # Finning Lab format
│   │   ├── T-10.xlsx
│   │   └── ...
│   └── emin/                     # EMIN client raw files
│       ├── muestrasAlsHistoricos.parquet  # ALS Lab format
│       └── Equipamiento.parquet
│
├── silver/                       # Silver Layer (Harmonized, validated)
│   ├── CDA.parquet               # Standardized CDA data
│   └── EMIN.parquet              # Standardized EMIN data
│
├── golden/                       # Golden Layer (Analysis-ready outputs)
│   ├── cda/
│   │   ├── classified.parquet         # Classified oil analysis reports
│   │   ├── machine_status.parquet     # Aggregated machine health status
│   │   └── stewart_limits.parquet     # Statistical thresholds for CDA
│   └── emin/
│       ├── classified.parquet
│       ├── machine_status.parquet
│       └── stewart_limits.parquet
│
└── essays_elements.xlsx          # Auxiliary: Essay metadata and mappings
```

### S3 Storage (Auto-synced)

```
s3://{BUCKET_NAME}/MultiTechnique Alerts/oil/
├── silver/
│   ├── CDA.parquet
│   └── EMIN.parquet
└── golden/
    ├── cda/
    │   ├── classified.parquet
    │   ├── machine_status.parquet
    │   └── stewart_limits.parquet
    └── emin/
        ├── classified.parquet
        ├── machine_status.parquet
        └── stewart_limits.parquet
```

---

## 📥 Bronze Layer

**Purpose**: Immutable storage of raw laboratory data  
**Update Frequency**: 
- Historical: One-time bulk load
- Incremental: Daily/Weekly new files  
**Retention**: Indefinite (source of truth)  
**Format**: Original laboratory format (Excel or Parquet)

### Location

```
Local: data/bronze/{client}/
S3: Not uploaded (raw data stays local)
```

### CDA Client (Finning Laboratory)

**Format**: Excel (.xlsx)  
**Source**: Finning Laboratory reports  
**Naming**: `T-{month}.xlsx` (e.g., T-09.xlsx)

**Characteristics**:
- One file per month
- Contains multiple oil samples
- Variable essay columns (laboratory-dependent)

### EMIN Client (ALS Laboratory)

**Format**: Parquet (.parquet)  
**Source**: ALS Laboratory  
**Files**:
- `muestrasAlsHistoricos.parquet` - Oil sample results
- `Equipamiento.parquet` - Equipment metadata

**Characteristics**:
- Nested format with testName/testValue pairs
- Historical data in single file
- Machine metadata in separate file

### Contract Guarantees

✅ **Immutability**: Files never modified after ingestion  
✅ **Completeness**: All source columns preserved  
✅ **Traceability**: Original formats maintained

---

## 🔄 Silver Layer

**Purpose**: Harmonized, validated data with standardized schema  
**Update Frequency**: After each Bronze processing  
**Retention**: Keep latest + historical for trend analysis  
**Format**: Parquet (columnar, compressed)

### Location

```
Local: data/silver/{CLIENT}.parquet
S3: s3://{BUCKET}/MultiTechnique Alerts/oil/silver/{CLIENT}.parquet
```

### Files

- `CDA.parquet` - Harmonized CDA oil analysis data
- `EMIN.parquet` - Harmonized EMIN oil analysis data

### Schema

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `client` | string | Client identifier | 'CDA', 'EMIN' |
| `sampleNumber` | string | Unique sample ID | 'CDA-2024-001' |
| `sampleDate` | date | Sample collection date | '2024-01-15' |
| `unitId` | string | Equipment unit ID | 'CAT-001' |
| `machineName` | string | Normalized machine type | 'camion', 'pala' |
| `machineModel` | string | Machine model | 'CAT 797F' |
| `machineBrand` | string | Machine brand | 'Caterpillar' |
| `machineHours` | float | Operating hours | 15420.5 |
| `machineSerialNumber` | string | Machine serial | 'ABC123' |
| `componentName` | string | Component analyzed (original with position) | 'motor diesel', 'mando final izquierdo' |
| `componentNameNormalized` | string | Component normalized for Stewart Limits | 'motor diesel', 'mando final' |
| `componentHours` | float | Component hours | 8230.0 |
| `componentSerialNumber` | string | Component serial | 'ENG456' |
| `oilMeter` | float | Oil meter reading | 1250.5 |
| `oilBrand` | string | Oil brand | 'Mobil' |
| `oilType` | string | Oil type | '15W40' |
| `oilWeight` | string | Oil weight | '15W-40' |
| `previousSampleNumber` | string | Previous sample ID | 'CDA-2023-998' |
| `previousSampleDate` | date | Previous sample date | '2023-12-20' |
| `daysSincePrevious` | int | Days between samples | 26 |
| `group_element` | string | Essay group | 'Desgaste', 'Contaminacion' |
| **Essay Columns** | float | Essay values (dynamic) | |
| `Hierro` | float | Iron content (ppm) | 45.3 |
| `Cobre` | float | Copper content (ppm) | 12.1 |
| `Silicio` | float | Silicon content (ppm) | 8.7 |
| ... | float | (21 total essay columns) | |

### Quality Rules

✅ Valid date formats (YYYY-MM-DD)  
✅ Essay values >= 0  
✅ Component hours <= Machine hours  
✅ No duplicate sample numbers  
✅ All essay columns present (filled with 0 if missing)

**Note on Component Names**:
- `componentName`: Preserves original granularity (e.g., "mando final izquierdo", "mando final derecho", "maza izquierda")
- `componentNameNormalized`: Grouped version for Stewart Limits calculation (e.g., "mando final", "maza")
- Golden layer reports use original `componentName` for detailed visibility
- Stewart Limits use `componentNameNormalized` to ensure sufficient sample size

---

## 🏆 Golden Layer

**Purpose**: Analysis-ready outputs with classifications, AI recommendations, and aggregations  
**Update Frequency**: After each Silver processing  
**Retention**: Keep all historical snapshots  
**Format**: Parquet (columnar, compressed)

### Location

```
Local: data/golden/{client}/
S3: s3://{BUCKET}/MultiTechnique Alerts/oil/golden/{client}/
```

### Files per Client

#### 1. Classified Reports (`classified.parquet`)

**Purpose**: Oil analysis reports with essay classifications, report status, and AI recommendations

**Schema**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| **Base Columns** | | (All Silver layer columns including componentName and componentNameNormalized) | |
| `essays_broken` | int | Number of essays exceeding thresholds | 2 |
| `severity_score` | float | Severity scoring metric | 3.5 |
| `desgaste_score` | float | Wear-specific scoring metric | 2.1 |
| `report_status` | string | Overall report status | 'Normal', 'Alerta', 'Anormal' |
| `breached_essays` | string (JSON) | Essays exceeding thresholds | '["Hierro", "Cobre"]' |
| `ai_recommendation` | string | AI-generated maintenance advice | 'Se recomienda...' |
| `ai_generated_at` | datetime | Timestamp when AI recommendation was generated | '2026-02-03 14:30:00' |

**Scoring Metrics**:
- `essays_broken`: Count of essays that exceeded their Stewart Limits
- `severity_score`: Aggregate severity based on how much essays exceeded thresholds
- `desgaste_score`: Specific scoring for wear-related essays (Hierro, Cromo, Aluminio, Cobre, etc.)

**Report Status Logic**:
- `Normal`: Low severity, no critical issues
- `Alerta`: Moderate severity, monitoring recommended
- `Anormal`: High severity, action required

**Sample Count**: ~6,000-7,000 reports per client

---

#### 2. Machine Status (`machine_status.parquet`)

**Purpose**: Aggregated current health status per equipment unit

**Schema**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `unit_id` | string | Equipment unit ID | 'CAT-001' |
| `client` | string | Client identifier | 'CDA' |
| `latest_sample_date` | datetime | Most recent sample date | '2024-02-01' |
| `overall_status` | string | Overall machine status | 'Normal', 'Alerta', 'Anormal' |
| `machine_score` | float | Aggregate machine severity score | 2.3 |
| `total_components` | int | Total components monitored | 5 |
| `components_normal` | int | Components with Normal status | 3 |
| `components_alerta` | int | Components with Alerta status | 1 |
| `components_anormal` | int | Components with Anormal status | 1 |
| `priority_score` | float | Fleet ranking score (higher = worse) | 45.2 |
| `component_details` | string (JSON) | Per-component status details | JSON array |
| `machine_ai_recommendation` | string | Latest AI recommendation for machine | 'Programar...' |

**Sample Count**: ~200-250 machines per client

---

#### 3. Stewart Limits (`stewart_limits.parquet`)

**Purpose**: Statistical thresholds for essay classification (per client)

**Schema**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `client` | string | Client identifier | 'CDA' |
| `machine` | string | Normalized machine name | 'camion' |
| `component` | string | Component name (normalized/grouped) | 'mando final' |
| `essay` | string | Essay name | 'Hierro' |
| `threshold_normal` | float | 90th percentile | 45.2 |
| `threshold_alert` | float | 95th percentile | 58.7 |
| `threshold_critic` | float | 98th percentile | 72.1 |

**Calculation**:
- Based on historical data for each client independently
- Prevents data leakage between clients
- Recalculated in historical mode, loaded in incremental mode
- **Component Grouping**: Uses `componentNameNormalized` to group similar components (e.g., "mando final izquierdo" + "mando final derecho" → "mando final") ensuring sufficient sample size for statistical validity

**Sample Count**: ~300-500 limit combinations per client

---

## ☁️ S3 Storage

### Upload Behavior

- **Automatic**: Uploads after each client completes processing
- **Independent**: CDA and EMIN upload separately
- **Resilient**: Partial failures don't block other clients

### Upload Scope

✅ **Uploaded**:
- Silver layer: `{CLIENT}.parquet`
- Golden layer: All 3 files per client

❌ **Not Uploaded**:
- Bronze layer (raw data stays local)
- Auxiliary files (`essays_elements.xlsx`)

### S3 Paths

```
s3://{BUCKET_NAME}/MultiTechnique Alerts/oil/silver/{CLIENT}.parquet
s3://{BUCKET_NAME}/MultiTechnique Alerts/oil/golden/{client}/classified.parquet
s3://{BUCKET_NAME}/MultiTechnique Alerts/oil/golden/{client}/machine_status.parquet
s3://{BUCKET_NAME}/MultiTechnique Alerts/oil/golden/{client}/stewart_limits.parquet
```

### Configuration

Required environment variables in `.env`:
```bash
ACCESS_KEY=your_aws_access_key
SECRET_KEY=your_aws_secret_key
BUCKET_NAME=your_bucket_name
AWS_S3_PREFIX=MultiTechnique Alerts/oil/
```

---

## ✅ Data Quality Rules

### Bronze Layer
- ❌ No validation (accept as-is from laboratories)

### Silver Layer
- ✅ All dates in ISO format (YYYY-MM-DD)
- ✅ Essay values >= 0
- ✅ Component hours <= Machine hours
- ✅ No duplicate sample numbers
- ✅ All expected essay columns present
- ✅ Machine names normalized

### Golden Layer
- ✅ Every sample has essay_status for all essays
- ✅ Every sample has report_status
- ✅ essay_score matches essay classifications
- ✅ AI recommendations present for Alerta/Anormal reports
- ✅ Machine status aggregations match classified reports

---

## 📝 Change Log

### Version 2.1 (April 15, 2026)
- **Updated schemas to match actual data implementation**:
  - `classified.parquet`: Changed from individual `essay_status_{essay}` columns to aggregate metrics (`essays_broken`, `severity_score`, `desgaste_score`); added `ai_generated_at` timestamp
  - `machine_status.parquet`: Updated schema to reflect component-based aggregation with `unit_id`, `overall_status`, `machine_score`, `components_normal/alerta/anormal`, `priority_score`, `component_details` (JSON), and `machine_ai_recommendation`
  - Removed columns: `machineName`, `machineModel`, `componentName`, `lastSampleNumber`, `totalSamples`, `normalCount`, `alertaCount`, `anormalCount`, `avgEssayScore`
- **Documentation now reflects production data schemas as of April 2026**

### Version 2.0 (February 3, 2026)
- Simplified folder structure: bronze/silver/golden
- Changed from `{client}_classified.parquet` to `golden/{client}/classified.parquet`
- Added S3 auto-upload functionality
- Split Stewart Limits per client (no more shared file)
- Removed Excel exports (Parquet only)
- Updated to use client-specific folders in golden layer

### Version 1.0 (January 2026)
- Initial data contracts
- Three-layer architecture (raw/processed/to_consume)
- Shared Stewart Limits file
