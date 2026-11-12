"""Resolve each tab's data-source statuses and hand them to the shared "Fuentes de Datos" popover.

The drawing lives in `dashboard/components/data_sources.py`; which sources a tab has lives
in `config/service_data_sources.py` (the audit that fixes those lists is
documentation/general/data_sources_documentation_dashboard.md). This module only turns what the
backend knows (catalog probes, the predictive v2 partitions, the Fleet Overview's per-technique
readings) into `DataSource` rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from dash import html

from config.service_data_sources import (
    PAGE_PREDICTIVE_COMPONENT,
    PREDICTIVE_DATE_FIELD,
    RESOLVED_SOURCES,
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
    "maintenance_query_1": "Mantención por Componente",
    "maintenance_query_2": "Registros de Unidad y Acciones",
    "maintenance_query_3": "Acciones de Mantención",
    "maintenance_query_4": "KPIs de Negocio",
    "maintenance_query_5": "Confiabilidad Mensual",
    "maintenance_query_6": "Ranking de Fallas por Componente",
    "maintenance_query_7": "Horas de Intervención (Diarias)",
    "maintenance_query_8": "Horas de Intervención (Mensuales)",
    "maintenance_query_9": "Intervención de Flota (Diaria)",
    "maintenance_query_10": "Estado de Equipos",
    "maintenance_summary": "Resumen Semanal de Mantención",
    "oil_limits": "Límites de Aceite (Formato Legado)",
    "telemetry_machine_status": "Estado de Equipos (Telemetría)",
    "telemetry_classified": "Componentes Clasificados (Telemetría)",
    "predictive_legacy_motor": "Modelo Predictivo de Motor (Legado)",
    "predictive_legacy_transmision": "Modelo Predictivo de Transmisión (Legado)",
    "campbell_manifest": "Manifiesto de Datos",
    "troubleshooting_agent": "Agente de Troubleshooting",
    "reporting_store": "Reportes en S3",
    "reporting_analysis_history": "Historial de Análisis Predictivo",
    "reporting_curve_history": "Historial de Curva de Riesgo Acumulado",
    "erp_warnings": "Avisos del ERP",
    "erp_sap_config": "Configuración SAP del Cliente",
    "auth_events_store": "Eventos de Acceso",
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


def _aggregate_predictive_table(client: str, components: Sequence[str], source: str, key: str) -> DataSource:
    """One predictive table across several components (Reportabilidad reads the history of all
    of them): Disponible when every component has it, Parcial when only some do, No Disponible
    when none. The date is the oldest newest-run across the components that have it."""
    rows = [predictive_table_source(client, component, source) for component in components]
    rows = [row for row in rows if row is not None]
    present = [row for row in rows if row.status == AVAILABLE]
    if not present:
        status = UNAVAILABLE
    else:
        status = AVAILABLE if len(present) == len(rows) else PARTIAL
    dates = [row.days_since_update for row in present if row.days_since_update is not None]
    return DataSource(key, _source_label(key), status, days_since_update=max(dates) if dates else None)


def _resolved_source(client: str, source: str) -> DataSource:
    """A source whose status comes from configuration rather than from a data file. A failure to
    resolve it is "No Disponible", never an error on the page."""
    label = _source_label(source)
    try:
        if source == "troubleshooting_agent":
            from config.client_services import is_service_dummy, is_service_enabled, normalize_client_id
            from dashboard.troubleshooting_handoff import SERVICE_ID, troubleshooting_agent_configured

            normalized = normalize_client_id(client)
            ok = (
                troubleshooting_agent_configured() and bool(normalized)
                and is_service_enabled(normalized, SERVICE_ID) and not is_service_dummy(normalized, SERVICE_ID)
            )
        elif source == "reporting_store":
            from dashboard.report_files import reporting_available
            from src.data.report_store import get_report_store

            ok = reporting_available(client) and get_report_store() is not None
        elif source in ("reporting_analysis_history", "reporting_curve_history"):
            from src.data.report_store import TECHNIQUE_PREDICTIVE, TECHNIQUE_SYSTEMS

            table = "predictive_unit_analysis" if source == "reporting_analysis_history" else "predictive_curve"
            return _aggregate_predictive_table(client, TECHNIQUE_SYSTEMS[TECHNIQUE_PREDICTIVE], table, source)
        elif source == "erp_sap_config":
            from src.data.erp_client_config import CLIENTS_DIR

            ok = (CLIENTS_DIR / f"{str(client).lower()}.yaml").is_file()
        elif source == "auth_events_store":
            from src.auth_events.storage import get_storage

            ok = get_storage() is not None
        else:
            ok = False
    except Exception:
        ok = False
    return DataSource(
        source, label, AVAILABLE if ok else UNAVAILABLE,
        detail=None if ok else t("source_status.no_compatible_source"),
    )


def _informe_table_source(client: str, component: str, source: str) -> Optional[DataSource]:
    """A predictive table as the preliminary failure report reads it: from the local copy, or from
    S3 when `INFORME_FALLA_ORIGEN=s3` (then only the configured bucket can be checked)."""
    from src.informe_falla.config import get_informe_settings

    settings = get_informe_settings()
    if settings.origen == "s3":
        status = AVAILABLE if settings.s3_bucket else UNAVAILABLE
        return DataSource(source, _source_label(source), status, detail="S3")
    return predictive_table_source(client, component, source)


def service_data_sources(client: str, service_id: str) -> list[DataSource]:
    """The configured sources of a tab, each with its current status for `client`. Only the sources
    that apply to this client and component are listed (and so counted)."""
    names = data_sources_for_service(service_id)
    if not names:
        return []
    if service_id.startswith("predictive-"):
        return predictive_data_sources(client, service_id.split("predictive-", 1)[1])
    availability = build_client_availability(client)
    component = PAGE_PREDICTIVE_COMPONENT.get(service_id)
    rows = []
    for name in names:
        if not source_applies_to_client(name, client):
            continue
        if name in RESOLVED_SOURCES:
            row = _resolved_source(client, name)
        elif component and name in _PREDICTIVE_TABLES:
            row = _informe_table_source(client, component, name)
        else:
            row = data_source_from_probe(name, availability.get(name))
        if row is not None:
            rows.append(row)
    return rows


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
