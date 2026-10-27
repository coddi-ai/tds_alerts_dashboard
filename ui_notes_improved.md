# UI/UX Guidelines — Improvements & Extensions (v1.0)

**Companion to:** `ui_notes.md` v2.1.1 (July 2026)
**Scope:** fills a gap the original guide doesn't cover, and fixes a few cross-cutting
issues found while redesigning Predictivo → Evidencia (unit CA-83, Oct 2026).
**Status:** proposed — thresholds and a couple of audit items need team sign-off
before this is final (see §10).

---

## 0. Why this document exists

`ui_notes.md` defines a semantic palette and tinted backgrounds for **four fixed,
named KPI cards** (Total Alerts = danger tint, Affected Units = info tint,
Telemetry Coverage = success tint, Oil Analysis = warning tint). That's a good
pattern — but it only covers cards whose color is tied to a *fixed identity*.

It has **no rule for value-driven metrics**: a number whose color should depend
on what the number *is* (a risk score, a ranking, a status) rather than on which
card it's in. That gap is what produced the inconsistent coloring on the
Predictivo → Evidencia page — KPI tiles had arbitrary left-border colors (orange,
orange, green, purple, gray) with no defined meaning behind any of them, because
there was nothing in the written guide to follow.

This document adds that missing layer: one severity system, applied consistently,
everywhere a number or state needs to communicate "how good or bad is this."
Everything else in `ui_notes.md` (typography, icons, card shadows/spacing, nav,
responsive grid) still applies unchanged.

---

## 1. Semantic color discipline for computed metrics

### 1.1 One severity scale, used dashboard-wide

Any value-driven metric (a risk score, a ranking, a unit status) must map to one
of a shared set of tiers — never a one-off color choice per card:

```python
# shared/severity.py — import this anywhere a computed metric needs a color.

SEVERITY_TIERS = {
    "bajo":     {"bg": "#dcfce7", "text": "#15803d", "border": "#86efac", "fill": "#16a34a", "label": "Bajo"},
    "atencion": {"bg": "#fef3c7", "text": "#92400e", "border": "#fde68a", "fill": "#f59e0b", "label": "Atención"},
    "alto":     {"bg": "#fee2e2", "text": "#b91c1c", "border": "#fca5a5", "fill": "#dc2626", "label": "Alto"},
}

def classify_severity(value, low_max=40, high_min=70):
    """Map a 0-100 score to a tier.
    Thresholds (40/70) are placeholders from the Evidencia mockup — CONFIRM with
    the team before relying on them anywhere (see §10)."""
    if value < low_max:
        return "bajo"
    if value < high_min:
        return "atencion"
    return "alto"
```

No chart, tile, or badge should pick a color for a computed value without going
through this (or an equivalent, single, documented) classifier. If a tab needs
different thresholds than another, that's a parameter to this function — not a
reason to invent a new palette.

### 1.2 Reserve the worst color for the worst tier

A unit/alert status banner needs **headroom**: if "Anormal" already uses full
solid red, there's nowhere to escalate to when something is actually critical,
and every non-normal unit ends up looking equally alarming (alarm fatigue).

Use three tiers, not two, for any unit/alert status surface:

```python
STATUS_TIERS = {
    "normal":  {"bg": "#ffffff", "text": "#0f172a", "border": "#d1d5db",
                "badge_bg": "#dcfce7", "badge_text": "#15803d"},
    "anormal": {"bg": "#c2410c", "text": "#ffffff", "border": "#c2410c",
                "badge_bg": "rgba(255,255,255,.16)", "badge_text": "#ffffff"},
    "critico": {"bg": "#b91c1c", "text": "#ffffff", "border": "#b91c1c",
                "badge_bg": "rgba(255,255,255,.16)", "badge_text": "#ffffff"},
}
```

`normal` is quiet (no alarm color at all) · `anormal` is amber/orange ·
`critico` is the deep red the current pages use for every non-normal state today.
This is a tiering change, not just a repaint — it should be applied anywhere a
unit/alert "Estado" is shown (Predictivo, Alertas, Aceite fleet views).

### 1.3 Color is never the only signal

