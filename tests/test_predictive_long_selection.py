"""Predictivo General: the unit selection of BOTH layer-2 charts (dropdown / chips / risk badges /
chart), the 2.5:1 chart frame, the red / yellow / green color rule, and the Short View's 7-day x axis."""
import colorsys
import json

import dash
import numpy as np
import pandas as pd
import pytest
from dash import dcc, html
from dash._callback_context import context_value
from dash._utils import AttributeDict

from dashboard.components import predictive_charts as pc
from dashboard.components import predictive_long_selection as sel_mod
from dashboard.components.predictive_charts import SCATTER_BASE_MARKER, create_fleet_scatter, create_long_view_chart
from dashboard.components.predictive_state import STATE_COLORS, STATE_SIZE_FACTOR, STATE_ZONE_FILL
from dashboard.tabs import tab_predictive_overview as ov
from test_predictive_long_view import BANDA, CONFIG, _curve_rows, _fleet, _graphs, _texts

FLEET = ["U1", "U2", "U3", "U4", "U5", "U6"]
GROUPS = {"Anormal": ["U1"], "Alerta": ["U2", "U3"], "Normal": ["U4", "U5", "U6"]}
# The Short View groups by its OWN estado, deliberately different from the Long View's above.
SHORT_STATUS = {"U1": "Normal", "U2": "Normal", "U3": "Anormal", "U4": "Alerta", "U5": "Normal", "U6": "Anormal",
                "U7": "Sin Datos"}
SHORT_GROUPS = {"Anormal": ["U3", "U6"], "Alerta": ["U4"], "Normal": ["U1", "U2", "U5"]}


def _s(*units, badge=None, restore=None):
    return sel_mod.Selection(tuple(units), badge, None if restore is None else tuple(restore))


# ── State machine ────────────────────────────────────────────────────────────

def test_badge_sets_exactly_that_group_and_remembers_what_was_there():
    start = sel_mod.initial_selection(FLEET)
    after = sel_mod.click_badge(start, "Alerta", GROUPS, FLEET)
    assert after.selected == ("U2", "U3") and after.badge == "Alerta" and after.restore == tuple(FLEET)


def test_reclicking_the_active_badge_restores_the_selection_from_before_any_badge():
    on = sel_mod.click_badge(_s("U1", "U4"), "Normal", GROUPS, FLEET)
    off = sel_mod.click_badge(on, "Normal", GROUPS, FLEET)
    assert off == _s("U1", "U4") and off.badge is None and off.restore is None


def test_badge_hopping_restores_the_pre_badge_selection_not_the_previous_badge():
    s = sel_mod.click_badge(_s("U1", "U4"), "Anormal", GROUPS, FLEET)
    s = sel_mod.click_badge(s, "Alerta", GROUPS, FLEET)
    assert s.selected == ("U2", "U3") and s.restore == ("U1", "U4")
    assert sel_mod.click_badge(s, "Alerta", GROUPS, FLEET).selected == ("U1", "U4")  # not the Anormal group


@pytest.mark.parametrize("manual", [
    lambda s: sel_mod.toggle_unit(s, "U6", FLEET),
    lambda s: sel_mod.pick_from_dropdown(s, ["U2"], FLEET),
])
def test_manual_edit_switches_the_badge_off_and_forgets_the_snapshot(manual):
    on = sel_mod.click_badge(sel_mod.initial_selection(FLEET), "Alerta", GROUPS, FLEET)
    edited = manual(on)
    assert edited.badge is None and edited.restore is None
    again = sel_mod.click_badge(edited, "Normal", GROUPS, FLEET)  # the next badge takes a FRESH snapshot
    assert again.restore == edited.selected


def test_dropdown_echo_of_the_current_selection_is_ignored():
    on = sel_mod.click_badge(sel_mod.initial_selection(FLEET), "Alerta", GROUPS, FLEET)
    assert sel_mod.pick_from_dropdown(on, ["U3", "U2"], FLEET) == on  # same set, other order: still the badge view


def test_selection_keeps_fleet_order_and_drops_unknown_units():
    assert sel_mod.pick_from_dropdown(_s("U1"), ["U5", "U2", "ghost"], FLEET).selected == ("U2", "U5")
    assert sel_mod.toggle_unit(_s("U1"), "ghost", FLEET) == _s("U1")


