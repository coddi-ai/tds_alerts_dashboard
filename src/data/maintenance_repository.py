"""
Repository layer for Mantenciones General dashboard.
Provides data access functions that can work in dummy or production mode.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import logging

from src.data.dummy_generator import generate_dummy_tables
from src.data.loaders import (
    load_maintenance_actions_all_equipment,
    load_business_kpis
)

logger = logging.getLogger(__name__)


class MaintenanceRepository:
    """Repository for maintenance data access."""
    
    def __init__(self, mode="dummy"):
        """
        Initialize repository.
        
        Args:
            mode: "dummy" for in-memory data, "parquet" for parquet files, "prod" for database queries
        """
        self.mode = mode
        self._dummy_cache = None
        self._parquet_cache = None
        
    def _get_dummy_data(self):
        """Get or generate dummy data."""
        if self._dummy_cache is None:
            logger.info("Generating dummy maintenance data...")
            self._dummy_cache = generate_dummy_tables()
        return self._dummy_cache
    
    def _get_parquet_data(self):
        """Get or load parquet data."""
        if self._parquet_cache is None:
            logger.info("Loading maintenance data from parquet files...")
            self._parquet_cache = {
                "actions": load_maintenance_actions_all_equipment(),
                "kpis": load_business_kpis()
            }
        return self._parquet_cache
    
    def get_status_counts(self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> pd.DataFrame:
        """
        Get count of machines by status (SANO vs DETENIDO).
        
        Args:
            start_date: Start date for filtering
            end_date: End date for filtering
            
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
            data = self._get_parquet_data()
            df_kpis = data["kpis"]
            
            if df_kpis.empty:
                return pd.DataFrame([
                    {"machine_status": "DETENIDO", "n_machines": 0},
                    {"machine_status": "SANO", "n_machines": 0}
                ])
            
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
    
    def get_downtime_mtd(self) -> pd.DataFrame:
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
            data = self._get_parquet_data()
            df_kpis = data["kpis"]
            
            if df_kpis.empty:
                return pd.DataFrame([{"total_downtime_hours_mtd": 0.0}])
            
            # Usar downtime_hours_70d pre-calculado de query_4
            total_hours = df_kpis['downtime_hours_70d'].sum() if 'downtime_hours_70d' in df_kpis.columns else 0.0
            
            logger.info(f"Total downtime (70d): {total_hours:.2f} hours")
            return pd.DataFrame([{"total_downtime_hours_mtd": float(total_hours)}])
        
        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")
    
    def get_last_detentions(self, n_per_machine: int = 3) -> pd.DataFrame:
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
            data = self._get_parquet_data()
            df_actions = data["actions"]
            
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
                # Calcular tiempo de detención: max(event_ts) - min(event_ts)
                start_date = group['event_ts'].min()
                end_date = group['event_ts'].max()
                duration_hours = (end_date - start_date).total_seconds() / 3600
                
                # Obtener array de action_type_name únicos
                action_types = group['action_type_name'].dropna().unique()
                job_types = ", ".join(action_types) if len(action_types) > 0 else "Sin información"
                
                records.append({
                    'machine_code': machine_code,
                    'machine_id': machine_id,
                    'record_id': record_id,
                    'start_date': start_date,
                    'end_date': end_date,
                    'ongoing': False,  # Datos históricos
                    'duration_hours': duration_hours,
                    'job_types': job_types
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
    
    def get_jobs_last_week(self) -> pd.DataFrame:
        """
        Get jobs performed in the last week.
        
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
            data = self._get_parquet_data()
            df_actions = data["actions"]
            
            if df_actions.empty:
                return pd.DataFrame(columns=[
                    "job_id", "machine_code", "system_name", "subsystem_name",
                    "job_type", "start_date", "end_date", "ongoing", "notes"
                ])
            
            # Filtrar últimas 10 semanas (70 días) para capturar datos históricos
            now = datetime.now()
            period_start = pd.Timestamp(now - timedelta(days=70))
            
            # Filtrar por change_date (sin timezone)
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
    
    def get_downtime_by_day_mtd(self) -> pd.DataFrame:
        """
        Get downtime hours by day for current month.
        
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
            data = self._get_parquet_data()
            df_actions = data["actions"]
            
            if df_actions.empty:
                return pd.DataFrame(columns=["date", "downtime_hours"])
            
            now = datetime.now()
            # Usar últimas 10 semanas (70 días)
            period_start = pd.Timestamp(now - timedelta(days=70))
            
            # Agrupar acciones por día
            df_period = df_actions[df_actions["change_date"] >= period_start].copy()
            
            if df_period.empty:
                # Si no hay datos en el período, usar todos los datos disponibles
                df_period = df_actions.copy()
            
            # Contar acciones por día como proxy de actividad de mantenimiento
            daily_counts = df_period.groupby("change_date").size().reset_index(name="action_count")
            
            # Estimar horas de downtime: 
            # - Cada acción representa ~1.5 horas de trabajo en promedio
            # - Esto es un estimado basado en la actividad registrada
            daily_counts["downtime_hours"] = daily_counts["action_count"] * 1.5
            
            # Renombrar columna y asegurar que sea date
            daily_counts = daily_counts.rename(columns={"change_date": "date"})
            
            # Convertir timestamp a date si es necesario
            if pd.api.types.is_datetime64_any_dtype(daily_counts["date"]):
                daily_counts["date"] = pd.to_datetime(daily_counts["date"]).dt.date
            
            return daily_counts[["date", "downtime_hours"]].sort_values("date")
        
        else:
            # TODO: Implement SQL query for production
            raise NotImplementedError("Production mode not yet implemented")


# Global instance
_repository = None


def get_repository(mode="dummy") -> MaintenanceRepository:
    """Get or create repository instance."""
    global _repository
    if _repository is None or _repository.mode != mode:
        _repository = MaintenanceRepository(mode)
    return _repository
