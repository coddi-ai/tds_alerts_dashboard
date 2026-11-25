"""Monitoreo > Operación y rendimiento (OP-PE): week discovery, the rules of the panels
(src/data/operation_performance.py), the figures, the tab layouts, the callbacks and the
registration of the service."""

import json
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import pytest

from src.data import operation_performance as op

CLIENT = "TESTCO"


# ------------------------------------------------------------------------------------------------
# Fixture: a client with two complete weeks and one still being written (no manifest)
# ------------------------------------------------------------------------------------------------

def _camiones(week):
    rows = [
        # unidad, flota, iv_rel, iv, climbs, decision, cause, lost vs fleet, lost vs curve, ranking
        ("T1", "F1", 1.04, 1.06, 40, op.CONFORME, None, 2.0, 1.0, 1),
        ("T2", "F1", 0.98, 0.99, 35, op.SEGUIMIENTO, "Sin causa en señales (camino, tráfico o carga)", 8.0, 6.0, 2),
        ("T3", "F1", 0.94, 0.95, 30, op.REVISAR, "Turbo / admisión (presión de turbo baja)", 20.5, 15.0, 3),
        ("T4", "F2", 1.01, 0.97, 25, op.CONFORME, None, 1.0, 0.0, 1),
        ("T5", "F2", 0.99, 1.00, 4, op.SIN_DATOS, None, 0.5, 0.0, 2),
    ]
    frame = pd.DataFrame(rows, columns=["unidad", "flota", "iv_rel_p50", "iv_p50", "pasadas_capacidad", "decision",
                                        "causa_principal", "min_perdidos_flota", "min_perdidos_curva", "ranking"])
    frame["pasadas_bajo_1"] = [0.1, 0.5, 0.8, 0.6, 0.4]
    frame["semana"] = week
    return frame


def _pasadas(day):
    rows = []
    model = {"T1": "M1", "T2": "M1", "T3": "M1", "T4": "M2", "T5": "M2"}
    for i, unit in enumerate(["T1", "T2", "T3", "T4", "T5"]):
        flota = "F1" if model[unit] == "M1" else "F2"
        # loaded full-throttle climbs on the main ramp (S1) and one on S2
        for k in range(3):
            rows.append(dict(unidad=unit, flota=flota, modelo=model[unit], sentido="subida", estado="cargado",
                             capacidad=True, rampa_id="S1", dia=day, turno="día", pend_pct=8.0, dist_m=500.0,
                             v_kmh=12.0 + i + k, gvw_t=380.0, fuerza_req_t=36.0, iv=1.0 - 0.02 * i, iv_rel=1.0 - 0.02 * i,
                             hp_pendiente=2000.0 + 10 * i, v_max_retardo_kmh=None, curva_retardo=None,
                             exceso_retardo=False, bajo_flota=unit == "T3", payload_t_media=200.0,
                             causa="Turbo / admisión (presión de turbo baja)" if unit == "T3" else None))
        rows.append(dict(rows[-1], rampa_id="S2", bajo_flota=False, causa=None))
        # not in the base population: empty climb, not full throttle, a descent
        rows.append(dict(rows[-1], estado="vacío", rampa_id="S2"))
        rows.append(dict(rows[-1], estado="cargado", capacidad=False, rampa_id="S2"))
        rows.append(dict(rows[-1], sentido="bajada", rampa_id="B1", capacidad=False, v_max_retardo_kmh=30.0,
                         v_kmh=32.0 if unit == "T1" else 25.0, curva_retardo="continuo",
                         exceso_retardo=unit == "T1", iv=None, iv_rel=None, hp_pendiente=None))
    # one slow climb of T2 without engine cause
    rows.append(dict(rows[0], unidad="T2", bajo_flota=True, causa="Sin causa en señales (camino, tráfico o carga)"))
    frame = pd.DataFrame(rows)
    frame["dia"] = pd.to_datetime(frame["dia"]).dt.date
    frame["pasada_id"] = [f"{u}_{i:03d}" for i, u in enumerate(frame["unidad"])]
    return frame


RAMP_START = {"S1": (-26.50, -70.30), "S2": (-26.52, -70.30), "B1": (-26.51, -70.31)}


