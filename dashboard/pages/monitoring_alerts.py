from src.i18n import page_title
import dash
from dashboard.tabs.tab_alerts import create_layout


def layout(unit=None, alert=None, **kwargs):
    """`?unit=<id>` opens the General view filtered to that unit; `?alert=<id>` opens that alert's
    detail (the drill-downs of Resumen > Unidad)."""
    return create_layout(unit=unit, alert=alert)


dash.register_page(__name__, path="/monitoring/alerts", title=page_title("page.title.monitoring_alerts"), layout=layout)
