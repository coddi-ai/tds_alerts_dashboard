"""Alertas -> Vista General: tabs, temporal filter, the shared
"Filtros activos" bar, the unit Pareto's progressive disclosure, the treemap's
click-to-filter and the selected-row card.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from dashboard.callbacks import alerts_callbacks as callbacks
from dashboard.components.alerts_charts import (
    FEATURE_NAMES_ES,
    NO_SIGNAL_KEY,
    PARETO_BAR_COLOR,
    PARETO_OTHERS_COLOR,
    create_alerts_per_unit_chart,
    create_system_signal_treemap,
)
from dashboard.components.alerts_report import filter_alert_rows
from dashboard.components.alerts_tables import alerts_report_table_styles, create_alerts_report_table
from dashboard.components.labels import SOURCE_STYLE, source_style
from dashboard.tabs.tab_alerts import create_layout as create_alerts_shell
from dashboard.tabs.tab_alerts_general import (
    create_active_filters_bar,
    create_layout as create_general_layout,
    default_alert_dates,
)


def _walk(component):
    """Every component in a layout tree, depth first."""
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            if hasattr(child, "children") or hasattr(child, "id"):
                yield from _walk(child)
    elif children is not None and (hasattr(children, "children") or hasattr(children, "id")):
        yield from _walk(children)


def _by_id(layout, component_id):
    return next((c for c in _walk(layout) if getattr(c, "id", None) == component_id), None)


# ---------------------------------------------------------------------------
# 1. Vista General / Vista Detallada: the Predictivo tab pattern
# ---------------------------------------------------------------------------

def test_view_tabs_use_the_predictivo_label_width_indicator():
    tabs = _by_id(create_alerts_shell(), "alerts-internal-tabs")
    assert [tab.value for tab in tabs.children] == ["general", "detail"]
    for tab in tabs.children:
        assert "pred-tab" in tab.className.split()
        assert "pred-tab--selected" in tab.selected_className.split()


# ---------------------------------------------------------------------------
# 2. Filtro temporal: two independent date inputs
# ---------------------------------------------------------------------------

def test_desde_and_hasta_are_two_separate_labelled_date_inputs():
    layout = create_general_layout()
    start, end = _by_id(layout, "alerts-date-start"), _by_id(layout, "alerts-date-end")
    assert start is not None and end is not None and start is not end
    assert type(start).__name__ == type(end).__name__ == "DatePickerSingle"
    text = str(layout)
    assert "Desde" in text and "Hasta" in text
    assert _by_id(layout, "alerts-date-range-picker") is None


def test_default_window_is_four_weeks_ending_today():
    start, end = default_alert_dates()
    assert end == date.today().isoformat()
    assert start == (date.today() - timedelta(weeks=4)).isoformat()
    layout = create_general_layout()
    assert (_by_id(layout, "alerts-date-start").date, _by_id(layout, "alerts-date-end").date) == (start, end)


def test_reset_puts_both_fields_back_to_the_rolling_window():
    assert callbacks.clear_date_range(1) == default_alert_dates()


# ---------------------------------------------------------------------------
# 3. Filtros activos
# ---------------------------------------------------------------------------

def _chip_keys(bar):
    return [
        c.id["key"] for c in _walk(bar)
        if isinstance(getattr(c, "id", None), dict) and c.id.get("type") == "alerts-general-filter-chip"
    ]


def test_filters_bar_is_not_rendered_without_filters():
    assert create_active_filters_bar({}) is None
    assert create_active_filters_bar(None) is None
    assert create_active_filters_bar({"unit": None, "system": ""}) is None


def test_one_chip_per_active_filter_each_with_its_own_clear():
    one = create_active_filters_bar({"unit": "CA-80"})
    assert _chip_keys(one) == ["unit"]
    assert "Filtros activos" in str(one) and "Unidad:" in str(one) and "CA-80" in str(one)

    two = create_active_filters_bar({"unit": "CA-80", "system": "Motor", "trigger": "EngCoolTemp"})
    assert _chip_keys(two) == ["unit", "system", "trigger"]
    text = str(two)
    assert "Sistema:" in text and "Motor" in text
    assert "Señal / Trigger:" in text
    assert "Limpiar todo" in text


def _chip_texts(bar):
    return [
        c.children for c in _walk(bar)
        if getattr(c, "className", None) == "alerts-filter-chip__text"
    ]


def test_trigger_chip_shows_the_signal_label_not_its_code():
    (chip,) = _chip_texts(create_active_filters_bar({"trigger": "EngCoolTemp"}))
    assert "EngCoolTemp" not in str(chip)
    assert FEATURE_NAMES_ES["EngCoolTemp"] in str(chip)
    assert "Sin señal registrada" in str(create_active_filters_bar({"trigger": NO_SIGNAL_KEY}))


def test_one_chip_per_selected_unit():
    bar = create_active_filters_bar({"unit": ["CA-1", "CA-2", "CA-3"], "system": "Motor"})
    assert _chip_keys(bar) == ["unit", "unit", "unit", "system"]
    chip_values = [
        c.id["value"] for c in _walk(bar)
        if isinstance(getattr(c, "id", None), dict) and c.id.get("type") == "alerts-general-filter-chip"
    ]
    assert chip_values == ["CA-1", "CA-2", "CA-3", "Motor"]


CATALOG = {
    "units": ["CA-1", "CA-2", "CA-3", "CA-4"],
    "systems": ["Frenos", "Motor"],
    "trigger_systems": {
        "imp_lb_psi": {"Motor": 3, "Frenos": 1},
        "imt_lbf_c": {"Motor": 1},
        "brake_temp": {"Frenos": 2},
    },
}


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    monkeypatch.setattr(callbacks, "_alert_catalog", lambda client: CATALOG)


def _reduce(monkeypatch, triggered_id, value, current, prop="clickData"):
    """Run the filter reducer as Dash would after ``triggered_id`` reported ``value``."""
    monkeypatch.setattr(callbacks, "callback_context", SimpleNamespace(
        triggered=[{"prop_id": f"{triggered_id}.{prop}", "value": value}], triggered_id=triggered_id,
    ))
    controls = {
        "alerts-filter-unit-checklist": None, "alerts-filter-system": None, "alerts-filter-trigger": None,
    }
    if isinstance(triggered_id, str) and triggered_id in controls:
        controls[triggered_id] = value
    return callbacks.update_active_filters(
        None, None, None, [], [],
        controls["alerts-filter-unit-checklist"], None,
        controls["alerts-filter-system"], controls["alerts-filter-trigger"],
        current, "capstone",
    )


def _click(monkeypatch, triggered_id, value, current):
    return _reduce(monkeypatch, triggered_id, value, current)


def _treemap_click(customdata):
    return {"points": [{"customdata": customdata}]}


def test_system_click_applies_and_toggles_a_system_filter(monkeypatch):
    chart = "alerts-system-distribution-chart"
    applied = _click(monkeypatch, chart, _treemap_click(["system", "Motor"]), {})
    assert applied == {"system": "Motor"}
    assert _click(monkeypatch, chart, _treemap_click(["system", "Motor"]), applied) == {}


def test_trigger_click_applies_a_trigger_filter_not_a_system_one(monkeypatch):
    """The regression: every treemap node used to carry only its owning system, so a
    click on a trigger cell toggled the *system* filter and no trigger filter existed."""
    chart = "alerts-system-distribution-chart"
    applied = _click(monkeypatch, chart, _treemap_click(["trigger", "imp_lb_psi"]), {})
    assert applied == {"trigger": "imp_lb_psi"}
    assert "system" not in applied
    # Same toggle as a system click: a second click removes just that filter.
    assert _click(monkeypatch, chart, _treemap_click(["trigger", "imp_lb_psi"]), applied) == {}


def test_trigger_filter_does_not_disturb_an_active_system_filter(monkeypatch):
    chart = "alerts-system-distribution-chart"
    current = {"system": "Motor"}
    applied = _click(monkeypatch, chart, _treemap_click(["trigger", "imp_lb_psi"]), current)
    assert applied == {"system": "Motor", "trigger": "imp_lb_psi"}
    assert _click(monkeypatch, chart, _treemap_click(["trigger", "imp_lb_psi"]), applied) == {"system": "Motor"}


def test_filters_from_different_charts_accumulate(monkeypatch):
    current = _click(monkeypatch, "alerts-unit-distribution-chart", {"points": [{"customdata": ["CA-1"]}]}, {})
    current = _click(monkeypatch, "alerts-system-distribution-chart", _treemap_click(["system", "Motor"]), current)
    assert current == {"unit": ["CA-1"], "system": "Motor"}
    assert len(_chip_keys(create_active_filters_bar(current))) == 2


def test_subsystem_cells_and_the_others_bar_filter_nothing(monkeypatch):
    from dash.exceptions import PreventUpdate

    with pytest.raises(PreventUpdate):
        _click(monkeypatch, "alerts-system-distribution-chart", _treemap_click(["", ""]), {})
    with pytest.raises(PreventUpdate):
        _click(monkeypatch, "alerts-unit-distribution-chart", {"points": [{"customdata": [None]}]}, {})


def test_chip_clear_removes_only_its_filter_and_clear_all_removes_everything(monkeypatch):
    current = {"unit": ["CA-1"], "system": "Motor", "trigger": "imp_lb_psi"}
    chip = {"type": "alerts-general-filter-chip", "key": "system", "value": "Motor"}
    assert _reduce(monkeypatch, chip, 1, current, prop="n_clicks") == {"unit": ["CA-1"], "trigger": "imp_lb_psi"}

    clear_all = {"type": "alerts-general-filter-clear-all", "index": 0}
    assert _reduce(monkeypatch, clear_all, 1, current, prop="n_clicks") == {}


def test_a_unit_chip_removes_only_that_unit(monkeypatch):
    chip = {"type": "alerts-general-filter-chip", "key": "unit", "value": "CA-2"}
    assert _reduce(monkeypatch, chip, 1, {"unit": ["CA-1", "CA-2", "CA-3"]}, prop="n_clicks") == {"unit": ["CA-1", "CA-3"]}
    only = {"type": "alerts-general-filter-chip", "key": "unit", "value": "CA-1"}
    assert _reduce(monkeypatch, only, 1, {"unit": ["CA-1"]}, prop="n_clicks") == {}


def test_a_freshly_mounted_chip_is_not_a_click(monkeypatch):
    from dash.exceptions import PreventUpdate

    chip = {"type": "alerts-general-filter-chip", "key": "unit", "value": "CA-1"}
    with pytest.raises(PreventUpdate):
        _reduce(monkeypatch, chip, 0, {"unit": ["CA-1"]}, prop="n_clicks")


# ---------------------------------------------------------------------------
# 3b. One shared state: the explicit controls and the charts write the same filters
# ---------------------------------------------------------------------------

UNIT_CHART = "alerts-unit-distribution-chart"
UNITS_CONTROL, SYSTEM_CONTROL, TRIGGER_CONTROL = "alerts-filter-unit-checklist", "alerts-filter-system", "alerts-filter-trigger"


def test_unit_clicks_accumulate_and_toggle_individually(monkeypatch):
    def click(unit, current):
        return _click(monkeypatch, UNIT_CHART, {"points": [{"customdata": [unit]}]}, current)

    state = click("CA-3", {})
    state = click("CA-1", state)
    assert state == {"unit": ["CA-1", "CA-3"]}  # roster order, whatever the click order
    assert click("CA-3", state) == {"unit": ["CA-1"]}
    assert click("CA-1", {"unit": ["CA-1"]}) == {}


def test_the_controls_write_the_same_state_the_charts_do(monkeypatch):
    assert _reduce(monkeypatch, UNITS_CONTROL, ["CA-2", "CA-1"], {}, prop="value") == {"unit": ["CA-1", "CA-2"]}
    assert _reduce(monkeypatch, SYSTEM_CONTROL, "Motor", {}, prop="value") == {"system": "Motor"}
    assert _reduce(monkeypatch, TRIGGER_CONTROL, "imt_lbf_c", {"system": "Motor"}, prop="value") == {"system": "Motor", "trigger": "imt_lbf_c"}
    # The same state a treemap click produces.
    assert _click(monkeypatch, "alerts-system-distribution-chart", _treemap_click(["system", "Motor"]), {}) == {"system": "Motor"}


def test_clearing_a_control_removes_its_filter(monkeypatch):
    current = {"unit": ["CA-1"], "system": "Motor", "trigger": "imt_lbf_c"}
    assert _reduce(monkeypatch, UNITS_CONTROL, [], current, prop="value") == {"system": "Motor", "trigger": "imt_lbf_c"}
    assert _reduce(monkeypatch, SYSTEM_CONTROL, None, current, prop="value") == {"unit": ["CA-1"], "trigger": "imt_lbf_c"}
    assert _reduce(monkeypatch, "alerts-filter-unit-clear", 1, current, prop="n_clicks") == {"system": "Motor", "trigger": "imt_lbf_c"}


def test_a_control_echoing_the_state_it_was_given_changes_nothing(monkeypatch):
    from dash.exceptions import PreventUpdate

    current = {"unit": ["CA-1", "CA-2"], "system": "Motor"}
    with pytest.raises(PreventUpdate):
        _reduce(monkeypatch, UNITS_CONTROL, ["CA-1", "CA-2"], current, prop="value")
    with pytest.raises(PreventUpdate):
        _reduce(monkeypatch, SYSTEM_CONTROL, "Motor", current, prop="value")
    with pytest.raises(PreventUpdate):
        _reduce(monkeypatch, TRIGGER_CONTROL, None, current, prop="value")


def test_changing_sistema_drops_a_trigger_that_does_not_belong_to_it(monkeypatch):
    current = {"system": "Motor", "trigger": "imt_lbf_c"}
    assert _reduce(monkeypatch, SYSTEM_CONTROL, "Frenos", current, prop="value") == {"system": "Frenos"}
    # A trigger the new Sistema also has is kept.
    assert _reduce(monkeypatch, SYSTEM_CONTROL, "Frenos", {"system": "Motor", "trigger": "imp_lb_psi"}, prop="value") == {"system": "Frenos", "trigger": "imp_lb_psi"}
    # Setting a Sistema with a Trigger already chosen follows the same rule.
    assert _reduce(monkeypatch, SYSTEM_CONTROL, "Frenos", {"trigger": "imt_lbf_c"}, prop="value") == {"system": "Frenos"}


def test_a_treemap_trigger_under_another_system_replaces_the_system(monkeypatch):
    """The trigger was the last thing chosen, so it wins over a Sistema it is not in."""
    state = _click(monkeypatch, "alerts-system-distribution-chart", _treemap_click(["trigger", "brake_temp"]), {"system": "Motor"})
    assert state == {"trigger": "brake_temp"}


# ---------------------------------------------------------------------------
# 4. The filters themselves: AND across dimensions, and the caption
# ---------------------------------------------------------------------------

def _alerts(rows):
    frame = pd.DataFrame(rows)
    frame["Timestamp"] = pd.to_datetime(frame["Timestamp"])
    frame["has_telemetry"] = True
    frame["has_tribology"] = False
    frame["Trigger_type"] = "Telemetria"
    frame["mensaje_ia"] = ""
    frame["componente"] = "engine"
    frame["FusionID"] = [f"F-{i}" for i in range(len(frame))]
    return frame


def _row(unit, system, signal, when):
    return {"UnitId": unit, "sistema": system, "subsistema": "admission", "Trigger_Var": signal, "Timestamp": when}


@pytest.fixture
def alerts():
    return _alerts([
        _row("CA-1", "motor", "imp_lb_psi", "2026-07-10 16:00"),
        _row("CA-1", "motor", "imt_lbf_c", "2026-07-11 16:00"),
        _row("CA-2", "motor", "imp_lb_psi", "2026-07-12 16:00"),
        _row("CA-2", "frenos", "imp_lb_psi", "2026-07-20 16:00"),
        _row("CA-3", "motor", None, "2026-07-12 16:00"),
    ])


def test_trigger_filter_matches_the_first_signal_and_combines_with_the_others(alerts):
    assert len(filter_alert_rows(alerts, trigger=["imp_lb_psi"])) == 3
    assert len(filter_alert_rows(alerts, trigger=["imp_lb_psi"], system=["Motor"])) == 2
    assert len(filter_alert_rows(alerts, trigger=["imp_lb_psi"], system=["Motor"], unit=["CA-2"])) == 1
    assert len(filter_alert_rows(alerts, trigger=[NO_SIGNAL_KEY])) == 1


def test_trigger_filter_count_equals_the_treemap_cells_of_that_signal(alerts):
    treemap = create_system_signal_treemap(alerts).data[0]
    leaves = [(node[1], count) for node, count in zip(treemap.customdata, treemap.values) if node[0] == "trigger"]
    assert {key for key, _ in leaves} == {"imp_lb_psi", "imt_lbf_c", NO_SIGNAL_KEY}
    for key in {key for key, _ in leaves}:
        assert len(filter_alert_rows(alerts, trigger=[key])) == sum(count for k, count in leaves if k == key)


def test_summary_caption_reflects_the_date_range_and_the_chart_filters_together(monkeypatch, alerts):
    monkeypatch.setattr(callbacks, "load_alerts_data", lambda client: alerts)

    def caption(start, end, active):
        return callbacks.update_general_tab("capstone", start, end, active)[5]

    # Date range alone: the 20th (CA-2, frenos) is outside it.
    assert "Mostrando 4 alertas de 3 unidades" in caption("2026-07-01", "2026-07-15", {})
    # Range + unit + trigger: only CA-2's imp_lb_psi alert on the 12th is left.
    narrowed = caption("2026-07-01", "2026-07-15", {"unit": "CA-2", "trigger": "imp_lb_psi"})
    assert "Mostrando 1 alertas de 1 unidades" in narrowed
    # The same chart filters over a wider range count the 20th as well.
    assert "Mostrando 2 alertas de 1 unidades" in caption("2026-07-01", "2026-07-31", {"unit": "CA-2", "trigger": "imp_lb_psi"})


def test_open_ended_range_when_a_field_is_cleared(monkeypatch, alerts):
    monkeypatch.setattr(callbacks, "load_alerts_data", lambda client: alerts)
    assert "Mostrando 5 alertas" in callbacks.update_general_tab("capstone", None, None, {})[5]


# ---------------------------------------------------------------------------
# 5. Distribución por unidad: bars until a cumulative share + "Otras (n)"
# ---------------------------------------------------------------------------

def _units(counts):
    rows = [{"UnitId": unit, "sistema": "motor"} for unit, n in counts.items() for _ in range(n)]
    return pd.DataFrame(rows)


def test_bars_run_until_the_cumulative_share_then_one_others_bar_folds_the_rest():
    counts = {f"U{i:02d}": 30 - i for i in range(20)}
    fig = create_alerts_per_unit_chart(_units(counts))
    bars = fig.data[0]
    # 80% of 410 alerts is reached by the busiest fourteen units (329 alerts).
    assert len(bars.x) == 15
    assert list(bars.x[:14]) == [f"U{i:02d}" for i in range(14)]
    assert bars.x[14] == "Otras (6)"
    assert bars.y[14] == sum(counts[f"U{i:02d}"] for i in range(14, 20))
    assert bars.marker.color[14] == PARETO_OTHERS_COLOR and bars.marker.color[0] == PARETO_BAR_COLOR
    # The aggregate is hatched and outlined; unit bars are solid.
    assert list(bars.marker.pattern.shape) == [""] * 14 + ["/"]
    assert bars.marker.line.width[14] == 1.5 and bars.marker.line.width[0] == 0
    # Unit bars carry their id for click-to-filter; "Otras" carries none.
    assert [list(c) for c in bars.customdata[:14]] == [[f"U{i:02d}"] for i in range(14)]
    assert list(bars.customdata[14]) == [None]
    assert "14 de 20 unidades concentran el 80% de las alertas." in [a.text for a in fig.layout.annotations]


def test_cumulative_line_spans_every_bar_including_others():
    fig = create_alerts_per_unit_chart(_units({f"U{i:02d}": 30 - i for i in range(20)}))
    cumulative = list(fig.data[1].y)
    assert list(fig.data[1].x) == list(fig.data[0].x)
    assert len(cumulative) == 15
    assert cumulative == sorted(cumulative)
    assert cumulative[-1] == 100


@pytest.mark.parametrize("counts", [{"U00": 7}, {"U00": 79, "U01": 21}, {"U00": 5, "U01": 5}])
def test_units_that_are_all_needed_to_reach_the_share_render_without_aggregation(counts):
    fig = create_alerts_per_unit_chart(_units(counts))
    assert list(fig.data[0].x) == list(counts)
    assert not any(str(x).startswith("Otras") for x in fig.data[0].x)
    assert fig.data[0].marker.color == PARETO_BAR_COLOR


def test_a_flat_fleet_stops_at_the_bar_cap_and_reports_the_share_actually_reached():
    fig = create_alerts_per_unit_chart(_units({f"U{i:02d}": 5 for i in range(40)}))
    assert len(fig.data[0].x) == 16 and fig.data[0].x[-1] == "Otras (25)"
    # 15 of 40 equal units hold 37.5%: the sentence must not claim 80% (nor round up to 38%).
    assert "15 de 40 unidades representan el 37% de las alertas." in [a.text for a in fig.layout.annotations]
    assert fig.data[1].y[-1] == 100


def test_target_and_cap_are_configurable():
    fig = create_alerts_per_unit_chart(_units({f"U{i:02d}": 10 - i for i in range(8)}), target_pct=50, max_bars=3)
    assert list(fig.data[0].x) == ["U00", "U01", "U02", "Otras (5)"]


def test_unit_click_resolves_to_the_unit_but_others_does_not():
    assert callbacks._chart_click_filter("alerts-unit-distribution-chart", {"points": [{"customdata": ["U01"]}]}) == ("unit", "U01")
    assert callbacks._chart_click_filter("alerts-unit-distribution-chart", {"points": [{"customdata": [None]}]}) is None


# ---------------------------------------------------------------------------
# 6. Treemap: hover on every cell, labels only where they fit
# ---------------------------------------------------------------------------

def test_every_treemap_cell_has_a_hover_with_its_full_path_and_count(alerts):
    treemap = create_system_signal_treemap(alerts).data[0]
    assert treemap.hoverinfo == "text"
    assert len(treemap.hovertext) == len(treemap.ids)
    leaf = next(h for h, node in zip(treemap.hovertext, treemap.customdata) if node[0] == "trigger")
    for part in ("Sistema:", "Subsistema:", "Señal / Trigger:", "Alertas:"):
        assert part in leaf
    # A subsystem's hover names its system as well.
    sub = next(h for h, node in zip(treemap.hovertext, treemap.customdata) if node[0] == "" )
    assert "Sistema:" in sub and "Subsistema:" in sub


def test_treemap_hides_labels_that_do_not_fit_instead_of_clipping_them(alerts):
    layout = create_system_signal_treemap(alerts).layout
    assert layout.uniformtext.mode == "hide"
    assert layout.uniformtext.minsize >= 10


def test_treemap_depth_is_not_capped_so_every_leaf_is_drawn(alerts):
    assert create_system_signal_treemap(alerts).data[0].maxdepth == -1


# ---------------------------------------------------------------------------
# 7. Listado: selected row and its card
# ---------------------------------------------------------------------------

def test_selected_row_is_highlighted_by_alert_id_after_the_source_tint():
    styles = alerts_report_table_styles("CAP-123")
    row_rules = [i for i, rule in enumerate(styles) if rule["if"].get("filter_query") == '{id} = "CAP-123"']
    tint_rules = [i for i, rule in enumerate(styles) if "Fuente" in rule["if"].get("filter_query", "") and "backgroundColor" in rule]
    assert len(row_rules) == 1
    assert row_rules[0] > max(tint_rules)
    assert not any("{id}" in rule["if"].get("filter_query", "") for rule in alerts_report_table_styles())


def test_table_rows_carry_the_source_color_the_card_uses(alerts):
    alerts.loc[0, "Trigger_type"] = "Mixto"
    table = create_alerts_report_table(alerts)
    by_label = {row["Fuente"]: row["fuente_color"] for row in table.data}
    for raw in ("Telemetria", "Mixto"):
        label, color = source_style(raw)
        assert by_label[label] == color


def _click_row(rows, index, page_offset=0):
    """active_cell as Dash reports it: ``row`` counts from the top of the current page,
    ``row_id`` is the clicked row's own id."""
    return {"row": index - page_offset, "column": 0, "row_id": rows[index]["id"]}


