# Data Contracts - Predictive Data Product

**Version**: 2.1
**Last Updated**: September 21, 2026
**Owner**: Predictive Module Team
**Status**: Golden layer migrated from the old wide per-client CSV to a partitioned parquet
format. **The data lives locally** under `data/{tecnica}/golden/{cliente}/{componente}/{tabla}/`
— it is synced there manually from S3 (not read live over `s3fs` by the dashboard). The dashboard
has a **dual-mode loader** (`src/data/predictive_v2.py`): it reads the v2.0 parquet layout when it
exists for a client/component, falling back to the v1.0 CSV otherwise (see
[§9 Migration Notes](#-migration-notes-v10--v20) for exactly what is wired up per table). As of
this version, upstream has also **published `failure_mode_diagnosis`** (previously "still being
defined") and clarified that `unit_status_summary.estado` is derived from the cumulative curve, not
flat 30/50/60/80 thresholds. **Both are now implemented and verified against a real sync**
(September 21, 2026): `attach_status()` trusts upstream `estado` directly
(`COMPUTE_STATUS = False`), and the evidence tab's AI panel reads `failure_mode_diagnosis` for
`capstone/motor` — see [§6](#status--classification-rules) and [§9](#-migration-notes-v10--v20).

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
rates, or failure-mode scores itself. **This includes fleet `estado`**: `tab_predictive_overview.py`
now trusts the upstream `unit_status_summary.estado` column directly (`COMPUTE_STATUS = False`) —
a client-side fallback (`_classify_status_from_scores`) still exists in code for the case a
future data drop breaks this again, but it isn't the active path. See
[§6](#status--classification-rules) and [§9](#-migration-notes-v10--v20).

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

Upstream, all four tables regenerate **once per week**, one partition per run. Locally, freshness
depends on when the manual sync from S3 was last run — the local mirror can lag the upstream
partitions. Either way, a stalled/skipped run does not produce an empty partition, so readers
should use the *last available* partition rather than assume the current calendar week has data.

### Tables

| Table | Contents | Grain |
|---|---|---|
| `telemetry / signal_daily_status` | % of the day each engine/transmission signal spent in the alert band and in the critical band | unit × day × signal |
| `predictive / risk_scores` | Risk score per failure mode, plus the synthetic `ranking`, in **long format** | unit × day × mode |
| `predictive / unit_status_summary` | Snapshot of each unit's status as of the run's close | unit (one row) |
| `predictive / cumulative_risk_curve` | Cumulative lifecycle risk curve per unit, with its fleet reference band | unit × day |
| `predictive / failure_mode_diagnosis` | **Published.** Per-flagged-mode written diagnosis (probable cause + recommended actions) | unit × flagged mode |

`failure_mode_diagnosis` is no longer "still being defined" — as of this version it is the
**published, public contract** for the weekly narrative diagnosis, documented in full in
[its own schema section](#predictive--failure_mode_diagnosis-published). It **replaces**
`analisis_inteligente.parquet`, which upstream now describes as **frozen legacy** (kept readable,
but not regenerated) — see
[the `analisis_inteligente.parquet` section](#predictive--analisis_inteligenteparquet-frozen-legacy)
for how the two differ and what stays valid to read. This repo's dashboard still reads the frozen
legacy file (`src/data/loaders.py::load_analisis_inteligente`, wired into
`tab_predictive_evidence.py`) — migrating to `failure_mode_diagnosis` is tracked as a follow-up,
not done as part of this update (see [§9](#-migration-notes-v10--v20)).

### Auto-Discovery

Unlike v1.0, components are not discovered by scanning a folder for `*.csv` files — the path
itself is parameterized by `{cliente}/{componente}`. As observed in the local mirror:

| Client | Component | `risk_scores` / `unit_status_summary` (new parquet) | `cumulative_risk_curve` | Legacy CSV still present |
|---|---|:-:|:-:|:-:|
| `capstone` | `motor` | ✅ | ✅ | ✅ (`motor.csv`) |
| `cda` | `motor` | ✅ (history back to `year=2021`) | ❌ | ✅ (`motor.csv`) |
| `cda` | `transmision` | ❌ — not migrated | ❌ | ✅ (`transmision.csv`) |

So the new layout currently only covers `componente = motor`, across at least two clients
(`capstone`, `cda`); `transmision` has **not** been migrated for either client and is still only
available as the old wide CSV. `cumulative_risk_curve` has only been observed for `capstone`.
Whether/how multi-client, multi-component discovery works against this layout (equivalent to
v1.0's `_discover_components`) is **not formally specified** — treat the table above as a snapshot
of what exists today, not a guarantee, and re-check before assuming a client/component pair is
covered.

---

## 📐 Table Schemas

### `unit_status_summary`

One row per unit — feeds the crítico/alerta/saludable fleet cards.

| Column | Type | Description |
|---|---|---|
| `Unit` | string | Unit identifier |
| `Fecha` | date | Date of **that unit's** last available reading (not necessarily the run date — see below) |
| `estado` | string | `anormal` / `alerta` / `normal` — **now sourced from the cumulative curve**, see [§6](#status--classification-rules) |
| `estado_origen` | string | `"curva"` or `"umbral"` — which of the two criteria below produced `estado` for this unit |
| `fecha_estado_curva` | date, nullable | Date of the curve point `estado` was read from; null when `estado_origen == "umbral"` |
| `desfase_estado_dias` | int, nullable | Days between `Fecha` and `fecha_estado_curva` — a large gap means the displayed status is older than the rest of the row; null when `estado_origen == "umbral"` |
| `ciclo_curva` | int, nullable | Component lifecycle number (`cumulative_risk_curve.ciclo`) at the point `estado` was read from; null when `estado_origen == "umbral"` |
| `estado_previo` | string | `estado` seven days earlier |
| `cambio_estado` | string | `"sí"` / `"no"` — whether `estado` changed vs. `estado_previo` |
| `estado_umbral` | string | `anormal` / `alerta` / `normal` by the old fixed-threshold rule — kept as fallback (when the unit has no curve) and as an audit trail otherwise, see [§6](#status--classification-rules) |
| `ranking` | float | Synthetic risk score for the day |
| `delta_ranking` | float | Change in `ranking` over the last 7 days |
| `media_30d` | float | 30-day rolling mean of `ranking`, **precomputed upstream** |
| `dias_media_30d` | int | Number of real days the 30-day mean was actually computed over |
| `peor_modo` | string | Failure mode with the highest score |
| `peor_valor` | float | That mode's score |
| `modes_over_threshold_count` | int | Count of modes scoring ≥ 35 (note: this is the `failure_mode_diagnosis` flag threshold, distinct from the 30/50/60/80 thresholds behind `estado_umbral` — see [§6](#status--classification-rules)). Should match the number of `failure_mode_diagnosis` rows for the same unit that week — a mismatch is a data problem, not something to paper over in the UI |
| `modos_ordenados` | string (JSON) | All 9 modes with their score, ordered highest → lowest |
| `dias_sin_datos` | int | Staleness of this unit's snapshot |

Every unit that exists is always present in the run's partition, even if it has stopped
reporting — a stale unit shows a stale `Fecha` and `dias_sin_datos > 0` rather than being absent.

`modos_ordenados` must be parsed:

```python
import json
modos = json.loads(fila["modos_ordenados"])
# {'lubrication_failure_risk': 85.3, 'blowby_risk': 70.0, ...}
```

`json.loads` preserves the highest→lowest order, so it can feed a bar chart or ranked list
directly without re-sorting.

### `risk_scores`

Long format: **10 rows per unit per day** — one per failure mode plus one row where
`failure_mode == "ranking"`.

| Column | Type | Description |
|---|---|---|
| `Unit` | string | Unit identifier |
| `Fecha` | date | Day of the record |
| `failure_mode` | string | One of the 9 modes (all end in `_risk`), or the literal value `"ranking"` |
| `risk_value` | float | Score, 0–100 |

```python
modos = riesgos[riesgos["failure_mode"] != "ranking"]
curva = riesgos[riesgos["failure_mode"] == "ranking"]
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

> **Oil signals do not appear to follow this shape.** `FAILURE_MODE_CONFIG["capstone"]["signals"]`
> lists a `technique` per signal (`telemetry` in the worked example), and oil (tribology) essay
> names (e.g. `Cromo`, `Hierro`, `Hollín`) also appear as `signals` entries for some failure modes
> — which could suggest an equivalent `oil/.../signal_daily_status` table. Checked against the
> local mirror: **no such table exists** (`data/oil/golden/{client}/` only has the pre-existing
> `stewart_limits*.parquet` files, unchanged). Instead, raw oil essay values plus derived 5-sample
> moving means / 30-day deltas / 90-day z-scores (`{Essay}_mm5`, `{Essay}_delta30`, `{Essay}_z90`)
> show up per-unit in `analisis_inteligente.parquet` (below). So the v1.0 static `OIL_THRESHOLDS`
> table is **not confirmed redundant** — oil classification upstream now looks closer to a
> per-unit statistical baseline (`z90`) than to the old fixed Normal/Alerta/Crítico bands, which is
> itself a change worth confirming with the upstream team before touching `OIL_THRESHOLDS` — see
> [§9](#-migration-notes-v10--v20).

### `predictive / analisis_inteligente.parquet` (frozen legacy)

Observed locally at `data/predictive/golden/{cliente}/analisis_inteligente.parquet` (both
`capstone` and `cda`). Originally flagged in v2.0 of this document as undocumented upstream and a
possible preview of `failure_mode_diagnosis` — **now confirmed**: upstream describes it explicitly
as superseded by the published `failure_mode_diagnosis` table below, and states it **"remains
frozen and is not regenerated"**. Treat any copy of this file as a point-in-time snapshot that will
not gain new weeks going forward, not as a live source.

This repo's dashboard still reads this file (`load_analisis_inteligente` /
`get_latest_analisis_inteligente` in `src/data/loaders.py`, consumed by
`tab_predictive_evidence.py` and `tab_predictive_overview.py::attach_status`) — see
[§9](#-migration-notes-v10--v20) for what switching to `failure_mode_diagnosis` implies for that
code.

**Grain**: one row per unit — a snapshot, not partitioned by `year=`/`week=` like the other four
tables (confirmed: 50 rows for 50 distinct `Unit` values in the `capstone` copy, most-recent
`Fecha` per unit).

**Contents**: one diagnosis per unit, covering only that unit's single worst mode — narrower than
`failure_mode_diagnosis`, which carries one row per unit **per flagged mode**:

| Column group | Examples | Description |
|---|---|---|
| Identifiers | `Unit`, `Fecha`, `year_week` | |
| Failure-mode scores | `abrasive_wear_risk`, ..., `ranking` | Same 9 modes as `risk_scores`, but wide (one column each) |
| Raw oil essays | `Aluminio`, `Cobre`, `Hierro`, `Viscocidad`, ... | Latest sample values |
| Oil/mode derived stats | `{col}_mm5`, `{col}_delta30`, `{col}_z90` | 5-sample moving mean, 30-day delta, 90-day z-score, per failure mode and per oil essay |
| Status | `media_30d`, `peor_riesgo`, `peor_modo`, `estado`, `rolling_risk_90d` | Same shape as `unit_status_summary` |
| **Narrative (LLM-generated)** | `observaciones` (JSON list of `{severidad, texto}`), `diagnostico`, `causa_probable`, `acciones` (JSON list), `limitacion` | Free-text diagnosis, in Spanish |
| Provenance | `analisis_fuente` (`"llm"` or `"omitida"`), `analisis_tokens`, `analisis_error` | `"omitida"` rows (seen for `normal`-status units) have no narrative fields populated — the LLM pass appears to be skipped for low-risk units, presumably to save cost |

This directly resolves two things left open by the upstream guide: the **narrative diagnosis
content does exist** for at least `capstone`/`cda`, and the **failure-mode set is 9**, matching
`risk_scores`/`unit_status_summary` (see [§5](#failure-mode--signal-catalog) for the confirmed
names).

### `predictive / failure_mode_diagnosis` (published)

> **Status: published.** This is the public contract for the weekly Capstone predictive analysis,
> replacing `analisis_inteligente.parquet` above.

**Grain**: one row per **unit × flagged failure mode** — a structural change from
`analisis_inteligente.parquet`'s one-row-per-unit shape. A unit with no mode above threshold does
not appear at all that week (no empty row, no filler text).

| Column | Type | Description |
|---|---|---|
| `Unit` | string | Unit identifier |
| `Fecha` | date | Date of the data the analysis was run on |
| `failure_mode` | string | The diagnosed mode, one of the 9 declared in `FAILURE_MODE_CONFIG` |
| `probable_cause` | string | Text: probable cause of the observed behavior |
| `recommended_actions` | string (JSON array) | Ordered list of recommended actions |
| `analysis_status` | string | `"ok"` / `"fallback_rules"` / `"error"` — see below |

**`analysis_status`** must drive how the UI treats the row, not just whether it has text:

- `"ok"` — ran normally, display as-is.
- `"fallback_rules"` — the LLM was unavailable and the text came from fixed rules instead; still
  valid, but should be flagged visually so it doesn't read as more precise than it is.
- `"error"` — the analysis failed. `probable_cause`/`recommended_actions` carry a **generic**
  placeholder message, never the underlying exception. **Never surface raw exception text to the
  user** — this rule exists because of a real incident where a `BadRequestError` string from a
  failed call ended up rendered in a unit's report. Show a UI-level error message instead of the
  field's literal contents whenever `analysis_status == "error"`.

**Threshold and lineage**: the flagging threshold is **35** (the same threshold behind
`unit_status_summary.modes_over_threshold_count`), versioned in the upstream analysis
configuration and recorded in the run manifest. `estado == "normal"` does not exclude a unit — a
unit can be `normal` overall and still have one mode above 35. The model receives all of a unit's
flagged modes in a single structured request; a missing/invalid mode from the model is completed
by deterministic fallback rules rather than dropped.

**Reading pattern**: same run-snapshot pattern as `unit_status_summary` — read only the latest
partition, not `leer_ultimas_semanas`:

```python
diagnoses = leer_ultima_semana(ruta_tabla("predictive", "failure_mode_diagnosis"))
```

To show a unit's diagnoses in the same severity order as the summary, join through
`modos_ordenados`:

```python
import json

row = summary[summary["Unit"] == "CA-44"].iloc[0]
scores = json.loads(row["modos_ordenados"])

detail = diagnoses[diagnoses["Unit"] == "CA-44"].copy()
detail["score"] = detail["failure_mode"].map(scores)
detail = detail.sort_values("score", ascending=False)
```

**Cross-references**: `unit_status_summary` says how many modes are flagged and which is worst;
`failure_mode_diagnosis` says what's going on with each of those modes; `FAILURE_MODE_CONFIG`
(§5) says which signals to plot as evidence for each. `modes_over_threshold_count` should equal
the number of `failure_mode_diagnosis` rows for that unit that week — a mismatch is a data
problem the UI should surface, not silently reconcile.

**Canonical path** (same partition layout as the other four tables):

```text
predictive/golden/capstone/motor/failure_mode_diagnosis/year=YYYY/week=WW/part-0.parquet
```

`YYYY`/`WW` come from the same run as `unit_status_summary`. Written with Zstandard compression, no
index; staged under `_runs/{run_id}` and promoted only after validation. If no modes are flagged
fleet-wide that week, an **empty** parquet with the same schema is published (not a missing
partition).

**Verified against the September 21, 2026 sync**: `data/predictive/golden/capstone/motor/failure_mode_diagnosis/year=2026/week=32/part-0.parquet`
exists and matches the schema above exactly (`Unit`, `Fecha`, `failure_mode`, `probable_cause`,
`recommended_actions`, `analysis_status`), 36 rows, all `analysis_status == "ok"` in this partition
(`fallback_rules`/`error` not yet observed in real data — the handling above is implemented but
untested against a live example of either). **Not present for `cda/motor`** as of this sync — only
`capstone/motor` has this table so far, confirmed via `discover_predictive_layout`.

**Not this repo's concern**: the upstream guide also documents how the generator loads its own AWS
S3 / OpenAI credentials in Docker (`Initialize-LocalRun.ps1`, `*_FILE` env-var pattern). That's the
upstream pipeline's execution environment, not this dashboard's read path — noted here only so it
isn't mistaken for a change to how this repo authenticates against anything.

---

## 📖 Reading Pattern

The three time-series tables (`unit_status_summary`, `risk_scores`, `signal_daily_status`) share
one reading pattern based on listing available `(year, week)` partitions and reading only the
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
covered can be wider. Filter by `Fecha` afterward if exact calendar windows matter.

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

Motor now has **9 failure modes**, confirmed directly from the local `risk_scores` and
`unit_status_summary` data (both `capstone` and `cda`):

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

---

## 🚦 Status & Classification Rules

### `unit_status_summary.estado` (fleet cards)

**Changed in this version.** `estado` is **not** the flat threshold rule below — it is the zone of
the **last point of the unit's current lifecycle** in `cumulative_risk_curve`
(`cumulative_risk_curve.estado`), lowercased. In other words it compares accumulated risk against
the fleet band, the same criterion documented in [§7](#cumulative-risk-curve), not a point-in-time
threshold on `ranking`/`media_30d`.

This has two consequences, both surfaced as their own columns on the row:

- `fecha_estado_curva` can be **earlier** than `Fecha`, because the curve depends on component
  hours (from oil sampling), which can lag behind the daily ranking series. `desfase_estado_dias`
  is the gap in days — a large gap means the displayed status is older than the rest of the row.
- If a unit **has no curve** (e.g. no recorded component hours), `estado` **falls back** to the
  threshold rule below, and `estado_origen` reads `"umbral"` instead of `"curva"`.
  `fecha_estado_curva`, `desfase_estado_dias` and `ciclo_curva` come back null in that case.

**`estado_umbral`** — the fixed-threshold rule from v2.0, kept as the fallback criterion above and
otherwise as an audit trail (it is *not* recomputed to explain `estado`, it's the independent
result of applying this rule regardless of source):

| Status | Condition |
|---|---|
| `anormal` | `media_30d ≥ 60` **or** any mode `≥ 80` |
| `alerta` | `media_30d ≥ 30` **or** any mode `≥ 50` |
| `normal` | otherwise |

`estado` and `estado_umbral` **can legitimately disagree** for the same unit — one looks at
accumulated risk against the fleet, the other at point-in-time risk against fixed thresholds. This
is documented as intentional, not a defect: use `estado` for the cards, `estado_umbral` to explain
*why* a unit sits where it does. `modes_over_threshold_count` uses a third, unrelated threshold of
35 (the `failure_mode_diagnosis` flag threshold) and should not be confused with either `estado` or
`estado_umbral`.

**Code impact**: `tab_predictive_overview.py`'s `COMPUTE_STATUS` flag used to bypass both `estado`
and `estado_umbral` and reclassify status client-side from 30-day scores, because upstream had told
this team `estado` was mis-computed. This clarification of how `estado` actually works explains why
the client-side recomputation and the old upstream `estado` disagreed (they were never the same
criterion) — **`COMPUTE_STATUS` is now `False`**, verified against the September 21, 2026 sync (see
[§9](#-migration-notes-v10--v20) for the exact numbers checked before flipping it). The client-side
classifier (`_classify_status_from_scores`) stays in the code as a safety net, not deleted, in case
a future data drop regresses `estado` again.

### `cumulative_risk_curve.estado` (curve zones)

Uses Title Case (`Normal` / `Alerta` / `Anormal`) and compares the accumulated curve against the
fleet reference band, **not** the fixed-threshold rule above. This is per-point (one value per
`Unit`/`Fecha` row along the curve), while `unit_status_summary.estado` above is now **literally
sourced from this column** — specifically the last point of the unit's current cycle
(`es_vigente == True`), lowercased. They should therefore agree by construction for the current
cycle's latest point; what **can** still legitimately disagree with `unit_status_summary.estado` is
`estado_umbral` (see above), not this column. Label `estado` here distinctly from `zona_final`
(same status, but repeated across all of a cycle's rows rather than per-point) in any UI that shows
both.

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

If `df.attrs["config"]`/`["banda"]` is lost (e.g. by reading with plain `pd.read_parquet`), the
plotting helper (`curva_figura.plot_curva_acumulada`, shipped as a separate module) does **not**
raise — it silently falls back to default `K_SIGMA`/`K_ALERTA` parameters and draws zone
boundaries that don't match the classification that was actually used. Always read this table with
`leer_curva`. Confirmed locally, `config` for the `capstone`/`motor` partition currently reads:

```json
{"PESO_HORAS": false, "CORREDOR_INDIVIDUAL": false, "LEAVE_ONE_OUT": true,
 "APLICAR_OFFSET": true, "REFERENCIA_SOLO_VIGENTES": false, "CALCULAR_TENDENCIA": false,
 "K_SIGMA": 2.0, "K_ALERTA": 1.0}
```

### Columns

The upstream reading guide (`new_predictive_data_contracts.md`) documents a 13-column subset; the
local parquet (`data/predictive/golden/capstone/motor/cumulative_risk_curve/...`) actually carries
**30 columns**. The full set, confirmed by direct inspection:

| Column | Type | Description |
|---|---|---|
| `Unit`, `Fecha` | string, date | Unit and day |
| `ciclo` | int | Component lifecycle number; increments on each component change |
| `curva` | string | Key for one full lifecycle, e.g. `"CA-30 - ciclo 1"` |
| `componentHours_filled` | float | Component hours that day — the chart's X axis |
| `ranking` | float | That day's non-cumulative risk |
| `ranking_acumulado` | float | Cumulative sum of `ranking` within the unit/cycle; starts near 0 |
| `offset_curva` | float | Vertical offset so the curve starts at the fleet mean |
| `ranking_acumulado_ajustado` | float | **The column that is plotted and classified against** |
| `banda_media`, `banda_umbral` | float | Fleet mean and threshold at that hour value |
| `banda_inferior` | float | *Undocumented upstream.* Lower band bound at that hour value (mirrors `banda_umbral` on the low side) |
| `banda_extrapolada` | bool | *Undocumented upstream.* Whether the band value at this point was extrapolated beyond the fitted grid |
| `tramo_flota` | float | *Undocumented upstream.* Likely a fleet-segment/bucket value at that hour — meaning not confirmed |
| `sigma_curva` | float | *Undocumented upstream.* Standard deviation of the band at that hour |
| `umbral_curva` | float | *Undocumented upstream.* Per-curve threshold, distinct from `banda_umbral` — relationship not confirmed |
| `z` | float | *Undocumented upstream.* Z-score of this point vs. the band (consistent with `K_SIGMA`/`K_ALERTA` in `config`) |
| `evaluable` | bool | *Undocumented upstream.* Whether this point had enough support to be classified |
| `estado` | string | `Normal` / `Alerta` / `Anormal`, or null if outside the band's domain |
| `nivel_medio` | float | *Undocumented upstream.* Meaning not confirmed |
| `horas_por_dia` | float | *Undocumented upstream.* Component-hours accrual rate for that unit/cycle |
| `delta_tendencia`, `tendencia` | float, string | *Undocumented upstream.* Trend delta and label; mostly null in the observed sample (`CALCULAR_TENDENCIA: false` in `config` for this partition) |
| `dias_desde_tendencia` | float | *Undocumented upstream.* Days since the trend was last computed |
| `es_vigente` | bool | `True` if this is the unit's current (active) cycle |
| `zona_final` | string | Status of the vigent curve's last point, repeated across all its rows; null for historical cycles |
| `peor_zona` | string | *Undocumented upstream.* Worst zone reached across the vigent cycle so far |
| `tendencia_final`, `peor_tendencia` | string | *Undocumented upstream.* Trend-equivalents of `zona_final`/`peor_zona` |
| `componente` | string | **Re-verified against the September 21, 2026 sync**: still `"MOTOR DIESEL"` (14,420/14,420 rows in `capstone/motor`), not the lowercase `"motor"`/`"transmision"` the upstream guide's own column table shows. The guide's table is simplified/aspirational on this point — **do not hardcode the lowercase form when filtering on this column** |

Two different nulls: `estado` null means "outside the reference band's domain"; `zona_final` null
means "historical cycle, not the current one" — don't conflate them. Columns marked *undocumented
upstream* are present in the data but not explained in `new_predictive_data_contracts.md`; the
descriptions above are best-effort inferences from column names and observed values — confirm with
the upstream team before building logic that depends on their exact semantics.

The X axis is component **hours**, not calendar time — wear tracks component usage, not the
calendar.

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
- ✅ `Unit` is present in `unit_status_summary` for every known unit on every run, even units that
  stopped reporting (surfaced instead via `dias_sin_datos` and a stale `Fecha`).
- ✅ `risk_value` (in `risk_scores`) and `pct_time_alert`/`pct_time_critical` (in
  `signal_daily_status`) are numeric in `[0, 100]` when present.
- ✅ **Absence of a row is the "no data" signal** in both long-format tables — do not backfill or
  interpret a missing unit/day/mode (or unit/day/signal) row as zero.
- ✅ `cumulative_risk_curve` must be read via `leer_curva`, not `pd.read_parquet`, to retain
  `config`/`banda` metadata — otherwise zone boundaries silently drift from what was actually used
  to classify the data.
- ✅ `failure_mode_diagnosis` is now a published, partitioned table (see
  [its schema](#predictive--failure_mode_diagnosis-published)) — `analisis_inteligente.parquet` is
  frozen legacy and will not gain new weeks. This repo's evidence UI still builds against the
  frozen file; treat that as a known gap to close, not an open question anymore.
- ⚠️ **Never render `failure_mode_diagnosis` fields when `analysis_status == "error"`** —
  `probable_cause`/`recommended_actions` carry a generic placeholder in that case, not the failure
  detail, but any future code path that assumes the fields are always safe to print should still
  guard on `analysis_status` explicitly (this is the same class of incident that already happened
  once with `analisis_inteligente.parquet`'s narrative fields).
- ✅ **Verified against the September 21, 2026 sync**: `unit_status_summary.modes_over_threshold_count`
  matches the number of `failure_mode_diagnosis` rows for every one of the 50 `capstone/motor`
  units that week (0 mismatches) — treat a future mismatch as a data-quality issue to surface, not
  to silently reconcile by trusting one number over the other.
- ⚠️ `componente` in `cumulative_risk_curve` is `"MOTOR DIESEL"` (re-confirmed on the fresh sync,
  14,420/14,420 rows), **not** the lowercase `"motor"`/`"transmision"` the upstream guide's own
  docs show (see [§7](#columns)), and not the lowercase `"motor"` used elsewhere in the
  path/config (`{componente}` in the S3/local path, or
  `FAILURE_MODE_CONFIG[...]["components"]["motor"]`). Treat the guide's lowercase form as
  aspirational/simplified documentation, not the real value.

---

## 🔀 Migration Notes (v1.0 → v2.0)

Summary of what changed and what it implies for this repo. **Corrected in this update**: contrary
to earlier versions of this document, most of this migration is **already implemented** —
`src/data/predictive_v2.py` provides dual-mode discovery/readers (`discover_predictive_layout`,
`load_risk_scores`, `load_unit_status_summary`, `read_cumulative_risk_curve`) that prefer the v2.0
parquet layout per client/component and fall back to the legacy CSV/`analisis_inteligente.parquet`
otherwise, wired into `tab_predictive_overview.py`/`tab_predictive_evidence.py`/
`predictive_callbacks.py` through the shared `attach_status()` helper. The table below reflects
what is actually wired up today, not a still-pending plan — remaining gaps are called out per row.

| Area | v1.0 | v2.0 | Status in this repo |
|---|---|---|---|
| Storage | Local per-client CSV, `data/predictive/golden/{client}/{component}.csv` | Partitioned parquet, mirrored locally at `data/{tecnica}/golden/{cliente}/{componente}/{tabla}/year=/week=/`, synced manually from S3 | **Implemented.** `predictive_v2.discover_predictive_layout` / `_list_week_partitions` / `read_latest_partition` / `read_last_n_weeks` read the local `pyarrow` mirror directly, per client/component, with an LRU cache keyed on file mtime/size. Per-component fallback to the legacy CSV path stays in `_discover_components` (`tab_predictive_overview.py`) for components not yet migrated |
| Shape | Wide: ~250 columns, one per operational-mode × signal × rate-type, plus one column per failure mode | Long: `risk_scores` and `signal_daily_status` are unit × day × (mode\|signal) rows | **Implemented via a pivot shim.** `predictive_v2.risk_scores_to_wide` pivots the long parquet back into the legacy wide shape so the existing rolling-window/table code didn't need a rewrite — this is a deliberate compatibility layer, not a leftover |
| Failure modes (Motor) | 7, hardcoded in `predictive_config.py::FAILURE_MODE_CONFIG["motor"]` | 9 — confirmed: `abrasive_wear_risk`, `bearing_wear_risk`, `blowby_risk`, `combustion_risk`, `coolant_contamination_risk`, `lubrication_failure_risk`, `oil_degradation_risk`, `thermal_imbalance_risk`, `turbocharger_risk` | **Implemented data-driven, not hardcoded.** `predictive_v2.get_failure_mode_keys` reads the mode list from `modos_ordenados`/`risk_scores` directly rather than a fixed count, so the 2 new modes appear automatically once present in the data — verify `FAILURE_MODE_CONFIG["capstone"]` still carries correct labels/signal mappings for both |
| Rolling averages | Computed client-side (`30d`/`60d`/`90d` per-`Unit` rolling means, `min_periods=1`) | `media_30d` precomputed upstream in `unit_status_summary`; no `60d`/`90d` equivalent observed | **Partially implemented.** `tab_predictive_overview.py` prefers `unit_status_summary.media_30d`/`dias_media_30d` when that table exists, falling back to client-side rolling computation otherwise; `60d`/`90d` windows still stay client-side either way |
| Status classification | Applied client-side on `avg_ranking_30d`/`max_fm_30d`, duplicated in 4 call sites | Precomputed upstream as `unit_status_summary.estado` — curve-derived, not the flat 30/50/60/80 rule (see [§6](#status--classification-rules)) | **`COMPUTE_STATUS` flipped to `False`.** Verified against the September 21, 2026 sync before flipping: `capstone/motor` has `estado_origen == "curva"` for all 50 units (no unit stuck on the `"umbral"` fallback), and `estado`/`estado_umbral` disagree for 18/50 units — the documented, intentional divergence, not a sign of bad data. `cda/motor` shows 10 `"curva"` + 1 `"umbral"`, also as expected. `attach_status()` now trusts `unit_status_summary.estado` directly (falling back to `analisis_inteligente.parquet`, then `"Normal"`, unchanged) |
| Cumulative curve | Built entirely client-side in `accumulated_curve.py` (hours-fill, cycle detection, reference band, zone classification), joined against Oil's `cleaned_component_hours.parquet` | Delivered precomputed as `cumulative_risk_curve`, including `componentHours_filled`, `zona_final`, and ~17 more columns not documented upstream (see [§7](#columns)) | **Implemented alongside the legacy path.** `predictive_v2.read_cumulative_risk_curve` is the dedicated reader (metadata-preserving, per Change 6); `accumulated_curve.py` keeps both `render_accumulated_section` (legacy, client-built) and `render_accumulated_section_from_curve` (new, precomputed) as parallel code paths rather than one replacing the other |
| Oil variables & thresholds | Separate wide columns per essay (`Hierro`, `Cobre`, ...) plus a static, hardcoded `OIL_THRESHOLDS` table in `predictive_config.py` | No `oil`-technique equivalent of `signal_daily_status` found locally (`data/oil/golden/{client}/` is unchanged: still just `stewart_limits*.parquet`). Raw essay values plus `_mm5`/`_delta30`/`_z90` derived stats now appear per-unit in `analisis_inteligente.parquet` | **Not touched.** `OIL_THRESHOLDS` is still the hardcoded v1.0 table; still not confirmed redundant — the upstream classification signal looks more like a per-unit `z90` baseline than fixed bands. Treat as a genuine behavior change to confirm with upstream before changing |
| Component-hours cross-module dependency | Predictive read Oil's `data/oil/golden/{client}/cleaned_component_hours.parquet` directly for horómetro figures on priority cards/unit banner | Not present in `unit_status_summary`/`risk_scores`; only `cumulative_risk_curve.componentHours_filled` carries hours, and only for `capstone` (no curve table for `cda` yet) | **Not changed** — the Oil-module join stays the source for any client/component without a `cumulative_risk_curve` table. Confirmed per client, not assumed |
| Clients/components observed | `CDA`: `motor`, `transmision` (CSV) | New parquet layout confirmed for `capstone/motor` and `cda/motor` (history back to `year=2021` for `cda`); `transmision` not migrated for either client; `cumulative_risk_curve` only observed for `capstone` | **Gated correctly.** `discover_predictive_layout` checks `risk_scores`/`unit_status_summary`/`cumulative_risk_curve` independently per component, so `cda/transmision` (still CSV-only) and `cda`'s missing curve table are each handled by their own fallback, not assumed covered |
| `failure_mode_diagnosis` | N/A (didn't exist) | Published (see [its schema](#predictive--failure_mode_diagnosis-published)) — one row per unit × flagged mode, replacing `analisis_inteligente.parquet` (frozen, one row per unit) | **Migrated for `capstone/motor`.** `predictive_v2.get_unit_failure_mode_diagnosis` reads the table, sorted worst-mode-first via the `modos_ordenados` join, and `tab_predictive_evidence.py`'s AI panel now shows it (with `fallback_rules` flagged in the panel header and `error` rows never rendering their raw fields). Verified against the September 21, 2026 sync: `capstone/motor` week 32 has 36 rows across the 50 units, all `analysis_status == "ok"` (`fallback_rules`/`error` handling is implemented but not yet exercised by real data), and `modes_over_threshold_count` matches the diagnosis row count for every unit (0 mismatches). **Not available for `cda/motor`** yet — `attach_status()`'s legacy `analisis_inteligente.parquet` fallback (and the rule-based insight engine below that) still cover it, gated automatically by `discover_predictive_layout`'s per-component `failure_mode_diagnosis` flag |

**Net effect of this update**: both previously-open questions — `estado`'s real derivation and
`failure_mode_diagnosis`'s final schema — are now implemented and verified against the September
21, 2026 data sync, not just documented. `COMPUTE_STATUS` is `False`; the evidence tab's AI panel
reads `failure_mode_diagnosis` for `capstone/motor` and falls back to the frozen legacy file
everywhere else.

---

## 📝 Change Log

### Version 2.1.1 (September 21, 2026 — data sync + implementation)
- The client's data sync landed the same day as v2.1's documentation update, so the code changes
  and verifications proposed there were carried out and checked against real parquet:
  - `src/data/predictive_v2.py`: added `failure_mode_diagnosis` to `ComponentAvailability`/discovery,
    plus `load_failure_mode_diagnosis` and `get_unit_failure_mode_diagnosis` (worst-mode-first join
    via `modos_ordenados`, matching §3's pattern)
  - `dashboard/tabs/tab_predictive_evidence.py`: AI panel now reads `failure_mode_diagnosis` first,
    handling `analysis_status` per §3's rules, falling back to `analisis_inteligente.parquet` then
    the rule-based insight engine
  - `dashboard/tabs/tab_predictive_overview.py`: `COMPUTE_STATUS` flipped to `False`
  - Verified against `data/predictive/golden/{capstone,cda}/motor/...` (week 32 / week 29 2026):
    `capstone/motor`'s `estado_origen` is `"curva"` for all 50 units (0 stuck on `"umbral"`);
    `estado`/`estado_umbral` disagree for 18/50 units, matching the documented intentional
    divergence; `cda/motor` shows 10 `"curva"` + 1 `"umbral"`; `failure_mode_diagnosis` exists only
    for `capstone/motor` (36 rows, all `analysis_status == "ok"`) and `modes_over_threshold_count`
    matches its row count for all 50 units; `cumulative_risk_curve.componente` is confirmed still
    `"MOTOR DIESEL"` (resolves the casing discrepancy raised in v2.1 — the guide's lowercase example
    was aspirational/simplified, not real)
  - Full test suite run: 589 passed, 1 skipped, 8 failed — all 8 failures are in
    `tests/test_campbell_ai*.py` (a schema-drift check unrelated to this module, tripped by the same
    fresh data sync), none touch `predictive_v2`/`attach_status`/`COMPUTE_STATUS`/
    `failure_mode_diagnosis`
  - Not exercised: `analysis_status` values `"fallback_rules"`/`"error"` (no real row with either
    value was present in the synced partition) — the handling code was smoke-tested with synthetic
    inputs only

### Version 2.1 (September 21, 2026)
- **`failure_mode_diagnosis` is now published**, not "still being defined": documented its full
  schema (`Unit`, `Fecha`, `failure_mode`, `probable_cause`, `recommended_actions`,
  `analysis_status`), grain (unit × flagged mode, threshold 35), canonical path, and its
  `analysis_status` handling rules (`ok`/`fallback_rules`/`error`, never surface raw error text).
  `analisis_inteligente.parquet` is retitled **frozen legacy** per upstream confirmation that it is
  superseded and no longer regenerated
- **Corrected `unit_status_summary.estado`'s derivation**: it is sourced from the cumulative
  curve's last-point zone for the unit's current cycle, not the flat 30/50/60/80 rule — documented
  the 5 new lineage columns (`estado_origen`, `fecha_estado_curva`, `desfase_estado_dias`,
  `ciclo_curva`, `estado_umbral`) and rewrote [§6](#status--classification-rules) accordingly. The
  old flat rule survives as `estado_umbral` (fallback when a unit has no curve, and an audit trail
  otherwise)
- **Corrected this document's own migration-status claim**: v2.0 said "none of this is implemented
  yet"; in fact `src/data/predictive_v2.py` already implements dual-mode discovery and readers for
  all four original tables, wired into the dashboard tabs behind `attach_status()`. Rewrote
  [§9](#-migration-notes-v10--v20) to reflect actual implementation state per area, including the
  **`COMPUTE_STATUS` temporary override** in `tab_predictive_overview.py` (bypasses upstream
  `estado` because it was previously reported mis-computed) — flagged as the thing this version's
  `estado` clarification most likely unblocks, pending verification against live data
- Flagged an unresolved discrepancy: `cumulative_risk_curve.componente` was observed locally as
  `"MOTOR DIESEL"`, but the updated upstream guide's own column table now shows lowercase
  `"motor"`/`"transmision"` — not re-verified locally as part of this update (no local
  `data/predictive/` mirror was available in this checkout to check against)
- Source: `predictive_guide.md` (supersedes `new_predictive_data_contracts.md` as the upstream
  reading guide this document is checked against)

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
  undocumented columns listed in [§7](#columns), including `componente` being the string
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
