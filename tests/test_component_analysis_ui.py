"""Análisis por Componente (Monitor de Aceite): the tab layout, the KPI tiles, the cards and the matrix.

The data layer is replaced by a synthetic client, so the figures can be checked by hand; the real
`classified.parquet` files are covered by a smoke test at the end (skipped when the data is absent).
"""

import json
import pathlib
import re

import pandas as pd
import pytest
from dash.development.base_component import Component

from src.data import component_analysis as ca
from src.i18n import forced_language, load_catalog
from src.utils.dash_ids import from_id_text, id_text

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = ca.local_today()


# ---- Helpers ----------------------------------------------------------------------------------------------

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


def of_type(node, name):
    return [c for c in walk(node) if type(c).__name__ == name]


def by_id(node, component_id):
    return next((c for c in walk(node) if getattr(c, "id", None) == component_id), None)


def with_class(node, name):
    return [c for c in walk(node) if name in str(getattr(c, "className", "") or "").split()]


def breach(essay, threshold="Marginal", group="Desgaste", use=1):
    return {"essay": essay, "value": 1.0, "threshold": threshold, "limit": 1.0, "points": 1, "group": group,
            "use_for_classification": use, "direction": "upper"}


def sample(unit, days_ago, status="Normal", component="diferencial trasero", normalized="diferencial", anomaly=None,
           breaches=(), hours=1000.0, oil=500.0, fleet="camion", previous_days_ago=None):
    when = pd.Timestamp(TODAY) - pd.Timedelta(days=days_ago)
    return {
        "unitId": unit, "machineName": fleet, "componentName": component, "componentNameNormalized": normalized,
        "sampleDate": when, "reportDate": when + pd.Timedelta(days=1),
        "previousSampleDate": (pd.Timestamp(TODAY) - pd.Timedelta(days=previous_days_ago)
                               if previous_days_ago is not None else pd.NaT),
        "report_status": status, "anomalyType": anomaly if anomaly is not None else ("Normal" if status == "Normal" else None),
        "componentHours": hours, "oilMeter": oil, "breached_essays": json.dumps(list(breaches)),
    }


def _classified():
    """40 units with one differential each (3 Anormal, 32 Alerta, 5 Normal), ages 5, 8, 11... days; U00 also
    has a front differential (Anormal, no essay out of limit that counts) and a motor; plus two units
    sampled exactly 90 and 91 days ago, and a unit of another fleet."""
    rows = []
    for i in range(40):
        status = "Anormal" if i < 3 else "Alerta" if i < 35 else "Normal"
        breaches = [] if status == "Normal" else [breach("Hierro", "Critico" if i % 4 == 0 else "Marginal"),
                                                  breach("Sodio", "Marginal", "Contaminante"),
                                                  breach("Zinc", "Marginal", "Aditivo", use=0)]
        rows.append(sample(f"U{i:02d}", 5 + 3 * i, status, anomaly=None if status == "Normal" else (
            "Desgaste de Componentes" if i % 2 else "Contaminación Lubricante"), breaches=breaches,
            previous_days_ago=(5 + 3 * i) + 30, hours=None if i == 1 else 4000.0 + i))
        rows.append(sample(f"U{i:02d}", 5 + 3 * i + 30, "Normal"))                  # the previous sample
    rows.append(sample("U00", 6, "Anormal", component="diferencial delantero", anomaly="Desgaste de Componentes",
                       breaches=[breach("Zinc", "Critico", "Aditivo", use=0)]))
    rows.append(sample("U00", 4, "Alerta", component="motor", normalized="motor", anomaly="Desgaste de Componentes"))
    rows.append(sample("U90", 90, "Normal"))
    rows.append(sample("U91", 91, "Normal"))
    rows.append(sample("P01", 5, "Alerta", fleet="pala", anomaly="Desgaste de Componentes"))
    return pd.DataFrame(rows)


@pytest.fixture
def mod(monkeypatch):
    from dashboard.components import oil_component_analysis as o

    frame = _classified()

    class _Path:
        def exists(self):
            return True

    class _Settings:
        get_classified_reports_path = staticmethod(lambda client: _Path())

    monkeypatch.setattr(o, "get_settings", lambda: _Settings())
    monkeypatch.setattr(o, "load_oil_classified", lambda client: frame.copy())
    return o


@pytest.fixture
def source(mod):
    return mod.build_source("cda", "camion", "diferencial")


def view(**kw):
    return {"sort": None, "page": 0, "rev": None, "expanded": False, **kw}


def matrix(mod, source, show="todos", include_all=False, **kw):
    return mod.render_matrix(source, view(**kw), show, include_all, TODAY)[2]


def body_rows(block):
    table = of_type(block, "Table")[0]
    return of_type(next(c for c in table.children if type(c).__name__ == "Tbody"), "Tr")


def cells(row):
    return [c for c in row.children if type(c).__name__ in ("Th", "Td")]


def header_row(block):
    thead = of_type(block, "Table")[0].children[0]
    return thead.children if isinstance(thead.children, Component) else thead.children[0]


def header_labels(block):
    return [text_of(c).replace("↕", "").replace("▲", "").replace("▼", "").strip() for c in cells(header_row(block))]


def row_by_unit(block, unit, component="diferencial trasero"):
    for row in body_rows(block):
        opener = of_type(cells(row)[0], "Button")[0]
        if from_id_text(opener.id["unit"]) == unit and from_id_text(opener.id["component"]) == component:
            return row
    raise AssertionError(f"{unit} / {component} is not on this page")


# ---- The tab and its controls -----------------------------------------------------------------------------

