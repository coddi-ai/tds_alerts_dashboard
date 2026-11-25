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
TRAMOS_COLUMNS = ("pasada_id", "tramo", "lat", "lon", "pend_pct", "v_kmh")

# pasadas_eval has 78-93 columns; the panels need these (the ones missing for a client are skipped).
PASADAS_COLUMNS = (
    "pasada_id", "unidad", "flota", "modelo", "sentido", "estado", "capacidad", "rampa_id", "dia", "turno",
    "pend_pct", "dist_m", "v_kmh", "gvw_t", "fuerza_req_t", "iv", "iv_rel", "hp_pendiente",
    "v_max_retardo_kmh", "curva_retardo", "exceso_retardo", "bajo_flota", "causa", "payload_t_media",
)

# --- Decision (camiones.decision), by the truck's median relative IV -----------------------------
FONDO_DE_MINA = "Fondo de mina"
SEGUIMIENTO = "Seguimiento"
REVISAR = "Revisar"
SIN_DATOS = "Sin datos suficientes"
DECISIONS = (FONDO_DE_MINA, SEGUIMIENTO, REVISAR, SIN_DATOS)
IV_REL_OK = 1.00            # >= : Fondo de mina
IV_REL_REVIEW = 0.97        # <  : Revisar (between both: Seguimiento)
MIN_CLIMBS = 10             # fewer loaded full-throttle climbs in the week: Sin datos suficientes

# Severity tier (shared/severity.py) of each decision: one severity scale for the whole dashboard.
DECISION_TIER = {FONDO_DE_MINA: "bajo", SEGUIMIENTO: "atencion", REVISAR: "alto", SIN_DATOS: None}

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


def week_kpis(camiones: Optional[pd.DataFrame], pasadas: Optional[pd.DataFrame]) -> Dict[str, object]:
    """The four figures of "Resumen de la semana".

    - evaluated: trucks with a firm decision (not "Sin datos suficientes"), out of `trucks`;
    - iv_median: median IV of the base population (None without climbs);
    - to_review: trucks in "Revisar";
    - lost_minutes: minutes lost against the fleet median, summed over every truck.
    """
    camiones = camiones if camiones is not None else pd.DataFrame(columns=["decision", "min_perdidos_flota"])
    climbs = base_climbs(pasadas)
    iv = pd.to_numeric(climbs.get("iv", pd.Series(dtype=float)), errors="coerce").dropna()
    return {
        "trucks": int(len(camiones)),
        "evaluated": int((camiones["decision"] != SIN_DATOS).sum()),
        "iv_median": float(iv.median()) if not iv.empty else None,
        "climbs": int(len(climbs)),
        "to_review": int((camiones["decision"] == REVISAR).sum()),
        "follow_up": int((camiones["decision"] == SEGUIMIENTO).sum()),
        "lost_minutes": float(pd.to_numeric(camiones["min_perdidos_flota"], errors="coerce").fillna(0).sum()),
    }


def decision_of(iv_rel: Optional[float], climbs: int) -> str:
    """The decision rule, for documentation and tests (the gold table already carries it)."""
    if climbs < MIN_CLIMBS or iv_rel is None or pd.isna(iv_rel):
        return SIN_DATOS
    if iv_rel >= IV_REL_OK:
        return FONDO_DE_MINA
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
    columns = ["pasada_id", "rampa_id", "unidad", "iv", "k", "lat", "lon", "pend_pct", "v_kmh"]
    climbs = base_climbs(pasadas)
    if climbs.empty or tramos is None or tramos.empty or "pasada_id" not in climbs:
        return pd.DataFrame(columns=columns)
    climbs = climbs.dropna(subset=["rampa_id"])
    top = climbs.groupby("rampa_id").size().sort_values(ascending=False).head(max_ramps).index
    climbs = climbs[climbs["rampa_id"].isin(top)][["pasada_id", "rampa_id", "unidad", "iv"]]
    points = tramos.dropna(subset=["lat", "lon"]).merge(climbs, on="pasada_id", how="inner")
    points = points.sort_values(["pasada_id", "tramo"])
    points["k"] = points.groupby("pasada_id").cumcount()
    return points.reset_index(drop=True)[columns]


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
