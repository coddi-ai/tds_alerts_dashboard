"""
Fleet Overview (dashboard/components/fleet_overview.py) - table format.

Covers documentation/general/general_specs/08_fleet_overview_table_format.md
(rows = units, one column per applicable technique, each cell =
`max_risk(label, estado_datos)` with a tooltip generated from that same
evaluation, Oil-table colors, whole-row click-through, Spanish text) on top of
the Confirmed business rules from 00_implementation_guide.md §3.1-3.3 that the
Phase 1 acceptance criteria call out: overall banding (worst-of, Maintenance
excluded), per-client applicability gating, and the ranking tiebreak (count of
Alerta/Anormal techniques, then alphabetical) - verified against a multi-client
dataset with mixed technique availability.

Replaces the card-based assertions of the earlier revisions (04/06), whose
card-specific items 08 supersedes; their data-correctness rules are asserted
here in table form.
"""

import pytest
from dash import dcc, html

import dashboard.components.fleet_overview as fo
from dashboard.callbacks.machines_callbacks import (
    _MACHINE_STATUS_BG,
    _MACHINE_STATUS_FG,
    _STATUS_BG,
    _STATUS_FG,
)


def _patch_all_sources(monkeypatch, *, enabled, alerts=None, telemetry=None, oil=None,
                        maintenance=None, predictive_components=None, predictive=None,
                        freshness=None):
    """Wire every per-technique data source to canned values so
    `build_fleet_overview` can run end-to-end without touching real data
    files. `enabled` gates monitoring-alerts/telemetry/oil/mantenciones via
    is_service_enabled; predictive is gated by `predictive_components`.

    `telemetry`/`oil` take a plain {unit: status} dict (no severity value -
    tests that need one patch `_telemetry_status_map`/`_oil_status_map`
    directly) and `freshness` the {(technique, unit): (label, elapsed)} map
    they share. `alerts`/`predictive` take the full
    ({unit: status}, {unit: value}, freshness_label, freshness_elapsed)
    tuple since freshness is central to what most of these tests assert."""
    monkeypatch.setattr(
        fo, "is_service_enabled",
        lambda client, service_id: enabled.get(service_id, False),
    )
    monkeypatch.setattr(fo, "_alerts_status_map", lambda client: alerts or ({}, {}, "Sin Datos", "N/A"))
    monkeypatch.setattr(fo, "_telemetry_status_map", lambda client: (telemetry or {}, {}))
    monkeypatch.setattr(fo, "_oil_status_map", lambda client: (oil or {}, {}))
    monkeypatch.setattr(fo, "_maintenance_status_map", lambda client: maintenance or ({}, "Sin Datos", "N/A"))
    monkeypatch.setattr(fo, "_enabled_predictive_components", lambda client: predictive_components or [])
    monkeypatch.setattr(fo, "_predictive_status_map", lambda client, components: predictive or ({}, {}, "Sin Datos", "N/A"))
    monkeypatch.setattr(fo, "_telemetry_tribologia_freshness_map", lambda client: freshness or {})


# ── Structural helpers: read the rendered component tree, not its repr ──────

def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        if hasattr(child, "children") or hasattr(child, "_namespace"):
            yield from _walk(child)


def _text(node) -> str:
    if isinstance(node, str):
        return node
    children = getattr(node, "children", None)
    if children is None:
        return ""
    if not isinstance(children, (list, tuple)):
        children = [children]
    return "".join(_text(c) for c in children)


def _tables(result):
    return [n for n in _walk(result) if isinstance(n, html.Table)]


def _header(table) -> list:
    thead = next(c for c in table.children if isinstance(c, html.Thead))
    return [_text(th) for th in thead.children.children]


def _rows(table) -> list:
    tbody = next(c for c in table.children if isinstance(c, html.Tbody))
    return list(tbody.children)


def _cells(row) -> list:
    return list(row.children)


def _row_values(table) -> dict:
    """{unit: [cell text per column after Unidad]}"""
    return {_text(_cells(r)[0]): [_text(c) for c in _cells(r)[1:]] for r in _rows(table)}


def _all_rows(result) -> dict:
    out = {}
    for t in _tables(result):
        out.update(_row_values(t))
    return out


