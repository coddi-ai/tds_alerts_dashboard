"""
Repository layer for Mantenciones General dashboard.
Provides data access functions that can work in dummy or production mode.
"""

import json
import math
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List
import logging

from src.data.dummy_generator import generate_dummy_tables
from src.data.loaders import (
    _data_path,
    _get_mantentions_data_path,
    load_maintenance_actions_all_equipment,
    load_business_kpis,
    list_maintenance_weeks,
    load_maintenance_week,
)

logger = logging.getLogger(__name__)


# Production files label the target as ``Sistema de Motor`` while compact
# fixtures and some client extracts use ``Motor``/``Sistema Motor``.  These
# are the only accepted aliases for the Summary Pareto scope; other systems
# must never enter that aggregation.
MOTOR_SYSTEM_ALIASES = frozenset({"motor", "sistema motor", "sistema de motor"})
PARETO_SCOPE = {
    "system_filter": "Motor",
    "system_column": "action_system_name",
    "system_aliases": sorted(MOTOR_SYSTEM_ALIASES),
    "dimension": "equipment",
    "dimension_source": "machine_code",
    "metric": "unique_action_id_count",
}

# The action extract has no governed operating-hours or repair-duration
# measurement.  These constants make the fallback proxy reproducible and
# deliberately visible in the payload metadata/UI labels.
ESTIMATED_HOURS_PER_ACTION = 1.5
SCHEDULE_HOURS_PER_DAY = 24.0


def _empty_estimated_kpis() -> dict:
    return {
        "availability_est_pct": None,
        "downtime_est_hours": None,
        "mtbf_est_hours": None,
        "mttr_est_hours": None,
    }


