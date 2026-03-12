# Data Contract V2 - Vista de Mantenciones General

**Fecha:** 12 de Marzo 2026  
**Versión:** 2.0  
**Actualización:** Migración a `query_3_actions_all_equipment.parquet` y `query_4_business_kpis.parquet`

---

## 📊 Archivos Parquet Requeridos

### 1. `query_3_actions_all_equipment.parquet` - Acciones de Mantenimiento Detalladas

**Propósito:** Registro completo de todas las acciones de mantenimiento realizadas en todos los equipos.

**Dimensiones:** 659 filas × 21 columnas

**Columnas:**

| Columna | Tipo | Descripción | Ejemplo |
|---------|------|-------------|---------|
| `action_id` | string | ID único de la acción | `"f3c84c44-5e1e-4c36-9c9f-4d0c1b972a2a"` |
| `job_id` | string | ID del trabajo de mantenimiento | `"job_001"` |
| `record_id` | string | ID del registro de mantenimiento | `"rec_100"` |
| `machine_id` | string (UUID) | ID único de la máquina | `"1b361a10-1bf9-4c59-a679-bbfb9451fa0a"` |
| `machine_code` | string | Código de la máquina | `"t10"`, `"t11"`, `"t12"`, etc. |
| `event_ts` | string (datetime) | Timestamp del evento | `"2026-01-15 10:30:00"` |
| `change_date` | datetime64[us] | Fecha del cambio registrado | `2026-01-15` |
| `action_type_name` | string | Tipo de acción | `"Cambio de filtro"`, `"Inspección"` |
| `job_system_name` | string | Sistema del trabajo | `"Sistema Hidráulico"`, `"Equipo"` |
| `job_subsystem_name` | string | Subsistema del trabajo | `"Filtros"`, `"Motor"` |
| `action_subsystem_name` | string | Subsistema de la acción | `"Filtros"` |
| `action_system_name` | string | Sistema de la acción | `"Sistema Hidráulico"` |
| `component_names` | object (array) | Nombres de componentes afectados | `["Filtro hidráulico", "Bomba"]` |
| `component_count` | int64 | Número de componentes | `2` |
| `target_level` | string | Nivel objetivo | `"Preventivo"`, `"Correctivo"` |
| `action_detail_raw` | string | Detalle crudo de la acción | Texto original |
| `action_detail_clean` | string | Detalle limpio de la acción | Texto procesado |
| `action_detail_source` | object | Fuente del detalle | Sistema origen |
| `action_detail_version` | object | Versión del detalle | Versión del dato |
| `source_system` | string | Sistema fuente | `"SAP"`, `"Manual"` |
| `record_original_text` | string | Texto original del registro | Descripción completa |

**Valores Únicos:**
- **machine_code:** 10 máquinas (`t09`, `t10`, `t11`, `t12`, `t14`, `t15`, `t16`, `t17`, `t18`, + valores NaN)
- **action_type_name:** 92 tipos diferentes de acciones
- **job_system_name:** 7 sistemas principales
- **event_ts:** 220 timestamps únicos
- **change_date:** 22 fechas únicas

**Ejemplo de registro:**
```python
{
    'action_id': 'f3c84c44-5e1e-4c36-9c9f-4d0c1b972a2a',
    'job_id': 'job_123',
    'record_id': 'rec_456',
    'machine_code': 't10',
    'event_ts': '2026-01-15 10:30:00',
    'change_date': '2026-01-15',
    'action_type_name': 'Cambio de filtro',
    'job_system_name': 'Sistema Hidráulico',
    'job_subsystem_name': 'Filtros',
    'action_detail_clean': 'Reemplazo de filtro hidráulico principal'
}
```

---

### 2. `query_4_business_kpis.parquet` - KPIs de Negocio Pre-calculados

**Propósito:** Métricas de negocio pre-calculadas para cada equipo, optimizando el rendimiento del dashboard.

**Dimensiones:** 11 filas × 18 columnas (una fila por máquina)

**Columnas:**

