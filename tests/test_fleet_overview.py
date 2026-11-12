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


def _patch_all_sources(monkeypatch, *, enabled, alerts=None, telemetry=None, oil=None,
                        maintenance=None, predictive_components=None, predictive=None,
                        freshness=None, alert_counts=None):
    """Wire every per-technique data source to canned values so
    `build_fleet_overview` can run end-to-end without touching real data
    files. `enabled` gates monitoring-alerts/telemetry/oil/mantenciones via
    is_service_enabled; predictive is gated by `predictive_components`.

    `telemetry`/`oil` take a plain {unit: status} dict (no severity value -
    tests that need one patch `_telemetry_status_map`/`_oil_status_map`
    directly) and `freshness` the {(technique, unit): (label, elapsed)} map
    they share. `alert_counts` is {unit: (last week, 4 weeks, 8 weeks)}. `alerts`/`predictive` take the full
    ({unit: status}, {unit: value}, freshness_label, freshness_elapsed)
    tuple since freshness is central to what most of these tests assert."""
    monkeypatch.setattr(
        fo, "is_service_enabled",
        lambda client, service_id: enabled.get(service_id, False),
    )
    monkeypatch.setattr(fo, "_alerts_status_map", lambda client: alerts or ({}, {}, "Sin Datos", "N/A"))
    monkeypatch.setattr(fo, "_alerts_window_counts", lambda client: alert_counts or {})
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


def _tooltip(td) -> str:
    """The explanation a cell's chip button opens (hover, focus, click)."""
    return getattr(td.children, "data-tip")


def _chip(td) -> html.Span:
    """The status chip inside a table cell's button."""
    button = td.children
    assert isinstance(button, html.Button) and "chip-button" in button.className
    chip = button.children
    assert isinstance(chip, html.Span) and "status-chip" in chip.className
    return chip


def _toggles(result) -> list:
    return [
        n for n in _walk(result)
        if isinstance(n, html.Button) and getattr(n, "data-fleet-band-toggle", None)
    ]


def _band_titles(result) -> list:
    """"UNIDADES ANORMAL (2)" for each band header, in order."""
    return [f"{_text(b.children[1])} {_text(b.children[2])}" for b in _toggles(result)]


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
    """Maintenance is enabled here and still gets no column (it is hidden on the Fleet Overview)."""
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
    assert _header(tables[0]) == ["Unidad", "Estado", "Alertas", "Tribología"]


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
    assert _header(table) == ["Unidad", "Estado", "Alertas", "Tribología"]
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
    tooltip = _tooltip(cell)
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
    assert "El estado de la técnica (Anormal) es peor" in _tooltip(cell)


def test_every_status_is_a_chip_with_a_shape_and_the_status_word(monkeypatch):
    """No status is colored text alone: each is a chip carrying the word and a shape
    element (the CSS gives it a different silhouette per status)."""
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"A": "Normal", "B": "Alerta", "C": "Anormal", "D": "Sin Datos"}, {}, "Ok", "1h"),
    )
    result = fo.build_fleet_overview("TESTCO")
    rows = {_text(_cells(r)[0]): r for t in _tables(result) for r in _rows(t)}
    for unit, status in (("A", "Normal"), ("B", "Alerta"), ("C", "Anormal"), ("D", "Sin Datos")):
        for td in _cells(rows[unit])[1:]:
            assert getattr(td.children, "aria-label")  # a real button with an accessible name
            chip = _chip(td)
            shape, word = chip.children
            assert "status-chip__shape" in shape.className
            assert _text(word) == status
            assert getattr(chip, "data-status") == status


def test_estado_is_a_solid_chip_and_technique_cells_are_tinted(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"U1": "Alerta"}, {}, "Ok", "1h"),
    )
    row = _rows(_tables(fo.build_fleet_overview("TESTCO"))[0])[0]
    estado, technique = _cells(row)[1], _cells(row)[2]
    assert "status-chip--solid" in _chip(estado).className
    assert "status-chip--solid" not in _chip(technique).className
    assert "status-chip--alerta" in _chip(technique).className