def test_detail_card_paints_fuente_with_the_chip_color_and_replaces_in_place(alerts):
    alerts.loc[0, "Trigger_type"] = "Mixto"
    table = create_alerts_report_table(alerts)
    rows = table.data

    def card_for(index):
        return callbacks.render_selected_alert_summary(_click_row(rows, index), rows)

    mixto_index = next(i for i, row in enumerate(rows) if row["Fuente"] == source_style("Mixto")[0])
    other_index = next(i for i, row in enumerate(rows) if row["Fuente"] != source_style("Mixto")[0])
    assert source_style("Mixto")[1] in str(card_for(mixto_index))
    other_card = str(card_for(other_index))
    assert source_style("Mixto")[1] not in other_card
    assert source_style("Telemetria")[1] in other_card
    assert str(rows[other_index]["ID"]) in other_card


def test_click_resolves_to_its_own_alert_on_a_later_page_of_the_table(alerts):
    """active_cell["row"] is relative to the visible page; the alert must come from the
    row id, or the card (and "Ver detalle") describe another alert once the table is paged."""
    rows = create_alerts_report_table(alerts).data
    clicked = len(rows) - 1
    active = _click_row(rows, clicked, page_offset=clicked)  # "row" 0 of the last page
    assert active["row"] == 0
    assert str(rows[clicked]["ID"]) in str(callbacks.render_selected_alert_summary(active, rows))
    assert callbacks.store_selected_alert(active, rows) == rows[clicked]["ID"]
    assert callbacks.highlight_selected_alert_row(active) == alerts_report_table_styles(rows[clicked]["id"])


