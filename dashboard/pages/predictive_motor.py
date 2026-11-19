"""
Predictive - Motor page.

The actual content depends on the globally-selected client (client-selector
in the navbar) and must react live when the client changes, so this page
only renders a placeholder container. Its content is filled in reactively by
the pattern-matching callback in dashboard/callbacks/predictive_pages_callbacks.py.
"""

from src.i18n import page_title
import dash
from dash import dcc, html


def layout(unit=None, **kwargs):
    """`?unit=<id>` opens the Evidencia tab on that unit (the drill-down of Resumen > Unidad)."""
    return html.Div([
        html.Div(id={'type': 'predictive-page-content', 'component': 'motor'}),
        # Read by the callback that fills the container above.
        dcc.Store(id={'type': 'predictive-url-seed', 'component': 'motor'}, data=unit),
    ])


dash.register_page(__name__, path="/predictive/motor", title=page_title("page.title.predictive_motor"), layout=layout)