| Columna | Tipo | Descripción | Ejemplo |
|---------|------|-------------|---------|
| `machine_code` | string | Código de la máquina | `"t10"` |
| `machine_id` | string (UUID) | ID único de la máquina | `"9a0d66e4-9c4c-4e89-8b26-251e419d6e1a"` |
| `equipment_status` | string | Estado del equipo | `"OPERATIVO"`, `"DETENIDO"` |
| `has_ongoing_maintenance` | boolean | Tiene mantenimiento en curso | `True`, `False`, `<NA>` |
| `last_ongoing_date` | object (datetime) | Fecha del último mantenimiento ongoing | `None`, `"2026-01-15"` |
| `days_since_last_maintenance` | Int32 | Días desde último mantenimiento | `19`, `21`, `<NA>` |
| `last_action_date` | datetime64[us] | Fecha de última acción | `2026-01-02 22:30:00` |
| `total_actions_70d` | int64 | Total de acciones en 70 días | `24`, `19`, `15` |
| `ongoing_actions_70d` | int64 | Acciones ongoing en 70 días | `0` |
| `downtime_hours_70d` | float64 | **Horas de detención en 70 días** | `3088.8`, `1820.2` |
| `maintenance_frequency_per_day` | float64 | Frecuencia diaria de mantenimiento | `0.343`, `0.271` |
| `action_types_70d` | object (array) | Tipos de acciones en 70 días | Lista de tipos |
| `top_3_components` | object (array) | Top 3 componentes mantenidos | Lista de componentes |
| `inspections_70d` | int64 | Inspecciones en 70 días | `5`, `3` |
| `replacements_70d` | int64 | Reemplazos en 70 días | `8`, `6` |
| `repairs_70d` | int64 | Reparaciones en 70 días | `4`, `2` |
| `maintenances_70d` | int64 | Mantenimientos en 70 días | `12`, `8` |
| `reference_date` | datetime64[us] | Fecha de referencia del cálculo | `2026-01-22 10:10:00` |

**Valores Únicos:**
- **machine_code:** 11 máquinas (`t09`, `t10`, `t11`, `t12`, `t14`, `t15`, `t16`, `t17`, `t18`, `t24`, + 1 más)
- **equipment_status:** 1 valor único (`"OPERATIVO"`)
- **has_ongoing_maintenance:** Todos `<NA>` en datos actuales
- **days_since_last_maintenance:** 5 valores únicos (16-21 días, + `<NA>`)

**Ejemplo de registro:**
```python
{
    'machine_code': 't10',
    'machine_id': '9a0d66e4-9c4c-4e89-8b26-251e419d6e1a',
    'equipment_status': 'OPERATIVO',
    'has_ongoing_maintenance': False,
    'last_ongoing_date': None,
    'days_since_last_maintenance': 19,
    'last_action_date': '2026-01-02 22:30:00',
    'total_actions_70d': 24,
    'ongoing_actions_70d': 0,
    'downtime_hours_70d': 3088.8,
    'maintenance_frequency_per_day': 0.343,
    'reference_date': '2026-01-22 10:10:00'
}
```

---

## 🔧 Lógica de Negocio Implementada

### Status de Equipos (SANO vs DETENIDO)

**Fuente:** `query_4_business_kpis.parquet` → columna `has_ongoing_maintenance`

**Reglas:**
```python
if has_ongoing_maintenance == True:
    status = "DETENIDO"
else:
    status = "SANO"  # equipment_status == "OPERATIVO"
```

**Estado Actual (según datos):**
- Todos los equipos tienen `has_ongoing_maintenance = <NA>` (no aplica)
- Todos los equipos tienen `equipment_status = "OPERATIVO"`
- **Resultado:** Todos los equipos están **SANO**

---

### Downtime Total (70 días)

**Fuente:** `query_4_business_kpis.parquet` → columna `downtime_hours_70d`

**Cálculo:**
```python
total_downtime = df_kpis['downtime_hours_70d'].sum()
```

**Datos actuales:**
- **Total de downtime:** 6,594.28 horas (suma de 11 máquinas)
- **Máquina con mayor downtime:** t18 (3088.8 horas)
- **Máquina con menor downtime:** t24 (0.08 horas)

---

### Últimas Detenciones (por máquina)

**Fuente:** `query_3_actions_all_equipment.parquet`

**Agrupación:** Por `machine_id` (unit_id) y `record_id` - cada combinación representa un período de detención único