def test_a_cell_without_a_known_row_selects_nothing(alerts):
    from dash.exceptions import PreventUpdate

    rows = create_alerts_report_table(alerts).data
    assert str(callbacks.render_selected_alert_summary(None, rows)) == str(callbacks.html.Div())
    assert str(callbacks.render_selected_alert_summary({"row": 0, "column": 0, "row_id": "nope"}, rows)) == str(callbacks.html.Div())
    with pytest.raises(PreventUpdate):
        callbacks.store_selected_alert(None, rows)


# ---------------------------------------------------------------------------
# 8. Filtros panel: Unidad / Fecha / Sistema / Señal
# ---------------------------------------------------------------------------

def test_filters_panel_sits_above_the_weekly_analysis_with_the_four_criteria():
    layout = create_general_layout()
    for component_id in (
        "alerts-filter-unit-toggle", "alerts-filter-unit-checklist", "alerts-filter-system",
        "alerts-filter-trigger", "alerts-date-start", "alerts-date-end", "alerts-date-range-clear",
    ):
        assert _by_id(layout, component_id) is not None, component_id
    text = str(layout)
    assert text.index("Filtros") < text.index("Análisis semanal de alertas")
    assert "Últimas 4 semanas" in text


def test_date_reset_outputs_only_the_two_date_fields():
    from dash._callback import GLOBAL_CALLBACK_LIST

    (entry,) = [
        c for c in GLOBAL_CALLBACK_LIST
        if c["inputs"] == [{"id": "alerts-date-range-clear", "property": "n_clicks"}]
    ]
    assert entry["output"] == "..alerts-date-start.date...alerts-date-end.date.."


