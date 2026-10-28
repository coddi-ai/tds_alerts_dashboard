"""
Informe preliminar de falla: la IA redacta el diagnostico y la causa probable de cada seccion y el Resumen.

Tres llamadas, cada una sobre lo que se muestra en su seccion:
  - Aceite (aceite.observaciones_laboratorio): las muestras de laboratorio de los 3 meses previos.
  - Detenciones (redactar_detenciones): las intervenciones de mantencion del sistema (mantenciones.py).
  - Resumen (redactar_resumen): SOLO el diagnostico y la causa probable de Aceite, Monitoreo de riesgo (el
    analisis publicado, analisis_unidad) y Detenciones, tal como los lee el cliente. No recibe otros datos, asi
    que no puede contradecir a las secciones ni agregar hechos que no esten en ellas.

Todas siguen los lineamientos de mensajes del prompt del informe (agent.prompt_informe: Principios y Lenguaje) y
pasan por los mismos controles (vocabulario prohibido, terminos internos, afirmaciones que los registros no
permiten, largo). Aceite y Detenciones tienen un limite mas amplio que el Resumen (c.LIMITES_SECCION).
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

from src.informe_falla import catalog as c
from src.informe_falla.agent import (_AFIRMACIONES_PROHIBIDAS, _LENGUAJE_PROHIBIDO, _LISTA_TEXTO, _TERMINOS_INTERNOS,
                                     _TEXTO, LlmFn, _enum, _frases, _obj, _palabras, prompt_informe, validar_esquema)
from src.informe_falla.report_html import _textos_predictivo
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Cambia cada vez que cambian los prompts o los esquemas de este modulo o de aceite.py; queda en el registro.
PROMPT_VERSION = "secciones-1"

_VALOR = re.compile(r"\d+(?:[.,]\d+)?\s*(?:ppm|%|cSt)\b", re.IGNORECASE)

# Textos fijos de Detenciones cuando no hay registros que leer (sin IA).
SIN_REGISTROS = {"diagnostico": "No hay registros de mantención de la unidad para este período.",
                 "causa_probable": "Las detenciones no permiten orientar la causa."}


def esquema_diagnostico_causa(nombre: str) -> dict:
    return {"name": nombre, "strict": True, "schema": _obj({"diagnostico": _TEXTO, "causa_probable": _TEXTO})}


ESQUEMA_DETENCIONES = esquema_diagnostico_causa("detenciones_diagnostico_causa")


# =============================================================================
# Comunes
# =============================================================================
def lineamientos(perfil: dict) -> str:
    """Principios y Lenguaje del prompt del informe: las mismas reglas de redaccion en todas las secciones."""
    p = prompt_informe(perfil)
    return p[p.index("Principios"):p.index("Diagnóstico (máximo")] + p[p.index("Lenguaje\n"):p.index("Casos especiales")]


def formato_seccion() -> str:
    (d_frases, d_palabras), (k_frases, k_palabras) = (c.LIMITES_SECCION[k] for k in ("diagnostico", "causa_probable"))
    return (f"- diagnostico: máximo {d_frases} frases, unas {d_palabras} palabras.\n"
            f"- causa_probable: máximo {k_frases} frases, unas {k_palabras} palabras.")


def _vocabulario(textos: List[str]) -> List[str]:
    problemas = []
    for patron, nombre in ((_LENGUAJE_PROHIBIDO, "palabra prohibida"), (_TERMINOS_INTERNOS, "término interno"),
                           (_AFIRMACIONES_PROHIBIDAS, "afirmación prohibida")):
        problemas += [f"{nombre} '{m.group(0)}'" for t in textos for m in patron.finditer(t or "")]
    problemas += [f"valor '{v}'" for t in textos for v in _VALOR.findall(t or "")]
    return problemas


def controles_diagnostico_causa(dc: dict, limites: Optional[dict] = None) -> List[str]:
    """Largo (con c.TOLERANCIA_LARGO) y vocabulario de un par diagnostico / causa probable."""
    limites = limites or c.LIMITES_SECCION
    problemas = []
    for campo in ("diagnostico", "causa_probable"):
        texto = dc.get(campo, "")
        frases, palabras = limites[campo]
        if _frases(texto) > frases or _palabras(texto) > palabras * c.TOLERANCIA_LARGO:
            problemas.append(f"{campo}: {_frases(texto)} frases, {_palabras(texto)} palabras")
    return problemas + _vocabulario([dc.get("diagnostico", ""), dc.get("causa_probable", "")])


def pedir(llm_fn: LlmFn, prompt: str, entrada: dict, esquema: dict) -> dict:
    """Una llamada a la IA con Structured Outputs; lanza si la respuesta no cumple el esquema."""
    respuesta = json.loads(llm_fn(prompt, json.dumps(entrada, ensure_ascii=False), esquema))
    errores = validar_esquema(respuesta, esquema)
    if errores:
        raise ValueError(f"la respuesta de {esquema['name']} no cumple el esquema: {errores}")
    return respuesta


# =============================================================================
# Detenciones
# =============================================================================
def entrada_detenciones(evid: dict, perfil: dict, sistema: str) -> dict:
    a = evid.get("antecedentes_mantencion") or {}
    destacados = [r["modo"] for r in evid.get("ranking_modos", []) if r["nivel"] in ("alto", "medio")]
    return {
        "sistema": sistema, "equipo": perfil["equipo"], "fecha_detencion": evid["consulta"]["fecha"],
        "ventana": {"desde": evid["ventanas"]["periodo_desde"], "hasta": evid["ventanas"]["periodo_hasta"]},
        "modos_destacados": [c.NOMBRE_MODO.get(m, m) for m in destacados],
        "intervenciones": [{
            "fecha": p["fecha"], "dias_antes": p["dias_antes"], "tipo": p["tipo"], "subsistema": p["subsistema"],
            "componentes": p["componentes"], "descripcion": p["descripcion"], "sin_cierre": p["sin_cierre"],
            "dias_previos_a_la_detencion": p["cerca_de_la_detencion"],
            "modos_relacionados": sorted({c.NOMBRE_MODO.get(r["modo"], r["modo"]) for r in p.get("modos_relacionados", [])}),
        } for p in evid.get("detenciones_previas") or []],
        "ultimo_mantenimiento_programado": a.get("ultimo_pm"),
        "recurrencias": a.get("recurrencia", []),
        "rellenos": {k: v["n"] for k, v in (a.get("rellenos") or {}).items()},
    }


def prompt_detenciones(perfil: dict, sistema: str) -> str:
    return f"""Eres un ingeniero de confiabilidad. Recibes las intervenciones de mantención del {sistema} de una unidad
