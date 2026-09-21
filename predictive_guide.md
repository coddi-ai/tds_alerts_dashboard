# Reading ERS data from the dashboard

Quick guide to where the data lives, how to read it, and why it is organised this way.

> **A note on naming.** Table names, column names, function names and column values are kept exactly as they appear in the data and in the code — many of them are Spanish (`Fecha`, `estado`, `peor_modo`, `leer_ultima_semana`). Do not translate them: they are identifiers, and renaming them breaks the joins. Only the explanations are in English.

---

## 1. What is available

Five tables, all parquet on S3.

| Table | What it holds | Grain |
|---|---|---|
| `telemetry / signal_daily_status` | % of each day each engine signal spent in the alert and critical bands | unit × day × signal |
| `predictive / risk_scores` | risk score of each failure mode, plus the synthetic ranking | unit × day × mode |
| `predictive / unit_status_summary` | snapshot of each unit's status at the close of the run | unit |
| `predictive / cumulative_risk_curve` | accumulated risk curve per life cycle, with its fleet band | unit × day |
| `predictive / failure_mode_diagnosis` | intelligent analysis: probable cause and actions per flagged mode | unit × mode |

All five are regenerated once a week. `failure_mode_diagnosis` is the published
weekly Capstone analysis; its public contract is defined in section 6.

---

## 2. Where they live

```
s3://{bucket}/MultiTechnique Alerts/{technique}/golden/{client}/{component}/{table}/year=2026/week=33/part-0.parquet
```

Today `client = capstone` and `component = motor`. A real example:

```
.../MultiTechnique Alerts/predictive/golden/capstone/motor/risk_scores/year=2026/week=33/part-0.parquet
```

Here is how the five tables look for week 33 of 2026:

```
MultiTechnique Alerts/
├── telemetry/golden/capstone/motor/
│   └── signal_daily_status/     year=2026/week=33/part-0.parquet
└── predictive/golden/capstone/motor/
    ├── risk_scores/             year=2026/week=33/part-0.parquet
    ├── unit_status_summary/     year=2026/week=33/part-0.parquet
    ├── failure_mode_diagnosis/  year=2026/week=33/part-0.parquet
    └── cumulative_risk_curve/   year=2026/week=33/part-0.parquet
```

Each one also has the folders for previous weeks sitting next to `week=33`.

The `year=` and `week=` folders are **partitions**: you never open them by hand, the functions below use them to read only what is needed.

Weeks are ISO (Monday to Sunday) and `year` is the ISO year, not the calendar year. That is why 29 December 2025 lands in `year=2026/week=1`.

**Watch what each partition actually holds**, because it is not the same across tables:

| Table | What is inside `week=33` |
|---|---|
| `signal_daily_status`, `risk_scores` | only the 7 days of that week |
| `unit_status_summary`, `failure_mode_diagnosis` | the snapshot of every unit at the close of that run |
| `cumulative_risk_curve` | **the full history**, recomputed at the close of that run |

---

## 3. How to read them

Copy this block as-is:

```python
import os
import re
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as pads
import s3fs

BUCKET = os.getenv("ERS_S3_BUCKET")
RAIZ = "MultiTechnique Alerts"
CLIENTE, COMPONENTE = "capstone", "motor"

fs = s3fs.S3FileSystem()
PARTICION = pads.partitioning(pa.schema([("year", pa.int32()), ("week", pa.int32())]),
                              flavor="hive")


def ruta_tabla(tecnica, nombre, cliente=CLIENTE, componente=COMPONENTE):
    return f"{BUCKET}/{RAIZ}/{tecnica}/golden/{cliente}/{componente}/{nombre}"


def semanas_disponibles(ruta, filesystem=fs):
    """List the (year, week) pairs that exist. Lists paths only, opens no files."""
    dset = pads.dataset(ruta, format="parquet", partitioning=PARTICION, filesystem=filesystem)
    return sorted({(int(y.group(1)), int(w.group(1)))
                   for r in dset.files
                   if (y := re.search(r"year=(\d+)", r)) and (w := re.search(r"week=(\d+)", r))})


def leer_ultimas_semanas(ruta, n=13, filesystem=fs):
    """Read the last n weeks that have data. n=13 ≈ 3 months."""
    pares = semanas_disponibles(ruta, filesystem)[-n:]
    return pd.read_parquet(ruta,
                           filters=[[("year", "==", y), ("week", "==", w)] for y, w in pares],
                           filesystem=filesystem)


def leer_ultima_semana(ruta, filesystem=fs):
    return leer_ultimas_semanas(ruta, n=1, filesystem=filesystem)
```