@pytest.mark.parametrize("units, expected", [
    ([], "Todas las unidades"),
    (None, "Todas las unidades"),
    (["CA-80"], "CA-80"),
    (["CA-1", "CA-2"], "2 unidades seleccionadas"),
    (["CA-1", "CA-2", "CA-3"], "3 unidades seleccionadas"),
])
def test_closed_unit_control_summarises_the_selection(units, expected):
    from dashboard.tabs.tab_alerts_general import unit_filter_summary

    assert unit_filter_summary(units) == expected


def test_unit_roster_is_every_unit_not_the_ones_the_pareto_draws():
    from dashboard.components.alerts_report import alert_filter_catalog

    counts = {f"CA-{i}": 30 - i for i in range(1, 21)}
    frame = _units(counts)
    chart = create_alerts_per_unit_chart(frame)
    assert len(chart.data[0].x) == 15  # fourteen units reach 80%, then "Otras"
    catalog = alert_filter_catalog(frame)
    assert catalog["units"] == [f"CA-{i}" for i in range(1, 21)]  # natural order, none folded away


def test_trigger_options_narrow_to_the_system_and_the_full_list_is_grouped():
    from dashboard.tabs.tab_alerts_general import TRIGGER_GROUP_PREFIX, trigger_options

    narrowed = trigger_options(CATALOG["trigger_systems"], "Frenos")
    assert {option["value"] for option in narrowed} == {"imp_lb_psi", "brake_temp"}
    assert not any(option.get("disabled") for option in narrowed)

    full = trigger_options(CATALOG["trigger_systems"], None)
    values = [option["value"] for option in full if not option.get("disabled")]
    assert sorted(values) == sorted(CATALOG["trigger_systems"])  # every trigger, once
    headers = [option["label"] for option in full if option.get("disabled")]
    assert headers == ["Frenos", "Motor"]
    assert all(option["value"].startswith(TRIGGER_GROUP_PREFIX) for option in full if option.get("disabled"))
    # imp_lb_psi fires mostly in Motor, so it is listed there and only there.
    motor_at = next(i for i, option in enumerate(full) if option["label"] == "Motor")
    assert "imp_lb_psi" in [option["value"] for option in full[motor_at + 1:]]


