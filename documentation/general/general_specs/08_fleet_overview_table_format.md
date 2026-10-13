# Technical Requirement — Fleet Overview: Table Format (Replaces KPI Cards)

> Supersedes: the KPI-card-based layout from Phase 1 and the card-specific items in `04_fleet_overview_status_and_freshness_revision.md` and `06_fleet_overview_revision_2.md` (card grid, per-card text simplification). The data-correctness requirements from those two documents remain in force and must be satisfied within this new table design — see Functional Rules.
> Depends on: `implementation_guide.md` (Phase 0) for the severity ranking used by `max_risk`, and for the overall-Estado aggregation rule used to group/sort rows.

## Goal Definition

Replace the Fleet Overview's unit KPI cards with a single table — one row per unit, one column per technique — where each cell shows one merged value computed as `max_risk(label, estado_datos)`, with a hover tooltip revealing the underlying label, the data-freshness state, and a plain-language explanation of the rule applied. Cell coloring reuses the existing color scheme from Monitoring > Oil's table.

---

## Business Problem Context

The KPI-card layout, even after two rounds of revision, still struggles with scannability across many units and techniques, and left the rule for merging a technique's status with its data-freshness state only partially defined (flagged repeatedly as an open contradiction in `04` and `06`). The business has requested a table format instead, which both compresses the view into something scannable at a glance and — critically — requires formally defining, for the first time, a single rule for merging label and estado_datos into one displayed value per cell.

---

## Feature Context

Applies to the Fleet Overview page. Replaces the per-unit KPI card grid with a table. Preserves the existing status-band grouping and sorting from Phase 1, and the click-through navigation into Unit Summary from Phase 2 — only the per-unit visual representation changes, from card to table row.

---

## Required Changes

1. **Replace the KPI card grid with a table.** Rows = units. Columns = techniques applicable to the current client (Alertas, Telemetría, Tribología, Mantención, Predictivo — whichever subset applies). A technique not available to the client is omitted as a column entirely; technique availability is a client-level property, so a column is never hidden for some rows and shown for others.
2. **Add a leading "Unidad" column** (unit identifier) and an **"Estado" column** (overall status), the latter used to group rows into the existing Anormal / Alerta / Normal bands and sort within each band, per the aggregation rule already established in Phase 1.
3. **Merged cell value.** Each technique cell displays one value computed as `max_risk(label, estado_datos)` — the worse of the technique's own status label (Normal/Alerta/Anormal) and its data-freshness state (estado_datos), using a single shared severity ranking (see Functional Rules).
4. **Hover tooltip.** Hovering any technique cell displays: the technique's own label, its estado_datos value, and a short, plain-language sentence explaining which of the two inputs was worse and is therefore driving the displayed value.
5. **Color reuse.** All severity-based cell coloring must reuse the existing color scheme/style already implemented in the Monitoring > Oil table, rather than introducing a new palette.
6. **Row click-through preserved.** Clicking a unit's row (or its Unidad cell) opens that unit's Unit Summary, exactly as the card click did in the prior layout.

---

## Functional Rules

- `max_risk(label, estado_datos)` must use one shared severity ranking for both inputs (e.g. Normal < Alerta < Anormal, with estado_datos states — fresh / stale / sin datos — mapped onto that same scale). If this mapping isn't already defined, it must be confirmed and recorded in `implementation_guide.md` before implementation.
- The tooltip's explanation text must be generated from the same rule evaluation that produced the cell's value — never a separately authored or static string that could drift out of sync with the actual logic.
- Columns are determined purely by client-level technique availability; a unit with no data for an available technique still gets a cell (reflecting "Sin Datos" through the max_risk output), never a blank or omitted cell.
- All table headers, tooltip text, and any other labels on this page must be in Spanish, per the standing localization requirement from `06_...md`.
- The data-correctness rules carried over from `04_...md` / `06_...md` still apply in table form: the Estado column must never show "Normal" for a unit with no supporting data across its techniques, and any data-source availability indicator elsewhere on this page must not contradict what the table itself shows.

---

## Acceptance Criteria

- [ ] Fleet Overview renders as a table: Unidad + Estado columns, followed by one column per technique applicable to the client.
- [ ] Rows remain grouped into Anormal / Alerta / Normal bands and sorted within each band per the existing rule.
- [ ] Each technique cell's value equals `max_risk(label, estado_datos)`, verified against representative cases (technique Normal + stale data → cell reflects the worse state, and vice versa).
- [ ] Hovering a technique cell shows the label, the estado_datos value, and an explanation consistent with the rule actually applied.
- [ ] Cell coloring matches the Monitoring > Oil table's existing color scheme.
- [ ] Clicking a unit's row opens that unit's Unit Summary.
- [ ] No column is hidden per-row; every applicable technique has a column for every unit.
- [ ] All table text (headers, tooltips) is in Spanish.
