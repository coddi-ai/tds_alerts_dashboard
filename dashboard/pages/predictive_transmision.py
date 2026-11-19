"""
Predictive - Transmisión page.

See dashboard/pages/predictive_motor.py for why this is a placeholder
container filled in reactively by predictive_pages_callbacks.py.
"""

from src.i18n import page_title
import dash
from dash import dcc, html


def layout(unit=None, **kwargs):
    """`?unit=<id>` opens the Evidencia tab on that unit (the drill-down of Resumen > Unidad)."""
    return html.Div([
        html.Div(id={'type': 'predictive-page-content', 'component': 'transmision'}),
        # Read by the callback that fills the container above.
        dcc.Store(id={'type': 'predictive-url-seed', 'component': 'transmision'}, data=unit),
    ])


dash.register_page(__name__, path="/predictive/transmision", title=page_title("page.title.predictive_transmision"), layout=layout)
