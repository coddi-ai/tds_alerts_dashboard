# Technical Requirement — Phase 2: Unit Summary Navigation Shell

> Depends on: Phase 1 (Fleet Overview) must be shipped, since this view is entered from its unit KPI cards. No dependency on unconfirmed Phase 0 business rules — this phase is purely navigational/UX.

## Goal Definition

Build the navigation shell for the per-unit drill-down view ("Unit Summary"): the ability to open it from a Fleet Overview card, move between units without returning to the fleet view, and return to the Fleet Overview with prior state preserved. Content (charts, records, components) is out of scope for this phase — see Phase 3.

---

## Business Problem Context

Today there is no consolidated per-unit view — understanding a single machine's full picture means navigating across separate sections. The requested redesign is explicitly a 2-step model: a fleet-level overview, and a per-unit drill-down. Before populating that drill-down with data, the navigation pattern between "all units" and "one unit" needs to be solid, since this is what the user will use constantly when triaging the units flagged as Anormal/Alerta in Phase 1.

---

## Feature Context

This is the UX shell wrapping the future Unit Summary content. It defines:
- How a user enters the Unit Summary from a Fleet Overview card.
- How a user moves laterally between units while inside the Unit Summary, without needing to return to the Fleet Overview each time.
- How a user returns to the Fleet Overview, and what state is preserved when they do.

---

## Required Changes

1. **Entry point.** Clicking any unit KPI card in the Fleet Overview opens the Unit Summary view for that specific unit.
2. **Persistent unit identification.** The Unit Summary view always displays which unit is currently being viewed (e.g. header or breadcrumb with the unit identifier and its current overall status).
3. **Return to Fleet Overview.** A clearly visible control returns the user to the Fleet Overview.
4. **Lateral navigation.** A control (e.g. prev/next, or a unit switcher/search) lets the user move to another unit's Unit Summary directly, without passing back through the Fleet Overview.
5. **State preservation.** Returning to the Fleet Overview restores the state the user left it in (expanded/collapsed bands, scroll position) rather than resetting to a default view.

---

## Functional Rules

- Switching between units inside the Unit Summary must not trigger a full reload of the Fleet Overview in the background.
- The "back to fleet" action must be available from anywhere within the Unit Summary view, not only from a specific sub-tab or scroll position.
- The currently viewed unit must remain visible/identifiable at all times while scrolling within the Unit Summary (e.g. sticky header).

---

## Acceptance Criteria

- [x] Clicking a unit card in the Fleet Overview opens that unit's Unit Summary.
- [x] The Unit Summary always shows which unit is currently displayed.
- [x] A visible, always-available control returns the user to the Fleet Overview.
- [x] Returning to the Fleet Overview preserves the previously expanded bands and scroll position.
- [x] The user can navigate to a different unit's Unit Summary without first returning to the Fleet Overview.
- [x] No full-page reload occurs when switching between units within the Unit Summary.
