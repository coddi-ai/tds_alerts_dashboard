"""
Informe preliminar de falla, paso 2: la IA redacta sus textos sobre la evidencia y los controles los revisan.

La IA escribe el diagnostico y la causa probable de la seccion Detenciones y, al final, el Resumen
(diagnostico, causa probable y acciones) integrando el Predictivo y las detenciones. El diagnostico
y la causa probable de la seccion Predictivo no los escribe: vienen de unit_failure_analisis.
Todos los textos siguen los lineamientos de mensajes del Analisis Inteligente (largos, vocabulario,
glosario). Los controles verifican el esquema, el largo de cada mensaje, el vocabulario prohibido,
los terminos internos del paquete y las afirmaciones que los registros de mantencion no permiten.

Modelo, timeout, temperatura y semilla: src/informe_falla/config.py (requiere OPENAI_API_KEY).
"""

from __future__ import annotations

import json
import re
from typing import Callable, Optional

from src.informe_falla import catalog as c
from src.informe_falla.catalog import MODOS, NOMBRE_MODO
from src.informe_falla.config import get_informe_settings

# Cambia cada vez que cambian el prompt o el esquema; queda en el registro de cada informe.
PROMPT_VERSION = "3.1"

# llm_fn(system, user, esquema) -> str con la respuesta JSON del modelo
LlmFn = Callable[[str, str, dict], str]


# =============================================================================
# Esquema de salida (informe preliminar de fallas)
# =============================================================================
# La IA escribe dos de las tres secciones del informe, en este orden:
#   1. detenciones: diagnostico y causa probable a partir de las mantenciones previas;
#   2. resumen: diagnostico, causa probable y acciones, integrando el Predictivo y las detenciones.
# El diagnostico y la causa probable de la seccion Predictivo NO los escribe: vienen de
# unit_failure_analisis (analisis_unidad.py), el mismo texto que el cliente ve en la plataforma.
def _obj(props):
    """Objeto estricto: todos los campos obligatorios y ninguno extra (requisito de Structured Outputs)."""
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


_TEXTO = {"type": "string"}
_LISTA_TEXTO = {"type": "array", "items": _TEXTO}


def _enum(opciones):
    return {"type": "string", "enum": opciones}


ESQUEMA_INFORME = {"name": "informe_preliminar_falla", "strict": True, "schema": _obj({
    "veredicto": _enum(c.VEREDICTOS),
    "confianza": _enum(c.CONFIANZAS),
    "motivo_confianza": _TEXTO,
    "detenciones": _obj({"diagnostico": _TEXTO, "causa_probable": _TEXTO}),
    "resumen": _obj({"diagnostico": _TEXTO, "causa_probable": _TEXTO, "acciones": _LISTA_TEXTO,
                     "riesgo_si_no_se_hace": _TEXTO}),
    "coincide_con_veredicto_reglas": {"type": "boolean"},
    "motivo_si_difiere": _TEXTO,
})}


def _textos_cliente(informe) -> list:
    """Todo lo que lee el cliente en el PDF (los controles revisan su vocabulario)."""
    r, d = informe.get("resumen") or {}, informe.get("detenciones") or {}
    return [informe.get("motivo_confianza", ""), r.get("diagnostico", ""), r.get("causa_probable", ""),
            *r.get("acciones", []), r.get("riesgo_si_no_se_hace", ""), d.get("diagnostico", ""),
            d.get("causa_probable", "")]


# =============================================================================
# Prompt
# =============================================================================
def _tabla_modos() -> str:
    return "\n".join(f"  {m} = {NOMBRE_MODO[m]}" for m in MODOS)


def _limite(campo: str) -> str:
    frases, palabras = c.LIMITES_MENSAJE[campo]
    return f"máximo {frases} frases, unas {palabras} palabras"