def test_empty_selection_is_a_real_selection_and_restores_to_empty():
    empty = sel_mod.pick_from_dropdown(sel_mod.initial_selection(FLEET), [], FLEET)
    assert empty.selected == ()
    on = sel_mod.click_badge(empty, "Alerta", GROUPS, FLEET)
    assert sel_mod.click_badge(on, "Alerta", GROUPS, FLEET).selected == ()  # back to empty, never the fleet


def test_store_roundtrip_and_bad_store():
    s = _s("U1", badge="Anormal", restore=("U2", "U3"))
    assert sel_mod.from_dict(sel_mod.to_dict(s), FLEET) == s
    assert sel_mod.from_dict(None, FLEET).selected == tuple(FLEET)
    assert sel_mod.from_dict({"selected": ["U1", "gone"]}, FLEET).selected == ("U1",)


# ── Color rule: red / yellow / green, state only ─────────────────────────────

def _hue(color):
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


def test_the_state_palette_is_red_yellow_green():
    assert _hue(STATE_COLORS["Anormal"]) < 10 or _hue(STATE_COLORS["Anormal"]) > 350        # red
    assert 40 <= _hue(STATE_COLORS["Alerta"]) <= 55                                         # yellow, not orange
    assert 140 <= _hue(STATE_COLORS["Normal"]) <= 170                                       # green
    assert set(STATE_ZONE_FILL) == set(STATE_COLORS)


def test_unit_summary_scatter_uses_the_same_palette():
    from dashboard.components import unit_summary_content

    assert unit_summary_content._PREDICTIVE_STATUS_COLORS is STATE_COLORS


# ── Long View chart ──────────────────────────────────────────────────────────

@pytest.fixture()
def fleet_active():
    """6 units, current estado: U1 Anormal / U2,U3 Alerta / U4-U6 Normal, at different scales."""
    final = {"U1": "Anormal", "U2": "Alerta", "U3": "Alerta", "U4": "Normal", "U5": "Normal", "U6": "Normal"}
    frames = [_curve_rows(unit, ["Normal", "Normal", state], hours_step=300.0 * (i + 1))
              for i, (unit, state) in enumerate(final.items())]
    df = pd.concat(frames, ignore_index=True)
    df.attrs.update({"banda": BANDA, "config": CONFIG})
    return df


@pytest.fixture()
def short_frame():
    return pd.DataFrame({
        "Unit": list(SHORT_STATUS), "status": list(SHORT_STATUS.values()),
        "ranking": [90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0],
        "avg_ranking_7d": [5.0, 15.0, 25.0, 35.0, 45.0, 55.0, 65.0],
        "avg_ranking_30d": [8.0, 12.0, 30.0, 26.0, 40.0, 60.0, 20.0],
        "ranking_acum_90d": [10.0, 22.0, 33.0, 44.0, 66.0, 77.0, 88.0],
    })


def _drawn(fig):
    return sorted(t.name for t in fig.data if t.name)


def test_chart_draws_only_the_selected_units(fleet_active):
    assert _drawn(create_long_view_chart(fleet_active, ["U2", "U5"])) == ["U2", "U5"]
    assert _drawn(create_long_view_chart(fleet_active, None)) == FLEET  # None = no filter


def test_empty_selection_is_an_empty_chart_never_the_fleet(fleet_active):
    fig = create_long_view_chart(fleet_active, [])
    assert not fig.data
    assert [a.text for a in fig.layout.annotations] == ["Selecciona al menos una unidad para verla en el gráfico."]
    assert fig.layout.xaxis.visible is False and fig.layout.yaxis.visible is False
    assert not create_long_view_chart(fleet_active, ["not-a-unit"]).data


def test_axes_fit_the_selected_units_not_the_fleet(fleet_active):
    full = create_long_view_chart(fleet_active, FLEET)
    small = create_long_view_chart(fleet_active, ["U1"])   # smallest hours step: ends at 900 h
    big = create_long_view_chart(fleet_active, ["U6"])     # largest: ends at 5400 h
    assert small.layout.xaxis.range[1] < big.layout.xaxis.range[1] == full.layout.xaxis.range[1]
    assert small.layout.yaxis.range[1] <= full.layout.yaxis.range[1]
    assert small.layout.xaxis.range[1] >= 900  # still contains the selected curve


