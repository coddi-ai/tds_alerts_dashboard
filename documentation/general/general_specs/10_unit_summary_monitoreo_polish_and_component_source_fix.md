# Technical Requirement — Unit Summary: Monitoreo Grid Polish & Monitored Components Source Fix

> Revises: `09_unit_summary_monitoreo_grid_and_oil_overview.md` (visual/consistency fixes within the shipped 2x2 grid) and the monitored-components sourcing rule originally defined in `03_unit_summary_content.md` (Required Changes item 3 / Functional Rules) and referenced again in `05_...md`.
> Confirmed as intentional and out of scope for this requirement: the Pareto card has no status badge; the Alertas card is the only one showing a staleness/reference-date banner.

## Goal Definition

Fix a set of consistency and correctness issues found in the shipped Monitoreo 2x2 grid — badge/color mismatches, a self-contradicting data freshness message, table and chart rendering overflow — and correct the Componentes Monitoreados list to source only from the Oil dataset, no longer from Alerts.

---

## Business Problem Context

Reviewing the shipped Monitoreo grid surfaced several small but trust-eroding inconsistencies: a card's status badge disagrees with the color used in its own chart, the Alertas card states two things that read as contradictory in the same breath, and two visualizations (the Tribología table and the Pareto chart) overflow or render content outside their card boundaries as more data is added. Separately, the monitored components list currently pulls from both Oil and Alerts datasets, but the intended source is Oil only — the Alerts-derived entries need to be removed from this list.

---

## Feature Context

Applies to the Unit Summary's Monitoreo section: the Telemetría, Alertas, Tribología and Pareto cards (visual/content fixes), and the Componentes Monitoreados list (data-sourcing fix).

---

## Required Changes

1. **Fix badge/chart color mismatch on Telemetría.** The card's status badge and the severity color scale used in its bar chart must agree — if the badge reads "Anormal" because of a specific bar (e.g. Engine), that bar's color must reflect the same severity level the badge represents, using one shared color-to-severity mapping across the card.
2. **Verify the Monitoreo section's overall status aggregation.** Confirm that the section-level badge ("Monitoreo — Anormal") correctly accounts for sub-cards reporting "Sin Datos" (e.g. Alertas) and not only cards with a Normal/Alerta/Anormal label — fix the aggregation if "Sin Datos" states are not currently factored in per the rule defined in `implementation_guide.md`.
3. **Fix the Alertas card's self-contradicting message.** The stale-data banner ("Sin datos nuevos hace 4+ semanas — mostrando datos de referencia al [fecha]") and the summary line ("Sin alertas registradas en los últimos 30 días") must reference the same reference date, so the two statements read as one consistent fact rather than contradicting each other (e.g. "Sin alertas registradas en los últimos 30 días, con datos de referencia al [fecha]").
4. **Fix the Tribología table's overflow.** With 9+ monitored components, the table currently requires horizontal scrolling and wraps long column headers awkwardly. Replace this with a default view showing only the worst N components (by severity) with an option to expand/see the full list, rather than a wide scrollable table.
5. **Fix the Pareto chart's rendering overflow.** The chart's x-axis labels currently overlap and are cut off below the card's visible boundary. This must render fully within the card at any data volume (e.g. via label rotation, truncation with full text on hover, or a scrollable chart area contained within the card).
6. **Source Componentes Monitoreados from Oil only.** Remove Alerts as a data source for this list. The list must reflect only components present in the Oil dataset for that unit — superseding the earlier dual-source (Oil + Alerts) deduplication rule from `03_unit_summary_content.md`.

---

## Functional Rules

- Severity color mappings must be shared/consistent across a card's badge and its chart elements — never defined independently per visual.
- The Monitoreo section's aggregated status must account for every possible sub-card state, including "Sin Datos," not only the three severity levels.
- The Alertas card's two data-related statements (freshness banner and summary conclusion) must always share the same reference date when the underlying data is the same stale snapshot.
- The Tribología table's "worst N" default view must use the same severity ranking already used elsewhere (Normal < Alerta < Anormal) to determine which components are shown by default.
- The Pareto chart's rendering fix must hold regardless of how many systems are present in a given unit's data — it must not regress to overflowing again as data volume grows.
- The Componentes Monitoreados list must not silently reintroduce Alerts-sourced components through any shared/cached logic — the data-fetch for this list must explicitly query Oil only.

---

## Acceptance Criteria

- [ ] Telemetría's status badge and its chart's bar colors reflect one consistent severity mapping.
- [ ] The Monitoreo section's overall badge correctly reflects sub-cards reporting "Sin Datos," verified against a unit with at least one such sub-card.
- [ ] The Alertas card's banner and summary line reference the same date and no longer read as contradictory.
- [ ] The Tribología card shows a default "worst N" view with an expand option, with no horizontal scrolling required to read the default view.
- [ ] The Pareto chart's x-axis labels render fully within the card boundary, tested with a unit that has 7+ systems.
- [ ] Componentes Monitoreados reflects Oil-dataset components only, verified against a unit previously showing Alerts-derived entries.
