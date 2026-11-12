# Technical Requirement — Mailing Service for Alert Summary Emails (Backend)

| | |
|---|---|
| **Area** | Backend (Python / Flask) |
| **Related documents** | `02_alert_summary_email_template.md` (email content and HTML), `03_admin_mailing_screen.md` (admin UI), `04_sidebar_menu_reorder.md` (menu order) |
| **Where the work lives** | Same repository as `app.py`. Code, development and deployment all stay in this repo. No new infrastructure. |

---

## Context

**Platform.** The dashboard is built with Python + Plotly (Dash) on top of a Flask backend. `app.py` is the entry point that handles the whole platform. It is deployed on an EC2 instance that runs 24/7.

**Email delivery.** An AWS Lambda already sends emails. It is invoked with an HTTP request to the URL stored in the `.env` variable `LAMBDA_URL`, and it accepts HTML bodies. The existing "Boletín Predictivo" email is the visual reference for new emails.

**Current behavior.** The platform has no mailing module. Alerts are visible only inside the dashboard (Alertas section), so clients and the Coddi team receive nothing unless they log in.

**What this ticket delivers.** A new backend service called `mailing` that:

1. Sends the **alerts summary** automatically on a schedule:
   - **Emin:** daily summary, every day at 08:00.
   - **Capstone:** weekly summary, every Wednesday at 08:00.
   - All times are Chilean time (`America/Santiago`).
2. Exposes operations so an admin can preview and send the same email manually from the dashboard (screen defined in `03_admin_mailing_screen.md`).

This is the first use of the module. Other reports will be added later, so delivery must not be tied to the alerts report.

---

## Required Changes

### 1. Create the `mailing` service

- Create a `mailing` package in the repository, next to `app.py` (exact path per repo conventions).
- Keep three responsibilities separated:
  - **Recipients:** resolves who can receive an email, per client and environment.
  - **Report builder:** produces `subject` + `html` for a client and date. Implemented in `02_alert_summary_email_template.md`.
  - **Delivery:** a generic function that receives `subject`, `html` and recipients and calls the Lambda. It must contain no alerts-specific logic.
- Add any new dependency to the repo's dependency file.

### 2. Recipient registry (hardcoded)

Define the registry in code (no database). Client keys **must match the client identifiers the dashboard already uses** (confirm exact values in the codebase; expected `emin` and `capstone`).

```python
MAILING_RECIPIENTS = {
    "emin": [
        {"name": "[NAME]", "email": "[EMAIL]", "send_email": True},
    ],
    "capstone": [
        {"name": "[NAME]", "email": "[EMAIL]", "send_email": True},
    ],
}

CODDI_RECIPIENTS = {
    "technical": [
        {"name": "Equipo Técnico", "email": "tds@coddi.ai", "send_email": True},
    ],
    "management": [
        {"name": "Eduardo", "email": "eduardo@coddi.ai", "send_email": True},
        {"name": "Pedro",   "email": "pedro@coddi.ai",   "send_email": True},
    ],
}
```

- `send_email` controls whether the contact receives the **scheduled** email and whether the contact is **pre-selected** in the manual screen.
- Real client contacts are an input (see Open Items). Do not commit placeholder values as if they were real.

### 3. Schedules

Define both schedules in one configuration structure:

```python
MAILING_TIMEZONE = "America/Santiago"
MAILING_SCHEDULES = {
    "emin":     {"frequency": "daily",  "time": "08:00"},
    "capstone": {"frequency": "weekly", "weekday": "wednesday", "time": "08:00"},
}
```

- The scheduled run must fire at 08:00 **Chilean local time**, including when Chile changes between summer and winter time. A UTC-based fixed hour is not acceptable.
- The scheduler can be an in-process scheduler or an OS-level job (cron / systemd timer) on the EC2 instance. If it is OS-level, its definition must be versioned in this repo and included in the deployment steps.
- **Exactly once per scheduled run.** If the app runs with several workers/processes, or restarts around 08:00, the same client must not get the same scheduled email twice. Use a persisted marker keyed by `(client, scheduled date)` that all processes share and that survives restarts.
- The scheduler must be switchable by configuration (suggested variable: `MAILING_SCHEDULER_ENABLED`) so that development environments do not run it unintentionally.

### 4. Report period and subject

| Client | Frequency | Period covered |
|---|---|---|
| `emin` | Daily | Previous calendar day |
| `capstone` | Weekly | The 7 calendar days ending the day before the send date (inclusive) |

- Dates and days are evaluated in `America/Santiago`.
- Manual sends use the same rule, relative to the day the admin clicks send.
- **Subject:** `[CODDI] Monitoreo de Alertas DD/MM/YYYY`, where the date is the **send date**. Example: `[CODDI] Monitoreo de Alertas 11/11/2026`.

**Example (Capstone).** Scheduled on Wednesday 11/11/2026 08:00 → subject `[CODDI] Monitoreo de Alertas 11/11/2026`, period 04/11/2026 – 10/11/2026.

### 5. Delivery through the Lambda

- Read the URL from `LAMBDA_URL` (`.env`). Never hardcode it, log it, or commit it.
- Build the request according to the Lambda's existing contract (see Open Items).
- A send is successful only when the Lambda confirms success. Any timeout, network error or non-success response is a failure.
- **Scheduled sends:** on failure, retry up to 3 times with increasing wait time (default, adjustable), then log an error.
- **Manual sends:** no automatic retry. Return the failure to the caller.

### 6. Operations for the admin screen

The service must expose these operations to the Dash/Flask layer (names are indicative):

