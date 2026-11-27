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
    # Two passes per trip, in each unit's order: 3 trips with a loaded climb (T2: 4, its extra climb).
    frame["viaje"] = frame.groupby("unidad").cumcount() // 2 + 1
    frame["dur_s"] = 100.0
    frame["carga_motor_pct_media"] = [80.0 if u == "T3" else 95.0 for u in frame["unidad"]]
    return frame


RAMP_START = {"S1": (-26.50, -70.30), "S2": (-26.52, -70.30), "B1": (-26.51, -70.31)}


def _tramos(pasadas):
    """Four 100 m segments per pass along its ramp; T3 is 20 % slower than the others."""
    rows = []
    for p in pasadas.itertuples():
        lat0, lon0 = RAMP_START[p.rampa_id]
        for k in range(4):
            rows.append(dict(pasada_id=p.pasada_id, tramo=10 + k, lat=lat0 - 0.001 * k, lon=lon0 - 0.0005 * k,
                             pend_pct=6.0 + k, v_kmh=(12.0 if p.unidad == "T3" else 15.0) - 0.5 * k,
                             carga_motor_pct_media=80.0 if p.unidad == "T3" else 95.0, rpm_media=1700.0 + 10 * k))
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


def test_week_kpis_tie_performance_to_the_operation(week47):
    kpis = op.week_kpis(week47.camiones, week47.pasadas)
    climbs = op.base_climbs(week47.pasadas)
    assert kpis["trips"] == 4 * 3 + 4                       # T2 has one more trip with a loaded climb
    assert kpis["loss_per_trip_s"] == pytest.approx(32.0 * 60 / 16)
    # 21 full-throttle climbs of 100 s: the 32 minutes lost are 32 / 35 of that time
    assert kpis["lost_share"] == pytest.approx(32.0 / 35.0)
    assert kpis["km_loaded"] == pytest.approx(26 * 0.5)      # every loaded climb, at full throttle or not
    assert kpis["km_base"] == pytest.approx(21 * 0.5)
    assert kpis["iv_weighted"] == pytest.approx(climbs["iv"].mean())   # same distance: the plain mean
    assert kpis["tonnes"] == pytest.approx(5 * 4 * 200.0)    # one payload per loaded trip


def test_week_kpis_without_climbs():
    kpis = op.week_kpis(None, None)
    assert kpis["iv_median"] is None and kpis["trucks"] == 0
    assert kpis["trips"] == 0 and kpis["loss_per_trip_s"] is None and kpis["lost_share"] is None
    assert kpis["iv_weighted"] is None and kpis["tonnes"] is None


def test_unit_operation(week47):
    table = op.unit_operation(week47.pasadas, week47.camiones).set_index("unidad")
    t3 = table.loc["T3"]
    assert t3["viajes"] == 3 and t3["km_subida"] == pytest.approx(2.5)
    assert t3["carga_motor"] == pytest.approx(80.0) and table.loc["T1", "carga_motor"] == pytest.approx(95.0)
    assert t3["s_perdidos_viaje"] == pytest.approx(20.5 * 60 / 3)
    assert table.loc["T2", "viajes"] == 4
    # Without trip ids (an older pipeline) the per-trip figures are missing, not an error.
    bare = op.unit_operation(week47.pasadas.drop(columns=["viaje"]), week47.camiones)
    assert bare["viajes"].isna().all() and bare["s_perdidos_viaje"].isna().all()
    assert op.unit_operation(None, None).empty


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


def test_unit_stress(week47):
    stress = op.unit_stress(week47.pasadas, week47.camiones).set_index("unidad")
    # The fixture has trips, distance, payload, engine load, grade; no power, rpm or fuel.
    assert op.stress_metrics(stress.reset_index()) == ["viajes", "km_rampa", "carga_t", "h_carga_alta",
                                                       "carga_motor", "pend_subida"]
    assert stress.loc["T2", "viajes"] == 4 and stress.loc["T3", "viajes"] == 3
    assert stress.loc["T1", "km_rampa"] == pytest.approx(7 * 0.5)            # every ramp pass
    assert stress.loc["T1", "carga_t"] == pytest.approx(200.0)
    # Every T1 pass is at 95 % engine load (>= 90): 7 passes of 100 s; T3 runs at 80 %, never high.
    assert stress.loc["T1", "h_carga_alta"] == pytest.approx(700 / 3600)
    assert stress.loc["T3", "h_carga_alta"] == 0
    # Worked like its fleet on everything = index 1; T3's lower engine load puts it under.
    assert stress.loc["T3", "indice_estres"] < 1
    assert set(op.PERFORMANCE_METRICS) <= set(stress.columns)
    assert op.unit_stress(None, None).empty