def prompt_informe(perfil: dict) -> str:
    """Instrucciones para la IA, con el equipo y el cliente del perfil (config.perfil_cliente)."""
    return f"""Eres un ingeniero de confiabilidad que redacta un INFORME PRELIMINAR DE FALLAS para un cliente. Una unidad
({perfil["equipo"]}, cliente {perfil["nombre"]}) tuvo una detención. El cliente entregó la unidad y la fecha; a veces
agrega un relato escrito (contexto_cliente) que nadie verificó. No hay resultados de inspección confirmados. Todo lo
que concluyas es PROBABLE, nunca confirmado. Nunca lo llames "RCA" ni "análisis de causa raíz".

El informe tiene tres secciones:
1. Resumen: diagnóstico, causa probable y acciones. Lo escribes tú, AL FINAL, integrando las otras dos.
2. Predictivo: gráficos y tablas del sistema predictivo, más su diagnóstico y causa probable, que YA EXISTEN
   (analisis_unidad: el texto que el Predictivo publicó para esta unidad la semana previa). No los reescribas.
3. Detenciones: las detenciones previas de la unidad. Escribes su diagnóstico y su causa probable.

DATOS (calculados por herramientas; tú no calculas nada):
- analisis_unidad: diagnóstico, causa probable, acciones y limitación que el Predictivo publicó para la unidad,
  con su fecha. "con_texto": false = la unidad estaba normal y el Predictivo no escribió nada; "disponible":
  false = no hay análisis previo. "antiguo": true = tiene más de {c.DIAS_ANALISIS_VIEJO} días antes de la detención.
- analisis_por_metrica.<modo> y ranking_modos: el nivel de cada modo de falla en el último mes ("alto", "medio",
  "bajo", "ninguno" o "sin_datos"), comparado con lo habitual de la propia unidad. "nivel" es el mayor entre el
  semanal y el diario. diario.analisis_por_modo.<modo> trae los días anómalos y el inicio del episodio.
- trayectoria: el estado semanal de la unidad ("normal", "alerta", "anormal") en los 3 meses previos.
- ciclo_vida: el estado general del motor según sus horas de uso, comparado con los demás motores de la flota
  con las mismas horas. No es el modo "desgaste acumulado": no los mezcles. estado_final ("Normal", "Alerta", "Anormal"), evaluable (false = bajo
  {c.HORAS_MIN_CURVA} horas: "Normal" no significa sano), fuera_de_normal_desde, horas_motor, fecha_ultimo_dato.
  Cómo usarlo en los textos:
  · Nunca lo nombres como gráfico ni como herramienta: di "el estado general del motor" o "para sus horas de
    uso". Ejemplos: "para sus horas de uso, el motor ya estaba por sobre lo habitual de la flota";
    "para sus horas de uso, el estado general del motor era normal".
  · Menciónalo solo si cambia la decisión: "Alerta" o "Anormal" refuerza la causa probable o la urgencia;
    "Normal" solo vale la pena decirlo si es lo único que contradice a las otras señales.
  · Si fecha_ultimo_dato es anterior a las señales del último mes, o si evaluable es false, no lo menciones:
    describe un momento anterior y no aporta a esta detención. Nunca escribas su fecha.
- veredicto_reglas: el veredicto determinista (referencia).
- Mantenciones (registros ANTERIORES a la detención; no son hallazgos de esta detención):
  cobertura_mantenciones.estado ("completa", "parcial", "unidad_sin_registros", "fuera_de_cobertura",
  "sin_fuente"); detenciones_previas (fecha, tipo Correctiva/Programada/Sin clasificar, subsistema, componentes,
  qué se hizo, horas, modos_relacionados, cerca_de_la_detencion); antecedentes_mantencion (último mantenimiento
  programado, correctivas repetidas por subsistema, rellenos de aceite o refrigerante).
- acciones_previas y analisis_por_metrica.<modo>.verificaciones_sugeridas: el catálogo de pasos de inspección.
  Úsalo para elegir QUÉ revisar en las acciones; redáctalo en palabras simples.
- contexto_cliente (si viene): título, descripción, hallazgos y acciones que escribió el cliente.

NOMBRES DE LOS MODOS: en todo texto usa estos nombres, nunca el identificador, en minúscula dentro de una frase:
{_tabla_modos()}

PASO 1. DETENCIONES ("detenciones"):
- Diagnóstico: qué muestran las detenciones previas que importa para esta falla (por ejemplo, correctivas
  repetidas en el mismo sistema o rellenos frecuentes), con una sola cifra.
- Causa probable: qué sugieren sobre la causa, con su nivel de certeza.
- Una correctiva reciente sobre un componente relacionado pesa en los dos sentidos (reparado, o mal reparado o con
  causa no resuelta). La relación entre modos y subsistemas es una propuesta sin validar: escribe "relacionado
  con", nunca "causado por" ni "confirmado por el registro".
- Un registro con cerca_de_la_detencion = true puede ser parte de esta misma detención: descríbelo así.
- Si cobertura_mantenciones.estado no es "completa", no afirmes que no hubo intervenciones: di que no hay
  registros. Si detenciones_previas es null: diagnóstico "No hay registros de mantención de la unidad para este
  período." y causa probable "Las detenciones no permiten orientar la causa.".

PASO 2. RESUMEN ("resumen"), integrando el Predictivo (analisis_unidad + niveles + estados + ciclo_vida) y las
detenciones (lo que escribiste en el paso 1):
- Si las dos fuentes apuntan a lo mismo, dilo en una frase; la confianza puede subir.
- Si se contradicen, dilo en la causa probable, y la acción principal es verificar cuál de las dos se cumple.
- Si una de las dos no aporta (sin texto, sin registros o sin señal), dilo en la causa probable en una frase.
- La unidad YA está detenida: la urgencia es "en esta detención" o "antes de volver a operar".

LINEAMIENTOS DE LOS MENSAJES (valen para los cinco textos que escribes):
Principios
- Escribe para un operador o supervisor, no para un ingeniero: el vocabulario de un colega en terreno.
- Incluye solo lo que cambia la decisión. Si un dato no modifica lo que el usuario hará, no lo menciones.
- Sé asertivo en la acción y honesto en la incertidumbre. Nunca inventes certeza.
- No inventes datos: cada cifra debe existir en el paquete. Si falta información clave, dilo en una frase.
- Consistencia: la misma estructura, el mismo orden y las mismas palabras para el mismo concepto.
- Prueba de los 5 segundos: el lector debe poder responder qué pasa, qué tan urgente es y qué hace.
Diagnóstico ({_limite("diagnostico")})
- Abre con qué pasa en el equipo, en lenguaje cotidiano.
- Una sola cifra o comparación, traducida a algo comprensible ("seis veces lo normal para este motor").
- Deja clara la gravedad o la urgencia con una palabra o frase simple.
- Sin variables técnicas sueltas, porcentajes múltiples ni historial que no cambie la acción.
Causa probable ({_limite("causa_probable")})
- Una causa principal en palabras simples; si hay dos plausibles, como máximo dos.
- Certeza con una expresión directa: "lo más probable es…", "se sospecha…", "aún no se puede confirmar".
- Si no se puede concluir, dilo y señala que la inspección lo confirmará. No expliques cómo razonaste.
Acciones (máximo {c.MAX_ACCIONES} acciones en "acciones", unas {c.LIMITES_MENSAJE["acciones"][1]} palabras en total contando "riesgo_si_no_se_hace")
- Una acción principal con qué hacer, dónde y cuándo. Una secundaria solo si es complementaria.
- Cuando corresponda, qué hacer según el resultado: "si está limpio, avisar para seguir el análisis".
- Verbos en imperativo y concretos (revisar, comparar, avisar, tomar). Nunca "evaluar", "monitorear" ni
  "considerar". Nunca etiquetas como "Inmediato", "Próxima ventana" o "Próximo PM": usa el momento real.
- "riesgo_si_no_se_hace": qué pasa si no se hace (falla mayor, nueva detención, mayor costo), en una frase corta.
Lenguaje
- Frases cortas, voz activa, español cotidiano de operación. Cifras en términos humanos ("casi un tercio del día").
- Prohibido: "score", "puntaje de riesgo", "anomalía", "desviación", "percentil", "sigma", "ranking", "banco",
  "PM", "diferencial", "admisión", "inyección", "dashboard", "telemetría", nombres de campos o rutas del paquete,
  identificadores de modos, códigos de semana ("W09"), términos en inglés y siglas sin explicar.
- Prohibido: "curva", "curva acumulada", "ciclo de vida", "riesgo acumulado", "zona normal/alerta/anormal".
- Prohibido: "es compatible con", "no permite concluir", "podría estar relacionado", "podría eventualmente".
- Sin dramatismo ("crítico", "grave") si los datos no lo respaldan.
- Glosario: desbalance térmico → un lado del motor más caliente que el otro; banco derecho o izquierdo → lado
  derecho o izquierdo del motor; sistema de admisión y escape → entrada de aire y salida de gases; inyección →
  entrega de combustible; excursiones → momentos fuera de lo normal; PM → próxima mantención.
- Fechas como "23 de febrero", nunca códigos de semana ni posiciones relativas.
Casos especiales
- Sin hallazgo en el Predictivo ni en las detenciones: dilo brevemente; las acciones son el procedimiento
  habitual de diagnóstico de la detención (por ejemplo, tomar una muestra de aceite antes de drenar). No inventes.
- Datos incompletos o contradictorios: dilo en la causa probable y deja la acción en una verificación simple.

OTRAS REGLAS
- Tu confianza no puede superar auditoria.techo_confianza. "motivo_confianza": una frase en palabras del cliente
  (por ejemplo, "el Predictivo y las detenciones apuntan a lo mismo" o "faltan 6 días de datos antes de la
  detención").
- contexto_cliente no está verificado: úsalo para orientar la redacción, sin subir la confianza ni cambiar niveles.
- veredicto_reglas es una referencia; si tu veredicto difiere, explica por qué en "motivo_si_difiere".

VEREDICTOS:
- SEÑAL CLARA: al menos un modo con nivel "alto".
- SEÑAL DÉBIL: solo modos con nivel "medio".
- SIN SEÑAL ANÓMALA: datos adecuados y ningún modo "alto" ni "medio".
- DATOS INSUFICIENTES: la auditoría no alcanza.

ANTES DE RESPONDER, verifica: ¿un operador entiende cada palabra?, ¿hay una acción principal con qué, dónde y
cuándo?, ¿se entiende la urgencia?, ¿cada dato cambia lo que el usuario hará?, ¿respetas los largos?, ¿distingues
lo que se sabe de lo que se sospecha?

Devuelve SOLO JSON con la estructura pedida."""