def _tramos(pasadas):
    """Four 100 m segments per pass along its ramp; T3 is 20 % slower than the others."""
    rows = []
    for p in pasadas.itertuples():
        lat0, lon0 = RAMP_START[p.rampa_id]
        for k in range(4):
            rows.append(dict(pasada_id=p.pasada_id, tramo=10 + k, lat=lat0 - 0.001 * k, lon=lon0 - 0.0005 * k,
                             pend_pct=6.0 + k, v_kmh=(12.0 if p.unidad == "T3" else 15.0) - 0.5 * k))
    return pd.DataFrame(rows)


def _camion_dia(days, iv_rel_t3):
    rows = []
    for day in days:
        for unit, flota in (("T1", "F1"), ("T2", "F1"), ("T3", "F1"), ("T4", "F2"), ("T5", "F2")):
            rows.append(dict(flota=flota, unidad=unit, dia=day, pasadas=10,
                             iv_rel_p50=iv_rel_t3 if unit == "T3" else 1.0, iv_p50=1.0, hp_pendiente_p50=2000.0,
                             eficiencia_p50=0.8, payload_t_media=None))
    frame = pd.DataFrame(rows)
    frame["dia"] = pd.to_datetime(frame["dia"]).dt.date
    return frame


def _rampas(week):
    return pd.DataFrame([
        dict(rampa_id="S1", sentido="subida", pasadas=15, camiones=5, lat0=-26.50, lon0=-70.30, lat1=-26.51,
             lon1=-70.31, orden=1, nombre="Subida 8,0 % · 0,5 km", semana=week),
        dict(rampa_id="B1", sentido="bajada", pasadas=5, camiones=5, lat0=-26.51, lon0=-70.31, lat1=-26.52,
             lon1=-70.32, orden=2, nombre="Bajada 6,0 % · 0,6 km", semana=week),
        dict(rampa_id="S2", sentido="subida", pasadas=5, camiones=5, lat0=-26.52, lon0=-70.30, lat1=-26.53,
             lon1=-70.31, orden=3, nombre="Subida 7,0 % · 0,4 km", semana=week),
    ])


def _curvas():
    rows = []
    for model in ("M1", "M2"):
        for v in range(1, 40):
            rows.append(dict(v_kmh=float(v), fuerza_t=900.0 / v, marcha=0, modelo=model, tipo="propulsión",
                             curva=f"{model} propulsión", largo_max_m=None))
        rows.append(dict(v_kmh=20.0, fuerza_t=30.0, marcha=0, modelo=model, tipo="retardo",
                         curva=f"{model} retardo", largo_max_m=None))
    return pd.DataFrame(rows)


def _escape():
    rows = []
    for unit, flota in (("T1", "F1"), ("T3", "F1")):
        for c in range(1, 17):
            value = 5.0
            if unit == "T3" and c == 4:
                value = 45.0
            if unit == "T1" and c == 9:
                value = 400.0     # dropped reading
            rows.append(dict(flota=flota, unidad=unit, cilindro=f"{c:02d}", desv_cilindro_c=value, patron_flota_c=0.0,
                             desv_vs_flota_c=value, sensor_sospechoso=abs(value) > 150, alerta=abs(value) > 30,
                             pasadas=10))
    return pd.DataFrame(rows)


def _calidad(days):
    rows = []
    for day in days:
        for unit in ("T1", "T2", "T3", "T4", "T5"):
            rows.append(dict(unidad=unit, dia=day, horas_con_datos=20, horas_con_gps=0 if unit == "T5" else 18,
                             horas_en_movimiento=12.0, sin_gps=unit == "T5"))
    frame = pd.DataFrame(rows)
    frame["dia"] = pd.to_datetime(frame["dia"]).dt.date
    return frame


def _write_week(base, folder, *, manifest=True, iv_rel_t3=0.94, with_escape=False):
    gold = base / "gold" / folder
    silver = base / "silver" / folder
    gold.mkdir(parents=True)
    silver.mkdir(parents=True)
    week = op.Week.parse(folder)
    days = [week.monday, date.fromordinal(week.monday.toordinal() + 1)]
    # Written with the pipeline's own name for the best decision; load_week shows it as "Conforme".
    _camiones(folder).replace({"decision": {op.CONFORME: "Fondo de mina"}}).to_parquet(gold / "camiones.parquet")
    pasadas = _pasadas(days[0])
    pasadas.to_parquet(gold / "pasadas_eval.parquet")
    _tramos(pasadas).to_parquet(silver / "tramos.parquet")
    _camion_dia(days, iv_rel_t3).to_parquet(gold / "camion_dia.parquet")
    _rampas(folder).to_parquet(gold / "rampas.parquet")
    _curvas().to_parquet(gold / "curvas.parquet")
    if with_escape:
        _escape().to_parquet(gold / "escape.parquet")
    _calidad(days).to_parquet(silver / "calidad.parquet")
    if manifest:
        for folder_path in (gold, silver):
            (folder_path / "manifest.json").write_text(json.dumps({
                "cliente": "testco", "semana": week.iso, "carpeta": folder, "lunes": str(week.monday),
                "generado_utc": "2026-11-24T16:24:17+00:00",
            }), encoding="utf-8")


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    base = tmp_path / "operation-performance" / "testco"
    _write_week(base, "Week46Year2026", iv_rel_t3=0.99)
    _write_week(base, "Week47Year2026", with_escape=True)
    _write_week(base, "Week48Year2026", manifest=False)     # still being written
    yield tmp_path


