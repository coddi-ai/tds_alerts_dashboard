"""Informe preliminar de falla: la IA por seccion (src/informe_falla/secciones.py). Ninguna prueba llama a OpenAI."""

from __future__ import annotations

import json

import pytest

from src.informe_falla import catalog as c, config, report_html, secciones

PERFIL = config.perfil_cliente("CAPSTONE")


def _previa(fecha="2025-10-31", **cambios):
    return {"fecha": fecha, "dias_antes": 35, "tipo": "Correctiva", "subsistema": "Sistema de Lubricación",
            "componentes": "Líneas de Aceite de Motor", "descripcion": "Se identificó filtración de aceite.",
            "sin_cierre": False, "cerca_de_la_detencion": False,
            "modos_relacionados": [{"modo": "lubrication_failure_risk", "por": "subsistema"}], **cambios}


def _evid(previas=(), techo="media", aceite=None):
    return {
        "consulta": {"unidad": "CA-30", "fecha": "2025-12-05"},
        "ventanas": {"periodo_desde": "2025-09-01", "periodo_hasta": "2025-12-04"},
        "ranking_modos": [{"modo": "lubrication_failure_risk", "nivel": "alto"}, {"modo": "blowby_risk", "nivel": "bajo"}],
        "auditoria": {"techo_confianza": techo, "advertencias": ["Línea base corta."]},
        "detenciones_previas": None if previas is None else list(previas),
        "antecedentes_mantencion": {"ultimo_pm": {"fecha": "2025-11-15", "dias_antes": 20}, "recurrencia": [],
                                    "rellenos": {"aceite": {"n": 3, "fechas": []}}},
        "analisis_unidad": {"disponible": False},
        "aceite": aceite or {"disponible": True, "muestras": []},
    }


def _no_llamar(*_):
    pytest.fail("no debe llamarse a la IA")


def test_los_lineamientos_son_los_del_informe():
    texto = secciones.lineamientos(PERFIL)
    assert texto.startswith("Principios") and "Lenguaje" in texto and "Prohibido" in texto
    assert "Diagnóstico (máximo" not in texto and "Casos especiales" not in texto


@pytest.mark.parametrize("previas, diagnostico", [
    (None, secciones.SIN_REGISTROS["diagnostico"]),
    ([], "No hubo intervenciones del motor en los 3 meses previos a la detención."),
])
def test_detenciones_sin_registros_es_texto_fijo(previas, diagnostico):
    dt = secciones.redactar_detenciones(_evid(previas), PERFIL, "motor", _no_llamar)
    assert dt["diagnostico"] == diagnostico and dt["fijo"] and dt["origen"] == "fijo"


def test_detenciones_con_la_ia_y_sus_controles():
    recibido = {}

    def llm(system, user, esquema):
        recibido.update(json.loads(user))
        assert esquema is secciones.ESQUEMA_DETENCIONES
        return json.dumps({"diagnostico": "Hubo filtraciones de aceite en lubricación el 31 oct.",
                           "causa_probable": "Quedó confirmado por los registros un problema de lubricación."})

    dt = secciones.redactar_detenciones(_evid([_previa()]), PERFIL, "motor", llm)
    assert recibido["intervenciones"][0]["modos_relacionados"] == ["Falla de lubricación"]
    assert recibido["modos_destacados"] == ["Falla de lubricación"] and recibido["rellenos"] == {"aceite": 3}
    assert dt["origen"] == "ia" and not dt["fijo"]
    assert any(p.startswith("afirmación prohibida") for p in dt["controles"])


def test_resumen_solo_con_las_secciones_y_confianza_hasta_el_techo():
    recibido, esquemas = {}, []
    evid = _evid([_previa()], techo="baja",
                 aceite={"disponible": True, "muestras": [{}], "observaciones": {
                     "diagnostico": "Contaminación por refrigerante crítica desde el 29 oct.",
                     "causa_probable": "Se sospecha una fuga de refrigerante."}})
    detenciones = {"diagnostico": "Filtraciones de aceite.", "causa_probable": "Problema de lubricación.", "fijo": False}

    def llm(system, user, esquema):
        recibido.update(json.loads(user))
        esquemas.append(esquema)
        return json.dumps({"diagnostico": "Posible fuga de refrigerante.", "causa_probable": "Las secciones no coinciden.",
                           "acciones": ["Revise el nivel de refrigerante en esta detención."],
                           "riesgo_si_no_se_hace": "Puede repetirse la detención.", "confianza": "baja",
                           "motivo_confianza": "El aceite y las detenciones apuntan a causas distintas."})

    r = secciones.redactar_resumen(evid, PERFIL, "motor", detenciones, llm, {"titulo": "", "descripcion": "Humo blanco"})
    assert esquemas[0]["schema"]["properties"]["confianza"]["enum"] == ["insuficiente", "baja"]
    assert recibido["aceite"]["diagnostico"].startswith("Contaminación por refrigerante")
    assert recibido["detenciones"] == {"diagnostico": "Filtraciones de aceite.", "causa_probable": "Problema de lubricación.",
                                       "sin_registros": False}
    assert recibido["monitoreo_de_riesgo"]["diagnostico"] == report_html._textos_predictivo(evid)[0]
    assert recibido["contexto_cliente"] == {"descripcion": "Humo blanco"}       # solo lo que el usuario escribio
    assert "Falla de lubricación" in recibido["verificaciones_sugeridas"]
    assert "ranking_modos" not in recibido and "detenciones_previas" not in recibido   # no recibe otros datos
    assert r["confianza"] == "baja" and r["controles"] == []


def test_resumen_sin_aceite_lo_dice_y_controla_las_acciones():
    def llm(system, user, esquema):
        entrada = json.loads(user)
        assert entrada["aceite"]["sin_muestras"]
        return json.dumps({"diagnostico": "Sin hallazgos.", "causa_probable": "No se puede concluir.",
                           "acciones": ["Tome una muestra.", "Revise niveles.", "Avise."], "riesgo_si_no_se_hace": "Nueva detención.",
                           "confianza": "insuficiente", "motivo_confianza": "Faltan datos."})

    r = secciones.redactar_resumen(_evid(None), PERFIL, "motor", {**secciones.SIN_REGISTROS, "fijo": True}, llm)
    # Se queda con las primeras MAX_ACCIONES; el control mira lo que se publica.
    assert len(r["acciones"]) == c.MAX_ACCIONES and r["controles"] == []


def test_una_respuesta_fuera_de_esquema_falla():
    with pytest.raises(ValueError):
        secciones.redactar_detenciones(_evid([_previa()]), PERFIL, "motor", lambda *_: json.dumps({"otro": "formato"}))


def test_los_controles_de_las_secciones_llegan_a_la_vista():
    res = {"informe": {"detenciones": {"controles": ["diagnostico: 4 frases, 70 palabras"]},
                       "resumen": {"controles": ["palabra prohibida 'anomalía'"]}}}
    assert report_html.problemas(res) == ["Detenciones: diagnostico: 4 frases, 70 palabras.",
                                          "Resumen: palabra prohibida 'anomalía'."]
