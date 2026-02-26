"""
Repository layer for Mantenciones General dashboard.
Provides data access functions that can work in dummy or production mode.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import logging

from src.data.dummy_generator import generate_dummy_tables

logger = logging.getLogger(__name__)


class MaintenanceRepository:
    """Repository for maintenance data access."""
    
    def __init__(self, mode="dummy"):
        """
        Initialize repository.
        
        Args:
            mode: "dummy" for in-memory data, "prod" for database queries
        """
        self.mode = mode
        self._dummy_cache = None
        
    def _get_dummy_data(self):
        """Get or generate dummy data."""
        if self._dummy_cache is None:
            logger.info("Generating dummy maintenance data...")
            self._dummy_cache = generate_dummy_tables()
        return self._dummy_cache
    
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
