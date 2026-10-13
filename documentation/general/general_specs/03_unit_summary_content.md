# Technical Requirement — Phase 3: Unit Summary Content

> Depends on: Phase 2 (Unit Summary Navigation Shell) must be shipped. The "recent" time windows, and the component deduplication rule, use the Confirmed rules from `00_implementation_guide.md` §3.4–3.5 (Phase 0).

## Goal Definition

Populate the Unit Summary view (shell built in Phase 2) with the actual per-unit content: recent-activity charts per technique, a maintenance record summary, and a deduplicated list of monitored components — so a user can understand "what we can say about this unit with the most recent data" in one place.

---

## Business Problem Context

The Fleet Overview (Phase 1) tells a user *that* a unit is worrying and *which* techniques are driving that status, at a glance. It does not give the depth needed to actually investigate a unit. The requested drill-down view must consolidate everything currently scattered across the Alerts, Telemetry, Oil, Maintenance and Predictive Models sections into one recent-data summary per unit, plus the list of components being monitored on that unit.

---

## Feature Context

This is the content layer of the Unit Summary view opened via Phase 2's navigation shell. It covers:
- One chart per applicable technique, showing recent activity/results.
- A maintenance activity summary (record count + systems involved).
- A single, deduplicated list of monitored components for the unit.

---

## Required Changes

1. **Per-technique recent-activity charts**, rendered only for techniques applicable to the unit's client (same conditional-rendering rule as Phase 1):
   - **Alerts** — chart of alert history/severity over the recent period.
   - **Oil** — chart of recent oil analysis results/trend.
   - **Telemetry** — chart of recent telemetry trend/results.
   - **Predictive Models** — chart of recent model output/factor trend, consistent with the factors shown on the Phase 1 KPI card.
2. **Maintenance summary** — number of maintenance records in the recent period, and the list/breakdown of systems involved in those records.
3. **Monitored components list** — a single deduplicated list of components for the unit, built from the Oil and Alerts datasets per the deduplication rule confirmed in `00_implementation_guide.md` §3.4 (uppercase-string union, existing `build_component_filter_options()` precedent).
4. **Conditional rendering** — a technique unavailable for the unit's client is omitted from the Unit Summary entirely (no chart, no section).

---

## Functional Rules

- The "recent" period for each chart follows the technique-specific windows confirmed in `00_implementation_guide.md` §3.5 (no forced shared window — each technique keeps its existing default; Alerts standardizes on 30 days). Each chart must label its own reference period on screen.
- A technique that is **available** for the client but has **no data** in the recent window must render an explicit empty/no-data state — this is distinct from a technique being unavailable for the client (Phase 1 rule), which omits the section entirely.
- The monitored components list must include only components with data in the Oil and/or Alerts datasets for that specific unit, and must not list a component twice if it appears in both sources.
- Maintenance record counts and systems-involved lists must reflect the same recent-period window used elsewhere in the view, unless maintenance data uses its own defined window per the implementation guide.

---

## Acceptance Criteria

- [x] A chart renders for every technique (Alerts, Telemetry, Oil, Predictive Models) available to the unit's client.
- [x] Techniques unavailable to the client show no section; techniques available but without recent data show an explicit empty state.
- [x] Maintenance section correctly shows record count and involved systems for the applicable recent period.
- [x] Monitored components list is complete, deduplicated, and unit-specific.
- [x] Every chart/section visibly states its reference time period.
- [x] Manual verification against at least one unit per status band (Normal, Alerta, Anormal) and one unit with a partial technique set.
