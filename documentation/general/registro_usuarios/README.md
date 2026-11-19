# Actividad de Usuarios (formerly Registro de Usuarios) — implementation notes

Implements `registro_usuarios_specs.md` (TR-1, TR-2, TR-3) and the "Actividad de Usuarios" TR-6/TR-7 spec of 18 Nov 2026 (not stored in the repo;
TR-7 replaced the TR-2/TR-3 views). See section 5 for the page-view extension. Code: `src/auth_events/`,
`dashboard/tabs/tab_user_registry.py`, `dashboard/components/user_registry_*.py`,
`dashboard/callbacks/admin_callbacks.py`, `dashboard/assets/user_registry.css`.

## 1. The legacy login log (TR-1 item 1)

The spec describes a single parquet that every login read, modified and re-uploaded. That was the
**first** writer. By the time of this work the repo had gone through three writers; the data in S3
can contain any of them:

| Generation | Writer (removed) | Where it wrote | Columns |
|---|---|---|---|
| 1 | `src/utils/auth_logger.py` (only ran when `DEPLOY_STATUS=poc`) | `MultiTechnique Alerts/auxiliar/authentication_register.parquet` | `username, timestamp (naive local), success, ip_address` |
| 2 | same, later switched to CSV | `MultiTechnique Alerts/auxiliar/authentication_register.csv` | same |
| 3 (the one live before this change) | `src/utils/auth_event_logger.py::log_authentication_event` | one JSON per login: `MultiTechnique Alerts/auxiliar/authentication_register/year=YYYY/month=MM/day=DD/<YYYYMMDDTHHMMSSffffff>_<uuid>.json`, plus a local copy under `DASHBOARD_DATA_ROOT/auxiliar/authentication_register/` and a derived `authentication_register.parquet` rewritten on every login | JSON fields `event_id, username, timestamp (ISO UTC, ms), deploy_status, client_id` |

