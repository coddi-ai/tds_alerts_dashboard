from src.i18n import t, page_title
import dash
from dashboard.layout import create_placeholder_content


def layout(**kwargs):
    return create_placeholder_content(t("nav.service.reporting-main"))


dash.register_page(__name__, path="/reporting", title=page_title("page.title.reporting_main"), layout=layout)
