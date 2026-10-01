"""Pestaña Agentes > Troubleshooting y traspaso firmado al agente (repo tds_faillure_code_agent).

Contrato del token (PLAN_INTEGRACION_DASHBOARD.md §5), identico en `src/sso.py` del agente.
Las pruebas usan secretos sinteticos por variable de entorno (que tiene precedencia sobre
config/troubleshooting_integration.json); el secreto real del archivo nunca se imprime.
"""

from __future__ import annotations

import logging
from unittest import mock
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import dash
import itsdangerous.timed as itsdangerous_timed
import pytest
from itsdangerous import BadSignature, URLSafeTimedSerializer

from config.client_services import KNOWN_SERVICE_IDS, get_enabled_services, is_service_enabled
from config.users import USERS
from dashboard import troubleshooting_handoff as handoff
from dashboard.callbacks.troubleshooting_callbacks import build_troubleshooting_card
from dashboard.layout import build_navigation_items
from dashboard.services_registry import (
    NAV_PATHS,
    SERVICE_EXACT_ROUTES,
    SERVICE_LABELS,
    SERVICE_SECTIONS,
    resolve_service_id_for_pathname,
)

SSO_SECRET = "secreto-sintetico-de-pruebas-handoff-0123456789"
FLASK_SECRET = "flask-secret-key-sintetica-distinta-0123456789"
AGENT_URL = "https://agente.example.test/agent-lab/"
PREFIX = "/alerts-dashboard/"
ROUTE = f"{PREFIX}handoff/troubleshooting"

ADMIN = next(name for name, user in USERS.items() if user.get("role") == "admin")
CAPSTONE_USER = next(n for n, u in USERS.items() if u.get("role") == "client" and u.get("clients") == ["CAPSTONE"])
EMIN_USER = next(n for n, u in USERS.items() if u.get("role") == "client" and u.get("clients") == ["EMIN"])


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.setenv("TROUBLESHOOTING_AGENT_URL", AGENT_URL)
    monkeypatch.setenv("TROUBLESHOOTING_SSO_SECRET", SSO_SECRET)


@pytest.fixture
def client():
    """Un Dash con el mismo prefijo que el despliegue y solo la ruta de traspaso."""
    app = dash.Dash(__name__, url_base_pathname=PREFIX, suppress_callback_exceptions=True)
    app.layout = dash.html.Div()
    app.server.secret_key = FLASK_SECRET
    handoff.register_troubleshooting_handoff(app)
    app.server.testing = True
    with app.server.test_client() as test_client:
        yield test_client


def _login(test_client, username):
    with test_client.session_transaction() as session:
        session["dashboard_user"] = username


def _token_from(response) -> str:
    location = response.headers["Location"]
    assert location.startswith(AGENT_URL)
    return parse_qs(urlsplit(location).query)["sso"][0]


def _loads(token: str) -> dict:
    return URLSafeTimedSerializer(SSO_SECRET, salt=handoff.HANDOFF_SALT).loads(token, max_age=120)


# ---------------------------------------------------------------------------
# Registro del servicio
# ---------------------------------------------------------------------------

def test_servicio_conocido_y_ordenado_tras_campbell_ai():
    i = KNOWN_SERVICE_IDS.index("agents-campbell-ai")
    assert KNOWN_SERVICE_IDS[i + 1] == "agents-troubleshooting"


def test_todo_servicio_de_agentes_tiene_etiqueta_ruta_y_guarda():
    """Sin SERVICE_EXACT_ROUTES la ruta quedaria sin guarda para cualquier cliente."""
    agents = next(s for s in SERVICE_SECTIONS if s["section"] == "agents")
    assert "agents-troubleshooting" in agents["services"]
    for service_id in agents["services"]:
        assert service_id in KNOWN_SERVICE_IDS
        assert SERVICE_LABELS[service_id]
        path = NAV_PATHS[service_id]
        assert SERVICE_EXACT_ROUTES[path.strip("/")] == service_id
        assert resolve_service_id_for_pathname(path.strip("/")) == service_id
    assert SERVICE_LABELS["agents-troubleshooting"] == "Troubleshooting"


