"""Alertas -> Vista General: tabs, data-source chips, temporal filter, the shared
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
from dashboard.components.source_status import render_source_chips
from dashboard.tabs.tab_alerts import create_layout as create_alerts_shell
from dashboard.tabs.tab_alerts_general import (
    create_active_filters_bar,
    create_layout as create_general_layout,
    default_alert_dates,
)
from src.data.catalog import SourceProbe


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
# 2. Fuentes de datos: one chip per source
# ---------------------------------------------------------------------------

def _probe(source, status, note=""):
    return SourceProbe(client="X", technique="alerts", source=source, status=status, path=None, candidates=(), note=note)


def _chips(rendered):
    return [c for c in _walk(rendered) if "source-chip" in str(getattr(c, "className", "")).split()]


def test_each_data_source_renders_as_its_own_chip():
    rendered = render_source_chips({
        "alerts_consolidated": _probe("alerts_consolidated", "available"),
        "telemetry_alert_detail": _probe("telemetry_alert_detail", "available"),
        "oil_classified": _probe("oil_classified", "available"),
    })
    chips = _chips(rendered)
    assert [chip.to_plotly_json()["props"]["data-source"] for chip in chips] == [
        "alerts_consolidated", "telemetry_alert_detail", "oil_classified",
    ]
    text = str(rendered)
    for label in ("Alertas Consolidadas", "Detalle de Alertas (Telemetría)", "Clasificación de Aceite"):
        assert label in text


def test_an_unavailable_source_is_visually_distinct():
    rendered = render_source_chips({
        "alerts_consolidated": _probe("alerts_consolidated", "available"),
        "oil_classified": _probe("oil_classified", "missing"),
        # A source the catalog could not probe at all is unavailable too, not left out.
        "telemetry_alert_detail": None,
    })
    by_source = {c.to_plotly_json()["props"]["data-source"]: c for c in _chips(rendered)}
    assert set(by_source) == {"alerts_consolidated", "oil_classified", "telemetry_alert_detail"}
    assert "source-chip--available" in by_source["alerts_consolidated"].className
    for unavailable in ("oil_classified", "telemetry_alert_detail"):
        assert "source-chip--missing" in by_source[unavailable].className
        assert "source-chip--available" not in by_source[unavailable].className
        assert "Sin fuente" in str(by_source[unavailable])
        assert "fa-times-circle" in str(by_source[unavailable])


def test_source_banner_no_longer_uses_the_left_border_box():
    assert "borderLeft" not in str(render_source_chips({"oil_classified": _probe("oil_classified", "available")}))


# ---------------------------------------------------------------------------
# 3. Filtro temporal: two independent date inputs
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
# 4. Filtros activos
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


def test_trigger_chip_shows_the_signal_label_not_its_code():
    text = str(create_active_filters_bar({"trigger": "EngCoolTemp"}))
    assert "EngCoolTemp" not in text
    assert FEATURE_NAMES_ES["EngCoolTemp"] in text
    assert "Sin señal registrada" in str(create_active_filters_bar({"trigger": NO_SIGNAL_KEY}))


def _click(monkeypatch, triggered_id, value, current):
    prop = triggered_id if isinstance(triggered_id, str) else str(triggered_id)
    monkeypatch.setattr(callbacks, "callback_context", SimpleNamespace(
        triggered=[{"prop_id": f"{prop}.clickData", "value": value}], triggered_id=triggered_id,
    ))
    return callbacks.update_active_filters(None, None, None, [], [], current)


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
    current = _click(monkeypatch, "alerts-unit-distribution-chart", {"points": [{"customdata": ["CA-80"]}]}, {})
    current = _click(monkeypatch, "alerts-system-distribution-chart", _treemap_click(["system", "Motor"]), current)
    assert current == {"unit": "CA-80", "system": "Motor"}
    assert len(_chip_keys(create_active_filters_bar(current))) == 2


def test_subsystem_cells_and_the_others_bar_filter_nothing(monkeypatch):
    from dash.exceptions import PreventUpdate

    with pytest.raises(PreventUpdate):
        _click(monkeypatch, "alerts-system-distribution-chart", _treemap_click(["", ""]), {})
    with pytest.raises(PreventUpdate):
        _click(monkeypatch, "alerts-unit-distribution-chart", {"points": [{"customdata": [None]}]}, {})


def test_chip_clear_removes_only_its_filter_and_clear_all_removes_everything(monkeypatch):
    current = {"unit": "CA-80", "system": "Motor", "trigger": "imp_lb_psi"}
    chip = {"type": "alerts-general-filter-chip", "key": "system"}
    monkeypatch.setattr(callbacks, "callback_context", SimpleNamespace(
        triggered=[{"prop_id": "chip.n_clicks", "value": 1}], triggered_id=chip,
    ))
    assert callbacks.update_active_filters(None, None, None, [1], [], current) == {"unit": "CA-80", "trigger": "imp_lb_psi"}

    clear_all = {"type": "alerts-general-filter-clear-all", "index": 0}
    monkeypatch.setattr(callbacks, "callback_context", SimpleNamespace(
        triggered=[{"prop_id": "clear.n_clicks", "value": 1}], triggered_id=clear_all,
    ))
    assert callbacks.update_active_filters(None, None, None, [], [1], current) == {}


def test_a_freshly_mounted_chip_is_not_a_click(monkeypatch):
    from dash.exceptions import PreventUpdate

    chip = {"type": "alerts-general-filter-chip", "key": "unit"}
    monkeypatch.setattr(callbacks, "callback_context", SimpleNamespace(
        triggered=[{"prop_id": "chip.n_clicks", "value": 0}], triggered_id=chip,
    ))
    with pytest.raises(PreventUpdate):
        callbacks.update_active_filters(None, None, None, [0], [], {"unit": "CA-80"})


# ---------------------------------------------------------------------------
# 5. The filters themselves: AND across dimensions, and the caption
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
# 6. Distribución por unidad: top N + "Otras (n)"
# ---------------------------------------------------------------------------

def _units(counts):
    rows = [{"UnitId": unit, "sistema": "motor"} for unit, n in counts.items() for _ in range(n)]
    return pd.DataFrame(rows)


def test_more_than_n_units_renders_n_bars_plus_one_others_bar():
    counts = {f"U{i:02d}": 30 - i for i in range(20)}
    fig = create_alerts_per_unit_chart(_units(counts))
    bars = fig.data[0]
    assert len(bars.x) == 13
    assert list(bars.x[:12]) == [f"U{i:02d}" for i in range(12)]
    assert bars.x[12] == "Otras (8)"
    assert bars.y[12] == sum(counts[f"U{i:02d}"] for i in range(12, 20))
    assert bars.marker.color[12] == PARETO_OTHERS_COLOR and bars.marker.color[0] == PARETO_BAR_COLOR
    # Unit bars carry their id for click-to-filter; "Otras" carries none.
    assert [list(c) for c in bars.customdata[:12]] == [[f"U{i:02d}"] for i in range(12)]
    assert list(bars.customdata[12]) == [None]


def test_cumulative_line_spans_every_bar_including_others():
    fig = create_alerts_per_unit_chart(_units({f"U{i:02d}": 30 - i for i in range(20)}))
    cumulative = list(fig.data[1].y)
    assert list(fig.data[1].x) == list(fig.data[0].x)
    assert len(cumulative) == 13
    assert cumulative == sorted(cumulative)
    assert cumulative[-1] == 100


@pytest.mark.parametrize("unit_total", [1, 5, 12])
def test_at_most_n_units_render_without_aggregation(unit_total):
    fig = create_alerts_per_unit_chart(_units({f"U{i:02d}": 5 + i for i in range(unit_total)}))
    assert len(fig.data[0].x) == unit_total
    assert not any(str(x).startswith("Otras") for x in fig.data[0].x)
    assert fig.data[0].marker.color == PARETO_BAR_COLOR


def test_n_is_configurable():
    fig = create_alerts_per_unit_chart(_units({f"U{i:02d}": 10 - i for i in range(8)}), top_n=3)
    assert list(fig.data[0].x) == ["U00", "U01", "U02", "Otras (5)"]


def test_unit_click_resolves_to_the_unit_but_others_does_not():
    assert callbacks._chart_click_filter("alerts-unit-distribution-chart", {"points": [{"customdata": ["U01"]}]}) == ("unit", "U01")
    assert callbacks._chart_click_filter("alerts-unit-distribution-chart", {"points": [{"customdata": [None]}]}) is None


# ---------------------------------------------------------------------------
# 7. Treemap: hover on every cell, labels only where they fit
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
# 8. Listado: selected row and its card
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