def test_color_encodes_only_the_state_so_units_in_one_state_look_alike(fleet_active):
    traces = {t.name: t for t in create_long_view_chart(fleet_active, FLEET).data if t.name}
    for unit, state in {"U1": "Anormal", "U2": "Alerta", "U3": "Alerta", "U4": "Normal", "U5": "Normal", "U6": "Normal"}.items():
        assert traces[unit].marker.color == STATE_COLORS[state]
        assert traces[unit].line.color == pc._hex_to_rgba(STATE_COLORS[state], 0.85)
    # same state -> the very same line and dot color; no per-unit hue anywhere
    assert len({(traces[u].line.color, traces[u].marker.color) for u in ("U4", "U5", "U6")}) == 1
    assert len({t.marker.color for t in traces.values()}) == 3
    assert len({t.line.color for t in traces.values()}) == 3


def test_a_units_color_follows_its_state_whatever_is_selected(fleet_active):
    first = {t.name: t.line.color for t in create_long_view_chart(fleet_active, FLEET).data if t.name}
    second = {t.name: t.line.color for t in create_long_view_chart(fleet_active, ["U6", "U2"]).data if t.name}
    assert second["U2"] == first["U2"] and second["U6"] == first["U6"]


def test_end_dot_is_sized_and_colored_by_the_units_own_state(fleet_active):
    traces = {t.name: t for t in create_long_view_chart(fleet_active, FLEET).data if t.name}
    for unit, state in (("U1", "Anormal"), ("U2", "Alerta"), ("U6", "Normal")):
        assert traces[unit].marker.color == STATE_COLORS[state]
        assert list(traces[unit].marker.size)[-1] == pytest.approx(SCATTER_BASE_MARKER * STATE_SIZE_FACTOR[state])
        assert set(list(traces[unit].marker.size)[:-1]) == {0}          # a dot only at the line's end


def test_every_drawn_unit_has_one_gray_label_at_its_end_point(fleet_active):
    fig = create_long_view_chart(fleet_active, ["U2", "U5"])
    labels = [a for a in fig.layout.annotations if a.name == "unit-label"]
    assert sorted(a.text for a in labels) == ["U2", "U5"]
    ends = {t.name: (t.x[-1], t.y[-1]) for t in fig.data if t.name}
    assert all((a.x, a.y) == ends[a.text] for a in labels)
    assert {a.font.color for a in labels} == {pc.LABEL_COLOR}          # gray, not the state color
    assert not [a for a in fig.layout.annotations if a.showarrow]      # and never a connector line


def test_crowded_long_view_labels_shrink_or_drop_and_the_dots_stay(fleet_active):
    crowded = pd.concat([_curve_rows(f"C{i:02d}", ["Normal", "Normal", "Normal"], hours_step=300.0 + i)
                         for i in range(20)], ignore_index=True)
    crowded.attrs.update({"banda": BANDA, "config": CONFIG})
    fig = create_long_view_chart(crowded)
    labels = [a for a in fig.layout.annotations if a.name == "unit-label"]
    assert len([t for t in fig.data if t.name]) == 20                  # every unit is drawn
    assert 0 < len(labels) < 20                                        # but its label only where it does not crowd
    assert {a.font.size for a in labels} <= {pc.LABEL_FONT_PX, pc.LABEL_FONT_SMALL_PX}
    assert not [a for a in fig.layout.annotations if a.showarrow]


def test_long_view_figure_has_no_fixed_height_so_the_container_sets_the_frame(fleet_active):
    assert create_long_view_chart(fleet_active, FLEET).layout.height is None
    assert create_long_view_chart(fleet_active, []).layout.height is None


# ── Controls + callback wiring, through a simulated front end ────────────────

def _walk(node, found=None):
    """Every Dash component under `node` (including ones with no `children`, like Store/Dropdown)."""
    found = [] if found is None else found
    found.append(node)
    kids = getattr(node, "children", None)
    for kid in kids if isinstance(kids, (list, tuple)) else [kids]:
        if isinstance(kid, dash.development.base_component.Component):
            _walk(kid, found)
    return found


def _prop_id(kind, key, value):
    return json.dumps({"type": kind, key: value}, separators=(",", ":"), sort_keys=True) + ".n_clicks"


