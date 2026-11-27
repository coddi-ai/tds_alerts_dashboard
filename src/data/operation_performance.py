"""Operación y rendimiento (OP-PE): rimpull and performance of haul trucks against the manufacturer curve.

Feeds Monitoreo > Operación y rendimiento. The OP-PE weekly pipeline computes everything (bronze ->
silver -> gold) and uploads it to S3; the S3 downloader mirrors it under

    data/operation-performance/<client>/gold/WeekNNYearYYYY/*.parquet      panels
    data/operation-performance/<client>/silver/WeekNNYearYYYY/calidad.parquet  data quality

A week folder is complete only when it holds ``manifest.json`` (the pipeline writes it last), so a
week without one is never listed. The dashboard does not recompute the method: it reads, filters
and aggregates the gold tables. The rules (decision thresholds, base population, main ramp) are the
ones of the OP-PE specification, summarized in documentation/operation_performance/data_contracts.md.

No Dash import: the rules are tested on their own (tests/test_operation_performance.py).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.data.catalog import dashboard_data_root
from src.utils.logger import get_logger

logger = get_logger(__name__)

ROOT_FOLDER = "operation-performance"
GOLD, SILVER = "gold", "silver"
MANIFEST = "manifest.json"

# Gold tables the dashboard reads. `frenos` only exists for CDA (Cat 789C, brake temperatures);
# `potencia` and `escape` only for Capstone (Komatsu 830E, engine power and per-cylinder exhaust).
GOLD_TABLES = ("camiones", "pasadas_eval", "camion_dia", "rampas", "curvas", "frenos", "potencia", "escape")
QUALITY_TABLE = "calidad"   # silver data quality per truck and day
# Silver 100 m segments: the GPS position of every climb, for the map of ramps. Only these columns
# are read (the file is 10-45 MB per week).
TRAMOS_TABLE = "tramos"
TRAMOS_COLUMNS = ("pasada_id", "tramo", "lat", "lon", "pend_pct", "v_kmh",
                  # engine effort per 100 m, for the unit's map (potencia only exists for Capstone)
                  "carga_motor_pct_media", "rpm_media", "potencia_hp_media")
ROLLING_RESISTANCE = 1.5    # % added to the grade for the force a climb requires (OP-PE specification)

# pasadas_eval has 78-93 columns; the panels need these (the ones missing for a client are skipped).
PASADAS_COLUMNS = (
    "pasada_id", "unidad", "flota", "modelo", "sentido", "estado", "capacidad", "rampa_id", "dia", "turno",
    "pend_pct", "tr_pct", "dist_m", "v_kmh", "gvw_t", "fuerza_req_t", "iv", "iv_rel", "hp_pendiente",
    "v_max_retardo_kmh", "curva_retardo", "exceso_retardo", "bajo_flota", "causa", "payload_t_media",
    # Operation: trips, time, engine load and the minutes each climb lost against the fleet.
    "viaje", "dur_s", "carga_motor_pct_media", "min_perdidos_flota",
    # Operational stress: engine effort and fuel (both clients), engine power (Capstone) and the
    # apparent mass Capstone's pipeline estimates for lack of payload.
    "rpm_media", "combustible_lh_media", "potencia_hp_media", "masa_aparente_t",
)

# --- Decision (camiones.decision), by the truck's median relative speed index -------------------
CONFORME = "Conforme"
SEGUIMIENTO = "Seguimiento"
REVISAR = "Revisar"
SIN_DATOS = "Sin datos suficientes"
DECISIONS = (CONFORME, SEGUIMIENTO, REVISAR, SIN_DATOS)
# The pipeline names the best decision "Fondo de mina"; the dashboard shows it as "Conforme". The
# gold table is renamed on load (load_week), so every panel, filter and test sees one name.
PIPELINE_DECISION_NAMES = {"Fondo de mina": CONFORME}
IV_REL_OK = 1.00            # >= : Conforme
IV_REL_REVIEW = 0.97        # <  : Revisar (between both: Seguimiento)
MIN_CLIMBS = 10             # fewer loaded full-throttle climbs in the week: Sin datos suficientes

# Severity tier (shared/severity.py) of each decision: one severity scale for the whole dashboard.
DECISION_TIER = {CONFORME: "bajo", SEGUIMIENTO: "atencion", REVISAR: "alto", SIN_DATOS: None}

# Causes that do not point at the engine (CDA: road, traffic or load; Capstone: electric drive,
# load or road). They are drawn neutral so the engine causes stand out.
NEUTRAL_CAUSE_PREFIXES = ("Sin causa", "Fuera del motor")

# Metrics of camion_dia offered by the daily trend, in display order. Each client has its own
# signals; only the columns present in the data are offered.
TREND_METRICS = (
    "iv_rel_p50", "iv_p50", "hp_pendiente_p50", "eficiencia_p50", "pasadas",
    # CDA (Cat 789C)
    "payload_t_media", "boost_kpa_media", "rpm_media", "slip_trn_media", "slip_lockup_media",
    "escape_izq_c_media", "escape_der_c_media",
    # Capstone (Komatsu 830E)
    "potencia_hp_media", "imp_psi_media", "turbo_rpm_media", "egt_disp_c_media", "refrigerante_c_media",
)

QUALITY_COLUMNS = ("horas_con_gps", "horas_con_datos", "horas_en_movimiento")

MAP_RAMPS = 30              # climb ramps drawn on the map (the ones with most loaded full-throttle climbs)
MIN_SEGMENT_CLIMBS = 3      # a 100 m point of a ramp is drawn when at least this many climbs passed it
MIN_UNIT_RAMP_CLIMBS = 3    # a unit's ramp (or ramp point) counts when the unit climbed it this many times
SCATTER_SAMPLE = 4000       # passes drawn on a scatter at most (fixed random sample)
NOMINAL_ENGINE_HP = 2500    # Komatsu 830E gross power (Capstone potencia panel)
ESCAPE_ALERT_C = 30         # |deviation vs fleet| above it: alert
ESCAPE_SCALE_C = 60         # fixed color scale of the exhaust heat map (+-)

_WEEK_RE = re.compile(r"^Week(\d{1,2})Year(\d{4})$")


# ------------------------------------------------------------------------------------------------
# Weeks
# ------------------------------------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class Week:
    """A week folder (`WeekNNYearYYYY`): ISO week in Chile time, Monday to Sunday."""

    year: int
    number: int

    @property
    def folder(self) -> str:
        return f"Week{self.number:02d}Year{self.year}"

    @property
    def iso(self) -> str:
        return f"{self.year}-W{self.number:02d}"

    @property
    def monday(self) -> date:
        return date.fromisocalendar(self.year, self.number, 1)

    @property
    def sunday(self) -> date:
        return self.monday + timedelta(days=6)

    @classmethod
    def parse(cls, folder: str) -> Optional["Week"]:
        """The week of a folder name, or None when it is not one (`Week7Year2026` is accepted)."""
        match = _WEEK_RE.match(str(folder or "").strip())
        if not match:
            return None
        number, year = int(match.group(1)), int(match.group(2))
        try:
            date.fromisocalendar(year, number, 1)
        except ValueError:
            return None
        return cls(year=year, number=number)


def client_root(client: str, root=None) -> Path:
    """`<data root>/operation-performance/<client>` (the client folder is lower case)."""
    return dashboard_data_root(root) / ROOT_FOLDER / str(client or "").strip().lower()


def available_weeks(client: str, layer: str = GOLD, root=None) -> List[Week]:
    """Complete weeks of a client and layer (folders with manifest.json), oldest first."""
    base = client_root(client, root) / layer
    if not client or not base.is_dir():
        return []
    weeks = []
    for folder in base.iterdir():
        week = Week.parse(folder.name)
        if week is not None and folder.is_dir() and (folder / MANIFEST).is_file():
            weeks.append(week)
    return sorted(set(weeks))


def latest_week(client: str, root=None) -> Optional[Week]:
    weeks = available_weeks(client, GOLD, root)
    return weeks[-1] if weeks else None


def read_manifest(client: str, week: Week, layer: str = GOLD, root=None) -> dict:
    """The week's manifest (cliente, semana, lunes, generado_utc, archivos...); {} if unreadable."""
    path = client_root(client, root) / layer / week.folder / MANIFEST
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------------------------------------
# Tables
# ------------------------------------------------------------------------------------------------

