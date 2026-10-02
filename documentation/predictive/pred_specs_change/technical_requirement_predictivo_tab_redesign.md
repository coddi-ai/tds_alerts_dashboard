# Technical Requirement — Predictivo Tab Redesign (General + Evidence)

## Context

The backend data contract was migrated to v2.8:

- `cumulative_risk_curve` was removed from the golden layer (now client-side only, unused going forward).
- `unit_status_summary.estado` is now precomputed upstream from `ranking` vs `media_30d` (80th-percentile thresholds per client) — no client-side recomputation.
- A new scored failure mode, `accumulated_wear_risk`, was added to `risk_scores` for `capstone`/`motor` only.
- A new table, `oil_meter_history` (capstone/motor only), provides per-sample running totals of six wear metals per component life.

As a result, the "Riesgo Acumulado" (accumulated curve) view in General's second layer is no longer backed by a live data source and must be removed, along with "Prioridad Actual". The scatter chart previously in Evidence (ranking_today vs ranking_30d) moves to General. Evidence's fleet-comparison layer is restructured to add a new "calendar" visualization, and the failure-mode selector gains the new `accumulated_wear_risk` mode, whose evidence is built from `oil_meter_history` instead of standard signal evidence.

## Required Changes

### 1. General — Layer 2 (replace sub-tab structure)

- Remove the existing sub-tabs "Riesgo Acumulado" and "Prioridad Actual" and all associated UI (tab selector, accumulated-curve chart, per-unit KPI cards).
- Replace this layer with a single chart: the fleet-wide scatter plot of `ranking_today` vs `ranking_30d`, reusing the same chart/behavior currently implemented in Evidence's "Comparación Flota" (left chart) — same axes, same data source, same interactions (e.g. point selection/hover), with no sub-tab wrapper around it.

### 2. General — Layers 1 and 3

- No change. KPI cards (Layer 1) and "Riesgo por modo de falla" table (Layer 3) keep their current behavior, data source, and layout.

### 3. Evidence — Layer 4 (rename + restructure)

- Rename "Comparación Flota" to "Comparación Modo de Falla".
- Remove the scatter chart (`ranking_today` vs `ranking_30d`) from this layer — it now lives only in General.
- Keep the existing right-side chart (failure mode vs fleet mean per mode) unchanged, in the right position.
- Add a new chart in the left position: a "calendar" heatmap showing, for the currently selected unit, the daily status of every failure mode available for that unit over the last 90 days, matching the layout in the reference image (modes on Y axis, dates on X axis, dotted vertical line marking each Monday/week start, 4-color legend).

### 4. Evidence — Layer 5 (failure mode selector)

- Add `accumulated_wear_risk` as a new selectable entry in the failure mode list (display label: "Riesgo Acumulado" / cumulative risk), alongside existing modes.
- This mode must behave as a real scored failure mode: it appears in the mode selector, in `modos_ordenados`-derived rankings, and in General's "Riesgo por modo de falla" table, exactly like any other mode, with its score read from `risk_scores`.
- When selected, its evidence panel does **not** use the standard signal/oil evidence charts used by other modes. Instead, it displays the cumulative wear curve(s) built from `oil_meter_history` (`{Metal}_acum_total` columns, read per component life / `ciclo_motor`), plotted over time for the selected unit.

### 5. Evidence — Layers 1, 2, 3

- No change.

## Functional Rules

- `accumulated_wear_risk` and its `oil_meter_history`-backed evidence are only present where backend data exists (`capstone`/`motor`). No special-case fallback UI is required for other clients/components — since the mode has no row in their `risk_scores`/`modos_ordenados`, it must simply not appear for those units, consistent with how the mode list is already expected to be derived from the data available for the unit's client rather than hardcoded.
- The calendar chart's daily status per mode must use the same four-band classification already used for `criticidad` in `mode_failure_analisis` (uniform across clients): Saludable `<35`, Monitoreo `35–55`, Prioridad alta `55–75`, Crítico `≥75`, applied day-by-day to `risk_scores.risk_value`.
- The calendar must include every failure mode the selected unit has data for (mode set is per client/unit, not fixed-count) — a mode with no `risk_scores` row for a given day is rendered as "no data" rather than implicitly healthy.
- The General scatter chart must be fleet-wide (one point per unit), matching the data scope and fields (`ranking_today`, `ranking_30d`) of the chart it replaces in Evidence — no new filtering logic introduced.
- Removing "Prioridad Actual" must not break any other component that depended on it (e.g. navigation, deep links); if none exist, no further action is needed.
- Existing functionality outside the layers listed above must remain unchanged.

## Acceptance Criteria

- [ ] General no longer shows "Riesgo Acumulado" or "Prioridad Actual" anywhere.
- [ ] General Layer 2 shows the `ranking_today` vs `ranking_30d` scatter plot, fleet-wide, with no sub-tab wrapper.
- [ ] General Layers 1 and 3 are visually and functionally unchanged.
- [ ] Evidence Layer 4 is titled "Comparación Modo de Falla".
- [ ] Evidence Layer 4 left chart is the new 90-day calendar heatmap for the selected unit, covering all failure modes available for that unit, with the 4-color criticidad legend and week-start dotted lines.
- [ ] Evidence Layer 4 right chart (fleet-mean comparison) is unchanged.
- [ ] Evidence Layer 5 selector includes `accumulated_wear_risk` as a new option, only for units/clients where the mode has data.
- [ ] Selecting `accumulated_wear_risk` in Layer 5 displays the cumulative wear-metal chart sourced from `oil_meter_history`, not the standard signal evidence view.
- [ ] `accumulated_wear_risk` appears in General's "Riesgo por modo de falla" table and in any mode ranking derived from `modos_ordenados`, for applicable units.
- [ ] Evidence Layers 1–3 are unchanged.
