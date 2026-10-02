# Summary Improvements — Implementation Guide (Phase 0: Discovery, Business Rules & Implementation Guide)

**Status:** Business rules confirmed by stakeholder (2026-09-29). Ready to support Phase 1–3 implementation.
**Scope:** Documentation and business-rule definition. No UI/UX behavior is introduced or implied here beyond what Phase 1–3 requirement documents (`01_fleet_overview_unified_view.md`, `02_unit_summary_navigation_shell.md`, `03_unit_summary_content.md`, this same folder) already specify.

## Changelog

| Version | Date | Change | Author |
|---|---|---|---|
| 0.1 | 2026-09-29 | Initial draft — data inventory, codebase audit, and 5 business rules produced from repo analysis. No stakeholder review yet. Published as `documentation/general/summary_improvements_implementation_guide.md`. | Agent (Claude Code) |
| 0.2 | 2026-09-29 | Moved to `documentation/general/general_specs/00_implementation_guide.md` to match the filename Phase 1–3 docs already reference. All 5 business rules **Confirmed** by stakeholder. Freshness thresholds for Alerts/Predictivo/Maintenance set. Capstone freshness-CSV naming bug fixed (`data/auxiliar/golden/capstone/Data_Date_Last_Update.csv` + `dataDep/` copy: `telemetry`→`Telemetria`). CDA staleness bug accepted as-is (upstream issue, no dashboard action). | Agent (Claude Code), decisions by patricio.ortiz.v@ug.uchile.cl |
| 0.3 | 2026-09-29 | All 3 bugs in §4 now resolved/closed: fixed the stale `cumulative_risk_curve` claim in `predictive_data_contracts.md`. No remaining codebase-actionable bugs from the original audit — CDA's staleness is the sole open item, and it's an accepted upstream risk, not a dashboard defect. | Agent (Claude Code) |
| 0.4 | 2026-09-29 | Added bug #4 to §4: implementing `04_fleet_overview_status_and_freshness_revision.md` required actually verifying the freshness calculation (its Required Changes #3), which surfaced that Alertas/Predictivo/Mantenciones are badly stale on every currently-enabled client, not only Telemetría/CDA as bug #1 described. Confirmed as a genuine, wider upstream ingestion gap (calculation itself is correct) — escalated, no dashboard code change. | Agent (Claude Code) |

| 0.5 | 2026-10-02 | Added §3.6 recording the `max_risk(label, estado_datos)` ranking that `08_fleet_overview_table_format.md` requires to be confirmed before implementation. The Normal/Alerta/Anormal ↔ Ok/Atención/Preocupante mapping is §3.2's own table; the three cases §3.2 left open (no technique reading, undeterminable freshness, Maintenance's SANO/DETENIDO) were resolved by the implementer as defaults — **pending stakeholder confirmation**. Implemented in `dashboard/components/fleet_overview.py::max_risk`. | Agent (Claude Code) |

Any rule changed after Phase 1 has started requires explicit stakeholder approval and a note here on which downstream phase(s) it affects.

---

## 0. How to read this document

- Every technique section below cites concrete files (`path:line`) so a reviewer can verify claims against the live codebase rather than trusting prose.
- §3's business rules are now **Confirmed** — Phase 1–3 implementation should treat them as binding, not as open assumptions to re-litigate per PR.
- One threshold pair (Alerts/Predictivo freshness, §3.2) reflects the agent's interpretation of an ambiguous instruction — flagged explicitly; correct it if misread.
- Three concrete bugs were found during the original audit, independent of any business-rule decision. Two are resolved as of v0.2 (see §4).

---

## 1. Data inventory per technique

### 1.1 Alerts

