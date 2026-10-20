# English translation of long text fields

Some data files carry long Spanish prose written by the pipelines (AI recommendations, alert
messages, predictive diagnoses). The UI language toggle (`i18n.md`) cannot translate those at
display time, so they are translated **offline** with an LLM and stored next to the original as
`<column>_eng`. The dashboard only chooses which column to show.

| Piece | Where |
|---|---|
| File -> column mapping (machine-readable input of the script) | `scripts/translation_mapping.json` |
| Translation script | `scripts/translate_text_fields.py` |
| Column choice at display time | `src/i18n/data_text.py` (`localized_value`, `localized_series`, `is_eng_column`) |
| Tests | `tests/test_translate_text_fields.py`, `tests/test_data_text.py` |

The script is never imported or triggered by the dashboard.

## Mapping (file -> columns)

Paths are relative to `data/`; with the prefix `MultiTechnique Alerts/` they are the S3 keys.

| Target id | File | Columns translated | Rendered in |
|---|---|---|---|
| `oil_classified` | `oil/golden/{client}/classified.parquet` | `ai_recommendation` | Oil > Fleet overview (heatmap tooltips, machine detail table); Oil > Report detail (Diagnóstico/Acción boxes, comment history) |
| `oil_machine_status` | `oil/golden/{client}/machine_status.parquet` | `machine_ai_recommendation` | Oil > Fleet overview (machine recommendation card) |
| `alerts_consolidated` | `alerts/golden/{client}/consolidated_alerts.csv` | `mensaje_ia` | Alerts > General view (table), Alerts > Detailed view (case header) |
| `predictive_unit_failure_analisis` | `predictive/golden/{client}/{component}/unit_failure_analisis/year=*/week=*/*.parquet` (latest week) | `diagnostico`, `causa_probable`, `acciones` | Predictive > Evidence (unit "Análisis inteligente" panel) |
| `predictive_mode_failure_analisis` | `predictive/golden/{client}/{component}/mode_failure_analisis/year=*/week=*/*.parquet` (latest week) | `diagnostico`, `probable_cause`, `recommended_actions` | Predictive > Evidence (stand-in panel for units without a unit narrative) |
| `predictive_analisis_inteligente_legacy` | `predictive/golden/{client}/analisis_inteligente.parquet` | `diagnostico`, `causa_probable`, `acciones` | Predictive > Evidence, only for clients not yet on the v2 layout |

Not translated, on purpose:

* **Predictive > General** renders no long text column (state, ranking and curves only).
* `breached_essays` (JSON of essay names/values; the names are translated at display time),
  `component_details` (nested struct, read only by Overview), `observaciones`, `limitacion`,
  `limitation` (not rendered anywhere), `modos_ordenados` (JSON of scores).
* Every other file under `data/`, including maintenance (`mantentions/`) evidence shown inside
  EMIN alerts, telemetry comments and Overview.

To add a column, add it to `scripts/translation_mapping.json`, read it at its display site through
`localized_value` / `localized_series`, and add a case to `tests/test_data_text.py`.

## Running it

Needs `OPENAI_API_KEY` (environment or `.env`). The upload also needs `BUCKET_NAME` and
`ACCESS_KEY`/`SECRET_KEY` (or `STAGE_NAME` on AWS) — the same variables as `src/data/s3_downloader.py`.

```bash
python scripts/translate_text_fields.py --list     # what would be processed, no API calls
python scripts/translate_text_fields.py --demo     # 20 rows per file, NO S3 at all
# review scripts/output/translation/demo/demo_review.csv and report.json
python scripts/translate_text_fields.py            # full run, asks for confirmation, then replaces files in S3
```

By default only rows dated within the **last 365 days** are translated (`--since-days N` to change it,
`--all-dates` to translate everything). The date is the row's own date, taken from the `date_column` of each
mapping target: `sampleDate` (oil samples), `latest_sample_date` (machine status), `Timestamp` (alerts), `Fecha`
(predictive). Older rows, and rows whose date cannot be read, keep a blank `_eng` and show Spanish in the
dashboard. The window is applied before the demo sample is drawn. On the current data it cuts the unique texts
from about 12,000 to about 6,400; alerts (`mensaje_ia`, 400–1,400 characters each) are ~95% of what remains, so
a shorter `--since-days` (e.g. 180) is the lever if the run is still too slow. `--workers` (default 16) sets
the number of parallel API calls.

