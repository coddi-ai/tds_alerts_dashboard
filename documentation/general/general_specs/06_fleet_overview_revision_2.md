# Technical Requirement — Fleet Overview: Revision 2 (Localization, Layout, Content & Status Consistency)

> Revises: Phase 1 (Unified Fleet Overview) and `04_fleet_overview_status_and_freshness_revision.md`. Depends on: `implementation_guide.md` (Phase 0) for the overall-status aggregation rule and the data-source availability definition.
>
> Scope note: item 2 (card grid) and item 3 (text simplification) are content/density decisions; exact visual spacing, sizing and typography are left to the later UI/UX pass. Everything else here is functional.

## Goal Definition

Localize all remaining English text on the Fleet Overview to Spanish, arrange unit cards in a grid (max 3 per row) instead of a single column, reduce the amount of text shown per card, and eliminate the contradiction currently visible between a unit's overall status, its per-technique "Sin Datos" rows, and the data-sources banner.

---

## Business Problem Context

The current Fleet Overview mixes Spanish and English (the page title and every label in the "Fuentes de datos" banner are still in English), stacks all unit cards in one column regardless of available width, and shows dense per-row text. More importantly, every visible unit currently shows "Sin Datos" on every technique row, while its top-level "Estado" badge still reads "Normal" — and the "Fuentes de datos" banner simultaneously claims every source is "Disponible." A user reading this page sees three signals that contradict each other (banner: available; rows: no data; badge: normal), which defeats the page's purpose of giving a trustworthy oversight of the fleet.

---

## Feature Context

Applies to the Fleet Overview page: page header/title, the "Fuentes de datos" banner, and the unit card grid (layout, per-card text, and status computation).

---

## Required Changes

1. **Localize remaining text to Spanish.** The page title ("Fleet Overview") and every label in the "Fuentes de datos" banner ("Oil Machine Status," "Alerts Consolidated," "Data Freshness," "Maintenance Contract," "Telemetry Unit Health," "Predictive Components") must be translated, along with any other leftover English string on this page.
2. **Grid layout for unit cards.** Within each status band (Anormal/Alerta/Normal), render unit cards in a responsive grid with a maximum of 3 cards per row, reflowing to fewer per row on narrower viewports, instead of a single vertical column.
3. **Simplify per-card text.** Reduce the text shown per technique row — the current full-sentence freshness description ("Última actualización: hace 82 días - desactualizado") should be trimmed to a more compact form while keeping the same underlying information (technique, status, freshness). Exact wording/format to be defined with product in the later UI/UX pass; the requirement here is reduced text volume without losing information.
4. **Fix overall Estado vs. technique-data contradiction.** When every technique available to a unit shows "Sin Datos," the unit's top-level Estado must not display "Normal." It must reflect that no evaluation is currently possible, per the aggregation rule confirmed/updated in `implementation_guide.md`.
5. **Fix banner vs. row contradiction.** The "Fuentes de datos" banner must be computed from the same real, current data-availability signal as the per-unit technique rows. If units are showing "Sin Datos" for a source, that source's banner entry cannot simultaneously read "Disponible."
6. **Investigate and report the underlying stale-data issue.** Freshness gaps of 70+ days and reference dates several months behind the current date recur across nearly every technique and unit. This is very likely a data-ingestion problem outside the dashboard's own code and must be investigated and reported to the team owning those pipelines; the dashboard's status logic cannot be fully validated until this is resolved or explicitly acknowledged as expected/known.

---

## Functional Rules

- Overall Estado must always be derived strictly from actual technique statuses/data availability — it must never default to "Normal" in the absence of supporting data.
- The banner's "Disponible / No disponible" indicators must share the same source of truth as the per-unit technique rows; they cannot be computed independently or statically.
- Text simplification (item 3) must not drop any information already required by prior phases (status, freshness state, which technique) — only reduce verbosity.
- The grid layout (item 2) applies within each existing status band; band grouping and ordering (Anormal → Alerta → Normal, with counts) must remain unchanged.

---

## Acceptance Criteria

- [ ] No English-language text remains anywhere on the Fleet Overview page.
- [ ] Unit cards render in a grid of up to 3 per row within each status band, reflowing responsively.
- [ ] Per-card technique rows show a reduced/simplified text format while still conveying status and freshness.
- [ ] A unit with "Sin Datos" across all its techniques cannot display "Estado: Normal" — it shows a no-data-appropriate state instead.
- [ ] The "Fuentes de datos" banner cannot show "Disponible" for a source that the unit rows report as "Sin Datos."
- [ ] The root cause of the widespread stale/missing data has been investigated, with findings documented and escalated if it originates outside the dashboard.
