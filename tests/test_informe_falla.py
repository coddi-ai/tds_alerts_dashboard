"""Informe preliminar de falla (src/informe_falla): evidencia, controles de la IA, informe, validador, servicio y ruta del PDF.

Los datos del Predictivo son sinteticos: una flota de 12 unidades con ruido bajo y una
unidad (T_09) cuya contaminacion por refrigerante se dispara en el ultimo mes. La IA se
reemplaza por una funcion que devuelve un informe fijo; ninguna prueba llama a OpenAI.
El PDF se reemplaza por bytes fijos salvo en la prueba que exige WeasyPrint real.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import date, timedelta

import dash
import numpy as np
import pandas as pd
import pytest

from config.users import USERS
from dashboard import informe_falla_files
from src.informe_falla import agent, catalog, config, evidence, report_html, service
from src.informe_falla.catalog import MODOS

FECHA = "2026-03-12"          # jueves; la semana de la fecha queda excluida por diseño
UNIDAD = "T_09"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
CDA_USER = next(n for n, u in USERS.items() if u.get("role") == "client" and u.get("clients") == ["CDA"])


# ---------------------------------------------------------------------------
# Datos sinteticos en el formato de los lectores de src/data/predictive_v2.py
# ---------------------------------------------------------------------------

def _flota(semanas: int = 20):
    rng = np.random.default_rng(7)
    unidades = [UNIDAD] + [f"T_{i}" for i in range(10, 21)]
    fecha = date.fromisoformat(FECHA)
    lunes0 = fecha - timedelta(days=fecha.weekday())
    status, risk = [], []
    for rel in range(-semanas, 0):
        lunes = lunes0 + timedelta(weeks=rel)
        year, week, _ = lunes.isocalendar()
        for u in unidades:
            modos = {m: round(5 + rng.normal(0, 0.5), 2) for m in MODOS}
            if u == UNIDAD and rel >= -3:
                modos["coolant_contamination_risk"] = 40.0 + rel
            status.append({"Unit": u, "Fecha": pd.Timestamp(lunes + timedelta(days=6)), "estado": "normal",
                           "ranking": 10.0, "media_30d": 5.0, "dias_media_30d": 30, "peor_modo": "blowby_risk",
                           "peor_valor": 5.0, "modos_ordenados": json.dumps(modos), "dias_sin_datos": 0,
                           "year": year, "week": week})
    for d in pd.date_range(lunes0 + timedelta(weeks=-semanas), fecha + timedelta(days=3)):
        for u in unidades:
            for m in MODOS:
                valor = 5 + rng.normal(0, 0.5)
                if u == UNIDAD and m == "coolant_contamination_risk" and (pd.Timestamp(FECHA) - d).days <= 10:
                    valor = 45.0
                risk.append({"Unit": u, "Fecha": d, "failure_mode": m, "risk_value": round(valor, 2)})
    return pd.DataFrame(status), pd.DataFrame(risk)


@pytest.fixture(scope="module")
def fuentes():
    status, risk = _flota()
    return status, risk


@pytest.fixture(scope="module")
def evid(fuentes):
    status, risk = fuentes
    return evidence.armar_evidencia(UNIDAD, FECHA, evidence.preparar_status(status),
                                    evidence.preparar_risk(risk), config.perfil_cliente("CDA"))


def _informe(fuente_valida: str) -> dict:
    """Respuesta de la IA que cumple el esquema, con una fuente inventada y un paso fuera de lugar."""
    return {
        "veredicto": "SEÑAL CLARA", "confianza": "media", "motivo_confianza": "Datos completos.",
        "causa_mas_probable": "Posible contaminación por refrigerante.",
        "que_mostro_el_predictivo": "El índice de refrigerante subió en el último mes.",
        "recomendacion_principal": "Revisar el sistema de refrigeración.",
        "estado_unidad": "Unidad detenida; causa pendiente de confirmar.",
        "hipotesis": [
            {"nombre": "Contaminación por refrigerante", "modos": ["coolant_contamination_risk"],
             "a_favor": "Semanas anómalas.", "en_contra": "Sin evidencia en contra.",
             "evaluacion": "mas_probable", "fuentes": [fuente_valida, "trayectoria[rel=-99].blowby_risk"]},
            {"nombre": "Falla eléctrica, estructural o de montaje", "modos": [], "a_favor": "Sin evidencia a favor.",
             "en_contra": "El Predictivo no mide estas fallas.", "evaluacion": "no_evaluable", "fuentes": []},
        ],
        "cadena_causal": [{"pregunta": "¿Qué falló, probablemente?", "respuesta": "Refrigerante.", "a_confirmar": True}],
        "causa_fisica": "Pendiente.", "causas_contribuyentes": "Ninguna identificada.",
        "inspeccion": [{"id": "PRE-1", "nota": ""}, {"id": "REF-2", "nota": ""}, {"id": "TUR-1", "nota": ""}],
        "prevencion": ["Revisar fugas."], "limitaciones": ["No se conoce el componente encontrado."],
        "coincide_con_veredicto_reglas": True, "motivo_si_difiere": "",
    }


def _llm(system, user, esquema):
    assert esquema is agent.ESQUEMA_INFORME
    return json.dumps(_informe("analisis_por_metrica.coolant_contamination_risk.nivel"))


# ---------------------------------------------------------------------------
# Evidencia (sin IA)
# ---------------------------------------------------------------------------

def test_la_señal_de_la_unidad_se_detecta_y_el_resto_no(evid):
    assert evid["veredicto_reglas"]["veredicto"] == "SEÑAL CLARA"
    primero = evid["ranking_modos"][0]
    assert (primero["modo"], primero["nivel"]) == ("coolant_contamination_risk", "alto")
    assert all(r["nivel"] in ("ninguno", "bajo") for r in evid["ranking_modos"][1:])
    assert evid["diario"]["analisis_por_modo"]["coolant_contamination_risk"]["dias_anomalos"]


def test_nada_posterior_a_la_fecha_entra_al_analisis(evid):
    assert evid["auditoria"]["ultimo_dato_unidad"] < FECHA
    assert all(p["fecha"] < FECHA for serie in evid["diario"]["series"].values() for p in serie)


def test_un_modo_que_el_cliente_no_publica_queda_sin_datos(fuentes):
    status, risk = fuentes
    risk = risk[risk["failure_mode"] != "turbocharger_risk"]
    ancho = evidence.preparar_risk(risk)
    assert ancho["turbocharger_risk"].isna().all()
    e = evidence.armar_evidencia(UNIDAD, FECHA, evidence.preparar_status(status), ancho)
    assert e["analisis_por_metrica"]["turbocharger_risk"]["nivel_diario"] == "sin_datos"


def test_unidad_sin_datos_es_datos_insuficientes(fuentes):
    status, risk = fuentes
    e = evidence.armar_evidencia("T_99", FECHA, evidence.preparar_status(status), evidence.preparar_risk(risk))
    assert e["veredicto_reglas"]["veredicto"] == "DATOS INSUFICIENTES"


def test_configuracion_por_defecto_y_por_entorno(monkeypatch, tmp_path):
    for var in ("INFORME_FALLA_MODEL", "INFORME_FALLA_TEMPERATURE", "INFORME_FALLA_SEED", "INFORME_FALLA_OUTPUT_DIR"):
        monkeypatch.delenv(var, raising=False)
    ajustes = config.get_informe_settings()
    assert ajustes.model == "gpt-6-luna" and ajustes.temperature is None and ajustes.seed is None
    monkeypatch.setenv("INFORME_FALLA_MODEL", "otro-modelo")
    monkeypatch.setenv("INFORME_FALLA_TEMPERATURE", "0")
    monkeypatch.setenv("INFORME_FALLA_SEED", "7")
    monkeypatch.setenv("INFORME_FALLA_OUTPUT_DIR", str(tmp_path))
    ajustes = config.get_informe_settings()
    assert (ajustes.model, ajustes.temperature, ajustes.seed, ajustes.output_dir) == ("otro-modelo", 0.0, 7, tmp_path)


def test_el_prompt_no_pide_ishikawa_y_nombra_los_modos_en_español():
    prompt = agent.prompt_informe(config.perfil_cliente("CDA"))
    assert "ishikawa" not in prompt.lower() and "ishikawa" not in json.dumps(agent.ESQUEMA_INFORME).lower()
    assert "coolant_contamination_risk = Contaminación por refrigerante" in prompt


def test_perfil_por_cliente():
    assert "QSK60" in config.perfil_cliente("capstone")["equipo"]
    generico = config.perfil_cliente("CDA")
    assert generico["nombre"] == "Cda" and generico["fecha_inicio_base"] is None
    assert "QSK60" in agent.prompt_informe(config.perfil_cliente("CAPSTONE"))


# ---------------------------------------------------------------------------
# Agente y controles
# ---------------------------------------------------------------------------

def test_controles_detectan_fuentes_inventadas_y_pasos_fuera_de_lugar(evid):
    res = agent.correr_agente(evid, config.perfil_cliente("CDA"), _llm, {"titulo": "Pérdida de potencia"})
    assert res["errores_esquema"] == []
    assert res["fuentes_no_encontradas"] == [{"hipotesis": "Contaminación por refrigerante",
                                              "fuente": "trayectoria[rel=-99].blowby_risk"}]
    assert res["hipotesis_sin_respaldo"] == []
    assert res["verificaciones_fuera_de_lugar"] == ["TUR-1"]
    assert res["terminos_internos"] == []
    assert res["evidencia_enviada"]["contexto_cliente"] == {"titulo": "Pérdida de potencia"}
    assert "series" not in res["evidencia_enviada"]["diario"]


def test_terminos_internos_en_textos_para_el_cliente():
    informe = _informe("x")
    informe["motivo_confianza"] = "El techo de confianza de la auditoría es bajo en W37."
    informe["hipotesis"][0]["a_favor"] = "coolant_contamination_risk con nivel 'medio' en rel=-2."
    assert agent.terminos_internos(informe) == sorted(
        ["techo de confianza", "auditoría", "W37", "coolant_contamination_risk", "nivel 'medio'", "rel=-2"])
    assert agent.terminos_internos(_informe("x")) == []


def test_otros_modos_se_enumeran_como_una_frase():
    evid = {"ranking_modos": [{"modo": m, "nivel": n} for m, n in (
        ("coolant_contamination_risk", "medio"), ("turbocharger_risk", "bajo"), ("combustion_risk", "bajo"),
        ("blowby_risk", "bajo"), ("bearing_wear_risk", "ninguno"), ("abrasive_wear_risk", "sin_datos"))]}
    assert report_html._otros_modos(evid, "coolant_contamination_risk") == (
        "Turbocargador, combustión y blow-by: leve alza, dentro de su variación habitual. "
        "El otro modo, sin cambios. Desgaste abrasivo: sin datos para la unidad.")


def test_sin_contexto_no_se_envia_la_clave(evid):
    assert "contexto_cliente" not in agent.evidencia_para_ia(evid, {"titulo": "", "hallazgos": None})


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------

def test_informe_escapa_el_texto_del_usuario_e_incluye_las_fotos(evid):
    res = agent.correr_agente(evid, config.perfil_cliente("CDA"), _llm)
    foto = {"filename": "falla.png", "caption": "Fuga <b>visible</b>",
            "data": "data:image/png;base64," + base64.b64encode(PNG).decode()}
    externa = {"filename": "x.png", "caption": "", "data": "https://ejemplo.com/x.png"}
    html = report_html.documento(res, cliente="CDA", contexto={"descripcion": "<script>alert(1)</script>"},
                                 imagenes=[foto, externa])
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "Fuga &lt;b&gt;visible&lt;/b&gt;" in html and "10. Registro fotográfico" in html
    assert "ejemplo.com" not in html
    assert "window.print" not in html and "fonts.googleapis" not in html
    assert "Revisar antes de entregar" not in html and "Ishikawa" not in html and "por integrar" not in html


def test_pdf_real_con_weasyprint(evid):
    from src.informe_falla import pdf
    if not pdf.pdf_disponible():
        pytest.skip("WeasyPrint o Pango no disponibles en este entorno (se prueba en la imagen Docker)")
    res = agent.correr_agente(evid, config.perfil_cliente("CDA"), _llm)
    contenido = pdf.html_a_pdf(report_html.documento(res, cliente="CDA"))
    assert contenido.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------

@pytest.fixture
def servicio(fuentes, monkeypatch, tmp_path):
    status, risk = fuentes
    lecturas = []
    monkeypatch.setenv("INFORME_FALLA_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(service, "_FUENTES", {})
    monkeypatch.setenv("INFORME_FALLA_ORIGEN", "local")

    def leer_particiones(cliente, tabla, desde=None, hasta=None, tecnica="predictive"):
        if tabla == "unit_status_summary":
            lecturas.append(cliente)
            return status
        return risk
    monkeypatch.setattr(service.fuentes, "leer_particiones", leer_particiones)
    monkeypatch.setattr(service, "pdf_disponible", lambda: True)
    monkeypatch.setattr(service, "html_a_pdf", lambda html: b"%PDF-sintetico")
    # Sin fuente de mantenciones: estas pruebas no leen la data real (tests/test_informe_falla_mantenciones.py la cubre).
    monkeypatch.setattr(service.mantenciones, "_cargar", lambda cliente: (pd.DataFrame(), pd.DataFrame(
        columns=["unidad_key", "dia", "intervention_hours"])))
    # Ni de aceite (tests/test_informe_falla_aceite.py la cubre).
    monkeypatch.setattr(service.aceite, "_cargar", lambda cliente: pd.DataFrame())
    return lecturas


def _solicitud(**cambios):
    imagen = {"filename": "a.png", "mime": "image/png", "size": len(PNG), "caption": "Vista",
              "data_base64": base64.b64encode(PNG).decode()}
    return {"client": "CDA", "unit": "T_9", "system": "motor", "event_date": FECHA, "title": "Pérdida de potencia",
            "description": "", "findings": "", "actions": "", "troubleshooting": None, "images": [imagen],
            "requested_by": "operador", "requested_at": "2026-03-12T12:00:00+00:00", **cambios}


def test_genera_guarda_y_lista_el_informe(servicio):
    enviados = []
    def llm(system, user, esquema):
        enviados.append(json.loads(user))
        return _llm(system, user, esquema)
    resultado = service.generar_informe(_solicitud(), llm_fn=llm, sistema_label="Motor")
    # El sistema elegido va al PDF, no a la IA.
    assert enviados[0]["contexto_cliente"] == {"titulo": "Pérdida de potencia"}
    assert resultado["status"] == service.STATUS_READY
    assert resultado["unit"] == UNIDAD                     # T_9 del formulario es T_09 en los datos
    assert resultado["problems"]                          # la fuente inventada queda como aviso

    ruta = service.ruta_pdf("CDA", resultado["report_id"])
    assert ruta.read_bytes() == b"%PDF-sintetico"
    registro = json.loads(ruta.with_suffix(".json").read_text(encoding="utf-8"))
    assert registro["solicitud"]["images"][0] == {"filename": "a.png", "mime": "image/png", "size": len(PNG),
                                                  "caption": "Vista"}
    assert registro["informe"]["veredicto"] == "SEÑAL CLARA"
    assert registro["prompt"] == agent.PROMPT_VERSION and registro["modelo"] == "personalizado"
    assert [r["report_id"] for r in service.listar_informes("cda")] == [resultado["report_id"]]
    assert service.listar_informes("CAPSTONE") == []


def test_el_historial_se_lee_una_vez_por_cliente(servicio):
    service.generar_informe(_solicitud(), llm_fn=_llm)
    service.generar_informe(_solicitud(), llm_fn=_llm)
    assert servicio == ["cda"]


@pytest.mark.parametrize("report_id", ["", "../cda/x", "IPF_x/../../y", "a" * 200, "IPF_no_existe"])
def test_ids_ajenos_o_maliciosos_no_resuelven(servicio, report_id):
    assert service.ruta_pdf("CDA", report_id) is None


@pytest.mark.parametrize("cambios, motivo", [
    ({"system": "frenos"}, service.ERROR_SYSTEM),
    ({"unit": "T_99"}, service.ERROR_UNIT),
])
def test_errores_de_la_solicitud(servicio, cambios, motivo):
    with pytest.raises(service.InformeError) as error:
        service.generar_informe(_solicitud(**cambios), llm_fn=_llm)
    assert error.value.motivo == motivo


# ---------------------------------------------------------------------------
# Validador de datos
# ---------------------------------------------------------------------------

def test_validador_con_datos_suficientes(servicio):
    r = service.validar_disponibilidad("CDA", "T_9", FECHA)
    assert r["ok"] and r["motivo"] is None and r["unidad"] == UNIDAD and r["base"] == "diario"
    assert (r["dias_con_dato"], r["dias_ventana"], r["min_dias"]) == (28, 28, catalog.MIN_DIAS_RECIENTES)
    assert r["datos_desde"] < FECHA < r["datos_hasta"]


def test_validador_sin_datos_en_la_ventana(servicio):
    # Dos meses despues del ultimo dato: la ventana de 4 semanas queda vacia.
    r = service.validar_disponibilidad("CDA", UNIDAD, "2026-05-15")
    assert not r["ok"] and r["motivo"] == service.ERROR_INSUFFICIENT and r["dias_con_dato"] == 0


def test_validador_unidad_inexistente(servicio):
    assert service.validar_disponibilidad("CDA", "T_99", FECHA) == {"ok": False, "motivo": service.ERROR_UNIT}


def test_interruptores_apagados_por_defecto(monkeypatch):
    for var in ("INFORME_FALLA_VALIDAR_DATOS", "INFORME_FALLA_FORMULARIO_COMPLETO"):
        monkeypatch.delenv(var, raising=False)
    ajustes = config.get_informe_settings()
    assert not ajustes.validar_datos and not ajustes.formulario_completo
    monkeypatch.setenv("INFORME_FALLA_VALIDAR_DATOS", "true")
    assert config.get_informe_settings().validar_datos


def test_sin_validador_se_genera_igual(servicio, monkeypatch):
    monkeypatch.delenv("INFORME_FALLA_VALIDAR_DATOS", raising=False)
    llamadas = []
    def llm(system, user, esquema):
        llamadas.append(1)
        return _llm(system, user, esquema)
    resultado = service.generar_informe(_solicitud(event_date="2026-05-15"), llm_fn=llm)
    assert resultado["status"] == service.STATUS_READY and llamadas == [1]
    assert resultado["rules_verdict"] == "DATOS INSUFICIENTES"


def test_sin_datos_suficientes_no_se_llama_a_la_ia(servicio, monkeypatch):
    monkeypatch.setenv("INFORME_FALLA_VALIDAR_DATOS", "true")
    def llm(*_):
        raise AssertionError("no debe llamarse a la IA sin datos suficientes")
    with pytest.raises(service.InformeError) as error:
        service.generar_informe(_solicitud(event_date="2026-05-15"), llm_fn=llm)
    assert error.value.motivo == service.ERROR_INSUFFICIENT
    assert error.value.datos["dias_con_dato"] == 0 and error.value.datos["unidad"] == UNIDAD


def test_mensajes_del_validador_en_la_vista(servicio):
    from dashboard.callbacks import informe_falla_callbacks as rc
    ok = rc.availability_messages(service.validar_disponibilidad("CDA", "T_9", FECHA))
    assert ok[0].startswith("Datos suficientes: T_09 tiene 28 de 28 días")
    falta = service.validar_disponibilidad("CDA", UNIDAD, "2026-05-15")
    mensajes = rc.availability_messages(falta)
    assert mensajes[0].startswith("No se puede generar el informe: T_09 tiene 0 de 28 días")
    assert "mínimo 7" in mensajes[0] and mensajes[1].startswith("Datos del Predictivo disponibles para esta unidad")
    assert "No se puede generar el informe" in str(rc.build_error(service.ERROR_INSUFFICIENT, falta))
    assert "OPENAI_API_KEY" in str(rc.build_error("no_api_key"))


def test_sin_api_key_no_llama_a_la_ia(servicio, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(service.InformeError) as error:
        service.generar_informe(_solicitud())
    assert error.value.motivo == service.ERROR_NO_API_KEY


def test_el_trabajo_en_segundo_plano_termina(monkeypatch):
    monkeypatch.setattr(service, "generar_informe",
                        lambda request, sistema_label=None, avance=None: {"status": service.STATUS_READY, "report_id": "INFORME_FALLA_1"})
    job_id = service.iniciar(_solicitud())
    for _ in range(100):
        job = service.estado(job_id)
        if job["status"] != service.STATUS_RUNNING:
            break
        time.sleep(0.02)
    assert job["status"] == service.STATUS_READY and job["client"] == "CDA" and job["report_id"] == "INFORME_FALLA_1"
    assert service.estado("no-existe") is None


def test_un_error_del_trabajo_queda_con_su_motivo(monkeypatch):
    def falla(request, sistema_label=None, avance=None):
        raise service.InformeError(service.ERROR_NO_DATA)
    monkeypatch.setattr(service, "generar_informe", falla)
    job_id = service.iniciar(_solicitud())
    for _ in range(100):
        if service.estado(job_id)["status"] != service.STATUS_RUNNING:
            break
        time.sleep(0.02)
    assert service.estado(job_id) | {"started": 0} == {"status": "error", "reason": "no_data", "details": {},
                                                        "client": "CDA", "requested_by": "operador", "started": 0,
                                                        "unit": "T_9", "event_date": FECHA, "etapa": None, "progreso": 0}


# ---------------------------------------------------------------------------
# Ruta del PDF
# ---------------------------------------------------------------------------

PREFIX = "/alerts-dashboard/"


@pytest.fixture
def web(servicio):
    report_id = service.generar_informe(_solicitud(), llm_fn=_llm)["report_id"]
    app = dash.Dash(__name__, url_base_pathname=PREFIX, suppress_callback_exceptions=True)
    app.layout = dash.html.Div()
    app.server.secret_key = "flask-secret-key-sintetica-0123456789"
    informe_falla_files.register_informe_falla_files(app)
    app.server.testing = True
    with app.server.test_client() as test_client:
        yield test_client, report_id


def _get(test_client, report_id, client="CDA", **extra):
    return test_client.get(f"{PREFIX}informe-falla/file", query_string={"client": client, "id": report_id, **extra})


def _login(test_client, username):
    with test_client.session_transaction() as session:
        session["dashboard_user"] = username


def test_ruta_entrega_el_pdf_al_usuario_del_cliente(web):
    test_client, report_id = web
    assert _get(test_client, report_id).status_code == 302       # sin sesion
    _login(test_client, CDA_USER)
    response = _get(test_client, report_id)
    assert response.status_code == 200 and response.data == b"%PDF-sintetico"
    assert response.headers["Content-Disposition"].startswith("inline;")
    assert "no-store" in response.headers["Cache-Control"]
    assert _get(test_client, report_id, download="1").headers["Content-Disposition"].startswith("attachment;")


def test_ruta_niega_otro_cliente_e_ids_invalidos(web):
    test_client, report_id = web
    _login(test_client, CDA_USER)
    assert _get(test_client, report_id, client="CAPSTONE").status_code == 403
    assert _get(test_client, "../" + report_id).status_code == 404
    assert _get(test_client, "IPF_no_existe").status_code == 404
