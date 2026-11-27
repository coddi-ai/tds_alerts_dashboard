# Multi-Technical Alerts Dashboard

Interactive Dash web application for fleet health monitoring, consolidating oil (tribology),
telemetry, maintenance, and cross-technique alerts data into a single platform.

This repository is **dashboard-only**: it reads pre-processed Gold-layer data (produced by an
upstream data pipeline) from `data/{technique}/{layer}/{client}/` and, if that folder is missing
locally, syncs it from S3 on startup. There is no data-processing pipeline in this repo.

## Features

- **Authentication**: Username/password login with per-client, role-based access (`admin` vs `client`)
- **Multi-client**: Global client selector in the header switches all views (CDA, EMIN, ENEX, CAPSTONE)
- **Resumen (Overview)**: Fleet-wide status summary and per-unit data freshness
- **Monitoreo (Monitoring)**: Alertas (consolidated alerts), Telemetría (sensor health), Aceite (oil/tribology, incl. lab compliance)
- **Predictivo (Predictive)**: Component-level failure-mode KPIs and evidence, restricted to select clients
- **Integración / Reportes / Administración**: Placeholder sections reserved for future work

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the project root (see `config/settings.py` for all options):

```bash
BUCKET_NAME=...          # S3 bucket holding processed data (used for auto-sync)
ACCESS_KEY=...
SECRET_KEY=...
OPENAI_API_KEY=...       # optional, for AI-generated recommendations/insights
MAPBOX_TOKEN=...         # optional, for the GPS location map in Alerts detail
```

### 3. Get Data

