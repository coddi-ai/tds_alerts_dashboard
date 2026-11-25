"""Friendly page shell for the EMIN historical fleet review."""

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
            dbc.Card(
                dbc.CardBody(
                    [
                        html.Div(t("emin_history.filters_title"), className="emin-history-filter-title"),
                        dbc.Row(
                            [
                                dbc.Col(
                                    [
                                        dbc.Label(t("emin_history.filter_day"), html_for="emin-history-cutoff"),
                                        dcc.Dropdown(id="emin-history-cutoff", clearable=False, searchable=True),
                                    ],
                                    xs=12,
                                    md=4,
                                ),
                                dbc.Col(
                                    [
                                        dbc.Label(t("emin_history.filter_group"), html_for="emin-history-group"),
                                        dcc.Dropdown(id="emin-history-group", clearable=False, searchable=True),
                                    ],
                                    xs=12,
                                    md=4,
                                ),
                                dbc.Col(
                                    [
                                        dbc.Label(t("emin_history.filter_unit"), html_for="emin-history-unit"),
                                        dcc.Dropdown(id="emin-history-unit", clearable=False, searchable=True),
                                    ],
                                    xs=12,
                                    md=4,
                                ),
                            ],
                            className="g-3",
                        ),
                    ]
                ),
                class_name="emin-history-card mb-3",
            ),
            dcc.Store(id="emin-history-package"),
            dcc.Loading(html.Div(id="emin-history-kpis"), type="circle"),
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
                        xl=7,
                        class_name="mb-3",
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                dcc.Graph(
                                    id="emin-history-groups",
                                    config={"displayModeBar": False},
                                    responsive=True,
                                    style={"height": "350px", "width": "100%"},
                                )
                            ),
                            class_name="emin-history-card h-100",
                        ),
                        xs=12,
                        xl=5,
                        class_name="mb-3",
                    ),
                ],
                className="g-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(t("emin_history.ranking_title"), class_name="emin-history-card-header"),
                                dbc.CardBody(dcc.Loading(html.Div(id="emin-history-ranking"), type="circle")),
                            ],
                            class_name="emin-history-card h-100",
                        ),
                        xs=12,
                        xl=7,
                        class_name="mb-3",
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(t("emin_history.evidence_title"), class_name="emin-history-card-header"),
                                dbc.CardBody(dcc.Loading(html.Div(id="emin-history-evidence"), type="circle")),
                            ],
                            class_name="emin-history-card h-100",
                        ),
                        xs=12,
                        xl=5,
                        class_name="mb-3",
                    ),
                ],
                className="g-3",
            ),
            dbc.Alert(
                [html.I(className="fas fa-info-circle me-2"), t("emin_history.method_note")],
                color="light",
                class_name="emin-history-method-note",
            ),
        ],
        className="container-fluid p-4 emin-history-page",
    )
