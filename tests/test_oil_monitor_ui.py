"""Monitor de Aceite UI/UX alignment: severity tiers, fleet matrix (column order, row identity),
Detalle de Reporte, Cumplimiento de Laboratorio and the Panel de Frecuencia tab."""

import re
from datetime import date

import pandas as pd
import pytest
from dash.development.base_component import Component

from shared.severity import SEVERITY_TIERS, STATUS_TIERS, classify_severity


def walk(node):
    """Every component under `node` (and `node`), however it is nested."""
    if isinstance(node, Component):
        yield node
        yield from walk(getattr(node, "children", None))
    elif isinstance(node, (list, tuple)):
        for child in node:
            yield from walk(child)


def text_of(node) -> str:
    parts = []
    for component in walk(node):
        children = getattr(component, "children", None)
        for child in children if isinstance(children, (list, tuple)) else [children]:
            if isinstance(child, (str, int, float)):
                parts.append(str(child))
    return " ".join(parts)


def buttons(node):
    return [c for c in walk(node) if type(c).__name__ == "Button"]


# ---- shared/severity.py -----------------------------------------------------------------------

def test_severity_tiers_and_classifier_are_the_guides():
    assert SEVERITY_TIERS["bajo"]["fill"] == "#16a34a" and SEVERITY_TIERS["alto"]["text"] == "#b91c1c"
    assert [classify_severity(v) for v in (0, 39.9, 40, 69.9, 70, 100)] == [
        "bajo", "bajo", "atencion", "atencion", "alto", "alto"]
    assert classify_severity(85, low_max=80, high_min=100) == "atencion"
    assert STATUS_TIERS["normal"]["bg"] == "#ffffff"
    assert STATUS_TIERS["anormal"]["bg"] == "#c2410c" and STATUS_TIERS["critico"]["bg"] == "#b91c1c"


def test_machine_status_surfaces_follow_the_approved_mapping():
    from dashboard.components.oil_ui import estado_surface

    normal, alerta, anormal = (estado_surface(e) for e in ("Normal", "Alerta", "Anormal"))
    assert normal["background"] == "#ffffff"                       # no solid green for Normal
    assert (alerta["background"], alerta["color"]) == ("#c2410c", "#ffffff")
    assert (anormal["background"], anormal["color"]) == ("#b91c1c", "#ffffff")


def test_banner_background_text_and_badge_come_from_one_status():
    from dashboard.components.oil_ui import status_banner

    for estado, tier in (("Normal", "normal"), ("Alerta", "anormal"), ("Anormal", "critico")):
        banner = status_banner(estado, title="T_1")
        assert banner.style["background"] == STATUS_TIERS[tier]["bg"]
        assert banner.style["color"] == STATUS_TIERS[tier]["text"]
        badge = [c for c in walk(banner) if getattr(c, "className", "") and "status-chip " in c.className + " "][0]
        assert badge.style["background"] == STATUS_TIERS[tier]["badge_bg"]
        assert badge.style["color"] == STATUS_TIERS[tier]["badge_text"]
        assert estado in text_of(banner)                           # the word is always there


def test_component_cells_use_the_severity_tints():
    from dashboard.components.oil_fleet_matrix import _cell

    for estado, tier in (("Normal", "bajo"), ("Alerta", "atencion"), ("Anormal", "alto")):
        cell = _cell("T_1", "motor", {"s": estado, "d": 168}, None)
        button = buttons(cell)[0]
        assert button.children == f"{estado} · 168 d"
        assert button.style["background"] == SEVERITY_TIERS[tier]["bg"]
        assert button.style["color"] == SEVERITY_TIERS[tier]["text"]
    # No sample: a dash that is named "Sin muestra" for assistive technology and is not clickable.
    empty = _cell("T_1", "motor", None, None)
    assert text_of(empty) == "—" and not buttons(empty)
    label = [c for c in walk(empty) if getattr(c, "role", None) == "img"][0]
    assert label.to_plotly_json()["props"]["aria-label"] == "Sin muestra"


def test_estado_maquina_cell_is_white_and_only_its_pill_is_colored():
    from dashboard.components.oil_fleet_matrix import _estado_cell

    expected = {"Normal": ("#dcfce7", "#15803d"), "Alerta": ("#c2410c", "#ffffff"), "Anormal": ("#b91c1c", "#ffffff")}
    for estado, (background, text) in expected.items():
        cell = _estado_cell(estado)
        assert getattr(cell, "style", None) is None                 # no fill on the cell itself
        pill = [c for c in walk(cell) if "status-chip " in (getattr(c, "className", "") or "") + " "][0]
        assert (pill.style["background"], pill.style["color"]) == (background, text)
        assert estado in text_of(cell)                              # the word is always there


# ---- fleet matrix: column order ----------------------------------------------------------------

def _pivot(coverage, units=10):
    """units x components of "Normal", with `coverage[c]` units having data for each component."""
    index = [f"U{i:02d}" for i in range(units)]
    data = {c: ["Normal" if i < n else None for i in range(units)] for c, n in coverage.items()}
    return pd.DataFrame(data, index=index)


def test_components_are_ordered_by_how_many_units_have_data():
    from dashboard.components.oil_fleet_matrix import order_components_by_coverage

    pivot = _pivot({"c": 1, "a": 10, "b": 5})                      # all units, half, about 10 %
    assert order_components_by_coverage(pivot, ["c", "a", "b"]) == ["a", "b", "c"]


def test_equal_coverage_is_broken_alphabetically():
    from dashboard.components.oil_fleet_matrix import order_components_by_coverage

    pivot = _pivot({"zeta": 4, "Alfa": 4, "beta": 4, "full": 9})
    assert order_components_by_coverage(pivot, list(pivot.columns)) == ["full", "Alfa", "beta", "zeta"]