def test_week_kpis_count_engine_hours_at_high_load(week47):
    kpis = op.week_kpis(week47.camiones, week47.pasadas)
    # T3 (80 %) never counts; the other four units: 7 passes each (T2: 8) of 100 s
    assert kpis["high_load_hours"] == pytest.approx((7 * 3 + 8) * 100 / 3600)
    assert kpis["high_load_top"][0] == "T2"
    assert 0 < kpis["high_load_share"] < 1


def test_performance_by_load_bins(week47):
    assert op.load_variables(week47.pasadas) == ["carga_t", "pend_pct", "carga_motor_pct_media"]
    bins = op.performance_by_load(week47.pasadas, "carga_motor_pct_media", "iv_p50", "T3", bins=2)
    assert len(bins) == 2 and bins["n"].sum() == 26                          # every loaded climb
    assert bins["unidad"].notna().sum() == 1                                  # T3 only in its own bin
    # The payload is the same on every climb: one value, no bins to draw.
    assert op.performance_by_load(week47.pasadas, "carga_t", "iv_p50").empty
    assert op.performance_by_load(None, "carga_t").empty


def test_weekly_history_stops_at_the_selected_week(data_root):
    history = op.load_weekly_history(CLIENT, op.Week(2026, 47))
    assert sorted(history["semana"].unique()) == ["Week46Year2026", "Week47Year2026"]
    assert op.CONFORME in set(history["decision"]) and "Fondo de mina" not in set(history["decision"])
    assert (history["mitad"] - history["lunes"]).dt.days.eq(3).all()
    assert set(op.load_weekly_history(CLIENT, op.Week(2026, 46))["semana"]) == {"Week46Year2026"}
    assert set(op.load_weekly_history(CLIENT, None, "F2")["flota"]) == {"F2"}
    assert op.load_weekly_history("NODATA").empty


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

def _unit_map_inputs(unit):
    week = op.load_week(CLIENT, op.Week(2026, 47))
    points, segments = op.ramp_map_data(CLIENT, op.Week(2026, 47))
    return segments, op.unit_stretches(points, unit, week.curvas), op.unit_ramp_table(week.pasadas, week.rampas, unit)


def test_unit_map_shows_one_ramp_when_selected(data_root):
    from dashboard.components import operation_performance_charts as charts

    segments, stretches, ramps = _unit_map_inputs("T1")
    figure = charts.unit_ramp_map_figure(segments, stretches, ramps, "T1", "iv", "S1")
    points = next(trace for trace in figure.data if trace.mode == "markers" and trace.marker.colorbar)
    assert set(points.customdata[:, 0]) == {"S1"}
    bands = [trace for trace in figure.data if trace.showlegend is not False and trace.name]
    used = [trace.name for trace in bands if any(v is not None for v in trace.lat)]
    assert used == [charts.t("opp.map.band.high")]                    # S1: 8 % median grade
    effort = charts.unit_ramp_map_figure(segments, stretches, ramps, "T1", "carga_motor", None)
    points = next(trace for trace in effort.data if trace.mode == "markers" and trace.marker.colorbar)
    assert points.marker.colorscale[0][1] == charts.EFFORT_SCALE[0][1]


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
        charts.fleet_ramp_map_figure(op.ramp_map_data(CLIENT, op.Week(2026, 47))[1], "satelite", "S1"),
        charts.unit_history_figure(op.load_weekly_history(CLIENT, op.Week(2026, 47)), op.load_history(CLIENT),
                                   "T3", "iv_rel_p50", op.Week(2026, 47)),
        charts.unit_history_figure(op.load_weekly_history(CLIENT), op.load_history(CLIENT), "T3", "iv_p50"),
        charts.unit_ramp_map_figure(*_unit_map_inputs("T3"), "T3", "iv", None),
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
                   charts.retarder_figure(None), charts.quality_figure(None),
                   charts.fleet_ramp_map_figure(pd.DataFrame()),
                   charts.unit_history_figure(pd.DataFrame(), None, "T3"),
                   charts.unit_history_figure(op.load_weekly_history("NODATA"), None, None)):
        assert not figure.data and figure.layout.annotations


def test_fleet_map_puts_demand_under_the_fleet_performance(data_root):
    from dashboard.components import operation_performance_charts as charts

    segments = op.ramp_map_data(CLIENT, op.Week(2026, 47))[1]
    figure = charts.fleet_ramp_map_figure(segments, "satelite", "S1")
    # S1 stretches are 6, 7, 8, 9 %: its three 100 m links average 6.5, 7.5, 8.5 % -> bands mid, mid, high
    bands = {trace.name: trace for trace in figure.data if trace.showlegend}
    assert list(bands) == [charts.t(key) for _, key, _, _ in charts.DEMAND_BANDS]
    widths = [trace.line.width for trace in bands.values()]
    assert widths == sorted(widths)                                   # steeper: wider
    mid = bands[charts.t("opp.map.band.mid")]
    assert sum(v is None for v in mid.lat) >= 2
    performance = next(trace for trace in figure.data if trace.mode == "markers" and trace.marker.colorbar)
    assert list(performance.customdata[:, 0]).count("S1") == 4        # a click gives the ramp id
    labels = next(trace for trace in figure.data if trace.mode == "markers+text")
    assert all(" · " in text for text in labels.text)                 # "S1 · 0,96": the ramp and its IV
    assert figure.layout.showlegend
    assert charts.demand_band(5.9) == 0 and charts.demand_band(6.0) == 1 and charts.demand_band(12) == 3
    hardest = charts.ramp_demand(segments)
    assert hardest["pend_pct"].is_monotonic_decreasing


