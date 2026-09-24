"""
Tarjeta de la pestaña Agentes > Troubleshooting.

El boton es un `<a target="_blank">` normal hacia la ruta Flask de traspaso
(dashboard/troubleshooting_handoff.py), no un callback que abra la ventana:
un `window.open` lanzado tras un callback asincrono no cuenta como gesto del
usuario y los bloqueadores de ventanas emergentes lo cortan. Como el token se
firma al recibir el clic, el tiempo que el usuario pase en esta pagina no
consume su vida util. El `href` solo lleva el cliente; la autorizacion real
se repite en la ruta.
"""

from urllib.parse import urlencode

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, html
from dash.exceptions import PreventUpdate

from config.client_services import is_service_dummy, is_service_enabled, normalize_client_id
from dashboard.troubleshooting_handoff import (
    HANDOFF_PATH,
    SERVICE_ID,
    sso_enabled,
    troubleshooting_agent_configured,
)


def handoff_href(client: str) -> str:
    """Enlace relativo a la ruta de traspaso para el cliente activo."""
    return dash.get_relative_path(f"/{HANDOFF_PATH}") + "?" + urlencode({"client": normalize_client_id(client)})


def _unavailable(message: str) -> dbc.Alert:
    return dbc.Alert([html.I(className="fas fa-circle-info me-2"), message], color="secondary", className="mb-0")


def build_troubleshooting_card(client: str, agent_configured: bool, with_sso: bool) -> dbc.Card:
    """Contenido de la tarjeta para el cliente activo."""
    client = normalize_client_id(client)

    if not agent_configured:
        body = [_unavailable("El agente de troubleshooting no está disponible en este entorno.")]
    elif not client or not is_service_enabled(client, SERVICE_ID) or is_service_dummy(client, SERVICE_ID):
        # El selector puede cambiar de cliente estando en esta pagina; la
        # guarda de rutas solo actua al navegar.
        body = [_unavailable("El agente de troubleshooting no está habilitado para este cliente.")]
    else:
        access_note = (
            "Entrarás con tu sesión del dashboard."
            if with_sso
            else "El agente te pedirá sus propias credenciales."
        )
        body = [
            html.P(
                f"Consulta manuales y códigos de falla de la flota de {client}.",
                className="mb-3",
            ),
            html.A(
                [html.I(className="fas fa-arrow-up-right-from-square me-2"), "Abrir agente de troubleshooting"],
                id="troubleshooting-open-link",
                href=handoff_href(client),
                target="_blank",
                rel="noopener noreferrer",
                className="btn btn-primary",
            ),
            html.P(
                [
                    f"Se abre en una pestaña nueva. {access_note} ",
                    "Si recargas esa pestaña, vuelve a abrirla desde aquí.",
                ],
                className="text-muted small mt-3 mb-0",
            ),
        ]

    return dbc.Card([
        dbc.CardHeader(
            html.H5([html.I(className="fas fa-robot me-2"), "Troubleshooting"], className="mb-0"),
            className="bg-light",
        ),
        dbc.CardBody(body),
    ], className="shadow-sm mb-4")


def register_troubleshooting_callbacks(app: dash.Dash) -> None:
    """Rellena la tarjeta segun el cliente activo."""

    @app.callback(
        Output("troubleshooting-agent-card", "children"),
        Input("client-selector", "value"),
        State("user-info-store", "data"),
    )
    def render_troubleshooting_card(selected_client, user_data):
        if not user_data:
            raise PreventUpdate
        user_clients = user_data.get("clients", [])
        client = selected_client or (user_clients[0] if user_clients else "")
        return build_troubleshooting_card(client, troubleshooting_agent_configured(), sso_enabled())
