"""
Unit Detail (dashboard/components/unit_summary.py + unit_summary_content.py): banner,
"Estado por Técnica" tiles, Telemetría / Tribología rows, Pareto period, Predictivo
titles and the navigation bar (ui_notes_improved.md, Unit Detail requirements).

The data sources are replaced by canned values: nothing here reads the data mirror.
"""

from datetime import date, datetime

import pandas as pd
import pytest
import dash_bootstrap_components as dbc
from dash import dcc, html

import dashboard.components.fleet_overview as fo
import dashboard.components.unit_summary as us
import dashboard.components.unit_summary_content as usc
import src.data.unit_horometer as horometer
from dashboard.components.oil_machine_detail import OilComponentRow


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


def _find(root, component, class_part=None):
    return [
        n for n in _walk(root)
        if isinstance(n, component) and (class_part is None or class_part in (getattr(n, "className", None) or ""))
    ]


def _chips(root):
    return [(getattr(n, "data-status"), _text(n)) for n in _find(root, html.Span, "status-chip ")]


def _oil_rows(statuses):
    return [
        OilComponentRow(f"Comp {i}", status, "Desgaste" if status != "Normal" else None,
                        f"Diagnóstico {i}" if i % 2 else None, pd.Timestamp("2026-06-18"))
        for i, status in enumerate(statuses)
    ]


# ── Telemetría ──────────────────────────────────────────────────────────────

def _telemetry_frame(statuses):
    return pd.DataFrame({
        "unit": ["U1"] * len(statuses),
        "system": [f"Sistema {i}" for i in range(len(statuses))],
        "system_score": [10.0 * (i + 1) for i in range(len(statuses))],
        "system_status": statuses,
        "week": [31] * len(statuses), "year": [2026] * len(statuses),
    })


def _telemetry_card(monkeypatch, statuses, card_status="Anormal"):
    monkeypatch.setattr(usc, "load_telemetry_system_health", lambda client: _telemetry_frame(statuses))
    return usc._telemetry_section("TESTCO", "U1", card_status)


def test_telemetry_shows_one_status_row_per_system_and_no_score(monkeypatch):
    card = _telemetry_card(monkeypatch, ["Normal", "Alerta", "Normal"])
    text = _text(card)
    assert text.count("Sistema ") == 3
    for score in ("10.0", "20.0", "30.0"):
        assert score not in text
    assert not _find(card, dcc.Graph)  # no bar chart either
    assert "Semana más reciente" in text


def test_telemetry_rows_are_worst_first(monkeypatch):
    card = _telemetry_card(monkeypatch, ["Normal", "Normal", "Alerta", "Anormal"])
    (table,) = _find(card, html.Table)
    order = [_text(tr.children[0]) for tr in table.children[2].children]
    assert order == ["Sistema 3", "Sistema 2", "Sistema 1", "Sistema 0"]  # inside a status: higher score first


def test_telemetry_explains_visibly_what_anormal_combines(monkeypatch):
    card = _telemetry_card(monkeypatch, ["Normal", "Normal"], card_status="Anormal")
    text = _text(card)
    assert "combina el estado general de la unidad y la antigüedad de los datos" in text
    # The thresholds quoted are the rule's: Telemetria goes Alerta after 2 h, Anormal after 24 h.
    assert "Más de 2 h sin actualizarse cuenta como Alerta" in text
    assert "Más de 24 h sin actualizarse cuenta como Anormal" in text
    assert not _find(card, html.Details)  # visible, not behind a toggle


def test_few_normal_rows_stay_visible(monkeypatch):
    card = _telemetry_card(monkeypatch, ["Alerta", "Normal", "Normal", "Normal"])
    assert not _find(card, html.Details)
    assert len(_find(card, html.Table)) == 1


def test_more_than_three_normal_rows_collapse_but_alerta_and_anormal_never_do(monkeypatch):
    card = _telemetry_card(monkeypatch, ["Alerta", "Anormal"] + ["Normal"] * 4)
    (details,) = _find(card, html.Details)
    shown = [t for t in _find(card, html.Table) if t not in list(_walk(details))]
    assert len(shown) == 1
    assert [_text(tr.children[0]) for tr in shown[0].children[2].children] == ["Sistema 1", "Sistema 0"]
    assert "Mostrar 4 en Normal" in _text(details.children[0])
    hidden_rows = [r for r in _find(details, html.Tr) if _find(r, html.Td)]
    assert len(hidden_rows) == 4


def test_card_header_counts_statuses_worst_first(monkeypatch):
    card = _telemetry_card(monkeypatch, ["Alerta"] * 4 + ["Normal"] * 6)
    assert "4 en Alerta · 6 Normal" in _text(card)


def test_telemetry_without_data_is_an_empty_state(monkeypatch):
    monkeypatch.setattr(usc, "load_telemetry_system_health", lambda client: pd.DataFrame())
    assert "Sin evaluación de telemetría" in _text(usc._telemetry_section("TESTCO", "U1", "Sin Datos"))


# ── Tribología ──────────────────────────────────────────────────────────────

def _oil_card(monkeypatch, statuses, status="Anormal"):
    monkeypatch.setattr(usc, "unit_oil_components", lambda client, unit: _oil_rows(statuses))
    return usc._oil_section("TESTCO", "U1", status)