def _link(td) -> dcc.Link:
    return td.children


def _band_titles(result) -> list:
    return [
        _text(n) for n in _walk(result)
        if isinstance(n, html.Span) and "UNIDADES" in _text(n)
    ]


# ---------------------------------------------------------------------------
# 1. max_risk (08, Functional Rules): one shared ranking for label + estado_datos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "label,estado_datos,expected",
    [
        # technique worse than its data -> technique drives
        ("Alerta", "Ok", "Alerta"),
        ("Anormal", "Atención", "Anormal"),
        ("Crítico", "Ok", "Anormal"),  # Alerts' confirmed synonym (§3.1)
        # data worse than a healthy technique -> data drives ("vice versa")
        ("Normal", "Atención", "Alerta"),
        ("Normal", "Preocupante", "Anormal"),
        ("Alerta", "Preocupante", "Anormal"),
        # same level
        ("Normal", "Ok", "Normal"),
        ("Alerta", "Atención", "Alerta"),
        # no reading for the technique: never a healthy-looking cell, whatever the freshness
        ("Sin Datos", "Ok", "Sin Datos"),
        ("Sin Datos", "Preocupante", "Sin Datos"),
        ("Sin Datos", "Sin Datos", "Sin Datos"),
        ("InsufficientData", "Ok", "Sin Datos"),
        # freshness undeterminable: the technique's own label stays in force
        ("Normal", "Sin Datos", "Normal"),
        ("Anormal", "Sin Datos", "Anormal"),
    ],
)
def test_max_risk_value(label, estado_datos, expected):
    assert fo.max_risk(label, estado_datos).value == expected


def test_max_risk_maintenance_is_degraded_by_stale_data_but_never_adds_severity():
    """SANO/DETENIDO is an operational axis (§3.1): it keeps its own wording
    while the data is fresh enough, and stale data can still degrade it."""
    assert fo.max_risk("DETENIDO", "Ok").value == "DETENIDO"
    assert fo.max_risk("SANO", "Ok").value == "SANO"
    assert fo.max_risk("SANO", "Preocupante").value == "Anormal"


def test_max_risk_driver_and_explanation_come_from_the_same_evaluation():
    data_wins = fo.max_risk("Normal", "Preocupante", elapsed="82 días")
    assert data_wins.driver == "data"
    assert "peor que el estado de la técnica (Normal)" in data_wins.explanation
    assert "se muestra Anormal" in data_wins.explanation

    label_wins = fo.max_risk("Alerta", "Ok")
    assert label_wins.driver == "label"
    assert "El estado de la técnica (Alerta) es peor" in label_wins.explanation

    tie = fo.max_risk("Normal", "Ok")
    assert tie.driver == "both"
    assert "coinciden" in tie.explanation

    missing = fo.max_risk("Sin Datos", "Ok")
    assert missing.driver == "none"
    assert "No hay lectura" in missing.explanation


def test_max_risk_tooltip_shows_label_estado_datos_and_explanation():
    cell = fo.max_risk("Normal", "Preocupante", elapsed="82 días", score=None)
    tooltip = cell.tooltip
    assert "Estado de la técnica: Normal" in tooltip
    assert "Estado de los datos: Preocupante (última actualización hace 82 días)" in tooltip
    assert cell.explanation in tooltip


def test_max_risk_tooltip_includes_severity_value_only_while_it_still_explains_the_cell():
    assert "Valor de severidad: 8" in fo.max_risk("Alerta", "Ok", score=8).tooltip
    # Stale data overrides the technique -> its own score no longer explains the cell.
    assert "Valor de severidad" not in fo.max_risk("Alerta", "Preocupante", score=8).tooltip


# ---------------------------------------------------------------------------
# 2. Table structure (08, Required Changes #1-#2, Acceptance: columns)
# ---------------------------------------------------------------------------

def test_table_has_unidad_estado_then_one_column_per_applicable_technique(monkeypatch):
    enabled = {"monitoring-alerts": True, "monitoring-oil": True, "monitoring-mantenciones": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
        oil={"U1": "Normal"},
        maintenance=({"U1": "SANO"}, "Ok", "1 día"),
        freshness={("oil", "U1"): ("Ok", "2 días")},
    )
    tables = _tables(fo.build_fleet_overview("TESTCO"))
    assert len(tables) == 1
    assert _header(tables[0]) == ["Unidad", "Estado", "Alertas", "Tribología", "Mantención"]