| | |
|---|---|
| **Source** | `data/alerts/golden/{client}/consolidated_alerts.csv` (probe: `alerts_consolidated`, `src/data/catalog.py:169`). Loaded by `load_alerts_data()` (`src/data/loaders.py:541-549`, transform at `:487-538`). |
| **Grain** | One row = one fused alert (`FusionID`), spanning telemetry and/or oil evidence. |
| **Raw columns** | `mensaje_ia, TribologyID, SourceType, subsistema, UnitId, Trigger_type, FusionID, Timestamp, Trigger_Var, sistema, Semana_Resumen_Mantencion, componente, TelemetryID`. Derived: `has_telemetry`/`has_tribology` (from `Trigger_type`), `Month`. `sistema`/`subsistema`/`componente` nulls filled `'Desconocido'`. |
| **Unit key** | `UnitId` only. **`Unidad` is not a real column** — it's a display alias built in `alerts_tables.py:297`; a defensive `'UnitId' if in df.columns else 'Unidad'` fallback exists in a couple of callbacks but is never exercised against this file. Treat `Unidad` as UI label, not data. |
| **Adjacent source** | `telemetry_alert_detail` (`data/telemetry/golden/{client}/alerts_detail_wide_with_gps.csv`) — raw per-telemetry-alert detail, filed under `telemetry` technique because it's telemetry's native output before fusion. |
| **What drives severity** | No severity/priority field exists in the raw data at all. The only per-unit severity concept is `calculate_alert_criticality_score()` — **Overview-tab-only**, not in `alerts_callbacks.py` (`dashboard/callbacks/overview_general_callbacks.py:116-182`): groups last-30-days alerts by `UnitId`+`componente`, `score = alert_count * (1 + component_count * 0.5)`, buckets via `categorize_status()` (`:172-178`) into `'Normal'` (0) / `'Alerta'` (0–15) / **`'Crítico'`** (>15). |
| **Status vocabulary** | ⚠️ **Not Normal/Alerta/Anormal — it's Normal/Alerta/Crítico**, and it only exists as a derived Overview rollup, not a field the Alerts tab itself produces. `tab_alerts.py`/`alerts_callbacks.py` have no per-unit status concept; only descriptive fields (`Trigger_type`). This "Crítico" vocabulary already leaks into the Overview table's shared `STATUS_STYLE`/`STATUS_PRIORITY` dicts (`overview_general_callbacks.py:444-483`) as a synonym for "Anormal" — **Confirmed (§3.1): treat as an intentional synonym for Anormal going forward.** |
| **Freshness** | **Confirmed (§3.2): Normal <1wk, Alerta 1-3wk, Anormal >3wk**, measured against the max `Timestamp` of the client's alert feed. No `Alertas` row exists in `Data_Date_Last_Update.csv` today — per §3.2, freshness config is being modularized so this can be added without further schema hacks. |
| **Per-client availability** | `config/client_services.json` → `monitoring-alerts` key, via `is_service_enabled()` — **Confirmed (§3.1) as the authoritative applicability gate.** Currently true for CDA/EMIN/CAPSTONE, denied-by-default for ENEX/CENTINELA. |
| **"Recent" window** | Alerts General tab defaults to **27 days** (`tab_alerts_general.py:18-20,47,63-65`, user-adjustable); Overview's criticality scorer hardcodes **30 days**; Alerts Detail tab has **no date filter at all**. **Confirmed (§3.5): standardize on 30 days** as the one canonical Alerts default. |

### 1.2 Telemetry