def test_unit_history_is_a_3_day_moving_mean_against_the_fleet_median(data_root):
    from dashboard.components import operation_performance_charts as charts

    weekly = op.load_weekly_history(CLIENT, op.Week(2026, 47))
    daily = op.load_history(CLIENT)
    figure = charts.unit_history_figure(weekly, daily, "T3", "iv_rel_p50", op.Week(2026, 47))
    assert [trace.mode for trace in figure.data] == ["lines", "lines"]      # no band, no points
    fleet, unit = figure.data
    # T3's days: 0,99 (week 46) and 0,94 (week 47), two days each; 3-day window, equal weights.
    assert list(unit.y) == pytest.approx([0.99, 0.99, 0.94, 0.94])
    # F1's daily median is 1,00 every day (T1, T2 at 1,00; T3 lower).
    assert list(fleet.y) == pytest.approx([1.0] * 4)
    assert list(figure.layout.xaxis.ticktext) == [charts.t("opp.axis.week_short", n=46),
                                                  charts.t("opp.axis.week_short", n=47)]
    assert figure.layout.shapes                                        # thresholds and the shaded week
    # A day with more climbs weighs more in the moving mean.
    days = pd.DataFrame({"dia": pd.to_datetime(["2026-11-16", "2026-11-17"]), "iv_rel_p50": [1.0, 0.9],
                         "pasadas": [30, 10]})
    assert charts._rolling(days, "iv_rel_p50").iloc[-1] == pytest.approx((30 * 1.0 + 10 * 0.9) / 40)


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
    assert "opp-view" in ids                      # the open view survives a rebuild of the page


FLEET_IDS = {
    "opp-fleet-view", "opp-fleet-graph", "opp-fleet-how", "opp-heatmap-extra", "opp-heatmap-extra-wrap",
    "opp-scatter-x", "opp-scatter-x-wrap", "opp-map", "opp-map-base", "opp-map-caption", "opp-ramp-select", "opp-ramp-metric", "opp-ramp-graph",
    "opp-ramp-caption",
}
# Off the page in this version (their figures stay in operation_performance_charts.py).
HIDDEN_IDS = {"opp-ranking-graph", "opp-go-unit", "opp-decision-table", "opp-decision-filter", "opp-stress-graph",
              "opp-stress-view", "opp-curve-units", "opp-history-metric", "opp-unit-map-base", "opp-scatter-graph",
              "opp-heatmap-graph", "opp-scatter-y", "opp-scatter-y-wrap"}
UNIT_IDS = {
    "opp-unit", "opp-unit-focus", "opp-curve-graph", "opp-curve-caption", "opp-history-graph",
    "opp-history-caption", "opp-unit-map", "opp-unit-map-color", "opp-unit-map-caption", "opp-unit-ramps",
    "opp-unit-ramp",
}
PAGE_IDS = FLEET_IDS | UNIT_IDS | {"opp-view-tabs"}


def _view(page, value):
    tabs = next(n for n in _walk(page) if getattr(n, "id", None) == "opp-view-tabs")
    return next(tab for tab in tabs.children if tab.value == value)


@pytest.mark.parametrize("fleet", [None, "F1", "F2"])
def test_the_page_builds_with_every_control_its_callbacks_read(week47, fleet):
    from dashboard.tabs import tab_operation_performance as tab

    page = tab.build_page(op.filter_fleet(week47, fleet), all_fleets=fleet is None)
    assert PAGE_IDS <= _ids(page)
    assert not HIDDEN_IDS & _ids(page)


def test_fleet_and_unit_evidence_are_two_views(week47):
    from dashboard.tabs import tab_operation_performance as tab

    page = tab.build_page(week47, all_fleets=True)
    assert FLEET_IDS <= _ids(_view(page, "flota")) and not UNIT_IDS & _ids(_view(page, "flota"))
    assert UNIT_IDS <= _ids(_view(page, "unidad")) and not FLEET_IDS & _ids(_view(page, "unidad"))
    tabs = next(n for n in _walk(page) if getattr(n, "id", None) == "opp-view-tabs")
    assert tabs.value == "flota"
    assert next(n for n in _walk(tab.build_page(week47, True, "unidad"))
                if getattr(n, "id", None) == "opp-view-tabs").value == "unidad"
    assert next(n for n in _walk(tab.build_page(week47, True, "nope"))
                if getattr(n, "id", None) == "opp-view-tabs").value == "flota"