@pytest.fixture
def week47(data_root):
    return op.load_week(CLIENT, op.Week(2026, 47))


# ------------------------------------------------------------------------------------------------
# Weeks
# ------------------------------------------------------------------------------------------------

def test_week_folder_names_parse_to_iso_weeks():
    week = op.Week.parse("Week47Year2026")
    assert (week.iso, week.folder) == ("2026-W47", "Week47Year2026")
    assert week.monday == date(2026, 11, 16) and week.sunday == date(2026, 11, 22)
    assert op.Week.parse("Week7Year2026").folder == "Week07Year2026"
    assert op.Week.parse("Week54Year2026") is None
    assert op.Week.parse("2026-W47") is None
    assert op.Week.parse(None) is None


def test_only_weeks_with_manifest_are_listed_oldest_first(data_root):
    assert [w.iso for w in op.available_weeks(CLIENT)] == ["2026-W46", "2026-W47"]
    assert op.latest_week(CLIENT).iso == "2026-W47"
    assert [w.iso for w in op.available_weeks("lower-case-unknown")] == []
    assert op.available_weeks("") == []


def test_a_client_folder_is_lower_case(data_root):
    assert op.available_weeks("testco") == op.available_weeks("TESTCO")


def test_load_week_reads_gold_and_silver_and_leaves_missing_tables_as_none(week47):
    assert len(week47.camiones) == 5
    assert week47.frenos is None and week47.potencia is None
    assert week47.escape is not None and week47.calidad is not None
    assert week47.manifest["semana"] == "2026-W47"
    assert pd.api.types.is_datetime64_any_dtype(week47.pasadas["dia"])
    assert week47.measured_payload
    assert week47.fleets == ["F1", "F2"]
    assert week47.models == ["M1", "M2"]


def test_loaded_tables_are_copies(week47):
    week47.camiones.drop(week47.camiones.index, inplace=True)
    assert len(op.load_week(CLIENT, op.Week(2026, 47)).camiones) == 5


# ------------------------------------------------------------------------------------------------
# Rules
# ------------------------------------------------------------------------------------------------

def test_base_population_is_loaded_full_throttle_climbs(week47):
    climbs = op.base_climbs(week47.pasadas)
    assert set(climbs["sentido"]) == {"subida"} and set(climbs["estado"]) == {"cargado"}
    assert climbs["capacidad"].all()
    assert len(climbs) == 5 * 4 + 1
    assert op.base_climbs(None).empty


def test_week_kpis(week47):
    kpis = op.week_kpis(week47.camiones, week47.pasadas)
    assert kpis["trucks"] == 5
    assert kpis["evaluated"] == 4          # "Sin datos suficientes" is not evaluated
    assert kpis["to_review"] == 1 and kpis["follow_up"] == 1
    assert kpis["lost_minutes"] == pytest.approx(32.0)
    assert kpis["iv_median"] == pytest.approx(op.base_climbs(week47.pasadas)["iv"].median())


def test_week_kpis_without_climbs():
    kpis = op.week_kpis(None, None)
    assert kpis["iv_median"] is None and kpis["trucks"] == 0


@pytest.mark.parametrize("iv_rel, climbs, expected", [
    (1.00, 10, op.CONFORME), (1.05, 50, op.CONFORME), (0.99, 10, op.SEGUIMIENTO),
    (0.97, 10, op.SEGUIMIENTO), (0.969, 10, op.REVISAR), (1.10, 9, op.SIN_DATOS), (None, 30, op.SIN_DATOS),
])
def test_decision_thresholds(iv_rel, climbs, expected):
    assert op.decision_of(iv_rel, climbs) == expected