### Usage

```python
# Fleet status cards — a single partition, 30 rows
summary = leer_ultima_semana(ruta_tabla("predictive", "unit_status_summary"))

# Risk per unit over time — 3 months
risks = leer_ultimas_semanas(ruta_tabla("predictive", "risk_scores"), n=13)

# Signal evidence — 3 months
signals = leer_ultimas_semanas(ruta_tabla("telemetry", "signal_daily_status"), n=13)

# Cumulative curve — see section 5, it needs its own reader
```

`leer_ultimas_semanas` returns a DataFrame already concatenated. It also carries the `year` and `week` columns, which come from the path.

---

## 4. Inside the tables

### `unit_status_summary`

One row per unit. This is what feeds the critical / alert / healthy cards.

| Column | What it is |
|---|---|
| `Unit` | unit identifier |
| `Fecha` | date of the latest data **for that unit** |
| `estado` | `anormal` / `alerta` / `normal` — **this is the one to display** |
| `estado_origen` | `curva` or `umbral`: where `estado` came from |
| `fecha_estado_curva` | date of the curve point that produced that status |
| `desfase_estado_dias` | days between `Fecha` and `fecha_estado_curva` |
| `ciclo_curva` | component life-cycle number at that point |
| `estado_previo` | status 7 days earlier, same criterion |
| `cambio_estado` | `sí` / `no` |
| `estado_umbral` | status by risk thresholds; fallback and audit trail |
| `ranking` | synthetic risk for the day |
| `delta_ranking` | how much the ranking moved in 7 days |
| `media_30d` | 30-day rolling mean of the ranking |
| `dias_media_30d` | how many actual days went into that mean |
| `peor_modo`, `peor_valor` | the highest-scoring mode and its value |
| `modes_over_threshold_count` | how many modes are above 35 |
| `modos_ordenados` | JSON with the 9 modes and their scores, highest first |
| `dias_sin_datos` | how stale this unit's snapshot is |

**Careful with `Fecha`**: each unit carries its own. Every unit is always present in the run's partition, but one that stopped reporting will have an older date and `dias_sin_datos > 0`.

**`modos_ordenados` is text**, it has to be parsed:

```python
import json
modes = json.loads(row["modos_ordenados"])
# {'lubrication_failure_risk': 85.3, 'blowby_risk': 70.0, ...}
```

It comes sorted highest to lowest and `json.loads` preserves that order, so it can drive a list or a bar chart directly.

**Where `estado` comes from**

It comes from the **cumulative curve**: it is the zone of the last point of that unit's current cycle, lowercased. In other words it compares accumulated risk against the fleet band, not against fixed thresholds.

Two consequences:

`fecha_estado_curva` can be **earlier** than `Fecha`. The curve depends on component hours, which come from oil sampling, so it can end before the ranking series does. `desfase_estado_dias` says how many days apart they are. A large gap means the status shown is older than the rest of the row.

If a unit **has no curve** — no recorded component hours, for instance — `estado` falls back to the threshold criterion and `estado_origen` reads `umbral`. In that case `fecha_estado_curva`, `desfase_estado_dias` and `ciclo_curva` come back null.

**`estado_umbral`** is the previous criterion, kept so the result can be audited:

- `anormal` — `media_30d ≥ 60` **or** any mode `≥ 80`
- `alerta` — `media_30d ≥ 30` **or** any mode `≥ 50`
- `normal` — everything else

The two criteria **can disagree** for the same unit, and that is not a bug: one looks at accumulated risk against the fleet, the other at point-in-time risk against thresholds. Use `estado` for the cards; `estado_umbral` helps explain why a unit sits where it sits.

### `risk_scores`

| Column | What it is |
|---|---|
| `Unit`, `Fecha` | unit and day |
| `failure_mode` | one of the 9 modes, **or** the literal value `ranking` |
| `risk_value` | score 0–100 |

