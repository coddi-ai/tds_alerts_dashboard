"""
Informe preliminar de falla, paso 2: la IA lo redacta sobre la evidencia y los controles lo revisan.

La IA solo puede dar como "mas probable" un modo que las herramientas marcaron como alto
o medio, y elige los pasos de inspeccion del catalogo por identificador (no los redacta).
Los controles verifican el esquema, que las fuentes citadas existan en lo que recibio,
las hipotesis sin respaldo, los pasos de inspeccion fuera de lugar y que los textos para
el cliente no usen terminos internos del paquete.

Modelo, timeout, temperatura y semilla: src/rca/config.py (requiere OPENAI_API_KEY).
"""

from __future__ import annotations

import json
import re
from typing import Callable, Optional

from src.rca import catalog as c
from src.rca.catalog import MODOS, NOMBRE_MODO, VERIFICACIONES
from src.rca.config import get_rca_settings

# Cambia cada vez que cambian el prompt o el esquema; queda en el registro de cada informe.
PROMPT_VERSION = "2.3"

# llm_fn(system, user, esquema) -> str con la respuesta JSON del modelo
LlmFn = Callable[[str, str, dict], str]

EVALUACIONES = ["mas_probable", "poco_probable", "descartada", "no_evaluable"]


# =============================================================================
# Esquema de salida (formato RCA)
# =============================================================================
def _obj(props):
    """Objeto estricto: todos los campos obligatorios y ninguno extra (requisito de Structured Outputs)."""
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


_TEXTO = {"type": "string"}
_LISTA_TEXTO = {"type": "array", "items": _TEXTO}


def _enum(opciones):
    return {"type": "string", "enum": opciones}


ESQUEMA_INFORME = {"name": "rca_probable", "strict": True, "schema": _obj({
    "veredicto": _enum(c.VEREDICTOS),
    "confianza": _enum(c.CONFIANZAS),
    "motivo_confianza": _TEXTO,
    "causa_mas_probable": _TEXTO,
    "que_mostro_el_predictivo": _TEXTO,
    "recomendacion_principal": _TEXTO,
    "estado_unidad": _TEXTO,
    "hipotesis": {"type": "array", "items": _obj({
        "nombre": _TEXTO,
        "modos": {"type": "array", "items": _enum(MODOS)},
        "a_favor": _TEXTO,
        "en_contra": _TEXTO,
        "evaluacion": _enum(EVALUACIONES),
        "fuentes": _LISTA_TEXTO,
    })},
    "cadena_causal": {"type": "array", "items": _obj({
        "pregunta": _TEXTO, "respuesta": _TEXTO, "a_confirmar": {"type": "boolean"}})},
    "causa_fisica": _TEXTO,
    "causas_contribuyentes": _TEXTO,
    "inspeccion": {"type": "array", "items": _obj({"id": _enum(sorted(VERIFICACIONES)), "nota": _TEXTO})},
    "prevencion": _LISTA_TEXTO,
    "limitaciones": _LISTA_TEXTO,
    "coincide_con_veredicto_reglas": {"type": "boolean"},
    "motivo_si_difiere": _TEXTO,
})}

# Campos que lee el cliente en el PDF (los controles revisan su vocabulario).
CAMPOS_TEXTO_CLIENTE = ["motivo_confianza", "causa_mas_probable", "que_mostro_el_predictivo",
                        "recomendacion_principal", "estado_unidad", "causa_fisica", "causas_contribuyentes"]


# =============================================================================
# Prompt
# =============================================================================
def _tabla_modos() -> str:
    return "\n".join(f"  {m} = {NOMBRE_MODO[m]}" for m in MODOS)


