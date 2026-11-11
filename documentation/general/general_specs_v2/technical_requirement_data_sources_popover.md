## Technical Requirement: Replace the "Fuentes de Datos" Strip with a Popover and Audit Every Tab's Sources

Reference mockup: **Option B · Popover** — https://claude.ai/artifact/FBaUheQubykm5hqDXRANy7

### Context

Every dashboard page shows an always-open "Fuentes de Datos" strip at the top (for example, *Componentes Predictivos: Disponible · Hace 59 días* and *IA Predictiva: No disponible*). It uses vertical space on every page. The sources it lists have not been verified against what each tab actually reads, so they may be outdated or wrong.

This requirement does two things:

- Replace the strip with a popover (UI).
- Audit, document and correct the sources on every tab (data documentation).

### Required Changes

**A. UI: Popover (applies to every page that currently shows the strip)**

1. **Remove the current always-open strip.** It must be replaced, not kept alongside the new pattern.
2. **Add a trigger button in the page header**, aligned to the right of the page title block (title and subtitle), as in Option B.
   - Label: "Fuentes de Datos".
   - Next to the label, a summary badge in the form `n/total`, where `n` is the number of available sources and `total` is the number of sources on that page (for example, `1/2`).
3. **Add a popover** that opens below the trigger, anchored to it and right-aligned, with a caret pointing to the trigger. It must contain:
   - A title, "Fuentes de Datos".
   - A close button (icon only).
   - One entry per source of the page, each showing:
     - Source name.
     - Status chip: "Disponible" or "No Disponible", with an icon plus text, never color alone.
     - "Última actualización: <value>", reusing the current "Hace N días" logic. If the source has no value, show "—".
4. **Keep the existing availability logic and "Hace N días" calculation.** Only the presentation changes.

**B. Data documentation: audit, document, edit (applies to every tab of the dashboard)**

These three steps must happen in this order.

5. **Audit.** The engineering team reviews every page and tab (including sub-tabs such as Resumen/Evidencia and Corto Plazo/Largo Plazo) and determines the real data sources it uses. For each tab, record:
   - The sources currently displayed in the strip.
   - The sources actually used.
   - The underlying origin of each (table, file, API or model output).
   - The module or callback that reads it.
   - The UI sections that depend on it.
   - How its availability status is determined.
   - How its "last update" value is calculated and which date it reflects.
   - Any difference between the displayed list and the real list.
6. **Document.** Create `data_sources_documentation_dashboard.md` in the repository, in the location the team uses for dashboard documentation. It must have one section per page/tab with the audit findings above, plus a list of discrepancies found. This file is the reference for step 7.
7. **Edit the code.** Update the sources shown in the popover on each page/tab so they match the documentation exactly. Sources that are not used must be removed, and used sources that were missing must be added.

### Functional Rules

- The same trigger and popover pattern must be used on every page. Only the list of sources changes per page.
- The popover opens on trigger click. It closes via the close button, the Escape key, or a click outside it.
- The trigger is a real `<button>` with `aria-haspopup="dialog"` and an `aria-expanded` that reflects its state. The close button has an `aria-label`. When the popover closes, focus returns to the trigger.
- The summary badge is amber when at least one source is not available, and green when all sources are available.
- The popover must stay within the viewport on narrow screens.
- Text follows `ui_notes_improved.md` (§1.3, §6, §7): Title Case and correct Spanish accents, and status never conveyed by color alone.
- The availability logic, source data and the rest of the page content must not change.
- Code edits (step 7) start only after the documentation (step 6) exists. Any discrepancy between the audit and the old strip is corrected in code, not left as is.
- The audit must clarify why "Componentes Predictivos" shows "Hace 59 días" while the model run date on the same page is 06 Nov 2026, and document whether they are different dates.

### Acceptance Criteria

- [ ] The old always-open strip no longer appears on any page.
- [ ] Every page that had the strip now shows the "Fuentes de Datos" button, with the `n/total` badge, next to the page title.
- [ ] Clicking the button opens the popover, and the close button, Escape and an outside click all close it.
- [ ] Each source in the popover shows its name, a status chip with icon and text, and "Última actualización".
- [ ] The button and the popover can be operated with the keyboard, and focus returns to the trigger on close.
- [ ] `data_sources_documentation_dashboard.md` exists and covers every page and tab.
- [ ] The sources listed in each popover match the documentation exactly.
- [ ] The document lists every discrepancy between the old strip and the audit result.
- [ ] Availability statuses and "Hace N días" values are the same as before the change for sources that were already shown.
- [ ] No other functionality changes outside the affected header area.
