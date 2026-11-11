# Technical Requirement — Alert Summary Email: Content, Data Rules and HTML Template

| | |
|---|---|
| **Area** | Backend (report builder + HTML template) |
| **Related documents** | `01_mailing_service_backend.md` (service, schedules, recipients, delivery), `03_admin_mailing_screen.md` (preview in the admin screen) |
| **Where the work lives** | Same repository as `app.py`. Code, development and deployment stay in this repo. |
| **Reference** | Mockup "Correo — Resumen Semanal (Capstone)" (attached with this ticket) |

---

## Context

**Platform.** Dashboard in Python + Plotly (Dash) on a Flask backend (`app.py`), running on an EC2 instance. Emails are sent through an existing AWS Lambda that accepts HTML (see `01_mailing_service_backend.md`).

**Current behavior.** Alerts are shown only inside the dashboard, in the Alertas section ("Análisis semanal de alertas": distribution by unit, evolution over time, distribution by system, and the "Listado de alertas" table with the columns Fecha, Unidad, Fuente, Sistema, Componente, Señal / variable, Diagnóstico). Alert sources are Telemetría, Tribología and Multitécnica. Systems are Dirección, Frenos, Motor and Tren de Fuerza.

**What this ticket delivers.** The report builder and HTML template that turn the alerts of a client and a period into the email `subject` + `html` used by the mailing service. The same email is sent to Emin (daily) and Capstone (weekly) and is also used for the preview in the admin screen.

**Key principle.** The numbers in the email must match what the Alertas page shows for the same client and date range. Reuse the existing alert-loading and aggregation logic (see `dashboard/callbacks/alerts_callbacks.py`) instead of writing new queries. If that logic is coupled to Dash callbacks, extract it to a shared module without changing the Alertas page behavior.

---

## Required Changes

### 1. Report builder

Create a builder that receives `client`, `period_start`, `period_end` and `send_date`, and returns:

- `subject`: `[CODDI] Monitoreo de Alertas DD/MM/YYYY` (send date).
- `html`: the full email body.
- `meta`: total alerts, affected units and report variant (`daily` | `weekly`), for logging.

The data used is the client's alerts whose date falls inside the period (`America/Santiago` dates, both ends inclusive).

### 2. Email structure (in this order)

1. Top bar and header.
2. Headline and summary sentence.
3. Three KPI tiles.
4. **Alertas por Unidad**.
5. **Alertas por Sistema**.
6. **Alertas Destacadas del Período**.
7. Button **Ver Alertas en el Dashboard**.
8. Footer.

### 3. Header

- Eyebrow: `CODDI · MONITOREO DE ALERTAS`.
- Title: `Resumen Semanal de Alertas` (weekly) or `Resumen Diario de Alertas` (daily).
- Subtitle: `Flota {Client} · Período {DD/MM/YYYY} – {DD/MM/YYYY}`. For a one-day period: `Período {DD/MM/YYYY}`.
- A solid blue top bar (6 px, `#1d4ed8`) like the Boletín Predictivo email. Do not use left-border accent cards (deprecated in `ui_notes_improved.md` §2).

### 4. Headline and summary sentence

- Headline: `{N} alertas en {M} unidades`.
- Summary sentence: `{X} de {M} unidades concentran el 80% de las alertas. Analice las unidades con más alertas: {U1}, {U2} y {U3}.`
  - `X` = smallest number of units (ordered by alert count, descending) whose accumulated alerts reach at least 80% of the total.
  - `{U1}, {U2} y {U3}` = the 3 units with most alerts. Ties at the cut-off are broken by most recent alert date, then unit ID.
  - The words "Priorice" and "mantenimiento" must **not** appear. The call to action is "Analice las unidades".
- Singular/plural must be correct ("1 alerta en 1 unidad"). If only one unit is affected, omit the 80% part and write `Analice la unidad {U1}.`

### 5. KPI tiles

