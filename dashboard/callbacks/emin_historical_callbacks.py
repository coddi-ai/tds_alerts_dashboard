"""Authorized EMIN Beta callbacks. Metrics and evidence classifications come from the package."""

from dash import ClientsideFunction, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc

from dashboard.auth import allowed_clients
from dashboard.components.emin_beta import (
    _t, date_caption, evidence_page, fleet_intro, fleet_table, unit_record_weeks, unit_records_page, unit_story,
)
from src.data.emin_historical import InvalidHistoricalBundle, load_emin_historical_bundle
from src.i18n import t


def _authorized_emin(client: str | None, user_data: dict | None) -> bool:
    if str(client or "").strip().upper() != "EMIN":
        return False
    return any(str(allowed).strip().upper() == "EMIN" for allowed in allowed_clients(user_data))


def _trend_figure_from_view(view: dict):
    """Normalize legacy figures for callers of the pre-Beta read model."""
    trend = view["trend"]
    return getattr(trend, "figure", trend)


def _get_report(client, user_data, package):
    if not _authorized_emin(client, user_data) or not isinstance(package, dict) or not package.get("run"):
        return None
    try:
        return _scoped_report(load_emin_historical_bundle(run_name=package["run"]))
    except (FileNotFoundError, InvalidHistoricalBundle, OSError):
        return None


def _scoped_report(bundle):
    report = bundle.dashboard.get("beta_report")
    return report if report and report.get("analysis_start") == "2024-01-01" and report.get("quadrants") else None


def _message(label):
    return dbc.Alert(label, color="light", class_name="mb-3")


def register_emin_historical_callbacks(app):
    app.clientside_callback(
        ClientsideFunction(namespace="eminHistory", function_name="switchView"),
        Output("emin-history-overview-panel", "style"),
        Output("emin-history-detail-panel", "style"),
        Input("emin-history-view-tabs", "value"),
    )

    @callback(
        Output("emin-beta-cutoff", "children"),
        Output("emin-beta-package", "data"),
        Output("emin-beta-fleet", "children"),
        Output("emin-beta-group", "options"),
        Output("emin-beta-group", "value"),
        Output("emin-history-unit", "options"),
        Output("emin-history-unit", "value"),
        Input("client-selector", "value"),
        Input("user-info-store", "data"),
    )
    def load_report(client, user_data):
        empty_controls = ([], "__all__", [], None)
        if not _authorized_emin(client, user_data):
            return None, None, _message(t("emin_history.emin_only")), *empty_controls
        try:
            bundle = load_emin_historical_bundle()
        except FileNotFoundError:
            return None, None, _message(t("emin_history.package_missing")), *empty_controls
        except (InvalidHistoricalBundle, OSError):
            return None, None, _message(t("emin_history.package_invalid")), *empty_controls
        report = _scoped_report(bundle)
        if not report:
            return None, None, _message(_t("pending")), *empty_controls
        groups = [{"label": _t("all_groups"), "value": "__all__"},
                  *[{"label": group, "value": group} for group in report["groups"]]]
        units = [{"label": unit, "value": unit} for unit in sorted(report["units"], key=str.casefold)]
        return (date_caption(report), {"run": bundle.run}, fleet_intro(report),
                groups, "__all__", units, report["rows"][0]["unit"] if report["rows"] else None)

    @callback(
        Output("emin-beta-ranking", "children"),
        Input("emin-beta-group", "value"),
        Input("emin-beta-package", "data"),
        State("client-selector", "value"),
        State("user-info-store", "data"),
    )
    def update_ranking(group, package, client, user_data):
        report = _get_report(client, user_data, package)
        return fleet_table(report, group) if report else _message(_t("pending"))

    @callback(
        Output("emin-beta-story", "children"),
        Output("emin-beta-milestones-graph", "children"),
        Output("emin-beta-oil-graph", "children"),
        Input("emin-history-unit", "value"),
        Input("emin-history-view-tabs", "value"),
        Input("emin-beta-package", "data"),
        Input("emin-beta-focused-record", "data"),
        State("client-selector", "value"),
        State("user-info-store", "data"),
    )
    def update_story(unit, tab, package, focus, client, user_data):
        if tab != "unit":
            return None, None, None
        report = _get_report(client, user_data, package)
        return unit_story(report, unit, focus) if report else (_message(_t("pending")), None, None)

    for table in ("milestones", "oil"):
        _register_unit_records_table(table)

    @callback(
        Output("emin-beta-records", "children"),
        Output("emin-beta-record-page", "data"),
        Output("emin-beta-record-previous", "disabled"),
        Output("emin-beta-record-next", "disabled"),
        Input("emin-history-unit", "value"),
        Input("emin-history-view-tabs", "value"),
        Input("emin-beta-record-category", "value"),
        Input("emin-beta-record-search", "value"),
        Input("emin-beta-record-previous", "n_clicks"),
        Input("emin-beta-record-next", "n_clicks"),
        Input("emin-beta-package", "data"),
        State("emin-beta-record-page", "data"),
        State("client-selector", "value"),
        State("user-info-store", "data"),
    )
    def update_records(unit, tab, category, query, previous, following, package, page, client, user_data):
        if tab != "unit":
            return None, 0, True, True
        report = _get_report(client, user_data, package)
        if not report:
            return _message(_t("pending")), 0, True, True
        direction = {"emin-beta-record-previous": -1, "emin-beta-record-next": 1}.get(ctx.triggered_id)
        requested = (page or 0) + direction if direction else 0
        return evidence_page(report, unit, category, query, requested)