**Cálculo:**
```python
# Agrupar por machine_id y record_id
for (machine_id, record_id, machine_code), group in df_actions.groupby(['machine_id', 'record_id', 'machine_code']):
    # Tiempo de detención: diferencia entre primera y última acción del record
    start_date = group['event_ts'].min()
    end_date = group['event_ts'].max()
    duration_hours = (end_date - start_date).total_seconds() / 3600
    
    # Array de todos los action_type_name únicos involucrados
    action_types = group['action_type_name'].dropna().unique()
    job_types = ", ".join(action_types)
```

**Lógica:**
- Cada `record_id` representa un ciclo de mantenimiento
- Se filtra por registros con `machine_id` y `record_id` válidos (no NaN)
- El período de detención va desde la primera hasta la última acción del record
- Los tipos de trabajo incluyen **todos** los `action_type_name` únicos (no limitado a 3)

**Output:** Top N detenciones más recientes por máquina (ordenadas por `start_date` descendente)

---

### Trabajos de la Última Semana (70 días)

**Fuente:** `query_3_actions_all_equipment.parquet`

**Filtro:** `change_date >= (now - 70 días)`

**Campos retornados:**
- `job_id`
- `machine_code`
- `job_system_name` (renombrado a `system_name`)
- `job_subsystem_name` (renombrado a `subsystem_name`)
- `action_type_name` (renombrado a `job_type`)
- `event_ts` (renombrado a `start_date`)
- `action_detail_clean` (renombrado a `notes`)

**Límite:** 100 registros más recientes

---

### Downtime por Día

**Fuente:** `query_3_actions_all_equipment.parquet`

**Agrupación:** Por `change_date`

**Cálculo:**
```python
daily_counts = df_actions.groupby('change_date').size()
downtime_hours = daily_counts * 1.5  # 1.5 horas por acción (estimado)
```

**Justificación:**
- Cada acción registrada representa ~1.5 horas de trabajo de mantenimiento
- Es un proxy basado en la actividad diaria registrada

---

## 📈 KPIs Visualizados en el Dashboard

### 1. Equipos Totales
```python
total = len(df_kpis)  # 11 máquinas
```

### 2. Equipos Sanos
```python
sanos = total - df_kpis['has_ongoing_maintenance'].sum()
```

### 3. Equipos Detenidos
```python
detenidos = df_kpis['has_ongoing_maintenance'].sum()
```

### 4. Horas Detenidas (70 días)
```python
total_downtime = df_kpis['downtime_hours_70d'].sum()
```

---

## 🗂️ Estructura de Datos en Repository

### Parquet Cache Structure
```python
{
    "actions": load_maintenance_actions_all_equipment(),  # 659 rows
    "kpis": load_business_kpis()                         # 11 rows
}
```

### Métodos Principales

| Método | Fuente Principal | Output |
|--------|------------------|--------|
| `get_status_counts()` | `query_4` KPIs | SANO/DETENIDO counts |
| `get_downtime_mtd()` | `query_4` KPIs | Total downtime_hours_70d |
| `get_last_detentions()` | `query_3` Actions | Top 3 detenciones/máquina |
| `get_jobs_last_week()` | `query_3` Actions | 100 trabajos recientes |
| `get_downtime_by_day_mtd()` | `query_3` Actions | Downtime diario estimado |

---

## 🔄 Ventana Temporal

**Período de análisis:** 70 días (10 semanas)

**Justificación:**
- Los datos actuales son de enero 2026
- Fecha actual: marzo 2026
- 70 días permite capturar actividad histórica reciente
- Alineado con los KPIs pre-calculados (`*_70d`)

---

## ✅ Validaciones de Datos

### Validaciones Automáticas

1. **Conversión de fechas:**
   ```python
   df['event_ts'] = pd.to_datetime(df['event_ts'])
   df['change_date'] = pd.to_datetime(df['change_date'])
   ```

2. **Manejo de valores NaN:**
   - `machine_code` puede tener NaN → filtrado en agregaciones
   - `has_ongoing_maintenance` puede ser `<NA>` → tratado como False

3. **Agrupaciones robustas:**
   - Uso de `.dropna()` en operaciones críticas
   - Validación de DataFrames vacíos antes de procesar

