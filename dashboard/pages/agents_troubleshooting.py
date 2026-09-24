import dash
from dash import html


def layout(**kwargs):
    # The page router doesn't know the active client, so the card (and the
    # button's ?client= link) is filled in by
    # dashboard/callbacks/troubleshooting_callbacks.py from client-selector.
    return html.Div([
        html.Div([
            html.H3([
                html.I(className="fas fa-screwdriver-wrench me-2"),
                "Agente de Troubleshooting",
            ], className="text-primary mb-2"),
            html.P(
                "Consulta de manuales y códigos de falla con el corpus documental de tu cliente.",
                className="text-muted",
            ),
        ], className="mb-4"),
        html.Div(id="troubleshooting-agent-card"),
    ], className="container-fluid p-4")


dash.register_page(
    __name__,
    path="/agents/troubleshooting",
    title="Troubleshooting | Multi-Technical Alerts",
    layout=layout,
)