| Operation | Behavior |
|---|---|
| `get_mailing_context(client)` | Returns: report type (daily/weekly), schedule description, subject, period, environment, and the recipient list grouped as Cliente / Coddi Técnico / Coddi Gerencia. Each recipient includes `name`, `email`, `group`, `selected_by_default`, `locked`, `disabled` and `disabled_reason`. |
| `build_preview(client)` | Returns `subject` and `html` exactly as a real send would. Sends nothing. |
| `send_manual(client, selected_emails, requested_by)` | Validates the selection, builds the email, sends it, and returns a result per recipient (`sent` / `failed`). |

- If a client has no entry in `MAILING_SCHEDULES`, `get_mailing_context` must say that mailing is not configured for it.
- The scheduled run and `send_manual` must use the same report builder and delivery function.

### 7. Authorization, logging and errors

- `send_manual`, `build_preview` and `get_mailing_context` are **admin-only**. Enforce this on the server side with the same admin check the platform already uses; hiding the menu entry is not enough.
- Log every send attempt (using the app's existing logging): timestamp, client, trigger (`scheduled` / `manual`), requesting admin user (manual only), recipient emails, subject, result per recipient. Do **not** log the HTML body or the Lambda URL.
- Errors returned to the UI must be readable and must not expose internals (URLs, stack traces).

### 8. Configuration and deployment

- New configuration lives in `.env` / the existing config mechanism. Required: `LAMBDA_URL`. The environment flag (see rule 1 below) uses the app's existing one, or `APP_ENV` (`production` | `development`) if none exists.
- Deployment uses the current EC2 process. Document any new step (scheduler job, new variables) in the repo's deployment notes.

### 9. Tests

Automated tests, with the Lambda mocked, for:

- Recipient resolution per client and environment (matrix below).
- Period calculation and subject date, including a date range that crosses a Chile daylight-saving change.
- Schedule evaluation (daily vs. weekly Wednesday, 08:00 `America/Santiago`).
- Exactly-once behavior for a scheduled run triggered twice.
- Manual send validation (rejects emails outside the allowed set; always includes Coddi Técnico).
- Admin-only authorization.

---

## Functional Rules

1. **Environments.** "Production" is determined by the app's environment flag. Every other environment is "non-production".
2. **"Mock test" is not a separate mode.** It is a manual send where only Coddi Técnico is selected. There is no separate code path.
3. **Recipient matrix:**

| Group | Production | Non-production |
|---|---|---|
| Cliente (from `MAILING_RECIPIENTS[client]`) | Selectable. Scheduled sends include only `send_email = True`. Pre-selected when `send_email = True`. | Never sent. Not selectable. |
| Coddi · Técnico (`tds@coddi.ai`) | Always included (scheduled and manual). Cannot be removed. | Always included. Cannot be removed. |
| Coddi · Gerencia (`eduardo@coddi.ai`, `pedro@coddi.ai`) | Included in scheduled sends. Selectable and pre-selected in manual sends. | Never sent. Not selectable. |

4. **Server-side validation.** `send_manual` must ignore the UI as a source of truth. Reject any email that is not in the allowed set for that client and environment, and add Coddi Técnico automatically if missing.
5. A manual send does **not** change, skip or reschedule the automatic schedule.
6. Concurrent double triggers (for example a double click) for the same client must not produce two manual emails within the same few seconds. A short per-client lock is enough.
7. If a period has no alerts, the behavior is defined in `02_alert_summary_email_template.md` (Open Items). The service only sends what the builder returns.
8. Existing functionality of the platform must remain unchanged. If alerts-loading code must be shared with the email builder, extract it without altering the Alertas page behavior.

---

## Acceptance Criteria

- [ ] A `mailing` service exists in the same repo as `app.py` and needs no new infrastructure.
- [ ] Emin's summary is sent every day at 08:00 Chilean time; Capstone's every Wednesday at 08:00 Chilean time.
- [ ] The schedule keeps firing at 08:00 Chilean time after a daylight-saving change.
- [ ] Restarting the app or running multiple workers never produces a duplicate scheduled email.
- [ ] The subject is exactly `[CODDI] Monitoreo de Alertas DD/MM/YYYY` with the send date.
- [ ] Daily period = previous day; weekly period = 7 days ending the day before the send date.
- [ ] In production, scheduled emails go to the client contacts with `send_email = True`, to `tds@coddi.ai`, and to `eduardo@coddi.ai` and `pedro@coddi.ai`.
- [ ] In non-production, only `tds@coddi.ai` can receive emails.
- [ ] `tds@coddi.ai` is included in every send and cannot be removed.
- [ ] Manual send rejects recipients outside the allowed set, even if the request is crafted manually.
- [ ] Non-admin users cannot call preview or manual send.
- [ ] `LAMBDA_URL` is read from `.env` and appears nowhere in code, logs or UI.
- [ ] Every send attempt is logged with the fields listed above and without the HTML body.
- [ ] A Lambda failure on a scheduled send is retried and then logged; on a manual send it is returned to the UI.
- [ ] Automated tests listed in item 9 pass.

---

## Open Items (inputs required before or during development)

1. **Real client contacts** (`name`, `email`, `send_email`) for Emin and Capstone.
2. **Lambda request contract:** required fields (recipients, subject, HTML, sender, etc.) and response format. Reuse the helper that already sends other emails if one exists in the repo.
3. **Recipient privacy (decision needed).** Recommended: one email per recipient, so client contacts never see each other's addresses or Coddi's. If the Lambda only accepts a single message with multiple recipients, use hidden recipients (BCC) instead.
4. **Exact client identifiers** used by the dashboard's client selector.

## Optional Considerations (not in scope)

- Catch-up send if the server was down at 08:00 and comes back the same day.
- Check the Lambda URL's authentication type. If it is publicly invokable, treat the URL as a secret and consider adding authentication.
- Add an environment prefix (for example `[DEV]`) to the subject in non-production to tell test emails apart. This would change the required subject format, so it needs product approval.
