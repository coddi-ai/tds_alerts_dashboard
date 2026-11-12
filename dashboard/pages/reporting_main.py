"""
Reportes > Reportabilidad: navegador de los reportes generados que viven en S3.

Dos pestañas: *Estado actual* (unidades de una fecha de generacion, por estado combinado;
al abrir una se muestra el informe de unidad en vista dividida, dentro de la misma
pagina) e *Historial* (todos los reportes, con filtros, orden y paginacion).

El contenido depende del cliente global (client-selector), asi que la pagina solo arma
el esqueleto; dashboard/callbacks/reporting_callbacks.py lo rellena y
dashboard/components/reporting_views.py dibuja las piezas. Los PDFs se abren por la
ruta Flask de dashboard/report_files.py, nunca directo desde S3. Estilos en
assets/reporting.css; las acciones de los elementos redibujados, en
assets/reporting_actions.js.
"""

from src.i18n import t, page_title
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard.callbacks.reporting_callbacks import DEFAULT_HISTORY_STATE
from dashboard.components.reporting_views import viewer_shell
from src.data.report_view import ALL


def _select(id_: str, label: str) -> html.Div:
    """Select nativo con su etiqueta visible; las opciones las pone el callback del catalogo."""
    return html.Div([
        html.Label(label, htmlFor=id_, className="rp-field__label"),
        dbc.Select(id=id_, options=[], value=None, className="rp-select"),
    ], className="rp-field")


def _button(id_: str, label: str, icon: str) -> html.Button:
    return html.Button([html.I(className=f"fas {icon}", **{"aria-hidden": "true"}), label],
                       id=id_, type="button", n_clicks=0, className="rp-btn")


def _tabs() -> html.Div:
    def tab(key: str, label: str, on: bool) -> html.Button:
        return html.Button(
            label, id=f"reporting-tab-{key}", type="button", role="tab", n_clicks=0,
            className="rp-tab" + (" rp-tab--on" if on else ""),
            **{"aria-selected": "true" if on else "false", "aria-controls": f"reporting-panel-{key}"},
        )

    return html.Div([
        tab("current", t("reporting.tab_current"), True),
        tab("history", t("reporting.tab_history"), False),
    ], className="rp-tabs", role="tablist", **{"aria-label": t("reporting.tabs_aria")})


def _current_panel() -> html.Div:
    # Filtros y secciones son la vista completa: se ocultan juntos mientras hay un informe abierto.
    return html.Div([
        html.Div([
            html.Div([
                html.Div([
                    _select("reporting-cur-technique", t("reporting.filter_technique")),
                    _select("reporting-cur-system", t("alerts_general.filter_system")),
                    _select("reporting-cur-date", t("reporting.batch_label")),
                ], className="rp-toolbar-fields"),
                _button("reporting-cur-refresh", t("reporting.refresh"), "fa-sync-alt"),
            ], className="rp-filterbar"),
            html.Div(id="reporting-state-filters"),
            dcc.Loading(html.Div(id="reporting-sections"), type="circle"),
        ], id="reporting-overview"),
        html.Div(viewer_shell(), id="reporting-viewer", hidden=True),
    ], id="reporting-panel-current", role="tabpanel", **{"aria-labelledby": "reporting-tab-current"})


def _history_panel() -> html.Div:
    return html.Div([
        html.Div([
            html.Div([
                _select("reporting-his-technique", t("reporting.filter_technique")),
                _select("reporting-his-system", t("alerts_general.filter_system")),
                _select("reporting-his-unit", t("reporting.filter_unit")),
                _select("reporting-his-date", t("reporting.filter_date")),
                _select("reporting-his-state", t("reporting.col_health")),
            ], className="rp-toolbar-fields"),
            _button("reporting-his-clear", t("reporting.clear_filters"), "fa-filter-circle-xmark"),
        ], className="rp-filterbar"),
        html.Div([
            html.Span(id="reporting-history-count", className="rp-count", **{"aria-live": "polite"}),
            _button("reporting-his-refresh", t("reporting.refresh"), "fa-sync-alt"),
        ], className="rp-countbar"),
        html.Div(id="reporting-history-table"),
        html.Div(id="reporting-history-pager"),
    ], id="reporting-panel-history", role="tabpanel", hidden=True,
        **{"aria-labelledby": "reporting-tab-history"})


def layout(report=None, **kwargs):
    """`?report=<clave>` abre ese informe (enlaces de tarjetas y fichas); se valida contra el catalogo."""
    initial_view = {"tab": "current", "key": report if isinstance(report, str) else None, "list_date": None}
    return html.Div([
        html.Div([
            html.Div([
                html.H3([
                    html.I(className="fas fa-file-alt me-2"),
                    t("nav.service.reporting-main"),
                ], className="text-primary mb-2"),
                html.P(t("reporting.subtitle"), className="text-muted"),
            ]),
            # "Fuentes de Datos" button + popover (dashboard/callbacks/data_sources_callbacks.py).
            html.Div(id="reporting-source-status", className="ds-header-slot"),
        ], className="mb-3 d-flex flex-wrap justify-content-between align-items-start gap-3"),

        dcc.Store(id="reporting-catalog-store"),
        dcc.Store(id="reporting-action"),
        dcc.Store(id="reporting-view-store", data=initial_view),
        dcc.Store(id="reporting-state-filter", data=ALL),
        dcc.Store(id="reporting-history-state", data=DEFAULT_HISTORY_STATE),
        html.Div(id="reporting-status"),
        # Oculto mientras no haya catalogo (cliente sin acceso, sin reportes o S3 caido).
        html.Div([_tabs(), _current_panel(), _history_panel()], id="reporting-body"),
    ], className="container-fluid p-4 rp-page")


dash.register_page(__name__, path="/reporting", title=page_title("page.title.reporting_main"), layout=layout)