def test_controls_show_the_shared_state_whichever_path_set_it():
    units, unit_value, label, systems, system_value, triggers, trigger_value = callbacks.sync_filter_controls("capstone", {})
    assert [o["value"] for o in units] == CATALOG["units"]
    assert unit_value == [] and label == "Todas las unidades"
    assert [o["value"] for o in systems] == ["Frenos", "Motor"]
    assert system_value is None and trigger_value is None
    assert any(o.get("disabled") for o in triggers)  # grouped while no Sistema is chosen

    *_, label, _, system_value, triggers, trigger_value = callbacks.sync_filter_controls(
        "capstone", {"unit": ["CA-1", "CA-2"], "system": "Motor", "trigger": "imt_lbf_c"},
    )
    assert label == "2 unidades seleccionadas" and system_value == "Motor" and trigger_value == "imt_lbf_c"
    assert {o["value"] for o in triggers} == {"imp_lb_psi", "imt_lbf_c"}


# ---------------------------------------------------------------------------
# 9. Every chart and total follows the filters, keeping its own categories
# ---------------------------------------------------------------------------

def _kpis(stats):
    return [int(str(c.children).replace(",", "")) for c in _walk(stats) if type(c).__name__ == "H2"]


def _general(monkeypatch, alerts, active, start="2026-07-01", end="2026-07-31"):
    monkeypatch.setattr(callbacks, "load_alerts_data", lambda client: alerts)
    return callbacks.update_general_tab("capstone", start, end, active)


