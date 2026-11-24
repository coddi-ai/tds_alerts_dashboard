"""Monitor de Aceite > Panel de Frecuencia: building the data and drawing it.

The rules (what is due, what is "Sin muestra", the order) live in `src/data/sampling_frequency.py`;
this module turns the filters into a plain, JSON-safe structure (kept client-side in a store) and that
structure into the KPI tiles, the "Grupos de Criticidad" card and the main table.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd
from dash import html
import dash_bootstrap_components as dbc

from config.settings import get_settings
from dashboard.components.labels import display_component_name
from dashboard.components.oil_table import (
    PAGE_SIZE,
    DESC,
    new_revision,
    page_slice,
    pager,
    sortable_th,
)
from dashboard.components.oil_ui import kpi_tile, severity_chip
from shared.severity import SEVERITY_TIERS
from src.data import sampling_frequency as sf
from src.data.loaders import load_oil_classified
from src.i18n import t
from src.utils.logger import get_logger

logger = get_logger(__name__)

TABLE = "freq"

# Natural direction of the first click on each header.
FIRST_DIRS = {
    "unit_id": "asc", "component": "asc", "group": "asc", "last_sample": "asc", "days_since": DESC,
    "interval_pct": DESC, "due_date": "asc", "days_to_due": "asc", "avg_hist": DESC, "status": "asc",
}

# The word each state shows (chip and filter), the tile that counts it and its severity tier.
_STATUS_LABEL = {
    sf.SOLICITAR: "frequency.estado_solicitar_muestra",
    sf.PROXIMA: "frequency.estado_proxima_a_vencer",
    sf.AL_DIA: "frequency.estado_al_dia",
    sf.SIN_MUESTRA: "frequency.estado_sin_muestra",
}
MISSING = "—"


def status_text(status: str) -> str:
    return t(_STATUS_LABEL[status])


def group_label(days: int) -> str:
    return t("frequency.cada_n_dias", days=days)


def group_short_label(days: int) -> str:
    return t("frequency.n_dias", days=days)


def component_label(name) -> str:
    return display_component_name(name)


# ---------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------

def _iso(value) -> Optional[str]:
    return None if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")


def serialize_rows(rows: pd.DataFrame) -> List[dict]:
    """Rows as JSON-safe records (dates as ISO text, missing values as None)."""
    records = []
    for r in rows.itertuples(index=False):
        records.append({
            "unit_id": r.unit_id, "machine": r.machine, "site": None if pd.isna(r.site) else r.site,
            "component": r.component, "component_normalized": r.component_normalized,
            "group": r.group, "group_days": int(r.group_days),
            "last_sample": _iso(r.last_sample),
            "days_since": None if pd.isna(r.days_since) else int(r.days_since),
            "interval_pct": None if pd.isna(r.interval_pct) else float(r.interval_pct),
            "due_date": _iso(r.due_date),
            "days_to_due": None if pd.isna(r.days_to_due) else int(r.days_to_due),
            "avg_hist": None if pd.isna(r.avg_hist) else float(r.avg_hist),
            "status": r.status,
        })
    return records


def frame_from_records(records: List[dict]) -> pd.DataFrame:
    """The inverse of `serialize_rows`, restoring the dtypes `sampling_frequency.sort_rows` expects."""
    frame = pd.DataFrame(records, columns=sf.ROW_COLUMNS)
    if frame.empty:
        return frame
    frame["last_sample"] = pd.to_datetime(frame["last_sample"])
    frame["due_date"] = pd.to_datetime(frame["due_date"])
    frame["days_since"] = frame["days_since"].astype("Int64")
    frame["days_to_due"] = frame["days_to_due"].astype("Int64")
    frame["interval_pct"] = frame["interval_pct"].astype("float64")
    frame["avg_hist"] = frame["avg_hist"].astype("Float64")
    return frame


def _message(key: str, as_of: Optional[str] = None) -> dict:
    return {"rev": new_revision(), "message": key, "as_of": as_of, "rows": []}


def build_frequency_data(client, site=None, fleet=None, component=None, group=None, status=None, today=None) -> dict:
    """What the panel shows for these filters, in the default (urgency) order.

    With no Flota selected nothing is displayed (as in Visión de Flota). `message` is the i18n key of
    an empty-state text; `as_of` is the client's latest reportDate.
    """
    if not client:
        return _message("fleet_overview.select_client")
    if not get_settings().get_classified_reports_path(client.lower()).exists():
        return _message("lab_compliance_callbacks.sin_datos_disponibles")
    try:
        classified = load_oil_classified(client)
        as_of = _iso(sf.data_as_of(classified))
        if not fleet:
            return _message("frequency.seleccione_una_flota", as_of)
        config = sf.load_config()
        all_rows = sf.build_frequency_rows(classified, config, today)
        rows = sf.sort_rows(sf.filter_rows(all_rows, site, fleet, component, group, status))
        summaries = sf.group_summaries(rows, config)
        return {
            "rev": new_revision(), "message": None if len(rows) else "frequency.sin_filas", "as_of": as_of,
            "rows": serialize_rows(rows), "counts": sf.status_counts(rows), "total": int(len(rows)),
            "groups": [
                {"key": s.group.key, "days": s.group.days, "total": s.total, "overdue": s.overdue,
                 "components": s.components, "avg": s.avg_between_samples}
                for s in summaries
            ],
        }
    except sf.FrequencyConfigError as exc:
        logger.error("Sampling frequency configuration: %s", exc)
        return {**_message("frequency.error_de_configuracion"), "detail": str(exc)}
    except Exception:
        logger.exception("Frequency panel error")
        return _message("frequency.error_al_cargar")


def filter_options(client, site=None, fleet=None) -> Dict[str, list]:
    """Dropdown options (sites, fleets, components) for the cascade of filters."""
    empty = {"sites": [], "fleets": [], "components": []}
    if not client or not get_settings().get_classified_reports_path(client.lower()).exists():
        return empty
    try:
        df = load_oil_classified(client)
        sites = sorted(df["site"].dropna().unique().tolist()) if "site" in df.columns else []
        scoped = df[df["site"] == site] if site and "site" in df.columns else df
        fleets = sorted(scoped["machineName"].dropna().unique().tolist())
        components: List[str] = []
        if fleet:
            rows = sf.build_frequency_rows(df, sf.load_config())
            rows = sf.filter_rows(rows, site, fleet)
            components = sorted({str(c) for c in rows["component"]}, key=str.casefold) if not rows.empty else []
        return {"sites": sites, "fleets": fleets, "components": components}
    except Exception:
        logger.exception("Frequency filter options error")
        return empty


# ---------------------------------------------------------------------------------------------
# KPI tiles and the criticality card
# ---------------------------------------------------------------------------------------------

def _share(count: int, total: int) -> float:
    return count * 100.0 / total if total else 0.0


def render_kpis(data: dict) -> dbc.Row:
    counts, total = data.get("counts", {}), data.get("total", 0)
    caption = t("frequency.de_n_componentes", total=total)
    tiles = [
        (sf.SOLICITAR, "frequency.kpi_vencidas", "frequency.chip_solicitar_muestra", "alto", "fa-bell"),
        (sf.PROXIMA, "frequency.kpi_proximas_a_vencer", "frequency.chip_atencion", "atencion", "fa-hourglass-half"),
        (sf.AL_DIA, "frequency.kpi_al_dia", "frequency.chip_sin_accion", "bajo", "fa-check-circle"),
        (sf.SIN_MUESTRA, "frequency.kpi_sin_historial", "frequency.chip_revisar", None, "fa-question-circle"),
    ]
    cols = []
    for status, label_key, chip_key, tier, icon in tiles:
        count = int(counts.get(status, 0))
        cols.append(dbc.Col(
            kpi_tile(t(label_key), str(count), icon=icon, tier=tier, chip=t(chip_key),
                     gauge_pct=_share(count, total), caption=caption),
            xs=12, sm=6, lg=3, className="mb-3",
        ))
    return dbc.Row(cols, className="g-3")


def render_group_card(data: dict) -> dbc.Card:
    blocks = []
    groups = data.get("groups", [])
    width = max(1, 12 // max(1, len(groups)))
    for g in groups:
        blocks.append(dbc.Col(
            html.Div([
                html.Div(group_label(g["days"]), className="oil-group-card__title"),
                html.Div(t("frequency.x_de_n_vencidas", vencidas=g["overdue"], total=g["total"]),
                         className="oil-group-card__stat"),
                html.Div(t("frequency.componentes_asignados"), className="oil-group-card__label"),
                html.Div(", ".join(component_label(c) for c in g["components"]) or MISSING,
                         className="oil-group-card__value"),
                html.Div(t("frequency.promedio_historico_entre_muestras"), className="oil-group-card__label"),
                html.Div(sf.format_days(g["avg"]), className="oil-group-card__value"),
            ], className="oil-group-card"),
            md=width, className="mb-3",
        ))
    return dbc.Card(dbc.CardBody([
        html.H5(t("frequency.grupos_de_criticidad"), className="fw-bold mb-3"),
        dbc.Row(blocks, className="g-3"),
    ]), className="shadow-sm mb-4")


# ---------------------------------------------------------------------------------------------
# Main table
# ---------------------------------------------------------------------------------------------

_TIER_BY_STATUS = sf.SEVERITY_BY_STATUS


def _percent_text(pct: float) -> str:
    return "999+ %" if pct > 999 else f"{int(pct)} %"    # whole percent, rounded down: 79.9 % is still "79 %"


def vencimiento_text(days_to_due: Optional[int]) -> str:
    if days_to_due is None:
        return MISSING
    if days_to_due > 0:
        return t("frequency.vence_en", dias=days_to_due)
    if days_to_due == 0:
        return t("frequency.vence_hoy")
    return t("frequency.vencida_hace", dias=-days_to_due)


def _bar(pct: float, status: str) -> html.Div:
    tier = SEVERITY_TIERS[_TIER_BY_STATUS[status]]
    return html.Div([
        html.Div(html.Div(className="oil-bar__fill", style={"width": f"{min(100.0, pct):.1f}%", "background": tier["fill"]}),
                 className="oil-bar", role="progressbar",
                 **{"aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": f"{min(100.0, pct):.0f}",
                    "aria-label": t("frequency.col_intervalo_consumido")}),
        html.Span(_percent_text(pct), className="oil-bar__pct"),
    ], className="oil-bar-cell")


def _status_chip(status: str) -> html.Span:
    return severity_chip(_TIER_BY_STATUS.get(status), status_text(status))


def _row_cells(row: dict) -> list:
    missing = row["status"] == sf.SIN_MUESTRA
    dash = html.Span(MISSING, className="text-muted", **{"aria-label": t("frequency.sin_dato")})
    last = (dash if missing else html.Button(
        row["last_sample"], id={"type": f"{TABLE}-open", "unit": row["unit_id"], "component": row["component"]},
        className="oil-link-btn", type="button", n_clicks=0,
        title=t("frequency.abrir_reporte", unidad=row["unit_id"], componente=component_label(row["component"]))))
    return [
        html.Th(row["unit_id"], scope="row", className="oil-col-left"),
        html.Td(component_label(row["component"]), className="oil-col-left"),
        html.Td(group_short_label(row["group_days"]), className="oil-col-center"),
        html.Td(last, className="oil-col-center"),
        html.Td(dash if missing else str(row["days_since"]), className="oil-col-center"),
        html.Td(dash if missing else _bar(row["interval_pct"], row["status"])),
        html.Td(dash if missing else row["due_date"], className="oil-col-center"),
        html.Td(dash if missing else vencimiento_text(row["days_to_due"]), className="oil-col-center"),
        html.Td(dash if row["avg_hist"] is None else sf.format_days(row["avg_hist"]), className="oil-col-center"),
        html.Td(_status_chip(row["status"]), className="oil-col-center"),
    ]


def _columns() -> list:
    return [
        ("unit_id", t("frequency.col_unidad"), "left"),
        ("component", t("frequency.col_componente"), "left"),
        ("group", t("frequency.col_criticidad"), "center"),
        ("last_sample", t("frequency.col_ultima_muestra"), "center"),
        ("days_since", t("frequency.col_dias_desde_ultima_muestra"), "center"),
        ("interval_pct", t("frequency.col_intervalo_consumido"), "center"),
        ("due_date", t("frequency.col_fecha_limite"), "center"),
        ("days_to_due", t("frequency.col_vencimiento"), "center"),
        ("avg_hist", t("frequency.col_promedio_historico"), "center"),
        ("status", t("frequency.col_estado"), "center"),
    ]


def render_frequency_table(data: Optional[dict], view: Optional[dict]):
    """`(table block, sort note, rows chip)`: the main table for the stored rows and the view."""
    if not data:
        return html.Div(), "", ""
    if data.get("message") or not data.get("rows"):
        key = data.get("message") or "frequency.sin_filas"
        text = t(key) + (f" {data['detail']}" if data.get("detail") else "")
        return html.P(text, className="text-muted text-center py-4"), "", ""
    frame = frame_from_records(data["rows"])
    sort = (view or {}).get("sort")
    ordered = sf.sort_rows(frame, (sort or {}).get("col"), (sort or {}).get("dir") != DESC)
    records = serialize_rows(ordered)
    page_rows, page, _ = page_slice(records, view)

    columns = _columns()
    header = html.Tr([sortable_th(TABLE, col_id, label, view, align=align) for col_id, label, align in columns])
    body = [html.Tr(_row_cells(row)) for row in page_rows]
    table = html.Div(
        html.Table([html.Thead(header), html.Tbody(body)], className="oil-table",
                   **{"aria-label": t("frequency.estado_de_muestreo")}),
        className="oil-table-wrap",
    )
    labels = {col_id: label for col_id, label, _ in columns}
    note = (t("frequency.ordenado_por_columna", columna=labels.get(sort["col"], sort["col"]))
            if sort and sort.get("col") else t("frequency.ordenado_por_urgencia"))
    chip = html.Span(t("frequency.n_filas", n=len(records)), className="kpi-chip oil-neutral-chip")
    return html.Div([table, pager(TABLE, page=page, total_rows=len(records), page_size=PAGE_SIZE)]), note, chip
