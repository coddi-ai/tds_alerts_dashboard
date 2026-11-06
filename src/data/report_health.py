"""
Estado combinado de la unidad al momento de cada reporte (Reportabilidad).

Cada unidad tiene UN estado por (tecnica, sistema, fecha de reporte): el mas critico
de dos fuentes.

* Analisis de la unidad: columna `estado` de
  `data/predictive/golden/{cliente}/{sistema}/unit_failure_analisis/year=/week=/`.
* Curva de riesgo acumulado: columna `estado` de `.../cumulative_risk_curve/`, que ya
  trae el historial de cada unidad (ver `predictive_v2.load_curve_state_history`).

Ninguna vista de Reportabilidad lee `Estado` de una fuente directamente: todas usan
`record["health"]`. Las fuentes siguen en el registro (`health_analysis`,
`health_curve`) solo para mostrar de donde sale el estado combinado.

Escala unica del dashboard (src/status_scale.py), de menos a mas critico: Sin Datos <
Normal < Alerta < Anormal. Un "Critico" o "Atencion" de una fuente se lee como Anormal /
Alerta, igual que en el resto del dashboard. Una fuente sin estado no cuenta (nunca se
lee como Normal); si ninguna tiene estado, la unidad queda en Sin Datos.

Que fila de cada fuente corresponde a un reporte: la ultima publicada hasta la fecha
de generacion. La semana ISO de esa fecha no sirve sola: un informe generado el lunes
2026-09-07 cae en la semana 37, cuyo analisis es del sabado 2026-09-12, posterior al
informe. Si esa ultima fila es mas vieja que MAX_ANALYSIS_AGE_DAYS, la fuente no
aporta estado: mostrar el estado de hace un mes junto a un informe de hoy seria mas
enganoso que no mostrar nada.

Los nombres de unidad no coinciden entre fuentes (`T_09` en el parquet, `t_9` en el
PDF); se comparan por `unit_key`, que quita ceros a la izquierda.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from src.data import predictive_v2
from src.data.report_store import TECHNIQUE_PREDICTIVE
from src.status_scale import SCALE, SIN_DATOS, get_status, worst
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_ANALYSIS_AGE_DAYS = 10

NO_DATA = SIN_DATOS.key

# De menos a mas critico. El indice es el rango de cada estado.
STATE_ORDER = tuple(status.key for status in SCALE)
STATE_RANK = {status.key: status.rank for status in SCALE}
# Del mas critico al menos: el orden en que la interfaz los lista.
STATES_BY_SEVERITY = tuple(reversed(STATE_ORDER))

LoadHistory = Callable[[str, str], pd.DataFrame]

# tecnica -> lector del historial del analisis (client, system) -> DataFrame[Unit, Fecha, estado, year, week]
HISTORY_LOADERS: Dict[str, LoadHistory] = {
    TECHNIQUE_PREDICTIVE: predictive_v2.load_unit_state_history,
}

# tecnica -> lector del historial de la curva (client, system) -> DataFrame[Unit, Fecha, estado]
CURVE_LOADERS: Dict[str, LoadHistory] = {
    TECHNIQUE_PREDICTIVE: predictive_v2.load_curve_state_history,
}

# unit_key -> (fechas ordenadas, [(fecha, estado, "yyyy-Www" | None)] en el mismo orden)
_History = Dict[str, Tuple[List[date], List[Tuple[date, str, Optional[str]]]]]


def unit_key(unit) -> str:
    """`T_09`, `t_9` y `T_9` son la misma unidad."""
    return re.sub(r"\d+", lambda m: str(int(m.group())), str(unit or "").strip().upper())


def normalize_state(value) -> Optional[str]:
    """`Anormal`, `anormal `, `Critico` -> clave de la escala; None si no es un estado.

    "Sin Datos" tampoco es un estado de una fuente: es la ausencia de uno."""
    status = get_status(value)
    return None if status is SIN_DATOS else status.key


def combine_states(*states) -> str:
    """El mas critico de los estados dados; `sin_datos` si ninguno es un estado."""
    return worst(*states).key


def _index_history(df: pd.DataFrame) -> _History:
    grouped: Dict[str, List[Tuple[date, str, Optional[str]]]] = {}
    if df is None or df.empty:
        return {}
    has_week = {"year", "week"}.issubset(df.columns)
    for row in df.dropna(subset=["Unit", "Fecha", "estado"]).itertuples(index=False):
        state = normalize_state(row.estado)
        if state is None:
            continue
        week = f"{int(row.year)}-W{int(row.week):02d}" if has_week else None
        grouped.setdefault(unit_key(row.Unit), []).append((pd.Timestamp(row.Fecha).date(), state, week))
    index: _History = {}
    for key, runs in grouped.items():
        runs.sort(key=lambda run: run[0])  # estable: a igual fecha manda el ultimo leido
        index[key] = ([run[0] for run in runs], runs)
    return index


def state_at(history: _History, unit: str, report_date: str,
             max_age_days: int = MAX_ANALYSIS_AGE_DAYS) -> Optional[Tuple[date, str, Optional[str]]]:
    """(fecha, estado, semana) de la ultima fila hasta `report_date`, o None."""
    try:
        when = date.fromisoformat(report_date)
    except (TypeError, ValueError):
        return None
    dates, runs = history.get(unit_key(unit), ([], []))
    position = bisect_right(dates, when) - 1
    if position < 0 or (when - dates[position]).days > max_age_days:
        return None
    return runs[position]


def _load_index(loaders: Dict[str, LoadHistory], technique: str, system: str, client: str, source: str) -> _History:
    loader = loaders.get(technique)
    if loader is None:
        return {}
    try:
        return _index_history(loader(client.lower(), system))
    except Exception as exc:
        logger.error(f"Estado {source} {client}/{technique}/{system}: no se pudo leer ({type(exc).__name__}: {exc})")
        return {}


def attach_health(records: List[dict], client: str,
                  loaders: Optional[Dict[str, LoadHistory]] = None,
                  curve_loaders: Optional[Dict[str, LoadHistory]] = None) -> List[dict]:
    """Agrega el estado combinado y sus dos fuentes a cada registro.

    `health` es siempre una clave de STATE_ORDER (`sin_datos` si ninguna fuente tiene
    estado). `health_analysis` / `health_curve` son el estado de cada fuente o None, con
    su fecha (`*_date`) y, para el analisis, la semana (`health_analysis_week`).
    """
    analysis_loaders = HISTORY_LOADERS if loaders is None else loaders
    curve_loaders = CURVE_LOADERS if curve_loaders is None else curve_loaders
    analysis: Dict[tuple, _History] = {}
    curves: Dict[tuple, _History] = {}
    for record in records:
        slot = (record["technique"], record["system"])
        if slot not in analysis:
            analysis[slot] = _load_index(analysis_loaders, *slot, client, "analisis")
            curves[slot] = _load_index(curve_loaders, *slot, client, "curva")
        from_analysis = state_at(analysis[slot], record["unit"], record["date"])
        from_curve = state_at(curves[slot], record["unit"], record["date"])
        record["health_analysis"] = from_analysis[1] if from_analysis else None
        record["health_analysis_date"] = from_analysis[0].isoformat() if from_analysis else None
        record["health_analysis_week"] = from_analysis[2] if from_analysis else None
        record["health_curve"] = from_curve[1] if from_curve else None
        record["health_curve_date"] = from_curve[0].isoformat() if from_curve else None
        record["health"] = combine_states(record["health_analysis"], record["health_curve"])
    return records
