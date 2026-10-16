"""Predictivo General: Short/Long View submenu, combined KPI state, Component Hour
source, and state-based styling (color, size, labels) of every scatter-style chart."""
import json
import math

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from dash import dcc, html

from dashboard.components import predictive_charts as pc
from dashboard.components.predictive_charts import (
    SCATTER_BASE_MARKER,
    create_fleet_scatter,
    create_long_view_chart,
    place_labels,
)
from dashboard.components.predictive_state import (
    STATE_COLORS,
    STATE_SIZE_FACTOR,
    STATE_ZONE_FILL,
    combine_states,
    normalize_state,
    state_marker_size,
)
from dashboard.tabs import tab_predictive_overview as ov
from src.data import predictive_v2

BANDA = {
    "grid": [0.0, 1000.0, 2000.0, 3000.0],
    "media": [0.0, 100.0, 200.0, 300.0],
    "umbral": [0.0, 200.0, 400.0, 600.0],
}
CONFIG = {"PESO_HORAS": True, "K_SIGMA": 2.0, "K_ALERTA": 1.0}


def _curve_rows(unit, estados, *, vigente=True, ciclo=1, hours_step=500.0, start="2026-08-01"):
    n = len(estados)
    return pd.DataFrame({
        "Unit": unit,
        "Fecha": pd.date_range(start, periods=n),
        "ciclo": ciclo,
        "componentHours_filled": [hours_step * (i + 1) for i in range(n)],
        "ranking_acumulado_ajustado": [50.0 * (i + 1) for i in range(n)],
        "banda_media": [100.0] * n,
        "banda_umbral": [200.0] * n,
        "estado": estados,
        "evaluable": [True] * n,
        "es_vigente": vigente,
    })


