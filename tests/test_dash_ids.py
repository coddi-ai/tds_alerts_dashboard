"""Data text inside the ids of clickable Dash elements (src/utils/dash_ids.py) and the Oil tabs that use it.

Dash escapes a non-ASCII character of a pattern-matching id on the server but not in the browser, so a click on
an element whose id has an accent ("transmisión" of ENEX) arrived without its value and did nothing. The ids
are now written so that they are ASCII; everything that was ASCII before must stay exactly as it was.
"""

import json
import string

import pytest
from dash._utils import stringify_id
from dash.development.base_component import Component

from src.utils.dash_ids import from_id_text, id_text


def walk(node):
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


def browser_spelling(ident: dict) -> str:
    """How the browser (JSON.stringify) writes an id: non-ASCII characters are kept as they are."""
    return json.dumps(ident, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---- The helper ---------------------------------------------------------------------------------------------

def test_ascii_text_is_left_exactly_as_it_is_so_every_id_that_worked_keeps_its_spelling():
    printable = "".join(chr(code) for code in range(0x20, 0x7F) if chr(code) != "%")
    for text in ("CT_230", "RXLB0001", "motor diesel", "mando final", "T_10", "Camión".encode("ascii", "ignore").decode(), printable):
        assert id_text(text) == text


def test_non_ascii_text_becomes_ascii_and_comes_back_exactly():
    for text in ("transmisión", "sistema hidráulico", "motor de tracción derecho", "dirección y freno", "Índice PQ", "ñandú 100 %",
                 "100%AB", "%25", "a/b?c=d&e", 'quote " and \\ backslash', "tab\tnew\nline", "emoji 🙂", "\x7f"):
        encoded = id_text(text)
        assert encoded.isascii() and all(0x20 <= ord(c) < 0x7F for c in encoded), encoded
        assert from_id_text(encoded) == text


def test_an_encoded_id_is_spelled_the_same_by_dash_and_by_the_browser_which_is_what_broke():
    raw = {"type": "fleet-cell", "unit": "RXLB0001", "component": "transmisión"}
    assert stringify_id(raw) != browser_spelling(raw)                  # the bug: server and browser disagree
    fixed = {**raw, "component": id_text(raw["component"])}
    assert stringify_id(fixed) == browser_spelling(fixed)              # the fix: they agree
    for text in ("sistema hidráulico", 'a "quoted" \\ name', "x\ty", "\x7f", "ñ"):
        ident = {"type": "t", "a": id_text(text)}
        assert stringify_id(ident) == browser_spelling(ident), text


# ---- Visión de Flota ----------------------------------------------------------------------------------------

def _fleet_data():
    cell = lambda status, days: {"s": status, "d": days}
    return {"message": None, "client": None, "columns": ["motor diesel", "transmisión"], "grouped": [], "rows": [
        {"id": "RXLB0001", "machine_status": "Alerta",
         "cells": {"motor diesel": cell("Normal", 4), "transmisión": cell("Alerta", 9)}}]}


def _view(**kw):
    return {"sort": None, "page": 0, "rev": None, "expanded": False, **kw}


def test_fleet_matrix_ids_keep_ascii_names_as_they_were_and_escape_the_accented_one():
    from dashboard.components.oil_fleet_matrix import render_fleet_matrix

    block, _ = render_fleet_matrix(_fleet_data(), _view(), None)
    ids = [b.id for b in walk(block) if type(b).__name__ == "Button" and isinstance(getattr(b, "id", None), dict)]
    cells = {i["component"]: i for i in ids if i["type"] == "fleet-cell"}
    assert cells["motor diesel"] == {"type": "fleet-cell", "unit": "RXLB0001", "component": "motor diesel"}   # unchanged
    assert cells["transmisi%C3%B3n"] == {"type": "fleet-cell", "unit": "RXLB0001", "component": "transmisi%C3%B3n"}
    assert from_id_text("transmisi%C3%B3n") == "transmisión"
    assert {i["unit"] for i in ids if i["type"] in ("fleet-unit", "fleet-select")} == {"RXLB0001"}
    assert all(json.dumps(i, ensure_ascii=False).isascii() for i in ids)            # nothing in an id needs escaping any more


def test_fleet_matrix_sort_headers_of_accented_components_work_the_same_way():
    from dashboard.components.oil_fleet_matrix import render_fleet_matrix

    block, _ = render_fleet_matrix(_fleet_data(), _view(sort={"col": "transmisión", "dir": "desc"}), None)
    cols = {b.id["col"] for b in walk(block) if type(b).__name__ == "Button" and isinstance(b.id, dict) and b.id["type"] == "fleet-sort"}
    assert {"unit_id", "machine_status", "motor diesel", "transmisi%C3%B3n"} == cols
    headers = [th for th in walk(block) if type(th).__name__ == "Th" and th.to_plotly_json()["props"].get("aria-sort") == "descending"]
    assert len(headers) == 1 and "Transmisión" in text_of(headers[0])


# ---- Panel de Frecuencia ----------------------------------------------------------------------------------

def test_frequency_links_keep_ascii_names_as_they_were_and_escape_the_accented_one():
    from dashboard.components.oil_frequency import _component_cells
    from src.data import sampling_frequency as sf

    def link(component):
        row = {"unit_id": "WDZ003", "component": component, "group_days": 30, "last_sample": "2026-11-01", "days_since": 25,
               "interval_pct": 83.3, "due_date": "2026-12-01", "days_to_due": 5, "avg_hist": 20.0, "status": sf.PROXIMA}
        return [b for b in walk(_component_cells(row)) if type(b).__name__ == "Button"][0].id

    assert link("motor diesel") == {"type": "freq-open", "unit": "WDZ003", "component": "motor diesel"}      # unchanged
    assert link("transmisión") == {"type": "freq-open", "unit": "WDZ003", "component": "transmisi%C3%B3n"}


# ---- The shared sort header -------------------------------------------------------------------------------

@pytest.mark.parametrize("table, column, expected", [
    ("fleet", "unit_id", "unit_id"), ("freq", "late", "late"), ("fleet", "motor diesel", "motor diesel"),
    ("fleet", "transmisión", "transmisi%C3%B3n"), ("ca", "essay:Níquel", "essay:N%C3%ADquel")])
def test_sort_buttons_write_ascii_ids_and_leave_ascii_columns_untouched(table, column, expected):
    from dashboard.components.oil_table import sort_button

    button = sort_button(table, column, "label", None)
    assert button.id == {"type": f"{table}-sort", "col": expected}
    assert from_id_text(button.id["col"]) == column