def _classified():
    """Four units; `motor` on all of them, `freno` on two, `cubo` on one."""
    rows = []
    layout = {"U1": {"motor": "Anormal", "freno": "Normal", "cubo": "Normal"},
              "U2": {"motor": "Alerta", "freno": "Normal"},
              "U3": {"motor": "Normal"},
              "U4": {"motor": "Normal"}}
    for unit, components in layout.items():
        for component, status in components.items():
            rows.append({"unitId": unit, "machineName": "camion", "componentName": component, "site": "Mina",
                         "sampleDate": pd.Timestamp("2026-11-10"), "report_status": status,
                         "ai_recommendation": f"{unit} {component}"})
    return pd.DataFrame(rows)


@pytest.fixture
def fleet(monkeypatch):
    from dashboard.components import oil_fleet_matrix as m

    classified = _classified()

    class _Path:
        def exists(self):
            return True

    class _Settings:
        get_classified_reports_path = get_machine_status_path = staticmethod(lambda client: _Path())

    monkeypatch.setattr(m, "get_settings", lambda: _Settings())
    monkeypatch.setattr(m, "load_oil_classified", lambda client: classified.copy())
    monkeypatch.setattr(m, "load_machine_status_for_client", lambda client: pd.DataFrame(
        {"unit_id": ["U1", "U2", "U3", "U4"], "overall_status": ["Anormal", "Alerta", "Normal", "Normal"]}))
    return m


def test_matrix_columns_follow_coverage_and_machine_status_comes_with_each_row(fleet):
    data = fleet.build_fleet_matrix_data("cda", None, "camion", None, None, today="2026-11-23")
    assert data["columns"] == ["motor", "freno", "cubo"]
    assert [r["id"] for r in data["rows"]] == ["U1", "U2", "U3", "U4"]      # worst machine first
    assert data["rows"][0]["cells"]["motor"] == {"s": "Anormal", "d": 13}


def test_filters_recompute_the_column_order(fleet):
    # Only the Normal machines (U3, U4): `motor` is the only component with data left. `cubo` and `freno`
    # have none, which is below the threshold (at least one unit), so they fall into the group, in
    # coverage order (a tie: alphabetical).
    data = fleet.build_fleet_matrix_data("cda", None, "camion", ["Normal"], None, today="2026-11-23")
    assert data["columns"] == ["motor"] and data["grouped"] == ["cubo", "freno"]
    # Only Anormal / Alerta machines (U1, U2): motor 2, freno 2 (alphabetical tie), cubo 1
    data = fleet.build_fleet_matrix_data("cda", None, "camion", ["Anormal", "Alerta"], None, today="2026-11-23")
    assert data["columns"] == ["freno", "motor", "cubo"]


def test_the_components_filter_changes_which_columns_not_their_order(fleet):
    data = fleet.build_fleet_matrix_data("cda", None, "camion", None, ["cubo", "freno"], today="2026-11-23")
    assert data["columns"] == ["freno", "cubo"]


def test_empty_states_carry_a_message_key(fleet):
    assert fleet.build_fleet_matrix_data("cda", None, None, None, None)["message"].startswith("machines_callbacks.")
    assert fleet.build_fleet_matrix_data(None, None, "camion", None, None)["message"] == "fleet_overview.select_client"


# ---- fleet matrix: sorting and row identity ------------------------------------------------------

def _big_data(n_units=70):
    rows = []
    for i in range(n_units):
        status = ("Normal", "Alerta", "Anormal")[i % 3]
        rows.append({"id": f"U{i:03d}", "machine_status": status,
                     "cells": {"motor": {"s": status, "d": i}} if i % 5 else {}})
    return {"rev": "r", "message": None, "client": "cda", "site": None, "fleet": "camion",
            "columns": ["motor"], "rows": rows}


def test_header_cells_and_unit_buttons_carry_the_units_own_id(fleet, monkeypatch):
    monkeypatch.setattr(fleet, "recommendations", lambda data, units: {})
    data = _big_data()
    block, chip = fleet.render_fleet_matrix(data, {"sort": None, "page": 1, "rev": "r"}, None)
    assert "70" in text_of(chip)
    ids = [b.id for b in buttons(block) if isinstance(b.id, dict)]
    cells = [i for i in ids if i["type"] == "fleet-cell"]
    page_2_units = [r["id"] for r in data["rows"]][30:60]
    assert [i["unit"] for i in ids if i["type"] == "fleet-unit"] == page_2_units
    assert {i["unit"] for i in cells} <= set(page_2_units)
    assert all(i["component"] == "motor" for i in cells)
    assert [i["unit"] for i in ids if i["type"] == "fleet-select"] == page_2_units


def test_the_row_clicked_after_sorting_is_the_row_that_opens(fleet, monkeypatch):
    monkeypatch.setattr(fleet, "recommendations", lambda data, units: {})
    data = _big_data()
    view = {"sort": {"col": "unit_id", "dir": "desc"}, "page": 1, "rev": "r"}
    block, _ = fleet.render_fleet_matrix(data, view, None)
    third_row = [r for r in walk(block) if type(r).__name__ == "Tr"][1:][2]
    unit_button = [b for b in buttons(third_row) if b.id["type"] == "fleet-unit"][0]
    expected = sorted((r["id"] for r in data["rows"]), reverse=True)[30:60][2]
    assert unit_button.id["unit"] == expected == unit_button.children


def test_sorting_a_component_column_is_worst_first_with_empty_cells_last(fleet):
    data = _big_data(12)
    ordered = fleet.sort_matrix_rows(data["rows"], {"col": "motor", "dir": "desc"})
    ranks = [fleet.SEVERITY_RANK.get(r["cells"]["motor"]["s"]) if r["cells"] else None for r in ordered]
    present = [r for r in ranks if r is not None]
    assert present == sorted(present, reverse=True)
    assert ranks[len(present):] == [None] * (len(ranks) - len(present))
    asc = fleet.sort_matrix_rows(data["rows"], {"col": "motor", "dir": "asc"})
    assert [r["id"] for r in asc if not r["cells"]] == [r["id"] for r in ordered if not r["cells"]]


