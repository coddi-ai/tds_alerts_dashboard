"""
Seleccion, orden y filtros de Reportabilidad, sin Dash.

Trabaja sobre los registros del catalogo (`dashboard/callbacks/reporting_callbacks.py`
los arma desde S3 y `report_health.attach_health` les pone el estado combinado en
`record["health"]`). Lo que decide aqui:

* Que unidades van en "Requieren atencion" / "Sin alertas" y en que orden: del mas al
  menos critico, luego por numero de unidad.
* La lista del informe de unidad (a la izquierda) y sus vecinos Anterior / Siguiente.
* Que informe se abre al cambiar de unidad, de sistema o de fecha dentro del visor.
* Filtro, orden y paginacion del Historial.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from src.data.report_health import NO_DATA, STATE_RANK, STATES_BY_SEVERITY, normalize_state, unit_key
from src.data.report_store import TECHNIQUE_SYSTEMS, unit_sort_key

ALL = "all"  # valor de los selects para "sin filtro" (dbc.Select tambien dibuja una opcion "" oculta)

ATTENTION_STATES = ("anormal", "alerta")

HISTORY_PAGE_SIZE = 15
HISTORY_COLUMNS = ("date", "unit", "system", "health")
# Primer sentido al ordenar por una columna: la fecha y el estado parten de lo mas relevante.
HISTORY_FIRST_DIRECTION = {"date": "desc", "health": "desc"}

Record = dict


def health_of(record: Record) -> str:
    return normalize_state(record.get("health")) or NO_DATA


def wanted_state(value: Optional[str]) -> Optional[str]:
    """Estado que pide un filtro, o None si no filtra ("all", vacio)."""
    if value in (None, "", ALL):
        return None
    return normalize_state(value) or NO_DATA


def system_order(technique: str, system: str) -> int:
    systems = TECHNIQUE_SYSTEMS.get(technique, ())
    return systems.index(system) if system in systems else len(systems)


def criticality_key(record: Record) -> tuple:
    """Del mas al menos critico; a igual estado, por numero de unidad y sistema."""
    return (-STATE_RANK[health_of(record)], unit_sort_key(record["unit"]),
            system_order(record["technique"], record["system"]))


def ordered_systems(records: Iterable[Record]) -> List[Tuple[str, str]]:
    present = {(r["technique"], r["system"]) for r in records}
    return [(tech, system) for tech, systems in TECHNIQUE_SYSTEMS.items() for system in systems
            if (tech, system) in present]


# ---------------------------------------------------------------------------
# Estado actual
# ---------------------------------------------------------------------------

def batch_records(records: List[Record], technique: Optional[str], system: Optional[str],
                  date: Optional[str]) -> List[Record]:
    """Informes de una fecha de generacion para la tecnica y el sistema elegidos."""
    return [
        r for r in records
        if r["date"] == date
        and (not technique or r["technique"] == technique)
        and (not system or system == ALL or r["system"] == system)
    ]


def state_counts(batch: List[Record]) -> Dict[str, int]:
    """Unidades por estado combinado, con los cinco estados presentes (aunque en 0)."""
    counts = {state: 0 for state in STATES_BY_SEVERITY}
    for record in batch:
        counts[health_of(record)] += 1
    return counts


def split_sections(batch: List[Record], state_filter: Optional[str] = ALL) -> Tuple[List[Record], List[Record]]:
    """(requieren atencion, sin alertas), cada uno ordenado por criticidad y unidad.

    `state_filter` deja solo los informes de ese estado combinado."""
    wanted = wanted_state(state_filter)
    shown = [r for r in batch if wanted is None or health_of(r) == wanted]
    shown.sort(key=criticality_key)
    attention = [r for r in shown if health_of(r) in ATTENTION_STATES]
    clear = [r for r in shown if health_of(r) not in ATTENTION_STATES]
    return attention, clear


# ---------------------------------------------------------------------------
# Informe de unidad (visor)
# ---------------------------------------------------------------------------

class CatalogIndex:
    """Busquedas por (tecnica, unidad, sistema) sobre el catalogo, del informe mas nuevo al mas viejo."""

    def __init__(self, records: List[Record]):
        self.by_key: Dict[str, Record] = {r["key"]: r for r in records}
        self._slots: Dict[tuple, List[Record]] = {}
        for record in sorted(records, key=lambda r: r["date"], reverse=True):
            self._slots.setdefault((record["technique"], record["unit"], record["system"]), []).append(record)

    def reports(self, technique: str, unit: str, system: str) -> List[Record]:
        return self._slots.get((technique, unit, system), [])

    def at(self, technique: str, unit: str, system: str, date: str) -> Optional[Record]:
        return next((r for r in self.reports(technique, unit, system) if r["date"] == date), None)

    def latest(self, technique: str, unit: str, system: str) -> Optional[Record]:
        reports = self.reports(technique, unit, system)
        return reports[0] if reports else None

    def target(self, technique: str, unit: str, system: str, date: str) -> Optional[Record]:
        """Informe de la unidad en ese sistema y fecha; si no existe, el mas reciente del sistema."""
        return self.at(technique, unit, system, date) or self.latest(technique, unit, system)

    def systems_of(self, technique: str, unit: str) -> List[str]:
        return [s for s in TECHNIQUE_SYSTEMS.get(technique, ()) if self.reports(technique, unit, s)]


def unit_list(records: List[Record], technique: str, system: str, list_date: str) -> List[Record]:
    """Informes del sistema en la fecha de la lista, del mas al menos critico."""
    return sorted(batch_records(records, technique, system, list_date), key=criticality_key)


def viewer_model(records: List[Record], key: Optional[str], list_date: Optional[str] = None) -> Optional[dict]:
    """Todo lo que el visor necesita para un informe abierto, o None si la clave no existe.

    `rows` es la lista de la izquierda (una entrada por unidad con su informe de destino:
    mismo sistema y fecha que el abierto, o el mas reciente del sistema). Anterior /
    Siguiente recorren `rows` completa, aunque la busqueda la acorte en pantalla.
    """
    index = CatalogIndex(records)
    current = index.by_key.get(key)
    if current is None:
        return None
    technique, system, unit = current["technique"], current["system"], current["unit"]
    list_date = list_date if list_date else current["date"]

    rows = []
    for record in unit_list(records, technique, system, list_date):
        target = index.target(technique, record["unit"], system, current["date"])
        rows.append({"unit": record["unit"], "health": health_of(record), "target": target,
                     "selected": record["unit"] == unit})
    position = next((i for i, row in enumerate(rows) if row["selected"]), None)
    if position is None:
        previous_row, next_row = None, (rows[0] if rows else None)
    else:
        previous_row = rows[position - 1] if position > 0 else None
        next_row = rows[position + 1] if position + 1 < len(rows) else None

    return {
        "record": current,
        "list_date": list_date,
        "rows": rows,
        "position": position,
        "total": len(rows),
        "previous": previous_row,
        "next": next_row,
        "systems": [(s, index.target(technique, unit, s, current["date"]))
                    for s in index.systems_of(technique, unit)],
        "dates": index.reports(technique, unit, system),
    }


def search_rows(rows: List[dict], query: Optional[str]) -> List[dict]:
    """Filtra la lista por texto; `9` encuentra `T_9` y `T_09`."""
    needle = (query or "").strip().lower()
    if not needle:
        return rows
    return [r for r in rows if needle in r["unit"].lower() or needle in unit_key(r["unit"]).lower()]


# ---------------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------------

def filter_history(records: List[Record], technique=None, system=None, unit=None, date=None,
                   state=None) -> List[Record]:
    """Filtra por tecnica, sistema, unidad, fecha y estado combinado ("all"/None = sin filtro)."""
    def free(value):
        return value in (None, "", ALL)

    wanted = wanted_state(state)
    return [
        r for r in records
        if (free(technique) or r["technique"] == technique)
        and (free(system) or r["system"] == system)
        and (free(unit) or r["unit"] == unit)
        and (free(date) or r["date"] == date)
        and (wanted is None or health_of(r) == wanted)
    ]


def _history_sort_key(column: str):
    if column == "date":
        return lambda r: r["date"]
    if column == "unit":
        return lambda r: unit_sort_key(r["unit"])
    if column == "system":
        return lambda r: system_order(r["technique"], r["system"])
    return lambda r: STATE_RANK[health_of(r)]


def sort_history(records: List[Record], column: str, direction: str) -> List[Record]:
    """Orden por columna; los empates quedan por fecha reciente, unidad y sistema."""
    column = column if column in HISTORY_COLUMNS else "date"
    base = sorted(records, key=lambda r: (unit_sort_key(r["unit"]), system_order(r["technique"], r["system"])))
    base.sort(key=lambda r: r["date"], reverse=True)
    base.sort(key=_history_sort_key(column), reverse=direction == "desc")
    return base


def next_sort(state: dict, column: str) -> dict:
    """Estado de orden tras pulsar una columna: la activa invierte el sentido, otra parte de su sentido inicial."""
    if column not in HISTORY_COLUMNS:
        return state
    if state.get("sort") == column:
        direction = "asc" if state.get("dir") == "desc" else "desc"
    else:
        direction = HISTORY_FIRST_DIRECTION.get(column, "asc")
    return {**state, "sort": column, "dir": direction, "page": 1}


def paginate(items: list, page: int, size: int = HISTORY_PAGE_SIZE) -> Tuple[list, int, int, int]:
    """(pagina, numero de pagina corregido, total de paginas, indice del primero 1-based; 0 si no hay)."""
    pages = max(1, -(-len(items) // size))
    page = min(max(int(page or 1), 1), pages)
    start = (page - 1) * size
    return items[start:start + size], page, pages, (start + 1 if items else 0)
