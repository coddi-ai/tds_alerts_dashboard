"""Resolve each tab's data-source statuses and hand them to the shared indicator.

The drawing lives in `dashboard/components/data_sources.py`; which sources a tab has lives
in `config/service_data_sources.py`. This module only turns what the backend knows (catalog
probes, the Fleet Overview's per-technique readings) into `DataSource` rows.
"""

from __future__ import annotations

from typing import Optional

from dash import html

from config.service_data_sources import SOURCE_DATE_FIELDS, TECHNIQUE_SOURCE, data_sources_for_service
from dashboard.components.data_sources import (
    AVAILABLE,
    PARTIAL,
    UNAVAILABLE,
    DataSource,
    render_data_sources,
)
from src.data.catalog import SourceProbe, build_client_availability
from src.data.source_freshness import days_since, latest_data_date
from src.i18n import t, t_or

# Spanish display labels for the raw probe/source ids - these used to leak into the UI as
# English title-cased ids (06_fleet_overview_revision_2.md, Required Changes #1). Falls
# back to that same title-casing for any source id not listed here.
SOURCE_LABELS_ES: dict[str, str] = {
    "oil_classified": "Clasificación de Aceite",
    "oil_machine_status": "Estado de Máquina (Aceite)",
    "oil_limits_four": "Límites de Aceite",
    "alerts_consolidated": "Alertas Consolidadas",
    "telemetry_alert_detail": "Detalle de Alertas (Telemetría)",
    "telemetry_unit_health": "Salud de Unidad (Telemetría)",
    "telemetry_system_health": "Salud de Sistema (Telemetría)",
    "telemetry_manifest": "Manifiesto de Telemetría",
    "data_freshness": "Frescura de Datos",
    "maintenance_contract": "Contrato de Mantención",
    "predictive_components": "Componentes Predictivos",
    "predictive_ai": "IA Predictiva",
}

# Catalog probe status -> shared component status. A source the catalog has no probe for
# is unavailable, not omitted.
_PROBE_STATUS = {"available": AVAILABLE, "partial": PARTIAL, "missing": UNAVAILABLE}


def source_days_since_update(source: str, probe: Optional[SourceProbe]) -> Optional[int]:
    """Days between today and the most recent date in the source's data, or ``None`` when
    the source has no configured date field or it cannot be read (no freshness text)."""
    field = SOURCE_DATE_FIELDS.get(source)
    if field is None or probe is None or probe.status == "missing":
        return None
    days = days_since(latest_data_date(probe.path, field))
    return None if days is None else max(days, 0)


def _source_label(source: str) -> str:
    return t_or(f"source_status.source_{source}", SOURCE_LABELS_ES.get(source, source.replace("_", " ").title()))


def data_source_from_probe(source: str, probe: Optional[SourceProbe]) -> DataSource:
    if probe is None:
        return DataSource(source, _source_label(source), UNAVAILABLE, detail=t("source_status.no_compatible_source"))
    return DataSource(
        source,
        _source_label(source),
        _PROBE_STATUS.get(probe.status, UNAVAILABLE),
        detail=probe.note or probe.path or t("source_status.no_compatible_source"),
        days_since_update=source_days_since_update(source, probe),
    )


def service_data_sources(client: str, service_id: str) -> list[DataSource]:
    """The configured sources of a tab, each with its current status for `client`."""
    names = data_sources_for_service(service_id)
    if not names:
        return []
    availability = build_client_availability(client)
    return [data_source_from_probe(name, availability.get(name)) for name in names]


def render_service_data_sources(client: str, service_id: str) -> Optional[html.Div]:
    """The "Fuentes de datos" indicator for a tab, or ``None`` when it has no sources."""
    return render_data_sources(service_data_sources(client, service_id))


def fleet_overview_data_sources(client: str) -> list[DataSource]:
    """Resumen > General: one source per technique, from the same per-unit reading the
    Fleet Overview cards use.

    A file merely existing on disk does not mean the cards have data: the banner cannot
    read "Disponible" while every unit's row for that technique reads "Sin Datos"
    (06_fleet_overview_revision_2.md, Required Changes #5). Deferred import:
    fleet_overview.py does not import this module, this just avoids an eager dependency.
    """
    from dashboard.components.fleet_overview import technique_availability, technique_label

    availability = build_client_availability(client)

    def freshness(technique: str) -> Optional[int]:
        source = TECHNIQUE_SOURCE.get(technique, "")
        return source_days_since_update(source, availability.get(source))

    return [
        DataSource(
            technique,
            technique_label(technique),
            AVAILABLE if available else UNAVAILABLE,
            detail=t("source_status.technique_has_reading" if available else "source_status.technique_no_reading"),
            days_since_update=freshness(technique),
        )
        for technique, available in technique_availability(client).items()
    ]


def render_fleet_overview_data_sources(client: str) -> Optional[html.Div]:
    return render_data_sources(fleet_overview_data_sources(client))
