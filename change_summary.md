# Change summary — partitioned alert storage (Parquet, one file per week)

The Alertas views no longer load the whole `consolidated_alerts.csv`. A scheduled script splits it
into Parquet files and the views read only the weeks their filters need. What the views show is
unchanged; what changes is how much data is read to show it.

## What changed

**Storage.** `data/alerts/golden/{client}/{week}/file.parquet`: one file per Monday-week holding every
unit, with the CSV's columns, dtypes, values and row order. `{week}` is the ISO date of the Monday
(`2026-10-19`), computed exactly like the *Evolución temporal* bars. A small `_alert_index.parquet`
(one light row per alert) feeds the filter options and finds one alert by id. The CSV stays where it
is and is never modified.

> **Deviation from the ticket's wording.** The ticket says `{week}/{unit}/file.parquet`. I first built
> that and then measured it: capstone has ~91 alerts per week spread over 49 units, so unit files held
> ~5 rows each (1,227 files, 17 MB for a 7.7 MB CSV). One file per week is 69 files / 1.75 MB, reads
> faster (see below), and removes the need to read other units separately for *Distribución por
> unidad*. `Unidad` is applied as a row filter on the loaded weeks. The ticket text and the acceptance
> criterion "one unit and 4 weeks reads only the matching `{week}/{unit}` partitions" need to be updated
> to match; the layout lives in one module (`src/data/alert_partitions.py`) if the team prefers to go back.

**Weekly script** — `scripts/partition_alerts.py`. Every **Wednesday 04:00, `America/Santiago`**
(explicit, configurable) it rebuilds every client's partitions: only those whose content changed are
rewritten (the in-progress week included), partitions the CSV no longer yields are removed, and the run
is idempotent. Files are swapped in atomically, so a reader never sees a half-written one. It then
**syncs the regenerated partitions to S3**
(`{bucket}/MultiTechnique Alerts/alerts/golden/{client}/{week}/file.parquet`). A failed upload is
logged, the run exits 2, local files stay valid, and the next run retries. Runs as the
`alerts-partitioner` service in `docker-compose.yml`; the ECS equivalent is an EventBridge rule
`cron(0 4 ? * WED *)` (America/Santiago) running the same image.

**Read path.** Vista General: `Desde`/`Hasta` pick the weeks; `Unidad`, Sistema and Señal are applied on
the loaded rows. Vista Detallada: same, plus the selected alert is read from its single week file. Neither
view opens the CSV (a test deletes it and exercises both). The old and new paths do not coexist inside
the views.

**`Fecha desde` default.** Vista Detallada opens on the start of Vista General's "Últimas 4 semanas"
(same `default_alert_dates()` calculation) instead of "Sin límite", so opening it reads ~5 weekly files.
"Sin límite" is still selectable and loads the full history.

## Optional S3 backfill (off by default)

```
python scripts/partition_alerts.py --backfill                # 1. all history, local only
#   (--validate runs by default: row totals, columns, dtypes, values and placement vs the CSV)
python scripts/partition_alerts.py --backfill --sync-s3      # 2. only after validating locally
python scripts/partition_alerts.py --verify-s3               # 3. S3 == local (paths, sizes, hashes, row counts)
```

Never implicit. Bucket/prefix come from `ALERT_PARTITIONS_S3_BUCKET` (falls back to `BUCKET_NAME`) and
`ALERT_PARTITIONS_S3_PREFIX`, shared with the weekly run. The sync only uploads what is missing or
different, so it can be re-run without duplicates or partial uploads. **Sequencing is enforced:** step 2
writes `_backfill_complete.json`, and the weekly sync refuses to run for a client without it.

**Status (2026-11-18):** steps 1–3 were run for all three clients against
`s3://teck-cda-datasource/MultiTechnique Alerts/alerts/golden/`: capstone 69 partitions + index, cda 54,
emin 50 (6,258 / 152 / 235 rows, equal to the CSVs). `--verify-s3` reports S3 identical to local, and an
immediate weekly run uploaded 0 files. Pre-existing objects under those prefixes (`backtest/`, the CSVs)
were not touched.