def test_oil_is_a_vertical_table_with_four_columns(monkeypatch):
    card = _oil_card(monkeypatch, ["Alerta", "Normal"])
    (table,) = _find(card, html.Table)
    # Four data columns, plus the one holding each row's "Ver en Tribología" (named for screen readers only).
    assert [_text(th) for th in _find(table, html.Th)] == ["Componente", "Estado", "Anomalía", "Diagnóstico", "Acciones"]
    (hidden,) = [th for th in _find(table, html.Th) if _text(th) == "Acciones"]
    assert "visually-hidden" in hidden.children.className


def test_every_oil_row_has_a_keyboard_diagnosis_toggle(monkeypatch):
    card = _oil_card(monkeypatch, ["Alerta", "Normal", "Normal"])
    toggles = _find(card, html.Summary, "unit-diagnosis-toggle")
    assert len(toggles) == 3
    assert all(_text(t) == "Ver Diagnóstico" for t in toggles)
    # A native <details>: opens by click/Enter/Space, never by hover (no title tooltip).
    assert all(isinstance(t, html.Summary) for t in toggles)
    assert "Sin recomendación" in _text(card)  # a row without a diagnosis still has the toggle


def test_oil_with_ten_components_shows_alerts_and_collapses_the_normal_ones(monkeypatch):
    card = _oil_card(monkeypatch, ["Alerta"] * 4 + ["Normal"] * 6)
    (details,) = _find(card, html.Details, "unit-normal-details")
    outside = [r for r in _find(card, html.Tr) if r not in list(_walk(details)) and _find(r, html.Td)]
    assert len(outside) == 4
    assert "Mostrar 6 en Normal" in _text(details.children[0])
    assert "4 en Alerta · 6 Normal" in _text(card)


def test_oil_header_states_the_data_date_and_its_age(monkeypatch):
    card = _oil_card(monkeypatch, ["Normal"])
    text = _text(card)
    assert "Datos al 18/06/2026 · hace " in text and " días" in text


def test_oil_rows_come_worst_first(monkeypatch):
    rows = _oil_rows(["Anormal", "Alerta", "Normal"])  # the data layer sorts; the table keeps it
    monkeypatch.setattr(usc, "unit_oil_components", lambda client, unit: rows)
    chips = _chips(usc._oil_section("TESTCO", "U1", "Anormal"))
    assert [c[0] for c in chips[1:]] == ["Anormal", "Alerta", "Normal"]


# ── Pareto ──────────────────────────────────────────────────────────────────

def test_pareto_period_is_the_current_month_when_it_has_data():
    current = datetime.now().strftime("%Y-%m")
    assert usc._pareto_period(["2026-01", current]) == (current, True)


def test_pareto_period_falls_back_to_the_latest_month_with_data():
    assert usc._pareto_period(["2025-11", "2026-01"]) == ("2026-01", False)
    assert usc._pareto_period([]) == (None, False)


# ── Banner ──────────────────────────────────────────────────────────────────

def _patch_banner(monkeypatch, *, hours=None, components=("Motor",), sample=pd.Timestamp("2026-07-23")):
    monkeypatch.setattr(us, "monitored_components", lambda client, unit: list(components))
    monkeypatch.setattr(us, "unit_horometer", lambda client, unit: hours)
    monkeypatch.setattr(us, "last_sample_date", lambda client, unit: sample)


def test_banner_shows_unit_estado_components_horometer_and_last_sample(monkeypatch):
    _patch_banner(monkeypatch, hours=horometer.UnitHorometer(116846.0, date(2026, 6, 18)), components=["A"] * 10)
    banner = us._banner("TESTCO", "T_10", "Alerta")
    text = _text(banner)
    assert "T_10" in text and "Componentes monitoreados10" in text
    assert "Horómetro de la Unidad116.846 hLectura al 18/06/2026" in text
    assert "Última Muestra de Aceite23/07/2026" in text
    assert _chips(banner) == [("Alerta", "Alerta")]


def test_banner_shows_a_dash_for_every_missing_value(monkeypatch):
    _patch_banner(monkeypatch, hours=None, components=[], sample=None)
    banner = us._banner("TESTCO", "T_10", "Normal")
    values = [_text(dd) for dd in _find(banner, html.Dd)]
    assert values == ["—", "—", "—"]


# ── Horómetro ───────────────────────────────────────────────────────────────

class _Settings:
    def __init__(self, path):
        self._path = path

    def get_component_hours_path(self, client):
        return self._path


@pytest.fixture
def hours_file(tmp_path, monkeypatch):
    path = tmp_path / "cleaned_component_hours.parquet"
    df = pd.DataFrame({
        "client": "TESTCO",
        "unitId": ["U1"] * 5 + ["U2"],
        "componentName": ["motor", "motor", "hidraulico", "transmision", "convertidor", "motor"],
        "sampleDate": pd.to_datetime(["2026-01-01", "2026-06-18", "2026-06-18", "2026-06-18", "2026-06-18", "2026-06-18"]),
        "componentHours": [900.0, 13785.0, 116846.0, 2120.0, None, None],
        "componentHours_cleaned": [900.0, 13785.0, 116846.0, 2120.0, None, None],
    })
    df.to_parquet(path)
    monkeypatch.setattr(horometer, "get_settings", lambda: _Settings(path))
    return path


def test_horometer_is_the_largest_latest_reading_of_the_unit(hours_file):
    reading = horometer.unit_horometer("TESTCO", "U1")
    assert reading == horometer.UnitHorometer(116846.0, date(2026, 6, 18))


def test_horometer_is_none_when_the_unit_has_no_reading(hours_file):
    assert horometer.unit_horometer("TESTCO", "U2") is None
    assert horometer.unit_horometer("TESTCO", "NOPE") is None