def test_every_decision_has_a_tier_from_the_shared_scale():
    from shared.severity import SEVERITY_TIERS

    assert set(op.DECISION_TIER) == set(op.DECISIONS)
    assert all(tier is None or tier in SEVERITY_TIERS for tier in op.DECISION_TIER.values())


def test_main_ramp_is_the_one_with_most_base_climbs(week47):
    options = op.ramp_options(week47.pasadas, week47.rampas)
    assert [o["rampa_id"] for o in options] == ["S1", "S2"]
    assert options[0] == {"rampa_id": "S1", "nombre": "Subida 8,0 % · 0,5 km", "pasadas": 16}
    assert op.main_ramp(week47.pasadas) == "S1"
    assert len(op.ramp_climbs(week47.pasadas, "S1")) == 16
    assert op.ramp_climbs(week47.pasadas, None).empty


def test_causes_count_slow_climbs_with_the_neutral_cause_last(week47):
    counts = op.cause_counts(week47.pasadas)
    assert counts.groupby("unidad")["pasadas"].sum().to_dict() == {"T3": 3, "T2": 1}
    assert counts["unidad"].iloc[0] == "T3"      # most passes first
    order = op.cause_order(counts)
    assert order[-1].startswith("Sin causa")
    assert op.is_neutral_cause("Fuera del motor (propulsión, carga o camino)")
    assert not op.is_neutral_cause("Motor: turbo / admisión")


def test_units_in_a_decision_worst_first(week47):
    assert op.units_in(week47.camiones, op.REVISAR) == ["T3"]
    assert op.units_in(None, op.REVISAR) == []


def test_fleet_filter_reaches_every_table(week47):
    f2 = op.filter_fleet(week47, "F2")
    assert set(f2.camiones["unidad"]) == {"T4", "T5"}
    assert set(f2.pasadas["unidad"]) == {"T4", "T5"}
    assert set(f2.calidad["unidad"]) == {"T4", "T5"}          # no `flota` column: through the units
    assert set(f2.curvas["modelo"]) == {"M2"}                 # the fleet's model curve only
    assert f2.escape.empty
    assert op.filter_fleet(week47, "all") is week47
    assert op.filter_fleet(week47, None) is week47


def test_descents_and_retarder_excess(week47):
    descents = op.descents(week47.pasadas)
    assert set(descents["sentido"]) == {"bajada"} and len(descents) == 5
    assert int(descents["exceso_retardo"].sum()) == 1


def test_low_efficiency_lists_trucks_below_1_at_nominal_load(week47):
    rows = op.low_efficiency(week47.camiones)
    assert rows["unidad"].tolist() == ["T3", "T4", "T2"]


def test_history_joins_every_complete_week(data_root):
    history = op.load_history(CLIENT)
    assert set(history["semana"]) == {"Week46Year2026", "Week47Year2026"}
    assert len(history) == 2 * 2 * 5                     # 2 weeks x 2 days x 5 trucks
    assert op.trend_metrics(history)[:2] == ["iv_rel_p50", "iv_p50"]
    assert "payload_t_media" not in op.trend_metrics(history)   # all empty: not offered
    assert set(op.load_history(CLIENT, "F2")["unidad"]) == {"T4", "T5"}


def test_history_keeps_the_newest_week_for_a_repeated_day(data_root):
    base = data_root / "operation-performance" / "testco" / "gold"
    older = pd.read_parquet(base / "Week46Year2026" / "camion_dia.parquet")
    newer = pd.read_parquet(base / "Week47Year2026" / "camion_dia.parquet")
    pd.concat([older, newer.assign(iv_rel_p50=0.5)]).to_parquet(base / "Week46Year2026" / "camion_dia.parquet")
    history = op.load_history(CLIENT)
    assert not history.duplicated(["unidad", "dia"]).any()
    repeated = history[history["dia"].isin(pd.to_datetime(newer["dia"]))]
    assert set(repeated["semana"]) == {"Week47Year2026"}
    assert (repeated["iv_rel_p50"] != 0.5).all()


def test_escape_matrix_leaves_suspicious_sensors_out_of_the_scale(week47):
    matrix, suspicious = op.escape_matrix(week47.escape)
    assert matrix.index.tolist() == ["T3", "T1"]          # largest deviation first, suspicious not counted
    assert pd.isna(matrix.loc["T1", "09"]) and suspicious.loc["T1", "09"] == 400.0
    assert matrix.loc["T3", "04"] == 45.0
    assert suspicious.stack().dropna().size == 1


