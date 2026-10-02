# Technical Requirement — Fleet Overview: Status Semantics & Freshness Revision

> Revises: Phase 1 (Unified Fleet Overview). Depends on: `implementation_guide.md` (Phase 0) for freshness thresholds and status vocabulary — items below that surface open questions must be resolved there (or in an addendum to it) before implementation.
>
> Scope note: this requirement is functional/content only. Visual layout issues already logged (card separation, alignment, use of width) are explicitly out of scope here and will be addressed in a later UI/UX pass.

## Goal Definition

Remove the ambiguity and apparent contradictions in how the shipped Fleet Overview communicates unit status and data freshness, verify that the freshness calculation is actually correct, and restore the per-technique severity detail that was present in the original design but lost in the current implementation.

---

## Business Problem Context

The shipped Fleet Overview (see current screenshot) shows, per unit, a pair of top-level badges (e.g. `Anormal` / `SANO`) that read as contradictory, and per-technique rows that pair a status word with a freshness note using overlapping severity language (e.g. `Telemetria — Normal — Preocupante · hace 73 días`). On top of that, every technique on every visible unit currently shows as stale ("Preocupante"), which is either a genuine, fleet-wide data pipeline problem or a bug in the freshness calculation — and as shipped there's no way to tell which. Finally, the coarse status-only rows removed the underlying severity value that let a user compare "how Anormal" two units in the same band actually are, which was present in the original Predictive Models KPI card this view was based on. Left unresolved, these issues undermine trust in the entire Fleet Overview, since the labels themselves look inconsistent or wrong.

---

## Feature Context

Applies to the unit KPI cards on the Fleet Overview (the grouped/sorted list of units by status band). This is a revision of functionality delivered in Phase 1 — no new sections or views are introduced.

---

## Required Changes

1. **Clarify or remove the dual top-level badge.** Determine whether the overall band label (e.g. `Anormal`) and the second label (e.g. `SANO`) represent two genuinely distinct scales. If so, label each distinctly so they cannot be read as contradictory (e.g. prefix or reposition so their different meaning is obvious). If the second label is redundant or leftover from an earlier iteration, remove it.
2. **Separate status and freshness language on technique rows.** Each row must make it unambiguous that the status word (Normal/Alerta/Anormal) refers to the technique's reading, and the freshness note refers strictly to data recency — not a second severity judgment. Avoid freshness wording that itself implies severity (e.g. "Preocupante") when the intent is purely descriptive; prefer a neutral freshness statement (e.g. "Última actualización: hace X días") paired with a separate stale/fresh flag.
3. **Verify the freshness threshold calculation.** Since all techniques on all currently visible units render as stale, confirm against the thresholds in `implementation_guide.md` whether this reflects a real, fleet-wide data ingestion problem (in which case: no dashboard code change, but the finding must be escalated to the team owning the relevant data pipelines) or a bug in the threshold/date computation (in which case: fix it). This must be explicitly determined, not left as an open question.
4. **Restore per-technique severity value on the card.** Reintroduce the underlying score/value driving each technique's status color (not just the colored label), matching the level of detail in the original Predictive Models KPI card, so units within the same band remain comparable at a glance.
5. **Resolve the "Fuentes de datos" banner.** Confirm whether these values are meant to vary per client. If they are meant to be dynamic and currently render statically as "Disponible" regardless of actual availability, fix the data binding. If no per-client dynamic behavior is intended, remove the banner rather than show a value that carries no information.

---

## Functional Rules

- No technique row may combine a status word and a freshness descriptor whose vocabulary overlaps or contradicts (e.g. "Normal" next to "Preocupante").
- When a technique's data is stale beyond the confirmed threshold, its displayed status must reflect that it cannot currently be trusted (per the rule in `implementation_guide.md`) — it must not show a green/Normal label alongside a "stale" flag as if both were independently and equally true.
- The two top-level unit badges may only both appear if each has a distinct, clearly labeled meaning. An unexplained, potentially contradictory pair is not acceptable.
- Any severity value reintroduced on the card must use the same scale/units already established for that technique — do not invent a new unified scale without an explicit decision recorded in `implementation_guide.md`.

---

## Acceptance Criteria

- [x] Each unit card shows an unambiguous top-level status badge (or clearly, distinctly labeled badges if more than one is genuinely needed). — `_labeled_badge()` (`dashboard/components/fleet_overview.py`) prefixes both the overall badge ("Estado: …") and the independent Maintenance badge ("Mantención: …") with a caption naming their axis, so they can no longer read as two contradictory opinions of the same thing.
- [x] No technique row shows a status label and a freshness label with contradictory or overlapping severity wording. — `_freshness_badge()` now renders a neutral "Última actualización: hace X" statement (plus a non-overlapping "por actualizar"/"desactualizado" flag when trending/badly stale), never the raw Ok/Atención/Preocupante tier word next to the status badge.
- [x] The freshness calculation has been verified: either confirmed correct with the underlying data issue escalated to the appropriate team, or fixed if the calculation itself was wrong. — Verified against real data for all 3 enabled clients (2026-09-29): the calculation is correct (CAPSTONE's Predictivo reads "Atención", not "Preocupante", proving it isn't stuck worst-case); the widespread staleness is a genuine upstream ingestion gap, broader than previously known (now also affects Alertas/Predictivo/Mantenciones, not just Telemetría). Recorded and escalated in `00_implementation_guide.md` §4, bug #4. No dashboard code fix applicable to the calculation itself. Additionally, `_effective_status()` now ensures a technique whose freshness has crossed into the worst tier is displayed as "Sin Datos" rather than as a trustworthy resolved status.
- [x] Each technique row again displays its underlying severity value/score, not only a coarse status label. — `_severity_value_chip()` restores Alerts' `criticality_score`, Telemetry's `unit_score`, Oil's `machine_score`, and Predictivo's `ranking` (the same value the original Predictive Models KPI card showed) next to each technique's status badge; suppressed when that row's status was just overridden to "Sin Datos" by the freshness check above.
- [x] The "Fuentes de datos" banner accurately reflects real per-client data source availability, or has been removed. — Confirmed genuinely dynamic per client (verified against real probes), but its `SERVICE_SOURCES["overview-general"]` mapping (`dashboard/components/source_status.py`) only checked 3 of the Fleet Overview's 5 techniques — Telemetry and Predictivo were silently excluded, so a client missing either still read "Disponible" (e.g. CAPSTONE, which has no Telemetría feed). Fixed by adding `telemetry_unit_health` and `predictive_components` to the probed set; CAPSTONE now correctly reads "Parcial".
