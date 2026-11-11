# Technical Requirement — Sidebar Menu Order: Reportes Before Conexión ERP

| | |
|---|---|
| **Area** | Frontend (left navigation menu, "Navegación") |
| **Related documents** | `03_admin_mailing_screen.md` (adds the "Mailing" entry inside Administración; independent of this change) |
| **Where the work lives** | Same repository as `app.py`. Code, development and deployment stay in this repo. |

---

## Context

The dashboard (Python + Plotly / Dash on Flask, entry point `app.py`) has a left navigation menu titled **Navegación**. Its sections currently appear in this order:

1. Resumen
2. Monitoreo
3. Predictivo
4. Agentes
5. Conexión ERP
6. Reportes
7. Administración

The product decision is that **Reportes** must appear before **Conexión ERP**. This is only a change of position; the sections themselves do not change.

---

## Required Changes

1. Change the order of the left menu sections to:

   1. Resumen
   2. Monitoreo
   3. Predictivo
   4. Agentes
   5. **Reportes**
   6. **Conexión ERP**
   7. Administración

2. Keep everything else about each menu item unchanged: label, icon, route, expand/collapse behavior, sub-items, permissions and visibility rules.
3. Apply the same order everywhere the menu is rendered (expanded, collapsed and mobile/narrow layouts, if they exist).

---

## Functional Rules

- If any code depends on the position of a menu item (for example, indexes, default-open sections or active-state logic), it must be updated so that behavior remains identical after the reorder.
- Existing functionality must remain unchanged outside the menu order.

---

## Acceptance Criteria

- [ ] The menu shows Reportes immediately above Conexión ERP, and Conexión ERP immediately above Administración.
- [ ] The other items keep their positions: Resumen, Monitoreo, Predictivo and Agentes first, Administración last.
- [ ] Each item still opens the same page and shows the same icon and expand/collapse behavior as before.
- [ ] Visibility and permissions of each item are unchanged for every user role.
- [ ] The active-item highlight still works on every section.