| Tile | Value | Sub-caption | Color tint |
|---|---|---|---|
| Total de Alertas | Total alerts in the period | `últimos 7 días` (weekly) / `último día` (daily) | Danger tint (`#fee2e2`, value `#b91c1c`) |
| Unidades Afectadas | Units with at least 1 alert | `con al menos 1 alerta` | Info tint (`#dbeafe`, value `#1d4ed8`) |
| Sistema Principal | Name of the system with most alerts | `{n} alertas · {p}%` | Neutral (`#f1f5f9`, value `#1e3a5f`) |

If two systems tie for first place, show the first in alphabetical order.

### 6. Alertas por Unidad (grouping rule)

Units with the same number of alerts are **compressed into a single row**. This applies to any count (1 or more), so the lower part of the chart has no repeated numbers.

Algorithm:

1. Count alerts per unit.
2. Group units by identical alert count; sort groups by count, descending.
3. One row per group:
   - **Label:** unit ID if the group has one unit. If the group has 2 or 3 units, list their IDs sorted naturally (`T_4, T_31`). If the group has more than 3 units, show `{N} unidades`.
   - **Alertas column:** the number if the group has one unit; `{count} c/u` ("cada una") if it has several.
   - **Bar:** width = `count / highest per-unit count` (per-unit count, not group total).
   - **% Acumulado:** accumulated alerts up to and including that row, divided by total alerts, rounded half-up to an integer. The last row is always `100%`.
4. Show at most **15 rows**. If there are more than 15 groups, the remaining groups are merged into one final gray row `Otras ({N})`, where `N` is the number of units merged. Its Alertas column shows the total alerts of the merged units, and its bar width is capped at 100%.
5. Below the chart, add the note: `c/u = cada una. Las unidades con la misma cantidad de alertas se agrupan en una sola fila.` Show it only if at least one row is compressed.

**Worked example** (62 alerts, 19 units):

| Input (alerts per unit) | Row label | Alertas | % Acumulado |
|---|---|---|---|
| T_18: 18 | T_18 | 18 | 29% |
| T_15: 11 | T_15 | 11 | 47% |
| T_9: 7 | T_9 | 7 | 58% |
| T_22: 4 | T_22 | 4 | 65% |
| T_4: 3, T_31: 3 | T_4, T_31 | 3 c/u | 74% |
| T_12: 2, T_27: 2, T_7: 2 | T_12, T_27, T_7 | 2 c/u | 84% |
| 10 units with 1 alert | 10 unidades | 1 c/u | 100% |

### 7. Alertas por Sistema

- One row per system with alerts, ordered by alert count descending. Columns: system name, bar, Alertas, `% del Total`.
- Bar width = `count / highest system count`.
- Percentages are rounded half-up; they must add up to 100% (adjust the largest row if rounding breaks this).
- Bar colors (same family as the dashboard charts): Motor `#2f5675`, Tren de Fuerza `#3f8a85`, Frenos `#c9783f`, Dirección `#7a68a0`. Any other system uses `#94a3b8`.

### 8. Alertas Destacadas del Período

Show **at most 5 alerts**, selected and ordered by these criteria, in this order of priority:

1. **Source:** alerts from **Multitécnica** come first.
2. **Unit activity:** then alerts from units with more alerts in the period (higher count first).
3. **Recency:** remaining ties by most recent date first.

Table columns: `Fecha` (`DD/MM`), `Unidad`, `Fuente`, `Sistema / Componente`, `Diagnóstico`.

- `Fuente` is a colored chip **with the source name as text**: Telemetría (`#dbeafe` / `#1e40af`), Tribología (`#fef3c7` / `#92400e`), Multitécnica (`#ede9fe` / `#5b21b6`).
- `Diagnóstico` uses the alert's diagnosis text, truncated at a word boundary with `…` to fit about two lines in the table (suggested maximum 120 characters).
- If a system or component is missing, show `—`.
- Caption below the table: `Mostrando {k} de {N} alertas del período. Se priorizan las alertas multitécnicas y las unidades con más alertas.`

