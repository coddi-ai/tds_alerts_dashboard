from src.i18n import t
from src.i18n import page_title
import dash
from dash import html
import dash_bootstrap_components as dbc


def layout(**kwargs):
    return html.Div([
        dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.I(className="fas fa-plug-circle-xmark fa-3x mb-3 text-muted"),
                    html.H3(t("no_services.heading"), className="text-muted"),
                    html.P(
                        t("no_services.body"),
                        className="text-muted mb-0"
                    ),
                ], className="text-center py-5")
            ])
        ])
    ], className="mt-4")


dash.register_page(
    __name__,
    path="/sin-servicios",
    title=page_title("page.title.no_services"),
    layout=layout,
)
