# Data Contracts - Mantentions Data Product

**Version**: 1.0  
**Last Updated**: February 4, 2026  
**Owner**: Mantentions Data Product Team

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Data Layer Architecture](#data-layer-architecture)
3. [Golden Layer](#golden-layer)
4. [Data Quality Rules](#data-quality-rules)

---

## 🎯 Overview

This document defines the data contracts for the Mantentions (Maintenance) Data Product, which tracks and summarizes maintenance activities performed on mining equipment.

**Data Product Purpose**: Provide structured records of maintenance interventions, enabling tracking of maintenance frequency, activity patterns, and resource allocation across the fleet.

**Primary Consumers**:
- Multi-Technical Alerts Dashboard
- Maintenance planning systems
- Resource allocation tools
- Performance analytics

---

## 🏗️ Data Layer Architecture

### Local Storage Structure

```
data/
└── mantentions/
    └── golden/                    # Processed maintenance reports
        └── {client}/
            ├── 01-2025.csv        # Week 1, 2025
            ├── 02-2025.csv        # Week 2, 2025
            └── ww-yyyy.csv        # Week-Year format
```

**File Naming Convention**: `ww-yyyy.csv`
- `ww`: ISO week number (01-53)
- `yyyy`: Year (4 digits)

**Example**: `32-2025.csv` = Week 32 of 2025

---

## 🏆 Golden Layer

**Purpose**: Weekly maintenance activity summaries per equipment unit  
**Update Frequency**: Weekly (new file per week)  
**Retention**: Historical archive (all weeks retained)  
**Format**: CSV

### Location

```
Local: data/mantentions/golden/{client}/ww-yyyy.csv
```

---

### Weekly Maintenance Report (`ww-yyyy.csv`)

**Purpose**: Comprehensive maintenance activity log per unit for a specific week

**Schema**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `UnitId` | string | Equipment unit identifier | `'CAT-001'` |
| `Tasks_List` | dict | Nested activities by day and system | See below |
| `Summary` | string | AI-generated summary of week's activities | `'Se realizaron 3 intervenciones en el sistema de motor...'` |

---

### `Tasks_List` Structure

The `Tasks_List` column contains a **nested dictionary** with the following structure:

```python
{
    "Day D": {
        "System S": [
            "Activity 1",
            "Activity 2",
            "Activity 3"
        ],
        "System T": [
            "Activity 4"
        ]
    },
    "Day E": {
        "System S": [
            "Activity 5"
        ]
    }
}
```

**Structure Explanation**:
- **Level 1 (Day)**: Date when activities were performed
  - Format: `"YYYY-MM-DD"` or day name
- **Level 2 (System)**: Equipment system affected
  - Examples: `"Motor"`, `"Transmision"`, `"Hidraulico"`, `"Electrico"`
- **Level 3 (Activities)**: List of specific maintenance tasks
  - Examples: `"Cambio de filtro"`, `"Inspeccion visual"`, `"Ajuste de tension"`

---

### Example Record

```csv
UnitId,Tasks_List,Summary
CAT-001,"{""2025-01-15"": {""Motor"": [""Cambio de aceite"", ""Reemplazo de filtro de aire""], ""Transmision"": [""Inspeccion de niveles""]}, ""2025-01-17"": {""Hidraulico"": [""Revision de mangueras"", ""Cambio de filtro hidraulico""]}}","Se realizaron 5 actividades de mantenimiento durante la semana 03-2025. Motor: 2 actividades (cambio de aceite y filtro). Transmision: 1 inspeccion. Hidraulico: 2 actividades preventivas."
CAT-002,"{""2025-01-16"": {""Electrico"": [""Revision de bateria"", ""Limpieza de terminales""]}}","Se realizaron 2 actividades en el sistema electrico. Mantenimiento preventivo de bateria completado."
```

---

### Common Systems

Standard system categories used in `Tasks_List`:

| System | Spanish | Description |
|--------|---------|-------------|
| `Engine` | `Motor` | Engine and related components |
| `Transmission` | `Transmision` | Transmission system |
| `Hydraulic` | `Hidraulico` | Hydraulic systems |
| `Electrical` | `Electrico` | Electrical and electronic systems |
| `Brake` | `Frenos` | Braking system |
| `Cooling` | `Enfriamiento` | Cooling and radiator systems |
| `Fuel` | `Combustible` | Fuel system |
| `Tire` | `Neumaticos` | Tires and wheels |
| `Structural` | `Estructura` | Structural components |
| `Other` | `Otros` | Miscellaneous activities |

---

### Common Activities

Typical maintenance activities found in task lists:

**Preventive Maintenance**:
- `Cambio de aceite` - Oil change
- `Reemplazo de filtros` - Filter replacement
- `Inspeccion visual` - Visual inspection
- `Lubricacion` - Lubrication
- `Ajuste de tension` - Tension adjustment
- `Revision de niveles` - Level checks

**Corrective Maintenance**:
- `Reparacion de fuga` - Leak repair
- `Reemplazo de componente` - Component replacement
- `Ajuste de parametros` - Parameter adjustment
- `Diagnostico de falla` - Failure diagnosis

**Specialized Activities**:
- `Analisis de vibraciones` - Vibration analysis
- `Termografia` - Thermography
- `Ultrasonido` - Ultrasound inspection
- `Alineacion` - Alignment

---

## ✅ Data Quality Rules

### Golden Layer

**File-level Rules**:
- ✅ One file per week per client
- ✅ Consistent naming: `ww-yyyy.csv` format
- ✅ All units in fleet should appear (even if no activities)
- ✅ No duplicate UnitId within a week

**Record-level Rules**:
- ✅ Valid UnitId (matches fleet registry)
- ✅ `Tasks_List` is valid JSON/dict structure
- ✅ Date keys in `Tasks_List` within the week's date range
- ✅ System names from predefined vocabulary
- ✅ Activities are non-empty strings
- ✅ Summary is present and coherent

**Data Validation**:
```python
# Validate Tasks_List structure
import json

def validate_tasks_list(tasks_str):
    tasks = json.loads(tasks_str)
    
    # Check structure
    assert isinstance(tasks, dict), "Tasks must be dict"
    
    for day, systems in tasks.items():
        assert isinstance(systems, dict), f"Day {day} must contain dict"
        
        for system, activities in systems.items():
            assert isinstance(activities, list), f"System {system} must have list"
            assert len(activities) > 0, f"System {system} has no activities"
            assert all(isinstance(a, str) for a in activities), "Activities must be strings"
    
    return True
```

---

## 📊 Data Volume Estimates

### Per Client Weekly Volume

| Metric | Typical Range |
|--------|---------------|
| Units with maintenance | 20-50 |
| Total activities | 100-300 |
| File size | 50-200 KB |
| Files per year | 52 |

**Note**: Volumes vary based on:
- Fleet size
- Maintenance frequency
- Level of detail captured
- Preventive vs corrective balance

---

## 🔄 Data Flow

```
Maintenance Management System (CMMS)
       ↓
  Weekly Aggregation
       ↓
  Golden Layer
  (ww-yyyy.csv per week)
       ↓
  Dashboard / Analytics
```

---

## 📈 Use Cases

### 1. Maintenance Frequency Analysis
Track how often each unit receives maintenance:
```python
import glob
import pandas as pd

# Load all weeks
files = glob.glob('data/mantentions/golden/*/??-????.csv')
all_maintenance = pd.concat([pd.read_csv(f) for f in files])

# Count interventions per unit
interventions = all_maintenance['UnitId'].value_counts()
```

### 2. System Focus Analysis
Identify which systems receive most attention:
```python
import json

def extract_systems(tasks_str):
    tasks = json.loads(tasks_str)
    systems = []
    for day, day_tasks in tasks.items():
        systems.extend(day_tasks.keys())
    return systems

all_maintenance['Systems'] = all_maintenance['Tasks_List'].apply(extract_systems)
system_counts = pd.Series([s for systems in all_maintenance['Systems'] for s in systems]).value_counts()
```

### 3. Activity Pattern Recognition
Identify recurring maintenance patterns:
```python
def extract_activities(tasks_str):
    tasks = json.loads(tasks_str)
    activities = []
    for day, systems in tasks.items():
        for system, acts in systems.items():
            activities.extend(acts)
    return activities

all_maintenance['Activities'] = all_maintenance['Tasks_List'].apply(extract_activities)
activity_counts = pd.Series([a for acts in all_maintenance['Activities'] for a in acts]).value_counts()
```

---

## 🔗 Integration with Other Data Products

### Correlation with Alerts
Match maintenance activities with alert occurrences:
```python
# Join maintenance with alerts
# Week reference in consolidated_alerts.csv: Semana_Resumen_Mantencion
alerts_with_maintenance = alerts.merge(
    maintenance,
    left_on=['UnitId', 'Semana_Resumen_Mantencion'],
    right_on=['UnitId', 'week_number']
)
```

### Correlation with Oil Analysis
Identify if maintenance followed oil alerts:
```python
# Check if maintenance occurred after oil anomalies
oil_alerts = oil_data[oil_data['report_status'] == 'Anormal']
maintenance_response = maintenance[maintenance['UnitId'].isin(oil_alerts['unitId'])]
```

---

## 📝 Change Log

### Version 1.0 (February 2026)
- Initial mantentions data contracts
- Weekly report structure
- Nested task organization by day and system
- AI-generated summaries
