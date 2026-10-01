"""
Acceso al agente de troubleshooting (repo `tds_faillure_code_agent`).

La pestaña Agentes > Troubleshooting (dashboard/pages/agents_troubleshooting.py)
enlaza con la ruta Flask `{PATH_PREFIX}handoff/troubleshooting?client=<X>`.
Esa ruta repite las comprobaciones de acceso (la guarda de rutas de Dash no
la cubre), firma en el momento del clic un token de vida corta y redirige al
agente con `?sso=<token>`. El token nunca pasa por el DOM ni por el estado de
Dash. Diseño y decisiones: PLAN_INTEGRACION_DASHBOARD.md (§5 y §7).

Contrato del token, identico en `src/sso.py` del repo agente:

    URLSafeTimedSerializer(TROUBLESHOOTING_SSO_SECRET, salt="tds-failure-agent-handoff-v1")
    payload = {"v": 1, "sub": username, "name": nombre, "client": CLIENTE, "jti": uuid4.hex}

Sin campo `role`: el agente crea siempre una sesion `client` (decision D7).

Configuracion: `config/troubleshooting_integration.json`, un archivo IDENTICO
en este repo y en el del agente (secreto compartido, URL del agente). Una
variable de entorno con el nombre de la clave en mayusculas tiene precedencia
(TROUBLESHOOTING_AGENT_URL, TROUBLESHOOTING_SSO_SECRET); definida vacia,
desactiva ese valor:
- sin URL del agente, la pestaña se oculta;
- sin secreto (o de menos de 32 caracteres, o igual a `secret_key` de Flask),
  la ruta abre el agente sin token y el agente pide sus credenciales (Opcion A
  del plan). Nunca se reutiliza `secret_key`: quien controle el agente podria
  fabricar cookies de sesion del dashboard.

El secreto esta versionado: riesgo aceptado para la PoC (solo expone manuales
tecnicos). Antes de un cliente real se cambia en los dos archivos o se define
la variable en los dos entornos.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import dash
from flask import current_app, make_response, redirect, request
from itsdangerous import URLSafeTimedSerializer

from config.client_services import is_service_dummy, is_service_enabled, normalize_client_id
from config.users import USERS
from dashboard.auth import resolve_authenticated_username

logger = logging.getLogger(__name__)

SERVICE_ID = "agents-troubleshooting"
HANDOFF_PATH = "handoff/troubleshooting"

HANDOFF_SALT = "tds-failure-agent-handoff-v1"
CONTRACT_VERSION = 1

DEFAULT_AGENT_URL = "https://poc.tds.coddi.ai/agent-lab/"

INTEGRATION_FILE = Path(__file__).resolve().parent.parent / "config" / "troubleshooting_integration.json"

# Un secreto corto se adivina; por debajo de esto se trata como ausente.
MIN_SECRET_LENGTH = 32


def load_integration_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Contenido del archivo compartido con el agente; {} si falta o esta roto."""
    try:
        data = json.loads(Path(path or INTEGRATION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.error(f"Sin configuracion de integracion con el agente ({type(exc).__name__})")
        return {}
    return data if isinstance(data, dict) else {}


def _setting(key: str, default: Any = "") -> Any:
    """Variable de entorno KEY en mayusculas si existe; si no, el archivo compartido."""
    value = os.getenv(key.upper())
    if value is not None:
        return value
    return load_integration_config().get(key, default)


def get_agent_url() -> str:
    """URL publica del agente, o "" si no es una URL http(s) utilizable."""
    url = str(_setting("troubleshooting_agent_url", DEFAULT_AGENT_URL) or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return url


def troubleshooting_agent_configured() -> bool:
    """Interruptor global de la pestaña, encima del registro de servicios."""
    return bool(get_agent_url())


def get_sso_secret(flask_secret: Optional[str] = None) -> str:
    """
    Secreto de firma, o "" si el traspaso de identidad no esta disponible:
    ausente, demasiado corto o igual al `secret_key` de Flask.
    """
    secret = str(_setting("troubleshooting_sso_secret") or "").strip()
    if not secret:
        return ""
    if len(secret) < MIN_SECRET_LENGTH:
        logger.error("TROUBLESHOOTING_SSO_SECRET demasiado corto; traspaso de identidad desactivado")
        return ""
    if flask_secret is not None and secret == str(flask_secret):
        logger.error("TROUBLESHOOTING_SSO_SECRET coincide con secret_key de Flask; traspaso desactivado")
        return ""
    return secret


def sso_enabled() -> bool:
    """True si el agente se abre con la identidad del dashboard (requiere app activa)."""
    return bool(get_sso_secret(current_app.secret_key))


def issue_handoff_token(username: str, client: str, name: str = "", *,
                        secret: str, jti: Optional[str] = None) -> str:
    """Firma el token de traspaso. `secret` es obligatorio (ver get_sso_secret)."""
    if not secret:
        raise ValueError("Se requiere el secreto de integracion para firmar")
    payload = {
        "v": CONTRACT_VERSION,
        "sub": username,
        "name": name,
        "client": normalize_client_id(client),
        "jti": jti or uuid.uuid4().hex,
    }
    return URLSafeTimedSerializer(secret, salt=HANDOFF_SALT).dumps(payload)


def _with_query_param(url: str, key: str, value: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != key]
    query.append((key, value))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _deny(status: int, message: str):
    response = make_response(message, status)
    response.mimetype = "text/plain"
    return _no_store(response)


def handoff_response(app_root: str):
    """
    Respuesta de la ruta de traspaso para el request activo.

    Comprobaciones, en orden: sesion del dashboard, cliente del usuario,
    servicio habilitado y no dummy, agente configurado. Solo entonces firma.
    """
    username = resolve_authenticated_username()
    if not username:
        return _no_store(redirect(app_root, code=302))

    user = USERS.get(username, {})
    client = normalize_client_id(request.args.get("client", ""))
    user_clients = {normalize_client_id(c) for c in user.get("clients", [])}
    if not client or client not in user_clients:
        logger.warning(f"Handoff troubleshooting denegado: cliente '{client}' ajeno al usuario '{username}'")
        return _deny(403, "No tienes acceso a este cliente.")

    if not is_service_enabled(client, SERVICE_ID) or is_service_dummy(client, SERVICE_ID):
        logger.warning(f"Handoff troubleshooting denegado: servicio no habilitado para '{client}' (usuario '{username}')")
        return _deny(403, "El agente de troubleshooting no está habilitado para este cliente.")

    agent_url = get_agent_url()
    if not agent_url:
        return _deny(503, "El agente de troubleshooting no está disponible en este entorno.")

    secret = get_sso_secret(current_app.secret_key)
    if not secret:
        # Opcion A: el agente pide sus propias credenciales.
        logger.info(f"Handoff troubleshooting sin token (SSO desactivado): usuario '{username}', cliente '{client}'")
        return _no_store(redirect(agent_url, code=302))

    jti = uuid.uuid4().hex
    token = issue_handoff_token(username, client, str(user.get("name", "") or ""), secret=secret, jti=jti)
    # Nunca el token en el log: los del ALB ya guardan la URL completa.
    logger.info(f"Handoff troubleshooting: usuario '{username}', cliente '{client}', jti {jti}")
    return _no_store(redirect(_with_query_param(agent_url, "sso", token), code=302))


def register_troubleshooting_handoff(app: dash.Dash) -> None:
    """
    Registra la ruta Flask bajo el prefijo de Dash, fuera del espacio de
    paginas: `/agents/troubleshooting` es la pagina, esto es el salto.
    """
    route = f"{app.config.routes_pathname_prefix}{HANDOFF_PATH}"
    app_root = app.config.requests_pathname_prefix

    def troubleshooting_handoff():
        return handoff_response(app_root)

    app.server.add_url_rule(route, "troubleshooting_handoff", troubleshooting_handoff, methods=["GET"])
