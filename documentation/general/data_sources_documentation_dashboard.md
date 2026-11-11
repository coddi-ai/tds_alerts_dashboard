# Data Sources Documentation — Dashboard

Audit of the real data sources behind every page and tab of the dashboard, and the
reference the "Fuentes de Datos" popover is built from
(`documentation/general/general_specs_v2/technical_requirement_data_sources_popover.md`, step 6).

- **Audited:** 2026-11-10, branch `data-sources-popover` (from `origin/dev` 502e71e).
- **Method:** every page/tab was traced from its layout, through its callbacks, to the loader that
  reads the data and the file it opens. The predictive finding (section 7) was also reproduced
  with the local data mirror (`data/predictive/golden/capstone`, `.../cda`).
- **Amended 2026-11-10** (`technical_requirement_data_sources_popover_amendment.md`): the popover
  was first built for the five pages that had the strip (Resumen General, Alertas, Telemetría,
  Aceite, Predictivo Motor/Transmisión) and is now on **every page with data sources**: Informe de
  Confiabilidad, Campbell AI, Troubleshooting, Reportabilidad, Informe preliminar de falla,
  Validación y Seguimiento de Avisos and Administración (Registro de Usuarios, Mailing). The
  `/admin` landing page is a placeholder with no data, so it has none. The tables of sections 6, 8,
  9 and 10 are exactly the lists the popovers show.

## 1. How a source's status and "last update" are determined

These rules are shared by every popover and are unchanged by the redesign.

**Three-state status model** (`dashboard/components/source_status.py`, `src/data/catalog.py`)

