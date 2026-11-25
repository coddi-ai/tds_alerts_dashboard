# Historical EMIN fleet view

The dashboard adds `Resumen > Histórico de flota` for the EMIN client. The
page reads a local, immutable analysis bundle and never queries or writes to
S3/SharePoint itself. The normal dashboard S3 sync makes the bundle available
under the configured data root.

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
manifest and daily ranking, and uses the observed records for the evidence
table. Daily rows carry the date, equipment, relative rank, heuristic points,
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
   event groups, and source evidence. If the pointer or package is invalid, the
   page shows an unavailable state instead of a partial ranking.

The dashboard branch implements the consumer and the sync freshness check.
It does not upload a package or change the EMIN producer. The producer still
needs to publish to the documented prefix before the page can show a real
package in a deployment.

## Interpretation

The daily rank is relative within the package's fleet and the score is
heuristic; neither is a failure probability. Missing observations remain
separate from an estimated score and from an observed score of zero. Ranking
event groups are aggregated by equipment and day. The evidence panel therefore
shows all available source records for that equipment and day without
misattributing a daily group to an individual source row. Operational alerts
can arrive one day late.

## Implementation handoff

### Objective and result

Add an EMIN-only `Resumen > Histórico de flota` tab that presents the weekly
fleet package in the same dashboard shell and visual language as the existing
overview. The dashboard consumer, package validation, navigation, localization,
responsive charts, and S3 freshness handling are implemented on branch
`ai/codex/emin-historico-flota`.

### Changed areas

- Navigation and access: `dashboard/services_registry.py`,
  `config/client_services.json`, `config/client_services.py`, and the EMIN page
  callback authorization check.
- Page and presentation: `dashboard/pages/overview_emin_historical.py`,
  `dashboard/tabs/tab_emin_historical.py`,
  `dashboard/components/emin_historical.py`, and dashboard styles.
- Data and sync: `src/data/emin_historical.py` validates and reads the local
  immutable package; `src/data/s3_downloader.py` refreshes same-size pointers
  when their remote `LastModified` changes.
- Language, documentation, and regression coverage: locale files, README,
  package contract, access, sync, and navigation tests.

### Local commits

Implementation commit: `8914f09` (`feat: add EMIN historical fleet overview`).
The branch is local only; no remote push is part of this task.

### Validation

- Focused offline regression command: `python -m pytest -q tests/test_emin_historical.py tests/test_s3_downloader_sync.py tests/test_client_services.py tests/test_navigation_shell.py` — 55 passed.
- Full offline profile command: `python -m pytest -q tests` in the test image
  with Docker networking disabled — 2,480 passed, 13 skipped, 20 failed, and
  51 errors. Remaining failures/errors are outside this feature, including
  report/AI fixtures and page-view tests whose
  `config/auth_registry/pages.json` seed is absent in this checkout. The
  focused EMIN, sync, client-access, and navigation suites pass.
- `git diff --check` — passed with no whitespace errors.
- Visual review used the local dashboard and a locally fabricated package
  shaped for the consumer, not records from EMIN. At 1,440 px the page matches
  the shared header, sidebar, typography,
  cards, and tables; the Resumen link navigates to the page. At 1,024 px the
  filters and content stack cleanly. At 390 px the sidebar becomes an icon rail
  and the document has no horizontal overflow. With `Motor / Emisiones` and
  `BULL-031` selected, the evidence panel displayed two same-day source rows,
  including an EGR event and a maintenance record. This is UI evidence only;
  it does not validate a real published package.

### Risks and decisions

- The EMIN producer has not yet published a real bundle to the documented S3
  prefix. The visual fixture is not production data. The loader rejects
  manifests with `synthetic: true`; no real published bundle was available for
  this review.
- The consumer is read-only. It relies on the existing dashboard S3 sync and
  does not call S3 or SharePoint from callbacks.
- The ranking and score are heuristic, not a failure probability; alert data
  can lag by one day. Ranking groups aggregate by equipment and day, while the
  evidence panel preserves the selected day's source rows.
- EMIN authorization is checked server-side against the user's allowed clients;
  other clients remain default-denied for this page.

### Open questions and next action

- Confirm the owner and release schedule for the producer that publishes
  `latest.json` and immutable run folders under the documented prefix.
- After publication, run the normal dashboard sync, verify the real run ID and
  source rows, then repeat the EMIN access and visual smoke check against that
  package before integrating the branch.
