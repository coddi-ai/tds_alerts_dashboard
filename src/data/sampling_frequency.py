"""Oil sampling frequency: which units and components are due a new sample.

Feeds the Monitor de Aceite > Panel de Frecuencia. Everything is derived from the client's
`classified.parquet` plus `config/sampling_frequency.yaml` (intervals, thresholds and the
machine/component -> group mapping, owned by the dashboard team). Nothing here is stored: the
days since the last sample are computed against "today" every time the panel renders, so changing
the configuration or the date changes the result without a pipeline run.

No Dash import: the rules are tested on their own (tests/test_sampling_frequency.py).

Row identity is the (unit, component) pair. `component` is the oil data's own `componentName`
(so a "mando final" mapping covers its left and right side); a unit that was never sampled for a
mapped component has no `componentName` of its own, so the normalized name stands in for it.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yaml

from shared.severity import classify_severity

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "sampling_frequency.yaml"

# Row states, in the order the panel lists them by default (see `urgency_rank`).
SOLICITAR = "solicitar"        # Solicitar muestra: the interval is used up (>= 100 %)
SIN_MUESTRA = "sin_muestra"    # Sin muestra: a mapped component this unit was never sampled for
PROXIMA = "proxima"            # Próxima a vencer: 80 % up to 100 %
AL_DIA = "al_dia"              # Al día: below 80 %
STATUSES = (SOLICITAR, SIN_MUESTRA, PROXIMA, AL_DIA)
_URGENCY = {status: rank for rank, status in enumerate(STATUSES)}

# The severity tier that colors each state (shared/severity.py). "Sin muestra" is not a severity.
SEVERITY_BY_STATUS = {SOLICITAR: "alto", PROXIMA: "atencion", AL_DIA: "bajo"}
_STATUS_BY_SEVERITY = {tier: status for status, tier in SEVERITY_BY_STATUS.items()}

DEFAULT_PROXIMA_PCT = 80.0
DEFAULT_VENCIDA_PCT = 100.0
_DISPLAY_TIMEZONE = "America/Santiago"


class FrequencyConfigError(ValueError):
    """The frequency configuration file is missing or malformed."""


@dataclass(frozen=True)
class Group:
    key: str
    days: int


@dataclass(frozen=True)
class FrequencyConfig:
    groups: Dict[str, Group]
    mapping: Dict[Tuple[str, str], str]   # (machine, component) normalized -> group key
    proxima_pct: float = DEFAULT_PROXIMA_PCT
    vencida_pct: float = DEFAULT_VENCIDA_PCT

    def ordered_groups(self) -> List[Group]:
        """Groups from the shortest interval to the longest (ties by key)."""
        return sorted(self.groups.values(), key=lambda g: (g.days, g.key))

    def components_by_machine(self) -> Dict[str, Dict[str, str]]:
        by_machine: Dict[str, Dict[str, str]] = {}
        for (machine, component), group in self.mapping.items():
            by_machine.setdefault(machine, {})[component] = group
        return by_machine


def normalize_name(value) -> str:
    """`Mando Final ` -> `mando final`; accents, case and repeated spaces never separate two names."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.strip().casefold())


# ---------------------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------------------

_config_cache: Dict[Path, Tuple[int, FrequencyConfig]] = {}


def parse_config(raw) -> FrequencyConfig:
    """Validate the parsed YAML and turn it into a FrequencyConfig (raises FrequencyConfigError)."""
    if not isinstance(raw, dict):
        raise FrequencyConfigError("la configuración debe ser un mapa con 'groups' y 'mapping'")

    groups: Dict[str, Group] = {}
    for key, body in (raw.get("groups") or {}).items():
        days = body.get("days") if isinstance(body, dict) else body
        if isinstance(days, bool) or not isinstance(days, (int, float)) or days <= 0 or int(days) != days:
            raise FrequencyConfigError(f"el grupo '{key}' necesita un intervalo 'days' entero y positivo")
        groups[str(key)] = Group(str(key), int(days))
    if not groups:
        raise FrequencyConfigError("falta al menos un grupo en 'groups'")

    thresholds = raw.get("thresholds") or {}
    proxima = float(thresholds.get("proxima_pct", DEFAULT_PROXIMA_PCT))
    vencida = float(thresholds.get("vencida_pct", DEFAULT_VENCIDA_PCT))
    if not 0 < proxima <= vencida:
        raise FrequencyConfigError("los umbrales deben cumplir 0 < proxima_pct <= vencida_pct")

    mapping: Dict[Tuple[str, str], str] = {}
    for machine, components in (raw.get("mapping") or {}).items():
        if not isinstance(components, dict):
            raise FrequencyConfigError(f"'mapping.{machine}' debe asignar componentes a grupos")
        for component, group in components.items():
            if str(group) not in groups:
                raise FrequencyConfigError(f"'{machine} / {component}' usa el grupo '{group}', que no existe")
            mapping[(normalize_name(machine), normalize_name(component))] = str(group)
    return FrequencyConfig(groups=groups, mapping=mapping, proxima_pct=proxima, vencida_pct=vencida)