def test_estado_maquina_is_the_first_column_after_unidad(fleet, monkeypatch):
    monkeypatch.setattr(fleet, "recommendations", lambda data, units: {})
    block, _ = fleet.render_fleet_matrix(_big_data(5), None, None)
    header = [th for th in walk(block) if type(th).__name__ == "Th"][:4]
    labels = [text_of(th) for th in header]
    assert labels[1].startswith("Unidad") and labels[2].startswith("Estado Máquina") and labels[3].startswith("Motor")


# ---- fleet matrix: "Otros componentes (N)" group and frozen columns -----------------------------------

def test_group_threshold_is_exact_integer_arithmetic():
    from dashboard.components.oil_fleet_matrix import group_threshold

    # ceil(0.20 * 35) is 8 in floating point (7.000000000000001); 20 % of 35 units is exactly 7.
    assert [group_threshold(n) for n in (0, 1, 5, 10, 11, 35, 100)] == [0, 1, 1, 2, 3, 7, 20]


def _grouped_classified():
    """Ten units. `motor` on all, `freno` on half, `borde` on exactly 20 % (keeps its own column), and
    `cubo`, `tapa`, `rueda` on one unit each (below the threshold of 2 units: grouped)."""
    layout = {
        "motor": {f"U{i:02d}": "Anormal" if i == 9 else "Normal" for i in range(10)},
        "freno": {f"U{i:02d}": "Normal" for i in range(5)},
        "borde": {"U05": "Normal", "U06": "Normal"},
        "cubo": {"U00": "Normal"},
        "tapa": {"U00": "Alerta"},
        "rueda": {"U03": "Normal"},
    }
    rows = [{"unitId": unit, "machineName": "camion", "componentName": component, "site": "Mina",
             "sampleDate": pd.Timestamp("2026-11-10"), "report_status": status, "ai_recommendation": ""}
            for component, units in layout.items() for unit, status in units.items()]
    return pd.DataFrame(rows)


@pytest.fixture
def grouped_fleet(fleet, monkeypatch):
    classified = _grouped_classified()
    monkeypatch.setattr(fleet, "load_oil_classified", lambda client: classified.copy())
    monkeypatch.setattr(fleet, "recommendations", lambda data, units: {})
    return fleet


def _group_data(fleet):
    return fleet.build_fleet_matrix_data("cda", None, "camion", None, None, today="2026-11-23")


def _row_of(block, unit):
    for tr in walk(block):
        if type(tr).__name__ == "Tr" and any(
                isinstance(b.id, dict) and b.id.get("type") == "fleet-unit" and b.id["unit"] == unit
                for b in buttons(tr)):
            return tr
    raise AssertionError(f"no row for {unit}")


def _prop(component, name):
    return component.to_plotly_json()["props"].get(name)


def test_components_below_the_threshold_go_to_the_group_in_coverage_order(grouped_fleet):
    data = _group_data(grouped_fleet)
    assert data["columns"] == ["motor", "freno", "borde"]              # 10, 5 and exactly 20 % of the units
    assert data["grouped"] == ["cubo", "rueda", "tapa"]                # 1 unit each: a tie, alphabetical
    assert set(data["rows"][0]["cells"]) <= {"motor", "freno", "borde", "cubo", "rueda", "tapa"}


def test_without_components_below_the_threshold_there_is_no_group(fleet, monkeypatch):
    monkeypatch.setattr(fleet, "recommendations", lambda data, units: {})
    data = fleet.build_fleet_matrix_data("cda", None, "camion", None, None, today="2026-11-23")
    assert data["grouped"] == []
    block, _ = fleet.render_fleet_matrix(data, {"expanded": True}, None)
    assert not [b for b in buttons(block) if isinstance(b.id, dict) and b.id["type"] == "fleet-group"]


def test_group_summary_is_the_worst_status_and_how_many_have_data():
    from dashboard.components.oil_fleet_matrix import group_summary

    cells = {"a": {"s": "Normal", "d": 3}, "b": {"s": "Alerta", "d": 9}, "c": {"s": "Normal", "d": 1}}
    assert group_summary(cells, ["a", "b"]) == ("Alerta", 2)
    assert group_summary(cells, ["a", "c", "z"]) == ("Normal", 2)       # "z" has no data: not counted
    assert group_summary({**cells, "d": {"s": "Anormal", "d": 5}}, ["a", "b", "d"]) == ("Anormal", 3)
    assert group_summary(cells, ["z"]) is None and group_summary({}, []) is None


def test_collapsed_group_is_one_column_with_a_toggle_and_a_summary_per_unit(grouped_fleet):
    data = _group_data(grouped_fleet)
    block, _ = grouped_fleet.render_fleet_matrix(data, {"sort": None, "page": 0, "expanded": False}, None)

    toggles = [b for b in buttons(block) if isinstance(b.id, dict) and b.id["type"] == "fleet-group"]
    assert len(toggles) == 1
    assert _prop(toggles[0], "aria-expanded") == "false"
    assert "Otros componentes (3)" in text_of(toggles[0])
    assert "datos en menos del 20 % de las unidades" in text_of(block)
    # not sortable, and the grouped components have no column of their own
    sorts = [b.id["col"] for b in buttons(block) if isinstance(b.id, dict) and b.id["type"] == "fleet-sort"]
    assert sorts == ["unit_id", "machine_status", "motor", "freno", "borde"]
    assert not [b for b in buttons(block) if isinstance(b.id, dict) and b.id["type"] == "fleet-cell"
                and b.id["component"] in data["grouped"]]
    # the group cell: worst status + components with data; a dash with none; never a button
    for unit, text in (("U00", "Alerta · 2 comp."), ("U03", "Normal · 1 comp."), ("U01", "—")):
        last_cell = [td for td in _row_of(block, unit).children if type(td).__name__ == "Td"][-1]
        assert text_of(last_cell) == text and not buttons(last_cell)