Generation 3 already fixed the lost-update problem for S3 (unique key per event) but still rewrote a
local parquet on every login, and had no `user_type`, no registry and an unmapped `client_id`
(first entry of the user's allowed-clients list, `unknown` when none).

**Why `environment = unknown`:** `deploy_status` was `os.getenv("DEPLOY_STATUS", "unknown")`: the
variable was missing in that deployment. Any value other than `POC` / `test` also reached the chart
unmapped. Generations 1–2 had no environment column at all.

Everything above was removed in the cutover (`auth_event_logger.py`, `auth_events_repository.py`,
their test, the old chart). Old objects stay in S3 and are archived by the migration.

## 2. New layout in S3

All keys live under the bucket/prefix the legacy log used: `AUTH_EVENTS_S3_ROOT`
(default `MultiTechnique Alerts/auxiliar/`).

```
auth_events/raw/dt=YYYY-MM-DD/<YYYYMMDDTHHMMSSmmmZ>_<event_id>.json   one object per login
auth_events/daily/dt=YYYY-MM-DD/events.parquet                          compacted, one per UTC day
auth_events/daily/dt=legacy/events.parquet                              migrated rows with no timestamp
auth_events/legacy/...                                                  legacy objects, archived unchanged
auth_registry/clients.json, users.json                                  maintained by hand
```

Configuration (all optional): `AUTH_EVENTS_LOCAL_DIR` (a directory instead of S3, for local runs),
`AUTH_EVENTS_DISPLAY_TZ` (default `America/Santiago`), `AUTH_REGISTRY_CACHE_TTL_SECONDS` (300),
`AUTH_EVENTS_CACHE_TTL_SECONDS` (60), `AUTH_EVENTS_RAW_RETENTION_DAYS` (7),
`AUTH_EVENTS_ENVIRONMENT` (overrides `DEPLOY_STATUS`: `POC`→production, `test`→development, else unknown).

Least privilege: login handler = PUT on `auth_events/raw/` + GET on `auth_registry/`; dashboard =
GET/LIST on both prefixes; compaction + migration = GET/PUT/DELETE/LIST on `auth_events/`.

## 3. Operating it

1. **Registry** (once): `python scripts/seed_auth_registry.py` uploads `config/auth_registry/*.json`
   (it refuses to overwrite). After that, edit the JSON and upload by hand. Without the registry the
   dashboard shows "No se pudo cargar…" and logins are stored as `unmapped`.
2. **Compaction** (daily): `python -m src.auth_events.compaction` (`--dry-run` to preview). It is
   idempotent. **Where it runs is still undecided** (open item 4); the dashboard works without it
   because it reads raw objects for days that are not compacted, but raw objects are only pruned by it.
3. **Cutover**: deploy this release → `python -m src.auth_events.migration` (dry run) → review →
   `python -m src.auth_events.migration --apply`. Logins between deploy and `--apply` are already
   stored by the new writer; legacy events logged by the *old* build before the deploy are picked
   up by running `--apply` again (idempotent, deterministic event ids). The migration prints
   per-user and per-environment counts to compare with the legacy data.

## 4. Decisions taken where the spec was open

- Display timezone default = `America/Santiago` (the app's existing `DEFAULT_DISPLAY_TZ`).
- "Recompact the last 3 days": a day is compacted if it is before today or within the last 3 days
  **and has raw objects** (nothing to add otherwise).
- Events of users of an *inactive* client (or a client missing from `clients.json`) are excluded
  from every figure and reported in an extra footnote, so the first KPI always equals the table total.
- `Último Acceso` and all counts use the full history filtered by Ambiente (period is applied in memory).
- Date, weekday, relative-time and number strings are es-CL as the spec defines them, in both UI
  languages; labels and captions go through the i18n catalogs.
- Seed registry = Appendix A + every account in `config/users.py`. Additions beyond Appendix A:
  `centinela` client and `centinela_user`, `a.casanga` (cda), `e.carvajal` and `f.vilches`
  (internal). **Open item 2/6: confirm these mappings.**
- Weekly buckets above 90 days: tooltip reads `Sem. D Mmm – D Mmm · n inicios de sesión`.
- Narrow screens: figures carry every x-axis label plus the desktop interval (`layout.meta.urTicks`);
  `dashboard/assets/user_registry_axis.js` widens the interval to the plot width so labels never
  overlap, and keeps the last day labelled when it had to thin them. At desktop width nothing changes.
- Relative-time phrases, "Nuevo" and the weekly tooltip go through the catalogs; dates and numbers
  stay es-CL in both languages.
- A client with `active = false` opened by URL shows "Cliente no encontrado" (open item 5, as built).

## 5. Page views and the merged views (TR-6, TR-7)

**Capture.** `dashboard/page_view_capture.py` installs one Flask `before_request` hook on
`/_dash-update-component` (Dash 4.4.1; pages need no edits). A *page opening* is the Dash Pages router
callback (output `_pages_content.children`) fired with `_pages_location.pathname` among the changed inputs
(navigation, reload, landing after login); a query-string-only change is not one. A *tab opening* is a
watched tab strip's `value` among the changed inputs; the path comes from the `Referer`. Tab strips are
listed in `TAB_COMPONENTS` (alerts, oil, telemetry, predictive component); a page that shows a default tab
is one view carrying that tab. Stored: `username`, `page_id`, `path` (no query/fragment/deployment prefix),
`tab`. `/` and the old `/admin/registro-usuarios` are not recorded (they only redirect). A non-admin never
records an `/admin/*` path (the route guard bounces them).

**Writing.** `src/auth_events/pageviews.py`: the request only appends to an in-memory buffer. A background
thread resolves user type/client (`users.json`) and `page_id` (`pages.json`) and writes one JSON Lines
object per UTC date, `auth_events/raw/dt=YYYY-MM-DD/pv_<stamp>_<batch_id>.jsonl`, every **20 minutes** (or at
100 events), **only between 07:00 and 22:00** display time (views recorded outside wait in the buffer), and
always at shutdown. Views can therefore appear in the dashboard up to ~20 min late, and a killed process
loses at most what was buffered since the last flush (overnight: since 22:00). 3 retries then an ERROR with the replayable payload; buffer cap 5,000 (oldest dropped,
ERROR). De-duplication (2 s) is per process.

| Variable | Default | |
|---|---|---|
| `AUTH_EVENTS_PAGE_VIEWS` | off | `1`/`true`/`on` enables capture. **Enable only after compaction is scheduled** |
| `AUTH_EVENTS_PAGE_VIEW_FLUSH_SECONDS` / `_FLUSH_SIZE` | 1200 / 100 | |
| `AUTH_EVENTS_PAGE_VIEW_FLUSH_WINDOW` | `07:00-22:00` | display timezone, `HH:MM-HH:MM` (may cross midnight) or `always` |
| `AUTH_EVENTS_PAGE_VIEW_BUFFER_CAP` / `_DEDUP_SECONDS` | 5000 / 2 | |

**Schema v2.** `page_id`, `path`, `tab` are added (null on logins). Logins are still written as the nine-field
v1 object; readers fill the missing columns with null. Compaction reads `.json` and `.jsonl`, rejects a
`page_view` without `page_id`/`path` (logged, object kept), rewrites a v1 day with the new columns, and
does not re-read settled days' batches every night (only the recompaction window and the pruning step).
`pages.json` (`auth_registry/pages.json`, seed in `config/auth_registry/`, uploaded by
`scripts/seed_auth_registry.py`) resolves `(path, tab)` -> `page_id` at write time and `display_name` at
read time; `<param>` path segments match one segment. A page missing from it is `unregistered` and is shown
by path.

**Data access.** `get_events(..., event_types=)`, `get_pages()`, `page_view_capture_start()`.

**UI.** Route `/admin/actividad-usuarios`; the old route redirects (the route guard changes only the
pathname, so the query string survives). The chart toggle swaps a pre-built figure in the browser; the chosen
metric lives in a store in the page layout (survives filter changes, resets between views). Internal ids
(`user_registry.*` i18n keys, `ur-*` classes, `admin-user-registry` nav id, module names) were kept.

### Decisions taken where TR-6/TR-7 were open
- Open item 1: `pages.json` was derived from the real routes (`NAV_PATHS`) and tab values in the code; the two
  Appendix A names are kept as written (`Overview › General`, `Administración › Mailing`), the rest follow the
  Spanish menu names. Predictive pages are listed per component (`motor`, `transmision`) and tab.
- Open items 4-6: flush 20 min inside 07:00-22:00 (was 30 s in the spec), 100 events, cap 5,000, dedup 2 s; admin pages recorded; reload counts).
- Layer-2 sub-tabs (Short/Long) and the `Vista de Reporte` selectors are not watched; hidden tabs are not either.
- The Última Actividad / Usuarios Activos / Clientes Activos figures include any event type; "Equipo Interno"
  active users count internal users only when *Incluir Usuarios Internos* is on.
- The page-view change chip is `–` unless the whole previous period is on/after the capture start; it uses the
  earliest page view in storage regardless of Ambiente.
- English wording: item 5 suggestions used; `Sin accesos` -> `No access`, `Sin inicios de sesión` -> `No logins`.