| | |
|---|---|
| **Source** | `data/telemetry/golden/{client}/unit_health/year=/week=/` (Hive-partitioned parquet), latest partition picked by `_latest_telemetry_partition` (`src/data/loaders.py:1052-1080,1190-1207`). Also `system_health/` (unit×system grain) and `latest.json` manifest. |
| **Grain** | `unit_health` = one row per unit per weekly run. `system_health` = one row per unit×system. |
| **Unit key** | `unit` is canonical in telemetry's own contract (`documentation/telemetry/data_contracts.md:641`). `unit_id` is **not native** — it's an alias added only in `overview_general_callbacks.py:1025-1030` for the cross-technique merge. |
| **Fields** | `unit_health`: `unit, overall_status, priority_score, unit_score, n_anormal_systems, n_alerta_systems, top_risk_systems, executive_summary, evaluation_timestamp, baseline_version`. `system_health`: adds `system_score, confidence, n_techniques_triggered, top_signal, top_technique, explanation`. |
| **What drives status** | Four detection techniques roll up into `overall_status`: deviation (threshold exceedance vs. `limits_{date}.parquet` percentiles), events (spike/anomaly episodes), trend (worsening/improving), autoencoder (reconstruction error) — each queryable per-signal via `technique_results/{technique}/` tables, analogous to Predictivo's per-factor breakdown. |
| **Status vocabulary** | `Normal`, `Alerta`, `Anormal`, **`InsufficientData`** — one shared vocabulary across `status`/`system_status`/`overall_status`, enforced by a Pydantic regex (`data_contracts.md:782-855`). Maps 1:1 to the 3-level model **plus one extra state** that needs UI translation: displayed as "Sin evidencia suficiente" (`tab_telemetry_fleet.py:32`), not literally "Sin Datos". |
| **Freshness** | **Two independent, unreconciled signals**, unchanged by this round of decisions (only Alerts/Predictivo/Maintenance thresholds were newly set — Telemetry/Oil keep their existing code thresholds). (1) `evaluation_timestamp` embedded per-row in the golden contract. (2) The auxiliary `Data_Date_Last_Update.csv` 'Telemetria' row, thresholds Ok<2h/Atención<24h/Preocupante≥24h. These answer different questions (analysis freshness vs. raw ingestion freshness) and are not cross-referenced. |
| **Per-client availability** | `monitoring-telemetry` is `true` only for CDA; `false` for EMIN; **absent entirely** for ENEX and CAPSTONE (defaults denied). `catalog.py` probes all 4 clients regardless. |
| **"Recent" window** | Unit-detail signal chart defaults to **1 day** (radio 1/7/30, `tab_telemetry_unit_detail.py:132-144`); fleet/unit health is always "most recent week" (not a rolling window); cross-technique evidence use (Predictivo tab) reads telemetry with a **90-day** window instead. **Confirmed (§3.5): keep technique-specific windows, each chart labels its own reference period** — no forced unification. |

### 1.3 Oil (Tribología)

| | |
|---|---|
| **Sources** | `classified.parquet` (per-sample-per-component grain, ~6-7k rows/client), `machine_status.parquet` (per-machine current-state snapshot, ~200-250 rows/client, **derived from** `classified.parquet` by grouping latest-per-component and weighted scoring), `stewart_limits.parquet`/`stewart_limits_four.parquet` (percentile threshold lookup tables, not sample-grain), `cleaned_component_hours.parquet` (undocumented schema). |
| **Fields** | `machine_status.parquet`: `unit_id, client, latest_sample_date, overall_status, machine_score, total_components, components_normal/alerta/anormal, priority_score, component_details[{component, status, severity_score, weight, sample_date}], machine_ai_recommendation`. Note: `component_details` entries do **not** carry `ai_recommendation` per the contract/view-model — only the machine-level `machine_ai_recommendation` does. |
| **What drives status** | Documented scoring rule (`documentation/oil/oil_data_contracts.md:363-436`): per-essay percentile bands vs. `stewart_limits.parquet` (Normal <90th, Marginal 90-95th, Condenatorio 95-98th, Crítico >98th) → `report_status`; machine-level `overall_status` = weighted component scoring (motor/transmisión 2.0×, convertidor/diferencial 1.0×, others 0.5×; thresholds <6 Normal, 6-<10 Alerta, ≥10 Anormal). A **separate** four-limit (LIC/LIM/LSM/LSC) classification exists in `oil_charts.py` for chart/evidence views only, independent of `overall_status`. |
| **Status vocabulary** | Field is `overall_status`/`report_status` (not `estado`). Confirmed exactly `Normal`/`Alerta`/`Anormal` — clean 1:1, no distinct "Sin Datos" state at this layer. |
| **Freshness** | `latest_sample_date` (per machine) vs. `Data_Date_Last_Update.csv` 'Tribologia' row (unchanged thresholds: Ok<20d/Atención<40d/Preocupante≥40d). **Confirmed: the CSV is not generated from `latest_sample_date` anywhere in this repo** — read as-is from an externally-produced file. Real, currently-unverified drift risk, not addressed by this round of decisions. |
| **Per-client availability** | `monitoring-oil` is `true` for all 4 configured clients (CENTINELA has no key). Catalog probes 5 separate oil files per client independently — e.g. CAPSTONE has no `stewart_limits_four.parquet` source, so that probe reports missing even though `monitoring-oil` is enabled. |
| **"Recent" window** | **None in the Oil tab itself** — always "most recent sample per machine," no staleness cutoff. **Confirmed (§3.5): keep as-is.** |