def test_quality_matrix(week47):
    matrix = op.quality_matrix(week47.calidad)
    assert matrix.shape == (5, 2)
    assert (matrix.loc["T5"] == 0).all()
    assert op.quality_matrix(None).empty


# ------------------------------------------------------------------------------------------------
# Figures
# ------------------------------------------------------------------------------------------------

def test_every_panel_figure_builds(week47, data_root):
    from dashboard.components import operation_performance_charts as charts

    figures = [
        charts.ranking_figure(week47.camiones, show_fleet=True),
        charts.causes_figure(op.cause_counts(week47.pasadas)),
        charts.lost_minutes_figure(week47.camiones),
        charts.escape_figure(week47.escape),
        charts.curve_figure(week47.pasadas, week47.curvas, "M1", ["T3"]),
        charts.ramp_box_figure(op.ramp_climbs(week47.pasadas, "S1"), week47.camiones),
        charts.ramp_map_figure(op.ramp_map_data(CLIENT, op.Week(2026, 47))[1], "pendiente"),
        charts.trend_figure(op.load_history(CLIENT), "iv_rel_p50", ["T3"]),
        charts.retarder_figure(week47.pasadas),
        charts.quality_figure(week47.calidad, "horas_con_datos"),
    ]
    for figure in figures:
        assert isinstance(figure, go.Figure)
        assert figure.data, figure.layout
        figure.to_json()


def test_missing_tables_give_a_message_not_an_error():
    from dashboard.components import operation_performance_charts as charts

    for figure in (charts.power_figure(None), charts.brakes_figure(None), charts.escape_figure(None),
                   charts.ranking_figure(None), charts.trend_figure(pd.DataFrame(), "iv_rel_p50"),
                   charts.retarder_figure(None), charts.quality_figure(None)):
        assert not figure.data and figure.layout.annotations


def test_ranking_colors_follow_the_decision(week47):
    from dashboard.components import operation_performance_charts as charts
    from shared.severity import SEVERITY_TIERS

    figure = charts.ranking_figure(week47.camiones)
    colors = {trace.name: trace.marker.color for trace in figure.data}
    assert colors[op.REVISAR] == SEVERITY_TIERS["alto"]["fill"]
    assert colors[op.CONFORME] == SEVERITY_TIERS["bajo"]["fill"]
    # highest relative IV on top: the category array runs bottom to top
    assert list(figure.layout.yaxis.categoryarray)[-1] == "T1"


def test_curve_highlights_only_trucks_of_the_model(week47):
    from dashboard.components import operation_performance_charts as charts

    figure = charts.curve_figure(week47.pasadas, week47.curvas, "M1", ["T3", "T4"])
    names = [trace.name for trace in figure.data]
    assert any("T3" in name for name in names)
    assert not any("T4" in name for name in names)       # T4 is an M2 truck
    assert figure.layout.yaxis.type == "log"


def test_numbers_follow_the_language():
    from dashboard.components import operation_performance_charts as charts
    from src.i18n import forced_language

    with forced_language("es"):
        assert charts.fmt(1234.567) == "1.234,57" and charts.separators() == ",."
    with forced_language("en"):
        assert charts.fmt(1234.567) == "1,234.57" and charts.separators() == ".,"
    assert charts.fmt(None) == "—" and charts.fmt(float("nan")) == "—"


# ------------------------------------------------------------------------------------------------
# Layout and callbacks
# ------------------------------------------------------------------------------------------------

def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None and not isinstance(children, str):
        yield from _walk(children)


def _ids(component):
    return {node.id for node in _walk(component) if isinstance(getattr(node, "id", None), str)}


def test_page_layout_has_its_filters_and_source_slot():
    from dashboard.tabs import tab_operation_performance as tab

    ids = _ids(tab.create_layout())
    assert {"opp-week", "opp-fleet", "opp-page-content", "opp-source-status", "opp-week-caption"} <= ids
    assert "opp-internal-tabs" not in ids          # one page, no internal tabs


PAGE_IDS = {
    "opp-ranking-graph", "opp-unit", "opp-unit-focus", "opp-map", "opp-map-color", "opp-map-base",
    "opp-map-caption", "opp-curve-graph", "opp-curve-caption", "opp-ramp-select", "opp-ramp-metric",
    "opp-ramp-graph", "opp-ramp-caption", "opp-decision-filter", "opp-decision-table", "opp-decision-count",
}