def test_horometer_is_none_when_the_client_has_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(horometer, "get_settings", lambda: _Settings(tmp_path / "missing.parquet"))
    assert horometer.unit_horometer("TESTCO", "U1") is None


# ── Status tiles ────────────────────────────────────────────────────────────

def _patch_tiles(monkeypatch, applicable, predictive_components=("motor",)):
    monkeypatch.setattr(usc, "applicable_techniques", lambda client: applicable)
    monkeypatch.setattr(usc, "enabled_predictive_components", lambda client: list(predictive_components))
    monkeypatch.setattr(usc, "_technique_data_date", lambda *a, **k: pd.Timestamp("2026-07-23"))


def test_tiles_exist_only_for_monitored_techniques_and_never_for_maintenance(monkeypatch):
    _patch_tiles(monkeypatch, {"alerts": True, "telemetry": False, "oil": True, "maintenance": True, "predictive": True})
    tiles = _find(usc.build_status_tiles("TESTCO", "U1", {"alerts": "Normal", "oil": "Alerta", "predictive": "Normal"}),
                  html.A, "unit-tile")
    names = [_text(t.children[0]) for t in tiles]
    assert names == ["Alertas", "Tribología", "Predictivo"]
    assert "Mantención" not in " ".join(names)


def test_a_client_with_telemetry_gets_a_telemetry_tile_first(monkeypatch):
    _patch_tiles(monkeypatch, {"alerts": True, "telemetry": True, "oil": True, "maintenance": False, "predictive": False})
    tiles = _find(usc.build_status_tiles("TESTCO", "U1", {"telemetry": "Anormal"}), html.A, "unit-tile")
    assert [_text(t.children[0]) for t in tiles] == ["Telemetría", "Alertas", "Tribología"]


def test_tile_shows_name_chip_data_date_and_links_to_its_section(monkeypatch):
    _patch_tiles(monkeypatch, {"alerts": False, "telemetry": False, "oil": True, "maintenance": False, "predictive": False})
    (tile,) = _find(usc.build_status_tiles("TESTCO", "U1", {"oil": "Alerta"}), html.A, "unit-tile")
    assert tile.href == "#" + usc.SECTION_IDS["oil"]
    assert _chips(tile) == [("Alerta", "Alerta")]
    assert "Datos al 23/07/2026" in _text(tile)


def test_a_monitored_technique_without_a_status_reads_sin_datos(monkeypatch):
    _patch_tiles(monkeypatch, {"alerts": True, "telemetry": False, "oil": False, "maintenance": False, "predictive": False})
    (tile,) = _find(usc.build_status_tiles("TESTCO", "U1", {}), html.A, "unit-tile")
    assert _chips(tile) == [("Sin Datos", "Sin Datos")]


def test_no_monitored_technique_means_no_tiles(monkeypatch):
    _patch_tiles(monkeypatch, {"alerts": False, "telemetry": False, "oil": False, "maintenance": True, "predictive": False},
                 predictive_components=())
    assert usc.build_status_tiles("TESTCO", "U1", {}) is None


# ── Predictivo ──────────────────────────────────────────────────────────────

def test_fleet_position_title_names_the_axes_the_scatter_really_plots():
    # CAPSTONE / motor is configured as (ranking_7d, ranking_90d) in Settings.fleet_scatter_axes.
    title = usc._fleet_position_title("CAPSTONE", "motor")
    assert "Ranking 7 días (eje X)" in title and "Ranking 90 días (eje Y)" in title


def test_fleet_position_title_is_plain_when_the_pair_has_no_axes():
    assert usc._fleet_position_title("NOCLIENT", "motor") == "Posición en la flota"


# ── Master-detail: the unit list and the detail header ──────────────────────

def _entries(spec):
    """`[(unit, band), ...]` as the ordered list `get_ordered_units` returns."""
    return [{"unit": u, "band": b, "overall_status": b, "technique_status": {}} for u, b in spec]


FLEET = _entries([("A1", "Anormal"), ("A2", "Anormal"), ("B1", "Alerta"), ("N1", "Normal"), ("N2", "Normal"), ("N3", "Normal")])


def _detail_controls(header):
    return {
        "prev": next(b for b in _find(header, html.Button) if getattr(b, "data-unit-nav") == "prev"),
        "next": next(b for b in _find(header, html.Button) if getattr(b, "data-unit-nav") == "next"),
        "position": next(n for n in _walk(header) if getattr(n, "data-unit-position", None)),
        "close": _find(header, dcc.Link)[0],
    }


def test_old_navigation_controls_are_gone():
    page = us._split(FLEET, "A1", [us._detail_header(FLEET, "A1", "Anormal")])
    text = _text(page)
    for gone in ("Volver a Fleet Overview", "Primera unidad", "Cambiar unidad", "Última unidad"):
        assert gone not in text
    assert not _find(page, html.Select)
    assert not hasattr(us, "_navigation_bar")


def test_list_has_a_labeled_search_the_state_date_and_every_unit_grouped_by_estado():
    listing = us._unit_list(FLEET, "B1")
    (label,) = _find(listing, html.Label)
    (search,) = [n for n in _walk(listing) if isinstance(n, dcc.Input)]
    assert _text(label) == "Buscar Unidad" and label.htmlFor == search.id == us.SEARCH_ID
    assert search.type == "search"
    caption = next(n for n in _find(listing, html.P, "unit-list__caption"))
    assert _text(caption) == f"Estado al {datetime.now():%d/%m/%Y}"
    groups = _find(listing, html.Div, "unit-group")
    assert [getattr(g, "data-unit-group") for g in groups] == ["Anormal", "Alerta", "Normal"]
    # Title and unit count of each group.
    assert [" ".join(_text(c) for c in g.children[0].children[1:3]) for g in groups] == [
        "Anormal (2)", "Alerta (1)", "Normal (3)"]
    items = _find(listing, html.Li)
    assert [getattr(i, "data-unit-item") for i in items] == ["A1", "A2", "B1", "N1", "N2", "N3"]  # list order
    # Each item is a real link to the unit, showing its id and Estado chip.
    for item, entry in zip(items, FLEET):
        (link,) = [n for n in _walk(item) if isinstance(n, dcc.Link)]
        assert link.href.endswith(fo.unit_summary_path(entry["unit"]))
        assert _chips(item) == [(entry["band"], entry["band"])]