def test_expanding_the_group_swaps_it_for_its_components_under_a_bar(grouped_fleet):
    data = _group_data(grouped_fleet)
    block, _ = grouped_fleet.render_fleet_matrix(data, {"sort": None, "page": 0, "expanded": True}, None)

    header_rows = [c for c in walk(block) if type(c).__name__ == "Thead"][0].children
    assert len(header_rows) == 2
    bar = [th for th in header_rows[0].children if _prop(th, "scope") == "colgroup"][0]
    assert _prop(bar, "colSpan") == 3 and "Otros componentes (3)" in text_of(bar)
    assert _prop(buttons(bar)[0], "aria-expanded") == "true"
    assert all(_prop(th, "rowSpan") == 2 for th in header_rows[0].children if th is not bar)
    second = [b.id["col"] for b in buttons(header_rows[1])]
    assert second == data["grouped"]                                    # coverage order, each sortable
    # the components are ordinary pill cells now, and the summary column is gone
    cells = [b.id["component"] for b in buttons(_row_of(block, "U00")) if b.id["type"] == "fleet-cell"]
    assert cells == ["motor", "freno", "cubo", "tapa"]                  # U00 has no sample for borde / rueda
    assert "comp." not in text_of(block)


def test_the_first_three_columns_are_frozen(grouped_fleet):
    data = _group_data(grouped_fleet)
    block, _ = grouped_fleet.render_fleet_matrix(data, {"sort": None, "page": 0, "expanded": False}, None)
    table = [c for c in walk(block) if type(c).__name__ == "Table"][0]
    assert "oil-table--frozen" in table.className
    header = [c for c in walk(block) if type(c).__name__ == "Tr"][0]
    row = _row_of(block, "U00")
    for line in (header, row):
        first_three = [c for c in line.children if type(c).__name__ in ("Th", "Td")][:3]
        assert [c.className.split()[-1] for c in first_three] == [
            "oil-frozen--select", "oil-frozen--unit", "oil-frozen--estado"]
        assert all("oil-frozen" in c.className.split() for c in first_three)
    # the cell behind the machine's pill is neutral
    assert getattr([c for c in row.children if "oil-frozen--estado" in c.className][0], "style", None) is None


def test_group_state_persists_while_paging_and_sorting_and_closing_drops_a_hidden_sort():
    from dashboard.components.oil_table import initial_view, next_view

    first = {"unit_id": "asc", "*": "desc"}
    assert initial_view()["expanded"] is False                         # starts collapsed
    grouped = ["cubo", "rueda", "tapa"]
    view = next_view(initial_view(), {"kind": "group", "columns": grouped}, total_rows=70, first_dirs=first)
    assert view["expanded"] is True
    view = next_view(view, {"kind": "page", "dir": "next"}, total_rows=70, first_dirs=first)
    view = next_view(view, {"kind": "sort", "col": "motor"}, total_rows=70, first_dirs=first)
    view = next_view(view, {"kind": "data", "rev": "x"}, total_rows=70, first_dirs=first)
    assert view["expanded"] is True and view["sort"]["col"] == "motor"
    # closing keeps the sort on a visible column and the page ...
    paged = {**view, "page": 1}
    closed = next_view(paged, {"kind": "group", "columns": grouped}, total_rows=70, first_dirs=first)
    assert closed["expanded"] is False and closed["sort"] == view["sort"] and closed["page"] == 1
    # ... but drops a sort on a column the closed group no longer shows
    hidden = next_view({**view, "sort": {"col": "tapa", "dir": "desc"}}, {"kind": "group", "columns": grouped},
                       total_rows=70, first_dirs=first)
    assert hidden["expanded"] is False and hidden["sort"] is None


# ---- shared table state (sort / page) -----------------------------------------------------------------

def test_view_state_transitions():
    from dashboard.components.oil_table import initial_view, next_view

    first = {"unit_id": "asc", "*": "desc"}
    view = initial_view()
    view = next_view(view, {"kind": "page", "dir": "next"}, total_rows=70, first_dirs=first)
    view = next_view(view, {"kind": "page", "dir": "next"}, total_rows=70, first_dirs=first)
    assert view["page"] == 2
    assert next_view(view, {"kind": "page", "dir": "next"}, total_rows=70, first_dirs=first)["page"] == 2   # last page
    sorted_view = next_view(view, {"kind": "sort", "col": "motor"}, total_rows=70, first_dirs=first)
    assert sorted_view["sort"] == {"col": "motor", "dir": "desc"} and sorted_view["page"] == 0
    flipped = next_view(sorted_view, {"kind": "sort", "col": "motor"}, total_rows=70, first_dirs=first)
    assert flipped["sort"]["dir"] == "asc"
    assert next_view(sorted_view, {"kind": "sort", "col": "unit_id"}, total_rows=70, first_dirs=first)["sort"]["dir"] == "asc"
    # new data goes back to page 1 but keeps the sort
    fresh = next_view({**sorted_view, "page": 2}, {"kind": "data", "rev": "x"}, total_rows=5, first_dirs=first)
    assert fresh["page"] == 0 and fresh["sort"] == sorted_view["sort"] and fresh["rev"] == "x"


def test_page_size_is_at_most_30():
    from dashboard.components.oil_table import PAGE_SIZE, page_slice

    rows = list(range(100))
    page, index, start = page_slice(rows, {"page": 99})
    assert PAGE_SIZE <= 30 and len(page) <= 30 and index == 3 and start == 90


# ---- Detalle de Reporte -------------------------------------------------------------------------------

def _sample(**extra):
    base = {"unitId": "T_1", "componentName": "motor", "client": "cda", "componentHours": 1234.0,
            "sampleDate": pd.Timestamp("2026-10-01"), "report_status": "Alerta",
            "ai_recommendation": "Diagnóstico: Desgaste alto.\nAcción: Cambiar aceite.\nRevisar filtros."}
    base.update(extra)
    return pd.Series(base)