def test_the_week_figures_are_operational(week47):
    from dashboard.tabs import tab_operation_performance as tab
    from src.i18n import t

    # The week's figures sit inside the fleet view.
    fleet = _view(tab.build_page(week47, all_fleets=True), "flota")
    labels = [n.children for n in _walk(fleet) if getattr(n, "className", None) == "kpi-label"]
    # Minutes lost first, the fleet's speed index second.
    assert labels == [t("opp.kpi.lost_minutes"), t("opp.kpi.iv_fleet"), t("opp.kpi.high_load"), t("opp.kpi.distance")]
    # Week 47 against week 46 (the fixture's only earlier week): each tile carries its change.
    chips = [n.children for n in _walk(fleet) if getattr(n, "className", None) == "kpi-chip"
             and t("opp.kpi.vs_week", n=46) in str(n.children)]
    assert len(chips) == 4


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
    assert t("opp.panel.ranking.title") not in texts
    assert {t("opp.panel.heatmap.title"), t("opp.panel.map.title")} <= set(titles)


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


def _trigger(prop_id, value):
    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    context_value.set(AttributeDict(triggered_inputs=[{"prop_id": prop_id, "value": value}]))


def test_unit_callbacks(data_root):
    from dash.exceptions import PreventUpdate

    from dashboard.callbacks import operation_performance_callbacks as cb

    folder = "Week47Year2026"
    options = [{"value": u} for u in ("T1", "T2", "T3", "T4", "T5")]
    # A unit clicked on the fleet card (a scatter bubble: customdata[0]; a heat map cell: its customdata)
    # becomes the unit under analysis, and its evidence opens.
    assert cb.select_unit({"points": [{"customdata": ["T2", 3]}]}, options) == ("T2", "unidad")
    assert cb.select_unit({"points": [{"customdata": "T4"}]}, options) == ("T4", "unidad")
    with pytest.raises(PreventUpdate):
        cb.select_unit({"points": [{"customdata": ["ZZ", 1]}]}, options)
    with pytest.raises(PreventUpdate):
        cb.select_unit(None, options)
    assert cb.remember_view("unidad") == "unidad"
    assert cb.update_unit_focus("T2", CLIENT, folder, "all") is not None
    figure, caption = cb.update_curve("T4", CLIENT, folder, "all")
    assert "M2" in caption and "T4" in caption and any("T4" in trace.name for trace in figure.data)
    figure, caption = cb.update_curve("T3", CLIENT, folder, "all")
    assert "M1" in caption and not any("T1" in (trace.name or "") for trace in figure.data)
    figure, caption = cb.update_history("T3", CLIENT, folder, "all")
    assert figure.data and "T3" in caption and "2" in caption
    # Week 46 alone: its history stops there.
    figure, caption = cb.update_history("T3", CLIENT, "Week46Year2026", "all")
    assert "1" in caption


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


def test_unit_focus_has_no_probable_cause_and_no_ramps(week47):
    from dashboard.components import operation_performance_views as views
    from src.i18n import t

    focus = views.unit_focus(week47, "T3")
    assert not [n.id for n in _walk(focus) if isinstance(getattr(n, "id", None), dict)]
    texts = " ".join(str(getattr(n, "children", "")) for n in _walk(focus))
    assert "Turbo" not in texts and t("opp.col.cause") not in texts
    assert views.unit_focus(week47, None) is not None


def test_unit_ramps_most_demanding_first(week47):
    from dashboard.components import operation_performance_views as views

    ramps = op.unit_ramp_table(week47.pasadas, week47.rampas, "T1")
    assert list(ramps["rampa_id"]) == ["S1"]                  # S2: one full-throttle climb, below 3
    assert ramps.loc[0, "pend_pct"] == pytest.approx(8.0) and ramps.loc[0, "km"] == pytest.approx(0.5)
    two = pd.DataFrame({"rampa_id": ["A", "B"], "nombre": "", "pend_pct": [6.5, 10.2], "km": 1.0,
                        "pasadas": 5, "iv": [1.0, 0.9], "iv_rel": [1.0, 0.95], "iv_flota": 1.0})
    listed = views.unit_ramp_list(two.sort_values("pend_pct", ascending=False), "A")
    ids = [n.id["rampa"] for n in _walk(listed) if isinstance(getattr(n, "id", None), dict)]
    assert ids == ["", "B", "A"]                               # "all", then by grade
    active = [n.id["rampa"] for n in _walk(listed) if "is-active" in str(getattr(n, "className", ""))]
    assert active == ["A"]
    flags = [n for n in _walk(listed) if getattr(n, "className", None) == "opp-ramp-btn__flag"]
    assert len(flags) == 1                                     # B: relative IV 0,95 < 0,97
    assert op.unit_ramp_table(None, None, "T1").empty


