"""Oil component analysis: how one critical component (motor, transmisión, convertidor, diferencial)
stands across a whole fleet.

Feeds the Monitor de Aceite > Análisis por Componente tab. Everything is derived from the client's
`classified.parquet` plus `config/component_analysis.yaml` (which names belong to each option, the
stale threshold and the age buckets). Nothing is stored: the days since the last sample are computed
against "today" every time the tab renders, so changing the configuration or the date changes the
result without a pipeline run.

No Dash import: the rules are tested on their own (tests/test_component_analysis.py).

Unit of analysis. One row per `unitId` + `componentName` (a unit can have several differentials or
transmissions), taken from that pair's LATEST sample:
  * Estado is the sample's own `report_status`: it is never recomputed from the essays;
  * Tipo de anomalía is `anomalyType` ("Sin clasificar" when a non-Normal sample has none);
  * the essays out of limit are the entries of `breached_essays`. Marginal is "Marginal"; Condenatorio
    and Critico are both "Condenatorio" (critical values are merged), whether the limit is the upper or
    the lower one;
  * the estado of the previous sample is the one dated `previousSampleDate`.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import yaml

from src.data.sampling_frequency import data_as_of, local_today, normalize_name
from src.status_scale import get_status

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "component_analysis.yaml"

# Estados, worst first (the order the tab lists them in), and their rank (higher = worse).
NORMAL, ALERTA, ANORMAL = "Normal", "Alerta", "Anormal"
ESTADOS = (ANORMAL, ALERTA, NORMAL)
RANK = {NORMAL: 1, ALERTA: 2, ANORMAL: 3}

# Levels of an essay out of limit. `Critico` in the data is merged into CONDENATORIO.
MARGINAL, CONDENATORIO = "Marginal", "Condenatorio"
LEVEL_RANK = {MARGINAL: 1, CONDENATORIO: 2}
_LEVEL_BY_THRESHOLD = {"marginal": MARGINAL, "condenatorio": CONDENATORIO, "critico": CONDENATORIO}

# Criticality classes the machine score already uses.
CRITICO, IMPORTANTE = "critico", "importante"
CRITICALITIES = (CRITICO, IMPORTANTE)

# The "Mostrar" options of the matrix.
SHOW_ALERTA_ANORMAL, SHOW_ANORMAL, SHOW_TODOS = "alerta_anormal", "anormal", "todos"
SHOW_OPTIONS = (SHOW_ALERTA_ANORMAL, SHOW_ANORMAL, SHOW_TODOS)
_SHOWN_ESTADOS = {SHOW_ALERTA_ANORMAL: {ALERTA, ANORMAL}, SHOW_ANORMAL: {ANORMAL}, SHOW_TODOS: {NORMAL, ALERTA, ANORMAL}}

# How the estado changed against the previous sample.
WORSENING, IMPROVING, UNCHANGED = "worsening", "improving", "unchanged"
TREND_RANK = {WORSENING: 3, UNCHANGED: 2, IMPROVING: 1}

# Sort key of the essay columns of the matrix: "essay:<name>".
ESSAY_PREFIX = "essay:"


def alpha_key(text) -> tuple:
    """Sort key for "alphabetical" order of Spanish text: accents and case do not separate letters
    ("Índice PQ" sorts with the I's, not after the Z's); the exact text only breaks a full tie."""
    return (normalize_name(text), str(text))


def essay_column(essay: str) -> str:
    """The sort key of an essay's column. The header button writes it into its id with `id_text` and the
    table's controller reads it back, so here it is the plain text (see src/utils/dash_ids.py)."""
    return ESSAY_PREFIX + essay


class ComponentAnalysisConfigError(ValueError):
    """The component analysis configuration file is missing or malformed."""


@dataclass(frozen=True)
class ComponentSpec:
    key: str
    criticality: str
    names: Tuple[str, ...]          # normalized componentNameNormalized values