def test_the_selector_has_four_pressable_options_and_motor_is_the_default():
    from dashboard.tabs.tab_component_analysis import SELECTOR_LABEL_ID, create_component_analysis_tab

    layout = create_component_analysis_tab()
    buttons = [b for b in of_type(layout, "Button") if isinstance(b.id, dict) and b.id.get("type") == "ca-component"]
    assert [text_of(b) for b in buttons] == ["Motor", "Transmisión", "Convertidor", "Diferencial"]
    assert [b.id["key"] for b in buttons] == ["motor", "transmision", "convertidor", "diferencial"]
    pressed = [b.to_plotly_json()["props"]["aria-pressed"] for b in buttons]
    assert pressed == ["true", "false", "false", "false"]
    group = [c for c in walk(layout) if getattr(c, "role", None) == "group"][0]
    assert group.to_plotly_json()["props"]["aria-labelledby"] == SELECTOR_LABEL_ID
    assert text_of(by_id(layout, SELECTOR_LABEL_ID)) == "Componente"
    assert by_id(layout, "ca-component").data == "motor"


def test_the_selector_comes_above_the_title_and_the_criticality_chip_is_next_to_it():
    from dashboard.tabs.tab_component_analysis import create_component_analysis_tab

    layout = create_component_analysis_tab()
    nodes = list(walk(layout))
    assert nodes.index(by_id(layout, "ca-criticality")) < nodes.index(by_id(layout, "ca-header"))
    assert text_of(by_id(layout, "ca-criticality")) == "Criticidad del componente: Crítico"
    heading = of_type(by_id(layout, "ca-header"), "H3")[0]
    assert text_of(heading).split() == ["Análisis", "de", "Motor", "Preview"]


def test_flota_is_the_only_filter_and_there_is_no_site_or_area_filter():
    from dashboard.tabs.tab_component_analysis import create_component_analysis_tab

    layout = create_component_analysis_tab()
    dropdowns = {d.id for d in of_type(layout, "Dropdown")}
    assert dropdowns == {"ca-fleet-filter", "ca-show"}                    # "Mostrar" is a control of the matrix, not a filter
    labels = {l.htmlFor: text_of(l) for l in of_type(layout, "Label")}
    assert labels["ca-fleet-filter"] == "Flota (Tipo de Equipo)"
    ids = [c.id for c in walk(layout) if isinstance(getattr(c, "id", None), str)]
    assert not [i for i in ids if "site" in i or "area" in i or "sitio" in i]      # no Sitio / Área control anywhere
    assert not [text_of(l) for l in of_type(layout, "Label") if "Sitio" in text_of(l) or "Área" in text_of(l)]


def test_the_matrix_controls_and_defaults():
    from dashboard.tabs.tab_component_analysis import create_component_analysis_tab

    layout = create_component_analysis_tab()
    show = by_id(layout, "ca-show")
    assert [o["label"] for o in show.options] == ["Anormal y Alerta", "Solo Anormal", "Todos"]
    assert show.value == "alerta_anormal" and show.clearable is False
    checkbox = by_id(layout, "ca-include-all")
    assert checkbox.label == "Incluir ensayos que no afectan el estado" and checkbox.value is False
    assert "Mostrar" in text_of([l for l in of_type(layout, "Label") if l.htmlFor == "ca-show"])
    footnote = text_of(with_class(layout, "oil-footnote")[-1])
    for part in ("ordenadas por el número de muestras", "«—»", "modelo del laboratorio", "vs Muestra Anterior"):
        assert part in footnote


def test_the_matrix_legend_names_both_levels_and_the_critical_merge():
    from dashboard.tabs.tab_component_analysis import create_component_analysis_tab

    legend = text_of(with_class(create_component_analysis_tab(), "oil-level-legend"))
    assert "Cond." in legend and "Condenatorio" in legend and "Marg." in legend and "Marginal" in legend
    assert "(condenatorio incluye valores críticos)" in legend


# ---- The page follows the selection -----------------------------------------------------------------------

@pytest.mark.parametrize("key, title, plural, article, chip", [
    ("motor", "Motor", "motores", "los motores", "Crítico"),
    ("transmision", "Transmisión", "transmisiones", "las transmisiones", "Crítico"),
    ("convertidor", "Convertidor", "convertidores", "los convertidores", "Importante"),
    ("diferencial", "Diferencial", "diferenciales", "los diferenciales", "Importante"),
])
def test_every_option_has_its_words_and_criticality(key, title, plural, article, chip):
    from dashboard.components.oil_component_analysis import criticality_text, words

    w = words(key)
    assert (w.title, w.plural, w.the_plural) == (title, plural, article)
    assert criticality_text(ca.load_config(), key) == f"Criticidad del componente: {chip}"


def test_selecting_diferencial_changes_the_title_the_nouns_and_every_element(mod, source):
    header = text_of(mod.render_header(source))
    assert "Análisis de Diferencial" in header and "Preview" in header
    assert "los diferenciales" in header and "cada diferencial" in header
    assert "(último reporte validado)" in header and "Vista en desarrollo" in header

    kpis = mod.render_kpis(source, TODAY)
    assert text_of(kpis).startswith("Diferenciales")
    assert "% de los diferenciales" in text_of(kpis)
    age = text_of(mod.render_age_card(source, TODAY))
    assert "Días desde la última muestra de cada diferencial" in age and "actual del diferencial" in age
    assert "Diferenciales en Alerta o Anormal" in text_of(mod.render_anomaly_card(source))
    title, chip, _ = mod.render_matrix(source, view(), "todos", False, TODAY)
    assert title == "Qué Explica el Estado de cada Diferencial"
    assert text_of(chip) == "43 de 43 diferenciales"


def test_the_words_follow_the_language(mod, source):
    with forced_language("en"):
        assert "Differential Analysis" in text_of(mod.render_header(source))
        assert mod.matrix_title(source) == "What Explains the Status of Each Differential"