def prompt_informe(perfil: dict) -> str:
    """Instrucciones para la IA, con el equipo y el cliente del perfil (config.perfil_cliente)."""
    return f"""Eres un ingeniero de confiabilidad que redacta un INFORME PRELIMINAR DE FALLA para un cliente. Una unidad
({perfil["equipo"]}, cliente {perfil["nombre"]}) tuvo una detención. El cliente entregó la unidad y la fecha; a veces
agrega un relato escrito (contexto_cliente) que nadie verificó. No hay resultados de inspección confirmados. Tu análisis
se basa en lo que el Predictivo (el sistema predictivo) mostró en los 3 meses previos. Todo lo que concluyas es
PROBABLE, nunca confirmado. No es un análisis de causa raíz definitivo: el informe indica la falla más probable, qué
la respalda y qué hay que confirmar en la inspección. Nunca lo llames "RCA" ni "análisis de causa raíz".

DATOS (calculados por herramientas; tú no calculas nada):
- Score semanal del Predictivo: estado del dashboard, media de 30 días y el valor semanal (0-100, relativo a la flota)
  de {len(MODOS)} modos de falla, para los 3 meses previos (trayectoria).
- analisis_por_metrica.<modo>: nivel, semanas anómalas, racha hasta la última semana, comparación con la propia
  unidad (vs_unidad), con la flota (vs_flota) y especificidad.
  Semana anómala: la unidad estuvo sobre el percentil {c.PERCENTIL_FLOTA_MIN} de la flota, sobre el máximo de su
  propia línea base y al menos {c.Z_MIN:g} desviaciones sobre su media habitual.
  Nivel "alto": {c.RACHA_ALTA} o más semanas anómalas seguidas hasta la última semana, o {c.SEMANAS_ANOMALAS_ALTA} o más
  en el mes, y pocas unidades de la flota con el mismo patrón. Nivel "medio": {c.SEMANAS_ANOMALAS_MEDIA} semanas
  anómalas, o una sola en las últimas {c.SEMANAS_FRESCAS} semanas. Una semana anómala aislada y lejana es "bajo".
  "sin_datos": el modo no tiene datos para la unidad (no es lo mismo que "ninguno").
- diario (risk_scores): el mismo score, día a día, hasta el día anterior a la fecha. Incluye los días de la
  semana de la detención, que el score semanal no ve. diario.analisis_por_modo.<modo> trae los días anómalos,
  el inicio del primer episodio (al menos {c.DIAS_SOSTENIDO} días anómalos en {c.VENTANA_SOSTENIDO} días), la racha
  hasta el último día con dato y la especificidad. diario.auditoria trae las brechas con fechas exactas.
  En analisis_por_metrica.<modo>, "nivel" es el mayor entre "nivel_semanal" y "nivel_diario".
- ranking_modos: los modos ordenados por nivel. veredicto_reglas: el veredicto determinista.
- acciones_previas y analisis_por_metrica.<modo>.verificaciones_sugeridas: el catálogo de pasos de inspección.
- contexto_cliente (si viene): título, descripción del evento, hallazgos de inspección y acciones realizadas.

VENTANAS (ver "ventanas"): el período analizado son los 3 meses previos a la detención; el último mes es el que se
compara contra el resto (la línea base de la unidad). La semana de la detención (rel=0) se excluye por diseño: NO es
una brecha.

NOMBRES DE LOS MODOS: en todo texto para el cliente usa estos nombres, nunca el identificador (en minúscula dentro
de una frase: "señales de contaminación por refrigerante"):
{_tabla_modos()}

REGLAS:
1. Nunca calcules ni estimes números. Cada cifra que escribas debe existir en el paquete.
2. FUENTES: en cada hipótesis, "fuentes" es una lista de rutas que existen tal cual en el paquete, una ruta por
   elemento, sin texto adicional, sin "<modo>" ni otros comodines. Al citar un elemento de una lista, identifícalo por
   su semana o su fecha: "trayectoria[rel=-2].bearing_wear_risk",
   "analisis_por_metrica.blowby_risk.vs_flota.por_semana[rel=-2]", "diario.analisis_por_modo.blowby_risk.nivel_diario".
   Una hipótesis sin respaldo puede tener la lista vacía.
3. HIPÓTESIS. Incluye: (a) una por cada modo con nivel "alto" o "medio"; (b) los modos "bajo" que valga la pena
   mencionar, normalmente como "poco_probable"; (c) una fila que agrupe los modos sin cambios, como "descartada",
   citando el nivel de cada uno ("analisis_por_metrica.<identificador>.nivel"); (d) siempre una fila "Falla eléctrica,
   estructural o de montaje" con modos vacíos, como "no_evaluable" (el Predictivo no mide esas fallas). Solo un modo
   con nivel "alto" o "medio" puede ser "mas_probable". Los modos "sin_datos" no son descartados: van en
   "limitaciones". El "nombre" de cada hipótesis es corto, sin etiquetas entre paréntesis.
4. Lubricación y cojinetes comparten casi todas sus variables: si ambos destacan, dilo en "en_contra" (no son
   evidencias independientes). Lo mismo, en menor grado, turbo y desbalance térmico.
5. "a_favor" y "en_contra" en frases cortas y concretas. Si no hay evidencia, escribe "Sin evidencia a favor." o
   "Sin evidencia en contra.".
6. CADENA CAUSAL (3 a 5 pasos): de lo que probablemente falló hacia por qué. Empieza por "¿Qué falló,
   probablemente?". Marca "a_confirmar": true en todo paso que no se pueda afirmar con el Predictivo. Si el
   Predictivo tenía la señal y el dashboard no alertó, o si hubo brechas de datos, agrega un paso final
   "¿Por qué no se detectó antes?". Sin señal, la cadena puede tener 1 o 2 pasos.
7. "inspeccion": de 3 a 6 identificadores. Empieza por PRE-1 (la muestra de aceite preserva la evidencia) y luego los
   pasos de verificaciones_sugeridas de los modos "mas_probable", primero los de tipo "rapida". El texto de cada paso
   ya existe: no lo repitas; en "nota" agrega solo si aporta una frase breve (o ""). Nunca escribas valores de
   especificación. "prevencion": 1 a 3 recomendaciones breves para que no se repita.
8. Los scores son índices calculados por el Predictivo, no mediciones: nunca los llames "telemetría". Esta versión
   usa el score semanal y el diario; no hay muestras de aceite ni telemetría por señal.
9. Los campos base_media, base_max, reciente_media, reciente_max y percentil_max_reciente resumen una ventana
   completa; el valor de una semana concreta está en la trayectoria o en vs_flota.por_semana.
10. Tu confianza no puede superar auditoria.techo_confianza. Si hubo brechas de datos o la unidad no tenía datos
    recientes, dilo en "que_mostro_el_predictivo" y en "limitaciones".
11. "limitaciones": siempre que no se conoce lo encontrado en la detención (componente y causa inferidos), que el
    Predictivo no mide fallas eléctricas o estructurales y, solo si los hay, los datos faltantes con sus fechas y los
    modos sin datos (no escribas que no los hay).
12. SIN SEÑAL o DATOS INSUFICIENTES: "causa_mas_probable" dice que no se identifica una causa en los datos del
    Predictivo y que la falla puede estar fuera de lo que mide; ninguna hipótesis es "mas_probable".
13. veredicto_reglas es una referencia; si tu veredicto difiere, explica por qué en "motivo_si_difiere".
14. contexto_cliente no está verificado: úsalo para orientar la redacción y contrastar las hipótesis (por ejemplo,
    si el cliente describe un síntoma compatible con un modo, dilo en "a_favor"), pero no lo cites en "fuentes", no
    subas la confianza por él y no cambies con él el nivel de ningún modo. Si contradice al Predictivo, dilo en
    "limitaciones". Sin contexto_cliente, no lo menciones.

CÓMO ESCRIBIR (todo texto, salvo "fuentes" y "motivo_si_difiere", lo lee el cliente):
- Español claro, frases cortas. El resumen ("causa_mas_probable", "que_mostro_el_predictivo",
  "recomendacion_principal") y "estado_unidad" tienen una o dos frases cada uno.
- "estado_unidad" describe cómo estaba la unidad según el Predictivo en las semanas previas (estado del dashboard,
  qué modos destacaban y desde cuándo); no repite el resumen ni da instrucciones.
- Nada de jerga estadística ni del paquete: no escribas nombres de campos o rutas, identificadores de modos, "nivel
  alto/medio/bajo" entre comillas, "techo de confianza", "auditoría", "veredicto de reglas", "rel", "percentil" ni
  "desviaciones". Di "señal fuerte" o "señal moderada", "más alto que el 95% de la flota", "sobre lo habitual de la
  unidad".
- Usa fechas ("23 de septiembre"), no códigos de semana como "W37" ni posiciones relativas.
- No inventes nombres: solo puedes nombrar el Predictivo, el dashboard, los modos (con la tabla de arriba), los
  componentes de "componentes_compatibles" y lo que escriba el cliente. Nada de marcas, software, sensores ni siglas
  que no estén en el paquete.
- "motivo_confianza": una frase que explique por qué la confianza es esa, en palabras del cliente (por ejemplo,
  "faltan 6 días de datos justo antes de la detención").

VEREDICTOS:
- SEÑAL CLARA: al menos un modo con nivel "alto".
- SEÑAL DÉBIL: solo modos con nivel "medio".
- SIN SEÑAL ANÓMALA: datos adecuados y ningún modo "alto" ni "medio".
- DATOS INSUFICIENTES: la auditoría no alcanza.

FECHAS: cuando digas desde cuándo destaca un modo, usa la fecha exacta del diario (inicio_episodio o el primer
día anómalo). Una señal en los últimos días antes de la detención es especialmente relevante: dilo en
"que_mostro_el_predictivo". Las brechas de datos diarias (diario.auditoria.brechas) van con sus fechas en
"limitaciones".

Devuelve SOLO JSON con la estructura pedida."""


