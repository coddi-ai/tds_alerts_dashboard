"""Callbacks for the EMIN historical fleet page."""

from dash import ClientsideFunction, Input, Output, State, callback, ctx, no_update
import plotly.graph_objects as go
import dash_bootstrap_components as dbc

from dashboard.auth import allowed_clients
from dashboard.components.emin_historical import build_historical_view, chronology_page, filter_options, fleet_criticality_panel, fleet_highlights_panel
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
        dbc.Alert(note, color="light", class_name="mb-0"),
        None,
        None,
        dbc.Alert(note, color="light", class_name="mb-0"),
        dbc.Alert(note, color="light", class_name="mb-0"),
        _empty_figure(t("emin_history.trend_title", unit=t("emin_history.no_unit")), note),
        dbc.Alert(note, color="light", class_name="mb-0"),
    )


def register_emin_historical_callbacks(app):
    """Register EMIN-only package filters, views, and internal tab navigation."""

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

    app.clientside_callback(
        ClientsideFunction(namespace="eminHistory", function_name="switchView"),
        [
            Output("emin-history-overview-panel", "style"),
            Output("emin-history-detail-panel", "style"),
        ],
        Input("emin-history-view-tabs", "value"),
    )
    app.clientside_callback(
        ClientsideFunction(namespace="eminHistory", function_name="openTrendDay"),
        Output("emin-history-trend-action", "data"),
        Input("emin-history-trend", "clickData"),
        prevent_initial_call=True,
    )
    @callback(
        Output("emin-history-criticality", "children"),
        Input("client-selector", "value"),
        Input("emin-history-package", "data"),
        Input("emin-history-cutoff", "value"),
        Input("emin-history-top-period", "value"),
        State("user-info-store", "data"),
    )
    def update_fleet_criticality(client, package, day, period, user_data):
        if not _authorized_emin(client, user_data):
            return None
        if not isinstance(package, dict) or not package.get("run"):
            return dbc.Alert(t("emin_history.package_missing"), color="light", class_name="mb-0")
        try:
            bundle = load_emin_historical_bundle(run_name=package["run"])
        except (FileNotFoundError, InvalidHistoricalBundle, OSError):
            return dbc.Alert(t("emin_history.package_invalid"), color="light", class_name="mb-0")
        return fleet_criticality_panel(bundle, day, period)

    @callback(
        [
            Output("emin-history-meta", "children"),
            Output("emin-history-highlights", "children"),
            Output("emin-history-kpis", "children"),
            Output("emin-history-groups", "children"),
            Output("emin-history-ranking", "children"),
            Output("emin-history-status", "children"),
            Output("emin-history-trend", "figure"),
            Output("emin-history-evidence", "children"),
        ],
        [
            Input("client-selector", "value"),
            Input("emin-history-package", "data"),
            Input("emin-history-cutoff", "value"),
            Input("emin-history-group", "value"),
            Input("emin-history-unit", "value"),
            Input("emin-history-search", "value"),
            Input("emin-history-movement-filter", "value"),
            Input("emin-history-high-signal-only", "value"),
            Input("emin-history-evidence-context", "data"),
        ],
        State("user-info-store", "data"),
    )
    def update_emin_historical_view(client, package, day, group, unit, search, movement_filter, high_only, evidence_context, user_data):
        if not _authorized_emin(client, user_data):
            return _empty_outputs(t("emin_history.emin_only"))
        if not isinstance(package, dict) or not package.get("run"):
            return _empty_outputs(t("emin_history.package_missing"))
        try:
            bundle = load_emin_historical_bundle(run_name=package["run"])
        except (FileNotFoundError, InvalidHistoricalBundle, OSError):
            return _empty_outputs(t("emin_history.package_invalid"))
        period = evidence_context.get("period") if isinstance(evidence_context, dict) and evidence_context.get("unit") == unit else None
        view = build_historical_view(
            bundle, day, group, unit, search, movement_filter, period,
            include_chronology=False, require_high_signal=high_only is True,
        )
        triggers = set(ctx.triggered_prop_ids)
        if triggers and triggers <= {"emin-history-unit.value", "emin-history-evidence-context.data"}:
            return (no_update,) * 5 + (view["status"], view["trend"], view["evidence"])
        return (
            view["meta"],
            fleet_highlights_panel(view["fleet_highlights"], view["daily_rows"], view["movements"]),
            view["kpis"],
            view["groups"],
            view["ranking"],
            view["status"],
            view["trend"],
            view["evidence"],
        )


    @callback(
        Output("emin-history-record-results", "children"),
        Output("emin-history-record-page", "data"),
        Output("emin-history-record-previous", "disabled"),
        Output("emin-history-record-next", "disabled"),
        Input("client-selector", "value"),
        Input("emin-history-package", "data"),
        Input("emin-history-cutoff", "value"),
        Input("emin-history-unit", "value"),
        Input("emin-history-record-type", "value"),
        Input("emin-history-record-search", "value"),
        Input("emin-history-record-previous", "n_clicks"),
        Input("emin-history-record-next", "n_clicks"),
        State("emin-history-record-page", "data"),
        State("user-info-store", "data"),
    )
    def update_chronology(client, package, cutoff, unit, kind, query, previous, following, page, user_data):
        if not _authorized_emin(client, user_data):
            return None, 0, True, True
        if not isinstance(package, dict) or not package.get("run"):
            return t("emin_history.package_missing"), 0, True, True
        try:
            bundle = load_emin_historical_bundle(run_name=package["run"])
        except (FileNotFoundError, InvalidHistoricalBundle, OSError):
            return t("emin_history.package_invalid"), 0, True, True

        delta = {"emin-history-record-previous": -1, "emin-history-record-next": 1}.get(ctx.triggered_id)
        page = (page + delta) if delta is not None and isinstance(page, int) else 0
        return chronology_page(bundle, unit, cutoff, kind, query, page)