def test_totals_table_and_caption_follow_every_filter(monkeypatch, alerts):
    unit_chart, week_chart, treemap, stats, table, caption = _general(monkeypatch, alerts, {})
    assert _kpis(stats) == [5, 3, 0] and len(table.data) == 5 and "Mostrando 5 alertas de 3 unidades" in caption

    for active, total, units in (
        ({"system": "Motor"}, 4, 3),
        ({"unit": ["CA-2"]}, 2, 1),
        ({"unit": ["CA-1", "CA-3"]}, 3, 2),  # OR within Unidad
        ({"trigger": "imp_lb_psi"}, 3, 2),
        ({"unit": ["CA-2"], "system": "Motor"}, 1, 1),  # AND across criteria
        ({"week": "2026-07-06"}, 4, 3),
    ):
        _, _, _, stats, table, caption = _general(monkeypatch, alerts, active)
        assert _kpis(stats)[:2] == [total, units], active
        assert len(table.data) == total, active
        assert f"Mostrando {total} alertas de {units} unidades" in caption, active

    # Clearing everything restores the unfiltered dataset.
    assert _kpis(_general(monkeypatch, alerts, {})[3])[:2] == [5, 3]


def test_a_filter_matching_nothing_zeroes_the_totals(monkeypatch, alerts):
    _, _, _, stats, table, caption = _general(monkeypatch, alerts, {"unit": ["CA-3"], "system": "Frenos"})
    assert _kpis(stats) == [0, 0, 0]
    assert "No hay alertas" in caption


