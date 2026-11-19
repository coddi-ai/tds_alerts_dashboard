from src.i18n import page_title
import dash
from dashboard.tabs.tab_oil import create_layout


def layout(unit=None, component=None, **kwargs):
    """`?unit=<id>&component=<name>` opens Detalle de Reporte on that unit's component (the
    drill-down of Resumen > Unidad)."""
    return create_layout(unit=unit, component=component)


dash.register_page(__name__, path="/monitoring/oil", title=page_title("page.title.monitoring_oil"), layout=layout)
