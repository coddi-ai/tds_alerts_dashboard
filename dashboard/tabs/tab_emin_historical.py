"""Friendly two-level EMIN historical fleet review page."""

from dash import dcc, html
import dash_bootstrap_components as dbc

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
                            html.Div(id="emin-history-meta", className="emin-history-meta"),
                        ],
                        xs=12,
                    )
                ],
                className="mb-3",
            ),
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
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.Div(t("emin_history.fleet_filters_title"), className="emin-history-filter-title"),
                                dbc.Row(
                                    [
                                        dbc.Col(
                                            [
                                                dbc.Label(t("emin_history.filter_day"), html_for="emin-history-cutoff"),
                                                dcc.Dropdown(id="emin-history-cutoff", clearable=False, searchable=True),
                                            ],
                                            xs=12,
                                            md=6,
                                        ),
                                        dbc.Col(
                                            [
                                                dbc.Label(t("emin_history.filter_group"), html_for="emin-history-group"),
                                                dcc.Dropdown(id="emin-history-group", clearable=False, searchable=True),
                                            ],
                                            xs=12,
                                            md=6,
                                        ),
                                    ],
                                    className="g-3",
                                ),
                            ]
                        ),
                        class_name="emin-history-card mb-3",
                    ),
                    dcc.Loading(html.Div(id="emin-history-highlights"), type="circle"),
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
                    dbc.Card(
                        [
                            dbc.CardHeader(t("emin_history.ranking_title"), class_name="emin-history-card-header"),
                            dbc.CardBody(dcc.Loading(html.Div(id="emin-history-ranking"), type="circle")),
                        ],
                        class_name="emin-history-card mb-3",
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
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.Div(t("emin_history.detail_filters_title"), className="emin-history-filter-title"),
                                dbc.Row(
                                    dbc.Col(
                                        [
                                            dbc.Label(t("emin_history.filter_unit"), html_for="emin-history-unit"),
                                            dcc.Dropdown(id="emin-history-unit", clearable=False, searchable=True),
                                        ],
                                        xs=12,
                                        md=6,
                                    ),
                                    className="g-3",
                                ),
                            ]
                        ),
                        class_name="emin-history-card mb-3",
                    ),
                    dcc.Loading(html.Div(id="emin-history-status"), type="circle"),
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Card(
                                    dbc.CardBody(
                                        dcc.Graph(
                                            id="emin-history-trend",
                                            config={"displayModeBar": False},
                                            responsive=True,
                                            style={"height": "350px", "width": "100%"},
                                        )
                                    ),
                                    class_name="emin-history-card h-100",
                                ),
                                xs=12,
                                className="mb-3",
                            ),
                        ],
                        className="g-3",
                    ),
                    dbc.Card(
                        [
                            dbc.CardHeader(t("emin_history.timeline_title"), class_name="emin-history-card-header"),
                            dbc.CardBody(dcc.Loading(html.Div(id="emin-history-evidence"), type="circle")),
                        ],
                        class_name="emin-history-card mb-3",
                    ),
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
