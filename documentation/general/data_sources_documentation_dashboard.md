# Data Sources Documentation — Dashboard

Audit of the real data sources behind every page and tab of the dashboard, and the
reference the "Fuentes de Datos" popover is built from
(`documentation/general/general_specs_v2/technical_requirement_data_sources_popover.md`, step 6).

- **Audited:** 2026-11-10, branch `data-sources-popover` (from `origin/dev` 502e71e).
- **Method:** every page/tab was traced from its layout, through its callbacks, to the loader that
  reads the data and the file it opens. The predictive finding (section 7) was also reproduced
  with the local data mirror (`data/predictive/golden/capstone`, `.../cda`).
- **Scope of the UI change:** only the pages that showed the old strip get the popover (Resumen
  General, Alertas, Telemetría, Aceite, Predictivo Motor/Transmisión). The remaining pages are
  audited here but have no sources indicator; see section 10.

## 1. How a source's status and "last update" are determined

These rules are shared by every popover and are unchanged by the redesign.

**Availability** (`dashboard/components/source_status.py`, `src/data/catalog.py`)

| Status | Meaning |
|---|---|
| Disponible | The catalog probe found the file/folder (a folder needs at least one data file). |
| Parcial | The folder exists but holds no usable data (shown as its own amber chip, counts as not available in `n/total`). |
| No Disponible | No compatible file/folder, or no probe result. An unknown status is never shown as healthy. |

Resumen General is the exception: its rows are techniques, and a technique is "Disponible" only if
at least one unit has a real reading for it (`fleet_overview.technique_availability`), so the
popover can never say "Disponible" while every unit cell reads "Sin Datos".

**Última actualización** (`src/data/source_freshness.py`, `config/service_data_sources.py::SOURCE_DATE_FIELDS`)

- It is the **date inside the data**, never the file's modified time: the newest value of the
  source's configured date column that is not in the future, in America/Santiago, as `Hoy` /
  `Hace 1 día` / `Hace N días`.
- It is informational and never changes the availability status.
- A source with no configured date column, or an unreadable one, shows `—`.
- Partitioned predictive tables (`<table>/year=YYYY/week=WW/*.parquet`) take the date from the
  newest partition only (`Fecha`).

## 2. Resumen > General

Page: `/overview/general` (`tab_overview_general.py`, `overview_general_callbacks.py`,
`components/fleet_overview.py`). Also covers the Unit Detail drill-down `/overview/unit/<unit>`
(`unit_summary_content.py`), which reads the same sources.

**Displayed in the old strip (5 technique rows):** Alertas, Telemetría, Aceite, Predictivo, Mantención.

| Row | Underlying origin | Read by | UI sections | Availability | Last update (date column) |
|---|---|---|---|---|---|
| Alertas | `data/alerts/golden/<client>/consolidated_alerts.csv` | `load_alerts_data` → `_alerts_status_map`, `_alerts_window_counts` | Alertas column, alert counts tooltip, band/ranking | ≥1 unit with a non-"Sin Datos" Alertas cell | newest `Timestamp` |
| Telemetría | `data/telemetry/golden/<client>/unit_health/` (partitions) + `data/auxiliar/<client>/Data_Date_Last_Update.csv` (row `Telemetria`) | `load_telemetry_unit_health` → `_telemetry_status_map`; `load_data_freshness` → `_telemetry_tribologia_freshness_map` | Telemetría column | same rule | newest `evaluation_timestamp` of `unit_health` |
| Aceite | `data/oil/golden/<client>/machine_status.parquet` + `Data_Date_Last_Update.csv` (row `Tribologia`) | `load_machine_status_for_client` → `_oil_status_map`; `_telemetry_tribologia_freshness_map` | Aceite column | same rule | newest `sampleDate` of `oil/.../classified.parquet` |
| Predictivo | `data/predictive/golden/<client>/<component>/unit_status_summary/` for each enabled component (motor, transmision) | `predictive_v2.load_unit_status_summary` → `_predictive_status_map`; `get_model_run_date` | Predictivo column | same rule | **oldest** model run date (`Fecha` of the latest `unit_status_summary` partition) across enabled components |
| Mantención | `data/mantentions/golden/<client>/Maintance_Labeler_Views/query_10_equipment_status.parquet` | `load_maintenance_equipment_status` → `_maintenance_status_map` | no column; feeds the maintenance signal only | same rule | newest `reference_date` |

