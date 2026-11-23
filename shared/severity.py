"""One severity scale for the whole dashboard (ui_notes_improved.md §1.1 and §1.2).

Any value-driven metric (a score, a ranking, a unit status) takes its colors from here - never a
one-off palette per card. Import this anywhere a computed metric needs a color:

    from shared.severity import SEVERITY_TIERS, classify_severity

If a tab needs different thresholds than another, that is a parameter of `classify_severity`,
not a reason to invent a new palette.
"""

SEVERITY_TIERS = {
    "bajo":     {"bg": "#dcfce7", "text": "#15803d", "border": "#86efac", "fill": "#16a34a", "label": "Bajo"},
    "atencion": {"bg": "#fef3c7", "text": "#92400e", "border": "#fde68a", "fill": "#f59e0b", "label": "Atención"},
    "alto":     {"bg": "#fee2e2", "text": "#b91c1c", "border": "#fca5a5", "fill": "#dc2626", "label": "Alto"},
}


def classify_severity(value, low_max=40, high_min=70):
    """Map a 0-100 score to a tier.

    Thresholds (40/70) are placeholders from the Evidencia mockup - CONFIRM with the team before
    relying on them anywhere (ui_notes_improved.md §10). The Oil frequency panel passes its own
    (`low_max=80, high_min=100`).
    """
    if value < low_max:
        return "bajo"
    if value < high_min:
        return "atencion"
    return "alto"


# §1.2: a unit/alert status surface has three tiers, not two, so the worst one keeps headroom.
# `normal` is quiet (no alarm color at all), `anormal` is amber/orange, `critico` is the deep red.
STATUS_TIERS = {
    "normal":  {"bg": "#ffffff", "text": "#0f172a", "border": "#d1d5db",
                "badge_bg": "#dcfce7", "badge_text": "#15803d"},
    "anormal": {"bg": "#c2410c", "text": "#ffffff", "border": "#c2410c",
                "badge_bg": "rgba(255,255,255,.16)", "badge_text": "#ffffff"},
    "critico": {"bg": "#b91c1c", "text": "#ffffff", "border": "#b91c1c",
                "badge_bg": "rgba(255,255,255,.16)", "badge_text": "#ffffff"},
}

# The Oil status words (Normal / Alerta / Anormal) onto those tiers. The mapping was approved with
# the requirement: Alerta is the orange tier and Anormal the deep red one.
STATUS_TIER_BY_ESTADO = {"Normal": "normal", "Alerta": "anormal", "Anormal": "critico"}

# The tinted component cells keep three tints, taken from the severity tiers.
SEVERITY_TIER_BY_ESTADO = {"Normal": "bajo", "Alerta": "atencion", "Anormal": "alto"}
