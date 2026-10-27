# Estado rule: how a technique's and a unit's Estado are decided

Applies to the General tab: Fleet Overview and Unit Detail. Single code location:
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
| Tribología | `data/oil/golden/{client}/machine_status.parquet`: `overall_status`, `machine_score`, `component_details` | Each component gets points: Normal 0, Alerta 2, Anormal 5. Points are multiplied by a criticality weight (motor and transmisión 2.0, convertidor and diferencial 1.0, the rest 0.25 to 0.5 in current data). Machine score = sum. **Normal below 6, Alerta from 6 to under 10, Anormal from 10.** Documented in `documentation/oil/oil_data_contracts.md`, "Machine Score Calculation". |
| Telemetría | `data/telemetry/golden/{client}/unit_health`: `overall_status`; per system `system_health`: `system_status` | Computed by the telemetry pipeline from the systems' scores (`n_anormal_systems`, `n_alerta_systems`, `unit_score`). The exact rule is not in this repository. See `documentation/telemetry/data_contracts.md`. |
| Alertas | computed in the dashboard: `calculate_alert_criticality_score` (`dashboard/callbacks/overview_general_callbacks.py`) | `alert_count x (1 + 0.5 x components_with_alerts)` over 30 days: 0 Normal, up to 15 Alerta, above 15 Anormal (shown as Anormal; there is no separate Crítico). |
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
  nothing to degrade, and it is never shown as Normal.
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
| Alertas | no reading | n/a | n/a | Sin Datos |
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
