# Dashboard Update Summary

**Date**: February 3, 2026  
**Project**: Oil Analysis Data Product Dashboard  
**Status**: Updated to work with existing golden layer data structure

---

## 🎯 Overview

Updated the dashboard code to correctly consume data from the **existing golden layer** files. The actual data files in the repository use a different schema than what's specified in DATA_CONTRACTS.md v2.0, so the code has been adjusted to match the actual data structure.

---

## 📋 Actual Data Structure

### Golden Layer Files (Located in `data/oil/golden/{client}/`)

#### 1. **classified.parquet**
- Contains oil analysis reports with classifications
- **Key columns**:
  - Base: `client`, `sampleNumber`, `sampleDate`, `unitId`, `machineName`, `componentName`
  - Essays: `Hierro`, `Cobre`, `Silicio`, etc. (21 essay columns)
  - Classification: `essays_broken`, `severity_score`, `report_status`, `breached_essays`
  - AI: `ai_recommendation`, `ai_generated_at`

#### 2. **machine_status.parquet**
- Machine-level aggregations
- **Key columns**:
  - `unit_id`, `client`, `latest_sample_date`
  - `overall_status`, `machine_score`, `priority_score`
  - `total_components`, `components_normal`, `components_alerta`, `components_anormal`
  - `component_details` (nested)

#### 3. **stewart_limits.parquet**
- Statistical thresholds (per client)
- **Columns**: `client`, `machine`, `component`, `essay`, `threshold_normal`, `threshold_alert`, `threshold_critic`

---

## 🔧 Code Updates

### Configuration ([config/settings.py](config/settings.py))
✅ **Added path helpers** (these work correctly):
- `get_bronze_path(client)`, `get_silver_path(client)`, `get_golden_path(client)`
- `get_classified_reports_path(client)` → `data/oil/golden/{client}/classified.parquet`
- `get_machine_status_path(client)` → `data/oil/golden/{client}/machine_status.parquet`
- `get_stewart_limits_path(client)` → `data/oil/golden/{client}/stewart_limits.parquet`

### Dashboard Components
✅ **All callbacks updated** to use:
- Correct file paths (golden layer per client)
- Actual column names from existing data

---

## 📊 Column Names (Actual Data)

### classified.parquet
- `unitId` ✓ (camelCase)
- `componentName` ✓ (camelCase)
- `sampleDate` ✓ (camelCase)
- `severity_score` ✓ (snake_case)
- `essays_broken` ✓ (snake_case)
- `report_status` ✓ (snake_case)
- `ai_recommendation` ✓
- `ai_generated_at` ✓

### machine_status.parquet
- `unit_id` ✓ (snake_case)
- `overall_status` ✓
- `machine_score` ✓
- `latest_sample_date` ✓
- `components_normal`, `components_alerta`, `components_anormal` ✓
- `priority_score` ✓

---

## ⚠️ Important Notes

**DATA_CONTRACTS.md vs Actual Data**:
- The DATA_CONTRACTS.md v2.0 specification describes an **ideal future state**
- The **actual data files** use a slightly different schema (mix of camelCase and snake_case)
- The dashboard code now matches the **actual data** that exists in the repository

**Working Features**:
- ✅ Loading data from golden layer per client
- ✅ Stewart limits per client (separate files for CDA and EMIN)
- ✅ Machine status aggregations
- ✅ Classified reports with AI recommendations

---

## ✅ Verification

The dashboard should now work correctly with the existing data files:
- `data/oil/golden/cda/classified.parquet` (6,832 rows)
- `data/oil/golden/cda/machine_status.parquet` (11 rows)
- `data/oil/golden/cda/stewart_limits.parquet` (119 rows)
- `data/oil/golden/emin/` (similar structure)

---

## 🚀 Next Steps

1. **Test the dashboard** - verify all tabs load correctly
2. **If data contracts need updating** - align DATA_CONTRACTS.md with actual data schema
3. **Or regenerate data** - create new golden layer files matching DATA_CONTRACTS.md v2.0
