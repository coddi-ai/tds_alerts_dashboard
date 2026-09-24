"""
Repository layer for Mantenciones General dashboard.
Provides data access functions that can work in dummy or production mode.
"""

import json
import math
import re
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List
import logging

from src.data.dummy_generator import generate_dummy_tables
from src.data.loaders import (
    _data_path,
    _get_mantentions_data_path,
    load_maintenance_actions_all_equipment,
    load_maintenance_unit_records_actions,
    load_business_kpis,
    load_maintenance_reliability_monthly,
    load_maintenance_component_failure_ranking,
    load_oil_classified,
    list_maintenance_weeks,
    load_maintenance_week,
)

logger = logging.getLogger(__name__)


# Production files label the target as ``Sistema de Motor`` while compact
# fixtures and some client extracts use ``Motor``/``Sistema Motor``.  These
# CDA keeps this focused Summary Pareto scope. EMIN and CAPSTONE opt into all
# source systems through ``ALL_SYSTEMS_CLIENTS`` below.
MOTOR_SYSTEM_ALIASES = frozenset({"motor", "sistema motor", "sistema de motor"})
ALL_SYSTEMS_CLIENTS = frozenset({"emin", "capstone"})
TRAIN_FORCE_SYSTEM_ALIASES = frozenset(
    {
        "tren de fuerza",
        "tren fuerza",
        "sistema de tren de fuerza",
        "sistema tren de fuerza",
    }
)
PARETO_SCOPE = {
    "mode": "focused",
    "system_filter": "Motor",
    "system_column": "action_system_name",
    "system_aliases": sorted(MOTOR_SYSTEM_ALIASES),
    "dimension": "equipment",
    "dimension_source": "machine_code",
    "metric": "unique_action_id_count",
}

SCHEDULE_HOURS_PER_DAY = 24.0


def _empty_estimated_kpis() -> dict:
    return {
        "availability_est_pct": None,
        "downtime_est_hours": None,
        "mtbf_est_hours": None,
        "mttr_est_hours": None,
    }


def _normalize_unit_key(value) -> Optional[str]:
    """Normalize maintenance/oil unit identifiers to a stable join key.

    EMIN publishes ``BULL-022`` in maintenance and ``BULL_022`` in Oil. CDA
    also has ``T_09``/``T_9`` variants across sources. The Tribología catalog
    is therefore joined after normalizing separators and numeric zero padding.
    """
    if pd.isna(value):
        return None
    code = str(value).strip().upper().replace("-", "_")
    if not code:
        return None
    match = re.fullmatch(r"([^_]+)_(0*)(\d+)", code)
    if match:
        return f"{match.group(1)}_{int(match.group(3))}"
    return code


UNKNOWN_FLEET = "otros"


def _estimated_kpi_meta(
    period: Optional[str] = None,
    status: str = "unavailable",
    equipment: int = 0,
    actions: int = 0,
    records: int = 0,
    reason: Optional[str] = None,
    source_kind: str = "unavailable",
    source: Optional[list[str]] = None,
    source_columns: Optional[list[str]] = None,
    window_label: str = "mes seleccionado",
    reference_start: Optional[str] = None,
    reference_end: Optional[str] = None,
    event_count: Optional[int] = None,
    scheduled_days: Optional[int] = None,
    downtime_formula: Optional[str] = None,
) -> dict:
    """Describe the source-backed time KPI contract and its coverage."""
    calendar_days = 0
    if period:
        try:
            calendar_days = int(pd.Period(period, freq="M").days_in_month)
        except (TypeError, ValueError):
            calendar_days = 0
    schedule_days = calendar_days if scheduled_days is None else scheduled_days
    scheduled_hours = equipment * schedule_days * SCHEDULE_HOURS_PER_DAY
    source = source or ["query_4_business_kpis.parquet"]
    source_columns = source_columns or ["machine_code", "downtime_hours_70d", "reference_date"]
    meta = {
        "status": status,
        "label": "FUENTE",
        "source_kind": source_kind,
        "confidence": "source_defined" if source_kind == "business_kpis_70d" else "unavailable",
        "source": source,
        "source_columns": source_columns,
        "period": period,
        "coverage": {
            "window_label": window_label,
            "reference_start": reference_start,
            "reference_end": reference_end,
            "equipment": equipment,
            "actions": actions,
            "records": records,
            "event_count": event_count if event_count is not None else records,
            "calendar_days": schedule_days,
            "scheduled_hours_proxy": round(scheduled_hours, 3),
        },
        "unit": {
            "availability_est_pct": "%",
            "downtime_est_hours": "h",
            "mtbf_est_hours": "h",
            "mttr_est_hours": "h",
        },
        "assumptions": [
            "Las horas fuera de servicio provienen de downtime_hours_70d definido por la fuente de negocio.",
            "Horas programadas de referencia = equipos cubiertos × días de la ventana × 24 h.",
            "Cuando la fuente de negocio no está disponible o no tiene desglose para los filtros, el KPI queda sin dato.",
        ],
        "formula": {
            "downtime_est_hours": downtime_formula or "unavailable",
            "availability_est_pct": "max(scheduled_hours_proxy − downtime_est_hours, 0) / scheduled_hours_proxy × 100",
            "mtbf_est_hours": "query_5_reliability_monthly: sum(mtbf_hours × n_mtbf_intervals) / sum(n_mtbf_intervals)",
            "mttr_est_hours": "query_5_reliability_monthly: sum(total_downtime_hours) / sum(n_failures)",
        },
    }
    if reason:
        meta["reason"] = reason
    return meta


def _calculate_estimated_kpis(
    df: pd.DataFrame,
    period: Optional[str],
    business_kpis: Optional[pd.DataFrame] = None,
    equipment_filter: Optional[List[str]] = None,
    filter_reason: Optional[str] = None,
) -> tuple[dict, dict]:
    """Use source-defined 70-day hours or leave time KPIs unavailable."""
    if df.empty:
        return _empty_estimated_kpis(), _estimated_kpi_meta(period, reason="No hay acciones para el período/filtros.")
    equipment = int(df["machine_code"].nunique())
    actions = int(df["action_id"].dropna().astype(str).nunique())
    records = int(df["record_id"].dropna().astype(str).nunique())
    required = {"machine_code", "downtime_hours_70d", "reference_date"}
    kpi = business_kpis.copy() if business_kpis is not None else pd.DataFrame()
    can_use_kpi = not kpi.empty and required.issubset(kpi.columns) and not filter_reason
    if can_use_kpi and equipment_filter is not None:
        kpi = kpi[kpi["machine_code"].isin(equipment_filter)].copy()
        can_use_kpi = not kpi.empty
    if can_use_kpi:
        kpi["downtime_hours_70d"] = pd.to_numeric(kpi["downtime_hours_70d"], errors="coerce")
        kpi = kpi.dropna(subset=["downtime_hours_70d"])
        can_use_kpi = not kpi.empty
    if can_use_kpi:
        downtime_values = kpi["downtime_hours_70d"].tolist()
        if any(not math.isfinite(float(value)) or float(value) < 0 for value in downtime_values):
            can_use_kpi = False
    if can_use_kpi:
        equipment = int(kpi["machine_code"].nunique())
        downtime = float(kpi["downtime_hours_70d"].sum())
        repairs = float(pd.to_numeric(kpi.get("repairs_70d"), errors="coerce").fillna(0).sum()) if "repairs_70d" in kpi else 0.0
        event_count = int(repairs) if repairs > 0 else int(pd.to_numeric(kpi.get("total_actions_70d"), errors="coerce").fillna(0).sum()) if "total_actions_70d" in kpi else 0
        if event_count <= 0:
            event_count = records
        reference = pd.to_datetime(kpi["reference_date"], utc=True, errors="coerce").dropna()
        reference_end = reference.max().isoformat() if not reference.empty else None
        reference_start = (reference.min() - pd.Timedelta(days=69)).isoformat() if not reference.empty else None
        meta = _estimated_kpi_meta(
            period,
            status="source",
            equipment=equipment,
            actions=int(pd.to_numeric(kpi.get("total_actions_70d"), errors="coerce").fillna(0).sum()) if "total_actions_70d" in kpi else actions,
            records=records,
            source_kind="business_kpis_70d",
            source=["query_4_business_kpis.parquet"],
            source_columns=["machine_code", "downtime_hours_70d", "repairs_70d", "total_actions_70d", "reference_date"],
            window_label="ventana móvil 70d",
            reference_start=reference_start,
            reference_end=reference_end,
            event_count=event_count,
            scheduled_days=70,
            downtime_formula="sum(downtime_hours_70d)",
        )
    else:
        meta = _estimated_kpi_meta(
            period,
            status="unavailable",
            equipment=equipment,
            actions=actions,
            records=records,
            reason=filter_reason or "query_4_business_kpis.parquet ausente, incompleto o sin valores utilizables; no se infieren horas desde el conteo de acciones.",
            source_kind="unavailable",
            source=["query_4_business_kpis.parquet"],
            source_columns=["machine_code", "downtime_hours_70d", "reference_date"],
        )
        event_count = records
        downtime = None
    scheduled_hours = float(meta["coverage"]["scheduled_hours_proxy"])
    operating = max(scheduled_hours - downtime, 0.0) if downtime is not None else None
    values = {
        "availability_est_pct": round(operating / scheduled_hours * 100, 1) if operating is not None and scheduled_hours else None,
        "downtime_est_hours": round(downtime, 1) if downtime is not None else None,
        "mtbf_est_hours": round(operating / event_count, 1) if operating is not None and event_count else None,
        "mttr_est_hours": round(downtime / event_count, 1) if downtime is not None and event_count else None,
    }
    return values, meta