({perfil["equipo"]}) en los 3 meses previos a una detención, ya filtradas a ese sistema: fecha, tipo (correctiva o
programada), subsistema, componentes, descripción, si quedaron sin cierre, si fueron en los días previos a la detención
y los modos de falla con que se relacionan. También recibes el último mantenimiento programado, las recurrencias por
subsistema, los rellenos de aceite y refrigerante y los modos de falla que el monitoreo de riesgo destacó.

Escribe dos mensajes para la sección Detenciones de un informe preliminar de falla dirigido al cliente:
- diagnostico: las intervenciones más relevantes para esta detención: qué subsistema o componente se intervino,
  cuántas veces y cuándo. Primero las correctivas recientes y las relacionadas con los modos destacados. No las
  enumeres una por una.
- causa_probable: un análisis de esos antecedentes, no una repetición del diagnóstico: si un mismo problema se repitió
  o quedó sin cerrar, si hubo trabajos en los días previos a la detención, qué origen se vuelve más probable y con qué
  modo destacado concuerda. Es probable, nunca confirmado. Si las intervenciones no orientan la causa, dilo en una
  frase.
{formato_seccion()}

Reglas:
- Usa solo lo que dicen los registros. No afirmes que una reparación falló, que causó la detención ni que algo quedó
  "confirmado por los registros".
- Fechas como "29 oct". Al sistema que destaca los modos llámalo "el monitoreo de riesgo".
- No menciones fuentes que no recibes (análisis de aceite, gráficos del monitoreo de riesgo): habla solo de las
  intervenciones y de los modos destacados.
