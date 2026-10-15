"""
Entrega de los PDF del Reporte RCA (pestaña Reportes > Reporte RCA).

La vista enlaza con `{PATH_PREFIX}rca/file?client=<X>&id=<informe>`. Como en
dashboard/report_files.py, la ruta repite las comprobaciones de acceso (la guarda de
rutas de Dash no la cubre): sesion del dashboard, cliente del usuario y servicio
`reporting-rca` habilitado. El id solo puede nombrar un archivo de la carpeta del
cliente (src/rca/service.ruta_pdf valida su forma).
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import dash
from flask import redirect, request, send_file

from config.client_services import is_service_dummy, is_service_enabled, normalize_client_id
from config.users import USERS
from dashboard.auth import resolve_authenticated_username
from dashboard.report_files import _content_disposition, _plain
from src.i18n import t
from src.rca.service import ruta_pdf

logger = logging.getLogger(__name__)

SERVICE_ID = "reporting-rca"
RCA_FILE_PATH = "rca/file"


def rca_available(client: str) -> bool:
    client = normalize_client_id(client)
    return bool(client) and is_service_enabled(client, SERVICE_ID) and not is_service_dummy(client, SERVICE_ID)


def rca_file_href(client: str, report_id: str, download: bool = False) -> str:
    """Enlace relativo a la ruta de entrega (requiere app de Dash activa)."""
    params = {"client": normalize_client_id(client), "id": report_id}
    if download:
        params["download"] = "1"
    return dash.get_relative_path(f"/{RCA_FILE_PATH}") + "?" + urlencode(params)


def rca_file_response(app_root: str):
    """Respuesta de la ruta de entrega para el request activo."""
    username = resolve_authenticated_username()
    if not username:
        return redirect(app_root, code=302)

    client = normalize_client_id(request.args.get("client", ""))
    user_clients = {normalize_client_id(c) for c in USERS.get(username, {}).get("clients", [])}
    if not client or client not in user_clients:
        logger.warning(f"RCA denegado: cliente '{client}' ajeno al usuario '{username}'")
        return _plain(403, t("report_files.no_access_client"))
    if not rca_available(client):
        return _plain(403, t("rca.unavailable", client=client))

    report_id = request.args.get("id", "")
    path = ruta_pdf(client, report_id)
    if path is None:
        return _plain(404, t("report_files.not_found"))

    download = request.args.get("download") == "1"
    logger.info(f"RCA entregado: usuario '{username}', cliente '{client}', informe '{report_id}'")
    response = send_file(path, mimetype="application/pdf", max_age=0)
    response.headers["Content-Disposition"] = _content_disposition(path.name, download)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    # La vista lo muestra en un iframe del propio dashboard; nadie mas puede embeberlo.
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    return response


def register_rca_files(app: dash.Dash) -> None:
    """Registra la ruta Flask bajo el prefijo de Dash, fuera del espacio de paginas."""
    route = f"{app.config.routes_pathname_prefix}{RCA_FILE_PATH}"
    app_root = app.config.requests_pathname_prefix

    def rca_file():
        return rca_file_response(app_root)

    app.server.add_url_rule(route, "rca_file", rca_file, methods=["GET"])
