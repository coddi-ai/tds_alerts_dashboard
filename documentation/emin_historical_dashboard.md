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

### Visual alignment with Resumen

The overview uses the same compact search and unit link styling as
Resumen de flota. The cut remains visible across both views. Group and
movement filters share the ranking header space, and the fleet charts
follow the ranking. The detail uses light section headers and a single
card for the milestone list.

Playwright used the real local cut on 24 November 2026 in the isolated
Dash view. It confirmed that the ranking precedes the charts and that
the CT-187 unit code opens its detail with the three section headers.
Document width matched the viewport at 1440, 1024, and 390 px. Timeline
rows rendered as cards at 390 px. The offline command above passed
57 tests with 8 warnings.

### Fleet criticality by period

The EMIN overview shows up to five units for the selected cut and period:
7 days, 90 days, 180 days or the full available source history. All fixed
windows include the cut. The ranking counts distinct days with explicit
source severity first. For short term it then uses average observed
score, followed by the share of observed days with positive points.
The other periods use the same two measures in reverse order. Historical
ranking also uses documented major intervention days after critical days
and before score-based measures.

Score calculations require two distinct observed days with finite scores.
Estimates are excluded. An explicit critical day can qualify a unit on
its own. The table shows observed score days against the period, the
latest documented milestone and the number of units with limited score
coverage. For historical coverage, the denominator starts at the first
published scoring day, even if the underlying evidence goes back further.
The top is the main review queue. The full ranking follows it, and the
low-signal list is collapsed by default. Each top row separates the reason
for its position from recent score movement. The view calls out when the
90- and 180-day windows have the same scoring days.

Opening a unit from the top explains its position and brings the selected
period's milestones forward. Medium-term detail shows event groups
recurring on days with a signal. Long-term detail summarizes monthly
observations and compares the 14 days on either side of the latest usable
major intervention, requiring two observed days on each side. The full
chronology remains available.

On the real 24 November cut, the two fixed longer windows shared 84
published scoring days. None of the 108,932 observed records carried the
structured critical or intervention flags consumed by this view. Sixteen
records matched milestone wording and retain the text-match label. The
historical top therefore ranks the observed score signal on that package.

The offline command above passed 57 tests. With the real package, the
isolated Dash browser review selected 90 days, opened CT-186, verified
its position and reason, then returned to the same period, cut and
unit control.

### Unit score contributions

The unit detail lists applied event points by component or event group
using the producer's `event_contributions[].applied` values. Alerts,
tribology, and residual points appear separately when the package cannot
attribute them to an individual component. The top uses the entire
selected period. Other entry points show the latest observed day through
the cut. Estimated scores are excluded from this breakdown.

The detail now shows the component-attributed share of the full score,
each row's share, and the number and latest date of contributing days.
The disclosure on each component samples up to three distinct published
event descriptions on each of its latest three contributing days.
Those are producer score records. Original evidence remains in the
chronology, and unallocated source points stay visible separately.
For a published event description the detail can filter the chronology
to records with the same equipment, day and event name. Several source
records can match one contribution, so the action does not imply a
one-to-one source record ID.

The local package check reconciled every one of the 3,683 observed daily
scores, built the detail for EXC-069 and confirmed that an estimated row
produces no attribution. The EMIN regression suite passed seven tests.

### Review workflow refinements

Recent movement has a contribution comparison using the same two
observed days and applied source scores. It also shows offsetting
changes when the net score stays stable. The trend leaves gaps for
days without observed scores and draws estimates as separate markers.
In the fleet overview, movement counts and event groups provide access
to the ranking filters. The duplicate movement chart was removed.
The Top 5 uses compact cards at phone widths to keep the reason,
movement, milestone and coverage visible.

The full chronology supports text search, evidence type filters and
pages of 40 records. It remains bounded by the selected cut and each
listed record can disclose original fields. Search and filter changes
reset pagination. CT-194 has 9,447 records in the local package.

The offline regression command above passed 57 tests. The isolated
browser review confirmed that the worsened shortcut selected four
units and focused the ranking. It also moved to chronology records
41–80, then selected maintenance and returned to the first 40 of 134
matching records for the default unit.

At the November 24 cut, 13 units had changes in their score
contributions. The package check reconciled each observed unit
comparison with its published score delta.

### Completed replacements

The detail shows the latest three Golden replacement actions with a
valid execution date through the cut. The chronology offers all such
actions as a filter, with the original source fields available for each.
Replacements are displayed separately from critical findings and do not
change priority. The local 24 November cut had 73 dated replacements
across 23 units. All 2,766 positively scored event contributions with
descriptions had matching unit, day and name in the local chronology.
In the isolated browser, the CT-187 tire contribution opened four
matching source rows. The replacements shortcut then cleared that query
and showed the four completed replacements for the same unit.

### Publishing follow-up

- Confirm who owns publication of `latest.json` and immutable run folders under
  the documented prefix, including whether the producer will include complete
  major maintenance/failure records in `observed.json`.
- After publication, run the normal dashboard sync, verify a real run ID and
  source rows, then repeat EMIN access, movement, timeline, and visual checks
  against that package before integrating the branch.