**Actually used:** the same five, plus `Data_Date_Last_Update.csv` as a supporting input to the
Telemetría and Aceite freshness labels (it is folded into those two rows, not a separate row).
The Unit Detail drill-down additionally reads `telemetry/.../system_health` and the predictive
status frame, both already represented by the Telemetría and Predictivo rows.

**Differences (old strip vs. real):**
- **D1** Predictivo's "Hace N días" came from the legacy `predictive/golden/<client>/<component>.csv`,
  which no Predictivo page reads. The page's own freshness (the cell label) and the "Fecha Ejecución
  Modelo" come from `unit_status_summary`. Corrected in code (section 7).
- **D2** (informational, not changed) Telemetría and Aceite rows take their "Hace N días" from the
  data file of their own status source or, for Aceite, from `classified.parquet`, while the
  per-unit cells use `Data_Date_Last_Update.csv`. These are different dates of the same technique.
  They are kept as is so the values shown before the change do not move.

## 3. Monitoreo > Alertas

Page: `/monitoring/alerts` (`tab_alerts.py`, `alerts_callbacks.py`, `tab_alerts_general.py`,
`tab_alerts_detail.py`).

**Displayed in the old strip:** Alertas Consolidadas, Detalle de Alertas (Telemetría), Clasificación de Aceite.

| Source | Origin | Read by | UI sections | Availability | Last update |
|---|---|---|---|---|---|
| Alertas Consolidadas | `alerts/golden/<client>/consolidated_alerts.csv` | `load_alerts_data` | Vista General (KPIs, charts, table, filters), Vista Detallada (case header, dropdowns) | file exists | newest `Timestamp` |
| Detalle de Alertas (Telemetría) | `telemetry/golden/<client>/alerts_detail_wide_with_gps.csv` | `load_telemetry_alert_detail_for_alert` | Vista Detallada › Evidencia de Telemetría | file exists | newest `Alert_TimeStart` |
| Clasificación de Aceite | `oil/golden/<client>/classified.parquet` | `load_oil_classified` (`create_oil_evidence_section`, `update_oil_tendencia_range`) | Vista Detallada › Evidencia de Aceite (report + trend) | file exists | newest `sampleDate` |
| Límites de Aceite | `oil/golden/<client>/stewart_limits_four.parquet` | `load_stewart_limits_four` (same functions) | Vista Detallada › Evidencia de Aceite (limits, trend bands); the section shows "Límites Stewart no disponibles" without it | file exists | newest `calculation_date` |
| Mantenciones Semanales | `mantentions/golden/<client>/<WW-YYYY>.csv` (weekly snapshots) | `load_maintenance_week`, `load_emin_maintenance_evidence` | Vista Detallada › Evidencia de Mantención (EMIN reads the four weeks before the alert) | folder holds ≥1 weekly file | none (the weekly files carry no single date column) → `—` |

Not a source of record: `oil/essays_elements.xlsx` (essay name mapping) is a static reference file
read alongside Clasificación de Aceite; it is not shown.

**Differences:**
- **D3** Missing from the strip, used by Vista Detallada: **Límites de Aceite**.
- **D4** Missing from the strip, used by Vista Detallada: **Mantenciones Semanales**.

**Popover list:** Alertas Consolidadas, Detalle de Alertas (Telemetría), Clasificación de Aceite,
Límites de Aceite, Mantenciones Semanales (5).

## 4. Monitoreo > Telemetría

Page: `/monitoring/telemetry` (`tab_telemetry.py`, `telemetry_callbacks.py`,
`tab_telemetry_fleet.py`, `tab_telemetry_unit_detail.py`, `components/telemetry_report.py`).
Sub-tabs: Vista de Flota, Detalle de Unidad.

**Displayed in the old strip:** Salud de Unidad, Salud de Sistema, Manifiesto de Telemetría.

