# Findings Report — Dashboard: per-mode status and Análisis Inteligente sources

**Ticket:** `req_dashboard_status_audit.md` (Dashboard team)
**Audited:** 2026-11-10, branch `dev`, before any code change
**Reference case:** CA-83, capstone / motor, cutoff 2026-11-06

Everything below was measured against the local mirror, not inferred from reading code.

## Verdict

**Not compliant.** The Dashboard never reads `risk_scores.risk_level`. It recomputes every per-mode status and color from the numeric `risk_value`, using thresholds of its own. It also falls back to two sources it must not use (`analisis_inteligente.parquet`, `mode_failure_analisis`), and the legacy `{component}.csv` read path is still wired in.

The statement "Falla de Lubricación and Falla de Turbocompresor appear orange/red" **did not reproduce** on this mirror. See (g).

## (a) Tables / files read

| Item | Source today |
|---|---|
| Per-mode score | `risk_scores.risk_value`, pivoted wide (`risk_scores_to_wide`), then rolling 7/30/60/90d means computed in `_load_component_data_cached` |
| Per-mode status / color (Calendario de estado) | **Not read.** Computed from `risk_value` (see d) |
| Per-mode status / color (Riesgo por modo de falla table cells) | **Not read.** Computed from the windowed mean of `risk_value` (see d) |
| Per-mode status / color (Evidence insight panel, "Resultado") | **Not read.** Computed from `risk_value` (see d) |
| Modo dominante | `argmax` of `{mode}_30d` (client-side rolling mean of `risk_value`). No badge or color today |
| Mode list | `predictive_v2.get_failure_mode_keys` = `unit_status_summary.modos_ordenados` keys + distinct `risk_scores.failure_mode`, minus `ranking` |
| Mode label | `src/data/predictive_catalog.py` (`FAILURE_MODE_CONFIG`), re-exported by `predictive_config.py`. Not read from data |
| Fleet `estado` | `unit_status_summary.estado` (fallback `analisis_inteligente.parquet`). Out of scope, unchanged |
| Análisis Inteligente | see (h) |

## (b) Path, partition, environment, sync

- Root: `DASHBOARD_DATA_ROOT` env var, default `<repo>/data`. **Local mirror**, no S3 read at runtime. `DASHBOARD_DATA_ROOT` is not set in `.env`, so the default applies here.
- `risk_scores`: `data/predictive/golden/capstone/motor/risk_scores/year=2026/week=45/part-0.parquet`. The Dashboard reads the **last 13 week partitions** (weeks 33 to 45 of 2026). Cutoff rows span 2026-11-02 to 2026-11-06.
- `unit_status_summary`, `unit_failure_analisis`, `mode_failure_analisis`: latest partition = `year=2026/week=45`.
- Last sync: partition files modified **2026-11-10 17:13**.
- Same-run check: for capstone/motor and cda/motor/transmision, `risk_scores`, `unit_status_summary` and `unit_failure_analisis` have the same latest `(year, week)`. cda is at `2026/29`, capstone at `2026/45`.

## (c) Columns used

- `risk_scores`: `Unit`, `Fecha`, `failure_mode`, `risk_value`. **`risk_level`, `risk_value_raw` and `coverage` are dropped at the pivot.**
- `unit_status_summary`: `Unit`, `estado`, `media_30d`, `dias_media_30d`, `modos_ordenados`.
- `unit_failure_analisis`: `Unit`, `Fecha`, `estado`, `analisis_fuente`, `diagnostico`, `causa_probable`, `acciones`.
- `mode_failure_analisis`: `Unit`, `failure_mode`, `analysis_status`, `diagnostico`, `probable_cause`, `recommended_actions`.

## (d) Logic applied on top

| Site | Logic | Verdict |
|---|---|---|
| `predictive_charts.create_mode_status_calendar` | Trailing 7-day mean of `risk_value` compared with per-mode P75/P90/P98 from `config/umbrales_criticidad/capstone.json`; modes without calibration use fixed 35/55/75 on the daily value. Missing day = "Sin datos" | **Threshold-derived. Replace.** |
| `tab_predictive_overview._mode_cell_style` / `_failure_table` | Same calibrated edges on the windowed value shown, else fixed 40/70 via `_score_cell_style` | **Threshold-derived. Replace.** |
| `tab_predictive_evidence._build_insight_panel` | `score >= 70` red "alto", `>= 40` amber "medio", else green "bajo" | **Threshold-derived. Replace.** |
| `tab_predictive_evidence._dominant_mode_card` | No color; score is the 30d mean | No status today. Add `risk_level` badge |
| `create_comparative_bars` (Perfil de riesgo) | Fixed series colors: fleet grey, unit blue `#2563EB` | **Not a status color. Keep** |
| `_risk_tile` / `RISK_SCALE_BANDS` (40/70 chips) | Colors the overall **ranking** (Riesgo Acum. 90d, Ranking 7 Días) | Not per-mode. Ranking is out of scope. Unchanged |
| `_score_cell_style` on the table's ranking column | 40/70 on the overall ranking | Not per-mode. Unchanged |
| `attach_status` | `unit_status_summary.estado`, fallback `analisis_inteligente.parquet` | Fleet `estado` unchanged, **fallback removed** |
| `_generate_insight_data` observations | `score > fleet_p80 and score > 10` produces a text observation | Descriptive text, not a status. Unchanged |