def test_stretch_iv_follows_the_manufacturer_curve(week47):
    curve = pd.DataFrame({"v_kmh": [5.0, 10.0, 20.0], "fuerza_t": [80.0, 40.0, 20.0]})
    # 30 t: between 40 t at 10 km/h and 20 t at 20 km/h -> 15 km/h; above 80 t: no speed.
    assert list(op.expected_speed([30.0, 40.0, 10.0], curve)) == pytest.approx([15.0, 10.0, 20.0])
    assert pd.isna(op.expected_speed([90.0], curve)[0])
    points = pd.DataFrame({"modelo": ["M"], "gvw_t": [300.0], "pend_pct": [8.5], "rr_pct": [1.5], "v_kmh": [12.0]})
    curvas = curve.assign(modelo="M", tipo="propulsión")
    assert op.stretch_iv(points, curvas).iloc[0] == pytest.approx(12.0 / 15.0)


def test_unit_stretches(data_root, week47):
    points, _segments = op.ramp_map_data(CLIENT, op.Week(2026, 47))
    stretches = op.unit_stretches(points, "T3", week47.curvas)
    assert set(stretches["rampa_id"]) == {"S1"} and list(stretches["k"]) == [0, 1, 2, 3]
    assert (stretches["pasadas"] == 3).all() and (stretches["carga_motor"] == 80.0).all()
    assert stretches["iv"].between(0.2, 1.0).all()                 # T3 climbs slower than its curve
    assert op.unit_stretches(points, None, week47.curvas).empty




@pytest.mark.parametrize("view, shown", [("mapa_calor", (True, False)), ("dispersion", (False, True))])
def test_fleet_card_shows_the_selectors_its_view_uses(data_root, view, shown):
    from dashboard.callbacks import operation_performance_callbacks as cb

    figure, how, *styles = cb.update_fleet(view, [], "km_rampa", CLIENT, "Week47Year2026", "all")
    assert figure.data and how
    assert [style is None for style in styles] == list(shown)


def test_fleet_card_figures(data_root):
    from dashboard.callbacks import operation_performance_callbacks as cb
    from dashboard.components import operation_performance_charts as charts

    folder = "Week47Year2026"
    figure = cb.update_fleet("dispersion", [], "km_rampa", CLIENT, folder, "all")[0]
    assert figure.layout.xaxis.title.text == charts.stress_label("km_rampa")
    # The vertical axis is always the IV against the curve, with the curve's 1,00 marked.
    assert figure.layout.yaxis.title.text == charts.stress_label("iv_p50")
    assert any(shape.y0 == 1.0 and shape.y1 == 1.0 for shape in figure.layout.shapes)
    # The fixture weighs every cycle, so the payload is offered; an unknown axis falls back to it.
    figure = cb.update_fleet("dispersion", [], "nope", CLIENT, folder, "all")[0]
    assert figure.layout.xaxis.title.text == charts.stress_label("carga_t")
    # The columns read left to right: decision, load, IV, then the added ones (unknown ones dropped).
    figure = cb.update_fleet("mapa_calor", ["viajes", "not-a-column"], None, CLIENT, folder, "all")[0]
    assert list(figure.layout.xaxis.ticktext) == [
        charts.t("opp.heatmap.decision"), charts._header(charts.stress_label("carga_t")),
        charts._header(charts.stress_label("iv_rel_p50")), charts._header(charts.stress_label("viajes"))]


def test_scatter_and_heatmap_without_payload_use_the_distance(week47):
    from dashboard.tabs import tab_operation_performance as tab

    nominal = op.filter_fleet(week47, None)
    nominal.pasadas = nominal.pasadas.drop(columns=["payload_t_media"])
    assert not nominal.measured_payload
    assert tab.scatter_x_options(nominal) == ["km_rampa"]
    stress = op.unit_stress(nominal.pasadas, nominal.camiones)
    assert tab.heatmap_default_columns(stress, False) == ["km_rampa", "iv_rel_p50"]
    assert "km_rampa" not in tab.heatmap_extra_options(stress, False)
    # Capstone's apparent mass (an estimate) is never the default load column.
    with_mass = stress.assign(carga_t=330.0)
    assert tab.heatmap_default_columns(with_mass, False) == ["km_rampa", "iv_rel_p50"]


