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
    assert text_of(_cell("T_1", "motor", None, None)) == "Sin muestra"


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
    # Only the Normal machines (U3, U4): `motor` is the only one with data left; the empty columns stay
    # (the Componentes filter alone decides which columns exist) and tie alphabetically at the end.
    data = fleet.build_fleet_matrix_data("cda", None, "camion", ["Normal"], None, today="2026-11-23")
    assert data["columns"] == ["motor", "cubo", "freno"]
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


def test_nothing_is_displayed_without_a_fleet_but_the_data_date_is(frequency):
    data = frequency.build_frequency_data("cda")
    assert data["message"] == "frequency.seleccione_una_flota" and data["rows"] == []
    assert data["as_of"] == "2026-11-22"                      # latest reportDate of the client


def test_kpis_groups_and_table_react_to_the_filters(frequency):
    today = date(2026, 11, 23)
    data = frequency.build_frequency_data("cda", None, "camion", today=today)
    assert data["total"] == 80                                 # 40 motor + 1 transmision + 39 "Sin muestra"
    assert data["counts"] == {"solicitar": 40, "sin_muestra": 39, "proxima": 0, "al_dia": 1}
    only_motor = frequency.build_frequency_data("cda", None, "camion", component="motor", today=today)
    assert only_motor["total"] == 40
    overdue_group_a = frequency.build_frequency_data("cda", None, "camion", group="A", status="solicitar", today=today)
    assert overdue_group_a["total"] == 40 and overdue_group_a["groups"][1]["total"] == 0
    assert frequency.build_frequency_data("cda", "Otra", "camion", today=today)["total"] == 0


def test_table_page_two_rows_open_their_own_unit_and_component(frequency):
    data = frequency.build_frequency_data("cda", None, "camion", component="motor", today=date(2026, 11, 23))
    block, note, chip = frequency.render_frequency_table(data, {"sort": None, "page": 1, "rev": "x"})
    ordered = [r["unit_id"] for r in data["rows"]]
    links = [b.id for b in buttons(block) if isinstance(b.id, dict) and b.id["type"] == "freq-open"]
    assert [i["unit"] for i in links] == ordered[30:]
    assert all(i["component"] == "motor" for i in links)
    assert "Ordenado por urgencia" in note and "40 filas" in text_of(chip)


def test_table_columns_and_cells(frequency):
    data = frequency.build_frequency_data("cda", None, "camion", today=date(2026, 11, 23))
    block, _, _ = frequency.render_frequency_table(data, None)
    headers = [text_of(th).replace("↕", "").strip() for th in walk(block) if type(th).__name__ == "Th"
               and getattr(th, "scope", None) == "col"]
    assert headers == ["Unidad", "Componente", "Criticidad", "Última Muestra", "Días Desde Última Muestra",
                       "Intervalo Consumido", "Fecha Límite", "Vencimiento", "Promedio Histórico", "Estado"]
    first = [r for r in walk(block) if type(r).__name__ == "Tr"][1]
    cells = [text_of(c) for c in walk(first) if type(c).__name__ in ("Th", "Td")]
    assert "15 días" in cells and "Solicitar muestra" in cells and any(c.startswith("Vencida hace") for c in cells)


def test_percentage_is_capped_in_the_bar_and_999_plus_in_the_text(frequency):
    assert frequency._percent_text(240.0) == "240 %"
    assert frequency._percent_text(1406.6) == "999+ %"
    assert frequency._percent_text(79.9) == "79 %"
    bar = frequency._bar(1406.6, "solicitar")
    fill = [c for c in walk(bar) if getattr(c, "className", "") == "oil-bar__fill"][0]
    assert fill.style["width"] == "100.0%"


def test_kpi_tiles_show_count_chip_gauge_and_total(frequency):
    data = frequency.build_frequency_data("cda", None, "camion", today=date(2026, 11, 23))
    row = frequency.render_kpis(data)
    tiles = [c for c in walk(row) if type(c).__name__ == "Card"]
    assert len(tiles) == 4
    rendered = text_of(row)
    for expected in ("Vencidas", "Próximas a vencer", "Al día", "Sin historial", "Solicitar muestra", "Atención",
                     "Sin acción", "Revisar", "de 80 componentes"):
        assert expected in rendered
    assert len([c for c in walk(row) if getattr(c, "role", None) == "progressbar"]) == 4


def test_group_card_lists_every_group(frequency):
    data = frequency.build_frequency_data("cda", None, "camion", today=date(2026, 11, 23))
    rendered = text_of(frequency.render_group_card(data))
    for expected in ("Cada 15 días", "Cada 30 días", "Cada 60 días", "de 40 vencidas", "Promedio histórico entre muestras"):
        assert expected in rendered


def test_the_panel_layout_has_the_five_labelled_filters_and_a_footnote():
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
    assert "Intervalo Consumido" in text_of(layout) and "Sin muestra" in text_of(layout)


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