@lru_cache(maxsize=96)
def _read_parquet_cached(path: str, mtime_ns: int, size: int, columns: Optional[Tuple[str, ...]]) -> pd.DataFrame:
    """Keyed by (mtime, size): a week the weekly run rewrites is read again, an untouched one never."""
    if columns is not None:
        import pyarrow.parquet as pq

        present = set(pq.read_schema(path).names)
        columns = tuple(c for c in columns if c in present)
    frame = pd.read_parquet(path, columns=list(columns) if columns is not None else None)
    return _normalize(frame)


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    """`dia` as a datetime (it is stored as a date object), unit ids as text."""
    if "dia" in frame.columns:
        frame["dia"] = pd.to_datetime(frame["dia"], errors="coerce")
    for column in ("unidad", "flota", "modelo"):
        if column in frame.columns:
            frame[column] = frame[column].astype("string").astype(object)
    return frame


def load_table(client: str, week: Week, name: str, layer: str = GOLD,
               columns: Optional[Tuple[str, ...]] = None, root=None) -> Optional[pd.DataFrame]:
    """One table of a week, or None when the client does not have it (e.g. `frenos` for Capstone).
    The frame is a copy: callers may filter or add columns freely."""
    path = client_root(client, root) / layer / week.folder / f"{name}.parquet"
    try:
        stat = path.stat()
    except OSError:
        return None
    try:
        return _read_parquet_cached(str(path), stat.st_mtime_ns, stat.st_size, columns).copy()
    except Exception:
        logger.exception("Operación y rendimiento: could not read %s", path)
        return None


@dataclass
class WeekData:
    """Every table one week of the panels reads. A table the client does not have is None."""

    client: str
    week: Week
    manifest: dict = field(default_factory=dict)
    camiones: Optional[pd.DataFrame] = None
    pasadas: Optional[pd.DataFrame] = None
    camion_dia: Optional[pd.DataFrame] = None
    rampas: Optional[pd.DataFrame] = None
    curvas: Optional[pd.DataFrame] = None
    frenos: Optional[pd.DataFrame] = None
    potencia: Optional[pd.DataFrame] = None
    escape: Optional[pd.DataFrame] = None
    calidad: Optional[pd.DataFrame] = None

    @property
    def fleets(self) -> List[str]:
        if self.camiones is None or "flota" not in self.camiones:
            return []
        return sorted(self.camiones["flota"].dropna().unique().tolist())

    @property
    def models(self) -> List[str]:
        """Truck models with loaded full-throttle climbs (one manufacturer curve each)."""
        climbs = base_climbs(self.pasadas)
        if climbs.empty or "modelo" not in climbs:
            return []
        return sorted(climbs["modelo"].dropna().unique().tolist())

    @property
    def measured_payload(self) -> bool:
        """CDA weighs every cycle; Capstone has no payload and uses the nominal load of the spec sheet."""
        return self.pasadas is not None and "payload_t_media" in self.pasadas.columns


def load_week(client: str, week: Week, root=None) -> WeekData:
    """All the tables of a week (gold) plus its data quality (silver)."""
    data = WeekData(client=client, week=week, manifest=read_manifest(client, week, GOLD, root))
    for name in GOLD_TABLES:
        columns = PASADAS_COLUMNS if name == "pasadas_eval" else None
        frame = load_table(client, week, name, GOLD, columns, root)
        setattr(data, "pasadas" if name == "pasadas_eval" else name, frame)
    if data.camiones is not None and "decision" in data.camiones:
        data.camiones["decision"] = data.camiones["decision"].replace(PIPELINE_DECISION_NAMES)
    if (client_root(client, root) / SILVER / week.folder / MANIFEST).is_file():
        data.calidad = load_table(client, week, QUALITY_TABLE, SILVER, root=root)
    return data