def test_fleet_heatmap_puts_the_best_unit_on_top(week47):
    from dashboard.components import operation_performance_charts as charts

    stress = op.unit_stress(week47.pasadas, week47.camiones)
    figure = charts.fleet_heatmap_figure(stress, ["carga_t", "iv_rel_p50", "viajes"])
    # One trace per column, each at its own x (the decision at 0), so cells and their text line up.
    assert [list(trace.x) for trace in figure.data] == [[0], [1], [2], [3]]
    assert list(figure.layout.yaxis.ticktext)[0] == "T1" and list(figure.layout.yaxis.ticktext)[-1] == "T3"
    decision = figure.data[0]
    assert decision.text[0][0] == op.CONFORME and figure.layout.yaxis.autorange == "reversed"
    # The IV column on the performance scale, load and trips against the fleet median.
    assert [trace.coloraxis for trace in figure.data[1:]] == ["coloraxis2", "coloraxis", "coloraxis2"]
    assert all(trace.text is not None and len(trace.text) == len(stress) for trace in figure.data)
    assert figure.data[2].customdata[0][0] == "T1"                       # a click gives the unit
    # Read, not zoomed.
    assert figure.layout.xaxis.fixedrange and figure.layout.yaxis.fixedrange and figure.layout.dragmode is False
    assert not charts.fleet_heatmap_figure(pd.DataFrame(), ["carga_t"]).data


def test_the_fleet_card_opens_on_the_scatter(week47):
    from dashboard.tabs import tab_operation_performance as tab

    page = tab.build_page(week47, all_fleets=True)
    view = next(n for n in _walk(page) if getattr(n, "id", None) == "opp-fleet-view")
    assert view.value == "dispersion" and [o["value"] for o in view.options] == ["dispersion", "mapa_calor"]
    x = next(n for n in _walk(page) if getattr(n, "id", None) == "opp-scatter-x")
    assert type(x).__name__ == "Dropdown"


def test_unit_figures_and_their_trend(data_root):
    from dashboard.components import operation_performance_views as views
    from src.i18n import t

    week47 = op.load_week(CLIENT, op.Week(2026, 47))
    figures = op.unit_figures(week47.camiones, week47.pasadas, "T3")
    assert figures["iv_rel_p50"] == pytest.approx(0.94) and figures["viajes"] == 3
    # 20,5 min lost over 4 full-throttle climbs of 100 s
    assert figures["lost_share"] == pytest.approx(20.5 / (4 * 100 / 60))
    assert op.unit_figures(week47.camiones, week47.pasadas, "ZZ") is None
    base = op.unit_baseline(CLIENT, op.Week(2026, 47), "T3")
    assert [w.number for w in base["weeks"]] == [46] and base["iv_rel_p50"] == pytest.approx(0.94)
    assert op.unit_baseline(CLIENT, op.Week(2026, 46), "T3") is None
    # Every figure of the card carries its change against week 46.
    focus = views.unit_focus(week47, "T3")
    chips = [n for n in _walk(focus) if getattr(n, "className", None) == "kpi-chip"
             and t("opp.kpi.vs_week", n=46) in str(n.children)]
    assert len(chips) == 8
    # Without an earlier week there is nothing to compare: no chip.
    week46 = op.load_week(CLIENT, op.Week(2026, 46))
    assert not [n for n in _walk(views.unit_focus(week46, "T3")) if "vs" in str(getattr(n, "children", ""))
                and getattr(n, "className", None) == "kpi-chip"]


def test_the_value_shows_its_level_and_the_chip_its_change(data_root):
    """Unit 11 in CDA: relative IV 0,95 both weeks. The value is red (under 0,97, Revisar); the chip,
    which only says how it moved, is neutral."""
    from dashboard.components import operation_performance_views as views
    from shared.severity import SEVERITY_TIERS

    assert op.kpi_level("iv_rel_p50", 0.95) == "alto"
    assert op.kpi_level("iv_rel_p50", 0.985) == "atencion" and op.kpi_level("iv_rel_p50", 1.02) == "bajo"
    assert op.kpi_level("iv_p50", 0.99) == "atencion"
    assert op.kpi_level("s_perdidos_viaje", 41, 21) == "alto"         # twice its fleet
    assert op.kpi_level("s_perdidos_viaje", 25, 21) is None and op.kpi_level("s_perdidos_viaje", 20, 21) == "bajo"
    assert op.kpi_level("lost_share", 0.08, 0.04) == "alto"          # loses twice its fleet's share
    assert op.kpi_level("lost_share", 0.08, None) is None
    assert op.kpi_level("viajes", 50) is None
    week47 = op.load_week(CLIENT, op.Week(2026, 47))
    shares = op.unit_lost_shares(week47.camiones, week47.pasadas)
    assert shares["T3"] == pytest.approx(20.5 / (4 * 100 / 60))

    # T3: relative IV 0,94 in weeks 46 and 47.
    stats = [n for n in _walk(views.unit_focus(week47, "T3")) if getattr(n, "className", None) == "opp-stat"]
    value = next(n for n in _walk(stats[0]) if "opp-level" in str(getattr(n, "className", "")))
    assert value.style["color"] == SEVERITY_TIERS["alto"]["text"]
    chip = next(n for n in _walk(stats[0]) if getattr(n, "className", None) == "kpi-chip")
    assert chip.style["background"] != SEVERITY_TIERS["alto"]["bg"]          # steady: neutral chip
    assert chip.children.startswith("0 % vs")                               # no change: "0 %", no arrow
    # Trips have no range of their own: a plain value.
    assert not [n for n in _walk(stats[4]) if "opp-level" in str(getattr(n, "className", ""))]
    # Without an earlier week: the value still shows its level, and there is no chip.
    week46 = op.load_week(CLIENT, op.Week(2026, 46))
    stats = [n for n in _walk(views.unit_focus(week46, "T3")) if getattr(n, "className", None) == "opp-stat"]
    assert [n for n in _walk(stats[0]) if "opp-level" in str(getattr(n, "className", ""))]
    assert not [n for n in _walk(stats[0]) if getattr(n, "className", None) == "kpi-chip"]


