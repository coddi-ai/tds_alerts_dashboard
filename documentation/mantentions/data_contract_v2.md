# Data Contract - Vista de Mantenciones General

**Fecha:** 28 de Septiembre 2026
**Versión:** 3.0
**Actualización:** Migración a las vistas de horas `query_7`, `query_8` y
`query_9`, KPIs mensuales en `query_4` y estado puntual en `query_10`.

---

## 📊 Archivos Parquet Requeridos

La pestaña usa `query_3` para actividad y detalle, `query_4`/`query_8` para
KPIs mensuales, `query_7`/`query_9` para la tendencia diaria, `query_5` para
MTBF/MTTR y `query_10` para el estado puntual del equipo. `query_6` queda
disponible para análisis de componentes. Las columnas históricas `*_70d` no
son una fuente válida para el informe nuevo.

Las vistas de horas son canónicas: unen intervalos solapados, parten cada
record por día calendario y exponen horas calendario como denominador. Sus
timestamps de calendario no llevan zona horaria; no deben parsearse con
`utc=True`.

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

### 2. `query_4_business_kpis.parquet` - KPIs mensuales de negocio

**Grano:** una fila por `machine_id × year_month`.

Incluye las horas de `query_8` y los agregados de actividad del mes. Las
columnas principales para el dashboard son:

| Columna | Descripción |
|---|---|
| `machine_id`, `machine_code` | Equipo |
| `year_month` | Mes calendario `YYYY-MM` |
| `intervention_hours` | Horas intervenidas deduplicadas |
| `downtime_hours` | Alias de `intervention_hours` para consumidores antiguos |
| `intervention_hours_raw` | Horas sin unir solapes, para auditoría |
| `dedup_hours_saved` | Diferencia entre horas brutas y deduplicadas |
| `calendar_hours_month` | Horas calendario del equipo en el mes |
| `pct_month_intervened` | Porcentaje del mes intervenido |
| `n_days_with_intervention`, `n_saturated_days` | Conteos diarios derivados |
| `n_actions`, `n_jobs`, `n_records_with_actions` | Volumen de actividad |
| `n_failure_records` | Records clasificados como fallas |
| `n_inspections`, `n_replacements`, `n_repairs`, `n_maintenances` | Acciones por tipo |
| `action_types`, `top_3_components` | Listas de actividad del mes |

Los campos con sufijo `*_70d` pertenecen al contrato anterior y no deben
usarse para calcular horas, disponibilidad o estado.

### 3. `query_7_intervention_hours_daily.parquet` - Horas por equipo-día

**Grano:** una fila por equipo y día con horas mayores que cero. La métrica
canónica es `intervention_hours`; `intervention_hours_raw` y
`dedup_hours_saved` sirven para auditoría. Incluye `day`, conteos de records,
`calendar_hours_day`, `pct_day_intervened`, `is_saturated_day` y
`touched_by_long_record`.

### 4. `query_8_intervention_hours_monthly.parquet` - Horas por equipo-mes

**Grano:** una fila por equipo y mes entre el primer y último mes con
actividad. Los meses intermedios aparecen con cero. Incluye las mismas
métricas de `query_7` agregadas al mes y añade
`calendar_hours_month`, `n_days_with_intervention` y `n_saturated_days`.

### 5. `query_9_fleet_intervention_daily.parquet` - Flota día a día

**Grano:** una fila por día del rango observado, incluidos días sin actividad.
`n_machines_intervened` y `intervention_hours` son métricas independientes.
También incluye `n_machines_fleet`, `calendar_hours_fleet`,
`pct_fleet_unavailable_calendar` y `avg_hours_per_intervened_machine`.

### 6. `query_10_equipment_status.parquet` - Estado puntual por equipo

**Grano:** una fila por equipo a `reference_date`. Incluye
`equipment_status`, `has_open_intervention`, fechas de última actividad y
conteos históricos. No se deriva desde el campo `ongoing` de la base.

### 7. `query_5_reliability_monthly.parquet` - Confiabilidad mensual

**Grano:** una fila por `machine_id × year_month`.