def filter_fleet(data: WeekData, fleet: Optional[str]) -> WeekData:
    """The week restricted to one fleet (None / "all": every fleet). Tables without `flota` are
    restricted through their units; the curves through the fleet's truck models."""
    if not fleet or fleet == "all" or data.camiones is None:
        return data
    units = set(data.camiones.loc[data.camiones["flota"] == fleet, "unidad"])

    def by_fleet(frame: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        if frame is None:
            return None
        if "flota" in frame.columns:
            return frame[frame["flota"] == fleet].copy()
        if "unidad" in frame.columns:
            return frame[frame["unidad"].isin(units)].copy()
        return frame

    pasadas = by_fleet(data.pasadas)
    curvas = data.curvas
    if curvas is not None and pasadas is not None and "modelo" in pasadas:
        curvas = curvas[curvas["modelo"].isin(set(pasadas["modelo"].dropna()))].copy()
    return replace(
        data,
        camiones=by_fleet(data.camiones), pasadas=pasadas, camion_dia=by_fleet(data.camion_dia),
        curvas=curvas, frenos=by_fleet(data.frenos), potencia=by_fleet(data.potencia),
        escape=by_fleet(data.escape), calidad=by_fleet(data.calidad),
    )


def load_history(client: str, fleet: Optional[str] = None, root=None) -> pd.DataFrame:
    """camion_dia of every complete week, with its `semana` (camion_dia does not carry it). A day the
    weekly run wrote in two weeks keeps the newest week's row."""
    frames = []
    for week in available_weeks(client, GOLD, root):
        frame = load_table(client, week, "camion_dia", GOLD, root=root)
        if frame is not None and not frame.empty:
            frame["semana"] = week.folder
            frame["_orden"] = week.year * 100 + week.number
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    history = pd.concat(frames, ignore_index=True)
    history = (
        history.sort_values("_orden").drop_duplicates(["unidad", "dia"], keep="last")
        .drop(columns="_orden").sort_values(["unidad", "dia"]).reset_index(drop=True)
    )
    if fleet and fleet != "all" and "flota" in history:
        history = history[history["flota"] == fleet].reset_index(drop=True)
    return history


def load_weekly_history(client: str, upto: Optional[Week] = None, fleet: Optional[str] = None,
                        root=None) -> pd.DataFrame:
    """`camiones` of every complete week up to `upto` (included): one row per truck and week, with
    `semana` (folder), `semana_n` (ISO number), `lunes` and `mitad` (the week's Thursday, where a
    weekly point is drawn). The decision carries the dashboard's name ("Conforme")."""
    frames = []
    for week in available_weeks(client, GOLD, root):
        if upto is not None and week > upto:
            continue
        frame = load_table(client, week, "camiones", GOLD, root=root)
        if frame is None or frame.empty:
            continue
        frame["semana"] = week.folder
        frame["semana_n"] = week.number
        frame["lunes"] = pd.Timestamp(week.monday)
        frame["mitad"] = pd.Timestamp(week.monday) + pd.Timedelta(days=3)
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    history = pd.concat(frames, ignore_index=True)
    if "decision" in history:
        history["decision"] = history["decision"].replace(PIPELINE_DECISION_NAMES)
    if fleet and fleet != "all" and "flota" in history:
        history = history[history["flota"] == fleet]
    return history.sort_values(["lunes", "unidad"]).reset_index(drop=True)


# ------------------------------------------------------------------------------------------------
# Rules of the panels
# ------------------------------------------------------------------------------------------------

def base_climbs(pasadas: Optional[pd.DataFrame]) -> pd.DataFrame:
    """The population every truck is decided on: loaded climbs at full throttle
    (`sentido == "subida"`, `capacidad`, `estado == "cargado"`)."""
    if pasadas is None or pasadas.empty:
        return pd.DataFrame(columns=list(PASADAS_COLUMNS))
    mask = (
        (pasadas["sentido"] == "subida")
        & pasadas["capacidad"].fillna(False).astype(bool)
        & (pasadas["estado"] == "cargado")
    )
    return pasadas[mask]


def loaded_climbs(pasadas: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Every loaded climb (`sentido == "subida"`, `estado == "cargado"`), at full throttle or not: what
    the fleet did uphill, loaded."""
    if pasadas is None or pasadas.empty:
        return pd.DataFrame(columns=list(PASADAS_COLUMNS))
    return pasadas[(pasadas["sentido"] == "subida") & (pasadas["estado"] == "cargado")]


def _number(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _trips(frame: pd.DataFrame) -> int:
    """Trips of a set of passes: distinct (unit, `viaje`). 0 when the pipeline gave no trip id."""
    if frame.empty or "viaje" not in frame.columns:
        return 0
    return int(frame.dropna(subset=["viaje"]).drop_duplicates(["unidad", "viaje"]).shape[0])


def _loaded_tonnes(pasadas: Optional[pd.DataFrame]) -> Optional[float]:
    """Material moved on the trips with a loaded ramp pass: each trip's measured payload, summed. None
    without payload (Capstone) or without trip ids."""
    if pasadas is None or pasadas.empty or "payload_t_media" not in pasadas or "viaje" not in pasadas:
        return None
    loaded = pasadas[pasadas["estado"] == "cargado"].dropna(subset=["viaje"])
    payload = loaded.assign(_t=_number(loaded, "payload_t_media")).groupby(["unidad", "viaje"])["_t"].median().dropna()
    return float(payload.sum()) if not payload.empty else None


def week_kpis(camiones: Optional[pd.DataFrame], pasadas: Optional[pd.DataFrame]) -> Dict[str, object]:
    """The figures of "Resumen de la semana": performance tied to how much the fleet operated.

    - lost_minutes: minutes lost against the fleet median, summed over every truck; `lost_share`:
      those minutes over the time spent climbing loaded at full throttle;
    - trips: trips with a loaded climb on a ramp; `loss_per_trip_s`: seconds lost per trip;
    - km_loaded / hours_loaded: distance and time climbing loaded (at full throttle or not);
    - iv_weighted: IV of the full-throttle climbs weighted by their distance (the IV of the km the
      fleet climbed), next to its plain median `iv_median`; `km_base`: those climbs' distance;
    - tonnes: material moved on those trips when the client weighs every cycle (CDA), else None;
    - trucks, evaluated, to_review, follow_up: the decision counts.
    """
    camiones = camiones if camiones is not None else pd.DataFrame(columns=["decision", "min_perdidos_flota"])
    climbs = base_climbs(pasadas)
    loaded = loaded_climbs(pasadas)
    iv, dist = _number(climbs, "iv"), _number(climbs, "dist_m")
    weighted = iv.notna() & dist.gt(0)
    lost = float(pd.to_numeric(camiones["min_perdidos_flota"], errors="coerce").fillna(0).sum())
    base_hours = float(_number(climbs, "dur_s").sum()) / 3600
    trips = _trips(loaded)
    high = _high_load_hours(pasadas)
    ramp_hours = float(_number(pasadas, "dur_s").sum()) / 3600 if pasadas is not None and not pasadas.empty else 0.0
    return {
        "high_load_hours": float(high.sum()) if not high.empty else None,
        "high_load_share": float(high.sum()) / ramp_hours if not high.empty and ramp_hours > 0 else None,
        "high_load_top": (high.idxmax(), float(high.max())) if not high.empty and high.max() > 0 else None,
        "trucks": int(len(camiones)),
        "evaluated": int((camiones["decision"] != SIN_DATOS).sum()),
        "iv_median": float(iv.median()) if iv.notna().any() else None,
        "iv_weighted": float(np.average(iv[weighted], weights=dist[weighted])) if weighted.any() else None,
        "climbs": int(len(climbs)),
        "to_review": int((camiones["decision"] == REVISAR).sum()),
        "follow_up": int((camiones["decision"] == SEGUIMIENTO).sum()),
        "lost_minutes": lost,
        "lost_share": lost / (60 * base_hours) if base_hours > 0 else None,
        "trips": trips,
        "loss_per_trip_s": 60 * lost / trips if trips else None,
        "km_loaded": float(_number(loaded, "dist_m").sum()) / 1000,
        "km_base": float(dist.sum()) / 1000,
        "hours_loaded": float(_number(loaded, "dur_s").sum()) / 3600,
        "tonnes": _loaded_tonnes(pasadas),
    }


HIGH_ENGINE_LOAD = 90.0     # % engine load from which a ramp pass counts as engine stress


def _high_load_hours(pasadas: Optional[pd.DataFrame]) -> pd.Series:
    """Hours per unit on ramp passes (any direction or state) with the engine at HIGH_ENGINE_LOAD % or more.
    Empty without engine load or durations."""
    if pasadas is None or pasadas.empty or "carga_motor_pct_media" not in pasadas or "dur_s" not in pasadas:
        return pd.Series(dtype=float)
    high = _number(pasadas, "carga_motor_pct_media") >= HIGH_ENGINE_LOAD
    return (_number(pasadas, "dur_s").where(high, 0).groupby(pasadas["unidad"]).sum() / 3600)


# --- Operational stress per unit ---------------------------------------------------------------
# Every figure grows with how hard the truck was worked. Shown only when the client has its signal.
STRESS_METRICS = (
    "viajes",           # trips with a loaded climb on a ramp (vueltas)
    "km_rampa",         # km on ramps, any direction or state
    "carga_t",          # load: measured payload per trip (CDA) or apparent mass (Capstone, estimated)
    "h_carga_alta",     # hours with the engine at >= HIGH_ENGINE_LOAD %
    "carga_motor",      # engine load on climbs, time-weighted (%)
    "potencia_hp",      # engine power on loaded climbs, time-weighted (Capstone)
    "rpm",              # engine rpm on loaded climbs, time-weighted
    "combustible_l_km",  # fuel per km climbed loaded
    "pend_subida",      # median grade of its loaded climbs: how demanding the routes it was sent to are
)
PERFORMANCE_METRICS = ("iv_rel_p50", "iv_p50", "s_perdidos_viaje")
# Pass-level variables the performance is binned by ("Desempeño según la carga").
LOAD_VARIABLES = ("carga_t", "pend_pct", "carga_motor_pct_media", "rpm_media", "potencia_hp_media")
# Pass-level performance behind each unit-level metric.
PASS_PERFORMANCE = {"iv_rel_p50": "iv_rel", "iv_p50": "iv", "s_perdidos_viaje": "s_perdidos"}
LOAD_BINS = 6


def load_column(pasadas: Optional[pd.DataFrame]) -> Optional[str]:
    """The pass column that measures how loaded a truck is: measured payload (CDA), else the apparent
    mass Capstone's pipeline estimates from power, grade and speed; None without either."""
    if pasadas is None:
        return None
    for column in ("payload_t_media", "masa_aparente_t"):
        if column in pasadas.columns and pasadas[column].notna().any():
            return column
    return None


def _weighted(values: pd.Series, weights: pd.Series, by: pd.Series) -> pd.Series:
    ok = values.notna() & weights.gt(0)
    num = (values * weights).where(ok).groupby(by).sum(min_count=1)
    den = weights.where(ok).groupby(by).sum(min_count=1)
    return num / den


def unit_stress(pasadas: Optional[pd.DataFrame], camiones: Optional[pd.DataFrame]) -> pd.DataFrame:
    """How hard each truck of `camiones` was worked in the week (STRESS_METRICS present in the data),
    next to its performance (PERFORMANCE_METRICS), `flota` and `decision`, and `indice_estres`: the mean
    of its stress figures each divided by its fleet's median (1 = worked like its fleet)."""
    if camiones is None or camiones.empty:
        return pd.DataFrame(columns=["unidad", "flota", "decision", "indice_estres"])
    table = camiones[["unidad", "flota", "decision", "iv_rel_p50", "iv_p50"]].copy().reset_index(drop=True)
    operation = unit_operation(pasadas, camiones)
    table = table.merge(operation[["unidad", "viajes", "s_perdidos_viaje"]], on="unidad", how="left")
    if pasadas is not None and not pasadas.empty:
        unit = pasadas["unidad"]
        dur = _number(pasadas, "dur_s")
        per_unit = pd.DataFrame({"km_rampa": _number(pasadas, "dist_m").groupby(unit).sum() / 1000})
        high = _high_load_hours(pasadas)
        if not high.empty:
            per_unit["h_carga_alta"] = high
        up = pasadas["sentido"] == "subida"
        per_unit["carga_motor"] = _weighted(_number(pasadas, "carga_motor_pct_media").where(up), dur, unit)
        loaded = loaded_climbs(pasadas)
        lu, ldur = loaded["unidad"], _number(loaded, "dur_s")
        if "potencia_hp_media" in loaded:
            per_unit["potencia_hp"] = _weighted(_number(loaded, "potencia_hp_media"), ldur, lu)
        per_unit["rpm"] = _weighted(_number(loaded, "rpm_media"), ldur, lu)
        liters = (_number(loaded, "combustible_lh_media") * ldur / 3600).groupby(lu).sum(min_count=1)
        km = _number(loaded, "dist_m").groupby(lu).sum() / 1000
        per_unit["combustible_l_km"] = liters / km.where(km > 0)
        per_unit["pend_subida"] = _number(loaded, "pend_pct").groupby(lu).median()
        column = load_column(pasadas)
        if column == "payload_t_media" and "viaje" in pasadas:
            trips = pasadas[pasadas["estado"] == "cargado"].dropna(subset=["viaje"])
            per_trip = _number(trips, column).groupby([trips["unidad"], trips["viaje"]]).median()
            per_unit["carga_t"] = per_trip.groupby(level=0).mean()
        elif column:
            per_unit["carga_t"] = _number(loaded, column).groupby(lu).median()
        table = table.join(per_unit, on="unidad")
    present = [m for m in STRESS_METRICS if m in table.columns and table[m].notna().any()]
    ratios = []
    for metric in present:
        median = table.groupby("flota")[metric].transform("median")
        ratios.append(table[metric] / median.where(median > 0))
    table["indice_estres"] = pd.concat(ratios, axis=1).mean(axis=1) if ratios else np.nan
    columns = ["unidad", "flota", "decision", *present, *PERFORMANCE_METRICS, "indice_estres"]
    return table[columns].reset_index(drop=True)


def stress_metrics(stress: pd.DataFrame) -> List[str]:
    """STRESS_METRICS present in a unit_stress table, in display order."""
    return [m for m in STRESS_METRICS if m in stress.columns]


def load_variables(pasadas: Optional[pd.DataFrame]) -> List[str]:
    """LOAD_VARIABLES this client has (carga_t only with payload or apparent mass)."""
    if pasadas is None or pasadas.empty:
        return []
    present = []
    for variable in LOAD_VARIABLES:
        column = load_column(pasadas) if variable == "carga_t" else variable
        if column and column in pasadas.columns and pasadas[column].notna().any():
            present.append(variable)
    return present


def performance_by_load(pasadas: Optional[pd.DataFrame], variable: str, metric: str = "iv_p50",
                        unit: Optional[str] = None, bins: int = LOAD_BINS) -> pd.DataFrame:
    """Loaded climbs cut in `bins` equal-count bins of a load variable (fleet quantiles): per bin its
    median `x`, the fleet's p25 / median / p75 of the pass performance behind `metric`, `n` climbs, and
    the unit's median (`unidad`, with `n_unidad`; NaN below MIN_UNIT_RAMP_CLIMBS climbs in the bin)."""
    columns = ["bin", "x", "p25", "p50", "p75", "n", "unidad", "n_unidad"]
    climbs = loaded_climbs(pasadas)
    column = load_column(pasadas) if variable == "carga_t" else variable
    if climbs.empty or not column or column not in climbs:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame({"unidad": climbs["unidad"], "x": _number(climbs, column)})
    if metric == "s_perdidos_viaje":
        frame["y"] = 60 * _number(climbs, "min_perdidos_flota")
    else:
        frame["y"] = _number(climbs, PASS_PERFORMANCE.get(metric, "iv"))
    frame = frame.dropna(subset=["x", "y"])
    if frame["x"].nunique() < 2:
        return pd.DataFrame(columns=columns)
    if frame["x"].nunique() <= bins:
        # A variable with few values (a constant payload, a rounded load): one group per value.
        frame["bin"] = frame["x"].rank(method="dense").astype(int) - 1
    else:
        frame["bin"] = pd.qcut(frame["x"], q=bins, labels=False, duplicates="drop")
    table = frame.groupby("bin").agg(x=("x", "median"), n=("y", "size"))
    quantiles = frame.groupby("bin")["y"].quantile([0.25, 0.5, 0.75]).unstack()
    table[["p25", "p50", "p75"]] = quantiles.values
    mine = frame[frame["unidad"] == unit].groupby("bin")["y"].agg(["median", "size"]) if unit else None
    if mine is not None and not mine.empty:
        table["unidad"] = mine["median"].where(mine["size"] >= MIN_UNIT_RAMP_CLIMBS)
        table["n_unidad"] = mine["size"]
    else:
        table["unidad"] = np.nan
        table["n_unidad"] = 0
    table["n_unidad"] = table["n_unidad"].fillna(0).astype(int)
    return table.reset_index()[columns]


BASELINE_WEEKS = 4          # the week's figures are compared with the mean of up to this many weeks before
BASELINE_KEYS = ("lost_minutes", "lost_share", "iv_weighted", "high_load_hours", "high_load_share", "km_loaded")


def kpi_baseline(client: str, week: Week, fleet: Optional[str] = None, n: int = BASELINE_WEEKS,
                 root=None) -> Optional[Dict[str, object]]:
    """The week's figures (week_kpis) averaged over the up to `n` complete weeks before `week`, same
    fleet: {key: mean, ..., "weeks": [Week, ...]}. None when there is no earlier week."""
    earlier = [w for w in available_weeks(client, GOLD, root) if w < week][-n:]
    values: Dict[str, list] = {key: [] for key in BASELINE_KEYS}
    used = []
    for previous in earlier:
        data = filter_fleet(load_week(client, previous, root), fleet)
        if data.camiones is None or data.pasadas is None:
            continue
        kpis = week_kpis(data.camiones, data.pasadas)
        for key in BASELINE_KEYS:
            if kpis.get(key) is not None:
                values[key].append(float(kpis[key]))
        used.append(previous)
    if not used:
        return None
    baseline: Dict[str, object] = {key: (float(np.mean(v)) if v else None) for key, v in values.items()}
    baseline["weeks"] = used
    return baseline


# How a figure compares with its baseline: which way is better, and the change (relative %, or absolute
# for an index) from which it counts as better / worth attention / bad. Tiers of shared/severity.py.
# Minutes lost and engine hours grow with how much the fleet worked, so they are compared as shares of
# the time (climbing at full throttle; on ramps). The distance is volume, not performance: its change
# is shown without a judgement (`better: None`).
KPI_TREND = {
    "lost_share": {"better": "down", "relative": True, "neutral": 0.05, "bad": 0.20},
    "iv_weighted": {"better": "up", "relative": True, "neutral": 0.01, "bad": 0.03},
    "high_load_share": {"better": "down", "relative": True, "neutral": 0.05, "bad": 0.15},
    "km_loaded": {"better": None, "relative": True, "neutral": 0.0, "bad": 0.0},
    # The unit under analysis (unit_figures): its indices, and what it lost; how much it operated
    # (climbs, trips, hours) and its engine load are shown with their change but no judgement.
    "iv_rel_p50": {"better": "up", "relative": True, "neutral": 0.01, "bad": 0.03},
    "iv_p50": {"better": "up", "relative": True, "neutral": 0.01, "bad": 0.03},
    "s_perdidos_viaje": {"better": "down", "relative": True, "neutral": 0.05, "bad": 0.20},
    "pasadas_capacidad": {"better": None, "relative": True, "neutral": 0.0, "bad": 0.0},
    "viajes": {"better": None, "relative": True, "neutral": 0.0, "bad": 0.0},
    "carga_motor": {"better": None, "relative": False, "neutral": 0.0, "bad": 0.0},
    "h_subida": {"better": None, "relative": True, "neutral": 0.0, "bad": 0.0},
}

LOSS_RATIO_REVIEW = 1.2     # seconds lost per trip over the fleet's median: worth attention from here
LOSS_RATIO_BAD = 1.5        # ... and bad from here


def kpi_level(key: str, value, reference=None) -> Optional[str]:
    """Where a figure stands on its own, whatever its trend: the relative IV by the decision thresholds
    (< 0,97 Revisar: alto; < 1,00 Seguimiento: atencion; else bajo); an IV against the curve by the
    same thresholds around 1; the seconds lost per trip, or the share of the climbing time lost, against
    `reference` (its fleet's median). None when the figure has no level rule (or no value)."""
    if value is None or pd.isna(value):
        return None
    if key in ("iv_rel_p50", "iv_p50", "iv_weighted"):
        if value < IV_REL_REVIEW:
            return "alto"
        return "atencion" if value < IV_REL_OK else "bajo"
    if key in ("s_perdidos_viaje", "lost_share") and reference is not None and pd.notna(reference) and reference > 0:
        ratio = float(value) / float(reference)
        if ratio >= LOSS_RATIO_BAD:
            return "alto"
        if ratio >= LOSS_RATIO_REVIEW:
            return "atencion"
        return "bajo" if ratio <= 1 else None
    return None


UNIT_FIGURES = ("iv_rel_p50", "iv_p50", "pasadas_capacidad", "min_perdidos_flota", "lost_share", "viajes",
                "s_perdidos_viaje", "carga_motor", "h_subida", "km_subida")


def unit_figures(camiones: Optional[pd.DataFrame], pasadas: Optional[pd.DataFrame],
                 unit: Optional[str]) -> Optional[Dict[str, float]]:
    """The unit's figures of one week (UNIT_FIGURES): its IVs, full-throttle climbs and minutes lost
    (camiones), `lost_share` (those minutes over its time climbing at full throttle) and what it
    operated (unit_operation). None when the unit has no row that week."""
    row = unit_row(camiones, unit)
    if row is None:
        return None
    figures = {key: (float(row[key]) if key in row and pd.notna(row[key]) else None)
               for key in ("iv_rel_p50", "iv_p50", "pasadas_capacidad", "min_perdidos_flota")}
    operation = unit_operation(pasadas, camiones)
    mine = operation[operation["unidad"] == unit]
    for key in ("viajes", "s_perdidos_viaje", "carga_motor", "h_subida", "km_subida"):
        value = mine[key].iloc[0] if not mine.empty else np.nan
        figures[key] = float(value) if pd.notna(value) else None
    climbs = base_climbs(pasadas)
    hours = float(_number(climbs[climbs["unidad"] == unit], "dur_s").sum()) / 3600 if not climbs.empty else 0.0
    lost = figures["min_perdidos_flota"]
    figures["lost_share"] = lost / (60 * hours) if lost is not None and hours > 0 else None
    return figures


def unit_lost_shares(camiones: Optional[pd.DataFrame], pasadas: Optional[pd.DataFrame]) -> pd.Series:
    """Per unit: its minutes lost against the fleet over its time climbing at full throttle (the
    `lost_share` of unit_figures, for every unit at once)."""
    if camiones is None or camiones.empty:
        return pd.Series(dtype=float)
    climbs = base_climbs(pasadas)
    hours = _number(climbs, "dur_s").groupby(climbs["unidad"]).sum() / 3600 if not climbs.empty else pd.Series(dtype=float)
    lost = pd.to_numeric(camiones.set_index("unidad")["min_perdidos_flota"], errors="coerce")
    return lost / (60 * hours.reindex(lost.index).where(lambda h: h > 0))


def unit_baseline(client: str, week: Week, unit: Optional[str], n: int = BASELINE_WEEKS,
                  root=None) -> Optional[Dict[str, object]]:
    """The unit's figures (unit_figures) averaged over the up to `n` complete weeks before `week` in
    which it had a row: {key: mean, ..., "weeks": [Week, ...]}. None without such a week."""
    if not unit:
        return None
    earlier = [w for w in available_weeks(client, GOLD, root) if w < week][-n:]
    values: Dict[str, list] = {key: [] for key in UNIT_FIGURES}
    used = []
    for previous in earlier:
        data = load_week(client, previous, root)
        figures = unit_figures(data.camiones, data.pasadas, unit)
        if figures is None:
            continue
        for key, value in figures.items():
            if value is not None:
                values[key].append(value)
        used.append(previous)
    if not used:
        return None
    baseline: Dict[str, object] = {key: (float(np.mean(v)) if v else None) for key, v in values.items()}
    baseline["weeks"] = used
    return baseline


def kpi_trend(key: str, value, baseline) -> Optional[Dict[str, object]]:
    """{"change": the change against the baseline (relative or absolute), "tier": "bajo" (better),
    None (about the same), "atencion" (worse) or "alto" (much worse)}; None without both values."""
    rule = KPI_TREND.get(key)
    if rule is None or value is None or baseline is None or pd.isna(value) or pd.isna(baseline):
        return None
    if rule["relative"]:
        if baseline == 0:
            return None
        change = (float(value) - float(baseline)) / abs(float(baseline))
    else:
        change = float(value) - float(baseline)
    if rule["better"] is None:
        return {"change": change, "tier": None}
    worse = -change if rule["better"] == "up" else change
    if worse <= -rule["neutral"]:
        tier = "bajo"
    elif worse < rule["neutral"]:
        tier = None
    elif worse < rule["bad"]:
        tier = "atencion"
    else:
        tier = "alto"
    return {"change": change, "tier": tier}


OPERATION_COLUMNS = ("unidad", "viajes", "km_subida", "h_subida", "carga_motor", "s_perdidos_viaje")


def unit_operation(pasadas: Optional[pd.DataFrame], camiones: Optional[pd.DataFrame]) -> pd.DataFrame:
    """What each truck of `camiones` did in the week, next to what it lost:

    - `viajes`: trips with a loaded climb on a ramp;
    - `km_subida`, `h_subida`: distance and time climbing loaded;
    - `carga_motor`: median engine load of its full-throttle climbs (%). High load with a low IV points
      at the engine or the drive; low load with a low IV, at how the truck is driven or derated;
    - `s_perdidos_viaje`: its minutes lost against the fleet (camiones), per trip, in seconds.
    """
    if camiones is None or camiones.empty:
        return pd.DataFrame(columns=list(OPERATION_COLUMNS))
    table = pd.DataFrame({"unidad": camiones["unidad"].tolist()})
    loaded = loaded_climbs(pasadas)
    if not loaded.empty:
        work = loaded.assign(_dist=_number(loaded, "dist_m"), _dur=_number(loaded, "dur_s"))
        per_unit = work.groupby("unidad").agg(km_subida=("_dist", "sum"), h_subida=("_dur", "sum"))
        per_unit["km_subida"] /= 1000
        per_unit["h_subida"] /= 3600
        if "viaje" in work.columns:
            per_unit["viajes"] = work.dropna(subset=["viaje"]).groupby("unidad")["viaje"].nunique()
        table = table.join(per_unit, on="unidad")
    climbs = base_climbs(pasadas)
    if not climbs.empty and "carga_motor_pct_media" in climbs.columns:
        load = climbs.assign(_load=_number(climbs, "carga_motor_pct_media")).groupby("unidad")["_load"].median()
        table["carga_motor"] = table["unidad"].map(load)
    for column in OPERATION_COLUMNS:
        if column not in table.columns:
            table[column] = np.nan
    lost = dict(zip(camiones["unidad"], pd.to_numeric(camiones["min_perdidos_flota"], errors="coerce")))
    trips = pd.to_numeric(table["viajes"], errors="coerce")
    table["s_perdidos_viaje"] = 60 * table["unidad"].map(lost) / trips.where(trips > 0)
    return table[list(OPERATION_COLUMNS)].reset_index(drop=True)


def decision_of(iv_rel: Optional[float], climbs: int) -> str:
    """The decision rule, for documentation and tests (the gold table already carries it)."""
    if climbs < MIN_CLIMBS or iv_rel is None or pd.isna(iv_rel):
        return SIN_DATOS
    if iv_rel >= IV_REL_OK:
        return CONFORME
    if iv_rel >= IV_REL_REVIEW:
        return SEGUIMIENTO
    return REVISAR


def units_in(camiones: Optional[pd.DataFrame], decision: str) -> List[str]:
    """Units with a decision, worst relative IV first."""
    if camiones is None or camiones.empty:
        return []
    rows = camiones[camiones["decision"] == decision].sort_values("iv_rel_p50")
    return rows["unidad"].tolist()


def is_neutral_cause(cause) -> bool:
    return str(cause).startswith(NEUTRAL_CAUSE_PREFIXES)


def cause_counts(pasadas: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Passes below the fleet with a probable cause, counted by unit and cause (`unidad`, `causa`,
    `pasadas`), units ordered by their total, most first."""
    if pasadas is None or pasadas.empty or "causa" not in pasadas:
        return pd.DataFrame(columns=["unidad", "causa", "pasadas"])
    slow = pasadas[pasadas["bajo_flota"].fillna(False).astype(bool) & pasadas["causa"].notna()]
    counts = slow.groupby(["unidad", "causa"]).size().rename("pasadas").reset_index()
    order = counts.groupby("unidad")["pasadas"].sum().sort_values(ascending=False)
    counts["_rank"] = counts["unidad"].map({u: i for i, u in enumerate(order.index)})
    return counts.sort_values(["_rank", "causa"]).drop(columns="_rank").reset_index(drop=True)


def cause_order(counts: pd.DataFrame) -> List[str]:
    """Engine causes first, most passes first; the neutral cause(s) last."""
    if counts.empty:
        return []
    totals = counts.groupby("causa")["pasadas"].sum().sort_values(ascending=False)
    return [c for c in totals.index if not is_neutral_cause(c)] + [c for c in totals.index if is_neutral_cause(c)]


def ramp_options(pasadas: Optional[pd.DataFrame], rampas: Optional[pd.DataFrame]) -> List[dict]:
    """Climb ramps with loaded full-throttle climbs, most climbs first:
    [{"rampa_id", "nombre", "pasadas"}]. The first one is the main ramp."""
    climbs = base_climbs(pasadas)
    if climbs.empty:
        return []
    counts = climbs.dropna(subset=["rampa_id"]).groupby("rampa_id").size().sort_values(ascending=False)
    names = {}
    if rampas is not None and not rampas.empty:
        names = dict(zip(rampas["rampa_id"], rampas["nombre"]))
    return [{"rampa_id": rid, "nombre": names.get(rid, ""), "pasadas": int(n)} for rid, n in counts.items()]


def main_ramp(pasadas: Optional[pd.DataFrame]) -> Optional[str]:
    """The ramp with most loaded full-throttle climbs."""
    options = ramp_options(pasadas, None)
    return options[0]["rampa_id"] if options else None


def ramp_climbs(pasadas: Optional[pd.DataFrame], rampa_id: Optional[str]) -> pd.DataFrame:
    climbs = base_climbs(pasadas)
    if climbs.empty or not rampa_id:
        return climbs.iloc[0:0]
    return climbs[climbs["rampa_id"] == rampa_id]


def descents(pasadas: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Descents evaluated against the retarder curve (`v_max_retardo_kmh` known)."""
    if pasadas is None or pasadas.empty:
        return pd.DataFrame(columns=list(PASADAS_COLUMNS))
    return pasadas[(pasadas["sentido"] == "bajada") & pasadas["v_max_retardo_kmh"].notna()]


def sample(frame: pd.DataFrame, n: int = SCATTER_SAMPLE) -> pd.DataFrame:
    """At most `n` rows, a fixed random sample (the same rows every render)."""
    return frame.sample(n, random_state=0) if len(frame) > n else frame


def low_efficiency(camiones: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Trucks whose median IV is below 1 at nominal load (Capstone): `flota`, `unidad`, `iv_p50`,
    `pasadas_bajo_1`, worst first."""
    if camiones is None or camiones.empty or "iv_p50" not in camiones:
        return pd.DataFrame(columns=["flota", "unidad", "iv_p50", "pasadas_bajo_1"])
    rows = camiones[pd.to_numeric(camiones["iv_p50"], errors="coerce") < 1]
    return rows[["flota", "unidad", "iv_p50", "pasadas_bajo_1"]].sort_values("iv_p50").reset_index(drop=True)


def trend_metrics(history: pd.DataFrame) -> List[str]:
    """Trend metrics present (and not all empty) in the history, in display order."""
    if history is None or history.empty:
        return []
    return [m for m in TREND_METRICS if m in history.columns and history[m].notna().any()]


def anomalous_power_units(potencia: Optional[pd.DataFrame]) -> List[str]:
    """Units whose power signal is above 1.2 x the fleet on some day (check the sensor first)."""
    if potencia is None or potencia.empty or "senal_anomala" not in potencia:
        return []
    return sorted(potencia.loc[potencia["senal_anomala"].fillna(False).astype(bool), "unidad"].unique().tolist())


def escape_matrix(escape: Optional[pd.DataFrame]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(deviation matrix unit x cylinder, suspicious-sensor mask). Suspicious readings are left out of
    the matrix (NaN). Units are ordered by their largest absolute deviation, without suspicious ones."""
    if escape is None or escape.empty:
        return pd.DataFrame(), pd.DataFrame()
    suspicious = escape["sensor_sospechoso"].fillna(False).astype(bool)
    values = escape.assign(valor=escape["desv_vs_flota_c"].where(~suspicious))
    matrix = values.pivot_table(index="unidad", columns="cilindro", values="valor", aggfunc="first", dropna=False)
    mask = escape.assign(s=suspicious).pivot_table(index="unidad", columns="cilindro", values="s", aggfunc="any")
    raw = escape.pivot_table(index="unidad", columns="cilindro", values="desv_vs_flota_c", aggfunc="first")
    order = matrix.abs().max(axis=1).fillna(0).sort_values(ascending=False).index
    columns = sorted(matrix.columns)
    return matrix.reindex(index=order, columns=columns), raw.reindex(index=order, columns=columns).where(
        mask.reindex(index=order, columns=columns).fillna(False).astype(bool)
    )


def quality_matrix(calidad: Optional[pd.DataFrame], column: str = "horas_con_gps") -> pd.DataFrame:
    """unit x day matrix of a data-quality column (hours), units in alphabetical order."""
    if calidad is None or calidad.empty or column not in calidad:
        return pd.DataFrame()
    matrix = calidad.pivot_table(index="unidad", columns="dia", values=column, aggfunc="sum")
    return matrix.sort_index().reindex(columns=sorted(matrix.columns))


# ------------------------------------------------------------------------------------------------
# Selected unit and map of ramps
# ------------------------------------------------------------------------------------------------

_UNIT_ID = re.compile(r"^(\D*?)[\s\-_]*(\d+)(.*)$")


def unit_sort_key(unit) -> tuple:
    """Natural order of unit ids: letters first, then the number as a number ("CA-9" < "CA-30",
    "11" < "101"). Ids without a number go last, alphabetically."""
    text = str(unit)
    match = _UNIT_ID.match(text.strip())
    if not match:
        return (1, text.upper(), 0, "")
    prefix, number, rest = match.groups()
    return (0, prefix.upper(), int(number), rest.upper())


def sort_units(units) -> List[str]:
    return sorted(units, key=unit_sort_key)


def unit_climbs(pasadas: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Per unit with loaded full-throttle climbs: `unidad`, `modelo`, `pasadas`, in natural unit order."""
    climbs = base_climbs(pasadas)
    if climbs.empty:
        return pd.DataFrame(columns=["unidad", "modelo", "pasadas"])
    per_unit = climbs.groupby("unidad", as_index=False).agg(modelo=("modelo", "first"), pasadas=("unidad", "size"))
    return per_unit.set_index("unidad").loc[sort_units(per_unit["unidad"])].reset_index()


def default_unit(camiones: Optional[pd.DataFrame]) -> Optional[str]:
    """The unit the page opens on: the worst one in "Revisar", else the lowest firm relative IV."""
    review = units_in(camiones, REVISAR)
    if review:
        return review[0]
    if camiones is None or camiones.empty:
        return None
    firm = camiones[(camiones["decision"] != SIN_DATOS) & camiones["iv_rel_p50"].notna()]
    rows = (firm if not firm.empty else camiones.dropna(subset=["iv_rel_p50"])).sort_values("iv_rel_p50")
    return rows["unidad"].iloc[0] if not rows.empty else None


def unit_row(camiones: Optional[pd.DataFrame], unit: Optional[str]) -> Optional[pd.Series]:
    if camiones is None or camiones.empty or not unit:
        return None
    rows = camiones[camiones["unidad"] == unit]
    return rows.iloc[0] if not rows.empty else None


def unit_ramps(pasadas: Optional[pd.DataFrame], rampas: Optional[pd.DataFrame], unit: Optional[str],
               min_climbs: int = MIN_UNIT_RAMP_CLIMBS) -> pd.DataFrame:
    """The unit's climb ramps, worst first: `rampa_id`, `nombre`, `pasadas`, `iv_rel` (median of its
    loaded full-throttle climbs there, against the fleet on the same ramp)."""
    climbs = base_climbs(pasadas)
    if climbs.empty or not unit:
        return pd.DataFrame(columns=["rampa_id", "nombre", "pasadas", "iv_rel"])
    mine = climbs[climbs["unidad"] == unit].dropna(subset=["rampa_id", "iv_rel"])
    table = mine.groupby("rampa_id").agg(pasadas=("iv_rel", "size"), iv_rel=("iv_rel", "median")).reset_index()
    table = table[table["pasadas"] >= min_climbs]
    names = dict(zip(rampas["rampa_id"], rampas["nombre"])) if rampas is not None and not rampas.empty else {}
    table["nombre"] = table["rampa_id"].map(names).fillna("")
    return table.sort_values("iv_rel").reset_index(drop=True)[["rampa_id", "nombre", "pasadas", "iv_rel"]]


def load_tramos(client: str, week: Week, root=None) -> Optional[pd.DataFrame]:
    """The week's silver 100 m segments (positions only), or None when the week has no silver."""
    if not (client_root(client, root) / SILVER / week.folder / MANIFEST).is_file():
        return None
    return load_table(client, week, TRAMOS_TABLE, SILVER, TRAMOS_COLUMNS, root)


def climb_points(pasadas: Optional[pd.DataFrame], tramos: Optional[pd.DataFrame],
                 max_ramps: int = MAP_RAMPS) -> pd.DataFrame:
    """Every 100 m segment of the loaded full-throttle climbs on the busiest climb ramps, with its
    position along the climb (`k`: 0 = first 100 m), the climb's unit and its IV."""
    columns = ["pasada_id", "rampa_id", "unidad", "iv", "k", "lat", "lon", "pend_pct", "v_kmh",
               "modelo", "gvw_t", "rr_pct"]
    climbs = base_climbs(pasadas)
    if climbs.empty or tramos is None or tramos.empty or "pasada_id" not in climbs:
        return pd.DataFrame(columns=columns)
    climbs = climbs.dropna(subset=["rampa_id"])
    top = climbs.groupby("rampa_id").size().sort_values(ascending=False).head(max_ramps).index
    climbs = climbs[climbs["rampa_id"].isin(top)]
    # What the climb's own force needs besides the grade (tr_pct - pend_pct: the rolling resistance).
    rr = (_number(climbs, "tr_pct") - _number(climbs, "pend_pct")).fillna(ROLLING_RESISTANCE)
    climbs = climbs.assign(rr_pct=rr, gvw_t=_number(climbs, "gvw_t"),
                           modelo=climbs["modelo"] if "modelo" in climbs else None)
    climbs = climbs[["pasada_id", "rampa_id", "unidad", "iv", "modelo", "gvw_t", "rr_pct"]]
    points = tramos.dropna(subset=["lat", "lon"]).merge(climbs, on="pasada_id", how="inner")
    points = points.sort_values(["pasada_id", "tramo"])
    points["k"] = points.groupby("pasada_id").cumcount()
    effort = [c for c in ("carga_motor_pct_media", "rpm_media", "potencia_hp_media") if c in points.columns]
    return points.reset_index(drop=True)[columns + effort]


def ramp_segments(points: pd.DataFrame, rampas: Optional[pd.DataFrame] = None,
                  min_climbs: int = MIN_SEGMENT_CLIMBS) -> pd.DataFrame:
    """The path of each climb ramp, one row per 100 m (`rampa_id`, `k`): median position, median grade
    (how demanding that stretch is), median speed, how many climbs passed it, and the ramp's median
    IV against the curve (how the fleet performs there). Stretches few climbs reach are left out."""
    columns = ["rampa_id", "k", "lat", "lon", "pend_pct", "v_kmh", "pasadas", "iv_rampa", "nombre", "pasadas_rampa"]
    if points is None or points.empty:
        return pd.DataFrame(columns=columns)
    seg = points.groupby(["rampa_id", "k"]).agg(
        lat=("lat", "median"), lon=("lon", "median"), pend_pct=("pend_pct", "median"),
        v_kmh=("v_kmh", "median"), pasadas=("pasada_id", "nunique"),
    ).reset_index()
    per_ramp = points.groupby("rampa_id").agg(pasadas_rampa=("pasada_id", "nunique"))
    per_ramp["iv_rampa"] = points.drop_duplicates("pasada_id").groupby("rampa_id")["iv"].median()
    seg = seg.join(per_ramp, on="rampa_id")
    seg = seg[seg["pasadas"] >= np.maximum(min_climbs, 0.2 * seg["pasadas_rampa"])]
    names = dict(zip(rampas["rampa_id"], rampas["nombre"])) if rampas is not None and not rampas.empty else {}
    seg["nombre"] = seg["rampa_id"].map(names).fillna("")
    order = seg.groupby("rampa_id")["pasadas_rampa"].first().sort_values(ascending=False).index
    seg["_orden"] = seg["rampa_id"].map({r: i for i, r in enumerate(order)})
    return seg.sort_values(["_orden", "k"]).drop(columns="_orden").reset_index(drop=True)[columns]


def unit_segment_speed(points: pd.DataFrame, unit: Optional[str],
                       min_climbs: int = MIN_UNIT_RAMP_CLIMBS) -> pd.DataFrame:
    """Where along each ramp a unit is slow: its median speed on each 100 m stretch divided by the
    fleet median speed on the same stretch (same ramp, same position, loaded at full throttle).
    `rampa_id`, `k`, `rel` (1 = like the fleet, below 1 = slower), `pasadas` (the unit's climbs)."""
    if points is None or points.empty or not unit:
        return pd.DataFrame(columns=["rampa_id", "k", "rel", "pasadas"])
    fleet = points.groupby(["rampa_id", "k"])["v_kmh"].median().rename("v_flota")
    mine = points[points["unidad"] == unit].groupby(["rampa_id", "k"]).agg(
        v_unidad=("v_kmh", "median"), pasadas=("pasada_id", "nunique"))
    table = mine.join(fleet).reset_index()
    table = table[(table["pasadas"] >= min_climbs) & (table["v_flota"] > 0)]
    table["rel"] = table["v_unidad"] / table["v_flota"]
    return table[["rampa_id", "k", "rel", "pasadas"]].reset_index(drop=True)


def expected_speed(force_t, curve: pd.DataFrame) -> np.ndarray:
    """Speed (km/h) the manufacturer propulsion curve gives for a required force (t): the highest speed
    at which the curve still delivers that force, interpolated between its points (the pipeline's
    `v_esp_kmh`, reproduced within 0.2 %). NaN above the curve's highest force."""
    force_t = np.asarray(force_t, dtype=float)
    if curve is None or curve.empty:
        return np.full(force_t.shape, np.nan)
    curve = curve.sort_values("v_kmh")
    v, f = curve["v_kmh"].to_numpy(dtype=float), curve["fuerza_t"].to_numpy(dtype=float)
    # Highest index whose force is still >= F: the same on the non-increasing envelope max(f[i:]).
    envelope = np.maximum.accumulate(f[::-1])[::-1]
    i = len(f) - 1 - np.searchsorted(envelope[::-1], force_t, side="left")
    out = np.full(force_t.shape, np.nan)
    last = i == len(f) - 1
    out[last] = v[-1]
    inner = (i >= 0) & ~last & ~np.isnan(force_t)
    j = i[inner]
    span = f[j] - f[j + 1]
    step = np.where(span > 0, (f[j] - force_t[inner]) / np.where(span > 0, span, 1), 0.0)
    out[inner] = v[j] + (v[j + 1] - v[j]) * step
    return out


def stretch_iv(points: pd.DataFrame, curvas: Optional[pd.DataFrame]) -> pd.Series:
    """IV of each 100 m stretch of a climb: its speed over the speed the manufacturer curve gives for
    the stretch's own grade (plus the climb's rolling resistance) and the climb's gross weight."""
    result = pd.Series(np.nan, index=points.index, dtype=float)
    if points.empty or curvas is None or curvas.empty or "modelo" not in points:
        return result
    force = _number(points, "gvw_t") * (_number(points, "pend_pct") + _number(points, "rr_pct")) / 100
    for model, part in points.groupby("modelo"):
        curve = curvas[(curvas["modelo"] == model) & (curvas["tipo"] == "propulsión")]
        expected = expected_speed(force.loc[part.index], curve)
        with np.errstate(divide="ignore", invalid="ignore"):
            result.loc[part.index] = _number(part, "v_kmh").to_numpy() / np.where(expected > 0, expected, np.nan)
    return result


UNIT_STRETCH_COLUMNS = ("iv", "carga_motor", "rpm", "potencia_hp")


def unit_stretches(points: pd.DataFrame, unit: Optional[str], curvas: Optional[pd.DataFrame],
                   min_climbs: int = MIN_UNIT_RAMP_CLIMBS) -> pd.DataFrame:
    """The unit along each ramp, per 100 m stretch (`rampa_id`, `k`) it climbed at least `min_climbs`
    times: median stretch IV against the curve, engine load (%), rpm and power (HP, Capstone), and
    `pasadas`. Positions come from the fleet's path (ramp_segments)."""
    columns = ["rampa_id", "k", *UNIT_STRETCH_COLUMNS, "pasadas"]
    if points is None or points.empty or not unit:
        return pd.DataFrame(columns=columns)
    mine = points[points["unidad"] == unit]
    if mine.empty:
        return pd.DataFrame(columns=columns)
    mine = mine.assign(iv_tramo=stretch_iv(mine, curvas), carga=_number(mine, "carga_motor_pct_media"),
                       rpm=_number(mine, "rpm_media"), potencia=_number(mine, "potencia_hp_media"))
    table = mine.groupby(["rampa_id", "k"]).agg(
        iv=("iv_tramo", "median"), carga_motor=("carga", "median"), rpm=("rpm", "median"),
        potencia_hp=("potencia", "median"), pasadas=("pasada_id", "nunique")).reset_index()
    return table[table["pasadas"] >= min_climbs].reset_index(drop=True)[columns]


def unit_ramp_table(pasadas: Optional[pd.DataFrame], rampas: Optional[pd.DataFrame], unit: Optional[str],
                    min_climbs: int = MIN_UNIT_RAMP_CLIMBS) -> pd.DataFrame:
    """The unit's climb ramps (at least `min_climbs` loaded full-throttle climbs), most demanding first:
    `rampa_id`, `nombre`, `pend_pct` (median grade of the fleet's climbs there), `km` (median length),
    the unit's `pasadas`, median `iv` and `iv_rel`, and `iv_flota` (the fleet's median IV there)."""
    columns = ["rampa_id", "nombre", "pend_pct", "km", "pasadas", "iv", "iv_rel", "iv_flota"]
    climbs = base_climbs(pasadas).dropna(subset=["rampa_id"]) if pasadas is not None else pd.DataFrame()
    if climbs.empty or not unit:
        return pd.DataFrame(columns=columns)
    fleet = climbs.groupby("rampa_id").agg(pend_pct=("pend_pct", "median"), km=("dist_m", "median"),
                                           iv_flota=("iv", "median"))
    fleet["km"] /= 1000
    mine = climbs[climbs["unidad"] == unit].groupby("rampa_id").agg(
        pasadas=("iv", "size"), iv=("iv", "median"), iv_rel=("iv_rel", "median"))
    table = mine[mine["pasadas"] >= min_climbs].join(fleet).reset_index()
    names = dict(zip(rampas["rampa_id"], rampas["nombre"])) if rampas is not None and not rampas.empty else {}
    table["nombre"] = table["rampa_id"].map(names).fillna("")
    return table.sort_values(["pend_pct", "rampa_id"], ascending=[False, True]).reset_index(drop=True)[columns]


@lru_cache(maxsize=16)
def _ramp_map_cached(client: str, folder: str, fleet: Optional[str], signature: tuple,
                     root: Optional[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    week = Week.parse(folder)
    data = filter_fleet(load_week(client, week, root), fleet)
    points = climb_points(data.pasadas, load_tramos(client, week, root))
    return points, ramp_segments(points, data.rampas)


def ramp_map_data(client: str, week: Week, fleet: Optional[str] = None,
                  root=None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """(points, segments) of the map for a week and fleet, cached until the week's files change.
    The frames are shared: callers must not modify them."""
    base = client_root(client, root)
    signature = []
    for path in (base / GOLD / week.folder / "pasadas_eval.parquet", base / SILVER / week.folder / f"{TRAMOS_TABLE}.parquet"):
        try:
            stat = path.stat()
            signature.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            signature.append(None)
    fleet = None if fleet in (None, "", "all") else fleet
    return _ramp_map_cached(str(client), week.folder, fleet, tuple(signature), None if root is None else str(root))
