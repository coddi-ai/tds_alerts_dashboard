"""
Reportes > Reportabilidad: navegador de los reportes generados que viven en S3.

El contenido depende del cliente global (client-selector), asi que la pagina solo
arma el esqueleto; dashboard/callbacks/reporting_callbacks.py lo rellena. Los PDFs
se abren por la ruta Flask de dashboard/report_files.py, nunca directo desde S3.
"""

from src.i18n import t, page_title
import dash
import dash_bootstrap_components as dbc
from dash import dash_table, dcc, html

from dashboard.callbacks.reporting_callbacks import health_cell_styles


def _filter(id_, label, icon, md=3, **kwargs):
    return dbc.Col([
        html.Label([html.I(className=f"fas {icon} me-1"), f" {label}"], className="fw-bold mb-2"),
        dcc.Dropdown(id=id_, options=[], **kwargs),
    ], md=md)


def _latest_card() -> dbc.Card:
    """Lote destacado: una fecha de generacion y un boton por unidad."""
    return dbc.Card([
        dbc.CardHeader(
            html.H5([html.I(className="fas fa-clock me-2"), t("reporting.latest_title")], className="mb-0"),
            className="bg-primary text-white",
        ),
        dbc.CardBody([
            html.Div([
                html.Span([html.I(className="fas fa-calendar-alt me-1"), t("reporting.batch_label")],
                          className="fw-bold me-2"),
                dbc.RadioItems(
                    id="reporting-batch-date",
                    options=[],
                    inline=True,
                    className="d-inline-flex flex-wrap gap-1",
                    inputClassName="btn-check",
                    labelClassName="btn btn-outline-primary btn-sm",
                    labelCheckedClassName="active",
                ),
            ], className="d-flex flex-wrap align-items-center mb-3"),
            dcc.Loading(html.Div(id="reporting-latest"), type="circle"),
        ]),
    ], className="shadow-sm mb-4")


def _explorer_card() -> dbc.Card:
    """Filtros por tecnica, sistema, unidad, fecha y estado sobre todo el historial."""
    return dbc.Card([
        dbc.CardHeader(
            html.Div([
                html.H5([html.I(className="fas fa-filter me-2"), t("reporting.explore_title")], className="mb-0"),
                dbc.Button(
                    [html.I(className="fas fa-sync-alt me-1"), t("reporting.refresh")],
                    id="reporting-refresh",
                    color="secondary",
                    outline=True,
                    size="sm",
                ),
            ], className="d-flex justify-content-between align-items-center"),
            className="bg-light",
        ),
        dbc.CardBody([
            dbc.Row([
                _filter("reporting-filter-technique", t("reporting.filter_technique"), "fa-flask", md=2,
                        clearable=False),
                _filter("reporting-filter-system", t("alerts_general.filter_system"), "fa-cogs", md=2,
                        placeholder=t("tab_alerts_detail.todos_los_sistemas")),
                _filter("reporting-filter-unit", t("reporting.filter_unit"), "fa-truck",
                        multi=True, placeholder=t("reporting.all_units")),
                _filter("reporting-filter-date", t("reporting.filter_date"), "fa-calendar-alt", md=2,
                        placeholder=t("reporting.all_dates")),
                _filter("reporting-filter-health", t("reporting.col_health"), "fa-heartbeat",
                        multi=True, placeholder=t("reporting.all_states")),
            ], className="g-3 mb-3"),
            html.Div(id="reporting-count", className="text-muted small mb-2"),
            _reports_table(),
        ]),
    ], className="shadow-sm mb-4")