def _register_unit_records_table(table):
    prefix = f"emin-beta-{table}"
    filters = [Input("emin-beta-oil-red", "value")] if table == "oil" else []

    @callback(
        Output(f"{prefix}-rows", "children"),
        Output(f"{prefix}-page", "data"),
        Output(f"{prefix}-previous", "disabled"),
        Output(f"{prefix}-next", "disabled"),
        Output(f"{prefix}-week", "data"),
        Output(f"{prefix}-week-label", "children"),
        Output(f"{prefix}-week-select", "options"),
        Output(f"{prefix}-week-select", "value"),
        Output(f"{prefix}-week-select", "disabled"),
        Input("emin-history-unit", "value"),
        Input("emin-history-view-tabs", "value"),
        Input("emin-beta-package", "data"),
        Input(f"{prefix}-previous", "n_clicks"),
        Input(f"{prefix}-next", "n_clicks"),
        Input(f"{prefix}-chart", "clickData", allow_optional=True),
        Input(f"{prefix}-week-select", "value"),
        *filters,
        State(f"{prefix}-week", "data"),
        State(f"{prefix}-page", "data"),
        State("client-selector", "value"),
        State("user-info-store", "data"),
    )
    def update_table(unit, tab, package, previous, following, click, selected_week, *values):
        if tab != "unit":
            return None, 0, True, True, None, None, [], "__all__", True
        selection, page, client, user_data = values[-4:]
        report = _get_report(client, user_data, package)
        if not report:
            return None, 0, True, True, None, None, [], "__all__", True
        direction = {f"{prefix}-previous": -1, f"{prefix}-next": 1}.get(ctx.triggered_id)
        requested = (page or 0) + direction if direction else 0
        week = selection.get("week") if isinstance(selection, dict) and selection.get("unit") == unit else None
        if ctx.triggered_id in {"emin-history-unit", "emin-beta-package"}:
            week = None
        elif ctx.triggered_id == f"{prefix}-week-select":
            week = selected_week
        elif ctx.triggered_id == f"{prefix}-chart" and isinstance(click, dict):
            points = click.get("points")
            point = points[0].get("customdata") if isinstance(points, list) and points and isinstance(points[0], dict) else None
            if isinstance(point, list) and point and point[-1] == unit and isinstance(point[0], str):
                week = point[0]
        weeks = unit_record_weeks(report, unit, table)
        if week not in {entry[0] for entry in weeks}:
            week = None
        options = [{"label": _t("clear_chart_week"), "value": "__all__"}]
        options.extend({"label": _t("table_week_option", week=iso, monday=monday), "value": iso}
                       for iso, monday in weeks)
        result = unit_records_page(report, unit, table, bool(values[0]) if filters else False, requested, week)
        return (*result, {"unit": unit, "week": week} if week else None,
                _t("selected_chart_week", week=week) if week else _t("choose_chart_week") if weeks else None,
                options, week or "__all__", not weeks)
