from src.i18n import page_title, t
import dash
from dashboard.layout import create_placeholder_content


def layout(**kwargs):
    return create_placeholder_content(t("nav.section.admin"))


dash.register_page(__name__, path="/admin", title=page_title("page.title.admin_main"), layout=layout)
