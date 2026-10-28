"""
Informe preliminar de falla: las muestras de aceite del sistema en los 3 meses previos a la detencion.

Para una unidad, un sistema y la fecha de la detencion, junta las muestras de laboratorio
(oil/golden/{cliente}/classified.parquet, la misma fuente que la vista de Aceite) de los componentes
del sistema, desde el inicio de la ventana del informe (evid["ventanas"]["periodo_desde"]) y
ESTRICTAMENTE ANTERIORES a la fecha. Nada posterior.

Al informe van la fecha y el resultado de cada muestra y el nivel cualitativo de los ensayos fuera de
limite (marginal o critico); no las concentraciones. La recomendacion que el laboratorio escribio para
cada muestra (`ai_recommendation`) se resume en conjunto en `observaciones_laboratorio`: el diagnostico y la
causa probable de la seccion, con el formato del resto del informe (secciones.py), que redacta la IA o, si no
se puede, un resumen sin IA. Nunca bloquea el informe.

Notas:
- Los cambios de aceite no estan registrados: se infieren porque el horometro del aceite (oilMeter)
  vuelve a partir entre dos muestras del mismo componente. La primera muestra de la ventana no marca
  cambio (su anterior es de antes de los 3 meses). Igual con las horas del motor: si vuelven a partir, hubo un
  cambio de motor.
- Un motor con menos de RODAJE_HORAS_MOTOR horas esta en asentamiento: el cobre alto es esperable y el texto
  lo nombra en pocas palabras, sin tomarlo como causa.
- El resultado de cada muestra y el nivel de cada ensayo los da el clasificador del laboratorio, con
  limites calculados sobre toda la historia; las recomendaciones se generaron despues
  (`ai_generated_at`), pero cada una describe solo su muestra.

Uso: muestras_aceite("CAPSTONE", "CA-30", "2025-12-05", desde="2025-09-01")
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import List, Optional

import pandas as pd

from src.data import predictive_catalog
from src.data.loaders import load_oil_classified
from src.data.report_health import unit_key
from src.informe_falla import catalog as c
from src.informe_falla import secciones
from src.informe_falla.agent import LlmFn
from src.informe_falla.config import get_informe_settings
from src.informe_falla.report_html import _fecha_corta
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Componentes de cada sistema tal como los nombra el laboratorio (componentNameNormalized, de todos los
# clientes). Lista explicita a proposito: "motor de giro" o "motor de traccion" son otros sistemas.
COMPONENTES_ACEITE = {c.COMPONENTE: ("motor", "motor diesel", "motor diesel delantero", "motor diesel trasero")}

RODAJE_HORAS_MOTOR = 500   # bajo esto el motor esta en asentamiento: el cobre alto es esperable
NIVEL_ENSAYO = {"Marginal": "marginal", "Critico": "crítico", "Crítico": "crítico"}

# Concentraciones en el texto del laboratorio: "(Cu 6,7 ppm, K 17,5 ppm)" o "8,4 ppm". Las horas
# ("seguimiento cada 125 hrs") quedan.
_CONCENTRACION = re.compile(r"\s*\((?=[^)]*\d)[^)]*\)|\d+(?:[.,]\d+)?\s*(?:ppm|%|cSt)\b", re.IGNORECASE)
_VALOR = re.compile(r"\d+(?:[.,]\d+)?\s*(?:ppm|%|cSt)\b", re.IGNORECASE)


# =============================================================================
# Carga (con cache por cliente, como las mantenciones)
# =============================================================================
_CACHE: dict = {}
_LOCK = threading.Lock()


def _cargar(cliente: str) -> pd.DataFrame:
    """Muestras clasificadas del cliente, listas para filtrar; DataFrame vacio si no hay fuente."""
    cliente = (cliente or "").lower()
    with _LOCK:
        guardado = _CACHE.get(cliente)
        if guardado and time.time() - guardado[0] < get_informe_settings().data_cache_seconds:
            return guardado[1]
        tabla = _preparar(load_oil_classified(cliente))
        _CACHE[cliente] = (time.time(), tabla)
        return tabla


def _preparar(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or not {"unitId", "sampleDate", "componentNameNormalized"} <= set(df.columns):
        return pd.DataFrame()
    df = df.copy()
    fechas = pd.to_datetime(df["sampleDate"], errors="coerce")
    if getattr(fechas.dt, "tz", None) is not None:
        fechas = fechas.dt.tz_localize(None)
    df["dia"] = fechas.dt.normalize()
    df["unidad_key"] = df["unitId"].map(unit_key)
    df["componente_norm"] = df["componentNameNormalized"].fillna("").str.strip().str.lower()
    nombre = df["componentName"] if "componentName" in df.columns else df["componente_norm"]
    df["componente"] = nombre.fillna(df["componente_norm"]).str.strip().str.capitalize()
    return df.dropna(subset=["dia"])


# =============================================================================
# Muestras
# =============================================================================
def niveles_fuera(valor) -> dict:
    """breached_essays (JSON del clasificador) como {ensayo: 'marginal' | 'crítico'}, sin valores."""
    try:
        ensayos = json.loads(valor) if isinstance(valor, str) else list(valor if valor is not None else [])
    except (TypeError, ValueError):
        return {}
    return {e.get("essay"): NIVEL_ENSAYO.get(e.get("threshold"), str(e.get("threshold")).lower())
            for e in ensayos if isinstance(e, dict) and e.get("essay")}


def sin_concentraciones(texto) -> str:
    return " ".join(_CONCENTRACION.sub("", texto if isinstance(texto, str) else "").split())


def _nombres_ensayo(cliente: str) -> dict:
    """Nombre legible de cada ensayo ("Viscocidad" -> "Viscosidad"), sin la unidad."""
    try:
        senales = predictive_catalog.get_signals_catalog((cliente or "").lower())
    except Exception:
        return {}
    return {k: v["label"].split(" (")[0] for k, v in senales.items() if v.get("label")}


def _horas(x) -> Optional[float]:
    return None if x is None or pd.isna(x) else round(float(x), 1)


def _texto(x) -> Optional[str]:
    return None if x is None or (isinstance(x, float) and pd.isna(x)) else str(x)


def muestras_aceite(cliente: str, unidad: str, fecha, desde, sistema: str = c.COMPONENTE) -> dict:
    """La clave `aceite` de la evidencia: las muestras del sistema entre `desde` y el dia anterior a `fecha`.

    `disponible` es False cuando no hay fuente para el cliente o el sistema no tiene componentes de aceite;
    con fuente, una ventana sin muestras queda como `muestras: []` (el informe lo dice).
    """
    fecha, desde = pd.Timestamp(fecha).normalize(), pd.Timestamp(desde).normalize()
    base = {"sistema": sistema, "ventana_desde": desde.date().isoformat(),
            "ventana_hasta": (fecha - pd.Timedelta(days=1)).date().isoformat()}
    componentes = COMPONENTES_ACEITE.get(sistema)
    if not componentes:
        return {"disponible": False, "motivo": "sistema_sin_componentes", **base}
    try:
        tabla = _cargar(cliente)
    except Exception as exc:   # una fuente ilegible no debe tumbar el informe
        logger.warning(f"Aceite {cliente}: no se pudieron leer las muestras ({type(exc).__name__}: {exc})")
        return {"disponible": False, "motivo": "error_de_lectura", **base}
    if tabla.empty:
        return {"disponible": False, "motivo": "sin_fuente", **base}

    propias = tabla[(tabla["unidad_key"] == unit_key(unidad)) & tabla["componente_norm"].isin(componentes)
                    & (tabla["dia"] >= desde) & (tabla["dia"] < fecha)].sort_values("dia")
    # Por componente: con dos motores (delantero y trasero) las muestras se intercalan.
    horometro = propias["oilMeter"] if "oilMeter" in propias.columns else pd.Series(index=propias.index, dtype=float)
    cambio = horometro < horometro.groupby(propias["componente"]).shift()
    nombres = _nombres_ensayo(cliente)
    muestras = [{
        "fecha": fila["dia"].date().isoformat(),
        "componente": fila["componente"],
        "dias_antes": int((fecha - fila["dia"]).days),
        "horas_motor": _horas(fila.get("componentHours")),
        "horas_aceite": _horas(fila.get("oilMeter")),
        "cambio_de_aceite": bool(cambio.get(i, False)),
        "resultado": _texto(fila.get("report_status")),
        "fuera_de_limite": {nombres.get(e, e): n for e, n in niveles_fuera(fila.get("breached_essays")).items()},
        "tipo_anomalia": _texto(fila.get("anomalyType")),
        "recomendacion": sin_concentraciones(fila.get("ai_recommendation")),
    } for i, fila in propias.iterrows()]
    return {"disponible": True, **base, "componentes": sorted(propias["componente"].unique().tolist()),
            "muestras": muestras}


# =============================================================================
# Observaciones del laboratorio: diagnostico y causa probable de la seccion Aceite
# =============================================================================
ESQUEMA_OBSERVACIONES = secciones.esquema_diagnostico_causa("aceite_diagnostico_causa")
_DIAGNOSTICO = re.compile(r"Diagn[oó]stico:\s*(.+?)(?=\s*Acci[oó]n:|$)", re.IGNORECASE | re.DOTALL)
_ACCION = re.compile(r"Acci[oó]n:\s*(.+)", re.IGNORECASE | re.DOTALL)


def partes_recomendacion(texto: str) -> tuple:
    """(diagnostico, accion) del texto del laboratorio; una muestra normal no trae las etiquetas."""
    diag, acc = _DIAGNOSTICO.search(texto or ""), _ACCION.search(texto or "")
    if not diag and not acc:
        return (texto or "").strip(), ""
    return (diag.group(1).strip() if diag else ""), (acc.group(1).strip() if acc else "")


def modos_destacados(evid: dict, cliente: str, sistema: str = c.COMPONENTE) -> List[dict]:
    """Los modos alto/medio del monitoreo de riesgo con sus ensayos de aceite (para relacionar las condiciones)."""
    nombres = _nombres_ensayo(cliente)
    salida = []
    for r in evid.get("ranking_modos", []):
        if r["nivel"] not in ("alto", "medio"):
            continue
        try:
            ensayos = predictive_catalog.get_oil_variables_for_mode(r["modo"], sistema, (cliente or "").lower())
        except Exception:
            ensayos = []
        salida.append({"modo": c.NOMBRE_MODO.get(r["modo"], r["modo"]), "nivel": r["nivel"],
                       "ensayos_aceite": [nombres.get(e, e) for e in ensayos]})
    return salida


def entrada_observaciones(evid: dict, cliente: str, perfil: dict) -> dict:
    """Lo que recibe la IA: sin concentraciones (ya quitadas en muestras_aceite), con el diagnostico y la accion
    del laboratorio separados, los cambios de aceite y de motor inferidos de los horometros y el asentamiento."""
    a = evid["aceite"]
    muestras, horas_previas = [], {}
    for m in a["muestras"]:
        diagnostico, accion = partes_recomendacion(m["recomendacion"])
        anterior = horas_previas.get(m["componente"])
        horas_previas[m["componente"]] = m["horas_motor"]
        muestras.append({
            "fecha": m["fecha"], "componente": m["componente"], "horas_motor": m["horas_motor"],
            "horas_aceite": m["horas_aceite"], "horometro_aceite_reinicia_desde_la_anterior": m["cambio_de_aceite"],
            "horas_motor_reinician_desde_la_anterior": bool(anterior is not None and m["horas_motor"] is not None
                                                           and m["horas_motor"] < anterior),
            "motor_en_asentamiento": m["horas_motor"] is not None and m["horas_motor"] <= RODAJE_HORAS_MOTOR,
            "resultado": m["resultado"], "ensayos_fuera_de_limite": m["fuera_de_limite"],
            "tipo_de_anomalia": m["tipo_anomalia"], "diagnostico_laboratorio": diagnostico,
            "accion_laboratorio": accion,
        })
    return {
        "sistema": a["sistema"], "equipo": perfil["equipo"], "fecha_detencion": evid["consulta"]["fecha"],
        "ventana": {"desde": a["ventana_desde"], "hasta": a["ventana_hasta"]},
        "modos_destacados": modos_destacados(evid, cliente, a["sistema"]),
        "muestras": muestras,
    }


def prompt_observaciones(perfil: dict, sistema: str) -> str:
    return f"""Eres un ingeniero de confiabilidad. Recibes las muestras de aceite del {sistema} de una unidad
