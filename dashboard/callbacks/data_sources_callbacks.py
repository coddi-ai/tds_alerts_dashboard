"""Fills the "Fuentes de Datos" button + popover in the header of the pages that render it from the
selected client (Informe de Confiabilidad, Campbell AI, Troubleshooting, Reportabilidad, Informe
preliminar de falla, Validación/Seguimiento de Avisos and Administración > Mailing).

Alertas, Telemetría, Aceite, Resumen General and Predictivo fill theirs next to their own callbacks.
Which sources a page lists lives in `config/service_data_sources.py`; how each one is resolved in
`dashboard/components/source_status.py`.
"""

from dash import Input, Output, callback

from dashboard.components.source_status import render_service_data_sources
from src.utils.logger import get_logger

logger = get_logger(__name__)

# service id -> id of the header slot (an empty html.Div in the page's layout).
HEADER_SLOTS = {
    "monitoring-mantenciones": "mantenciones-source-status",
    "agents-campbell-ai": "campbell-ai-source-status",
    "agents-troubleshooting": "troubleshooting-source-status",
    "reporting-main": "reporting-source-status",
    "reporting-informe-falla": "informe-source-status",
    "integration-validacion-avisos": "erp-validacion-source-status",
    "integration-seguimiento-avisos": "erp-seguimiento-source-status",
    "admin-mailing": "mailing-source-status",
}


def _register(service_id: str, slot_id: str) -> None:
    @callback(Output(slot_id, "children"), Input("client-selector", "value"))
    def update_source_status(client):
        if not client:
            return None
        try:
            return render_service_data_sources(client, service_id)
        except Exception:
            # The indicator is context; a failure resolving it must never break the page.
            logger.exception("Fuentes de Datos: could not resolve %s for %s", service_id, client)
            return None

    update_source_status.__name__ = f"update_source_status_{service_id.replace('-', '_')}"


for _service_id, _slot_id in HEADER_SLOTS.items():
    _register(_service_id, _slot_id)