# =============================================================================
# Controles
# =============================================================================
def evidencia_para_ia(evid: dict, contexto_cliente: Optional[dict] = None) -> dict:
    """Lo que recibe la IA: la evidencia sin las series de los graficos, mas el contexto del cliente.

    Las muestras de aceite no van: tienen su propio resumen (aceite.observaciones_laboratorio) y el prompt
    del informe no las menciona.
    """
    e = json.loads(json.dumps({k: v for k, v in evid.items() if k != "aceite"}))
    if "diario" in e:
        e["diario"] = {k: v for k, v in e["diario"].items() if k != "series"}
    if e.get("ciclo_vida"):
        e["ciclo_vida"] = {k: v for k, v in e["ciclo_vida"].items() if k not in ("puntos", "banda", "flota")}
    contexto = {k: v for k, v in (contexto_cliente or {}).items() if v}
    if contexto:
        e["contexto_cliente"] = contexto
    return e


def validar_esquema(informe, esquema=None):
    """Diferencias entre la respuesta y el esquema (vacio = valida)."""
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema no está instalado: no se validó el esquema"]
    validador = jsonschema.Draft202012Validator((esquema or ESQUEMA_INFORME)["schema"])
    return [f"{'/'.join(map(str, e.path)) or '(raíz)'}: {e.message}" for e in validador.iter_errors(informe)]


