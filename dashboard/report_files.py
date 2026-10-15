"""
Entrega de reportes de S3 al navegador (pestaña Reportes > Reportabilidad).

La pagina enlaza con la ruta Flask `{PATH_PREFIX}reports/file?client=<X>&key=<fecha/archivo>`.
La ruta repite las comprobaciones de acceso (la guarda de rutas de Dash no la
cubre) y transmite el PDF desde S3 a traves del servidor: el navegador nunca ve
credenciales ni una URL firmada de S3, solo el cliente y la clave relativa.

Comprobaciones, en orden: sesion del dashboard, cliente del usuario, servicio
`reporting-main` habilitado y no dummy, clave con forma de reporte conocido y
sistema visible para el cliente. Solo entonces se pide el objeto a S3, siempre
bajo `{raiz}/{cliente}/reports/`.

Es la solucion sencilla (proxy). Pasa cada byte por el dashboard, lo que esta
bien para PDFs de cientos de KB; si crecen el volumen o el tamaño, el paso
siguiente es redirigir a una URL prefirmada de vida corta (~60 s) emitida con
el rol IAM de la tarea, o servirlos por CloudFront con URLs firmadas.
"""

from __future__ import annotations

import logging
from typing import List
from urllib.parse import quote, urlencode

import dash
from flask import Response, make_response, redirect, request, stream_with_context

from config.client_services import is_service_dummy, is_service_enabled, normalize_client_id
from config.users import USERS
from dashboard.auth import resolve_authenticated_username
from src.data.report_store import (
    TECHNIQUE_SYSTEMS,
    ReportNotFound,
    get_report_store,
    parse_report_key,
)
from src.i18n import t

logger = logging.getLogger(__name__)

SERVICE_ID = "reporting-main"
REPORT_FILE_PATH = "reports/file"


def visible_systems(client: str, technique: str) -> List[str]:
    """
    Sistemas de una tecnica que el cliente puede ver. Para predictivo sigue el
    registro de servicios: sin `predictive-transmision` no hay informes de
    transmision, aunque existan en el bucket.
    """
    client = normalize_client_id(client)
    return [s for s in TECHNIQUE_SYSTEMS.get(technique, ())
            if is_service_enabled(client, f"predictive-{s}")]


def reporting_available(client: str) -> bool:
    client = normalize_client_id(client)
    return bool(client) and is_service_enabled(client, SERVICE_ID) and not is_service_dummy(client, SERVICE_ID)


def report_file_href(client: str, key: str, download: bool = False) -> str:
    """Enlace relativo a la ruta de entrega (requiere app de Dash activa)."""
    params = {"client": normalize_client_id(client), "key": key}
    if download:
        params["download"] = "1"
    return dash.get_relative_path(f"/{REPORT_FILE_PATH}") + "?" + urlencode(params)


def _plain(status: int, message: str):
    response = make_response(message, status)
    response.mimetype = "text/plain"
    response.headers["Cache-Control"] = "no-store"
    return response


def _content_disposition(filename: str, download: bool) -> str:
    kind = "attachment" if download else "inline"
    return f"{kind}; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"


def report_file_response(app_root: str):
    """Respuesta de la ruta de entrega para el request activo."""
    username = resolve_authenticated_username()
    if not username:
        return redirect(app_root, code=302)

    client = normalize_client_id(request.args.get("client", ""))
    user_clients = {normalize_client_id(c) for c in USERS.get(username, {}).get("clients", [])}
    if not client or client not in user_clients:
        logger.warning(f"Reporte denegado: cliente '{client}' ajeno al usuario '{username}'")
        return _plain(403, t("report_files.no_access_client"))
    if not reporting_available(client):
        logger.warning(f"Reporte denegado: reportabilidad no habilitada para '{client}' (usuario '{username}')")
        return _plain(403, t("report_files.service_disabled"))

    key = request.args.get("key", "")
    entry = parse_report_key(key)
    if entry is None:
        return _plain(400, t("report_files.invalid_key"))
    if entry.system not in visible_systems(client, entry.technique):
        return _plain(404, t("report_files.not_found"))

    store = get_report_store()
    if store is None:
        return _plain(503, t("report_files.storage_unavailable"))
    try:
        chunks, length = store.open_report(client, entry.key)
    except ReportNotFound:
        return _plain(404, t("report_files.not_found"))
    except Exception as exc:
        logger.error(f"Reporte {client}/{entry.key}: error leyendo S3 ({type(exc).__name__})")
        return _plain(502, t("report_files.storage_unavailable"))

    download = request.args.get("download") == "1"
    logger.info(f"Reporte entregado: usuario '{username}', cliente '{client}', clave '{entry.key}'")
    response = Response(stream_with_context(chunks), mimetype="application/pdf")
    if length is not None:
        response.headers["Content-Length"] = str(length)
    response.headers["Content-Disposition"] = _content_disposition(entry.filename, download)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    # La previsualizacion lo muestra en un iframe del propio dashboard; nadie mas puede embeberlo.
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    return response


def register_report_files(app: dash.Dash) -> None:
    """Registra la ruta Flask bajo el prefijo de Dash, fuera del espacio de paginas."""
    route = f"{app.config.routes_pathname_prefix}{REPORT_FILE_PATH}"
    app_root = app.config.requests_pathname_prefix

    def report_file():
        return report_file_response(app_root)

    app.server.add_url_rule(route, "report_file", report_file, methods=["GET"])