def _estimated_kpi_meta(
    period: Optional[str] = None,
    status: str = "unavailable",
    equipment: int = 0,
    actions: int = 0,
    records: int = 0,
    reason: Optional[str] = None,
    source_kind: str = "actions_monthly_proxy",
    source: Optional[list[str]] = None,
    source_columns: Optional[list[str]] = None,
    window_label: str = "mes seleccionado",
    reference_start: Optional[str] = None,
    reference_end: Optional[str] = None,
    event_count: Optional[int] = None,
    scheduled_days: Optional[int] = None,
    downtime_formula: Optional[str] = None,
) -> dict:
    """Describe the conservative estimated KPI contract and its coverage."""
    calendar_days = 0
    if period:
        try:
            calendar_days = int(pd.Period(period, freq="M").days_in_month)
        except (TypeError, ValueError):
            calendar_days = 0
    schedule_days = calendar_days if scheduled_days is None else scheduled_days
    scheduled_hours = equipment * schedule_days * SCHEDULE_HOURS_PER_DAY
    source = source or ["query_3_actions_all_equipment.parquet"]
    source_columns = source_columns or ["action_id", "record_id", "machine_code", "change_date"]
    meta = {
        "status": status,
        "label": "ESTIMADO",
        "source_kind": source_kind,
        "confidence": "precalculated_proxy" if source_kind == "business_kpis_70d" else "proxy",
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
            f"{ESTIMATED_HOURS_PER_ACTION:g} h por acción única como fallback de indisponibilidad/tiempo de reparación.",
            "Horas programadas proxy = equipos cubiertos × días de la ventana × 24 h.",
            "Eventos proxy = reparaciones_70d o registros/acciones únicos; no son fallas confirmadas.",
            "Horas operativas proxy = max(horas programadas proxy − downtime estimado, 0).",
            "Los valores siguen rotulados ESTIMADO aunque provengan de KPIs precalculados.",
        ],
        "formula": {
            "downtime_est_hours": downtime_formula or f"unique_action_id_count × {ESTIMATED_HOURS_PER_ACTION:g}",
            "availability_est_pct": "max(scheduled_hours_proxy − downtime_est_hours, 0) / scheduled_hours_proxy × 100",
            "mtbf_est_hours": "operating_hours_proxy / event_count_proxy",
            "mttr_est_hours": "downtime_est_hours / event_count_proxy",
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
    """Prefer the governed 70-day KPI extract; fall back to monthly actions."""
    if df.empty:
        return _empty_estimated_kpis(), _estimated_kpi_meta(period, reason="No hay acciones para el período/filtros.")
    equipment = int(df["machine_code"].nunique())
    actions = int(df["action_id"].dropna().astype(str).nunique())
    records = int(df["record_id"].dropna().astype(str).nunique())
    required = {"machine_code", "downtime_hours_70d", "repairs_70d", "reference_date"}
    kpi = business_kpis.copy() if business_kpis is not None else pd.DataFrame()
    can_use_kpi = not kpi.empty and required.issubset(kpi.columns) and not filter_reason
    if can_use_kpi and equipment_filter:
        kpi = kpi[kpi["machine_code"].isin(equipment_filter)].copy()
        can_use_kpi = not kpi.empty
    if can_use_kpi:
        kpi["downtime_hours_70d"] = pd.to_numeric(kpi["downtime_hours_70d"], errors="coerce")
        kpi["repairs_70d"] = pd.to_numeric(kpi["repairs_70d"], errors="coerce")
        kpi = kpi.dropna(subset=["downtime_hours_70d"])
        can_use_kpi = not kpi.empty
    anomaly_reason = None
    if can_use_kpi:
        downtime_probe = float(kpi["downtime_hours_70d"].sum())
        scheduled_probe = int(kpi["machine_code"].nunique()) * 70 * SCHEDULE_HOURS_PER_DAY
        repairs_values = kpi["repairs_70d"].fillna(0).tolist()
        if (
            not math.isfinite(downtime_probe)
            or downtime_probe < 0
            or downtime_probe > scheduled_probe
            or any(not math.isfinite(float(value)) or float(value) < 0 for value in repairs_values)
        ):
            anomaly_reason = (
                "query_4 rechazado por plausibilidad: downtime_hours_70d debe ser finito, no negativo "
                "y no superar las horas calendario proxy de la misma ventana."
            )
            can_use_kpi = False
    if can_use_kpi:
        equipment = int(kpi["machine_code"].nunique())
        downtime = float(kpi["downtime_hours_70d"].sum())
        repairs = float(kpi["repairs_70d"].fillna(0).sum())
        event_count = int(repairs) if repairs > 0 else int(pd.to_numeric(kpi.get("total_actions_70d"), errors="coerce").fillna(0).sum()) if "total_actions_70d" in kpi else 0
        if event_count <= 0:
            event_count = records
        reference = pd.to_datetime(kpi["reference_date"], utc=True, errors="coerce").dropna()
        reference_end = reference.max().isoformat() if not reference.empty else None
        reference_start = (reference.min() - pd.Timedelta(days=69)).isoformat() if not reference.empty else None
        meta = _estimated_kpi_meta(
            period,
            status="estimated",
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
            status="estimated",
            equipment=equipment,
            actions=actions,
            records=records,
            reason=filter_reason or anomaly_reason or "query_4_business_kpis.parquet ausente, incompleto o sin valores utilizables; se usa fallback mensual.",
        )
        event_count = records
        downtime = actions * ESTIMATED_HOURS_PER_ACTION
    scheduled_hours = float(meta["coverage"]["scheduled_hours_proxy"])
    operating = max(scheduled_hours - downtime, 0.0)
    values = {
        "availability_est_pct": round(operating / scheduled_hours * 100, 1) if scheduled_hours else None,
        "downtime_est_hours": round(downtime, 1),
        "mtbf_est_hours": round(operating / event_count, 1) if event_count else None,
        "mttr_est_hours": round(downtime / event_count, 1) if event_count else None,
    }
    return values, meta


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
        self._parquet_kpis_cache = None

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
                "kpis": self._get_parquet_kpis(),
            }
        return self._parquet_cache

    def _filtered_actions(
        self,
        systems: Optional[List[str]] = None,
        equipment: Optional[List[str]] = None,
        subsystems: Optional[List[str]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Apply the dashboard's System / Equipment / date-range filters to the
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

    def get_available_equipment(self, systems: Optional[List[str]] = None) -> List[str]:
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
            return sorted(df_actions["machine_code"].dropna().unique().tolist())
        elif self.mode == "dummy":
            data = self._get_dummy_data()
            return sorted(data["machines"]["machine_code"].tolist())
        else:
            raise NotImplementedError("Production mode not yet implemented")

    def refresh(self) -> None:
        """Drop this client's in-process caches so a manual refresh sees new files."""
        self._dummy_cache = None
        self._parquet_cache = None
        self._parquet_actions_cache = None
        self._parquet_kpis_cache = None

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
        """Return calendar months with valid action dates in YYYY-MM order."""
        if self.mode != "parquet":
            if self.mode == "dummy":
                df = self._get_dummy_data()["jobs"]
                dates = pd.to_datetime(df.get("start_date"), errors="coerce")
                return sorted(dates.dropna().dt.strftime("%Y-%m").unique().tolist())
            raise NotImplementedError("Production mode not yet implemented")
        df = self._get_parquet_data()["actions"]
        if df.empty or "change_date" not in df:
            return []
        return sorted(df["change_date"].dropna().dt.strftime("%Y-%m").unique().tolist())

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
            "pareto": [],
            "equipment": [],
            "matrix": [],
            "detail": [],
        }

    @staticmethod
    def _json_records(frame: pd.DataFrame) -> list[dict]:
        """Convert a frame to records without leaking numpy NaN values."""
        if frame.empty:
            return []
        return frame.astype(object).where(pd.notna(frame), None).to_dict("records")

    @staticmethod
    def _pareto_scope() -> dict:
        """Return the serializable contract for the Summary Pareto."""
        return {
            **PARETO_SCOPE,
            "system_aliases": list(PARETO_SCOPE["system_aliases"]),
        }

    @staticmethod
    def _is_motor_system(values: pd.Series) -> pd.Series:
        """Match only the canonical Motor system aliases, case-insensitively."""
        normalized = values.astype("string").str.strip().str.casefold()
        return normalized.isin(MOTOR_SYSTEM_ALIASES)

    def get_monthly_payload(
        self,
        period: Optional[str] = None,
        systems: Optional[List[str]] = None,
        equipment: Optional[List[str]] = None,
        subsystems: Optional[List[str]] = None,
        detail_limit: int = 250,
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
                    "filters": {"systems": systems or [], "equipment": equipment or [], "subsystems": subsystems or []},
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
                "filters": {"systems": systems or [], "equipment": equipment or [], "subsystems": subsystems or []},
                "kpis": {"equipment": 0, "actions": 0, "records": 0, "systems": 0, "activity_days": 0, "motor_share_pct": None, **_empty_estimated_kpis()},
                "data": empty,
            }
        if not selected or selected not in months:
            return {
                "status": "empty",
                "meta": {
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
                "filters": {"systems": systems or [], "equipment": equipment or [], "subsystems": subsystems or []},
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
        )
        source_start = base["change_date"].min() if not base.empty else None
        source_end = base["change_date"].max() if not base.empty else None
        source_start = source_start.isoformat() if pd.notna(source_start) else None
        source_end = source_end.isoformat() if pd.notna(source_end) else None

        if df.empty:
            return {
                "status": "empty",
                "meta": {
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
                },
                "filters": {"systems": systems or [], "equipment": equipment or [], "subsystems": subsystems or []},
                "kpis": {"equipment": 0, "actions": 0, "records": 0, "systems": 0, "activity_days": 0, "motor_share_pct": None, **_empty_estimated_kpis()},
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
        business_kpis = self._get_parquet_data().get("kpis", pd.DataFrame()) if self.mode == "parquet" else pd.DataFrame()
        filter_reason = "Los KPIs 70d no tienen desglose por sistema/subsistema; se usa el fallback mensual." if systems or subsystems else None
        estimated_kpis, estimated_meta = _calculate_estimated_kpis(
            df,
            selected,
            business_kpis=business_kpis,
            equipment_filter=equipment,
            filter_reason=filter_reason,
        )
        kpis.update(estimated_kpis)

        daily = (
            df.assign(day=df["change_date"].dt.strftime("%Y-%m-%d"))
            .groupby("day", as_index=False)["action_id"]
            .nunique()
            .rename(columns={"day": "date", "action_id": "count"})
            .sort_values("date")
        )

        system_mix = (
            df.assign(system_name=df["action_system_name"].fillna("Sin sistema"))
            .groupby("system_name", as_index=False)["action_id"]
            .nunique()
            .rename(columns={"action_id": "count"})
            .sort_values(["count", "system_name"], ascending=[False, True])
            .reset_index(drop=True)
        )

        # The Summary Pareto is intentionally scoped to Motor and grouped by
        # equipment.  It counts each action_id once per machine, never mixes
        # other systems, and keeps the existing monthly payload envelope.
        pareto = (
            motor_df.groupby("machine_code", as_index=False)["action_id"]
            .nunique()
            .rename(columns={"machine_code": "equipment", "action_id": "count"})
            .sort_values(["count", "equipment"], ascending=[False, True])
            .reset_index(drop=True)
        )
        pareto["cumulative_pct"] = (
            pareto["count"].cumsum() / pareto["count"].sum() * 100
            if not pareto.empty
            else pd.Series(dtype=float)
        )
        if not pareto.empty:
            pareto.loc[pareto.index[-1], "cumulative_pct"] = 100.0

        equipment_df = (
            df.groupby("machine_code", as_index=False)["action_id"]
            .nunique()
            .rename(columns={"action_id": "count"})
            .sort_values(["count", "machine_code"], ascending=[False, True])
        )
        matrix_df = (
            df.assign(system_name=df["action_system_name"].fillna("Sin sistema"))
            .groupby(["machine_code", "system_name"], as_index=False)["action_id"]
            .nunique()
            .rename(columns={"action_id": "count"})
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
                "period": selected,
                "period_label": selected,
                "available_months": months,
                "source_start": source_start,
                "source_end": source_end,
                "source_status": source_status,
                "is_current_period": selected == datetime.now().strftime("%Y-%m"),
                "detail_total": detail_total,
                "pareto_scope": self._pareto_scope(),
                "estimated_kpis": estimated_meta,
            },
            "filters": {"systems": systems or [], "equipment": equipment or [], "subsystems": subsystems or []},
            "kpis": kpis,
            "data": {
                "daily": self._json_records(daily),
                "system_mix": self._json_records(system_mix),
                "pareto": self._json_records(pareto),
                "equipment": self._json_records(equipment_df),
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
            
            # Agrupar por machine_id (unit_id) y record_id
            # Cada combinación representa un período de detención único
            grouped = df_valid.groupby(['machine_id', 'record_id', 'machine_code'], dropna=True)
            
            records = []
            for (machine_id, record_id, machine_code), group in grouped:
                # Usar event_ts como fecha y hora del evento (momento de la detención)
                event_datetime = pd.to_datetime(group['event_ts'].iloc[0], utc=True)
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
                
                # Para duración, usamos el conteo de acciones como proxy
                # Cada acción representa aproximadamente 1-2 horas de trabajo
                # Esto es una estimación basada en la actividad registrada
                estimated_duration = n_actions * 1.5  # 1.5 horas por acción en promedio
                
                records.append({
                    'machine_code': machine_code,
                    'machine_id': machine_id,
                    'record_id': record_id,
                    'start_date': event_datetime,
                    'end_date': event_datetime,  # Misma fecha para registros históricos
                    'ongoing': False,  # Datos históricos
                    'duration_hours': estimated_duration,
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
    
    # Excluded from the by-system Pareto: "Equipo" is a generic catch-all
    # system (not a specific one) and "Estación del Operador - Cabina" is out
    # of scope for this view - both would otherwise dominate the chart.
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
        Excludes _PARETO_EXCLUDED_SYSTEMS.

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
            
            # Contar acciones por día como proxy de actividad de mantenimiento
            daily_counts = df_month.groupby('date').size().reset_index(name='action_count')
            
            # Estimar horas de downtime: 
            # - Cada acción representa ~1.5 horas de trabajo en promedio
            # - Esto es un estimado basado en la actividad registrada
            daily_counts['downtime_hours'] = daily_counts['action_count'] * 1.5

            logger.info(f"Data range: {len(daily_counts)} days from {daily_counts['date'].min()} to {daily_counts['date'].max()}")
            logger.info(f"Total actions: {daily_counts['action_count'].sum()}, Total hours: {daily_counts['downtime_hours'].sum():.2f}")
            
            return daily_counts[['date', 'downtime_hours']].sort_values('date')
        
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