@pytest.mark.parametrize("fleet", [None, "F1", "F2"])
def test_the_page_builds_with_every_control_its_callbacks_read(week47, fleet):
    from dashboard.tabs import tab_operation_performance as tab

    page = tab.build_page(op.filter_fleet(week47, fleet), all_fleets=fleet is None)
    assert PAGE_IDS <= _ids(page)


def test_the_page_opens_on_the_worst_unit(week47):
    from dashboard.tabs import tab_operation_performance as tab

    page = tab.build_page(week47, all_fleets=True)
    unit = next(n for n in _walk(page) if getattr(n, "id", None) == "opp-unit")
    assert unit.value == "T3" == op.default_unit(week47.camiones)


def test_diagnosis_trend_descent_and_quality_are_off_the_page(week47):
    from dashboard.tabs import tab_operation_performance as tab
    from src.i18n import t

    titles = {n.children for n in _walk(tab.build_page(week47, True))
              if "opp-panel__title" in str(getattr(n, "className", ""))}
    texts = " | ".join(titles)
    for key in ("opp.panel.causes.title", "opp.panel.lost.title", "opp.panel.escape.title",
                "opp.panel.trend.title", "opp.panel.retarder.title", "opp.panel.quality.title"):
        assert t(key) not in texts, key
    assert t("opp.panel.ranking.title") in texts and t("opp.panel.map.title") in texts


def test_weeks_callback_lists_newest_first(data_root):
    from dashboard.callbacks import operation_performance_callbacks as cb

    options, value = cb.populate_weeks(CLIENT)
    assert [o["value"] for o in options] == ["Week47Year2026", "Week46Year2026"]
    assert value == "Week47Year2026"
    assert cb.populate_weeks(None) == ([], None)


def test_fleet_callback(data_root):
    from dashboard.callbacks import operation_performance_callbacks as cb

    options, value, disabled = cb.populate_fleets(CLIENT, "Week47Year2026", "F2")
    assert [o["value"] for o in options] == ["all", "F1", "F2"]
    assert (value, disabled) == ("F2", False)
    options, value, disabled = cb.populate_fleets(CLIENT, None, None)
    assert (value, disabled) == ("all", True)


def test_page_for_a_client_without_data_is_an_empty_state(data_root):
    from dashboard.callbacks import operation_performance_callbacks as cb
    from src.i18n import t

    rendered = cb.render_opp_page("NODATA", None, "all")
    texts = " ".join(str(getattr(n, "children", "")) for n in _walk(rendered))
    assert t("opp.empty.no_weeks_title") in texts


def test_unit_callbacks(data_root):
    from dashboard.callbacks import operation_performance_callbacks as cb

    folder = "Week47Year2026"
    options = [{"value": u} for u in ("T1", "T2", "T3", "T4", "T5")]
    click = {"points": [{"customdata": ["Revisar", "x", 0.9, 30, 20, "T2"]}]}
    assert cb.select_unit_from_ranking(click, options) == "T2"
    with pytest.raises(Exception):
        cb.select_unit_from_ranking({"points": [{"customdata": ["a", "b", 1, 1, 1, "ZZ"]}]}, options)
    figure = cb.update_ranking("T2", CLIENT, folder, "all")
    bold = [text for text in figure.layout.yaxis.ticktext if text.startswith("<b>")]
    assert bold == ["<b>▶ T2 · F1</b>"]
    assert cb.update_unit_focus("T2", CLIENT, folder, "all") is not None
    figure, caption, options = cb.update_curve(["T4"], CLIENT, folder, "all")
    assert "M2" in caption and any("T4" in trace.name for trace in figure.data)
    # Units of another model than the curve's are listed but disabled.
    assert {o["value"]: o["disabled"] for o in options} == {"T1": True, "T2": True, "T3": True, "T4": False, "T5": False}
    # Several units of one model share the curve; one of another model is dropped.
    figure, caption, _ = cb.update_curve(["T1", "T3", "T4"], CLIENT, folder, "all")
    named = {trace.name for trace in figure.data}
    assert "M1" in caption and "T1, T3" in caption
    assert any("T1" in n for n in named) and any("T3" in n for n in named) and not any("T4" in n for n in named)
    assert cb.curve_follows_unit("T2") == ["T2"]


def test_the_pipeline_decision_name_is_shown_as_conforme(week47):
    assert "Fondo de mina" not in set(week47.camiones["decision"])
    assert set(week47.camiones["decision"]) == {op.CONFORME, op.SEGUIMIENTO, op.REVISAR, op.SIN_DATOS}


