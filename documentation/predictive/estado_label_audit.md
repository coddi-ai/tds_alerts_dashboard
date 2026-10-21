# Audit: where the unit "Estado" label comes from (Predictivo)

Status: **decision taken (see [Decision](#decision-general-estado))**; the §1 rule still needs
backend confirmation (see [Open questions](#open-questions)).

## Decision: general Estado

The `Estado` on the Evidencia banner **and** in the Riesgo por Modo de Falla table is the worse of
the short-view `unit_status_summary.estado` and the long-view `cumulative_risk_curve.estado` of the
unit's active cycle (Normal < Alerta < Anormal). It is computed once by `attach_general_status()`
(`tab_predictive_overview.py`, built on `combine_states`) into `latest["general_status"]`.

- `latest["status"]` keeps the short view's own value: the Short View scatter and the charts still
  style each point with their own source's `estado`, as the contract asks.
- A unit with no curve (or a client with none) keeps its short-view state; it is never read as Normal.
- The Resumen KPI counts already used this rule, so the table, banner and KPI cards now agree.
- The failure-mode score cells are unchanged: they classify a mode score, not the unit.

The sections below describe the state of the code **before** this change (§1 and §2 are the two
inputs; §3's `Estado` column is now the general Estado).

## 1. Source of the unit `Estado`

One value per unit, `status`, set by `attach_status()` in
`dashboard/tabs/tab_predictive_overview.py`. Every surface reads it from there: the Evidencia
unit banner (`update_unit_banner` in `dashboard/callbacks/predictive_callbacks.py`), the
`Estado` column of Riesgo por Modo de Falla, the Short View scatter and the priority cards.

Resolution order, first hit wins:

1. `unit_status_summary.estado`, loaded by `predictive_v2.load_unit_status_summary(client, component)`.
2. `analisis_inteligente.parquet` `estado` (`get_latest_analisis_inteligente`), for components not
   yet on the v2 layout (e.g. `cda/transmision`).
3. `"Sin Datos"` when the unit is in neither. A missing unit is never shown as `Normal`.

`COMPUTE_STATUS = False` (same module) keeps the client-side `_classify_status_from_scores`
override off; the dashboard reads `estado` as delivered.

### How the backend computes `unit_status_summary.estado`

Data contract §6 (`predictive_data_contracts.md`, "unit_status_summary.estado"): each unit-day is
placed on two axes, the day's `ranking` and its 30-day mean `media_30d`, each compared with a
fixed per-client threshold (`UMBRAL_DIA`, `UMBRAL_30D`, the 80th percentile of the client's
history, frozen).

| `media_30d` high | `ranking` high | `estado` |
|:-:|:-:|---|
| yes | yes | `anormal` |
| yes | no | `alerta` |
| no | yes | `alerta` |
| no | no | `normal` |

Consequences:

- **`ranking_7d` and `ranking_90d` do not feed `Estado`.** The inputs are the daily `ranking` and
  `media_30d`. The two Evidencia tiles that show 7d and 90d can therefore look "worse" or
  "better" than the Estado beside them without either being wrong.
- No single failure mode feeds it (`peor_modo` / `modos_ordenados` surface that case).

## 2. Does it include the Curva Acumulada?

**No.** The curve has its own field, `cumulative_risk_curve.estado` (Title Case; the curve's
last-point zone against the fleet reference band). The contract states the two can disagree for the
same unit and must be labelled distinctly.

The code keeps them separate:

- Charts style each point with their own source's `estado` (`dashboard/components/predictive_state.py`).
- The only place they meet is `combine_states` / `general_states`: the worse of the two, used **only**
  for the Resumen KPI counts. It never overwrites `status`.

So the hypothesis in the requirement is half right: Estado does not use the curve, but it is also
not derived from `ranking_7d` x `ranking_90d`.

## 3. Riesgo por Modo de Falla: what labels it uses

The table (`_failure_table`) mixes three different rules in a row:

| Cell | Rule |
|---|---|
| `Estado` column | `status` above (same as the banner) |
| Ranking column | fixed 40 / 70 score colors (`_score_cell_style`) |
| Each failure-mode cell | per-mode criticidad band (Saludable / Monitoreo / Prioridad alta / Crítico) from the client's calibrated P75/P90/P98 edges (`config/umbrales_criticidad/<client>.json`, `get_mode_thresholds`), falling back to fixed 35 / 55 / 75 |

The mode cells carry **colors only**; the same bands (with names) drive the Calendario de estado. The `Estado` column is already the same value as the banner, so the two surfaces named in
the requirement already agree with each other. What differs is the mode cells, which classify a
score and not a unit.

## Open questions

1. **Backend:** confirm the §6 rule above is what runs in production. The contract's threshold
   table (`UMBRAL_30D`, `UMBRAL_DIA` for `capstone/motor` and `cda/motor`) is still "to fill".
2. **Product:** the failure-mode score cells still use per-mode criticidad bands. Say if they
   should follow the general Estado too; that needs a definition first, since they are per-mode scores.
