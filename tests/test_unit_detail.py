"""
Unit Detail (dashboard/components/unit_summary.py + unit_summary_content.py): banner,
"Estado por Técnica" tiles, Telemetría / Tribología rows, Pareto period, Predictivo
titles and the navigation bar (ui_notes_improved.md, Unit Detail requirements).

The data sources are replaced by canned values: nothing here reads the data mirror.
"""

from datetime import date, datetime

import pandas as pd
import pytest
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
    assert [_text(th) for th in _find(table, html.Th)] == ["Componente", "Estado", "Anomalía", "Diagnóstico"]


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


# ── Navigation bar ──────────────────────────────────────────────────────────

def test_navigation_bar_has_a_labeled_select_and_all_controls():
    ordered = [{"unit": u, "band": "Normal"} for u in ("U1", "U2", "U3")]
    bar = us._navigation_bar(ordered, "U1", None, "U2")
    text = _text(bar)
    for control in ("Fleet Overview", "Volver a Fleet Overview", "Primera unidad", "Cambiar unidad", "Siguiente"):
        assert control in text
    (label,) = _find(bar, html.Label)
    (select,) = _find(bar, html.Select)
    assert label.htmlFor == select.id
    assert [o.value.endswith(fo.unit_summary_path(u)) for o, u in zip(_find(select, html.Option), ("U1", "U2", "U3"))] == [True] * 3
    assert [o.selected for o in _find(select, html.Option)] == [True, False, False]


def test_navigation_bar_and_banner_do_not_float_over_the_content():
    ordered = [{"unit": "U1", "band": "Normal"}]
    bar = us._navigation_bar(ordered, "U1", None, None)
    assert not any("sticky" in str(getattr(n, "style", "")) for n in _walk(bar))
    assert bar.className == "unit-nav"  # the stylesheet keeps it in flow (no position rule)
    css = open("dashboard/assets/unit_detail.css", encoding="utf-8").read()
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
    monkeypatch.setattr(usc, "load_alerts_data", lambda client: pd.DataFrame())
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
    monkeypatch.setattr(usc, "load_alerts_data", lambda client: feed)
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


def test_monitoreo_pairs_telemetry_with_alerts_and_stacks_the_rest(monkeypatch):
    monkeypatch.setattr(usc, "applicable_techniques", lambda client: {
        "telemetry": True, "alerts": True, "oil": True, "maintenance": True, "predictive": False})
    monkeypatch.setattr(usc, "enabled_predictive_components", lambda client: [])
    for name in ("_telemetry_section", "_alerts_section", "_oil_section", "_maintenance_pareto_section"):
        monkeypatch.setattr(usc, name, lambda *a, _n=name, **k: html.Div(_n, className=_n))
    monkeypatch.setattr(usc, "build_status_tiles", lambda *a: None)
    content = usc.build_unit_summary_content("TESTCO", "U1", {})
    stack = _find(content, html.Div, "unit-stack")[0]
    assert [c.className for c in stack.children] == ["unit-pair", "_oil_section", "_maintenance_pareto_section"]
    assert [c.className for c in stack.children[0].children] == ["_telemetry_section", "_alerts_section"]


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