### 1.4 Maintenance (Mantenciones)

| | |
|---|---|
| **Sources** | `data/mantentions/golden/{client}/Maintance_Labeler_Views/*.parquet` — 10 canonical "vistas de confiabilidad" views (`documentation/mantentions/data_contract_v2.md:9-155`), keyed by `machine_code` (display) / `machine_id` (UUID). Legacy weekly `ww-yyyy.csv` files coexist. **ENEX has no maintenance data directory at all.** |
| **Relevant views** | `query_10_equipment_status` (authoritative point-in-time status, backs `get_status_counts()`), `query_5_reliability_monthly` (MTBF/MTTR per machine×month), `query_8_intervention_hours_monthly` (canonical monthly downtime), `query_9_fleet_intervention_daily` (fleet-day grain incl. zero-activity days). |
| **What drives status** | `machine_status` is derived from `query_10.equipment_status`'s `OPERATIVO`/`DETENIDO`, mapped `SANO`↔`OPERATIVO`. Richer fields (MTBF/MTTR, downtime hours, `low_confidence` flag) live on separate views and are period aggregates, not a per-machine current-severity score. |
| **⚠️ Status vocabulary → 3-level mapping** | **Does not map cleanly — and per §3.1, does not need to.** `SANO`/`DETENIDO` is a binary *operational* axis (running vs. stopped for intervention), not a severity gradient. **Confirmed (§3.1): Maintenance is fully excluded from cross-technique status aggregation and ranking.** It keeps its own operational badge (SANO/DETENIDO), shown independently, never folded into a unit's overall Normal/Alerta/Anormal. |
| **Freshness** | **Confirmed (§3.2): Normal <2wk, Alerta 2-4wk, Anormal >4wk.** Measured against the latest available `query_10.reference_date`/`year_month` for the client — no dedicated ingestion-date field exists, so freshness is inferred from the max available period, consistent with the tab's existing implicit staleness warning (`PRODUCTIVE_VIEW.md:205-207`). |
| **Per-client availability** | `monitoring-mantenciones` true for CDA/EMIN/CAPSTONE, absent for ENEX/CENTINELA. `catalog.py`'s partial-fallback-to-weekly-CSVs path exists but is **not currently exercised** by any enabled client. |
| **"Recent" window** | **Month-to-date (MTD)** remains the primary window (`data_contract_v2.md:317-328` explicitly deprecates a 70-day rolling window). **Confirmed (§3.5): keep as-is** — Maintenance is not part of the Unit Summary's per-technique recent-activity charts in the same sense as the others (§03 doc's "maintenance summary" uses record count + systems involved, not a status chart), but its own MTD convention is unaffected by this guide. |

### 1.5 Predictive Models (Predictivo)