def test_habilitado_solo_en_clientes_con_base_en_el_agente():
    """Debe coincidir con CLIENT_TO_KB del agente (CDA y CAPSTONE en la PoC)."""
    habilitados = {c for c in ["CDA", "EMIN", "ENEX", "CAPSTONE", "CENTINELA"]
                   if is_service_enabled(c, "agents-troubleshooting")}
    assert habilitados == {"CDA", "CAPSTONE"}
    assert "agents-troubleshooting" not in get_enabled_services("EMIN")


def _nav_ids(client_id: str, username: str) -> list:
    user = USERS[username]
    user_data = {"username": username, "role": user["role"], "clients": user["clients"]}
    return [sub["id"] for sec in build_navigation_items(client_id, user_data) for sub in sec["subsections"]]


def test_menu_muestra_la_pestana_solo_al_cliente_habilitado():
    assert "agents-troubleshooting" in _nav_ids("CAPSTONE", CAPSTONE_USER)
    assert "agents-troubleshooting" not in _nav_ids("EMIN", EMIN_USER)


def test_menu_oculta_la_pestana_con_la_url_del_agente_vacia(monkeypatch):
    monkeypatch.setenv("TROUBLESHOOTING_AGENT_URL", "")
    assert "agents-troubleshooting" not in _nav_ids("CAPSTONE", CAPSTONE_USER)


def test_url_del_agente_desde_el_archivo_y_validacion(monkeypatch):
    monkeypatch.delenv("TROUBLESHOOTING_AGENT_URL")
    assert handoff.get_agent_url() == handoff.load_integration_config()["troubleshooting_agent_url"]
    monkeypatch.setattr(handoff, "INTEGRATION_FILE", Path("no-existe") / "integration.json")
    assert handoff.get_agent_url() == handoff.DEFAULT_AGENT_URL
    for invalid in ("javascript:alert(1)", "//otro.example/", "agente-sin-esquema", "ftp://x/"):
        monkeypatch.setenv("TROUBLESHOOTING_AGENT_URL", invalid)
        assert handoff.get_agent_url() == ""


# ---------------------------------------------------------------------------
# Firma del token
# ---------------------------------------------------------------------------

def test_token_se_verifica_con_el_mismo_secreto_y_salt():
    token = handoff.issue_handoff_token("cda_user", " cda ", "CDA", secret=SSO_SECRET)
    payload = _loads(token)
    assert payload["v"] == 1
    assert payload["sub"] == "cda_user"
    assert payload["client"] == "CDA"
    assert len(payload["jti"]) == 32
    assert "role" not in payload


def test_salt_de_identidad_del_dashboard_no_lo_acepta():
    token = handoff.issue_handoff_token("cda_user", "CDA", secret=SSO_SECRET)
    with pytest.raises(BadSignature):
        URLSafeTimedSerializer(SSO_SECRET, salt="tds-dashboard-identity-v1").loads(token)


def test_no_firma_sin_secreto():
    with pytest.raises(ValueError):
        handoff.issue_handoff_token("cda_user", "CDA", secret="")


def test_sin_variable_el_secreto_sale_del_archivo_compartido(monkeypatch):
    monkeypatch.delenv("TROUBLESHOOTING_SSO_SECRET")
    from config.settings import get_settings

    secret = handoff.get_sso_secret(FLASK_SECRET)
    # Comparaciones en variables: si fallan, pytest no imprime el secreto.
    from_file = secret == handoff.load_integration_config()["troubleshooting_sso_secret"]
    long_enough = len(secret) >= handoff.MIN_SECRET_LENGTH
    # Nunca el secret_key de Flask del dashboard (config/settings.py).
    reuses_flask_secret = secret == get_settings().secret_key
    assert from_file
    assert long_enough
    assert not reuses_flask_secret


