# translate_text_fields.py: usage guide

Offline script that translates the dashboard's long Spanish text columns (AI recommendations, alert
messages, predictive and telemetry comments) into English with an OpenAI model. Each translation is stored
next to the original as `<column>_eng` (for example `mensaje_ia` -> `mensaje_ia_eng`). The dashboard shows
`_eng` when the UI language is English and falls back to the Spanish text when `_eng` is empty.

The script never runs from the dashboard. Run it by hand or on a schedule.

Reference docs: `documentation/general/translation_text_fields.md` (design, mapping table, limits).
Mapping of files and columns: `scripts/translation_mapping.json`.

## Requirements

Run everything from the project root.

| Variable (in `.env` or the environment) | Needed for |
|---|---|
| `OPENAI_API_KEY` | every run except `--list` |
| `BUCKET_NAME`, `ACCESS_KEY`, `SECRET_KEY` (or `STAGE_NAME` on AWS) | full runs that upload to S3 |

Python packages are already in `requirements.txt` (`openai`, `pandas`, `pyarrow`, `boto3`, `tqdm`).

## The three-step workflow

### 1. Preview (free, no API calls)

```bash
python scripts/translate_text_fields.py --list
```

Prints every file that would be processed, the rows in scope, the unique texts and the characters. Use it to
check the date window and the file list before spending anything.

### 2. Demo (cheap, never touches S3)

```bash
python scripts/translate_text_fields.py --demo
```

* Translates 20 random rows per file (`--demo-rows N` to change, `--seed N` to get another sample).
* Does not create an S3 client and does not read S3 credentials.
* Output goes to `scripts/output/translation/demo/`:
  * the complete files with `_eng` filled for the sampled rows only,
  * `demo_review.csv`: Spanish and English side by side, open it in Excel to judge quality,
  * `report.json`: counts, tokens, approximate cost, failures.

To see the demo in the dashboard, copy `scripts/output/translation/demo/` over your local `data/` (or point
`DASHBOARD_DATA_ROOT` at a copy) and switch the UI to English. Sampled rows show English, the rest show Spanish.

### 3. Full run (translates and replaces the files in S3)

```bash
python scripts/translate_text_fields.py
```

It prints the plan and asks you to type `yes`. Then, for each file:

1. downloads the version that is in S3 right now,
2. translates every row in scope,
3. uploads it back to the same key, only if the file did not change in S3 in the meantime.

Afterwards open `scripts/output/translation/full/report.json`. Every entry under `uploads` should say
`uploaded`. The exit code is non-zero if any text failed or any upload was skipped.

## Which rows are translated

By default only rows dated within the **last 365 days** (the row's own date: `sampleDate` for oil,
`Timestamp` for alerts, `Fecha` for predictive, `evaluation_timestamp` for telemetry). Older rows keep a blank
`_eng` and show Spanish.

```bash
--since-days 180      # shorter window, faster and cheaper
--all-dates           # no window: every row
```

For predictive and telemetry only the latest `year=/week=` partition is processed, because that is the one the
dashboard reads.

## Options

| Option | Meaning |
|---|---|
| `--list` | show the plan and exit |
| `--demo`, `--demo-rows N`, `--seed N` | demo mode and its sample |
| `--clients cda emin` | only these clients |
| `--targets alerts_consolidated ...` | only these mapping targets (ids are in `translation_mapping.json`) |
| `--since-days N`, `--all-dates` | date window |
| `--model NAME` | OpenAI model (default `gpt-5-nano`, the cheapest) |
| `--workers N` | parallel API calls (default 16) |
| `--retries N` | retries for a rejected or failed translation (default 3) |
| `--no-upload` | full run without any S3 access; files are only written locally |
| `--in-place` | also write the translated files over the local copies in `data/` |
| `--force` | upload even if the S3 file changed while translating |
| `--yes` | skip the confirmation prompt (needed without a terminal) |
| `--data-root PATH`, `--output-dir PATH` | change the data folder or the output folder |
| `--reasoning-effort LEVEL` | for `gpt-5*` models (default `minimal`; `none` omits it) |

## Common recipes

```bash
# One file type only
python scripts/translate_text_fields.py --targets alerts_consolidated

# Predictive files only
python scripts/translate_text_fields.py --targets predictive_unit_failure_analisis predictive_mode_failure_analisis predictive_analisis_inteligente_legacy

# One client
python scripts/translate_text_fields.py --clients cda

# Translate and keep the result local (no S3), e.g. to test in the dashboard
python scripts/translate_text_fields.py --no-upload --in-place

# Quality is not good enough: try another model (cache is per model)
python scripts/translate_text_fields.py --demo --model gpt-4.1-nano
```

## Output folder

`scripts/output/translation/` (ignored by git):

| Path | Content |
|---|---|
| `demo/`, `full/` | translated files (same paths as under `data/`), `report.json`, `demo_review.csv` (demo only) |
| `full/_s3_source/` | the S3 copies that were downloaded and translated |
| `translation_cache.jsonl` | every finished translation, keyed by model + prompt version + text |

## Cost, speed and reruns

* Identical texts are translated once and cached. A rerun, or a full run after a demo, only pays for texts it
  has not seen. Deleting `translation_cache.jsonl` forces everything to be translated again.
* If a run stops halfway, run it again: finished texts come from the cache.
* A demo of 20 rows per file costs around one cent; a full run on the current data is under a dollar (the report
  shows the approximate cost). Alert messages are about 95% of the volume, so `--since-days` is the main lever.

## What gets checked

Each translation is validated before it is stored: not empty, plausible length, not the Spanish text echoed
back, and unit ids / signal names unchanged. The Spanish section labels the dashboard parsers rely on
(`DIAGNÓSTICO:`, `CAUSA PROBABLE:`, `Acción:`, ...) are protected, and JSON columns stay valid JSON. A rejected
translation is retried, then left blank and listed in `report.json`; the dashboard shows the Spanish text for it.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `OPENAI_API_KEY is not set` | add it to `.env` or the environment |
| Upload says `skipped: no object at this key` | the file does not exist in S3; the script only replaces existing files |
| Upload says `S3 version changed while translating` | the pipeline published a new version meanwhile; run again (cached texts are free) or use `--force` |
| Translations disappear after restarting the dashboard | the file never reached S3 and `SYNC_DATA=True` re-downloaded the Spanish original; check `uploads` in `report.json` |
| Dashboard still shows Spanish for new data | the pipeline rewrote the file without `_eng` columns, or a newer week partition appeared; run the script again after each publish |
| Some rows stay Spanish | they are older than the window, or their translation failed (see `failures` in `report.json`) |
| `FileNotFoundError` on Windows with very long paths | use a shorter `--output-dir` |

## Adding a new column or file

1. Add a target to `scripts/translation_mapping.json` (path, format, `date_column`, `columns`).
2. Read the column where the dashboard shows it with `localized_value` / `localized_series` from
   `src/i18n/data_text.py`.
3. Add a case to `tests/test_data_text.py`.