Incluye `source_system`, `machine_id`, `machine_code`, `year_month`,
`n_failures`, `mttr_hours`, `total_downtime_hours`, `n_mtbf_intervals`,
`mtbf_hours`, `mttf_hours` y `low_confidence`. Los valores nulos de métricas
son datos insuficientes para ese equipo-mes y no se convierten a cero. Una fila
con `low_confidence=true` se conserva y se marca visualmente cuando
`n_mtbf_intervals < 3`.

### 8. `query_6_component_failure_ranking.parquet` - Ranking acumulado

**Grano:** componente por equipo y fuente, acumulado histórico; no es una
serie temporal. Incluye `source_system`, `machine_id`, `machine_code`,
`component_id`, `component_name`, `n_failure_records` y
`n_failure_actions`. La pestaña lo presenta como ranking filtrable por equipo,
sin interpretarlo como una tasa mensual.

`query_6` se consume como ranking histórico y no como una serie mensual de
confiabilidad.

---

## 🔧 Lógica de Negocio Implementada

### Status de Equipos (SANO vs DETENIDO)

**Fuente:** `query_10_equipment_status.parquet` → columnas `equipment_status` y
`has_open_intervention`

**Reglas:**
```python
if equipment_status == "DETENIDO" or has_open_intervention == True:
    status = "DETENIDO"
else:
    status = "SANO"  # equipment_status == "OPERATIVO"
```

El estado actual se lee por equipo desde `query_10`; no se asume que todos
los equipos estén operativos y no se usa el flag histórico `ongoing`.

---

### Downtime mensual canónico

**Fuente:** `query_8_intervention_hours_monthly.parquet` → columna
`intervention_hours`

**Cálculo del extracto de referencia:**
```python
total_downtime_month = df_month['intervention_hours'].sum()
```

**Datos actuales:**
- `intervention_hours` es la unión deduplicada de records y representa el
  total de horas-equipo del mes seleccionado.
- `calendar_hours_month` es el denominador explícito; no se infieren horas
  desde el conteo de acciones.

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

### Horas fuera de servicio por día

**Fuente primaria:** `query_9_fleet_intervention_daily.parquet` para la flota
completa y `query_7_intervention_hours_daily.parquet` cuando se filtra por
unidad o flota.

**Cálculo:** las vistas ya cortan cada record por día calendario y unen
solapes. La métrica publicada es:
```python
hours_equipment = intervention_hours
```

No se convierten acciones a horas. El resultado es **horas-equipo**: una
flota puede superar 24 h en un día porque suma varios equipos; un equipo
individual no supera 24 h por día después de la distribución del intervalo.

---

## 📈 KPIs Visualizados en el Dashboard

### 1. Equipos Totales
```python
total = len(df_kpis)  # 11 máquinas
```

### 2. Equipos Sanos
```python
sanos = (df_status['equipment_status'] == 'OPERATIVO').sum()
```

### 3. Equipos Detenidos
```python
detenidos = (df_status['equipment_status'] == 'DETENIDO').sum()
```

### 4. Horas intervenidas del mes
```python
total_intervention_hours = df_month['intervention_hours'].sum()

> El Resumen usa las horas deduplicadas de query8 y no las columnas históricas
> `*_70d`.
```

---

## 🗂️ Estructura de Datos en Repository

### Parquet Cache Structure
```python
{
    "actions": load_maintenance_actions_all_equipment(),  # acciones
    "records": load_maintenance_unit_records_actions(),   # compatibilidad
    "kpis": load_business_kpis(),                         # query4 mensual
    "hours_daily": load_maintenance_intervention_hours_daily(),  # query7
    "hours_monthly": load_maintenance_intervention_hours_monthly(),  # query8
    "fleet_daily": load_maintenance_fleet_intervention_daily(),  # query9
    "equipment_status": load_maintenance_equipment_status(),  # query10
}
```

### Métodos Principales

