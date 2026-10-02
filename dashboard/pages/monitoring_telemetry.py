from src.i18n import page_title
import dash
from dashboard.tabs.tab_telemetry import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(__name__, path="/monitoring/telemetry", title=page_title("page.title.monitoring_telemetry"), layout=layout)
