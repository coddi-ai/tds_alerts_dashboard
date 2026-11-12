"""Which backend data sources each dashboard tab depends on.

Keys are service ids (`dashboard/services_registry.py`); a trailing ``*`` matches a family
(`predictive-*` covers every predictive component). Values are source ids from the catalog
(`src/data/catalog.py::build_client_availability`). A tab with no entry shows no
"Fuentes de Datos" popover at all.

Adding a source to a tab is one line here plus its label in the i18n catalogs
(`source_status.source_<id>`); the shared component is not touched.

The lists below are the result of the audit in
documentation/general/data_sources_documentation_dashboard.md: each entry is a source the
tab's code actually reads, and each missing one is a discrepancy to be fixed there first.

Every page that has data sources has an entry (the seven pages added later are listed at the
end of SERVICE_DATA_SOURCES). Pages with no data to show -- the Administración placeholder -- stay
out. `total` in the popover is the length of the list that applies to the current client and
component: sources that do not apply are neither listed nor counted (CLIENT_GATED_SOURCES, the
per-component predictive list).
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Optional

SERVICE_DATA_SOURCES: dict[str, tuple[str, ...]] = {
    "monitoring-alerts": (
        "alerts_consolidated", "telemetry_alert_detail", "oil_classified", "oil_limits_four", "maintenance_weekly",
    ),
    "monitoring-telemetry": (
        "telemetry_unit_health", "telemetry_system_health", "telemetry_manifest", "telemetry_ai_comments",
        "telemetry_deviation", "telemetry_trends", "telemetry_events", "telemetry_limits", "telemetry_silver_weekly",
    ),
    "monitoring-oil": ("oil_classified", "oil_machine_status", "oil_limits_four", "oil_component_hours"),
    # Predictivo reads the v2 long-format tables, not the legacy `<component>.csv` /
    # `analisis_inteligente.parquet`. The `predictive_*` ids below are those tables (resolved from
    # their partitions in dashboard/components/source_status.py), not catalog probes.
    "predictive-*": (
        "predictive_risk_scores", "predictive_unit_status", "predictive_curve", "predictive_unit_analysis",
        "predictive_signal_status", "oil_classified", "oil_limits_four", "predictive_oil_meter",
    ),
    # --- Pages added to the popover in the amendment (documented in section 6 onwards of
    # data_sources_documentation_dashboard.md) ---
    "monitoring-mantenciones": (
        "maintenance_query_1", "maintenance_query_2", "maintenance_query_3", "maintenance_query_4",
        "maintenance_query_5", "maintenance_query_6", "maintenance_query_7", "maintenance_query_8",
        "maintenance_query_9", "maintenance_query_10", "maintenance_weekly", "oil_classified",
    ),
    "agents-campbell-ai": (
        "alerts_consolidated", "telemetry_alert_detail", "oil_classified", "oil_machine_status",
        "oil_limits", "oil_limits_four", "telemetry_machine_status", "telemetry_classified",
        "maintenance_query_3", "maintenance_summary", "predictive_legacy_motor",
        "predictive_legacy_transmision", "campbell_manifest",
    ),
    "agents-troubleshooting": ("troubleshooting_agent",),
    "reporting-main": ("reporting_store", "reporting_analysis_history", "reporting_curve_history"),
    "reporting-informe-falla": (
        "predictive_unit_status", "predictive_risk_scores", "predictive_curve", "predictive_unit_analysis",
        "oil_classified", "maintenance_query_3", "maintenance_query_7",
    ),
    "integration-validacion-avisos": ("erp_warnings", "erp_sap_config"),
    "integration-seguimiento-avisos": ("erp_warnings",),
    "admin-user-registry": ("auth_events_store",),
    "admin-mailing": ("alerts_consolidated",),
}

# Sources that are not a catalog probe: their status comes from configuration (an agent URL, a
# bucket, a client YAML) or from several predictive components at once. Resolved in
# dashboard/components/source_status.py.
RESOLVED_SOURCES = frozenset({
    "troubleshooting_agent", "reporting_store", "reporting_analysis_history", "reporting_curve_history",
    "erp_sap_config", "auth_events_store",
})

# Pages whose predictive v2 tables belong to one fixed component rather than the page's own.
# The preliminary failure report analyses engines only (src/informe_falla/catalog.py::COMPONENTE).
PAGE_PREDICTIVE_COMPONENT = {"reporting-informe-falla": "motor"}

# Sources a tab lists only for some clients (the tab never reads them for the others).
# `oil_component_hours`: the Horas Componente column of the oil machine detail
# (`Settings.component_hours_allowed_clients`).
CLIENT_GATED_SOURCES = {"oil_component_hours"}


def source_applies_to_client(source: str, client: Optional[str]) -> bool:
    """Whether the tab reads `source` for `client` (always true for ungated sources)."""
    if source not in CLIENT_GATED_SOURCES or not client:
        return True
    from config.settings import get_settings

    return str(client).upper() in {c.upper() for c in get_settings().component_hours_allowed_clients}



@dataclass(frozen=True)
class DateField:
    """Where to read the date of a source's data: `column` in the source's file, or in every
    file matching `glob` when the source is a folder. The freshness shown on a chip is
    measured from the most recent value of this column that is not in the future."""

    column: str
    glob: Optional[str] = None


# Source id -> the date field of its data. Shared by every tab that lists the source.
# A source without an entry shows no freshness ("—" in the popover): see NO_DATE_SOURCES. The
# `predictive_*` tables are partitioned by week and are dated from their newest partition's
# `Fecha` (`PREDICTIVE_DATE_FIELD`), not from this mapping.
SOURCE_DATE_FIELDS: dict[str, DateField] = {
    "alerts_consolidated": DateField("Timestamp"),
    "telemetry_alert_detail": DateField("Alert_TimeStart"),
    "oil_classified": DateField("sampleDate"),
    "oil_machine_status": DateField("latest_sample_date"),
    "oil_limits_four": DateField("calculation_date"),
    "oil_component_hours": DateField("sampleDate"),
    "maintenance_query_10": DateField("reference_date"),
    "predictive_legacy_motor": DateField("Fecha"),
    "predictive_legacy_transmision": DateField("Fecha"),
    "data_freshness": DateField("Ultima Fecha de Actualizacion"),
    "telemetry_unit_health": DateField("evaluation_timestamp", glob="**/*.parquet"),
    "telemetry_system_health": DateField("evaluation_timestamp", glob="**/*.parquet"),
    "telemetry_manifest": DateField("execution_timestamp"),
    "maintenance_contract": DateField("reference_date", glob="query_10_equipment_status.parquet"),
}


# Listed sources with no single date column to read; their "Última actualización" is "—".
NO_DATE_SOURCES = frozenset({
    "maintenance_weekly", "telemetry_ai_comments", "telemetry_deviation", "telemetry_trends",
    "telemetry_events", "telemetry_limits", "telemetry_silver_weekly",
    "maintenance_query_1", "maintenance_query_2", "maintenance_query_3", "maintenance_query_4",
    "maintenance_query_5", "maintenance_query_6", "maintenance_query_7", "maintenance_query_8",
    "maintenance_query_9", "maintenance_summary", "oil_limits", "telemetry_machine_status",
    "telemetry_classified", "campbell_manifest", "erp_warnings",
}) | RESOLVED_SOURCES

# The date column of every partitioned `predictive_*` table (read from the newest partition).
PREDICTIVE_DATE_FIELD = DateField("Fecha", glob="*.parquet")

# Resumen > General lists techniques rather than files; each takes its freshness from the data
# of the catalog source that backs it. Predictivo is not here: its date is the model run date
# of the v2 `unit_status_summary` (dashboard/components/source_status.py::predictive_run_days).
TECHNIQUE_SOURCE: dict[str, str] = {
    "alerts": "alerts_consolidated",
    "telemetry": "telemetry_unit_health",
    "oil": "oil_classified",
    "maintenance": "maintenance_contract",
}


def data_sources_for_service(service_id: str) -> tuple[str, ...]:
    """Source ids configured for a service id; empty when the tab has none."""
    if service_id in SERVICE_DATA_SOURCES:
        return SERVICE_DATA_SOURCES[service_id]
    for pattern, sources in SERVICE_DATA_SOURCES.items():
        if "*" in pattern and fnmatchcase(service_id, pattern):
            return sources
    return ()
