from src.i18n import page_title
import dash
from dashboard.tabs.tab_integration_seguimiento_avisos import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(__name__, path="/integration/seguimiento-avisos", title=page_title("page.title.integration_seguimiento_avisos"), layout=layout)