def test_alerta_and_anormal_use_distinct_tiers_and_there_is_no_critico(monkeypatch):
    from dashboard.components.status_chip import STATUS_SOLID_COLORS, canonical_status

    assert STATUS_SOLID_COLORS["Alerta"] != STATUS_SOLID_COLORS["Anormal"]
    assert canonical_status("Crítico") == "Anormal"
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"U1": "Crítico"}, {}, "Ok", "1h"),
    )
    assert _all_rows(fo.build_fleet_overview("TESTCO"))["U1"] == ["Anormal", "Anormal"]


def test_row_has_one_real_link_to_the_unit_detail(monkeypatch):
    """The unit id is a real link (`<a href>` via dcc.Link); the other cells carry chip
    buttons that explain themselves instead of links."""
    enabled = {"monitoring-alerts": True, "monitoring-oil": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
        oil={"U1": "Normal"},
        freshness={("oil", "U1"): ("Ok", "2 días")},
    )
    row = _rows(_tables(fo.build_fleet_overview("TESTCO"))[0])[0]
    links = [n for n in _walk(row) if isinstance(n, dcc.Link)]
    assert len(links) == 1
    assert links[0].href.endswith(fo.unit_summary_path("U1"))
    assert _cells(row)[0].children is links[0]


def test_band_headers_are_buttons_with_aria_expanded_and_a_tinted_icon_badge(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"N": "Normal", "A": "Alerta", "X": "Anormal"}, {}, "Ok", "1h"),
    )
    result = fo.build_fleet_overview("TESTCO")
    toggles = _toggles(result)
    assert len(toggles) == 3
    for button in toggles:
        assert getattr(button, "aria-controls").startswith("fleet-band-body-")
        assert "icon-badge" in button.children[0].className
        assert not hasattr(button, "style")  # no inline left-border accent
    controlled = {n.id for n in _walk(result) if getattr(n, "data-fleet-band-body", None)}
    assert {getattr(b, "aria-controls") for b in toggles} == controlled


def test_anormal_starts_expanded_and_alerta_and_normal_collapsed_with_their_counts(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"N1": "Normal", "N2": "Normal", "A": "Alerta", "X": "Anormal"}, {}, "Ok", "1h"),
    )
    result = fo.build_fleet_overview("TESTCO")
    states = {_text(b.children[1]): getattr(b, "aria-expanded") for b in _toggles(result)}
    assert states == {"UNIDADES ANORMAL": "true", "UNIDADES ALERTA": "false", "UNIDADES NORMAL": "false"}
    assert _band_titles(result) == ["UNIDADES ANORMAL (1)", "UNIDADES ALERTA (1)", "UNIDADES NORMAL (2)"]
    bodies = {getattr(n, "id"): n for n in _walk(result) if getattr(n, "data-fleet-band-body", None)}
    assert bodies["fleet-band-body-anormal"].style is None
    assert bodies["fleet-band-body-normal"].style == {"display": "none"}


# ---------------------------------------------------------------------------
# 3b. Search ("Buscar Unidad")
# ---------------------------------------------------------------------------

def _patch_search_fleet(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"CA-9": "Normal", "CA-90": "Anormal", "CA-93": "Alerta", "CA-2": "Normal", "CA-10": "Anormal"},
                {}, "Ok", "1h"),
    )
    fo._SNAPSHOTS.clear()


def test_search_lists_only_matching_units_and_opens_their_sections(monkeypatch):
    _patch_search_fleet(monkeypatch)
    result = fo.build_fleet_overview("TESTCO", "CA-9")
    assert list(_all_rows(result)) == ["CA-90", "CA-93", "CA-9"]  # band by band, natural order inside
    states = {_text(b.children[1]): getattr(b, "aria-expanded") for b in _toggles(result)}
    assert states == {"UNIDADES ANORMAL": "true", "UNIDADES ALERTA": "true", "UNIDADES NORMAL": "true"}
    assert getattr(result, "data-fleet-search") == "active"