- Si el registro usa una sigla que no está explicada (por ejemplo "UF"), no la expandas ni la adivines: nombra el
  componente que sí describe el registro (por ejemplo, "la válvula de escape").
{lineamientos(perfil)}
Devuelve SOLO JSON con la estructura pedida."""


def redactar_detenciones(evid: dict, perfil: dict, sistema: str, llm_fn: LlmFn) -> dict:
    """Diagnostico y causa probable de Detenciones. Sin registros que leer, o sin intervenciones del sistema en la
    ventana, un texto fijo (`fijo`: True) y sin IA."""
    previas = evid.get("detenciones_previas")
    if previas is None:
        return {**SIN_REGISTROS, "origen": "fijo", "fijo": True, "controles": []}
    if not previas:
        return {"diagnostico": f"No hubo intervenciones del {sistema} en los 3 meses previos a la detención.",
                "causa_probable": "Las detenciones no orientan la causa de esta detención.",
                "origen": "fijo", "fijo": True, "controles": []}
    dc = pedir(llm_fn, prompt_detenciones(perfil, sistema), entrada_detenciones(evid, perfil, sistema), ESQUEMA_DETENCIONES)
    return {"diagnostico": dc["diagnostico"].strip(), "causa_probable": dc["causa_probable"].strip(), "origen": "ia",
            "fijo": False, "controles": controles_diagnostico_causa(dc)}


# =============================================================================
# Resumen
# =============================================================================
def confianzas_permitidas(evid: dict) -> List[str]:
    """Las confianzas hasta el techo que permiten los datos (auditoria.techo_confianza)."""
    techo = (evid.get("auditoria") or {}).get("techo_confianza")
    return c.CONFIANZAS[:c.CONFIANZAS.index(techo) + 1] if techo in c.CONFIANZAS else list(c.CONFIANZAS)


def esquema_resumen(evid: dict) -> dict:
    return {"name": "resumen_secciones", "strict": True, "schema": _obj({
        "diagnostico": _TEXTO, "causa_probable": _TEXTO, "acciones": _LISTA_TEXTO, "riesgo_si_no_se_hace": _TEXTO,
        "confianza": _enum(confianzas_permitidas(evid)), "motivo_confianza": _TEXTO,
    })}


def entrada_resumen(evid: dict, perfil: dict, sistema: str, detenciones: dict,
                    contexto_cliente: Optional[dict] = None) -> dict:
    diag_m, causa_m, nota_m = _textos_predictivo(evid)
    obs = (evid.get("aceite") or {}).get("observaciones")
    aceite = ({"diagnostico": obs["diagnostico"], "causa_probable": obs["causa_probable"]} if obs else
              {"diagnostico": "No hay muestras de aceite del sistema en los 3 meses previos.",
               "causa_probable": "El aceite no orienta la causa de la detención.", "sin_muestras": True})
    entrada = {
        "unidad": evid["consulta"]["unidad"], "sistema": sistema, "equipo": perfil["equipo"],
        "fecha_detencion": evid["consulta"]["fecha"],
        "aceite": aceite,
        "monitoreo_de_riesgo": {"diagnostico": diag_m, "causa_probable": causa_m, "nota": nota_m},
        "detenciones": {"diagnostico": detenciones["diagnostico"], "causa_probable": detenciones["causa_probable"],
                        "sin_registros": bool(detenciones.get("fijo"))},
        # Las verificaciones del catalogo para los modos destacados: de ahi salen las acciones concretas.
        "verificaciones_sugeridas": {
            c.NOMBRE_MODO.get(r["modo"], r["modo"]): [
                {k: v for k, v in x.items() if k in ("accion", "que_buscar")}
                for x in c.verificaciones(c.VERIFICACIONES_POR_MODO.get(r["modo"], []))]
            for r in evid.get("ranking_modos", []) if r["nivel"] in ("alto", "medio")},
        "techo_de_confianza": confianzas_permitidas(evid)[-1],
        "advertencias_de_datos": (evid.get("auditoria") or {}).get("advertencias", []),
    }
    contexto = {k: v for k, v in (contexto_cliente or {}).items() if v}
    if contexto:
        entrada["contexto_cliente"] = contexto
    return entrada


def prompt_resumen(perfil: dict) -> str:
    d, k, a = (c.LIMITES_MENSAJE[x] for x in ("diagnostico", "causa_probable", "acciones"))
    return f"""Eres un ingeniero de confiabilidad. Una unidad ({perfil["equipo"]}, cliente {perfil["nombre"]}) tuvo una
