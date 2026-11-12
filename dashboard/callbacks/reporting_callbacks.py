"""
Callbacks de Reportes > Reportabilidad (dashboard/pages/reporting_main.py).

Flujo: al cambiar de cliente (o con "Actualizar") se lista su carpeta de S3 una vez,
se le agrega el estado combinado de cada unidad (src/data/report_health.py) y el
catalogo queda en `reporting-catalog-store`. Todo lo demas (estado actual, informe de
unidad, historial) trabaja sobre ese catalogo sin volver a S3. El PDF se muestra en un
iframe que apunta a la ruta de dashboard/report_files.py, que repite la autorizacion
en cada apertura.

Navegacion: lo que se pulsa y se redibuja (fichas, tarjetas, botones del visor,
cabeceras de la tabla) no usa n_clicks sino `data-rp` + assets/reporting_actions.js,
que escribe la accion en `reporting-action`. Tres callbacks la atienden, cada uno la
parte que le toca: `navigate` (pestaña e informe abierto), `update_state_filter` y
`update_history_state`. Las reglas de seleccion viven en src/data/report_view.py.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from config.client_services import normalize_client_id
from dashboard.components.report_states import state_label
from dashboard.components.reporting_views import (
    history_pager, history_table, overview_sections, pdf_src, report_header, report_toolbar,
    state_filter_row, system_label, technique_label, viewer_list,
)
from dashboard.report_files import report_file_href, reporting_available, visible_systems
from src.data.report_health import STATES_BY_SEVERITY, attach_health, normalize_state
from src.data.report_store import TECHNIQUE_SYSTEMS, get_report_store, unit_sort_key
from src.data.report_view import (
    ALL, HISTORY_PAGE_SIZE, batch_records, filter_history, next_sort, ordered_systems, paginate, search_rows,
    sort_history, split_sections, state_counts, viewer_model,
)
from src.i18n import t
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_HISTORY_STATE = {"sort": "date", "dir": "desc", "page": 1}
DEFAULT_VIEW = {"tab": "current", "key": None, "list_date": None}
TABS = ("current", "history")


def _notice(message: str, color: str = "secondary") -> dbc.Alert:
    return dbc.Alert([html.I(className="fas fa-circle-info me-2"), message], color=color, className="mb-4")


def keep_latest_versions(records: List[dict]) -> List[dict]:
    """Un informe regenerado el mismo dia (`_01`) reemplaza al original."""
    newest: Dict[tuple, dict] = {}
    for record in records:
        slot = (record["technique"], record["system"], record["unit"], record["date"])
        if slot not in newest or record["version"] > newest[slot]["version"]:
            newest[slot] = record
    kept = {id(r) for r in newest.values()}
    return [r for r in records if id(r) in kept]


def load_catalog(client: str, user_clients: List[str], refresh: bool = False):
    """(registros, aviso) para el cliente activo; aviso es None si todo salio bien."""
    client = normalize_client_id(client)
    if not client or client not in {normalize_client_id(c) for c in user_clients}:
        return [], _notice(t("reporting.no_access"))
    if not reporting_available(client):
        return [], _notice(t("reporting.unavailable", client=client))

    store = get_report_store()
    if store is None:
        return [], _notice(t("reporting.storage_error"), "warning")
    try:
        entries = store.list_reports(client, refresh=refresh)
    except Exception as exc:
        logger.error(f"Reportabilidad {client}: no se pudo listar S3 ({type(exc).__name__}: {exc})")
        return [], _notice(t("reporting.storage_error"), "warning")

    allowed = {tech: set(visible_systems(client, tech)) for tech in TECHNIQUE_SYSTEMS}
    records = []
    for entry in entries:
        if entry.system not in allowed.get(entry.technique, ()):
            continue
        record = entry.to_record()
        record["href"] = report_file_href(client, entry.key)
        record["download_href"] = report_file_href(client, entry.key, download=True)
        records.append(record)

    if not records:
        return [], _notice(t("reporting.no_reports", client=client))
    return attach_health(keep_latest_versions(records), client), None


# ---------------------------------------------------------------------------
# Opciones de los filtros
# ---------------------------------------------------------------------------

def _options(values, label) -> List[dict]:
    return [{"label": label(v), "value": v} for v in values]


def filter_options(records: List[dict]) -> dict:
    """Opciones de todos los selects, calculadas una vez por catalogo."""
    techniques = [tech for tech in TECHNIQUE_SYSTEMS if any(r["technique"] == tech for r in records)]
    systems = list(dict.fromkeys(system for _, system in ordered_systems(records)))
    units = sorted({r["unit"] for r in records}, key=unit_sort_key)
    dates = sorted({r["date"] for r in records}, reverse=True)
    return {
        "techniques": techniques,
        "dates": dates,
        "technique": _options(techniques, technique_label),
        "system": [{"label": t("reporting.all_systems"), "value": ALL}] + _options(systems, system_label),
        "unit": [{"label": t("reporting.all_units"), "value": ALL}] + _options(units, str),
        "date": _options(dates, str),
        "date_all": [{"label": t("reporting.all_dates"), "value": ALL}] + _options(dates, str),
        "state": [{"label": t("reporting.all_states"), "value": ALL}] + _options(STATES_BY_SEVERITY, state_label),
    }


# ---------------------------------------------------------------------------
# Estado de la vista
# ---------------------------------------------------------------------------

def next_view(view: Optional[dict], action: dict, records: List[dict], current_date: Optional[str]) -> Optional[dict]:
    """Vista tras una accion `open` / `close` / `tab`; None si no cambia nada."""
    view = {**DEFAULT_VIEW, **(view or {})}
    kind = action.get("type")
    if kind == "close":
        return {**view, "tab": "current", "key": None, "list_date": None}
    if kind == "tab":
        return {**view, "tab": action["tab"]} if action.get("tab") in TABS else None
    if kind != "open":
        return None
    record = next((r for r in records if r["key"] == action.get("key")), None)
    if record is None:
        return None
    context = action.get("ctx")
    if context == "current":
        list_date = current_date or record["date"]
    elif context == "record":
        list_date = record["date"]
    else:  # "keep": la lista conserva la fecha con que se abrio el visor
        list_date = view.get("list_date")
    return {"tab": "current", "key": record["key"], "list_date": list_date}


def open_model(view: Optional[dict], records: List[dict]) -> Optional[dict]:
    """Modelo del informe abierto, o None (sin informe o clave que ya no esta en el catalogo)."""
    view = view or {}
    if not view.get("key") or not records:
        return None
    return viewer_model(records, view["key"], view.get("list_date"))


def next_history_state(state: Optional[dict], trigger, action: Optional[dict]) -> Optional[dict]:
    """Estado de orden y pagina del Historial; None si la accion no es suya."""
    state = {**DEFAULT_HISTORY_STATE, **(state or {})}
    if trigger != "reporting-action":
        return {**state, "page": 1}  # cambiaron los filtros
    kind = (action or {}).get("type")
    if kind == "sort":
        return next_sort(state, action.get("col"))
    if kind == "page":
        try:
            return {**state, "page": max(1, int(action.get("page")))}
        except (TypeError, ValueError):
            return None
    return None


def register_reporting_callbacks(app: dash.Dash) -> None:
    """Catalogo por cliente, estado actual, informe de unidad e historial."""

    @app.callback(
        Output("reporting-catalog-store", "data"),
        Output("reporting-status", "children"),
        Output("reporting-body", "style"),
        Output("reporting-cur-technique", "options"),
        Output("reporting-cur-technique", "value"),
        Output("reporting-cur-system", "options"),
        Output("reporting-cur-system", "value"),
        Output("reporting-cur-date", "options"),
        Output("reporting-cur-date", "value"),
        Output("reporting-his-technique", "options"),
        Output("reporting-his-technique", "value"),
        Output("reporting-his-system", "options"),
        Output("reporting-his-system", "value"),
        Output("reporting-his-unit", "options"),
        Output("reporting-his-unit", "value"),
        Output("reporting-his-date", "options"),
        Output("reporting-his-date", "value"),
        Output("reporting-his-state", "options"),
        Output("reporting-his-state", "value"),
        Input("client-selector", "value"),
        Input("reporting-cur-refresh", "n_clicks"),
        Input("reporting-his-refresh", "n_clicks"),
        State("user-info-store", "data"),
    )
    def load_reporting_catalog(selected_client, _cur_refresh, _his_refresh, user_data):
        if not user_data:
            raise PreventUpdate
        user_clients = user_data.get("clients", [])
        client = selected_client or (user_clients[0] if user_clients else "")
        refresh = ctx.triggered_id in ("reporting-cur-refresh", "reporting-his-refresh")
        records, notice = load_catalog(client, user_clients, refresh=refresh)
        opts = filter_options(records)

        # "Actualizar" no cambia de cliente: conserva los filtros elegidos.
        first_technique = opts["techniques"][0] if opts["techniques"] else None
        newest = opts["dates"][0] if opts["dates"] else None
        return (
            records,
            notice,
            {} if records else {"display": "none"},
            opts["technique"], no_update if refresh else first_technique,
            opts["system"], no_update if refresh else ALL,
            opts["date"], no_update if refresh else newest,
            opts["technique"], no_update if refresh else first_technique,
            opts["system"], no_update if refresh else ALL,
            opts["unit"], no_update if refresh else ALL,
            opts["date_all"], no_update if refresh else ALL,
            opts["state"], no_update if refresh else ALL,
        )

    # ----- navegacion -------------------------------------------------------

    @app.callback(
        Output("reporting-view-store", "data"),
        Input("reporting-tab-current", "n_clicks"),
        Input("reporting-tab-history", "n_clicks"),
        Input("reporting-action", "data"),
        State("reporting-view-store", "data"),
        State("reporting-cur-date", "value"),
        State("reporting-catalog-store", "data"),
        prevent_initial_call=True,
    )
    def navigate(_current, _history, action, view, current_date, records):
        trigger = ctx.triggered_id
        if trigger == "reporting-tab-current":
            action = {"type": "tab", "tab": "current"}
        elif trigger == "reporting-tab-history":
            action = {"type": "tab", "tab": "history"}
        result = next_view(view, action or {}, records or [], current_date)
        if result is None:
            raise PreventUpdate
        return result

    @app.callback(
        Output("reporting-state-filter", "data"),
        Input("reporting-action", "data"),
        prevent_initial_call=True,
    )
    def update_state_filter(action):
        if not action or action.get("type") != "state":
            raise PreventUpdate
        value = action.get("state")
        return ALL if value in (None, "", ALL) else (normalize_state(value) or "sin_datos")

    @app.callback(
        Output("reporting-history-state", "data"),
        Input("reporting-action", "data"),
        Input("reporting-his-technique", "value"),
        Input("reporting-his-system", "value"),
        Input("reporting-his-unit", "value"),
        Input("reporting-his-date", "value"),
        Input("reporting-his-state", "value"),
        State("reporting-history-state", "data"),
        prevent_initial_call=True,
    )
    def update_history_state(action, _technique, _system, _unit, _date, _state, state):
        result = next_history_state(state, ctx.triggered_id, action)
        if result is None:
            raise PreventUpdate
        return result

    @app.callback(
        Output("reporting-his-technique", "value", allow_duplicate=True),
        Output("reporting-his-system", "value", allow_duplicate=True),
        Output("reporting-his-unit", "value", allow_duplicate=True),
        Output("reporting-his-date", "value", allow_duplicate=True),
        Output("reporting-his-state", "value", allow_duplicate=True),
        Input("reporting-his-clear", "n_clicks"),
        State("reporting-catalog-store", "data"),
        prevent_initial_call=True,
    )
    def clear_history_filters(clicks, records):
        if not clicks:
            raise PreventUpdate
        techniques = filter_options(records or [])["techniques"]
        return (techniques[0] if techniques else None), ALL, ALL, ALL, ALL

    # ----- dibujo -----------------------------------------------------------

    @app.callback(
        Output("reporting-panel-current", "hidden"),
        Output("reporting-panel-history", "hidden"),
        Output("reporting-overview", "hidden"),
        Output("reporting-viewer", "hidden"),
        Output("reporting-tab-current", "className"),
        Output("reporting-tab-current", "aria-selected"),
        Output("reporting-tab-history", "className"),
        Output("reporting-tab-history", "aria-selected"),
        Input("reporting-view-store", "data"),
        Input("reporting-catalog-store", "data"),
    )
    def render_shell(view, records):
        view = {**DEFAULT_VIEW, **(view or {})}
        on_history = view["tab"] == "history"
        viewing = not on_history and open_model(view, records or []) is not None
        return (
            on_history, not on_history, viewing, not viewing,
            "rp-tab" + ("" if on_history else " rp-tab--on"), "false" if on_history else "true",
            "rp-tab" + (" rp-tab--on" if on_history else ""), "true" if on_history else "false",
        )

    @app.callback(
        Output("reporting-state-filters", "children"),
        Output("reporting-sections", "children"),
        Input("reporting-catalog-store", "data"),
        Input("reporting-cur-technique", "value"),
        Input("reporting-cur-system", "value"),
        Input("reporting-cur-date", "value"),
        Input("reporting-state-filter", "data"),
    )
    def render_overview(records, technique, system, date, state_filter):
        records = records or []
        if not records:
            return [], []
        batch = batch_records(records, technique, system, date)
        state_filter = state_filter or ALL
        attention, clear = split_sections(batch, state_filter)
        show_system = len({r["system"] for r in batch}) > 1
        return (
            state_filter_row(state_counts(batch), state_filter),
            overview_sections(attention, clear, show_system),
        )

    @app.callback(
        Output("reporting-viewer-list", "children"),
        Input("reporting-view-store", "data"),
        Input("reporting-catalog-store", "data"),
        Input("reporting-viewer-search", "value"),
    )
    def render_viewer_list(view, records, query):
        model = open_model(view, records or [])
        if model is None:
            return []
        return viewer_list(model, search_rows(model["rows"], query))

    @app.callback(
        Output("reporting-report-header", "children"),
        Output("reporting-report-toolbar", "children"),
        Output("reporting-pdf-frame", "src"),
        Input("reporting-view-store", "data"),
        Input("reporting-catalog-store", "data"),
    )
    def render_viewer_report(view, records):
        model = open_model(view, records or [])
        if model is None:
            return [], [], None
        return report_header(model), report_toolbar(model), pdf_src(model["record"])

    @app.callback(
        Output("reporting-history-count", "children"),
        Output("reporting-history-table", "children"),
        Output("reporting-history-pager", "children"),
        Input("reporting-catalog-store", "data"),
        Input("reporting-his-technique", "value"),
        Input("reporting-his-system", "value"),
        Input("reporting-his-unit", "value"),
        Input("reporting-his-date", "value"),
        Input("reporting-his-state", "value"),
        Input("reporting-history-state", "data"),
    )
    def render_history(records, technique, system, unit, date, state, history_state):
        records = records or []
        if not records:
            return "", [], []
        history_state = {**DEFAULT_HISTORY_STATE, **(history_state or {})}
        shown = filter_history(records, technique, system, unit, date, state)
        ordered = sort_history(shown, history_state["sort"], history_state["dir"])
        page_rows, page, pages, start = paginate(ordered, history_state["page"], HISTORY_PAGE_SIZE)
        return (
            t("reporting.count", shown=len(shown), total=len(records)),
            history_table(page_rows, history_state["sort"], history_state["dir"]),
            history_pager(start, len(page_rows), len(shown), page, pages),
        )
