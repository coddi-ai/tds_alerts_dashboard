"""Client-facing source availability and provenance components."""

from __future__ import annotations

from src.i18n import t, t_or
from dash import html

from src.data.catalog import SourceProbe, build_client_availability


SERVICE_SOURCES = {
    # The Fleet Overview page no longer uses this raw file-existence probe
    # for its own "Fuentes de datos" banner - see render_fleet_overview_source_status
    # below, which reads dashboard.components.fleet_overview.technique_availability
    # instead, because a file merely existing on disk was proven to disagree
    # with what the unit cards actually show (06_fleet_overview_revision_2.md,
    # Required Changes #5: the banner can't read "Disponible" while every
    # unit's row for that source reads "Sin Datos"). This dict/mechanism is
    # kept for the other pages below, which still want a lighter-weight
    # existence probe rather than the full per-unit aggregation.
    "monitoring-alerts": ("alerts_consolidated", "telemetry_alert_detail", "oil_classified"),
    "monitoring-telemetry": ("telemetry_unit_health", "telemetry_system_health", "telemetry_manifest"),
    "monitoring-oil": ("oil_classified", "oil_machine_status", "oil_limits_four"),
    "predictive": ("predictive_components", "predictive_ai"),
}

# Spanish display labels for the raw probe/source ids above - these used to
# leak into the UI as English title-cased ids (e.g. "Oil Machine Status",
# "Alerts Consolidated") via a plain `.replace("_", " ").title()`
# (06_fleet_overview_revision_2.md, Required Changes #1). Falls back to that
# same title-casing for any source id not listed here.
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

# Colors per aggregate status; the label is looked up per render (see `_status_view`).
_STATUS_STYLE = {
    "available": ("#198754", "var(--green-light)"),
    "partial": ("#946200", "var(--amber-light)"),
    "missing": ("#6c757d", "var(--surface-2)"),
}


def _status_view(status: str) -> tuple[str, str, str]:
    """(label, color, background) for a source status, label in the current language."""
    status = status if status in _STATUS_STYLE else "missing"
    color, background = _STATUS_STYLE[status]
    return t(f"source_status.status_{status}"), color, background


def service_source_status(client: str, service_id: str) -> tuple[str, dict[str, SourceProbe]]:
    """Return the aggregate status and the probes relevant to a service."""

    availability = build_client_availability(client)
    names = SERVICE_SOURCES.get(service_id, ())
    selected = {name: availability[name] for name in names if name in availability}
    if not selected:
        return "missing", selected
    statuses = {probe.status for probe in selected.values()}
    if statuses == {"available"}:
        return "available", selected
    if "available" in statuses or "partial" in statuses:
        return "partial", selected
    return "missing", selected


def render_service_source_status(client: str, service_id: str, *, compact: bool = False):
    """Render a small, non-blocking provenance banner for a dashboard page."""

    aggregate, probes = service_source_status(client, service_id)
    label, color, background = _status_view(aggregate)
    children = [
        html.Strong(t("source_status.data_sources", label=label)),
        html.Span(" · " if compact else "  "),
    ]
    for source, probe in probes.items():
        source_label = t_or(f"source_status.source_{source}", SOURCE_LABELS_ES.get(source, source.replace("_", " ").title()))
        status_label, status_color, status_bg = _status_view(probe.status)
        children.append(
            html.Span(
                f"{source_label}: {status_label}",
                title=probe.note or probe.path or t("source_status.no_compatible_source"),
                style={
                    "display": "inline-block",
                    "marginRight": "8px",
                    "padding": "2px 7px",
                    "borderRadius": "4px",
                    "backgroundColor": status_bg,
                    "color": status_color,
                    "fontSize": "11px",
                },
            )
        )
    return html.Div(
        children,
        className="mb-3",
        style={
            "padding": "8px 12px",
            "borderLeft": f"4px solid {color}",
            "backgroundColor": background,
            "fontSize": "12px",
        },
    )


def render_fleet_overview_source_status(client: str):
    """The Fleet Overview page's own "Fuentes de datos" banner.

    Unlike `render_service_source_status` above (a raw file-existence
    probe), this reads `dashboard.components.fleet_overview.technique_availability`
    - the exact same per-unit technique-status computation backing every
    card row. That's what makes it impossible for this banner to claim
    "Disponible" for a technique whose rows the user is looking at right
    below it all read "Sin Datos" (06_fleet_overview_revision_2.md, Required
    Changes #5); a file merely existing on disk doesn't guarantee that, but
    an actual resolved per-unit reading does.

    Deferred import: fleet_overview.py doesn't import this module, so there
    is no cycle - this is just kept local to avoid the two modules taking on
    an eager top-level dependency on each other for what is a single
    call site.
    """
    from dashboard.components.fleet_overview import technique_availability, technique_label

    availability = technique_availability(client)
    if not availability:
        aggregate = "missing"
    elif all(availability.values()):
        aggregate = "available"
    elif any(availability.values()):
        aggregate = "partial"
    else:
        aggregate = "missing"

    label, color, background = _status_view(aggregate)
    children = [
        html.Strong(t("source_status.data_sources", label=label)),
        html.Span("  "),
    ]
    for technique, available in availability.items():
        item_label, item_color, item_bg = _status_view("available" if available else "missing")
        children.append(
            html.Span(
                f"{technique_label(technique)}: {item_label}",
                title=(
                    t("source_status.technique_has_reading")
                    if available
                    else t("source_status.technique_no_reading")
                ),
                style={
                    "display": "inline-block",
                    "marginRight": "8px",
                    "padding": "2px 7px",
                    "borderRadius": "4px",
                    "backgroundColor": item_bg,
                    "color": item_color,
                    "fontSize": "11px",
                },
            )
        )
    return html.Div(
        children,
        className="mb-3",
        style={
            "padding": "8px 12px",
            "borderLeft": f"4px solid {color}",
            "backgroundColor": background,
            "fontSize": "12px",
        },
    )