| Source | Origin (`data/telemetry/...`) | Read by | UI sections | Availability | Last update |
|---|---|---|---|---|---|
| Salud de Unidad | `golden/<client>/unit_health/` | `load_telemetry_unit_health` | Vista de Flota matrix and priority rows; Detalle de Unidad header | folder with data files | newest `evaluation_timestamp` |
| Salud de Sistema | `golden/<client>/system_health/` | `load_telemetry_system_health` | Vista de Flota system rows; Detalle de Unidad systems | same | newest `evaluation_timestamp` |
| Manifiesto de Telemetría | `golden/<client>/latest.json` | `load_telemetry_manifest` | "Evaluación" header (week/year/execution) and snapshot cache key | file exists | `execution_timestamp` |
| Comentarios de IA (Telemetría) | `golden/<client>/ai_unit_comments/`, `ai_system_comments/`, `ai_signal_comments/` (legacy `ai_comments/`) | `load_telemetry_ai_comments` | AI comment on unit, system and signal rows | at least one of the folders holds data | none → `—` |
| Desviación de Señales | `golden/<client>/deviation_summary/` (or `technique_results/deviation/`) | `load_telemetry_deviation_results` | Detalle de Unidad › signal table, system rows | folder with data | none → `—` |
| Tendencias de Señales | `golden/<client>/trend_results/` (or `technique_results/trend/`) | `load_telemetry_trends` | Detalle de Unidad › signal chart trend | folder with data | none → `—` |
| Eventos de Señales | `golden/<client>/event_results/` (or `technique_results/events/`) | `load_telemetry_events` (lazy, per chart) | Detalle de Unidad › signal chart event bands | folder with data | none → `—` |
| Límites de Telemetría | `silver/<client>/limits/limits_*.parquet` (fallback `silver/<client>/baselines/baseline_*.parquet`) | `load_telemetry_limits` | Detalle de Unidad › signal chart limits | folder with data | none → `—` |
| Telemetría Semanal | `silver/<client>/Telemetry_Wide_With_States/Week<WW>Year<YYYY>.parquet` | `load_silver_telemetry_week` | Detalle de Unidad › raw signal time series | folder with data | none (one large file per week, not scanned) → `—` |

Configuration files read next to these (`telemetry/config/<client>/signal_registry.yaml`,
`equipment_registry.yaml`, `telemetry/features_mapping_name.json`) are static references, not shown.

**Differences:**
- **D5** Missing from the strip, used by Vista de Flota / Detalle de Unidad: Comentarios de IA,
  Desviación, Tendencias, Eventos, Límites, Telemetría Semanal (six entries).
- Not a discrepancy: `alerts_detail_wide_with_gps.csv` is *not* used by this page (only by Alertas).

**Popover list:** the three existing plus the six above (9).

## 5. Monitoreo > Aceite

Page: `/monitoring/oil` (`tab_oil.py`, `machines_callbacks.py`, `reports_callbacks.py`,
`lab_compliance_callbacks.py`, `components/oil_machine_detail.py`). Sub-tabs: Visión de Flota,
Detalle de Reporte, Cumplimiento de Laboratorio. (Horómetro de Componentes is commented out of the
tab bar; `component_hours_callbacks.py` stays registered but is unreachable.)

**Displayed in the old strip:** Clasificación de Aceite, Estado de Máquina (Aceite), Límites de Aceite.

| Source | Origin (`data/oil/golden/<client>/`) | Read by | UI sections | Availability | Last update |
|---|---|---|---|---|---|
| Clasificación de Aceite | `classified.parquet` | `load_oil_classified` | all three sub-tabs (fleet KPIs/charts, report detail, lab compliance KPIs) | file exists | newest `sampleDate` |
| Estado de Máquina (Aceite) | `machine_status.parquet` | `load_machine_status_for_client` | Visión de Flota (status, priority), machine detail card | file exists | newest `latest_sample_date` |
| Límites de Aceite | `stewart_limits_four.parquet` | `load_stewart_limits_four` | Detalle de Reporte (essay limits, radar/series bands) | file exists | newest `calculation_date` |
| Horas de Componente (Aceite) | `cleaned_component_hours.parquet` | `get_latest_component_hours` | Visión de Flota › machine detail table, column "Horas Componente" (only for CDA, ENEX, CAPSTONE: `component_hours_allowed_clients`) | file exists | newest `sampleDate` |

