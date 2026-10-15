"""
Estado de salud de la unidad al momento de cada reporte (Reportabilidad).

El estado sale de la tecnica del reporte. Para predictivo es la columna `estado`
de `data/predictive/golden/{cliente}/{sistema}/unit_failure_analisis/year=/week=/`
(`normal`, `alerta`, `anormal`).

Que semana corresponde a un reporte: la del ultimo analisis publicado hasta la
fecha de generacion. La semana ISO de esa fecha no sirve sola: un informe
generado el lunes 2026-09-07 cae en la semana 37, cuyo analisis es del sabado
2026-09-12, posterior al informe. Si el ultimo analisis es mas viejo que
MAX_ANALYSIS_AGE_DAYS, el estado queda vacio ("sin dato"): mostrar el estado de
hace un mes junto a un informe de hoy seria mas engañoso que no mostrar nada.

Los nombres de unidad no coinciden entre fuentes (`T_09` en el parquet, `t_9` en
el PDF); se comparan por `unit_key`, que quita ceros a la izquierda.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from src.data import predictive_v2
from src.data.report_store import TECHNIQUE_PREDICTIVE
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_ANALYSIS_AGE_DAYS = 10

# Estados del modelo, del mas grave al mas sano (mismo orden que el Predictivo).
HEALTH_STATES = ("anormal", "alerta", "normal")

# tecnica -> lector del historial de estados (client, system) -> DataFrame[Unit, Fecha, estado, year, week]
HISTORY_LOADERS: Dict[str, Callable[[str, str], pd.DataFrame]] = {
    TECHNIQUE_PREDICTIVE: predictive_v2.load_unit_state_history,
}

# unit_key -> [(fecha, estado, "yyyy-Www")] ordenado por fecha
_History = Dict[str, List[Tuple[date, str, str]]]


def unit_key(unit) -> str:
    """`T_09`, `t_9` y `T_9` son la misma unidad."""
    return re.sub(r"\d+", lambda m: str(int(m.group())), str(unit or "").strip().upper())


def _index_history(df: pd.DataFrame) -> _History:
    index: _History = {}
    if df is None or df.empty:
        return index
    for row in df.dropna(subset=["Unit", "Fecha", "estado"]).itertuples(index=False):
        week = f"{int(row.year)}-W{int(row.week):02d}"
        index.setdefault(unit_key(row.Unit), []).append(
            (pd.Timestamp(row.Fecha).date(), str(row.estado).strip().lower(), week)
        )
    for runs in index.values():
        runs.sort()
    return index


def state_at(history: _History, unit: str, report_date: str) -> Optional[Tuple[date, str, str]]:
    """(fecha, estado, semana) del ultimo analisis hasta `report_date`, o None."""
    try:
        when = date.fromisoformat(report_date)
    except (TypeError, ValueError):
        return None
    best = None
    for run in history.get(unit_key(unit), ()):
        if run[0] > when:
            break
        best = run
    if best is None or (when - best[0]).days > MAX_ANALYSIS_AGE_DAYS:
        return None
    return best


def attach_health(records: List[dict], client: str,
                  loaders: Optional[Dict[str, Callable[[str, str], pd.DataFrame]]] = None) -> List[dict]:
    """Agrega `health`, `health_date` y `health_week` a cada registro (None si no hay dato)."""
    loaders = HISTORY_LOADERS if loaders is None else loaders
    histories: Dict[tuple, _History] = {}
    for record in records:
        slot = (record["technique"], record["system"])
        if slot not in histories:
            loader = loaders.get(record["technique"])
            try:
                histories[slot] = _index_history(loader(client.lower(), record["system"])) if loader else {}
            except Exception as exc:
                logger.error(f"Estado de salud {client}/{slot}: no se pudo leer ({type(exc).__name__}: {exc})")
                histories[slot] = {}
        found = state_at(histories[slot], record["unit"], record["date"])
        record["health"] = found[1] if found else None
        record["health_date"] = found[0].isoformat() if found else None
        record["health_week"] = found[2] if found else None
    return records