def test_the_selected_unit_is_highlighted_and_nothing_else():
    links = _find(us._unit_list(FLEET, "B1"), dcc.Link, "unit-item")
    assert [("unit-item--selected" in l.className) for l in links] == [False, False, True, False, False, False]


def test_groups_are_real_toggle_buttons_open_for_attention_and_for_the_selected_unit():
    def state(selected):
        listing = us._unit_list(FLEET, selected)
        return {
            getattr(b, "aria-controls"): getattr(b, "aria-expanded") for b in _find(listing, html.Button, "unit-group__header")
        }

    assert state("A1") == {"unit-group-body-anormal": "true", "unit-group-body-alerta": "true", "unit-group-body-normal": "false"}
    assert state("N2")["unit-group-body-normal"] == "true"  # the unit being shown is never hidden away
    listing = us._unit_list(FLEET, "A1")
    bodies = {b.id: b for b in _find(listing, html.Ul, "unit-group__items")}
    assert bodies["unit-group-body-normal"].hidden and not bodies["unit-group-body-anormal"].hidden


def test_header_shows_unit_estado_prev_position_next_and_close():
    header = us._detail_header(FLEET, "A2", "Anormal")
    text = _text(header)
    assert "A2" in text and "Anterior" in text and "Siguiente" in text and "Cerrar Unidad" in text
    assert _chips(header) == [("Anormal", "Anormal")]
    controls = _detail_controls(header)
    assert _text(controls["position"]) == "2 / 3"  # A1, A2, B1 are shown: Normal is closed
    assert getattr(controls["position"], "data-unit-position-format") == "{n} / {total}"
    assert controls["close"].href.endswith("/overview/general")
    assert [controls["prev"].disabled, controls["next"].disabled] == [False, False]


def test_anterior_is_disabled_on_the_first_unit_and_siguiente_on_the_last_one_shown():
    first = _detail_controls(us._detail_header(FLEET, "A1", "Anormal"))
    assert [first["prev"].disabled, first["next"].disabled] == [True, False]
    assert _text(first["position"]) == "1 / 3"
    last = _detail_controls(us._detail_header(FLEET, "B1", "Alerta"))
    assert [last["prev"].disabled, last["next"].disabled] == [False, True]  # N1.. sit in a closed group


def test_a_unit_in_a_closed_group_has_no_position_but_the_group_it_is_in_is_open():
    # The selected unit's own group is always rendered open, so it is in the navigable set.
    controls = _detail_controls(us._detail_header(FLEET, "N2", "Normal"))
    assert _text(controls["position"]) == "5 / 6"


def test_the_whole_split_is_built_from_the_snapshot_and_has_no_other_unit_selected(monkeypatch):
    from tests.test_fleet_overview import _patch_all_sources

    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True},
        alerts=({"U1": "Normal", "U2": "Alerta"}, {}, "Ok", "1h"),
    )
    _patch_banner(monkeypatch)
    monkeypatch.setattr(us, "build_unit_summary_content", lambda *a, **k: html.Div("BODY"))
    page = us._build_unit_summary("TESTCO", "U2")
    assert page.className == "unit-split"
    assert [c.className for c in page.children] == ["unit-list", "unit-detail"]
    assert "BODY" in _text(page) and _text(_find(page, html.H2, "unit-detail__unit")[0]) == "U2"


def test_unknown_unit_keeps_the_list_so_another_one_can_be_picked(monkeypatch):
    from tests.test_fleet_overview import _patch_all_sources

    _patch_all_sources(monkeypatch, enabled={"monitoring-alerts": True}, alerts=({"U1": "Normal"}, {}, "Ok", "1h"))
    page = us._build_unit_summary("TESTCO", "NOPE")
    assert _find(page, dcc.Link, "unit-item") and "NOPE" in _text(page)
    assert not any("unit-item--selected" in l.className for l in _find(page, dcc.Link, "unit-item"))


def test_split_stacks_under_900px_and_nothing_floats_over_the_content():
    css = open("dashboard/assets/unit_detail.css", encoding="utf-8").read()
    assert "@media (max-width: 900px)" in css
    narrow = css[css.index("@media (max-width: 900px)"):]
    block = narrow[:narrow.index("\n}")]
    assert ".unit-split" in block and "grid-template-columns: minmax(0, 1fr)" in block  # one column: list above detail
    assert "position: sticky" not in css and "position: fixed" not in css and "position: absolute" not in css


# ── The unit's Estado is the same in both views ─────────────────────────────