# =============================================================================
# Controles
# =============================================================================
def evidencia_para_ia(evid: dict, contexto_cliente: Optional[dict] = None) -> dict:
    """Lo que recibe la IA: la evidencia sin las series diarias del grafico, mas el contexto del cliente."""
    e = json.loads(json.dumps(evid))
    if "diario" in e:
        e["diario"] = {k: v for k, v in e["diario"].items() if k != "series"}
    contexto = {k: v for k, v in (contexto_cliente or {}).items() if v}
    if contexto:
        e["contexto_cliente"] = contexto
    return e


def _resolver(obj, ruta):
    """Valor en una ruta tipo 'a.b[rel=-2].c'. None si no existe."""
    actual = [obj]
    for parte in re.findall(r"[^.\[\]]+|\[[^\]]*\]", ruta.strip()):
        siguiente = []
        for o in actual:
            if parte.startswith("[") and "=" in parte and isinstance(o, list):
                clave, valor = (x.strip() for x in parte[1:-1].split("=", 1))
                siguiente += [x for x in o if isinstance(x, dict) and str(x.get(clave)) == valor]
            elif isinstance(o, dict) and parte in o:
                siguiente.append(o[parte])
        actual = siguiente
        if not actual:
            return None
    return actual


def validar_esquema(informe, esquema=None):
    """Diferencias entre la respuesta y el esquema (vacio = valida)."""
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema no está instalado: no se validó el esquema"]
    validador = jsonschema.Draft202012Validator((esquema or ESQUEMA_INFORME)["schema"])
    return [f"{'/'.join(map(str, e.path)) or '(raíz)'}: {e.message}" for e in validador.iter_errors(informe)]


