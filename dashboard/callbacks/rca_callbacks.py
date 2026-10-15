"""
Callbacks de Reportes > Reporte RCA (dashboard/pages/reporting_rca.py).

Flujo: al cambiar de cliente se cargan sus unidades (las mismas del Resumen General);
las imagenes subidas quedan en `rca-images-store` con su descripcion; "Generar" valida
la unidad, arma la solicitud (src/data/rca_report.py) y se la pasa al generador. Como
el generador aun esta en desarrollo, el resultado muestra la solicitud que recibiria.
"""

from __future__ import annotations

import json
from typing import List, Optional

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from config.client_services import is_service_dummy, is_service_enabled, normalize_client_id
from dashboard.components.fleet_overview import get_ordered_units
from src.data.erp_schemas import SYSTEM_LABELS
from src.data.rca_report import (
    RCA_MAX_IMAGE_BYTES,
    RCA_MAX_IMAGES,
    STATUS_PENDING_BACKEND,
    build_rca_request,
    decode_image,
    request_summary,
    submit_rca_request,
)
from src.data.report_health import unit_key
from src.data.report_store import unit_sort_key
from src.i18n import t
from src.utils.logger import get_logger

logger = get_logger(__name__)

SERVICE_ID = "reporting-rca"


def _notice(message: str, color: str = "secondary") -> dbc.Alert:
    return dbc.Alert([html.I(className="fas fa-circle-info me-2"), message], color=color, className="mb-4")


def load_units(client: str, user_clients: List[str]):
    """(unidades ordenadas, aviso) para el cliente activo; aviso es None si todo salio bien."""
    client = normalize_client_id(client)
    if not client or client not in {normalize_client_id(c) for c in user_clients}:
        return [], _notice(t("reporting.no_access"))
    if not is_service_enabled(client, SERVICE_ID) or is_service_dummy(client, SERVICE_ID):
        return [], _notice(t("rca.unavailable", client=client))
    # Mantenciones trae `T_09` donde el resto dice `T_9`: es la misma unidad.
    units = sorted({unit_key(e["unit"]) for e in get_ordered_units(client)}, key=unit_sort_key)
    if not units:
        return [], _notice(t("rca.no_units", client=client))
    return units, None


def system_label(system: Optional[str]) -> str:
    if not system:
        return t("tab_alerts_detail.todos_los_sistemas")
    try:
        return SYSTEM_LABELS[system]
    except KeyError:
        return system


