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
   alert-summary e-mail). *Superseded:* they were migrated afterwards, see "every alert consumer reads the weekly
   partitions" below.
3. **Freshness is weekly** (EMIN: daily since the change below). A running dashboard only sees new partitions if it shares the script's data volume or
   restarts (the S3 → `data/` sync happens at startup). Deployed dashboards will download the new objects (~176)
   at their next startup sync.
4. **Not done, optional:** the table is still one 520 KB payload (about half is the Diagnóstico/Acción text stored
   twice, in the row and in its tooltip) and the browser-side render of the table was not measured. If it feels slow
   in the browser, split the table into its own callback and trim the payload. Caching partitions is not needed.
5. `codebase.md` does not exist in the repo; the equivalent file, `documentation/codebase_explaining.md`, was updated.

---

# Change summary — every alert consumer reads the weekly partitions; EMIN is partitioned daily

Hot Sheet, Menace Control, Fleet overview, Unit summary, the alert-summary e-mail, the data-source chips, the
source catalog probe and the Campbell AI assistant now read the weekly Parquet partitions through
`src/data/alert_partitions.py`. The whole-CSV loader (`load_alerts_data`) is gone. EMIN's partitions are
regenerated **every day** (its data updates daily); capstone and cda stay weekly.

Decisions received for this change:

1. **EMIN is partitioned daily** (the e-mail schedule check failed for it, see below).
2. Warm-path cost: explained in "Open decisions", still waiting for an answer.
3. **The other CSV readers are redirected too** (data-source chips, catalog probe, Campbell AI).

## Consumer audit (`consolidated_alerts.csv`, runtime code)

| Reader | Status |
|---|---|
| Hot Sheet (`hot_sheet_callbacks.py`) | migrated |
| Menace Control (`menace_control_callbacks.py`, 3 callbacks) | migrated |
| Fleet overview (`fleet_overview.py`: status map, window counts, feed freshness) | migrated |
| Unit summary (`unit_summary_content.py`: alerts card, data date) | migrated |
| Alert-summary e-mail (`src/mailing/alert_summary.py`) | migrated (after the daily-EMIN decision) |
| Data-source freshness chips (`src/data/source_freshness.py`, source `alerts_consolidated`) | redirected: reads the newest weekly partition's `Timestamp` column |
| Source availability probe (`src/data/catalog.py`) | redirected: probes the newest dated weekly partition |
| Campbell AI assistant (`src/campbell_ai/data.py`, dataset `alerts`) | redirected: whole history from the partitions, same frame |
| `config/settings.py` `get_consolidated_alerts_path` | dead code, removed |
| `scripts/translate_text_fields.py` / `translation_mapping.json` | **not a reader: a producer of the CSV.** It downloads the CSV, adds `mensaje_ia_eng` and uploads the CSV back, i.e. it sits *upstream* of the partitioner. Not changed; its README now says to run the partitioner after copying a demo over `data/` |
| `scripts/partition_alerts.py` with `src/data/alert_partition_builder.py` and `telemetry_partition_builder.py` | the partitioner: the only readers of the CSV left |

`grep consolidated_alerts` over runtime code now finds only the partitioner (alerts and telemetry builders and their
constants/docstrings) and the translate tool's mapping. The criterion "no runtime code outside
`scripts/partition_alerts.py` references the CSV" is met, with the translate tool as the one named exception.

## E-mail schedule check and its resolution

From `src/mailing/config.py` and `periods.py` (times in `America/Santiago`):

| Client | Schedule | Period covered | Newest alert it needs vs. the partitions |
|---|---|---|---|
| capstone | weekly, Wednesday 12:00 | previous Monday–Sunday | Sunday 23:59; the Wednesday 04:00 run holds it. OK |
| emin | **daily, 12:00** | **the previous day** | with a weekly run it would omit most days. **Resolved: EMIN is partitioned every day at 10:30**, after its data is complete (10:00, confirmed by the data engineer) and before the 12:00 send |

The scheduled send already syncs `data/` from S3 right before building (`src/mailing/data_sync.py`), so the partitions
the 10:30 run uploads are on the mailing process's disk at 12:00 (90 minutes of margin for the build and the upload). The e-mail resolves them below the same
`DASHBOARD_DATA_ROOT` as the dashboard (local, or the folder synced from S3). Weekly freshness does not omit anything
capstone's e-mail needs.

**Dependency to confirm before relying on it:** EMIN's data is complete at 10:00 (data engineer), but the partitioner
reads the CSV from *its own* `data/` volume and the script does not download it. The daily run is only useful if the
fresh EMIN CSV is on that volume by 10:30 (a pipeline that writes it there, or a sync step). Still unconfirmed: where the
CSV lands and how long it takes to get to the partitioner's volume. The time is `ALERT_PARTITIONS_DAILY_TIME`.

## What changed

**Partitioning schedule** (`scripts/partition_alerts.py`, `docker-compose.yml`). `--schedule` now keeps two schedules.
The weekly one is unchanged (Wednesday 04:00) but leaves the *daily clients* out. The daily clients
(`ALERT_PARTITIONS_DAILY_CLIENTS`, comma-separated, default `emin`, `none` for no one) run every day at
`ALERT_PARTITIONS_DAILY_TIME` (default **10:30**, `--daily-time`: EMIN's data is complete at 10:00 and its e-mail goes
out at 12:00). `--client` still limits both. Layout, S3 layout, backfill marker and atomic swap are untouched. For ECS the
equivalent is a second EventBridge rule, `cron(30 10 ? * * *)` (America/Santiago), running the same image with
`python scripts/partition_alerts.py --client emin`, next to the existing Wednesday rule.

**Readers** (`src/data/loaders.py`, on `alert_partitions.py`):

- `load_alerts_since(client, since_utc)`: whole weeks that overlap `[since, ∞)`, the normalized frame (EMIN evidence
  included); empty-with-columns when the window has no alerts but the client does.
- `load_alerts_for_scope(client, start_date=, end_date=)` (existing): the e-mail uses it for its period.
- `latest_alert_timestamp(client)`: the feed's newest `Timestamp`, from one column of the newest week.
- `load_alert_units(client, dated_only=False)`: every unit of the history, from `_alert_index.parquet`.
- `alert_partitions.py`: `newest_partition`, `schema_columns`, `total_rows`, `partitions_size`, `generation_ns`.

| Consumer | Reads now | Same output because |
|---|---|---|
| Hot Sheet | last 14 days of weeks; unit list from the index | the rule counts 7/14-day windows; units without recent alerts still show "normal" |
| Menace Control | the selected `days` of weeks | each callback's own `Timestamp >= now - days` still trims the rows |
| Fleet overview | status 30 days; counts 56 days + index units (zeros); freshness: newest week | counts keep every unit of the history, same keys and order |
| Unit summary | 30 days before the reference date; data date from the newest week | `_reference_time` still anchors on the feed's newest alert |
| E-mail | the weeks its period touches (`load_alerts_for_scope`), then `slice_to_period` and the exact Chile-day filter as before | same pipeline, only the source of the rows changed |
| Source chips / catalog probe | the newest dated week's file (`Timestamp` column) | the newest week holds the newest alert; the date is "closest to today, not in the future" as before |
| Campbell AI | all weeks (`read_scope`), cached by the newest mtime among the partitions and the index | frame identical to `pd.read_csv` for capstone, cda and emin (checked on the real data, dtypes included) |