def test_report_header_is_a_status_banner():
    from dashboard.callbacks.reports_callbacks import create_report_identity_display

    banner = [c for c in walk(create_report_identity_display(_sample())) if "oil-banner" == getattr(c, "className", "")][0]
    assert banner.style["background"] == STATUS_TIERS["anormal"]["bg"]
    quiet = [c for c in walk(create_report_identity_display(_sample(report_status="Normal")))
             if "oil-banner" == getattr(c, "className", "")][0]
    assert quiet.style["background"] == "#ffffff"


def test_ai_actions_are_a_checklist_and_empty_actions_say_so():
    from dashboard.callbacks.reports_callbacks import create_ai_diagnosis_and_action

    box, _ = create_ai_diagnosis_and_action(_sample())
    checklist = [c for c in walk(box) if type(c).__name__ == "Checklist"][0]
    assert [o["label"] for o in checklist.options] == ["Cambiar aceite.", "Revisar filtros."]

    box, _ = create_ai_diagnosis_and_action(_sample(ai_recommendation="Diagnóstico: Todo bien."))
    assert not [c for c in walk(box) if type(c).__name__ == "Checklist"]
    assert "No disponible para este reporte." in text_of(box)


def test_actions_split_by_line_bullet_or_sentence():
    from dashboard.callbacks.reports_callbacks import _split_actions

    assert _split_actions("1. Cambiar aceite\n2) Revisar filtro\n- Tomar muestra") == [
        "Cambiar aceite", "Revisar filtro", "Tomar muestra"]
    assert _split_actions("Cambiar el aceite a 1.5 bar. Revisar el filtro.") == [
        "Cambiar el aceite a 1.5 bar.", "Revisar el filtro."]
    assert _split_actions("") == [] and _split_actions(None) == []


def test_result_summary_has_no_alarm_colored_count():
    from dashboard.callbacks.reports_callbacks import create_decision_summary

    summary = create_decision_summary(_sample(essays_broken=3, breached_essays="[]", oilMeter=10.0), None, "cda", "camion", "motor")
    classes = " ".join(str(getattr(c, "className", "")) for c in walk(summary))
    assert not re.search(r"text-(danger|warning|success)|bg-(danger|warning|success)", classes)


def test_viscosity_label_is_corrected_without_touching_the_data_name():
    from dashboard.callbacks.reports_callbacks import get_essay_options
    from dashboard.components.labels import essay_label

    assert essay_label("Viscocidad") == "Viscosidad" and essay_label("Hierro") == "Hierro"
    options = get_essay_options(pd.DataFrame({"unitId": ["u"], "Viscocidad": [1.0]}))
    assert options == [{"label": "Viscosidad", "value": "Viscocidad"}]


# ---- Cumplimiento de Laboratorio / tabs / copy -----------------------------------------------------------

def test_total_samples_is_a_caption_not_a_tile():
    from dashboard.tabs.tab_lab_compliance import create_lab_compliance_tab

    layout = create_lab_compliance_tab()
    ids = {getattr(c, "id", None) for c in walk(layout)}
    assert "lab-kpi-total-samples" in ids
    assert "Total Muestras" not in text_of(layout)
    tiles = [c for c in walk(layout) if type(c).__name__ == "Card"]
    assert len([t for t in tiles if "kpi-value" in repr(t.to_plotly_json())]) == 2
    caption = [c for c in walk(layout) if getattr(c, "id", None) == "lab-kpi-total-samples"][0]
    assert caption.id == "lab-kpi-total-samples"


def test_tiles_are_neutral_and_have_no_colored_edge():
    from dashboard.components.oil_ui import kpi_tile

    tile = kpi_tile("Tiempo de Tránsito Promedio", "12.3", icon="fa-truck")
    dumped = repr(tile.to_plotly_json())
    assert "border-start" not in dumped and "borderLeft" not in dumped and "h-100" in dumped


def test_the_oil_tabs_and_copy():
    from dashboard.tabs.tab_oil import create_layout

    tabs = [c for c in walk(create_layout()) if type(c).__name__ == "Tab"]
    assert [t.label for t in tabs] == ["Visión de Flota", "Detalle de Reporte", "Cumplimiento de Laboratorio",
                                       "Panel de Frecuencia"]
    assert all("oil-tab" in t.className and "pred-tab--selected" in t.selected_className for t in tabs)


def test_no_oil_module_draws_a_left_border_accent():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "dashboard"
    for name in ("tabs/tab_machines.py", "tabs/tab_reports.py", "tabs/tab_lab_compliance.py", "tabs/tab_frequency.py",
                 "components/oil_ui.py", "components/oil_fleet_matrix.py", "components/oil_frequency.py",
                 "callbacks/machines_callbacks.py", "assets/oil_monitor.css"):
        source = (root / name).read_text(encoding="utf-8")
        assert not re.search(r"border-?[Ll]eft|border-start|border_left", source), name


def test_copy_has_no_abbreviations_or_loud_headers():
    from src.i18n import load_catalog

    es = load_catalog("es")
    assert es["machines_callbacks.estado_maquina"] == "Estado Máquina"
    assert es["tab_lab_compliance.tiempo_de_transito_prom"] == "Tiempo de Tránsito Promedio"
    assert es["tab_oil.cumplimiento_laboratorio"] == es["tab_lab_compliance.cumplimiento_de_laboratorio"]
    assert es["tab_reports.tendencia"] == "Tendencia" and es["tab_reports.ultimo_ensayo"] == "Último Ensayo"


# ---- Panel de Frecuencia tab ---------------------------------------------------------------------------------

def _frequency_classified():
    rows = []
    for i in range(40):                    # 40 units, one overdue motor each: two pages
        rows.append({"unitId": f"U{i:02d}", "machineName": "camion", "componentName": "motor",
                     "componentNameNormalized": "motor", "site": "Mina",
                     "sampleDate": pd.Timestamp("2026-11-23") - pd.Timedelta(days=16 + i),
                     "reportDate": pd.Timestamp("2026-11-20") + pd.Timedelta(days=i % 3),
                     "daysSincePrevious": 14})
    rows.append({"unitId": "U00", "machineName": "camion", "componentName": "transmision",
                 "componentNameNormalized": "transmision", "site": "Mina",
                 "sampleDate": pd.Timestamp("2026-11-20"), "reportDate": pd.Timestamp("2026-11-21"),
                 "daysSincePrevious": 28})
    return pd.DataFrame(rows)