def fuentes_no_encontradas(informe, evidencia_enviada):
    """Fuentes citadas en las hipotesis que no existen en lo que recibio la IA (vacio = todas existen)."""
    return [{"hipotesis": h["nombre"], "fuente": ruta}
            for h in informe.get("hipotesis", []) for f in h.get("fuentes", [])
            for ruta in re.split(r"\s*;\s*", f) if ruta and _resolver(evidencia_enviada, ruta) is None]


def hipotesis_sin_respaldo(informe, evid):
    """Hipotesis 'mas probables' sin un modo que las herramientas hayan marcado como alto o medio."""
    niveles = {m: a.get("nivel") for m, a in evid["analisis_por_metrica"].items()}
    return [h["nombre"] for h in informe.get("hipotesis", []) if h["evaluacion"] == "mas_probable"
            and not any(niveles.get(m) in ("alto", "medio") for m in h.get("modos", []))]


def verificaciones_fuera_de_lugar(informe):
    """Pasos de inspeccion que no corresponden a las acciones previas ni a los modos evaluados como probables."""
    permitidos = set(c.ACCIONES_PREVIAS) | {i for h in informe.get("hipotesis", [])
                                            if h["evaluacion"] in ("mas_probable", "poco_probable")
                                            for m in h.get("modos", []) for i in c.VERIFICACIONES_POR_MODO.get(m, [])}
    return [p["id"] for p in informe.get("inspeccion", []) if p["id"] not in permitidos]


