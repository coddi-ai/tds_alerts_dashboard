"""Friendly two-level EMIN historical fleet review page."""

from dash import dcc, html
import dash_bootstrap_components as dbc

from dashboard.components.emin_historical import section_header
from src.i18n import t


def create_layout() -> html.Div:
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H2(
                                [html.I(className="fas fa-history me-3"), t("emin_history.title")],
                                className="text-primary mb-1",
                            ),
                            html.P(t("emin_history.subtitle"), className="text-muted mb-2"),
                            html.Div(id="emin-history-meta", className="overview-meta"),
                        ],
                        xs=12,
                    )
                ],
                className="mb-3",
            ),
            html.Div([
                html.Label(t("emin_history.filter_day"), htmlFor="emin-history-cutoff", className="fleet-search__label"),
                dcc.Dropdown(id="emin-history-cutoff", clearable=False, searchable=True),
            ], className="fleet-search"),
            dcc.Tabs(
                id="emin-history-view-tabs",
                value="fleet",
                children=[
                    dcc.Tab(
                        label=t("emin_history.tab_fleet"),
                        value="fleet",
                        className="custom-tab pred-tab",
                        selected_className="custom-tab--selected pred-tab--selected",
                    ),
                    dcc.Tab(
                        label=t("emin_history.tab_unit"),
                        value="unit",
                        className="custom-tab pred-tab",
                        selected_className="custom-tab--selected pred-tab--selected",
                    ),
                ],
                className="mb-3",
            ),
            dcc.Store(id="emin-history-package"),
            html.Div(
                [
                    dcc.Loading(html.Div(id="emin-history-highlights"), type="circle"),
                    dbc.Card(
                        [
                            section_header(t("emin_history.ranking_title"), "fas fa-list-ol"),
                            dbc.CardBody([
                                dbc.Row([
                                    dbc.Col([
                                        html.Label(t("emin_history.search_unit"), htmlFor="emin-history-search", className="fleet-search__label"),
                                        dcc.Input(
                                            id="emin-history-search", type="search", value="", debounce=0.4, autoComplete="off",
                                            placeholder=t("tab_overview_general.buscar_unidad_placeholder"),
                                            className="form-control form-control-sm",
                                        ),
                                    ], xs=12, md=4),
                                    dbc.Col([
                                        html.Label(t("emin_history.filter_group"), htmlFor="emin-history-group", className="fleet-search__label"),
                                        dcc.Dropdown(id="emin-history-group", clearable=False, searchable=True),
                                    ], xs=12, md=4),
                                    dbc.Col([
                                        html.Label(t("emin_history.col_movement"), htmlFor="emin-history-movement-filter", className="fleet-search__label"),
                                        dbc.Select(
                                            id="emin-history-movement-filter", size="sm",
                                            value="__all__",
                                            options=[
                                                {"label": t("emin_history.all_movements"), "value": "__all__"},
                                                *[
                                                    {"label": t(f"emin_history.movement_{state}"), "value": state}
                                                    for state in ("improved", "worsened", "stable", "insufficient")
                                                ],
                                            ],
                                        ),
                                    ], xs=12, md=4),
                                ], class_name="g-2 mb-3"),
                                dcc.Loading(html.Div(id="emin-history-ranking"), type="circle"),
                            ]),
                        ],
                        class_name="emin-history-card mb-3",
                    ),
                    dcc.Loading(html.Div(id="emin-history-kpis"), type="circle"),
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Card(
                                    dbc.CardBody(
                                        dcc.Graph(
                                            id="emin-history-movement",
                                            config={"displayModeBar": False},
                                            responsive=True,
                                            style={"height": "320px", "width": "100%"},
                                        )
                                    ),
                                    class_name="emin-history-card h-100",
                                ),
                                xs=12,
                                xl=5,
                                class_name="mb-3",
                            ),
                            dbc.Col(
                                dbc.Card(
                                    dbc.CardBody(
                                        dcc.Graph(
                                            id="emin-history-groups",
                                            config={"displayModeBar": False},
                                            responsive=True,
                                            style={"height": "320px", "width": "100%"},
                                        )
                                    ),
                                    class_name="emin-history-card h-100",
                                ),
                                xs=12,
                                xl=7,
                                class_name="mb-3",
                            ),
                        ],
                        className="g-3",
                    ),
                    dbc.Alert(
                        [html.I(className="fas fa-info-circle me-2"), t("emin_history.fleet_note")],
                        color="light",
                        class_name="emin-history-method-note",
                    ),
                ],
                id="emin-history-overview-panel",
                className="emin-history-view-panel",
            ),
            html.Div(
                [
                    html.Div([
                        html.Button(
                            t("emin_history.back_to_fleet"), type="button",
                            className="btn btn-sm btn-outline-primary emin-history-action",
                            **{"data-emin-back": "true"},
                        ),
                        html.H3(t("emin_history.tab_unit"), id="emin-history-detail-heading", tabIndex=-1, className="h5 mb-0"),
                    ], className="d-flex flex-wrap align-items-center gap-2 mb-3"),
                    html.Div([
                        html.Label(t("emin_history.filter_unit"), htmlFor="emin-history-unit", className="fleet-search__label"),
                        dcc.Dropdown(id="emin-history-unit", clearable=False, searchable=True),
                    ], className="fleet-search"),
                    dcc.Loading(html.Div(id="emin-history-status"), type="circle"),
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Card([
                                    section_header(t("emin_history.trend_section"), "fas fa-chart-line"),
                                    dbc.CardBody(
                                        dcc.Graph(
                                            id="emin-history-trend",
                                            config={"displayModeBar": False},
                                            responsive=True,
                                            style={"height": "350px", "width": "100%"},
                                        )
                                    ),
                                ], class_name="shadow-sm unit-card",
                                ),
                                xs=12,
                                className="mb-3",
                            ),
                        ],
                        className="g-3",
                    ),
                    dcc.Loading(html.Div(id="emin-history-evidence"), type="circle"),
                    dbc.Alert(
                        [html.I(className="fas fa-info-circle me-2"), t("emin_history.detail_note")],
                        color="light",
                        class_name="emin-history-method-note",
                    ),
                ],
                id="emin-history-detail-panel",
                className="emin-history-view-panel",
                style={"display": "none"},
            ),
        ],
        className="container-fluid p-4 emin-history-page",
    )