Current color mapping (to be replaced by one `risk_level` to color map):

| Level | Calendar | Table cell (bg / text) | Insight panel |
|---|---|---|---|
| Saludable | `#1d9e75` | `#eaf3de` / `#3b6d11` | green `#1d9e75` if score < 40 |
| Monitoreo | `#f2d04b` | `#fdf3c4` / `#7a5f00` | amber `#ef9f27` if score 40 to 69 |
| Prioridad alta | `#ef7f27` | `#fde4cf` / `#9a4a0a` | no equivalent (3 tiers) |
| Crítico | `#e24b4a` | `#fcebeb` / `#a32d2d` | red `#e24b4a` if score >= 70 |
| Sin datos | `#e5e7eb` | n/a | n/a |

The same four levels get **three different palettes**, and the insight panel has only three tiers.

## (e) Remaining references to legacy files

Reads in Dashboard-reachable code:
- `src/data/loaders.py`: `load_analisis_inteligente`, `_load_analisis_inteligente_cached`, `get_latest_analisis_inteligente`, and `get_model_run_date` (which reads the file first).
- `tab_predictive_overview.py`: `attach_status` fallback; `_load_component_data_cached` legacy CSV branch (`fast_read_csv`); `_discover_components` `legacy_csv` branch.
- `tab_predictive_evidence.py`: `_resolve_unit_ai_panel` fallback to `load_analisis_inteligente`.
- `src/data/predictive_v2.py`: `discover_predictive_layout` records `{component}.csv` as `legacy_csv`.
- `dashboard/components/fleet_overview.py`: `_component_predictive_status_maps` fallback to `get_latest_analisis_inteligente`.
- `dashboard/callbacks/predictive_pages_callbacks.py`: availability check accepts `legacy_csv`.

Outside the Dashboard files, **reported, not changed in this ticket**:
- `src/campbell_ai/data.py:189-195`: `DatasetSpec` reads `predictive/golden/{client}/motor.csv` and `transmision.csv`.
- `src/data/catalog.py:172` probes `analisis_inteligente.parquet`; `catalog.py:191` globs `*.csv`.
- `scripts/benchmark_dashboard.py:30`: reads `motor.csv`.
- The mirror still holds `capstone/motor.csv`, `cda/motor.csv`, `cda/transmision.csv`, `cda/analisis_inteligente.parquet` (not deleted locally).

## (f) `risk_level` check

Measured on `risk_scores` week 45 (2,532 rows) and on the 13-week window the Dashboard loads:

- **Exists:** yes.
- **dtype:** `string` (pandas `StringDtype`).
- **Distinct values (4):** `Saludable`, `Monitoreo`, `Prioridad alta`, `Critico`. **`Critico` has no accent**, while the Dashboard's label is "Crítico". Matching must be accent-insensitive or use a map keyed on the contract spelling.
- **Nulls:** 0 on all rows, **including the `ranking` rows** (its levels are Saludable, Monitoreo, Prioridad alta; no `Critico` in week 45).
- Other new columns: `risk_value_raw` (float), `coverage` (float). Both are NaN on `ranking` rows.
- **`risk_level` is not a function of `risk_value`.** `combustion_risk` on CA-83: 12.26 is `Monitoreo` (2026-11-04) and 12.40 is `Prioridad alta` (2026-11-06). In the 13-week data a single `risk_value` range maps to several levels: `thermal_imbalance_risk` `Monitoreo` spans 1.31 to 35.30, `Prioridad alta` spans 4.66 to 52.36. Upstream classifies on something else (the `risk_value_raw` / calibration path). This confirms that no consumer-side threshold can reproduce it.

## (g) CA-83 reference case (cutoff 2026-11-06)

"Dashboard" = what the Calendario de estado cell for 2026-11-06 renders today (computed by calling the current code on the real data). "PDF" column = `mode_failure_analisis.criticidad`, which is what the PDF's "Saludable" values trace back to.

