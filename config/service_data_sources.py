"""Which backend data sources each dashboard tab depends on.

Keys are service ids (`dashboard/services_registry.py`); a trailing ``*`` matches a family
(`predictive-*` covers every predictive component). Values are source ids from the catalog
(`src/data/catalog.py::build_client_availability`). A tab with no entry shows no
"Fuentes de datos" indicator at all.

Adding a source to a tab is one line here plus its label in the i18n catalogs
(`source_status.source_<id>`); the shared component is not touched.

Tabs still pending confirmation of their backend dependencies are deliberately absent:
monitoring-mantenciones, agents-campbell-ai, agents-troubleshooting,
integration-validacion-avisos, integration-seguimiento-avisos, reporting-main. The admin
tabs are configuration, not data pipelines, and stay out for good.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Optional

SERVICE_DATA_SOURCES: dict[str, tuple[str, ...]] = {
    "monitoring-alerts": ("alerts_consolidated", "telemetry_alert_detail", "oil_classified"),
    "monitoring-telemetry": ("telemetry_unit_health", "telemetry_system_health", "telemetry_manifest"),
    "monitoring-oil": ("oil_classified", "oil_machine_status", "oil_limits_four"),
    "predictive-*": ("predictive_components", "predictive_ai"),
}



@dataclass(frozen=True)
class DateField:
    """Where to read the date of a source's data: `column` in the source's file, or in every
    file matching `glob` when the source is a folder. The freshness shown on a chip is
    measured from the most recent value of this column that is not in the future."""

    column: str
    glob: Optional[str] = None


# Source id -> the date field of its data. Shared by every tab that lists the source.
# A source without an entry (e.g. a predictive client with only partitioned parquet, whose
# files carry no date column) shows no freshness.
SOURCE_DATE_FIELDS: dict[str, DateField] = {
    "alerts_consolidated": DateField("Timestamp"),
    "telemetry_alert_detail": DateField("Alert_TimeStart"),
    "oil_classified": DateField("sampleDate"),
    "oil_machine_status": DateField("latest_sample_date"),
    "oil_limits_four": DateField("calculation_date"),
    "data_freshness": DateField("Ultima Fecha de Actualizacion"),
    "predictive_ai": DateField("Fecha"),
    "predictive_components": DateField("Fecha", glob="*.csv"),
    "telemetry_unit_health": DateField("evaluation_timestamp", glob="**/*.parquet"),
    "telemetry_system_health": DateField("evaluation_timestamp", glob="**/*.parquet"),
    "telemetry_manifest": DateField("execution_timestamp"),
    "maintenance_contract": DateField("reference_date", glob="query_10_equipment_status.parquet"),
}


# Resumen > General lists techniques rather than files; each takes its last-modified time
# from the catalog source that backs it.
TECHNIQUE_SOURCE: dict[str, str] = {
    "alerts": "alerts_consolidated",
    "telemetry": "telemetry_unit_health",
    "oil": "oil_classified",
    "predictive": "predictive_components",
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