Useful flags: `--clients cda emin`, `--targets alerts_consolidated`, `--model`, `--workers`,
`--seed` (demo sample), `--no-upload` (full run without S3), `--in-place` (write over the local
copies under `data/`), `--yes` (skip the confirmation), `--force` (see Safety).

### Demo mode

* Translates `--demo-rows` (default 20) rows per file — a reproducible random sample of the rows that
  have text; files with fewer rows are translated whole.
* **Never touches S3**: no S3 client is created and no credentials are read.
* Writes the **complete** file plus the `_eng` columns (filled for the sampled rows only) to
  `scripts/output/translation/demo/<same path as under data/>`, and a side-by-side
  `demo_review.csv` (Spanish | English) for quality review.
* To see it in the dashboard, copy that tree over a local `data/` (or point `DASHBOARD_DATA_ROOT` at a
  copy) and switch the UI to English: sampled rows show English, the rest fall back to Spanish.

Full mode uses exactly the same translation code; only the row scope (all rows) and the S3 step differ.

### Full mode and S3

After translating, each file is uploaded to the key it came from, replacing it. Safety checks, per file:

* **No new keys**: if there is no object at that key, the file is skipped.
* **No lost upstream updates**: if the S3 object is newer than the local source file (the pipeline
  published since `data/` was last synced), it is skipped. Sync `data/` and re-run, or pass `--force`.
* Skipped uploads and translation failures make the exit code non-zero and are listed in `report.json`.

## Translation rules

* Model: `gpt-5-nano` with `reasoning_effort=minimal` — the cheapest OpenAI text model at the time of
  writing (about $0.05 / $0.40 per 1M input/output tokens; `gpt-4.1-nano` and `gpt-4o-mini` are the
  next steps up). The whole dataset is a few thousand unique texts, i.e. well under a dollar. If the
  demo review shows the quality is not acceptable, rerun with `--model gpt-4.1-nano` (the cache is
  keyed by model, so nothing stale is reused).
* Identical texts are translated once (many recommendations repeat) and every result is cached in
  `scripts/output/translation/translation_cache.jsonl`, so reruns and the demo -> full step cost nothing for
  texts already done. Bump `PROMPT_VERSION` in the script when the prompt changes.
* **Structure is preserved** so the existing parsers keep working on `_eng`:
  * the Spanish section labels the parsers key on (`DIAGNÓSTICO:`, `CAUSA PROBABLE:`, `ACCIONES …:`,
    `Diagnóstico:`, `Acción:`) are kept verbatim — they are delimiters and are never displayed; only the
    text after them is translated. The script swaps each label for a `[[n]]` token before calling the
    model and restores it afterwards, so this does not depend on the model's behaviour;
  * JSON columns (`acciones`, `recommended_actions`) stay valid JSON: each string item is translated;
  * unit ids, signal identifiers (`EngCoolTemp`, `abrasive_wear_risk`) and codes are copied, not translated;
  * decimal commas become points (`1,0 ppm` -> `1.0 ppm`).
* Each result is validated (not empty, plausible length, not the Spanish text echoed back, labels and identifiers intact). A rejected
  translation is retried with the reason, then left **blank** and reported; it never writes a bad value.
* Original columns, dtypes, Parquet compression, CSV encoding (BOM) and line endings are unchanged.

## Dashboard behaviour

* English selected and `<column>_eng` has text -> the English text. Spanish selected -> the original
  column, unchanged.
* **Fallback (decision taken, easy to change in `data_text.py`)**: a missing column, null or blank
  `_eng` shows the original Spanish text, so nothing renders blank while translation is partial.
* Only the display sites listed in the mapping read `_eng`. Other readers (Overview, Unit Summary,
  Campbell AI, telemetry) keep reading the Spanish columns. `_eng` columns are excluded from the
  essay-column scans of Oil > Report detail.
* The text under the labels is shown translated, but values the dashboard rewrites itself
  (`_translate_signal_text` swaps signal keys for their label in the current language) behave as before.

## Limits and follow-ups

* **Upstream regeneration overwrites `_eng`.** The pipelines rewrite these files (alerts and oil
  every run, predictive every weekly partition) without the `_eng` columns, so a translation lasts only
  until the next publish. Until the pipeline carries `_eng` through (or a scheduled run of this script
  follows each publish), rerun the script; the cache makes a rerun cheap because unchanged texts are not
  re-translated.
* Only the **latest** predictive week is translated (the one the dashboard reads).
* Not implemented (out of the current scope): automatic retry queue for failed rows and detecting
  changed Spanish text beyond the cache (a changed text simply gets a new translation on the next run).