class FrontEnd:
    """What the browser would hold for one panel ("long" or "short"), updated only through the
    real selection callback (its outputs applied the way the Dash renderer does)."""

    def __init__(self, monkeypatch, kind, active, short_frame, client="capstone", component="motor"):
        from dashboard.callbacks import predictive_callbacks as pcb

        monkeypatch.setattr(ov, "load_active_curve", lambda c, comp: active)
        monkeypatch.setattr(pcb, "load_active_curve", lambda c, comp: active)
        monkeypatch.setattr(pcb, "load_status_frame", lambda c, comp: short_frame)
        app = dash.Dash(__name__, suppress_callback_exceptions=True)
        pcb.register_callbacks(app)
        self.kind = kind
        self.panel = ov.LONG_PANEL if kind == "long" else ov.SHORT_PANEL
        self.groups = GROUPS if kind == "long" else SHORT_GROUPS
        self.callback_keys = [k for k in app.callback_map if self.panel.state_id in k]
        self.callback = app.callback_map[self.callback_keys[0]]["callback"].__wrapped__
        self.client, self.component = client, component
        tree = ov.render_long_view(client, component, []) if kind == "long" else ov.render_short_view(short_frame, client, component)
        nodes = _walk(tree)
        self.store = next(n for n in nodes if isinstance(n, dcc.Store)).data
        self.dropdown_props = next(n for n in nodes if isinstance(n, dcc.Dropdown))
        self.dropdown = list(self.dropdown_props.value)
        buttons = [n for n in nodes if isinstance(n, html.Button)]
        self.chips = {n.id["unit"]: n.className for n in buttons if n.id["type"] == self.panel.chip}
        self.badges = {n.id["badge"]: n.className for n in buttons if n.id["type"] == self.panel.badge}
        self.badge_text = {n.id["badge"]: n.children for n in buttons if n.id["type"] == self.panel.badge}
        self.graph = next(n for n in nodes if isinstance(n, dcc.Graph) and n.id == self.panel.graph_id)
        self.figure = self.graph.figure
        self.group_headings = [n.children for n in nodes if getattr(n, "className", None) == "unit-chip-heading"]
        self.texts = _texts(tree)

    def _fire(self, prop_id, value):
        outputs = [
            {"id": self.panel.state_id, "property": "data"},
            {"id": self.panel.dropdown_id, "property": "value"},
            [{"id": {"type": self.panel.chip, "unit": u}, "property": "className"} for u in self.chips],
            [{"id": {"type": self.panel.badge, "badge": b}, "property": "className"} for b in self.badges],
            {"id": self.panel.graph_id, "property": "figure"},
        ]
        context_value.set(AttributeDict(triggered_inputs=[{"prop_id": prop_id, "value": value}], outputs_list=outputs))
        try:
            out = self.callback(self.dropdown, [], [], self.store, self.client, self.component)
        finally:
            context_value.set({})
        for target, new in zip(("store", "dropdown", "chips", "badges", "figure"), out):
            if new is dash.no_update:
                continue
            if target == "chips":
                self.chips = dict(zip(self.chips, new))
            elif target == "badges":
                self.badges = dict(zip(self.badges, new))
            else:
                setattr(self, target, new)
        return out

    def chip(self, unit):
        return self._fire(_prop_id(self.panel.chip, "unit", unit), 1)

    def badge(self, name):
        return self._fire(_prop_id(self.panel.badge, "badge", name), 1)

    def pick(self, values):
        self.dropdown = list(values)  # the user's own change is already in the dropdown
        return self._fire(self.panel.dropdown_id + ".value", list(values))

    @property
    def chips_on(self):
        return sorted(u for u, c in self.chips.items() if "unit-chip--on" in c)

    @property
    def chart(self):
        """The units the chart currently draws."""
        if self.kind == "long":
            return sorted(t.name for t in self.figure.data if t.name)
        return sorted(u for t in self.figure.data for u in t.text)

    @property
    def point_colors(self):
        """{unit: marker color} of what the chart draws."""
        if self.kind == "long":
            return {t.name: t.marker.color for t in self.figure.data if t.name}
        return {u: t.marker.color for t in self.figure.data for u in t.text}

    @property
    def active_badges(self):
        return [b for b, c in self.badges.items() if "unit-badge--active" in c]

    def assert_consistent(self, expected=None):
        assert sorted(self.dropdown) == self.chips_on == self.chart == sorted(self.store["selected"])
        assert self.active_badges == ([self.store["badge"]] if self.store["badge"] else [])
        if expected is not None:
            assert self.chart == sorted(expected)