def test_kpi_baseline_and_trend(data_root):
    base = op.kpi_baseline(CLIENT, op.Week(2026, 47))
    assert [w.number for w in base["weeks"]] == [46]
    assert op.kpi_baseline(CLIENT, op.Week(2026, 46)) is None             # no earlier week
    week46 = op.load_week(CLIENT, op.Week(2026, 46))
    assert base["lost_minutes"] == pytest.approx(op.week_kpis(week46.camiones, week46.pasadas)["lost_minutes"])
    # Minutes (as a share of the time): lower is better; +10 % is worth attention, +25 % bad.
    assert op.kpi_trend("lost_share", 0.9, 1.0)["tier"] == "bajo"
    assert op.kpi_trend("lost_share", 1.02, 1.0)["tier"] is None
    assert op.kpi_trend("lost_share", 1.10, 1.0)["tier"] == "atencion"
    assert op.kpi_trend("lost_share", 1.25, 1.0)["tier"] == "alto"
    # The speed index: higher is better, its change in % (1 % about the same, 3 % bad).
    assert op.kpi_trend("iv_weighted", 1.03, 1.01)["tier"] == "bajo"
    assert op.kpi_trend("iv_weighted", 0.97, 1.01)["tier"] == "alto"
    assert op.kpi_trend("iv_weighted", 0.99, 1.01)["change"] == pytest.approx(-0.02 / 1.01)
    # The distance is volume: its change is shown without a judgement.
    assert op.kpi_trend("km_loaded", 50.0, 100.0) == {"change": -0.5, "tier": None}
    assert op.kpi_trend("lost_share", None, 1.0) is None and op.kpi_trend("lost_share", 1.0, None) is None


def test_stress_figures(week47):
    from dashboard.components import operation_performance_charts as charts

    stress = op.unit_stress(week47.pasadas, week47.camiones)
    heat = charts.stress_heatmap_figure(stress, True, "T3")
    assert list(heat.data[0].y)[0] == stress.sort_values("indice_estres")["unidad"].iloc[0]
    assert heat.data[0].x[-1] == charts.t("opp.stress.metric.indice_estres")
    assert "<b>▶ T3</b>" in heat.layout.yaxis.ticktext
    scatter = charts.stress_scatter_figure(stress, "viajes", "iv_rel_p50", True, "T3")
    assert {trace.name for trace in scatter.data} == set(stress["decision"])
    bars = charts.stress_bars_figure(stress, "viajes", True, "T3")
    assert list(bars.layout.xaxis.categoryarray)[0] == "T2"                   # most trips first
    # Without payload the load is the apparent mass, and says so.
    assert charts.stress_label("carga_t", False) != charts.stress_label("carga_t", True)


def test_fleet_ramp_selection_follows_the_map_and_the_unit(data_root):
    from dashboard.callbacks import operation_performance_callbacks as cb

    folder = "Week47Year2026"
    options = [{"value": "S1"}, {"value": "S2"}]

    def fire(prop_id, value, *args):
        _trigger(prop_id, value)
        return cb.select_ramp(*args, options, CLIENT, folder, "all")

    click = {"points": [{"customdata": ["S2", "Subida", "0–100 m", 6, 6, 15, 5]}]}
    assert fire("opp-map.clickData", click, "T1", click) == "S2"
    assert fire("opp-unit.value", "T3", "T3", None) == "S1"