| Failure mode | Dashboard (calendar, 11-06) | `risk_level` (`risk_scores`) | Match? | `mode_failure_analisis.criticidad` |
|---|---|---|---|---|
| lubrication_failure_risk | Monitoreo | Monitoreo | yes | Saludable |
| coolant_contamination_risk | Saludable | Saludable | yes | Saludable |
| turbocharger_risk | Monitoreo | Monitoreo | yes | Saludable |
| bearing_wear_risk | Saludable | Saludable | yes | Saludable |
| oil_degradation_risk | Saludable | Saludable | yes | Saludable |
| thermal_imbalance_risk | Prioridad alta | Prioridad alta | yes | Monitoreo |
| combustion_risk | Prioridad alta | Prioridad alta | yes | Saludable |
| abrasive_wear_risk | Saludable | Saludable | yes | Saludable |
| blowby_risk | Saludable | Saludable | yes | Saludable |
| accumulated_wear_risk | Monitoreo | Monitoreo | yes | Saludable |
| *(ranking, not displayed per mode)* | n/a | Prioridad alta | n/a | n/a |

Reading of the table:

1. **The 10 cells match on this one day, by coincidence.** The calibrated P75/P90/P98 edges happen to land on the right level for 2026-11-06. Across the full 90-day window the calendar disagrees with `risk_level` on **2 of 810 cells for CA-83** (both `lubrication_failure_risk`) and **109 of 39,736 fleet-wide** (0.3%: coolant 28, oil degradation 20, turbocharger 18, bearing 9, and others). So the logic is wrong even though today's headline cells look right.
2. **No orange/red for Lubricación or Turbocompresor on this mirror.** Both are `Monitoreo` (yellow `#f2d04b`). The orange/red the ticket describes may come from another partition or environment. That is not reproduced here and is not claimed as fixed.
3. **The PDF's "Saludable" is a different field.** `mode_failure_analisis.criticidad` says Saludable for lubrication, turbocharger, combustion and accumulated wear, while `risk_scores.risk_level` says Monitoreo / Monitoreo / Prioridad alta / Monitoreo. The Dashboard/PDF disagreement is explained by two different columns, not by the Dashboard misreading one of them. The PDF and Mailing teams should confirm they read `risk_scores.risk_level`.
4. **"Score 26.4" vs "31.9":** the Modo dominante card shows the **30-day rolling mean** (`thermal_imbalance_risk_30d` = 26.4). The PDF's 31.9 is the cutoff-day `risk_value` (= `unit_status_summary.peor_valor` 31.92). Both are valid numbers; they are different windows. The ticket allows numeric scores to be displayed, so this is left as is and raised as an open question below.
5. **Mode list / label:** the Dashboard shows 10 modes (all that `risk_scores` carries). "Desgaste de Cojinetes" is the catalog label (`predictive_catalog.py:74`); "Desgaste de Rodamientos" exists in the same catalog at line 106 for another component. Unifying labels is listed as optional in the ticket and was not changed.

## (h) Source of Diagnóstico / Causa probable / Acciones

Today, in order (`tab_predictive_evidence._resolve_unit_ai_panel`):

1. `unit_failure_analisis` latest partition: `diagnostico`, `causa_probable`, `acciones`. Correct source.
2. If that table is empty: `analisis_inteligente.parquet`. **Forbidden.**
3. If the unit's `analisis_fuente == "omitida"` or narrative is empty: worst-mode row of `mode_failure_analisis` (`diagnostico`, `probable_cause`, `recommended_actions`). **Forbidden.**

CA-83 is `analisis_fuente = llm`, so it already gets the correct text. The violation hits the units that fall to step 2 or 3: in week 45, **45 of 50 units are `omitida`** and currently show `mode_failure_analisis` text.

Note: `omitida` rows are not null in the table. They carry a fixed template ("El motor no presenta modos de falla sobre 50...") in the three columns. The ticket says `omitida` is an empty-state case, so that behavior is kept.

## Planned changes (executed after this report; outcome in the next section)

1. Read `risk_scores.risk_level` (keep it through the pivot, normalized `Critico` / `Crítico`), one shared `risk_level` to color/label map.
2. Calendario de estado, Riesgo-por-modo table cells and the Evidence insight "Resultado" use `risk_level`. Delete the threshold code and `config/umbrales_criticidad` loading.
3. Modo dominante gets a badge with the dominant mode's `risk_level`.
4. Análisis Inteligente reads only `unit_failure_analisis` for the same `(year, week)` as `risk_scores`; no fallbacks.
5. Remove the `analisis_inteligente.parquet` and `{component}.csv` read paths.