Static reference: `oil/essays_elements.xlsx` (essay mapping), not shown.

**Differences:**
- **D6** Missing from the strip, used by the machine detail: **Horas de Componente (Aceite)**, for
  the clients allowed to see it. It is not listed for other clients, where the page never reads it.

**Popover list:** the three existing plus Horas de Componente (Aceite) for CDA/ENEX/CAPSTONE (3 or 4).

## 6. Monitoreo > Informe de Confiabilidad

Page: `/monitoring/mantenciones` (`tab_mantenciones_general.py`,
`mantenciones_general_callbacks.py`, `src/data/maintenance_repository.py`). No strip (pending
confirmation).

Origin: `data/mantentions/golden/<client>/Maintance_Labeler_Views/query_1…query_10_*.parquet`
(component maintenance, unit records, actions, business KPIs, reliability monthly, component failure
ranking, intervention hours daily/monthly, fleet intervention daily, equipment status), the weekly
snapshots `mantentions/golden/<client>/<WW-YYYY>.csv`, and `oil/golden/<client>/classified.parquet`.
Read by `get_repository(mode="parquet")` (dummy mode generates in-memory data and reads nothing).
Availability per query is tracked internally by the repository (`source_status`: ok / partial /
missing / error) and surfaced in-page as notices.

## 7. Predictivo > Motor / Transmisión

Pages: `/predictive/motor`, `/predictive/transmision` (`tab_predictive_component.py`,
`tab_predictive_overview.py`, `tab_predictive_evidence.py`, `predictive_callbacks.py`,
`predictive_pages_callbacks.py`, `src/data/predictive_v2.py`). Sub-tabs: **Resumen**
(Vista Corta / Vista Larga) and **Evidencia**. The page reads exclusively the Predictive Data
Contract v2.0 long-format partitions
(`data/predictive/golden/<client>/<component>/<table>/year=YYYY/week=WW/*.parquet`).

**Displayed in the old strip:** Componentes Predictivos, IA Predictiva.

**Neither of them is read by the page.**
- *Componentes Predictivos* = `predictive/golden/<client>/*.csv` (legacy `motor.csv`,
  `transmision.csv`). No Predictivo page opens them any more (only Campbell AI, section 8).
- *IA Predictiva* = `predictive/golden/<client>/analisis_inteligente.parquet` (legacy flat file). The
  Análisis Inteligente panel reads `unit_failure_analisis` since fa61520.

| Source | Origin (per component) | Read by | UI sections | Availability | Last update |
|---|---|---|---|---|---|
| Puntaje de Riesgo | `predictive/golden/<client>/<component>/risk_scores/` (last 13 weeks) | `load_risk_scores` | Resumen: KPI "Ranking Flota", failure-mode table, Vista Corta scatter. Evidencia: KPIs, mode status calendar, comparative bars, risk by mode | folder has `year=*/week=*` partitions (required: the component is not listed without it) | newest `Fecha` of the latest partition |
| Estado de Unidades | `.../<component>/unit_status_summary/` (latest partition) | `load_unit_status_summary`, `get_model_run_date` | Resumen: KPI counts, "Fecha Ejecución Modelo", `Estado`; fleet scatter colors; Evidencia banner | partitions exist | newest `Fecha` = model run date |
| Curva de Riesgo Acumulado | `.../<component>/cumulative_risk_curve/` (latest partition) | `load_active_cycle_curve`, `active_cycle_estado`, `active_cycle_component_hours` | Resumen › Vista Larga; general state ("worse of short and long"); Component Hour column; Evidencia banner hours. Not published for every client/component (e.g. CDA Transmisión) | partitions exist | newest `Fecha` of the latest partition |
| Análisis Inteligente | `.../<component>/unit_failure_analisis/` (partition of the same run as `risk_scores`) | `load_unit_failure_analisis(run=…)` | Evidencia › Análisis Inteligente panel (diagnóstico, causa probable, acciones) | partitions exist | newest `Fecha` |
| Estado de Señales de Telemetría | `telemetry/golden/<client>/<component>/signal_daily_status/` (last 13 weeks) | `load_signal_daily_status` | Evidencia › telemetry signal charts (falls back to risk-score columns when absent) | partitions exist | newest `Fecha` |
| Clasificación de Aceite | `oil/golden/<client>/classified.parquet` | `load_real_oil_samples` | Evidencia › oil variables table and series | file exists | newest `sampleDate` |
| Límites de Aceite | `oil/golden/<client>/stewart_limits_four.parquet` | `load_predictive_oil_limits_four` | Evidencia › oil limits in table and series | file exists | newest `calculation_date` |
| Historial de Desgaste Acumulado | `oil/golden/<client>/<component>/oil_meter_history/` | `load_latest_cycle_oil_meter_history` | Evidencia › "Desgaste Acumulado" mode (only components that publish it: Capstone Motor today) | partitions exist | newest `Fecha` |

