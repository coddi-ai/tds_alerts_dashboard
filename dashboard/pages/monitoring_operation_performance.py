from src.i18n import page_title
import dash
from dashboard.tabs.tab_operation_performance import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(
    __name__,
    path="/monitoring/operacion-rendimiento",
    title=page_title("page.title.monitoring_operation_performance"),
    layout=layout,
)