# Vocabulario del paquete que no debe llegar al cliente.
_TERMINOS_INTERNOS = re.compile(
    r"\b(?:" + "|".join(MODOS + c.MODOS_EXCLUIDOS) + r"|analisis_por_metrica|analisis_unidad|ciclo_vida"
    r"|vs_flota|vs_unidad|trayectoria|veredicto_reglas|techo de confianza|techo_confianza|auditor[ií]a"
    r"|rel=-?\d+|\d{4}-W\d{2}|W\d{2})\b|nivel ['\"](?:alto|medio|bajo)['\"]",
    re.IGNORECASE,
)

# Lineamientos de mensajes: jerga y estructuras defensivas que no van en los textos para el cliente.
_LENGUAJE_PROHIBIDO = re.compile(
    r"\b(?:scores?|puntajes? de riesgo|anomal[ií]as?|desviaci[oó]n(?:es)?|percentil(?:es)?|sigmas?|ranking"
    r"|curvas?(?: acumuladas?)?|ciclo de vida|riesgo acumulado|zonas? (?:normal|de alerta|alerta|anormal)"
    r"|bancos?|PM|diferencial(?:es)?|admisi[oó]n|inyecci[oó]n|dashboard|telemetr[ií]a|desbalance t[eé]rmico"
    r"|excursi[oó]n(?:es)?|evaluar|monitorear|considerar|pr[oó]xima ventana|pr[oó]ximo pm"
    r"|es compatible con|no permite concluir|podr[ií]a estar relacionad[oa]|podr[ií]a eventualmente)\b"
    r"|\binmediato\s*:",                      # etiqueta de horizonte; "de inmediato" en una frase si vale
    re.IGNORECASE,
)