@pytest.fixture(params=["long", "short"])
def front(request, monkeypatch, fleet_active, short_frame):
    return FrontEnd(monkeypatch, request.param, fleet_active, short_frame)


def test_controls_group_chips_by_the_charts_own_estado_with_fleet_wide_counts(front):
    g = front.groups
    assert front.badge_text == {b: f"{b} ({len(g[b])})" for b in ("Anormal", "Alerta", "Normal")}
    assert front.group_headings == [f"{b} ({len(g[b])})" for b in ("Anormal", "Alerta", "Normal")]
    assert front.dropdown == FLEET and front.chips_on == FLEET and front.active_badges == []
    assert front.dropdown_props.multi is True and front.dropdown_props.searchable is True
    for badge, units in g.items():                                   # chips carry their risk group's color class
        assert all(f"unit-chip--{badge.lower()}" in front.chips[u] for u in units)


def test_each_panel_groups_by_its_own_state_not_the_other_panels(monkeypatch, fleet_active, short_frame):
    long_front = FrontEnd(monkeypatch, "long", fleet_active, short_frame)
    short_front = FrontEnd(monkeypatch, "short", fleet_active, short_frame)
    assert long_front.badge_text != short_front.badge_text
    assert short_front.badge_text == {"Anormal": "Anormal (2)", "Alerta": "Alerta (1)", "Normal": "Normal (3)"}
    assert long_front.badge_text == {"Anormal": "Anormal (1)", "Alerta": "Alerta (2)", "Normal": "Normal (3)"}


def test_the_two_panels_are_fully_independent(monkeypatch, fleet_active, short_frame):
    short, long_ = ov.SHORT_PANEL, ov.LONG_PANEL
    assert not {short.graph_id, short.state_id, short.dropdown_id} & {long_.graph_id, long_.state_id, long_.dropdown_id}
    assert short.chip != long_.chip and short.badge != long_.badge
    a = FrontEnd(monkeypatch, "short", fleet_active, short_frame)
    b = FrontEnd(monkeypatch, "long", fleet_active, short_frame)
    assert len(a.callback_keys) == len(b.callback_keys) == 1            # one callback per panel...
    assert long_.state_id not in a.callback_keys[0] and short.state_id not in b.callback_keys[0]  # ...touching only its own ids
    before = (b.store, list(b.dropdown), dict(b.chips))
    a.badge("Anormal"); a.pick(["U3"])
    assert (b.store, list(b.dropdown), dict(b.chips)) == before         # nothing on the Long View moved
    b.badge("Alerta")
    assert a.dropdown == ["U3"] and a.store["badge"] is None            # and the other way round


def test_a_visible_note_says_the_grouping_is_this_charts_own_state(front):
    text = " ".join(front.texts)
    assert "tarjetas KPI" in text
    assert ("estado propio de esta curva" if front.kind == "long" else "estado propio de esta vista") in text


def test_every_interaction_keeps_dropdown_chips_badges_store_and_chart_in_sync(front):
    g = front.groups
    front.assert_consistent(FLEET)
    front.badge("Anormal"); front.assert_consistent(g["Anormal"])
    front.badge("Alerta"); front.assert_consistent(g["Alerta"])
    front.badge("Alerta"); front.assert_consistent(FLEET)             # restores the pre-badge selection
    front.chip("U1"); front.assert_consistent([u for u in FLEET if u != "U1"])
    front.pick(["U3", "U4"]); front.assert_consistent(["U3", "U4"])
    front.badge("Normal"); front.assert_consistent(g["Normal"])
    front.badge("Normal"); front.assert_consistent(["U3", "U4"])      # back to the manual pick
    front.pick([]); front.assert_consistent([])
    assert not front.figure.data                                      # empty chart, not the fleet
    assert [a.text for a in front.figure.layout.annotations] == ["Selecciona al menos una unidad para verla en el gráfico."]
    front.badge("Alerta"); front.assert_consistent(g["Alerta"])
    front.badge("Alerta"); front.assert_consistent([])


