from src.i18n import page_title
import dash
from dashboard.tabs.tab_user_registry import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(
    __name__,
    path="/admin/registro-usuarios",
    title=page_title("page.title.admin_user_registry"),
    layout=layout,
)