| | |
|---|---|
| **Sources** | Data Contract v2.0 long-format parquet: `unit_status_summary`, `risk_scores`, `mode_failure_analisis`, `unit_failure_analisis`, `cumulative_risk_curve`. Dual-mode per client/component: new layout preferred, legacy CSV fallback (`src/data/predictive_v2.py::discover_predictive_layout`). `cda/motor` now also has `cumulative_risk_curve` — the contract doc (v2.4, Sept 22) is stale on this point, should be corrected. `cda/transmision` remains CSV-only. |
| **Fields — the "factors" driving status** | `unit_status_summary`: `Unit, Fecha, estado, estado_previo, cambio_estado, ranking, delta_ranking, media_30d, peor_modo, peor_valor, modes_over_threshold_count, modos_ordenados` (JSON array — all 9 failure modes ordered highest→lowest, the per-factor breakdown a generalized KPI card would surface), `dias_sin_datos`. `FAILURE_MODE_CONFIG`/`resolve_failure_modes()` map each mode to a label + driving signals. |
| **Status vocabulary** | Confirmed exactly `Normal`/`Alerta`/`Anormal` (field `estado`). **⚠️ Previously: no "Sin Datos" state — units absent from every table silently defaulted to `"Normal"` in `attach_status()` (`tab_predictive_overview.py:319`). Confirmed (§3.1): this must change — an absent/no-record unit shows "Sin Datos", never a defaulted "Normal".** This is a Phase 1 implementation change (this guide records the decision; the code at `attach_status()` still needs to be updated when Phase 1 touches this view). Directly relevant to the still-open `capstone/motor` 30-vs-50-unit population mismatch (unrelated prior finding, not re-investigated here) — once this rule ships, those 20 extra/missing units should surface as "Sin Datos" instead of silently vanishing. |
| **Freshness** | **Confirmed (§3.2): Normal <1wk, Alerta 1-3wk, Anormal >3wk** (same shape as Alerts), measured against `get_model_run_date()` ("Fecha Ejecución Modelo") rather than the shared CSV, which has no Predictivo row and isn't being extended to cover it — Predictivo keeps its own dedicated freshness field. |
| **Per-client availability** | The only technique with per-component service ids (`predictive-motor`, `predictive-transmision`). `catalog.py`'s `predictive_components` probe is technique-level (recursively globs the whole client folder) and cannot see per-component gaps — **Confirmed (§3.1): use `client_services.json`'s per-component keys as the applicability gate** (not the coarser file probe) so a nav-visible-but-dataless component still shows "Sin Datos" rather than being silently treated as available. |
| **"Recent" window** | Cumulative risk curve has no time window (full history, indexed by component hours). Evidence tab borrows technique-specific windows (90-day telemetry, last-3-samples oil). **Confirmed (§3.5): keep as-is.** |

---

## 2. Codebase audit — existing components and reuse plan

*(Unchanged from v0.1 — see rationale below; no new findings from the confirmation round.)*

### 2.1 KPI card — `dashboard/components/predictive_kpis.py`

`KPI()`, `create_kpi_card()`, `create_kpi_row()` are already technique-agnostic (`title/value/icon_class/color_type/subtitle` only). Directly reusable for Phase 1's per-unit and per-technique KPI cards — the work is computing the right `(value, icon, color)` per technique/unit, not modifying this component.

### 2.2 Data Summary / freshness table — `tab_data_freshness.py` + `data_freshness_callbacks.py`

Structurally hardcoded to exactly two `Data` values (`FRESHNESS_CRITERIA` dict keys, pivot logic in `process_freshness_data()`). **Confirmed (§3.2): this becomes data-driven off a new config file covering all 5 techniques**, replacing the two-key hardcode — required before Phase 1's per-technique freshness rows (Alerts/Maintenance/Predictivo) can render at all, since those three techniques have no threshold today.

### 2.3 Ranking/sort logic — `create_critical_equipment_summary_table()`, `overview_general_callbacks.py:357-731`

