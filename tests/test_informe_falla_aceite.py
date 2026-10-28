"""Informe preliminar de falla: muestras de aceite del sistema (src/informe_falla/aceite.py).

Las muestras son sinteticas: ninguna prueba lee data/.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.informe_falla import aceite as a, agent, config, report_html

FECHA, DESDE = "2025-12-05", "2025-09-01"
PERFIL = config.perfil_cliente("CAPSTONE")


def _muestra(dia, unidad="CA-30", componente="MOTOR DIESEL", normalizado="motor diesel", horas_aceite=100.0,
             estado="Normal", fuera=(), anomalia="Normal", recomendacion="Continuar con monitoreo."):
    return {
        "unitId": unidad, "sampleDate": pd.Timestamp(dia), "componentName": componente,
        "componentNameNormalized": normalizado, "componentHours": 500.0, "oilMeter": horas_aceite,
        "report_status": estado, "anomalyType": anomalia, "ai_recommendation": recomendacion,
        "breached_essays": json.dumps([{"essay": e, "value": 8.4, "threshold": n, "limit": 3.5} for e, n in fuera]),
    }


@pytest.fixture
def fuente(monkeypatch):
    def usar(filas):
        tabla = a._preparar(pd.DataFrame(filas))
        monkeypatch.setattr(a, "_cargar", lambda cliente: tabla)
    return usar


def _evid(aceite_):
    return {"consulta": {"unidad": "CA-30", "fecha": FECHA}, "ranking_modos": [
        {"modo": "bearing_wear_risk", "nivel": "alto"}, {"modo": "thermal_imbalance_risk", "nivel": "alto"},
        {"modo": "blowby_risk", "nivel": "ninguno"}], "aceite": aceite_}


def test_solo_muestras_del_sistema_en_la_ventana(fuente):
    fuente([
        _muestra("2025-08-31"),                                                     # antes de la ventana
        _muestra("2025-09-01"),
        _muestra("2025-11-29"),
        _muestra("2025-11-30", componente="Motor de giro", normalizado="motor de giro"),   # otro sistema
        _muestra("2025-11-30", unidad="CA-31"),
        _muestra(FECHA),                                                            # el dia de la detencion
        _muestra("2025-12-08"),                                                     # posterior
    ])
    r = a.muestras_aceite("CAPSTONE", "CA-30", FECHA, DESDE)
    assert r["disponible"] and r["componentes"] == ["Motor diesel"]
    assert [m["fecha"] for m in r["muestras"]] == ["2025-09-01", "2025-11-29"]
    assert r["muestras"][-1]["dias_antes"] == 6
    assert (r["ventana_desde"], r["ventana_hasta"]) == ("2025-09-01", "2025-12-04")


def test_niveles_cualitativos_sin_concentraciones(fuente):
    fuente([_muestra("2025-11-22", estado="Alerta", fuera=[("Cobre", "Critico"), ("Viscocidad", "Marginal")],
                     recomendacion="Diagnóstico: cobre alto (Cu 8,4 ppm, K 2,7 ppm). Acción: Cambio de lubricante. "
                                   "Seguimiento cada 125 hrs.")])
    m = a.muestras_aceite("CAPSTONE", "CA-30", FECHA, DESDE)["muestras"][0]
    assert m["fuera_de_limite"] == {"Cobre": "crítico", "Viscosidad": "marginal"}
    assert "ppm" not in m["recomendacion"] and "8,4" not in m["recomendacion"]
    assert "cada 125 hrs" in m["recomendacion"]


def test_cambio_de_aceite_por_componente(fuente):
    fuente([
        _muestra("2025-10-01", componente="Motor diesel delantero", normalizado="motor diesel delantero", horas_aceite=50),
        _muestra("2025-10-02", componente="Motor diesel trasero", normalizado="motor diesel trasero", horas_aceite=400),
        _muestra("2025-10-10", componente="Motor diesel delantero", normalizado="motor diesel delantero", horas_aceite=200),
        _muestra("2025-10-11", componente="Motor diesel trasero", normalizado="motor diesel trasero", horas_aceite=20),
    ])
    r = a.muestras_aceite("CAPSTONE", "CA-30", FECHA, DESDE)
    assert r["componentes"] == ["Motor diesel delantero", "Motor diesel trasero"]
    # La primera de cada componente no marca cambio; solo el trasero reinicio su horometro.
    assert [(m["fecha"], m["cambio_de_aceite"]) for m in r["muestras"]] == [
        ("2025-10-01", False), ("2025-10-02", False), ("2025-10-10", False), ("2025-10-11", True)]


def test_sin_fuente_o_sistema_sin_componentes(fuente):
    fuente([])
    assert a.muestras_aceite("CAPSTONE", "CA-30", FECHA, DESDE)["motivo"] == "sin_fuente"
    assert a.muestras_aceite("CAPSTONE", "CA-30", FECHA, DESDE, sistema="transmision")["motivo"] == "sistema_sin_componentes"


def _con_muestras(fuente):
    fuente([_muestra("2025-11-06", estado="Alerta", fuera=[("Cobre", "Critico")], anomalia="Desgaste de Componentes",
                     recomendacion="Diagnóstico: desgaste. Acción: Cambio inmediato de lubricante."),
            _muestra("2025-11-29")])
    return _evid(a.muestras_aceite("CAPSTONE", "CA-30", FECHA, DESDE))


def test_observaciones_con_la_ia(fuente):
    evid = _con_muestras(fuente)
    recibido = {}

    def llm(system, user, esquema):
        recibido.update(json.loads(user))
        assert esquema is a.ESQUEMA_OBSERVACIONES
        return json.dumps({"diagnostico": "Cobre crítico desde el 6 nov.", "causa_probable": "Se sospecha desgaste."})

    obs = a.observaciones_laboratorio(evid, "CAPSTONE", PERFIL, llm)
    assert obs == {"origen": "ia", "diagnostico": "Cobre crítico desde el 6 nov.",
                   "causa_probable": "Se sospecha desgaste.", "controles": []}
    # La IA recibe los modos destacados con sus ensayos de aceite (un modo sin ensayos queda con la lista vacia)
    # y el diagnostico y la accion del laboratorio por separado.
    modos = {m["modo"]: m["ensayos_aceite"] for m in recibido["modos_destacados"]}
    assert "Cobre" in modos["Desgaste de cojinetes"]
    assert modos["Temperatura dispareja entre lados del motor"] == []
    primera = recibido["muestras"][0]
    assert primera["ensayos_fuera_de_limite"] == {"Cobre": "crítico"}
    assert (primera["diagnostico_laboratorio"], primera["accion_laboratorio"]) == ("desgaste.", "Cambio inmediato de lubricante.")


def test_asentamiento_y_cambio_de_motor(fuente):
    """Las horas del motor que vuelven a partir marcan un cambio de motor; bajo RODAJE_HORAS_MOTOR, asentamiento."""
    fuente([{**_muestra("2025-10-01"), "componentHours": 28000.0}, {**_muestra("2025-10-29"), "componentHours": 0.0},
            {**_muestra("2025-11-29"), "componentHours": a.RODAJE_HORAS_MOTOR + 92.0}])
    muestras = a.entrada_observaciones(_evid(a.muestras_aceite("CAPSTONE", "CA-30", FECHA, DESDE)), "CAPSTONE", PERFIL)["muestras"]
    assert [m["horas_motor_reinician_desde_la_anterior"] for m in muestras] == [False, True, False]
    assert [m["motor_en_asentamiento"] for m in muestras] == [False, True, False]


@pytest.mark.parametrize("respuesta", [
    lambda *_: json.dumps({"diagnostico": "Cobre en 8,4 ppm.", "causa_probable": "Desgaste."}),   # valores
    lambda *_: json.dumps({"veredicto": "otro formato"}),                                          # esquema
    lambda *_: (_ for _ in ()).throw(RuntimeError("sin red")),                                    # error
])
def test_observaciones_sin_ia_cuando_la_respuesta_no_sirve(fuente, respuesta):
    obs = a.observaciones_laboratorio(_con_muestras(fuente), "CAPSTONE", PERFIL, respuesta)
    assert obs["origen"] == "sin_ia"
    assert obs["diagnostico"] == "1 de 2 muestras con resultado fuera de lo normal: Desgaste de Componentes (1, desde el 6 nov)."


def test_texto_largo_se_acepta_con_aviso(fuente):
    largo = " ".join(["palabra"] * 80)
    obs = a.observaciones_laboratorio(_con_muestras(fuente), "CAPSTONE", PERFIL,
                                      lambda *_: json.dumps({"diagnostico": largo, "causa_probable": "Desgaste."}))
    assert obs["origen"] == "ia" and obs["controles"] == ["diagnostico: 1 frases, 80 palabras"]
    assert "Observaciones del laboratorio" in report_html.problemas({"evidencia": {"aceite": {"observaciones": obs}}})[0]


def test_sin_muestras_no_se_llama_a_la_ia(fuente):
    fuente([_muestra("2025-12-08")])
    evid = _evid(a.muestras_aceite("CAPSTONE", "CA-30", FECHA, DESDE))
    assert a.observaciones_laboratorio(evid, "CAPSTONE", PERFIL, lambda *_: pytest.fail("no debe llamarse")) is None


def test_tarjeta_del_informe(fuente):
    evid = _con_muestras(fuente)
    evid["aceite"]["observaciones"] = {"origen": "ia", "diagnostico": "Cobre crítico desde el 6 nov.",
                                       "causa_probable": "Se sospecha desgaste.", "controles": []}
    html = report_html._bloque_aceite(evid)
    assert "<h2>2. Aceite</h2>" in html and "<svg" in html
    assert ("Motor diesel: 2 muestras de aceite entre el 1 sep 2025 y el 4 dic 2025; 1 con resultado fuera de lo "
            "normal (1 en Alerta). La última se tomó el 29 nov 2025, 6 días antes de la detención, con resultado Normal.") in html
    assert "Cobre (crítico)" in html and "ppm" not in html
    # El diagnostico y la causa probable van en el mismo recuadro que Monitoreo de riesgo, con su nota.
    assert report_html._cierre("Cobre crítico desde el 6 nov.", "Se sospecha desgaste.",
                               "Resumen de las recomendaciones del laboratorio de 2 muestras, del 6 nov 2025 al 29 nov 2025.") in html


def test_tarjeta_sin_muestras_y_sin_fuente(fuente):
    fuente([_muestra("2025-12-08")])
    html = report_html._bloque_aceite(_evid(a.muestras_aceite("CAPSTONE", "CA-30", FECHA, DESDE)))
    assert "Motor: no hay muestras de aceite entre el 1 sep 2025 y el 4 dic 2025." in html
    fuente([])
    assert report_html._bloque_aceite(_evid(a.muestras_aceite("CAPSTONE", "CA-30", FECHA, DESDE))) == ""
    assert report_html._bloque_aceite({"consulta": {"unidad": "CA-30", "fecha": FECHA}}) == ""   # registros antiguos


def test_la_ia_del_informe_no_recibe_el_aceite():
    enviada = agent.evidencia_para_ia({"consulta": {"unidad": "CA-30"}, "aceite": {"muestras": [1]}})
    assert "aceite" not in enviada


# ---------------------------------------------------------------------------
# Con la data real (data/): se saltan si la copia local no esta
# ---------------------------------------------------------------------------
DATA_ACEITE = config.PROJECT_ROOT / "data" / "oil" / "golden" / "capstone" / "classified.parquet"
DATA_PREDICTIVO = config.PROJECT_ROOT / "data" / "predictive" / "golden" / "capstone"
con_data = pytest.mark.skipif(not DATA_ACEITE.is_file(), reason="sin data/oil local de Capstone")
con_data_completa = pytest.mark.skipif(not (DATA_ACEITE.is_file() and DATA_PREDICTIVO.is_dir()),
                                       reason="sin data/ local de Capstone (aceite y Predictivo)")

# Los dos casos revisados en el notebook borrador: (unidad, fecha, inicio de la ventana, muestras, fuera de lo normal,
# ultima muestra, su resultado, cambios de aceite inferidos).
CASOS = [
    ("CA-30", "2025-12-05", "2025-09-01", 13, 9, "2025-11-29", "Normal",
     ["2025-09-19", "2025-09-26", "2025-11-02", "2025-11-29"]),
    ("CA-80", "2026-10-04", "2026-06-29", 12, 9, "2026-10-01", "Alerta",
     ["2026-08-09", "2026-09-02", "2026-09-18", "2026-10-01"]),
]


@con_data
@pytest.mark.parametrize("unidad, fecha, desde, n, fuera, ultima, resultado, cambios", CASOS)
def test_data_real_muestras_de_la_ventana(unidad, fecha, desde, n, fuera, ultima, resultado, cambios):
    r = a.muestras_aceite("CAPSTONE", unidad, fecha, desde)
    ms = r["muestras"]
    assert r["disponible"] and r["componentes"] == ["Motor diesel"]
    assert len(ms) == n and sum(m["resultado"] != "Normal" for m in ms) == fuera
    assert (ms[-1]["fecha"], ms[-1]["resultado"]) == (ultima, resultado)
    assert [m["fecha"] for m in ms if m["cambio_de_aceite"]] == cambios
    # Nada fuera de la ventana y ninguna concentracion en lo que viaja.
    assert all(desde <= m["fecha"] < fecha for m in ms)
    assert not any(a._VALOR.search(m["recomendacion"]) for m in ms)


@con_data_completa
@pytest.mark.parametrize("unidad, fecha, desde, n, fuera, ultima, resultado, cambios", CASOS)
def test_data_real_informe_con_la_tarjeta(monkeypatch, tmp_path, unidad, fecha, desde, n, fuera, ultima, resultado, cambios):
    """El flujo del boton del dashboard (service.generar_informe) con la data real; la IA y el PDF simulados."""
    from src.informe_falla import service
    from src.informe_falla.probar_informe import ia_de_relleno

    monkeypatch.setenv("INFORME_FALLA_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("INFORME_FALLA_ORIGEN", "local")
    monkeypatch.setattr(service, "pdf_disponible", lambda: True)
    documentos = []
    monkeypatch.setattr(service, "html_a_pdf", lambda html: documentos.append(html) or b"%PDF-sintetico")
    esquemas = []

    def llm(system, user, esquema):
        esquemas.append(esquema["name"])
        return ia_de_relleno(system, user, esquema)

    etapas = []
    resultado_ = service.generar_informe({"client": "CAPSTONE", "unit": unidad, "event_date": fecha, "system": "motor",
                                          "images": [], "requested_by": "pytest"}, llm_fn=llm, avance=etapas.append)
    assert resultado_["status"] == service.STATUS_READY
    assert etapas == list(service.ETAPAS)             # la barra de progreso de la vista pasa por todas, en orden
    # Aceite, Detenciones (solo con registros de mantencion: CA-80 no tiene) y el Resumen, en ese orden.
    con_registros = unidad == "CA-30"
    assert esquemas == (["aceite_diagnostico_causa"] + (["detenciones_diagnostico_causa"] if con_registros else [])
                        + ["resumen_secciones"])
    html = documentos[0]
    assert (html.index("<h2>1. Resumen</h2>") < html.index("<h2>2. Aceite</h2>")
            < html.index("<h2>3. Monitoreo de riesgo</h2>") < html.index("<h2>4. Detenciones</h2>"))
    assert "calefacción" not in html                # la cabina no es del motor (CA-30 tiene un registro)
    assert f"{n} muestras de aceite" in html and f"{fuera} con resultado fuera de lo normal" in html
    assert f"Última: {report_html._fecha_corta(ultima)}" in html
    assert "Resumen de las recomendaciones del laboratorio" in html and "ppm" not in html
    assert "Aceite: incorporado" in html