Long format: 10 rows per unit and day. `ranking` arrives as one more row, not as a separate column.

To split them:

```python
modes = risks[risks["failure_mode"] != "ranking"]
curve = risks[risks["failure_mode"] == "ranking"]
```

Every mode name ends in `_risk`, so `str.endswith("_risk")` works as a filter too.

If a mode has no row for a given unit and day, it means **there was no data** — different from a 0.0, which means no risk.

### `telemetry / signal_daily_status`

| Column | What it is |
|---|---|
| `Unit`, `Fecha` | unit and day |
| `signal_name` | signal name (`oil_diff_pressure_psi`, `egt_avg_c`, …) |
| `pct_time_alert` | % of the day in the alert band (0–100) |
| `pct_time_critical` | % of the day in the critical band (0–100) |

Same rule: no row = no data that day for that signal.

---

## 5. The cumulative curve

This is the only table that **cannot** be read with the functions above, for two reasons: each partition holds the full history (not just that week), and it carries metadata that `pd.read_parquet` throws away.

It has its own reader:

```python
import json

def leer_curva(ruta, filesystem=fs, semana=None):
    """Read one partition of the curve and restore attrs for plot_curva_acumulada."""
    dset = pads.dataset(ruta, format="parquet", partitioning=PARTICION, filesystem=filesystem)
    pares = sorted({(int(y.group(1)), int(w.group(1))) for r in dset.files
                    if (y := re.search(r"year=(\d+)", r)) and (w := re.search(r"week=(\d+)", r))})
    y, w = semana or pares[-1]

    tabla = dset.to_table(filter=(pads.field("year") == y) & (pads.field("week") == w))
    df = tabla.to_pandas()
    for k, v in (tabla.schema.metadata or {}).items():
        if (nombre := k.decode()) in ("config", "banda"):
            df.attrs[nombre] = json.loads(v.decode())
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    return df
```

### Plotting it

The figure module ships separately (attached file). Use it as-is:

```python
from curva_figura import plot_curva_acumulada

df_curve = leer_curva(ruta_tabla("predictive", "cumulative_risk_curve"))
fig = plot_curva_acumulada(df_curve)
fig.show()
```

Useful options: `units=["CA-44"]` to filter machines, `solo_vigentes=False` to include historical cycles, `height=` for the chart height.

**You must use `leer_curva`, not `pd.read_parquet`.** The plotting function reads `df.attrs["config"]` (the `K_SIGMA` and `K_ALERTA` parameters the curve was generated with) and `df.attrs["banda"]` (the fleet band from hour zero, which is what lets it draw the dotted opening segment). That information travels in the parquet metadata and `pd.read_parquet` discards it. If it is lost the chart **does not fail**: it falls back to default values and paints the coloured zones at different boundaries than the ones used for classification. The failure is silent.

### Columns

| Column | What it is |
|---|---|
| `Unit`, `Fecha` | unit and day |
| `ciclo` | component life number; increments on every replacement |
| `curva` | key of a full life, `"CA-44 - ciclo 2"` |
| `componentHours_filled` | component hours that day (X axis of the chart) |
| `ranking` | risk for the day, not accumulated |
| `ranking_acumulado` | running sum within the cycle; starts at ~0 |
| `offset_curva` | vertical shift so the curve starts at the fleet mean |
| `ranking_acumulado_ajustado` | **the column that is plotted and classified on** |
| `banda_media`, `banda_umbral` | fleet mean and threshold at that point's hours |
| `estado` | zone of the point: `Normal` / `Alerta` / `Anormal`, or null if it falls outside the band's domain |
| `es_vigente` | `True` if this is the unit's current cycle |
| `zona_final` | status of the last point of the current curve, repeated across all its rows; null on historical ones |
| `componente` | `motor` or `transmision` |

**The two nulls mean different things**: a null `estado` is "outside the band's domain", a null `zona_final` is "historical curve, not current".

**The X axis is hours, not dates.** The curve is plotted against `componentHours_filled` because wear depends on component hours, not on the calendar.

---

## 6. The intelligent analysis (`failure_mode_diagnosis`)

> **Status: published.** This is the public contract for the weekly Capstone
> predictive analysis. The existing `analisis_inteligente.parquet` remains
> frozen and is not regenerated.