Every color-coded value needs a text label next to it (a chip, a word, a badge) —
not just a tint or a border. A viewer should be able to tell severity from the
text alone, with color as reinforcement, not as the only channel. Example: a
decreasing-risk trend shows "▼ -7.4 pts" **and** the word "Mejorando," not just a
green down-arrow.

---

## 2. The left-border-accent card: deprecated

The left-border-colored-card pattern seen on the Predictivo KPI row (and worth
checking for elsewhere) isn't documented anywhere in `ui_notes.md` — it was
invented ad hoc, inconsistently, per card. Retire it. `ui_notes.md` already has a
better pattern for identity-based coloring (full tinted card backgrounds, §Card
Background Colors) — prefer that, or one of these, over a colored left edge:

- **Tinted icon badge** — a small rounded square behind the card's icon, colored
  per severity/identity, rather than a border running the height of the card.
- **Chip + gauge** (see §3) for scored metrics — the color lives in a small,
  explicit element, not an ambient edge.

---

## 3. KPI tile pattern for scored (0–100) metrics

```python
def render_kpi_gauge_tile(label, value, scale_max=100, caption=None, tiered=True):
    """
    KPI tile for a 0-100 scored metric.

    tiered=True  -> value is a risk/severity score; colored via classify_severity().
    tiered=False -> value is NOT risk/severity (e.g. a classification confidence
                    or "how dominant is this mode" score). Use a neutral info
                    color instead — never reuse the red/amber/green severity
                    palette for a number whose meaning isn't actually severity.
    """
    if tiered:
        tier = SEVERITY_TIERS[classify_severity(value)]
        fill = tier["fill"]
        chip = html.Span(tier["label"], className="kpi-chip", style={
            "background": tier["bg"], "color": tier["text"],
        })
    else:
        fill = "#2563eb"  # neutral info blue
        chip = None

    return dbc.Card(
        dbc.CardBody([
            html.Div([
                html.Div(label.upper(), className="text-muted kpi-label"),
                chip,
            ], className="d-flex justify-content-between align-items-center"),
            html.Div(f"{value}", className="kpi-value"),
            html.Div(
                html.Div(className="kpi-gauge-fill", style={"width": f"{value}%", "background": fill}),
                className="kpi-gauge-track",
            ),
            html.Div(caption or f"Escala 0–{scale_max}", className="text-muted kpi-caption"),
        ]),
        className="shadow-sm h-100",  # h-100: equal-height tiles in a row, no exceptions
    )
```

```css
/* assets/kpi.css */
.kpi-label   { font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; }
.kpi-value   { font-size: 30px; font-weight: 700; line-height: 1; margin: 10px 0; }
.kpi-caption { font-size: 12px; }
.kpi-chip    { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
.kpi-gauge-track { height: 6px; border-radius: 999px; background: #e5e7eb; overflow: hidden; margin-bottom: 8px; }
.kpi-gauge-fill  { height: 100%; border-radius: 999px; }
```

Rules:
- Any two metrics on the same conceptual scale (e.g. two risk scores) must use
  the **same** `classify_severity` thresholds — never let one tile's "Atención"
  mean a different range than another's.
- `h-100` is mandatory on every tile in a KPI row, so uneven text length (a long
  label like "Desbalance Térmico entre Bancos") never breaks row alignment.
- A non-severity score (confidence, dominance, intensity) gets `tiered=False` —
  don't let it borrow the risk palette just because it's also a number 0–100.

---

## 4. Status banner / hero header pattern

```python
def render_status_banner(unit_id, component, estado, horometro, last_date):
    t = STATUS_TIERS[estado]
    return html.Div([
        html.Div([
            # icon + eyebrow/title/subtitle, colored from `t`
        ], className="d-flex align-items-center gap-3"),
        html.Div([
            # horómetro value + date
            html.Span(STATUS_TIERS[estado]["badge_text"] and estado.capitalize(),
                      className="status-badge",
                      style={"background": t["badge_bg"], "color": t["badge_text"]}),
        ], className="d-flex align-items-center gap-4"),
    ], className="status-banner p-4 rounded-4", style={
        "background": t["bg"], "color": t["text"], "border": f'1px solid {t["border"]}',
    })
```