| Status | Chip | Meaning |
|---|---|---|
| Disponible | green, check icon | The probe found the file/folder (a folder needs at least one data file), or the configured service answers. |
| Parcial | amber, warning-triangle icon | The source exists but is incomplete: a folder without data files, only some levels of the AI comments, or a source spread over several components of which only some publish it (Reportabilidad's history). |
| No Disponible | red, exclamation icon | No compatible file/folder, no configuration, or no probe result. An unknown status is never shown as healthy. |

The chip always shows its icon **and** its word; the optional note of a source (`reason`, `detail`)
goes to the hover text and never replaces the word.

**How `n/total` is counted**

- `total` is the number of sources the popover **lists for the current client and component**.
  A source that does not apply is neither listed nor counted. Examples: Aceite lists *Horas de
  Componente* only for CDA, ENEX and CAPSTONE (total 4, otherwise 3); Predictivo lists 8 sources for
  a component that publishes `oil_meter_history` (Capstone Motor) and 7 for one that does not
  (`total` therefore differs between Motor and Transmisión); Resumen General lists only the
  techniques the client has enabled.
- `n` counts **only "Disponible"** sources. "Parcial" and "No Disponible" are not counted.
- The badge is **green** when `n == total` and **amber** when any listed source is not
  "Disponible" (including "Parcial").

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

**Date rule of the Resumen General rows.** Each row's "Hace N días" is the newest date inside a
**data file of that technique**, measured the same way for every row:

| Row | File its date is read from | Same as before the change set? |
|---|---|---|
| Alertas | `consolidated_alerts.csv` (`Timestamp`) | yes |
| Telemetría | `telemetry/.../unit_health` (`evaluation_timestamp`) | yes (kept, not `Data_Date_Last_Update.csv`) |
| Aceite | `oil/.../classified.parquet` (`sampleDate`) | yes (kept) |
| Mantención | `query_10_equipment_status.parquet` (`reference_date`) | yes |
| Predictivo | `unit_status_summary` of each enabled component (`Fecha`), the **oldest** one | **No: documented exception, see below** |

**Explicit exception: Predictivo.** Before the change set the row took its date from the legacy
`predictive/golden/<client>/<component>.csv`. Engineering keeps the **oldest v2 model run date**
instead, for this reason: no Predictivo page, nor the Resumen cell itself, reads that CSV any more,
so its date describes a file the row's own status does not come from. That produced "Hace 59 días"
next to a model run of 06 Nov 2026 (section 7). Reading `unit_status_summary` follows the same
principle as the other rows (the date comes from the file the row's status reads) and is the same
date the cell's freshness label already uses. Reverting is one line: restore
`"predictive": "predictive_components"` in `TECHNIQUE_SOURCE` and delete the
`predictive_run_days` branch in `fleet_overview_data_sources`; the row would then show the legacy
file's age again.

**Differences (old strip vs. real):**
- **D1** Predictivo's "Hace N días" came from the legacy `predictive/golden/<client>/<component>.csv`,
  which no Predictivo page reads. The page's own freshness (the cell label) and the "Fecha Ejecución
  Modelo" come from `unit_status_summary`. Corrected in code; recorded above as the exception.
- **D2** (informational, **not changed**) Telemetría and Aceite rows take their "Hace N días" from
  the data file of their own status source or, for Aceite, from `classified.parquet`, while the
  per-unit cells use `Data_Date_Last_Update.csv`. These are different dates of the same technique.
  They are kept as they were so the values shown before the change do not move.

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
`mantenciones_general_callbacks.py`, `src/data/maintenance_repository.py`). The repository is
created with `get_repository(mode="parquet", client=…)` and reads the maintenance contract. Its
own `source_status` (ok / partial / missing / error per query) drives the in-page notices; the
popover only reports whether each file is there.

| Source | Origin (`data/mantentions/golden/<client>/…`) | Read by | UI sections | Last update |
|---|---|---|---|---|
| Mantención por Componente | `Maintance_Labeler_Views/query_1_component_maintenance.parquet` | `load_maintenance_component_maintenance` | component maintenance tables | — |
| Registros de Unidad y Acciones | `…/query_2_unit_records_actions.parquet` | `load_maintenance_unit_records_actions` | unit records / actions | — |
| Acciones de Mantención | `…/query_3_actions_all_equipment.parquet` | `load_maintenance_actions_all_equipment` | actions, Paretos, monthly counts | — |
| KPIs de Negocio | `…/query_4_business_kpis.parquet` | `load_business_kpis` | KPI cards (hours) | — |
| Confiabilidad Mensual | `…/query_5_reliability_monthly.parquet` | `load_maintenance_reliability_monthly` | MTBF / MTTR | — |
| Ranking de Fallas por Componente | `…/query_6_component_failure_ranking.parquet` | `load_maintenance_component_failure_ranking` | failure ranking | — |
| Horas de Intervención (Diarias) | `…/query_7_intervention_hours_daily.parquet` | `load_maintenance_intervention_hours_daily` | daily hours | — |
| Horas de Intervención (Mensuales) | `…/query_8_intervention_hours_monthly.parquet` | `load_maintenance_intervention_hours_monthly` | monthly hours | — |
| Intervención de Flota (Diaria) | `…/query_9_fleet_intervention_daily.parquet` | `load_maintenance_fleet_intervention_daily` | fleet daily view | — |
| Estado de Equipos | `…/query_10_equipment_status.parquet` | `load_maintenance_equipment_status` | equipment status | newest `reference_date` |
| Mantenciones Semanales | `<WW-YYYY>.csv` snapshots | `list_maintenance_weeks`, `load_maintenance_week` | weekly summary | — |
| Clasificación de Aceite | `oil/golden/<client>/classified.parquet` | `load_oil_classified` | oil cross-reference | newest `sampleDate` |

Availability: file exists (the weekly snapshots: at least one `WW-YYYY.csv`). The queries carry no
single date column the dashboard reads, so their "Última actualización" is `—`. **Popover list:**
the twelve above (total 12; fewer files on disk lower `n`, never `total`).

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

### Campbell AI

Page `/agents/campbell-ai` (`dashboard/campbell_ai/`, `src/campbell_ai/data.py`). The agent reads
through a declared dataset registry (`DATASETS`), so the popover lists exactly those datasets for
the current client, plus the data manifest (13 sources). An LLM API is also used; it is a service,
not a data source, and is not listed.

| Source | Origin (`data/…`) | `DATASETS` key |
|---|---|---|
| Alertas Consolidadas | `alerts/golden/<client>/consolidated_alerts.csv` | `alerts` |
| Detalle de Alertas (Telemetría) | `telemetry/golden/<client>/alerts_detail_wide_with_gps.csv` | `alerts_detail` |
| Clasificación de Aceite | `oil/golden/<client>/classified.parquet` | `oil_classified` |
| Estado de Máquina (Aceite) | `oil/golden/<client>/machine_status.parquet` | `oil_machine_status` |
| Límites de Aceite (Formato Legado) | `oil/golden/<client>/stewart_limits.parquet` | `oil_limits` |
| Límites de Aceite | `oil/golden/<client>/stewart_limits_four.parquet` | `oil_limits_four` |
| Estado de Equipos (Telemetría) | `telemetry/golden/<client>/machine_status.parquet` | `telemetry_machine_status` |
| Componentes Clasificados (Telemetría) | `telemetry/golden/<client>/classified.parquet` | `telemetry_classified` |
| Acciones de Mantención | `mantentions/golden/<client>/Maintance_Labeler_Views/query_3_actions_all_equipment.parquet` | `maintenance_actions` |
| Resumen Semanal de Mantención | `mantentions/golden/<client>/Resumen_Semanal_Completo.csv` | `maintenance_summary` |
| Modelo Predictivo de Motor (Legado) | `predictive/golden/<client>/motor.csv` | `predictive_motor` |
| Modelo Predictivo de Transmisión (Legado) | `predictive/golden/<client>/transmision.csv` | `predictive_transmission` |
| Manifiesto de Datos | `auxiliar/manifest.json` | (manifest status) |

Availability: file exists. Dates: only the files with a date column show one (alerts `Timestamp`,
alert detail `Alert_TimeStart`, oil `sampleDate`, machine status `latest_sample_date`, limits
`calculation_date`, the legacy predictive CSVs `Fecha`); the rest show `—`.

> **Technical debt (D10), no code change in this change set.** Campbell AI still reads the **legacy
> predictive CSVs**, `predictive/golden/<client>/motor.csv` and `predictive/golden/<client>/transmision.csv`
> (`DATASETS` keys `predictive_motor`, `predictive_transmission`; required columns `Unit`/`unitId`
> and `ranking`). Predictivo's pages stopped reading them when the Predictive Data Contract v2.0
> landed, so the agent can answer from a model state that is months older than the one on screen
> (its popover rows are dated "Hace N días" from the file's own `Fecha`, e.g. 59 days for Capstone).
> **Target source:** the v2 tables of `predictive/golden/<client>/<component>/`, read through
> `src/data/predictive_v2.py`: `unit_status_summary` (has `Unit`, `ranking`, `estado` per unit and
> the run date `Fecha`) for the current state, `risk_scores` for the per-mode history and
> `unit_failure_analisis` for the narrative. The exact column mapping for the agent's tools is not
> defined yet and needs the Campbell AI owner to confirm it.

### Troubleshooting

Page `/agents/troubleshooting`. A card with a link to an external agent (`?client=`); it reads no
data file. Its single source is the **agent itself**: *Agente de Troubleshooting* is "Disponible"
when the agent URL is configured (`config/troubleshooting_integration.json` or
`TROUBLESHOOTING_AGENT_URL`) and the service is enabled for the client (not dummy); otherwise "No
Disponible". No date (`—`). **Popover list:** 1 source (total 1).

## 9. Reportes y Conexión ERP

### Reportabilidad (`/reporting`)

| Source | Origin | Read by | Availability | Last update |
|---|---|---|---|---|
| Reportes en S3 | `{REPORTS_S3_ROOT}/<client>/reports/<date>/<file>` in bucket `BUCKET_NAME` | `ReportStore.list_reports` / `open_report` | the service is enabled for the client and a bucket is configured | — |
| Historial de Análisis Predictivo | `predictive/golden/<client>/<component>/unit_failure_analisis/` of every component of the predictive technique (motor, transmisión) | `predictive_v2.load_unit_state_history` (state chips, `report_health`) | all components publish it → Disponible; only some → **Parcial**; none → No Disponible | oldest newest `Fecha` across components |
| Historial de Curva de Riesgo Acumulado | `…/<component>/cumulative_risk_curve/` | `predictive_v2.load_curve_state_history` | same rule | same |

**Popover list:** the three above (total 3). The S3 listing itself is not probed on render (no
network on a header), so a bucket that is configured but unreachable still reads "Disponible"; the
page's own notice shows that failure.

### Informe preliminar de falla (`/reporting/informe-falla`)

Reads the Predictivo v2 tables of the **motor** component (`src/informe_falla/catalog.py::COMPONENTE`)
from the local copy, or from S3 when `INFORME_FALLA_ORIGEN=s3`; the oil samples and two maintenance
queries; and an LLM API (a service, not listed).

| Source | Origin | Read by |
|---|---|---|
| Estado de Unidades | `predictive/golden/<client>/motor/unit_status_summary/` | `load_unit_status_history` (`evidence.py`) |
| Puntaje de Riesgo | `…/motor/risk_scores/` | `load_risk_scores_history` |
| Curva de Riesgo Acumulado | `…/motor/cumulative_risk_curve/` | `curva.py` |
| Análisis Inteligente | `…/motor/unit_failure_analisis/` | `analisis_unidad.py` |
| Clasificación de Aceite | `oil/golden/<client>/classified.parquet` | `aceite.py` |
| Acciones de Mantención | `…/query_3_actions_all_equipment.parquet` | `mantenciones.py` |
| Horas de Intervención (Diarias) | `…/query_7_intervention_hours_daily.parquet` | `mantenciones.py` |

With the S3 origin the four predictive rows report only whether the bucket (`ERS_S3_BUCKET`) is
configured, without a date; the local-copy probes would be misleading there. **Popover list:** the
seven above (total 7).

### Validación de Avisos (`/integration/validacion-avisos`)

| Source | Origin | Read by |
|---|---|---|
| Avisos del ERP | `data/warnings/<client>/<state>.parquet`, states `pending`, `validated`, `rejected`, `sent` | `erp_warning_store.load_all_warnings`; the page also writes state changes |
| Configuración SAP del Cliente | `config/clients/<client>.yaml` | `erp_client_config.load_client_config` (approve and send) |

"Avisos del ERP" is Disponible when at least one state file exists. **Popover list:** 2 sources.

### Seguimiento de Avisos (`/integration/seguimiento-avisos`)

Read-only follow-up of the same store: *Avisos del ERP* only (total 1).

## 10. Administración

- **`/admin`** is a placeholder ("en construcción"): no data, **no popover**.
- **`/admin/registro-usuarios`** (Registro de Usuarios, overview view). Reads login events and the
  registry only through `src/auth_events/data_access.py` (`auth_events/raw|daily/`,
  `auth_registry/*.json` in S3 under `MultiTechnique Alerts/auxiliar/`, or `AUTH_EVENTS_LOCAL_DIR`).
  Source: *Eventos de Acceso*, Disponible when a backend is configured (`get_storage()` is not
  `None`); it does not depend on the client; no date. Total 1.
- **`/admin/mailing`** (Mailing). The summary e-mails are built from the same alert pipeline as the
  Alertas page (`src/mailing/alert_summary.py` → `load_alerts_data`), so the source is *Alertas
  Consolidadas* of the selected client (`consolidated_alerts.csv`, newest `Timestamp`). Total 1.
  Only the **header** of this page changed (an empty slot for the button); `src/mailing`, the
  mailing callbacks, `mailing.css` and `config.py` are untouched.

Pages without a popover: `/admin` only.

## 11. Discrepancy list (old strip vs. audit)

| # | Page | Old strip | Finding | Resolution |
|---|---|---|---|---|
| D1 | Resumen General | Predictivo "Hace N días" from legacy CSV | Page uses `unit_status_summary` run date | Corrected: row date = oldest v2 run date. **Documented exception** to the "keep previous values" rule (section 2) |
| D2 | Resumen General | Telemetría/Aceite dates from their status files | Cells use `Data_Date_Last_Update.csv` | Documented, **not changed** |
| D3 | Alertas | no Límites de Aceite | Used by Vista Detallada | Added |
| D4 | Alertas | no Mantenciones Semanales | Used by Vista Detallada | Added |
| D5 | Telemetría | 3 sources | 6 more are read (AI comments, deviation, trends, events, limits, weekly silver) | Added |
| D6 | Aceite | no component hours | Used by machine detail (CDA/ENEX/CAPSTONE) | Added for those clients |
| D7 | Predictivo | Componentes Predictivos, IA Predictiva | Neither is read by the page; "59 days" vs 06 Nov explained in section 7 | Removed |
| D8 | Predictivo | — | Eight v2 sources used and not listed | Added |
| D9 | Predictivo | same list for every component | Sources depend on the component's published tables | Built per component (7 or 8) |
| D10 | Campbell AI | (no strip) | Still reads legacy predictive CSVs | **Technical debt**, documented only (section 8) |
| D11 | Seven pages | (no strip) | Had documented sources but no indicator | Popover added (sections 6, 8, 9, 10) |
| D12 | Troubleshooting | (no strip) | Reads no data file | Single source: the configured agent |
| D13 | Reportabilidad | (no strip) | History from several components can be incomplete | "Parcial" state used for it |

Also noted: `data/predictive/golden/<client>/analisis_inteligente*.parquet`,
`unit_failure_analisis_<client>.parquet` and the legacy `<component>.csv` files are orphans for the
Predictivo pages; the catalog probes `predictive_components` and `predictive_ai` are no longer used
by any page after this change. The legacy CSVs are still read by Campbell AI (D10).

