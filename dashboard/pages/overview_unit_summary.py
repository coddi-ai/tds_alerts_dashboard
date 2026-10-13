from src.i18n import page_title
import dash
from dash import dcc, html

from dashboard.services_registry import UNIT_SUMMARY_PATH_TEMPLATE


def layout(unit_id: str = None, **kwargs):
    """Static shell only - actual content (header, prev/next, body) is
    filled in reactively by dashboard/callbacks/unit_summary_callbacks.py,
    keyed off `client-selector` and the `unit_id` path param stashed below,
    exactly like the Fleet Overview page does for its own cards."""
    return html.Div([
        dcc.Store(id='unit-summary-current-unit', data=unit_id),
        dcc.Loading(
            id='loading-unit-summary-content',
            type='circle',
            children=[html.Div(id='unit-summary-content')],
        ),
    ], className="container-fluid p-4")


# pages_folder="" disables Dash's auto-discovery "plug" step, which is what
# normally fills in page["layout"] from the module's `layout` attribute — so
# with manual registration, `layout=` must be passed explicitly here.
dash.register_page(
    __name__,
    path_template=UNIT_SUMMARY_PATH_TEMPLATE,
    title=page_title("page.title.overview_unit_summary"),
    layout=layout,
)
