from src.i18n import page_title
import dash
from dashboard.tabs.tab_integration_validacion_avisos import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(__name__, path="/integration/validacion-avisos", title=page_title("page.title.integration_validacion_avisos"), layout=layout)