## Open questions (not blocking)

- **Canonical palette.** The ticket refers to a palette "defined by the technical lead" that is not in the repo. The existing calendar palette (`#1d9e75`, `#f2d04b`, `#ef7f27`, `#e24b4a`, no-data `#e5e7eb`) becomes the single map, in one place, so it can be swapped for the canonical values in one edit.
- **Modo dominante score.** Keep the 30-day mean, or show the cutoff-day `risk_value` (31.9) so it matches the PDF?
- **Riesgo-por-modo table.** Its cells show a windowed mean (hoy / 30 / 60 / 90 d), but `risk_level` exists only per day. The cell color will be the `risk_level` of the unit's latest day for that mode, whatever window is selected.

## Outcome (after the changes)

**Verified on the real mirror** (capstone/motor, week 45):
- Calendario de estado: 45,000 fleet cells over 90 days, **0 mismatches** against `risk_level` (before: 109 of 39,736). CA-83's 10 modes at the cutoff are Monitoreo / Monitoreo / Prioridad alta / Prioridad alta / Saludable x4 / Monitoreo, identical to the `risk_level` column in (g).
- Modo dominante (CA-83): badge **Prioridad alta** (the `risk_level` of `thermal_imbalance_risk`), score text unchanged at 26.4.
- Evidence "Resultado" for CA-83 / thermal imbalance: Prioridad alta, from `risk_level` (the old code read the 31.9 score against 40/70).
- Análisis Inteligente: CA-83 shows `unit_failure_analisis` text from `year=2026/week=45`; an `omitida` unit (CA-30) shows the empty state, not `mode_failure_analisis`.
- Tests: 2,006 pass. The same 24 tests fail on a clean `HEAD` checkout (informe_falla, mantenciones, navigation, report_health, i18n sort order); none touch these changes.

**What changed**
- `predictive_state.py`: one `risk_level` to color/label table (`RISK_LEVEL_STYLE`), accent-insensitive (`Crítico` and `Critico`). Palette is the previous calendar palette, pending the lead's canonical one.
- `predictive_v2.py`: `risk_level` readers (`risk_levels_to_wide`, `load_risk_levels`, `latest_risk_levels`), `latest_risk_scores_run`, and `load_unit_failure_analisis(run=...)` reading exactly the page's `(year, week)`. Removed `legacy_csv` discovery and the `mode_failure_analisis` readers.
- `predictive_charts.py`: calendar colors only from `risk_level`; threshold code (`classify_criticidad`, `get_mode_thresholds`, `CRITICIDAD_BANDS`, the JSON loader) deleted.
- `tab_predictive_overview.py`: table cells use `risk_level`; CSV path and `analisis_inteligente.parquet` fallback removed.
- `tab_predictive_evidence.py`: Modo dominante badge, insight "Resultado" from `risk_level`, Análisis Inteligente from `unit_failure_analisis` only.
- `loaders.py`, `fleet_overview.py`, `predictive_pages_callbacks.py`, `predictive_callbacks.py`: removed `load_analisis_inteligente`, `get_latest_analisis_inteligente` and the fallbacks; `get_model_run_date` now reads only `unit_status_summary`.
- i18n: `tab_predictive_evidence.nivel_riesgo_para`, `tab_predictive_evidence.sin_nivel_de_riesgo_publicado` (es + en).

**Consequences to know about**
1. **cda has no per-mode status right now.** In the local mirror, cda `risk_scores` (through week 29) has no `risk_level` column. With the no-recompute rule, cda shows no calendar (it says the run does not publish the level), neutral table cells and a "Sin datos" badge until upstream republishes with `risk_level`. Needs confirmation from the data team.
2. **Hero banner date:** `get_model_run_date` no longer reads the legacy file; for cda it now comes from `unit_status_summary`. Capstone is unchanged.
3. **Fleet `estado`:** a component with no `unit_status_summary` now shows "Sin Datos" instead of falling back to the legacy file.
4. **Left alone, owned elsewhere:** `src/campbell_ai/data.py` (reads `motor.csv`/`transmision.csv`), `src/data/catalog.py` probe, `scripts/benchmark_dashboard.py`, and the files still present in the local mirror. `config/umbrales_criticidad/capstone.json` is now unused and can be deleted.

## Follow-up decisions (2026-11-10)

- Palette stays as is for now; cda `risk_level` will be published later by data engineering.
- **Modo dominante follows the PDF:** the dominant mode and its score are the unit's cutoff-day `risk_value` (CA-83: thermal imbalance, 31.9), not the 30-day mean (26.4). The default mode of the Evidence dropdown uses the same rule.
