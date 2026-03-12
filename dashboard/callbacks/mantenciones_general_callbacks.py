"""
Callbacks for Mantenciones General tab.
Handles data loading, KPI updates, and visualizations.
"""

from dash import callback, Output, Input, State, html
from dash.exceptions import PreventUpdate
import json
from datetime import datetime
import logging

from src.data.maintenance_repository import get_repository
from dashboard.tabs.tab_mantenciones_general import (
    create_status_donut_chart,
    create_downtime_trend_chart,
    create_detentions_table,
    create_jobs_table,
    create_empty_figure
)

logger = logging.getLogger(__name__)


def register_mantenciones_general_callbacks(app):
    """
    Register all callbacks for Mantenciones General tab.
    
    Args:
        app: Dash application instance
    """
    
    @callback(
        [
            Output("store-general-data", "data"),
            Output("store-general-timestamp", "data"),
            Output("store-general-loaded", "data"),
        ],
        [
            Input("btn-refresh-general", "n_clicks"),
            Input("store-general-loaded", "data"),
        ],
        prevent_initial_call=False
    )
    def load_general_data(n_clicks, loaded):
        """
        Load all data for the general view.
        Triggered by refresh button or initial page load.
        """
        try:
            logger.info(f"Loading mantenciones general data... (n_clicks={n_clicks}, loaded={loaded})")
            
            # Get repository (using parquet mode for real data)
            repo = get_repository(mode="parquet")
            
            # Load all datasets
            df_status = repo.get_status_counts()
            df_downtime_mtd = repo.get_downtime_mtd()
            df_last_detentions = repo.get_last_detentions(n_per_machine=3)
            df_jobs_last_week = repo.get_jobs_last_week()
            df_downtime_by_day = repo.get_downtime_by_day_mtd()
            
            # Convert to JSON-serializable format
            data = {
                "status": df_status.to_dict("records"),
                "downtime_mtd": df_downtime_mtd.to_dict("records"),
                "last_detentions": df_last_detentions.to_dict("records"),
                "jobs_last_week": df_jobs_last_week.to_dict("records"),
                "downtime_by_day": df_downtime_by_day.to_dict("records"),
            }
            
            timestamp = datetime.now().isoformat()
            
            logger.info("Data loaded successfully")
            return data, timestamp, True
            
        except Exception as e:
            logger.error(f"Error loading mantenciones general data: {e}", exc_info=True)
            return {}, None, False
    
    @callback(
        [
            Output("kpi-equipos-totales", "children"),
            Output("kpi-equipos-sanos", "children"),
            Output("kpi-equipos-detenidos", "children"),
            Output("kpi-horas-detenidas-mtd", "children"),
        ],
        [Input("store-general-data", "data")]
    )
    def update_kpis(data):
        """Update KPI cards with loaded data."""
        if not data or not data.get("status"):
            return "0", "0", "0", "0"
        
        try:
            # Parse status counts
            status_data = data["status"]
            sanos = next((item["n_machines"] for item in status_data if item["machine_status"] == "SANO"), 0)
            detenidos = next((item["n_machines"] for item in status_data if item["machine_status"] == "DETENIDO"), 0)
            total = sanos + detenidos
            
            # Parse downtime MTD
            downtime_mtd = data.get("downtime_mtd", [{}])[0].get("total_downtime_hours_mtd", 0)
            downtime_str = f"{downtime_mtd:.1f}"
            
            return str(total), str(sanos), str(detenidos), downtime_str
            
        except Exception as e:
            logger.error(f"Error updating KPIs: {e}")
            return "Error", "Error", "Error", "Error"
    
    @callback(
        Output("chart-status-distribution", "figure"),
        [Input("store-general-data", "data")]
    )
    def update_status_chart(data):
        """Update status distribution donut chart."""
        if not data or not data.get("status"):
            return create_empty_figure("No hay datos de estado disponibles")
        
        try:
            import pandas as pd
            df_status = pd.DataFrame(data["status"])
            return create_status_donut_chart(df_status)
        except Exception as e:
            logger.error(f"Error updating status chart: {e}")
            return create_empty_figure("Error al cargar gráfico")
    
    @callback(
        Output("chart-downtime-trend", "figure"),
        [Input("store-general-data", "data")]
    )
    def update_downtime_trend(data):
        """Update downtime trend line chart."""
        if not data or not data.get("downtime_by_day"):
            return create_empty_figure("No hay datos de tendencia disponibles")
        
        try:
            import pandas as pd
            df_trend = pd.DataFrame(data["downtime_by_day"])
            return create_downtime_trend_chart(df_trend)
        except Exception as e:
            logger.error(f"Error updating downtime trend: {e}")
            return create_empty_figure("Error al cargar gráfico")
    
    @callback(
        Output("table-last-detentions", "children"),
        [Input("store-general-data", "data")]
    )
    def update_detentions_table(data):
        """Update last detentions table."""
        if not data or not data.get("last_detentions"):
            return html.P("No hay datos de detenciones disponibles", 
                         className="text-muted text-center p-3")
        
        try:
            import pandas as pd
            df_detentions = pd.DataFrame(data["last_detentions"])
            return create_detentions_table(df_detentions)
        except Exception as e:
            logger.error(f"Error updating detentions table: {e}")
            return html.P("Error al cargar tabla", className="text-danger text-center p-3")
    
    @callback(
        Output("table-jobs-last-week", "children"),
        [Input("store-general-data", "data")]
    )
    def update_jobs_table(data):
        """Update jobs last week table."""
        if not data or not data.get("jobs_last_week"):
            return html.P("No hay trabajos registrados en la última semana", 
                         className="text-muted text-center p-3")
        
        try:
            import pandas as pd
            df_jobs = pd.DataFrame(data["jobs_last_week"])
            return create_jobs_table(df_jobs)
        except Exception as e:
            logger.error(f"Error updating jobs table: {e}")
            return html.P("Error al cargar tabla", className="text-danger text-center p-3")
    
    @callback(
        Output("text-last-update", "children"),
        [Input("store-general-timestamp", "data")]
    )
    def update_timestamp(timestamp):
        """Update last update timestamp."""
        if not timestamp:
            return "N/A"
        
        try:
            dt = datetime.fromisoformat(timestamp)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.error(f"Error formatting timestamp: {e}")
            return "Error"