Campbell AI details: the `alerts` dataset's path is now `_alert_index.parquet` (it exists exactly when the client has
partitions), as the parallel telemetry change already does for `alerts_detail`; columns come from one partition's footer,
the row count (only when asked) from the index's. Its declared schema now says `parquet` for the three clients. A
*generated* copy of the declaration in `data/auxiliar/dataset_columns.json` (it takes precedence and is refreshed weekly)
still says `csv` until it is regenerated; the service then does not trust it and reads the footer, which is safe and only
skips the shortcut.

**Freshness change (accepted, per consumer).** These consumers used to show the CSV as of the moment of the request.
They now show the data of the last partition run: **Wednesday 04:00 for capstone and cda, every day 10:30 for EMIN**
(Hot Sheet, Menace Control, Fleet overview statuses/counts/freshness label, Unit summary alerts card and date, the
e-mail, the data-source chips, the Campbell AI assistant). A running dashboard also needs the new partitions on its
disk (shared volume or next startup sync); the e-mail gets them from its pre-send sync.

**Removed:** `load_alerts_data`, `_load_alerts_data_cached`, `get_consolidated_alerts_path`. Tests that used them now
use `csv_history` (an oracle in `tests/alert_partition_support.py` that reads the CSV like the old loader did) or the
partitioned readers.

## Verification

- **Dashboard sections, pre-change vs final: identical.** 150 snapshots (Hot Sheet; Menace Control's three callbacks at
  3/30/90/365 days; Fleet overview output, status map and window counts; Unit summary and its alerts card for four units
  each, one unknown; the data date) for capstone, cda and emin at two frozen clocks (2026-11-18 12:00 and
  2026-02-11 15:30:17). Re-run after the last change: still identical.
- **E-mail, HEAD (CSV) vs final (partitions): identical.** 15 requests on the real data (capstone, emin and cda; days,
  weeks, mid-week ranges, the whole history, an empty period), 9,530 records in total, and the full HTML and subject
  for capstone and emin.
- **Campbell AI:** `repository.load("alerts", …)` equals `pd.read_csv` of the CSV (values, dtypes, order) for all three
  clients; the declared schema still verifies for the alerts dataset.
- **Tests:** `tests/test_alert_partition_consumers.py` (29): every section, the e-mail, the chips/probe and Campbell AI run
  with the CSV deleted (any attempt to look for it fails); each equals the run over the whole history; mid-week cut-offs;
  only the needed weeks are opened; no partitions, a window past the last alert, unknown units, an undated-only history,
  a stale feed and a period without partitions raise nothing; a rewritten partition is seen by Campbell AI.
  `test_alert_partitions.py` adds the daily-client schedule (which clients each run takes, and a walk of four runs of
  the loop with a fake clock). Existing tests that used the CSV loader or wrote a CSV for Campbell AI now partition it.
- **Full suite:** 2,400 pass; the failing set is *exactly* the 31 tests and 2 errors that already fail on an untouched
  HEAD on this machine (`informe_falla*`, `mantenciones_productive`, `report_health`, two in `campbell_ai_resources`);
  none is new.

## Impact on response time

`capstone`, default filters, callbacks invoked directly, Windows laptop, pandas engine. Cold = first call in a fresh
process; warm = median of 5 further calls. **A** = before and after processes interleaved, median of 7 fresh processes;
**B** = whole list, median of 3 fresh processes, before then after. Machine load moved the same unchanged code by up to
±80 % between B runs, so read B's warm figures of heavy scenarios as indicative only.

| Section / scenario | Before cold / warm (ms) | After cold / warm (ms) | Cold | Warm | Set |
|---|---|---|---|---|---|
| **Hot Sheet** capstone (default) | 467 / 260 | 301 / 186 | **−36 %** | −28 % | A |
| Hot Sheet emin | 1,129 / 959 | 396 / 276 | −65 % | −71 % | A |
| Hot Sheet cda | 216 / 99 | 153 / 46 | −29 % | −54 % | B |
| **Menace Control** capstone 90 d (default, 3 callbacks) | 296 / 95 | 279 / 151 | **−6 %** | **+59 %** | A |
| Menace Control 30 d | 294 / 82 | 291 / 113 | −1 % | +38 % | B |
| Menace Control 365 d | 296 / 100 | 337 / 199 | **+14 %** | +99 % | B |
| Menace Control emin 90 d | 6,099 / 10,480 | 829 / 733 | −86 % | −93 % | B |
| **Fleet overview** capstone (default) | 262 / 48 | 187 / 70 | **−29 %** | **+46 %** | A |
| Fleet overview emin | 1,373 / 1,291 | 369 / 239 | −73 % | −81 % | A |
| Fleet overview cda | 147 / 29 | 164 / 48 | +12 % | +66 % | B |
| **Unit summary** capstone busiest unit (default) | 1,073 / 254 | 1,036 / 317 | **−3 %** (noise) | **+25 %** | A |
| Unit summary capstone, least-recent unit | 723 / 198 | 787 / 1,654 | +9 % | not meaningful | B |
| Unit summary cda busiest unit (stale feed) | 1,173 / 558 | 1,338 / 624 | **+14 %** | +12 % | A |
| **E-mail** capstone weekly (default) | 1,089 / 24 | 1,032 / 27 | **−5 %** | +3 ms (+12 %) | A |
| E-mail capstone 4 weeks | 881 / 49 | 796 / 54 | −10 % | +10 % | A |
| E-mail emin daily | 1,441 / 603 | 863 / 32 | −40 % | −95 % | A |