def test_variable_vacia_o_archivo_ausente_desactivan_el_secreto(monkeypatch):
    monkeypatch.setenv("TROUBLESHOOTING_SSO_SECRET", "")
    assert handoff.get_sso_secret(FLASK_SECRET) == ""
    monkeypatch.delenv("TROUBLESHOOTING_SSO_SECRET")
    monkeypatch.setattr(handoff, "INTEGRATION_FILE", Path("no-existe") / "integration.json")
    assert handoff.get_sso_secret(FLASK_SECRET) == ""


def test_archivo_compartido_identico_al_del_agente():
    """Los dos repos deben tener el mismo archivo; se omite si el agente no esta al lado."""
    agent_copy = (
        Path(__file__).resolve().parents[2] / "tds_faillure_code_agent" / "config" / "troubleshooting_integration.json"
    )
    if not agent_copy.exists():
        pytest.skip("repo del agente no disponible junto al dashboard")
    identical = agent_copy.read_bytes() == handoff.INTEGRATION_FILE.read_bytes()
    assert identical, "config/troubleshooting_integration.json difiere entre dashboard y agente"


def test_secreto_igual_a_secret_key_o_corto_se_descarta(monkeypatch):
    monkeypatch.setenv("TROUBLESHOOTING_SSO_SECRET", FLASK_SECRET)
    assert handoff.get_sso_secret(FLASK_SECRET) == ""
    monkeypatch.setenv("TROUBLESHOOTING_SSO_SECRET", "corto")
    assert handoff.get_sso_secret(FLASK_SECRET) == ""


# Contrato cruzado: el mismo literal esta en tests/test_sso.py del agente,
# que comprueba que su verificador lo acepta.
FIXTURE_SECRET = "contrato-cruzado-secreto-sintetico-0123456789"
FIXTURE_SIGNED_AT = 1790000000
FIXTURE_JTI = "0123456789abcdef0123456789abcdef"
FIXTURE_TOKEN = (
    ".eJyrVipTsjLUUSouTVKyUkpOLCguyc9LjS8tTi1S0lHKS8xNVbJScoYKK4RChJNzMlPzSkASjgHBIf5-rko6SlklmUpWSgaGRsYmpmbmFpaJSckpqWnofKVaANmnIh8"
    ".arE7gA.4eHrFcYYX-UUU7BAp-u1GqYWWKE"
)


def test_contrato_cruzado_el_fixture_sigue_el_contrato_del_dashboard():
    """
    Se compara el contenido, no los bytes: itsdangerous comprime con zlib y la
    salida cambia entre versiones de Python (local frente a la imagen Docker).
    """
    serializer = URLSafeTimedSerializer(FIXTURE_SECRET, salt=handoff.HANDOFF_SALT)
    payload, signed_at = serializer.loads(FIXTURE_TOKEN, return_timestamp=True)
    assert int(signed_at.timestamp()) == FIXTURE_SIGNED_AT

    with mock.patch.object(itsdangerous_timed.time, "time", return_value=float(FIXTURE_SIGNED_AT)):
        token = handoff.issue_handoff_token(
            "capstone_user", "capstone", "Capstone User", secret=FIXTURE_SECRET, jti=FIXTURE_JTI
        )
    assert serializer.loads(token, return_timestamp=True) == (payload, signed_at)
    assert payload == {
        "v": 1, "sub": "capstone_user", "name": "Capstone User", "client": "CAPSTONE", "jti": FIXTURE_JTI,
    }


# ---------------------------------------------------------------------------
# Ruta de traspaso
# ---------------------------------------------------------------------------

def test_sin_sesion_redirige_al_login(client):
    response = client.get(f"{ROUTE}?client=CDA")
    assert response.status_code == 302
    assert urlsplit(response.headers["Location"]).path == PREFIX
    assert "sso" not in response.headers["Location"]


def test_cliente_ajeno_al_usuario_es_403(client):
    _login(client, CAPSTONE_USER)
    assert client.get(f"{ROUTE}?client=CDA").status_code == 403
    assert client.get(ROUTE).status_code == 403


def test_servicio_deshabilitado_es_403(client):
    _login(client, ADMIN)
    response = client.get(f"{ROUTE}?client=EMIN")
    assert response.status_code == 403
    assert "no-store" in response.headers["Cache-Control"]