def test_the_reported_dropdown_vs_chart_mismatch_does_not_reproduce(front):
    """Screenshot: dropdown showed only CA-30 while the chart and the CA-36 chip also had CA-36."""
    front.pick(["U6"])
    front.chip("U1")
    front.assert_consistent(["U1", "U6"])
    assert sorted(front.dropdown) == ["U1", "U6"] and front.chips_on == ["U1", "U6"]


def test_an_echo_of_the_unchanged_dropdown_value_is_a_no_op(front):
    out = front.pick(FLEET)
    assert all(o is dash.no_update for o in out)
    front.assert_consistent(FLEET)


def test_counts_headings_and_point_colors_never_move_with_the_selection(front):
    texts, headings, colors = dict(front.badge_text), list(front.group_headings), dict(front.point_colors)
    for action in (lambda: front.badge("Alerta"), lambda: front.chip("U2"), lambda: front.pick(["U5"]), lambda: front.pick([])):
        action()
        assert front.badge_text == texts and front.group_headings == headings
        assert all(colors[u] == c for u, c in front.point_colors.items())


def test_point_colors_are_only_the_three_state_colors(front):
    assert set(front.point_colors.values()) <= set(STATE_COLORS.values())
    for badge, units in front.groups.items():
        assert all(front.point_colors[u] == STATE_COLORS[badge] for u in units)


def test_random_interaction_sequences_never_desynchronize_the_views(front):
    rng = np.random.default_rng(7)
    for _ in range(150):
        kind = rng.choice(["chip", "badge", "pick"])
        if kind == "chip":
            front.chip(str(rng.choice(FLEET)))
        elif kind == "badge":
            front.badge(str(rng.choice(["Anormal", "Alerta", "Normal"])))
        else:
            n = int(rng.integers(0, len(FLEET) + 1))
            front.pick([str(u) for u in rng.choice(FLEET, size=n, replace=False)])
        front.assert_consistent()


def test_fresh_buttons_arriving_with_zero_clicks_change_nothing(front):
    out = front._fire(_prop_id(front.panel.badge, "badge", "Alerta"), 0)
    assert all(o is dash.no_update for o in out)
    front.assert_consistent(FLEET)


# ── Short View panel specifics ───────────────────────────────────────────────

def test_short_view_only_offers_units_it_can_draw(monkeypatch, fleet_active, short_frame):
    front = FrontEnd(monkeypatch, "short", fleet_active, short_frame)
    assert "U7" not in front.dropdown and "U7" not in front.chips and "U7" not in front.chart   # "Sin Datos": no point, no chip
    assert sum(len(t.x) for t in front.figure.data) == 6


def test_short_view_selection_draws_only_those_points_and_fits_the_axes(monkeypatch, fleet_active, short_frame):
    front = FrontEnd(monkeypatch, "short", fleet_active, short_frame)
    front.pick(["U1"])
    [trace] = front.figure.data
    assert list(trace.text) == ["U1"] and list(trace.x) == [5.0] and list(trace.y) == [10.0]
    wide = create_fleet_scatter(short_frame.iloc[:6], None, STATE_COLORS, thresholds=None, axes=("ranking_7d", "ranking_90d"))
    narrow = create_fleet_scatter(short_frame.iloc[:1], None, STATE_COLORS, thresholds=None, axes=("ranking_7d", "ranking_90d"))
    assert narrow.layout.xaxis.range[1] < wide.layout.xaxis.range[1]


def test_short_view_keeps_click_to_evidence_working(monkeypatch, fleet_active, short_frame):
    front = FrontEnd(monkeypatch, "short", fleet_active, short_frame)
    assert front.graph.id == "predictive-fleet-scatter"                    # the id the navigation callback listens to
    front.badge("Anormal")
    assert [c[0] for t in front.figure.data for c in t.customdata] == ["U3", "U6"]   # customdata[0] is still the unit


# ── 2.5:1 frame ──────────────────────────────────────────────────────────────