def test_banner_estado_is_the_fleet_overview_estado(monkeypatch):
    from tests.test_fleet_overview import _patch_all_sources

    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True, "monitoring-oil": True},
        alerts=({"U1": "Normal"}, {}, "Ok", "1h"),
        oil={"U1": "Alerta"},
        freshness={("oil", "U1"): ("Ok", "2 días")},
    )
    _patch_banner(monkeypatch)
    monkeypatch.setattr(us, "build_unit_summary_content", lambda *a, **k: html.Div())
    page = us._build_unit_summary("TESTCO", "U1")
    banner_chip = _chips(_find(page, html.Section, "unit-banner")[0])
    assert banner_chip == [("Alerta", "Alerta")]
    assert fo.get_unit_snapshot("TESTCO", "U1")["overall_status"] == "Alerta"


# ── Banner color follows the Estado ─────────────────────────────────────────

@pytest.mark.parametrize("estado,css,on_dark", [
    ("Alerta", "unit-banner--alerta", True),
    ("Anormal", "unit-banner--anormal", True),
    ("Normal", "unit-banner--normal", False),
    ("Sin Datos", "unit-banner--sindatos", False),
])
def test_banner_takes_the_tier_color_of_the_estado(monkeypatch, estado, css, on_dark):
    _patch_banner(monkeypatch)
    banner = us._banner("TESTCO", "U1", estado)
    assert css in banner.className
    chip = _find(banner, html.Span, "status-chip ")[0]
    assert ("status-chip--on-dark" in chip.className) == on_dark


# ── Freshness: "Datos al [fecha] · hace N días" ─────────────────────────────

def test_freshness_caption_states_date_and_age():
    old = pd.Timestamp(datetime.now() - pd.Timedelta(days=84))
    assert usc._freshness_caption(old) == f"Datos al {old.strftime('%d/%m/%Y')} · hace 84 días"
    assert usc._freshness_caption(pd.Timestamp(datetime.now())).endswith("· hoy")
    assert usc._freshness_caption(None) is None


def test_every_card_with_technique_data_carries_the_freshness_caption(monkeypatch):
    stamp = pd.Timestamp(datetime.now() - pd.Timedelta(days=10))
    monkeypatch.setattr(usc, "_telemetry_data_date", lambda client, unit: stamp)
    monkeypatch.setattr(usc, "_alerts_data_date", lambda client: stamp)
    monkeypatch.setattr(usc, "latest_alert_timestamp", lambda client: None)  # no alert feed
    telemetry = _telemetry_card(monkeypatch, ["Normal"])
    alerts = usc._alerts_section("TESTCO", "U1", "Sin Datos")
    rows = [OilComponentRow(r.component, r.status, r.anomaly, r.diagnosis, stamp) for r in _oil_rows(["Normal"])]
    monkeypatch.setattr(usc, "unit_oil_components", lambda client, unit: rows)
    oil = usc._oil_section("TESTCO", "U1", "Normal")
    for card in (telemetry, alerts, oil):
        assert "Datos al " in _text(card) and "hace 10 días" in _text(card)


def test_stale_alertas_keeps_its_chip_notice_and_empty_state(monkeypatch):
    stale = pd.Timestamp(datetime.now() - pd.Timedelta(days=100))
    feed = pd.DataFrame({"UnitId": ["U9"], "Timestamp": [stale]})
    monkeypatch.setattr(usc, "latest_alert_timestamp", lambda client: stale)
    monkeypatch.setattr(usc, "load_alerts_since", lambda client, since: feed)
    card = usc._alerts_section("TESTCO", "U1", "Sin Datos")
    text = _text(card)
    assert _chips(card) == [("Sin Datos", "Sin Datos")]
    assert "Sin datos nuevos hace 4+ semanas" in text and "Sin alertas registradas" in text and "hace 100 días" in text


# ── Display names ───────────────────────────────────────────────────────────

def test_telemetry_systems_are_shown_in_spanish(monkeypatch):
    monkeypatch.setattr(usc, "load_telemetry_system_health", lambda client: pd.DataFrame({
        "unit": ["U1"] * 4, "system": ["Engine", "Transmission", "Steering", "Brakes"],
        "system_score": [1.0, 2.0, 3.0, 4.0], "system_status": ["Normal"] * 4, "week": [1] * 4, "year": [2026] * 4,
    }))
    text = _text(usc._telemetry_section("TESTCO", "U1", "Normal"))
    for shown in ("Motor", "Transmisión", "Dirección", "Frenos"):
        assert shown in text
    for english in ("Engine", "Transmission", "Steering", "Brakes"):
        assert english not in text


@pytest.mark.parametrize("raw,shown", [
    ("sistema de direccion", "Sistema de Dirección"),
    ("sistema hidraulico", "Sistema Hidráulico"),
    ("transmision", "Transmisión"),
    ("mando final trasero derecho", "Mando Final Trasero Derecho"),
    ("MOTOR DIESEL", "Motor Diesel"),
])
def test_component_names_get_their_accents(raw, shown):
    from dashboard.components.labels import display_component_name

    assert display_component_name(raw) == shown


# ── Pareto ──────────────────────────────────────────────────────────────────

def test_pareto_uses_one_color_and_full_axis_labels():
    from dashboard.tabs.tab_mantenciones_general import PARETO_BAR_COLOR, create_equipment_pareto_chart

    names = ["Sistema de Dirección y Frenos de Servicio", "Tren de Fuerza", "Sistema Hidráulico"]
    fig = usc._fit_pareto_figure(create_equipment_pareto_chart(
        pd.DataFrame({"system_name": names, "count": [9, 5, 2]}), system_label="Sistemas",
    ))
    assert fig.data[0].marker.color == PARETO_BAR_COLOR
    assert list(fig.layout.xaxis.ticktext) == names  # none shortened


