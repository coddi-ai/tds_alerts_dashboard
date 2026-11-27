"""Latest-cutoff EMIN Beta layout."""

from dash import dcc, html
import dash_bootstrap_components as dbc

from dashboard.components.emin_beta import CATEGORIES, _t
from dashboard.components.emin_historical import section_header
from src.i18n import t


def _unit_history_card(kind, title, icon, table_title):
    prefix = f"emin-beta-{kind}"
    table_controls = []
    if kind == "oil":
        table_controls.append(dbc.Checkbox(
            id="emin-beta-oil-red", value=False, label=_t("see_abnormal_oil"), class_name="mb-2",
        ))
    return dbc.Card([
        html.Div(section_header(_t(title), icon), id=f"{prefix}-heading", tabIndex=-1),
        dbc.CardBody([
            html.H6(_t(table_title), className="mb-2"),
            *table_controls,
            dcc.Store(id=f"{prefix}-page", data=0),
            dcc.Store(id=f"{prefix}-week"),
            html.Div(id=f"{prefix}-week-label", className="small text-muted mb-1", role="status"),
            html.Label(_t("table_week_filter"), htmlFor=f"{prefix}-week-select", className="small fw-semibold"),
            dbc.Select(id=f"{prefix}-week-select", value="__all__", size="sm",
                       class_name="emin-beta-filter mb-2", disabled=True),
            dcc.Loading(html.Div(id=f"{prefix}-rows"), type="circle"),
            html.Div([
                dbc.Button(t("emin_history.chronology_previous"), id=f"{prefix}-previous",
                           outline=True, color="secondary", size="sm", disabled=True),
                dbc.Button(t("emin_history.chronology_next"), id=f"{prefix}-next",
                           outline=True, color="secondary", size="sm", disabled=True),
            ], className="d-flex gap-2 mt-2 mb-3"),
            dcc.Loading(html.Div(id=f"{prefix}-graph"), type="circle"),
        ]),
    ], class_name="shadow-sm unit-card mb-3")


def create_layout():
    tab_style = {"className": "custom-tab pred-tab",
                 "selected_className": "custom-tab--selected pred-tab--selected"}
    return html.Div([
        html.H2([html.I(className="fas fa-history me-2", **{"aria-hidden": "true"}),
                 t("emin_history.title"), dbc.Badge("Beta", color="secondary", class_name="ms-2 align-middle")],
                className="text-primary mb-1 emin-beta-title"),
        html.P(id="emin-beta-cutoff", className="small text-muted mb-3", role="status"),
        dcc.Store(id="emin-beta-package"),
        dcc.Store(id="emin-beta-focused-record"),
        dcc.Tabs(id="emin-history-view-tabs", value="fleet", children=[
            dcc.Tab(label=_t("fleet_tab"), value="fleet", **tab_style),
            dcc.Tab(label=_t("unit_tab"), value="unit", **tab_style),
        ], className="mb-3"),
        html.Div([
            dcc.Loading(html.Div(id="emin-beta-fleet"), type="circle"),
            dbc.Card([
                html.Div(section_header(_t("fleet_table"), "fas fa-list-ol"),
                         id="emin-history-ranking-heading", tabIndex=-1),
                dbc.CardBody([
                    html.P(_t("table_note"), className="small text-muted mb-2"),
                    html.Div([
                        html.Label(t("emin_history.filter_group"), htmlFor="emin-beta-group", className="fleet-search__label"),
                        dcc.Dropdown(id="emin-beta-group", value="__all__", clearable=False, searchable=True),
                    ], className="emin-beta-filter mb-3"),
                    html.P(_t("ranking_historical_note"), className="small text-muted mb-2"),
                    dcc.Loading(html.Div(id="emin-beta-ranking"), type="circle"),
                ]),
            ], class_name="shadow-sm unit-card mb-3"),
        ], id="emin-history-overview-panel"),
        html.Div([
            html.Button([html.I(className="fas fa-arrow-left me-2", **{"aria-hidden": "true"}),
                         t("emin_history.back_to_fleet")], type="button",
                        className="btn btn-sm btn-outline-primary mb-3", **{"data-emin-back": "true"}),
            html.H3(_t("unit_tab"), className="h5", id="emin-history-detail-heading", tabIndex=-1),
            html.Div([
                html.Label(_t("team"), htmlFor="emin-history-unit", className="fleet-search__label"),
                dcc.Dropdown(id="emin-history-unit", clearable=False, searchable=True),
            ], className="emin-beta-filter mb-3"),
            dcc.Loading(html.Div(id="emin-beta-story"), type="circle"),
            _unit_history_card("milestones", "timeline", "fas fa-stream", "milestone_table"),
            _unit_history_card("oil", "oil_title", "fas fa-oil-can", "oil_table"),
            html.Details([
                html.Summary(_t("browse_all_records")),
                html.Div([
                    html.P(_t("records_note"), className="small text-muted mb-2"),
                    dbc.Row([
                        dbc.Col([
                            html.Label(_t("evidence_type"), htmlFor="emin-beta-record-category", className="fleet-search__label"),
                            dcc.Dropdown(id="emin-beta-record-category", clearable=False, value="__all__", options=[
                                {"label": _t("all_records"), "value": "__all__"},
                                {"label": _t("see_abnormal_oil"), "value": "abnormal_oil"},
                                *[{"label": _t(f"category_{category}"), "value": category} for category in CATEGORIES],
                            ]),
                        ], xs=12, md=4),
                        dbc.Col([
                            html.Label(_t("search_records"), htmlFor="emin-beta-record-search", className="fleet-search__label"),
                            dcc.Input(id="emin-beta-record-search", type="search", debounce=.4, value="",
                                      className="form-control", placeholder=_t("search_placeholder")),
                        ], xs=12, md=8),
                    ], class_name="g-2 mb-3"),
                    dcc.Store(id="emin-beta-record-page", data=0),
                    dcc.Loading(html.Div(id="emin-beta-records"), type="circle"),
                    html.Div([
                        dbc.Button(t("emin_history.chronology_previous"), id="emin-beta-record-previous",
                                   outline=True, color="secondary", size="sm", disabled=True),
                        dbc.Button(t("emin_history.chronology_next"), id="emin-beta-record-next",
                                   outline=True, color="secondary", size="sm", disabled=True),
                    ], className="d-flex gap-2 mt-3"),
                ], className="mt-3"),
            ], className="emin-beta-disclosure"),
        ], id="emin-history-detail-panel", style={"display": "none"}),
    ], className="container-fluid p-4 emin-history-page emin-beta-page")