def test_units_are_listed_letters_first_then_by_number():
    assert op.sort_units(["CA-81", "CA-9", "CA-30", "CA-100"]) == ["CA-9", "CA-30", "CA-81", "CA-100"]
    assert op.sort_units(["101", "11", "9"]) == ["9", "11", "101"]
    assert op.sort_units(["B2", "A10", "A2", "X"]) == ["A2", "A10", "B2", "X"]


def test_unit_selectors_use_the_natural_order(week47):
    from dashboard.components import operation_performance_views as views

    camiones = week47.camiones.assign(unidad=["CA-81", "CA-9", "CA-30", "CA-100", "CA-31"])
    assert [o["value"] for o in views.unit_options(camiones)] == ["CA-9", "CA-30", "CA-31", "CA-81", "CA-100"]
    per_unit = op.unit_climbs(week47.pasadas)
    assert list(per_unit["unidad"]) == ["T1", "T2", "T3", "T4", "T5"]
    # Once MAX_CURVE_UNITS are selected, the other units of the model are disabled too.
    many = pd.DataFrame({"unidad": [f"U{i}" for i in range(1, 8)], "modelo": "M1", "pasadas": 12})
    chosen = [f"U{i}" for i in range(1, 6)]
    options = views.curve_unit_options(many, "M1", chosen)
    assert [o["value"] for o in options if o["disabled"]] == ["U6", "U7"]
    assert options[0]["label"] == "U1 · 12 subidas"


def test_map_labels_carry_a_marker_and_the_view_fits_the_paths(week47):
    """A text-only Scattermap makes MapLibre reject the layer (text-offset NaN) and the map then
    ignores every later update, so the ramp labels must carry a (transparent) marker."""
    from dashboard.components import operation_performance_charts as charts

    segments = op.ramp_map_data(CLIENT, op.Week(2026, 47))[1]
    figure = charts.ramp_map_figure(segments, "pendiente")
    assert all(trace.mode != "text" for trace in figure.data)
    # Every point inside the map: MapLibre's world is 512·2^zoom px wide (Web Mercator).
    import numpy as np
    lat = pd.Series([-26.60, -26.51]); lon = pd.Series([-70.32, -70.29])
    view = charts._map_view(lat, lon)
    px_per_deg = 512 * 2 ** view["zoom"] / 360
    height = (lat.max() - lat.min()) / np.cos(np.radians(view["center"]["lat"])) * px_per_deg
    width = (lon.max() - lon.min()) * px_per_deg
    assert height <= charts.MAP_HEIGHT and width <= charts.MAP_FIT_WIDTH


def test_unit_focus_lists_its_worst_ramps_as_buttons(week47):
    from dashboard.components import operation_performance_views as views

    focus = views.unit_focus(week47, "T3")
    buttons = [n.id for n in _walk(focus) if isinstance(getattr(n, "id", None), dict)]
    assert buttons == [{"type": "opp-worst-ramp", "rampa": "S1"}]
    assert views.unit_focus(week47, None) is not None


def test_ramp_selection_follows_the_map_the_unit_and_the_buttons(data_root, monkeypatch):
    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    from dashboard.callbacks import operation_performance_callbacks as cb

    folder = "Week47Year2026"
    options = [{"value": "S1"}, {"value": "S2"}]

    def fire(prop_id, value, *args):
        context_value.set(AttributeDict(triggered_inputs=[{"prop_id": prop_id, "value": value}]))
        return cb.select_ramp(*args, options, CLIENT, folder, "all")

    click = {"points": [{"customdata": ["S2", "Subida", "0–100 m", 6, 6, 15, 5]}]}
    assert fire("opp-map.clickData", click, "T1", click, []) == "S2"
    assert fire("opp-unit.value", "T3", "T3", None, []) == "S1"
    button = '{"rampa":"S2","type":"opp-worst-ramp"}.n_clicks'
    assert fire(button, 1, "T3", None, [1]) == "S2"
    assert fire(button, 0, "T3", None, [0]) is cb.no_update       # the buttons appearing is not a click