def test_nothing_is_displayed_without_a_fleet_but_the_data_date_is(mod):
    data = mod.build_source("cda", None, "diferencial")
    assert data["message"] == "component_analysis.seleccione_una_flota" and data["rows"] == []
    assert data["as_of"] == (pd.Timestamp(TODAY) - pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    assert "Datos al" in text_of(mod.render_header(data))
    assert text_of(mod.render_matrix(data, view(), "todos", False, TODAY)[2]) == "Seleccione una flota para ver el análisis."
    assert mod.build_source(None, "camion", "motor")["message"] == "fleet_overview.select_client"


def test_a_fleet_without_the_component_says_so(mod):
    data = mod.build_source("cda", "pala", "motor")
    assert data["message"] == "component_analysis.sin_componentes"
    assert text_of(mod.render_matrix(data, view(), "todos", False, TODAY)[2]) == "No hay motores con muestras en la flota seleccionada."


def test_the_data_date_is_the_latest_report_of_the_client(mod, source):
    assert source["as_of"] == (pd.Timestamp(TODAY) - pd.Timedelta(days=3)).strftime("%Y-%m-%d")   # U00's motor, dated 4 days ago, reported 3


# ---- KPI tiles and the age card ---------------------------------------------------------------------------

def _tiles(mod, source):
    out = {}
    for card in of_type(mod.render_kpis(source, TODAY), "Card"):
        label = text_of(with_class(card, "kpi-label")[0])
        out[label] = {"value": int(text_of(with_class(card, "kpi-value")[0])), "chip": text_of(with_class(card, "kpi-chip")[0]),
                      "caption": text_of(with_class(card, "kpi-caption")[0]), "card": card}
    return out


def test_tile_counts_match_the_latest_estado_and_add_up_to_the_first_tile(mod, source):
    tiles = _tiles(mod, source)
    assert list(tiles) == ["Diferenciales", "Anormal", "Alerta", "Normal", "Estado desactualizado"]
    total = tiles["Diferenciales"]["value"]
    assert total == 43 and len(source["rows"]) == 43
    assert (tiles["Anormal"]["value"], tiles["Alerta"]["value"], tiles["Normal"]["value"]) == (4, 32, 5 + 2)
    assert tiles["Anormal"]["value"] + tiles["Alerta"]["value"] + tiles["Normal"]["value"] == total
    assert [tiles[k]["chip"] for k in tiles] == ["Con muestra", "Anormal", "Alerta", "Normal", "Revisar"]
    assert tiles["Diferenciales"]["caption"] == "en la flota seleccionada"
    assert tiles["Anormal"]["caption"] == "9 % de los diferenciales"
    assert tiles["Alerta"]["caption"] == "74 % de los diferenciales"
    assert tiles["Estado desactualizado"]["caption"] == "con última muestra de más de 90 días"


def test_tile_colors_come_from_the_severity_tiers(mod, source):
    from shared.severity import SEVERITY_TIERS

    tiles = _tiles(mod, source)
    for label, tier in (("Anormal", "alto"), ("Alerta", "atencion"), ("Normal", "bajo")):
        chip = with_class(tiles[label]["card"], "kpi-chip")[0]
        assert chip.style["background"] == SEVERITY_TIERS[tier]["bg"] and chip.style["color"] == SEVERITY_TIERS[tier]["text"]
        fill = with_class(tiles[label]["card"], "kpi-gauge-fill")[0]
        assert fill.style["background"] == SEVERITY_TIERS[tier]["fill"]
    for label in ("Diferenciales", "Estado desactualizado"):             # neutral: no severity threshold
        assert with_class(tiles[label]["card"], "kpi-chip")[0].style["background"] == "#f1f5f9"


def test_estado_desactualizado_counts_older_than_90_days_and_equals_the_last_age_bucket(mod, source):
    stale = _tiles(mod, source)["Estado desactualizado"]["value"]
    # U29..U39 are 92..122 days old (11 units), U91 is 91 days, U90 (exactly 90) is still current.
    assert stale == 12
    legend = text_of(with_class(mod.render_age_card(source, TODAY), "oil-legend"))
    assert f"Más de 90 días: {stale} (" in legend
    fleet_total = len(source["rows"])
    buckets = ca.age_buckets(source["rows"], ca.load_config(), TODAY)
    assert sum(b["count"] for b in buckets) == fleet_total
    assert buckets[2]["count"] >= 1                                       # U90 sits in "61 a 90 días"


def test_the_age_card_is_one_stacked_bar_with_four_buckets_a_legend_and_the_note(mod, source):
    card = mod.render_age_card(source, TODAY)
    bar = with_class(card, "oil-agebar")[0]
    segments = with_class(bar, "oil-agebar__seg")
    assert len(segments) == 4
    widths = [float(s.style["width"].rstrip("%")) for s in segments]
    assert abs(sum(widths) - 100.0) < 0.1
    fills = [s.style["background"] for s in segments]
    assert fills[-1] == "#f59e0b" and len(set(fills[:3])) == 3 and all(f.startswith("#") for f in fills)
    legend = [text_of(li) for li in of_type(with_class(card, "oil-legend")[0], "Li")]
    assert [l.split(":")[0] for l in legend] == ["30 días o menos", "31 a 60 días", "61 a 90 días", "Más de 90 días"]
    assert all(re.search(r": \d+ \(\d+ %\)$", l) for l in legend)
    assert "Con más de 90 días, el estado puede no reflejar la condición actual del diferencial." in text_of(card)


def test_the_threshold_of_the_tab_comes_from_the_configuration(mod, source, monkeypatch):
    tight = ca.parse_config({"stale_days": 30, "age_edges": [10], "components": {
        "diferencial": {"criticality": "importante", "names": ["diferencial"]}}})
    monkeypatch.setattr(ca, "load_config", lambda path=None: tight)
    tiles = _tiles(mod, source)
    assert tiles["Estado desactualizado"]["value"] == len([r for r in source["rows"]
                                                           if ca.days_since(r["sample_date"], TODAY) > 30])
    assert tiles["Estado desactualizado"]["caption"] == "con última muestra de más de 30 días"
    assert "Más de 30 días" in text_of(mod.render_age_card(source, TODAY))


# ---- Anomaly and essay cards ------------------------------------------------------------------------------

def test_anomaly_card_has_one_bar_per_type_with_its_figures_and_both_colors(mod, source):
    card = mod.render_anomaly_card(source)
    items = of_type(card, "Li")
    bars = [i for i in items if "oil-hbar" in str(i.className).split()]
    labels = [text_of(b) for b in bars]
    assert len(bars) == 2 and sum(int(re.search(r"(\d+) ·", l).group(1)) for l in labels) == 4 + 32
    assert all(re.search(r"\d+ · \d+ anormales? · \d+ alerta", l) for l in labels)
    fills = {s.style["background"] for s in with_class(card, "oil-hbar__seg")}
    assert fills <= {"#dc2626", "#f59e0b"}
    legend = text_of(with_class(card, "oil-legend")[0])
    assert "Anormal" in legend and "Alerta" in legend
    tracks = with_class(card, "oil-hbar__track")
    assert all(t.to_plotly_json()["props"].get("aria-hidden") == "true" for t in tracks)   # the figures are in the text


def test_a_single_anormal_reads_in_the_singular(mod):
    only = {"component": "diferencial", "rows": [{"estado": "Anormal", "anomaly": "Desgaste de Componentes", "breaches": []}]}
    assert "1 · 1 anormal · 0 alerta" in text_of(mod.render_anomaly_card(only))


def test_essay_card_shows_group_chip_levels_and_ignores_essays_that_do_not_classify(mod, source):
    card = mod.render_essay_card(source, include_all=False)
    labels = [text_of(i) for i in of_type(card, "Li") if "oil-hbar" in str(i.className).split()]
    assert labels == ["Hierro Desgaste 35 muestras · 9 cond. · 26 marg.",     # Zinc does not classify: no bar for it
                      "Sodio Contaminante 35 muestras · 0 cond. · 35 marg."]       # equal counts: more condenatorio first
    assert {text_of(c) for c in with_class(card, "kpi-chip")} == {"Desgaste", "Contaminante"}
    fills = {s.style["background"] for s in with_class(card, "oil-hbar__seg")}
    assert fills <= {"#dc2626", "#f59e0b"}
    legend = text_of(card)
    assert "Condenatorio" in legend and "Marginal" in legend and "(condenatorio incluye valores críticos)" in legend


def test_the_checkbox_adds_the_essays_that_do_not_affect_the_state_to_the_card_and_the_matrix(mod, source):
    narrow = text_of(mod.render_essay_card(source, False))
    wide = text_of(mod.render_essay_card(source, True))
    assert "Zinc" not in narrow and "Zinc" in wide and "Aditivo" in wide
    assert "Zinc" not in header_labels(matrix(mod, source, include_all=False))
    assert "Zinc" in header_labels(matrix(mod, source, include_all=True))


def test_essay_columns_follow_the_order_of_the_essay_card(mod, source):
    for include_all in (False, True):
        card_order = [text_of(with_class(li, "oil-hbar__name")[0]).split(" ")[0]
                      for li in of_type(mod.render_essay_card(source, include_all), "Li") if "oil-hbar" in str(li.className).split()]
        columns = header_labels(matrix(mod, source, include_all=include_all))[8:]
        assert columns == card_order


def test_a_card_with_nothing_to_rank_says_so(mod):
    quiet = {"component": "diferencial", "rows": [{"estado": "Normal", "anomaly": None, "breaches": []}]}
    assert "No hay diferenciales en Alerta o Anormal." in text_of(mod.render_anomaly_card(quiet))
    assert "No hay ensayos fuera de límite para mostrar." in text_of(mod.render_essay_card(quiet))


# ---- The matrix -------------------------------------------------------------------------------------------

def test_matrix_columns_and_the_chip(mod, source):
    title, chip, block = mod.render_matrix(source, view(), "alerta_anormal", False, TODAY)
    assert header_labels(block)[:8] == ["Unidad", "Estado", "Tipo de Anomalía", "Ensayos Fuera de Límite", "Última Muestra",
                                        "vs Muestra Anterior", "Horas del Componente", "Horas del Aceite"]
    assert text_of(chip) == "36 de 43 diferenciales"                       # 4 Anormal + 32 Alerta of 43
    assert text_of(mod.render_matrix(source, view(), "todos", False, TODAY)[1]) == "43 de 43 diferenciales"
    assert text_of(mod.render_matrix(source, view(), "anormal", False, TODAY)[1]) == "4 de 43 diferenciales"


def test_a_unit_with_two_differentials_appears_as_two_rows_each_with_its_own_component_name(mod, source):
    block = matrix(mod, source, show="anormal")
    rows = [r for r in body_rows(block) if of_type(cells(r)[0], "Button")[0].id["unit"] == "U00"]
    assert sorted(text_of(cells(r)[0]) for r in rows) == ["U00 Diferencial Delantero", "U00 Diferencial Trasero"]


def test_rows_come_anormal_first_then_alerta_and_a_row_without_essays_says_zero(mod, source):
    block = matrix(mod, source, show="todos")
    both_pages = body_rows(block) + body_rows(matrix(mod, source, show="todos", page=1))
    estados = [text_of(cells(r)[1]) for r in both_pages]
    assert len(estados) == 43 and estados == sorted(estados, key=["Anormal", "Alerta", "Normal"].index)
    assert estados[:4] == ["Anormal"] * 4 and estados[-7:] == ["Normal"] * 7
    front = row_by_unit(block, "U00", "diferencial delantero")           # Anormal whose only breach does not classify
    assert "0 ensayos" in text_of(cells(front)[3]) and "0 cond. · 0 marg." in text_of(cells(front)[3])
    assert all(text_of(c) == "—" for c in cells(front)[8:])              # nothing but dashes, and no error


def test_the_cells_of_a_row(mod, source):
    block = matrix(mod, source, show="todos")
    row = row_by_unit(block, "U01")                                       # Anormal, 8 days, no component hours
    unit, estado, anomaly, essays, last, trend, comp_hours, oil_hours = [text_of(c) for c in cells(row)[:8]]
    assert unit == "U01 Diferencial Trasero" and estado == "Anormal" and anomaly == "Desgaste de Componentes"
    assert essays == "2 ensayos\n0 cond. · 2 marg."                        # value on the first line, its levels under it
    assert last == f"{(pd.Timestamp(TODAY) - pd.Timedelta(days=8)).strftime('%Y-%m-%d')} · 8 d"       # current: one line, no flag
    assert trend == "Empeorando\nAntes: Normal"                             # Normal before, Anormal now
    assert comp_hours == "—" and oil_hours == "500 h"


def test_trend_words_and_before_text(mod, source):
    block, page_two = matrix(mod, source, show="todos"), matrix(mod, source, show="todos", page=1)
    worse = cells(row_by_unit(block, "U05"))[5]                            # Alerta now, Normal before
    assert text_of(worse) == "Empeorando\nAntes: Normal" and "oil-trend--worsening" in worse.className
    normal = cells(row_by_unit(page_two, "U36"))[5]                        # Normal now, Normal before
    assert text_of(normal) == "Sin cambio\nEstado: Normal" and "oil-trend--unchanged" in normal.className
    first = cells(row_by_unit(block, "U00", "diferencial delantero"))[5]
    assert text_of(first) == "Sin muestra anterior" and "oil-trend--none" in first.className
    improving = [c for r in body_rows(block) + body_rows(page_two) for c in [cells(r)[5]] if "oil-trend--improving" in str(c.className)]
    assert not improving                                                   # nothing in this fixture got better


def test_hours_use_a_thousands_separator_and_a_dash_when_missing(mod, source):
    row = row_by_unit(matrix(mod, source, show="todos"), "U02")
    assert text_of(cells(row)[6]) == "4,002 h"
    assert text_of(cells(row_by_unit(matrix(mod, source, show="todos"), "U01"))[6]) == "—"


def test_a_sample_older_than_90_days_is_flagged_desactualizada(mod, source):
    block = matrix(mod, source, show="todos", page=1)
    assert "Desactualizada" in text_of(cells(row_by_unit(block, "U91"))[4])
    assert "Desactualizada" not in text_of(cells(row_by_unit(block, "U90"))[4])


def test_essay_cells_are_pills_that_open_the_report_and_a_dash_is_neither_clickable_nor_focusable(mod, source):
    block = matrix(mod, source, show="todos")
    columns = header_labels(block)
    row = row_by_unit(block, "U03")                                       # Alerta with Hierro and Sodio out of limit
    hierro = cells(row)[columns.index("Hierro")]
    button = of_type(hierro, "Button")[0]
    assert text_of(button) in ("Cond.", "Marg.")
    assert button.id == {"type": "ca-open", "unit": "U03", "component": "diferencial trasero", "cell": "Hierro"}
    assert from_id_text(button.id["component"]) == "diferencial trasero"
    assert "Hierro" in button.to_plotly_json()["props"]["aria-label"] and "U03" in button.to_plotly_json()["props"]["aria-label"]
    assert button.style["background"] in ("#fee2e2", "#fef3c7")           # severity tints (alto / atencion)
    normal = row_by_unit(matrix(mod, source, show="todos", page=1), "U36")      # Normal: nothing out of limit
    dash = cells(normal)[columns.index("Hierro")]
    assert text_of(dash) == "—" and not of_type(dash, "Button") and not of_type(dash, "A")
    assert "tabIndex" not in repr(dash.to_plotly_json()) and "tabindex" not in repr(dash.to_plotly_json()).lower()


def test_the_unit_is_a_link_to_the_report_of_its_row(mod, source):
    row = row_by_unit(matrix(mod, source, show="todos"), "U00", "diferencial delantero")
    opener = of_type(cells(row)[0], "Button")[0]
    assert opener.id == {"type": "ca-open", "unit": "U00", "component": "diferencial delantero", "cell": "unit"}
    assert "oil-unit-btn" in opener.className


def test_estado_pills_are_solid_for_alerta_and_anormal_and_light_for_normal(mod, source):
    pills = {text_of(p): p.style for p in with_class(matrix(mod, source, show="todos"), "status-chip")
             + with_class(matrix(mod, source, show="todos", page=1), "status-chip")}
    assert (pills["Anormal"]["background"], pills["Anormal"]["color"]) == ("#b91c1c", "#ffffff")
    assert (pills["Alerta"]["background"], pills["Alerta"]["color"]) == ("#c2410c", "#ffffff")
    assert pills["Normal"]["background"] == "#dcfce7"


def test_page_two_opens_its_own_row_also_after_sorting_and_after_changing_mostrar(mod, source):
    for show in ("alerta_anormal", "todos"):
        total = len(ca.shown_rows(source["rows"], show))
        assert total > 30
        for sort in (None, {"col": "unit", "dir": "desc"}, {"col": "last", "dir": "desc"}, {"col": "essay:Hierro", "dir": "asc"}):
            ordered = ca.matrix_rows(ca.shown_rows(source["rows"], show), ca.load_config(), today=TODAY)
            if sort:
                ordered = ca.sort_matrix(ordered, sort["col"], sort["dir"] == "desc")
            expected = [(r["unit_id"], r["component"]) for r in ordered[30:]]
            block = matrix(mod, source, show=show, page=1, sort=sort)
            rows = body_rows(block)
            assert len(rows) == total - 30
            got = [(from_id_text(of_type(cells(r)[0], "Button")[0].id["unit"]),
                    from_id_text(of_type(cells(r)[0], "Button")[0].id["component"])) for r in rows]
            assert got == expected                                         # the ids carry the row's own identity
            for r in rows:                                                  # every opener of a row names that same row
                unit_cell = of_type(cells(r)[0], "Button")[0].id
                for button in of_type(r, "Button"):
                    assert (button.id["unit"], button.id["component"]) == (unit_cell["unit"], unit_cell["component"])


def test_every_column_header_is_a_sort_button_and_the_pager_is_30_rows(mod, source):
    block = matrix(mod, source, show="todos")
    thead = header_row(block)
    sorts = [b.id["col"] for b in of_type(thead, "Button")]
    assert sorts[:8] == list(ca.SORT_COLUMNS)
    assert sorts[8:] == [id_text(ca.essay_column(e)) for e in header_labels(block)[8:]]
    assert len(body_rows(block)) == 30
    assert "Mostrando 1–30 de 43" in text_of(of_type(block, "Nav"))
    assert all(th.to_plotly_json()["props"]["aria-sort"] == "none" for th in of_type(thead, "Th"))
    assert [th.scope for th in of_type(thead, "Th")] == ["col"] * len(sorts)


def test_a_sorted_header_says_so_to_assistive_technology(mod, source):
    block = matrix(mod, source, show="todos", sort={"col": "last", "dir": "desc"})
    sorted_th = [th for th in of_type(header_row(block), "Th") if th.to_plotly_json()["props"]["aria-sort"] != "none"]
    assert len(sorted_th) == 1 and sorted_th[0].to_plotly_json()["props"]["aria-sort"] == "descending"


def test_unit_and_estado_are_frozen_columns(mod, source):
    block = matrix(mod, source, show="todos")
    table = of_type(block, "Table")[0]
    assert "oil-table--frozen" in table.className and "oil-table--frozen-2" in table.className
    head, first = cells(header_row(block)), cells(body_rows(block)[0])
    for group in (head, first):
        assert "oil-frozen--unit" in group[0].className and "oil-frozen--estado" in group[1].className
        assert not any("oil-frozen" in str(c.className) for c in group[2:])
    css = (ROOT / "dashboard" / "assets" / "oil_monitor.css").read_text(encoding="utf-8")
    assert re.search(r"\.oil-table--frozen\.oil-table--frozen-2\s*\{[^}]*--oil-w-select:\s*0px", css)
    assert ".oil-table-wrap { overflow-x: auto; }" in css                  # the table scrolls inside its card


def test_a_mostrar_option_with_no_rows_says_so_and_keeps_the_chip(mod):
    calm = {"component": "diferencial", "message": None, "rows": [
        {"unit_id": "U1", "component": "diferencial", "machine": "camion", "estado": "Normal", "anomaly": None,
         "sample_date": TODAY.strftime("%Y-%m-%d"), "prev_estado": None, "component_hours": None, "oil_hours": None, "breaches": []}]}
    title, chip, block = mod.render_matrix(calm, view(), "anormal", False, TODAY)
    assert text_of(chip) == "0 de 1 diferenciales"
    assert text_of(block) == "No hay diferenciales que coincidan con la opción elegida en «Mostrar»."


def test_the_matrix_paging_store_counts_the_rows_of_the_selected_option(mod, source):
    assert mod.control_data(source, "alerta_anormal")["n_rows"] == 36
    assert mod.control_data(source, "anormal")["n_rows"] == 4
    assert mod.control_data(source, "todos")["n_rows"] == 43
    assert mod.control_data(None, None)["n_rows"] == 0
    assert mod.control_data(source, "todos")["rev"] != mod.control_data(source, "todos")["rev"]   # always back to page 1


def test_kpis_and_cards_do_not_depend_on_mostrar(mod, source):
    before = text_of(mod.render_kpis(source, TODAY)), text_of(mod.render_age_card(source, TODAY)), text_of(mod.render_anomaly_card(source))
    mod.control_data(source, "anormal")                                     # "Mostrar" touches the matrix store only
    assert before == (text_of(mod.render_kpis(source, TODAY)), text_of(mod.render_age_card(source, TODAY)),
                      text_of(mod.render_anomaly_card(source)))


# ---- Accessibility and color ------------------------------------------------------------------------------

def test_every_chip_pill_and_colored_value_carries_a_word(mod, source):
    block = matrix(mod, source, show="todos")
    colored = (with_class(block, "status-chip") + with_class(block, "oil-level-pill") + with_class(block, "oil-trend")
               + with_class(mod.render_kpis(source, TODAY), "kpi-chip"))
    assert colored and all(text_of(c).strip() for c in colored)
    for legend in with_class(mod.render_anomaly_card(source), "oil-legend") + with_class(mod.render_essay_card(source), "oil-legend"):
        assert all(text_of(li).strip() for li in of_type(legend, "Li"))
    swatches = with_class(mod.render_age_card(source, TODAY), "oil-legend__swatch")
    assert swatches and all(s.to_plotly_json()["props"].get("aria-hidden") == "true" for s in swatches)


def test_text_colors_used_on_white_reach_4_5_to_1():
    def luminance(hex_color):
        channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def contrast(a, b):
        hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    css = (ROOT / "dashboard" / "assets" / "oil_monitor.css").read_text(encoding="utf-8")
    for selector, background in ((".oil-trend--worsening::first-line", "#ffffff"), (".oil-trend--improving::first-line", "#ffffff"),
                                 (".oil-table .oil-two-line--stale", "#ffffff")):
        color = re.search(re.escape(selector) + r"\s*\{[^}]*color:\s*(#[0-9a-f]{6})", css).group(1)
        assert contrast(color, background) >= 4.5, selector
    assert contrast("#ffffff", "#2563eb") >= 4.5                           # the pressed option of the selector
    assert contrast("#b91c1c", "#fee2e2") >= 4.5 and contrast("#92400e", "#fef3c7") >= 4.5   # the essay pills


def test_no_component_analysis_module_draws_a_left_border_accent():
    for name in ("tabs/tab_component_analysis.py", "components/oil_component_analysis.py",
                 "callbacks/component_analysis_callbacks.py"):
        source = (ROOT / "dashboard" / name).read_text(encoding="utf-8")
        assert not re.search(r"border-?[Ll]eft|border-start|border_left", source), name


# ---- Preview pill and wiring --------------------------------------------------------------------------------

def test_the_preview_pill_follows_the_per_tab_flag_in_the_tab_and_after_the_title(monkeypatch):
    from dashboard.components import oil_ui
    from dashboard.tabs.tab_component_analysis import create_component_analysis_tab

    pills = lambda node: [c for c in walk(node) if getattr(c, "className", None) == "oil-preview-pill"]
    heading = of_type(create_component_analysis_tab(), "H3")[0]
    assert len(pills(heading)) == 1 and heading.children[0] == "Análisis de Motor"
    monkeypatch.setattr(oil_ui, "PREVIEW_TABS", frozenset({"frequency"}))
    assert not pills(of_type(create_component_analysis_tab(), "H3")[0])


def test_the_tab_is_the_fifth_of_the_bar_and_is_routed():
    from dashboard.tabs.tab_oil import OIL_TABS, create_layout

    assert [value for value, _ in OIL_TABS] == ["fleet-overview", "report-detail", "lab-compliance", "frequency", "component-analysis"]
    tabs = of_type(create_layout(), "Tab")
    assert tabs[4].value == "component-analysis" and "oil-tab" in tabs[4].className
    source = (ROOT / "dashboard" / "callbacks" / "oil_callbacks.py").read_text(encoding="utf-8")
    assert "active_tab == 'component-analysis'" in source and "create_component_analysis_tab()" in source


def test_the_callbacks_register_without_clashes_and_the_ids_of_the_layout_exist():
    from dash import Dash

    from dashboard.callbacks.component_analysis_callbacks import register_component_analysis_callbacks
    from dashboard.tabs.tab_component_analysis import create_component_analysis_tab

    app = Dash(__name__, suppress_callback_exceptions=True)
    register_component_analysis_callbacks(app)
    outputs = " ".join(app.callback_map)
    for target in ("ca-source.data", "ca-data.data", "ca-view.data", "ca-table-container.children", "ca-kpis.children",
                   "ca-age.children", "ca-anomalies.children", "ca-essays.children", "ca-header.children",
                   "ca-fleet-filter.options", "ca-component.data", "ca-criticality.children"):
        assert target in outputs, target
    layout_ids = {c.id for c in walk(create_component_analysis_tab()) if isinstance(getattr(c, "id", None), str)}
    for needed in ("ca-source", "ca-data", "ca-view", "ca-table-container", "ca-kpis", "ca-age", "ca-anomalies", "ca-essays",
                   "ca-header", "ca-fleet-filter", "ca-show", "ca-include-all", "ca-component", "ca-criticality",
                   "ca-matrix-title", "ca-count-chip"):
        assert needed in layout_ids, needed


def test_every_configured_option_has_its_words_in_both_catalogs():
    for language in ("es", "en"):
        catalog = load_catalog(language)
        for key in ca.load_config().components:
            for kind in ("componente", "singular", "plural", "articulo_plural", "del_singular"):
                assert catalog.get(f"component_analysis.{kind}_{key}"), (language, kind, key)
        for key in ("critico", "importante"):
            assert catalog[f"component_analysis.criticidad_{key}"]
        for group in ("desgaste", "contaminante", "conteo", "aditivo", "fisico_quimico"):
            assert catalog[f"component_analysis.grupo_{group}"]
    assert load_catalog("es")["tab_oil.analisis_por_componente"] == "Análisis por Componente"


def test_the_essay_groups_are_spelled_as_the_requirement_says():
    from dashboard.components.oil_component_analysis import group_label

    assert [group_label(g) for g in ("Desgaste", "Contaminante", "Conteo", "Aditivo", "Fisico Quimico")] == [
        "Desgaste", "Contaminante", "Conteo", "Aditivo", "Fisico Quimico"]
    assert group_label("Otro grupo") == "Otro grupo" and group_label(None) == ""


# ---- Real data --------------------------------------------------------------------------------------------

@pytest.mark.skipif(not (ROOT / "data" / "oil" / "golden").exists(), reason="no oil golden data in this checkout")
def test_every_client_fleet_and_option_renders_and_adds_up():
    from dashboard.components import oil_component_analysis as o

    for client in ("capstone", "cda", "emin", "enex"):
        path = ROOT / "data" / "oil" / "golden" / client / "classified.parquet"
        if not path.exists():
            continue
        for fleet in o.filter_options(client):
            for key in ca.load_config().components:
                data = o.build_source(client, fleet, key)
                assert data["message"] in (None, "component_analysis.sin_componentes")
                if data["message"]:
                    continue
                counts = ca.estado_counts(data["rows"])
                assert sum(counts.values()) == len(data["rows"])
                o.render_kpis(data, TODAY), o.render_age_card(data, TODAY), o.render_anomaly_card(data), o.render_essay_card(data, True)
                for show in ca.SHOW_OPTIONS:
                    o.render_matrix(data, view(), show, True, TODAY)


# ---- Markup weight ------------------------------------------------------------------------------------------

def test_matrix_cells_stay_light_so_dash_can_render_a_full_page_quickly():
    """Dash's renderer freezes for seconds as the number of components grows (a 30-row page with ~1,700 of
    them took 5-7 s in a real browser). Dashes and two-line cells therefore are bare <td>s holding a string."""
    from dashboard.components import oil_component_analysis as o

    src = {"component": "diferencial", "message": None, "rows": [
        {"unit_id": f"U{i:02d}", "component": "diferencial trasero", "machine": "camion", "estado": "Alerta",
         "anomaly": "Desgaste de Componentes", "sample_date": TODAY.strftime("%Y-%m-%d"), "prev_estado": "Normal",
         "component_hours": None, "oil_hours": None,
         "breaches": [{"essay": e, "level": "Marginal", "group": "Desgaste", "counts": True} for e in ("Hierro", "Sodio")]}
        for i in range(30)] + [
        {"unit_id": "OTHER", "component": "diferencial trasero", "machine": "camion", "estado": "Alerta", "anomaly": "X",
         "sample_date": TODAY.strftime("%Y-%m-%d"), "prev_estado": None, "component_hours": 1.0, "oil_hours": 1.0,
         "breaches": [{"essay": e, "level": "Condenatorio", "group": "Desgaste", "counts": True}
                      for e in ("Cobre", "Cromo", "Zinc", "Plata", "Boro", "Plomo", "Estaño", "Bario")]}]}
    block = matrix(o, src, show="todos")
    rows = body_rows(block)
    assert len(rows) == 30
    per_row = sum(1 for _ in walk(rows[0]))
    assert per_row <= 40, per_row                                          # was ~55 before the cells were slimmed
    for dash in with_class(block, "oil-cell-empty"):
        assert type(dash).__name__ == "Td" and dash.children == "—" and dash.to_plotly_json()["props"]["aria-label"]
    for cell in with_class(block, "oil-two-line"):
        assert type(cell).__name__ == "Td" and isinstance(cell.children, str) and "\n" in cell.children


def test_the_dash_cells_are_named_in_words_for_assistive_technology(mod, source):
    block = matrix(mod, source, show="todos")
    names = {d.to_plotly_json()["props"]["aria-label"] for d in with_class(block, "oil-cell-empty")}
    assert names <= {"Dentro de límite", "Sin dato", "Sin anomalía"} and "Dentro de límite" in names and "Sin dato" in names


# ---- Accented names inside element ids ----------------------------------------------------------------------

def _accented_source():
    """Essays and a component whose names carry accents (the real data has "Níquel", "Índice PQ", "Oxidación",
    and ENEX has component names such as "motor de tracción")."""
    def row(unit, estado, essays, component="diferencial trasero ñandú"):
        return {"unit_id": unit, "component": component, "machine": "camion", "estado": estado,
                "anomaly": "Desgaste de Componentes", "sample_date": TODAY.strftime("%Y-%m-%d"), "prev_estado": "Normal",
                "component_hours": 100.0, "oil_hours": 50.0,
                "breaches": [{"essay": e, "level": level, "group": "Desgaste", "counts": True} for e, level in essays]}

    return {"component": "diferencial", "message": None, "rows": [
        row("U1", "Anormal", [("Níquel", "Condenatorio"), ("Índice PQ", "Marginal"), ("Hierro", "Marginal")]),
        row("U2", "Alerta", [("Níquel", "Marginal"), ("Oxidación", "Marginal")]),
        row("U3", "Alerta", [("Hierro", "Marginal")])]}


def test_the_ids_of_every_clickable_element_are_plain_ascii(mod):
    """Dash escapes a non-ASCII character of a pattern id on the server but not in the browser, so such a click
    arrives without its value and is dropped (found in a real browser: the Níquel column did nothing)."""
    block = matrix(mod, _accented_source(), show="todos")
    ids = [b.id for b in of_type(block, "Button") if isinstance(getattr(b, "id", None), dict)]
    assert ids and all(json_text.isascii() for json_text in (json.dumps(i, ensure_ascii=False) for i in ids))
    openers = [i for i in ids if i["type"] == "ca-open"]
    assert {i["cell"] for i in openers} >= {"unit", "N%C3%ADquel", "%C3%8Dndice PQ", "Oxidaci%C3%B3n", "Hierro"}
    assert {from_id_text(i["component"]) for i in openers} == {"diferencial trasero ñandú"}
    assert {i["col"] for i in ids if i["type"] == "ca-sort"} >= {"essay:N%C3%ADquel", "essay:%C3%8Dndice PQ"}


def test_an_accented_essay_column_sorts_and_its_header_still_reads_with_the_accent(mod):
    source = _accented_source()
    assert [l for l in header_labels(matrix(mod, source, show="todos"))[8:]] == ["Níquel", "Hierro", "Índice PQ", "Oxidación"]
    ordered = ca.matrix_rows(ca.shown_rows(source["rows"], "todos"), ca.load_config(), today=TODAY)
    column = ca.essay_column("Níquel")
    assert [r["unit_id"] for r in ca.sort_matrix(ordered, column, True)] == ["U1", "U2", "U3"]      # Condenatorio, Marginal, none
    assert [r["unit_id"] for r in ca.sort_matrix(ordered, column, False)] == ["U2", "U1", "U3"]
    block = matrix(mod, source, show="todos", sort={"col": column, "dir": "desc"})
    assert [text_of(cells(r)[0]).split()[0] for r in body_rows(block)] == ["U1", "U2", "U3"]
    header = [th for th in of_type(header_row(block), "Th") if th.to_plotly_json()["props"]["aria-sort"] != "none"]
    assert len(header) == 1 and "Níquel" in text_of(header[0])


def test_the_report_opens_for_the_decoded_unit_and_component(monkeypatch):
    """The open-report callback receives the encoded id parts and must hand the real names to the navigation."""
    from dash.exceptions import PreventUpdate

    from dashboard.callbacks import component_analysis_callbacks as cb

    seen = {}
    monkeypatch.setattr(cb, "report_navigation", lambda client, unit, component: seen.update(
        client=client, unit=unit, component=component) or ("report-detail", {"equipo": unit, "component": component}))
    clicked = {"type": "ca-open", "unit": "CT_230", "component": id_text("motor de tracción derecho"), "cell": "unit"}
    assert cb.resolve_report("enex", clicked) == ("report-detail", {"equipo": "CT_230", "component": "motor de tracción derecho"})
    assert seen == {"client": "enex", "unit": "CT_230", "component": "motor de tracción derecho"}
    for client, nothing in (("enex", None), (None, clicked)):
        with pytest.raises(PreventUpdate):
            cb.resolve_report(client, nothing)




def test_alphabetical_ties_ignore_accents_and_case():
    rows = [{"estado": "Alerta", "anomaly": name, "breaches": [
        {"essay": name, "level": "Marginal", "group": None, "counts": True}]} for name in ("Oxidación", "Índice PQ", "aluminio", "Zinc")]
    assert [e["type"] for e in ca.anomaly_counts(rows)] == ["aluminio", "Índice PQ", "Oxidación", "Zinc"]
    assert [e["essay"] for e in ca.essay_counts(rows)] == ["aluminio", "Índice PQ", "Oxidación", "Zinc"]
