# Registro de Usuarios — login events (implementation notes)

Implements `registro_usuarios_specs.md` (TR-1, TR-2, TR-3). Code: `src/auth_events/`,
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
