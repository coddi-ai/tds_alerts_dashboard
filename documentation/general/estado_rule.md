# Estado rule: how a technique's and a unit's Estado are decided

Applies to the General tab: Fleet Overview and Unit Detail. The rule is applied once a day by a scheduled run that
writes the result to a golden file (section 6); the tab only draws that file. Single code location:
[`config/estado_rules.py`](../../config/estado_rules.py) (constants plus the functions
`technique_estado` and `unit_estado`). Data-age thresholds stay in
[`config/freshness_thresholds.py`](../../config/freshness_thresholds.py).

A rule exists, so this document describes it; it does not propose a new one. Section 5 lists
the levers stakeholders can pull, with their effect on a real unit.

## 1. The three layers

| Layer | Where it happens | Inputs | Output |
|---|---|---|---|
| 1. Components -> technique status | **Upstream data pipelines** (the dashboard reads the result) | per-component readings | Technique status: Normal / Alerta / Anormal |
| 2. Technique status x data age -> technique Estado | `technique_estado` in `config/estado_rules.py` | layer 1 status; data-age tier from `FRESHNESS_CRITERIA` | Technique Estado |
| 3. Technique Estados -> unit Estado | `unit_estado` in `config/estado_rules.py` | layer 2 Estados | Unit Estado (band) |

### Layer 1: components in Alerta (upstream)

| Technique | Source file / field | Roll-up |
|---|---|---|
| Tribología | `data/oil/golden/{client}/machine_status.parquet`: `overall_status`, `machine_score`, `component_details` | Each component gets points: Normal 0, Alerta 2, Anormal 5, multiplied by a criticality weight (motor 2.0, convertidor and diferencial 1.0, the rest 0.25 to 0.5 in current data); machine score = sum. **The machine is the worst status of its components, and Anormal whenever the score reaches 10.** Checked against all 392 machines of the local mirror (`tests/test_fleet_status.py`). The "Normal below 6, Alerta from 6, Anormal from 10" table of `documentation/oil/oil_data_contracts.md` does **not** reproduce the published statuses (a machine with one component in Alerta and score 4 is Alerta, not Normal) and is not what the page prints. |
| Telemetría | `data/telemetry/golden/{client}/unit_health`: `overall_status`; per system `system_health`: `system_status` | Computed by the telemetry pipeline from the systems' scores (`n_anormal_systems`, `n_alerta_systems`, `unit_score`). The exact rule is not in this repository. See `documentation/telemetry/data_contracts.md`. |
| Alertas | computed by the scheduled run: `calculate_alert_criticality_score` (`src/data/fleet_status.py`; limits in `config/estado_rules.py`) | `alert_count x (1 + 0.5 x components_with_alerts)` over 30 days: **no alert in the window is Normal**, up to 15 Alerta, above 15 Anormal (shown as Anormal; there is no separate Crítico). Sin Datos only when the client's feed cannot be read at all (no dated alerts). |
| Predictivo | `unit_status_summary.estado` (short term), worst across the client's predictive components | Delivered by the predictive pipeline. |
| Mantención | `query_10_equipment_status` (SANO / DETENIDO) | **Not a status.** Operational information only. |

The dashboard cannot change layer 1; changing a component weight or the 6 / 10 thresholds
is a pipeline change.

### Layer 2: data age (the staleness rule)

`technique_estado(label, age_tier)` returns the worse of the technique's own status and
what its data age forces:

* The age tier comes from `FRESHNESS_CRITERIA`: **Ok** (fresh), **Atención**, **Preocupante**.
* `STALENESS_FLOOR` maps each tier to the lowest Estado it allows: Ok -> Normal,
  Atención -> **Alerta**, Preocupante -> **Anormal**.
* No reading (Sin Datos / InsufficientData) stays **Sin Datos**: stale or fresh, there is
  nothing to degrade, and it is never shown as Normal. For Alertas, "no alert" **is** a reading (Normal),
  so it takes part in the age rule like any other: with the feed's newest alert older than the limit, units
  with no alerts read Alerta / Anormal as well.