def test_disabled_technique_gets_no_column_at_all(monkeypatch):
    """Availability is a client-level property: an inapplicable technique is
    omitted as a column, never shown as a placeholder or default Normal."""
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
    )
    tables = _tables(fo.build_fleet_overview("TESTCO"))
    assert _header(tables[0]) == ["Unidad", "Estado", "Alertas"]


def test_every_unit_has_a_cell_for_every_column_even_without_data(monkeypatch):
    """A unit with no record for an available technique still gets a cell,
    reading Sin Datos through max_risk - never blank or omitted."""
    enabled = {"monitoring-alerts": True, "monitoring-oil": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal", "U2": "Alerta"}, {}, "Ok", "1h"),
        oil={"U1": "Normal"},  # U2 has no oil record
        freshness={("oil", "U1"): ("Ok", "2 días")},
    )
    result = fo.build_fleet_overview("TESTCO")
    for table in _tables(result):
        for row in _rows(table):
            assert len(_cells(row)) == len(_header(table))
    assert _all_rows(result)["U2"] == ["Alerta", "Alerta", "Sin Datos"]


def test_all_text_is_spanish(monkeypatch):
    enabled = {"monitoring-alerts": True, "monitoring-oil": True, "monitoring-mantenciones": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal"}, {}, "Atención", "10 días"),
        oil={"U1": "Normal"},
        maintenance=({"U1": "SANO"}, "Ok", "1 día"),
    )
    result = fo.build_fleet_overview("TESTCO")
    table = _tables(result)[0]
    assert _header(table) == ["Unidad", "Estado", "Alertas", "Tribología", "Mantención"]
    for node in _walk(table):
        title = getattr(node, "title", None)
        if title:
            for english in ("Last update", "Status", "Fresh", "Stale", "because"):
                assert english not in title


# ---------------------------------------------------------------------------
# 3. Cell value, tooltip, color (08, Required Changes #3-#5)
# ---------------------------------------------------------------------------

def test_cell_shows_worse_of_label_and_estado_datos_with_matching_tooltip(monkeypatch):
    """Technique Normal + stale data -> the cell reflects the worse state, and
    the tooltip names both inputs plus the rule that decided it."""
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"U1": "Normal"}, {}, "Preocupante", "25 días"),
    )
    table = _tables(fo.build_fleet_overview("TESTCO"))[0]
    cell = _cells(_rows(table)[0])[2]
    assert _text(cell) == "Anormal"
    tooltip = _link(cell).title
    assert "Estado de la técnica: Normal" in tooltip
    assert "Estado de los datos: Preocupante (última actualización hace 25 días)" in tooltip
    assert "peor que el estado de la técnica (Normal)" in tooltip


def test_technique_worse_than_its_data_drives_the_cell(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"U1": "Anormal"}, {}, "Ok", "1h"),
    )
    cell = _cells(_rows(_tables(fo.build_fleet_overview("TESTCO"))[0])[0])[2]
    assert _text(cell) == "Anormal"
    assert "El estado de la técnica (Anormal) es peor" in _link(cell).title


def test_cell_colors_reuse_the_monitoring_oil_table_scheme(monkeypatch):
    enabled = {"monitoring-alerts": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"A": "Normal", "B": "Alerta", "C": "Anormal"}, {}, "Ok", "1h"),
    )
    result = fo.build_fleet_overview("TESTCO")
    rows = {}
    for t in _tables(result):
        for r in _rows(t):
            rows[_text(_cells(r)[0])] = r
    for unit, status in (("A", "Normal"), ("B", "Alerta"), ("C", "Anormal")):
        technique_cell = _cells(rows[unit])[2]
        assert technique_cell.style["backgroundColor"] == _STATUS_BG[status]
        assert technique_cell.style["color"] == _STATUS_FG[status]
        estado_cell = _cells(rows[unit])[1]
        assert estado_cell.style["backgroundColor"] == _MACHINE_STATUS_BG[status]
        assert estado_cell.style["color"] == _MACHINE_STATUS_FG[status]


