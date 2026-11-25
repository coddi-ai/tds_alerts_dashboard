"""EMIN-only historical fleet analysis page."""

from src.i18n import page_title
import dash

from dashboard.tabs.tab_emin_historical import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(
    __name__,
    path="/overview/emin-historical",
    title=page_title("page.title.overview_emin_historical"),
    layout=layout,
)
