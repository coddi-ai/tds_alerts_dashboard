"""
Data freshness thresholds and styling, shared across every technique.

Confirmed business rule (documentation/general/general_specs/00_implementation_guide.md
§3.2): Telemetria/Tribologia thresholds are unchanged; Alertas/Predictivo/
Mantenciones are new for the Phase 1 Fleet Overview. Moved out of
dashboard/callbacks/data_freshness_callbacks.py into its own config module per
that guide's "confirmed implementation direction: modularize thresholds into
a config file" - this is the single source of truth every technique's
freshness row reads from, instead of a two-key hardcode that only covered
Telemetria/Tribologia.
"""

from datetime import timedelta

from dashboard.components.labels import NO_DATA_ICON, NO_DATA_BG, NO_DATA_TEXT

# W34-02: the legend, the freshness table and the Fleet Overview cards all
# read icon/color from here instead of hand-picking their own palette.
# `bg`/`text` reuse the app-wide :root design tokens; `accent` stays a literal
# hex because it also feeds FRESHNESS_CRITERIA's threshold tuples below.
FRESHNESS_STATUS_STYLE: dict[str, dict[str, str]] = {
    'Ok':          {'icon': '🟢', 'accent': '#28a745', 'bg': 'var(--green-light)', 'text': 'var(--green-text)'},
    'Atención':    {'icon': '🟡', 'accent': '#ffc107', 'bg': 'var(--amber-light)', 'text': 'var(--amber-text)'},
    'Preocupante': {'icon': '🔴', 'accent': '#dc3545', 'bg': 'var(--red-light)',   'text': 'var(--red-text)'},
    # A unit/technique with no record at all, distinct from a resolved
    # Ok/Atención/Preocupante reading. Reuses labels.py's NO_DATA_* constants
    # - the same "no data" identity Estado x Unidad and Predictivo use.
    'Sin Datos':   {'icon': NO_DATA_ICON, 'accent': '#808080', 'bg': NO_DATA_BG, 'text': NO_DATA_TEXT},
}


# Modular criteria for data freshness status, one entry per technique.
# Format: list of (max_timedelta, label, color) in order of priority (best to
# worst). The last entry is the fallback (worst status).
FRESHNESS_CRITERIA = {
    'Telemetria': [
        (timedelta(hours=2),  'Ok',          FRESHNESS_STATUS_STYLE['Ok']['accent']),
        (timedelta(hours=24), 'Atención',    FRESHNESS_STATUS_STYLE['Atención']['accent']),
        (timedelta(hours=24), 'Preocupante', FRESHNESS_STATUS_STYLE['Preocupante']['accent']),
    ],
    'Tribologia': [
        (timedelta(days=20),  'Ok',          FRESHNESS_STATUS_STYLE['Ok']['accent']),
        (timedelta(days=40),  'Atención',    FRESHNESS_STATUS_STYLE['Atención']['accent']),
        (timedelta(days=40),  'Preocupante', FRESHNESS_STATUS_STYLE['Preocupante']['accent']),
    ],
    # New — confirmed this round (§3.2): Normal <1wk, Alerta 1-3wk, Anormal >3wk.
    'Alertas': [
        (timedelta(weeks=1), 'Ok',          FRESHNESS_STATUS_STYLE['Ok']['accent']),
        (timedelta(weeks=3), 'Atención',    FRESHNESS_STATUS_STYLE['Atención']['accent']),
        (timedelta(weeks=3), 'Preocupante', FRESHNESS_STATUS_STYLE['Preocupante']['accent']),
    ],
    # New — confirmed this round (§3.2): same shape as Alertas.
    'Predictivo': [
        (timedelta(weeks=1), 'Ok',          FRESHNESS_STATUS_STYLE['Ok']['accent']),
        (timedelta(weeks=3), 'Atención',    FRESHNESS_STATUS_STYLE['Atención']['accent']),
        (timedelta(weeks=3), 'Preocupante', FRESHNESS_STATUS_STYLE['Preocupante']['accent']),
    ],
    # New — confirmed this round (§3.2): Normal <2wk, Alerta 2-4wk, Anormal >4wk.
    'Mantenciones': [
        (timedelta(weeks=2), 'Ok',          FRESHNESS_STATUS_STYLE['Ok']['accent']),
        (timedelta(weeks=4), 'Atención',    FRESHNESS_STATUS_STYLE['Atención']['accent']),
        (timedelta(weeks=4), 'Preocupante', FRESHNESS_STATUS_STYLE['Preocupante']['accent']),
    ],
}
