"""Coherencia con el predictivo 1.3: estado final, sin_datos y Desgaste Acelerado."""

import pandas as pd
import pytest

from dashboard.components import fleet_overview
from dashboard.components.predictive_state import (
    NO_DATA_STATE, combine_states, is_no_data_state, published_state,
)
from dashboard.tabs import tab_predictive_overview as ov
from src.data import predictive_catalog, report_health
from src.data.report_store import TECHNIQUE_PREDICTIVE


# ---------------------------------------------------------------- vocabulario

def test_sin_datos_publicado_no_es_lo_mismo_que_unidad_ausente():
    assert is_no_data_state("sin_datos") and is_no_data_state("SIN_DATOS")
    assert not is_no_data_state("Sin Datos")        # etiqueta de "unidad sin fila"
    assert published_state("sin_datos") == NO_DATA_STATE
    assert published_state("anormal") == "Anormal" and published_state(None) is None


def test_combine_sin_datos_publicado_gana_sobre_la_curva():
    assert combine_states("sin_datos", "Anormal") == NO_DATA_STATE
    assert combine_states("Sin Datos", "Anormal") == "Anormal"   # ausente: la curva cuenta
    assert combine_states("normal", "Alerta") == "Alerta"


# ---------------------------------------------------------------- Vista general

def _resumen(formato_13: bool) -> pd.DataFrame:
    df = pd.DataFrame({
        "Unit": ["CA-41", "CA-46", "CA-50"],
        "estado": ["anormal", "sin_datos", "normal"],
        "media_7d": [20.0, None, 10.0], "media_90d": [25.0, None, 12.0],
    })
    if formato_13:
        df["estado_actual"] = ["normal", "sin_datos", "normal"]
        df["estado_ciclo_vida"] = ["anormal", "alerta", None]
        df["origen_estado"] = ["ciclo_vida", "sin_datos", "actual"]
    else:
        df["estado"] = ["normal", "sin_datos", "normal"]           # condicion actual
    return df


@pytest.fixture
def latest():
    return pd.DataFrame({"Unit": ["CA-41", "CA-46", "CA-50"], "ranking": [30.0, 40.0, 10.0],
                         "avg_ranking_7d": [99.0, 99.0, 99.0], "ranking_acum_90d": [99.0, 99.0, 99.0]})


@pytest.fixture
def curva_anormal(monkeypatch):
    monkeypatch.setattr(ov.predictive_v2, "active_cycle_estado",
                        lambda active: {"CA-41": "Anormal", "CA-46": "Anormal", "CA-50": "Normal"})


def test_13_vista_corta_usa_estado_actual_y_kpis_el_estado_final(monkeypatch, latest, curva_anormal):
    monkeypatch.setattr(ov.predictive_v2, "load_unit_status_summary", lambda c, comp: _resumen(True))
    out = ov.attach_general_status(ov.attach_status(latest, "capstone", "motor"), active=object())
    e = out.set_index("Unit")
    # Cuadrantes: estado_actual (CA-41 esta en Normal por sus medias)
    assert e.loc["CA-41", "status"] == "Normal"
    # KPIs / tablas: estado final publicado, sin volver a combinar
    assert e.loc["CA-41", "general_status"] == "Anormal" and e.loc["CA-41", "origen_estado"] == "ciclo_vida"
    assert e.loc["CA-46", "general_status"] == NO_DATA_STATE            # no toma la curva
    assert e.loc["CA-50", "general_status"] == "Normal"
    # El punto se ubica con las medias publicadas, no recalculadas
    assert e.loc["CA-41", "avg_ranking_7d"] == 20.0 and e.loc["CA-41", "ranking_acum_90d"] == 25.0
    assert e.loc["CA-46", "avg_ranking_7d"] == 99.0                    # sin media publicada: la propia


def test_anterior_a_13_combina_pero_sin_datos_no_toma_la_curva(monkeypatch, latest, curva_anormal):
    monkeypatch.setattr(ov.predictive_v2, "load_unit_status_summary", lambda c, comp: _resumen(False))
    out = ov.attach_general_status(ov.attach_status(latest, "capstone", "motor"), active=object())
    e = out.set_index("Unit")
    assert e.loc["CA-41", "general_status"] == "Anormal"               # combina con la curva
    assert e.loc["CA-46", "status"] == NO_DATA_STATE and e.loc["CA-46", "general_status"] == NO_DATA_STATE
    assert "final_status" not in out.columns


def test_unidad_ausente_del_resumen_sigue_tomando_la_curva(monkeypatch, latest, curva_anormal):
    r = _resumen(False).iloc[[0, 2]]                                    # CA-46 no esta
    monkeypatch.setattr(ov.predictive_v2, "load_unit_status_summary", lambda c, comp: r)
    e = ov.attach_general_status(ov.attach_status(latest, "capstone", "motor"), active=object()).set_index("Unit")
    assert e.loc["CA-46", "status"] == "Sin Datos" and e.loc["CA-46", "general_status"] == "Anormal"


# ---------------------------------------------------------------- pestaña General

def test_general_lee_sin_datos_como_sin_datos(monkeypatch):
    from src.data import predictive_v2
    monkeypatch.setattr(predictive_v2, "load_unit_status_summary", lambda c, comp: _resumen(True))
    estados, _ = fleet_overview._component_predictive_status_maps("capstone", "motor")
    assert estados[fleet_overview._normalize_unit_id("CA-46")] == NO_DATA_STATE
    assert estados[fleet_overview._normalize_unit_id("CA-41")] == "Anormal"


