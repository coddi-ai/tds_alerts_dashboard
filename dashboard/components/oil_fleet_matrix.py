"""Visión de Flota: the "Estado por Componente y Máquina" matrix.

Units are rows, components are columns, and a cell is the latest sample's status plus the days
since it. `build_fleet_matrix_data` turns the filters into plain data (stored client-side),
`render_fleet_matrix` turns that data and the view (sort, page) into the table.

Two rules of the requirement live here:
  * "Estado Máquina" sits right after "Unidad", and the component columns are ordered by how many
    of the units that pass the filters have data for them, most covered first (ties alphabetical).
  * every interaction is resolved from the unit and component written in the button's own id, so
    page 2, a re-sorted or a filtered table open the unit that was actually clicked.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import pandas as pd
from dash import html

from config.settings import get_settings
from dashboard.components.labels import status_label
from dashboard.components.labels import display_component_name
from dashboard.components.oil_table import (
    DESC,
    PAGE_SIZE,
    new_revision,
    pager,
    page_slice,
    sortable_th,
)
from dashboard.components.oil_ui import (
    canonical_estado,
    estado_badge,
    estado_severity_tier,
    estado_surface,
    severity_style,
)
from src.data.loaders import load_machine_status_for_client, load_oil_classified
from src.i18n import t
from src.i18n.data_text import localized_series
from src.utils.logger import get_logger

logger = get_logger(__name__)

TABLE = "fleet"                      # prefix of the table's stores and pattern ids
UNIT_COL = "unit_id"
STATUS_COL = "machine_status"

# Higher = worse. A cell with no sample has no rank and always sorts last.
SEVERITY_RANK = {"Anormal": 3, "Alerta": 2, "Normal": 1}

# First click on a header: units A-Z, everything else worst first.
FIRST_DIRS = {UNIT_COL: "asc", "*": DESC}


def infer_machine_status(statuses: Iterable) -> str:
    """The worst of the component statuses, when the machine has no status of its own."""
    values = {s for s in statuses if isinstance(s, str)}
    if "Anormal" in values:
        return "Anormal"
    if "Alerta" in values:
        return "Alerta"
    return "Normal"


def order_components_by_coverage(pivot: pd.DataFrame, columns: Iterable[str]) -> List[str]:
    """`columns` ordered by how many units (rows of `pivot`) have a status for each, most first.

    `pivot` is units x components holding the latest status (empty where a unit was never sampled
    for that component) and must already be restricted to the units that pass the active filters:
    coverage is counted over all of them, whatever page is shown. Ties are broken alphabetically
    by component name so the order is deterministic.
    """
    columns = [c for c in columns if c in pivot.columns]
    coverage = pivot[columns].notna().sum() if columns else pd.Series(dtype=int)
    return sorted(columns, key=lambda c: (-int(coverage[c]), str(c).casefold(), str(c)))


def _latest_by_pair(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["sampleDate"] = pd.to_datetime(df["sampleDate"])
    return df.loc[df.groupby(["unitId", "componentName"])["sampleDate"].idxmax()]


def _machine_status_map(client: str) -> Dict[str, str]:
    settings = get_settings()
    if not settings.get_machine_status_path(client.lower()).exists():
        return {}
    try:
        ms_df = load_machine_status_for_client(client)
        return dict(zip(ms_df["unit_id"], ms_df["overall_status"]))
    except Exception:
        logger.exception("Machine status could not be read for %s", client)
        return {}


def _message(key: str) -> dict:
    return {"rev": new_revision(), "message": key, "columns": [], "rows": []}


def build_fleet_matrix_data(client, site, fleet, statuses, selected_components, today=None) -> dict:
    """The matrix for these filters: ordered component columns and one entry per unit.

    `message` carries the i18n key of an empty-state text when there is nothing to show.
    """
    if not client:
        return _message("fleet_overview.select_client")
    if not fleet:
        return _message("machines_callbacks.seleccione_una_flota_para_ver_el")
    settings = get_settings()
    if not settings.get_classified_reports_path(client.lower()).exists():
        return _message("lab_compliance_callbacks.sin_datos_disponibles")

    try:
        df = load_oil_classified(client)
        if site:
            df = df[df["site"] == site]
        df = df[df["machineName"] == fleet]
        if df.empty:
            return _message("machines_callbacks.sin_datos_para_la_flota_seleccionada")

        latest = _latest_by_pair(df)
        now = pd.Timestamp.now().normalize() if today is None else pd.Timestamp(today).normalize()
        ms_map = _machine_status_map(client)

        pivot = latest.pivot_table(index="unitId", columns="componentName", values="report_status", aggfunc="first")
        pivot[STATUS_COL] = [ms_map.get(u) if canonical_estado(ms_map.get(u)) else infer_machine_status(pivot.loc[u])
                             for u in pivot.index]
        if statuses:
            pivot = pivot[pivot[STATUS_COL].isin(statuses)]
        if pivot.empty:
            return _message("machines_callbacks.sin_datos_para_los_filtros_seleccionados")

        component_cols = [c for c in pivot.columns if c != STATUS_COL]
        shown = [c for c in (selected_components or []) if c in component_cols] or component_cols
        columns = order_components_by_coverage(pivot, shown)

        days = latest.set_index(["unitId", "componentName"])["sampleDate"].apply(lambda d: int((now - d.normalize()).days))
        rank = {"Anormal": 0, "Alerta": 1, "Normal": 2}
        units = sorted(pivot.index, key=lambda u: (rank.get(pivot.loc[u, STATUS_COL], 3), str(u)))

        rows = []
        for unit in units:
            cells = {}
            for col in columns:
                status = pivot.loc[unit, col]
                if pd.notna(status):
                    cells[col] = {"s": status, "d": int(days.get((unit, col), 0))}
            rows.append({"id": unit, "machine_status": pivot.loc[unit, STATUS_COL], "cells": cells})
        return {"rev": new_revision(), "message": None, "client": client, "site": site, "fleet": fleet,
                "columns": columns, "rows": rows}
    except Exception:
        logger.exception("Fleet matrix error")
        return _message("machines_callbacks.error_al_cargar_la_matriz")


def sort_matrix_rows(rows: List[dict], sort: Optional[dict]) -> List[dict]:
    """The rows in the requested order. Without a sort they keep the order they were built in
    (worst machine first, then unit). A row with nothing to sort on goes last in either direction."""
    if not sort or not sort.get("col"):
        return list(rows)
    col, descending = sort["col"], sort.get("dir") == DESC

    if col == UNIT_COL:
        def key(row):
            return (str(row["id"]).casefold(), str(row["id"]))
    elif col == STATUS_COL:
        def key(row):
            return SEVERITY_RANK.get(canonical_estado(row["machine_status"]))
    else:
        def key(row):
            cell = row["cells"].get(col)
            return SEVERITY_RANK.get(canonical_estado(cell["s"])) if cell else None

    present = [r for r in rows if key(r) is not None]
    missing = [r for r in rows if key(r) is None]
    return sorted(present, key=key, reverse=descending) + missing


def recommendations(data: dict, units: Iterable[str]) -> Dict[tuple, str]:
    """AI recommendations (the cells' hover text) of the units on the visible page only."""
    units = list(units)
    client = data.get("client")
    if not client or not units:
        return {}
    try:
        df = load_oil_classified(client)
        if data.get("site"):
            df = df[df["site"] == data["site"]]
        df = df[(df["machineName"] == data.get("fleet")) & (df["unitId"].isin(units))]
        if df.empty or "ai_recommendation" not in df.columns:
            return {}
        latest = _latest_by_pair(df)
        latest = latest.assign(ai_recommendation=localized_series(latest, "ai_recommendation"))
        return {(r["unitId"], r["componentName"]): str(r["ai_recommendation"])[:300]
                for _, r in latest.iterrows() if pd.notna(r["ai_recommendation"])}
    except Exception:
        logger.exception("Recommendations could not be read")
        return {}


def _component_label(component: str) -> str:
    return display_component_name(component)


def _cell(unit: str, component: str, cell: Optional[dict], tip: Optional[str]):
    if not cell:
        return html.Td(html.Span(t("oil_fleet.sin_muestra"), className="oil-cell-empty"), className="oil-col-center")
    estado = canonical_estado(cell["s"]) or cell["s"]
    text = f"{status_label(estado)} · {cell['d']} d"
    style = {**severity_style(estado_severity_tier(estado))}
    return html.Td(
        html.Button(
            text,
            id={"type": f"{TABLE}-cell", "unit": unit, "component": component},
            className="oil-cell-btn",
            type="button",
            n_clicks=0,
            title=tip or None,
            style={"background": style["background"], "color": style["color"], "borderColor": style["borderColor"]},
            **{"aria-label": t("oil_fleet.celda_aria", unidad=unit, componente=_component_label(component),
                               estado=status_label(estado), dias=cell["d"])},
        ),
        className="oil-col-center",
    )


def _estado_cell(estado):
    surface = estado_surface(estado)
    return html.Td(estado_badge(estado), className="oil-estado-cell",
                   style={"background": surface["background"], "color": surface["color"]})


def render_fleet_matrix(data: Optional[dict], view: Optional[dict], selected_unit: Optional[str]):
    """`(table block, rows chip)` for the stored data and view."""
    if not data:
        return html.P(t("fleet_overview.select_client"), className="text-muted"), ""
    if data.get("message"):
        return html.P(t(data["message"]), className="text-muted text-center py-4"), ""

    rows = sort_matrix_rows(data["rows"], (view or {}).get("sort"))
    page_rows, page, _ = page_slice(rows, view)
    columns = data["columns"]
    tips = recommendations(data, [r["id"] for r in page_rows])

    header = html.Tr([
        html.Th(html.Span(t("oil_fleet.seleccionar"), className="visually-hidden"), scope="col"),
        sortable_th(TABLE, UNIT_COL, t("alerts_general.filter_unit"), view, align="left"),
        sortable_th(TABLE, STATUS_COL, t("machines_callbacks.estado_maquina"), view),
        *[sortable_th(TABLE, col, _component_label(col), view) for col in columns],
    ])
    body = []
    for row in page_rows:
        unit = row["id"]
        selected = unit == selected_unit
        body.append(html.Tr(
            [
                html.Td(html.Button(
                    id={"type": f"{TABLE}-select", "unit": unit}, className="oil-select", type="button", n_clicks=0,
                    title=t("oil_fleet.seleccionar_unidad", unidad=unit),
                    **{"aria-pressed": "true" if selected else "false",
                       "aria-label": t("oil_fleet.seleccionar_unidad", unidad=unit)},
                ), className="oil-col-center"),
                html.Th(html.Button(unit, id={"type": f"{TABLE}-unit", "unit": unit}, className="oil-unit-btn",
                                    type="button", n_clicks=0,
                                    title=t("oil_fleet.abrir_detalle_maquina", unidad=unit)),
                        scope="row", className="oil-col-left"),
                _estado_cell(row["machine_status"]),
                *[_cell(unit, col, row["cells"].get(col), tips.get((unit, col))) for col in columns],
            ],
            className="oil-row--selected" if selected else None,
        ))

    table = html.Div(
        html.Table([html.Thead(header), html.Tbody(body)], className="oil-table",
                   **{"aria-label": t("tab_machines.estado_por_componente_y_maquina")}),
        className="oil-table-wrap",
    )
    block = html.Div([table, pager(TABLE, page=page, total_rows=len(rows), page_size=PAGE_SIZE)])
    chip = html.Span(t("machines_callbacks.maquinas", len_records=len(rows)), className="kpi-chip oil-neutral-chip ms-2")
    return block, chip