def test_pareto_card_has_no_status_chip():
    card = usc._section_card("Pareto", "Período: 2026-01 (último con datos)", html.Div(), icon="fas fa-chart-bar")
    assert not _chips(card)


# ── Layout ──────────────────────────────────────────────────────────────────

def test_only_the_tiles_are_forced_to_equal_height():
    css = open("dashboard/assets/unit_detail.css", encoding="utf-8").read()
    assert css.count("grid-auto-rows") == 1  # the tiles
    assert "h-100" not in usc._section_card("T", "p", html.Div()).className


def test_monitoreo_cards_each_take_the_full_width_in_order(monkeypatch):
    monkeypatch.setattr(usc, "applicable_techniques", lambda client: {
        "telemetry": True, "alerts": True, "oil": True, "maintenance": True, "predictive": False})
    monkeypatch.setattr(usc, "enabled_predictive_components", lambda client: [])
    for name in ("_telemetry_section", "_alerts_section", "_oil_section", "_maintenance_pareto_section"):
        monkeypatch.setattr(usc, name, lambda *a, _n=name, **k: html.Div(_n, className=_n))
    monkeypatch.setattr(usc, "build_status_tiles", lambda *a: None)
    content = usc.build_unit_summary_content("TESTCO", "U1", {})
    stack = _find(content, html.Div, "unit-stack")[0]
    assert [c.className for c in stack.children] == [
        "_telemetry_section", "_alerts_section", "_oil_section", "_maintenance_pareto_section"]


# ── Predictivo (shared with the Predictivo tab) ─────────────────────────────

def _patch_predictive(monkeypatch):
    import plotly.graph_objects as go

    import dashboard.components.predictive_charts as charts
    import dashboard.components.predictive_config as config

    frame = pd.DataFrame({
        "Unit": ["U1", "U2", "U3"], "status": ["Anormal", "Normal", "Alerta"],
        "ranking": [71.4, 12.0, 40.0], "avg_ranking_7d": [30.0, 5.0, 18.0], "ranking_acum_90d": [20.0, 4.0, 11.0],
    })
    monkeypatch.setattr(usc, "load_status_frame", lambda client, component: frame)
    monkeypatch.setattr(usc, "get_predictive_component_status",
                        lambda client, unit, component: ({"motor": "Anormal", "transmision": "Alerta"}[component], 9.0))
    monkeypatch.setattr("src.data.loaders.get_model_run_date", lambda client, component: datetime(2026, 10, 1))
    monkeypatch.setattr(config, "resolve_failure_modes", lambda component, client: {"failure_a": "Modo A"})
    monkeypatch.setattr(charts, "create_comparative_bars", lambda row, latest, modes: go.Figure())
    monkeypatch.setattr(usc, "short_view_chart", lambda *a, **k: go.Figure())


def test_ranking_hoy_is_the_latest_predictive_value_even_when_the_status_is_stale(monkeypatch):
    _patch_predictive(monkeypatch)
    text = _text(usc._predictive_card("CAPSTONE", "U1", "motor"))
    assert "Ranking hoy: 71" in text
    assert "Posición en la flota: Ranking 7 días (eje X) vs Ranking 90 días (eje Y)" in text


def test_ranking_hoy_is_a_dash_when_the_unit_has_no_value(monkeypatch):
    _patch_predictive(monkeypatch)
    assert "Ranking hoy: —" in _text(usc._predictive_card("CAPSTONE", "NOPE", "motor"))


def test_several_components_become_tabs_labeled_with_name_and_status(monkeypatch):
    _patch_predictive(monkeypatch)
    (block,) = usc._predictive_sections("CAPSTONE", "U1", ["motor", "transmision"])
    tabs = _find(block, html.Button, "unit-tab")
    assert [_text(t) for t in tabs] == ["Motor · Anormal", "Transmisión · Alerta"]
    assert [t.role for t in tabs] == ["tab", "tab"]
    assert [getattr(t, "aria-selected") for t in tabs] == ["true", "false"]
    assert [t.tabIndex for t in tabs] == [0, -1]  # the selected tab is the one tab stop
    (tablist,) = [n for n in _walk(block) if getattr(n, "role", None) == "tablist"]
    assert getattr(tablist, "aria-label") == "Componentes predictivos"
    panel = next(n for n in _walk(block) if getattr(n, "id", None) == usc.PREDICTIVE_PANEL_ID)
    assert "Predictivo · Motor" in _text(panel) and "Transmisión" not in _text(panel)  # only the selected one


def test_choosing_a_tab_selects_it_and_deselects_the_others():
    states = usc.predictive_tab_states("CAPSTONE", "U1", ["motor", "transmision"], "transmision")
    assert states == [("unit-tab", "false", -1), ("unit-tab unit-tab--selected", "true", 0)]


def test_one_component_is_a_plain_card_without_tabs(monkeypatch):
    _patch_predictive(monkeypatch)
    cards = usc._predictive_sections("CAPSTONE", "U1", ["motor"])
    assert len(cards) == 1 and not isinstance(cards[0], dcc.Tabs)


