"""Resolve each tab's data-source statuses and hand them to the shared "Fuentes de Datos" popover.

The drawing lives in `dashboard/components/data_sources.py`; which sources a tab has lives
in `config/service_data_sources.py` (the audit that fixes those lists is
documentation/general/data_sources_documentation_dashboard.md). This module only turns what the
backend knows (catalog probes, the predictive v2 partitions, the Fleet Overview's per-technique
readings) into `DataSource` rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from dash import html

from config.service_data_sources import (
    PREDICTIVE_DATE_FIELD,
    SOURCE_DATE_FIELDS,
    TECHNIQUE_SOURCE,
    data_sources_for_service,
    source_applies_to_client,
)
from dashboard.components.data_sources import (
    AVAILABLE,
    PARTIAL,
    UNAVAILABLE,
    DataSource,
    render_data_sources,
)
from src.data import predictive_v2
from src.data.catalog import SourceProbe, build_client_availability
from src.data.source_freshness import days_since, latest_data_date, newest_week_partition
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
    "maintenance_weekly": "Mantenciones Semanales",
    "telemetry_ai_comments": "Comentarios de IA (Telemetría)",
    "telemetry_deviation": "Desviación de Señales",
    "telemetry_trends": "Tendencias de Señales",
    "telemetry_events": "Eventos de Señales",
    "telemetry_limits": "Límites de Telemetría",
    "telemetry_silver_weekly": "Telemetría Semanal",
    "oil_component_hours": "Horas de Componente (Aceite)",
    "predictive_risk_scores": "Puntaje de Riesgo",
    "predictive_unit_status": "Estado de Unidades",
    "predictive_curve": "Curva de Riesgo Acumulado",
    "predictive_unit_analysis": "Análisis Inteligente",
    "predictive_signal_status": "Estado de Señales de Telemetría",
    "predictive_oil_meter": "Historial de Desgaste Acumulado",
}

# Predictivo's v2 tables (`predictive_v2` is the one place that knows their paths): source id ->
# the table's base folder for (client, component).
_PREDICTIVE_TABLES = {
    "predictive_risk_scores": predictive_v2.risk_scores_base_path,
    "predictive_unit_status": predictive_v2.unit_status_summary_base_path,
    "predictive_curve": predictive_v2.cumulative_risk_curve_base_path,
    "predictive_unit_analysis": predictive_v2.unit_failure_analisis_base_path,
    "predictive_signal_status": predictive_v2.signal_daily_status_base_path,
    "predictive_oil_meter": predictive_v2.oil_meter_history_base_path,
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


def _partition_days(partition: Path) -> Optional[int]:
    """Days since the newest `Fecha` in one week partition (never negative), or ``None``."""
    days = days_since(latest_data_date(str(partition), PREDICTIVE_DATE_FIELD))
    return None if days is None else max(days, 0)


def predictive_table_source(client: str, component: str, source: str) -> Optional[DataSource]:
    """One predictive v2 table of a component as a source row. Available when the table has a
    published week partition; its date is the newest `Fecha` of that partition (for
    `unit_status_summary` that is the model run date the page shows). ``None`` for an optional
    table (`predictive_oil_meter`) the component does not publish at all."""
    base = _PREDICTIVE_TABLES[source](client, component)
    newest = newest_week_partition(base)
    if newest is None:
        if source == "predictive_oil_meter" and not base.is_dir():
            return None
        return DataSource(source, _source_label(source), UNAVAILABLE, detail=t("source_status.no_compatible_source"))
    return DataSource(source, _source_label(source), AVAILABLE, days_since_update=_partition_days(newest))


def predictive_data_sources(client: str, component: str) -> list[DataSource]:
    """Predictivo > <component>: the v2 tables the Resumen and Evidencia tabs read, plus the oil
    files Evidencia reads (same catalog probes as Aceite)."""
    availability = build_client_availability(client)
    rows = []
    for name in data_sources_for_service(f"predictive-{component}"):
        if name in _PREDICTIVE_TABLES:
            row = predictive_table_source(client, component, name)
        else:
            row = data_source_from_probe(name, availability.get(name))
        if row is not None:
            rows.append(row)
    return rows


def predictive_run_days(client: str) -> Optional[int]:
    """Days since the model run of Resumen > General's Predictivo row: the oldest run date across
    the client's enabled components, the same date that row's freshness label is measured from."""
    from dashboard.components.fleet_overview import enabled_predictive_components

    days = []
    for component in enabled_predictive_components(client):
        newest = newest_week_partition(predictive_v2.unit_status_summary_base_path(client, component))
        value = None if newest is None else _partition_days(newest)
        if value is not None:
            days.append(value)
    return max(days) if days else None


def service_data_sources(client: str, service_id: str) -> list[DataSource]:
    """The configured sources of a tab, each with its current status for `client`."""
    names = data_sources_for_service(service_id)
    if not names:
        return []
    if service_id.startswith("predictive-"):
        return predictive_data_sources(client, service_id.split("predictive-", 1)[1])
    availability = build_client_availability(client)
    return [
        data_source_from_probe(name, availability.get(name))
        for name in names
        if source_applies_to_client(name, client)
    ]


def render_service_data_sources(client: str, service_id: str) -> Optional[html.Div]:
    """The "Fuentes de Datos" popover for a tab, or ``None`` when it has no sources."""
    return render_data_sources(service_data_sources(client, service_id), scope=service_id)


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
        if technique == "predictive":
            return predictive_run_days(client)
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
    return render_data_sources(fleet_overview_data_sources(client), scope="overview-general")
