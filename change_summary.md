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

---

# Change summary — Hot Sheet, Menace Control, Fleet overview and Unit summary read the partitions

**Status: four of the five consumers are migrated. The alert-summary e-mail is held for a decision**
(its schedule check failed, see below), and with it the removal of the CSV loader.

## Consumer audit (`consolidated_alerts.csv`, runtime code)

| Reader | Status |
|---|---|
| Hot Sheet (`hot_sheet_callbacks.py`) | **migrated** |
| Menace Control (`menace_control_callbacks.py`, 3 callbacks) | **migrated** |
| Fleet overview (`fleet_overview.py`: status map, window counts, feed freshness) | **migrated** |
| Unit summary (`unit_summary_content.py`: alerts card, data date) | **migrated** |
| Alert-summary e-mail (`src/mailing/alert_summary.py`) | **not migrated, needs a decision** |
| `src/data/alert_partition_builder.py` (engine of `scripts/partition_alerts.py`) | allowed: it is the partitioner |

**Found beyond the expected five. Listed, not migrated, need approval:**

| Reader | What it does |
|---|---|
| Data-source freshness chips: `src/data/source_freshness.py` reads the CSV's `Timestamp` column (`config/service_data_sources.py`, source `alerts_consolidated`) | shown on Alertas, Fleet overview and the mailing admin page |
| Source availability probe: `src/data/catalog.py:251` (`file_probe("alerts", "alerts_consolidated", "consolidated_alerts.csv")`) | existence, size and mtime only |
| Campbell AI assistant: `src/campbell_ai/data.py:130`, dataset `alerts` | loads the whole CSV for the agent's tools |
| `config/settings.py:304` `get_consolidated_alerts_path` | no caller: dead code |
| `scripts/translate_text_fields.py` / `translation_mapping.json` | offline demo-data tool, not runtime |

So the acceptance criterion "no runtime code outside `scripts/partition_alerts.py` references
`consolidated_alerts.csv`" is **not met**, and cannot be without migrating the e-mail and the three
extra readers above. None of those was touched.

## E-mail schedule check — result: weekly freshness is NOT enough for EMIN

From `src/mailing/config.py` and `periods.py` (times in `America/Santiago`):

| Client | Schedule | Period covered | Newest alert it needs vs. the last partition run (Wed 04:00) |
|---|---|---|---|
| capstone | weekly, Wednesday 12:00 | previous Monday–Sunday | Sunday 23:59; the Wednesday 04:00 run already holds it. **OK**, provided the run has finished and its partitions reached the mailing process (it syncs `data/` from S3 right before a scheduled send) |
| emin | **daily, 12:00** | **the previous day** | Thursday's send covers Wednesday, and the sends from Thursday to Tuesday cover days newer than the last run. **Those alerts would be omitted.** |

EMIN's schedule is live in code (`logs/mailing` shows sends on 2026-11-10 and 11-11), although its scheduled
audience is currently only the Coddi technical contacts (`SCHEDULED_TECHNICAL_ONLY_CLIENTS`). As the requirement
says, I stopped there: **the e-mail still reads the CSV, and no other refresh mechanism was built.** Options for the decision:

1. Keep the e-mail on the CSV as a recorded exception.
2. Move EMIN's e-mail to a weekly cadence (changes the e-mail's content and schedule: out of this scope).
3. Refresh partitions more often (out of scope by definition; separate approval).
4. Migrate capstone's weekly e-mail only and keep EMIN's on the CSV.

The e-mail's baseline timings are below so a later migration can be compared. If it is migrated, it must also reach
the partitions in whatever process or container sends it (today the dashboard container mounts `./data:ro`, and the
pre-send S3 sync downloads them).

## What changed

New in `src/data/loaders.py`, all on top of `src/data/alert_partitions.py`:

- `load_alerts_since(client, since_utc)`: whole weeks that overlap `[since, ∞)`, same normalized frame as the Alertas
  loaders (EMIN evidence included). Empty-with-columns when the window has no alerts but the client does.
- `latest_alert_timestamp(client)`: the feed's newest `Timestamp`, read from one column of the newest week.
- `load_alert_units(client, dated_only=False)`: every unit of the history, from `_alert_index.parquet`.