def test_ramp_and_map_callbacks(data_root):
    from dashboard.callbacks import operation_performance_callbacks as cb

    folder = "Week47Year2026"
    figure, caption = cb.update_ramp("S1", "iv", "T3", CLIENT, folder, "all")
    assert any("T3" in trace.name for trace in figure.data) and caption
    for mode in ("pendiente", "flota", "unidad"):
        for base in ("satelite", "calles"):
            figure, caption = cb.update_map(mode, base, "T3", "S1", CLIENT, folder, "all")
            assert figure.data and caption
    satellite = cb.update_map("pendiente", "satelite", "T3", "S1", CLIENT, folder, "all")[0]
    assert satellite.layout.map.layers[0].sourcetype == "raster"
    rows, count = cb.filter_decision_table([op.REVISAR], CLIENT, folder, "all")
    assert [r["unidad"] for r in rows] == ["T3"] and "1" in count


def test_map_paths_and_unit_speed(data_root):
    points, segments = op.ramp_map_data(CLIENT, op.Week(2026, 47))
    assert set(segments["rampa_id"]) == {"S1", "S2"}             # climb ramps with full-throttle climbs
    s1 = segments[segments["rampa_id"] == "S1"]
    assert s1["k"].tolist() == [0, 1, 2, 3] and s1["pend_pct"].tolist() == [6.0, 7.0, 8.0, 9.0]
    speed = op.unit_segment_speed(points, "T3")
    assert set(speed["rampa_id"]) == {"S1"}                      # T3 climbed S2 only once
    assert (speed["rel"] < 1).all()                              # T3 is slower than the fleet
    assert op.unit_segment_speed(points, None).empty
    # F2 alone climbed S2 twice: below the minimum climbs a point needs, so only S1 is drawn
    assert set(op.ramp_map_data(CLIENT, op.Week(2026, 47), "F2")[1]["rampa_id"]) == {"S1"}


# ------------------------------------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------------------------------------

def test_service_is_registered_under_monitoring():
    from config.client_services import KNOWN_SERVICE_IDS
    from dashboard import services_registry as reg

    service = "monitoring-operation-performance"
    assert service in KNOWN_SERVICE_IDS
    monitoring = next(s for s in reg.SERVICE_SECTIONS if s["section"] == "monitoring")
    assert monitoring["services"][-1] == service
    assert reg.NAV_PATHS[service] == "/monitoring/operacion-rendimiento"
    assert reg.resolve_service_id_for_pathname("monitoring/operacion-rendimiento") == service
    assert reg.nav_id_for_pathname("/monitoring/operacion-rendimiento") == service
    assert reg.SERVICE_LABELS[service] == "Operación y rendimiento"


def test_service_is_enabled_for_the_clients_with_op_pe_data():
    from config.client_services import is_service_dummy, is_service_enabled

    for client in ("CDA", "CAPSTONE"):
        assert is_service_enabled(client, "monitoring-operation-performance")
        assert not is_service_dummy(client, "monitoring-operation-performance")
    for client in ("EMIN", "ENEX", "CENTINELA"):
        assert not is_service_enabled(client, "monitoring-operation-performance")


def test_data_sources_are_probed(data_root):
    from config.service_data_sources import data_sources_for_service
    from src.data.catalog import build_client_availability, clear_availability_cache

    assert data_sources_for_service("monitoring-operation-performance") == ("op_pe_gold", "op_pe_quality")
    clear_availability_cache()
    try:
        probes = build_client_availability(CLIENT, data_root)
    finally:
        clear_availability_cache()
    assert probes["op_pe_gold"].status == "available"
    assert probes["op_pe_quality"].status == "available"


# ------------------------------------------------------------------------------------------------
# The downloaded data, when present (skipped otherwise)
# ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("client", ["CDA", "CAPSTONE"])
def test_real_weeks_render_the_page(client, monkeypatch):
    monkeypatch.delenv("DASHBOARD_DATA_ROOT", raising=False)
    week = op.latest_week(client)
    if week is None:
        pytest.skip(f"no operation-performance data for {client}")
    from dashboard.tabs import tab_operation_performance as tab

    data = op.load_week(client, week)
    assert data.camiones is not None and data.pasadas is not None
    from dashboard.components import operation_performance_charts as charts

    for fleet in [None, *data.fleets]:
        assert PAGE_IDS <= _ids(tab.build_page(op.filter_fleet(data, fleet), all_fleets=fleet is None))
        points, segments = op.ramp_map_data(client, week, fleet)
        assert not segments.empty
        unit = op.default_unit(op.filter_fleet(data, fleet).camiones)
        charts.ramp_map_figure(segments, "unidad", "satelite", op.unit_segment_speed(points, unit), unit).to_json()