def format_size(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB" if size >= 1024 * 1024 else f"{max(1, size // 1024)} KB"


def add_images(images: List[dict], contents, filenames) -> tuple:
    """(imagenes, rechazos) tras agregar lo subido; rechazos = [(archivo, motivo)]."""
    images = list(images or [])
    rejected = []
    for content, filename in zip(contents or [], filenames or []):
        if len(images) >= RCA_MAX_IMAGES:
            rejected.append((filename, "limit"))
            continue
        image, reason = decode_image(filename, content)
        if image is None:
            rejected.append((filename, reason))
        else:
            images.append(image)
    return images, rejected


def with_captions(images: List[dict], caption_ids: List[dict], captions: List[Optional[str]]) -> List[dict]:
    """Copia a cada imagen la descripcion escrita en su tarjeta de la galeria."""
    by_id = {cid["id"]: (caption or "") for cid, caption in zip(caption_ids or [], captions or [])}
    return [{**image, "caption": by_id.get(image["id"], image.get("caption", ""))} for image in images or []]


def rejection_alert(rejected: list):
    if not rejected:
        return None
    reasons = {
        "type": t("rca.reject_type"),
        "size": t("rca.reject_size", max_mb=RCA_MAX_IMAGE_BYTES // (1024 * 1024)),
        "invalid": t("rca.reject_invalid"),
        "limit": t("rca.reject_limit", max_images=RCA_MAX_IMAGES),
    }
    return dbc.Alert([
        html.Div([html.I(className="fas fa-triangle-exclamation me-2"), t("rca.rejected_title")],
                 className="fw-bold mb-1"),
        html.Ul([html.Li(f"{name}: {reasons.get(reason, reason)}") for name, reason in rejected],
                className="mb-0 small"),
    ], color="warning", dismissable=True, className="mt-3 mb-0")


def build_gallery(images: List[dict]):
    if not images:
        return html.P(t("rca.no_images"), className="text-muted small mb-0")
    return dbc.Row([
        dbc.Col(dbc.Card([
            html.Div([
                html.Img(src=image["data"], alt=image["filename"], className="rca-thumb"),
                dbc.Button(html.I(className="fas fa-xmark"),
                           id={"type": "rca-image-remove", "id": image["id"]},
                           n_clicks=0, color="light", size="sm", className="rca-thumb-remove",
                           title=t("rca.remove_image")),
            ], className="position-relative"),
            dbc.CardBody([
                html.Div(image["filename"], className="small fw-bold text-truncate", title=image["filename"]),
                html.Div(format_size(image["size"]), className="text-muted small mb-2"),
                dbc.Input(id={"type": "rca-image-caption", "id": image["id"]}, value=image.get("caption", ""),
                          placeholder=t("rca.caption_placeholder"), size="sm", maxLength=200),
            ], className="p-2"),
        ], className="h-100 shadow-sm"), xs=12, sm=6, lg=4, xl=2)
        for image in images
    ], className="g-3")


def build_result(request: dict, response: dict):
    """Resumen de la solicitud y estado del generador."""
    summary = request_summary(request)
    rows = [
        (t("reporting.filter_unit"), request["unit"]),
        (t("alerts_general.filter_system"), system_label(request["system"])),
        (t("rca.event_date"), request["event_date"] or "—"),
        (t("rca.field_title"), request["title"] or "—"),
        (t("rca.images_title"), str(len(request["images"]))),
    ]
    if response.get("status") == STATUS_PENDING_BACKEND:
        status = dbc.Alert([
            html.I(className="fas fa-person-digging me-2"), t("rca.pending_backend"),
        ], color="info", className="mb-3")
    elif response.get("status") == "ready" and response.get("href"):
        status = dbc.Alert([
            html.I(className="fas fa-circle-check me-2"), t("rca.ready"),
            html.A([html.I(className="fas fa-file-pdf me-1"), t("reporting.preview")],
                   href=response["href"], target="_blank", rel="noopener noreferrer",
                   className="btn btn-primary btn-sm ms-3"),
        ], color="success", className="mb-3 d-flex align-items-center")
    else:
        status = dbc.Alert([
            html.I(className="fas fa-triangle-exclamation me-2"),
            response.get("message") or t("rca.generation_error"),
        ], color="danger", className="mb-3")

    return dbc.Card([
        dbc.CardHeader(
            html.H5([html.I(className="fas fa-clipboard-check me-2"), t("rca.result_title")], className="mb-0"),
            className="bg-primary text-white",
        ),
        dbc.CardBody([
            status,
            dbc.Row([
                dbc.Col([html.Small(label, className="text-muted d-block"), html.Strong(value)], xs=6, lg=True)
                for label, value in rows
            ], className="g-3 mb-3"),
            html.Details([
                html.Summary(t("rca.request_json"), className="small text-primary", style={"cursor": "pointer"}),
                html.Pre(json.dumps(summary, ensure_ascii=False, indent=2), className="rca-json mt-2 mb-0"),
            ]),
        ]),
    ], className="shadow-sm mb-4")


def register_rca_callbacks(app: dash.Dash) -> None:
    """Unidades por cliente, galeria de imagenes, generacion y limpieza del formulario."""

    @app.callback(
        Output("rca-unit", "options"),
        Output("rca-unit", "value"),
        Output("rca-status", "children"),
        Output("rca-body", "style"),
        Input("client-selector", "value"),
        State("user-info-store", "data"),
    )
    def load_rca_units(selected_client, user_data):
        if not user_data:
            raise PreventUpdate
        user_clients = user_data.get("clients", [])
        client = selected_client or (user_clients[0] if user_clients else "")
        units, notice = load_units(client, user_clients)
        return [{"label": u, "value": u} for u in units], None, notice, {} if units else {"display": "none"}

    @app.callback(
        Output("rca-generate", "disabled"),
        Output("rca-unit-feedback", "children"),
        Input("rca-unit", "value"),
    )
    def toggle_rca_generate(unit):
        return not unit, None

    @app.callback(
        Output("rca-images-store", "data"),
        Output("rca-upload", "contents"),
        Output("rca-images-feedback", "children"),
        Input("rca-upload", "contents"),
        Input({"type": "rca-image-remove", "id": ALL}, "n_clicks"),
        State("rca-upload", "filename"),
        State("rca-images-store", "data"),
        State({"type": "rca-image-caption", "id": ALL}, "id"),
        State({"type": "rca-image-caption", "id": ALL}, "value"),
        prevent_initial_call=True,
    )
    def update_rca_images(contents, _removes, filenames, images, caption_ids, captions):
        # Antes de re-dibujar la galeria se guardan las descripciones escritas.
        images = with_captions(images, caption_ids, captions)
        trigger = ctx.triggered_id
        if isinstance(trigger, dict):
            # La galeria se recrea con n_clicks=0: eso no es un clic.
            if not (ctx.triggered and ctx.triggered[0].get("value")):
                raise PreventUpdate
            return [i for i in images if i["id"] != trigger["id"]], no_update, None
        if not contents:
            raise PreventUpdate
        images, rejected = add_images(images, contents, filenames)
        # Limpiar `contents` permite volver a subir el mismo archivo tras quitarlo.
        return images, None, rejection_alert(rejected)

    @app.callback(
        Output("rca-gallery", "children"),
        Output("rca-images-count", "children"),
        Input("rca-images-store", "data"),
    )
    def render_rca_gallery(images):
        images = images or []
        return build_gallery(images), t("rca.images_count", count=len(images), max_images=RCA_MAX_IMAGES)

    @app.callback(
        Output("rca-result", "children"),
        Output("rca-unit-feedback", "children", allow_duplicate=True),
        Input("rca-generate", "n_clicks"),
        State("client-selector", "value"),
        State("user-info-store", "data"),
        State("rca-unit", "value"),
        State("rca-system", "value"),
        State("rca-event-date", "date"),
        State("rca-title", "value"),
        State("rca-description", "value"),
        State("rca-findings", "value"),
        State("rca-actions", "value"),
        State("rca-images-store", "data"),
        State({"type": "rca-image-caption", "id": ALL}, "id"),
        State({"type": "rca-image-caption", "id": ALL}, "value"),
        prevent_initial_call=True,
    )
    def generate_rca_report(n_clicks, selected_client, user_data, unit, system, event_date,
                            title, description, findings, actions, images, caption_ids, captions):
        if not n_clicks or not user_data:
            raise PreventUpdate
        if not unit:
            return no_update, t("rca.unit_required")
        user_clients = user_data.get("clients", [])
        client = normalize_client_id(selected_client or (user_clients[0] if user_clients else ""))
        # Se repite la autorizacion: la unidad viene del navegador.
        units, notice = load_units(client, user_clients)
        if notice is not None or unit not in units:
            return notice or _notice(t("reporting.no_access")), None

        request = build_rca_request(
            client, unit, system, event_date,
            {"title": title, "description": description, "findings": findings, "actions": actions},
            with_captions(images, caption_ids, captions),
            user_data.get("username"),
        )
        try:
            response = submit_rca_request(request)
        except Exception as exc:
            logger.error(f"Reporte RCA {client}/{unit}: fallo el generador ({type(exc).__name__}: {exc})")
            response = {"status": "error"}
        return build_result(request, response), None

    @app.callback(
        Output("rca-unit", "value", allow_duplicate=True),
        Output("rca-system", "value"),
        Output("rca-event-date", "date"),
        Output("rca-title", "value"),
        Output("rca-description", "value"),
        Output("rca-findings", "value"),
        Output("rca-actions", "value"),
        Output("rca-images-store", "data", allow_duplicate=True),
        Output("rca-images-feedback", "children", allow_duplicate=True),
        Output("rca-result", "children", allow_duplicate=True),
        Input("rca-clear", "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_rca_form(n_clicks):
        if not n_clicks:
            raise PreventUpdate
        return None, None, None, "", "", "", "", [], None, None