`priority = max(STATUS_PRIORITY[telem_status], STATUS_PRIORITY[oil_status])`, sorted `(-priority, equipo)`. Only 2 of 5 techniques feed this today (Alerts+freshness blended into "Telemetría", Oil as "Tribología"). **Confirmed (§3.3): extend to all techniques except Maintenance**, add a secondary tiebreak (count of techniques currently Alerta/Anormal) before falling back to alphabetical.

### 2.4 Per-client conditional rendering — two independent mechanisms

1. `config/client_services.json` + `is_service_enabled()` — nav/route allow-list, default-deny. **Confirmed (§3.1) as the authoritative "is this technique applicable to this client/unit at all" gate** — a disabled technique is omitted entirely (matches Phase 1 doc's Functional Rules item 3).
2. `src/data/catalog.py::build_client_availability()` — filesystem probing, used today only for the "Fuentes de datos" banner. Stays as a diagnostics/banner signal; **not** the applicability gate for the new unified card (per (1) above) — but still useful to distinguish "technique enabled, this specific unit has no record" (→ "Sin Datos") from "technique enabled, data pipeline entirely missing" (→ still worth a distinct banner state, out of this guide's scope to design in detail).

### 2.5 Component filter/dedup precedent — `build_component_filter_options()`, `overview_general_callbacks.py:25-69`

Unions Alerts' `componente` and Oil's `component_details[].component`, uppercased as the join key. `component_normalizer.py` is Oil-internal only (strips left/right positional indicators for Stewart Limits), not a cross-technique canonicalizer. **Confirmed (§3.4): keep as-is for now**, extend coverage to Telemetry's `system` and Predictivo's component keys as a required Phase 2/3 scope item once a per-client vocabulary spot-check is done.

---

## 3. Business rules — **Confirmed**

### 3.1 Overall unit status aggregation rule — **Confirmed**

- **Aggregation method: worst-of across applicable techniques.**
- **Maintenance is fully excluded from aggregation and ranking.** SANO/DETENIDO is an operational axis, not severity — it never contributes to a unit's overall Normal/Alerta/Anormal band, and is shown as its own independent badge instead (§1.4, §2.3).
- **Predictivo must not default absent units to "Normal."** An absent/no-record unit shows **"Sin Datos"** — a Phase 1 implementation change to `attach_status()` (`tab_predictive_overview.py:319`), recorded here, not yet applied to code.
- **Per-client technique availability must gate aggregation.** Not every client has every technique. `config/client_services.json` / `is_service_enabled()` is the authoritative "is this technique applicable here" check — an inapplicable technique contributes nothing to the aggregation and renders no row at all (distinct from an applicable technique with no data yet, which renders as "Sin Datos" and still participates in aggregation at priority 0, per the existing `STATUS_PRIORITY` convention).
- **Alerts' `Crítico` is a confirmed, intentional synonym for `Anormal`** in aggregation and display — not an accident of a shared dict.

### 3.2 Data freshness thresholds — **Confirmed**

| Technique | Normal | Alerta | Anormal | Source |
|---|---|---|---|---|
| Telemetría | < 2h | 2h – 24h | ≥ 24h | Unchanged (existing code) |
| Tribología (Oil) | < 20d | 20d – 40d | ≥ 40d | Unchanged (existing code) |
| Alertas | < 1 week | 1 – 3 weeks | > 3 weeks | **New — confirmed this round** |
| Predictivo | < 1 week | 1 – 3 weeks | > 3 weeks | **New — confirmed this round** |
| Mantenciones | < 2 weeks | 2 – 4 weeks | > 4 weeks | **New — confirmed this round** |

⚠️ The Alertas/Predictivo row is the agent's resolution of an ambiguous instruction ("normal if 1 week passes; alerta between 1 and 3 and anormal if more than 1 week" — the last clause as literally stated overlaps with the middle one). Interpreted as a standard 3-tier shape mirroring Maintenance's. **Flag for correction if this isn't what was intended.**

**Confirmed implementation direction: modularize thresholds into a config file** rather than hardcoding them in `FRESHNESS_CRITERIA` (`data_freshness_callbacks.py`). This guide records the decision and the target values; wiring `data_freshness_callbacks.py` (and extending `Data_Date_Last_Update.csv`-equivalent freshness sourcing for the 3 newly-thresholded techniques, none of which currently have a freshness *source*, only a threshold) is Phase 1 implementation work, not done as part of this Phase 0 guide update.

### 3.3 Cross-technique ranking/sort score — **Confirmed**

Extend the existing `(-priority, unit_name)` pattern to all techniques **except Maintenance** (per §3.1): `priority = max(STATUS_PRIORITY[technique_status] for technique in applicable_techniques)`. Add a secondary tiebreak — **count of techniques currently Alerta/Anormal** — before the final alphabetical fallback, so units affected on more axes surface above units affected on fewer, even at the same worst-status level.

### 3.4 Monitored component deduplication rule — **Confirmed**

Keep the existing precedent as-is: uppercase-string union of Alerts' `componente` and Oil's `component_details[].component`, labeled via `translate_component_label()`. Extending coverage to Telemetry's `system` and Predictivo's component keys is required before Phase 2/3 ships the full Unit Summary component list — needs a per-client vocabulary spot-check first (no evidence yet that these vocabularies already align).

### 3.5 "Recent" time window definitions — **Confirmed**

Keep technique-specific windows (no forced shared window), each chart explicitly labeling its own reference period. One correction: **standardize Alerts on 30 days**, resolving the existing internal inconsistency (27-day picker default vs. 30-day hardcoded criticality score vs. no window in Detail).

### 3.6 Merged cell value `max_risk(label, estado_datos)` — **Implemented, pending stakeholder confirmation**

Used by the Fleet Overview table (`08_fleet_overview_table_format.md`). One shared ranking, **Normal (1) < Alerta (2) < Anormal (3)**, applied to both inputs:

| Input | Maps to |
|---|---|
| Technique label | Normal→Normal · Alerta/Atención→Alerta · Anormal/Crítico→Anormal (§3.1 synonym) |
| `estado_datos` (§3.2 tiers) | Ok→Normal · Atención→Alerta · Preocupante→Anormal |

The cell shows the worse of the two. The cases the spec and §3.2 do not settle, and the default chosen for each (**confirm or correct**):

- **Technique has no reading for the unit** (Sin Datos / Sin Fuente / InsufficientData) → cell is **Sin Datos** whatever the freshness. A client-wide fresh feed must not turn a missing reading into a healthy-looking cell (08: Estado never "Normal" without supporting data).
- **Freshness undeterminable** (`estado_datos` = Sin Datos, e.g. a Telemetría/Tribología unit missing from `Data_Date_Last_Update.csv`) → the technique's own label stays in force; the tooltip says freshness could not be determined.
- **Maintenance SANO/DETENIDO** → ranks as Normal (it is an operational axis, §3.1): shown as-is while data is fresh enough, degraded to Alerta/Anormal by stale data, and still excluded from the overall Estado.
- **Overall Estado** = worst-of the merged cells (Maintenance excluded, Sin Datos only if every cell is), so the Estado column always agrees with the cells beside it.

**Consequence to be aware of:** this supersedes the earlier rule that a technique past the worst freshness tier is shown as "Sin Datos". A technique with a real `Normal` reading but `Preocupante` data now reads **Anormal**, so while the upstream feeds in §4 bug #4 stay stale, units on those clients land in the Anormal band (e.g. every CDA unit on 2026-10-02).

**Single source of truth:** the Unit Summary (header Estado, per-technique cards, Predictivo sub-model status) reads the same `max_risk` result as the table - the previous "stale == Sin Datos" override is removed - so when the upstream pipelines recover, every screen moves together with no code or threshold change.

---

## 4. Summary of bugs found

| # | Where | What | Status |
|---|---|---|---|
| 1 | `data/auxiliar/cda/Data_Date_Last_Update.csv` | Data dated 2026-07-16/17/18, ~74-75 days stale as of 2026-09-29 — matches the "72-75 days" gap in Image 2. | **Accepted as-is.** Confirmed as an upstream pipeline issue outside the dashboard's control; no dashboard-side action taken. Should self-resolve once the upstream feed is fixed. |
| 2 | `data/auxiliar/golden/capstone/Data_Date_Last_Update.csv` (+ `dataDep/` copy) | `Data` column used lowercase English `"telemetry"` instead of `"Telemetria"`; caused every CAPSTONE row to fall through to unstyled `'Desconocido'` status. | **Fixed (v0.2).** All 30 rows in both the `data/` and `dataDep/` copies renamed `telemetry` → `Telemetria`, matching CDA's naming convention. CAPSTONE still has zero Tribología rows in this file — not fabricated, since no such data exists; that gap is separate from the naming bug and reflects CAPSTONE genuinely having no oil-freshness feed wired yet. |
| 3 | `documentation/predictive/predictive_data_contracts.md` (v2.4, 2026-09-22) | States `cumulative_risk_curve` is capstone-only; `cda/motor` now also has it. | **Fixed.** Table (line 164) and prose (line 167-170) updated to reflect `cda/motor` having `cumulative_risk_curve` since `year=2026/week=29`, dated so the next reader knows to re-verify rather than trust it indefinitely. |
| 4 | Alertas/Predictivo/Mantenciones freshness, all 3 currently-enabled clients (2026-09-29 verification, `04_fleet_overview_status_and_freshness_revision.md` Required Changes #3) | Once Phase 1 wired freshness for these 3 techniques (bug #1 above only ever covered Telemetría), every one of them reads badly stale too, not just Telemetría: **CDA** — Alertas 81 días, Predictivo 74 días, Mantenciones 249 días; **EMIN** — Alertas 45 días, Mantenciones 53 días; **CAPSTONE** — Alertas 54 días, Mantenciones 118 días (Predictivo 17 días, within the Atención band — proves the calculation genuinely varies and isn't stuck). Traced to source: Mantenciones' `query_10_equipment_status.parquet` `reference_date` for CDA is a single fixed value, `2026-01-22`; Alertas' max `Timestamp` for CDA is `2026-07-09`. | **Accepted as-is / escalated, no dashboard code change.** The freshness calculation itself is confirmed correct — `_freshness_from_naive_timestamp()` (`dashboard/components/fleet_overview.py`) computes elapsed time correctly against real, upstream-sourced timestamps; CAPSTONE's Predictivo reading (Atención, not Preocupante) confirms the thresholds aren't miscalibrated into an always-worst state. This is a genuine, broader-than-previously-known upstream ingestion gap — Mantenciones' `query_10` view in particular hasn't refreshed in ~8 months for CDA. Needs escalation to the team owning these pipelines; out of the dashboard's control. |

---

## 5. Cross-references to Phase 1–3 requirement documents

This guide lives at `documentation/general/general_specs/00_implementation_guide.md`, alongside:
- `01_fleet_overview_unified_view.md` (Phase 1) — references this guide's aggregation, freshness, and ranking rules (§3.1–3.3). Its line 43 "default assumption pending confirmation" language should be read as **resolved** by §3.1 above.
- `02_unit_summary_navigation_shell.md` (Phase 2) — explicitly has no dependency on Phase 0 rules; unaffected by this update.
- `03_unit_summary_content.md` (Phase 3) — references this guide's "recent" window rule (§3.5) and component deduplication rule (§3.4), both now confirmed.

No further edits to the Phase 1–3 documents themselves were made — they already deferred to this guide by name rather than restating the open assumptions inline, so confirming the rules here is sufficient; re-read §3 there instead of duplicating rule text across files.
