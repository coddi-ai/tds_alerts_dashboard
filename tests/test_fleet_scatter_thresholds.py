"""Posición en la flota: per-client/component quadrant thresholds, horómetro in
the tooltip, and zone contrast."""
import numpy as np
import pandas as pd
import pytest

from config.settings import Settings
from dashboard.components.predictive_charts import create_fleet_scatter

COLORS = {"Normal": "#1d9e75", "Anormal": "#e24b4a"}


def _latest(n=6):
    return pd.DataFrame({
        "Unit": [f"T_{i:02d}" for i in range(n)],
        "ranking": np.linspace(2, 30, n),
        "avg_ranking_30d": np.linspace(30, 3, n),
        "status": ["Normal", "Anormal"] * (n // 2),
    })


def _dividers(fig):
    return [s for s in fig.layout.shapes if s.type == "line"]


def _zones(fig):
    return [s for s in fig.layout.shapes if s.type == "rect"]


@pytest.mark.parametrize("client,component,expected", [
    ("capstone", "motor", (50, 50)),
    ("CAPSTONE", "motor", (50, 50)),
    ("cda", "motor", (16, 16)),
    ("cda", "transmision", (16, 16)),
])
def test_configured_thresholds(client, component, expected):
    assert Settings().get_fleet_scatter_threshold(client, component) == expected


@pytest.mark.parametrize("client,component", [("cda", "convertidor"), ("emin", "motor"), ("capstone", "transmision"), (None, "motor")])
def test_unconfigured_pair_has_no_threshold(client, component):
    assert Settings().get_fleet_scatter_threshold(client, component) is None


@pytest.mark.parametrize("thresh", [(50, 50), (16, 16), (16, 40)])
def test_dividers_zones_and_labels_follow_the_threshold(thresh):
    fig = create_fleet_scatter(_latest(), None, COLORS, thresholds=thresh)
    xs = {s.x0 for s in _dividers(fig) if s.x0 == s.x1}
    ys = {s.y0 for s in _dividers(fig) if s.y0 == s.y1}
    assert xs == {thresh[0]} and ys == {thresh[1]}
    assert len(_zones(fig)) == 4 and len(fig.layout.annotations) == 4
    labels = {a.text: (a.x, a.y) for a in fig.layout.annotations}
    # every label sits inside its own zone, i.e. on the matching side of both dividers
    for (x, y), left, below in zip(
        labels.values(), [False, False, True, True], [False, True, False, True]
    ):
        assert (x < thresh[0]) == left and (y < thresh[1]) == below


def test_axis_range_contains_threshold_when_fleet_is_all_on_one_side():
    fig = create_fleet_scatter(_latest(), None, COLORS, thresholds=(50, 50))
    assert fig.layout.xaxis.range[1] > 50 and fig.layout.yaxis.range[1] > 50


def test_no_threshold_renders_plain_scatter():
    fig = create_fleet_scatter(_latest(), None, COLORS, thresholds=None)
    assert not fig.layout.shapes and not fig.layout.annotations
    assert sum(len(t.x) for t in fig.data) == 6


def test_all_nan_ranking_does_not_break_the_chart():
    df = _latest()
    df["ranking"] = np.nan
    df["avg_ranking_30d"] = np.nan
    for thresh in [(16, 16), None]:
        fig = create_fleet_scatter(df, None, COLORS, thresholds=thresh)
        assert all(np.isfinite(fig.layout.xaxis.range)) and all(np.isfinite(fig.layout.yaxis.range))


def test_tooltip_shows_meter_and_dash_for_unit_without_reading():
    df = _latest()
    fig = create_fleet_scatter(df, "T_01", COLORS, thresholds=(16, 16),
                               meter_by_unit={"T_00": 12345.0, "T_01": 800.0})
    for trace in fig.data:
        assert "%{hovertext}" in trace.hovertemplate
        # existing fields are still there
        assert "%{x:.0f}" in trace.hovertemplate and "%{y:.1f}" in trace.hovertemplate
        assert trace.hovertemplate.endswith("<extra></extra>")
    texts = {u: h for t in fig.data for u, h in zip(t.text, t.hovertext)}
    assert texts["T_00"] == "12,345 hrs" and texts["T_01"] == "800 hrs" and texts["T_02"] == "—"


def test_tooltip_without_meter_source_is_unchanged():
    fig = create_fleet_scatter(_latest(), None, COLORS, thresholds=(16, 16), meter_by_unit=None)
    for trace in fig.data:
        assert "hovertext" not in trace.hovertemplate and trace.hovertext is None


def test_click_to_evidence_still_reads_the_unit_from_customdata():
    fig = create_fleet_scatter(_latest(), "T_01", COLORS, thresholds=(16, 16), meter_by_unit={"T_00": 1.0})
    for trace in fig.data:
        assert list(trace.customdata) == list(trace.text)


def _alpha(rgba):
    return float(rgba.rsplit(",", 1)[1].rstrip(")"))


def _luminance(hex_or_rgb):
    if hex_or_rgb.startswith("#"):
        rgb = [int(hex_or_rgb[i:i + 2], 16) for i in (1, 3, 5)]
    else:
        rgb = [float(v) for v in hex_or_rgb[hex_or_rgb.index("(") + 1:-1].split(",")[:3]]
    lin = [(c / 255) / 12.92 if c / 255 <= 0.03928 else (((c / 255) + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def test_zone_fills_are_stronger_and_labels_readable_on_them():
    fig = create_fleet_scatter(_latest(), None, COLORS, thresholds=(16, 16))
    for shape, ann in zip(_zones(fig), fig.layout.annotations):
        assert _alpha(shape.fillcolor) >= 0.15  # was 0.05
        r, g, b = [float(v) for v in shape.fillcolor[5:shape.fillcolor.rindex(",")].split(",")]
        a = _alpha(shape.fillcolor)
        blended = f"rgb({255 * (1 - a) + r * a},{255 * (1 - a) + g * a},{255 * (1 - a) + b * a})"
        l1, l2 = sorted([_luminance(blended), _luminance(ann.font.color)], reverse=True)
        assert (l1 + 0.05) / (l2 + 0.05) >= 4.5  # WCAG AA for normal text
