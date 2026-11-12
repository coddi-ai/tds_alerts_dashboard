# Technical Requirement — Administración → Mailing: Manual Alert Summary Send Screen

| | |
|---|---|
| **Area** | Frontend (Dash page in the existing dashboard) |
| **Depends on** | `01_mailing_service_backend.md` (operations used by this screen) and `02_alert_summary_email_template.md` (email shown in the preview) |
| **Related documents** | `04_sidebar_menu_reorder.md` (menu order) |
| **Where the work lives** | Same repository as `app.py`. Code, development and deployment stay in this repo. |
| **Reference** | Mockup "Administración → Mailing (propuesta v2)" (attached with this ticket). The v1 mockup is obsolete and must not be implemented. |
| **UI guidelines** | `ui_notes.md` and `ui_notes_improved.md` apply (typography, icons, card style, accessibility, copy conventions). |

---

## Context

**Platform.** Dashboard in Python + Plotly (Dash) on a Flask backend (`app.py`), deployed on an EC2 instance. The left navigation menu has these sections: Resumen, Monitoreo, Predictivo, Agentes, Conexión ERP, Reportes, Administración.

**Current behavior.** There is no mailing feature in the dashboard. Administración has no option to send emails.

**Problem.** The backend is getting a `mailing` service that sends alert summary emails automatically (Emin daily, Capstone weekly). Admins also need to trigger the same email manually and choose who receives it.

**Expected behavior.** A new **Mailing** page under **Administración**, available only to admin users. The page works on the client already selected in the dashboard (the dashboard forces every user, admin included, to select a client), so **it has no client selector of its own**. It has one control for deciding who receives the email: a single grouped recipients list. There is no separate "send mode" control.

---

## Required Changes

### 1. Navigation entry and access

- Add a **Mailing** item inside the **Administración** section of the left menu (envelope icon). Highlight it as the active item when the page is open.
- Add the route consistent with the existing Administración routes (suggested: `/administracion/mailing`; confirm in the codebase).
- Only admin users can see the entry and open the page. A non-admin user who types the URL must be denied or redirected, following the behavior the platform already uses for other admin-only pages.
- Every backend operation called from this page must also check the admin role on the server side (see `01_mailing_service_backend.md`).

### 2. Page header

- Title: `Mailing` with an envelope icon, in the blue page-title style used by other sections.
- Subtitle: `Envío manual de resúmenes por correo. Solo disponible para usuarios administradores.`
- Two read-only chips on the right side of the header:
  - `Cliente: {Client}`, taken from the dashboard's current client selection.
  - `Entorno: Producción` or `Entorno: Desarrollo`, taken from the app's environment configuration. Users cannot change it.

### 3. Report card

A single card titled by the client's report type:

- Title: `Resumen Semanal de Alertas` (Capstone) or `Resumen Diario de Alertas` (Emin).
- Subtitle: `{Client} · se envía automáticamente los miércoles a las 08:00 (hora de Chile).` or `… todos los días a las 08:00 (hora de Chile).`, built from the schedule configuration.
- Two read-only details:
  - `Asunto`: the subject that will be sent, e.g. `[CODDI] Monitoreo de Alertas 10/11/2026` (send date = today).
  - `Período del Resumen`: e.g. `03/11/2026 – 09/11/2026 (últimos 7 días)`; for daily: `09/11/2026 (último día)`.
- Values come from `get_mailing_context(client)`; the page must not recompute them.

### 4. Recipients list (the only recipient control)

- Heading `Destinatarios` and a counter `{n} de {total} seleccionados`.
- One list with three groups, each with a header showing the group name and `{selected} de {total}`:
  1. `Cliente · {Client}`
  2. `Coddi · Técnico`
  3. `Coddi · Gerencia`
- Each row: checkbox + name (bold) + email. Clicking the name or email also toggles the checkbox.
- Row tags (text chips):
  - `Sin envío automático` on client contacts with `send_email = False`.
  - `Siempre incluido` on the Coddi Técnico contact.
  - `Solo producción` on Coddi Gerencia contacts.
- Initial state:
  - Client contacts: checked when `send_email = True`, unchecked otherwise.
  - Coddi Técnico: checked and **disabled** (cannot be removed).
  - Coddi Gerencia: checked in production.
  - Outside production, Cliente and Gerencia rows are **unchecked and disabled**, and show the reason from `disabled_reason`.
