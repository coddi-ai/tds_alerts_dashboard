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
}

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
})

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