## Impact on response time

Measured on `capstone` (6,258 alerts, 69 weeks, 49 units), default filters (last 4 weeks, ≈214 alerts),
callbacks invoked directly on a developer laptop (Windows, pandas engine; Polars is not installed here).
"Cold" = first call in a fresh process, median of 3; "warm" = median of 5 repeats.

| Interaction | Before: cold / warm | After: cold / warm | Change (cold) |
|---|---|---|---|
| **Vista General** — open (filters + all charts + table) | 8,498 ms / 7,662 ms | 590 ms / 165 ms | **−93 %** |
| Vista General — one unit selected | 7,238–10,151 ms / ~7,500 ms | 45–51 ms / 46–48 ms | −99 % |
| **Vista Detallada** — open | 421 ms / 20 ms | 143 ms / 17 ms | **−66 %** |
| Vista Detallada — "Sin límite" (full history) | ~420 ms first, then 17 ms | 54–57 ms every time | −87 % (vs first call) |

Reading the numbers:

- **Vista General** is where the time was: it parsed and decorated all 6,258 alerts on every interaction.
  Reading and normalising the ≈214 loaded alerts now takes ~11 ms. Two render-side fixes, with identical
  output, took the refresh from ~0.9 s to ~0.17 s: the signal-name translation in the alert table/IA parser
  ran one regex per signal name (88) per message and now runs a single compiled pattern (verified equal on
  17,840 real texts), and `alert_summary` no longer re-prepares rows the view has already prepared. What is
  left is ~35 ms for each chart, ~50 ms for the table and ~35 ms of row preparation.
- **Estimate for growth.** Before, cost grew ~1.3 ms per alert of history (8.1 s for 6.3 k alerts; a
  20 k-alert history would be ~25 s). After, at default filters it depends on the alerts in the loaded
  weeks, not on the history: opening either view stays at roughly today's figure however old the data
  gets. Only "Sin límite" still scales with history (~55 ms per 6 k alerts).
- Nothing is cached by the new path. With one file per week every case, warm Detallada included, is at
  or below the old cached figure, so caching is no longer needed for the views to be faster.
- Disk and S3: capstone is 69 files / 1.75 MB (the CSV is 7.7 MB); S3 holds 70 / 55 / 51 objects for
  capstone / cda / emin. A full rebuild takes ~2 s (it took ~22 s with unit files).

## Verification

- **Same output as before:** 120 snapshots (KPIs, the three charts, table, filter text, selector options, alert
  detail) for capstone, cda and emin were taken on the original code and are byte-identical on the final
  code. The suite also runs the previous General algorithm over the CSV and compares it with the view for 13
  filter scenarios, and compares the selector with the old `_filter_alerts` output.
- **Local backfill validated:** row totals per client equal the CSV, columns, dtypes and values match, a re-run
  rewrites 0 files.
- **S3:** verified against the real bucket (`--verify-s3`); the failure/retry, stale-deletion and guard paths are
  tested with an in-memory S3 double, not forced on the real bucket.

## Decisions and open points for the team

1. **Layout differs from the ticket** (week-only, see above). Needs the ticket's wording and acceptance criterion
   updated, or a decision to go back to unit folders.
2. **Other consumers still read the CSV** (Hot Sheet, Menace Control, Fleet overview, Unit summary, the
   alert-summary e-mail). Between runs their numbers can be fresher than the Alertas views'. Migrating them is
   out of this scope.
3. **Freshness is weekly.** A running dashboard only sees new partitions if it shares the script's data volume or
   restarts (the S3 → `data/` sync happens at startup). Deployed dashboards will download the new objects (~176)
   at their next startup sync.
4. **Not done, optional:** the table is still one 520 KB payload (about half is the Diagnóstico/Acción text stored
   twice, in the row and in its tooltip) and the browser-side render of the table was not measured. If it feels slow
   in the browser, split the table into its own callback and trim the payload. Caching partitions is not needed.
5. `codebase.md` does not exist in the repo; the equivalent file, `documentation/codebase_explaining.md`, was updated.