def test_general_scatter_is_the_predictivo_tab_scatter(monkeypatch):
    """Same frame: the figure General draws is the one the Predictivo tab's Short View draws
    (same drawable units, axes, thresholds and zones), with the unit highlighted on top."""
    import dashboard.tabs.tab_predictive_overview as tab

    frame = pd.DataFrame({
        "Unit": ["U1", "U2", "U3"], "status": ["Anormal", "Normal", "Alerta"],
        "ranking": [71.4, 12.0, 40.0], "avg_ranking_7d": [30.0, 5.0, 18.0], "ranking_acum_90d": [20.0, 4.0, 11.0],
        "avg_ranking_30d": [25.0, 6.0, 15.0],
    })
    monkeypatch.setattr(tab, "load_latest_component_meter", lambda *a, **k: None)
    general = tab.short_view_chart(frame, "CAPSTONE", "motor", selected_unit="U1")
    drawable, universe, _groups = tab._short_view_model(frame, "CAPSTONE", "motor")
    predictivo_tab = tab._short_view_figure(drawable, universe, "CAPSTONE", "motor")

    def xs(fig):
        return sorted({float(v) for trace in fig.data if trace.x is not None for v in trace.x} & {5.0, 18.0, 30.0})

    assert xs(general) == xs(predictivo_tab) == [5.0, 18.0, 30.0]  # the 7-day column, as labeled
    assert general.layout.xaxis.title.text == predictivo_tab.layout.xaxis.title.text == "Ranking 7 días"
    assert general.layout.xaxis.range == predictivo_tab.layout.xaxis.range
    assert [s.name for s in general.layout.shapes] == [s.name for s in predictivo_tab.layout.shapes]


# ── Contrast ────────────────────────────────────────────────────────────────

def _luminance(hex_color):
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_chip_and_banner_text_meets_4_5_to_1():
    import re

    css = open("dashboard/assets/status_chip.css", encoding="utf-8").read()
    tokens = dict(re.findall(r"--st-(\w+-\w+): (#[0-9a-f]{6})", css))
    for tier in ("normal", "alerta", "anormal", "nodata"):
        assert _contrast(tokens[f"{tier}-text"], tokens[f"{tier}-bg"]) >= 4.5, tier      # tinted chips
        assert _contrast("#ffffff", tokens[f"{tier}-solid"]) >= 4.5, tier               # solid chips, banners
    detail = open("dashboard/assets/unit_detail.css", encoding="utf-8").read()
    muted = re.search(r"--unit-muted: (#[0-9a-f]{6})", detail).group(1)
    assert _contrast(muted, "#f8f9fa") >= 4.5
    for tier in ("alerta", "anormal"):
        assert _contrast("#fff7ed", tokens[f"{tier}-solid"]) >= 4.5                      # banner captions


# ── Alertas: 12 weeks, Resumen / Listado de Alertas ─────────────────────────

def _alert_feed(unit, weeks_ago):
    """One alert of `unit` for each entry of `weeks_ago` (whole weeks before the reference week)."""
    reference = pd.Timestamp.now()
    return pd.DataFrame({
        "UnitId": [unit] * len(weeks_ago),
        "Timestamp": [reference - pd.Timedelta(weeks=w, hours=1) for w in weeks_ago],
        "sistema": ["Motor"] * len(weeks_ago),
        "componente": ["Admission Lbf"] * len(weeks_ago),
        "FusionID": [f"ID-{i}" for i in range(len(weeks_ago))],
        "Trigger_type": ["Telemetria"] * len(weeks_ago),
        "Trigger_Var": ["temp"] * len(weeks_ago),
        "mensaje_ia": [""] * len(weeks_ago),
    })


def _patch_alert_feed(monkeypatch, feed):
    monkeypatch.setattr(usc, "latest_alert_timestamp", lambda client: feed["Timestamp"].max() if len(feed) else None)
    monkeypatch.setattr(usc, "load_alerts_since", lambda client, since: feed)
    monkeypatch.setattr(usc, "_alerts_data_date", lambda client: None)


def _chart_totals(card):
    graph = _find(card, dcc.Graph)[0]
    weeks = list(dict.fromkeys(str(x) for trace in graph.figure.data for x in trace.x))
    return weeks, sum(float(v) for trace in graph.figure.data for v in trace.y), graph.figure


def test_alerts_chart_covers_twelve_weeks_including_empty_ones(monkeypatch):
    _patch_alert_feed(monkeypatch, _alert_feed("U1", [0, 0, 3, 11]))
    weeks, total, figure = _chart_totals(usc._alerts_section("TESTCO", "U1", "Alerta"))
    assert len(weeks) == usc.ALERTS_WINDOW_WEEKS == 12
    assert total == 4
    zero_labels = [a.x for a in figure.layout.annotations if a.text == "0"]
    assert len(zero_labels) == 12 - 3  # three weeks have alerts; each of the other nine reads 0


def test_alerts_older_than_the_window_are_left_out_and_other_units_never_count(monkeypatch):
    feed = pd.concat([_alert_feed("U1", [1, 12, 20]), _alert_feed("U2", [1, 2])], ignore_index=True)
    _patch_alert_feed(monkeypatch, feed)
    card = usc._alerts_section("TESTCO", "U1", "Alerta")
    assert _chart_totals(card)[1] == 1
    assert _find(card, dcc.Tabs)[0].children[1].label == "Listado de Alertas (1)"


def test_alerts_section_has_resumen_by_default_and_a_listado_tab_with_the_count(monkeypatch):
    _patch_alert_feed(monkeypatch, _alert_feed("U1", [0, 1, 2]))
    card = usc._alerts_section("TESTCO", "U1", "Alerta")
    (tabs,) = _find(card, dcc.Tabs)
    assert tabs.value == usc.ALERTS_TAB_SUMMARY
    assert [tab.label for tab in tabs.children] == ["Resumen", "Listado de Alertas (3)"]
    assert all("pred-tab" in tab.className.split() for tab in tabs.children)  # indicator under its own label
    assert _chart_totals(card)[1] == 3  # the tab's count is the chart's total


