# Historical EMIN fleet view

The dashboard adds an EMIN-only `Resumen > Histórico de flota` page with two
internal views: a fleet overview and an equipment detail. It reads a local,
immutable analysis bundle and never queries or writes to S3/SharePoint itself.
The normal dashboard S3 sync makes the bundle available under the configured
data root.

## Package contract

Publish these keys below the existing `MultiTechnique Alerts/` S3 prefix:

```text
emin_historical/published/latest.json
emin_historical/published/<run>/manifest.json
emin_historical/published/<run>/daily.json
emin_historical/published/<run>/observed.json
```

`<run>` uses the immutable run folder name emitted by the EMIN weekly process,
for example `20261124T0000-0300-<sha256>`. `latest.json` contains
`{"run":"<run>"}`. The consumer resolves it locally as
`<data-root>/emin_historical/published/latest.json`.

The manifest must mark `synthetic` as `false`. The dashboard requires the
manifest and daily ranking, and uses observed records for the event timeline.
Daily rows carry the date, equipment, relative rank, heuristic points,
observation/estimate state, alert and event counts, and `event_groups`. Observed
rows carry the date, equipment, kind, source timestamp, level, and source
`details`.

## Publishing sequence

1. Finish an EMIN package in a staging directory and validate all required
   files before making it visible.
2. Upload the whole immutable `<run>/` folder under the prefix above.
3. Replace `latest.json` only after every file in the run has uploaded
   successfully. Keep the previous run until the replacement has been
   validated by the dashboard.
4. The existing dashboard sync downloads the prefix into `data/`. It compares
   both object size and S3 `LastModified`, so a same-size `latest.json` is
   refreshed when the package changes.
5. Open the EMIN-only page and check its run capture time, ranking, selected
   event groups, movement counts, and source timeline. If the pointer or
   package is invalid, the page shows an unavailable state instead of a
   partial ranking.

The dashboard branch implements the consumer and sync freshness check. It
does not upload a package or change the EMIN producer. The producer still
needs to publish to the documented prefix before the page can show a real
package in a deployment.

## Interpretation

The daily rank is relative within the package and the score is heuristic;
neither is a failure probability. Movement compares the two latest distinct
days with observed, non-estimated scores up to the selected cut. A lower score
is shown as relative improvement, a higher score as relative worsening, and a
change within 0.001 points as stable. The detail shows both dates and both
scores. A comparison is unavailable until two observed scores exist. This is a
directional reading of the heuristic signal, not a condition diagnosis.

Missing observations remain separate from estimates and from an observed
score of zero. Ranking event groups are aggregated by equipment and day; the
event timeline retains every observed source record for the selected unit up to
the cut. Its time span is bounded by the records the producer includes in the
published package.

The timeline distinguishes explicit critical/severe fields from text matches
for major changes or failures (such as engine replacement or explosion). A
text match is labelled as such and is a review cue, not confirmation that the
failure occurred. Operational alerts can arrive one day late.

## Implementation handoff

### Objective and result

Add an EMIN-only `Resumen > Histórico de flota` view in the existing dashboard
shell. The redesign separates the fleet overview from equipment detail while
keeping the shared header, navigation, cards, chart theme, tables, and Spanish /
English labels.

The fleet overview summarizes improved, worsened, stable, and incomparable
units; plots movement counts and event groups; and adds the recent movement to
each unit's ranking row. It separates recent source critical events from score
priority and the lowest observed score list. Criticality uses source severity
within the seven calendar days ending at the selected cut. The score lists use
observed, non-estimated finite scores and do not overlap. Equipment detail shows the latest observed comparison,
heuristic score history, and a dated timeline of all source observations in
the package through the selected cut. Major events appear in a separate
highlights section before the full chronology. Explicit source severity and
textual major-event matches have different labels.

### Changed areas

- Page layout: `dashboard/tabs/tab_emin_historical.py` adds the two views and
  view-specific filters.
- Presentation and interpretation: `dashboard/components/emin_historical.py`
  calculates movement and builds the charts, prioritized fleet lists, ranking,
  status card, and highlighted timeline; `dashboard/callbacks/emin_historical_callbacks.py`
  handles the view switch and bound data.
- Responsive style: `dashboard/assets/custom_layout.css` keeps the EMIN header
  legible, frees the mobile content width, uses a navigation drawer, and turns
  evidence rows into readable cards on narrow screens.
- Localization and regression coverage: `src/i18n/locales/es.json`,
  `src/i18n/locales/en.json`, and `tests/test_emin_historical.py` cover the new
  status language, package timeline, major-event flags, and false-positive
  regression for the word “preventiva”.
- Package loading, navigation, authorization, and S3 freshness handling remain
  as implemented in `8914f09`.

### Local commits