One status value drives banner background, text color, *and* badge — never let a
banner's color and its badge's color be set independently; they'll drift apart.

---

## 5. Information hierarchy: decision-relevant vs. metadata

Not every KPI deserves equal visual weight. Before adding a tile to a summary
row, ask: *does a technician act differently depending on this value right now?*

- **Decision-relevant** (trend direction, dominant failure mode, current score) →
  full KPI tile.
- **Metadata** (last-updated date, record counts, file freshness) → a caption or
  inline note next to the section subtitle, not a tile competing for the same
  attention. ("Última evidencia: 17 Oct 2026" belongs next to "Indicadores
  principales de riesgo," not as its own card.)

---

## 6. Accessible interactive elements

- Every clickable control is a real `<button>`/`<a href>`, every input a real
  `<input>`/`<select>` paired with a `<label for>` — never a `<div>` with
  `onClick`. This isn't just correctness: Tab navigation and screen readers
  depend on it.
- An actionable list (the "Acciones" panel in Análisis Inteligente, or anything
  similar elsewhere) should render as a real checklist — `dcc.Checklist` or
  individual `dbc.Checkbox` + label — not plain bullets, whenever the items are
  things a technician will actually act on and could mark done.

---

## 7. Copy & typography conventions

- Keep Spanish accents correct in headers and labels ("Análisis," not
  "Analisis") — a quick pass over existing section titles is worth doing.
- Headers use Title Case consistently ("Causa Probable," not "Causa probable").
- Spell out abbreviations in labels where the full word isn't much longer
  ("Riesgo Acumulado 90d," not "Riesgo acum. 90d") — label real estate is rarely
  the constraint; clarity is.

---

## 8. Tab / navigation indicator

The active-tab underline must be scoped to the active tab's own label width
(e.g. a `border-bottom` on the tab element itself), not a full-width line drawn
across the whole tab bar container. Worth a quick visual check across every
section that uses this tab pattern, not just Predictivo.

---

## 9. Where to audit next (codebase pointers)

Based on the codebase orientation doc, these are the next places likely to have
the same "undocumented ad hoc color" issue, or that should stay visually in sync
with whatever Predictivo adopts:

- `dashboard/callbacks/machines_callbacks.py` — Oil's `fleet-heatmap-table`
  (`update_fleet_heatmap_table`).
- `dashboard/callbacks/telemetry_callbacks.py` — Telemetría's
  `telemetry-fleet-status-table` (`_fleet_status_table` / `update_fleet_overview`).
  **Note:** this one and the Oil heatmap above intentionally share one visual
  convention (header color, cell padding, status palette, tooltips) — if either
  is updated to follow this guide, update both together.
- `dashboard/callbacks/alerts_callbacks.py` (`_alert_case_header`) and
  `dashboard/callbacks/reports_callbacks.py` (`create_ai_diagnosis_and_action`) —
  both render an "Análisis Inteligente"-style box with the same left-border-card
  look addressed in §2; they're two independent parsers but could both adopt the
  same restyled card shell without touching their (different) text-parsing logic.

---

## 10. Open questions / decisions still needed from the team

- **Severity thresholds.** `classify_severity`'s 40/70 split is a placeholder
  from the mockup, not a confirmed business rule — needs real thresholds per
  metric (Ranking 7 Días and Riesgo Acumulado 90d may not share the same cutoffs
  after all).
- **"Modo Dominante" / "Riesgo por Modo de Falla" label source.** Carried over
  from the Evidencia requirement: confirm whether the unit "Estado" label is
  missing the Curva Acumulada classification, and if so, apply the same fix to
  Riesgo por Modo de Falla's labels for consistency.
- **Which fixed KPI identities should move to the gauge pattern.** The four
  named cards in `ui_notes.md` (Total Alerts, Affected Units, Telemetry
  Coverage, Oil Analysis) are identity-tinted today; if any of them becomes a
  value-driven score later, they should move to §3's pattern instead of keeping
  a fixed tint regardless of value.

---

## 11. Changelog

- **v1.0 (Oct 2026)** — initial version, derived from the Predictivo → Evidencia
  (CA-83) redesign and review.