def test_search_does_not_change_the_counts_in_the_headers(monkeypatch):
    _patch_search_fleet(monkeypatch)
    plain = _band_titles(fo.build_fleet_overview("TESTCO"))
    assert _band_titles(fo.build_fleet_overview("TESTCO", "CA-9", refresh=False)) == plain
    assert plain == ["UNIDADES ANORMAL (2)", "UNIDADES ALERTA (1)", "UNIDADES NORMAL (2)"]


def test_search_is_case_insensitive_and_a_band_without_matches_stays_closed(monkeypatch):
    _patch_search_fleet(monkeypatch)
    result = fo.build_fleet_overview("TESTCO", "ca-93", refresh=False)
    assert list(_all_rows(result)) == ["CA-93"]
    states = {_text(b.children[1]): getattr(b, "aria-expanded") for b in _toggles(result)}
    assert states == {"UNIDADES ANORMAL": "false", "UNIDADES ALERTA": "true", "UNIDADES NORMAL": "false"}


def test_search_without_results_says_so(monkeypatch):
    _patch_search_fleet(monkeypatch)
    result = fo.build_fleet_overview("TESTCO", "ZZ", refresh=False)
    assert _all_rows(result) == {}
    assert "Ninguna unidad coincide" in _text(result)


def test_search_and_load_more_agree_on_the_matches(monkeypatch):
    _many_units(monkeypatch)
    result = fo.build_fleet_overview("TESTCO", "U01")  # U010..U019
    assert list(_all_rows(result)) == [f"U01{i}" for i in range(10)]
    rows, remaining = fo.get_band_rows_chunk("TESTCO", "Normal", 1, "U01")
    assert (rows, remaining) == ([], 0)


def test_the_search_field_is_labeled():
    from dashboard.tabs.tab_overview_general import create_layout

    layout = create_layout()
    label = next(n for n in _walk(layout) if isinstance(n, html.Label))
    field = next(n for n in _walk(layout) if getattr(n, "id", None) == "fleet-search")
    assert label.htmlFor == "fleet-search" and _text(label) == "Buscar Unidad"
    assert field.type == "search"


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
        alerts=({"U1": "Sin Datos"}, {}, "Sin Datos", "N/A"),  # enabled, but no reading for U1
        maintenance=({"U1": "SANO"}, "Ok", "1 día"),
    )
    result = fo.build_fleet_overview("TESTCO")
    assert _band_titles(result) == ["UNIDADES SIN DATOS (1)"]
    assert _all_rows(result)["U1"] == ["Sin Datos", "Sin Datos"]  # Maintenance is not a column
    assert "Mantención" not in _header(_tables(result)[0])


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


def test_maintenance_has_no_status_but_keeps_its_data_source_availability(monkeypatch):
    """Mantención has no column and no status in the General tab - not in the unit's
    snapshot either - but "Fuentes de datos" still reports whether its data is there."""
    enabled = {"monitoring-alerts": True, "monitoring-mantenciones": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
        maintenance=({"U1": "DETENIDO"}, "Ok", "1 día"),
    )
    assert fo.technique_availability("TESTCO") == {"alerts": True, "maintenance": True}
    snapshot = fo.get_unit_snapshot("TESTCO", "U1")
    assert "maintenance" not in snapshot["technique_status"]
    assert "maintenance_status" not in snapshot
    assert "Mantención" not in _header(_tables(fo.build_fleet_overview("TESTCO"))[0])


def test_unit_known_only_to_maintenance_is_dropped(monkeypatch):
    enabled = {"monitoring-alerts": True, "monitoring-mantenciones": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
        maintenance=({"U1": "SANO", "M-ONLY": "DETENIDO"}, "Ok", "1 día"),
    )
    assert list(_all_rows(fo.build_fleet_overview("TESTCO"))) == ["U1"]
    assert [u["unit"] for u in fo.get_ordered_units("TESTCO")] == ["U1"]


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
    assert _all_rows(result)["U1"] == ["Normal", "Normal"]