def _reports_table() -> dash_table.DataTable:
    """Tabla fija en el layout: el clic en una fila abre la previsualizacion."""
    return dash_table.DataTable(
        id="reporting-datatable",
        columns=[
            {"name": t("reporting.col_date"), "id": "date"},
            {"name": t("reporting.filter_unit"), "id": "unit"},
            {"name": t("alerts_general.filter_system"), "id": "system"},
            {"name": t("reporting.col_health"), "id": "health"},
            {"name": t("reporting.preview"), "id": "preview", "presentation": "markdown"},
            {"name": t("reporting.download"), "id": "download", "presentation": "markdown"},
        ],
        data=[],
        # HTML solo para los iconos de Font Awesome; el contenido lo arma el servidor (table_rows).
        markdown_options={"html": True},
        css=[{"selector": ".dash-cell-value p", "rule": "margin: 0"},
             # Las celdas markdown (iconos) no heredan el textAlign de style_cell_conditional.
             {"selector": ".cell-markdown", "rule": "text-align: center"},
             {"selector": "td.dash-cell", "rule": "cursor: pointer"}],
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "left", "padding": "10px", "fontSize": "13px"},
        style_header={
            "backgroundColor": "#17a2b8",
            "color": "white",
            "fontWeight": "bold",
            "textAlign": "center",
        },
        style_cell_conditional=[
            {"if": {"column_id": "unit"}, "fontWeight": "bold"},
        ] + [{"if": {"column_id": c}, "textAlign": "center"} for c in ("health", "preview", "download")],
        style_data_conditional=health_cell_styles() + [
            # La celda activa solo sirve para abrir la previsualizacion; sin resaltado rosa.
            {"if": {"state": "active"}, "backgroundColor": "inherit", "border": "1px solid #dee2e6"},
        ],
        sort_action="native",
        page_size=15,
    )


def _preview_modal() -> dbc.Modal:
    """PDF dentro del dashboard, con saltos a otras fechas y sistemas de la misma unidad."""
    def _pills(id_, icon, label):
        return html.Div([
            html.Span([html.I(className=f"fas {icon} me-1"), label], className="fw-bold me-2 small"),
            dbc.RadioItems(
                id=id_,
                options=[],
                inline=True,
                className="d-inline-flex flex-wrap gap-1",
                inputClassName="btn-check",
                labelClassName="btn btn-outline-primary btn-sm",
                labelCheckedClassName="active",
            ),
        ], className="d-flex flex-wrap align-items-center")

    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle(id="reporting-preview-title", className="d-flex align-items-center")),
        dbc.ModalBody([
            html.Div([
                _pills("reporting-preview-date", "fa-calendar-alt", t("reporting.filter_date")),
                _pills("reporting-preview-system", "fa-cogs", t("alerts_general.filter_system")),
                html.Div([
                    html.A([html.I(className="fas fa-up-right-from-square me-1"), t("reporting.open_new_tab")],
                           id="reporting-preview-open", target="_blank", rel="noopener noreferrer",
                           className="btn btn-outline-secondary btn-sm"),
                    html.A([html.I(className="fas fa-download me-1"), t("reporting.download")],
                           id="reporting-preview-download", className="btn btn-primary btn-sm"),
                ], className="ms-auto d-flex gap-2"),
            ], className="d-flex flex-wrap align-items-center gap-3 mb-3"),
            html.Iframe(
                id="reporting-preview-frame",
                style={"width": "100%", "height": "75vh", "border": "1px solid #dee2e6", "borderRadius": "4px"},
            ),
        ]),
    ], id="reporting-preview-modal", size="xl", is_open=False, centered=True)


def layout(**kwargs):
    return html.Div([
        html.Div([
            html.H3([
                html.I(className="fas fa-file-alt me-2"),
                t("nav.service.reporting-main"),
            ], className="text-primary mb-2"),
            html.P(t("reporting.subtitle"), className="text-muted"),
        ], className="mb-4"),

        dcc.Store(id="reporting-catalog-store"),
        dcc.Store(id="reporting-preview-key"),
        html.Div(id="reporting-status"),
        # Oculto mientras no haya catalogo (cliente sin acceso, sin reportes o S3 caido).
        html.Div([_latest_card(), _explorer_card()], id="reporting-body"),
        _preview_modal(),
    ], className="container-fluid p-4")


dash.register_page(__name__, path="/reporting", title=page_title("page.title.reporting_main"), layout=layout)