| Section | Reads now | Same output because |
|---|---|---|
| Hot Sheet | last 14 days of weeks; the unit list from the index | the status rule only counts 7- and 14-day windows; units without recent alerts still appear as "normal" |
| Menace Control | the selected `days` of weeks | each callback's own `Timestamp >= now - days` still trims the rows |
| Fleet overview | status: 30 days; counts: 56 days plus the index's units (zeros); freshness: newest week | the counts keep every unit of the history, same keys and order |
| Unit summary | 30 days before the reference date; data date from the newest week | `_reference_time` still anchors on the feed's newest alert |

"The client has no alert data" (`client_has_alert_partitions`) and "nothing in the window" are kept apart, so each
section's two different messages are unchanged. Layout, weekly script, schedule and S3 sync were not touched.

**Freshness change (accepted, documented per section).** These sections used to show the CSV as of the moment of the
request. They now show the data of the last weekly partition run (**Wednesday 04:00**), like the Alertas views: Hot
Sheet; Menace Control; Fleet overview (statuses, window counts and the freshness label); Unit summary (the alerts card
and its data date). A running dashboard also needs the new partitions on its disk (shared volume or next startup sync).

## Verification

- **Snapshots, pre-change vs final: identical.** 150 snapshots (Hot Sheet; Menace Control's three callbacks at 3, 30,
  90 and 365 days; Fleet overview output, status map and window counts; Unit summary and its alerts card for four units
  each, one of them unknown; the data date) for capstone, cda and emin at two frozen clocks: 2026-11-18 12:00 and
  2026-02-11 15:30:17 (which puts every cut-off in the middle of a week and of the history). The same harness run twice
  on the old code was identical, so the comparison is not noise. The harness is not in the repo.
- **Tests** (`tests/test_alert_partition_consumers.py`, 23): every section and loader runs with the CSV deleted (any
  attempt to look for it fails); each section equals the run over the whole normalized history, for several windows;
  mid-week cut-offs return exactly the alerts in range, and the reader opens only the weeks it needs (14 days = at most
  3 files; the data date reads one file); no partitions, a window past the last alert, unknown units, an undated-only
  history and a stale feed raise nothing and keep their messages. In `test_unit_detail.py`, two tests that patched the
  removed `usc.load_alerts_data` now patch the new calls.
- **Full suite.** The untouched HEAD fails 31 tests and 2 errors on this machine (`informe_falla*`,
  `mantenciones_productive`, `report_health`, two in `campbell_ai_resources`: unrelated and pre-existing). With this
  change the same set fails plus one more, `test_alert_partitions.py::test_the_weekly_sync_refuses_to_run_before_the_backfill_reached_s3`.
  That one is **not from this change**: the working tree has an uncommitted edit to `src/data/alert_partition_s3.py`
  (a new `S3Dataset` for another partition set) that changed the error text the test matches ("no complete history"
  became "no complete alerts history"). I did not touch it.

## Impact on response time

`capstone`, default filters, callbacks invoked directly, Windows laptop, pandas engine. Cold = first call in a fresh
process; warm = median of 5 further calls. Two sets:

- **A**: re-measured with the before and after processes *interleaved*, median of 7 fresh processes.
- **B**: the whole list, median of 3 fresh processes, the before run and the after run one after the other.

Machine load moved the *same unchanged code* by up to ±80 % between runs (the e-mail rows), so read the warm figures
of the heavy sections in set B as indicative only.

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
| E-mail capstone weekly (default), **not migrated** | 965 / 20 | 944 / 21 | unchanged code | | B |
| E-mail capstone 4 weeks, not migrated | 907 / 45 | 927 / 49 | unchanged code | | B |
| E-mail emin daily, not migrated | 1,368 / 1,800 | 1,532 / 3,288 | unchanged code (shows the noise) | | B |

Reading it:

- **Cold is lower at default filters in all four capstone sections**: clearly for Hot Sheet (−36 %) and Fleet overview
  (−29 %); only marginally for Menace Control (−6 %) and Unit summary (−3 %, within run-to-run noise). The large wins are
  EMIN (−65 % to −86 %): the old path re-ran EMIN's maintenance-evidence enrichment over the whole history on every call,
  and now it runs over the loaded weeks only.