# ---------------------------------------------------------------- Reportabilidad

def test_reportabilidad_sin_datos_no_toma_la_curva():
    analisis = pd.DataFrame({"Unit": ["CA-46", "CA-41"], "Fecha": ["2026-11-06", "2026-11-06"],
                             "estado": ["sin_datos", "normal"], "year": [2026, 2026], "week": [45, 45]})
    curva = pd.DataFrame({"Unit": ["CA-46", "CA-41"], "Fecha": ["2026-11-01", "2026-11-01"],
                          "estado": ["Anormal", "Anormal"]})
    registros = [{"technique": TECHNIQUE_PREDICTIVE, "system": "motor", "unit": u, "date": "2026-11-07"}
                 for u in ("CA-46", "CA-41")]
    out = report_health.attach_health(registros, "capstone",
                                      loaders={TECHNIQUE_PREDICTIVE: lambda c, s: analisis},
                                      curve_loaders={TECHNIQUE_PREDICTIVE: lambda c, s: curva})
    salud = {r["unit"]: r["health"] for r in out}
    assert salud == {"CA-46": "sin_datos", "CA-41": "anormal"}


# ---------------------------------------------------------------- D2

def test_desgaste_acelerado_mismo_nombre_que_los_otros_repos():
    texto = str(predictive_catalog.__dict__)
    assert "Desgaste Acelerado" in texto and "Desgaste metálico acumulado del componente en su vida actual" not in texto


# ================================================================ parte 2: modos

from dashboard.tabs import tab_predictive_evidence as ev
from src.data import predictive_v2


def _rs_largo(con_valor=True):
    df = pd.DataFrame([
        ("CA-41", "2026-11-06", "combustion_risk", 12.0, "Prioridad alta", 3.5),
        ("CA-41", "2026-11-06", "ranking", 40.0, "Monitoreo", 40.0),
        ("CA-41", "2026-11-05", "combustion_risk", 2.0, "Monitoreo", None),   # particion antigua
    ], columns=["Unit", "Fecha", "failure_mode", "risk_value", "risk_level", "risk_level_value"])
    return df if con_valor else df.drop(columns="risk_level_value")


def test_numero_de_cada_modo_es_risk_level_value():
    w = predictive_v2.risk_scores_to_wide(_rs_largo()).set_index("Fecha")
    assert w.loc[pd.Timestamp("2026-11-06"), "combustion_risk"] == 3.5     # no el 12.0 del dia
    assert w.loc[pd.Timestamp("2026-11-05"), "combustion_risk"] == 2.0     # sin valor: el del dia
    assert w.loc[pd.Timestamp("2026-11-06"), "ranking"] == 40.0            # el ranking no cambia
    sin = predictive_v2.risk_scores_to_wide(_rs_largo(con_valor=False)).set_index("Fecha")
    assert sin.loc[pd.Timestamp("2026-11-06"), "combustion_risk"] == 12.0


def test_unidades_sin_datos_desde_el_resumen(monkeypatch):
    monkeypatch.setattr(predictive_v2, "load_unit_status_summary", lambda c, comp: _resumen(True))
    assert predictive_v2.units_without_data("capstone", "motor") == {"CA-46"}
    monkeypatch.setattr(predictive_v2, "load_unit_status_summary", lambda c, comp: _resumen(False))
    assert predictive_v2.units_without_data("capstone", "motor") == {"CA-46"}


def test_tabla_sin_niveles_de_modo_para_unidad_sin_datos(monkeypatch):
    niveles = pd.DataFrame({"combustion_risk": ["Critico", "Monitoreo"]}, index=pd.Index(["CA-46", "CA-41"], name="Unit"))
    monkeypatch.setattr(ov.predictive_v2, "load_risk_levels", lambda c, comp: pd.DataFrame())
    monkeypatch.setattr(ov.predictive_v2, "latest_risk_levels", lambda w: niveles.copy())
    monkeypatch.setattr(ov.predictive_v2, "units_without_data", lambda c, comp: {"CA-46"})
    out = ov.load_latest_risk_levels("capstone", "motor")
    assert out.loc["CA-46", "combustion_risk"] is None and out.loc["CA-41", "combustion_risk"] == "Monitoreo"


def _niveles_unidad(**por_modo):
    return pd.DataFrame({"Fecha": [pd.Timestamp("2026-11-06")], **{m: [v] for m, v in por_modo.items()}})


def test_modo_dominante_por_nivel_y_luego_por_valor():
    niveles = _niveles_unidad(a_risk="Monitoreo", b_risk="Prioridad alta", c_risk="Prioridad alta")
    # a_risk tiene el mayor numero, pero su nivel es menor: no es el dominante.
    assert ev._dominant_mode(["a_risk", "b_risk", "c_risk"],
                             {"a_risk": 90.0, "b_risk": 4.0, "c_risk": 7.0}, niveles) == "c_risk"


def test_aviso_si_el_analisis_no_coincide_con_los_niveles(monkeypatch):
    niveles = _niveles_unidad(combustion_risk="Prioridad alta")
    mfa = pd.DataFrame({"Unit": ["CA-83"], "failure_mode": ["combustion_risk"], "criticidad": ["Monitoreo"]})
    monkeypatch.setattr(ev.predictive_v2, "read_latest_partition", lambda base: mfa)
    assert "volver a correr" in ev._aviso_textos_desfasados("capstone", "motor", "CA-83", niveles).lower()
    mfa.loc[0, "criticidad"] = "Prioridad alta"
    assert ev._aviso_textos_desfasados("capstone", "motor", "CA-83", niveles) is None