"""
Central nav/service registry.

Single source of truth mapping each client-gated service id to its URL,
label, icon, and parent nav section - used by both the sidebar builder
(dashboard/layout.py) and the centralized route guard
(dashboard/callbacks/access_control_callbacks.py), so the two never drift.

Admin routes (admin-main, admin-user-registry) are role-gated, not
client-service-gated, and are kept separate from KNOWN_SERVICE_IDS.
"""

from src.i18n import t
from typing import Optional
from urllib.parse import quote

import dash

from config.client_services import KNOWN_SERVICE_IDS, is_service_dummy, is_service_enabled

# Nav sections in display order. Each service id here must be one of
# config.client_services.KNOWN_SERVICE_IDS. 'predictive' is a section on its
# own, built dynamically per client from the per-component
# `predictive-<component>` service ids (dashboard/layout.py::build_navigation_items),
# not listed here.
SERVICE_SECTIONS = [
    {
        "section": "overview",
        "label": "Resumen",
        "icon": "fas fa-tachometer-alt",
        "services": ["overview-general"],
    },
    {
        "section": "monitoring",
        "label": "Monitoreo",
        "icon": "fas fa-chart-line",
        "services": ["monitoring-alerts", "monitoring-telemetry", "monitoring-oil", "monitoring-mantenciones"],
    },
    {
        "section": "agents",
        "label": "Agentes",
        "icon": "fas fa-robot",
        "services": ["agents-campbell-ai", "agents-troubleshooting"],
    },
    {
        "section": "integration",
        "label": "Conexión ERP",
        "icon": "fas fa-plug",
        "services": ["integration-validacion-avisos", "integration-seguimiento-avisos"],
    },
    {
        "section": "reporting",
        "label": "Reportes",
        "icon": "fas fa-file-alt",
        "services": ["reporting-main"],
    },
]

SERVICE_LABELS = {
    "overview-general": "General",
    "monitoring-alerts": "Alertas",
    "monitoring-telemetry": "Telemetría",
    "monitoring-oil": "Aceite",
    "monitoring-mantenciones": "Informe de confiabilidad",
    "predictive-motor": "Predictivo - Motor",
    "predictive-transmision": "Predictivo - Transmisión",
    "agents-campbell-ai": "Campbell AI",
    "agents-troubleshooting": "Troubleshooting",
    "integration-validacion-avisos": "Validación de Avisos",
    "integration-seguimiento-avisos": "Seguimiento de Avisos",
    "reporting-main": "Reportabilidad",
}

# service id / admin nav id -> URL path.
NAV_PATHS = {
    "overview-general": "/overview/general",
    "monitoring-alerts": "/monitoring/alerts",
    "monitoring-telemetry": "/monitoring/telemetry",
    "monitoring-oil": "/monitoring/oil",
    "monitoring-mantenciones": "/monitoring/mantenciones",
    "predictive-motor": "/predictive/motor",
    "predictive-transmision": "/predictive/transmision",
    "agents-campbell-ai": "/agents/campbell-ai",
    "agents-troubleshooting": "/agents/troubleshooting",
    "integration-validacion-avisos": "/integration/validacion-avisos",
    "integration-seguimiento-avisos": "/integration/seguimiento-avisos",
    "reporting-main": "/reporting",
    "admin-main": "/admin",
    "admin-user-registry": "/admin/registro-usuarios",
}

# Route guard resolution: stripped pathname ('dash.strip_relative_path' form,
# no leading/trailing slash) -> service id.
SERVICE_EXACT_ROUTES = {
    "overview/general": "overview-general",
    "monitoring/alerts": "monitoring-alerts",
    "monitoring/telemetry": "monitoring-telemetry",
    "monitoring/oil": "monitoring-oil",
    "monitoring/mantenciones": "monitoring-mantenciones",
    "agents/campbell-ai": "agents-campbell-ai",
    "agents/troubleshooting": "agents-troubleshooting",
    "integration/validacion-avisos": "integration-validacion-avisos",
    "integration/seguimiento-avisos": "integration-seguimiento-avisos",
    "reporting": "reporting-main",
}


# Unit Summary drill-down (Phase 2, documentation/general/general_specs/
# 02_unit_summary_navigation_shell.md) - not a sidebar nav item (reached
# only via a Fleet Overview card or lateral nav within the view itself), so
# it's kept out of NAV_PATHS/SERVICE_LABELS, but it's gated by the same
# 'overview-general' service as its parent view (see
# resolve_service_id_for_pathname below).
UNIT_SUMMARY_PATH_TEMPLATE = "/overview/unit/<unit_id>"


def section_label(section_id: str) -> str:
    """Translated label of a nav section (the Spanish source text is in SERVICE_SECTIONS)."""
    return t(f"nav.section.{section_id}")


def service_label(service_id: str) -> str:
    """Translated label of a nav item (the Spanish source text is in SERVICE_LABELS)."""
    return t(f"nav.service.{service_id}")


def nav_path(nav_id: str) -> str:
    """Resolve a nav-item id to its URL path (predictive component ids are dynamic)."""
    if nav_id.startswith("predictive-"):
        return f"/predictive/{nav_id.split('predictive-', 1)[1]}"
    return NAV_PATHS[nav_id]


def unit_summary_path(unit_id: str) -> str:
    """URL for a unit's Unit Summary drill-down (Phase 2). `unit_id` is
    quoted since raw unit identifiers (e.g. from Alerts/Telemetry) aren't
    guaranteed to be URL-safe as-is."""
    return f"/overview/unit/{quote(str(unit_id), safe='')}"


def relative_path(path: str) -> str:
    """`dash.get_relative_path`, tolerant of running before the Dash app
    singleton exists (e.g. unit tests that call the card/page builders
    directly without booting the full app via dashboard/app.py) - falls
    back to the raw path, which is exactly what `get_relative_path` would
    return whenever DASH_PATH_PREFIX is unset (the common case)."""
    try:
        return dash.get_relative_path(path)
    except AttributeError:
        return path


def resolve_service_id_for_pathname(rel_path: str) -> Optional[str]:
    """
    Resolve a stripped pathname (as returned by dash.strip_relative_path) to
    a service id, or None if it isn't a client-service-gated route.

    /predictive/<component> resolves to its own `predictive-<component>`
    service id, one per component, so access can be granted independently
    per component instead of via a single umbrella service.

    /overview/unit/<unit_id> (Phase 2's Unit Summary) resolves to the same
    'overview-general' service as the Fleet Overview it drills down from -
    a client without Fleet Overview enabled can't reach a unit's summary
    either.
    """
    if rel_path in SERVICE_EXACT_ROUTES:
        return SERVICE_EXACT_ROUTES[rel_path]

    if rel_path.startswith("predictive/"):
        component = rel_path.split("/", 2)[1]
        if component:
            return f"predictive-{component}"

    if rel_path.startswith("overview/unit/"):
        return "overview-general"

    return None


def first_enabled_service_path(client_id: str) -> Optional[str]:
    """
    First enabled, non-dummy service's path for a client, in canonical
    order, or None if none qualify. Dummy services are skipped here since
    landing on one would just bounce straight to /sin-servicios anyway (see
    access_control_callbacks.py).
    """
    for service_id in KNOWN_SERVICE_IDS:
        if is_service_enabled(client_id, service_id) and not is_service_dummy(client_id, service_id):
            return NAV_PATHS[service_id]
    return None