def test_unit_ramp_selection(data_root):
    from dash.exceptions import PreventUpdate

    from dashboard.callbacks import operation_performance_callbacks as cb

    button = '{"rampa":"S1","type":"opp-unit-ramp-btn"}.n_clicks'
    _trigger(button, 1)
    assert cb.select_unit_ramp([1], None, "T3") == "S1"
    _trigger('{"rampa":"","type":"opp-unit-ramp-btn"}.n_clicks', 1)
    assert cb.select_unit_ramp([1], None, "T3") is None               # "Todas las rampas"
    _trigger(button, 0)
    with pytest.raises(PreventUpdate):                                # the list redrawn is not a click
        cb.select_unit_ramp([0], None, "T3")
    click = {"points": [{"customdata": ["S1", "x"]}]}
    _trigger("opp-unit-map.clickData", click)
    assert cb.select_unit_ramp([], click, "T3") == "S1"
    _trigger("opp-unit.value", "T2")
    assert cb.select_unit_ramp([], click, "T2") is None              # a new unit shows every ramp
    listed = cb.update_unit_ramps("T3", "S1", CLIENT, "Week47Year2026", "all")
    assert [n.id["rampa"] for n in _walk(listed) if isinstance(getattr(n, "id", None), dict)] == ["", "S1"]


def test_ramp_and_map_callbacks(data_root):
    from dashboard.callbacks import operation_performance_callbacks as cb

    folder = "Week47Year2026"
    figure, caption, style = cb.update_ramp("S1", "iv", "T3", CLIENT, folder, "all")
    assert any("T3" in trace.name for trace in figure.data) and caption
    assert style == {"minWidth": f"{cb.BOX_PX_PER_UNIT * 5 + 120}px"}          # wide enough for 5 boxes
    for base in ("satelite", "calles"):
        figure, caption = cb.update_map(base, "S1", CLIENT, folder, "all")
        assert figure.data and "S1" in caption
    satellite = cb.update_map("satelite", "S1", CLIENT, folder, "all")[0]
    assert satellite.layout.map.layers[0].sourcetype == "raster"
    # A unit without enough climbs on the map's ramps gets a message, never another coloring.
    for color in ("iv", "carga_motor", "rpm"):
        figure, caption = cb.update_unit_map(color, "T3", None, CLIENT, folder, "all")
        assert figure.data and "T3" in caption
    figure, caption = cb.update_unit_map("iv", "T3", "S1", CLIENT, folder, "all")
    assert "4 de 4" in caption or "4 of 4" in caption                 # every S1 stretch below its curve
    # A unit without enough climbs on the map's ramps gets a message, never another coloring.
    figure, caption = cb.update_unit_map("iv", "ZZ", None, CLIENT, folder, "all")
    assert not figure.data and figure.layout.annotations and caption == ""
    # The decision table is off the page; its rows (kept for when it returns) still carry the operation.
    from dashboard.components import operation_performance_views as views
    data = op.load_week(CLIENT, op.Week(2026, 47))
    rows = views.decision_rows(data.camiones, [op.REVISAR], op.unit_operation(data.pasadas, data.camiones))
    assert rows[0]["id"] == "T3" and rows[0]["viajes"] == 3 and rows[0]["s_perdidos_viaje"] == pytest.approx(410.0)


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
        charts.fleet_ramp_map_figure(segments, "satelite", segments["rampa_id"].iloc[0]).to_json()
        weekly = op.load_weekly_history(client, week, fleet)
        charts.unit_history_figure(weekly, op.load_history(client, fleet), unit, "iv_rel_p50", week).to_json()
        fleet_data = op.filter_fleet(data, fleet)
        stretches = op.unit_stretches(points, unit, fleet_data.curvas)
        ramps = op.unit_ramp_table(fleet_data.pasadas, fleet_data.rampas, unit)
        assert not stretches.empty and stretches["iv"].notna().mean() > 0.9
        assert ramps["pend_pct"].is_monotonic_decreasing
        charts.unit_ramp_map_figure(segments, stretches, ramps, unit, "iv", ramps["rampa_id"].iloc[0]).to_json()
        kpis = op.week_kpis(op.filter_fleet(data, fleet).camiones, op.filter_fleet(data, fleet).pasadas)
        assert kpis["trips"] > 0 and kpis["km_loaded"] > 0 and kpis["high_load_hours"] > 0
        fleet_data = op.filter_fleet(data, fleet)
        stress = op.unit_stress(fleet_data.pasadas, fleet_data.camiones)
        assert {"viajes", "km_rampa", "carga_t", "carga_motor", "rpm"} <= set(op.stress_metrics(stress))
        charts.stress_heatmap_figure(stress, data.measured_payload, unit).to_json()
        charts.stress_scatter_figure(stress, "carga_t", "iv_rel_p50", data.measured_payload, unit).to_json()
        bins = op.performance_by_load(fleet_data.pasadas, "carga_t", "iv_p50", unit)
        assert len(bins) == op.LOAD_BINS
        charts.load_performance_figure(bins, "carga_t", "iv_p50", unit, data.measured_payload).to_json()