def test_whole_row_links_to_the_unit_summary(monkeypatch):
    """Clicking a unit's row - any of its cells - opens that unit's Unit
    Summary: every cell's content is a link to the same href."""
    enabled = {"monitoring-alerts": True, "monitoring-oil": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
        oil={"U1": "Normal"},
        freshness={("oil", "U1"): ("Ok", "2 días")},
    )
    row = _rows(_tables(fo.build_fleet_overview("TESTCO"))[0])[0]
    hrefs = {_link(td).href for td in _cells(row)}
    assert len(hrefs) == 1
    assert next(iter(hrefs)).endswith(fo.unit_summary_path("U1"))
    assert all(isinstance(_link(td), dcc.Link) for td in _cells(row))


# ---------------------------------------------------------------------------
# 4. Overall banding (§3.1): worst-of across the merged cells, Maintenance excluded
# ---------------------------------------------------------------------------

def test_band_for_priority_maps_resolved_priorities_to_severity_bands():
    """_band_for_priority only ever receives a resolved (non-zero) priority
    - priority 0 ("every applicable technique is Sin Datos/Sin Fuente") is
    special-cased by the caller into its own "Sin Datos" band instead
    (06_fleet_overview_revision_2.md, Required Changes #4)."""
    assert fo._band_for_priority(3) == "Anormal"
    assert fo._band_for_priority(2) == "Alerta"
    assert fo._band_for_priority(1) == "Normal"


def test_unit_with_every_technique_sin_datos_is_not_labeled_normal(monkeypatch):
    """The Estado column never reads Normal for a unit with no supporting
    data across its techniques (08, Functional Rules). Maintenance stays
    excluded from that check (§3.1) - a maintenance-only real reading (SANO)
    must not make the unit read as evaluated on severity."""
    enabled = {"monitoring-alerts": True, "monitoring-mantenciones": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({}, {}, "Sin Datos", "N/A"),  # enabled, but no record for U1
        maintenance=({"U1": "SANO"}, "Ok", "1 día"),
    )
    result = fo.build_fleet_overview("TESTCO")
    assert _band_titles(result) == ["UNIDADES SIN DATOS (1)"]
    assert _all_rows(result)["U1"] == ["Sin Datos", "Sin Datos", "SANO"]  # Maintenance still shown


def test_technique_availability_matches_table_sin_datos_signal(monkeypatch):
    """The "Fuentes de datos" banner's per-technique availability
    (dashboard/components/source_status.py::render_fleet_overview_source_status)
    must be exactly the signal the table's column already shows - a technique
    with no real record for any unit must report unavailable, not
    "Disponible" (06_fleet_overview_revision_2.md, Required Changes #5)."""
    enabled = {"monitoring-alerts": True, "monitoring-oil": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
        oil={},  # enabled, but no records - every unit reads Sin Datos for oil
    )
    assert fo.technique_availability("TESTCO") == {"alerts": True, "oil": False}


def test_stale_but_real_reading_counts_as_available_and_never_normal(monkeypatch):
    """A technique whose latest reading is stale is shown (as the worse
    state), so the banner must not claim it has no data."""
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"U1": "Normal"}, {}, "Preocupante", "25 días"),
    )
    assert fo.technique_availability("TESTCO") == {"alerts": True}
    result = fo.build_fleet_overview("TESTCO")
    assert _band_titles(result) == ["UNIDADES ANORMAL (1)"]


def test_alerts_critico_is_a_synonym_for_anormal_in_priority():
    assert fo.STATUS_PRIORITY["Crítico"] == fo.STATUS_PRIORITY["Anormal"]


def test_unit_anormal_in_one_technique_lands_in_anormal_band(monkeypatch):
    enabled = {"monitoring-alerts": True, "monitoring-oil": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
        oil={"U1": "Anormal"},
        freshness={("oil", "U1"): ("Ok", "2 días")},
    )
    assert _band_titles(fo.build_fleet_overview("TESTCO")) == ["UNIDADES ANORMAL (1)"]


