# Technical Requirement — Dashboard: audit and align per-mode status and Análisis Inteligente sources

**Team:** Dashboard (Predictive: `tab_predictive_overview.py`, `tab_predictive_evidence.py`, `predictive_config.py`)
**Type:** Audit, then edit if needed
**Related tickets:** Mailing and PDF teams have the same audit with the same source of truth.

---

## Context

The same unit shows different failure mode statuses, colors and scores across the Dashboard, the Mailing and the PDF. The reference case is unit **CA-83** (capstone, motor, cutoff 06 Nov 2026).

In the Dashboard:

- The dominant mode (Desbalance Térmico) shows **"Score 26.4"**, while the PDF shows 31.9 for the same mode.
- In *Comparación Modo de Falla*, Falla de Lubricación and Falla de Turbocompresor sit well above the fleet average in *Perfil de riesgo* and appear orange/red in *Calendario de estado*. The PDF reports both as *Saludable*.
- The Dashboard lists more modes than the PDF and names one differently ("Desgaste de Cojinetes" vs "Desgaste de Rodamientos").
- The *Análisis Inteligente* panel in Predictive Evidence may not be reading `unit_failure_analisis`.

The most likely cause is that the three outputs read different files or apply their own logic on top of the data.

## Shared specification

**Source of truth for per-failure-mode status and color:** table `predictive/risk_scores`, column `risk_level`.

Path: `data/predictive/golden/{cliente}/{componente}/risk_scores/year=YYYY/week=WW/part-0.parquet`
Grain: unit × day × failure_mode, plus the `ranking` row.

`risk_level` is **not documented** in data contract v2.11 (the documentation is outdated). Assume it exists and verify it: report its dtype, its distinct values, and whether it is null on any row, including the `ranking` row.

**Rules for all three teams:**

- If the audit finds a different source or logic, edit it to match the above. If it is already compliant, document that and close the ticket with no code change.
- Status must never be recomputed from `risk_value`, `ranking`, `estado`, `criticidad` or any numeric threshold in consumer code.
- Each `risk_level` value maps to one color, identical across the three outputs. Record the current mapping in the findings and align it to the canonical palette defined by the technical lead.
- `motor.csv` and `analisis_inteligente.parquet` have been deleted. No reads of either may remain.

## Required Changes

1. **Audit mode status and color.**
   - Scope: *Resumen de Condición* (Modo dominante card), *Comparación Modo de Falla* (Calendario de estado, Perfil de riesgo), and any other per-mode badge or color in the files listed above.
   - Output: the findings report (see template below), posted in the ticket **before any code change**.

2. **Audit Análisis Inteligente.**
   - Identify the table and columns feeding *Diagnóstico*, *Causa probable* and *Acciones*.
   - Include them in the findings report.

3. **Align status and color.**
   - Every per-mode status or color that is not taken from `risk_scores.risk_level` must be replaced.
   - In *Calendario de estado*, each cell uses the `risk_level` of that unit × day × mode row.
   - The Modo dominante badge uses the `risk_level` of the dominant mode.

4. **Align Análisis Inteligente** to `unit_failure_analisis`:

   | UI segment | Column in `unit_failure_analisis` |
   |---|---|
   | Diagnóstico | `diagnostico` |
   | Causa probable | `causa_probable` |
   | Acciones | `acciones` (JSON list, rendered as items as it is today) |

   The unit and `year/week` partition must be the same run as the rest of the page.

5. **Remove** any reference or fallback to `motor.csv` and `analisis_inteligente.parquet`.

## Functional Rules

- Numeric scores (Score, Perfil de riesgo bars) may still be displayed, but must never decide status or color.
- The Análisis Inteligente panel must **not** fall back to `mode_failure_analisis` (`diagnostico`, `probable_cause`, `recommended_actions`).
- If the narrative is null or empty (for example `analisis_fuente = "omitida"`), keep the existing empty-state behavior.
- Existing functionality must remain unchanged outside the affected sections: hero banner, fleet `estado`, ranking, trend, and the series colors of *Perfil de riesgo* (these are not status colors).

## Findings Report Template

Post in the ticket before editing code.

| # | Item | Finding |
|---|---|---|
| a | Every table or file read for per-mode status, color, score, mode list and mode label | |
| b | Full path, `year/week` partition, environment (local mirror or S3) and last sync date | |
| c | Columns used for each item in (a) | |
| d | Logic applied on top (thresholds, color mappings, defaults, fallbacks) | |
| e | Remaining references to `motor.csv` or `analisis_inteligente.parquet` | |
| f | `risk_level` check: exists? dtype, distinct values, nulls (including the `ranking` row) | |
| g | CA-83 reference case (see below) | |
| h | Source of *Diagnóstico*, *Causa probable* and *Acciones* | |

**(g) CA-83 reference case** (capstone, motor, cutoff 06 Nov 2026):

| Failure mode | Status/color shown in the Dashboard | `risk_level` in `risk_scores` | Match? |
|---|---|---|---|
| (one row per mode) | | | |

## Acceptance Criteria

- [ ] Findings report posted with items (a) to (h).
- [ ] No per-mode status or color in the Dashboard is derived from a numeric threshold.
- [ ] CA-83 mode statuses in the Dashboard equal `risk_level` in `risk_scores` for the same partition.
- [ ] *Diagnóstico*, *Causa probable* and *Acciones* come from `diagnostico`, `causa_probable` and `acciones` of `unit_failure_analisis`.
- [ ] No reads of the deleted legacy files remain.
- [ ] Hero banner, fleet `estado`, ranking and trend are unchanged.

## Optional considerations (not in scope)

- Update the data contract to document `risk_level` (type, values, origin) and mark `criticidad` as not for consumer use.
- Use one shared status-to-color mapping across the three outputs so they can't drift apart again.
- Use one mode label list ("Desgaste de Cojinetes" vs "Desgaste de Rodamientos").