def _calculate_monthly_time_kpis(
    daily_hours: pd.DataFrame,
    period: Optional[str],
    equipment_count: int,
    source_name: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[dict, dict]:
    """Calculate monthly downtime and availability from unioned intervals.

    ``daily_hours`` is produced by ``_daily_out_of_service_hours`` after
    clipping each source interval to the selected month and unioning overlaps
    per equipment/day.  The denominator is therefore the exact calendar
    capacity of the selected equipment in that month.
    """
    empty = {"availability_est_pct": None, "downtime_est_hours": None}
    calendar_days = int((end - start).total_seconds() / 86400)
    scheduled_hours = float(max(equipment_count, 0) * calendar_days * 24)
    meta = {
        "status": "unavailable",
        "label": "FUENTE",
        "source_kind": "record_intervals",
        "confidence": "source_defined",
        "source": [source_name],
        "source_columns": (
            ["record_id", "machine_code", "first_event_ts", "last_event_ts"]
            if "query_2" in source_name
            else ["record_id", "machine_code", "event_ts"]
        ),
        "period": period,
        "coverage": {
            "window_label": "mes seleccionado",
            "reference_start": start.isoformat(),
            "reference_end": (end - pd.Timedelta(microseconds=1)).isoformat(),
            "equipment": int(equipment_count),
            "calendar_days": calendar_days,
            "scheduled_hours": round(scheduled_hours, 3),
        },
        "unit": {"availability_est_pct": "%", "downtime_est_hours": "h-equipo"},
        "formula": {
            "downtime_est_hours": "sum(hours_out_of_service)",
            "availability_est_pct": "(calendar_days × 24 × equipment − downtime_est_hours) / (calendar_days × 24 × equipment) × 100",
        },
        "assumptions": [
            "Los intervalos se recortan al mes seleccionado.",
            "Los solapes se unen por equipo y día antes de sumar.",
            "No se infieren horas desde el conteo de acciones.",
        ],
    }
    if daily_hours.empty or "hours_out_of_service" not in daily_hours.columns or scheduled_hours <= 0:
        meta["reason"] = "No hay intervalos fuente utilizables para el mes y filtros seleccionados."
        return empty, meta

    hours = pd.to_numeric(daily_hours["hours_out_of_service"], errors="coerce")
    hours = hours[hours.notna() & hours.map(math.isfinite) & hours.ge(0)]
    if hours.empty:
        meta["reason"] = "Los intervalos fuente no contienen horas finitas no negativas."
        return empty, meta

    downtime = float(hours.sum())
    availability = (scheduled_hours - downtime) / scheduled_hours * 100
    meta.update(
        {
            "status": "source",
            "coverage": {
                **meta["coverage"],
                "days_with_intervals": int(daily_hours["date"].nunique()) if "date" in daily_hours else int(len(daily_hours)),
            },
        }
    )
    return {
        "availability_est_pct": round(availability, 1),
        "downtime_est_hours": round(downtime, 1),
    }, meta


class MaintenanceRepository:
    """Repository for maintenance data access."""
    
    def __init__(self, mode="dummy", client="cda"):
        """
        Initialize repository.
        
        Args:
            mode: "dummy" for in-memory data, "parquet" for parquet files, "prod" for database queries
            client: Client name (e.g., "cda", "emin") for data filtering
        """
        self.mode = mode
        self.client = client.lower()  # Normalize to lowercase
        self._dummy_cache = None
        self._parquet_cache = None
        self._parquet_actions_cache = None
        self._parquet_records_cache = None
        self._parquet_kpis_cache = None
        self._parquet_reliability_cache = None
        self._parquet_component_failures_cache = None
        self._fleet_catalog_cache = None

    def _get_parquet_actions(self):
        """Load detailed actions only when a caller actually needs them."""
        if self._parquet_actions_cache is None:
            logger.info(
                "Loading maintenance actions from parquet files for client: %s",
                self.client,
            )
            frame = load_maintenance_actions_all_equipment(client=self.client)
            # Keep the repository contract stable even when a test fixture or
            # an alternate loader supplies ISO strings instead of the loader's
            # already-normalized UTC columns.
            for column in ("event_ts", "change_date"):
                if column in frame.columns:
                    frame[column] = pd.to_datetime(frame[column], utc=True, format="mixed", errors="coerce")
            self._parquet_actions_cache = frame
        return self._parquet_actions_cache

    def _get_parquet_kpis(self):
        """Load the small KPI source independently from detailed actions."""
        if self._parquet_kpis_cache is None:
            logger.info(
                "Loading maintenance KPIs from parquet files for client: %s",
                self.client,
            )
            self._parquet_kpis_cache = load_business_kpis(client=self.client)
        return self._parquet_kpis_cache

    def _get_parquet_records(self):
        """Load source-defined record intervals used for time aggregation."""
        if self._parquet_records_cache is None:
            logger.info(
                "Loading maintenance record intervals from parquet for client: %s",
                self.client,
            )
            frame = load_maintenance_unit_records_actions(client=self.client)
            for column in ("first_event_ts", "last_event_ts"):
                if column in frame.columns:
                    frame[column] = pd.to_datetime(
                        frame[column], utc=True, format="mixed", errors="coerce"
                    )
            self._parquet_records_cache = frame
        return self._parquet_records_cache

    def _get_parquet_reliability(self):
        """Load query 5 only once per repository instance."""
        if self._parquet_reliability_cache is None:
            logger.info(
                "Loading monthly reliability view from parquet for client: %s",
                self.client,
            )
            frame = load_maintenance_reliability_monthly(client=self.client)
            if "year_month" in frame.columns:
                frame["year_month"] = frame["year_month"].astype("string").str.strip()
            self._parquet_reliability_cache = frame
        return self._parquet_reliability_cache

    def _get_parquet_component_failures(self):
        """Load query 6 only once per repository instance."""
        if self._parquet_component_failures_cache is None:
            logger.info(
                "Loading component failure ranking from parquet for client: %s",
                self.client,
            )
            self._parquet_component_failures_cache = load_maintenance_component_failure_ranking(
                client=self.client
            )
        return self._parquet_component_failures_cache
        
    def _get_dummy_data(self):
        """Get or generate dummy data."""
        if self._dummy_cache is None:
            logger.info("Generating dummy maintenance data...")
            self._dummy_cache = generate_dummy_tables()
        return self._dummy_cache
    
    def _get_parquet_data(self):
        """Get or load parquet data."""
        if self._parquet_cache is None:
            self._parquet_cache = {
                "actions": self._get_parquet_actions(),
                "records": self._get_parquet_records(),
                "kpis": self._get_parquet_kpis(),
                "reliability": self._get_parquet_reliability(),
                "component_failures": self._get_parquet_component_failures(),
            }
        return self._parquet_cache

    def _fleet_catalog(self) -> dict[str, str]:
        """Return the Tribología unit-to-fleet catalog for this client.

        ``machineName`` is the governed fleet/type label in classified oil
        data. A unit can have historical label drift, so the most frequent
        non-empty label wins deterministically for each normalized unit key.
        """
        if self._fleet_catalog_cache is not None:
            return self._fleet_catalog_cache
        catalog: dict[str, str] = {}
        try:
            classified = load_oil_classified(self.client)
        except Exception as exc:  # pragma: no cover - defensive source isolation
            logger.warning("Could not load oil fleet catalog for %s: %s", self.client, exc)
            classified = pd.DataFrame()
        required = {"unitId", "machineName"}
        if not classified.empty and required.issubset(classified.columns):
            frame = classified[["unitId", "machineName"]].copy()
            frame["__unit_key"] = frame["unitId"].map(_normalize_unit_key)
            frame["__fleet"] = frame["machineName"].astype("string").str.strip()
            frame = frame.dropna(subset=["__unit_key"])
            frame = frame[frame["__fleet"].notna() & frame["__fleet"].ne("")]
            if not frame.empty:
                counts = (
                    frame.groupby(["__unit_key", "__fleet"], as_index=False)
                    .size()
                    .sort_values(
                        ["__unit_key", "size", "__fleet"],
                        ascending=[True, False, True],
                        kind="mergesort",
                    )
                    .drop_duplicates("__unit_key")
                )
                catalog = dict(zip(counts["__unit_key"], counts["__fleet"]))
        self._fleet_catalog_cache = catalog
        return catalog

    def _fleet_for_machine_code(self, value) -> str:
        """Resolve a unit strictly through Tribología's catalog.

        Maintenance codes are normalized only to make the join robust to
        separators and numeric zero padding. We deliberately do not infer a
        fleet from a code prefix: an unmatched unit is exposed as the explicit
        ``otros`` category so it remains visible and auditable.
        """
        key = _normalize_unit_key(value)
        return self._fleet_catalog().get(key, UNKNOWN_FLEET)

    def _filtered_actions(
        self,
        systems: Optional[List[str]] = None,
        equipment: Optional[List[str]] = None,
        subsystems: Optional[List[str]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        fleets: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Apply the dashboard's Fleet / System / Equipment / date-range filters to the
        raw maintenance-actions table (parquet mode only - every action-based
        get_* method funnels through this so the filters behave identically
        everywhere). Absent filters are a no-op, matching the "no filter ->
        full dataset" default.

        date_start/date_end are inclusive on both ends.
        """
        df = self._get_parquet_data()["actions"]
        if df.empty:
            return df

        if systems:
            df = df[df["action_system_name"].isin(systems)]
        if equipment:
            df = df[df["machine_code"].isin(equipment)]
        if fleets:
            df = df[df["machine_code"].map(self._fleet_for_machine_code).isin(fleets)]
        if subsystems:
            df = df[df["action_subsystem_name"].isin(subsystems)]
        if date_start:
            start = pd.Timestamp(date_start)
            start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
            df = df[df["change_date"] >= start]
        if date_end:
            end = pd.Timestamp(date_end)
            end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
            df = df[df["change_date"] < end + timedelta(days=1)]

        # Always a safe-to-mutate copy: callers (e.g. get_downtime_by_day_mtd)
        # add derived columns on the result, which would otherwise risk a
        # SettingWithCopyWarning on a boolean-indexed slice.
        return df.copy()

    def _machines_for_systems(self, systems: Optional[List[str]]) -> Optional[set]:
        """machine_code values with at least one action tagged with any of `systems`.

        Returns None (no restriction) when `systems` is empty/None - the
        status KPIs are per-machine, not per-action, so a System filter has
        to be resolved to the machines it touches via the actions table.
        """
        if not systems:
            return None
        df_actions = self._get_parquet_data()["actions"]
        if df_actions.empty:
            return set()
        return set(
            df_actions.loc[df_actions["action_system_name"].isin(systems), "machine_code"]
            .dropna()
            .unique()
        )

    def get_available_systems(self) -> List[str]:
        """Distinct system names present in the data, for populating the System filter."""
        if self.mode == "parquet":
            df_actions = self._get_parquet_data()["actions"]
            if df_actions.empty:
                return []
            return sorted(df_actions["action_system_name"].dropna().unique().tolist())
        elif self.mode == "dummy":
            return sorted(self._get_dummy_data()["systems"]["system_name"].tolist())
        else:
            raise NotImplementedError("Production mode not yet implemented")

    def get_available_fleets(self) -> List[str]:
        """Return Tribología fleet labels plus ``otros`` for unmatched units."""
        if self.mode == "parquet":
            machines = self._get_parquet_data()["actions"].get("machine_code", pd.Series(dtype=str))
        elif self.mode == "dummy":
            machines = self._get_dummy_data()["machines"].get("machine_code", pd.Series(dtype=str))
        else:
            raise NotImplementedError("Production mode not yet implemented")
        fleets = {self._fleet_for_machine_code(value) for value in machines.unique()}
        return sorted(fleets, key=lambda value: (value.casefold(), value))

    def get_available_equipment(
        self,
        systems: Optional[List[str]] = None,
        fleets: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Distinct machine codes present in the data, for populating the
        Equipment filter. When `systems` is given, scoped to machines that
        have at least one action on those systems (cascading filter).
        """
        if self.mode == "parquet":
            df_actions = self._get_parquet_data()["actions"]
            if df_actions.empty:
                return []
            if systems:
                df_actions = df_actions[df_actions["action_system_name"].isin(systems)]
            if fleets:
                df_actions = df_actions[
                    df_actions["machine_code"].map(self._fleet_for_machine_code).isin(fleets)
                ]
            return sorted(df_actions["machine_code"].dropna().unique().tolist())
        elif self.mode == "dummy":
            data = self._get_dummy_data()
            machines = data["machines"]["machine_code"].dropna()
            if fleets:
                machines = machines[machines.map(self._fleet_for_machine_code).isin(fleets)]
            return sorted(machines.tolist())
        else:
            raise NotImplementedError("Production mode not yet implemented")

    def refresh(self) -> None:
        """Drop this client's in-process caches so a manual refresh sees new files."""
        self._dummy_cache = None
        self._parquet_cache = None
        self._parquet_actions_cache = None
        self._parquet_records_cache = None
        self._parquet_kpis_cache = None
        self._parquet_reliability_cache = None
        self._parquet_component_failures_cache = None
        self._fleet_catalog_cache = None

    def _actions_source_state(self) -> tuple[str, str | None]:
        """Classify the action source without turning failures into empty data."""
        root = _get_mantentions_data_path(self.client)
        if root is None:
            return "missing", "No existe la carpeta de fuentes de mantenciones."
        path = root / "query_3_actions_all_equipment.parquet"
        if not path.exists():
            return "missing", f"No existe {path.name}."
        try:
            probe = pd.read_parquet(path, columns=["action_id"])
        except Exception as exc:
            return "error", f"No se pudo leer {path.name}: {exc}"
        if probe.empty:
            return "empty", f"{path.name} está vacío."
        return "ok", None

    def get_available_subsystems(
        self,
        systems: Optional[List[str]] = None,
        equipment: Optional[List[str]] = None,
    ) -> List[str]:
        """Return subsystem options after applying cascading filters."""
        if self.mode == "parquet":
            df = self._get_parquet_data()["actions"]
            if systems:
                df = df[df["action_system_name"].isin(systems)]
            if equipment:
                df = df[df["machine_code"].isin(equipment)]
            return sorted(df["action_subsystem_name"].dropna().unique().tolist())
        if self.mode == "dummy":
            df = self._get_dummy_data()["subsystems"]
            return sorted(df["subsystem_name"].dropna().unique().tolist())
        raise NotImplementedError("Production mode not yet implemented")

    def get_available_months(self) -> List[str]:
        """Return months exposed by activity or the reliability view."""
        if self.mode != "parquet":
            if self.mode == "dummy":
                df = self._get_dummy_data()["jobs"]
                dates = pd.to_datetime(df.get("start_date"), errors="coerce")
                return sorted(dates.dropna().dt.strftime("%Y-%m").unique().tolist())
            raise NotImplementedError("Production mode not yet implemented")
        data = self._get_parquet_data()
        months = set()
        actions = data["actions"]
        if not actions.empty and "change_date" in actions:
            months.update(actions["change_date"].dropna().dt.strftime("%Y-%m").tolist())
        reliability = data.get("reliability", pd.DataFrame())
        if not reliability.empty and "source_system" in reliability.columns:
            reliability = reliability[
                reliability["source_system"].astype("string").str.upper().eq(self.client.upper())
            ]
        if not reliability.empty and "year_month" in reliability:
            values = reliability["year_month"].astype("string").str.strip()
            months.update(values[values.str.fullmatch(r"\d{4}-\d{2}", na=False)].dropna().tolist())
        return sorted(months)

    def get_available_reliability_equipment(
        self, period: Optional[str] = None
    ) -> List[str]:
        """Return machine codes present in query 5, optionally for one month."""
        if self.mode != "parquet":
            return []
        frame = self._get_parquet_data().get("reliability", pd.DataFrame())
        if frame.empty or "machine_code" not in frame.columns:
            return []
        if "source_system" in frame.columns:
            frame = frame[frame["source_system"].astype("string").str.upper().eq(self.client.upper())]
        if period and "year_month" in frame.columns:
            frame = frame[frame["year_month"].astype("string").eq(str(period))]
        return sorted(frame["machine_code"].dropna().astype(str).unique().tolist())

    def get_available_weeks(self) -> List[str]:
        """Return weekly snapshot identifiers available for this client."""
        if self.mode == "parquet":
            return list_maintenance_weeks(self.client)
        if self.mode == "dummy":
            return []
        raise NotImplementedError("Production mode not yet implemented")

    @staticmethod
    def _month_bounds(period: str) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Return inclusive-start/exclusive-end UTC bounds for YYYY-MM."""
        start = pd.Timestamp(f"{period}-01")
        start = start.tz_localize("UTC")
        end = start + pd.offsets.MonthBegin(1)
        return start, end

    @staticmethod
    def _empty_month_data() -> dict:
        return {
            "daily": [],
            "system_mix": [],
            "system_mix_detail": [],
            "pareto": [],
            "system_pareto": [],
            "train_force_pareto": [],
            "equipment": [],
            "equipment_system_mix": [],
            "matrix": [],
            "detail": [],
        }

    @staticmethod
    def _json_records(frame: pd.DataFrame) -> list[dict]:
        """Convert a frame to records without leaking numpy NaN values."""
        if frame.empty:
            return []
        return frame.astype(object).where(pd.notna(frame), None).to_dict("records")

    def _optional_view_state(
        self, filename: str, frame: pd.DataFrame
    ) -> tuple[str, Optional[str]]:
        """Describe an optional query-5/query-6 source without masking errors."""
        if not frame.empty:
            return "ok", None
        root = _get_mantentions_data_path(self.client)
        if root is None or not (root / filename).exists():
            return "missing", f"No existe {filename}."
        try:
            probe = pd.read_parquet(root / filename)
        except Exception as exc:
            return "error", f"No se pudo leer {filename}: {exc}"
        if probe.empty:
            return "empty", f"{filename} está vacío."
        return "error", f"{filename} no entregó registros utilizables."

    def get_reliability_payload(
        self,
        period: Optional[str] = None,
        equipment: Optional[List[str]] = None,
        detail_limit: int = 250,
    ) -> dict:
        """Build the JSON contract for query 5 and query 6.

        Query 5 is monthly and query 6 is an accumulated ranking. Missing
        metric values remain ``null`` so the UI can communicate insufficient
        observations instead of manufacturing zeros.
        """
        empty = {"monthly": [], "components": []}
        if self.mode != "parquet":
            return {
                "status": "empty",
                "meta": {"source_system": self.client.upper(), "reason": "La fuente de confiabilidad solo está disponible en parquet."},
                "filters": {"period": period, "equipment": equipment or []},
                "data": empty,
            }

        data = self._get_parquet_data()
        monthly = data.get("reliability", pd.DataFrame()).copy()
        components = data.get("component_failures", pd.DataFrame()).copy()
        monthly_state, monthly_error = self._optional_view_state(
            "query_5_reliability_monthly.parquet", monthly
        )
        components_state, components_error = self._optional_view_state(
            "query_6_component_failure_ranking.parquet", components
        )
        if "error" in {monthly_state, components_state}:
            return {
                "status": "error",
                "meta": {
                    "source_system": self.client.upper(),
                    "source_status": {"query_5": monthly_state, "query_6": components_state},
                    "errors": [value for value in (monthly_error, components_error) if value],
                },
                "filters": {"period": period, "equipment": equipment or []},
                "data": empty,
            }
        monthly_required = {
            "source_system", "machine_id", "machine_code", "year_month",
            "n_failures", "mttr_hours", "total_downtime_hours",
            "n_mtbf_intervals", "mtbf_hours", "mttf_hours", "low_confidence",
        }
        component_required = {
            "source_system", "machine_id", "machine_code", "component_id",
            "component_name", "n_failure_records", "n_failure_actions",
        }
        missing_monthly = sorted(monthly_required.difference(monthly.columns)) if not monthly.empty else []
        missing_components = sorted(component_required.difference(components.columns)) if not components.empty else []
        if missing_monthly or missing_components:
            return {
                "status": "error",
                "meta": {
                    "source_system": self.client.upper(),
                    "source_status": {"query_5": monthly_state, "query_6": components_state},
                    "missing_columns": {"query_5": missing_monthly, "query_6": missing_components},
                    "errors": [value for value in (monthly_error, components_error) if value],
                },
                "filters": {"period": period, "equipment": equipment or []},
                "data": empty,
            }

        source_system = self.client.upper()
        if "source_system" in monthly.columns:
            monthly = monthly[monthly["source_system"].astype("string").str.upper().eq(source_system)]
        if "source_system" in components.columns:
            components = components[components["source_system"].astype("string").str.upper().eq(source_system)]
        available_months = []
        if not monthly.empty:
            values = monthly["year_month"].astype("string").str.strip()
            monthly["year_month"] = values
            available_months = sorted(values[values.str.fullmatch(r"\d{4}-\d{2}", na=False)].dropna().unique().tolist())
        selected = period or (available_months[-1] if available_months else None)
        selected_equipment = [str(value) for value in (equipment or []) if value not in (None, "", "__all__")]
        if selected:
            monthly = monthly[monthly["year_month"].eq(str(selected))]
        if selected_equipment:
            monthly = monthly[monthly["machine_code"].astype(str).isin(selected_equipment)]
            if not components.empty:
                components = components[components["machine_code"].astype(str).isin(selected_equipment)]
        monthly_columns = [
            "source_system", "machine_id", "machine_code", "year_month",
            "n_failures", "mttr_hours", "total_downtime_hours",
            "n_mtbf_intervals", "mtbf_hours", "mttf_hours", "low_confidence",
        ]
        component_columns = [
            "source_system", "machine_id", "machine_code", "component_id",
            "component_name", "n_failure_records", "n_failure_actions",
        ]
        monthly = monthly[monthly_columns].sort_values(
            ["year_month", "machine_code"], kind="mergesort"
        ) if not monthly.empty else monthly
        components = components[component_columns].sort_values(
            ["n_failure_records", "n_failure_actions", "component_name", "machine_code"],
            ascending=[False, False, True, True],
            kind="mergesort",
        ).head(detail_limit) if not components.empty else components
        status = "ok" if not monthly.empty and not components.empty else (
            "partial" if not monthly.empty or not components.empty else "empty"
        )
        return {
            "status": status,
            "meta": {
                "source_system": source_system,
                "available_months": available_months,
                "period": selected,
                "source_status": {"query_5": monthly_state, "query_6": components_state},
                "source": ["query_5_reliability_monthly.parquet", "query_6_component_failure_ranking.parquet"],
                "low_confidence_rows": int(monthly["low_confidence"].fillna(False).astype(bool).sum()) if not monthly.empty else 0,
                "monthly_rows": int(len(monthly)),
                "component_rows": int(len(components)),
                "errors": [value for value in (monthly_error, components_error) if value],
            },
            "filters": {"period": selected, "equipment": selected_equipment},
            "data": {
                "monthly": self._json_records(monthly),
                "components": self._json_records(components),
            },
        }

    def get_reliability_kpis(
        self,
        period: Optional[str] = None,
        equipment: Optional[List[str]] = None,
    ) -> dict:
        """Return the monthly MTBF/MTTR cards from query 5.

        Query 5 is already aggregated at ``machine_code × year_month``.  A
        fleet-level card must therefore weight each machine-month by the
        observations behind the metric instead of averaging machine averages:

        * MTBF uses ``n_mtbf_intervals`` as its weight.
        * MTTR uses ``n_failures`` and the source downtime total.

        Missing values remain unavailable.  In particular, a machine-month
        with zero/unknown intervals or failures never contributes a synthetic
        zero to the card.
        """
        empty_values = {"mtbf_est_hours": None, "mttr_est_hours": None}
        empty_meta = {
            "source": "query_5_reliability_monthly.parquet",
            "source_status": "empty",
            "period": period,
            "equipment": equipment or [],
            "low_confidence_rows": 0,
        }
        if self.mode != "parquet":
            empty_meta["reason"] = "La vista mensual de confiabilidad solo está disponible en parquet."
            return {"status": "empty", "values": empty_values, "meta": empty_meta}

        frame = self._get_parquet_data().get("reliability", pd.DataFrame()).copy()
        required = {
            "source_system", "machine_code", "year_month", "n_failures",
            "mttr_hours", "total_downtime_hours", "n_mtbf_intervals", "mtbf_hours",
        }
        if frame.empty:
            empty_meta["reason"] = "query_5_reliability_monthly.parquet no contiene filas."
            return {"status": "empty", "values": empty_values, "meta": empty_meta}
        missing = sorted(required.difference(frame.columns))
        if missing:
            empty_meta.update({"source_status": "error", "missing_columns": missing})
            empty_meta["reason"] = "Faltan columnas requeridas en query_5_reliability_monthly.parquet."
            return {"status": "error", "values": empty_values, "meta": empty_meta}

        source_system = self.client.upper()
        frame = frame[
            frame["source_system"].astype("string").str.upper().eq(source_system)
        ].copy()
        frame["year_month"] = frame["year_month"].astype("string").str.strip()
        available_months = sorted(
            frame.loc[
                frame["year_month"].str.fullmatch(r"\d{4}-\d{2}", na=False),
                "year_month",
            ].dropna().unique().tolist()
        )
        selected = period or (available_months[-1] if available_months else None)
        if selected:
            frame = frame[frame["year_month"].eq(str(selected))]
        selected_equipment = [
            str(value) for value in (equipment or [])
            if value not in (None, "", "__all__")
        ]
        if selected_equipment:
            frame = frame[frame["machine_code"].astype(str).isin(selected_equipment)]

        meta = {
            **empty_meta,
            "source_status": "ok",
            "source_system": source_system,
            "period": selected,
            "available_months": available_months,
            "equipment": selected_equipment,
        }
        if frame.empty:
            meta["reason"] = "No hay filas de query_5 para el período o filtros seleccionados."
            return {"status": "empty", "values": empty_values, "meta": meta}

        failures = pd.to_numeric(frame["n_failures"], errors="coerce")
        intervals = pd.to_numeric(frame["n_mtbf_intervals"], errors="coerce")
        mtbf = pd.to_numeric(frame["mtbf_hours"], errors="coerce")
        mttr = pd.to_numeric(frame["mttr_hours"], errors="coerce")
        downtime = pd.to_numeric(frame["total_downtime_hours"], errors="coerce")

        valid_mtbf = intervals.gt(0) & intervals.notna() & mtbf.notna() & mtbf.map(math.isfinite)
        mtbf_weight = intervals.where(valid_mtbf, 0.0)
        mtbf_numerator = (mtbf.where(valid_mtbf, 0.0) * mtbf_weight).sum()
        mtbf_denominator = mtbf_weight.sum()
        mtbf_value = (
            float(mtbf_numerator / mtbf_denominator)
            if mtbf_denominator > 0 and math.isfinite(float(mtbf_numerator))
            else None
        )

        # Prefer the source total downtime; when a legacy export omits it,
        # reconstruct only from the source MTTR × failure count (never from
        # action counts or an arbitrary proxy).
        derived_downtime = downtime.where(downtime.notna() & downtime.map(math.isfinite))
        derived_downtime = derived_downtime.where(
            derived_downtime.notna(),
            mttr.where(mttr.notna() & mttr.map(math.isfinite), 0.0) * failures.fillna(0.0),
        )
        valid_mttr = failures.gt(0) & failures.notna() & derived_downtime.notna()
        mttr_weight = failures.where(valid_mttr, 0.0)
        mttr_numerator = derived_downtime.where(valid_mttr, 0.0).sum()
        mttr_denominator = mttr_weight.sum()
        mttr_value = (
            float(mttr_numerator / mttr_denominator)
            if mttr_denominator > 0 and math.isfinite(float(mttr_numerator))
            else None
        )

        values = {
            "mtbf_est_hours": round(mtbf_value, 1) if mtbf_value is not None else None,
            "mttr_est_hours": round(mttr_value, 1) if mttr_value is not None else None,
        }
        meta.update(
            {
                "rows": int(len(frame)),
                "low_confidence_rows": int(
                    frame.get("low_confidence", pd.Series(False, index=frame.index))
                    .fillna(False)
                    .astype(bool)
                    .sum()
                ),
                "mtbf_intervals": int(mtbf_denominator),
                "failures": int(mttr_denominator),
            }
        )
        status = "ok" if mtbf_value is not None and mttr_value is not None else (
            "partial" if mtbf_value is not None or mttr_value is not None else "empty"
        )
        if status == "empty":
            meta["reason"] = "No hay intervalos MTBF o fallas suficientes para calcular las cards."
        return {"status": status, "values": values, "meta": meta}

    def _daily_out_of_service_hours(
        self,
        filtered_actions: pd.DataFrame,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> tuple[pd.DataFrame, str]:
        """Allocate source-defined record intervals to UTC calendar days.

        The business KPI extract only exposes a rolling 70-day total.  The
        daily series therefore uses the source record boundaries from query_2
        and clips each interval to the selected month.  Overlapping intervals
        are unioned per equipment/day before the fleet total is calculated. If query_2 is absent,
        the same boundaries are derived from query_3 as a compatibility
        fallback; no action-count-to-hours conversion is performed.
        """
        required = {"record_id", "machine_code", "first_event_ts", "last_event_ts"}
        records = self._get_parquet_data().get("records", pd.DataFrame())
        source_name = "query_2_unit_records_actions.parquet"
        if not required.issubset(records.columns) or records.empty:
            source_name = "query_3_actions_all_equipment.parquet (min/max event_ts por registro)"
            if filtered_actions.empty:
                return pd.DataFrame(columns=["date", "hours_out_of_service"]), source_name
            records = (
                filtered_actions.groupby(["record_id", "machine_code"], dropna=False)
                .agg(first_event_ts=("event_ts", "min"), last_event_ts=("event_ts", "max"))
                .reset_index()
            )
        else:
            keys = filtered_actions[["record_id", "machine_code"]].drop_duplicates()
            records = records.merge(keys, on=["record_id", "machine_code"], how="inner")
            if records.empty and not filtered_actions.empty:
                source_name = "query_3_actions_all_equipment.parquet (min/max event_ts por registro)"
                records = (
                    filtered_actions.groupby(["record_id", "machine_code"], dropna=False)
                    .agg(first_event_ts=("event_ts", "min"), last_event_ts=("event_ts", "max"))
                    .reset_index()
                )

        for column in ("first_event_ts", "last_event_ts"):
            records[column] = pd.to_datetime(records[column], utc=True, format="mixed", errors="coerce")
        records = records.dropna(subset=["first_event_ts", "last_event_ts"]).copy()
        records = records[records["last_event_ts"] >= records["first_event_ts"]]
        if records.empty:
            return pd.DataFrame(columns=["date", "hours_out_of_service"]), source_name

        interval_pieces = []
        for record in records.itertuples(index=False):
            interval_start = max(record.first_event_ts, start)
            interval_end = min(record.last_event_ts, end)
            if interval_end <= interval_start:
                continue
            day = interval_start.floor("D")
            while day < interval_end:
                day_end = day + pd.Timedelta(days=1)
                effective_start = max(interval_start, day)
                effective_end = min(interval_end, day_end)
                if effective_end > effective_start:
                    interval_pieces.append(
                        {
                            "machine_code": record.machine_code,
                            "date": day.strftime("%Y-%m-%d"),
                            "start": effective_start,
                            "end": effective_end,
                        }
                    )
                day = day_end

        if not interval_pieces:
            return pd.DataFrame(columns=["date", "hours_out_of_service"]), source_name
        pieces = pd.DataFrame(interval_pieces)
        union_rows = []
        for (machine_code, date), group in pieces.groupby(["machine_code", "date"], dropna=False):
            total_seconds = 0.0
            current_start = None
            current_end = None
            for interval in group.sort_values(["start", "end"]).itertuples(index=False):
                if current_start is None:
                    current_start, current_end = interval.start, interval.end
                elif interval.start <= current_end:
                    current_end = max(current_end, interval.end)
                else:
                    total_seconds += (current_end - current_start).total_seconds()
                    current_start, current_end = interval.start, interval.end
            if current_start is not None:
                total_seconds += (current_end - current_start).total_seconds()
            union_rows.append({"date": date, "hours_out_of_service": total_seconds / 3600})
        daily = pd.DataFrame(union_rows).groupby("date", as_index=False)["hours_out_of_service"].sum().sort_values("date")
        daily["hours_out_of_service"] = daily["hours_out_of_service"].round(3)
        return daily, source_name

    def _pareto_scope(self) -> dict:
        """Return this client's serializable scope for Summary Pareto charts."""
        scope = {
            **PARETO_SCOPE,
            "system_aliases": list(PARETO_SCOPE["system_aliases"]),
        }
        if self.client in ALL_SYSTEMS_CLIENTS:
            scope.update(
                {
                    "mode": "all_systems",
                    "system_filter": None,
                    "system_aliases": [],
                }
            )
        return scope

    @staticmethod
    def _is_motor_system(values: pd.Series) -> pd.Series:
        """Match only the canonical Motor system aliases, case-insensitively."""
        normalized = values.astype("string").str.strip().str.casefold()
        return normalized.isin(MOTOR_SYSTEM_ALIASES)

    @staticmethod
    def _is_train_force_system(values: pd.Series) -> pd.Series:
        """Match the canonical Tren de Fuerza aliases, case-insensitively."""
        normalized = values.astype("string").str.strip().str.casefold()
        return normalized.isin(TRAIN_FORCE_SYSTEM_ALIASES)

    def get_monthly_payload(
        self,
        period: Optional[str] = None,
        systems: Optional[List[str]] = None,
        equipment: Optional[List[str]] = None,
        subsystems: Optional[List[str]] = None,
        detail_limit: int = 250,
        fleets: Optional[List[str]] = None,
    ) -> dict:
        """Build the JSON-safe contract consumed by the productive Mantenciones page."""
        months = self.get_available_months()
        selected = period or (months[-1] if months else None)
        empty = self._empty_month_data()
        base = self._get_parquet_data()["actions"] if self.mode == "parquet" else pd.DataFrame()
        source_status, source_error = ("ok", None)
        if self.mode == "parquet" and base.empty:
            source_status, source_error = self._actions_source_state()
            if source_status in {"missing", "error"}:
                return {
                    "status": "error",
                    "meta": {
                        "client": self.client.upper(),
                        "period": selected,
                        "period_label": selected or "Sin datos",
                        "available_months": months,
                        "source_start": None,
                        "source_end": None,
                        "source_status": source_status,
                        "error": source_error,
                        "is_current_period": False,
                        "detail_total": 0,
                        "pareto_scope": self._pareto_scope(),
                        "estimated_kpis": _estimated_kpi_meta(selected, reason=source_error),
                    },
                    "filters": {"fleets": fleets or [], "systems": systems or [], "equipment": equipment or [], "subsystems": subsystems or []},
                    "kpis": {"equipment": 0, "actions": 0, "records": 0, "systems": 0, "activity_days": 0, "motor_share_pct": None, **_empty_estimated_kpis()},
                    "data": empty,
                }
        required_columns = {
            "action_id", "record_id", "job_id", "machine_code", "event_ts",
            "change_date", "action_type_name", "action_system_name",
            "action_subsystem_name", "action_detail_clean",
        }
        missing_columns = sorted(required_columns.difference(base.columns)) if not base.empty else []
        if missing_columns:
            return {
                "status": "error",
                "meta": {
                    "client": self.client.upper(),
                    "period": selected,
                    "period_label": selected or "Sin datos",
                    "available_months": months,
                    "source_start": None,
                    "source_end": None,
                    "source_status": source_status,
                    "is_current_period": False,
                    "detail_total": 0,
                    "missing_columns": missing_columns,
                    "pareto_scope": self._pareto_scope(),
                    "estimated_kpis": _estimated_kpi_meta(selected, reason="Faltan columnas requeridas en la fuente."),
                },
                "filters": {"fleets": fleets or [], "systems": systems or [], "equipment": equipment or [], "subsystems": subsystems or []},
                "kpis": {"equipment": 0, "actions": 0, "records": 0, "systems": 0, "activity_days": 0, "motor_share_pct": None, **_empty_estimated_kpis()},
                "data": empty,
            }
        if not selected or selected not in months:
            return {
                "status": "empty",
                "meta": {
                    "client": self.client.upper(),
                    "period": selected,
                    "period_label": "Sin datos",
                    "available_months": months,
                    "source_start": None,
                    "source_end": None,
                    "source_status": source_status,
                    "is_current_period": False,
                    "detail_total": 0,
                    "pareto_scope": self._pareto_scope(),
                    "estimated_kpis": _estimated_kpi_meta(selected, reason="El período no está disponible."),
                },
                "filters": {"fleets": fleets or [], "systems": systems or [], "equipment": equipment or [], "subsystems": subsystems or []},
                "kpis": {"equipment": 0, "actions": 0, "records": 0, "systems": 0, "activity_days": 0, "motor_share_pct": None, **_empty_estimated_kpis()},
                "data": empty,
            }

        start, end = self._month_bounds(selected)
        df = self._filtered_actions(
            systems=systems,
            equipment=equipment,
            subsystems=subsystems,
            date_start=start.isoformat(),
            date_end=(end - timedelta(days=1)).date().isoformat(),
            fleets=fleets,
        )
        source_start = base["change_date"].min() if not base.empty else None
        source_end = base["change_date"].max() if not base.empty else None
        source_start = source_start.isoformat() if pd.notna(source_start) else None
        source_end = source_end.isoformat() if pd.notna(source_end) else None

        equipment_filter = equipment or None
        if fleets:
            fleet_equipment = set(self.get_available_equipment(fleets=fleets))
            if equipment:
                fleet_equipment.intersection_update(equipment)
            equipment_filter = sorted(fleet_equipment)

        def _monthly_reliability_cards() -> dict:
            if systems or subsystems:
                return {
                    "status": "empty",
                    "values": {"mtbf_est_hours": None, "mttr_est_hours": None},
                    "meta": {
                        "source": "query_5_reliability_monthly.parquet",
                        "source_status": "unavailable",
                        "period": selected,
                        "equipment": equipment_filter or [],
                        "reason": "query_5 no tiene desglose por sistema/subsistema; las cards quedan sin dato para este filtro.",
                    },
                }
            return self.get_reliability_kpis(selected, equipment=equipment_filter)

        if df.empty:
            reliability_cards = _monthly_reliability_cards()
            empty_kpis = {
                "equipment": 0,
                "actions": 0,
                "records": 0,
                "systems": 0,
                "activity_days": 0,
                "motor_share_pct": None,
                **_empty_estimated_kpis(),
                **reliability_cards["values"],
            }
            return {
                "status": "empty",
                "meta": {
                    "client": self.client.upper(),
                    "period": selected,
                    "period_label": selected,
                    "available_months": months,
                    "source_start": source_start,
                    "source_end": source_end,
                    "source_status": source_status,
                    "is_current_period": selected == datetime.now().strftime("%Y-%m"),
                    "detail_total": 0,
                    "pareto_scope": self._pareto_scope(),
                    "estimated_kpis": _estimated_kpi_meta(selected, reason="No hay acciones para los filtros seleccionados."),
                    "reliability_kpis": reliability_cards["meta"],
                },
                "filters": {"fleets": fleets or [], "systems": systems or [], "equipment": equipment or [], "subsystems": subsystems or []},
                "kpis": empty_kpis,
                "data": empty,
            }

        action_ids = df["action_id"].dropna().astype(str)
        motor_df = df[self._is_motor_system(df["action_system_name"])].copy()
        total_actions = int(action_ids.nunique())
        motor_actions = int(motor_df["action_id"].dropna().astype(str).nunique())
        kpis = {
            "equipment": int(df["machine_code"].nunique()),
            "actions": total_actions,
            "records": int(df["record_id"].nunique()),
            "systems": int(df["action_system_name"].dropna().nunique()),
            "activity_days": int(df["change_date"].dt.strftime("%Y-%m-%d").nunique()),
            "motor_share_pct": round(motor_actions / total_actions * 100, 1) if total_actions else None,
        }
        daily = (
            df.assign(day=df["change_date"].dt.strftime("%Y-%m-%d"))
            .groupby("day", as_index=False)
            .agg(count=("action_id", "nunique"), equipment_count=("machine_code", "nunique"))
            .rename(columns={"day": "date"})
            .sort_values("date")
        )
        daily_hours, daily_time_source = self._daily_out_of_service_hours(df, start, end)
        # Keep interval-only days as well as action days so the monthly card
        # reconciles exactly with the daily hours series.
        daily = daily.merge(daily_hours, on="date", how="outer")
        daily["count"] = daily["count"].fillna(0).astype(int)
        daily["equipment_count"] = daily["equipment_count"].fillna(0).astype(int)
        daily["hours_out_of_service"] = daily["hours_out_of_service"].round(3)
        daily = daily.sort_values("date").reset_index(drop=True)
        time_kpis, time_meta = _calculate_monthly_time_kpis(
            daily_hours,
            selected,
            equipment_count=int(df["machine_code"].nunique()),
            source_name=daily_time_source,
            start=start,
            end=end,
        )
        kpis.update(_empty_estimated_kpis())
        kpis.update(time_kpis)
        reliability_cards = _monthly_reliability_cards()
        kpis.update(reliability_cards["values"])

        system_mix = (
            df.assign(system_name=df["action_system_name"].fillna("Sin sistema"))
            .groupby("system_name", as_index=False)["action_id"]
            .nunique()
            .rename(columns={"action_id": "count"})
            .sort_values(["count", "system_name"], ascending=[False, True])
            .reset_index(drop=True)
        )
        system_mix_detail = (
            df.assign(system_name=df["action_system_name"].fillna("Sin sistema"))
            .groupby(["system_name", "machine_code"], as_index=False)["action_id"]
            .nunique()
            .rename(columns={"machine_code": "equipment", "action_id": "count"})
            .sort_values(["system_name", "count", "equipment"], ascending=[True, False, True])
            .reset_index(drop=True)
        )

        # Summary Paretos are scoped to a system and grouped by equipment. Each
        # action_id is counted once per machine and the final point is pinned
        # to 100% so the cumulative line is stable for consumers.
        def _equipment_pareto(system_frame: pd.DataFrame) -> pd.DataFrame:
            result = (
                system_frame.groupby("machine_code", as_index=False)["action_id"]
                .nunique()
                .rename(columns={"machine_code": "equipment", "action_id": "count"})
                .sort_values(["count", "equipment"], ascending=[False, True])
                .reset_index(drop=True)
            )
            result["cumulative_pct"] = (
                result["count"].cumsum() / result["count"].sum() * 100
                if not result.empty
                else pd.Series(dtype=float)
            )
            if not result.empty:
                result.loc[result.index[-1], "cumulative_pct"] = 100.0
            return result

        def _system_pareto(system_frame: pd.DataFrame) -> pd.DataFrame:
            result = (
                system_frame.assign(system_name=system_frame["action_system_name"].fillna("Sin sistema"))
                .groupby("system_name", as_index=False)["action_id"]
                .nunique()
                .rename(columns={"action_id": "count"})
                .sort_values(["count", "system_name"], ascending=[False, True])
                .reset_index(drop=True)
            )
            result["cumulative_pct"] = (
                result["count"].cumsum() / result["count"].sum() * 100
                if not result.empty
                else pd.Series(dtype=float)
            )
            if not result.empty:
                result.loc[result.index[-1], "cumulative_pct"] = 100.0
            return result

        all_systems_mode = self.client in ALL_SYSTEMS_CLIENTS
        pareto = _equipment_pareto(df if all_systems_mode else motor_df)
        system_pareto = _system_pareto(df) if all_systems_mode else pd.DataFrame()
        train_force_df = df[self._is_train_force_system(df["action_system_name"])].copy()
        train_force_pareto = _equipment_pareto(train_force_df)

        equipment_df = (
            df.groupby("machine_code", as_index=False)["action_id"]
            .nunique()
            .rename(columns={"action_id": "count"})
            .sort_values(["count", "machine_code"], ascending=[False, True])
        )
        equipment_system = (
            df.assign(system_name=df["action_system_name"].fillna("Sin sistema"))
            .groupby(["machine_code", "system_name"], as_index=False)["action_id"]
            .nunique()
            .rename(columns={"action_id": "system_count"})
            .sort_values(["machine_code", "system_count", "system_name"], ascending=[True, False, True])
            .drop_duplicates("machine_code")
            .rename(columns={"system_name": "primary_system"})
        )
        equipment_df = equipment_df.merge(equipment_system[["machine_code", "primary_system"]], on="machine_code", how="left")
        matrix_df = (
            df.assign(system_name=df["action_system_name"].fillna("Sin sistema"))
            .groupby(["machine_code", "system_name"], as_index=False)["action_id"]
            .nunique()
            .rename(columns={"action_id": "count"})
        )
        # Keep the full equipment × system breakdown so the Summary chart can
        # retain every equipment row while using involved systems as colors.
        equipment_system_mix = (
            df.assign(system_name=df["action_system_name"].fillna("Sin sistema"))
            .groupby(["machine_code", "system_name"], as_index=False)["action_id"]
            .nunique()
            .rename(columns={"machine_code": "machine_code", "action_id": "count"})
            .sort_values(["machine_code", "count", "system_name"], ascending=[True, False, True])
            .reset_index(drop=True)
        )

        detail = df.copy()
        detail["date"] = detail["change_date"].dt.strftime("%Y-%m-%d")
        detail["timestamp_utc"] = detail["event_ts"].dt.strftime("%Y-%m-%d %H:%M UTC")
        detail = detail.rename(
            columns={
                "machine_code": "equipment",
                "action_system_name": "system_name",
                "action_subsystem_name": "subsystem_name",
                "action_type_name": "action_type",
                "action_detail_clean": "detail",
            }
        )
        detail["system_name"] = detail["system_name"].fillna("Sin sistema")
        detail["subsystem_name"] = detail["subsystem_name"].fillna("Sin subsistema")
        detail["detail"] = detail["detail"].fillna("Sin detalle")
        detail = detail.sort_values(["change_date", "event_ts"], ascending=False).head(detail_limit)
        detail_total = int(len(df))

        return {
            "status": "ok",
            "meta": {
                "client": self.client.upper(),
                "period": selected,
                "period_label": selected,
                "available_months": months,
                "source_start": source_start,
                "source_end": source_end,
                "source_status": source_status,
                "is_current_period": selected == datetime.now().strftime("%Y-%m"),
                "detail_total": detail_total,
                "pareto_scope": self._pareto_scope(),
                "estimated_kpis": time_meta,
                "reliability_kpis": reliability_cards["meta"],
                "time_measure": {
                    "source": daily_time_source,
                    "unit": "h-equipo",
                    "formula": "sum(intervalos unidos por equipo/día tras recortar al mes; duración last_event_ts - first_event_ts)",
                    "scope": "equipos filtrados; el total de flota puede superar 24 h por día",
                },
            },
            "filters": {"fleets": fleets or [], "systems": systems or [], "equipment": equipment or [], "subsystems": subsystems or []},
            "kpis": kpis,
            "data": {
                "daily": self._json_records(daily),
                "system_mix": self._json_records(system_mix),
                "system_mix_detail": self._json_records(system_mix_detail),
                "pareto": self._json_records(pareto),
                "system_pareto": self._json_records(system_pareto),
                "train_force_pareto": self._json_records(train_force_pareto),
                "equipment": self._json_records(equipment_df),
                "equipment_system_mix": self._json_records(equipment_system_mix),
                "matrix": self._json_records(matrix_df),
                "detail": self._json_records(detail[[
                    "action_id", "date", "timestamp_utc", "equipment", "system_name",
                    "subsystem_name", "action_type", "detail", "record_id", "job_id",
                ]]),
            },
        }

    def get_weekly_evidence(self, week: Optional[str] = None, equipment: Optional[List[str]] = None) -> dict:
        """Parse a weekly CSV into summary and day/system task rows."""
        weeks = self.get_available_weeks()
        selected = week or (weeks[-1] if weeks else None)
        if not selected or selected not in weeks:
            return {"status": "empty", "meta": {"week": selected, "available_weeks": weeks, "invalid_rows": 0}, "summary": [], "tasks": []}

        df = load_maintenance_week(self.client, selected)
        if df.empty:
            weekly_root = _data_path("mantentions", "golden", self.client)
            if not weekly_root.exists():
                weekly_root = _data_path("mantentions", "golden", self.client.upper())
            weekly_path = weekly_root / f"{selected}.csv"
            if not weekly_path.exists():
                return {
                    "status": "error",
                    "meta": {
                        "week": selected,
                        "available_weeks": weeks,
                        "invalid_rows": 0,
                        "error": f"No existe {weekly_path.name}.",
                    },
                    "summary": [],
                    "tasks": [],
                }
            return {
                "status": "error",
                "meta": {
                    "week": selected,
                    "available_weeks": weeks,
                    "invalid_rows": 0,
                    "error": f"No se pudo leer {weekly_path.name} o está vacío.",
                },
                "summary": [],
                "tasks": [],
            }

        required_columns = {"UnitId", "Summary", "Tasks_List"}
        missing_columns = sorted(required_columns.difference(df.columns))
        if missing_columns:
            return {
                "status": "error",
                "meta": {
                    "week": selected,
                    "available_weeks": weeks,
                    "invalid_rows": 0,
                    "missing_columns": missing_columns,
                },
                "summary": [],
                "tasks": [],
            }

        if equipment:
            df = df[df.get("UnitId", pd.Series(dtype=str)).isin(equipment)]
        summary = []
        tasks = []
        invalid_rows = 0
        for _, row in df.iterrows():
            unit = str(row.get("UnitId", "Sin equipo"))
            summary_value = row.get("Summary")
            if summary_value is None or (not isinstance(summary_value, (dict, list)) and bool(pd.isna(summary_value))):
                summary_value = "Sin resumen disponible"
            summary.append({"equipment": unit, "summary": str(summary_value)})
            raw = row.get("Tasks_List")
            if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                continue
            try:
                parsed = raw if isinstance(raw, (dict, list)) else json.loads(str(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                invalid_rows += 1
                continue
            if not isinstance(parsed, dict):
                invalid_rows += 1
                continue
            for day, systems in parsed.items():
                if not isinstance(systems, dict):
                    invalid_rows += 1
                    continue
                for system, values in systems.items():
                    values = values if isinstance(values, list) else [values]
                    for value in values:
                        tasks.append({"equipment": unit, "day": str(day), "system_name": str(system), "task": str(value)})

        status = "partial" if invalid_rows and (summary or tasks) else ("empty" if not summary else "ok")
        return {
            "status": status,
            "meta": {"week": selected, "available_weeks": weeks, "invalid_rows": invalid_rows},
            "summary": summary,
            "tasks": tasks,
        }

    def get_data_period_info(self) -> dict:
        """
        Get information about the period covered by the data.
        
        Returns:
            Dictionary with keys: period_start, period_end, period_label
        """
        if self.mode == "parquet":
            data = self._get_parquet_data()
            df_actions = data["actions"]
            
            if df_actions.empty:
                return {
                    "period_start": None,
                    "period_end": None,
                    "period_label": "Sin datos"
                }
            
            latest_date = df_actions['change_date'].max()
            if pd.isna(latest_date):
                return {
                    "period_start": None,
                    "period_end": None,
                    "period_label": "Sin datos"
                }
            
            # Usar el año y mes de la última fecha disponible
            latest_year = latest_date.year
            latest_month = latest_date.month
            
            month_start = datetime(latest_year, latest_month, 1)
            
            # Nombre del mes en español
            meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
            month_name = meses[latest_month - 1]
            
            return {
                "period_start": month_start,
                "period_end": latest_date,
                "period_label": f"{month_name} {latest_year}"
            }
        else:
            now = datetime.now()
            return {
                "period_start": datetime(now.year, now.month, 1),
                "period_end": now,
                "period_label": "Mes Actual"
            }
    
    def get_status_counts(
        self,
        systems: Optional[List[str]] = None,
        equipment: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Get count of machines by status (SANO vs DETENIDO).

        Args:
            systems: Restrict to machines with at least one action on any of
                these systems. Deliberately no date_start/date_end here -
                equipment status is real-time, not a historical figure, so
                the dashboard's date-range filter does not apply to it (only
                System/Equipment narrow which machines are counted).
            equipment: Restrict to these machine codes.

        Returns:
            DataFrame with columns: machine_status, n_machines
        """
        if self.mode == "dummy":
            data = self._get_dummy_data()
            df_machines = data["machines"]
            df_records = data["records"]

            # Determinar qué máquinas están detenidas (tienen records ongoing)
            detenidos = df_records[df_records["ongoing"] == True]["machine_id"].unique()

            status_data = [
                {"machine_status": "DETENIDO", "n_machines": len(detenidos)},
                {"machine_status": "SANO", "n_machines": len(df_machines) - len(detenidos)},
            ]
            return pd.DataFrame(status_data)

        elif self.mode == "parquet":
            # General only needs the compact KPI source for this operation;
            # do not parse the detailed action history on the login path.
            df_kpis = self._get_parquet_kpis()

            if df_kpis.empty:
                return pd.DataFrame([
                    {"machine_status": "DETENIDO", "n_machines": 0},
                    {"machine_status": "SANO", "n_machines": 0}
                ])

            if equipment:
                df_kpis = df_kpis[df_kpis["machine_code"].isin(equipment)]
            if systems:
                df_kpis = df_kpis[df_kpis["machine_code"].isin(self._machines_for_systems(systems))]

            # Usar equipment_status de query_4
            # equipment_status = 'OPERATIVO' significa SANO
            # Si tiene has_ongoing_maintenance = True, está DETENIDO
            
            # Contar máquinas por status
            # Por ahora todos están como OPERATIVO según los datos
            # Pero verificamos has_ongoing_maintenance para determinar si están detenidos
            n_detenidos = df_kpis['has_ongoing_maintenance'].sum() if 'has_ongoing_maintenance' in df_kpis.columns else 0
            total_machines = len(df_kpis)
            n_sanos = total_machines - n_detenidos
            
            logger.info(f"Status count - Total machines: {total_machines}, Detenidos: {n_detenidos}, Sanos: {n_sanos}")
            
            status_data = [
                {"machine_status": "DETENIDO", "n_machines": int(n_detenidos)},
                {"machine_status": "SANO", "n_machines": int(n_sanos)},
            ]
            return pd.DataFrame(status_data)
        
        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")
    
    def get_downtime_mtd(
        self,
        systems: Optional[List[str]] = None,
        equipment: Optional[List[str]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get total downtime hours for current month (Month-To-Date).

        Returns:
            DataFrame with column: total_downtime_hours_mtd
        """
        if self.mode == "dummy":
            data = self._get_dummy_data()
            df_records = data["records"]
            
            # Calcular MTD (Month-To-Date)
            now = datetime.now()
            month_start = datetime(now.year, now.month, 1)
            
            # Filtrar records del mes actual
            df_month = df_records[
                (df_records["start_date"] >= month_start) |
                (df_records["ongoing"] == True)
            ].copy()
            
            # Calcular horas de detención
            total_hours = 0.0
            for _, row in df_month.iterrows():
                start = row["start_date"]
                if pd.isna(start):
                    continue
                    
                # Si está ongoing, usar tiempo hasta ahora
                if row["ongoing"]:
                    end = now
                else:
                    end = row["end_date"]
                    if pd.isna(end):
                        continue
                
                # Solo contar desde inicio del mes
                effective_start = max(start, month_start)
                duration = (end - effective_start).total_seconds() / 3600
                total_hours += max(0, duration)
            
            return pd.DataFrame([{"total_downtime_hours_mtd": total_hours}])
        
        elif self.mode == "parquet":
            # Calculate MTD from the daily downtime data to ensure consistency
            df_daily = self.get_downtime_by_day_mtd(
                systems=systems, equipment=equipment, date_start=date_start, date_end=date_end
            )

            if df_daily.empty:
                return pd.DataFrame([{"total_downtime_hours_mtd": 0.0}])
            
            # Sum all daily hours for MTD total
            total_hours = df_daily['downtime_hours'].sum()
            
            logger.info(f"Total downtime MTD: {total_hours:.2f} hours (from {len(df_daily)} days)")
            return pd.DataFrame([{"total_downtime_hours_mtd": float(total_hours)}])
        
        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")
    
    def get_last_detentions(
        self,
        n_per_machine: int = 3,
        systems: Optional[List[str]] = None,
        equipment: Optional[List[str]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get last detention periods per machine.

        Args:
            n_per_machine: Number of last detentions per machine

        Returns:
            DataFrame with columns: machine_code, record_id, start_date, end_date, 
                                   ongoing, duration_hours, job_types
        """
        if self.mode == "dummy":
            data = self._get_dummy_data()
            df_machines = data["machines"]
            df_records = data["records"]
            df_jobs = data["jobs"]
            
            # Merge para obtener machine_code
            df = df_records.merge(
                df_machines[["machine_id", "machine_code"]], 
                on="machine_id"
            )
            
            # Calcular duración
            now = datetime.now()
            df["duration_hours"] = df.apply(
                lambda row: (
                    (now - row["start_date"]).total_seconds() / 3600 
                    if row["ongoing"] 
                    else (row["end_date"] - row["start_date"]).total_seconds() / 3600
                    if not pd.isna(row["end_date"])
                    else 0
                ),
                axis=1
            )
            
            # Agregar job_types por record
            job_types_by_record = df_jobs.groupby("record_id")["job_type"].apply(
                lambda x: ", ".join(x.unique())
            ).to_dict()
            
            df["job_types"] = df["record_id"].map(job_types_by_record).fillna("Sin trabajos")
            
            # Ordenar por fecha y tomar los últimos N por máquina
            df = df.sort_values("start_date", ascending=False)
            df = df.groupby("machine_code").head(n_per_machine)
            
            # Seleccionar columnas
            result = df[[
                "machine_code", "record_id", "start_date", "end_date", 
                "ongoing", "duration_hours", "job_types"
            ]].copy()
            
            return result.sort_values(["machine_code", "start_date"], ascending=[True, False])
        
        elif self.mode == "parquet":
            df_actions = self._filtered_actions(
                systems=systems, equipment=equipment, date_start=date_start, date_end=date_end
            )

            if df_actions.empty:
                return pd.DataFrame(columns=[
                    "machine_code", "record_id", "start_date", "end_date",
                    "ongoing", "duration_hours", "job_types"
                ])

            # Filtrar registros válidos (con machine_id y record_id)
            df_valid = df_actions[
                df_actions['machine_id'].notna() & 
                df_actions['record_id'].notna()
            ].copy()
            
            if df_valid.empty:
                return pd.DataFrame(columns=[
                    "machine_code", "record_id", "start_date", "end_date",
                    "ongoing", "duration_hours", "job_types"
                ])
            
            # Agrupar por machine_id (unit_id) y record_id.  The source
            # interval table is authoritative for the temporal boundaries;
            # action timestamps are only a compatibility fallback.
            grouped = df_valid.groupby(['machine_id', 'record_id', 'machine_code'], dropna=True)

            interval_source = self._get_parquet_data().get("records", pd.DataFrame())
            interval_map = {}
            if {"record_id", "machine_code", "first_event_ts", "last_event_ts"}.issubset(interval_source.columns):
                for interval in interval_source.itertuples(index=False):
                    interval_map[(interval.record_id, interval.machine_code)] = (
                        interval.first_event_ts,
                        interval.last_event_ts,
                    )
            
            records = []
            for (machine_id, record_id, machine_code), group in grouped:
                n_actions = len(group)
                
                # Crear job_types como "accion-sistema" sin duplicados
                # Combinar action_type_name con action_system_name
                action_system_pairs = []
                for _, row in group.iterrows():
                    action_type = row.get('action_type_name', '')
                    action_system = row.get('action_system_name', '')
                    if pd.notna(action_type) and pd.notna(action_system):
                        pair = f"{action_type}-{action_system}"
                        if pair not in action_system_pairs:
                            action_system_pairs.append(pair)
                
                job_types = ", ".join(action_system_pairs) if len(action_system_pairs) > 0 else "Sin información"
                
                interval = interval_map.get((record_id, machine_code))
                start_date, end_date = interval if interval else (
                    pd.to_datetime(group['event_ts'].min(), utc=True, format="mixed"),
                    pd.to_datetime(group['event_ts'].max(), utc=True, format="mixed"),
                )
                if pd.isna(start_date) or pd.isna(end_date) or end_date < start_date:
                    duration_hours = None
                else:
                    duration_hours = round((end_date - start_date).total_seconds() / 3600, 3)
                
                records.append({
                    'machine_code': machine_code,
                    'machine_id': machine_id,
                    'record_id': record_id,
                    'start_date': start_date,
                    'end_date': end_date,
                    'ongoing': False,  # Datos históricos
                    'duration_hours': duration_hours,
                    'job_types': job_types,
                    'n_actions': n_actions
                })
            
            df = pd.DataFrame(records)
            
            if df.empty:
                return pd.DataFrame(columns=[
                    "machine_code", "record_id", "start_date", "end_date",
                    "ongoing", "duration_hours", "job_types"
                ])
            
            # Ordenar por fecha descendente (más reciente primero)
            df = df.sort_values("start_date", ascending=False)
            
            # Tomar los últimos N períodos de detención por equipo (machine_code)
            df = df.groupby("machine_code", dropna=True).head(n_per_machine)
            
            # Seleccionar columnas finales (sin machine_id interno)
            result = df[[
                "machine_code", "record_id", "start_date", "end_date",
                "ongoing", "duration_hours", "job_types"
            ]].copy()
            
            return result.sort_values(["machine_code", "start_date"], ascending=[True, False])
        
        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")
    
    def get_jobs_last_week(
        self,
        systems: Optional[List[str]] = None,
        equipment: Optional[List[str]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get jobs performed in the last week (or, when an explicit date range
        is given, within that range instead of the rolling last-week window).

        Returns:
            DataFrame with columns: job_id, machine_code, system_name, subsystem_name,
                                   job_type, start_date, end_date, ongoing, notes
        """
        if self.mode == "dummy":
            data = self._get_dummy_data()
            df_jobs = data["jobs"]
            df_records = data["records"]
            df_machines = data["machines"]
            df_systems = data["systems"]
            df_subsystems = data["subsystems"]
            
            # Filtrar última semana
            now = datetime.now()
            week_ago = now - timedelta(days=7)
            
            df = df_jobs[df_jobs["start_date"] >= week_ago].copy()
            
            # Merge con records para obtener machine_id
            df = df.merge(df_records[["record_id", "machine_id"]], on="record_id")
            
            # Merge con machines para obtener machine_code
            df = df.merge(df_machines[["machine_id", "machine_code"]], on="machine_id")
            
            # Merge con systems
            df = df.merge(
                df_systems[["system_id", "system_name"]], 
                on="system_id", 
                how="left"
            )
            
            # Merge con subsystems
            df = df.merge(
                df_subsystems[["subsystem_id", "subsystem_name"]], 
                on="subsystem_id", 
                how="left"
            )
            
            # Seleccionar y ordenar columnas
            result = df[[
                "job_id", "machine_code", "system_name", "subsystem_name",
                "job_type", "start_date", "end_date", "ongoing", "notes"
            ]].copy()
            
            return result.sort_values("start_date", ascending=False)
        
        elif self.mode == "parquet":
            df_actions = self._filtered_actions(systems=systems, equipment=equipment)

            if df_actions.empty:
                return pd.DataFrame(columns=[
                    "job_id", "machine_code", "system_name", "subsystem_name",
                    "job_type", "start_date", "end_date", "ongoing", "notes"
                ])

            if date_start or date_end:
                # Explicit range from the dashboard filter overrides the
                # rolling "last week" window entirely.
                df = self._filtered_actions(
                    systems=systems, equipment=equipment, date_start=date_start, date_end=date_end
                )
            else:
                # Filtrar últimas 10 semanas (70 días) para capturar datos históricos,
                # ancladas a la última fecha disponible en los datos (no a la fecha
                # real de hoy, que puede estar muy por delante de los datos cargados).
                latest_date = df_actions["change_date"].max()
                if pd.isna(latest_date):
                    df = df_actions.copy()
                else:
                    period_start = latest_date - timedelta(days=70)
                    df = df_actions[df_actions["change_date"] >= period_start].copy()

                    # Si no hay datos en el período, usar todos los datos disponibles
                    if df.empty:
                        df = df_actions.copy()
            
            # Preparar datos para el formato esperado usando las columnas correctas
            result = df[[
                'job_id', 'machine_code', 'job_system_name', 'job_subsystem_name',
                'action_type_name', 'event_ts', 'action_detail_clean'
            ]].copy()
            
            # Renombrar columnas
            result = result.rename(columns={
                'job_system_name': 'system_name',
                'job_subsystem_name': 'subsystem_name',
                'action_type_name': 'job_type',
                'event_ts': 'start_date',
                'action_detail_clean': 'notes'
            })
            
            # Agregar columnas faltantes
            result["end_date"] = result["start_date"]  # Acciones instantáneas
            result["ongoing"] = False
            
            # Limitar a 100 registros más recientes
            result = result.sort_values("start_date", ascending=False).head(100)
            
            return result
        
        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")
    
    # CDA's legacy by-system Pareto omits these generic categories; EMIN and
    # CAPSTONE retain every source system, including these labels.
    _PARETO_EXCLUDED_SYSTEMS = {"Equipo", "Estación del Operador - Cabina"}

    def get_maintenance_by_system(
        self,
        systems: Optional[List[str]] = None,
        equipment: Optional[List[str]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get maintenance record counts grouped by system, for a Pareto chart.
        CDA excludes generic categories; EMIN and CAPSTONE retain every system.

        Returns:
            DataFrame with columns: system_name, count, cumulative_pct
            (sorted descending by count).
        """
        if self.mode == "dummy":
            data = self._get_dummy_data()
            df_jobs = data["jobs"]
            df_systems = data["systems"]

            if df_jobs.empty:
                return pd.DataFrame(columns=["system_name", "count", "cumulative_pct"])

            df = df_jobs.merge(
                df_systems[["system_id", "system_name"]],
                on="system_id",
                how="left"
            )
            counts = df["system_name"].fillna("Sin Sistema").value_counts().reset_index()
            counts.columns = ["system_name", "count"]

        elif self.mode == "parquet":
            df_actions = self._filtered_actions(
                systems=systems, equipment=equipment, date_start=date_start, date_end=date_end
            )

            if df_actions.empty:
                return pd.DataFrame(columns=["system_name", "count", "cumulative_pct"])

            counts = df_actions["action_system_name"].fillna("Sin Sistema").value_counts().reset_index()
            counts.columns = ["system_name", "count"]

        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")

        if self.client not in ALL_SYSTEMS_CLIENTS:
            counts = counts[~counts["system_name"].isin(self._PARETO_EXCLUDED_SYSTEMS)]
        counts = counts.sort_values("count", ascending=False).reset_index(drop=True)
        total = int(counts["count"].sum())
        counts["cumulative_pct"] = (counts["count"].cumsum() / total * 100) if total else 0.0
        # Guard against float drift so the last point always reads exactly 100%.
        if len(counts):
            counts.loc[counts.index[-1], "cumulative_pct"] = 100.0

        return counts

    def get_downtime_by_day_mtd(
        self,
        systems: Optional[List[str]] = None,
        equipment: Optional[List[str]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get downtime hours by day. With no explicit date_start/date_end, uses
        the most recent month with data available (MTD - Month To Date); if
        no data exists for the current month, uses the last month with
        available data. An explicit date range overrides that auto-detected
        month entirely and is used as-is.

        Returns:
            DataFrame with columns: date, downtime_hours
        """
        if self.mode == "dummy":
            data = self._get_dummy_data()
            df_records = data["records"]
            
            now = datetime.now()
            month_start = datetime(now.year, now.month, 1)
            
            # Crear rango de días del mes
            days = pd.date_range(month_start, now, freq='D')
            daily_hours = []
            
            for day in days:
                day_start = day
                day_end = day + timedelta(days=1)
                
                # Filtrar records activos en este día
                df_day = df_records[
                    (df_records["start_date"] < day_end) &
                    (
                        (df_records["end_date"] >= day_start) |
                        (df_records["ongoing"] == True)
                    )
                ]
                
                # Calcular horas de detención en este día
                day_hours = 0.0
                for _, row in df_day.iterrows():
                    start = max(row["start_date"], day_start)
                    if row["ongoing"]:
                        end = min(now, day_end)
                    else:
                        end = min(row["end_date"], day_end)
                    
                    duration = (end - start).total_seconds() / 3600
                    day_hours += max(0, duration)
                
                daily_hours.append({
                    "date": day.date(),
                    "downtime_hours": day_hours
                })
            
            return pd.DataFrame(daily_hours)
        
        elif self.mode == "parquet":
            df_actions = self._filtered_actions(systems=systems, equipment=equipment)

            if df_actions.empty:
                return pd.DataFrame(columns=["date", "downtime_hours"])

            df_actions['date'] = df_actions['change_date'].dt.date

            if date_start or date_end:
                # Explicit range from the dashboard filter overrides the
                # auto-detected "latest available month" entirely.
                df_month = self._filtered_actions(
                    systems=systems, equipment=equipment, date_start=date_start, date_end=date_end
                )
                if not df_month.empty:
                    df_month['date'] = df_month['change_date'].dt.date
                if df_month.empty:
                    return pd.DataFrame(columns=["date", "downtime_hours"])
            else:
                # Encontrar el último mes con datos disponibles
                latest_date = df_actions['change_date'].max()

                if pd.isna(latest_date):
                    logger.warning("No valid dates found in maintenance actions")
                    return pd.DataFrame(columns=["date", "downtime_hours"])

                # Usar el año y mes de la última fecha disponible
                latest_year = latest_date.year
                latest_month = latest_date.month

                # Calcular inicio y fin del último mes con datos
                month_start = pd.Timestamp(datetime(latest_year, latest_month, 1), tz='UTC')

                # Fin del mes: primer día del siguiente mes - 1 día
                if latest_month == 12:
                    month_end = pd.Timestamp(datetime(latest_year + 1, 1, 1), tz='UTC')
                else:
                    month_end = pd.Timestamp(datetime(latest_year, latest_month + 1, 1), tz='UTC')

                # Filtrar acciones del último mes con datos
                df_month = df_actions[
                    (df_actions["change_date"] >= month_start) &
                    (df_actions["change_date"] < month_end)
                ].copy()

                if df_month.empty:
                    logger.warning(f"No maintenance actions found for last available month ({latest_year}-{latest_month:02d})")
                    return pd.DataFrame(columns=["date", "downtime_hours"])
            
            if date_start:
                interval_start = pd.Timestamp(date_start)
                interval_start = interval_start.tz_localize("UTC") if interval_start.tzinfo is None else interval_start.tz_convert("UTC")
            else:
                interval_start = df_month["change_date"].min().floor("D")
            if date_end:
                interval_end = pd.Timestamp(date_end)
                interval_end = interval_end.tz_localize("UTC") if interval_end.tzinfo is None else interval_end.tz_convert("UTC")
                interval_end += pd.Timedelta(days=1)
            else:
                interval_end = df_month["change_date"].max().floor("D") + pd.Timedelta(days=1)

            daily_hours, _ = self._daily_out_of_service_hours(df_month, interval_start, interval_end)
            return daily_hours.rename(columns={"hours_out_of_service": "downtime_hours"})
        
        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")


# Global instance - now keyed by (mode, client)
_repositories = {}


def get_repository(mode="dummy", client="cda") -> MaintenanceRepository:
    """
    Get or create repository instance.
    
    Args:
        mode: "dummy" for in-memory data, "parquet" for parquet files
        client: Client name (e.g., "cda", "emin")
        
    Returns:
        MaintenanceRepository instance
    """
    global _repositories
    key = (mode, client.lower())
    if key not in _repositories:
        _repositories[key] = MaintenanceRepository(mode, client)
    return _repositories[key]