The data-source chips, the catalog probe and Campbell AI were not timed (the chips and probe read one column of one
file; Campbell AI loads capstone's whole history in ~60 ms from the partitions).

Reading it:

- **Cold is lower at default filters in every capstone consumer**: clearly for Hot Sheet (−36 %) and Fleet overview
  (−29 %); marginally for Menace Control (−6 %), Unit summary (−3 %, within noise) and the e-mail (−5 %; its time is
  dominated by importing the dashboard components, not by reading alerts). The large wins are EMIN (−40 % to −86 %): the
  old path re-ran EMIN's maintenance-evidence enrichment over the whole history on every call, and now it does so over
  the loaded weeks only.
- **Warm is slower for Menace Control, Fleet overview, Unit summary and (by 3 ms) the capstone e-mail** at default
  filters (+59 %, +46 %, +25 %, +12 %; roughly +3 to +60 ms per repeated interaction). See decision 2.
- Non-default scenarios slower on cold: Menace Control 365 d (+14 %: 53 weeks), Unit summary on cda's stale feed (+14 %),
  Fleet overview cda (+12 %). cda has 152 alerts in total, where the old cached CSV was tiny.

## Open decisions

1. **(Decided) EMIN daily.** Needs the operational dependency above (fresh EMIN CSV on the partitioner's volume before
   10:30, when EMIN's update finishes) and, in ECS, the second EventBridge rule.
2. **Warm-path cost, in plain words.** Before, the dashboard read the whole alert CSV *once* and kept it in memory, so
   the second time you opened Menace Control (or Fleet overview, or a unit) it cost almost nothing. Now each open reads
   the few weekly files it needs from disk again. The first open of the day is faster (less data, nothing to parse), but
   repeating it costs a few tens of milliseconds more than the old in-memory copy (about 0.05 to 0.15 s per click, never
   a noticeable wait on its own). Your rule says that anything slower at default filters needs approval. Options:
   **(a) accept it** (my recommendation: the cost is small, bounded by the window, and does not grow with the history,
   while the old one grew with it); **(b) approve reading only the ~6 of 13 columns these sections use** (a pure
   performance change beyond this migration, would remove most of the difference); **(c) approve a cache** (excluded
   today; it would bring back "stale until restart" questions). Nothing was added.
3. **(Decided) Other readers redirected.** Operational follow-ups: regenerate the Campbell AI declared schema so its
   generated copy says `parquet` for `alerts` (until then it just reads the footer); the translate tool's full run now
   needs a partition run to reach the dashboard.
4. The windows live as constants next to the rules they serve (`ALERT_STATUS_WINDOW_DAYS`, `ALERT_WINDOW_DAYS`,
   `ALERTS_WINDOW_DAYS`), so changing a rule's window changes what is read.
5. **Relation to the telemetry change (next section).** Both changes touch `scripts/partition_alerts.py`, `catalog.py`,
   `campbell_ai/data.py` and `loaders.py`. The daily EMIN run applies to every dataset of the run, but EMIN has no telemetry
   source, so for it a daily run only rebuilds its alert partitions. Telemetry for capstone and cda keeps its weekly cadence.

---

# Change summary — partitioned alert telemetry (the wide telemetry CSV)

The per-alert telemetry (sensor readings, limits and GPS around each alert) is no longer read from its
wide CSV at runtime. The weekly partitioning script splits it into Parquet files beside the alerts
partitions, and every reader now opens only the week it needs. What the screens show is unchanged
(187 output snapshots, byte-identical); what changes is how much is read to show it.

> **Naming.** The requirement calls the file `alerts_details_with_gps`; the file in the data lake is
> `telemetry/golden/{client}/alerts_detail_wide_with_gps.csv` (catalog source `telemetry_alert_detail`,
> Campbell AI dataset `alerts_detail`). Same file.

## 1. Audit — who reads the file (mandatory first step)

**The file is read at runtime, so the work went ahead.** Four runtime readers, found by searching the
repository for the file name, for its loaders and for its catalog/dataset ids (`telemetry_alert_detail`,
`alerts_detail`), measured on capstone before the change:

| # | Section / function | Filters and window | Columns used | Loaded the full file? |
|---|---|---|---|---|
| 1 | **Evidencia de Telemetría** in Vista Detallada: `create_telemetry_evidence_section` → `loaders.load_telemetry_alert_detail_for_alert` | `AlertID ∈ {alert's TelemetryID, FusionID}` and `Unit == UnitId` (stripped text); no date window — the whole telemetry window of the one alert (~260 rows) | all (all-NaN ones dropped): `Trigger`, `TimeStart`, `State`, `GPSLat/Lon/Elevation`, `{signal}_Value`, `{signal}_Upper/Lower_Limit`, `Payload_Value`, `Alert_TimeStart` | **Yes, per alert.** Polars pushes the predicate into the CSV scan but still scans all 309 MB; without Polars (as on this laptop) pandas parses it all (2.4–2.5 s cold). The result was cached per alert (`lru_cache(128)`). A full-file loader (`load_telemetry_alerts_detail_golden`) existed only as that path's fallback. |
| 2 | **Data-source chip** "Detalle de Alertas (Telemetría)" (popover of *Alertas* and *Campbell AI*): `source_status` → `source_freshness.latest_data_date`, field `Alert_TimeStart` | none; the date closest to today that is not in the future | one column, `Alert_TimeStart` | **Yes** (reads that column over the whole file, as text; cached by mtime/size). 1.3 s cold on capstone. |
| 3 | **Catalog probe** `telemetry_alert_detail` (`catalog.build_client_availability`) | none | none: `stat` only (exists / size / mtime) | No — not a read of the content. Moved to the new index so it stays truthful. |
| 4 | **Campbell AI** dataset `alerts_detail` (`src/campbell_ai/`), through `DashboardDataRepository.load` = `pd.read_csv` of the whole file | see below | see below | **Yes, always.** capstone's frame (396 MB in memory) is larger than the default 192 MB frame-cache budget, so it was **re-parsed on every query** (≈4 s, cold *and* warm). |

Campbell AI uses the file in six places: `query_alert_detail` (unit / alert id, FusionID resolved to the
telemetry id / trigger-contains), `alert_signal_series` (→ `query_alert_signals`, chart `alert_sensor_trend`;
unit and/or alert, newest alert of a unit), `chart_registry._alert_context_signals` (chart
`alert_context_signals`; unit, optional alert), `telemetry_signal_limits` (**no filter, the whole history**:
`Unit`, `SubState`/`State` and every `*_Upper_Limit`/`*_Lower_Limit`), the filter vocabularies of
`describe_dataset` (distinct `Unit`/`Trigger`/`AlertID`) and the schema checks (`validate_client`,
`schema.verify_against_disk`: column names only).

`scripts/benchmark_dashboard.py` listed the file as a CSV-reader benchmark target (a developer tool, not
runtime); that target was removed.

**Other telemetry sources are not this file.** *Telemetría* (fleet / unit detail) and the Campbell
`telemetry_signal_trend` chart read `telemetry/silver/.../Telemetry_Wide_With_States` and the golden
`unit_health`/`system_health` tables; they never touched it and are unchanged.

**EMIN has no telemetry file** — not locally and not in S3 (`MultiTechnique Alerts/telemetry/golden/emin/`
is empty). Its *Evidencia de Telemetría* has always rendered nothing (the alert header carries the event) and
its evidence comes from the maintenance-week files. So no EMIN telemetry partitions exist or can be built;
see open point 1.

## 2. Layout decision: one file per client and week (A)

Both candidates were built from the real capstone file and measured (median of 5, warm cache, the exact
read the reader does: open the files, concatenate, apply the row filter):

| capstone | **A** `{week}/telemetry.parquet` | B `{week}/{unit}/telemetry.parquet` |
|---|---|---|
| files | **24** | 315 |
| rows per file (min / median / max) | 490 / 6,798 / 49,392 | 96 / 620 / 6,294 |
| size per file (median) | 1,161 KB | 153 KB |
| total size | **53 MB** | 72 MB |
| full script rebuild (CSV read 3.9 s + write) | **≈ 5.4 s** (write 1.5 s) | ≈ 7.7 s (write 3.8 s) |
| read one alert, current week | 9.9 ms | 5.8 ms |
| read one alert, old week | 5.6 ms | 7.4 ms |
| read one alert, largest week / largest unit file | 23 ms | 6.5 ms |
| all alerts of one unit (15 weeks) | 227 ms | **70 ms** |
| one trigger, all weeks | 216 ms | **148 ms** |
| full history, limit columns only (Campbell limits) | **152 ms** | 1,060 ms |

**Decision: A.** The access pattern the audit found for the dashboard is one alert, and there the two layouts tie
(5–10 ms; the largest week costs 23 ms against 6.5 ms). A reads the full history 7× faster, stores 26 % less,
and keeps S3 and the startup sync at 25 objects instead of 316. B is 2–3× faster only for Campbell's
unit-wide and trigger-wide scans, which are rare and still sub-second. B's files are not tiny like the alerts
unit files were (median 620 rows), so the call was made on the read times and the object count, not on file
size. The layout lives in one module, `src/data/telemetry_partitions.py`, shared by the script and every
reader; going to B would be confined to it and the builder.

## 3. What changed

**Storage.** `data/alerts/golden/{client}/{week}/telemetry.parquet` (own file name, beside the alerts'
`file.parquet`) plus `_telemetry_index.parquet`. Each file has the source's columns, dtypes, values and row
order (the source row numbers travel in the footer, `telemetry.source_row_ids`).

**The week is the alert's, not the row's.** A telemetry row goes to the Monday-week of the `Timestamp` of the
alert it belongs to (same `week_starts`, same normalization as the alerts), so an event that crosses a
Sunday/Monday boundary stays whole in one file. This matters: on capstone **2,240 of 366,749 rows** (CDA: 286
of 53,057) carry a `TimeStart` in a different week from their alert.

**The key** that links telemetry to alerts: `telemetry.AlertID` = the alert's `TelemetryID` **or** `FusionID`
(capstone keys on the FusionID, CDA on the per-unit `TelemetryID`) **and** `telemetry.Unit` = its `UnitId`,
compared as stripped text. Documented in `telemetry_partitions.py`; resolved in
`telemetry_partition_builder.assign_weeks`.

**The index** (`_telemetry_index.parquet`, 43 KB capstone / 8 KB CDA) has one row per `(AlertID, Unit, Trigger,
Alert_TimeStart)` with its `week`, `rows`, `first_row` and `part_sha`. It locates an alert's week without
reading a partition, gives the data-source chip its date, serves the filter vocabularies and the row counts,
and — because `part_sha` changes whenever a partition does — changes whenever any partition changes, so every
cache keyed on it (the per-alert loader cache, Campbell's frame and vocabulary caches) can never serve a stale
generation. (The alerts' `_alert_index.parquet` cannot do this job: it has no `TelemetryID`, and capstone's
telemetry is keyed by FusionID but CDA's by TelemetryID.)

**Weekly script** (`scripts/partition_alerts.py`, same run, Wednesday 04:00 `America/Santiago`): per client the
alerts half runs first (unchanged) and the telemetry half second; each has its own build, validation, S3 sync
and exit-status contribution, so one failing never stops the other. Only partitions whose bytes changed are
rewritten (the in-progress week included), partitions the source no longer yields are removed, files are swapped
with `os.replace`, a per-client lock stops overlapping runs. New `--dataset alerts|telemetry|all` (default `all`).
A client with no telemetry source (EMIN) is logged and skipped; a source that vanishes while partitions exist is
an error that deletes nothing (a missing mount must not look like "no telemetry").

**Backfill, validation, S3.** `--backfill` builds the whole history locally (S3 off unless `--sync-s3`).
`--validate` (default for the backfill) checks row totals, columns, dtypes and values against the source, **that
every row sits in the week of its alert** (recomputed from `consolidated_alerts.csv` and each partition's recorded
source rows), and that the index agrees with the partitions. `--verify-s3` now also compares the telemetry objects
(keys, sizes, hashes, row counts). Keys: `s3://{bucket}/MultiTechnique Alerts/alerts/golden/{client}/{week}/telemetry.parquet`,
same bucket/prefix configuration. **Sequencing:** the weekly telemetry sync refuses (exit 2) for a client whose
`_telemetry_backfill_complete.json` is not in S3 — the alerts marker does not satisfy it. After that every weekly
run syncs the regenerated telemetry partitions; a failed upload is logged, the run exits 2, local files stay valid
and the next run retries. Each dataset deletes only its own stale keys, so syncing one can never remove the other's.

**Read path.** `src/data/telemetry_partitions.py` is the only reader: `read_alert` (index → one week file → the
alert's rows, source order), `read_weeks` (with column projection) and the index helpers. Replaced:

| Reader | Now |
|---|---|
| Evidencia de Telemetría | `load_telemetry_alert_detail_for_alert` (same name and signature) reads the index and **one** week file; cached per alert and index generation |
| Data-source chip / catalog probe | the index file: its `Alert_TimeStart` column dates the data; the probe is the index's existence |
| Campbell AI | `alerts_detail_rows` / `alerts_detail_index`: the index narrows the weeks a filter can match, then the **original** row filters run unchanged on those rows; the limits table reads only `Unit`, `SubState`/`State` and the limit columns of all weeks; vocabularies and row counts come from the index |

**Removed:** `load_telemetry_alerts_detail_golden`, its cached twin and the CSV filtered/fallback path in
`loaders.py`; `fast_io.read_csv_filtered` and its two tests (written for this reader, now unused); the benchmark
target. A test scans `src/`, `dashboard/` and `config/` and fails if anything but the script names the source
file. There is no fallback to the original file.

**Behaviour change (accepted).** Telemetry is as fresh as the last weekly run (Wednesday 04:00), like the alerts
partitions: *Evidencia de Telemetría*, the chip date and every Campbell AI telemetry answer move once a week. The
alerts and telemetry partitions are swapped separately, so between the two swaps an alert can briefly show the
usual "no hay datos de telemetría" message. Nothing raises: a missing week, an alert without telemetry or a client
without partitions is an empty frame, exactly the message shown today when telemetry is missing.

## 4. Impact on response time

Capstone (and CDA where noted), callbacks invoked directly, same method as above: **cold** = first call in a fresh
process, median of 3; **warm** = median of 5 repeats. Pandas engine; developer laptop. "Before" was measured on a
frozen copy of the pre-change code against the same data.

| Reader / scenario | Before cold / warm | After cold / warm | Change (cold) |
|---|---|---|---|
| **Evidencia de Telemetría**, load only — current-week alert | 2,550 ms / 0 (cached) | 19 ms / 0 | **−99 %** |
| load only — old-week alert | 2,451 ms / 0 | 13 ms / 0 | −99 % |
| **section, current week** (load + render) | 3,434 ms / 678 ms | 859 ms / 626 ms | **−75 %** |
| section, old week | 2,930 ms / 75 ms | 330 ms / 67 ms | −89 % |
| section, alert crossing a week boundary | 2,854 ms / 72 ms | 329 ms / 67 ms | −88 % |
| section, CDA current / old | 635 / 693 ms (115 / 150 warm) | 371 / 397 ms (106 / 134 warm) | −42 % / −43 % |
| **Data-source chip**, capstone / CDA | 1,290 / 102 ms | 27 / 21 ms | −98 % / −79 % |
| Campbell `query_alert_detail`, one alert (current / old week) | 4,426 / 4,030 ms (4,065 / 3,964 warm) | 120 / 113 ms (17 / 11 warm) | **−97 %** |
| Campbell `alert_signal_series`, one alert | 4,033 ms (4,061 warm) | 60 ms (22 warm) | −99 % |
| Campbell context chart, one alert | 4,515 ms (4,157 warm) | 222 ms (32 warm) | −95 % |
| Campbell, all alerts of a unit | 4,446 ms (4,300 warm) | 1,095 ms (1,049 warm) | −75 % |
| Campbell, one trigger, **full history** | 4,568 ms (4,630 warm) | 1,259 ms (1,166 warm) | −72 % |
| Campbell, latest alert of a unit | 4,175 ms (4,275 warm) | 707 ms (709 warm) | −83 % |
| Campbell limits table, **full history** (table recomputed each call) | 4,031 ms (3,921 warm) | 546 ms (524 warm) | −86 % |
| Campbell `describe_dataset` (rows + vocabularies) | 141 ms | 26 ms | −82 % |
| Campbell, CDA all alerts of a unit | 479 ms (189 warm) | 298 ms (160 warm) | −38 % |
| Campbell, CDA limits table | 260 ms (67 warm) | 138 ms (114 warm) | −47 % cold, **+47 ms warm** |
| Campbell `validate_client` (session opening) | 3.5 ms | 26.9 ms here; **2.9 ms** with the committed declaration | see open point 4 |

Reading the numbers:

- The remaining ~860 ms of the current-week section on capstone is rendering (that alert carries ~40 signals);
  the data read went from 2.5 s to 19 ms. The same function rendered an old-week alert in 330 ms cold.
- The old Campbell figures are flat (~4 s warm *and* cold) because capstone's 396 MB frame did not fit the default 192 MB frame-cache budget and was re-parsed on every call. The new path reads the index and the weeks it needs: it **scales with the
  weeks a filter touches, not with the history**. Whole-history and whole-unit queries still read many weeks, hence
  the ~0.5–1.2 s rows.
- Two rows are not faster and are explained, not hidden. *CDA limits, warm* (67 → 114 ms) is the harness clearing
  Campbell's per-client limits-table cache on every call to measure the recompute; in production the table is
  cached after the first call, so a warm call is ~0 before and after. *`validate_client`* is the stale-declaration
  effect in open point 4.
- No cache was added to the dashboard reader beyond the per-alert `lru_cache(128)` it already had.

## 5. Script runtime, S3 volume, startup sync

- **Runtime** (this laptop, nothing to rewrite = same work as a changed run, since every partition is regenerated and
  compared by hash): telemetry half **≈ 8.4 s** (capstone 6.3 s, CDA 1.5 s); the whole run, alerts + telemetry,
  **≈ 12.4 s**; `--validate` adds ≈ 6 s for capstone, ≈ 0.5 s for CDA. First backfill: 15.4 s with validation.
- **Added to S3** (once the backfill is synced): capstone 24 partitions + index = 25 objects, 54.3 MB; CDA 54 + index =
  55 objects, 6.2 MB; plus one `_telemetry_backfill_complete.json` per client — **82 objects, 60.5 MB**. A weekly run
  uploads the current week's partition and the index (a few MB).
- **Startup sync.** Deployed dashboards mirror `MultiTechnique Alerts/` at startup and skip files whose size matches,
  so at the first startup after the backfill is synced they download these 82 objects / 60.5 MB, then only the weekly
  changes. The local `data/` here is 18.3 GB, so this is +0.3 %: **not expected to affect startup noticeably; no escalation
  needed for the volume.** (Separately, the same mirror downloads the 327 MB of source CSVs that no dashboard code reads
  any more — see open point 3.)

## 6. Telemetry rows with no alert

The run counts them on every execution and keeps them in `unmatched/telemetry.parquet`; they are never dropped.

| Client | Telemetry rows | Rows with no matching alert | Distinct (AlertID, Unit) | Alerts of different weeks claiming one key | Rows of undated alerts |
|---|---|---|---|---|---|
| capstone | 366,749 | **0** | 0 | 0 | 0 |
| cda | 53,057 | **0** | 0 | 0 | 0 |
| emin | no source file | — | — | — | — |

Nothing needs escalating today. The handling is built so it stays visible if it ever happens: the rows are kept
(row totals still equal the source), the warning is logged on every weekly run, and the open decision — what to do
with such rows (repair upstream, show them, discard them) — stays with the team.

## 7. Verification

- **Same output as before:** 187 snapshots taken on the pre-change code and re-taken on the final code are
  byte-identical, for capstone, cda and emin: *Evidencia de Telemetría* rendered for the newest alert (current
  week), alerts of old weeks, alerts whose telemetry crosses a week boundary (3 capstone, 1 cda), alerts with no
  telemetry (2 capstone; every CDA alert has some) and EMIN's empty section (20 renders: figures, KPIs, GPS map,
  headers); the data-source chip result; and 164 Campbell AI
  outputs (`query_alert_detail`, `alert_signal_series`, `query_alert_signals`, the context chart, the limits table,
  `describe_dataset` with vocabularies and row counts, `validate_client`) including 34 error cases that must keep their
  messages.
- **No read of the original file:** the whole snapshot harness was run again with every attempt to open it turned
  into a failure: 187 identical outputs, **0 attempts**. A test also deletes the telemetry and alerts CSVs and runs
  every reader.
- **Local backfill validated on the real data:** capstone 366,749 rows in 24 partitions and CDA 53,057 rows in 54
  equal their sources in row totals, columns, dtypes and values; every row sits in the week of its alert (including
  the 2,240 + 286 boundary rows); a re-run rewrites **0** files.
- **S3:** the sync, the separate marker and the sequencing guard, the failed-upload/retry path, stale-key isolation
  between the two datasets and `--verify-s3` are tested with the in-memory S3 double used for the alerts
  (59 new tests in `tests/test_telemetry_partitions.py`). **Then run for real (2026-11-18):** `--backfill --sync-s3 --dataset telemetry` uploaded 25 objects for capstone and 55 for CDA (82 with the markers), and `--verify-s3` reports S3 identical to local for telemetry and alerts, all three clients.
- **Suite:** 2,398 passed. The 31 failures and 2 setup errors that remain are the same set that fails on a pristine
  checkout of `HEAD` (checked in a throwaway worktree): `informe_falla*`, `mantenciones_productive`, `report_health`
  and two in `campbell_ai_resources`. One regression I introduced (a reworded S3 message an alerts test matched) was
  found by the suite and fixed.

## 8. Acceptance criteria

| Criterion | Status |
|---|---|
| Audit recorded; readers, filters, columns | Done (§1) |
| Layout decision documented with measurements | Done (§2): A |
| Partitions exist for every week in the source for capstone, cda **and emin** | capstone ✔ (24 weeks), cda ✔ (54), **emin ✘ — it has no telemetry source** (open point 1) |
| Row totals = source; unmatched reported, not dropped | Done (§6) |
| Columns, dtypes, values identical | Done (validation) |
| Every row in its alert's week, boundary alerts included | Done (validation; 2,526 boundary rows) |
| Re-run rewrites 0 files, no duplicates | Done |
| Backfill local, S3 off by default | Done |
| `--verify-s3` identical to local after a sync | Done: run on the real bucket, S3 identical to local |
| Weekly telemetry sync refuses before the telemetry backfill is synced | Done (own marker; tested) |
| Failed upload reported, local intact, retried | Done (tested) |
| Nothing outside the script names the file; old loaders removed | Done (test) |
| Readers run with the original file deleted | Done (test + guarded harness) |
| Snapshots identical on capstone, cda, emin | Done (187/187) |
| Missing week / unit / alert partition raises nothing | Done (tests) |
| Default-filter time lower than baseline for every reader | Done for every reader at cold; two warm/session-open rows explained in §4 |
| `change_summary.md`, `codebase_explaining.md` updated | Done |

## 9. Open points

1. **EMIN publishes no telemetry file**, so the criterion "partitions for capstone, cda and emin" cannot be met as
   written. The script skips it cleanly. If EMIN starts publishing one, the next weekly run builds it locally, and
   `--backfill --sync-s3 --dataset telemetry` must run for it before the weekly sync will upload (the guard).
2. **S3 backfill: done (2026-11-18).** Backfill synced and verified (see §7). Deploy order still matters for any
   environment that does not yet have the partitions: a dashboard running this code without them on its disk shows
   "no hay datos de telemetría" for every alert (no errors); the startup mirror brings them (82 objects, 60.5 MB).
3. **Not done, needs approval — stop downloading the source CSVs in the dashboards.** The dashboards' startup mirror
   still downloads the 327 MB of wide telemetry CSVs (capstone 309 MB, CDA 18 MB) that no dashboard code reads any
   more; only the partitioning script (whose volume must keep them) does. Excluding them from the dashboards' mirror
   would cut each cold start by that amount. It is a separate performance change, so it was not made.
4. **Campbell AI schema declaration: patched (2026-11-18).** `alerts_detail` is now a Parquet dataset, so its
   `format` was changed from `csv` to `parquet` in `src/campbell_ai/schema/dataset_columns.json` and, only for those
   two entries (cda, capstone), in the **published** copy (`MultiTechnique Alerts/auxiliar/dataset_columns.json`, which
   dashboards mirror) and the local generated copy. The previous published version is kept at
   `campbellAI/schema/dataset_columns/history/20261118T221836Z-before-alerts_detail-parquet/`. A full
   `schema.build` from this machine was deliberately **not** published: the local `data/` lacks the predictive CSVs, so
   it would have dropped `predictive_motor`/`predictive_transmission` from the declaration. The weekly `schema.refresh`
   regenerates the whole file from the real data anyway.
5. **Layout A makes Campbell's unit-wide scans slower than layout B would** (227 vs 70 ms for the file reads; whole
   unit queries take ~1.1 s end to end). Accepted for the 7× faster full-history read and 12× fewer objects.
6. **Pandas reads the telemetry CSV in the partitioner, always** (`low_memory=False`), so every column's dtype is
   inferred from all its values. The previous dashboard reader used Polars when installed (`requirements.txt` lists
   it), which infers from the first rows only; on a sparse 120-column file that can type a numeric signal column as
   text. Parity was proven on the pandas engine (the one installed here); if production's Polars read ever differed,
   the partitions are the more consistent of the two. Worth a glance at one production alert after deploying.
7. **A pre-existing weakness surfaced by a test fixture:** `to_utc_naive` raises when the only unparseable
   `Timestamp` values of a column are non-empty garbage strings (empty values are fine). It affects the alerts build
   and now the telemetry build equally (exit 1, existing partitions untouched). Real data has none; out of scope.
8. The chip's "last modified" for this source is now the index file's mtime (the last weekly run that changed
   anything), not the CSV's.


# Change summary — 25/11/2026 incident: partitions built before the alerts existed; the partitioner moves into the app

The upstream alert creation moved from 03:00 to 07:00. The `alerts-partitioner` container still ran
**Wednesday 04:00**, so on 25/11 it partitioned `consolidated_alerts.csv` *before* the new alerts existed, and the
alert-summary e-mail (Wednesday 12:00), which reads those partitions, went out with incomplete data. The partitioner was
a separate container with no link to the mailing schedule, which is what allowed the ordering failure. This change fixes
the data and the report (steps 1–2) and then puts the partitioner next to the mailer so the order is enforced (step 3).
Order was mandatory: 1 → 2 → 3.

## The incident

- **Cause.** Alert creation 07:00 vs partitioner 04:00 (and e-mail 12:00, no dependency between them).
- **Affected data.** The weekly Parquet partitions of **capstone, week of Monday 16/11** — the week the Wednesday e-mail
  covers (period 16/11–22/11). The whole week's 43 alerts arrived in the 07:00 run (`consolidated_alerts.csv`
  6,258 → 6,301 rows), so the 04:00 run produced no `2026-11-16` partition at all. The task text speaks of the week of
  23/11 (the run's in-progress week): that week has **no alerts yet** (the newest is 22/11), so it has no partition and
  there was nothing to correct there. EMIN's `2026-11-16` partition was also stale in S3 (3 rows vs 13 in the CSV); its
  e-mail goes to the technical team only (test mode), so no client was affected. CDA had no change.
- **Client impact.** `capstone` received the 25/11 summary built without that week's alerts (not compared against the
  sent e-mail; the partitions it read had no rows for the period). Corrected by the erratum below. No other client was
  sent anything.

## Actions, in order, with their verification

**1. Partitioner re-run (25/11, ~13:15 Chile) — done, verified.**
- *Precondition* (before running): `consolidated_alerts.csv` in S3, last modified — **capstone 2026-11-25 10:34:55 UTC
  (07:34:55 Chile, after the 07:00 run)**, same size as the local copy (7,748,044 B); emin 2026-11-24 14:12:48 UTC (11:12
  Chile); cda 2026-10-27 19:42:22 UTC. Newest alert `Timestamp` (UTC): capstone 2026-11-22 06:35, emin 2026-11-21 08:40:09,
  cda 2026-07-09 19:13. The wide telemetry CSVs match S3 too (capstone 314,327,216 B, written 10:35:09 UTC; cda
  17,550,418 B). emin and cda were not touched by today's upstream run; they were included because the run is
  idempotent and the task said all clients.
- *Run:* normal weekly run (no `--backfill`), `python scripts/partition_alerts.py`, exit **0**. Uploads: capstone 2 alerts
  + 2 telemetry objects (the new week and the indexes), cda 0, emin 51 (the stale `2026-11-16` week plus metadata-only
  rewrites, see the note below). 0 stale deletions.
- *Verification:* rows in partitions = rows in the CSV for every client (capstone 6,301, cda 152, emin 245); capstone
  week `2026-11-16`: **43 in the partition = 43 in the CSV** (16/11…22/11 by Chile day); week `2026-11-23`: 0 = 0;
  `--verify-s3` after the run: S3 matches local for alerts and telemetry of all three clients, exit 0.
- *Note — run environment.* The run was made from a developer machine, not the container. A first read-only
  `--verify-s3` with that machine's pyarrow 25.0.1 flagged almost every object as different from S3 although the data was
  the same (the container's partitions were written by pyarrow 26.0.1; `requirements.txt` only says `pyarrow>=14`), and
  running it would have rewritten most of S3 byte for byte. The run was therefore made in a throwaway environment with the
  versions a fresh `pip install -r requirements.txt` resolves (pandas 3.1.1, pyarrow 26.0.1): cda matched S3 exactly and
  capstone differed only by the missing week and the indexes. EMIN's older S3 partitions carry a different pandas version
  string in their metadata (same data), hence its re-upload. **Suggestion (not done):** pin `pyarrow`/`pandas` so a manual
  run and the app write identical bytes.

**2. Erratum e-mail to `capstone` (25/11, 13:26 Chile) — done, after step 1 was verified and the preview approved.**
- New one-time option `erratum` (default off) on the existing mailing path (`ReportRequest.erratum` →
  `render_alert_summary` / `periods.build_subject`) and the entry points `service.build_erratum_preview` /
  `service.send_erratum`. Regular e-mails are byte-identical to before (checked against the previous template with the same
  data; a test pins it); they never carry the notice or the prefix.
- Subject `[FE DE ERRATA] [CODDI] Monitoreo de Alertas 25/11/2026`; the approved notice (Spanish) is the first block;
  everything else is the regular e-mail of that date. Recipients = those of the regular scheduled e-mail (10 Capstone
  contacts, `tds@`, `warren@`, `eduardo@`, `pedro@` — 14 addresses). Figures: 43 alerts, 11 units, period 16/11–22/11 = the
  CSV count. `send_erratum` has its own at-most-once marker (`logs/mailing/erratum_capstone_2026-11-25.json`, status
  `sent`) and never touches the scheduled-run markers; no retry. Sent through the `emailSender` Lambda with the `LAMBDA_*`
  keys of the project's `.env` (the default AWS chain had no credentials on that machine).

**3. Partitioner moved into the app — implemented and tested; deployment pending (see below).**

## New schedule (America/Santiago)

| What | When | Notes |
|---|---|---|
| Alert creation (upstream, unchanged) | 07:00 | not ours |
| **Partitioner, weekly** | **Wednesday 08:00** | every client; rebuild what changed (in-progress week included) + S3 sync |
| **Alert-summary e-mail, capstone** | **Wednesday 08:30** (was 12:00) | only if this week's partitioner run finished OK |
| Partitioner, daily clients | every day **11:30** (was 10:30) | `emin` only; EMIN's CSV reaches S3 ~11:10; see decision 1 |
| Alert-summary e-mail, EMIN | every day 12:00 (unchanged) | only if today's 11:30 run finished OK |

The partitioner values are environment variables of the app (`ALERT_PARTITIONS_TIMEZONE/WEEKDAY/TIME/DAILY_CLIENTS/
DAILY_TIME/GRACE_MINUTES/TIMEOUT_SECONDS/STATE_DIR/SCHEDULER_ENABLED`; documented in `documentation/codebase_explaining.md`
§5). The mailing schedules stay in code on purpose (`src/mailing/config.py`; a test pins them).

## How it works

- `src/data/partition_scheduler.py` (started from `dashboard/app.py` next to the mailing scheduler; production only, not
  under pytest): a daemon thread polls every 30 s and starts the job that is due (scheduled moment + 15 min grace,
  wall-clock in the zone, so DST does not move it). The job runs the **existing** `scripts/partition_alerts.py` in a
  **subprocess** — logic reused, not duplicated; its exit status (0/1/2) is the outcome; log lines are streamed into the app
  log (`partitioner | …`). The subprocess keeps a hundreds-of-MB CSV rebuild out of the web process's GIL and memory, so
  **dashboard requests are never blocked** (a test shows a tick returning at once while the job runs).
- `scripts/partition_alerts.py` is now **only the manual tool** (`--backfill`, `--validate`, `--sync-s3`, `--verify-s3`,
  `--client`, `--dataset`, one run now). Its `--schedule` loop and the `--weekday/--time/--timezone/--daily-*` options were
  removed so that only one scheduler exists; their tests moved to `tests/test_partition_scheduler.py`. Layout, atomic swaps,
  S3 sync, backfill guard, idempotency and freshness are untouched.
- **Dependency rule.** The scheduled e-mail, after claiming its marker and before building anything, reads the run status
  the partitioner recorded (`config.MAILING_PARTITION_DEPENDENCY`: capstone → the weekly run of that ISO week, EMIN → the
  daily run of that day; the newest run in the range decides). Not `ok` — failed (exit 1/2), still running/interrupted, or
  never ran — means: **not built, not sent**, an `ERROR` log (`mailing: scheduled send NOT SENT, partitioner dependency not
  met …`) and the reason in the mailer's marker. No retry or alternative path. It does not rely on the 30-minute gap.
- **Alerts-generated rule (capstone only, team decision 25/11).** After the partitioner check and the pre-send S3 sync,
  and before building, the e-mail counts the client's alerts of its own period in the partitions (same pipeline as the
  e-mail, `alert_summary.load_period_records`). **Zero alerts = not built, not sent**, an `ERROR` (`… NOT SENT, no alerts
  generated …`: the alert creation did not run or did not reach the partitions), reason in the marker, no retry; data that
  cannot be read blocks it too. Configured in `config.MAILING_REQUIRE_ALERTS` (`{"capstone"}`). **EMIN is deliberately
  not in it**: it generates alerts daily and not every day has alerts, so an empty day is normal and still gets its e-mail.
  Cost to know: a week in which capstone truly has zero alerts sends nothing (an error is logged instead). Checked on the
  real data: period 16–22/11 → 43 alerts, passes; period 23–29/11 → 0 today, so the 02/12 e-mail goes only if the 07:00
  creation of that day delivers alerts for it.

## How duplicate runs are prevented (and what it does not cover)

Same mechanism as the mailer: an atomic marker file per `(job, date)` (`O_CREAT | O_EXCL`) in `logs/partitions/` (the mailer
uses `logs/mailing/`), claimed **before** running, shared by every worker and kept across restarts. Whoever creates it runs
the job; everyone else logs "already claimed" and skips. Tested with 12 threads on one marker and with 6 separate processes
racing for it: exactly one wins. A restart inside the 15-minute window does not re-run it.
- **Multiple workers on one host or volume (gunicorn today: 1 worker × 8 threads):** one run per schedule.
- **Several app instances/tasks that do *not* share `logs/`:** each would claim its own marker, so each would run the job
  (idempotent and S3-safe, but wasteful) — **and each would send the e-mail**: the mailer already has this limit, so running
  more than one app task already needs a shared state directory (`MAILING_STATE_DIR`, `ALERT_PARTITIONS_STATE_DIR` on shared
  storage). Nothing was added for it.
- A run that dies mid-way leaves its marker `running`; it is not resumed (no catch-up) and the e-mail refuses to go until a
  run finishes `ok` — re-run the script by hand, and send the e-mail from the Mailing admin page if needed.
- The script keeps its own per-client lock file, so a manual run cannot overlap a scheduled one.

## Removed / what must change outside the repo

- `alerts-partitioner` service removed from `docker-compose.yml` (the Dockerfiles never had a partitioner entry point, so
  there was nothing to remove there).
- **AWS side (not in the repo, not touched):** delete the EventBridge rules `cron(0 4 ? * WED *)` and, if it exists,
  `cron(30 10 ? * * *)` for the partitioner. Otherwise two schedulers would coexist.

## Deployment (deadline: before Wednesday 02/12/2026 04:00) — NOT DONE YET

Prerequisites on the app's ECS task, none of which the repo can verify:
1. **S3 write access.** The app used to only *read* the bucket; the partitioner needs `List/Get/Put/DeleteObject` on
   `MultiTechnique Alerts/alerts/golden/` with the credentials the app passes (`BUCKET_NAME`, `ACCESS_KEY`/`SECRET_KEY` or the
   task role). Without it the run exits 2 and the e-mail is not sent.
2. A **writable data volume** (the app already downloads into it) and **memory for the rebuild** (it reads the 314 MB capstone
   telemetry CSV with pandas in a subprocess; ~14 s and fine on a developer machine, size not measured on the task).
3. `DEPLOY_STATUS` = POC/production (already needed for the mailer); `ALERT_PARTITIONS_*` only to change defaults.
4. Remove the old container's task/service and its EventBridge rules in the same deploy.

First live check: Wednesday 02/12 — `partitioner | …` lines at 08:00, `logs/partitions/partitions_weekly_2026-12-02.json` with
`"status": "ok"`, then the e-mail at 08:30.

## Decisions and open points

1. **EMIN's daily run was kept** (inside the app) **and moved from 10:30 to 11:30** (decision of the team, 25/11): EMIN's CSV reaches S3 around 11:10 (24/11: 11:12 Chile), so the 10:30 run always partitioned the previous day's file. The e-mail (12:00) waits for the 11:30 run. The old container ran it too, EMIN's 12:00 e-mail depends on it, and
   the task text only mentions Wednesday. The weekly run now covers *all* clients (as specified; before, it excluded the daily
   ones). EMIN's e-mail therefore also waits for its daily run. Say so if EMIN should not have a daily job.
2. **Subprocess instead of an in-process call** (above): chosen so the web process is never blocked or enlarged.
3. **Strict failure rule.** An S3-sync failure (exit 2) also blocks the e-mail even though the local partitions are valid,
   because the S3 copy is what other instances download. No retry was added (not approved).
4. EMIN's S3 `2026-11-16` partition was stale (3 rows vs 13) on 25/11 because the 10:30 daily run precedes the CSV's arrival
   (~11:10): explained by the schedule, not a fault; the move to 11:30 removes the one-day lag. EMIN generates alerts daily
   and not every day has alerts, so a day without new rows is normal for EMIN and is never treated as a failure.
5. **Freshness guard** (refuse to send when the partitions are older than the CSV) is still **not included**; the
   alerts-generated rule above is the narrower check the team asked for (would also have caught the 25/11 incident).
6. `pyarrow`/`pandas` are unpinned (see the note in step 1).

## Verification of step 3

`tests/test_partition_scheduler.py` (46 tests): defaults and env overrides; due times (Wednesday 08:00, daily 11:30, grace
window, any machine zone, DST); production-only start and the off switch; the command (weekly = every client, daily =
`--client emin`, never `--backfill`); status ok / failed (1, 2) / crash, never retried; once per schedule across 12 threads, a
restart and 6 real processes; a tick that returns while the job runs; the real subprocess runner (log streaming, exit status,
timeout); the e-mail not built nor sent when the run failed / is running / never ran (error logged, marker says why, no later
retry) and sent when it is `ok`; and a dry run of a Wednesday with one clock: 08:00 partitioner → 08:30 e-mail, and the same
day with a failing partitioner → no e-mail. The real script also ran through the subprocess path (exit status 1 propagated
from an empty data root) and the app boots with both schedulers reporting "not started: not production" locally. The alerts-generated rule is tested for zero alerts (not built, not sent, error, marker, no retry), alerts present (sent), unreadable
data, order against the partitioner check, and EMIN never blocked for an empty day. Existing
mailing/partition tests were updated for the 08:30 time and the removed `--schedule`.


---

# General tab: criteria on the page, "Sin Datos" fix, unit merge, golden layer (2026-11-26)

Requirement: *Unit status dashboard (criteria visibility, "Sin Datos" fix, unit merge, golden-layer reads)*. Not committed
(branch `dev`).

## What changed

| Change | Where |
|---|---|
| Golden layer: one script builds `data/general/golden/{client}/fleet_status.parquet`; the tab only reads it. The old on-the-fly processing is **removed** from `fleet_overview.py` (moved to the builder, not kept in parallel) | `src/data/fleet_status.py` (new), `scripts/build_fleet_status.py` (new), `dashboard/components/fleet_overview.py` (read + render only) |
| Scheduled at **10:30 America/Santiago**, daily, by the app's own scheduler; plus a build at app start, after the S3 mirror, for clients with no file (any environment) | `src/data/partition_scheduler.py` (job `fleet_status`, `catch_up_fleet_status`), `dashboard/app.py` |
| Alertas: a unit with no alerts is **Normal**; Sin Datos only when the feed cannot be read | `src/data/fleet_status.py` |
| `CT-184` / `CT_184` are one row; Estado computed after the merge; `T_09` / `T_9` too | `src/data/unit_ids.py` (new), builder |
| Criteria visible: collapsed "Cómo se asignan los estados" panel built from the constants the run uses | `dashboard/components/fleet_criteria.py` (new), `config/estado_rules.py` (Alertas / Tribología constants), `dashboard/assets/custom_layout.css`, 22 catalog keys (es/en) |
| Unit Detail still finds a merged unit's data in each source and links to each page with that page's own spelling | `unit_summary_content.py`, `oil_machine_detail.py`, `unit_horometer.py` |
| Informe preliminar de falla lists the General tab's names, so its unit matching (`report_health.unit_key`) now treats `-` and `_` as one separator (`T-10` finds `T_10` in the Predictivo / oil / maintenance sources) | `src/data/report_health.py` |

## Findings that shaped it (please read)

1. **Tribología's documented limits are wrong for the published data.** `oil_data_contracts.md` says Normal < 6 <= Alerta < 10 <=
   Anormal on the machine score; the published `overall_status` does not follow it (score 4 with one component in Alerta is Alerta;
   score 2 with an Anormal component is Anormal). What reproduces all 392 local machines: worst component status, Anormal when
   the score reaches 10. The page prints that rule; the contract document still says otherwise and should be corrected upstream.
2. **The S3 start-up sync deletes any local file S3 does not have**, so a file written by the script disappears on every
   start until the next 10:30 (it happened on the first local run: the tab was empty). Hence the build at app start, which runs
   *after* the mirror (`__main__` of `dashboard/app.py`, not at import), in every environment, on every start that finds a file
   missing (no once-a-day marker). Pushing the file to S3 (as the partitions are) was not done.
3. **EMIN's alert partitions are refreshed at 11:30** (its CSV arrives ~11:10), after this 10:30 run: EMIN's file carries the
   previous day's alerts until the next day's run. Other clients' alerts are partitioned weekly (Wednesday 08:00).
4. **A stale alert feed now also degrades units with no alerts** (they are Normal-with-old-data, and the age rule applies as for any
   cell). Local mirror: CDA's newest alert is from July, so its 11 units read Anormal in Alertas (their overall Estado was
   already Anormal, from Telemetría's age). Capstone and EMIN (feed 4-5 days old) are unaffected.
5. **Ids**: normalising to hyphens renames CDA (`T_10` -> `T-10`) and ENEX (`21_CRU_001` -> `21-CRU-001`) in the General tab and in
   the Unit Detail address; only EMIN had a real duplicate. Old links (`/overview/unit/T_10`) still resolve.
6. The "Última actualización" line under the title still shows the render time, not the file's run time (the file stores
   `generated_at`; showing it was optional in the requirement and is not done).

## Verification

* Before/after of the whole fleet (local mirror): Capstone 50 units, bands 9 / 11 / 30 unchanged (34 Alertas cells Sin Datos ->
  Normal); EMIN 58 -> 50 rows (8 merged: `CT-184`, `CT-185`, `CT-187`, `CT-190`...), bands Anormal 38 / Alerta 16 -> 8 / Normal 4;
  ENEX 281 unchanged; CDA 11 unchanged (Alertas Sin Datos -> Anormal, finding 4).
* `tests/test_fleet_status.py` (new, 56): ids, "no alerts" = Normal, merge, one row per unit, atomic write, failed run keeps the
  file, one client failing does not stop the others, the view never touches a raw source (and says "not available"), the criteria
  follow the constants, Alertas limits at the boundary, the Tribología sentence against every published machine; the failure report finds a hyphenated unit.
  `tests/test_partition_scheduler.py` (+10): due at 10:30, DST, env overrides, command, markers, start-up catch-up.
  `tests/test_fleet_overview.py` and `test_alert_partition_consumers.py` retargeted to the builder / golden file.
* Browser (Playwright on the local server): Capstone shows "UNIDADES ANORMAL (9)", the panel opens, search and links work, no
  console errors; EMIN `CT-184` is one row whose detail shows alerts and the oil components (5, last sample 09/11); CDA `T-10`
  shows horómetro, telemetry, alerts, oil and predictive.

* Full suite: every failure left is one that also fails on a clean copy of HEAD or depends on the data on disk (informe de falla AI
  schema / real-data counts, mantenciones, `test_report_health` x2, Campbell schema vs `oil_classified`, a page-views test that
  passes alone). The one test this work broke (`test_general_lee_sin_datos_como_sin_datos`, which patched a function that moved)
  was retargeted.

## Deploy

1. Nothing to configure: the app's scheduler runs it (production only, like the partitioner). `FLEET_STATUS_TIME=HH:MM` and
   `FLEET_STATUS_SCHEDULER_ENABLED=false` override. The app task needs write access to its `data/general` folder.
2. First start builds the missing files by itself; by hand: `python scripts/build_fleet_status.py`.
3. Watch `fleet status:` / `build_fleet_status:` lines in the app log; a failed run logs an error and the tab keeps the last file.