_AFIRMACIONES_PROHIBIDAS = re.compile(
    r"confirmad[oa]s? (?:por|en) (?:el |los |la |las )?(?:registros?|mantenci[oó]n|historial)"
    r"|causad[oa]s? por (?:la |el )?(?:mantenci[oó]n|intervenci[oó]n|registro)", re.IGNORECASE)


def _hallazgos(patron, informe) -> list:
    return sorted({m.group(0) for texto in _textos_cliente(informe) for m in patron.finditer(texto or "")})


def terminos_internos(informe) -> list:
    """Terminos internos del paquete (campos, identificadores, codigos de semana) en textos para el cliente."""
    return _hallazgos(_TERMINOS_INTERNOS, informe)


def lenguaje_prohibido(informe) -> list:
    """Palabras y estructuras que los lineamientos de mensajes prohiben."""
    return _hallazgos(_LENGUAJE_PROHIBIDO, informe)


def afirmaciones_prohibidas(informe) -> list:
    """Frases que convierten un registro de mantencion en prueba (la equivalencia esta sin validar)."""
    return _hallazgos(_AFIRMACIONES_PROHIBIDAS, informe)


def _frases(texto: str) -> int:
    return len([f for f in re.split(r"[.!?]+(?:\s|$)", texto or "") if f.strip()])


def _palabras(texto: str) -> int:
    return len(re.findall(r"\w+", texto or ""))


def largo_excedido(informe) -> list:
    """Mensajes que se pasan de los limites de los lineamientos (con TOLERANCIA_LARGO en palabras)."""
    avisos = []
    for seccion in ("resumen", "detenciones"):
        datos = informe.get(seccion) or {}
        for campo in ("diagnostico", "causa_probable"):
            frases, palabras = c.LIMITES_MENSAJE[campo]
            texto = datos.get(campo, "")
            if _frases(texto) > frases or _palabras(texto) > palabras * c.TOLERANCIA_LARGO:
                avisos.append(f"{seccion}.{campo}: {_frases(texto)} frases, {_palabras(texto)} palabras")
    resumen = informe.get("resumen") or {}
    acciones = resumen.get("acciones") or []
    total = sum(_palabras(a) for a in acciones) + _palabras(resumen.get("riesgo_si_no_se_hace", ""))
    if len(acciones) > c.MAX_ACCIONES or not acciones:
        avisos.append(f"resumen.acciones: {len(acciones)} acciones (deben ser 1 o {c.MAX_ACCIONES})")
    if total > c.LIMITES_MENSAJE["acciones"][1] * c.TOLERANCIA_LARGO:
        avisos.append(f"resumen.acciones: {total} palabras")
    return avisos


def controles(informe, evid, enviada, esquema=None):
    return {
        "errores_esquema": validar_esquema(informe, esquema),
        "terminos_internos": terminos_internos(informe),
        "lenguaje_prohibido": lenguaje_prohibido(informe),
        "afirmaciones_prohibidas": afirmaciones_prohibidas(informe),
        "largo_excedido": largo_excedido(informe),
    }


# =============================================================================
# Agente
# =============================================================================
def correr_agente(evid: dict, perfil: dict, llm_fn: LlmFn, contexto_cliente: Optional[dict] = None) -> dict:
    """La evidencia, lo que recibio la IA, su informe (formato informe preliminar) y los controles."""
    enviada = evidencia_para_ia(evid, contexto_cliente)
    informe = json.loads(llm_fn(prompt_informe(perfil), json.dumps(enviada, ensure_ascii=False), ESQUEMA_INFORME))
    return {"evidencia": evid, "evidencia_enviada": enviada, "informe": informe,
            **controles(informe, evid, enviada)}


def openai_llm(model: Optional[str] = None) -> LlmFn:
    """llm_fn sobre la API de OpenAI con Structured Outputs. Requiere OPENAI_API_KEY."""
    from openai import OpenAI

    ajustes = get_informe_settings()
    client = OpenAI(timeout=ajustes.llm_timeout_seconds)
    model = model or ajustes.model
    # Solo se envian si estan configurados: no todos los modelos los aceptan.
    opcionales = {k: v for k, v in (("temperature", ajustes.temperature), ("seed", ajustes.seed)) if v is not None}

    def llm_fn(system: str, user: str, esquema: Optional[dict] = None) -> str:
        formato = {"type": "json_schema", "json_schema": esquema} if esquema else {"type": "json_object"}
        respuesta = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=formato,
            **opcionales,
        )
        return respuesta.choices[0].message.content

    return llm_fn