The dashboard expects processed data under `data/{technique}/{layer}/{client}/` (see
[Data Layer Structure](#data-layer-structure) below). On startup, if the local `data/` folder is
missing, `dashboard/app.py` automatically syncs it from S3 via `src/data/s3_downloader.py`. If you
already have a `data/` folder, it's used as-is and no sync happens.

The EMIN historical tab reads the immutable weekly package from
`data/fleet_history/golden/emin/{YYYY-Www}/`, mirrored from
`s3://teck-cda-datasource/MultiTechnique Alerts/fleet_history/golden/emin/{YYYY-Www}/` by the same
S3 sync used by the other tabs. Each week contains versioned `manifest`, `daily`, `observed`, and
compressed `dashboard` files plus `latest.json`. The dashboard chooses the pointer with the newest
capture time. The current read model contract is `coddi.emin.historical-dashboard.v2`, produced by
`Analisis_Historico_Flota`; it contains precomputed fleet views for all units, weekly/monthly/quarterly/
historical variation, criticality windows, equipment movements, component contributions, and evidence
classifications. The reader remains compatible with v1 for existing packages; the fleet variation view
is available after the data repo publishes and syncs v2. The tab resolves package file references and
renders the selected view; scoring, ordering, aggregation, and event classification belong to the
producer. A package from before v1 must be republished by the data repo.

The EMIN `condition_model` v2 is an optional, separately marked Beta read model inside the producer's
precomputed report. It carries the source alert run ID and SHA-256 digests for the alert CSV, its
manifest, source columns, and the base package files. The reader checks the model version, unit roster,
cutoff, dates, and digest shapes before exposing it; older packages without this block continue to use
the existing historical page. The dashboard renders the producer's score, levels, weekly changes,
group scopes, evidence, and source-date markers. It never scores or joins source records itself.

The Beta score sums active conditions at 1, 2, or 3 points. It accepts health, safety, operational
condition, and fluid alerts; it excludes connectivity, operator-conduct, administrative-compliance,
scheduled-maintenance, and unclassified severity rows. Confirmed alert-to-oil links contribute the
greater of the two signals. A quiet week carries known conditions forward. An executed replacement with
a specific component and reference can close older conditions for that component. Source dates describe
the newest located record and do not certify full reporting coverage. See the producer's
`METODOLOGIA_EMIN.md` for the complete rule set and examples. This Beta is for verification and must
not be read as a probability of failure or an adopted operational priority without maintenance review.

The fleet overview plots every unit with comparable observations: previous-period average on the
horizontal axis, selected-period average on the vertical axis, and color for improved, worsened, or
stable. Priority units receive larger markers and labels; units without a valid comparison are counted,
and the full roster remains below the chart. Weekly, monthly, quarterly, and historical controls are
shared with equipment detail, where the chart shows precomputed period deltas around zero. Weekly event
references persist from the start of the ISO week through the selected cutoff. If the package does not
cover a comparable prior quarter, the quarter view explicitly reports insufficient coverage.
The criticality cards use the same selected calendar period as the fleet map. Opening a point or a
criticality card carries that period into the equipment detail.

The fleet cutoff selector uses `catalog.iso_week_cutoffs` from the producer and shows one selection
per ISO week, labeled with the last included date (for example, `2026-W48 · datos hasta 25-11-2026 · parcial`).
That date is the latest package cutoff available within the week; the producer marks a cutoff as
partial when it falls before Sunday. The page summary also reports the selected ISO week and the
number of weeks available, while the evidence panel is labeled as history through that cutoff. The
variation map reuses Predictivo's red/yellow/green background palette for
worsening, stable, and improving areas around the no-change diagonal. Its stable band follows the
producer's published `variation_stability_tolerance`; the dashboard only renders that value. A
horizontal point-color legend remains visible below the plot, and the coverage count sits above the
data area so it does not hide units. On narrow screens, labels are limited to the selected period's
five highest-priority units and edge labels move inward; all comparable points remain selectable.

Equipment detail also shows the producer's cumulative weekly heuristic score. Each increment is the
mean observed score for one ISO week, so persistent daily snapshots are not counted seven times.
Weeks without observations appear as gaps and are never treated as zero; the total is an explanatory
heuristic, not a failure probability.

### 4. Start Dashboard

```bash
# Option 1: Run directly
python dashboard/app.py

# Option 2: Run as module (from project root)
python -m dashboard.app
```

The dashboard will be available at: **http://localhost:8080** (or `DASHBOARD_PORT` if set).

## Login Credentials

User accounts are defined in `config/users.py`. Each user has a role (`admin` or `client`) and a
list of accessible clients. Example accounts:

| Username     | Access     | Role   |
|--------------|------------|--------|
| admin        | All clients| admin  |
| cda_user     | CDA        | client |
| emin_user    | EMIN       | client |
| enex_user    | ENEX       | client |
| capstone_user| CAPSTONE   | client |

Passwords are SHA-256 hashed in `config/users.py`; see that file for the full user list and to add
or rotate credentials.

## Dashboard Sections

Navigation is organized into sections/subsections in the left sidebar (`dashboard/layout.py`).

### Resumen (Overview)
- **General** — unified per-unit status table combining Telemetría, Alertas, Data Freshness, and
  latest Tribología result for the selected client
- **Estado de Datos** — per-unit data freshness table (🟢/🟡/🔴) for Telemetría and Tribología,
  based on `data/auxiliar/{client}/Data_Date_Last_Update.csv`

### Monitoreo (Monitoring)
- **Alertas** — consolidated cross-technique alerts
  - *Vista General*: date-filtered distribution charts (by unit, month, trigger, sistema) and an
    interactive alerts table
  - *Vista Detallada*: per-alert inspection with AI diagnosis, telemetry evidence (sensor trends,
    GPS alert location, KPIs), oil evidence (radar chart), and maintenance evidence
- **Telemetría** — sensor-based health monitoring
  - *Vista de Flota*: fleet matrix of unit/system status
  - *Detalle de Unidad*: unit → system → signal drill-down with AI commentary
- **Aceite** — tribology (oil) analysis
  - *Visión de Flota*: machine status distribution and priority table
  - *Detalle de Reporte*: radar chart, time series vs. Stewart Limits thresholds, AI recommendations
  - *Cumplimiento Laboratorio*: transit-time and lab-time KPIs, weekly and per-unit delay charts

### Predictivo (Predictive)
Only visible to users whose client is in `predictive_allowed_clients` (currently CDA, CAPSTONE).
Subsections are auto-discovered per component (e.g. Motor, Transmisión) from CSVs under
`data/predictive/golden/{client}/`, each with a *Resumen* (fleet KPIs, priority cards, failure-mode
table) and *Evidencia* (per-unit oil/telemetry evidence and narrative insights) tab.

### Integración / Reportes / Administración
Reserved navigation entries currently showing "En Desarrollo" placeholder content.

## Color Scheme

- **Normal**: Green (#28a745)
- **Alerta**: Yellow/Amber (#ffc107)
- **Anormal**: Red (#dc3545)

## Data Layer Structure

Data follows a **Data Mesh** pattern: `data/{technique}/{layer}/{client}/{datafile}`

```
data/
├── oil/{silver,golden}/{client}/
├── telemetry/{silver,golden}/{client}/
├── mantentions/golden/{client}/
├── alerts/golden/{client}/
├── predictive/golden/{client}/
└── auxiliar/{client}/Data_Date_Last_Update.csv
```

Paths are resolved via helpers on `config/settings.py::Settings` (e.g. `get_machine_status_path`,
`get_stewart_limits_path`).

## Architecture

```
dashboard/
├── app.py                  # Main application entry point, route/health-check registration
├── auth.py                 # Login/authorization helpers (reads config/users.py)
├── layout.py                # App shell: login page, header/navbar, sidebar navigation
├── assets/                 # CSS/JS auto-loaded by Dash, logo.svg
├── logos/                  # Per-client logo images served at /logos/<file>
├── components/             # Reusable charts, tables, filters (per technique)
├── tabs/                   # Page layouts, one (or a family) per subsection — see below
└── callbacks/              # Interactive callbacks, one module per subsection/technique
```

Each monitoring technique typically has a matching trio: `tabs/tab_<name>*.py` (layout),
`callbacks/<name>_callbacks.py` (interactivity + data loading), and often a
`components/<name>_charts.py` / `_tables.py` (Plotly figures, DataTables). Some tab/callback
modules exist in the codebase but are currently commented out of navigation in `layout.py`
(shelved or in-progress features): Stewart Limits/Machines/Reports standalone tabs (now
superseded by the Aceite subsections), Mantenciones General, Health Index, Menace Control, Hot
Sheet, and the standalone Component Hours tab (its logic is still used internally by Predictivo).

## Production Deployment

```bash
docker-compose up -d
```

This builds from the root `Dockerfile` and mounts `./data` (read-only), `./logs`, `./dashboard`,
`./config`, and `./src` into the container. Environment variables are loaded from `.env`.

For a bare WSGI deployment:

```bash
gunicorn dashboard.app:server --bind 0.0.0.0:8050 --workers 4
```

### Path Prefix / Load Balancer

Set `DASH_PATH_PREFIX` (e.g. `/alerts-dashboard/`) to mount the app under a sub-path behind a
reverse proxy or ALB. A health-check endpoint is available at `<prefix>/health`
(e.g. `/alerts-dashboard/health`).

## Customization

### Change User Credentials

Edit `config/users.py` and update the `USERS` dictionary:

```python
USERS = {
    'your_user': {
        'password': hash_password('your_password'),
        'name': 'Display Name',
        'role': 'admin',       # or 'client'
        'clients': ['CDA', 'EMIN']
    }
}
```

### Modify Thresholds / Access Control

Most tunables live in `config/settings.py` (`Settings`), including Stewart Limits percentiles,
classification thresholds, and module access lists (`predictive_allowed_clients`,
`component_hours_allowed_clients`).

## Troubleshooting

### No Data Available
- Confirm `data/` exists and contains the expected `{technique}/{layer}/{client}/` structure
- If missing, verify `BUCKET_NAME`/`ACCESS_KEY`/`SECRET_KEY` are set in `.env` so the automatic S3
  sync in `dashboard/app.py` can run (only triggers when `data/` doesn't exist)

### Import Errors
- Verify all dependencies installed: `pip install -r requirements.txt`
- Check Python version: requires Python 3.11+

### Port Already in Use
- Change `DASHBOARD_PORT` in `.env`, or pass it via environment when running `dashboard/app.py`

## Support

For issues or questions, refer to:
- `documentation/general/dashboard_overview.md` — architecture and feature overview
- `documentation/general/DATA_FRESHNESS_TAB.md` / `DATA_FRESHNESS_IMPLEMENTATION.md`