def load_config(path: Optional[Path] = None) -> FrequencyConfig:
    """The configuration, re-read whenever the file changes (so edits need no restart)."""
    path = Path(path or CONFIG_PATH)
    try:
        stamp = path.stat().st_mtime_ns
    except OSError as exc:
        raise FrequencyConfigError(f"no se encontró {path.name}") from exc
    cached = _config_cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FrequencyConfigError(f"{path.name} no es un YAML válido: {exc}") from exc
    config = parse_config(raw)
    _config_cache[path] = (stamp, config)
    return config


def local_today() -> date:
    """Today's calendar date where the plant is (the server may run in UTC)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(_DISPLAY_TIMEZONE)).date()
    except Exception:  # pragma: no cover - no tz database: fall back to the server's own date
        return date.today()


# ---------------------------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------------------------

def interval_consumed_pct(days_since: int, group_days: int) -> float:
    """Días / group days, as a percentage (unrounded: this is what classification uses)."""
    return days_since * 100.0 / group_days


def classify_interval(pct: float, config: FrequencyConfig) -> str:
    """Al día / Próxima a vencer / Solicitar muestra for an Intervalo Consumido percentage."""
    tier = classify_severity(pct, low_max=config.proxima_pct, high_min=config.vencida_pct)
    return _STATUS_BY_SEVERITY[tier]


def urgency_rank(status: str) -> int:
    return _URGENCY.get(status, len(_URGENCY))


ROW_COLUMNS = [
    "unit_id", "machine", "site", "component", "component_normalized", "group", "group_days",
    "last_sample", "days_since", "interval_pct", "due_date", "days_to_due", "avg_hist", "status",
]


def _empty_rows() -> pd.DataFrame:
    return pd.DataFrame({column: [] for column in ROW_COLUMNS})


def build_frequency_rows(classified: pd.DataFrame, config: FrequencyConfig, today: Optional[date] = None) -> pd.DataFrame:
    """One row per unit + component of the client that the configuration maps to a group.

    `classified` is the client's classified oil frame. Rows are returned in no particular order;
    see `sort_rows`. Sampled rows carry the last sample, the days since it, the interval consumed,
    the limit date and the historical average; "Sin muestra" rows carry none of those.
    """
    if classified is None or classified.empty or not config.mapping:
        return _empty_rows()
    today = today or local_today()
    needed = {"unitId", "machineName", "componentName", "sampleDate"}
    if not needed.issubset(classified.columns):
        return _empty_rows()

    df = pd.DataFrame({
        "unit_id": classified["unitId"],
        "machine": classified["machineName"],
        "site": classified["site"] if "site" in classified.columns else None,
        "component": classified["componentName"],
        "component_normalized": (classified["componentNameNormalized"]
                                 if "componentNameNormalized" in classified.columns else classified["componentName"]),
        "sample_date": pd.to_datetime(classified["sampleDate"], errors="coerce"),
        "days_prev": (pd.to_numeric(classified["daysSincePrevious"], errors="coerce")
                      if "daysSincePrevious" in classified.columns else float("nan")),
    })
    df = df.dropna(subset=["unit_id", "machine", "component", "sample_date"])
    if df.empty:
        return _empty_rows()

    df["machine_key"] = df["machine"].map(normalize_name)
    df["component_key"] = df["component_normalized"].map(normalize_name)
    # The unit's machine type and site never change; the first row speaks for it.
    units = df.drop_duplicates("unit_id").set_index("unit_id")[["machine", "machine_key", "site"]]

    mapped_group = [config.mapping.get(pair) for pair in zip(df["machine_key"], df["component_key"])]
    df["group"] = mapped_group
    sampled = df[df["group"].notna()]

    group_days = {key: group.days for key, group in config.groups.items()}
    today_ts = pd.Timestamp(today)

    pairs = sampled.groupby(["unit_id", "component"], sort=False).agg(
        last_sample=("sample_date", "max"), group=("group", "first"),
        component_normalized=("component_normalized", "first"), avg_hist=("days_prev", "mean"),
    ).reset_index()
    pairs["last_sample"] = pairs["last_sample"].dt.normalize()
    pairs["group_days"] = pairs["group"].map(group_days)
    # A sample dated in the future is a data slip: it counts as taken today, not as a negative age.
    pairs["days_since"] = (today_ts - pairs["last_sample"]).dt.days.clip(lower=0)
    pairs["interval_pct"] = pairs["days_since"] * 100.0 / pairs["group_days"]
    pairs["due_date"] = pairs["last_sample"] + pd.to_timedelta(pairs["group_days"], unit="D")
    pairs["days_to_due"] = pairs["group_days"] - pairs["days_since"]
    pairs["status"] = pairs["interval_pct"].map(lambda pct: classify_interval(pct, config))
    pairs["machine"] = pairs["unit_id"].map(units["machine"])
    pairs["site"] = pairs["unit_id"].map(units["site"])
    rows: List[dict] = pairs[ROW_COLUMNS].to_dict("records")

    # "Sin muestra": a mapped component this unit has no row for, provided the client's fleet of that
    # machine type does have it (otherwise the name is just spelled differently in this client).
    fleet_has = sampled.groupby("machine_key")["component_key"].agg(set).to_dict()
    unit_has = sampled.groupby("unit_id")["component_key"].agg(set).to_dict()
    expected = config.components_by_machine()
    for unit_id, unit in units.iterrows():
        listed = expected.get(unit["machine_key"], {})
        for component_key, group in listed.items():
            if component_key in unit_has.get(unit_id, set()) or component_key not in fleet_has.get(unit["machine_key"], set()):
                continue
            rows.append({
                "unit_id": unit_id, "machine": unit["machine"], "site": unit["site"],
                "component": component_key, "component_normalized": component_key,
                "group": group, "group_days": group_days[group],
                "last_sample": pd.NaT, "days_since": None, "interval_pct": float("nan"),
                "due_date": pd.NaT, "days_to_due": None, "avg_hist": None, "status": SIN_MUESTRA,
            })

    if not rows:
        return _empty_rows()
    result = pd.DataFrame(rows, columns=ROW_COLUMNS)
    result["days_since"] = result["days_since"].astype("Int64")
    result["days_to_due"] = result["days_to_due"].astype("Int64")
    result["avg_hist"] = result["avg_hist"].astype("Float64")
    return result


# ---------------------------------------------------------------------------------------------
# Filtering, ordering, summaries
# ---------------------------------------------------------------------------------------------

def filter_rows(rows: pd.DataFrame, site=None, fleet=None, component=None, group=None, status=None) -> pd.DataFrame:
    """Rows matching the panel's filters; a falsy filter does not restrict."""
    if rows.empty:
        return rows
    mask = pd.Series(True, index=rows.index)
    if site:
        mask &= rows["site"] == site
    if fleet:
        mask &= rows["machine"] == fleet
    if component:
        mask &= rows["component"] == component
    if group:
        mask &= rows["group"] == group
    if status:
        mask &= rows["status"] == status
    return rows[mask]


