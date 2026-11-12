"""
Informe preliminar de falla: diagnostico y causa probable del Predictivo para la unidad (sin IA propia).

La seccion Predictivo del informe usa el texto que el Predictivo ya publica cada semana en
`unit_failure_analisis` (antes `analisis_inteligente`; ver predictive_data_contracts.md): es el mismo
que el cliente vio en la plataforma y ya sigue los lineamientos de mensajes. Este modulo lo lee y
elige el de la ultima semana ANTERIOR a la detencion, para no usar nada posterior.

Contrato: una fila por unidad por particion year=/week=, con `diagnostico`, `causa_probable`,
`acciones` (lista JSON en texto), `limitacion` y `analisis_fuente` ("llm" u "omitida": las unidades
en estado normal suelen venir sin texto).

Uso:
    tabla = cargar("CAPSTONE")
    analisis = analisis_unidad(tabla, "CA-60", "2026-03-08")   # -> evid["analisis_unidad"]
"""

from __future__ import annotations

import json
import threading
import time

import pandas as pd

from src.data.report_health import unit_key
from src.informe_falla import catalog as c
from src.informe_falla import fuentes
from src.informe_falla.config import get_informe_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

TABLA = "unit_failure_analisis"
COLUMNAS = ["Unit", "Fecha", "diagnostico", "causa_probable", "acciones", "limitacion", "analisis_fuente"]

_CACHE: dict = {}
_LOCK = threading.Lock()


def cargar(cliente: str) -> pd.DataFrame:
    """Todas las particiones del cliente (pocas: una por semana), del origen configurado (fuentes.py)."""
    cliente = (cliente or "").lower()
    clave = (cliente, fuentes.origen())
    with _LOCK:
        guardado = _CACHE.get(clave)
        if guardado and time.time() - guardado[0] < get_informe_settings().data_cache_seconds:
            return guardado[1]
        tabla = fuentes.leer_particiones(cliente, TABLA)
        tabla = tabla.reindex(columns=COLUMNAS + ["year", "week"])
        tabla["Fecha"] = pd.to_datetime(tabla["Fecha"], errors="coerce").dt.normalize()
        tabla["unidad_key"] = tabla["Unit"].map(unit_key)
        _CACHE[clave] = (time.time(), tabla)
        return tabla


def _acciones(valor) -> list:
    if isinstance(valor, (list, tuple)):
        return [str(a) for a in valor if a]
    try:
        lista = json.loads(valor) if valor else []
    except (TypeError, ValueError):
        return [str(valor)]
    return [str(a) for a in lista if a] if isinstance(lista, list) else [str(lista)]


def _texto(valor) -> str:
    return "" if valor is None or (isinstance(valor, float) and pd.isna(valor)) else " ".join(str(valor).split())


def analisis_unidad(tabla: pd.DataFrame, unidad: str, fecha) -> dict:
    """El analisis publicado mas reciente con fecha ANTERIOR a la detencion, o {"disponible": False}."""
    fecha = pd.Timestamp(fecha).normalize()
    if tabla is None or tabla.empty:
        return {"disponible": False, "motivo": "sin_tabla"}
    filas = tabla[(tabla["unidad_key"] == unit_key(unidad)) & (tabla["Fecha"] < fecha)]
    if filas.empty:
        return {"disponible": False, "motivo": "sin_analisis_previo"}
    fila = filas.sort_values(["Fecha", "year", "week"]).iloc[-1]
    diagnostico, causa = _texto(fila["diagnostico"]), _texto(fila["causa_probable"])
    fuente = _texto(fila["analisis_fuente"]) or ("llm" if diagnostico else "omitida")
    dias = int((fecha - fila["Fecha"]).days)
    return {
        "disponible": True,
        "con_texto": bool(diagnostico),            # "omitida": unidad normal, sin texto del Predictivo
        "fuente": fuente,
        "fecha": fila["Fecha"].date().isoformat(),
        "dias_antes": dias,
        "antiguo": dias > c.DIAS_ANALISIS_VIEJO,
        "particion": f"{int(fila['year'])}-W{int(fila['week']):02d}" if pd.notna(fila["year"]) else None,
        "diagnostico": diagnostico,
        "causa_probable": causa,
        "acciones": _acciones(fila["acciones"]),
        "limitacion": _texto(fila["limitacion"]),
    }