- **Warm is slower for Menace Control, Fleet overview and Unit summary at default filters** (+59 %, +46 %, +25 %; in
  absolute terms roughly +10 to +60 ms per interaction). The old path served the whole history from an in-process cache
  (`lru_cache` plus a deep copy), so a repeated call cost almost nothing. The new path re-reads a few Parquet files each
  time (about 20 ms for each of Fleet overview's two alert reads, and several alert reads add up on a Unit summary page).
  Caching is excluded by the requirement. This is "slower than before at default filters" in the sense of the rule, so
  **it needs approval before merging** (decision 2).
- Non-default scenarios that got slower on cold: Menace Control 365 d (+14 %: it reads 53 weeks), Unit summary on cda's
  stale feed (+14 %), Fleet overview cda (+12 %). cda has only 152 alerts in total, where the old cached CSV is tiny, so
  a small history gains nothing from partitioning and pays a per-file cost.
- Growth: the old cost grew with the history; the new one grows with the window.

## Open decisions (need approval before merging)

1. **E-mail** (above): EMIN's daily e-mail needs alerts newer than the weekly run. Until one of the listed options is
   chosen, the e-mail, `load_alerts_data` and `_load_alerts_data_cached` stay. They are the only runtime use left of the
   CSV loader (tests that call it aside).
2. **Warm-path regression** at default filters in Menace Control, Fleet overview and Unit summary (cold is lower).
   Options: accept it (a few tens of ms per repeated interaction); approve **column projection** on these reads (the
   sections use about 6 of the 13 columns; not done, since it is a performance change beyond the migration); or approve
   caching (excluded today). Nothing was added.
3. **Other CSV readers** (data-source chips, catalog probe, Campbell AI): migrate them, or accept the CSV as a documented
   exception for them. Until then the CSV stays on disk and readable.
4. The windows live as constants next to the rules they serve (`ALERT_STATUS_WINDOW_DAYS`, `ALERT_WINDOW_DAYS`,
   `ALERTS_WINDOW_DAYS`), so changing a rule's window changes what is read.
5. Unrelated, found on the way: the uncommitted `alert_partition_s3.py` edit breaks one existing test (above), and 31
   other tests already fail on a clean HEAD here.


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
  (59 new tests in `tests/test_telemetry_partitions.py`). **Not run against the real bucket** — see open point 2.
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
| `--verify-s3` identical to local after a sync | Implemented and tested with the double; **not run on the real bucket** |
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
2. **The S3 backfill was not synced**: it is optional and off by default, and pushing to the real bucket is outward
   facing. The order matters for a deployment: **(1)** `--backfill --dataset telemetry` (done locally),
   **(2)** `--backfill --sync-s3 --dataset telemetry` (uploads the 82 objects and writes the markers),
   **(3)** `--verify-s3`, **(4)** only then deploy this code and restart the dashboards. A dashboard running this
   code without the partitions on its disk shows "no hay datos de telemetría" for every alert (no errors) until they
   arrive. I can run steps 2–3 on your word.
3. **Not done, needs approval — stop downloading the source CSVs in the dashboards.** The dashboards' startup mirror
   still downloads the 327 MB of wide telemetry CSVs (capstone 309 MB, CDA 18 MB) that no dashboard code reads any
   more; only the partitioning script (whose volume must keep them) does. Excluding them from the dashboards' mirror
   would cut each cold start by that amount. It is a separate performance change, so it was not made.
4. **Campbell AI schema declaration.** `alerts_detail` is now a Parquet dataset, so its entry in
   `src/campbell_ai/schema/dataset_columns.json` was changed from `csv` to `parquet`. The copy **generated** in the
   data root (`auxiliar/dataset_columns.json`, takes precedence, refreshed weekly by `schema.refresh`) still says
   `csv` until its next refresh; meanwhile `validate_client` cannot trust the declaration for that dataset and probes
   it (≈ 27 ms instead of ≈ 3 ms per session opening). Run `python -m src.campbell_ai.schema.build` at deploy, or wait
   for the weekly refresh. Not done here: it rewrites every dataset's declaration, including unrelated ones that
   already drifted.
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