def test_both_layer_two_charts_sit_in_the_2_5_to_1_frame(monkeypatch, fleet_active):
    monkeypatch.setattr(ov, "load_active_curve", lambda c, comp: fleet_active)
    latest = pd.DataFrame({"Unit": ["U1"], "ranking": [1.0], "avg_ranking_7d": [2.0],
                           "avg_ranking_30d": [3.0], "ranking_acum_90d": [4.0], "status": ["Normal"]})
    graphs = _graphs(ov.render_short_view(latest, "capstone", "motor")) + _graphs(ov.render_long_view("capstone", "motor", FLEET))
    assert len(graphs) == 2
    for graph in graphs:
        assert graph.className == ov.CHART_ASPECT_CLASS and graph.responsive is True
        assert graph.figure.layout.height is None  # the container's 2.5:1 box sets the height
    css = open("dashboard/assets/predictive_styles.css", encoding="utf-8").read()
    assert f".{ov.CHART_ASPECT_CLASS}" in css
    assert "--predictive-chart-ratio: 5 / 2;" in css and "aspect-ratio: var(--predictive-chart-ratio)" in css
    assert 5 / 2 == 2.5 and "3 / 1" not in css


def test_unit_summary_keeps_its_fixed_height_scatter():
    assert create_fleet_scatter(_fleet(), None, STATE_COLORS, thresholds=None, axes=("ranking_7d", "ranking_30d")).layout.height == 380


# ── Short View: 7-day x axis, 90-day y axis (configured, see test_fleet_scatter_axes) ──

def test_short_view_plots_the_7_day_mean_on_x_and_the_90_day_mean_on_y():
    df = _fleet()
    fig = create_fleet_scatter(df, None, STATE_COLORS, thresholds=(50, 50), axes=("ranking_7d", "ranking_90d"))
    xs = sorted(x for t in fig.data for x in t.x)
    ys = sorted(y for t in fig.data for y in t.y)
    assert xs == pytest.approx(sorted(df["avg_ranking_7d"])) and ys == pytest.approx(sorted(df["ranking_acum_90d"]))
    assert fig.layout.xaxis.title.text == "Ranking 7 días" and fig.layout.yaxis.title.text == "Ranking 90 días"
    assert {s.x0 for s in fig.layout.shapes if s.type == "line" and s.x0 == s.x1} == {50}  # thresholds unchanged
    assert {s.y0 for s in fig.layout.shapes if s.type == "line" and s.y0 == s.y1} == {50}


def test_short_view_tooltip_has_today_7d_30d_and_the_component_meter():
    df = _fleet()
    fig = create_fleet_scatter(df, None, STATE_COLORS, thresholds=None, meter_by_unit={"T_00": 1234.0}, axes=("ranking_7d", "ranking_30d"))
    for trace in fig.data:
        template = trace.hovertemplate
        assert "Ranking hoy: %{customdata[1]}" in template and "Ranking 7 días: %{customdata[2]}" in template
        assert "Ranking 30 días: %{customdata[3]}" in template and "Horómetro: %{hovertext}" in template
    today = {c[0]: c[1] for t in fig.data for c in t.customdata}
    assert today["T_00"] == f"{df.loc[0, 'ranking']:.0f}"  # today's ranking: shown, not plotted
    assert {u: h for t in fig.data for u, h in zip(t.text, t.hovertext)}["T_00"] == "1,234 hrs"


def test_seven_day_mean_uses_real_calendar_days_up_to_each_units_last_reading(tmp_path):
    """No 7-day figure is published upstream, so the loader computes it: the mean of the daily
    ranking over the 7 calendar days ending at the unit's own last reading; a day with no
    row is skipped, never counted as zero."""
    days = pd.date_range("2026-09-01", periods=20)
    rows = [{"Unit": "A", "Fecha": d, "ranking": float(i)} for i, d in enumerate(days) if d.day not in (15, 16)]
    rows += [{"Unit": "B", "Fecha": d, "ranking": 100.0} for d in days[:10]]  # stopped reporting on 10 Sep
    csv = tmp_path / "motor.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    stat = csv.stat()
    _, latest, _ = ov._load_component_data_cached(str(csv), "motor", "testclient", stat.st_mtime_ns, stat.st_size)
    mean7 = dict(zip(latest["Unit"], latest["avg_ranking_7d"]))
    # A: last reading 20 Sep; the window is 14-20 Sep and 15/16 have no rows -> days 14, 17, 18, 19, 20
    expected = np.mean([i for i, d in enumerate(days) if d.day in (14, 17, 18, 19, 20)])
    assert mean7["A"] == pytest.approx(expected)
    assert mean7["B"] == pytest.approx(100.0)  # anchored at ITS last reading, not the fleet's
