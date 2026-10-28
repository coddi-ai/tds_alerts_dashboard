"""
Informe preliminar de falla: intervenciones de mantencion previas de la unidad (sin IA).

Para una unidad, un sistema y la fecha de la detencion, junta los registros de mantencion
(una OT = un `record_id` de query_3) ESTRICTAMENTE ANTERIORES a la fecha, en dos ventanas:
- la del Predictivo (13 semanas) para la tabla y la linea de tiempo;
- una extendida (180 dias) para los antecedentes agregados: ultimo PM, recurrencia por
  subsistema y ultima intervencion en el subsistema de cada modo destacado.

Nunca lanza por falta de datos: lo declara en `cobertura_mantenciones.estado`. La ausencia
de registros solo se lee como "sin intervenciones" cuando la cobertura es completa.

Reglas (documentation/reporting/plan_detenciones_previas_informe.md y
documentation/mantentions/VISTAS_MANTENCIONES.md):
- fecha: `change_date` (dia calendario); nada del dia de la detencion ni posterior, y un
  record que sigue abierto en la fecha se excluye (puede ser la detencion misma);
- texto: solo `action_detail_clean`, recortado. De `record_original_text` se extrae con
  codigo unicamente el rotulo de la categoria (Capstone); el resto no se lee ni viaja;
- horas: `query_7.intervention_hours` de la unidad el dia de inicio del record (hora del
  equipo-dia, no del record);
- modos relacionados: por subsistema y por componente, con la tabla del catalogo marcada
  como propuesta sin validar.

Uso: antecedentes_mantencion("CAPSTONE", "CA-30", "2025-09-30", modos=["combustion_risk"])
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, timedelta
from typing import Iterable, List, Optional

import numpy as np
import pandas as pd

from src.data.loaders import load_maintenance_actions_all_equipment, load_maintenance_intervention_hours_daily
from src.data.report_health import unit_key
from src.informe_falla import catalog as c
from src.informe_falla.config import get_informe_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

SEMANAS_VENTANA = c.SEMANAS_ATRAS      # la misma ventana del Predictivo
DIAS_EXTENDIDO = 180                   # antecedentes agregados
DIAS_CERCA = 2                         # registros de los dias previos: posiblemente la misma detencion
MAX_FILAS_TABLA = 8
MAX_PUNTOS_LINEA = 4                   # correctivas recientes + el ultimo PM
MAX_DETALLE = 220

TIPO_CORRECTIVA, TIPO_PROGRAMADA, TIPO_SIN_CLASIFICAR = "Correctiva", "Programada", "Sin clasificar"

# Capstone: "Categoria: Mant. No Programada | Razon: ... | Comentario: ...". Solo el rotulo.
_CATEGORIA_RE = re.compile(r"^\s*Categor[ií]a:\s*([^|]+)", re.IGNORECASE)
# CDA (sin categoria estructurada): pistas del texto limpio.
_PROGRAMADA_RE = re.compile(
    r"\b(?:pre-?pm|pm\d*|pauta|mantenci[oó]n(?:es)? (?:programad|preventiv)|mantenimiento (?:programad|preventiv)"
    r"|preventiv[oa]|seg[uú]n programa|(?:cambio|reemplazo) de (?:los )?filtros?|toma de muestra)", re.IGNORECASE)
_CORRECTIVA_RE = re.compile(
    r"\b(?:falla|fuera de servicio|alarma|advertencia|c[oó]digo|fuga|filtraci[oó]n|da[ñn]ad|roto|rotura|cortad"
    r"|baja potencia|bajo nivel|ruido|humo|sobrecalent|reparaci[oó]n|repar[aó]|no programad|mnp\b|correctiv)",
    re.IGNORECASE)
# Registros que no dicen que se hizo.
_SIN_CONTENIDO_RE = re.compile(r"no especifica (?:la )?operaci[oó]n|no se informa (?:la|el) (?:operaci|trabajo)"
                               r"|sin detalle", re.IGNORECASE)
# Trabajo que quedo abierto.
_SIN_CIERRE_RE = re.compile(r"pendiente|queda en observaci[oó]n|sin soluci[oó]n|no se logr[oó]|se deriva",
                            re.IGNORECASE)


# =============================================================================
# Carga (con cache por cliente, como el historial del Predictivo)
# =============================================================================
_CACHE: dict = {}
_LOCK = threading.Lock()


def _cargar(cliente: str):
    """(acciones query_3, horas query_7) del cliente; DataFrames vacios si no hay vistas."""
    cliente = (cliente or "").lower()
    with _LOCK:
        guardado = _CACHE.get(cliente)
        if guardado and time.time() - guardado[0] < get_informe_settings().data_cache_seconds:
            return guardado[1], guardado[2]
        acciones = _preparar_acciones(load_maintenance_actions_all_equipment(cliente))
        horas = _preparar_horas(load_maintenance_intervention_hours_daily(cliente))
        _CACHE[cliente] = (time.time(), acciones, horas)
        return acciones, horas


def _dia(serie: pd.Series) -> pd.Series:
    """Dia calendario de una columna de fechas (el loader las deja en UTC a las 00:00 o naive)."""
    fechas = pd.to_datetime(serie, errors="coerce")
    if getattr(fechas.dt, "tz", None) is not None:
        fechas = fechas.dt.tz_localize(None)
    return fechas.dt.normalize()


def _preparar_acciones(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "record_id" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["dia"] = _dia(df["change_date"])
    df["unidad_key"] = df["machine_code"].map(unit_key)
    df["sistema"] = df["action_system_name"].fillna("").str.strip().str.lower()
    df["categoria"] = (df["record_original_text"].fillna("").str.extract(_CATEGORIA_RE)[0].str.strip()
                       if "record_original_text" in df.columns else None)
    # record_original_text no se usa mas alla del rotulo: se descarta aqui.
    df = df.drop(columns=[col for col in ("record_original_text", "action_detail_raw") if col in df.columns])
    df["componentes"] = df["component_names"].apply(
        lambda x: [str(v) for v in x] if isinstance(x, (list, tuple, np.ndarray)) else [])
    return df.dropna(subset=["dia"])


def _preparar_horas(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "day" not in df.columns:
        return pd.DataFrame(columns=["unidad_key", "dia", "intervention_hours"])
    df = df.copy()
    df["dia"] = _dia(df["day"])
    df["unidad_key"] = df["machine_code"].map(unit_key)
    return df[["unidad_key", "dia", "intervention_hours"]]


# =============================================================================
# Records
# =============================================================================
def _recortar(texto: str) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= MAX_DETALLE else texto[:MAX_DETALLE - 1].rstrip() + "…"


def _tipo(categorias: Iterable, textos: Iterable[str]) -> str:
    rotulo = next((str(x) for x in categorias if isinstance(x, str) and x), "")
    if rotulo:
        return TIPO_PROGRAMADA if re.search(r"\bprogramada\b", rotulo, re.IGNORECASE) and \
            not re.search(r"\bno programada\b", rotulo, re.IGNORECASE) else TIPO_CORRECTIVA
    texto = " ".join(textos)
    if _CORRECTIVA_RE.search(texto):
        return TIPO_CORRECTIVA
    if _PROGRAMADA_RE.search(texto):
        return TIPO_PROGRAMADA
    return TIPO_SIN_CLASIFICAR


def _fluido(fila) -> str:
    texto = (fila["action_detail_clean"] or "").lower() + " " + " ".join(fila["componentes"]).lower()
    if "refrigerante" in texto or "agua" in texto:
        return "refrigerante"
    if "aceite" in texto:      # incluye los rellenos rotulados "Bomba de Aceite de Motor" (son aceite)
        return "aceite"
    return "otro"


def _modos_relacionados(cliente: str, subsistemas: List[str], componentes: List[str]) -> list:
    relacionados = []
    tabla = c.SUBSISTEMAS_POR_MODO.get((cliente or "").upper(), {})
    for modo, subs in tabla.items():
        if set(subs) & set(subsistemas):
            relacionados.append({"modo": modo, "por": "subsistema"})
    texto = " ".join(componentes).lower()
    for modo, claves in c.COMPONENTES_CLAVE_POR_MODO.items():
        if any(k in texto for k in claves) and not any(r["modo"] == modo for r in relacionados):
            relacionados.append({"modo": modo, "por": "componente"})
    return relacionados


def _records(acciones: pd.DataFrame, cliente: str, horas: pd.DataFrame, fecha: pd.Timestamp) -> tuple:
    """(records del sistema, rellenos). Un record por OT, con sus acciones del sistema."""
    horas_dia = {(k, d): h for k, d, h in horas[["unidad_key", "dia", "intervention_hours"]].itertuples(index=False)}
    records, rellenos = [], []
    for record_id, g in acciones.groupby("record_id", sort=False):
        inicio, fin = g["dia"].min(), g["dia"].max()
        no_relleno = g[g["action_type_name"] != "Relleno"]
        for _, fila in g[g["action_type_name"] == "Relleno"].iterrows():
            rellenos.append({"fecha": fila["dia"], "fluido": _fluido(fila)})
        if no_relleno.empty:
            continue
        textos = [t for t in no_relleno["action_detail_clean"].fillna("") if t]
        subsistemas = sorted({s for s in no_relleno["action_subsystem_name"].dropna() if s})
        componentes = sorted({x for lista in no_relleno["componentes"] for x in lista})
        records.append({
            "record_id": str(record_id),
            "inicio": inicio, "fin": fin,
            "tipo": _tipo(g["categoria"].dropna() if "categoria" in g else [], textos),
            "subsistemas": subsistemas,
            "componentes": componentes,
            "descripcion": _recortar(" ".join(dict.fromkeys(textos))),
            "sin_cierre": any(_SIN_CIERRE_RE.search(t) for t in textos),
            "horas_dia": horas_dia.get((g["unidad_key"].iloc[0], inicio)),
            "modos_relacionados": _modos_relacionados(cliente, subsistemas, componentes),
            # No dice que se hizo: no va a la tabla, solo se cuenta.
            "sin_contenido": not textos or all(_SIN_CONTENIDO_RE.search(t) for t in textos),
        })
    return records, rellenos


def _publico(r: dict, fecha: pd.Timestamp) -> dict:
    """Lo que va a la evidencia (y lo que lee la plantilla): fechas ISO, nada de numpy."""
    dias = int((fecha - r["inicio"]).days)
    return {
        "fecha": r["inicio"].date().isoformat(),
        "fin": r["fin"].date().isoformat(),
        "dias_antes": dias,
        "tipo": r["tipo"],
        "subsistema": ", ".join(r["subsistemas"]),
        "componentes": ", ".join(r["componentes"]),
        "descripcion": r["descripcion"],
        "horas_dia": round(float(r["horas_dia"]), 1) if r["horas_dia"] is not None and not pd.isna(r["horas_dia"]) else None,
        "sin_cierre": bool(r["sin_cierre"]),
        "modos_relacionados": r["modos_relacionados"],
        "cerca_de_la_detencion": dias <= DIAS_CERCA,
        "fuente": f"query_3:record={r['record_id']}",
    }


# =============================================================================
# Antecedentes
# =============================================================================
def _cobertura(acciones: pd.DataFrame, presente: bool, desde: pd.Timestamp, hasta: pd.Timestamp,
               cliente: str) -> dict:
    tabla = bool(c.SUBSISTEMAS_POR_MODO.get((cliente or "").upper()))
    base = {"ventana_desde": desde.date().isoformat(), "ventana_hasta": hasta.date().isoformat(),
            "equivalencia": c.EQUIVALENCIA_SIN_VALIDAR if tabla else "sin tabla de equivalencias para el cliente",
            "clasificacion": "estructurada" if acciones.get("categoria") is not None
            and acciones["categoria"].notna().any() else "inferida del texto"}
    if acciones.empty:
        return {"estado": "sin_fuente", **base}
    datos_desde, datos_hasta = acciones["dia"].min(), acciones["dia"].max()
    base.update(datos_desde=datos_desde.date().isoformat(), datos_hasta=datos_hasta.date().isoformat())
    if not presente:
        return {"estado": "unidad_sin_registros", **base}
    if desde > datos_hasta or hasta < datos_desde:
        return {"estado": "fuera_de_cobertura", **base}
    if desde < datos_desde or hasta > datos_hasta:
        return {"estado": "parcial", **base}
    return {"estado": "completa", **base}


def cobertura(cliente: str, unidad: str, fecha, semanas: int = SEMANAS_VENTANA) -> dict:
    """Solo el estado de cobertura de las mantenciones (para el validador de la vista; no bloquea)."""
    fecha = pd.Timestamp(fecha).normalize()
    try:
        acciones, _ = _cargar(cliente)
    except Exception:
        acciones = pd.DataFrame()
    presente = not acciones.empty and (acciones["unidad_key"] == unit_key(unidad)).any()
    return _cobertura(acciones, presente, fecha - pd.Timedelta(weeks=semanas), fecha - pd.Timedelta(days=1), cliente)


def _orden_tabla(r: dict) -> tuple:
    return (r["tipo"] != TIPO_CORRECTIVA, -r["inicio"].value)


def antecedentes_mantencion(cliente: str, unidad: str, fecha, sistema: str = c.COMPONENTE,
                            modos: Optional[List[str]] = None, semanas: int = SEMANAS_VENTANA,
                            dias_extendido: int = DIAS_EXTENDIDO) -> dict:
    """Las tres claves de la evidencia: cobertura_mantenciones, detenciones_previas, antecedentes_mantencion.

    `detenciones_previas` es None cuando no se puede afirmar nada (sin fuente, unidad sin registros o fuera
    de cobertura). `modos`: modos destacados del Predictivo, para la ultima intervencion en su subsistema.
    """
    fecha = pd.Timestamp(fecha).normalize()
    desde, hasta = fecha - pd.Timedelta(weeks=semanas), fecha - pd.Timedelta(days=1)
    desde_ext = fecha - pd.Timedelta(days=dias_extendido)
    try:
        acciones, horas = _cargar(cliente)
    except Exception as exc:   # una vista ilegible no debe tumbar el informe
        logger.warning(f"Mantenciones {cliente}: no se pudieron leer las vistas ({type(exc).__name__}: {exc})")
        acciones, horas = pd.DataFrame(), pd.DataFrame(columns=["unidad_key", "dia", "intervention_hours"])

    clave = unit_key(unidad)
    propias = acciones[acciones["unidad_key"] == clave] if not acciones.empty else acciones
    cobertura = _cobertura(acciones, not propias.empty, desde, hasta, cliente)
    if cobertura["estado"] in ("sin_fuente", "unidad_sin_registros", "fuera_de_cobertura"):
        return {"cobertura_mantenciones": cobertura, "detenciones_previas": None, "antecedentes_mantencion": None}

    sistemas = c.SISTEMAS_MANTENCION.get(sistema, {sistema})
    otros_sistemas = propias[~propias["sistema"].isin(sistemas)]
    del_sistema = propias[propias["sistema"].isin(sistemas)]
    # Subsistemas agrupados en el sistema que no son de el (la cabina en el motor): fuera de la tabla, la linea de
    # tiempo, los antecedentes y la IA. Un record con otros subsistemas se queda, sin esas acciones.
    fuera = c.SUBSISTEMAS_FUERA_DEL_SISTEMA.get(sistema, set())
    es_fuera = del_sistema["action_subsystem_name"].fillna("").str.strip().str.lower().isin(fuera)
    en_ventana = (del_sistema["dia"] >= desde) & (del_sistema["dia"] < fecha)
    fuera_del_sistema = (set(del_sistema.loc[es_fuera & en_ventana, "record_id"])
                         - set(del_sistema.loc[~es_fuera & en_ventana, "record_id"]))
    del_sistema = del_sistema[~es_fuera]
    records, rellenos = _records(del_sistema, cliente, horas, fecha)

    # Sin fugas: solo records cerrados antes de la fecha (un record abierto en la fecha puede ser la detencion).
    cerrados = [r for r in records if r["fin"] < fecha]
    sin_contenido = sum(1 for r in cerrados if r["sin_contenido"] and r["inicio"] >= desde)
    previos = [r for r in cerrados if not r["sin_contenido"]]
    en_ventana = [r for r in previos if r["inicio"] >= desde]
    extendidos = [r for r in previos if r["inicio"] >= desde_ext]
    rellenos_ventana = [x for x in rellenos if desde <= x["fecha"] < fecha]

    programadas = sorted((r for r in extendidos if r["tipo"] == TIPO_PROGRAMADA), key=lambda r: r["inicio"])
    ultimo_pm = programadas[-1] if programadas else None
    tabla = sorted(en_ventana, key=_orden_tabla)
    en_linea = sorted((r for r in en_ventana if r["tipo"] == TIPO_CORRECTIVA), key=lambda r: -r["inicio"].value)
    en_linea = en_linea[:MAX_PUNTOS_LINEA - (1 if ultimo_pm is not None and ultimo_pm["inicio"] >= desde else 0)]

    recurrencia = {}
    for r in extendidos:
        if r["tipo"] == TIPO_CORRECTIVA:
            for s in r["subsistemas"]:
                recurrencia.setdefault(s, []).append(r["inicio"].date().isoformat())
    tabla_modos = c.SUBSISTEMAS_POR_MODO.get((cliente or "").upper(), {})
    ultima_modo = []
    for modo in modos or []:
        subs = set(tabla_modos.get(modo, []))
        candidatos = [r for r in extendidos if subs & set(r["subsistemas"])]
        if candidatos:
            ultimo = max(candidatos, key=lambda r: r["inicio"])
            ultima_modo.append({"modo": modo, "fecha": ultimo["inicio"].date().isoformat(),
                                "dias_antes": int((fecha - ultimo["inicio"]).days), "tipo": ultimo["tipo"],
                                "subsistema": ", ".join(ultimo["subsistemas"])})

    publicos = [_publico(r, fecha) for r in tabla]
    fechas_linea = {r["inicio"].date().isoformat() for r in en_linea}
    for p in publicos:
        p["en_linea_de_tiempo"] = p["fecha"] in fechas_linea and p["tipo"] == TIPO_CORRECTIVA
    antecedentes = {
        "ultimo_pm": ({"fecha": ultimo_pm["inicio"].date().isoformat(),
                       "dias_antes": int((fecha - ultimo_pm["inicio"]).days)} if ultimo_pm else None),
        "ultima_intervencion_por_modo": ultima_modo,
        "recurrencia": [{"subsistema": s, "correctivas": len(f), "fechas": sorted(f)}
                        for s, f in sorted(recurrencia.items()) if len(f) >= 2],
        "rellenos": {fluido: {"n": len(fs), "fechas": sorted({x["fecha"].date().isoformat() for x in fs})}
                     for fluido in ("aceite", "refrigerante", "otro")
                     for fs in [[x for x in rellenos_ventana if x["fluido"] == fluido]]},
        "omitidos": {
            "rellenos": len(rellenos_ventana),
            "sin_contenido": sin_contenido,
            "otros_sistemas": int(otros_sistemas[(otros_sistemas["dia"] >= desde) & (otros_sistemas["dia"] < fecha)]
                                  ["record_id"].nunique()),
            "fuera_del_sistema": len(fuera_del_sistema),
            "fuera_del_tope": max(0, len(publicos) - MAX_FILAS_TABLA),
            "abiertos_en_la_fecha": sum(1 for r in records if r["inicio"] < fecha <= r["fin"]),
        },
        "ventana_extendida_dias": dias_extendido,
    }
    return {"cobertura_mantenciones": cobertura, "detenciones_previas": publicos[:MAX_FILAS_TABLA],
            "antecedentes_mantencion": antecedentes}