detención y su informe preliminar de falla ya tiene tres secciones escritas, cada una con su diagnóstico y su causa
probable: Aceite (las muestras de laboratorio), Monitoreo de riesgo (el análisis publicado para la unidad) y
Detenciones (las intervenciones de mantención). Las recibes tal como las lee el cliente, más el techo de confianza
que permiten los datos, sus advertencias y las verificaciones sugeridas para los modos destacados. A veces llega un
relato del cliente (contexto_cliente) que nadie verificó.

Escribe el Resumen del informe, integrando SOLO esas tres secciones:
- diagnostico (máximo {d[0]} frases, unas {d[1]} palabras): qué pasa probablemente en el equipo.
- causa_probable (máximo {k[0]} frases, unas {k[1]} palabras): la causa principal. Si dos o más secciones apuntan a
  lo mismo, dilo; si se contradicen, dilo y no elijas sin fundamento.
- acciones (1 o {c.MAX_ACCIONES} acciones; unas {a[1]} palabras en total contando riesgo_si_no_se_hace): qué hacer,
  dónde y cuándo. Tómalas de verificaciones_sugeridas de los modos que coinciden con lo que dicen las secciones; si
  ninguna sección muestra algo, el procedimiento habitual (tomar una muestra de aceite antes de drenar).
- riesgo_si_no_se_hace: qué pasa si no se hace, en una frase corta.
- confianza (como máximo el techo de confianza) y motivo_confianza: una frase en palabras del cliente (por ejemplo,
  "el aceite y el monitoreo de riesgo apuntan a lo mismo").

Reglas:
- No agregues hechos, fechas ni causas que no estén en las tres secciones. Una sección sin registros o sin señales no
  aporta: no la uses para subir ni bajar la confianza.
- contexto_cliente no está verificado: úsalo para orientar la redacción, sin subir la confianza.
- Todo es probable, nunca confirmado; la inspección de la unidad confirma la causa. Nunca lo llames "RCA".
- La unidad YA está detenida: la urgencia es "en esta detención" o "antes de volver a operar", nunca "en la próxima
  detención".
- Acciones en imperativo formal (usted): "tome", "revise", "mida".
- Al sistema que destaca los modos llámalo "el monitoreo de riesgo".
{lineamientos(perfil)}
Devuelve SOLO JSON con la estructura pedida."""


def controles_resumen(r: dict) -> List[str]:
    problemas = [p for p in controles_diagnostico_causa(r, c.LIMITES_MENSAJE) if not p.startswith(("palabra", "término",
                                                                                                    "afirmación", "valor"))]
    total = sum(_palabras(x) for x in r["acciones"]) + _palabras(r["riesgo_si_no_se_hace"])
    if not r["acciones"] or len(r["acciones"]) > c.MAX_ACCIONES:
        problemas.append(f"acciones: {len(r['acciones'])} (deben ser 1 o {c.MAX_ACCIONES})")
    if total > c.LIMITES_MENSAJE["acciones"][1] * c.TOLERANCIA_LARGO:
        problemas.append(f"acciones: {total} palabras")
    return problemas + _vocabulario([r["diagnostico"], r["causa_probable"], r["riesgo_si_no_se_hace"],
                                     r["motivo_confianza"], *r["acciones"]])


def redactar_resumen(evid: dict, perfil: dict, sistema: str, detenciones: dict, llm_fn: LlmFn,
                     contexto_cliente: Optional[dict] = None) -> dict:
    """El Resumen (diagnostico, causa probable, acciones, riesgo, confianza y su motivo) desde las tres secciones."""
    entrada = entrada_resumen(evid, perfil, sistema, detenciones, contexto_cliente)
    r = pedir(llm_fn, prompt_resumen(perfil), entrada, esquema_resumen(evid))
    r = {**r, "diagnostico": r["diagnostico"].strip(), "causa_probable": r["causa_probable"].strip(),
         "acciones": [x.strip() for x in r["acciones"][:c.MAX_ACCIONES]]}
    return {**r, "controles": controles_resumen(r), "entrada": entrada}
