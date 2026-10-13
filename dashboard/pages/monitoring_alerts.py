from src.i18n import page_title
import dash
from dashboard.tabs.tab_alerts import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(__name__, path="/monitoring/alerts", title=page_title("page.title.monitoring_alerts"), layout=layout)