---

## 📁 Ubicación de Archivos

### Estructura de Producción

```
data/
└── mantentions/
    └── golden/
        └── {client}/                          # ej: "cda"
            └── Maintance_Labeler_Views/
                ├── query_3_actions_all_equipment.parquet  # 659 acciones
                └── query_4_business_kpis.parquet          # 11 máquinas con KPIs
```

### Estructura de Desarrollo (Fallback)

Para desarrollo local, los archivos pueden estar en el root del proyecto:

```
proyecto_root/
├── query_3_actions_all_equipment.parquet
└── query_4_business_kpis.parquet
```

**Configuración:**
- Por defecto usa `client = "cda"`
- Se puede configurar con variable de entorno: `CLIENT_NAME=cda`
- El código automáticamente detecta si usa la estructura de producción o el fallback

---

## 🚀 Código de Uso

### Carga de Datos
```python
from src.data.loaders import (
    load_maintenance_actions_all_equipment,
    load_business_kpis
)

# Cargar acciones de mantenimiento
# Por defecto usa client="cda" y busca en data/mantentions/golden/cda/Maintance_Labeler_Views/
df_actions = load_maintenance_actions_all_equipment()
print(f"Acciones cargadas: {len(df_actions)}")

# Cargar para otro cliente
df_actions = load_maintenance_actions_all_equipment(client="otro_cliente")

# Cargar KPIs de negocio
df_kpis = load_business_kpis()
print(f"Máquinas con KPIs: {len(df_kpis)}")

# Usar variable de entorno (opcional)
# export CLIENT_NAME=cda
# El loader automáticamente usará el valor de CLIENT_NAME
```

### Uso en Repository
```python
from src.data.maintenance_repository import get_repository

# Obtener repository en modo parquet
repo = get_repository(mode="parquet")

# Obtener datos para el dashboard
df_status = repo.get_status_counts()
df_downtime = repo.get_downtime_mtd()
df_detentions = repo.get_last_detentions(n_per_machine=3)
df_jobs = repo.get_jobs_last_week()
df_daily = repo.get_downtime_by_day_mtd()
```

---

## 🔍 Mejoras Futuras

1. **Calcular `has_ongoing_maintenance` dinámicamente:**
   - Actualmente todos los valores son `<NA>`
   - Implementar lógica basada en `days_since_last_maintenance`

2. **Usar `action_types_70d` y `top_3_components`:**
   - Aprovechar arrays pre-calculados en `query_4`
   - Crear visualizaciones de componentes más afectados

3. **Integrar `inspections_70d`, `replacements_70d`, etc.:**
   - Mostrar breakdown de tipos de mantenimiento
   - Gráficos de distribución por categoría

4. **Optimizar estimación de downtime:**
   - Actualmente usa 1.5 horas/acción
   - Considerar usar datos reales de duración si están disponibles

---

## 📝 Changelog

### v2.1 - 12 de Marzo 2026 (Actualización de Arquitectura)
- ✅ Consolidado loaders de mantenciones en `src/data/loaders.py`
- ✅ Eliminado archivo redundante `maintenance_loaders.py`
- ✅ Ruta de producción: `data/mantentions/golden/{client}/Maintance_Labeler_Views/`
- ✅ Soporte para variable de entorno `CLIENT_NAME`
- ✅ Fallback automático a root para desarrollo local
- ✅ Funciones con parámetro `client` configurable

### v2.0 - 12 de Marzo 2026
- ✅ Migración de `query_1`, `query_2`, `query_3` a `query_3_actions_all_equipment` y `query_4_business_kpis`
- ✅ Uso de KPIs pre-calculados para mejor rendimiento
- ✅ Simplificación de lógica de status usando `has_ongoing_maintenance`
- ✅ Downtime total directo desde `downtime_hours_70d`
- ✅ Mantención de compatibilidad con estructura de dashboard existente

### v1.0 - Versión Original
- Uso de `query_1.parquet`, `query_2.parquet`, `query_3.parquet`
- Cálculo manual de todos los KPIs
- Lógica de threshold de 70 días para ongoing

---

**Documento generado:** 12 de Marzo 2026  
**Autor:** Sistema de Migración de Datos  
**Versión:** 2.0
