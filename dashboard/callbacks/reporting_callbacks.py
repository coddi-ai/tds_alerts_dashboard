"""
Callbacks de Reportes > Reportabilidad (dashboard/pages/reporting_main.py).

Flujo: al cambiar de cliente (o con "Actualizar") se lista su carpeta de S3 una
vez, se le agrega el estado de salud de cada unidad (src/data/report_health.py) y
el catalogo queda en `reporting-catalog-store`; el lote destacado, la tabla y la
previsualizacion trabajan sobre ese catalogo sin volver a S3. El PDF se muestra en
un iframe que apunta a la ruta de dashboard/report_files.py, que repite la
autorizacion en cada apertura.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from config.client_services import normalize_client_id
from dashboard.components.labels import status_label
from dashboard.report_files import report_file_href, reporting_available, visible_systems
from dashboard.tabs.tab_predictive_overview import _status_colors
from src.data.report_health import HEALTH_STATES, attach_health
from src.data.report_store import TECHNIQUE_SYSTEMS, get_report_store, unit_sort_key
from src.i18n import t, t_or
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Lotes visibles como botones; los mas antiguos quedan en el filtro de fecha.
MAX_BATCH_BUTTONS = 8

SYSTEM_ICONS = {"motor": "fa-cog", "transmision": "fa-cogs"}

# Valor del filtro de estado para "sin dato" (None no sirve como valor de dropdown).
NO_HEALTH = "sin_dato"

# Columnas de la tabla que no abren la previsualizacion al hacer clic.
_NO_PREVIEW_COLUMNS = {"download"}


def technique_label(technique: str) -> str:
    return t_or(f"reporting.technique.{technique}", technique.title())


def system_label(system: str) -> str:
    return t_or(f"nav.service.predictive-{system}.short", system.title())


def health_label(health: Optional[str]) -> str:
    return status_label(health) if health else t("status.no_data")


def health_colors(health: Optional[str]) -> dict:
    """Paleta del Predictivo (border/bg/text); gris para "sin dato"."""
    return _status_colors((health or "").capitalize())


def health_detail(record: dict) -> str:
    if not record.get("health"):
        return t("reporting.health_missing")
    return t("reporting.health_source", week=record["health_week"], date=record["health_date"])


def health_badge(health: Optional[str], text: Optional[str] = None, title: Optional[str] = None,
                 **style) -> html.Span:
    colors = health_colors(health)
    return html.Span(
        text or health_label(health),
        title=title,
        style={
            "backgroundColor": colors["bg"], "color": colors["text"], "border": f"1px solid {colors['border']}",
            "borderRadius": "999px", "padding": "2px 10px", "fontSize": "0.8rem", "fontWeight": 600,
            "whiteSpace": "nowrap", **style,
        },
    )


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


def _ordered_systems(records: List[dict]) -> List[tuple]:
    present = {(r["technique"], r["system"]) for r in records}
    return [(tech, system) for tech, systems in TECHNIQUE_SYSTEMS.items() for system in systems
            if (tech, system) in present]


def _health_counts(records: List[dict]) -> list:
    """Pildoras con el conteo por estado, del mas grave al mas sano."""
    pills = []
    for health in (*HEALTH_STATES, None):
        count = sum(1 for r in records if r.get("health") == health)
        if count:
            pills.append(health_badge(health, f"{count} {health_label(health)}",
                                      marginLeft="6px", textTransform="none", letterSpacing="0"))
    return pills


def build_batch(records: List[dict], date: str):
    """Un boton por unidad para un lote, coloreado por estado y agrupado por sistema."""
    batch = [r for r in records if r["date"] == date]
    if not batch:
        return html.P(t("reporting.no_batch"), className="text-muted mb-0")

    groups = []
    for technique, system in _ordered_systems(batch):
        units = sorted((r for r in batch if r["technique"] == technique and r["system"] == system),
                       key=lambda r: unit_sort_key(r["unit"]))
        groups.append(html.Div([
            html.H6([
                html.I(className=f"fas {SYSTEM_ICONS.get(system, 'fa-file-pdf')} me-2"),
                f"{technique_label(technique)} · {system_label(system)}",
                *_health_counts(units),
            ], className="text-muted text-uppercase mb-2 d-flex flex-wrap align-items-center",
                style={"fontSize": "0.85rem", "letterSpacing": "0.5px"}),
            html.Div([
                html.Button(
                    [html.I(className="fas fa-file-pdf me-1"), r["unit"]],
                    id={"type": "reporting-open", "key": r["key"]},
                    n_clicks=0,
                    title=f"{health_label(r.get('health'))} · {health_detail(r)}",
                    className="btn btn-sm",
                    style={
                        "backgroundColor": health_colors(r.get("health"))["bg"],
                        "color": health_colors(r.get("health"))["text"],
                        "border": f"1px solid {health_colors(r.get('health'))['border']}",
                        "fontWeight": 600,
                    },
                )
                for r in units
            ], className="d-flex flex-wrap gap-2 mb-3"),
        ]))
    groups.append(html.P(t("reporting.batch_hint"), className="text-muted small mb-0"))
    return html.Div(groups)


def filter_records(records: List[dict], technique, system, units, date, health=None) -> List[dict]:
    units = set(units or [])
    health = set(health or [])
    return [
        r for r in records
        if (not technique or r["technique"] == technique)
        and (not system or r["system"] == system)
        and (not units or r["unit"] in units)
        and (not date or r["date"] == date)
        and (not health or (r.get("health") or NO_HEALTH) in health)
    ]


def table_rows(records: List[dict]) -> List[dict]:
    return [{
        "id": r["key"],
        "date": r["date"],
        "unit": r["unit"],
        "system": system_label(r["system"]),
        "health": health_label(r.get("health")),
        "health_raw": r.get("health") or NO_HEALTH,
        "preview": _icon_cell("fa-eye", "btn-outline-primary", t("reporting.preview")),
        "download": _icon_cell("fa-download", "btn-outline-secondary", t("reporting.download"),
                               href=r["download_href"]),
    } for r in records]


def _icon_cell(icon: str, style: str, label: str, href: Optional[str] = None) -> str:
    """Boton de icono para una celda markdown; con `href` es un enlace (la descarga)."""
    tag, link = ("a", f' href="{href}"') if href else ("span", "")
    return (f'<{tag}{link} class="btn btn-sm {style} py-0 px-2" title="{label}" aria-label="{label}">'
            f'<i class="fas {icon}"></i></{tag}>')


def health_cell_styles() -> List[dict]:
    """Color de la celda Estado segun el valor crudo (columna oculta `health_raw`)."""
    styles = []
    for health in (*HEALTH_STATES, NO_HEALTH):
        colors = health_colors(None if health == NO_HEALTH else health)
        styles.append({
            "if": {"filter_query": f'{{health_raw}} = "{health}"', "column_id": "health"},
            "backgroundColor": colors["bg"], "color": colors["text"], "fontWeight": "bold",
        })
    return styles


def preview_target(trigger, records: List[dict], current_key: Optional[str],
                   active_cell: Optional[dict], date_value: Optional[str], system_value: Optional[str]) -> Optional[dict]:
    """Registro a previsualizar segun lo que disparo el callback, o None."""
    by_key = {r["key"]: r for r in records}
    if isinstance(trigger, dict) and trigger.get("type") == "reporting-open":
        return by_key.get(trigger.get("key"))
    if trigger == "reporting-datatable":
        if not active_cell or active_cell.get("column_id") in _NO_PREVIEW_COLUMNS:
            return None
        return by_key.get(active_cell.get("row_id"))

    current = by_key.get(current_key)
    if current is None:
        return None
    if trigger == "reporting-preview-date":
        wanted = {"date": date_value}
    elif trigger == "reporting-preview-system":
        wanted = {"system": system_value}
    else:
        return None
    for record in records:
        if record["technique"] == current["technique"] and record["unit"] == current["unit"] and all(
            record[field] == current[field] if field not in wanted else record[field] == wanted[field]
            for field in ("system", "date")
        ):
            return record
    return None


def preview_title(record: dict) -> list:
    return [
        html.I(className="fas fa-file-pdf me-2 text-danger"),
        record["unit"],
        html.Span(f"· {system_label(record['system'])} · {record['date']}", className="text-muted fw-normal ms-2"),
        health_badge(record.get("health"), title=health_detail(record), marginLeft="12px", verticalAlign="middle"),
    ]


def register_reporting_callbacks(app: dash.Dash) -> None:
    """Catalogo por cliente, lote destacado, tabla filtrable y previsualizacion."""

    @app.callback(
        Output("reporting-catalog-store", "data"),
        Output("reporting-status", "children"),
        Output("reporting-body", "style"),
        Output("reporting-filter-technique", "options"),
        Output("reporting-filter-technique", "value"),
        Output("reporting-filter-system", "options"),
        Output("reporting-filter-system", "value"),
        Output("reporting-filter-unit", "options"),
        Output("reporting-filter-unit", "value"),
        Output("reporting-filter-date", "options"),
        Output("reporting-filter-date", "value"),
        Output("reporting-filter-health", "options"),
        Output("reporting-filter-health", "value"),
        Output("reporting-batch-date", "options"),
        Output("reporting-batch-date", "value"),
        Input("client-selector", "value"),
        Input("reporting-refresh", "n_clicks"),
        State("user-info-store", "data"),
        State("reporting-batch-date", "value"),
    )
    def load_reporting_catalog(selected_client, _refresh_clicks, user_data, current_batch):
        if not user_data:
            raise PreventUpdate
        user_clients = user_data.get("clients", [])
        client = selected_client or (user_clients[0] if user_clients else "")
        refresh = ctx.triggered_id == "reporting-refresh"
        records, notice = load_catalog(client, user_clients, refresh=refresh)

        techniques = [tech for tech in TECHNIQUE_SYSTEMS if any(r["technique"] == tech for r in records)]
        systems = list(dict.fromkeys(system for _, system in _ordered_systems(records)))
        units = sorted({r["unit"] for r in records}, key=unit_sort_key)
        dates = sorted({r["date"] for r in records}, reverse=True)
        present_health = {r.get("health") or NO_HEALTH for r in records}
        healths = [h for h in (*HEALTH_STATES, NO_HEALTH) if h in present_health]

        # "Actualizar" no cambia de cliente: conserva el lote y los filtros elegidos.
        keep = refresh and current_batch in dates
        return (
            records,
            notice,
            {} if records else {"display": "none"},
            [{"label": technique_label(tech), "value": tech} for tech in techniques],
            techniques[0] if techniques else None,
            [{"label": system_label(s), "value": s} for s in systems],
            no_update if refresh else None,
            [{"label": u, "value": u} for u in units],
            no_update if refresh else [],
            [{"label": d, "value": d} for d in dates],
            no_update if refresh else None,
            [{"label": health_label(None if h == NO_HEALTH else h), "value": h} for h in healths],
            no_update if refresh else [],
            [{"label": d, "value": d} for d in dates[:MAX_BATCH_BUTTONS]],
            current_batch if keep else (dates[0] if dates else None),
        )

    @app.callback(
        Output("reporting-latest", "children"),
        Input("reporting-batch-date", "value"),
        Input("reporting-catalog-store", "data"),
    )
    def render_reporting_batch(batch_date, records):
        if not records or not batch_date:
            return html.P(t("reporting.no_batch"), className="text-muted mb-0")
        return build_batch(records, batch_date)

    @app.callback(
        Output("reporting-datatable", "data"),
        Output("reporting-count", "children"),
        Input("reporting-catalog-store", "data"),
        Input("reporting-filter-technique", "value"),
        Input("reporting-filter-system", "value"),
        Input("reporting-filter-unit", "value"),
        Input("reporting-filter-date", "value"),
        Input("reporting-filter-health", "value"),
    )
    def render_reporting_table(records, technique, system, units, date, health):
        records = records or []
        shown = filter_records(records, technique, system, units, date, health)
        return table_rows(shown), t("reporting.count", shown=len(shown), total=len(records))

    @app.callback(
        Output("reporting-preview-modal", "is_open"),
        Output("reporting-preview-key", "data"),
        Output("reporting-preview-title", "children"),
        Output("reporting-preview-frame", "src"),
        Output("reporting-preview-open", "href"),
        Output("reporting-preview-download", "href"),
        Output("reporting-preview-date", "options"),
        Output("reporting-preview-date", "value"),
        Output("reporting-preview-system", "options"),
        Output("reporting-preview-system", "value"),
        Output("reporting-datatable", "active_cell"),
        Input({"type": "reporting-open", "key": ALL}, "n_clicks"),
        Input("reporting-datatable", "active_cell"),
        Input("reporting-preview-date", "value"),
        Input("reporting-preview-system", "value"),
        State("reporting-catalog-store", "data"),
        State("reporting-preview-key", "data"),
        prevent_initial_call=True,
    )
    def open_reporting_preview(_clicks, active_cell, date_value, system_value, records, current_key):
        trigger = ctx.triggered_id
        # Los botones del lote se recrean con n_clicks=0 al cambiar de fecha: eso no es un clic.
        if isinstance(trigger, dict) and not (ctx.triggered and ctx.triggered[0].get("value")):
            raise PreventUpdate
        record = preview_target(trigger, records or [], current_key, active_cell, date_value, system_value)
        if record is None:
            # Limpia la celda activa para que un segundo clic en la misma fila vuelva a abrir.
            if trigger == "reporting-datatable" and active_cell:
                return (no_update,) * 10 + (None,)
            raise PreventUpdate

        same_unit = [r for r in records if r["technique"] == record["technique"] and r["unit"] == record["unit"]]
        dates = sorted({r["date"] for r in same_unit if r["system"] == record["system"]}, reverse=True)
        dates = dates[:MAX_BATCH_BUTTONS] if record["date"] in dates[:MAX_BATCH_BUTTONS] else             sorted({*dates[:MAX_BATCH_BUTTONS - 1], record["date"]}, reverse=True)
        systems = [s for _, s in _ordered_systems([r for r in same_unit if r["date"] == record["date"]])]
        return (
            True,
            record["key"],
            preview_title(record),
            record["href"] + "#view=FitH",
            record["href"],
            record["download_href"],
            [{"label": d, "value": d} for d in dates],
            record["date"],
            [{"label": system_label(s), "value": s} for s in systems],
            record["system"],
            None,
        )