def test_maintenance_detenido_never_pulls_a_unit_into_a_worse_band(monkeypatch):
    """A unit stopped for maintenance (DETENIDO) but Normal on every other
    axis must land in the Normal band - Maintenance never contributes to the
    overall severity band."""
    enabled = {"monitoring-alerts": True, "monitoring-mantenciones": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
        maintenance=({"U1": "DETENIDO"}, "Ok", "1 día"),
    )
    result = fo.build_fleet_overview("TESTCO")
    assert _band_titles(result) == ["UNIDADES NORMAL (1)"]
    assert _all_rows(result)["U1"] == ["Normal", "Normal", "DETENIDO"]


def test_estado_tooltip_names_the_techniques_that_determine_it(monkeypatch):
    enabled = {"monitoring-alerts": True, "monitoring-oil": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
        oil={"U1": "Anormal"},
        freshness={("oil", "U1"): ("Ok", "2 días")},
    )
    row = _rows(_tables(fo.build_fleet_overview("TESTCO"))[0])[0]
    tooltip = _link(_cells(row)[1]).title
    assert "Anormal" in tooltip and "Tribología" in tooltip and "Alertas" not in tooltip


# ---------------------------------------------------------------------------
# 5. Ranking (§3.3): tiebreak = count of Alerta/Anormal techniques, then
#    alphabetical - verified with mixed technique availability.
# ---------------------------------------------------------------------------

def test_ranking_tiebreak_orders_by_count_of_alerta_or_anormal_techniques(monkeypatch):
    """Both units are worst-case Alerta overall, but U-TWO is Alerta on two
    techniques while U-ONE is Alerta on only one - U-TWO must sort first."""
    enabled = {"monitoring-alerts": True, "monitoring-oil": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U-ONE": "Alerta", "U-TWO": "Alerta"}, {}, "Ok", "1h"),
        oil={"U-ONE": "Normal", "U-TWO": "Alerta"},
        freshness={("oil", "U-ONE"): ("Ok", "1 día"), ("oil", "U-TWO"): ("Ok", "1 día")},
    )
    assert list(_all_rows(fo.build_fleet_overview("TESTCO"))) == ["U-TWO", "U-ONE"]


def test_ranking_falls_back_to_alphabetical_when_counts_tie(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"Z-UNIT": "Alerta", "A-UNIT": "Alerta"}, {}, "Ok", "1h"),
    )
    assert list(_all_rows(fo.build_fleet_overview("TESTCO"))) == ["A-UNIT", "Z-UNIT"]


def test_rows_are_grouped_into_bands_worst_first(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"N": "Normal", "A": "Alerta", "X": "Anormal"}, {}, "Ok", "1h"),
    )
    result = fo.build_fleet_overview("TESTCO")
    assert _band_titles(result) == ["UNIDADES ANORMAL (1)", "UNIDADES ALERTA (1)", "UNIDADES NORMAL (1)"]
    assert list(_all_rows(result)) == ["X", "A", "N"]


# ---------------------------------------------------------------------------
# 6. Multi-client dataset with mixed technique availability (acceptance
#    criterion: "verified against at least one multi-client dataset with
#    mixed technique availability")
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "client,enabled,expected_columns",
    [
        (
            "FULLCO",
            {"monitoring-alerts": True, "monitoring-telemetry": True, "monitoring-oil": True,
             "monitoring-mantenciones": True},
            ["Alertas", "Telemetría", "Tribología", "Mantención"],
        ),
        ("OILONLYCO", {"monitoring-oil": True}, ["Tribología"]),
    ],
)
def test_mixed_technique_availability_across_clients(monkeypatch, client, enabled, expected_columns):
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
        telemetry={"U1": "Normal"},
        oil={"U1": "Normal"},
        maintenance=({"U1": "SANO"}, "Ok", "1 día"),
        freshness={("telemetry", "U1"): ("Ok", "1h"), ("oil", "U1"): ("Ok", "2 días")},
    )
    tables = _tables(fo.build_fleet_overview(client))
    assert _header(tables[0]) == ["Unidad", "Estado"] + expected_columns
    for row in _rows(tables[0]):
        assert len(_cells(row)) == 2 + len(expected_columns)