def _sample_row(unit, component, days_ago, normalized=None):
    return {"unitId": unit, "machineName": "camion", "componentName": component,
            "componentNameNormalized": normalized or component, "site": "Mina",
            "sampleDate": pd.Timestamp("2026-11-23") - pd.Timedelta(days=days_ago),
            "reportDate": pd.Timestamp("2026-11-22"), "daysSincePrevious": 20}


@pytest.fixture
def frequency(monkeypatch):
    from dashboard.components import oil_frequency as f

    classified = _frequency_classified()

    class _Path:
        def exists(self):
            return True

    class _Settings:
        get_classified_reports_path = staticmethod(lambda client: _Path())

    monkeypatch.setattr(f, "get_settings", lambda: _Settings())
    monkeypatch.setattr(f, "load_oil_classified", lambda client: classified.copy())
    return f


TODAY = date(2026, 11, 23)


def _unit_bodies(block):
    return [c for c in walk(block) if type(c).__name__ == "Tbody" and getattr(c, "className", "") == "oil-unit"]


def _cells(row):
    """The text of each cell of a table row (not of the tables nested in it)."""
    return [text_of(c) for c in row.children if type(c).__name__ in ("Th", "Td")]


def _unit_row_and_detail(body):
    row, detail = body.children
    return row, detail


def _detail_rows(detail):
    table = [c for c in walk(detail) if type(c).__name__ == "Table"][0]
    tbody = [c for c in table.children if type(c).__name__ == "Tbody"][0]
    return tbody.children


def test_nothing_is_displayed_without_a_fleet_but_the_data_date_is(frequency):
    data = frequency.build_frequency_data("cda")
    assert data["message"] == "frequency.seleccione_una_flota" and data["rows"] == [] and data["units"] == []
    assert data["as_of"] == "2026-11-22"                      # latest reportDate of the client


def test_kpis_groups_and_units_react_to_the_filters(frequency):
    data = frequency.build_frequency_data("cda", None, "camion", today=TODAY)
    assert data["total"] == 80                                 # 40 motor + 1 transmision + 39 "Sin muestra"
    assert data["counts"] == {"solicitar": 40, "sin_muestra": 39, "proxima": 0, "al_dia": 1}
    assert (data["n_units"], data["pending_units"]) == (40, 40)
    only_motor = frequency.build_frequency_data("cda", None, "camion", component="motor", today=TODAY)
    assert (only_motor["total"], only_motor["n_units"]) == (40, 40)
    overdue_group_a = frequency.build_frequency_data("cda", None, "camion", group="A", status="solicitar", today=TODAY)
    assert overdue_group_a["total"] == 40 and overdue_group_a["groups"][1]["total"] == 0
    up_to_date = frequency.build_frequency_data("cda", None, "camion", status="al_dia", today=TODAY)
    assert (up_to_date["n_units"], up_to_date["pending_units"]) == (1, 0)       # only U00's transmision
    assert [u["unit_id"] for u in up_to_date["units"]] == ["U00"] and up_to_date["units"][0]["total"] == 1
    assert frequency.build_frequency_data("cda", "Otra", "camion", today=TODAY)["total"] == 0


def test_units_come_in_default_order_most_overdue_first(frequency):
    data = frequency.build_frequency_data("cda", None, "camion", today=TODAY)
    # one overdue component each, so the oldest sample (U39) leads
    assert [u["unit_id"] for u in data["units"]] == [f"U{i:02d}" for i in range(39, -1, -1)]


def test_the_list_is_one_row_per_unit_with_its_columns(frequency):
    data = frequency.build_frequency_data("cda", None, "camion", today=TODAY)
    block, note, chip = frequency.render_frequency_table(data, None)
    header = [c for c in walk(block) if type(c).__name__ == "Thead"][0]
    headers = [text_of(th).replace("↕", "").strip() for th in walk(header) if type(th).__name__ == "Th"]
    assert headers == ["Detalle", "Unidad", "Estado", "Componentes por Solicitar", "Más Atrasado", "Muestra Más Reciente"]
    bodies = _unit_bodies(block)
    assert len(bodies) == 30                                   # 30 units per page, not 30 components
    row, _ = _unit_row_and_detail(bodies[0])
    unit, estado, pending, late, latest = _cells(row)[1:]
    assert (unit, estado) == ("U39", "Solicitar muestra")
    assert pending.startswith("1 de 2")                        # motor overdue, transmision "Sin muestra"
    assert late == "Motor · vencida hace 40 d"                 # 55 days in a 15-day group
    assert latest == "2026-09-29 · hace 55 d"
    assert "Ordenado por urgencia: más componentes vencidos primero" in note
    assert "40 unidades · 80 componentes" in text_of(chip)