- Helper text under the list: `Vienen marcados los contactos con envío automático activo. Para una prueba, desmarque al cliente y a gerencia: el equipo técnico siempre recibe el correo. Fuera de producción, cliente y gerencia aparecen deshabilitados.`
- Selection is local to the page and applies only to the next send. It does not change the hardcoded `send_email` values.

### 5. Action bar

- Left: `Se enviará a {n} destinatarios.` (singular `1 destinatario`), updated live.
- Right, two buttons:
  - `Ver Vista Previa` (secondary): opens the email as it would be sent, using `build_preview(client)`, inside a modal. The email HTML must be rendered in a sandboxed `iframe` so that it cannot affect the dashboard. The modal has a close button and closes with Esc.
  - `Enviar Ahora` (primary): calls `send_manual(client, selected_emails, requested_by)`.

### 6. Send states and feedback

- While sending: both buttons and all checkboxes are disabled, and the primary button shows `Enviando…`. This also prevents double clicks.
- Success: an inline message `Resumen enviado a {n} destinatarios.` (announced to screen readers).
- Partial failure: `Se envió a {ok} de {n} destinatarios.` plus the list of emails that failed.
- Total failure: `No se pudo enviar el resumen. Intente nuevamente.` No technical details are shown.
- The selection is kept after a send, so the admin can retry.

### 7. Behavior when the client changes

- When the dashboard's selected client changes, the page reloads the chips, title, subtitle, subject, period and recipients for the new client.
- If the selected client has no mailing configuration, hide the card and show the message `Este cliente no tiene envío de resúmenes configurado.`

### 8. Style and accessibility

- Follow `ui_notes.md` and `ui_notes_improved.md`: Title Case headings, correct Spanish accents, spelled-out labels, tinted chips instead of left-border accents, white card with the platform's standard shadow and radius.
- Every clickable element is a real `<button>` or `<a href>`; every checkbox has a `<label for>`; icon-only controls have an `aria-label`.
- Group headers use `role="group"` with `aria-labelledby`.
- Color is never the only signal: every tag and state has text.
- Touch targets of at least 44 px; text contrast of at least 4.5:1.
- The layout must adapt to narrow widths (the card stacks; the action bar wraps).
- Use the same chip colors as the mockup: Cliente `#dbeafe` / `#1e40af`, Técnico `#ccfbf1` / `#115e59`, Solo producción `#fef3c7` / `#92400e`, Sin envío automático `#f1f5f9` / `#334155`; primary button `#1d4ed8`.

---

## Functional Rules

- The page never lets the admin pick a client; the client always comes from the dashboard's current selection.
- There is a single recipient control (the grouped list). No "Modo de Envío" / "Prueba" / "Producción" selector exists.
- A "test" send is done by unchecking the client and management groups; Coddi Técnico always receives the email.
- The UI does not decide what is allowed. The backend validates the selection; if it rejects it, the page shows the failure state.
- The manual send does not change the automatic schedule.
- Existing sections, routes and permissions remain unchanged outside this page and the new menu entry.

---

## Acceptance Criteria

- [ ] Admin users see **Mailing** inside Administración; non-admin users do not see it and cannot open its URL.
- [ ] The page shows no client selector and uses the dashboard's selected client.
- [ ] Changing the dashboard client updates the title, subject, period and recipients.
- [ ] A client without mailing configuration shows `Este cliente no tiene envío de resúmenes configurado.`
- [ ] The title reads `Resumen Semanal de Alertas` for Capstone and `Resumen Diario de Alertas` for Emin.
- [ ] Subject and period shown match what the backend sends.
- [ ] Recipients appear in three groups with the tags described above.
- [ ] In production, client contacts with `send_email = True` and Gerencia are pre-checked; contacts with `send_email = False` are unchecked.
- [ ] Coddi Técnico is always checked and cannot be unchecked.
- [ ] Outside production, Cliente and Gerencia rows are disabled and unchecked.
- [ ] The counter and the text `Se enviará a {n} destinatarios.` update immediately when the selection changes.
- [ ] `Ver Vista Previa` shows the same email that `Enviar Ahora` would send, inside a sandboxed iframe, and sends nothing.
- [ ] `Enviar Ahora` sends only to the selected recipients and shows the success, partial-failure or failure message.
- [ ] While sending, buttons and checkboxes are disabled, so a double click sends only once.
- [ ] The page can be operated with the keyboard only and passes the accessibility rules above.
- [ ] No other section of the dashboard changes behavior.

---

## Optional Considerations (not in scope)

- A confirmation dialog before `Enviar Ahora` (for example `¿Enviar a {n} destinatarios?`), since a manual send reaches real clients.
- A "last sent" indicator or send history.
