"""Short View "Posición en la flota": the (x, y) ranking fields are configuration
(Settings.fleet_scatter_axes, keyed client -> component like the thresholds), never
hardcoded in the chart; a pair without an entry has no default pairing."""
import json

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from config.settings import Settings
from dashboard.components.predictive_charts import create_fleet_scatter
from dashboard.components.predictive_state import STATE_COLORS
from dashboard.tabs import tab_predictive_overview as ov

PAIRS = [("capstone", "motor"), ("cda", "motor"), ("cda", "transmision")]
COLUMN = {"ranking_today": "ranking", "ranking_7d": "avg_ranking_7d", "ranking_30d": "avg_ranking_30d",
          "ranking_60d": "avg_ranking_60d", "ranking_90d": "ranking_acum_90d"}


def _latest(n=6):
    """Every ranking field on its own scale so a swapped axis cannot go unnoticed."""
    return pd.DataFrame({
        "Unit": [f"T_{i:02d}" for i in range(n)],
        "ranking": np.linspace(40, 1, n),
        "avg_ranking_7d": np.linspace(2, 30, n),
        "avg_ranking_30d": np.linspace(30, 3, n),
        "avg_ranking_60d": np.linspace(25, 4, n),
        "ranking_acum_90d": np.linspace(20, 5, n),
        "status": ["Normal", "Alerta", "Anormal"] * (n // 3),
    })


def _plotted(fig):
    return (sorted(x for t in fig.data for x in t.x), sorted(y for t in fig.data for y in t.y))


@pytest.fixture()
def use_settings(monkeypatch):
    """Run the tab's chart helpers against a Settings built from the given overrides."""
    monkeypatch.setattr(ov, "load_latest_component_meter", lambda *a, **k: {})

    def use(**overrides):
        settings = Settings(**overrides)
        monkeypatch.setattr(ov, "get_settings", lambda: settings)
        return settings
    return use


# ── configuration ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("client,component", PAIRS)
def test_default_axes_are_7d_vs_90d_for_every_pair_with_a_threshold(client, component):
    settings = Settings()
    assert settings.get_fleet_scatter_axes(client, component) == ("ranking_7d", "ranking_90d")
    assert settings.get_fleet_scatter_threshold(client, component) is not None
    assert settings.get_fleet_scatter_axes(client.upper(), component) == ("ranking_7d", "ranking_90d")


def test_axes_and_thresholds_cover_the_same_pairs():
    settings = Settings()
    pairs = lambda cfg: {(c, k) for c, by in cfg.items() for k in by}  # noqa: E731
    assert pairs(settings.fleet_scatter_axes) == pairs(settings.fleet_scatter_thresholds)


@pytest.mark.parametrize("client,component", [("enex", "motor"), ("cda", "hidraulico"), ("", ""), (None, None)])
def test_a_pair_without_an_entry_has_no_axes(client, component):
    assert Settings().get_fleet_scatter_axes(client, component) is None


def test_axes_can_be_overridden_from_the_environment(monkeypatch):
    monkeypatch.setenv("FLEET_SCATTER_AXES", json.dumps({"CDA": {"motor": ["ranking_30d", "ranking_60d"]}}))
    settings = Settings()
    assert settings.get_fleet_scatter_axes("cda", "motor") == ("ranking_30d", "ranking_60d")
    assert settings.get_fleet_scatter_axes("capstone", "motor") is None  # replaced, not merged: no hidden default


def test_an_unknown_ranking_field_in_the_config_is_rejected():
    with pytest.raises(ValidationError, match="ranking_45d"):
        Settings(fleet_scatter_axes={"CDA": {"motor": ("ranking_7d", "ranking_45d")}})


# ── the chart reads its axes from the configuration ──────────────────────────

@pytest.mark.parametrize("client,component", PAIRS)
def test_short_view_plots_7d_vs_90d_by_default(use_settings, client, component):
    use_settings()
    df = _latest()
    fig = ov.make_fleet_scatter(df, client, component, None, STATE_COLORS, height=None)
    xs, ys = _plotted(fig)
    assert xs == pytest.approx(sorted(df["avg_ranking_7d"])) and ys == pytest.approx(sorted(df["ranking_acum_90d"]))
    assert fig.layout.xaxis.title.text == "Ranking 7 días" and fig.layout.yaxis.title.text == "Ranking 90 días"


@pytest.mark.parametrize("axes", [
    ("ranking_7d", "ranking_30d"), ("ranking_7d", "ranking_60d"), ("ranking_today", "ranking_30d"), ("ranking_90d", "ranking_7d"),
])
def test_changing_the_configured_fields_changes_what_is_plotted_without_code_changes(use_settings, axes):
    use_settings(fleet_scatter_axes={"CDA": {"motor": axes}})
    df = _latest()
    fig = ov.make_fleet_scatter(df, "cda", "motor", None, STATE_COLORS, height=None)
    xs, ys = _plotted(fig)
    assert xs == pytest.approx(sorted(df[COLUMN[axes[0]]])) and ys == pytest.approx(sorted(df[COLUMN[axes[1]]]))


def test_each_pair_follows_its_own_entry(use_settings):
    use_settings(fleet_scatter_axes={"CDA": {"motor": ("ranking_7d", "ranking_30d"), "transmision": ("ranking_7d", "ranking_90d")}})
    df = _latest()
    motor = _plotted(ov.make_fleet_scatter(df, "cda", "motor", None, STATE_COLORS))
    transmision = _plotted(ov.make_fleet_scatter(df, "cda", "transmision", None, STATE_COLORS))
    assert motor[1] == pytest.approx(sorted(df["avg_ranking_30d"]))
    assert transmision[1] == pytest.approx(sorted(df["ranking_acum_90d"]))


def test_a_pair_without_axes_is_not_drawn_with_any_default_pairing(use_settings):
    use_settings(fleet_scatter_axes={"CDA": {"motor": ("ranking_7d", "ranking_90d")}})
    fig = ov.make_fleet_scatter(_latest(), "capstone", "motor", None, STATE_COLORS, height=None)
    assert not fig.data
    assert [a.text for a in fig.layout.annotations] == ["Los ejes de este gráfico no están configurados para este cliente y componente."]


def test_the_short_view_of_an_unconfigured_pair_offers_and_draws_no_unit(use_settings):
    use_settings(fleet_scatter_axes={})
    latest = _latest()
    drawable, universe, groups = ov._short_view_model(latest, "cda", "motor")
    assert drawable.empty and universe == [] and not any(groups.values())
    assert not ov.render_short_view(latest, "cda", "motor").children[3].figure.data  # the graph: message only


def test_a_unit_is_drawable_only_if_it_has_a_value_on_the_configured_axes(use_settings):
    use_settings(fleet_scatter_axes={"CDA": {"motor": ("ranking_7d", "ranking_90d")}})
    latest = _latest()
    latest.loc[0, "ranking_acum_90d"] = np.nan   # configured y: unit cannot be drawn
    latest.loc[1, "avg_ranking_30d"] = np.nan    # not an axis (tooltip only): unit still drawn
    _, universe, _ = ov._short_view_model(latest, "cda", "motor")
    assert "T_00" not in universe and "T_01" in universe


def test_the_chart_has_no_default_pairing_of_its_own():
    with pytest.raises(TypeError):
        create_fleet_scatter(_latest(), None, STATE_COLORS)
    for bad in (None, ("ranking_7d",), ("ranking_7d", "ranking_45d")):
        with pytest.raises(ValueError):
            create_fleet_scatter(_latest(), None, STATE_COLORS, axes=bad)


# ── tooltip and thresholds do not depend on the axes ─────────────────────────

@pytest.mark.parametrize("axes", [("ranking_7d", "ranking_90d"), ("ranking_7d", "ranking_30d"), ("ranking_60d", "ranking_90d")])
def test_tooltip_keeps_today_7d_30d_and_meter_whatever_is_plotted(axes):
    df = _latest()
    fig = create_fleet_scatter(df, None, STATE_COLORS, thresholds=(16, 16), meter_by_unit={"T_00": 100.0}, axes=axes)
    for trace in fig.data:
        template = trace.hovertemplate
        for needle in ("Ranking hoy: %{customdata[1]}", "Ranking 7 días: %{customdata[2]}",
                       "Ranking 30 días: %{customdata[3]}", "Horómetro: %{hovertext}"):
            assert needle in template
        assert "%{x" not in template and "%{y" not in template
    rows = {c[0]: c for t in fig.data for c in t.customdata}
    for i, unit in enumerate(df["Unit"]):
        assert rows[unit][1:] == [f"{df.loc[i, 'ranking']:.0f}", f"{df.loc[i, 'avg_ranking_7d']:.1f}", f"{df.loc[i, 'avg_ranking_30d']:.1f}"]


def test_tooltip_shows_a_dash_for_a_ranking_the_unit_lacks():
    df = _latest()
    df.loc[0, "avg_ranking_30d"] = np.nan
    fig = create_fleet_scatter(df, None, STATE_COLORS, axes=("ranking_7d", "ranking_90d"))
    assert {c[0]: c[3] for t in fig.data for c in t.customdata}["T_00"] == "—"


def test_thresholds_still_split_the_configured_axes(use_settings):
    use_settings(fleet_scatter_axes={"CDA": {"motor": ("ranking_7d", "ranking_60d")}},
                 fleet_scatter_thresholds={"CDA": {"motor": (12.0, 9.0)}})
    fig = ov.make_fleet_scatter(_latest(), "cda", "motor", None, STATE_COLORS, height=None)
    assert {s.x0 for s in fig.layout.shapes if s.type == "line" and s.x0 == s.x1} == {12.0}
    assert {s.y0 for s in fig.layout.shapes if s.type == "line" and s.y0 == s.y1} == {9.0}
    assert len([s for s in fig.layout.shapes if s.type == "rect"]) == 4