({perfil["equipo"]}) tomadas en los 3 meses previos a una detención. Cada muestra trae su resultado, los ensayos que
salieron de límite con su nivel (marginal o crítico), el diagnóstico y la acción que escribió el laboratorio, si el
horómetro del aceite o las horas del motor volvieron a partir desde la muestra anterior y si el motor estaba en
asentamiento. También recibes los modos de falla que el monitoreo de riesgo destacó antes de la detención.

Escribe dos mensajes para la sección Aceite de un informe preliminar de falla dirigido al cliente, con el mismo
formato que el resto del informe:
- diagnostico: agrupa los diagnósticos del laboratorio del período en la condición o las dos condiciones más
  relevantes: cuál, su nivel más alto y desde cuándo. Primero lo que se relaciona con los modos destacados. No repitas
  muestra por muestra.
- causa_probable: un análisis de los antecedentes de aceite, no una repetición del diagnóstico. Mira cómo evolucionó la
  condición: si persistió o volvió después de un cambio de aceite, si apareció después de un cambio de motor, si se
  concentró en pocas semanas. Di qué origen se vuelve más probable y con qué modo destacado concuerda. Es probable,
  nunca confirmado.
{secciones.formato_seccion()}

Reglas:
- Motor en asentamiento (motor_en_asentamiento: menos de {RODAJE_HORAS_MOTOR} horas, motor nuevo o recién
  reparado): es esperable que el aceite muestre cobre alto. Si el cobre alto se da solo en asentamiento, no abras el
  diagnóstico con él: va al final, en una cláusula de no más de 8 palabras (por ejemplo "el cobre alto corresponde
  al asentamiento del motor nuevo"), y no aparece en la causa probable. Solo dale peso si sigue alto cuando el motor
  ya pasó el asentamiento o si viene con otros metales de desgaste en nivel crítico.
- Relaciona una condición con un modo destacado solo si alguno de sus ensayos está en ensayos_aceite de ese modo.
- No escribas concentraciones ni valores de los ensayos (nada de ppm, %, cSt). Usa niveles (normal, marginal,
  crítico) y fechas como "29 oct".
- Los cambios no están registrados, se infieren de los horómetros: escribe "el horómetro del aceite indica un cambio
  de aceite" o "las horas del motor vuelven a cero, lo que indica un cambio de motor".
- Usa solo lo que está en los datos: no inventes causas, componentes ni acciones que el laboratorio no mencione.
- Al sistema que destaca los modos llámalo "el monitoreo de riesgo".
- Si todas las muestras fueron normales: diagnóstico "Las muestras de aceite del período no mostraron condiciones
  fuera de lo normal." y causa probable "El aceite no orienta la causa de la detención."
{secciones.lineamientos(perfil)}
Devuelve SOLO JSON con la estructura pedida."""


def observaciones_sin_ia(muestras: List[dict]) -> dict:
    """Sin IA: las muestras fuera de lo normal agrupadas por el tipo de anomalia del laboratorio."""
    alteradas = [m for m in muestras if m["resultado"] and m["resultado"] != "Normal"]
    if not alteradas:
        return {"diagnostico": "Las muestras de aceite del período no mostraron condiciones fuera de lo normal.",
                "causa_probable": "El aceite no orienta la causa de la detención."}
    grupos: dict = {}
    for m in alteradas:
        grupos.setdefault(m["tipo_anomalia"] or "Sin clasificar", []).append(m)
    tipos = sorted(grupos.items(), key=lambda g: -len(g[1]))
    diagnostico = (f"{len(alteradas)} de {len(muestras)} muestras con resultado fuera de lo normal: "
                   + "; ".join(f"{t} ({len(g)}, desde el {_fecha_corta(g[0]['fecha'])})" for t, g in tipos[:3]) + ".")
    return {"diagnostico": diagnostico,
            "causa_probable": "No se pudo resumir la causa a partir de las recomendaciones del laboratorio."}


def observaciones_laboratorio(evid: dict, cliente: str, perfil: dict, llm_fn: Optional[LlmFn]) -> Optional[dict]:
    """Diagnostico y causa probable de la seccion Aceite, o None si no hay muestras.

    Con la IA cuando se puede; si la llamada falla, la respuesta no cumple el formato o trae valores de
    ensayos, el resumen sin IA. Lo demas que marquen los controles (largo, vocabulario) se acepta con aviso.
    """
    muestras = (evid.get("aceite") or {}).get("muestras") or []
    if not muestras:
        return None
    if llm_fn is not None:
        try:
            obs = secciones.pedir(llm_fn, prompt_observaciones(perfil, evid["aceite"]["sistema"]),
                                  entrada_observaciones(evid, cliente, perfil), ESQUEMA_OBSERVACIONES)
            controles = secciones.controles_diagnostico_causa(obs)
            if not any(p.startswith("valor") for p in controles):
                return {"origen": "ia", "diagnostico": obs["diagnostico"].strip(),
                        "causa_probable": obs["causa_probable"].strip(), "controles": controles}
            logger.warning(f"Observaciones del laboratorio {cliente}: respuesta descartada ({controles})")
        except Exception as exc:
            logger.warning(f"Observaciones del laboratorio {cliente}: sin IA ({type(exc).__name__}: {exc})")
    return {"origen": "sin_ia", **observaciones_sin_ia(muestras), "controles": []}