def sort_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """The components in the order a unit's detail lists them.

    Solicitar muestra first (highest Intervalo Consumido first), then Sin muestra, Próxima a vencer and
    Al día (each by highest Intervalo Consumido). Ties fall back to the unit and component so the order
    is deterministic.
    """
    if rows.empty:
        return rows
    frame = rows.assign(_urgency=rows["status"].map(urgency_rank),
                        _pct=-rows["interval_pct"].astype("float64"))
    ordered = frame.sort_values(["_urgency", "_pct", "unit_id", "component"], na_position="last", kind="mergesort")
    return ordered.drop(columns=["_urgency", "_pct"])


# ---------------------------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------------------------
#
# The unit is the primary row of the panel; its components are the detail. A unit summary is a
# plain dict (JSON-safe, so it can sit in a dcc.Store as is) computed over the rows it is given:
# with the filters applied, M is the number of *matching* components and every figure follows.

def _text_date(value) -> Optional[str]:
    return None if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")


def summarize_units(rows: pd.DataFrame) -> List[dict]:
    """One summary per unit of `rows`, in the default order (see `sort_units`).

    Keys: `unit_id`, `machine`, `site`; `status` (the worst component status, in the order Solicitar
    muestra, Sin muestra, Próxima a vencer, Al día); `total` (components, Sin muestra included) and
    one count per status (`solicitar`, `sin_muestra`, `proxima`, `al_dia`); `max_pct` (the highest
    Intervalo Consumido); `late_component`, `late_days_to_due`, `late_pct` ("Más Atrasado": the
    overdue component with the highest Intervalo Consumido or, with none overdue, the one nearest to
    expire; None without a sampled component); `latest_sample` and `latest_days` (the most recent
    Última Muestra of the unit and its age in days).
    """
    if rows is None or rows.empty:
        return []
    units: List[dict] = []
    for unit_id, group in rows.groupby("unit_id", sort=False):
        statuses = group["status"].tolist()
        counts = {status: statuses.count(status) for status in STATUSES}
        sampled = group[group["status"] != SIN_MUESTRA].assign(
            _pct=lambda frame: frame["interval_pct"].astype("float64"),
            _due=lambda frame: frame["days_to_due"].astype("float64"),
        )
        unit = {
            "unit_id": unit_id, "machine": group["machine"].iloc[0],
            "site": None if pd.isna(group["site"].iloc[0]) else group["site"].iloc[0],
            "status": min(statuses, key=urgency_rank), "total": len(statuses),
            "solicitar": counts[SOLICITAR], "sin_muestra": counts[SIN_MUESTRA],
            "proxima": counts[PROXIMA], "al_dia": counts[AL_DIA],
            "max_pct": None, "late_component": None, "late_days_to_due": None, "late_pct": None,
            "latest_sample": None, "latest_days": None,
        }
        if not sampled.empty:
            overdue = sampled[sampled["status"] == SOLICITAR]
            if not overdue.empty:
                late = overdue.sort_values(["_pct", "component"], ascending=[False, True], kind="mergesort").iloc[0]
            else:
                late = sampled.sort_values(["_due", "_pct", "component"], ascending=[True, False, True],
                                           kind="mergesort").iloc[0]
            unit.update(
                max_pct=float(sampled["_pct"].max()),
                late_component=late["component"], late_days_to_due=int(late["_due"]), late_pct=float(late["_pct"]),
                latest_sample=_text_date(sampled["last_sample"].max()), latest_days=int(sampled["days_since"].min()),
            )
        units.append(unit)
    return sort_units(units)


