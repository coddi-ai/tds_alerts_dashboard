"""W34-02 — Mejorar Look&Feel Estado de Datos.

Before: three independently hand-picked icon/color palettes for the same
three statuses (Ok/Atención/Preocupante) — one in the (now retired) Data
Summary tab's legend, one baked into `FRESHNESS_CRITERIA`'s tuples, one
hardcoded across 8 `style_data_conditional` rules in the table (repeated once
per column). They happened to roughly agree; nothing enforced it.

After: `FRESHNESS_STATUS_STYLE` is the single source (icon, accent, bg,
text). Phase 1 (documentation/general/general_specs/01_fleet_overview_unified_view.md)
retired the standalone Data Summary tab and moved both dicts to
config/freshness_thresholds.py, covering all 5 techniques now instead of
just Telemetria/Tribologia - dashboard/callbacks/data_freshness_callbacks.py
re-exports the same names for backward compatibility.

Explicitly NOT touched (per the plan's "no cambia el cálculo de frescura"):
the threshold values inside FRESHNESS_CRITERIA, and calculate_freshness_status's
actual classification logic — only where the *color value* comes from.
"""

from datetime import datetime, timedelta

import pytz

from dashboard.callbacks.data_freshness_callbacks import (
    FRESHNESS_CRITERIA,
    FRESHNESS_STATUS_STYLE,
    calculate_freshness_status,
)


# ---------------------------------------------------------------------------
# 1. Thresholds are untouched — only the color's source changed
# ---------------------------------------------------------------------------

def test_telemetria_thresholds_unchanged():
    thresholds = [t for t, _, _ in FRESHNESS_CRITERIA['Telemetria']]
    assert thresholds == [timedelta(hours=2), timedelta(hours=24), timedelta(hours=24)]


def test_tribologia_thresholds_unchanged():
    thresholds = [t for t, _, _ in FRESHNESS_CRITERIA['Tribologia']]
    assert thresholds == [timedelta(days=20), timedelta(days=40), timedelta(days=40)]


def test_criteria_colors_still_match_the_original_hex_values():
    """The consolidation must be value-preserving — same three hex codes,
    now traced to FRESHNESS_STATUS_STYLE instead of typed twice."""
    telem_colors = [c for _, _, c in FRESHNESS_CRITERIA['Telemetria']]
    assert telem_colors == ['#28a745', '#ffc107', '#dc3545']
    tribo_colors = [c for _, _, c in FRESHNESS_CRITERIA['Tribologia']]
    assert tribo_colors == ['#28a745', '#ffc107', '#dc3545']


def test_criteria_colors_are_literally_the_same_object_as_the_style_map():
    """Not just equal by coincidence — FRESHNESS_CRITERIA's color values are
    read directly from FRESHNESS_STATUS_STYLE, so they cannot drift apart."""
    for label in ('Ok', 'Atención', 'Preocupante'):
        criteria_color = next(c for _, l, c in FRESHNESS_CRITERIA['Telemetria'] if l == label)
        assert criteria_color == FRESHNESS_STATUS_STYLE[label]['accent']


# ---------------------------------------------------------------------------
# 2. calculate_freshness_status — classification behavior unchanged
# ---------------------------------------------------------------------------

def _chile_now():
    return datetime.now(pytz.timezone('America/Santiago'))


def test_missing_value_is_sin_datos():
    status, color, time_str = calculate_freshness_status(None, 'Telemetria', _chile_now())
    assert status == 'Sin Datos'
    assert color == FRESHNESS_STATUS_STYLE['Sin Datos']['accent']
    assert time_str == 'N/A'


def test_recent_telemetria_is_ok():
    now = _chile_now()
    status, color, _ = calculate_freshness_status(now - timedelta(minutes=30), 'Telemetria', now)
    assert status == 'Ok'
    assert color == FRESHNESS_STATUS_STYLE['Ok']['accent']


def test_stale_telemetria_is_atencion():
    now = _chile_now()
    status, _, _ = calculate_freshness_status(now - timedelta(hours=10), 'Telemetria', now)
    assert status == 'Atención'


def test_very_stale_telemetria_is_preocupante():
    now = _chile_now()
    status, _, _ = calculate_freshness_status(now - timedelta(hours=30), 'Telemetria', now)
    assert status == 'Preocupante'


def test_tribologia_uses_day_scale_thresholds():
    now = _chile_now()
    status, _, _ = calculate_freshness_status(now - timedelta(days=10), 'Tribologia', now)
    assert status == 'Ok'
    status, _, _ = calculate_freshness_status(now - timedelta(days=30), 'Tribologia', now)
    assert status == 'Atención'
    status, _, _ = calculate_freshness_status(now - timedelta(days=50), 'Tribologia', now)
    assert status == 'Preocupante'


# ---------------------------------------------------------------------------
# 3. Ok / Atención / Preocupante / Sin Datos are all visually distinct
# ---------------------------------------------------------------------------

def test_all_four_statuses_have_distinct_accent_colors():
    accents = {style['accent'] for style in FRESHNESS_STATUS_STYLE.values()}
    assert len(accents) == 4


def test_all_four_statuses_have_distinct_backgrounds():
    backgrounds = {style['bg'] for style in FRESHNESS_STATUS_STYLE.values()}
    assert len(backgrounds) == 4


def test_style_reuses_root_design_tokens_not_new_hardcoded_hex():
    """bg/text values are CSS var() references into predictive_styles.css's
    :root block, not a fifth set of literal hex values."""
    for label in ('Ok', 'Atención', 'Preocupante', 'Sin Datos'):
        assert FRESHNESS_STATUS_STYLE[label]['bg'].startswith('var(--')
        assert FRESHNESS_STATUS_STYLE[label]['text'].startswith('var(--')


# ---------------------------------------------------------------------------
# 4. Phase 1 additions — Alertas/Predictivo/Mantenciones now have thresholds
#    too (documentation/general/general_specs/00_implementation_guide.md §3.2)
# ---------------------------------------------------------------------------

def test_alertas_and_predictivo_share_the_same_1_3_week_shape():
    for key in ('Alertas', 'Predictivo'):
        thresholds = [t for t, _, _ in FRESHNESS_CRITERIA[key]]
        assert thresholds == [timedelta(weeks=1), timedelta(weeks=3), timedelta(weeks=3)]


def test_mantenciones_uses_the_2_4_week_shape():
    thresholds = [t for t, _, _ in FRESHNESS_CRITERIA['Mantenciones']]
    assert thresholds == [timedelta(weeks=2), timedelta(weeks=4), timedelta(weeks=4)]
