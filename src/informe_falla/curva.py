"""
Informe preliminar de falla: estado del ciclo de vida del motor, desde la curva acumulada (sin IA).

Tabla `cumulative_risk_curve` (predictive_data_contracts.md, seccion Cumulative Risk Curve):
- cada particion trae la HISTORIA COMPLETA recalculada en esa corrida, y su configuracion de zonas
  (`config`, `banda`) viaja en los metadatos del parquet, que pd.read_parquet descarta. Por eso se
  lee una sola particion con pyarrow y se recuperan los metadatos;
- sin fugas: se usa la ultima particion de una semana ANTERIOR a la de la detencion y solo filas
  con fecha anterior a la detencion. El ciclo es el vigente a esa fecha (el ciclo cambia cuando se
  reemplaza el motor, asi que la curva posterior a la falla queda fuera);
- `estado` nunca es nulo, pero bajo HORAS_MIN_CURVA (`evaluable = False`) "Normal" significa "aun no
  se evalua", no "sano".

Zonas del grafico: bajo el limite de alerta, Normal; entre alerta y umbral, Alerta; sobre el umbral,
Anormal. El contrato publica `banda_media` (mediana de la flota) y `banda_umbral`; el limite de alerta
se deriva como media + K_ALERTA / K_SIGMA x (umbral - media), con K de `config`. SUPUESTO: que
banda_umbral = media + K_SIGMA x sigma, igual que en el grafico del dashboard. Confirmar con el equipo
del Predictivo.

Uso:
    tabla, meta = cargar("CAPSTONE", "2026-03-08")      # del origen configurado (fuentes.py)
    bloque = ciclo_vida(tabla, meta, "CA-60", "2026-03-08")    # -> evid["ciclo_vida"]
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from src.data.report_health import unit_key
from src.informe_falla import catalog as c
from src.informe_falla import fuentes
from src.informe_falla.config import get_informe_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

TABLA = "cumulative_risk_curve"
COLUMNAS = ["Unit", "Fecha", "ciclo", "curva", "componentHours_filled", "ranking_acumulado_ajustado",
            "banda_media", "banda_umbral", "estado", "evaluable"]
ZONAS_NO_NORMALES = ("Alerta", "Anormal")
PUNTOS_BANDA = 80

_CACHE: dict = {}
_LOCK = threading.Lock()


def _elegir_particion(particiones: list, fecha: pd.Timestamp):
    """La ultima de una semana anterior a la de la detencion; si no hay, la mas antigua (y se marca)."""
    lunes_det = (fecha - pd.Timedelta(days=fecha.weekday())).date()
    anteriores = [p for p in particiones if date.fromisocalendar(p[0], p[1], 1) < lunes_det]
    if anteriores:
        return anteriores[-1], False
    return (particiones[0], True) if particiones else (None, False)


def cargar(cliente: str, fecha):
    """(tabla, meta) de la particion que corresponde a la fecha. Tabla vacia si no hay curva."""
    fecha = pd.Timestamp(fecha).normalize()
    eleccion, posterior = _elegir_particion(fuentes.particiones(cliente, TABLA), fecha)
    if eleccion is None:
        return pd.DataFrame(columns=COLUMNAS), {"disponible": False}
    year, week, archivo = eleccion
    clave = (cliente.lower(), fuentes.origen(), str(archivo))
    with _LOCK:
        guardado = _CACHE.get(clave)
        if guardado and time.time() - guardado[0] < get_informe_settings().data_cache_seconds:
            return guardado[1], guardado[2]
        try:
            tabla_pa = fuentes.leer_archivo(archivo)
        except Exception as exc:
            logger.warning(f"{TABLA} {cliente}: no se pudo leer {archivo} ({type(exc).__name__}: {exc})")
            return pd.DataFrame(columns=COLUMNAS), {"disponible": False}
        meta = {"disponible": True, "particion": f"{year}-W{week:02d}", "particion_posterior": posterior}
        for k, v in (tabla_pa.schema.metadata or {}).items():
            if k.decode() in ("config", "banda"):
                try:
                    meta[k.decode()] = json.loads(v.decode())
                except ValueError:
                    pass
        df = tabla_pa.to_pandas().reindex(columns=COLUMNAS)
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce").dt.normalize()
        df["unidad_key"] = df["Unit"].map(unit_key)
        _CACHE[clave] = (time.time(), df, meta)
        return df, meta


def _muestrear(filas: pd.DataFrame, n: int) -> list:
    """[[horas, riesgo acumulado]] con a lo mas n puntos, incluido el ultimo."""
    filas = filas.dropna(subset=["componentHours_filled", "ranking_acumulado_ajustado"])
    if filas.empty:
        return []
    idx = np.unique(np.linspace(0, len(filas) - 1, min(n, len(filas))).round().astype(int))
    sub = filas.iloc[idx]
    return [[round(float(h), 1), round(float(v), 1)]
            for h, v in zip(sub["componentHours_filled"], sub["ranking_acumulado_ajustado"])]


def _ciclo_a_la_fecha(filas: pd.DataFrame) -> pd.DataFrame:
    filas = filas.sort_values("Fecha")
    return filas[filas["ciclo"] == filas["ciclo"].iloc[-1]] if "ciclo" in filas and filas["ciclo"].notna().any() else filas


def _banda(previas: pd.DataFrame, horas_max: float, k_alerta: float, k_sigma: float) -> list:
    """[[horas, media, alerta, umbral]]: mediana por tramo de horas de los valores de la flota."""
    b = previas.dropna(subset=["componentHours_filled", "banda_media", "banda_umbral"])
    b = b[b["componentHours_filled"] <= horas_max]
    if b.empty:
        return []
    tramos = pd.cut(b["componentHours_filled"], bins=PUNTOS_BANDA)
    g = b.groupby(tramos, observed=True)[["componentHours_filled", "banda_media", "banda_umbral"]].median().dropna()
    factor = k_alerta / k_sigma if k_sigma else 0.5
    return [[round(float(h), 1), round(float(m), 1), round(float(m + factor * (u - m)), 1), round(float(u), 1)]
            for h, m, u in zip(g["componentHours_filled"], g["banda_media"], g["banda_umbral"])]


def ciclo_vida(tabla: pd.DataFrame, meta: dict, unidad: str, fecha) -> dict:
    """Bloque del informe: la curva de la unidad, la banda y la flota de contexto, y sus datos clave."""
    fecha = pd.Timestamp(fecha).normalize()
    if tabla is None or tabla.empty or not meta.get("disponible"):
        return {"disponible": False, "motivo": "sin_tabla"}
    previas = tabla[tabla["Fecha"] < fecha]
    propias = previas[previas["unidad_key"] == unit_key(unidad)]
    if propias.empty:
        return {"disponible": False, "motivo": "unidad_sin_curva", "particion": meta.get("particion")}

    curva = _ciclo_a_la_fecha(propias)
    ultima = curva.iloc[-1]
    evaluable = bool(ultima["evaluable"]) if pd.notna(ultima["evaluable"]) else \
        float(ultima["componentHours_filled"] or 0) >= c.HORAS_MIN_CURVA
    estado = str(ultima["estado"]) if pd.notna(ultima["estado"]) else "Normal"
    # Desde cuando esta fuera de Normal (el tramo final continuo)
    desde = None
    if evaluable and estado in ZONAS_NO_NORMALES:
        for _, fila in curva.iloc[::-1].iterrows():
            if str(fila["estado"]) not in ZONAS_NO_NORMALES:
                break
            desde = fila["Fecha"]

    otras = []
    resumen = {"total": 0, "alerta_o_anormal": 0}
    for clave, filas in previas[previas["unidad_key"] != unit_key(unidad)].groupby("unidad_key"):
        ciclo = _ciclo_a_la_fecha(filas)
        fin = ciclo.iloc[-1]
        resumen["total"] += 1
        if bool(fin["evaluable"]) and str(fin["estado"]) in ZONAS_NO_NORMALES:
            resumen["alerta_o_anormal"] += 1
        otras.append(_muestrear(ciclo, c.MAX_PUNTOS_CURVA))
    resumen["total"] += 1                    # la unidad analizada cuenta en la flota
    if evaluable and estado in ZONAS_NO_NORMALES:
        resumen["alerta_o_anormal"] += 1
    paso = max(1, len(otras) // c.MAX_CURVAS_FLOTA)
    flota = [o for o in otras[::paso] if o][:c.MAX_CURVAS_FLOTA]

    puntos = _muestrear(curva, c.MAX_PUNTOS_CURVA * 2)
    horas_max = max([p[0] for o in flota for p in o] + [p[0] for p in puntos] + [1.0])
    config = meta.get("config") or {}
    return {
        "disponible": True,
        "particion": meta.get("particion"),
        "particion_posterior": bool(meta.get("particion_posterior")),   # sin particion previa: puede incluir datos posteriores
        "curva": str(ultima["curva"]) if pd.notna(ultima["curva"]) else None,
        "estado_final": estado,
        "evaluable": evaluable,
        "fuera_de_normal_desde": desde.date().isoformat() if desde is not None else None,
        "horas_motor": round(float(ultima["componentHours_filled"]), 0) if pd.notna(ultima["componentHours_filled"]) else None,
        "fecha_ultimo_dato": ultima["Fecha"].date().isoformat(),
        "flota_resumen": resumen,
        # Solo para el grafico (no van a la IA):
        "puntos": puntos,
        "banda": _banda(previas, horas_max * 1.02, float(config.get("K_ALERTA", 1.0)), float(config.get("K_SIGMA", 2.0))),
        "flota": flota,
    }


def para_ia(bloque: Optional[dict]) -> Optional[dict]:
    """Lo que recibe la IA de la curva: los datos clave, sin las series del grafico."""
    if not bloque:
        return bloque
    return {k: v for k, v in bloque.items() if k not in ("puntos", "banda", "flota")}