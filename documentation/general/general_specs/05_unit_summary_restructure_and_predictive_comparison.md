# Technical Requirement — Unit Summary: Monitoreo/Predictivo Split & Predictive Fleet Comparison

> Revises/extends: Phase 3 (Unit Summary Content). Depends on: `implementation_guide.md` (Phase 0) for the no-data fallback rule and the "recent window" rule referenced below. Also depends on the status labels defined/fixed in the companion requirement `04_fleet_overview_status_and_freshness_revision.md`, since chart headers here must reuse that same status source.
>
> Scope note: this requirement is functional/content only. Visual layout issues already logged separately are out of scope here.

## Goal Definition

Reorganize the Unit Summary so the monitored components list is immediately visible, each chart card shows its own current status, monitoring-type data (Alerts, Telemetry, Oil, Maintenance) and predictive-model data are split into two dedicated tabs, and the predictive charts show fleet-relative context instead of raw, hard-to-interpret failure-mode scores.

---

## Business Problem Context

Reviewing the shipped Unit Summary (see current screenshot) surfaced several content gaps: the monitored components list — arguably the most foundational context for interpreting the rest of the page — sits at the bottom, below charts the user hasn't yet been oriented for. Each chart card shows data but not its own status, forcing the user to mentally cross-reference the Fleet Overview to know if what they're looking at is concerning. Monitoring data and predictive-model data serve different analytical purposes (observed current state vs. forward-looking model output) but are mixed into one flat scroll. And the predictive charts show raw failure-mode scores with no fleet context, so a user can't tell whether a given score is actually unusual for this unit relative to the rest of the fleet — context that already exists and is visualized elsewhere in the product (Predictivo > Evidence).

---

## Feature Context

Applies to the Unit Summary content layer (charts, maintenance summary, components list) delivered in Phase 3. This restructures and extends that content — it does not change the navigation shell built in Phase 2.

---

## Required Changes

1. **Reorder: Componentes Monitoreados to the top.** Move the monitored components list above the technique chart cards.
2. **Per-technique status label on each chart card.** Each chart card's header displays that technique's current status (Normal/Alerta/Anormal), sourced from the same status computation used on the Fleet Overview card for that unit/technique.
3. **Split into two tabs:**
   - **Monitoreo** — Alerts, Telemetry, Oil, Maintenance.
   - **Predictivo** — Predictive Models only.
4. **Monitoreo tab: add a Pareto chart of main systems with corrections**, reusing the existing chart and underlying logic already implemented in the Mantenciones tab (not a reimplementation).
5. **Predictivo tab, per predictive sub-model** (e.g. Motor, Transmisión):
   - Display the general ranking value and its label at the top of that sub-model's card.
   - Replace the raw failure-mode bar chart with the fleet-comparison visualizations already implemented in **Predictivo > Evidence**: (a) this unit's ranking vs. fleet, and (b) factor-level comparison vs. fleet.

---

## Functional Rules

- The Pareto chart and fleet-comparison visualizations must reuse the existing chart components/logic from Mantenciones and Predictivo > Evidence respectively, to guarantee consistency rather than introducing parallel, potentially diverging implementations.
- When a predictive sub-model has no data for the most recent run (e.g. current Predictivo · Transmisión for T_11), the view must apply the fallback/no-data rule confirmed in `implementation_guide.md` (either fall back to the last available run, or explicitly render a no-data state) — this must not be left as an undefined "no data" message without a documented rule behind it.
- The maintenance Pareto chart's time window and record scope (corrections only vs. all maintenance types) must follow the "recent window" rule confirmed in `implementation_guide.md`.
- Status labels added to chart headers must be read from the same status source used by the Fleet Overview — never recalculated independently — so the two views cannot disagree about a technique's status for the same unit.
- It must be explicitly decided and implemented whether the unit-level top status badge applies globally across both tabs, or whether Monitoreo and Predictivo each carry their own status badge, since they now represent functionally distinct domains.

---

## Acceptance Criteria

- [x] Componentes Monitoreados renders at the top of the Unit Summary, above the chart cards.
- [x] Every chart card displays a status label matching the Fleet Overview's status for that unit/technique.
- [x] The Unit Summary is split into Monitoreo and Predictivo tabs with the technique grouping specified above.
- [x] Monitoreo tab includes the maintenance Pareto chart, reusing the existing Mantenciones implementation.
- [x] Predictivo tab shows, per sub-model, the general ranking value/label plus both fleet-comparison visualizations, reusing the Predictivo > Evidence components.
- [x] A predictive sub-model with no data in the latest run follows the confirmed fallback/no-data rule (verified against at least one such case, e.g. T_11 · Transmisión).
- [x] The global-vs-per-tab status badge decision is implemented consistently and verified across multiple units.

**Implementation notes (2026-09-29):**
- Status source: `fleet_overview._compute_unit_entries()` now records each unit's per-technique effective status in `technique_status`, exposed via `get_ordered_units()`/`get_unit_snapshot()`. `unit_summary.py` passes it into `build_unit_summary_content()`, which is the only place chart-card and tab-header status badges are read from (`dashboard/components/fleet_overview.py`, `dashboard/components/unit_summary.py`, `dashboard/components/unit_summary_content.py`).
- Predictivo sub-model status: `fleet_overview.get_predictive_component_status(client, unit, component)` factors out the same per-component estado/ranking computation the Fleet Overview's merged Predictivo row uses (`_component_predictive_status_maps`), and applies the same freshness-untrusted override (`_effective_status`) so a sub-model card can never disagree with the Fleet Overview on the same unit/component. Verified live: CDA's Predictivo is currently stale fleet-wide (documented in `00_implementation_guide.md` bug #4), so both Motor and Transmisión correctly show "Sin Datos" for every CDA unit including T_11 - the explicit no-data/untrusted state the Functional Rules require, not a silently misleading reading.
- Maintenance Pareto: `unit_summary_content._maintenance_pareto_section()` reuses `maintenance_repository.get_repository().get_monthly_payload(equipment=[unit])`'s `equipment_system_mix` data and `tab_mantenciones_general.create_equipment_pareto_chart()` unmodified (dimension auto-detected as `system_name`), on the same month-to-date window as the Maintenance summary card.
- Predictivo fleet comparison: `unit_summary_content._predictive_sections()` reuses `tab_predictive_overview._discover_components`/`_load_component_data`/`attach_status` and `predictive_charts.create_fleet_scatter`/`create_comparative_bars` directly (same call shape as `tab_predictive_evidence.render_initial_content`).
- Global-vs-per-tab badge decision: kept the sticky header's existing unit-wide overall/Maintenance badges (global, unchanged - the "is this unit OK" signal for prev/next navigation) and added a worst-of status per tab header ("Monitoreo · X" / "Predictivo · Y"), both computed from the same `technique_status` source.
- Verified end-to-end in a live browser session (CDA/T_09, CAPSTONE/CA-80: Monitoreo tab with Alertas/Tribología/Mantenciones/Pareto, Predictivo tab with ranking + fleet scatter + comparative bars) with no server-side errors.

---

**Optional consideration (not mandatory scope):** extending per-component status coloring within the Componentes Monitoreados list (each component tagged by its own oil/alert severity) rather than a flat tag list. Flagged for future consideration, not included here.