### What it is

For each unit and each failure mode above threshold, a written diagnosis: what is probably causing it and what to do about it. It replaces the previous `analisis_inteligente`, which stored a single diagnosis per unit covering only its worst mode.

One row per **unit × flagged mode**. A unit with no mode above threshold does not appear in the file that week — there is no empty row and no filler text.

### Columns

| Column | What it is |
|---|---|
| `Unit` | unit identifier |
| `Fecha` | date of the data the analysis was run on |
| `failure_mode` | the mode diagnosed, one of those declared in `FAILURE_MODE_CONFIG` |
| `probable_cause` | text: the probable cause of the observed behaviour |
| `recommended_actions` | string containing a JSON array of ordered actions |
| `analysis_status` | `ok` / `fallback_rules` / `error` |

### `analysis_status`

Tells you how the diagnosis was produced, and the interface should treat each case differently:

- **`ok`** — the analysis ran normally. Display it as-is.
- **`fallback_rules`** — the model was unavailable and the text came from fixed rules. It is valid but more generic; worth flagging visually so it does not imply more precision than it has.
- **`error`** — the analysis failed. `probable_cause` and `recommended_actions` carry a generic message, **never** the technical detail of the error.

**Never show exception text to the user.** This comes from a real incident: a unit's analysis fields ended up containing a literal `BadRequestError` from a failed call, and it was printed in the report. If `analysis_status` is `error`, show an interface message, not the field's contents.

### How to read it

It is a run snapshot, same as `unit_status_summary`:

```python
diagnoses = leer_ultima_semana(ruta_tabla("predictive", "failure_mode_diagnosis"))
```

For a single unit's detail, filter and sort by the scores carried in `modos_ordenados` from the summary:

```python
import json

row = summary[summary["Unit"] == "CA-44"].iloc[0]
scores = json.loads(row["modos_ordenados"])

detail = diagnoses[diagnoses["Unit"] == "CA-44"].copy()
detail["score"] = detail["failure_mode"].map(scores)
detail = detail.sort_values("score", ascending=False)
```

That way the diagnosis table follows the same severity order the summary shows.

### How it connects to the rest

The three artefacts join on `Unit` and `failure_mode`:

- **`unit_status_summary`** says how many modes are flagged and which is the worst.
- **`failure_mode_diagnosis`** says what is going on with each of those modes.
- **`FAILURE_MODE_CONFIG`** (section 7) says which signals to plot as evidence.

`modes_over_threshold_count` from the summary should match the number of rows for that unit here. If it does not, that is a data problem and the interface should surface it rather than showing both numbers as if nothing happened.

### Implemented contract

- The initial `flag_threshold` is **35**, versioned in the analysis configuration
  and recorded in the run manifest. `estado=normal` does not exclude a unit if
  one of its modes meets the threshold.
- `modos_ordenados` from `unit_status_summary` is the source of current scores;
  `modes_over_threshold_count` must match the generated rows at threshold 35.
- Trends come from the matching `risk_scores` mode. Physical evidence is limited
  to that mode's signals in `FAILURE_MODE_CONFIG`; a missing row means missing
  evidence, never zero risk. `cumulative_risk_curve` is not read directly.
- The model receives all flagged modes for a unit in one structured request. A
  missing or invalid mode is completed by deterministic rules. Technical errors
  stay only in logs and the technical manifest; public fields remain generic.
- The canonical path is:

  ```text
  MultiTechnique Alerts/predictive/golden/capstone/motor/
    failure_mode_diagnosis/year=YYYY/week=WW/part-0.parquet
  ```

  `YYYY` and `WW` come from the `unit_status_summary` run partition. The file is
  written with Zstandard compression and no index, first under `_runs/{run_id}`
  and promoted only after validation. If no modes are flagged, an empty Parquet
  with the same schema is published.

The current dashboard still reads the frozen legacy file. Migrating it to this
contract is a separate follow-up task.

### Credenciales de ejecución

En Docker, `Initialize-LocalRun.ps1` transforma el `.env` en `.env.runtime` y
monta las claves como archivos secretos. El generador acepta el mismo patrón:
`AWS_ACCESS_KEY_ID_FILE`, `AWS_SECRET_ACCESS_KEY_FILE`,
`AWS_SESSION_TOKEN_FILE` y `OPENAI_API_KEY_FILE`, con `S3_BUCKET` (o `bucket`)
para el bucket. Las credenciales se cargan sólo en memoria y nunca forman parte
del Parquet ni del manifiesto.

