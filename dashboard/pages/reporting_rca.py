"""
Reportes > Reporte RCA: formulario para pedir un informe de analisis de causa raiz.

La unidad depende del cliente global (client-selector), asi que la pagina solo arma
el esqueleto; dashboard/callbacks/rca_callbacks.py lo rellena y arma la solicitud
(src/data/rca_report.py). El generador del informe aun esta en desarrollo.
"""

from src.i18n import t, page_title
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html

from src.data.erp_schemas import SYSTEM_LABELS, System
from src.data.rca_report import RCA_MAX_IMAGE_BYTES, RCA_MAX_IMAGES

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
    """Unidad (obligatoria), sistema (opcional) y fecha del evento."""
    return dbc.Card([
        dbc.CardHeader(
            html.H5([html.I(className="fas fa-crosshairs me-2"), t("rca.scope_title")], className="mb-0"),
            className="bg-primary text-white",
        ),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    _label("fa-truck", t("reporting.filter_unit"), required=True),
                    dcc.Dropdown(id="rca-unit", options=[], placeholder=t("rca.unit_placeholder")),
                    html.Div(id="rca-unit-feedback", className="text-danger small mt-1"),
                ], md=4),
                dbc.Col([
                    _label("fa-cogs", t("alerts_general.filter_system")),
                    dcc.Dropdown(
                        id="rca-system",
                        options=[{"label": SYSTEM_LABELS[s], "value": s.value} for s in System],
                        placeholder=t("tab_alerts_detail.todos_los_sistemas"),
                    ),
                ], md=4),
                dbc.Col([
                    _label("fa-calendar-alt", t("rca.event_date")),
                    dcc.DatePickerSingle(
                        id="rca-event-date",
                        placeholder=t("rca.event_date_placeholder"),
                        display_format="DD/MM/YYYY",
                        clearable=True,
                        className="w-100",
                    ),
                ], md=4),
            ], className="g-3"),
            html.P([html.Span("* ", className="text-danger"), t("rca.required_hint")],
                   className="text-muted small mb-0 mt-3"),
        ]),
    ], className="shadow-sm mb-4")


def _context_card() -> dbc.Card:
    """Campos de texto libre que el generador incorpora al informe."""
    return dbc.Card([
        dbc.CardHeader(
            html.H5([html.I(className="fas fa-pen-to-square me-2"), t("rca.context_title")], className="mb-0"),
            className="bg-light",
        ),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    _label("fa-heading", t("rca.field_title")),
                    dbc.Input(id="rca-title", placeholder=t("rca.field_title_placeholder"), maxLength=150),
                ], md=12),
                _textarea("rca-description", "fa-triangle-exclamation", t("rca.field_description"),
                          t("rca.field_description_placeholder")),
                _textarea("rca-findings", "fa-magnifying-glass", t("rca.field_findings"),
                          t("rca.field_findings_placeholder"), md=6),
                _textarea("rca-actions", "fa-wrench", t("rca.field_actions"),
                          t("rca.field_actions_placeholder"), md=6),
            ], className="g-3"),
        ]),
    ], className="shadow-sm mb-4")


def _images_card() -> dbc.Card:
    """Zona para soltar imagenes y la galeria con una descripcion por imagen."""
    return dbc.Card([
        dbc.CardHeader(
            html.Div([
                html.H5([html.I(className="fas fa-images me-2"), t("rca.images_title")], className="mb-0"),
                html.Span(id="rca-images-count", className="text-muted small"),
            ], className="d-flex justify-content-between align-items-center"),
            className="bg-light",
        ),
        dbc.CardBody([
            dcc.Upload(
                id="rca-upload",
                children=html.Div([
                    html.I(className="fas fa-cloud-arrow-up fa-2x mb-2 text-primary"),
                    html.Div([t("rca.upload_drop"), " ",
                              html.Span(t("rca.upload_browse"), className="text-primary fw-bold")]),
                    html.Small(t("rca.upload_hint", max_images=RCA_MAX_IMAGES,
                                 max_mb=RCA_MAX_IMAGE_BYTES // (1024 * 1024)), className="text-muted"),
                ]),
                accept="image/png,image/jpeg,image/webp,image/gif",
                multiple=True,
                className="rca-upload",
            ),
            html.Div(id="rca-images-feedback"),
            html.Div(id="rca-gallery", className="rca-gallery mt-3"),
        ]),
    ], className="shadow-sm mb-4")


def _troubleshooting_card() -> dbc.Card:
    """Placeholder: aqui se vinculara una sesion del agente de Troubleshooting."""
    return dbc.Card([
        dbc.CardHeader(
            html.Div([
                html.H5([html.I(className="fas fa-screwdriver-wrench me-2"),
                         t("nav.service.agents-troubleshooting")], className="mb-0"),
                dbc.Badge(t("rca.in_development"), color="warning", text_color="dark", className="ms-2"),
            ], className="d-flex align-items-center"),
            className="bg-light",
        ),
        dbc.CardBody([
            html.P(t("rca.troubleshooting_hint"), className="text-muted small mb-3"),
            dbc.Textarea(
                id="rca-troubleshooting",
                placeholder=t("rca.troubleshooting_placeholder"),
                rows=3,
                disabled=True,
                style=TEXTAREA_STYLE,
            ),
        ], className="rca-in-development"),
    ], className="shadow-sm mb-4")


def _actions_bar() -> html.Div:
    return html.Div([
        dbc.Button([html.I(className="fas fa-eraser me-1"), t("rca.clear")],
                   id="rca-clear", color="secondary", outline=True),
        dbc.Button([html.I(className="fas fa-file-circle-plus me-1"), t("rca.generate")],
                   id="rca-generate", color="primary", disabled=True),
    ], className="d-flex justify-content-end gap-2 mb-4")


def layout(**kwargs):
    return html.Div([
        html.Div([
            html.H3([
                html.I(className="fas fa-diagram-project me-2"),
                t("nav.service.reporting-rca"),
            ], className="text-primary mb-2"),
            html.P(t("rca.subtitle"), className="text-muted"),
        ], className="mb-4"),

        # Imagenes cargadas: [{id, filename, mime, size, data, caption}].
        dcc.Store(id="rca-images-store", data=[]),
        html.Div(id="rca-status"),
        # Oculto mientras el cliente activo no tenga unidades o acceso.
        html.Div([
            _scope_card(),
            _context_card(),
            _images_card(),
            _troubleshooting_card(),
            _actions_bar(),
            dcc.Loading(html.Div(id="rca-result"), type="circle"),
        ], id="rca-body"),
    ], className="container-fluid p-4")


dash.register_page(__name__, path="/reporting/rca", title=page_title("page.title.reporting_rca"), layout=layout)