def test_treemap_keeps_every_system_and_marks_the_selected_one(monkeypatch, alerts):
    _, _, treemap, *_ = _general(monkeypatch, alerts, {"system": "Motor"})
    node = treemap.data[0]
    systems = [label for label, cd in zip(node.labels, node.customdata) if cd[0] == "system"]
    assert set(systems) == {"Motor", "Frenos"}  # not collapsed to Motor
    widths = dict(zip(node.ids, node.marker.line.width))
    by_label = dict(zip(node.labels, node.ids))
    assert widths[by_label["Motor"]] > widths[by_label["Frenos"]]
    # The unselected system fades back; the selected one keeps its color.
    colors = dict(zip(node.ids, node.marker.colors))
    assert colors[by_label["Frenos"]] != colors[by_label["Motor"]]


def test_treemap_marks_a_selected_trigger_without_dropping_the_others(monkeypatch, alerts):
    _, _, treemap, *_ = _general(monkeypatch, alerts, {"trigger": "imt_lbf_c"})
    node = treemap.data[0]
    triggers = {cd[1] for cd in node.customdata if cd[0] == "trigger"}
    assert triggers == {"imp_lb_psi", "imt_lbf_c", NO_SIGNAL_KEY}
    outlined = [cd[1] for cd, width in zip(node.customdata, node.marker.line.width) if width > 1 and cd[0] == "trigger"]
    assert outlined == ["imt_lbf_c"]


