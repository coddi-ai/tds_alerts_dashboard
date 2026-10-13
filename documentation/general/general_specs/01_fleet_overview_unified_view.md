# Technical Requirement — Phase 1: Unified Fleet Overview

> Depends on: `00_implementation_guide.md` (Phase 0). The aggregation, freshness, and ranking rules referenced below use the Confirmed rules from that guide (§3.1–3.3).

## Goal Definition

Replace the current "Summary" and "Data Summary" tabs with a single, unified Fleet Overview: units grouped and sorted by severity (Anormal → Alerta → Normal), each represented by one KPI card that shows per-technique status **and** data freshness in one place.

---

## Business Problem Context

The dashboard's purpose is to give a clean oversight of the full fleet. Today that oversight is split across two tabs — a KPI-card "Summary" (only built out for Predictive Models) and a "Data Summary" table showing whether data is arriving per unit/source. A user has to cross-reference both tabs to know both "how bad is this unit" and "can I trust what this card is telling me." This slows down triage and undermines confidence in the severity labels, since a unit can look "Normal" while its data is actually stale.

---

## Feature Context

This is the landing view of the dashboard. It must:
- Surface the most worrying units first, using the existing 3-level severity model already used for Predictive Models (Image 1: Anormal / Alerta / Normal).
- Extend the KPI-card pattern (currently Predictive-Models-only) to cover every technique applicable to a given client: Alerts, Telemetry, Oil, Maintenance, Predictive Models.
- Fold in the freshness signal currently shown in the separate Data Summary table (Image 2) so each card also communicates whether each technique's data is current.
- Respect existing per-client conditional rendering — a technique not available for a client must not appear.

---

## Required Changes

1. **Remove the tab split.** The "Summary" and "Data Summary" tabs are retired and replaced by one Fleet Overview view.
2. **Status bands.** Group units into three sections, in fixed order: Anormal (red), Alerta (yellow), Normal (green). Each section header shows a count, e.g. "UNIDADES ALERTA (2)", matching the current visual pattern.
3. **Sorting within a band.** Order units by descending severity/ranking score, per the ranking rule confirmed in `00_implementation_guide.md` §3.3 (worst-of priority across all techniques except Maintenance, tiebroken by count of Alerta/Anormal techniques, then alphabetical).
4. **Unit KPI card.** For each unit, render one card containing:
   - Unit identifier.
   - Overall status badge (Normal/Alerta/Anormal), per the aggregation rule confirmed in `00_implementation_guide.md` §3.1. Maintenance status (SANO/DETENIDO) is shown as its own separate badge, never folded into this one.
   - One row per applicable technique (Alerts, Telemetry, Oil, Maintenance, Predictive Models) showing that technique's own status.
   - A freshness indicator per technique row (data arriving vs. stale/missing), derived from the per-technique thresholds confirmed in `00_implementation_guide.md` §3.2.
5. **Per-client conditional rendering.** A technique not available for the unit's client must not render a row on that card — no placeholders, no empty rows.

---

## Functional Rules

- A unit's overall band is determined by the aggregation rule confirmed in `00_implementation_guide.md` §3.1: worst-status-among-applicable-techniques, **excluding Maintenance** (operational axis, not severity — shown as its own independent badge instead), gated per-client via `is_service_enabled()` so an inapplicable technique renders no row at all rather than a placeholder.
- A stale/missing-data state on a technique row must be visually distinguishable from that technique legitimately being "Normal." Stale data is never rendered as if it were a good status.
- If a client has zero data for a technique, that technique's row is omitted entirely from the card.
- Sorting logic must work for units that have different subsets of available techniques (a unit with 2 techniques and a unit with 5 must still be comparably ranked).
- All other dashboard functionality (Alerts, Telemetry, Oil, Maintenance, Predictive Models detail sections) is unaffected by this phase.

---

## Acceptance Criteria

- [x] The "Summary" and "Data Summary" tabs no longer exist as separate tabs; one Fleet Overview view exists in their place.
- [x] Units render grouped into Anormal / Alerta / Normal bands, in that order, each with an accurate count.
- [x] Each unit card displays a status row for every technique available to that client, and no rows for unavailable techniques.
- [x] Each technique row visibly distinguishes "stale/no data" from "Normal."
- [x] Units within each band are sorted per the confirmed ranking rule, verified against at least one multi-client dataset with mixed technique availability.
- [x] No regressions to Alerts, Telemetry, Oil, Maintenance, or Predictive Models detail views.
