# Data Contracts - Predictive Data Product

**Version**: 2.11
**Last Updated**: October 17, 2026
**Owner**: Predictive Module Team
**Status**: Golden layer migrated from the old wide per-client CSV to a partitioned parquet
format. **The data lives locally** under `data/{tecnica}/golden/{cliente}/{componente}/{tabla}/`
— it is synced there manually from S3 (not read live over `s3fs` by the dashboard). The
dashboard-side readers (`tab_predictive_overview.py`, `tab_predictive_evidence.py`,
`predictive_config.py`) still target the **v1.0 local-CSV shape** described in the
[Change Log](#change-log) — see [§9 Migration Notes](#-migration-notes-v10--v20) for what needs to
change in this repo before this contract is fully live.

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Data Layer Architecture](#data-layer-architecture)
3. [Table Schemas](#table-schemas)
4. [Reading Pattern](#reading-pattern)
5. [Failure Mode → Signal Catalog](#failure-mode--signal-catalog)
6. [Status & Classification Rules](#status--classification-rules)
7. [Cumulative Risk Curve](#cumulative-risk-curve)
8. [Data Quality Rules](#data-quality-rules)
9. [Migration Notes (v1.0 → v2.0)](#-migration-notes-v10--v20)
10. [Change Log](#change-log)

---

## 🎯 Overview

This document defines the data contract for the **Predictive** data product: per-component
(Motor, Transmisión, ...) failure-mode risk scores combining oil (tribology) and telemetry
evidence, produced entirely by an **upstream pipeline outside this repo**. This dashboard only
reads the golden-layer output described below — it does not compute essay classifications, alert
rates, or failure-mode scores itself.

**Data Product Purpose**: Provide a weekly-refreshed, per-unit record of failure-mode risk
(0-100) so the dashboard can rank units by priority, show which failure mode is driving risk, and
generate narrative evidence.

**Primary Consumer**: Multi-Technical Alerts Dashboard, Predictivo section
(`dashboard/tabs/tab_predictive_overview.py`, `tab_predictive_evidence.py`).

**As of v2.0**, the golden layer is **partitioned parquet**, replacing the wide per-client CSV
files described in v1.0. The canonical copy is produced on S3, but this repo reads it from a
**local mirror synced there manually** — there is no runtime S3 dependency. See
[§9](#-migration-notes-v10--v20) for the full diff and what it implies for this repo's loaders.

---

## 🏗️ Data Layer Architecture

### Storage Location

**Local (what this repo actually reads):**

```
data/{tecnica}/golden/{cliente}/{componente}/{tabla}/year={YYYY}/week={WW}/part-0.parquet
```

Example (verified against this checkout):

```
data/predictive/golden/capstone/motor/risk_scores/year=2026/week=32/part-0.parquet
data/telemetry/golden/capstone/motor/signal_daily_status/year=2025/week=28/part-0.parquet
```

**Upstream origin (S3):** the same relative layout is produced at
`s3://{bucket}/MultiTechnique Alerts/{tecnica}/golden/{cliente}/{componente}/{tabla}/year=/week=/part-0.parquet`
(bucket from `ERS_S3_BUCKET`), and mirrored into `data/` **manually** — there is no `s3fs`/live-S3
read path in the dashboard. Treat S3 as the origin/backup, and the local `data/` tree under the
paths above as the actual contract this repo reads against.

- **`year=` / `week=`** are Hive-style partitions, ISO week/year (Monday–Sunday; `year` is the ISO
  year, so e.g. Dec 29, 2025 falls in `year=2026/week=1`). Readers should list available
  `(year, week)` pairs rather than assume a fixed range — see [§4](#reading-pattern).
- There are **no bronze/silver layers** for Predictive — only this golden output is read.

### Refresh Cadence

Upstream, all eight tables regenerate **once per week**, one partition per run. `unit_status_summary`
also has its **history backfilled**: every past week with data has its own partition (see
[§3](#unit_status_summary)). `oil_meter_history` is exported one week at a time: each partition is
written once and not revised afterwards (see [§3](#oil--oil_meter_history)). Each
`cumulative_risk_curve` partition holds the **full history**, recomputed at that run (see
[§7](#cumulative-risk-curve)). `operating_hours` replaces only the partition of the week it
processes, and a week whose telemetry file is empty gets no partition at all (see
[§3](#telemetry--operating_hours)). Locally, freshness
depends on when the manual sync from S3 was last run — the local mirror can lag the upstream
partitions. Either way, a stalled/skipped run does not produce an empty partition, so readers
should use the *last available* partition rather than assume the current calendar week has data.

### Tables

| Table | Contents | Grain |
|---|---|---|
| `telemetry / signal_daily_status` | % of the day each engine/transmission signal spent in the alert band and in the critical band | unit × day × signal |
| `telemetry / operating_hours` | Hours each truck operated each day, total and split by operating state (idle, unloaded, loaded) | unit × day |
| `predictive / risk_scores` | Risk score per failure mode, plus the synthetic `ranking`, in **long format** | unit × day × mode |
| `predictive / unit_status_summary` | Snapshot of each unit's status as of the run's close | unit (one row) |
| `predictive / mode_failure_analisis` | Criticality plus probable cause and recommended actions for every failure mode, AI-written for flagged modes and a fixed message for healthy ones (formerly `failure_mode_diagnosis`) | unit × mode (all modes) |
| `predictive / unit_failure_analisis` | One AI-written diagnosis per unit for its worst mode, wide format (formerly `analisis_inteligente`) | unit (one row) |
| `predictive / cumulative_risk_curve` | Cumulative lifecycle risk curve per unit, with its fleet reference band | unit × day |
| `oil / oil_meter_history` | Per oil sample: hours on the current oil charge, component hours, oil and component cycles, and the running total of six wear metals | unit × sample date |

### `mode_failure_analisis` (published contract, v1.3 — formerly `failure_mode_diagnosis`)

This is the weekly analysis contract, published for both `capstone` and `cda` (motor),
**alongside** `unit_failure_analisis` (below) — the two are generated and published together by
the same run, in the same location, neither replaces the other. As of v1.2, the table has one row
per unit and **every** failure mode the unit has a score for — not only flagged ones. A unit with
no data for a given mode (missing from `modos_ordenados`) has no row for that mode; otherwise every
mode gets a row, either AI/rules-analyzed or with a fixed healthy-state message.

| Column | Type / meaning |
|---|---|
| `Unit` | Unit identifier |
| `Fecha` | Date of the data used for the analysis |
| `failure_mode` | Mode, keyed against `reglas_<cliente>_motor.json` |
| `criticidad` | `Saludable` / `Monitoreo` / `Prioridad alta` / `Critico`, from each client's own `escala` in `reglas_<cliente>_motor.json` — CDA: 0/35/55/75/100; Capstone: 0/30/50/80/100. Not a scale shared across clients. Added in v1.2. |
| `diagnostico` | What is happening for this unit in this specific mode: severity, trend, fleet position. Distinct from `probable_cause` — no mechanism here. |
| `probable_cause` | Probable physical mechanism for this mode. No actions or lab/telemetry values beyond what the mechanism implies. |
| `recommended_actions` | JSON array of ordered actions, stored as a string (exactly 3 for AI/rules rows; 1 for healthy-default rows). Each AI/rules action starts with an explicit timeframe (`Inmediato:` / `Proxima ventana:` / `Proximo PM:`, or the lowercase CDA equivalent). |
| `limitation` | What single measurement, sample, or inspection would close the open question for this mode. Added in v1.1 — absent in v1.0. |
| `analysis_status` | `ok`, `fallback_rules`, `error`, or `healthy_default` (added in v1.2) |

For modes scored at least `FLAG_THRESHOLD` (flagged), `diagnostico`, `probable_cause`,
`recommended_actions`, and `limitation` are generated by an LLM call per unit (one call covers all
of that unit's flagged modes), using the same payload as the `unit_failure_analisis` narrative
below (context, all of the unit's modes, observations). `probable_cause` deliberately stays surface-level: it
names the general physical/mechanical phenomenon (wear, combustion, lubrication, temperature,
etc.) and, if it cites an observation, the variable and its direction — it does not walk through
the multi-signal reasoning chain (e.g. "sodium and potassium rising together signals coolant
ingress"); that reasoning stays internal to the model's own judgment and to `recommended_actions`,
never the published text. If the LLM call fails, or omits one of the requested modes, that row
falls back to the static `reglas_<cliente>_motor.json` entry for that mode (`analysis_status =
fallback_rules`); if no complete rule exists either, the row is marked `error` with generic text —
the underlying exception is never written to a public field.

As of v1.3, `FLAG_THRESHOLD` is per client, not a single fixed number: it is the upper bound of
that client's own `escala` "Saludable" band — the same escala `criticidad` reads from, and the
same one used for `RIESGO_ALERTA`/`RIESGO_CRITICO` in Observaciones. Every client's `escala` has
the same shape (`0→A` Saludable, `A→B` Monitoreo, `B→C` Prioridad alta, `C→100` Critico);
`FLAG_THRESHOLD` is always that client's own `A` — 30 for Capstone, 35 for CDA today, and whatever
a future client's `reglas_<cliente>_motor.json` declares, with no code change required. This
guarantees `criticidad` and the flagging decision never disagree: a row is always `Saludable` when
and only when it is `healthy_default`.

For modes scored below `FLAG_THRESHOLD` (healthy, `criticidad = Saludable`), the row never reaches
the LLM or `reglas_<cliente>_motor.json`: it gets a fixed, client-agnostic message
(`analysis_status = healthy_default`) — `diagnostico`: "El equipo no presenta indicios de este modo
de fallo.", `probable_cause`: "El equipo se encuentra dentro de los parametros normales.",
`recommended_actions`: `["Se recomienda seguir monitoreando el equipo."]`. This does not add any
LLM cost — the model is only ever called for flagged modes, same as before v1.2.

`FLAG_THRESHOLD` is unrelated to `modes_over_threshold_count` (`unit_status_summary`, [§3](#unit_status_summary)):
that column is computed **upstream**, with a single fixed 35 for both clients, regardless of each
client's own `escala`. `analisis_predictivo.ipynb` still validates its own parsing of
`modos_ordenados` against it — a data-integrity check, unrelated to which modes this contract
chooses to publish with real analysis. The two numbers can legitimately differ (Capstone: 35 for
the integrity check, 30 for `FLAG_THRESHOLD`) without indicating a bug.

The table joins to `unit_status_summary` on `Unit` and to `risk_scores` on `Unit` plus
`failure_mode`. Its weekly snapshot path is
`MultiTechnique Alerts/predictive/golden/{cliente}/motor/mode_failure_analisis/year=YYYY/week=WW/mode_failure_analisis.parquet`.
The partition is selected from the matching `unit_status_summary` run. Publish with Zstandard
compression and no index; validate a staged `_runs/{run_id}` object before promoting it to the
canonical path.

`analisis_predictivo.ipynb` (repo root) generates and publishes this table for both clients in one
run each, alongside `unit_failure_analisis`. It does not depend on `FAILURE_MODE_CONFIG` from the
dashboard repo: the mode → telemetry-signal catalog lives in `telemetry_variables`, inside each
mode's entry in `reglas_<cliente>_motor.json`, within this repo.

### `unit_failure_analisis` (formerly `analisis_inteligente`)

One AI-written diagnosis per unit for its worst mode, wide format — the same shape the frozen
legacy `analisis_inteligente.parquet` snapshot documented below always had, just under the new
name and **no longer frozen**: `analisis_predictivo.ipynb` regenerates and publishes it every run,
side by side with `mode_failure_analisis`, partitioned the same way, at
`MultiTechnique Alerts/predictive/golden/{cliente}/motor/unit_failure_analisis/year=YYYY/week=WW/unit_failure_analisis.parquet`.
Publish with a staged `_runs/{run_id}` object validated before promotion, same as
`mode_failure_analisis`. Its columns are the ones described just below, in
"`predictive / analisis_inteligente.parquet` (frozen legacy input...)", including the
`diagnostico`/`causa_probable`/`acciones`/`limitacion` narrative fields — that section documents
the shape; treat "frozen" there as describing the original migration-era snapshot, not the current
`unit_failure_analisis` output.

### Auto-Discovery

Unlike v1.0, components are not discovered by scanning a folder for `*.csv` files — the path
itself is parameterized by `{cliente}/{componente}`. As observed in the local mirror:

| Client | Component | `risk_scores` / `unit_status_summary` (new parquet) | `cumulative_risk_curve` | `oil_meter_history` | `operating_hours` | Legacy CSV still present |
|---|---|:-:|:-:|:-:|:-:|:-:|
| `capstone` | `motor` | ✅ | ✅ | ✅ | ✅ | ✅ (`motor.csv`) |
| `cda` | `motor` | ✅ (history back to `year=2021`) | ❌ | ❌ | ❌ | ✅ (`motor.csv`) |
| `cda` | `transmision` | ❌ — not migrated | ❌ | ❌ | ❌ | ✅ (`transmision.csv`) |

So the new layout currently only covers `componente = motor`, across at least two clients
(`capstone`, `cda`); `transmision` has **not** been migrated for either client and is still only
available as the old wide CSV. `cumulative_risk_curve` has only been observed for `capstone`, and
`oil_meter_history` and `operating_hours` exist for `capstone` only.
Whether/how multi-client, multi-component discovery works against this layout (equivalent to
v1.0's `_discover_components`) is **not formally specified** — treat the table above as a snapshot
of what exists today, not a guarantee, and re-check before assuming a client/component pair is
covered.

---

## 📐 Table Schemas

### `unit_status_summary`

One row per unit per weekly snapshot — feeds the crítico/alerta/saludable fleet cards.

| Column | Type | Description |
|---|---|---|
| `Unit` | string | Unit identifier |
| `Fecha` | date | Date of **that unit's** last available reading (not necessarily the run date — see below) |
| `estado` | string | `anormal` / `alerta` / `normal` — see [§6](#status--classification-rules) |
| `estado_previo` | string | `estado` on the reading nearest to 7 days before `Fecha` (within ±3 days); null if there is none |
| `cambio_estado` | string | `"sí"` / `"no"` — whether `estado` changed vs. `estado_previo` |
| `ranking` | float | Synthetic risk score for the day |
| `delta_ranking` | float | `ranking` minus the `ranking` of that same ~7-days-earlier reading |
| `media_30d` | float | 30-day rolling mean of `ranking`, **precomputed upstream** |
| `dias_media_30d` | int | Number of real days the 30-day mean was actually computed over |
| `peor_modo` | string | Failure mode with the highest score |
| `peor_valor` | float | That mode's score |
| `modes_over_threshold_count` | int | Count of modes scoring ≥ 35. Informational only: it does **not** feed `estado` (see [§6](#status--classification-rules)) |
| `modos_ordenados` | string (JSON) | Every failure mode with its score, ordered highest → lowest |
| `dias_sin_datos` | int | Days between this unit's `Fecha` and the latest date of any unit in the same snapshot |

#### Partitions and history

Each `year=`/`week=` partition is a **snapshot of the fleet as of that week's cutoff**: the Sunday
that closes the ISO week, or the last available date for the current, still-open week. Every
snapshot is computed only from data up to its cutoff, so a past week shows what was known then —
not what is known today. The only exception is the `estado` thresholds; see
[§6](#status--classification-rules).

History is **backfilled**: every past week with data has its own snapshot, not only the weeks that
were live runs.

- A unit appears from the first week it has data. Weeks before that, it is absent.
- Once present, a unit stays in every later snapshot even if it stops reporting — a stale unit
  shows a stale `Fecha` and a growing `dias_sin_datos` rather than disappearing.
- `Fecha` varies between rows of the same snapshot: each unit carries its own last reading.

How to read it depends on the question:

```python
ruta = ruta_tabla("predictive", "unit_status_summary", "capstone", "motor")

# Current status (fleet cards): one partition, one row per unit
resumen = leer_ultimas_semanas(ruta, n=1)

# Weekly history: one row per unit per week — tell snapshots apart by year/week
historia = leer_ultimas_semanas(ruta, n=13)
historia.groupby(["year", "week"])["estado"].value_counts()
```

With `n > 1` the same unit appears once per week. Do not aggregate across weeks without grouping
by `year`/`week` first.

`modos_ordenados` must be parsed:

```python
import json
modos = json.loads(fila["modos_ordenados"])
# {'lubrication_failure_risk': 85.3, 'blowby_risk': 70.0, ...}
```

`json.loads` preserves the highest→lowest order, so it can feed a bar chart or ranked list
directly without re-sorting.

### `risk_scores`

Long format: **one row per failure mode per unit per day**, plus one row where
`failure_mode == "ranking"` — today 12 rows per unit-day for `capstone` (11 modes) and 10 for
`cda` (9 modes). Do not hardcode the count: filter by name instead (see below).

| Column | Type | Description |
|---|---|---|
| `Unit` | string | Unit identifier |
| `Fecha` | date | Day of the record |
| `failure_mode` | string | One of the failure modes (all end in `_risk`, see [§5](#failure-mode--signal-catalog)), or the literal value `"ranking"` |
| `risk_value` | float | Score, 0–100. For failure modes, the value **as it enters the `ranking`** (see below) |

**Failure-mode values are the weighted values that feed the `ranking`.** Each mode's
`risk_value` is `100 × soft_saturate(raw, scale) × weight / max_weight`, i.e. the value after
saturation and after applying the mode's weight relative to the highest weight. The `ranking`
of the day can therefore be reproduced from that unit-day's mode values alone:
`noisy_or = 1 − Π(1 − mode/100)` and
`ranking_condicion = 0.40·noisy_or + 0.30·mean(top 3) + 0.20·max + 0.10·mean(top 2)`
(`ranking` additionally applies the age factor). A consequence: a mode can never exceed
`100 × weight / max_weight`, so lower-weight modes top out below 100.

```python
modos = riesgos[riesgos["failure_mode"] != "ranking"]
ranking_diario = riesgos[riesgos["failure_mode"] == "ranking"]
# or: riesgos[riesgos["failure_mode"].str.endswith("_risk")]
```

**Absence of a row ≠ a score of 0.0.** No row for a given unit/day/mode means no data was
available that day; `risk_value == 0.0` means an actual computed score of zero risk.

### `telemetry / signal_daily_status`

| Column | Type | Description |
|---|---|---|
| `Unit` | string | Unit identifier |
| `Fecha` | date | Day of the record |
| `signal_name` | string | Signal identifier, e.g. `oil_diff_pressure_psi`, `egt_avg_c` |
| `pct_time_alert` | float | % of the day in the alert band (0–100) |
| `pct_time_critical` | float | % of the day in the critical band (0–100) |

Same rule as `risk_scores`: a missing row means no measurement that day for that signal, not a
zero reading.

> **Oil signals do not follow this shape.** `FAILURE_MODE_CONFIG["capstone"]["signals"]` lists a
> `technique` per signal, and oil (tribology) essay names (e.g. `Cromo`, `Hierro`, `Hollín`) appear
> as `signals` entries for some failure modes — which could suggest an equivalent
> `oil/.../signal_daily_status` table. **There is none.** The only oil table in the golden layer is
> `oil_meter_history` (below), which is wide, per sample, and covers six metals as running totals
> — not a per-signal daily alert/critical rate. Raw oil essay values plus derived 5-sample moving
> means / 30-day deltas / 90-day z-scores (`{Essay}_mm5`, `{Essay}_delta30`, `{Essay}_z90`) also
> show up per-unit in `analisis_inteligente.parquet` (below). So the v1.0 static `OIL_THRESHOLDS`
> table is **not confirmed redundant** — oil classification upstream now looks closer to a
> per-unit statistical baseline (`z90`) than to the old fixed Normal/Alerta/Crítico bands, which is
> itself a change worth confirming with the upstream team before touching `OIL_THRESHOLDS` — see
> [§9](#-migration-notes-v10--v20).

### `telemetry / operating_hours`

How many hours each truck operated each day, in total and split by operating state. It is the
persisted version of the `df_horas_operacion` computation that the notebook used to do in memory
over the whole telemetry history: the weekly run only reads one week of telemetry, so it needs the
previous weeks stored.

**Grain**: unit × day. A row exists only for days on which that truck has telemetry records.

**Path**: `data/telemetry/golden/{cliente}/{componente}/operating_hours/year=YYYY/week=WW/part-0.parquet`,
partitioned by the ISO week of `dia`. Available for `capstone` / `motor` only. At the time of
writing it holds 33,776 rows over 158 weeks, from `2023-W36` to `2026-W37`.

| Column | Type | Description |
|---|---|---|
| `Unit` | string | Truck, e.g. `CA-31` |
| `dia` | date | Day, in **Chile local time** |
| `h_op` | float | Hours with the engine turning (RPM > 0) |
| `h_ralenti` | float | Of those, hours with RPM below 780 |
| `h_sin_carga` | float | Hours with RPM ≥ 780 and load below 40% |
| `h_con_carga` | float | Hours with RPM ≥ 780 and load ≥ 40% |

**The date column is `dia`, not `Fecha`**, unlike every other table in this contract. Rename it
before joining on `Unit` + date.

**The three states add up to `h_op`**, except when load is missing in the telemetry: those hours
count toward `h_op` but toward no state. The 780 RPM and 40% load thresholds are the same ones
that define the operating states elsewhere in telemetry, and come from the client's
configuration. `h_op` counts RPM > 0 because that is the criterion validated against the
horómetros in the notebook.

**How it is computed**, from one week of minute-level telemetry, **before** engine-off rows are
dropped:

1. Timestamps are converted from UTC to Chile local time.
2. Each truck's records are sorted, and each record is assigned the time elapsed since the
   previous one.
3. A gap longer than three times the typical sampling interval is capped, so a long hole in the
   telemetry does not count as operation.
4. Each record's duration goes to `h_op` and to one of the three states, by RPM and load.
5. Durations are summed by truck and day.

**How it is written.** The weekly run, a history backfill script and the full bootstrap all use
the same computation, so they produce identical output. Each write replaces **only the partition
of its own week**: re-running a week leaves the same partition, with no duplicates. Records that
belong to a neighbouring week are dropped before writing, so that a fragment can never overwrite
the other week's partition.

**Missing data is not zero operation.** A day without telemetry has no row, and a week whose
telemetry file is empty has no partition. Today `2026-W38` to `2026-W41` are missing for that
reason; they fill in once the telemetry arrives. Do not read an absent row as a day the truck
was stopped, and note that `leer_ultimas_semanas(..., n=13)` skips missing weeks, so the window
can reach further back in time than 13 calendar weeks.

**Who uses it.** Each weekly run reads every **earlier** week of this table — never its own week
or later ones — plus the week it is processing, and feeds it into:

- **Horómetro cleaning.** When a horómetro repeats the same value twice, it checks whether the
  truck operated between those dates: if it did, the reading is stale and discarded; if not, the
  truck was stopped and the reading is valid.
- **The daily hours series.** The horómetro's advance between samples is spread over the days the
  truck actually operated, instead of evenly.
- **The age factor** applied to `ranking` (see [§3](#risk_scores)). Each hour is
  weighted by state — idle 0.3, unloaded 0.7, loaded 1.0 — to measure whether an engine worked
  harder or easier than the fleet, accumulated since its last engine change. The `k_norm`
  calibration also reads this table.

**Open point — Monday daylight-saving edge.** If the weekly telemetry files are cut in UTC, during
Chile's daylight-saving period the first hour of some Mondays would land in the previous week's
file and be dropped. That would be a few minutes per week; not confirmed, as it depends on how the
files are cut.

### `oil / oil_meter_history`

One row per unit per oil sample. At each sample it records the hours on the current oil charge,
the component's hours, the oil-change and component-change cycles, and a running total of six wear
metals.

**Grain**: unit × sample date — **not daily**. Each unit is sampled roughly every two weeks, and
different units are sampled on different days.

**Path**: `data/oil/golden/{cliente}/{componente}/oil_meter_history/year=YYYY/week=WW/part-0.parquet`,
partitioned by the ISO week of the sample date. Available for `capstone` / `motor` only.

| Column | Type | Description |
|---|---|---|
| `Unit` | string | Unit identifier |
| `Fecha` | date | Sample date |
| `oilMeter_raw` | float | Hours on the current oil charge, as reported by the lab |
| `oilMeter_filled` | float | Same, after cleaning — **read this one** |
| `oilMeter_flag` | string | How `oilMeter_filled` was obtained — see the flag table below |
| `es_cambio_aceite` | bool | `True` if the oil was changed at this sample — `oilMeter` drops back |
| `n_ciclos_aceite` | int | Oil-charge number for this unit; starts at 1, +1 on each oil change |
| `componentHours_raw` | float | Component hours as reported. **`0.0` is a missing-value placeholder, not a reading** |
| `componentHours_filled` | float | Component hours after cleaning and interpolation — **read this one**. Null when there is no reading to anchor on |
| `componentHours_flag` | string | How `componentHours_filled` was obtained — see the flag table below |
| `es_reset` | bool | `True` if a component change was detected at this sample |
| `ciclo_motor` | int | Component life number; starts at 1, +1 on each reset |
| `Hierro_acum_total`, `Cobre_acum_total`, `Plomo_acum_total`, `Cromo_acum_total`, `Aluminio_acum_total`, `Estaño_acum_total` | float | Running total of each wear metal over the current component life — see below |

The table also carries `ciclo_aceite`, which is **pending review**: do not rely on it until it is
documented here.

Every `_raw` / `_filled` / `_flag` group works the same way: `_raw` is kept for audit, `_filled`
is the usable value, `_flag` says how it was produced. **Always read `_filled`.**

**How the metals accumulate.** A lab result gives the concentration of each metal in the current
oil charge, and that concentration starts over at every oil change. `_acum_total` is the sum of
the last concentration of every **completed** oil charge in the current component life, **plus**
the concentration measured in the current charge. So it measures the wear generated over the whole
life of the component, and:

- At each oil change, the previous charge's last value is added to the base, so the total
  jumps up.
- Between two samples of the **same** oil charge, the total follows the current concentration, so
  it **can go down** if a later sample reads lower. In the example data, `Aluminio_acum_total`
  goes from 1.40 to 1.22 within the first charge.
- It **restarts** when the component changes (`ciclo_motor` increases).

**Flag values.** Both flag columns are closed sets; any other value is a contract violation.

| Value | `oilMeter_flag` | `componentHours_flag` | Meaning |
|---|:-:|:-:|---|
| `ok` | ✅ | ✅ | Raw value kept as-is |
| `sin_dato` | ✅ | ✅ | No raw value for this sample |
| `pico` | ✅ | ✅ | Raw value was an isolated spike and was corrected |
| `aplanado` | ✅ | ✅ | Raw value dropped without it being a real reset, and was flattened |
| `estancado` | ✅ | ✅ | Raw value stayed unchanged across consecutive samples |
| `congelado` | ✅ | | Raw value frozen over a long run of samples |
| `fuera_rango` | ✅ | | Raw value outside the plausible range |
| `reset_sin_confirmar` | ✅ | | Looks like an oil change, but `es_cambio_aceite` could not confirm it |
| `cero_relleno` | | ✅ | Raw value was `0.0` (missing placeholder) and was filled in |
| `valle` | | ✅ | Raw value was an isolated dip and was corrected |

The meaning of `ok`, `sin_dato` and `cero_relleno` is certain. The rest is inferred from the value
names and the cleaning steps; the authoritative rules live in the generating notebook — confirm
there before building logic that branches on a specific flag.

**Past partitions are not revised.** The table is exported one week at a time, and each partition
is written once. `componentHours_filled` is interpolated with the readings available at export
time, and cycles and `_acum_total` are computed over the history known then. A later correction
upstream — a late lab result, a re-cleaned reading — only reaches future weeks unless the history
is re-exported. Past weeks stay stable, but they reflect what was known when they were written.

**Not an oil equivalent of `signal_daily_status`.** It covers six metals only. The other oil
signals that `FAILURE_MODE_CONFIG` lists as evidence — `Hollín`, `Silicio`, `Sodio`, `Potasio`,
`Viscocidad`, `Oxidación`, `Combustible`, `Boro` — are not in this table.

### `predictive / analisis_inteligente.parquet` (frozen legacy input — schema now published live as `unit_failure_analisis`)

This section documents the schema of the original, frozen migration-era snapshot. As of the
`analisis_predictivo.ipynb` pipeline, the same shape is generated fresh every run and published as
`unit_failure_analisis` (see above) — no longer frozen, and no longer just a migration input.
Do not publish this wide, one-row-per-unit schema as `mode_failure_analisis`: that contract
requires one row for every flagged mode, not just the unit's worst one.

**Grain**: one row per unit — a snapshot, not partitioned by `year=`/`week=` like the five public
tables.

**Contents**: the legacy row carries per-unit scores and the previous worst-mode narrative:

| Column group | Examples | Description |
|---|---|---|
| Identifiers | `Unit`, `Fecha`, `year_week` | |
| Failure-mode scores | `abrasive_wear_risk`, ..., `ranking` | One column per failure mode, wide. The frozen snapshot has the 9 modes of its time; whether the live `unit_failure_analisis` for `capstone` carries the 2 modes added in v2.8 is *to confirm* |
| Raw oil essays | `Aluminio`, `Cobre`, `Hierro`, `Viscocidad`, ... | Latest sample values |
| Oil/mode derived stats | `{col}_mm5`, `{col}_delta30`, `{col}_z90` | 5-sample moving mean, 30-day delta, 90-day z-score, per failure mode and per oil essay |
| Status | `media_30d`, `peor_riesgo`, `peor_modo`, `estado`, `rolling_risk_90d` | Same shape as `unit_status_summary` |
| **Narrative (LLM-generated)** | `observaciones` (JSON list of `{severidad, texto}`), `diagnostico`, `causa_probable`, `acciones` (JSON list), `limitacion` | Free-text diagnosis, in Spanish |
| Provenance | `analisis_fuente` (`"llm"` or `"omitida"`), `analisis_tokens`, `analisis_error` | `"omitida"` rows (seen for `normal`-status units) have no narrative fields populated — the LLM pass appears to be skipped for low-risk units, presumably to save cost |

The legacy file remains unchanged by the migration notebook. Its per-unit scores supply the
`failure_mode` rows; the new output uses the contract schema and deterministic rules.

This legacy snapshot confirms that **narrative diagnosis content exists** for at least
`capstone`/`cda`, and that the **failure-mode set was 9** at the time it was frozen (see
[§5](#failure-mode--signal-catalog) for the current list, which has grown since).

---

## 📖 Reading Pattern

The five weekly tables (`unit_status_summary`, `risk_scores`, `signal_daily_status`,
`oil_meter_history`, `operating_hours`) share one reading pattern based on listing available `(year, week)` partitions and reading only the
requested ones — do not `pd.read_parquet` the whole dataset and filter in memory.

**Read from the local mirror** (`data/{tecnica}/golden/{cliente}/{componente}/{tabla}/`) — no S3
client is needed at read time, since the sync already happened:

```python
import re
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as pads

RAIZ = "data"
PARTICION = pads.partitioning(pa.schema([("year", pa.int32()), ("week", pa.int32())]), flavor="hive")

def ruta_tabla(tecnica, nombre, cliente, componente):
    return f"{RAIZ}/{tecnica}/golden/{cliente}/{componente}/{nombre}"

def semanas_disponibles(ruta):
    dset = pads.dataset(ruta, format="parquet", partitioning=PARTICION)
    return sorted({(int(y.group(1)), int(w.group(1)))
                   for r in dset.files
                   if (y := re.search(r"year=(\d+)", r)) and (w := re.search(r"week=(\d+)", r))})

def leer_ultimas_semanas(ruta, n=13):
    pares = semanas_disponibles(ruta)[-n:]
    return pd.read_parquet(ruta, filters=[[("year", "==", y), ("week", "==", w)] for y, w in pares])
```

The same functions work unmodified against the S3 origin (pass an `s3fs.S3FileSystem()` as
`filesystem=` to `pads.dataset`/`pd.read_parquet` and point `RAIZ` at the bucket path) — the
partition layout is identical, only the filesystem changes. This repo has no reason to do that
today since the local mirror is kept in sync manually.

`leer_ultimas_semanas` returns a concatenated DataFrame including the `year`/`week` columns parsed
from the path. `n=13` weeks ≈ 91 days, i.e. "last 13 available weeks", not "last 90 calendar
days" — if a week is missing (ingestion gap, or a stale local sync), the actual calendar span
covered can be wider. Filter by `Fecha` afterward if exact calendar windows matter. For
`oil_meter_history`, which is per sample rather than daily, 13 weeks is about 6–7 samples per
unit.

`cumulative_risk_curve` does **not** use this pattern — see [§7](#cumulative-risk-curve).

`Fecha` comes back as a Python `date` object, not `datetime64` — call `pd.to_datetime` before any
date arithmetic.

---

## 🧩 Failure Mode → Signal Catalog

Same role as v1.0's `FAILURE_MODE_CONFIG`, still a Python dict imported by the dashboard, **not**
data stored in parquet — but its shape has changed (see [§9](#-migration-notes-v10--v20)): it is
now keyed by client, then by component, and each signal's own catalog entry carries its source
`technique` and display metadata.

```python
FAILURE_MODE_CONFIG["capstone"]["components"]["motor"]["blowby_risk"]
# {'label': 'Blow-by / Desgaste de Anillos',
#  'signals': ['Cromo', 'Hierro', 'Hollín', 'crankcase_pressure_inh2o', 'oil_level_pct']}

FAILURE_MODE_CONFIG["capstone"]["signals"]["crankcase_pressure_inh2o"]
# {'technique': 'telemetry', 'label': 'Presión Cárter', 'unit': 'inH2O'}
```

To render a mode's evidence: filter `signals` for the selected mode, then for each signal look up
its `technique` in the `signals` catalog to know which `signal_daily_status` table to read from.

**The mode set is per client.** Nine modes are shared by `capstone` and `cda`, confirmed directly
from the local `risk_scores` and `unit_status_summary` data; `capstone` has two more, added in
contract v2.8:

| Client | Modes | Count |
|---|---|:-:|
| `capstone` | the 9 shared + `early_oil_change_risk`, `accumulated_wear_risk` | 11 |
| `cda` | the 9 shared | 9 |

The 9 shared modes:

```
abrasive_wear_risk, bearing_wear_risk, blowby_risk, combustion_risk,
coolant_contamination_risk, lubrication_failure_risk, oil_degradation_risk,
thermal_imbalance_risk, turbocharger_risk
```

The 7 already known from v1.0 carry over unchanged; the **2 new modes** are `turbocharger_risk`
("Turbocompresor") and `coolant_contamination_risk` ("Contaminación por Refrigerante") — labels
confirmed from the generated narrative text in `analisis_inteligente.parquet` (e.g. *"Desbalance
Térmico: riesgo en ascenso"*, *"El motor muestra Contaminación por Refrigerante en banda
Crítica..."*). Still confirm the exact label strings and oil/telemetry variable mapping against
`FAILURE_MODE_CONFIG["capstone"]` in code before wiring these into the dashboard — the values here
are inferred from data, not read from the config dict itself.

The **2 modes added in v2.8** are `early_oil_change_risk` and `accumulated_wear_risk`, for
`capstone` only. Both follow
the `_risk` naming convention, so every table that selects modes by that suffix picks them up with
no code change: they appear as rows in `risk_scores`, inside `modos_ordenados`, and can become
`peor_modo` or count toward `modes_over_threshold_count` in `unit_status_summary`.

| Mode | Label | Clients | Evidence signals | Feeds `ranking` |
|---|---|---|---|---|
| `early_oil_change_risk` | *to confirm* | `capstone` | *to confirm* | *to confirm* |
| `accumulated_wear_risk` | *to confirm* | `capstone` | *to confirm* | *to confirm* |

Until those are filled in, two things are known to be missing downstream:

- **`FAILURE_MODE_CONFIG["capstone"]`** has no entry for either mode, so the dashboard's mode
  selector would offer them with no signals to plot.

Because the set differs by client, the dashboard must build its mode list from the data of the
client being shown, not from a single shared list.
- **`mode_failure_analisis`** needs an entry for each mode in `reglas_capstone_motor.json`.
  Without one, a flagged row whose LLM call fails or omits the mode has no rule to fall back on,
  and ends up as `analysis_status = error` with generic text.

---

## 🚦 Status & Classification Rules

### `unit_status_summary.estado` (fleet cards)

Each unit-day is placed on two axes — the day's `ranking` and its 30-day mean `media_30d` — and
each axis is compared against a fixed threshold. The combination gives four quadrants, three
statuses:

| Status | `media_30d ≥ UMBRAL_30D` | `ranking ≥ UMBRAL_DIA` | Reading |
|---|:-:|:-:|---|
| `anormal` | ✅ | ✅ | High today **and** high over the month: sustained, current risk |
| `alerta` | ✅ | ❌ | High over the month, low today |
| `alerta` | ❌ | ✅ | A spike today, not yet sustained |
| `normal` | ❌ | ❌ | Low on both |

**How the thresholds are set.** Each one is the **80th percentile** of its variable over the
client's full history — every unit, every day — at calibration time: `UMBRAL_30D` from
`media_30d`, `UMBRAL_DIA` from `ranking`. "High" therefore means "within the worst 20% of what this
fleet has historically recorded".

That is **not** "the worst 20% of the fleet this week". The thresholds are fixed values, so the
share of units in each status changes freely from week to week: in a bad week more than 20% of the
fleet can be `anormal`, in a good one nobody.

**The thresholds are frozen.** They are calibrated once and hardcoded in the generating notebook,
not recomputed on every run. That keeps a past week's `estado` from changing as new data arrives.
One consequence for backfilled history: snapshots older than the calibration date are classified
with thresholds computed from a history that includes later data. Every other column in those
snapshots uses only data up to its cutoff.

**The thresholds are per client.** Each client is calibrated on its own history, so the same
`ranking` can be `alerta` for one client and `normal` for another.

| Client | Component | `UMBRAL_30D` | `UMBRAL_DIA` | Calibrated on |
|---|---|---|---|---|
| `capstone` | `motor` | *to fill* | *to fill* | *to fill* |
| `cda` | `motor` | *to fill* | *to fill* | *to fill* |

**No single mode drives `estado`.** The rule looks only at `ranking` and `media_30d`. A unit with
one mode at 95 and a moderate `ranking` can be `normal` — use `peor_modo` / `peor_valor` /
`modos_ordenados` to surface that case. This is a deliberate difference from the previous rule
(below).

**`estado_previo`** applies the same rule, with the same thresholds, to the reading nearest to
7 days earlier (±3 days). If there is no reading in that window it is null, and so is
`cambio_estado`.

**Not the v1.0 rule.** Until contract v2.7, `estado` used `media_30d ≥ 60` or any mode `≥ 80` for
`anormal`, and `media_30d ≥ 30` or any mode `≥ 50` for `alerta` — the same 30/50/60/80 thresholds
as the v1.0 dashboard. Statuses computed with the old rule are **not comparable** with the current
ones. The dashboard must read `estado` as delivered and not recompute it with either rule (see
[§9](#-migration-notes-v10--v20)).

Two other thresholds exist and are unrelated to `estado`: the fixed 35 behind
`modes_over_threshold_count`, and each client's `FLAG_THRESHOLD` in `mode_failure_analisis`.

### `cumulative_risk_curve.estado` (curve zones)

Uses Title Case (`Normal` / `Alerta` / `Anormal`) and compares the accumulated curve against the
fleet reference band, **not** the `ranking` × `media_30d` rule above. **The two `estado` fields can
disagree for the same unit** — this mirrors a known v1.0 behavior (the classic hero status vs. the
accumulated-curve zone status could already disagree; see `project_overview.md` §"Curva Acumulada
de Riesgo"). Label them distinctly in any UI that shows both.

---

## 📈 Cumulative Risk Curve

`cumulative_risk_curve` requires its own reader — it does **not** use
[`leer_ultimas_semanas`](#reading-pattern), for two reasons: each partition already contains the
**full history** (not just that week), and the parquet file carries schema-level metadata
(`config`, `banda`, and a third key `tendencia`) that `pd.read_parquet` silently discards.

```python
import json

def leer_curva(ruta, semana=None):
    dset = pads.dataset(ruta, format="parquet", partitioning=PARTICION)
    pares = sorted({(int(y.group(1)), int(w.group(1))) for r in dset.files
                    if (y := re.search(r"year=(\d+)", r)) and (w := re.search(r"week=(\d+)", r))})
    y, w = semana or pares[-1]
    tabla = dset.to_table(filter=(pads.field("year") == y) & (pads.field("week") == w))
    df = tabla.to_pandas()
    for k, v in (tabla.schema.metadata or {}).items():
        if (nombre := k.decode()) in ("config", "banda", "tendencia"):
            df.attrs[nombre] = json.loads(v.decode())
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    return df
```

(Same note as [§4](#reading-pattern): this reads the local mirror; pass `filesystem=` for S3.)

> ⚠️ **Do not toggle `CALCULAR_TENDENCIA` without updating this reader.** With the trend off, the
> trend columns are written as numeric nulls; with it on, `tendencia`, `tendencia_final` and
> `peor_tendencia` are written as text. `pads.dataset` infers one schema across all partitions, so
> once both kinds exist, reading the other kind fails (`Failed to parse string: 'Alerta' as a
> scalar of type double` — reproduced locally). Either keep the flag fixed, or read the selected
> partition's file on its own instead of through the unified dataset schema.

If `df.attrs["config"]`/`["banda"]` is lost (e.g. by reading with plain `pd.read_parquet`), the
plotting helper (`curva_figura.plot_curva_acumulada`, shipped as a separate module) does **not**
raise — it silently falls back to default `K_SIGMA`/`K_ALERTA` parameters and draws zone
boundaries that don't match the classification that was actually used. Always read this table with
`leer_curva`. With the current defaults of `curva_acumulada.py`, `config` reads:

```json
{"PESO_HORAS": true, "CORREDOR_INDIVIDUAL": true, "LEAVE_ONE_OUT": false,
 "APLICAR_OFFSET": true, "REFERENCIA_SOLO_VIGENTES": false, "CALCULAR_TENDENCIA": false,
 "USAR_HORAS_CRUDAS": true, "K_SIGMA": 2.0, "K_ALERTA": 1.0}
```

Always trust the `config` of the partition you read over this example. Note that `config` does
**not** record every parameter that shapes the result — notably `CENTRO_BANDA` (`"mediana"`),
`MIN_TRAMO_HORAS` (1,500) and the hours-cleaning limits (`MAX_GAP_DAYS`, `TAIL_RATE_CAP`, ...).
Those are only visible in the module that generated the partition.

### Columns

The upstream reading guide (`new_predictive_data_contracts.md`) documents a 13-column subset; the
local parquet (`data/predictive/golden/capstone/motor/cumulative_risk_curve/...`) actually carries
**30 columns**. The full set, confirmed by direct inspection:

| Column | Type | Description |
|---|---|---|
| `Unit`, `Fecha` | string, date | Unit and day |
| `ciclo` | int | Component lifecycle number; increments on each component change |
| `curva` | string | Key for one full lifecycle, e.g. `"CA-30 · ciclo 1"` — the separator is a middle dot (`·`), not a hyphen |
| `componentHours_filled` | float | Component hours that day — the chart's X axis. Rebuilt from the raw lab readings (`componentHours`) with this module's own cleaning when `USAR_HORAS_CRUDAS = true`, not taken from the source's pre-filled column |
| `ranking` | float | That day's non-cumulative risk |
| `ranking_acumulado` | float | Cumulative risk within the unit/cycle; starts at 0. With `PESO_HORAS = true` each day adds `ranking × hours worked that day` (Δ hours, capped at 20 h/day), so a day with no hour advance adds nothing. Units: ranking × hours |
| `offset_curva` | float | Vertical offset so the curve starts at the fleet mean |
| `ranking_acumulado_ajustado` | float | **The column that is plotted and classified against** |
| `banda_media`, `banda_umbral` | float | Fleet center and threshold at that hour value. Despite the name, `banda_media` is the fleet **median** when `CENTRO_BANDA = "mediana"` (current default) |
| `banda_inferior` | float | *Undocumented upstream.* Lower band bound at that hour value (mirrors `banda_umbral` on the low side) |
| `banda_extrapolada` | bool | `True` where the fleet has too little support at that hour value and the band is extrapolated. These points are still classified |
| `tramo_flota` | float | Accumulated risk the fleet would be expected to reach over this curve's own span of hours — the reference `z` compares against |
| `sigma_curva` | float | Dispersion that scales `z` for this curve's span of hours |
| `umbral_curva` | float | *Undocumented upstream.* Per-curve threshold, distinct from `banda_umbral` — relationship not confirmed |
| `z` | float | `(ranking_acumulado − tramo_flota) / sigma_curva`: distance from the fleet expectation, in sigmas, compared against `K_SIGMA` / `K_ALERTA` from `config` |
| `evaluable` | bool | `True` once the curve has covered at least 1,500 h (`MIN_TRAMO_HORAS`). Before that, `estado` is forced to `Normal` — see below |
| `estado` | string | `Normal` / `Alerta` / `Anormal`. **Never null**: points outside the fleet's support are classified anyway and flagged in `banda_extrapolada` |
| `nivel_medio` | float | `ranking_acumulado` divided by the hours covered by the curve. With `PESO_HORAS = true` this is the average `ranking` per hour worked, on the same 0–100 scale as `ranking` |
| `horas_por_dia` | float | Average component-hours accrual rate over the whole curve — **constant per curve**, not a daily value |
| `delta_tendencia`, `tendencia` | float, string | *Undocumented upstream.* Trend delta and label; mostly null in the observed sample (`CALCULAR_TENDENCIA: false` in `config` for this partition) |
| `dias_desde_tendencia` | float | *Undocumented upstream.* Days since the trend was last computed |
| `es_vigente` | bool | `True` if this is the unit's current (active) cycle |
| `zona_final` | string | Status of the vigent curve's last point, repeated across all its rows; null for historical cycles |
| `peor_zona` | string | *Undocumented upstream.* Worst zone reached across the vigent cycle so far |
| `tendencia_final`, `peor_tendencia` | string | *Undocumented upstream.* Trend-equivalents of `zona_final`/`peor_zona` |
| `componente` | string | Observed locally as `"MOTOR DIESEL"`, not the lowercase `"motor"` the reading guide shows — **do not hardcode the lowercase form when filtering on this column** |

`estado` is never null, but it can be **unevaluated**: while a curve has covered fewer than
1,500 h, its points read `Normal` with `evaluable = False`, which is not the same as a genuinely
normal point. Check `evaluable` before treating `Normal` as healthy. `zona_final` is null on historical
cycles (`es_vigente = False`) only. Columns marked *undocumented
upstream* are present in the data but not explained in `new_predictive_data_contracts.md`; the
descriptions above are best-effort inferences from column names and observed values — confirm with
the upstream team before building logic that depends on their exact semantics.

The X axis is component **hours**, not calendar time — wear tracks component usage, not the
calendar.

**Partitions written under different settings are not comparable.** `PESO_HORAS`,
`CENTRO_BANDA` and `USAR_HORAS_CRUDAS` each change the curve's scale or shape. Because every
partition holds the full history recomputed at that run, the latest partition is internally
consistent — but reading an older week with `leer_curva(..., semana=...)` returns it on the
settings of that week. Compare `config` before putting two partitions side by side.

**Implication for this repo**: `componentHours_filled` now arrives already joined upstream. In
v1.0, the dashboard built this same curve itself
(`dashboard/components/accumulated_curve.py::build_accumulated_data`) by merging `ranking` from the
component CSV with `cleaned_component_hours.parquet` from the Oil module and computing
`ranking_acumulado` client-side. If this table is adopted as-is, most of that module's logic
(`fill_hours_progressive`, cycle-break detection, `build_reference_band`, `classify_curves`)
becomes redundant — see [§9](#-migration-notes-v10--v20).

---

## ✅ Data Quality Rules

- ✅ `Fecha` is present and comparable across tables for a given unit/day, but arrives as a `date`
  object per parquet, not `datetime64` — cast with `pd.to_datetime` before date arithmetic.
- ✅ `Unit` is present in every `unit_status_summary` snapshot from the first week it has data
  onward, even after it stops reporting (surfaced instead via `dias_sin_datos` and a stale
  `Fecha`).
- ✅ A past week's `unit_status_summary` does not change between runs: snapshots use only data up
  to their cutoff, and the `estado` thresholds are frozen.
- ✅ `risk_value` (in `risk_scores`) and `pct_time_alert`/`pct_time_critical` (in
  `signal_daily_status`) are numeric in `[0, 100]` when present.
- ✅ **Absence of a row is the "no data" signal** in both long-format tables — do not backfill or
  interpret a missing unit/day/mode (or unit/day/signal) row as zero.
- ✅ `oil_meter_history` has at most one row per `Unit` + `Fecha` (one sample per unit per day).
- ✅ `operating_hours` has at most one row per `Unit` + `dia`, and its date column is `dia`, not
  `Fecha`.
- ✅ In `operating_hours`, `h_ralenti + h_sin_carga + h_con_carga ≤ h_op`; the difference is hours
  with missing load. A sum **above** `h_op` is a data problem.
- ✅ In `oil_meter_history`, read the `_filled` columns, not `_raw`. `componentHours_raw == 0.0`
  means missing, not zero hours.
- ✅ `oilMeter_flag` and `componentHours_flag` only take the values listed in
  [§3](#oil--oil_meter_history); treat anything else as a contract violation, not as `ok`.
- ⚠️ Do not assume `{Metal}_acum_total` is monotonic: it can decrease between two samples of the
  same oil charge (see [§3](#oil--oil_meter_history)). A decrease is not by itself a data problem.
- ✅ `cumulative_risk_curve` must be read via `leer_curva`, not `pd.read_parquet`, to retain
  `config`/`banda` metadata — otherwise zone boundaries silently drift from what was actually used
  to classify the data.
- ✅ `mode_failure_analisis` (formerly `failure_mode_diagnosis`) is the published weekly contract;
  `unit_failure_analisis` (formerly `analisis_inteligente`, no longer frozen) is a distinct,
  wide, one-row-per-unit companion — not a row-level replacement for either direction.
- ✅ Since v1.2, `mode_failure_analisis` has one row per unit × **every** scored mode, not just
  flagged ones — do not treat a unit's absence from a prior week's row count as "nothing to show";
  a row with `analysis_status = healthy_default` is still a real row, just not AI-analyzed.
- ⚠️ `componente` in `cumulative_risk_curve` is observed as `"MOTOR DIESEL"`, not the lowercase
  `"motor"` used elsewhere in the path/config (`{componente}` in the S3/local path, or
  `FAILURE_MODE_CONFIG[...]["components"]["motor"]`) — don't assume the casing/format is
  consistent across tables.

---

## 🔀 Migration Notes (v1.0 → v2.0)

Summary of what changed and what it implies for this repo. **None of these are implemented yet** —
this repo's Predictive tabs, callbacks, and config still read the v1.0 local-CSV shape.

| Area | v1.0 | v2.0 | Implication |
|---|---|---|---|
| Storage | Local per-client CSV, `data/predictive/golden/{client}/{component}.csv` | Partitioned parquet, mirrored locally at `data/{tecnica}/golden/{cliente}/{componente}/{tabla}/year=/week=/`, synced manually from S3 | Loaders (`_load_component_data` in both tabs) need a rewrite around `pyarrow.dataset` (local `data/` root — no live S3 client needed) plus partition-listing/caching, and a way to trigger/detect the manual sync running stale — not a `pd.read_csv` swap |
| Shape | Wide: ~250 columns, one per operational-mode × signal × rate-type, plus one column per failure mode | Long: `risk_scores` and `signal_daily_status` are unit × day × (mode\|signal) rows | Code that pattern-matches column name substrings (`create_telemetry_signal_chart`, `_analyze_telemetry_observations`) must switch to filtering rows instead |
| Failure modes (Motor) | 7, hardcoded in `predictive_config.py::FAILURE_MODE_CONFIG["motor"]` | 11 — the 9 confirmed in v2.0 (`abrasive_wear_risk`, `bearing_wear_risk`, `blowby_risk`, `combustion_risk`, `coolant_contamination_risk`, `lubrication_failure_risk`, `oil_degradation_risk`, `thermal_imbalance_risk`, `turbocharger_risk`), shared by both clients, plus `early_oil_change_risk` and `accumulated_wear_risk` for `capstone` only (v2.8): 11 for `capstone`, 9 for `cda` | `FAILURE_MODE_CONFIG` needs the 4 modes that v1.0 did not have, with label and signal mapping confirmed. Any dashboard code that assumes a fixed number of modes, or the same set for every client (table rows, driver bars, `risk_scores` rows per unit-day) must read the set from the data instead |
| Rolling averages | Computed client-side (`30d`/`60d`/`90d` per-`Unit` rolling means, `min_periods=1`) | `media_30d` precomputed upstream in `unit_status_summary`; no `60d`/`90d` equivalent observed | Client-side 30d rolling-window computation becomes redundant once the dashboard reads `unit_status_summary.media_30d` directly; `60d`/`90d` rolling logic likely still needs to stay client-side (or be requested from upstream) unless confirmed otherwise |
| Status classification | Applied client-side on `avg_ranking_30d`/`max_fm_30d`, duplicated in 4 call sites (`tab_predictive_overview.py`, `tab_predictive_evidence.py`, twice in `predictive_callbacks.py`) | Precomputed upstream as `unit_status_summary.estado` with a **different rule**: `ranking` vs. `media_30d`, each against a frozen per-client 80th-percentile threshold (see [§6](#status--classification-rules)). The 30/50/60/80 rule was dropped in contract v2.8 | The dashboard must read `estado` as delivered and remove all 4 client-side call sites — recomputing with the v1.0 thresholds would now **disagree** with the published status, not just duplicate it. Expect different units in each card than v1.0 showed. The accumulated curve's separate `estado`/`zona_final` classification stays a second, independently-computed status (see [§6](#cumulative_risk_curveestado-curve-zones)) — label them distinctly |
| Cumulative curve | Built entirely client-side in `accumulated_curve.py` (hours-fill, cycle detection, reference band, zone classification), joined against Oil's `cleaned_component_hours.parquet` | Delivered precomputed as `cumulative_risk_curve`, including `componentHours_filled`, `zona_final`, and ~17 more columns not documented upstream (see [§7](#columns)) | Most of `accumulated_curve.py` becomes redundant if this table is adopted as-is; the `K_SIGMA=2.0`/`K_ALERTA=1.0` parameters observed locally are close to the old `EXCLUDE_FROM_REFERENCE`/`K_SIGMA=2` constants but now travel as `df.attrs["config"]`/`["banda"]`/`["tendencia"]` parquet metadata instead of hardcoded constants — `z`, `evaluable`, `tramo_flota`, `sigma_curva`, `banda_extrapolada`, `nivel_medio` and `horas_por_dia` are now documented in [§7](#columns); the rest marked *undocumented upstream* (`umbral_curva`, `peor_zona`, `banda_inferior`, the trend columns) should be clarified before being relied on |
| Oil variables & thresholds | Separate wide columns per essay (`Hierro`, `Cobre`, ...) plus a static, hardcoded `OIL_THRESHOLDS` table in `predictive_config.py` | No `oil`-technique equivalent of `signal_daily_status`. The only oil golden table is `oil_meter_history` (`capstone` only): six metals as running totals per component life, per sample — not per-essay alert rates. Raw essay values plus `_mm5`/`_delta30`/`_z90` derived stats appear per-unit in `analisis_inteligente.parquet` | `OIL_THRESHOLDS` is **not confirmed redundant** — the upstream classification signal looks more like a per-unit `z90` baseline than the old fixed Normal/Alerta/Crítico bands; treat this as a genuine behavior change to confirm with upstream, not just a storage-format change |
| Component-hours cross-module dependency | Predictive read Oil's `data/oil/golden/{client}/cleaned_component_hours.parquet` directly for horómetro figures on priority cards/unit banner | Not present in `unit_status_summary`/`risk_scores`. Two golden tables carry it, both `capstone` only: `cumulative_risk_curve.componentHours_filled` (**daily**, interpolated for the curve) and `oil_meter_history.componentHours_filled` (**per sample**, as cleaned from the lab readings) | For `capstone`, the horómetro can come from either table instead of the cross-module join — pick one and use it consistently: the daily curve value is interpolated between samples, and the curve rebuilds hours from the raw readings with its own cleaning, so the two can differ. For `cda` the standalone Oil-module join is still required |
| Clients/components observed | `CDA`: `motor`, `transmision` (CSV) | New parquet layout confirmed for `capstone/motor` and `cda/motor` (history back to `year=2021` for `cda`); `transmision` not migrated for either client; `cumulative_risk_curve` only observed for `capstone` | Do not assume `transmision` is available under the new layout for any client, and don't assume `cumulative_risk_curve` exists for `cda` — gate per client **and** per table, not just per client, before enabling in `predictive_allowed_clients` |
| `failure_mode_diagnosis` / `analisis_inteligente` | Frozen one-diagnosis-per-unit `analisis_inteligente.parquet` | Published one-row-per-unit-per-flagged-mode contract (v1.1), threshold 35, with `diagnostico`, `probable_cause`, JSON-string `recommended_actions`, `limitation`, and `analysis_status`, renamed `mode_failure_analisis`; plus its unfrozen wide-format companion `unit_failure_analisis` (formerly `analisis_inteligente`), generated and published alongside it every run | `analisis_predictivo.ipynb` generates both for `capstone` and `cda` via an LLM call per unit, falling back to static rules (`reglas_<cliente>_motor.json`) per mode when the call fails; the dashboard migration remains a separate task |

**Net effect**: v2.0 removes most of the client-side computation this module currently does
(rolling averages, status classification, curve construction) by shifting it upstream, and swaps
the wide/CSV shape for a long/parquet one. Adopting it is a loader + config rewrite, not a
column-mapping patch — treat it as a separate, scoped migration task rather than a drop-in change
to the existing CSV readers.

---

## 📝 Change Log

### Version 2.11 (October 17, 2026)
- **Added `telemetry / operating_hours`** (`capstone` / `motor` only): hours each truck operated
  each day, total (`h_op`) and by state (`h_ralenti`, `h_sin_carga`, `h_con_carga`). Documented
  how it is computed from minute-level telemetry, that each write replaces only its own week, that
  missing days and weeks mean missing telemetry rather than zero operation, and that its date
  column is `dia` in Chile local time. It feeds the horómetro cleaning, the daily hours series and
  the age factor applied to `ranking`.

### Version 2.10 (October 17, 2026)
- Updated §7 to the current `curva_acumulada.py`:
  - **`PESO_HORAS` is now `true`**: `ranking_acumulado` adds `ranking × hours worked` per day
    instead of `ranking` per day. Days with no hour advance add nothing, and `nivel_medio` is on
    the 0–100 scale of `ranking`. The accumulated values change scale.
  - **`banda_media` is the fleet median** (`CENTRO_BANDA = "mediana"`), not the mean, despite its
    name.
  - **`componentHours_filled` is rebuilt from the raw lab readings** (`USAR_HORAS_CRUDAS = true`)
    instead of the source's pre-filled column.
  - The `config` example now reflects the current defaults, including `CORREDOR_INDIVIDUAL: true`,
    `LEAVE_ONE_OUT: false` and the new `USAR_HORAS_CRUDAS` key, and notes which parameters
    `config` does not record.
- Added a note that partitions generated under different settings are not comparable.
- Removed the count of unevaluated cycles, which came from a partition generated before these
  changes.

### Version 2.9 (October 16, 2026)
- **Restored `cumulative_risk_curve`**, removed in 2.8, in every place it had before: the table
  listing, *Auto-Discovery*, the note in *Reading Pattern*, its curve-zone `estado` in §6, the full
  §7 with `leer_curva`, its two data-quality rules, and its migration rows. The text comes from
  v2.7, with these corrections verified against the `capstone` partition and
  `curva_acumulada.py`:
  - `curva` uses a middle dot: `"CA-30 · ciclo 1"`, not `"CA-30 - ciclo 1"`.
  - `estado` is **never null** — points outside the fleet's support are classified and flagged in
    `banda_extrapolada`. Replaced the "two different nulls" note: the real pitfall is unevaluated
    points (`evaluable = False`) reading `Normal`.
  - Documented `z`, `evaluable`, `tramo_flota`, `sigma_curva`, `banda_extrapolada`, `nivel_medio`
    and `horas_por_dia`, previously marked as undocumented.
  - Added a warning that toggling `CALCULAR_TENDENCIA` changes the type of the trend columns and
    breaks `leer_curva` across partitions.
- §6 curve-zones note now contrasts against the current `ranking` × `media_30d` rule instead of
  the old 30/50/60/80 rule.
- Component-hours migration row now lists both `capstone` sources: the daily
  `cumulative_risk_curve.componentHours_filled` and the per-sample
  `oil_meter_history.componentHours_filled`.
- Documented `risk_scores.risk_value` for failure modes as the **weighted** value that enters the
  `ranking` (`100 × soft_saturate(raw, scale) × weight / max_weight`), so a day's `ranking` can be
  reproduced from that unit-day's mode values alone.
- Renumbered sections back to 1–10 (Data Quality §8, Migration Notes §9, Change Log §10).

### Version 2.8 (October 2, 2026)
- **Removed `cumulative_risk_curve`** from the golden layer and from this contract: the table, its
  dedicated `leer_curva` reader, its column reference, its `estado` zones, and every
  per-client/per-table note that depended on it. The curve stays a client-side computation
  (`accumulated_curve.py`).
- **Replaced the `unit_status_summary.estado` rule.** The previous rule (`media_30d ≥ 60` or any
  mode `≥ 80` → `anormal`; `media_30d ≥ 30` or any mode `≥ 50` → `alerta`) is gone. `estado` now
  crosses the day's `ranking` with `media_30d`, each against the client's 80th percentile over its
  full history: high on both → `anormal`, high on one → `alerta`, high on neither → `normal`.
  Thresholds are frozen per client. Individual mode scores no longer feed `estado`. Statuses from
  before and after this change are not comparable.
- **Backfilled `unit_status_summary` history**: every past week with data now has its own
  snapshot, computed only from data up to that week's cutoff (Sunday, or the last available date
  for the current week). Documented the partition semantics and how to read current status
  (`n=1`) vs. weekly history (`n>1`).
- Clarified `estado_previo` / `delta_ranking` (reading nearest to 7 days earlier, ±3 days) and
  `dias_sin_datos` (relative to the latest date in the same snapshot).
- **Added `oil / oil_meter_history`** (`capstone` / `motor` only): one row per unit per oil sample
  with oil-charge hours, component hours, oil and component cycles, and the running total of six
  wear metals (`_acum_total`: completed oil charges plus the current charge's concentration,
  restarted on each component change — not monotonic within a charge). Documented the `_raw` / `_filled` / `_flag` convention and the closed sets of flag
  values. `ciclo_aceite` is present in the data but left undocumented pending review. Exported one
  week at a time: past partitions are not revised.
- **Added 2 failure modes for `capstone` only**: `early_oil_change_risk` and
  `accumulated_wear_risk`. Motor now has 11 modes for `capstone` and stays at 9 for `cda`, so the
  mode set is documented per client. Label, evidence signals and whether they feed `ranking` are
  pending.
  Replaced every hardcoded count ("9 modes", "10 rows per unit per day") with wording that does
  not depend on the number of modes, and noted the two pieces still missing downstream: their
  `FAILURE_MODE_CONFIG` entries and their `reglas_<cliente>_motor.json` fallback rules.
- Corrected the note under `signal_daily_status` that said no oil table exists in the golden
  layer, and updated the component-hours migration row: for `capstone`, horómetro figures can now
  come from `oil_meter_history` instead of the cross-module join.
- Fixed a broken `[§7](#columns)` link in the `mode_failure_analisis` section, which pointed to the
  removed curve columns instead of `unit_status_summary`. Renumbered sections 8–10 to 7–9.

### Version 2.7 (September 23, 2026)
- Bumped `mode_failure_analisis` to contract v1.3: `FLAG_THRESHOLD` (the score that decides
  whether a mode gets real AI/rules analysis vs. the `healthy_default` message) is now per
  client — the upper bound of that client's own `escala` "Saludable" band (Capstone: 30, CDA:
  35, unchanged) — instead of a single fixed 35 for both. This closes the v2.6 gap: `criticidad`
  and the flagging decision can no longer disagree, for Capstone or any future client, since both
  read the same per-client `escala`.
- For Capstone specifically, this is a real behavior change: modes scored 30–35 (previously
  `healthy_default`) are now flagged and go through the LLM/rules pipeline like any other flagged
  mode. CDA is unaffected (its `escala` boundary was already 35).
- Clarified that `FLAG_THRESHOLD` is intentionally decoupled from `modes_over_threshold_count`
  (`unit_status_summary`, computed upstream with a fixed 35 for both clients): the notebook still
  validates its parsing of `modos_ordenados` against that fixed 35 as a data-integrity check, but
  that number no longer has to equal `FLAG_THRESHOLD` — they now legitimately differ for Capstone.

### Version 2.6 (September 23, 2026)
- Corrected `criticidad` (`mode_failure_analisis`, v1.2, added in v2.5): v2.5 computed it from a
  scale uniform across both clients (0/35/55/75/100). It now uses each client's own `escala` from
  `reglas_<cliente>_motor.json` instead — CDA 0/35/55/75/100 (unchanged in practice), Capstone
  0/30/50/80/100 — the same scale already used for `RIESGO_ALERTA`/`RIESGO_CRITICO` in
  Observaciones and referenced by that client's own prompts.
- This reopens a gap the uniform scale had closed: the flagging threshold (`FLAG_THRESHOLD = 35`,
  still fixed and shared by both clients) does not align with Capstone's `escala` (Saludable ends
  at 30). A Capstone mode scored 30–35 now gets `criticidad = "Monitoreo"` together with
  `analysis_status = "healthy_default"` — flagged as past-Saludable by its own criticidad label,
  but not actually analyzed. CDA is unaffected (its `escala` boundary already sits at 35). Left
  as-is for now; making the flagging threshold per-client would close it but was not part of this
  change.

### Version 2.5 (September 23, 2026)
- Bumped `mode_failure_analisis` to contract v1.2 and changed its grain: the table now has one row
  per unit × **every** scored failure mode, not only flagged ones (>= 35). Previously a unit with
  no flagged mode had zero rows in the table; now every unit gets a row per mode it has a score
  for, whether or not it is flagged.
- Added the `criticidad` column: `Saludable` (<35) / `Monitoreo` (35–55) / `Prioridad alta`
  (55–75) / `Critico` (≥75). This scale is uniform across both clients and deliberately does
  **not** come from each client's own `escala` in `reglas_<cliente>_motor.json` — Capstone's is
  30/50/80, not 35/55/75 — because `criticidad` needs to line up exactly with the existing 35
  flagging threshold, so a healthy-default row is always `Saludable` and never anything else.
- Added `analysis_status = healthy_default`: for modes scored below 35, the row gets a fixed,
  client-agnostic message instead of an LLM/rules call — `diagnostico`: "El equipo no presenta
  indicios de este modo de fallo.", `probable_cause`: "El equipo se encuentra dentro de los
  parametros normales.", `recommended_actions`: `["Se recomienda seguir monitoreando el
  equipo."]`. This adds no LLM cost: the model is still called only for flagged modes, exactly as
  before.

### Version 2.4 (September 22, 2026)
- Corrected `unit_failure_analisis`'s S3 path: v2.3 said it stayed at the old flat
  `predictive/golden/{cliente}/unit_failure_analisis.parquet` object (overwritten every run). It
  is now partitioned like the rest of the golden layer, matching `mode_failure_analisis`:
  `MultiTechnique Alerts/predictive/golden/{cliente}/motor/unit_failure_analisis/year=YYYY/week=WW/unit_failure_analisis.parquet`,
  published via the same staged-`_runs/{run_id}`-then-`copy_object` mechanism (size + sha256
  validated before promotion). Local storage is unaffected — still a flat file under `salidas/`.
- Changed `mode_failure_analisis`'s leaf filename from `part-0.parquet` to
  `mode_failure_analisis.parquet`, for consistency with `unit_failure_analisis`'s new
  table-name-as-filename convention. Only the filename changed; the partitioned path
  (`.../mode_failure_analisis/year=YYYY/week=WW/...`) is unchanged from v2.3.
- Any object already published under the v2.3 flat path for `unit_failure_analisis` is stale and
  should be deleted manually — the pipeline no longer writes there.

### Version 2.3 (September 22, 2026)
- Renamed the two `analisis_predictivo.ipynb` output tables: `failure_mode_diagnosis` →
  `mode_failure_analisis`, and `analisis_inteligente` → `unit_failure_analisis`. Same locations
  (`predictive/golden/{cliente}/...`), same schemas, only the name changed — both local filenames
  and the S3 table-folder segment for `mode_failure_analisis`'s partitioned path. The two continue
  to be generated and published together, side by side, in every run.
- Simplified the required style of `probable_cause` (`mode_failure_analisis`) and `causa_probable`
  (`unit_failure_analisis`): both now name only the general physical/mechanical phenomenon
  (wear, combustion, lubrication, temperature, etc.) and, when citing an observation, the variable
  and its direction of change — never the multi-signal reasoning chain that used to justify the
  mechanism (e.g. "sodium and potassium rising together is the signature of coolant ingress").
  That domain reasoning still exists in the prompts as internal reference for choosing accurate
  `recommended_actions`, it just no longer surfaces in the published `probable_cause` text.
- Fixed a real defect found while validating the above: the CDA prompts (`cda_motor.md`,
  `cda_motor_diagnosis.md`) were missing the "no raw column names" prohibition that the Capstone
  prompts already had, and generated output was leaking literal identifiers (e.g.
  `combustion_risk`) into `probable_cause`. Added the same prohibition to both CDA prompts;
  re-validated with real output — zero leaks across the corrected sample.
- CDA's `causa_probable` domain-hypothesis section (`cda_motor.md`) was also missing
  `turbocharger_risk` and `coolant_contamination_risk` (the 2 modes added in v2.0) — added,
  matching what `cda_motor_diagnosis.md` already had.

### Version 2.2 (September 22, 2026)
- Bumped `failure_mode_diagnosis` to contract v1.1: added `diagnostico` (what is happening for
  this unit in this mode) and `limitation` (what single measurement would close the question),
  matching the four-field narrative shape already used by the legacy `analisis_inteligente`
  output. Schema is now 8 columns instead of 6; both are required, non-null strings.
- The contract is no longer Capstone-only in practice: `analisis_predictivo.ipynb` (a single
  notebook, parameterized by client) generates and publishes it for both `capstone` and `cda`
  (motor). `probable_cause`/`recommended_actions`/`diagnostico`/`limitation` are now generated by
  an LLM call per unit (covering all of that unit's flagged modes in one call), not by static
  rules alone — `reglas_<cliente>_motor.json` is used only as the fallback when the LLM call
  fails or omits a requested mode (`analysis_status = fallback_rules`), matching the original
  v1.0 design intent of never leaving a flagged mode without a row.
- Removed the `FAILURE_MODE_CONFIG` (dashboard repo) dependency from the generation pipeline: the
  mode → telemetry-signal catalog now lives in `telemetry_variables`, added to each mode's entry
  in `reglas_<cliente>_motor.json`, inside this repo. This was a prerequisite for running the
  pipeline outside the analyst's machine (e.g. in a container), since the dashboard repo's
  absolute path obviously does not exist there.

### Version 2.1 (September 21, 2026)
- Added the published weekly `failure_mode_diagnosis` contract from `predictive_guide.md`,
  including its six-column schema, per-flagged-mode grain, threshold 35, status values, and
  canonical partition path
- Documented a no-model migration from the frozen legacy output using existing deterministic rules
  for every flagged mode

### Version 2.0 (September 1, 2026)
- Documented the new parquet golden layer (`telemetry/signal_daily_status`,
  `predictive/risk_scores`, `predictive/unit_status_summary`, `predictive/cumulative_risk_curve`),
  replacing the wide per-client CSV files described in v1.0, based on
  `new_predictive_data_contracts.md`
- Recorded the long-format schema, Hive `year=`/`week=` partitioning, weekly refresh cadence, and
  the dedicated `cumulative_risk_curve` reader (parquet metadata dependency)
- **Corrected the storage model**: the golden layer is read from a **local mirror**
  (`data/{tecnica}/golden/{cliente}/{componente}/{tabla}/`) synced manually from S3 — the
  dashboard has no live/runtime S3 dependency, contrary to how the upstream reading guide frames
  it. Reading-pattern code samples updated to target the local filesystem, with S3 noted as a
  drop-in `filesystem=` swap if ever needed.
- Verified the actual local parquet against the upstream reading guide and corrected several
  discrepancies: `cumulative_risk_curve` has 30 columns locally vs. 13 documented upstream (17
  undocumented columns listed in the then-§7, including `componente` being the string
  `"MOTOR DIESEL"` rather than lowercase `"motor"`); the 9 Motor failure-mode names are now listed
  explicitly (`turbocharger_risk`, `coolant_contamination_risk` are the 2 new vs. v1.0); confirmed
  no `oil`-technique `signal_daily_status`-equivalent table exists yet, so `OIL_THRESHOLDS`
  redundancy remains unconfirmed; confirmed the new layout covers `capstone/motor` and
  `cda/motor` (not `transmision`, not yet `cda`'s cumulative curve)
- Discovered and documented `analisis_inteligente.parquet`, an LLM-generated per-unit narrative
  snapshot present locally for `capstone`/`cda` that appears to be the `failure_mode_diagnosis`
  content the upstream guide describes as "not available yet" — **not mentioned in the upstream
  guide itself**; flagged for confirmation with the upstream team
- Added [§9 Migration Notes](#-migration-notes-v10--v20) enumerating control changes vs. v1.0 and
  their implications for this repo's loaders, `FAILURE_MODE_CONFIG`, rolling-average logic, status
  classification, and the accumulated-curve module — none of which have been implemented against
  this new contract yet

### Version 1.0 (July 29, 2026)
- Initial formal data contract for the Predictive module, split out from the informal processing
  notes in `RESUMEN_PROCESAMIENTO_PREDICTIVO.md` to match this repo's `project_overview.md` /
  `data_contracts.md` documentation pattern
- Documented the golden CSV schema, dashboard-side oil thresholds, and the component-hours
  cross-module dependency
