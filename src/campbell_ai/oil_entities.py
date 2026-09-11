"""Shared contract for the three oil entity levels, and the deterministic latest-sample pick.

Written for one recurring failure: a question about *a sample* was answered with the
*machine* aggregate, so a transmission result appeared attributed to the engine. The three
levels answer three different questions and none of them substitutes for another:

- **Equipo (machine).** One row per unit in ``oil/golden/{client}/machine_status.parquet``.
  ``overall_status`` there is an aggregate computed upstream by weighting its components
  (``component_details`` carries each component's ``weight``). It is never the result of one
  sample, and this package does not recompute it.
- **Componente (component).** A physical position on a unit — engine, transmission, final
  drive. Its condition comes from the sample selected for it.
- **Muestra (sample).** One row of ``oil/golden/{client}/classified.parquet``, keyed by
  ``sampleNumber``, taken from one component on one ``sampleDate``. The essays are *columns*
  of that row, so a sample is never split across rows and selecting a row keeps all of its
  essays together.

The selection helper exists because three call sites used to reproduce it by hand
(``DashboardDataRepository.query_oil_components``, ``DashboardChartRegistry._oil_component_status``
and the ad-hoc ``oil_components`` chart, which did not do it at all). Two defects were common
to the copies and are fixed here once:

- ``sort_values`` puts ``NaT`` **last**, so a row with an unreadable ``sampleDate`` was picked
  as the newest one. A sample with no valid date can never be the most recent, so undated
  rows sort first and only win when the group has nothing else.
- Same-day samples for the same component are real (189 such pairs in ENEX at the time of
  writing), and with the date alone as the sort key the winner depended on the row order the
  parquet happened to have. ``sampleNumber`` breaks the tie, so repeating the question gives
  the same answer.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Column aliases per level, so the entity keys are declared once instead of being re-typed
# at every call site.
UNIT_COLUMNS: tuple[str, ...] = ("unitId", "unit_id", "UnitId")
MACHINE_UNIT_COLUMNS: tuple[str, ...] = ("unit_id", "unitId", "UnitId")
COMPONENT_COLUMNS: tuple[str, ...] = ("componentNameNormalized", "componentName", "component")
# `componentName` is the raw label and `componentNameNormalized` the resolved alias. Grouping
# on the normalized name is what keeps "MOTOR" and "Motor" together; it must not merge two
# distinct positions, which is why the raw name travels in the payload alongside it.
COMPONENT_GROUP_COLUMNS: tuple[str, ...] = ("componentNameNormalized", "componentName")
SAMPLE_DATE_COLUMNS: tuple[str, ...] = ("sampleDate", "reportDate")
SAMPLE_ID_COLUMNS: tuple[str, ...] = ("sampleNumber", "sample_number", "sampleId")

LEVEL_MACHINE = "equipo"
LEVEL_COMPONENT = "componente"
LEVEL_SAMPLE = "muestra"

# Scope names travel in every payload so a reader can tell "the current condition" from
# "the history of a period" without inferring it from the row count.
SCOPE_LATEST = "latest_per_unit_component"
SCOPE_HISTORY = "history"
# "The newest sample *within* a period" is a third thing, and it kept being collapsed into one
# of the other two: the query tool answered it while the chart answered the whole period, for
# the same words from the same user.
SCOPE_LATEST_IN_PERIOD = "latest_per_unit_component_in_period"

ENTITY_GLOSSARY: dict[str, str] = {
    LEVEL_MACHINE: (
        "Equipo: una unidad. Su estado global es un agregado calculado aguas arriba "
        "ponderando sus componentes; no es el resultado de una muestra."
    ),
    LEVEL_COMPONENT: (
        "Componente: una posicion fisica del equipo (motor, transmision, mando final). "
        "Su condicion proviene de la muestra seleccionada para ese componente."
    ),
    LEVEL_SAMPLE: (
        "Muestra: una extraccion de aceite de un componente en una fecha, identificada por "
        "sampleNumber. Sus ensayos son columnas de esa fila y viajan juntos."
    ),
}

# Reused verbatim by every oil payload so the wording the model reads cannot drift between
# tools.
SCOPE_NOTES: dict[str, str] = {
    SCOPE_LATEST: (
        "Alcance: la muestra mas reciente disponible por equipo y componente, sin ventana "
        "temporal implicita. Puede tener mas de 60 dias; informa su fecha en vez de "
        "descartarla."
    ),
    SCOPE_HISTORY: (
        "Alcance: historico de muestras del periodo indicado. No lo presentes como la "
        "condicion actual de un componente."
    ),
    SCOPE_LATEST_IN_PERIOD: (
        "Alcance: la ultima muestra por equipo y componente DENTRO del periodo indicado. No "
        "es la condicion actual si el periodo termina en el pasado, ni el historial del "
        "periodo."
    ),
}

# The three scopes an oil question can have, exposed so tools, the chart registry and the
# ad-hoc chart name them identically instead of each inventing its own wording.
SAMPLE_SCOPES: tuple[str, ...] = (SCOPE_LATEST, SCOPE_LATEST_IN_PERIOD, SCOPE_HISTORY)


_IDENTITY_COLUMN = "__component_identity"


def component_identity(frame: pd.DataFrame, component_col: str | None) -> pd.Series | None:
    """Canonical grouping key for one physical component position.

    Grouping on the stored name alone splits a component in two whenever the source spells
    it inconsistently: ENEX carries both ``"bastidor izquierdo"`` and
    ``"bastidor izquierdo "``, and 838 raw ``componentName`` groups collapse to 667 once the
    resolved alias is used. Each split invents a second "latest sample" for one position.

    Only whitespace and case are folded. That cannot merge two different positions - left and
    right frame stay distinct - which is the error that would matter in the other direction.
    """
    if component_col is None or component_col not in frame.columns:
        return None
    return frame[component_col].astype(str).str.strip().str.casefold()


def canonical_name(value: Any) -> str:
    """The comparison form of a machine family or component name: trimmed, case-folded."""
    return str(value or "").strip().casefold()


# How `resolve_catalog_key` matched a name. Named so a payload can report what happened
# instead of only whether it found something.
MATCH_EXACT = "exact"
MATCH_CANONICAL = "canonical"
MATCH_DUPLICATE = "canonical_duplicate"
MATCH_AMBIGUOUS = "ambiguous"
MATCH_MISSING = "missing"


def resolve_catalog_key(mapping: dict[str, Any], requested: Any) -> tuple[str | None, str]:
    """Find `requested` among `mapping`'s keys, tolerating spelling, and say how.

    The selection side groups components by their canonical identity, but the calibration
    dictionary was being indexed with the *stored* text: a component recorded as ``"motor "``
    found no limits while ``"motor"`` did, and the answer then reported a missing calibration
    that was in fact present.

    **A collision is checked before an exact match wins.** If two stored keys fold to the same
    identity, this contract already says they are the *same physical component*; a source that
    carries both with different content is contradicting itself, and resolving it by which
    spelling the sample happens to use would pick a calibration by accident. Exact-match-first
    would have made the answer depend on a stray space.

    The exception is a harmless one: colliding keys whose content is identical are a
    duplicated row, not a contradiction, so one of them is returned and the duplication is
    reported. (No calibration file in service today has any collision at all - checked across
    every client - so this decides a hypothetical source defect, not current behaviour.)

    Returns ``(key, status)`` with status one of ``exact``, ``canonical``,
    ``canonical_duplicate``, ``ambiguous`` (nothing returned, the source must be fixed) or
    ``missing``.
    """
    if not isinstance(mapping, dict) or not mapping:
        return None, MATCH_MISSING
    name = str(requested or "")
    target = canonical_name(name)
    if not target:
        return None, MATCH_MISSING
    matches = [key for key in mapping if canonical_name(key) == target]
    if not matches:
        return None, MATCH_MISSING
    if len(matches) > 1:
        first = mapping[matches[0]]
        if not all(mapping[key] == first for key in matches[1:]):
            # Different content under one identity: which one applies is unknowable here.
            return None, MATCH_AMBIGUOUS
        # Same content under two spellings: nothing to choose between them.
        preferred = name if name in mapping else matches[0]
        return preferred, MATCH_DUPLICATE
    if name in mapping:
        return name, MATCH_EXACT
    return matches[0], MATCH_CANONICAL


def resolve_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    """First candidate present in the frame, compared case-insensitively."""
    if frame is None or not len(frame.columns):
        return None
    available = {str(column).casefold(): str(column) for column in frame.columns}
    for candidate in candidates:
        resolved = available.get(str(candidate).casefold())
        if resolved is not None:
            return resolved
    return None


def latest_sample_per_component(
    frame: pd.DataFrame,
    *,
    unit_col: str | None,
    component_col: str | None,
    date_col: str | None,
    sample_id_col: str | None = None,
) -> pd.DataFrame:
    """Keep one row per (unit, component): its most recent, deterministically chosen sample.

    Applies no date window: the newest sample a component has *is* its current condition
    even when it is old, and a window here silently answers "no data" for a component that
    simply has not been sampled lately.

    Undated rows sort first so a valid date always outranks ``NaT``; ``sample_id_col`` breaks
    same-date ties so the result does not depend on the parquet's row order.
    """
    if frame.empty or not (unit_col and component_col and date_col):
        return frame
    ranked = frame.copy()
    ranked[date_col] = pd.to_datetime(ranked[date_col], errors="coerce")
    identity = component_identity(ranked, component_col)
    if identity is None:
        return frame
    ranked[_IDENTITY_COLUMN] = identity
    order = [date_col]
    if sample_id_col and sample_id_col in ranked.columns:
        order.append(sample_id_col)
    ranked = ranked.sort_values(
        order,
        ascending=True,
        na_position="first",
        # Stable, so rows that tie on every sort key keep the source order instead of being
        # permuted by the sort itself.
        kind="mergesort",
    )
    selected = ranked.groupby([unit_col, _IDENTITY_COLUMN], dropna=False).tail(1).copy()
    return selected.drop(columns=[_IDENTITY_COLUMN])


def latest_sample_selection(
    frame: pd.DataFrame, *, group_columns: tuple[tuple[str, ...], ...] = ()
) -> pd.DataFrame:
    """``latest_sample_per_component`` with the columns resolved from the frame itself."""
    unit_candidates, component_candidates = (
        group_columns if group_columns else (UNIT_COLUMNS, COMPONENT_GROUP_COLUMNS)
    )
    return latest_sample_per_component(
        frame,
        unit_col=resolve_column(frame, unit_candidates),
        component_col=resolve_column(frame, component_candidates),
        date_col=resolve_column(frame, SAMPLE_DATE_COLUMNS),
        sample_id_col=resolve_column(frame, SAMPLE_ID_COLUMNS),
    )


def sample_scope_payload(
    frame: pd.DataFrame,
    *,
    scope: str,
    level: str,
    date_col: str | None = None,
) -> dict[str, Any]:
    """The scope block every oil payload carries: level, selection rule and dates covered.

    Stated rather than implied, because "one row per component" and "every sample of the
    last 60 days" look identical in a records list and mean different things.
    """
    payload: dict[str, Any] = {
        "level": level,
        "scope": scope,
        "selection": SCOPE_NOTES.get(scope, ""),
        "glossary": ENTITY_GLOSSARY.get(level, ""),
    }
    if date_col and date_col in frame.columns and not frame.empty:
        dates = pd.to_datetime(frame[date_col], errors="coerce")
        valid = dates.dropna()
        payload["sample_date_field"] = date_col
        payload["samples_without_date"] = int(dates.isna().sum())
        if not valid.empty:
            payload["oldest"] = valid.min().isoformat()
            payload["newest"] = valid.max().isoformat()
    return payload
