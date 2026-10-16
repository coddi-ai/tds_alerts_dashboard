"""
Callbacks de Reportes > Informe preliminar de falla (dashboard/pages/reporting_informe_falla.py).

Flujo: al cambiar de cliente se cargan sus unidades (las mismas del Resumen General);
las imagenes subidas quedan en `informe-images-store` con su descripcion; "Generar" valida
unidad y fecha, arma la solicitud (src/data/informe_falla_request.py) y la encola en src/informe_falla/service.py.
La IA tarda, asi que `informe-job-poll` consulta el trabajo hasta que termina; entonces se
muestra el PDF (servido por dashboard/informe_falla_files.py) y se refresca el historial.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from config.client_services import is_service_dummy, is_service_enabled, normalize_client_id
from dashboard.components.fleet_overview import get_ordered_units
from src.data.erp_schemas import SYSTEM_LABELS
from dashboard.informe_falla_files import informe_file_href
from src.data.informe_falla_request import INFORME_MAX_IMAGE_BYTES, INFORME_MAX_IMAGES, build_informe_request, decode_image
from src.data.report_health import unit_key
from src.data.report_store import unit_sort_key
from src.i18n import t, t_or
from src.informe_falla import service
from src.informe_falla.catalog import COMPONENTE
from src.utils.logger import get_logger

logger = get_logger(__name__)

SERVICE_ID = "reporting-informe-falla"


def _notice(message: str, color: str = "secondary") -> dbc.Alert:
    return dbc.Alert([html.I(className="fas fa-circle-info me-2"), message], color=color, className="mb-4")


def load_units(client: str, user_clients: List[str]):
    """(unidades ordenadas, aviso) para el cliente activo; aviso es None si todo salio bien."""
    client = normalize_client_id(client)
    if not client or client not in {normalize_client_id(c) for c in user_clients}:
        return [], _notice(t("reporting.no_access"))
    if not is_service_enabled(client, SERVICE_ID) or is_service_dummy(client, SERVICE_ID):
        return [], _notice(t("informe_falla.unavailable", client=client))
    # Mantenciones trae `T_09` donde el resto dice `T_9`: es la misma unidad.
    units = sorted({unit_key(e["unit"]) for e in get_ordered_units(client)}, key=unit_sort_key)
    if not units:
        return [], _notice(t("informe_falla.no_units", client=client))
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
        if len(images) >= INFORME_MAX_IMAGES:
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
        "type": t("informe_falla.reject_type"),
        "size": t("informe_falla.reject_size", max_mb=INFORME_MAX_IMAGE_BYTES // (1024 * 1024)),
        "invalid": t("informe_falla.reject_invalid"),
        "limit": t("informe_falla.reject_limit", max_images=INFORME_MAX_IMAGES),
    }
    return dbc.Alert([
        html.Div([html.I(className="fas fa-triangle-exclamation me-2"), t("informe_falla.rejected_title")],
                 className="fw-bold mb-1"),
        html.Ul([html.Li(f"{name}: {reasons.get(reason, reason)}") for name, reason in rejected],
                className="mb-0 small"),
    ], color="warning", dismissable=True, className="mt-3 mb-0")


def build_gallery(images: List[dict]):
    if not images:
        return html.P(t("informe_falla.no_images"), className="text-muted small mb-0")
    return dbc.Row([
        dbc.Col(dbc.Card([
            html.Div([
                html.Img(src=image["data"], alt=image["filename"], className="informe-thumb"),
                dbc.Button(html.I(className="fas fa-xmark"),
                           id={"type": "informe-image-remove", "id": image["id"]},
                           n_clicks=0, color="light", size="sm", className="informe-thumb-remove",
                           title=t("informe_falla.remove_image")),
            ], className="position-relative"),
            dbc.CardBody([
                html.Div(image["filename"], className="small fw-bold text-truncate", title=image["filename"]),
                html.Div(format_size(image["size"]), className="text-muted small mb-2"),
                dbc.Input(id={"type": "informe-image-caption", "id": image["id"]}, value=image.get("caption", ""),
                          placeholder=t("informe_falla.caption_placeholder"), size="sm", maxLength=200),
            ], className="p-2"),
        ], className="h-100 shadow-sm"), xs=12, sm=6, lg=4, xl=2)
        for image in images
    ], className="g-3")


VERDICT_COLORS = {"SEÑAL CLARA": "danger", "SEÑAL DÉBIL": "warning", "SIN SEÑAL ANÓMALA": "success",
                  "DATOS INSUFICIENTES": "secondary"}


def _result_card(body, color: str = "primary") -> dbc.Card:
    return dbc.Card([
        dbc.CardHeader(
            html.H5([html.I(className="fas fa-clipboard-check me-2"), t("informe_falla.result_title")], className="mb-0"),
            className=f"bg-{color} text-white",
        ),
        dbc.CardBody(body),
    ], className="shadow-sm mb-4")


def build_running(unit: str, event_date: str):
    return _result_card(html.Div([
        dbc.Spinner(size="sm", color="primary", spinner_class_name="me-3"),
        html.Div([
            html.Div(t("informe_falla.running", unit=unit, date=event_date), className="fw-bold"),
            html.Small(t("informe_falla.running_hint"), className="text-muted"),
        ]),
    ], className="d-flex align-items-center"))


def _fecha(iso: Optional[str]) -> str:
    return date.fromisoformat(iso[:10]).strftime("%d/%m/%Y") if iso else "—"


def availability_messages(result: dict) -> list:
    """Frases del validador: si alcanza o no, con las cifras de la ventana y el rango de datos de la unidad."""
    if result.get("motivo") not in (None, service.ERROR_INSUFFICIENT):
        return [t_or(f"informe_falla.error.{result.get('motivo')}", t("informe_falla.generation_error"))]
    estado = "ok" if result["ok"] else "insufficient"
    if result["base"] == "diario":
        frase = t(f"informe_falla.data_{estado}_days", unit=result["unidad"], days=result["dias_con_dato"],
                  window=result["dias_ventana"], weeks=result["dias_ventana"] // 7, min=result["min_dias"])
    else:
        frase = t(f"informe_falla.data_{estado}_weeks", unit=result["unidad"], weeks=result["semanas_validas"],
                  window=result["semanas_ventana"], min=result["min_semanas"])
    mensajes = [frase]
    if result.get("datos_desde"):
        mensajes.append(t("informe_falla.data_range", start=_fecha(result["datos_desde"]), end=_fecha(result["datos_hasta"])))
    mantencion = maintenance_message(result.get("mantenciones"))
    if mantencion:
        mensajes.append(mantencion)
    return mensajes


def maintenance_message(cobertura: Optional[dict]) -> Optional[str]:
    """Cobertura de los registros de mantencion: solo informa, no bloquea el informe."""
    estado = (cobertura or {}).get("estado")
    if not estado or estado == "sin_fuente":
        return None
    fechas = {"start": _fecha(cobertura.get("datos_desde")), "end": _fecha(cobertura.get("datos_hasta"))}
    return t_or(f"informe_falla.maint_{estado}", "").format(**fechas) or None


def build_availability(result: dict) -> dbc.Alert:
    mensajes = availability_messages(result)
    return dbc.Alert([
        html.Div([html.I(className=f"fas {'fa-circle-check' if result['ok'] else 'fa-ban'} me-2"), mensajes[0]],
                 className="fw-bold" if not result["ok"] else None),
        *[html.Div(m, className="small mt-1") for m in mensajes[1:]],
    ], color="success" if result["ok"] else "danger", className="mb-0 py-2")


def build_error(reason: Optional[str], details: Optional[dict] = None):
    if reason == service.ERROR_INSUFFICIENT and details:
        cuerpo = [html.Div(m, className="mb-1") for m in availability_messages(details)]
    else:
        cuerpo = [t_or(f"informe_falla.error.{reason}", t("informe_falla.generation_error"))]
    return _result_card(dbc.Alert([
        html.I(className="fas fa-triangle-exclamation me-2"), *cuerpo,
    ], color="danger", className="mb-0"), color="danger")


def build_ready(client: str, job: dict):
    """Veredicto, avisos de los controles y el PDF embebido."""
    href = informe_file_href(client, job["report_id"])
    problems = job.get("problems") or []
    return _result_card([
        html.Div([
            html.Div([
                html.Span(job["unit"], className="fw-bold fs-5 me-2"),
                html.Span(f"· {job['event_date']}", className="text-muted me-3"),
                dbc.Badge(job.get("verdict") or "—", color=VERDICT_COLORS.get(job.get("verdict"), "secondary"),
                          className="me-2"),
                dbc.Badge(t("informe_falla.confidence", value=job.get("confidence") or "—"), color="light",
                          text_color="dark", className="border"),
            ], className="d-flex flex-wrap align-items-center gap-1"),
            html.Div([
                html.A([html.I(className="fas fa-up-right-from-square me-1"), t("reporting.open_new_tab")],
                       href=href, target="_blank", rel="noopener noreferrer",
                       className="btn btn-outline-secondary btn-sm"),
                html.A([html.I(className="fas fa-download me-1"), t("reporting.download")],
                       href=informe_file_href(client, job["report_id"], download=True), className="btn btn-primary btn-sm"),
            ], className="ms-auto d-flex gap-2"),
        ], className="d-flex flex-wrap align-items-center gap-3 mb-3"),
        dbc.Alert([
            html.Div([html.I(className="fas fa-triangle-exclamation me-2"), t("informe_falla.review_before_sending")],
                     className="fw-bold mb-1"),
            html.Ul([html.Li(p) for p in problems], className="mb-0 small"),
        ], color="warning", className="mb-3") if problems else None,
        html.Iframe(src=href + "#view=FitH", className="informe-preview"),
    ])


def build_history(client: str, reports: List[dict]):
    if not reports:
        return html.P(t("informe_falla.history_empty"), className="text-muted mb-0")
    header = html.Thead(html.Tr([html.Th(label) for label in (
        t("informe_falla.col_created"), t("reporting.filter_unit"), t("informe_falla.event_date"), t("informe_falla.field_title"),
        t("informe_falla.col_verdict"), "")]))
    rows = [html.Tr([
        html.Td((r.get("created_at") or "")[:16].replace("T", " ")),
        html.Td(html.Strong(r.get("unit"))),
        html.Td(r.get("event_date")),
        html.Td(r.get("title") or "—", className="text-truncate", style={"maxWidth": "260px"}),
        html.Td(dbc.Badge(r.get("verdict") or "—", color=VERDICT_COLORS.get(r.get("verdict"), "secondary"))),
        html.Td(html.Div([
            html.A(html.I(className="fas fa-eye"), href=informe_file_href(client, r["report_id"]), target="_blank",
                   rel="noopener noreferrer", className="btn btn-sm btn-outline-primary py-0 px-2",
                   title=t("reporting.preview")),
            html.A(html.I(className="fas fa-download"), href=informe_file_href(client, r["report_id"], download=True),
                   className="btn btn-sm btn-outline-secondary py-0 px-2", title=t("reporting.download")),
        ], className="d-flex gap-1 justify-content-end")),
    ]) for r in reports]
    return dbc.Table([header, html.Tbody(rows)], hover=True, responsive=True, size="sm", className="mb-0")


def _active_client(selected_client, user_data) -> str:
    user_clients = (user_data or {}).get("clients", [])
    return normalize_client_id(selected_client or (user_clients[0] if user_clients else ""))


def register_informe_falla_callbacks(app: dash.Dash) -> None:
    """Unidades por cliente, galeria de imagenes, generacion y limpieza del formulario."""

    @app.callback(
        Output("informe-unit", "options"),
        Output("informe-unit", "value"),
        Output("informe-status", "children"),
        Output("informe-body", "style"),
        Input("client-selector", "value"),
        State("user-info-store", "data"),
    )
    def load_informe_falla_units(selected_client, user_data):
        if not user_data:
            raise PreventUpdate
        user_clients = user_data.get("clients", [])
        client = selected_client or (user_clients[0] if user_clients else "")
        units, notice = load_units(client, user_clients)
        return [{"label": u, "value": u} for u in units], None, notice, {} if units else {"display": "none"}

    @app.callback(
        Output("informe-generate", "disabled"),
        Output("informe-unit-feedback", "children"),
        Input("informe-unit", "value"),
        Input("informe-event-date", "date"),
        Input("informe-job-poll", "disabled"),
        Input("informe-data-ok", "data"),
    )
    def toggle_informe_falla_generate(unit, event_date, poll_disabled, data_ok):
        # Un informe a la vez por vista: el boton vuelve cuando termina el que esta en curso.
        # Sin datos suficientes (validador) no se puede generar.
        return not (unit and event_date and poll_disabled and data_ok), None

    @app.callback(
        Output("informe-availability", "children"),
        Output("informe-data-ok", "data"),
        Input("informe-unit", "value"),
        Input("informe-event-date", "date"),
        State("client-selector", "value"),
        State("user-info-store", "data"),
    )
    def check_informe_falla_data(unit, event_date, selected_client, user_data):
        if not unit or not event_date or not user_data:
            return None, False
        client = _active_client(selected_client, user_data)
        if client not in {normalize_client_id(c) for c in user_data.get("clients", [])}:
            return None, False
        if date.fromisoformat(event_date[:10]) > date.today():
            return dbc.Alert(t("informe_falla.future_date"), color="danger", className="mb-0 py-2"), False
        result = service.validar_disponibilidad(client, unit, event_date[:10])
        return build_availability(result), result["ok"]

    @app.callback(
        Output("informe-images-store", "data"),
        Output("informe-upload", "contents"),
        Output("informe-images-feedback", "children"),
        Input("informe-upload", "contents"),
        Input({"type": "informe-image-remove", "id": ALL}, "n_clicks"),
        State("informe-upload", "filename"),
        State("informe-images-store", "data"),
        State({"type": "informe-image-caption", "id": ALL}, "id"),
        State({"type": "informe-image-caption", "id": ALL}, "value"),
        prevent_initial_call=True,
    )
    def update_informe_falla_images(contents, _removes, filenames, images, caption_ids, captions):
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
        Output("informe-gallery", "children"),
        Output("informe-images-count", "children"),
        Input("informe-images-store", "data"),
    )
    def render_informe_falla_gallery(images):
        images = images or []
        return build_gallery(images), t("informe_falla.images_count", count=len(images), max_images=INFORME_MAX_IMAGES)

    @app.callback(
        Output("informe-result", "children"),
        Output("informe-unit-feedback", "children", allow_duplicate=True),
        Output("informe-job-id", "data"),
        Output("informe-job-poll", "disabled"),
        Input("informe-generate", "n_clicks"),
        State("client-selector", "value"),
        State("user-info-store", "data"),
        State("informe-unit", "value"),
        State("informe-system", "value"),
        State("informe-event-date", "date"),
        State("informe-title", "value"),
        State("informe-description", "value"),
        State("informe-findings", "value"),
        State("informe-actions", "value"),
        State("informe-images-store", "data"),
        State({"type": "informe-image-caption", "id": ALL}, "id"),
        State({"type": "informe-image-caption", "id": ALL}, "value"),
        prevent_initial_call=True,
    )
    def generate_informe_falla_request(n_clicks, selected_client, user_data, unit, system, event_date,
                            title, description, findings, actions, images, caption_ids, captions):
        if not n_clicks or not user_data:
            raise PreventUpdate
        if not unit or not event_date:
            return no_update, t("informe_falla.unit_required"), no_update, no_update
        if date.fromisoformat(event_date[:10]) > date.today():
            return no_update, t("informe_falla.future_date"), no_update, no_update
        client = _active_client(selected_client, user_data)
        # Se repite la autorizacion: la unidad viene del navegador.
        units, notice = load_units(client, user_data.get("clients", []))
        if notice is not None or unit not in units:
            return notice or _notice(t("reporting.no_access")), None, None, True

        system = system or COMPONENTE
        request = build_informe_request(
            client, unit, system, event_date[:10],
            {"title": title, "description": description, "findings": findings, "actions": actions},
            with_captions(images, caption_ids, captions),
            user_data.get("username"),
        )
        job_id = service.iniciar(request, sistema_label=system_label(system))
        return build_running(unit, event_date[:10]), None, job_id, False

    @app.callback(
        Output("informe-result", "children", allow_duplicate=True),
        Output("informe-job-poll", "disabled", allow_duplicate=True),
        Output("informe-history-version", "data"),
        Input("informe-job-poll", "n_intervals"),
        State("informe-job-id", "data"),
        State("informe-history-version", "data"),
        State("user-info-store", "data"),
        prevent_initial_call=True,
    )
    def poll_informe_falla_job(_n, job_id, history_version, user_data):
        job = service.estado(job_id)
        user_clients = {normalize_client_id(c) for c in (user_data or {}).get("clients", [])}
        if job is None or job["client"] not in user_clients:
            return build_error(service.ERROR_UNEXPECTED), True, no_update
        if job["status"] == service.STATUS_RUNNING:
            raise PreventUpdate
        if job["status"] == service.STATUS_ERROR:
            return build_error(job.get("reason"), job.get("details")), True, no_update
        return build_ready(job["client"], job), True, (history_version or 0) + 1

    @app.callback(
        Output("informe-history", "children"),
        Input("client-selector", "value"),
        Input("informe-history-version", "data"),
        State("user-info-store", "data"),
    )
    def render_informe_falla_history(selected_client, _version, user_data):
        if not user_data:
            raise PreventUpdate
        client = _active_client(selected_client, user_data)
        if client not in {normalize_client_id(c) for c in user_data.get("clients", [])}:
            return None
        return build_history(client, service.listar_informes(client))

    @app.callback(
        Output("informe-unit", "value", allow_duplicate=True),
        Output("informe-system", "value"),
        Output("informe-event-date", "date"),
        Output("informe-title", "value"),
        Output("informe-description", "value"),
        Output("informe-findings", "value"),
        Output("informe-actions", "value"),
        Output("informe-images-store", "data", allow_duplicate=True),
        Output("informe-images-feedback", "children", allow_duplicate=True),
        Output("informe-result", "children", allow_duplicate=True),
        Input("informe-clear", "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_informe_falla_form(n_clicks):
        if not n_clicks:
            raise PreventUpdate
        return None, COMPONENTE, None, "", "", "", "", [], None, None