def test_the_acceptance_examples_in_a_units_detail(frequency, monkeypatch):
    classified = pd.DataFrame([
        _sample_row("ACC1", "motor", 36),                                              # 15-day group
        _sample_row("ACC1", "mando final izquierdo", 51, normalized="mando final"),    # 60-day group
        _sample_row("ACC2", "motor", 2), _sample_row("ACC2", "transmision", 3),        # ACC1 lacks transmision
    ])
    monkeypatch.setattr(frequency, "load_oil_classified", lambda client: classified.copy())
    data = frequency.build_frequency_data("cda", None, "camion", today=TODAY)
    block, _, _ = frequency.render_frequency_table(data, None)
    by_unit = {c.children[0].children[1].children: c for c in _unit_bodies(block)}     # unit id -> its <tbody>
    row, detail = _unit_row_and_detail(by_unit["ACC1"])

    assert _cells(row)[1] == "ACC1" and _cells(row)[2] == "Solicitar muestra" and _cells(row)[3].startswith("1 de 3")
    motor, sin_muestra, mando = [_cells(r) for r in _detail_rows(detail)]    # Solicitar, Sin muestra, Próxima
    # Componente, Criticidad, Última Muestra, Días, Intervalo Consumido, Fecha Límite, Vencimiento, Promedio, Estado
    assert motor[:2] == ["Motor", "15 días"] and motor[3] == "36" and "240 %" in motor[4]
    assert motor[6:] == ["Vencida hace 21 d", "20 d", "Solicitar muestra"]
    assert mando[:2] == ["Mando Final Izquierdo", "60 días"] and mando[3] == "51" and "85 %" in mando[4]
    assert mando[6] == "Vence en 9 d" and mando[8] == "Próxima a vencer" and mando[5] == "2026-12-02"
    # a mapped component without a sample: "—" in every calculated column, and it counts in the unit's total
    assert sin_muestra[0] == "Transmisión" and sin_muestra[8] == "Sin muestra"
    assert sin_muestra[2:8] == ["—"] * 6
    # components are ordered Solicitar muestra, then Sin muestra, then Próxima a vencer, then Al día
    assert [c[8] for c in (motor, sin_muestra, mando)] == ["Solicitar muestra", "Sin muestra", "Próxima a vencer"]


def test_a_units_detail_lists_overdue_first_then_sin_muestra_proxima_and_al_dia(frequency, monkeypatch):
    classified = pd.DataFrame([
        _sample_row("T1", "motor", 36), _sample_row("T1", "transmision", 29),                    # 240 % / 97 %
        _sample_row("T1", "mando final", 3),                                                      # al día
        _sample_row("T2", "motor", 1), _sample_row("T2", "transmision", 1),
        _sample_row("T2", "mando final", 1),
    ])
    monkeypatch.setattr(frequency, "load_oil_classified", lambda client: classified.copy())
    data = frequency.build_frequency_data("cda", None, "camion", today=TODAY)
    unit = [u for u in data["units"] if u["unit_id"] == "T1"][0]
    assert (unit["status"], unit["solicitar"], unit["proxima"], unit["al_dia"], unit["sin_muestra"]) == (
        "solicitar", 1, 1, 1, 0)
    ordered = [r["status"] for r in data["rows"] if r["unit_id"] == "T1"]
    assert ordered == ["solicitar", "proxima", "al_dia"]


def test_the_stacked_bar_splits_the_components_by_status_and_says_so_in_words(frequency, monkeypatch):
    classified = pd.DataFrame([
        _sample_row("T1", "motor", 36), _sample_row("T1", "transmision", 29), _sample_row("T1", "mando final", 3),
        _sample_row("T2", "motor", 1), _sample_row("T2", "transmision", 1),
    ])
    monkeypatch.setattr(frequency, "load_oil_classified", lambda client: classified.copy())
    data = frequency.build_frequency_data("cda", None, "camion", today=TODAY)
    unit = [u for u in data["units"] if u["unit_id"] == "T1"][0]
    bar = frequency._stack(unit)
    segments = [c for c in walk(bar) if getattr(c, "className", "") == "oil-stack__segment"]
    assert [s.style["width"] for s in segments] == ["33.33%"] * 3
    assert [s.style["background"] for s in segments] == [
        SEVERITY_TIERS["alto"]["fill"], SEVERITY_TIERS["atencion"]["fill"], SEVERITY_TIERS["bajo"]["fill"]]
    label = "Vencidos: 1 · Próximos a vencer: 1 · Al día: 1 · Sin muestra: 0"
    assert bar.role == "img" and bar.title == label
    assert bar.to_plotly_json()["props"]["aria-label"] == label   # color is never the only signal


def test_expand_buttons_are_real_buttons_that_name_their_unit_and_their_detail(frequency):
    data = frequency.build_frequency_data("cda", None, "camion", today=TODAY)
    block, _, _ = frequency.render_frequency_table(data, None)
    toggles = [b for b in buttons(block) if "data-oil-expand" in b.to_plotly_json()["props"]]
    assert len(toggles) == 30
    props = [b.to_plotly_json()["props"] for b in toggles]
    assert all(p["aria-expanded"] == "false" and p["type"] == "button" for p in props)    # rows start collapsed
    assert props[0]["aria-label"] == "Detalle de U39"
    details = {c.id: c for c in walk(block) if type(c).__name__ == "Tr" and getattr(c, "className", "") == "oil-unit__detail"}
    assert len(details) == 30 and all(d.hidden for d in details.values())
    assert [p["aria-controls"] for p in props] == [
        _unit_row_and_detail(body)[1].id for body in _unit_bodies(block)]                 # each controls its own detail


def test_page_two_opens_its_own_unit_and_component_also_after_sorting(frequency):
    data = frequency.build_frequency_data("cda", None, "camion", component="motor", today=TODAY)
    ordered = [u["unit_id"] for u in data["units"]]
    block, note, chip = frequency.render_frequency_table(data, {"sort": None, "page": 1, "rev": "x"})
    links = [b.id for b in buttons(block) if isinstance(getattr(b, "id", None), dict) and b.id["type"] == "freq-open"]
    assert [i["unit"] for i in links] == ordered[30:]
    assert all(i["component"] == "motor" for i in links)
    # the unit list pages by unit: "Mostrando 31-40 de 40"
    assert "31" in text_of(block) and "40" in text_of(block)

    # re-sorted by Unidad, page 2: the unit and component come from the row, not from its position
    view = {"sort": {"col": "unit_id", "dir": "asc"}, "page": 1, "rev": "x"}
    block, note, _ = frequency.render_frequency_table(data, view)
    links = [b.id for b in buttons(block) if isinstance(getattr(b, "id", None), dict) and b.id["type"] == "freq-open"]
    assert [i["unit"] for i in links] == [f"U{i:02d}" for i in range(30, 40)]
    assert [_cells(_unit_row_and_detail(b)[0])[1] for b in _unit_bodies(block)] == [i["unit"] for i in links]
    assert "Ordenado por Unidad" in note