# ---------------------------------------------------------------------------
# 7. Consistency across screens: one rule, whatever state the pipelines are in
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("freshness_label,elapsed,expected", [
    ("Preocupante", "82 días", "Anormal"),  # pipeline stalled
    ("Atención", "10 días", "Alerta"),      # catching up
    ("Ok", "1h", "Normal"),                 # pipeline working again
])
def test_table_and_unit_summary_snapshot_agree_as_the_pipeline_recovers(
    monkeypatch, freshness_label, elapsed, expected
):
    """The Unit Summary header/cards read the same merged value the table
    shows - never a second computation - so when the upstream feed becomes
    current every screen moves together."""
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"U1": "Normal"}, {}, freshness_label, elapsed),
    )
    table_value = _all_rows(fo.build_fleet_overview("TESTCO"))["U1"][1]
    snapshot = fo.get_unit_snapshot("TESTCO", "U1")
    assert table_value == expected
    assert snapshot["technique_status"]["alerts"] == expected
    assert snapshot["overall_status"] == expected


def test_predictive_submodel_status_follows_the_same_rule(monkeypatch):
    import src.data.loaders as loaders
    from datetime import datetime, timedelta

    monkeypatch.setattr(fo, "_component_predictive_status_maps",
                        lambda client, component: ({"T_1": "Normal"}, {"T_1": 12.0}))

    def status_for(age_days):
        monkeypatch.setattr(loaders, "get_model_run_date",
                            lambda client, component: datetime.now() - timedelta(days=age_days))
        return fo.get_predictive_component_status("TESTCO", "T_1", "motor")

    assert status_for(60) == ("Anormal", None)   # stale: flagged, own ranking dropped
    assert status_for(0) == ("Normal", 12.0)     # pipeline current: the model's own reading


# ---------------------------------------------------------------------------
# 8. Pagination: a band renders 50 rows, further chunks load on demand
# ---------------------------------------------------------------------------

def _many_units(monkeypatch, n=120):
    units = {f"U{i:03d}": "Normal" for i in range(n)}
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=(units, {}, "Ok", "1h"),
    )
    fo._SNAPSHOTS.clear()
    return sorted(units)


def _buttons(result):
    return [n for n in _walk(result) if isinstance(n, html.Button)]


def test_band_renders_only_the_first_page_and_offers_the_next(monkeypatch):
    names = _many_units(monkeypatch)
    result = fo.build_fleet_overview("TESTCO")
    assert list(_all_rows(result)) == names[:50]
    # The band header still reports the real total, not the page size.
    assert _band_titles(result) == ["UNIDADES NORMAL (120)"]
    (button,) = _buttons(result)
    assert button.id == {"type": "fleet-more", "band": "Normal"}
    assert "50 unidades (70 restantes)" in button.children


def test_chunks_continue_the_order_without_gaps_or_duplicates(monkeypatch):
    names = _many_units(monkeypatch)
    fo.build_fleet_overview("TESTCO")
    shown = names[:50]
    for page, expected_left in ((1, 20), (2, 0)):
        rows, left = fo.get_band_rows_chunk("TESTCO", "Normal", page)
        shown += [_text(_cells(r)[0]) for r in rows]
        assert left == expected_left
    assert shown == names
    assert fo.get_band_rows_chunk("TESTCO", "Normal", 3) == ([], 0)


def test_chunk_rows_are_identical_to_what_the_first_render_would_show(monkeypatch):
    _many_units(monkeypatch)
    fo.build_fleet_overview("TESTCO")
    rows, _ = fo.get_band_rows_chunk("TESTCO", "Normal", 1)
    assert all(len(_cells(r)) == 3 for r in rows)  # Unidad, Estado, Alertas - full columns
    assert all(_link(_cells(r)[2]).title for r in rows)  # tooltips still attached


def test_small_band_has_no_button_and_unknown_band_is_empty(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
    )
    fo._SNAPSHOTS.clear()
    assert _buttons(fo.build_fleet_overview("TESTCO")) == []
    assert fo.get_band_rows_chunk("TESTCO", "Anormal", 1) == ([], 0)


def test_load_more_recomputes_when_this_worker_never_built_the_page(monkeypatch):
    names = _many_units(monkeypatch)
    fo._SNAPSHOTS.clear()  # e.g. the click lands on another gunicorn worker
    rows, remaining = fo.get_band_rows_chunk("TESTCO", "Normal", 1)
    assert [_text(_cells(r)[0]) for r in rows] == names[50:100]
    assert remaining == 20
