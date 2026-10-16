"""
Reportes > Informe preliminar de falla: formulario para pedir el informe de una detencion.

La unidad depende del cliente global (client-selector), asi que la pagina solo arma
el esqueleto; dashboard/callbacks/informe_falla_callbacks.py lo rellena y arma la solicitud
(src/data/informe_falla_request.py); src/informe_falla genera el PDF en segundo plano y la vista lo muestra.
"""

from datetime import date

from src.i18n import t, page_title
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html

from src.data.erp_schemas import SYSTEM_LABELS, System
from src.data.informe_falla_request import INFORME_MAX_IMAGE_BYTES, INFORME_MAX_IMAGES
from src.informe_falla.service import SISTEMAS_SOPORTADOS

# Mientras corre un informe, la vista consulta su estado cada tanto.
POLL_INTERVAL_MS = 2000

TEXTAREA_STYLE = {"fontSize": "14px", "minHeight": "110px"}


def _label(icon, text, required=False):
    return html.Label([
        html.I(className=f"fas {icon} me-1"), f" {text}",
        html.Span(" *", className="text-danger") if required else None,
    ], className="fw-bold mb-2")


def _textarea(id_, icon, label, placeholder, md=12):
    return dbc.Col([
        _label(icon, label),
        dbc.Textarea(id=id_, placeholder=placeholder, rows=4, style=TEXTAREA_STYLE),
    ], md=md)


def _scope_card() -> dbc.Card:
    """Unidad y fecha de la detencion (obligatorias) y sistema (por ahora solo motor)."""
    return dbc.Card([
        dbc.CardHeader(
            html.H5([html.I(className="fas fa-crosshairs me-2"), t("informe_falla.scope_title")], className="mb-0"),
            className="bg-primary text-white",
        ),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    _label("fa-truck", t("reporting.filter_unit"), required=True),
                    dcc.Dropdown(id="informe-unit", options=[], placeholder=t("informe_falla.unit_placeholder")),
                    html.Div(id="informe-unit-feedback", className="text-danger small mt-1"),
                ], md=4),
                dbc.Col([
                    _label("fa-cogs", t("alerts_general.filter_system")),
                    dcc.Dropdown(
                        id="informe-system",
                        options=_system_options(),
                        value=SISTEMAS_SOPORTADOS[0],
                        clearable=False,
                    ),
                ], md=4),
                dbc.Col([
                    _label("fa-calendar-alt", t("informe_falla.event_date"), required=True),
                    dcc.DatePickerSingle(
                        id="informe-event-date",
                        placeholder=t("informe_falla.event_date_placeholder"),
                        display_format="DD/MM/YYYY",
                        max_date_allowed=date.today(),
                        clearable=True,
                        className="w-100",
                    ),
                ], md=4),
            ], className="g-3"),
            # Validador de datos (src/informe_falla/service.validar_disponibilidad), al elegir unidad y fecha.
            dcc.Loading(html.Div(id="informe-availability", className="mt-3"), type="dot"),
            html.P([html.Span("* ", className="text-danger"), t("informe_falla.required_hint")],
                   className="text-muted small mb-0 mt-3"),
        ]),
    ], className="shadow-sm mb-4")


def _system_options() -> list:
    """Los sistemas que el informe aun no analiza se muestran, deshabilitados."""
    return [{"label": SYSTEM_LABELS[s] if s.value in SISTEMAS_SOPORTADOS
             else f"{SYSTEM_LABELS[s]} ({t('informe_falla.coming_soon')})",
             "value": s.value, "disabled": s.value not in SISTEMAS_SOPORTADOS} for s in System]


def _context_card() -> dbc.Card:
    """Campos de texto libre que el generador incorpora al informe."""
    return dbc.Card([
        dbc.CardHeader(
            html.H5([html.I(className="fas fa-pen-to-square me-2"), t("informe_falla.context_title")], className="mb-0"),
            className="bg-light",
        ),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    _label("fa-heading", t("informe_falla.field_title")),
                    dbc.Input(id="informe-title", placeholder=t("informe_falla.field_title_placeholder"), maxLength=150),
                ], md=12),
                _textarea("informe-description", "fa-triangle-exclamation", t("informe_falla.field_description"),
                          t("informe_falla.field_description_placeholder")),
                _textarea("informe-findings", "fa-magnifying-glass", t("informe_falla.field_findings"),
                          t("informe_falla.field_findings_placeholder"), md=6),
                _textarea("informe-actions", "fa-wrench", t("informe_falla.field_actions"),
                          t("informe_falla.field_actions_placeholder"), md=6),
            ], className="g-3"),
        ]),
    ], className="shadow-sm mb-4")