def test_every_list_column_can_be_re_sorted(frequency):
    data = frequency.build_frequency_data("cda", None, "camion", today=TODAY)
    for col in frequency.FIRST_DIRS:
        for direction in ("asc", "desc"):
            block, _, _ = frequency.render_frequency_table(data, {"sort": {"col": col, "dir": direction}, "page": 0})
            assert len(_unit_bodies(block)) == 30
    sortable = [b.id["col"] for b in buttons(frequency.render_frequency_table(data, None)[0])
                if isinstance(getattr(b, "id", None), dict) and b.id["type"] == "freq-sort"]
    assert sortable == list(frequency.FIRST_DIRS)


def test_percentage_is_capped_in_the_bar_and_999_plus_in_the_text(frequency):
    assert frequency._percent_text(240.0) == "240 %"
    assert frequency._percent_text(1406.6) == "999+ %"
    assert frequency._percent_text(79.9) == "79 %"
    bar = frequency._bar(1406.6, "solicitar")
    fill = [c for c in walk(bar) if getattr(c, "className", "") == "oil-bar__fill"][0]
    assert fill.style["width"] == "100.0%"


def test_kpi_tiles_count_units_then_components(frequency):
    data = frequency.build_frequency_data("cda", None, "camion", today=TODAY)
    row = frequency.render_kpis(data)
    tiles = [c for c in walk(row) if type(c).__name__ == "Card"]
    assert len(tiles) == 5
    labels = [text_of(c) for c in walk(row) if getattr(c, "className", "") == "kpi-label"]
    assert labels == ["Unidades con pendientes", "Componentes vencidos", "Próximos a vencer", "Al día", "Sin historial"]
    values = [text_of(c) for c in walk(row) if getattr(c, "className", "") == "kpi-value"]
    assert values == ["40", "40", "0", "1", "39"]               # units with pending / then components
    chips = [text_of(c) for c in walk(row) if getattr(c, "className", "") == "kpi-chip"]
    assert chips == ["Solicitar muestra", "Solicitar muestra", "Atención", "Sin acción", "Revisar"]
    captions = [text_of(c) for c in walk(row) if getattr(c, "className", "") == "kpi-caption"]
    assert captions == ["de 40 unidades"] + ["de 80 componentes"] * 4
    gauges = [c for c in walk(row) if getattr(c, "role", None) == "progressbar"]
    assert len(gauges) == 5 and gauges[0].to_plotly_json()["props"]["aria-valuenow"] == "100"


def test_criteria_card_lists_every_group(frequency):
    data = frequency.build_frequency_data("cda", None, "camion", today=TODAY)
    rendered = text_of(frequency.render_criteria_card(data))
    for expected in ("Criterios de Criticidad", "Cada 15 días", "Cada 30 días", "Cada 60 días", "de 40 vencidas",
                     "promedio histórico", "Motor", "Intervalo por componente; ajustable con el promedio histórico real "
                     "entre muestras."):
        assert expected in rendered


def test_the_panel_layout_has_the_five_labelled_filters_the_expand_all_button_and_a_footnote():
    from dashboard.tabs.tab_frequency import create_frequency_tab

    layout = create_frequency_tab()
    labels = {c.htmlFor: text_of(c) for c in walk(layout) if type(c).__name__ == "Label"}
    assert labels == {
        "freq-site-filter": "Sitio / Área", "freq-fleet-filter": "Flota (Tipo de Equipo)",
        "freq-component-filter": "Componente", "freq-group-filter": "Criticidad",
        "freq-status-filter": "Estado de Frecuencia"}
    status = [c for c in walk(layout) if getattr(c, "id", None) == "freq-status-filter"][0]
    assert [o["label"] for o in status.options] == [
        "Todos los estados", "Solicitar muestra", "Próxima a vencer", "Al día", "Sin muestra"]
    group = [c for c in walk(layout) if getattr(c, "id", None) == "freq-group-filter"][0]
    assert [o["label"] for o in group.options] == ["Todas", "Cada 15 días", "Cada 30 días", "Cada 60 días"]
    rendered = text_of(layout)
    for expected in ("Componentes por Solicitar", "Intervalo Consumido", "Sin muestra", "Estado de Muestreo por Unidad"):
        assert expected in rendered

    expand_all = [c for c in walk(layout) if getattr(c, "id", None) == "freq-expand-all"][0]
    props = expand_all.to_plotly_json()["props"]
    assert type(expand_all).__name__ == "Button" and props["type"] == "button"
    assert props["data-label-expand"] == "Expandir todas" and props["data-label-collapse"] == "Contraer todas"
    assert props["data-oil-expand-all"] == "freq-table-container"
    assert [c for c in walk(layout) if getattr(c, "id", None) == "freq-table-container"]   # the element it targets


def test_the_expand_script_speaks_the_markup_the_panel_writes():
    import pathlib

    script = (pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "assets" / "oil_expandable_rows.js").read_text(
        encoding="utf-8")
    for attribute in ("data-oil-expand", "data-oil-expand-all", "aria-expanded", "aria-controls",
                      "data-label-expand", "data-label-collapse"):
        assert attribute in script
    assert "Expandir" not in script and "Contraer" not in script            # the words come from the page


def test_every_filter_of_the_oil_tabs_has_a_label_for_it():
    from dashboard.tabs.tab_machines import create_machines_tab
    from dashboard.tabs.tab_reports import create_reports_tab

    for layout in (create_machines_tab(), create_reports_tab()):
        controls = {c.id for c in walk(layout) if type(c).__name__ in ("Dropdown", "DatePickerRange")
                    and isinstance(getattr(c, "id", None), str)
                    and not getattr(c, "style", None) == {"display": "none"}}
        targets = {c.htmlFor for c in walk(layout) if type(c).__name__ == "Label"}
        hidden = {"reports-time-range-selector", "reports-essays-selector"}
        assert controls - hidden <= targets, controls - hidden - targets