| Método | Fuente Principal | Output |
|--------|------------------|--------|
| `get_status_counts()` | `query_10` | SANO/DETENIDO counts |
| `get_downtime_mtd()` | `query_8`/`query_9` | Horas-equipo del período |
| `get_last_detentions()` | `query_3` Actions | Top 3 detenciones/máquina |
| `get_jobs_last_week()` | `query_3` Actions | 100 trabajos recientes |
| `get_downtime_by_day_mtd()` | `query_7`/`query_9` | Horas-equipo fuera de servicio por día |

---

## 🔄 Ventana Temporal

El Resumen productivo evalúa el mes seleccionado. Usa
`calendar_hours_month` como denominador y no aplica una ventana móvil de 70
días.

**Justificación:**
- Los datos actuales son de enero 2026
- Fecha actual: marzo 2026
- Las vistas nuevas permiten reconciliar horas por equipo-día, equipo-mes y
  flota-día.

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
   - `has_open_intervention` puede ser nulo → el estado se resuelve con
     `equipment_status`

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
                ├── query_3_actions_all_equipment.parquet
                ├── query_4_business_kpis.parquet          # KPIs por equipo-mes
                ├── query_5_reliability_monthly.parquet    # MTBF / MTTR
                ├── query_6_component_failure_ranking.parquet
                ├── query_7_intervention_hours_daily.parquet
                ├── query_8_intervention_hours_monthly.parquet
                ├── query_9_fleet_intervention_daily.parquet
                └── query_10_equipment_status.parquet
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
    load_business_kpis,
    load_maintenance_intervention_hours_daily,
    load_maintenance_intervention_hours_monthly,
    load_maintenance_fleet_intervention_daily,
    load_maintenance_equipment_status,
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

df_daily = load_maintenance_intervention_hours_daily()
df_monthly = load_maintenance_intervention_hours_monthly()
df_fleet = load_maintenance_fleet_intervention_daily()
df_status = load_maintenance_equipment_status()

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

1. **Usar `query_6_component_failure_ranking`:**
   - Incorporar un ranking de componentes cuando la vista productiva lo requiera.

2. **Agregar horas operativas si aparece una fuente gobernada:**
   - Mantener `calendar_hours_month` como referencia hasta disponer de
     horómetro o telemetría operativa.

3. **Confirmar la asunción horaria de EMIN:**
   - El pipeline documenta qué reloj local corresponde a cada fuente.

---

## 📝 Changelog

### v3.0 - 28 de Septiembre 2026 (Vistas canónicas de horas)
- ✅ `query_4` migrado de una ventana móvil de 70 días a grano equipo-mes.
- ✅ `query_7`, `query_8` y `query_9` como fuentes canónicas de horas.
- ✅ `query_10` como fuente de estado puntual por equipo.
- ✅ La pestaña ya no usa columnas `*_70d` para sus KPIs de tiempo.

### v2.1 - 12 de Marzo 2026 (Actualización de Arquitectura)
- ✅ Consolidado loaders de mantenciones en `src/data/loaders.py`
- ✅ Eliminado archivo redundante `maintenance_loaders.py`
- ✅ Ruta de producción: `data/mantentions/golden/{client}/Maintance_Labeler_Views/`
- ✅ Soporte para variable de entorno `CLIENT_NAME`
- ✅ Fallback automático a root para desarrollo local
- ✅ Funciones con parámetro `client` configurable

### v2.0 - 12 de Marzo 2026 (Contrato histórico)
- ✅ Migración de `query_1`, `query_2`, `query_3` a `query_3_actions_all_equipment` y `query_4_business_kpis`
- ✅ Uso de KPIs pre-calculados para mejor rendimiento
- ✅ Simplificación de lógica de status usando `has_ongoing_maintenance`
- ✅ Downtime mensual desde intervalos `query_2`/`query_3`, con solapes unidos
- ✅ Mantención de compatibilidad con estructura de dashboard existente

### v1.0 - Versión Original
- Uso de `query_1.parquet`, `query_2.parquet`, `query_3.parquet`
- Cálculo manual de todos los KPIs
- Lógica de threshold de 70 días para ongoing

---

**Documento actualizado:** 28 de Septiembre 2026
**Autor:** Sistema de Migración de Datos  
**Versión:** 3.0