def test_estado_tooltip_names_the_techniques_that_determine_it(monkeypatch):
    enabled = {"monitoring-alerts": True, "monitoring-oil": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
        oil={"U1": "Anormal"},
        freshness={("oil", "U1"): ("Ok", "2 días")},
    )
    row = _rows(_tables(fo.build_fleet_overview("TESTCO"))[0])[0]
    tooltip = _tooltip(_cells(row)[1])
    assert "Anormal" in tooltip and "Tribología" in tooltip and "Alertas" not in tooltip


# ---------------------------------------------------------------------------
# 5. Ranking (§3.3): tiebreak = count of Alerta/Anormal techniques, then
#    alphabetical - verified with mixed technique availability.
# ---------------------------------------------------------------------------

def test_units_follow_natural_ascending_id_order_within_a_band(monkeypatch):
    """CA-2 before CA-10, whatever the units' readings: the ranking by number of techniques
    in Alerta and by alert counts no longer orders a band."""
    enabled = {"monitoring-alerts": True, "monitoring-oil": True}
    _patch_all_sources(
        monkeypatch, enabled=enabled,
        alerts=({"CA-10": "Alerta", "CA-2": "Alerta", "CA-1": "Alerta", "CA-9": "Alerta"}, {}, "Ok", "1h"),
        oil={"CA-10": "Alerta", "CA-2": "Normal", "CA-1": "Normal", "CA-9": "Normal"},
        freshness={("oil", u): ("Ok", "1 día") for u in ("CA-10", "CA-2", "CA-1", "CA-9")},
        alert_counts={"CA-10": (9, 9, 9), "CA-2": (0, 1, 1)},
    )
    assert list(_all_rows(fo.build_fleet_overview("TESTCO"))) == ["CA-1", "CA-2", "CA-9", "CA-10"]


def test_natural_key_compares_numbers_as_numbers():
    assert sorted(["CA-10", "CA-2", "T_9", "CA-1", "ca-3"], key=fo.natural_key) == ["CA-1", "CA-2", "ca-3", "CA-10", "T_9"]


def test_alerts_tooltip_lists_the_three_window_counts(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"U1": "Alerta", "U2": "Alerta"}, {}, "Ok", "1h"),
        alert_counts={"U1": (2, 7, 11)},  # U2 has no alert at all
    )
    rows = {_text(_cells(r)[0]): r for r in _rows(_tables(fo.build_fleet_overview("TESTCO"))[0])}
    assert "Alertas: última semana 2 · últimas 4 semanas 7 · últimas 8 semanas 11" in _tooltip(_cells(rows["U1"])[2])
    assert "última semana 0 · últimas 4 semanas 0 · últimas 8 semanas 0" in _tooltip(_cells(rows["U2"])[2])


def test_alerts_tooltip_has_no_counts_line_without_an_alert_feed(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"U1": "Alerta"}, {}, "Ok", "1h"),
    )
    row = _rows(_tables(fo.build_fleet_overview("TESTCO"))[0])[0]
    assert "última semana" not in _tooltip(_cells(row)[2])


def test_count_alerts_by_window_uses_nested_trailing_windows():
    from datetime import datetime, timedelta

    import pandas as pd

    from dashboard.callbacks.overview_general_callbacks import count_alerts_by_window

    now = datetime.now()
    ago = lambda days: now - timedelta(days=days, hours=1)  # noqa: E731 - just inside the window edge
    df = pd.DataFrame({
        "UnitId": ["U1", "U1", "U1", "U1", "U1", "U2"],
        "Timestamp": [ago(1), ago(6), ago(27), ago(55), ago(70), ago(100)],
    })
    assert count_alerts_by_window(df) == {"U1": (2, 3, 4), "U2": (0, 0, 0)}
    assert count_alerts_by_window(pd.DataFrame()) == {}


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
            ["Alertas", "Telemetría", "Tribología"],
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
    """The "show more" buttons (not the band toggles)."""
    return [n for n in _walk(result) if isinstance(n, html.Button) and isinstance(getattr(n, "id", None), dict)]


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
    assert all(_tooltip(_cells(r)[2]) for r in rows)  # tooltips still attached


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