Present on disk but **not read** by the page: `mode_failure_analisis/`, `failure_mode_diagnosis/`.

**Why "Componentes Predictivos" said "Hace 59 días" while the model run is 06 Nov 2026**
(reproduced with the local Capstone data, today = 2026-11-10):

| | Value | Where it comes from |
|---|---|---|
| Strip "Componentes Predictivos · Disponible · Hace 59 días" | max `Fecha` = **2026-09-12** | legacy `predictive/golden/capstone/motor.csv` (a stale flat file, last written in September) |
| Page "Fecha Ejecución Modelo" | **2026-11-06** | `unit_status_summary` latest partition, `Fecha` max (`get_model_run_date`) |
| Strip "IA Predictiva · No Disponible" | file missing | legacy `analisis_inteligente.parquet` does not exist for Capstone, although `unit_failure_analisis` (the real source of the panel) is published and dated 2026-11-06 |

They are **different dates from different files**: the strip measured a legacy CSV that the page no
longer reads, so it was both stale and not representative. (Locally, CDA shows the opposite
symptom: the legacy files are 115–116 days old while the v2 run date is 2026-07-18.) The corrected
popover reads the v2 tables, so its "Estado de Unidades" row reports the same date as the KPI.

**Differences:**
- **D7** Both displayed entries (Componentes Predictivos, IA Predictiva) are not used by the page → removed.
- **D8** Missing: Puntaje de Riesgo, Estado de Unidades, Curva de Riesgo Acumulado, Análisis
  Inteligente, Estado de Señales de Telemetría, Clasificación de Aceite, Límites de Aceite,
  Historial de Desgaste Acumulado (where published) → added.
- **D9** The popover is built per component: sources that the component does not publish are
  listed as "No Disponible" only when the page would read them (`risk_scores`, `unit_status_summary`,
  `cumulative_risk_curve`, `unit_failure_analisis`, `signal_daily_status`); `oil_meter_history` is
  listed only for components that publish it.

**Popover list:** Puntaje de Riesgo, Estado de Unidades, Curva de Riesgo Acumulado, Análisis
Inteligente, Estado de Señales de Telemetría, Clasificación de Aceite, Límites de Aceite
(+ Historial de Desgaste Acumulado where published) (7 or 8).

## 8. Agentes

**Campbell AI** (`/agents/campbell-ai`, `dashboard/campbell_ai/`, `src/campbell_ai/data.py`). No strip.
The agent reads through a declared dataset registry (`DATASETS`) under `data/`:
`alerts/.../consolidated_alerts.csv`, `oil/.../classified.parquet`, `machine_status.parquet`,
`stewart_limits.parquet`, `stewart_limits_four.parquet`, `telemetry/.../machine_status.parquet`,
`classified.parquet`, `alerts_detail_wide_with_gps.csv`, `mantentions/.../query_3_actions_all_equipment.parquet`,
`Resumen_Semanal_Completo.csv`, `predictive/.../motor.csv`, `transmision.csv`; plus
`auxiliar/manifest.json` (data manifest status) and an external LLM API.
- **D10** Campbell AI still reads the **legacy** predictive CSVs (`predictive_motor`,
  `predictive_transmission`) that the Predictivo pages have replaced with the v2 tables. Not changed
  here (out of scope; Campbell AI has no indicator); flagged for the team.

