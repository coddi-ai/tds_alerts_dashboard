"""
Informe preliminar de falla desde el dashboard: valida los datos, corre el agente, arma el PDF y lo guarda.

La IA tarda (decenas de segundos), mas que lo razonable para un callback de Dash, asi que
cada solicitud corre en un hilo y la vista consulta su estado (`iniciar` / `estado`). Los
trabajos viven en memoria del proceso: el dashboard corre con un solo worker de gunicorn
(Dockerfile). Con varios workers habria que moverlos a un almacenamiento compartido.

La configuracion (modelo, carpeta de salida, caches, hilos) esta en src/informe_falla/config.py.
Cada informe queda en la carpeta de salida (por defecto outputs/informe_falla) como
`{cliente}/{id}.pdf` mas `{cliente}/{id}.json` con el registro completo: la solicitud
(sin las imagenes), la evidencia, lo que recibio la IA, su respuesta y los controles.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from src.data.predictive_v2 import load_risk_scores_history, load_unit_status_history
from src.data.report_health import unit_key
from src.informe_falla import catalog as c
from src.informe_falla.agent import PROMPT_VERSION, LlmFn, correr_agente, openai_llm
from src.informe_falla.config import get_informe_settings, perfil_cliente
from src.informe_falla.evidence import armar_evidencia, preparar_risk, preparar_status
from src.informe_falla import mantenciones
from src.informe_falla.pdf import html_a_pdf, pdf_disponible
from src.informe_falla.report_html import documento, numero_informe, problemas
from src.utils.logger import get_logger

logger = get_logger(__name__)


# Sistemas del formulario que el informe sabe analizar (los modos y el catalogo son de motor).
SISTEMAS_SOPORTADOS = (c.COMPONENTE,)

STATUS_RUNNING, STATUS_READY, STATUS_ERROR = "running", "ready", "error"

# Motivos de error que la vista traduce (informe_falla.error.<motivo>).
ERROR_NO_API_KEY = "no_api_key"
ERROR_NO_PDF = "no_pdf"
ERROR_SYSTEM = "unsupported_system"
ERROR_NO_DATA = "no_data"
ERROR_UNIT = "unit_not_found"
ERROR_INSUFFICIENT = "insufficient_data"
ERROR_LLM = "llm"
ERROR_UNEXPECTED = "unexpected"

_REPORT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,120}$")


class InformeError(Exception):
    def __init__(self, motivo: str, detalle: str = "", datos: Optional[dict] = None):
        super().__init__(detalle or motivo)
        self.motivo = motivo
        # Lo que la vista necesita para explicar el error (p. ej. dias con datos frente al minimo).
        self.datos = datos or {}


# =============================================================================
# Almacenamiento
# =============================================================================
def output_dir() -> Path:
    return get_informe_settings().output_dir


def _carpeta(cliente: str) -> Path:
    return output_dir() / (cliente or "").lower()


def ruta_pdf(cliente: str, report_id: str) -> Optional[Path]:
    """PDF de un informe del cliente, o None si el id no es valido o no existe."""
    if not report_id or not _REPORT_ID.match(report_id):
        return None
    ruta = _carpeta(cliente) / f"{report_id}.pdf"
    return ruta if ruta.is_file() else None


def listar_informes(cliente: str, limite: int = 50) -> List[dict]:
    """Resumen de los informes guardados del cliente, del mas reciente al mas antiguo."""
    carpeta = _carpeta(cliente)
    if not carpeta.is_dir():
        return []
    resumenes = []
    for registro in sorted(carpeta.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limite]:
        try:
            datos = json.loads(registro.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (carpeta / f"{registro.stem}.pdf").is_file():
            resumenes.append({"report_id": registro.stem, **datos.get("resumen", {})})
    return resumenes


def _guardar(cliente: str, report_id: str, pdf: bytes, registro: dict) -> None:
    carpeta = _carpeta(cliente)
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{report_id}.json").write_text(
        json.dumps(registro, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # El PDF al final: listar_informes solo muestra los que tienen ambos archivos.
    (carpeta / f"{report_id}.pdf").write_bytes(pdf)


# =============================================================================
# Generacion
# =============================================================================
def resolver_unidad(unidad: str, *tablas) -> Optional[str]:
    """La unidad tal como la escriben los datos del Predictivo (`T_9` en el formulario, `T_09` en CDA)."""
    buscada = unit_key(unidad)
    for tabla in tablas:
        if "Unit" in tabla.columns:
            for nombre in tabla["Unit"].dropna().unique():
                if unit_key(nombre) == buscada:
                    return str(nombre)
    return None


# Historial del Predictivo ya preparado, por cliente. Se publica una vez por semana: leer las
# ~150 particiones de cada tabla en cada informe es lo mas lento del flujo despues de la IA.
_FUENTES: dict = {}
_FUENTES_LOCK = threading.Lock()


def cargar_fuentes(cliente: str):
    """(status, risk) del motor del cliente, listos para evidence.armar_evidencia."""
    cliente = cliente.lower()
    with _FUENTES_LOCK:
        guardado = _FUENTES.get(cliente)
        if guardado and time.time() - guardado[0] < get_informe_settings().data_cache_seconds:
            return guardado[1], guardado[2]
        status = preparar_status(load_unit_status_history(cliente, c.COMPONENTE))
        risk = preparar_risk(load_risk_scores_history(cliente, c.COMPONENTE))
        _FUENTES[cliente] = (time.time(), status, risk)
        return status, risk


def contexto_de(request: dict, sistema_label: Optional[str] = None) -> dict:
    return {
        "sistema": sistema_label,
        "titulo": request.get("title"),
        "descripcion": request.get("description"),
        "hallazgos": request.get("findings"),
        "acciones": request.get("actions"),
    }


# =============================================================================
# Validador de datos
# =============================================================================
def _rango_unidad(unidad: str, status, risk) -> tuple:
    """(primer dia, ultimo dia) con datos del Predictivo para la unidad, en cualquiera de las dos tablas."""
    fechas = [t.loc[t["Unit"] == unidad, "Fecha"] for t in (status, risk) if not t.empty]
    fechas = [f for f in fechas if not f.empty]
    if not fechas:
        return None, None
    return (min(f.min() for f in fechas).date().isoformat(), max(f.max() for f in fechas).date().isoformat())


def disponibilidad(evid: dict, unidad: str, status, risk) -> dict:
    """Si hay datos suficientes en la ventana del informe, con las cifras para explicarlo.

    Usa el mismo criterio que el metodo (evidence.auditoria / auditoria_diaria): con score diario,
    al menos MIN_DIAS_RECIENTES dias con datos en las DIAS_RECIENTES previas a la detencion; sin
    score diario, al menos MIN_SEMANAS_RECIENTES semanas validas en el ultimo mes. Bajo eso el
    metodo concluye DATOS INSUFICIENTES y el informe no diria nada util.
    """
    diario = evid.get("diario") or {}
    hay_diario = bool(diario.get("analisis_por_modo"))
    aud_d = diario.get("auditoria") or {}
    desde, hasta = _rango_unidad(unidad, status, risk)
    ok = evid["veredicto_reglas"]["veredicto"] != "DATOS INSUFICIENTES"
    return {
        "ok": ok,
        "motivo": None if ok else ERROR_INSUFFICIENT,
        "unidad": unidad,
        "fecha": evid["consulta"]["fecha"],
        "base": "diario" if hay_diario else "semanal",
        "dias_con_dato": (aud_d.get("dias_con_dato") or {}).get("reciente", 0),
        "dias_ventana": c.DIAS_RECIENTES,
        "min_dias": c.MIN_DIAS_RECIENTES,
        "semanas_validas": evid["auditoria"]["semanas_validas"]["reciente"],
        "semanas_ventana": c.SEMANAS_RECIENTES,
        "min_semanas": c.MIN_SEMANAS_RECIENTES,
        "datos_desde": desde,
        "datos_hasta": hasta,
    }


def validar_disponibilidad(cliente: str, unidad: str, fecha: str) -> dict:
    """Validador previo (sin IA): {"ok": bool, "motivo": ..., cifras}. La vista lo llama al elegir unidad y fecha."""
    status, risk = cargar_fuentes(cliente)
    if status.empty and risk.empty:
        return {"ok": False, "motivo": ERROR_NO_DATA}
    nombre = resolver_unidad(unidad, status, risk)
    if nombre is None:
        return {"ok": False, "motivo": ERROR_UNIT}
    evid = armar_evidencia(nombre, fecha, status, risk, perfil_cliente(cliente))
    resultado = disponibilidad(evid, nombre, status, risk)
    # Las mantenciones no bloquean el informe: solo se informa su cobertura.
    resultado["mantenciones"] = mantenciones.cobertura(cliente, unidad, fecha)
    return resultado


def _imagenes(request: dict) -> list:
    return [{"filename": i["filename"], "caption": i.get("caption", ""),
             "data": f"data:{i['mime']};base64,{i['data_base64']}"} for i in request.get("images", [])]


def generar_informe(request: dict, llm_fn: Optional[LlmFn] = None, sistema_label: Optional[str] = None) -> dict:
    """Corre el informe completo para una solicitud (src/data/informe_falla_request.build_informe_request) y guarda el PDF."""
    cliente = request["client"]
    if request.get("system") and request["system"] not in SISTEMAS_SOPORTADOS:
        raise InformeError(ERROR_SYSTEM)
    if llm_fn is None and not os.getenv("OPENAI_API_KEY"):
        raise InformeError(ERROR_NO_API_KEY)
    if not pdf_disponible():
        raise InformeError(ERROR_NO_PDF)

    perfil = perfil_cliente(cliente)
    status, risk = cargar_fuentes(cliente)
    if status.empty and risk.empty:
        raise InformeError(ERROR_NO_DATA)
    unidad = resolver_unidad(request["unit"], status, risk)
    if unidad is None:
        raise InformeError(ERROR_UNIT)

    contexto = contexto_de(request, sistema_label)
    evid = armar_evidencia(unidad, request["event_date"], status, risk, perfil)
    # Sin datos suficientes en la ventana no se llama a la IA: el informe no tendria contenido.
    if get_informe_settings().validar_datos:
        datos = disponibilidad(evid, unidad, status, risk)
        if not datos["ok"]:
            raise InformeError(ERROR_INSUFFICIENT, datos=datos)
    # Intervenciones de mantencion previas (sin IA): cobertura, tabla y antecedentes.
    destacados = [r["modo"] for r in evid["ranking_modos"] if r["nivel"] in ("alto", "medio")]
    evid.update(mantenciones.antecedentes_mantencion(cliente, unidad, evid["consulta"]["fecha"],
                                                     sistema=request.get("system") or c.COMPONENTE,
                                                     modos=destacados))
    ajustes = get_informe_settings()
    modelo = {"modelo": ajustes.model if llm_fn is None else "personalizado", "temperatura": ajustes.temperature,
              "semilla": ajustes.seed, "prompt": PROMPT_VERSION}
    try:
        contexto_ia = {k: v for k, v in contexto.items() if k != "sistema"}
        res = correr_agente(evid, perfil, llm_fn or openai_llm(), contexto_ia)
    except Exception as exc:
        raise InformeError(ERROR_LLM, f"{type(exc).__name__}: {exc}") from exc

    fecha = evid["consulta"]["fecha"]
    report_id = f"IPF_{re.sub(r'[^A-Za-z0-9-]', '-', unidad)}_{fecha}_{datetime.now():%Y%m%d%H%M%S}"
    numero = numero_informe(unidad, fecha)
    html = documento(res, cliente=perfil["nombre"], numero=numero, version=c.VERSION,
                     contexto=contexto, imagenes=_imagenes(request))
    pdf = html_a_pdf(html)

    resumen = {
        "unit": unidad, "event_date": fecha, "title": request.get("title") or "",
        "verdict": res["informe"].get("veredicto"), "confidence": res["informe"].get("confianza"),
        "rules_verdict": evid["veredicto_reglas"]["veredicto"], "problems": problemas(res),
        "requested_by": request.get("requested_by"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    request_sin_imagenes = {**request, "images": [{k: v for k, v in i.items() if k != "data_base64"}
                                                   for i in request.get("images", [])]}
    _guardar(cliente, report_id, pdf, {"resumen": resumen, **modelo, "version": c.VERSION,
                                       "solicitud": request_sin_imagenes, **res})
    logger.info(f"Informe preliminar generado: {cliente}/{report_id} ({resumen['verdict']}, controles: "
                f"{'OK' if not resumen['problems'] else resumen['problems']})")
    return {"status": STATUS_READY, "report_id": report_id, **resumen}


# =============================================================================
# Trabajos en segundo plano
# =============================================================================
_EXECUTOR = ThreadPoolExecutor(max_workers=get_informe_settings().max_workers, thread_name_prefix="informe_falla")
_JOBS: dict = {}
_LOCK = threading.Lock()


def _purgar_viejos() -> None:
    limite = time.time() - get_informe_settings().job_ttl_seconds
    for job_id in [j for j, d in _JOBS.items() if d["started"] < limite]:
        _JOBS.pop(job_id, None)


def _correr(job_id: str, request: dict, sistema_label: Optional[str]) -> None:
    try:
        resultado = generar_informe(request, sistema_label=sistema_label)
    except InformeError as exc:
        logger.warning(f"Informe preliminar {request['client']}/{request['unit']}: {exc.motivo} ({exc})")
        resultado = {"status": STATUS_ERROR, "reason": exc.motivo, "details": exc.datos}
    except Exception:
        logger.exception(f"Informe preliminar {request['client']}/{request['unit']}: error inesperado")
        resultado = {"status": STATUS_ERROR, "reason": ERROR_UNEXPECTED}
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(resultado)


def iniciar(request: dict, sistema_label: Optional[str] = None) -> str:
    """Encola la generacion y devuelve el id del trabajo."""
    job_id = uuid.uuid4().hex
    with _LOCK:
        _purgar_viejos()
        _JOBS[job_id] = {"status": STATUS_RUNNING, "client": request["client"],
                         "requested_by": request.get("requested_by"), "started": time.time()}
    _EXECUTOR.submit(_correr, job_id, request, sistema_label)
    return job_id


def estado(job_id: Optional[str]) -> Optional[dict]:
    with _LOCK:
        job = _JOBS.get(job_id or "")
        return dict(job) if job else None