def test_unit_chart_keeps_every_unit_and_marks_the_selected_ones(monkeypatch, alerts):
    unit_chart, *_ = _general(monkeypatch, alerts, {"unit": ["CA-2"]})
    bars = unit_chart.data[0]
    # The selected unit always keeps its own bar, whatever the cutoff folds away.
    assert "CA-2" in set(bars.x)
    colors = dict(zip(bars.x, bars.marker.color))
    assert colors["CA-2"] == PARETO_BAR_COLOR
    assert all(color != PARETO_BAR_COLOR for unit, color in colors.items() if unit != "CA-2")
    # Other filters still narrow the counts.
    narrowed, *_ = _general(monkeypatch, alerts, {"unit": ["CA-2"], "system": "Frenos"})
    assert list(narrowed.data[0].x) == ["CA-2"]


def test_a_selected_unit_beyond_the_cutoff_is_drawn_on_its_own_bar():
    fig = create_alerts_per_unit_chart(_units({f"U{i:02d}": 30 - i for i in range(20)}), selected_units=["U19"])
    assert "U19" in list(fig.data[0].x)
    assert fig.data[0].x[-1].startswith("Otras")
    assert list(fig.data[0].customdata[list(fig.data[0].x).index("U19")]) == ["U19"]


def test_weekly_chart_keeps_every_week_and_marks_the_selected_one(monkeypatch, alerts):
    _, week_chart, *_ = _general(monkeypatch, alerts, {"week": "2026-07-06"})
    first = week_chart.data[0]
    weeks = [c[0] for c in first.customdata]
    assert "2026-07-06" in weeks and len(set(weeks)) >= 3  # the 6th, 13th and 20th weeks stay on the axis
    opacities = dict(zip(weeks, first.marker.opacity))
    assert opacities["2026-07-06"] == 1.0 and opacities["2026-07-13"] < 1.0

    # Filtering on another dimension thins the bars but not the axis.
    _, filtered_weeks, *_ = _general(monkeypatch, alerts, {"system": "Frenos"})
    assert len(set(filtered_weeks.data[0].x)) == len(set(week_chart.data[0].x))


# ---------------------------------------------------------------------------
# 10. Filter row layout: five sibling cells in one responsive grid row
# ---------------------------------------------------------------------------

def _filter_cells(layout):
    row = next(c for c in _walk(layout) if getattr(c, "className", None) == "alerts-filter-row")
    return row.children


def _cell_label(cell):
    head = cell.children[0]
    return head.children[0].children


def test_filter_row_is_five_sibling_cells_with_no_fecha_group_label():
    layout = create_general_layout()
    cells = _filter_cells(layout)
    assert [_cell_label(cell) for cell in cells] == ["Unidad", "Desde", "Hasta", "Sistema", "Señal / Trigger"]
    assert "Fecha" not in [c.children for c in _walk(layout) if getattr(c, "className", None) == "alerts-filter-field__label"]


def test_date_reset_sits_on_the_hasta_label_line():
    layout = create_general_layout()
    hasta = _filter_cells(layout)[2]
    head = hasta.children[0]
    assert getattr(head.children[1], "id", None) == "alerts-date-range-clear"
    assert "Últimas 4 semanas" in head.children[1].children and "↺" in head.children[1].children
    # The only date control the reset acts on is the pair of date pickers.
    assert _by_id(hasta, "alerts-date-end") is not None


def test_filter_row_css_is_an_auto_fit_grid():
    from pathlib import Path

    css = (Path(callbacks.__file__).parents[1] / "assets" / "alerts_general.css").read_text(encoding="utf-8")
    rule = css[css.index(".alerts-filter-row {"):].split("}")[0]
    assert "display: grid" in rule
    assert "repeat(auto-fit, minmax(190px, 1fr))" in rule
    assert "gap: 16px" in rule