* A data age that cannot be determined leaves the technique's own status in force.

Current thresholds (`FRESHNESS_CRITERIA`; data older than the first limit is Atención,
older than the second is Preocupante):

| Technique | Atención after | Anormal after |
|---|---|---|
| Telemetría | 2 hours | 24 hours |
| Tribología | 20 days | 40 days |
| Alertas | 1 week | 3 weeks |
| Predictivo | 1 week | 3 weeks |
| Mantención | 2 weeks | 4 weeks (only feeds the "Fuentes de datos" availability) |

### Layer 3: the unit

The unit Estado is the **worst technique Estado**. Alertas, Telemetría (if the client has it),
Tribología and Predictivo take part. **Mantención never contributes** (it is in
`NO_STATUS_TECHNIQUES`; before this change it was already excluded from the Estado, so no
unit changed band because of it). If no technique has a reading the unit is **Sin Datos**.
Inside a band, units are listed in natural ascending ID order (CA-2 before CA-10); the
alert counts of the last week, 4 weeks and 8 weeks stay in the Alertas explanation.

Fleet Overview's Estado column and Unit Detail's banner, tiles and card chips all read the
same computed snapshot (`fleet_overview.get_unit_snapshot`), so they cannot differ.

## 2. Why T_10 reads Anormal (CDA, local data mirror)

| Technique | Own status (layer 1) | Data age | Age tier | Shown |
|---|---|---|---|---|
| Telemetría | Alerta (Engine Alerta; Transmission, Steering, Brakes Normal) | 101 days (limit 24 h) | Preocupante | **Anormal** |
| Tribología | Alerta (4 of 10 components in Alerta, machine score 6, none Anormal) | 130 days (limit 40 d) | Preocupante | **Anormal** |
| Predictivo | Normal | 101 days (limit 3 weeks) | Preocupante | **Anormal** |
| Alertas | no alert in 30 days: Normal (was Sin Datos before the golden layer) | 140 days (newest alert of the CDA feed; limit 3 weeks) | Preocupante | **Anormal** |
| Mantención | (not a status) | | | not shown |

No component is above Alerta; the Anormal comes entirely from data age. Every one of the
11 CDA units is Anormal for the same reason on this mirror. Unit Detail says so on the
Telemetría card ("Anormal combina el estado general de la unidad y la antigüedad de los
datos..."), with the thresholds read from the same constants.

Worth a decision: Telemetría's 24 h limit assumes a daily feed, while the system and unit
health files are published weekly (`year=/week=` partitions). Even a freshly published week
is older than 24 h for most of the week.

## 3. Where to change it

| To change | Edit |
|---|---|
| Whether stale data forces Alerta / Anormal | `STALENESS_FLOOR` in `config/estado_rules.py` |
| After how long data counts as stale | `FRESHNESS_CRITERIA` in `config/freshness_thresholds.py` |
| Which techniques have a status | `NO_STATUS_TECHNIQUES` in `config/estado_rules.py` |
| Worst-of priorities, Crítico = Anormal | `STATUS_PRIORITY`, `LABEL_TO_RISK` in `config/estado_rules.py` |
| Component weights, 6 / 10 machine thresholds | upstream oil pipeline |

Nothing else needs an edit: the Telemetría explanation sentence (thresholds included) and
the unit Estado are derived from those constants. `tests/test_estado_rules.py` checks that
one edit to `STALENESS_FLOOR` moves Fleet Overview and Unit Detail together.

## 4. Open: horómetro

Unit Detail's banner derives the unit's horómetro from `cleaned_component_hours.parquet`,
which has per-component rows only: the **largest** latest `componentHours_cleaned` of the
unit's components (CDA T_10: 116,846 h, the hydraulic and steering systems; its motor reads
13,785 h because it was replaced). The rule is in `src/data/unit_horometer.py`
(`HOROMETER_RULE`); the team still has to confirm it.

