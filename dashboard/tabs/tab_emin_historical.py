"""Friendly two-level EMIN historical fleet review page."""

from dash import dcc, html
import dash_bootstrap_components as dbc

from dashboard.components.emin_historical import CHRONOLOGY_TYPES, section_header
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
            dcc.Store(id="emin-history-evidence-context"),
            html.Div(
                [
                    dbc.Row([
                        dbc.Col(
                            [
                                dcc.Tabs(
                                    id="emin-history-fleet-window",
                                    value="week",
                                    children=[
                                        dcc.Tab(
                                            label=t("emin_history.period_week"), value="week",
                                            className="custom-tab pred-tab",
                                            selected_className="custom-tab--selected pred-tab--selected",
                                        ),
                                        dcc.Tab(
                                            label=t("emin_history.period_month"), value="month",
                                            className="custom-tab pred-tab",
                                            selected_className="custom-tab--selected pred-tab--selected",
                                        ),
                                        dcc.Tab(
                                            label=t("emin_history.period_quarter"), value="quarter",
                                            className="custom-tab pred-tab",
                                            selected_className="custom-tab--selected pred-tab--selected",
                                        ),
                                        dcc.Tab(
                                            label=t("emin_history.period_history"), value="history",
                                            className="custom-tab pred-tab",
                                            selected_className="custom-tab--selected pred-tab--selected",
                                        ),
                                    ],
                                    className="mb-2",
                                ),
                                dcc.Loading(html.Div(id="emin-history-kpis"), type="circle"),
                                html.P(t("emin_history.variation_chart_note"), className="small text-muted mt-1 mb-0"),
                            ],
                            xs=12,
                        ),
                    ], class_name="g-3 mb-3"),
                    dbc.Card([
                        section_header(t("emin_history.top_title"), "fas fa-list-ol"),
                        dbc.CardBody([
                            html.P(t("emin_history.top_period_follow"), className="small text-muted mb-2"),
                            dcc.Loading(html.Div(id="emin-history-criticality"), type="circle"),
                        ]),
                    ], class_name="shadow-sm unit-card mb-3"),
                    dbc.Card(
                        [
                            html.Div(section_header(t("emin_history.ranking_title"), "fas fa-list-ol"), id="emin-history-ranking-heading", tabIndex=-1),
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
                                dbc.Checkbox(
                                    id="emin-history-high-signal-only", value=False,
                                    label=t("emin_history.ranking_high_signal_only"),
                                    class_name="mb-3",
                                ),
                                dcc.Loading(html.Div(id="emin-history-ranking"), type="circle"),
                            ]),
                        ],
                        class_name="emin-history-card mb-3",
                    ),
                    dcc.Loading(html.Div(id="emin-history-highlights"), type="circle"),
                    dbc.Card(
                        dbc.CardBody(dcc.Loading(html.Div(id="emin-history-groups"), type="circle")),
                        class_name="shadow-sm unit-card mb-3",
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
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Card([
                                    section_header(t("emin_history.trend_section"), "fas fa-chart-line"),
                                    dbc.CardBody([
                                        html.P(
                                            [t("emin_history.trend_open_records"), " ", t("emin_history.trend_direction_note")],
                                            className="small text-muted mb-1",
                                        ),
                                        dcc.Tabs(
                                            id="emin-history-trend-window",
                                            value="week",
                                            children=[
                                                dcc.Tab(
                                                    label=t("emin_history.period_week"),
                                                    value="week",
                                                    className="custom-tab pred-tab",
                                                    selected_className="custom-tab--selected pred-tab--selected",
                                                ),
                                                dcc.Tab(
                                                    label=t("emin_history.period_month"),
                                                    value="month",
                                                    className="custom-tab pred-tab",
                                                    selected_className="custom-tab--selected pred-tab--selected",
                                                ),
                                                dcc.Tab(
                                                    label=t("emin_history.period_quarter"), value="quarter",
                                                    className="custom-tab pred-tab",
                                                    selected_className="custom-tab--selected pred-tab--selected",
                                                ),
                                                dcc.Tab(
                                                    label=t("emin_history.period_history"), value="history",
                                                    className="custom-tab pred-tab",
                                                    selected_className="custom-tab--selected pred-tab--selected",
                                                ),
                                            ],
                                            className="mb-2",
                                        ),
                                        dcc.Store(id="emin-history-trend-action"),
                                        dcc.Graph(
                                            id="emin-history-trend",
                                            config={"displayModeBar": False},
                                            responsive=True,
                                            style={"height": "430px", "width": "100%"},
                                        ),
                                    ]),
                                ], class_name="shadow-sm unit-card",
                                ),
                                xs=12,
                                lg=6,
                                className="mb-3",
                            ),
                            dbc.Col(
                                dbc.Card([
                                    section_header(t("emin_history.cumulative_score_heading"), "fas fa-chart-area"),
                                    dbc.CardBody([
                                        html.P(t("emin_history.cumulative_score_note"), className="small text-muted mb-1"),
                                        dcc.Graph(
                                            id="emin-history-cumulative-score",
                                            config={"displayModeBar": False},
                                            responsive=True,
                                            style={"height": "340px", "width": "100%"},
                                        ),
                                    ]),
                                ], class_name="shadow-sm unit-card"),
                                xs=12,
                                lg=6,
                                className="mb-3",
                            ),
                        ],
                        className="g-3",
                    ),
                    dcc.Loading(html.Div(id="emin-history-status"), type="circle"),
                    dcc.Loading(html.Div(id="emin-history-evidence"), type="circle"),
                    dbc.Card([
                        section_header(t("emin_history.full_chronology"), "fas fa-history"),
                        dbc.CardBody(html.Details([
                            html.Summary(t("emin_history.chronology_expand")),
                            dbc.Row([
                                dbc.Col([
                                    html.Label(t("emin_history.chronology_type"), htmlFor="emin-history-record-type", className="fleet-search__label"),
                                    dbc.Select(
                                        id="emin-history-record-type", size="sm", value="all",
                                        options=[
                                            {"label": t(f"emin_history.chronology_{kind}"), "value": kind}
                                            for kind in CHRONOLOGY_TYPES
                                        ],
                                    ),
                                ], xs=12, md=4),
                                dbc.Col([
                                    html.Label(t("emin_history.chronology_search"), htmlFor="emin-history-record-search", className="fleet-search__label"),
                                    dcc.Input(
                                        id="emin-history-record-search", type="search", value="", debounce=0.4,
                                        placeholder=t("emin_history.chronology_search_placeholder"),
                                        className="form-control form-control-sm",
                                    ),
                                ], xs=12, md=8),
                            ], className="g-2 mb-3"),
                            dcc.Store(id="emin-history-record-page", data=0),
                            dcc.Loading(html.Div(id="emin-history-record-results"), type="circle"),
                            html.Div([
                                dbc.Button(t("emin_history.chronology_previous"), id="emin-history-record-previous", color="secondary", outline=True, size="sm", disabled=True),
                                dbc.Button(t("emin_history.chronology_next"), id="emin-history-record-next", color="secondary", outline=True, size="sm", disabled=True),
                            ], className="d-flex gap-2 mt-3"),
                        ], open=False)),
                    ], class_name="shadow-sm unit-card mb-3"),
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