---

## 7. Which signals to show per failure mode

This one is **not** in a parquet: it lives in `FAILURE_MODE_CONFIG`, a Python dictionary imported by the dashboard.

```python
FAILURE_MODE_CONFIG["capstone"]["components"]["motor"]["blowby_risk"]
# {'label': 'Blow-by / Desgaste de Anillos',
#  'signals': ['Cromo', 'Hierro', 'Hollín', 'crankcase_pressure_inh2o', 'oil_level_pct']}
```

And the catalogue says where each signal comes from and how to display it:

```python
FAILURE_MODE_CONFIG["capstone"]["signals"]["crankcase_pressure_inh2o"]
# {'technique': 'telemetry', 'label': 'Presión Cárter', 'unit': 'inH2O'}
```

That is what drives the dropdown: pick a mode, filter its signals, and `technique` tells you which table to read each one from.

```python
cfg = FAILURE_MODE_CONFIG["capstone"]
mode = cfg["components"]["motor"]["blowby_risk"]

for name in mode["signals"]:
    s = cfg["signals"][name]
    path = ruta_tabla(s["technique"], "signal_daily_status")
    series = leer_ultimas_semanas(path, n=13).query("signal_name == @name")
    # plot with s["label"] in the legend and s["unit"] on the axis
```

Signal names and labels are in Spanish (`Hierro`, `Presión Cárter`) because they are the canonical keys used by the oil-limits table. They are identifiers, not display copy that can be rewritten.

---

## 8. Why it is organised this way

**Long format instead of one column per signal.** There used to be ~250 columns with the name encoded in them (`OPERACIONAL_CON_CARGA_oil_diff_pressure_psi_alert_rate`). Now adding a signal or a failure mode is one more row, not a schema change — the dashboard does not break when it happens.

**`year=` / `week=` partitions in Hive format.** That is what lets `pyarrow` read only the weeks requested. In a test with 38 weeks loaded, asking for the last 13 opened 13 files and skipped the other 25. Without it you would have to read everything and filter afterwards.

**Year and week as separate integers, not as a `Week33Year2026` string.** Two integers support ranges (`week >= 30`) and do not break across a year boundary. With a string you can only ask for exact equality.

**"Last N weeks available", not "last 90 calendar days".** `semanas_disponibles` lists the partitions that actually exist and takes the last ones. If a run was delayed, the dashboard still shows the most recent data instead of coming up empty.

**The curve stores the full history in every partition.** It weighs under 1 MB, so instead of accumulating increments it is recomputed whole each week. That keeps the fleet band consistent across all points and makes it reproducible exactly which curve was shown on any given week.

**`unit_status_summary` all in one partition.** Time series partition by the date of the data; the summary partitions by the week of the run. That way a single read always brings the full fleet, including units that stopped reporting.

**No row = no data.** Long format naturally distinguishes "no measurement" from "measurement of zero", which was easy to confuse with columns and NaN.

---

## 9. Practical notes

**Cache `semanas_disponibles`.** It performs a listing on S3 every time it is called. It is fast, but if it runs on every user interaction it is worth caching and refreshing once per run.

**13 weeks is 91 days, not exactly 3 months.** If a week is missing because of an ingestion outage, the last 13 weeks *with data* may span more calendar time. If that matters, filter by `Fecha` after reading.

**The summary's `estado` already comes from the curve.** `unit_status_summary.estado` is the cumulative curve's status lowercased, so the cards and the curve chart agree. The `estado` column in `cumulative_risk_curve` keeps its original capitalisation (`Normal` / `Alerta` / `Anormal`) and is per point, not per unit. The one that **can** disagree is `estado_umbral`, and that is deliberate: it is the previous criterion, kept for auditing.

**`Fecha` comes back as a `date` object**, not as text and not as `datetime64`. If you need to do date arithmetic, convert with `pd.to_datetime`.

**`cambio_estado` holds `sí` / `no`**, with the accent, not `yes` / `no`. It is a stored value, so compare against the literal.