### 9. Button and footer

- Button text: `Ver Alertas en el Dashboard`. It links to the Alertas section of the dashboard. The URL comes from configuration (for example `DASHBOARD_ALERTS_URL`), not hardcoded.
- Footer: `Este resumen se genera automáticamente {cada miércoles | todos los días} a las 08:00 (hora de Chile) y cubre las alertas registradas entre el {start} y el {end}.` followed by `Coddi · coddi.ai`. The frequency text comes from the client's schedule configuration. For a one-day period, use `el {date}`.

### 10. HTML and style constraints

- **Email-safe HTML only:** table-based layout, inline CSS, no flexbox, no CSS grid, no JavaScript, no SVG, no external CSS, no web fonts. Font stack: `Arial, Helvetica, sans-serif`.
- Maximum content width 640 px; it must stay readable on mobile widths.
- Bars are drawn with table cells (a track cell and a fill cell with percentage width and background color), not with CSS shapes that email clients ignore.
- Text contrast of at least 4.5:1. Every color-coded value also has a text label (the chip says "Telemetría", not just a color), per `ui_notes_improved.md` §1.3.
- Spanish accents and Title Case in headings (`Alertas por Unidad`, `Alertas Destacadas del Período`).
- Page colors: text `#0f172a`, secondary text `#475569`, table header `#1e293b` with white text, bar track `#e2e8f0`, primary button `#1d4ed8` with white text.
- The HTML is produced from a template file in the repo (Jinja2 is already available through Flask). Escape all alert text.
- The email must render correctly in at least Gmail (web and mobile) and Outlook.

### 11. Tests

Automated tests for:

- Unit grouping: the worked example above, groups of 1, 2, 3 and more than 3 units, more than 15 groups (`Otras`), and a single-unit case.
- Cumulative percentages rounding and last row = 100%.
- Ranking of Alertas Destacadas (Multitécnica first, then unit activity, then recency, max 5).
- The 80% sentence with and without ties, and the singular/plural cases.
- Numbers equal to those of the Alertas page for the same client and range.

---

## Functional Rules

- Dates are shown as `DD/MM/YYYY` (headers) and `DD/MM` (table), always in `America/Santiago`.
- Daily and weekly emails share the same template; only the title, period text, KPI captions and footer text change.
- Alerts of other clients never appear in the email.
- Existing Alertas page behavior must remain unchanged.

---

## Acceptance Criteria

- [ ] The subject is `[CODDI] Monitoreo de Alertas DD/MM/YYYY` with the send date.
- [ ] Emin gets the "Resumen Diario" variant and Capstone gets the "Resumen Semanal" variant.
- [ ] Totals, affected units, per-unit and per-system counts equal those shown in the Alertas page for the same client and range.
- [ ] Units with the same alert count appear in a single row (worked example reproduces exactly).
- [ ] No more than 15 unit rows plus one optional `Otras ({N})` row.
- [ ] `% Acumulado` ends at 100% and uses integer rounding.
- [ ] Alertas Destacadas shows at most 5 alerts, with Multitécnica alerts first, then units with more alerts, then most recent.
- [ ] The summary sentence says "Analice las unidades…" and never mentions prioritizing maintenance.
- [ ] The email contains no flex, grid, SVG, JavaScript or external assets, and renders correctly in Gmail and Outlook.
- [ ] Every colored chip or tile has a readable text label.
- [ ] The preview returned for the admin screen is identical to the HTML sent.

---

## Open Items

- **Period with no alerts (proposed default, needs product confirmation).** Send the email with the header, `0 alertas` and the message `Sin alertas registradas en el período.`, with no charts or table. The alternative is to skip the send. Implement the proposed default unless told otherwise.
- **Dashboard link.** Confirm the URL/route of the Alertas section, and whether the link should preselect the client (the dashboard forces a client selection).

## Optional Considerations (not in scope)

- Hidden preheader text for email previews.
- Showing the total per group (for example `6 en total`) in compressed rows.