@dataclass(frozen=True)
class AnalysisConfig:
    components: Dict[str, ComponentSpec]    # in the order of the selector
    stale_days: int
    age_edges: Tuple[int, ...]              # inner edges, all below stale_days

    def default_component(self) -> str:
        return next(iter(self.components))

    def spec(self, key: Optional[str]) -> ComponentSpec:
        """The option for `key`; the default one when `key` is not (or no longer) a configured option."""
        return self.components.get(key) or self.components[self.default_component()]


# ---------------------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------------------

_config_cache: Dict[Path, Tuple[int, AnalysisConfig]] = {}


def _positive_int(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 or int(value) != value:
        raise ComponentAnalysisConfigError(f"'{what}' debe ser un número entero positivo")
    return int(value)


def parse_config(raw) -> AnalysisConfig:
    """Validate the parsed YAML and turn it into an AnalysisConfig (raises ComponentAnalysisConfigError)."""
    if not isinstance(raw, dict):
        raise ComponentAnalysisConfigError("la configuración debe ser un mapa con 'components'")

    stale_days = _positive_int(raw.get("stale_days", 90), "stale_days")
    edges = tuple(_positive_int(edge, "age_edges") for edge in (raw.get("age_edges") or ()))
    if list(edges) != sorted(set(edges)) or (edges and edges[-1] >= stale_days):
        raise ComponentAnalysisConfigError("'age_edges' debe ir en orden creciente y por debajo de 'stale_days'")

    components: Dict[str, ComponentSpec] = {}
    for key, body in (raw.get("components") or {}).items():
        if not isinstance(body, dict):
            raise ComponentAnalysisConfigError(f"'components.{key}' debe ser un mapa con 'criticality' y 'names'")
        criticality = str(body.get("criticality", "")).strip().casefold()
        if criticality not in CRITICALITIES:
            raise ComponentAnalysisConfigError(
                f"'components.{key}.criticality' debe ser uno de: {', '.join(CRITICALITIES)}")
        names = tuple(dict.fromkeys(normalize_name(n) for n in (body.get("names") or ()) if normalize_name(n)))
        if not names:
            raise ComponentAnalysisConfigError(f"'components.{key}.names' necesita al menos un nombre")
        components[str(key)] = ComponentSpec(str(key), criticality, names)
    if not components:
        raise ComponentAnalysisConfigError("falta al menos un componente en 'components'")
    return AnalysisConfig(components=components, stale_days=stale_days, age_edges=edges)


def load_config(path: Optional[Path] = None) -> AnalysisConfig:
    """The configuration, re-read whenever the file changes (so edits need no restart)."""
    path = Path(path or CONFIG_PATH)
    try:
        stamp = path.stat().st_mtime_ns
    except OSError as exc:
        raise ComponentAnalysisConfigError(f"no se encontró {path.name}") from exc
    cached = _config_cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ComponentAnalysisConfigError(f"{path.name} no es un YAML válido: {exc}") from exc
    config = parse_config(raw)
    _config_cache[path] = (stamp, config)
    return config


# ---------------------------------------------------------------------------------------------
# Reading the classified frame
# ---------------------------------------------------------------------------------------------

def canonical_estado(value) -> Optional[str]:
    """Normal / Alerta / Anormal for any spelling of a report status; None for anything else."""
    name = get_status(value).name
    return name if name in RANK else None


def _text(value) -> Optional[str]:
    """A stripped string, or None for a missing / blank value."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    return text or None


def _number(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def iso_date(value) -> Optional[str]:
    """`YYYY-MM-DD`, or None for a missing date."""
    return None if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")


def latest_report_text(classified: pd.DataFrame) -> Optional[str]:
    """The client's latest `reportDate` as `YYYY-MM-DD` (the "Datos al ..." date), or None without reports."""
    return iso_date(data_as_of(classified))


def parse_breaches(raw) -> List[dict]:
    """The essays out of limit of one sample: `[{essay, level, group, counts}]`, one per essay.

    `raw` is the `breached_essays` cell (a JSON text, or already a list). `level` is Marginal or
    Condenatorio (Critico merged; an entry with any other threshold is not a breach we can level, so it
    is left out). `counts` is `use_for_classification` (whether the essay takes part in the state);
    an entry that does not say is taken to count. An essay listed twice keeps its worst level.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else []
        except ValueError:
            return []
    if raw is None or isinstance(raw, (int, float)) or not hasattr(raw, "__iter__"):
        return []
    found: Dict[str, dict] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        essay = _text(entry.get("essay"))
        level = _LEVEL_BY_THRESHOLD.get(normalize_name(entry.get("threshold")))
        if essay is None or level is None:
            continue
        flag = entry.get("use_for_classification", 1)
        counts = bool(_number(flag)) if _number(flag) is not None else str(flag).strip().casefold() in ("true", "si", "sí")
        current = found.get(essay)
        if current is None or LEVEL_RANK[level] > LEVEL_RANK[current["level"]]:
            found[essay] = {"essay": essay, "level": level, "group": _text(entry.get("group")), "counts": counts}
    return list(found.values())


def build_component_rows(classified: pd.DataFrame, spec: ComponentSpec, fleet: Optional[str] = None) -> List[dict]:
    """One JSON-safe record per unit + component of the option `spec`, from that pair's latest sample.

    `fleet` is the machine type (`machineName`) to analyse; without one nothing is selected. A record:
    `unit_id`, `component` (the data's own `componentName`), `machine`, `estado`, `anomaly` (None when the
    sample is Normal or has no usable label), `sample_date` (ISO), `prev_estado` (None without a previous
    sample), `component_hours`, `oil_hours` and `breaches` (see `parse_breaches`). Rows come out in no
    particular order; a sample whose `report_status` is not Normal / Alerta / Anormal is left out so the
    counts always add up.
    """
    needed = {"unitId", "componentName", "sampleDate", "report_status", "componentNameNormalized"}
    if classified is None or classified.empty or not fleet or not needed.issubset(classified.columns):
        return []

    df = classified
    if "machineName" in df.columns:
        df = df[df["machineName"] == fleet]
    names = set(spec.names)
    df = df[df["componentNameNormalized"].map(normalize_name).isin(names)]
    if df.empty:
        return []

    df = df.assign(_sample=pd.to_datetime(df["sampleDate"], errors="coerce").dt.normalize())
    reports = (pd.to_datetime(df["reportDate"], errors="coerce") if "reportDate" in df.columns
               else pd.Series(pd.NaT, index=df.index))
    df = df.assign(_report=reports)
    df = df.dropna(subset=["unitId", "componentName", "_sample"])
    # Oldest first within each pair; samples of the same day fall back to the later report.
    df = df.sort_values(["_sample", "_report"], kind="mergesort", na_position="first")
    previous_dates = (pd.to_datetime(df["previousSampleDate"], errors="coerce").dt.normalize()
                      if "previousSampleDate" in df.columns else pd.Series(pd.NaT, index=df.index))
    df = df.assign(_previous=previous_dates)

    rows: List[dict] = []
    for (unit_id, component), history in df.groupby(["unitId", "componentName"], sort=False):
        latest = history.iloc[-1]
        estado = canonical_estado(latest["report_status"])
        if estado is None:
            continue
        prev_estado = None
        if pd.notna(latest["_previous"]):
            earlier = history.iloc[:-1]
            same_day = earlier[earlier["_sample"] == latest["_previous"]]
            if not same_day.empty:
                prev_estado = canonical_estado(same_day.iloc[-1]["report_status"])
        anomaly = _text(latest.get("anomalyType"))
        if estado == NORMAL:
            anomaly = None                                  # a Normal sample has no anomaly to name
        elif anomaly is not None and normalize_name(anomaly) == "normal":
            anomaly = None                                  # non-Normal sample labelled "Normal": unclassified
        rows.append({
            "unit_id": str(unit_id), "component": str(component),
            "machine": _text(latest.get("machineName")),
            "estado": estado, "anomaly": anomaly,
            "sample_date": iso_date(latest["_sample"]), "prev_estado": prev_estado,
            "component_hours": _number(latest.get("componentHours")),
            "oil_hours": _number(latest.get("oilMeter")),
            "breaches": parse_breaches(latest.get("breached_essays")),
        })
    return rows


def fleets_of(classified: pd.DataFrame) -> List[str]:
    """The machine types of the client, A-Z."""
    if classified is None or classified.empty or "machineName" not in classified.columns:
        return []
    return sorted(str(f) for f in classified["machineName"].dropna().unique())


# ---------------------------------------------------------------------------------------------
# Rules applied at render time (they depend on today's date)
# ---------------------------------------------------------------------------------------------

def days_since(sample_date, today: Optional[date] = None) -> Optional[int]:
    """Calendar days from the sample to today (never negative: a sample dated in the future is today's)."""
    if sample_date is None:
        return None
    today = today or local_today()
    return max(0, (pd.Timestamp(today).normalize() - pd.Timestamp(sample_date).normalize()).days)


def is_stale(days: Optional[int], config: AnalysisConfig) -> bool:
    """Older than `stale_days` (exactly `stale_days` days old is still current)."""
    return days is not None and days > config.stale_days


def estado_counts(rows: Iterable[dict]) -> Dict[str, int]:
    counts = {estado: 0 for estado in ESTADOS}
    for row in rows:
        counts[row["estado"]] += 1
    return counts


def age_buckets(rows: Iterable[dict], config: AnalysisConfig, today: Optional[date] = None) -> List[dict]:
    """The components split by days since their last sample: `[{lo, hi, count}]`, `hi` None for the last
    bucket (older than `stale_days`). With edges [30, 60] and 90 stale days: 0-30, 31-60, 61-90, 91+."""
    edges = [*config.age_edges, config.stale_days]
    buckets = []
    low = 0
    for edge in edges:
        buckets.append({"lo": low, "hi": edge, "count": 0})
        low = edge + 1
    buckets.append({"lo": low, "hi": None, "count": 0})
    for row in rows:
        days = days_since(row["sample_date"], today)
        if days is None:
            continue
        for bucket in buckets:
            if bucket["hi"] is None or days <= bucket["hi"]:
                bucket["count"] += 1
                break
    return buckets


def stale_count(rows: Iterable[dict], config: AnalysisConfig, today: Optional[date] = None) -> int:
    return sum(1 for row in rows if is_stale(days_since(row["sample_date"], today), config))


def active_breaches(row: dict, include_all: bool = False) -> List[dict]:
    """The essays out of limit of a row: only those that take part in the state, or all of them."""
    return [b for b in row["breaches"] if include_all or b["counts"]]


def out_of_limit_rows(rows: Iterable[dict]) -> List[dict]:
    """The components in Alerta or Anormal: the population of the anomaly and essay cards."""
    return [row for row in rows if row["estado"] != NORMAL]


def anomaly_counts(rows: Iterable[dict], unclassified: str = "Sin clasificar") -> List[dict]:
    """`[{type, anormal, alerta, total}]` over the components in Alerta or Anormal, biggest total first
    (ties A-Z). A non-Normal sample with no `anomalyType` counts under `unclassified`."""
    counts: Dict[str, Dict[str, int]] = {}
    for row in out_of_limit_rows(rows):
        label = row["anomaly"] or unclassified
        entry = counts.setdefault(label, {ANORMAL: 0, ALERTA: 0})
        entry[row["estado"]] += 1
    result = [{"type": label, "anormal": c[ANORMAL], "alerta": c[ALERTA], "total": c[ANORMAL] + c[ALERTA]}
              for label, c in counts.items()]
    return sorted(result, key=lambda e: (-e["total"], alpha_key(e["type"])))


def essay_counts(rows: Iterable[dict], include_all: bool = False) -> List[dict]:
    """`[{essay, group, n, cond, marg}]` over the components in Alerta or Anormal: for each essay, the
    number of latest samples that have it out of limit (`n`) and how many of them at each level.

    Biggest `n` first; ties by Condenatorio count (more first), then A-Z. By default only the essays
    that take part in the state are counted; `include_all` adds the rest."""
    stats: Dict[str, dict] = {}
    for row in out_of_limit_rows(rows):
        for breach in active_breaches(row, include_all):
            entry = stats.setdefault(breach["essay"], {"essay": breach["essay"], "group": breach["group"],
                                                       "n": 0, "cond": 0, "marg": 0})
            entry["n"] += 1
            entry["cond" if breach["level"] == CONDENATORIO else "marg"] += 1
            entry["group"] = entry["group"] or breach["group"]
    return sorted(stats.values(), key=lambda e: (-e["n"], -e["cond"], alpha_key(e["essay"])))


def trend_of(estado: str, prev_estado: Optional[str]) -> Optional[str]:
    """Worsening / improving / unchanged against the previous sample (Normal < Alerta < Anormal); None
    without a previous sample."""
    if prev_estado is None:
        return None
    if RANK[estado] > RANK[prev_estado]:
        return WORSENING
    if RANK[estado] < RANK[prev_estado]:
        return IMPROVING
    return UNCHANGED


def shown_rows(rows: Iterable[dict], show: str = SHOW_ALERTA_ANORMAL) -> List[dict]:
    """The rows the matrix lists for a "Mostrar" option (it never changes the KPIs or the cards)."""
    allowed = _SHOWN_ESTADOS.get(show, _SHOWN_ESTADOS[SHOW_ALERTA_ANORMAL])
    return [row for row in rows if row["estado"] in allowed]


def matrix_rows(rows: Iterable[dict], config: AnalysisConfig, *, include_all: bool = False,
                today: Optional[date] = None) -> List[dict]:
    """The rows of the matrix with everything the table needs (days, levels, counts, trend), in the
    default order: Anormal, Alerta, Normal; within an estado more Condenatorio first, then more
    Marginal; then unit and component for a stable order."""
    result = []
    for row in rows:
        breaches = active_breaches(row, include_all)
        cond = sum(1 for b in breaches if b["level"] == CONDENATORIO)
        days = days_since(row["sample_date"], today)
        result.append({
            **{k: row[k] for k in ("unit_id", "component", "estado", "anomaly", "sample_date", "prev_estado",
                                   "component_hours", "oil_hours")},
            "days": days, "stale": is_stale(days, config),
            "trend": trend_of(row["estado"], row["prev_estado"]),
            "n_essays": len(breaches), "n_cond": cond, "n_marg": len(breaches) - cond,
            "levels": {b["essay"]: b["level"] for b in breaches},
        })
    return sorted(result, key=lambda r: (-RANK[r["estado"]], -r["n_cond"], -r["n_marg"],
                                         alpha_key(r["unit_id"]), alpha_key(r["component"])))


def _sort_key(column: str):
    """The value a header sorts a matrix row by; None means "nothing to sort on" (always last)."""
    if column.startswith(ESSAY_PREFIX):
        essay = column[len(ESSAY_PREFIX):]
        return lambda r: LEVEL_RANK.get(r["levels"].get(essay))
    keys = {
        "unit": lambda r: (alpha_key(r["unit_id"]), alpha_key(r["component"])),
        "estado": lambda r: RANK[r["estado"]],
        "anomaly": lambda r: alpha_key(r["anomaly"]) if r["anomaly"] else None,
        "essays": lambda r: (r["n_cond"], r["n_marg"]),
        "last": lambda r: r["days"],
        "trend": lambda r: TREND_RANK.get(r["trend"]),
        "component_hours": lambda r: r["component_hours"],
        "oil_hours": lambda r: r["oil_hours"],
    }
    return keys.get(column)


SORT_COLUMNS = ("unit", "estado", "anomaly", "essays", "last", "trend", "component_hours", "oil_hours")


def sort_matrix(rows: List[dict], column: Optional[str], descending: bool = False) -> List[dict]:
    """The matrix rows (already in the default order) re-ordered by one column. A row with nothing to
    sort on (no hours, no breach of that essay...) goes last in either direction, and equal rows keep
    their default order."""
    key = _sort_key(column) if column else None
    if key is None:
        return list(rows)
    present = [r for r in rows if key(r) is not None]
    missing = [r for r in rows if key(r) is None]
    return sorted(present, key=key, reverse=descending) + missing