## 5. Levers on the staleness rule, with their effect on T_10

| Option | Change | T_10 telemetría / tribología / predictivo | T_10 unit Estado |
|---|---|---|---|
| A. Current | Stale data forces up to Anormal | Anormal / Anormal / Anormal | **Anormal** |
| B. Cap at Alerta | `STALENESS_FLOOR["Preocupante"] = "Alerta"` | Alerta / Alerta / Alerta | **Alerta** |
| C. Weekly telemetry | Telemetría limits to 8 days / 15 days (others unchanged) | Anormal / Anormal / Anormal (101 days is past 15 days too) | **Anormal** |
| D. Age never changes the Estado | `STALENESS_FLOOR` all Normal (age still shown in tooltips and "Fuentes de datos") | Alerta / Alerta / Normal | **Alerta** |

A keeps the strictest reading (nothing stale looks healthy) but paints a whole stalled fleet
red; B and D keep the band for genuinely alarming components visible; C fixes the weekly-feed mismatch for a healthy pipeline but changes nothing
for T_10 on this mirror, whose data is 100+ days old. None of them is applied: the current rule (A) stays until
stakeholders choose.

## 6. Golden layer: when and where the rule is applied

The General tab does not evaluate the rule when you open it. `scripts/build_fleet_status.py` does, once a day
(10:30 America/Santiago, half an hour after the 10:00 source update; `FLEET_STATUS_TIME`), and writes one file per client:

    data/general/golden/{client}/fleet_status.parquet     one row per unit

* **What it holds** (`src/data/fleet_status.py` lists the columns): the unit's name, its Estado, and for each technique the
  Estado, its own status, the data-age tier, why (`driver`), the age text, the severity value, the spelling the technique's
  own source uses, plus the Alertas counts of the last 1 / 4 / 8 weeks. Everything the table, the tooltips and the Unit Detail
  need, so the view never reads a raw source. When the file is missing or unreadable the tab says the data is not available;
  it does not rebuild it.
* **One row per unit.** `CT-184` (alert feed) and `CT_184` (oil report) are one unit: ids are compared with separators
  normalised (`src/data/unit_ids.py`; `T_09` / `T_9` too) and the unit is named with hyphens. Each technique's result is merged
  into the one row and the unit's Estado is taken from the merged result. The Unit Detail asks each technique's page for the
  unit by the spelling that page knows (`fleet_status.source_units`). Case and inner spaces (`ca-80`, `CA 80`) are not
  normalised.
* **Failure.** A client is written to a temporary file, read back, and swapped in with one atomic replace. If the build or the
  write fails, the previous file stays and no partial file is left; the other clients are not affected; the script exits 1.
  A client with no unit publishes nothing.
* **What "final" costs.** The ages in the file are the ones at the time of the run (the rule above compares them with limits as
  short as 2 h for Telemetría), so a technique whose data turns stale after 10:30 changes state at the next run, not before.
* **Criteria on the page.** The collapsed panel "Cómo se asignan los estados" (`dashboard/components/fleet_criteria.py`) prints
  the limits above from the same constants the run uses (`config/estado_rules.py`, `config/freshness_thresholds.py`).
* **Scheduling and the first run.** The app runs the script (`src/data/partition_scheduler.py`, job `fleet_status`). The data
  folder is mirrored from S3 on every start (`python dashboard/app.py`, unless `SYNC_DATA=False`) and the mirror deletes the
  files S3 does not have - the golden files included - so after every start there is no file until the next 10:30. To avoid
  an empty tab, `dashboard/app.py` builds the missing ones (`--only-missing`) right after the mirror, in every environment
  (not only production); `FLEET_STATUS_SCHEDULER_ENABLED=false` turns that and the 10:30 job off. By hand:
  `python scripts/build_fleet_status.py [--client capstone] [--only-missing]`.