- `8914f09` — `feat: add EMIN historical fleet overview`.
- `8ca88d8` — `docs: record EMIN historical dashboard handoff`.
- `854db57` — `feat: split EMIN fleet history overview and detail`.
- These commits are local on branch `ai/codex/emin-historico-flota`; no remote
  push is part of this task.

### Validation

- Focused offline regression command:
  `$repo = (Get-Location).Path; docker run --rm --network none --entrypoint python -v "${repo}:/app" -w /app tds-alerts-dashboard-emin-test:latest -m pytest -q tests/test_emin_historical.py tests/test_s3_downloader_sync.py tests/test_client_services.py tests/test_navigation_shell.py`
  — 57 passed (8 warnings from existing pytest hooks / return-value tests).
- Python compile check:
  `python -m py_compile dashboard/components/emin_historical.py dashboard/callbacks/emin_historical_callbacks.py dashboard/tabs/tab_emin_historical.py tests/test_emin_historical.py`
  — passed.
- Both locale JSON files parsed successfully.
- `git diff --check` — passed.
- Browser visual audit compared the shared shell at 1,440 px and 1,024 px,
  then checked both views at 390 px. At phone width the page has no document
  horizontal overflow; the navigation opens as a drawer, the top-bar controls
  fit, and evidence becomes a sequence of readable event cards. At desktop and
  tablet sizes the Bootstrap cards, tabs, filters, charts, and responsive tables
  remain aligned with the existing dashboard.
- The local UI audit used a temporary fabricated package with five equipment
  examples and eight daily cuts. It showed each movement state, the comparison
  dates, an EGR event, an engine change, and an explosion report. The fixture
  was isolated from S3/SharePoint and is not EMIN evidence. Its local manifest
  temporarily used `synthetic: false` only to exercise the production consumer;
  it was removed after review. The package loader's `synthetic: true` rejection
  is separately covered by a test.
- The fleet-priority and event-highlights additions were not re-audited in a
  browser during this follow-up. Their behavior is covered by offline tests;
  repeat the 1,440 px, 1,024 px, and 390 px visual review before integration.
- The earlier full offline suite for the original implementation reported
  2,480 passed, 13 skipped, 20 failed, and 51 errors in unrelated report/AI and
  page-view fixtures. This redesign did not rerun the full repository suite;
  focused EMIN, sync, client-access, and navigation suites passed.

### Risks and decisions

- No real published EMIN bundle was available. The visual review validates the
  interface and package contract, not production records or producer coverage.
- Showing every major change requires the producer's `observed.json` to include
  those records throughout the intended period. The detail explicitly states
  that the timeline span depends on package coverage.
- Major-event text recognition is heuristic. Explicit source severity is
  separated from textual matches, and matches are not treated as confirmed
  failures. Other wording may require additional patterns.
- The ranking and score are heuristic, not a failure probability. Movement
  labels describe score direction, not a diagnostic result. Alerts can lag by
  one day.
- Critical review prioritization depends on source severity fields and covers
  seven calendar days through the selected cut. Text matches remain review
  cues and do not raise an equipment's critical priority.
- The page remains EMIN-only and read-only; server-side authorization still
  checks the user's allowed client.

### Fleet-to-unit review · 25 November 2026

The fleet cards and ranking now open the unit directly. Returning restores
the source button and scroll position while retaining the cut and the ranking
filters. Search and movement filters affect the ranking only. The detail
shows the first three milestones, with disclosure controls for additional
milestones and the source fields for each record.

Validation used the local real package for the 24 November cut. Playwright
opened CT-187 from its fleet card, expanded a source record, and verified
the return to the original control with the cut retained. The detail had no
document overflow at 1440, 1024, or 390 px. The 390 px event rows rendered as
cards. The browser used an isolated Dash layout with the production EMIN
components and callbacks, so this did not verify the production login or
the full dashboard shell.

Offline command from the worktree in PowerShell:

```powershell
docker run --rm --network none --entrypoint python -v "${PWD}:/app" -w /app tds-alerts-dashboard-emin-test:latest -m pytest -q --disable-warnings tests/test_emin_historical.py tests/test_s3_downloader_sync.py tests/test_client_services.py tests/test_navigation_shell.py
```

Result: 57 passed with 8 warnings. The real package had five prioritized
scores and five lower observed scores at this cut. There were no recent
explicit critical records, so a live positive example of that branch
was unavailable.

### Publishing follow-up

- Confirm who owns publication of `latest.json` and immutable run folders under
  the documented prefix, including whether the producer will include complete
  major maintenance/failure records in `observed.json`.
- After publication, run the normal dashboard sync, verify a real run ID and
  source rows, then repeat EMIN access, movement, timeline, and visual checks
  against that package before integrating the branch.