def _images_card() -> dbc.Card:
    """Zona para soltar imagenes y la galeria con una descripcion por imagen."""
    return dbc.Card([
        dbc.CardHeader(
            html.Div([
                html.H5([html.I(className="fas fa-images me-2"), t("informe_falla.images_title")], className="mb-0"),
                html.Span(id="informe-images-count", className="text-muted small"),
            ], className="d-flex justify-content-between align-items-center"),
            className="bg-light",
        ),
        dbc.CardBody([
            dcc.Upload(
                id="informe-upload",
                children=html.Div([
                    html.I(className="fas fa-cloud-arrow-up fa-2x mb-2 text-primary"),
                    html.Div([t("informe_falla.upload_drop"), " ",
                              html.Span(t("informe_falla.upload_browse"), className="text-primary fw-bold")]),
                    html.Small(t("informe_falla.upload_hint", max_images=INFORME_MAX_IMAGES,
                                 max_mb=INFORME_MAX_IMAGE_BYTES // (1024 * 1024)), className="text-muted"),
                ]),
                accept="image/png,image/jpeg,image/webp,image/gif",
                multiple=True,
                className="informe-upload",
            ),
            html.Div(id="informe-images-feedback"),
            html.Div(id="informe-gallery", className="informe-gallery mt-3"),
        ]),
    ], className="shadow-sm mb-4")


def _troubleshooting_card() -> dbc.Card:
    """Placeholder: aqui se vinculara una sesion del agente de Troubleshooting."""
    return dbc.Card([
        dbc.CardHeader(
            html.Div([
                html.H5([html.I(className="fas fa-screwdriver-wrench me-2"),
                         t("nav.service.agents-troubleshooting")], className="mb-0"),
                dbc.Badge(t("informe_falla.in_development"), color="warning", text_color="dark", className="ms-2"),
            ], className="d-flex align-items-center"),
            className="bg-light",
        ),
        dbc.CardBody([
            html.P(t("informe_falla.troubleshooting_hint"), className="text-muted small mb-3"),
            dbc.Textarea(
                id="informe-troubleshooting",
                placeholder=t("informe_falla.troubleshooting_placeholder"),
                rows=3,
                disabled=True,
                style=TEXTAREA_STYLE,
            ),
        ], className="informe-in-development"),
    ], className="shadow-sm mb-4")


def _actions_bar() -> html.Div:
    return html.Div([
        dbc.Button([html.I(className="fas fa-eraser me-1"), t("informe_falla.clear")],
                   id="informe-clear", color="secondary", outline=True),
        dbc.Button([html.I(className="fas fa-file-circle-plus me-1"), t("informe_falla.generate")],
                   id="informe-generate", color="primary", disabled=True),
    ], className="d-flex justify-content-end gap-2 mb-4")


def _history_card() -> dbc.Card:
    """Informes informe preliminar ya generados para el cliente activo."""
    return dbc.Card([
        dbc.CardHeader(
            html.H5([html.I(className="fas fa-clock-rotate-left me-2"), t("informe_falla.history_title")], className="mb-0"),
            className="bg-light",
        ),
        dbc.CardBody(dcc.Loading(html.Div(id="informe-history"), type="circle")),
    ], className="shadow-sm mb-4")


def layout(**kwargs):
    return html.Div([
        html.Div([
            html.H3([
                html.I(className="fas fa-diagram-project me-2"),
                t("nav.service.reporting-informe-falla"),
            ], className="text-primary mb-2"),
            html.P(t("informe_falla.subtitle"), className="text-muted"),
        ], className="mb-4"),

        # Imagenes cargadas: [{id, filename, mime, size, data, caption}].
        dcc.Store(id="informe-images-store", data=[]),
        # True cuando hay datos suficientes para la unidad y la fecha elegidas.
        dcc.Store(id="informe-data-ok", data=False),
        # Trabajo en curso (src/informe_falla/service.py) y contador para refrescar el historial.
        dcc.Store(id="informe-job-id"),
        dcc.Store(id="informe-history-version", data=0),
        dcc.Interval(id="informe-job-poll", interval=POLL_INTERVAL_MS, disabled=True),
        html.Div(id="informe-status"),
        # Oculto mientras el cliente activo no tenga unidades o acceso.
        html.Div([
            _scope_card(),
            _context_card(),
            _images_card(),
            _troubleshooting_card(),
            _actions_bar(),
            html.Div(id="informe-result"),
            _history_card(),
        ], id="informe-body"),
    ], className="container-fluid p-4")


dash.register_page(__name__, path="/reporting/informe-falla", title=page_title("page.title.reporting_informe_falla"), layout=layout)
