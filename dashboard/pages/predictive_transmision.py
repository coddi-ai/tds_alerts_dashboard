"""
Predictive - Transmisión page.

See dashboard/pages/predictive_motor.py for why this is a placeholder
container filled in reactively by predictive_pages_callbacks.py.
"""

from src.i18n import page_title
import dash
from dash import html


def layout(**kwargs):
    return html.Div(id={'type': 'predictive-page-content', 'component': 'transmision'})


dash.register_page(__name__, path="/predictive/transmision", title=page_title("page.title.predictive_transmision"), layout=layout)
