"""Callbacks for the EMIN historical fleet page."""

from dash import Input, Output, State, callback
import plotly.graph_objects as go
import dash_bootstrap_components as dbc

from dashboard.auth import allowed_clients
from dashboard.components.emin_historical import build_historical_view, filter_options
from src.data.emin_historical import InvalidHistoricalBundle, load_emin_historical_bundle
from src.i18n import t


def _authorized_emin(client: str | None, user_data: dict | None) -> bool:
    if str(client or "").strip().upper() != "EMIN":
        return False
    return any(str(allowed).strip().upper() == "EMIN" for allowed in allowed_clients(user_data))


def _empty_figure(title: str, note: str) -> go.Figure:
    figure = go.Figure()
    figure.add_annotation(text=note, showarrow=False, font={"color": "#7f8c8d", "size": 13})
    figure.update_layout(title=title, template="plotly_white", height=350)
    return figure


def _empty_outputs(note: str):
    return (
        dbc.Alert(note, color="light", class_name="mb-0"),
        None,
        _empty_figure(t("emin_history.trend_title", unit=t("emin_history.no_unit")), note),
        _empty_figure(t("emin_history.groups_title"), note),
        dbc.Alert(note, color="light", class_name="mb-0"),
        dbc.Alert(note, color="light", class_name="mb-0"),
    )


def register_emin_historical_callbacks(app):
    """Register data-bound filter options and the read-only historical view."""

    @callback(
        [
            Output("emin-history-cutoff", "options"),
            Output("emin-history-cutoff", "value"),
            Output("emin-history-group", "options"),
            Output("emin-history-group", "value"),
            Output("emin-history-unit", "options"),
            Output("emin-history-unit", "value"),
            Output("emin-history-package", "data"),
        ],
        Input("client-selector", "value"),
        State("user-info-store", "data"),
    )
    def load_emin_filter_options(client, user_data):
        if not _authorized_emin(client, user_data):
            return [], None, [], None, [], None, None
        try:
            bundle = load_emin_historical_bundle()
        except (FileNotFoundError, InvalidHistoricalBundle):
            return [], None, [], None, [], None, None
        options = filter_options(bundle)
        return (
            options["days"],
            options["default_day"],
            options["groups"],
            "__all__",
            options["units"],
            options["default_unit"],
            {"run": bundle.run},
        )

    @callback(
        [
            Output("emin-history-meta", "children"),
            Output("emin-history-kpis", "children"),
            Output("emin-history-trend", "figure"),
            Output("emin-history-groups", "figure"),
            Output("emin-history-ranking", "children"),
            Output("emin-history-evidence", "children"),
        ],
        [
            Input("client-selector", "value"),
            Input("emin-history-package", "data"),
            Input("emin-history-cutoff", "value"),
            Input("emin-history-group", "value"),
            Input("emin-history-unit", "value"),
        ],
        State("user-info-store", "data"),
    )
    def update_emin_historical_view(client, package, day, group, unit, user_data):
        if not _authorized_emin(client, user_data):
            return _empty_outputs(t("emin_history.emin_only"))
        if not isinstance(package, dict) or not package.get("run"):
            return _empty_outputs(t("emin_history.package_missing"))
        try:
            bundle = load_emin_historical_bundle(run_name=package["run"])
        except (FileNotFoundError, InvalidHistoricalBundle, OSError):
            return _empty_outputs(t("emin_history.package_invalid"))
        view = build_historical_view(bundle, day, group, unit)
        return (
            view["meta"],
            view["kpis"],
            view["trend"],
            view["groups"],
            view["ranking"],
            view["evidence"],
        )
