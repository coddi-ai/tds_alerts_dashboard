# Technical Requirement — Unit Summary: Monitoreo 2x2 Grid & Oil Overview Replacement

> Assumption flagged for confirmation: "the Evidence tab" in this requirement is interpreted as the Unit Summary's **Monitoreo** section (Alertas, Telemetría, Tribología, Mantención/Pareto), established in `05_unit_summary_restructure_and_predictive_comparison.md` and `07_unit_summary_revision_2.md`, since the "4 monitoring techniques" described matches that set exactly. If a different screen was meant, this document needs to be redirected accordingly.
>
> Revises: the Monitoreo card layout from `05_...md` / `07_...md`.

## Goal Definition

Rearrange the Unit Summary's Monitoreo section into a 2x2 grid when all 4 monitoring techniques are available for a unit's client, with Telemetría and Alertas on the top row, and replace the current Tribología (Oil) chart with the general oil-analysis overview already implemented in Monitoring > Oil > General for that unit.

---

## Business Problem Context

After the prior revision removed the standalone Mantenciones summary card (`07_...md`), the Monitoreo section now holds 4 cards: Alertas, Telemetría, Tribología, and the Pareto chart (Mantención). Displayed in a single row, this is harder to scan than a 2x2 arrangement, and the two techniques users check most often — Telemetría and Alertas — aren't prioritized in position. Separately, the current Tribología (Oil) chart is a simplified severity-by-component bar chart that doesn't match the richer, general oil-analysis overview already built elsewhere in the product (Monitoring > Oil > General, available per unit) — maintaining two different oil visualizations is unnecessary and gives users an inconsistent experience depending on where they look.

---

## Feature Context

Applies to the Unit Summary's Monitoreo section: the grid arrangement of its cards, and specifically the content of the Tribología (Oil) card.

---

## Required Changes

1. **2x2 grid for 4 available techniques.** When all 4 monitoring techniques are available for a unit's client (Alertas, Telemetría, Tribología, Mantención/Pareto), arrange their cards in a 2-column, 2-row grid instead of a single row.
2. **Top-row priority.** Place Telemetría and Alertas in the top row, left to right, in that order. Place the remaining two cards (Tribología, Mantención/Pareto) in the bottom row.
3. **Replace the Oil chart.** Replace the current Tribología (Oil) bar chart entirely with the general oil-analysis overview already implemented in Monitoring > Oil > General for a selected unit, reusing that existing component/logic rather than the current visualization.

---

## Functional Rules

- The 2x2 layout as specified applies to the 4-technique case described above. The layout for clients with fewer available monitoring techniques (1–3) is not defined by this requirement; default recommendation is to fill available grid cells left-to-right, top-to-bottom, but this must be explicitly confirmed with the business before implementation rather than assumed.
- The replacement oil visualization must be the same component/logic used in Monitoring > Oil > General — not a reimplementation — so the two stay in sync going forward.
- This change replaces the Tribología chart; it does not add the new oil overview alongside the old one.

---

## Acceptance Criteria

- [ ] With 4 monitoring techniques available, the Monitoreo section renders as a 2-column, 2-row grid.
- [ ] Telemetría and Alertas occupy the top row, in that order.
- [ ] Tribología and Mantención/Pareto occupy the bottom row.
- [ ] The Tribología card shows the same general oil-analysis overview as Monitoring > Oil > General for the selected unit, with the previous bar chart fully removed.
- [ ] Layout behavior for fewer than 4 available techniques is explicitly confirmed and documented before implementation.