def test_servicio_dummy_es_403(client, monkeypatch):
    monkeypatch.setattr(handoff, "is_service_dummy", lambda client_id, service_id: True)
    _login(client, CAPSTONE_USER)
    assert client.get(f"{ROUTE}?client=CAPSTONE").status_code == 403


def test_sin_url_del_agente_es_503(client, monkeypatch):
    monkeypatch.setenv("TROUBLESHOOTING_AGENT_URL", "")
    _login(client, CAPSTONE_USER)
    assert client.get(f"{ROUTE}?client=CAPSTONE").status_code == 503


def test_redirige_al_agente_con_token_del_cliente_activo(client, caplog):
    _login(client, ADMIN)
    with caplog.at_level(logging.INFO, logger=handoff.__name__):
        response = client.get(f"{ROUTE}?client=capstone")

    assert response.status_code == 302
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["Referrer-Policy"] == "no-referrer"
    token = _token_from(response)
    payload = _loads(token)
    # Un admin entra como cualquier usuario: con el cliente elegido, sin rol (D7).
    assert payload["sub"] == ADMIN
    assert payload["client"] == "CAPSTONE"
    assert "role" not in payload
    # Usuario, cliente y jti en el log; el token, nunca.
    assert payload["jti"] in caplog.text
    assert token not in caplog.text


def test_cada_clic_firma_un_token_distinto(client):
    _login(client, CAPSTONE_USER)
    first = _loads(_token_from(client.get(f"{ROUTE}?client=CAPSTONE")))
    second = _loads(_token_from(client.get(f"{ROUTE}?client=CAPSTONE")))
    assert first["jti"] != second["jti"]


def test_sin_secreto_abre_el_agente_sin_token(client, monkeypatch):
    """Opcion A: el agente pide sus credenciales; ningun token sale del dashboard."""
    monkeypatch.setenv("TROUBLESHOOTING_SSO_SECRET", "")
    _login(client, CAPSTONE_USER)
    response = client.get(f"{ROUTE}?client=CAPSTONE")
    assert response.status_code == 302
    assert response.headers["Location"] == AGENT_URL


def test_conserva_la_query_de_la_url_del_agente(client, monkeypatch):
    monkeypatch.setenv("TROUBLESHOOTING_AGENT_URL", "https://agente.example.test/?embed=1&sso=viejo")
    _login(client, CAPSTONE_USER)
    query = parse_qs(urlsplit(client.get(f"{ROUTE}?client=CAPSTONE").headers["Location"]).query)
    assert query["embed"] == ["1"]
    assert len(query["sso"]) == 1 and query["sso"][0] != "viejo"


# ---------------------------------------------------------------------------
# Tarjeta de la pagina
# ---------------------------------------------------------------------------

def _card_in_app(client_id: str, agent_configured: bool = True, with_sso: bool = True) -> str:
    app = dash.Dash(__name__, url_base_pathname=PREFIX)
    with app.server.test_request_context():
        return str(build_troubleshooting_card(client_id, agent_configured, with_sso).to_plotly_json())


def test_tarjeta_enlaza_a_la_ruta_de_traspaso_sin_token():
    card = _card_in_app("CAPSTONE")
    assert f"{PREFIX}handoff/troubleshooting?client=CAPSTONE" in card
    assert "_blank" in card and "noopener noreferrer" in card
    assert "sso" not in card


def test_tarjeta_sin_agente_configurado():
    card = _card_in_app("CAPSTONE", agent_configured=False)
    assert "no está disponible en este entorno" in card
    assert "handoff" not in card


def test_tarjeta_para_cliente_sin_el_servicio():
    card = _card_in_app("EMIN")
    assert "no está habilitado para este cliente" in card
    assert "handoff" not in card


def test_tarjeta_explica_el_modo_de_acceso():
    assert "sesión del dashboard" in _card_in_app("CDA", with_sso=True)
    assert "propias credenciales" in _card_in_app("CDA", with_sso=False)