**Troubleshooting** (`/agents/troubleshooting`). A static card with a link to an external agent
(`?client=`); it reads no data source.

## 9. Reportes y Conexión ERP

| Page | Origin | Read by | Notes |
|---|---|---|---|
| Reportabilidad `/reporting` | S3 report store `{REPORTS_S3_ROOT}/<client>/reports/<date>/<file>` (bucket `BUCKET_NAME`) | `ReportStore.list_reports` / `open_report` | The state chips read `predictive_v2.load_unit_state_history` (`unit_failure_analisis` history) and `load_curve_state_history` (`cumulative_risk_curve`), plus the status scale. |
| Informe preliminar de falla `/reporting/informe-falla` | Predictivo v2 golden tables (`unit_status_summary`, `risk_scores`, `cumulative_risk_curve`, `unit_failure_analisis`) from the local copy or S3 (`INFORME_FALLA_ORIGEN`), `oil/.../classified.parquet`, maintenance `query_3` and `query_7`, an LLM API | `src/informe_falla/*` | The unit list comes from the Fleet Overview's ordered units. |
| Validación de Avisos `/integration/validacion-avisos` | `data/warnings/<client>/<state>.parquet`, states `pending`, `validated`, `rejected`, `sent`; per-client SAP config `config/clients/<client>.yaml` | `erp_warning_store.load_all_warnings` | Writes to the same store (state changes, SAP send). |
| Seguimiento de Avisos `/integration/seguimiento-avisos` | same store | `erp_warning_store` | Read-only follow-up. |

## 10. Administración

`/admin` is a placeholder; `/admin/registro-usuarios` reads authentication events
(`data/auxiliar/authentication_register.parquet`, rebuilt from S3 event files);
`/admin/mailing` is the mailing configuration. They are configuration/operations pages, not data
pipelines, and never get a sources indicator.

Pages without an indicator today (Informe de Confiabilidad, Campbell AI, Troubleshooting,
Reportabilidad, Informe preliminar de falla, Validación/Seguimiento de Avisos, Admin) stay
as they are: the requirement replaces the existing strip, it does not add one to new pages.
The tables above are the starting point if the team wants to adopt them (add the probes and one
line in `config/service_data_sources.py`).

## 11. Discrepancy list (old strip vs. audit)

| # | Page | Old strip | Finding | Resolution |
|---|---|---|---|---|
| D1 | Resumen General | Predictivo "Hace N días" from legacy CSV | Page uses `unit_status_summary` run date | Corrected: row date = oldest v2 run date |
| D2 | Resumen General | Telemetría/Aceite dates from their status files | Cells use `Data_Date_Last_Update.csv` | Documented, **not changed** (keeps pre-existing values) |
| D3 | Alertas | no Límites de Aceite | Used by Vista Detallada | Added |
| D4 | Alertas | no Mantenciones Semanales | Used by Vista Detallada | Added |
| D5 | Telemetría | 3 sources | 6 more are read (AI comments, deviation, trends, events, limits, weekly silver) | Added |
| D6 | Aceite | no component hours | Used by machine detail (CDA/ENEX/CAPSTONE) | Added for those clients |
| D7 | Predictivo | Componentes Predictivos, IA Predictiva | Neither is read by the page; "59 days" vs 06 Nov explained in section 7 | Removed |
| D8 | Predictivo | — | Eight v2 sources used and not listed | Added |
| D9 | Predictivo | same list for every component | Sources depend on the component's published tables | Built per component |
| D10 | Campbell AI | (no strip) | Still reads legacy predictive CSVs | Documented only |

Also noted: `data/predictive/golden/<client>/analisis_inteligente*.parquet`,
`unit_failure_analisis_<client>.parquet` and the legacy `<component>.csv` files are orphans for the
dashboard pages; the catalog probes `predictive_components` and `predictive_ai` are no longer used by
any page after this change.