def _default_order(unit: dict) -> tuple:
    # Most components to request first; ties by the highest Intervalo Consumido (a unit with none sorts last).
    pct = unit["max_pct"] if unit["max_pct"] is not None else -1.0
    return (-unit["solicitar"], -pct, unit["unit_id"].casefold(), unit["unit_id"])


# Sortable columns of the unit list (column id -> sort key; None sorts last in either direction).
UNIT_SORT_KEYS = {
    "unit_id": lambda unit: unit["unit_id"].casefold(),
    "status": lambda unit: urgency_rank(unit["status"]),
    "pending": lambda unit: (unit["solicitar"], unit["total"]),
    "late": lambda unit: unit["late_days_to_due"],        # most overdue first when ascending
    "latest": lambda unit: unit["latest_sample"],         # ISO dates sort as text
}


def sort_units(units: List[dict], column: Optional[str] = None, ascending: bool = True) -> List[dict]:
    """The units in the default order (no column given) or sorted by one column.

    Default order: most components in Solicitar muestra first, ties by the highest Intervalo Consumido.
    A column sort keeps the default order among equal values, and units with nothing to sort on (no
    sampled component) go last whichever the direction.
    """
    ordered = sorted(units, key=_default_order)
    key = UNIT_SORT_KEYS.get(column or "")
    if key is None:
        return ordered
    valued = [unit for unit in ordered if key(unit) is not None]
    missing = [unit for unit in ordered if key(unit) is None]
    valued.sort(key=key, reverse=not ascending)           # a reversed sort is still stable
    return valued + missing


def status_counts(rows: pd.DataFrame) -> Dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    if not rows.empty:
        for status, count in rows["status"].value_counts().items():
            counts[status] = int(count)
    return counts


@dataclass(frozen=True)
class GroupSummary:
    group: Group
    total: int
    overdue: int                   # rows in Solicitar muestra
    components: List[str]          # normalized names, sorted
    avg_between_samples: Optional[float]


def group_summaries(rows: pd.DataFrame, config: FrequencyConfig) -> List[GroupSummary]:
    """One summary per configured group, over the given (already filtered) rows."""
    summaries = []
    for group in config.ordered_groups():
        mine = rows[rows["group"] == group.key] if not rows.empty else rows
        if mine.empty:
            summaries.append(GroupSummary(group, 0, 0, [], None))
            continue
        averages = mine["avg_hist"].dropna().astype("float64")
        summaries.append(GroupSummary(
            group=group,
            total=len(mine),
            overdue=int((mine["status"] == SOLICITAR).sum()),
            components=sorted({str(c) for c in mine["component_normalized"].dropna()}),
            avg_between_samples=float(averages.mean()) if len(averages) else None,
        ))
    return summaries


def data_as_of(classified: pd.DataFrame) -> Optional[pd.Timestamp]:
    """The latest `reportDate` of the client ("Datos al ..."), or None without reports."""
    if classified is None or classified.empty or "reportDate" not in classified.columns:
        return None
    latest = pd.to_datetime(classified["reportDate"], errors="coerce").max()
    return None if pd.isna(latest) else latest.normalize()


def format_days(value: Optional[float]) -> str:
    """`N d` for a number of days (whole days, rounded), or an em dash without one."""
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return "—"
    return f"{int(round(float(value)))} d"