def test_alerts_list_has_the_requested_columns_a_link_per_row_and_the_legend(monkeypatch):
    _patch_alert_feed(monkeypatch, _alert_feed("U1", [0, 1]))
    panel = usc.alerts_panel("TESTCO", "U1", usc.ALERTS_TAB_LIST)
    (table,) = [n for n in _walk(panel) if type(n).__name__ == "DataTable"]
    assert [c["name"] for c in table.columns][:6] == ["Fecha", "Fuente", "Sistema", "Componente", "Alerta", "Resumen"]
    assert "Unidad" not in [c["name"] for c in table.columns]
    assert table.sort_action == "native" and table.page_action == "native"
    assert len(table.data) == 2
    # every row has its own link to the alert's detail
    hrefs = {row["Detalle"].split("](")[1].rstrip(")") for row in table.data}
    assert hrefs == {fo.relative_path("/monitoring/alerts?alert=ID-0"), fo.relative_path("/monitoring/alerts?alert=ID-1")}
    assert "Telemetría" in _text(panel) and "Tribología" in _text(panel) and "Multitécnica" in _text(panel)


def test_unit_without_alerts_in_the_window_gets_the_message_and_a_zero_count(monkeypatch):
    _patch_alert_feed(monkeypatch, _alert_feed("U9", [1, 2]))
    card = usc._alerts_section("TESTCO", "U1", "Normal")
    assert _find(card, dcc.Tabs)[0].children[1].label == "Listado de Alertas (0)"
    panel = usc.alerts_panel("TESTCO", "U1", usc.ALERTS_TAB_LIST)
    assert "Sin alertas registradas para esta unidad en las últimas 12 semanas." in _text(panel)
    assert not [n for n in _walk(panel) if type(n).__name__ == "DataTable"]


# ── Redirect buttons ────────────────────────────────────────────────────────

def _links(card):
    return [(_text(l), l.href) for l in _find(card, dcc.Link, "unit-btn")]


def test_alertas_has_one_section_button_to_the_unit_filtered_alerts(monkeypatch):
    _patch_alert_feed(monkeypatch, _alert_feed("U1", [0]))
    assert _links(usc._alerts_section("TESTCO", "U1", "Alerta")) == [("Ver en Alertas", fo.relative_path("/monitoring/alerts?unit=U1"))]


def test_tribologia_has_one_button_per_component_row_with_that_rows_component(monkeypatch):
    rows = [
        OilComponentRow("Motor Diesel", "Alerta", "Desgaste", None, pd.Timestamp("2026-06-18"), raw_component="MOTOR DIESEL"),
        OilComponentRow("Mando Final", "Normal", None, None, pd.Timestamp("2026-06-10"), raw_component="MANDO FINAL"),
    ]
    monkeypatch.setattr(usc, "unit_oil_components", lambda client, unit: rows)
    links = _links(usc._oil_section("TESTCO", "U1", "Alerta"))
    assert [href for _text_, href in links] == [
        fo.relative_path("/monitoring/oil?unit=U1&component=MOTOR%20DIESEL"),
        fo.relative_path("/monitoring/oil?unit=U1&component=MANDO%20FINAL")]
    assert all(text.startswith("Ver en Tribología") for text, _ in links)


def test_predictivo_button_is_in_the_card_header_and_opens_that_component(monkeypatch):
    _patch_predictive(monkeypatch)
    card = usc._predictive_card("CAPSTONE", "U1", "motor")
    assert _links(card) == [("Ver en Predictivo (Motor)", fo.relative_path("/predictive/motor?unit=U1"))]
    header = _find(card, dbc.CardHeader)[0]
    assert _find(header, dcc.Link, "unit-btn")


def test_registry_urls_escape_what_is_not_url_safe():
    from dashboard.services_registry import alert_detail_path, alerts_unit_path, oil_evidence_path, predictive_detail_path

    assert alerts_unit_path("T 9&x") == "/monitoring/alerts?unit=T%209%26x"
    assert alert_detail_path("CAP-1/2") == "/monitoring/alerts?alert=CAP-1%2F2"
    assert oil_evidence_path("CA-80", "MOTOR DIESEL") == "/monitoring/oil?unit=CA-80&component=MOTOR%20DIESEL"
    assert predictive_detail_path("transmision", "T_09") == "/predictive/transmision?unit=T_09"


def test_target_pages_open_with_what_the_url_asks_for():
    from dashboard.tabs.tab_alerts import create_layout as alerts_layout
    from dashboard.tabs.tab_alerts_general import create_layout as general_layout
    from dashboard.tabs.tab_oil import create_layout as oil_layout

    def by_id(root, component_id):
        return next(n for n in _walk(root) if getattr(n, "id", None) == component_id)

    assert by_id(alerts_layout(), "alerts-internal-tabs").value == "general"
    assert by_id(alerts_layout(), "alerts-url-seed").data is None
    assert by_id(alerts_layout(unit="U1"), "alerts-url-seed").data == {"unit": "U1", "alert": None}
    assert by_id(alerts_layout(alert="A-1"), "alerts-internal-tabs").value == "detail"
    assert by_id(general_layout(initial_filters={"unit": ["U1"]}), "alerts-general-active-filters").data == {"unit": ["U1"]}
    assert by_id(general_layout(), "alerts-general-active-filters").data == {}
    assert by_id(oil_layout(), "oil-internal-tabs").value == "fleet-overview"
    assert by_id(oil_layout(unit="U1", component="C"), "oil-internal-tabs").value == "report-detail"
    assert by_id(oil_layout(unit="U1"), "oil-internal-tabs").value == "fleet-overview"  # both are needed