# Vocabulario del paquete que no debe llegar al cliente.
_TERMINOS_INTERNOS = re.compile(
    r"\b(?:" + "|".join(MODOS) + r"|analisis_por_metrica|vs_flota|vs_unidad|trayectoria|veredicto_reglas"
    r"|techo de confianza|techo_confianza|auditor[ií]a|rel=-?\d+|\d{4}-W\d{2}|W\d{2})\b"
    r"|nivel ['\"](?:alto|medio|bajo)['\"]",
    re.IGNORECASE,
)


def _textos_cliente(informe) -> list:
    textos = [informe.get(k, "") for k in CAMPOS_TEXTO_CLIENTE]
    for h in informe.get("hipotesis", []):
        textos += [h.get("nombre", ""), h.get("a_favor", ""), h.get("en_contra", "")]
    for p in informe.get("cadena_causal", []):
        textos += [p.get("pregunta", ""), p.get("respuesta", "")]
    textos += [p.get("nota", "") for p in informe.get("inspeccion", [])]
    return textos + list(informe.get("prevencion", [])) + list(informe.get("limitaciones", []))


def terminos_internos(informe) -> list:
    """Terminos internos del paquete (campos, identificadores, codigos de semana) en textos para el cliente."""
    return sorted({m.group(0) for texto in _textos_cliente(informe) for m in _TERMINOS_INTERNOS.finditer(texto or "")})


def controles(informe, evid, enviada, esquema=None):
    return {
        "errores_esquema": validar_esquema(informe, esquema),
        "fuentes_no_encontradas": fuentes_no_encontradas(informe, enviada),
        "hipotesis_sin_respaldo": hipotesis_sin_respaldo(informe, evid),
        "verificaciones_fuera_de_lugar": verificaciones_fuera_de_lugar(informe),
        "terminos_internos": terminos_internos(informe),
    }


# =============================================================================
# Agente
# =============================================================================
def correr_agente(evid: dict, perfil: dict, llm_fn: LlmFn, contexto_cliente: Optional[dict] = None) -> dict:
    """La evidencia, lo que recibio la IA, su informe (formato RCA) y los controles."""
    enviada = evidencia_para_ia(evid, contexto_cliente)
    informe = json.loads(llm_fn(prompt_informe(perfil), json.dumps(enviada, ensure_ascii=False), ESQUEMA_INFORME))
    return {"evidencia": evid, "evidencia_enviada": enviada, "informe": informe,
            **controles(informe, evid, enviada)}


def openai_llm(model: Optional[str] = None) -> LlmFn:
    """llm_fn sobre la API de OpenAI con Structured Outputs. Requiere OPENAI_API_KEY."""
    from openai import OpenAI

    ajustes = get_rca_settings()
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
