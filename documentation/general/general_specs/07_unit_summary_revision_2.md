# Technical Requirement — Unit Summary: Revision 2 (Localization, Single-Column Layout, Content Trim & Predictive Status Consistency)

> Revises: `05_unit_summary_restructure_and_predictive_comparison.md`. Depends on: `implementation_guide.md` (Phase 0) for the no-data/fallback rule referenced below.
>
> Scope note: exact spacing/sizing of stacked sections and cards is left to the later UI/UX pass. Everything here is functional/content scope.

## Goal Definition

Localize remaining text, replace the Monitoreo/Predictivo tab split with a single vertically stacked layout, remove the standalone maintenance-records card in favor of the Pareto chart alone, stack multiple predictive sub-model cards vertically instead of side by side, and resolve the contradiction between a predictive card's "Sin Datos" status and the populated fleet-comparison charts it still renders.

---

## Business Problem Context

The prior revision (`05_...md`) split the Unit Summary into Monitoreo and Predictivo tabs. After using the shipped result, the preference is now for both sections to sit one above the other on a single scroll, rather than behind tabs. Separately, the dedicated "Mantenciones" summary card (record count + systems-involved tags) is judged redundant next to the Pareto chart, which already conveys that information with more analytical value. When a unit has multiple predictive sub-models (e.g. Motor, Transmisión), showing them side by side makes them harder to read and compare than stacking them. Finally, reviewing the current Predictivo cards shows a status contradiction: the card header reads "Ranking general: — · Sin Datos," yet the fleet-position scatter chart and the failure-mode comparison bar chart directly below it render fully populated data for the unit and the fleet average — undermining trust in the status label itself.

---

## Feature Context

Applies to the Unit Summary page: the Monitoreo/Predictivo section structure, the Monitoreo cards (Alertas, Telemetría, Tribología, Mantenciones, Pareto), and the Predictivo cards (one per sub-model).

---

## Required Changes

1. **Localize remaining text to Spanish.** Confirm and fix any leftover English strings on this page (e.g. hardcoded labels pulled from other modules), consistent with the fleet-wide localization requirement.
2. **Replace tabs with stacked sections.** Remove the Monitoreo/Predictivo tab UI. Render Monitoreo section content followed by Predictivo section content on a single vertical scroll. Section headers remain as visual dividers, not clickable tabs.
3. **Remove the standalone Mantenciones summary card.** Drop the record-count + "Sistemas involucrados" card from the Monitoreo section. Keep only the "Pareto de Correcciones por Sistema" chart.
4. **Stack multiple predictive sub-model cards vertically.** When a unit has more than one predictive sub-model (e.g. Motor, Transmisión), render their cards one above the other instead of side by side.
5. **Fix the "Sin Datos" vs. rendered-chart contradiction on Predictivo cards.** A card cannot show "Sin Datos" in its header/ranking while its own scatter and comparison charts render real, populated values for the current unit. Either the status computation is wrong and must be corrected to reflect that data does exist, or — for genuinely data-less cases — the charts must not render at all.
6. **Decide on section-level status indicators.** Now that Monitoreo/Predictivo are stacked sections rather than tabs, decide and implement whether each section keeps an independent status indicator in its header (as the tab labels currently show) or whether this is dropped in favor of the per-card status labels already established.

---

## Functional Rules

- Removing the Mantenciones summary card removes it from this view only — the underlying record-count/systems-involved data must remain available in the Mantenciones module itself.
- A card's "Sin Datos" status must be computed from the same data that feeds its own charts; a card cannot claim no data while displaying populated charts for the current unit.
- Stacking predictive sub-model cards must preserve full legibility of each card's charts — content must not be compressed to the point of becoming unreadable (exact sizing left to the UI/UX pass).
- If section-level status indicators are kept (item 6), they must be sourced from the same status computation used elsewhere (Fleet Overview, individual chart cards) — never computed independently.

---

## Acceptance Criteria

- [ ] No English-language text remains on the Unit Summary page.
- [ ] Monitoreo and Predictivo render as stacked vertical sections on one page, with no tab navigation between them.
- [ ] The standalone Mantenciones summary card no longer appears in the Monitoreo section; the Pareto chart remains.
- [ ] A unit with multiple predictive sub-models renders their cards stacked vertically.
- [ ] No Predictivo card shows "Sin Datos" while its own charts render populated data for the current unit — verified against at least one previously affected case.
- [ ] The decision on section-level status indicators is implemented consistently across units.