def _write_curve(root, client, df, *, week=37, with_metadata=True):
    path = root / "predictive" / "golden" / client / "motor" / "cumulative_risk_curve" / "year=2026" / f"week={week}"
    path.mkdir(parents=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    if with_metadata:
        table = table.replace_schema_metadata({
            **(table.schema.metadata or {}),
            b"config": json.dumps(CONFIG).encode(),
            b"banda": json.dumps(BANDA).encode(),
        })
    pq.write_table(table, path / "part-0.parquet")


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture()
def active():
    """Active-cycle frame as `load_active_cycle_curve` returns it (banda attached)."""
    df = pd.concat([
        _curve_rows("U1", ["Normal", "Normal", "Normal"]),
        _curve_rows("U2", ["Normal", "Alerta", "Alerta"], hours_step=400.0),
        _curve_rows("U3", ["Normal", "Alerta", "Anormal"], hours_step=300.0),
    ], ignore_index=True)
    df.attrs.update({"banda": BANDA, "config": CONFIG})
    return df


# ── Item 8: state vocabulary, size rule ──────────────────────────────────────

def test_marker_size_rule_is_1_5_1_2_1():
    assert STATE_SIZE_FACTOR == {"Normal": 1.0, "Alerta": 1.2, "Anormal": 1.5}
    assert state_marker_size("Anormal", 8) == pytest.approx(12.0)
    assert state_marker_size("alerta", 8) == pytest.approx(9.6)  # either casing
    assert state_marker_size("Normal", 8) == 8
    assert state_marker_size("Sin Datos", 8) == 8 and state_marker_size(None, 8) == 8


@pytest.mark.parametrize("raw,expected", [
    ("normal", "Normal"), ("Alerta ", "Alerta"), ("ANORMAL", "Anormal"),
    ("Sin Datos", None), (None, None), (float("nan"), None), ("", None),
])
def test_normalize_state(raw, expected):
    assert normalize_state(raw) == expected


# ── Item 5: combined state is the worse of the two ───────────────────────────

@pytest.mark.parametrize("short,long,expected", [
    ("normal", "Normal", "Normal"),
    ("normal", "Alerta", "Alerta"),
    ("alerta", "Normal", "Alerta"),
    ("alerta", "Anormal", "Anormal"),
    ("anormal", "Normal", "Anormal"),
    ("normal", "Anormal", "Anormal"),
])
def test_combined_state_is_the_worse_of_short_and_long(short, long, expected):
    assert combine_states(short, long) == expected


@pytest.mark.parametrize("short,long,expected", [
    ("alerta", None, "Alerta"),      # absent from the curve: its short state alone, not Normal
    ("Sin Datos", "Anormal", "Anormal"),
    (None, "Alerta", "Alerta"),
    (None, None, None),
    ("Sin Datos", float("nan"), None),
])
def test_missing_side_contributes_nothing(short, long, expected):
    assert combine_states(short, long) == expected


def test_general_states_do_not_overwrite_either_source(active):
    latest = pd.DataFrame({"Unit": ["U1", "U2", "U3", "U4"],
                           "status": ["Alerta", "Normal", "Normal", "Alerta"]})
    before = latest.copy()
    general = ov.general_states(latest, active)
    # U1 short Alerta/long Normal; U2 Normal/Alerta; U3 Normal/Anormal; U4 (not in curve) Alerta
    assert list(general) == ["Alerta", "Alerta", "Anormal", "Alerta"]
    pd.testing.assert_frame_equal(latest, before)  # `status` is still the short view's own


def test_general_states_without_a_curve_are_the_short_view():
    latest = pd.DataFrame({"Unit": ["A", "B"], "status": ["Anormal", "Sin Datos"]})
    assert list(ov.general_states(latest, None)) == ["Anormal", None]


def test_unit_ids_match_across_zero_padding(active):
    padded = active.assign(Unit=active["Unit"].replace({"U3": "T_09"}))
    padded.attrs.update(active.attrs)
    latest = pd.DataFrame({"Unit": ["T_9"], "status": ["Normal"]})
    assert list(ov.general_states(latest, padded)) == ["Anormal"]
    assert ov.units_missing_from_curve(["T_9", "U1", "ZZ"], padded) == ["ZZ"]


def _kpi_values(page):
    """{label: value} of the KPI cards in a rendered overview."""
    out = {}

    def walk(node):
        if isinstance(node, html.Div) and "kpi-card-enhanced" in (getattr(node, "className", None) or ""):
            inner = node.children.children
            out[inner[1].children] = inner[2].children
        kids = getattr(node, "children", None)
        for kid in kids if isinstance(kids, (list, tuple)) else [kids]:
            if hasattr(kid, "children"):
                walk(kid)

    walk(page)
    return out


def _overview(monkeypatch, status, active):
    units = [f"U{i}" for i in range(1, len(status) + 1)]
    df_latest = pd.DataFrame({
        "Unit": units, "ranking": 10.0, "avg_ranking_7d": 10.0, "avg_ranking_30d": 10.0,
        "avg_ranking_60d": 10.0, "ranking_acum_90d": 10.0, "fm1_30d": 10.0,
    })
    monkeypatch.setattr(ov, "attach_status", lambda latest, c, comp: latest.assign(status=status, _status_rank=0))
    monkeypatch.setattr(ov, "load_active_curve", lambda c, comp: active)
    monkeypatch.setattr(ov, "resolve_failure_modes", lambda comp, c: {"fm1": "Modo Uno"})
    monkeypatch.setattr(ov, "get_model_run_date", lambda *a: None)
    return ov._render_component_overview(df_latest, {}, "motor", "capstone")


def test_kpi_cards_count_the_combined_state(monkeypatch, active):
    # short: U1 Normal, U2 Normal, U3 Normal -> 3 Normal; long adds U2 Alerta, U3 Anormal
    page = _overview(monkeypatch, ["Normal", "Normal", "Normal"], active)
    kpis = _kpi_values(page)
    assert (kpis["Unidades Anormales"], kpis["Unidades en Alerta"], kpis["Unidades Normales"]) == ("1", "1", "1")


def test_kpi_cards_are_the_short_view_when_the_client_has_no_curve(monkeypatch):
    page = _overview(monkeypatch, ["Normal", "Alerta", "Alerta"], None)
    kpis = _kpi_values(page)
    assert (kpis["Unidades Anormales"], kpis["Unidades en Alerta"], kpis["Unidades Normales"]) == ("0", "2", "1")


# ── Items 6 & 7: Component Hour from the curve, one source ───────────────────

def test_component_hours_come_from_the_active_cycle_curve(monkeypatch, active):
    monkeypatch.setattr(ov, "load_active_curve", lambda c, comp: active)
    meter = ov.load_latest_component_meter("capstone", "motor", ["U1", "U2", "U3", "U9"])
    # last point of each curve: U1 3*500, U2 3*400, U3 3*300; U9 has no reading
    assert meter == {"U1": 1500.0, "U2": 1200.0, "U3": 900.0}


def test_no_curve_means_no_component_hours_source(monkeypatch):
    monkeypatch.setattr(ov, "load_active_curve", lambda c, comp: None)
    assert ov.load_latest_component_meter("cda", "transmision", ["U1"]) is None
    latest = ov.attach_component_hours(pd.DataFrame({"Unit": ["U1"]}), None)
    assert latest["component_hours"].isna().all()


def test_table_shows_component_hour_column(active):
    latest = ov.attach_component_hours(pd.DataFrame({
        "Unit": ["U1", "U9"], "status": "Normal", "ranking": 1.0, "avg_ranking_30d": 1.0, "fm1_30d": 1.0,
    }), active)
    table = ov._failure_table(latest, "avg_ranking_30d", "avg_ranking_30d", False, {"fm1": "Modo Uno"})
    thead, tbody = table.children[0].children
    assert "Horas de componente" in str(thead)
    first, second = (row.children[3] for row in tbody.children)  # Unit, ranking, Estado, Component Hour
    assert first.children == "1,500" and second.children == "—"


def test_fleet_scatter_tooltip_hours_use_the_same_source(monkeypatch, active):
    monkeypatch.setattr(ov, "load_active_curve", lambda c, comp: active)
    latest = pd.DataFrame({"Unit": ["U1", "U2"], "ranking": [5.0, 9.0], "avg_ranking_7d": [5.5, 8.5],
                           "avg_ranking_30d": [4.0, 8.0], "status": ["Normal", "Alerta"]})
    fig = ov.make_fleet_scatter(latest, "capstone", "motor", None, STATE_COLORS)
    texts = {u: h for t in fig.data for u, h in zip(t.text, t.hovertext)}
    assert texts == {"U1": "1,500 hrs", "U2": "1,200 hrs"}


# ── Item 2: the active-cycle reader ──────────────────────────────────────────

def test_loader_keeps_metadata_and_only_the_active_cycle(data_root):
    df = pd.concat([
        _curve_rows("U1", ["Normal"] * 4, vigente=False, ciclo=1),
        _curve_rows("U1", ["Normal", "Alerta"], vigente=True, ciclo=2, start="2026-09-01"),
    ], ignore_index=True)
    _write_curve(data_root, "capstone", df)
    active = predictive_v2.load_active_cycle_curve("capstone", "motor")
    assert len(active) == 2 and active["es_vigente"].all() and set(active["ciclo"]) == {2}
    assert active.attrs["banda"] == BANDA and active.attrs["config"] == CONFIG  # not lost like pd.read_parquet


def test_loader_reads_only_the_latest_partition(data_root):
    _write_curve(data_root, "capstone", _curve_rows("OLD", ["Normal"] * 3), week=36)
    _write_curve(data_root, "capstone", _curve_rows("NEW", ["Anormal"] * 3), week=37)
    assert set(predictive_v2.load_active_cycle_curve("capstone", "motor")["Unit"]) == {"NEW"}


def test_loader_is_none_without_table_rows_or_columns(data_root):
    assert predictive_v2.load_active_cycle_curve("cda", "motor") is None  # table not produced
    _write_curve(data_root, "capstone", _curve_rows("U1", ["Normal"] * 2, vigente=False))
    assert predictive_v2.load_active_cycle_curve("capstone", "motor") is None  # nothing active
    _write_curve(data_root, "emin", _curve_rows("U1", ["Normal"]).drop(columns=["ranking_acumulado_ajustado"]))
    assert predictive_v2.load_active_cycle_curve("emin", "motor") is None  # contract columns absent


def test_estado_is_trusted_as_delivered_including_unevaluated_units(data_root):
    df = _curve_rows("U1", ["Normal", "Normal"])
    df["evaluable"] = False
    _write_curve(data_root, "capstone", df)
    active = predictive_v2.load_active_cycle_curve("capstone", "motor")
    assert predictive_v2.active_cycle_estado(active) == {"U1": "Normal"}


def test_last_point_defines_the_unit_state_and_hours(active):
    assert predictive_v2.active_cycle_estado(active) == {"U1": "Normal", "U2": "Alerta", "U3": "Anormal"}
    shuffled = active.sample(frac=1, random_state=3)
    assert predictive_v2.active_cycle_estado(shuffled)["U3"] == "Anormal"


# ── Item 2: the Long View figure ─────────────────────────────────────────────

def _unit_traces(fig):
    return [t for t in fig.data if t.name]


def test_long_view_plots_hours_vs_adjusted_ranking_one_series_per_unit(active):
    fig = create_long_view_chart(active)
    traces = {t.name: t for t in _unit_traces(fig)}
    assert set(traces) == {"U1", "U2", "U3"}
    u3 = traces["U3"]
    assert list(u3.x) == [300.0, 600.0, 900.0]            # componentHours_filled
    assert list(u3.y) == [50.0, 100.0, 150.0]             # ranking_acumulado_ajustado
    assert u3.mode == "lines+markers"                      # scatter + connecting line
    assert fig.layout.xaxis.title.text == "Horas de componente"
    assert fig.layout.yaxis.title.text == "Ranking acumulado ajustado"


def test_long_view_styles_each_unit_by_its_own_estado(active):
    traces = {t.name: t for t in _unit_traces(create_long_view_chart(active))}
    expected = {"U1": "Normal", "U2": "Alerta", "U3": "Anormal"}
    for unit, state in expected.items():
        marker = traces[unit].marker
        assert marker.color == STATE_COLORS[state]
        assert traces[unit].line.color == pc._hex_to_rgba(STATE_COLORS[state], 0.85)  # the line too
        # the current point is the one drawn; earlier rows are line vertices only
        assert list(marker.size)[:-1] == [0] * (len(traces[unit].x) - 1)
        assert list(marker.size)[-1] == pytest.approx(SCATTER_BASE_MARKER * STATE_SIZE_FACTOR[state])


def test_long_view_draw_order_puts_severe_units_on_top(active):
    assert [t.name for t in _unit_traces(create_long_view_chart(active))] == ["U1", "U2", "U3"]
    reordered = active.assign(estado=active["estado"].where(active["Unit"] != "U1", "Anormal"))
    reordered.attrs.update(active.attrs)
    names = [t.name for t in _unit_traces(create_long_view_chart(reordered))]
    assert names[0] == "U2" and set(names[1:]) == {"U1", "U3"}


def test_long_view_labels_each_unit_next_to_its_point_in_gray_without_connectors(active):
    fig = create_long_view_chart(active)
    labels = {a.text: a for a in fig.layout.annotations if a.name == "unit-label"}
    assert set(labels) == {"U1", "U2", "U3"}   # these three sit far apart: all of them fit
    traces = {t.name: t for t in _unit_traces(fig)}
    for unit, annotation in labels.items():
        assert (annotation.x, annotation.y) == (traces[unit].x[-1], traces[unit].y[-1])  # anchored at its point
        assert annotation.font.color == pc.LABEL_COLOR                                    # gray whatever the state
        assert annotation.showarrow is False                                              # never a connector line
    assert not [a for a in fig.layout.annotations if a.showarrow]


def test_long_view_background_is_the_reference_band_independent_of_unit_state(active):
    fig = create_long_view_chart(active)
    zones = [t for t in fig.data if t.fill == "toself"]
    assert len(zones) == 3  # Normal / Alerta / Anormal
    assert {z.fillcolor for z in zones} == set(STATE_ZONE_FILL.values())  # green / yellow / red, nothing else
    zone_text = {a.text for a in fig.layout.annotations if a.name != "unit-label"}
    assert zone_text == {"Normal", "Alerta", "Anormal"}
    # changing every unit's estado leaves the shading untouched
    other = active.assign(estado="Anormal")
    other.attrs.update(active.attrs)
    before = [(list(t.x), list(t.y)) for t in zones]
    after = [(list(t.x), list(t.y)) for t in create_long_view_chart(other).data if t.fill == "toself"]
    assert before == after


def test_long_view_falls_back_to_row_band_when_metadata_is_missing(active):
    bare = active.copy()
    bare.attrs.clear()
    fig = create_long_view_chart(bare)
    assert len([t for t in fig.data if t.fill == "toself"]) == 3


def test_long_view_has_nothing_to_plot_for_empty_data(active):
    assert create_long_view_chart(None) is None
    assert create_long_view_chart(active.iloc[0:0]) is None


# ── Item 3: placeholder when the client has no curve data ────────────────────

def _texts(node):
    found = []

    def walk(n):
        kids = getattr(n, "children", None)
        if isinstance(kids, str):
            found.append(kids)
        for kid in kids if isinstance(kids, (list, tuple)) else [kids]:
            if hasattr(kid, "children"):
                walk(kid)

    walk(node)
    return found


def _graphs(node):
    found = []

    def walk(n):
        if isinstance(n, dcc.Graph):
            found.append(n)
        kids = getattr(n, "children", None)
        for kid in kids if isinstance(kids, (list, tuple)) else [kids]:
            if hasattr(kid, "children") or isinstance(kid, dcc.Graph):
                walk(kid)

    walk(node)
    return found


def test_client_without_curve_data_gets_a_working_on_it_placeholder(monkeypatch):
    monkeypatch.setattr(ov, "load_active_curve", lambda c, comp: None)
    view = ov.render_long_view("cda", "transmision", ["T_11"])
    assert not _graphs(view)
    assert any("trabajando" in text for text in _texts(view))


def test_long_view_renders_graph_and_lists_units_missing_from_the_curve(monkeypatch, active):
    monkeypatch.setattr(ov, "load_active_curve", lambda c, comp: active)
    view = ov.render_long_view("capstone", "motor", ["U1", "U2", "U3", "U7"])
    assert len(_graphs(view)) == 1
    assert any("U7" in text and "1 unidades" in text for text in _texts(view))
    assert not any("sin curva" in text for text in _texts(ov.render_long_view("capstone", "motor", ["U1"])))


def test_a_broken_curve_never_takes_the_tab_down(monkeypatch, active):
    monkeypatch.setattr(ov, "load_active_curve", lambda c, comp: active)
    monkeypatch.setattr(ov, "create_long_view_chart", lambda *a: 1 / 0)
    view = ov.render_long_view("capstone", "motor", ["U1"])
    assert not _graphs(view) and any("No se pudo" in text for text in _texts(view))


def test_overview_exposes_the_two_layer_two_tabs(monkeypatch):
    page = _overview(monkeypatch, ["Normal"], None)
    tabs = []

    def walk(n):
        if isinstance(n, dcc.Tabs):
            tabs.append(n)
        kids = getattr(n, "children", None)
        for kid in kids if isinstance(kids, (list, tuple)) else [kids]:
            if hasattr(kid, "children"):
                walk(kid)

    walk(page)
    layer2 = [t for t in tabs if t.id == ov.LAYER2_TABS_ID]
    assert len(layer2) == 1
    assert [c.value for c in layer2[0].children] == [ov.LAYER2_SHORT, ov.LAYER2_LONG]
    assert [c.label for c in layer2[0].children] == ["Corto Plazo", "Largo Plazo"]
    assert len(_graphs(page)) == 1  # the Short View scatter is rendered up front, the Long View on demand


# ── Item 8: Short View scatter styling ───────────────────────────────────────

def _fleet(n=9):
    states = ["Normal", "Alerta", "Anormal"] * (n // 3)
    return pd.DataFrame({
        "Unit": [f"T_{i:02d}" for i in range(n)],
        "ranking": np.linspace(90, 1, n), "avg_ranking_7d": np.linspace(2, 80, n),
        "avg_ranking_30d": np.linspace(5, 70, n), "status": states,
    })


def test_scatter_points_are_colored_and_sized_by_their_own_state():
    fig = create_fleet_scatter(_fleet(), None, STATE_COLORS, thresholds=(50, 50))
    by_state = {t.name: t for t in fig.data}
    for state in ("Normal", "Alerta", "Anormal"):
        trace = [t for t in fig.data if t.marker.color == STATE_COLORS[state]]
        assert len(trace) == 1
        assert trace[0].marker.size == pytest.approx(SCATTER_BASE_MARKER * STATE_SIZE_FACTOR[state])
    assert len(by_state) == 3


def test_scatter_selected_unit_keeps_its_state_color_and_gets_a_ring():
    fig = create_fleet_scatter(_fleet(), "T_02", STATE_COLORS, thresholds=None)
    selected = fig.data[-1]
    assert list(selected.text) == ["T_02"]
    assert selected.marker.color == STATE_COLORS["Anormal"]          # T_02 is Anormal
    assert selected.marker.line.color == pc.SELECTED_COLOR
    assert selected.marker.size > state_marker_size("Anormal", SCATTER_BASE_MARKER)


def test_scatter_labels_are_gray_in_trace_text_and_never_connector_lines():
    fig = create_fleet_scatter(_fleet(), None, STATE_COLORS, thresholds=(50, 50))
    for trace in fig.data:
        assert len(trace.textposition) == len(trace.x) == len(trace.text) == len(trace.texttemplate)
        assert trace.textfont.color == pc.LABEL_COLOR            # gray, whatever the state
    assert sum(1 for t in fig.data for tmpl in t.texttemplate if tmpl == "%{text}") == 9  # spread out: all fit
    assert not [a for a in fig.layout.annotations if a.name == "unit-label" or a.showarrow]


def test_scatter_selected_unit_label_is_gray_too():
    fig = create_fleet_scatter(_fleet(), "T_02", STATE_COLORS, thresholds=None)
    assert fig.data[-1].textfont.color == pc.LABEL_COLOR
    assert fig.data[-1].texttemplate[0] == "%{text}"            # the selected unit keeps its label


def test_scatter_zones_use_the_state_colors_only():
    fig = create_fleet_scatter(_fleet(), None, STATE_COLORS, thresholds=(50, 50))
    fills = [s.fillcolor for s in fig.layout.shapes if s.type == "rect"]
    assert len(fills) == 4
    assert set(fills) == set(STATE_ZONE_FILL.values())          # red critical, yellow x2, green healthy
    assert fills.count(STATE_ZONE_FILL["Alerta"]) == 2


def test_crowded_scatter_labels_shrink_or_drop_never_a_connector_line():
    rng = np.random.default_rng(0)
    n = 30
    df = pd.DataFrame({
        "Unit": [f"CA-{i:02d}" for i in range(n)],
        "ranking": 10 + rng.normal(0, 0.6, n), "avg_ranking_7d": 10 + rng.normal(0, 0.6, n),
        "avg_ranking_30d": 10 + rng.normal(0, 0.6, n), "status": "Normal",
    })
    fig = create_fleet_scatter(df, None, STATE_COLORS, thresholds=None)
    assert not [a for a in fig.layout.annotations if a.showarrow]      # no line to an offset label
    trace = fig.data[0]
    shown = [tmpl == "%{text}" for tmpl in trace.texttemplate]
    assert any(shown) and not all(shown)                                # some labels drawn, the crowded rest omitted
    assert len(trace.x) == n                                            # but every point is still drawn
    assert list(trace.text) == list(df["Unit"])                         # omitted labels stay for the tooltip / click
    assert {s for s, on in zip(trace.textfont.size, shown) if on} <= {pc.LABEL_FONT_PX, pc.LABEL_FONT_SMALL_PX}


# ── Label placement ──────────────────────────────────────────────────────────

def _boxes(placements, xs, ys, labels, x_range, y_range, px):
    """Label rectangles (plot pixels, y up) of the labels that were placed."""
    out = []
    for p, x, y, label in zip(placements, xs, ys, labels):
        if p is None:
            continue
        ux, uy = pc._TEXT_DIRECTION[p.position]
        sx = px[0] / (x_range[1] - x_range[0])
        sy = px[1] / (y_range[1] - y_range[0])
        out.append(pc._label_box(x * sx + p.dx, y * sy + p.dy, ux, uy, len(label) * p.font_px * 0.6, p.font_px * 1.3))
    return out


def test_an_isolated_label_takes_the_preferred_position_at_the_normal_size():
    [p] = place_labels([50], [50], [8], ["CA-01"], (0, 100), (0, 100), (900, 300))
    assert p.position == "top center" and p.font_px == pc.LABEL_FONT_PX


def test_label_flips_below_when_the_point_is_at_the_top_edge():
    [p] = place_labels([50], [100], [8], ["CA-01"], (0, 100), (0, 100), (900, 300))
    assert p.position.startswith("bottom")


def test_label_distance_follows_the_marker_size():
    small, big = (place_labels([50], [50], [s], ["CA-01"], (0, 100), (0, 100), (900, 300))[0] for s in (8, 12))
    assert big.dy - small.dy == pytest.approx(2.0)  # radius 6 vs 4: the label clears the larger marker


def test_dense_labels_never_overlap_each_other_and_the_rest_are_omitted():
    rng = np.random.default_rng(1)
    n = 25
    xs, ys = rng.normal(50, 1.5, n), rng.normal(50, 1.5, n)
    labels = [f"CA-{i:02d}" for i in range(n)]
    placements = place_labels(xs, ys, [8.0] * n, labels, (0, 100), (0, 100), (900, 300))
    boxes = _boxes(placements, xs, ys, labels, (0, 100), (0, 100), (900, 300))
    assert all(pc._rect_overlap(boxes[i], boxes[j]) == 0 for i in range(len(boxes)) for j in range(i + 1, len(boxes)))
    assert 0 < len(boxes) < n                                    # some drawn, the crowded rest left out
    assert all(p is None or p.font_px in (pc.LABEL_FONT_PX, pc.LABEL_FONT_SMALL_PX) for p in placements)


def test_a_label_that_only_fits_smaller_shrinks_instead_of_being_dropped():
    # One point at plot pixel (500, 200). The blocked areas leave room for a 7px label above it
    # (a 9px one would run into them) and nowhere else.
    blocked = [(0, 217.5, 1000, 400), (0, 0, 1000, 182.5), (0, 0, 470, 400), (530, 0, 1000, 400)]
    [p] = place_labels([50], [50], [8], ["CA-01"], (0, 100), (0, 100), (1000, 400), blocked=blocked)
    assert p is not None and p.position == "top center" and p.font_px == pc.LABEL_FONT_SMALL_PX
    [roomy] = place_labels([50], [50], [8], ["CA-01"], (0, 100), (0, 100), (1000, 400))
    assert roomy.font_px == pc.LABEL_FONT_PX                     # without the blockers it keeps the normal size


def test_a_label_that_fits_nowhere_even_smaller_is_omitted():
    blocked = [(0, 0, 1000, 400)]                                  # the whole plot is taken
    assert place_labels([50], [50], [8], ["CA-01"], (0, 100), (0, 100), (1000, 400), blocked=blocked) == [None]


def test_stacked_points_cannot_all_claim_a_label():
    xs = [50.0, 50.2, 50.4, 50.6]                                  # ~2px apart: markers overlap
    labels = ["CA-01", "CA-02", "CA-03", "CA-04"]
    placements = place_labels(xs, [50] * 4, [8] * 4, labels, (0, 100), (0, 100), (900, 300))
    assert sum(p is not None for p in placements) < 4              # an unattributable label is left out


def test_more_severe_points_place_their_labels_first():
    # ~25px apart: both want "top center" and the two labels would overlap, so whoever is
    # placed first gets it and the other takes another position.
    args = ([50.0, 52.8], [50, 50], [8, 8], ["AAAAA", "BBBBB"], (0, 100), (0, 100), (900, 300))
    low_first = place_labels(*args, priority=[2, 0])
    assert low_first[0].position == "top center" and low_first[1].position != "top center"
    high_first = place_labels(*args, priority=[0, 2])
    assert high_first[1].position == "top center" and high_first[0].position != "top center"


def test_nan_points_are_not_obstacles_and_get_no_label():
    placements = place_labels([np.nan, 10.0], [5.0, np.nan], [8, 8], ["A", "B"], (0, 100), (0, 100), (900, 300))
    assert placements == [None, None]
    assert place_labels([], [], [], [], (0, 1), (0, 1), (900, 300)) == []


def test_degenerate_axis_range_does_not_divide_by_zero():
    placements = place_labels([5.0, 5.0], [5.0, 5.0], [8, 8], ["A", "B"], (5, 5), (5, 5), (900, 300))
    assert len(placements) == 2 and all(p is None or math.isfinite(p.dx) for p in placements)


# ── Evidence banner uses the same single source ──────────────────────────────

def _banner_callback(monkeypatch, active):
    import dash
    from dashboard.callbacks import predictive_callbacks as pcb

    monkeypatch.setattr(ov, "load_active_curve", lambda c, comp: active)
    monkeypatch.setattr(pcb, "_discover_components", lambda client: {})  # no status lookup needed
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    pcb.register_callbacks(app)
    key = next(k for k in app.callback_map if "predictive-ev-unit-banner" in k)
    return app.callback_map[key]["callback"].__wrapped__


def test_evidence_banner_shows_the_same_component_hours_as_the_table(monkeypatch, active):
    banner = _banner_callback(monkeypatch, active)
    text = " ".join(_texts(banner("U2", "capstone", "motor")))
    assert "1,200 hrs" in text and "03 Aug 2026" in text  # U2's last active-cycle point
    assert ov.load_latest_component_meter("capstone", "motor", ["U2"]) == {"U2": 1200.0}


def test_evidence_banner_has_no_hours_without_curve_data(monkeypatch):
    banner = _banner_callback(monkeypatch, None)
    assert "—" in _texts(banner("U2", "cda", "transmision"))
