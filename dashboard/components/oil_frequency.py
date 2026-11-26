"""Monitor de Aceite > Panel de Frecuencia: building the data and drawing it.

The rules (what is due, what is "Sin muestra", the order of units and components) live in
`src/data/sampling_frequency.py`; this module turns the filters into a plain, JSON-safe structure (kept
client-side in a store) and that structure into the KPI tiles, the "Criterios de Criticidad" card and
the unit list.

The unit is the primary row; its components are the detail, one click away. Every unit is its own
`<tbody>` holding the unit row and a hidden detail row. Opening and closing a detail is done in the
browser (assets/oil_expandable_rows.js, on real `<button aria-expanded>`s), so the button keeps the
keyboard focus and no server round trip is spent on it.
"""

from __future__ import annotations

import hashlib
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
from dashboard.components.oil_ui import NEUTRAL, kpi_tile, severity_chip
from shared.severity import SEVERITY_TIERS
from src.data import sampling_frequency as sf
from src.data.loaders import load_oil_classified
from src.i18n import t
from src.utils.logger import get_logger

logger = get_logger(__name__)

TABLE = "freq"
UNITS_ID = "freq-table-container"      # the element holding the unit list (the expand/collapse-all button targets it)

# Natural direction of the first click on each header. "late" ascending = most overdue first.
FIRST_DIRS = {"unit_id": "asc", "status": "asc", "pending": DESC, "late": "asc", "latest": DESC}

# The word each state shows (chip and filter).
_STATUS_LABEL = {
    sf.SOLICITAR: "frequency.estado_solicitar_muestra",
    sf.PROXIMA: "frequency.estado_proxima_a_vencer",
    sf.AL_DIA: "frequency.estado_al_dia",
    sf.SIN_MUESTRA: "frequency.estado_sin_muestra",
}
_TIER_BY_STATUS = sf.SEVERITY_BY_STATUS      # Sin muestra has none: it is the neutral tone
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
    """Component rows as JSON-safe records (dates as ISO text, missing values as None)."""
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


def _message(key: str, as_of: Optional[str] = None) -> dict:
    return {"rev": new_revision(), "message": key, "as_of": as_of, "rows": [], "units": []}


def build_frequency_data(client, site=None, fleet=None, component=None, group=None, status=None, today=None) -> dict:
    """What the panel shows for these filters.

    `rows` are the matching components (in the order a unit's detail lists them) and `units` one summary
    per unit of those components, in the default order; every unit figure is computed over the matching
    components only. With no Flota selected nothing is displayed (as in Visión de Flota). `message` is
    the i18n key of an empty-state text; `as_of` is the client's latest reportDate.
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
        units = sf.summarize_units(rows)
        summaries = sf.group_summaries(rows, config)
        return {
            "rev": new_revision(), "message": None if len(rows) else "frequency.sin_filas", "as_of": as_of,
            "rows": serialize_rows(rows), "units": units, "counts": sf.status_counts(rows), "total": int(len(rows)),
            "n_units": len(units), "pending_units": sum(1 for unit in units if unit["solicitar"]),
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
    """Five tiles: units with pending samples (counts units), then four component counts."""
    counts, components = data.get("counts", {}), data.get("total", 0)
    units = data.get("n_units", 0)
    caption_units = t("frequency.de_n_unidades", total=units)
    caption_components = t("frequency.de_n_componentes", total=components)
    # (label, count, total, caption, chip, severity tier, icon)
    tiles = [
        ("frequency.kpi_unidades_con_pendientes", data.get("pending_units", 0), units, caption_units,
         "frequency.chip_solicitar_muestra", "alto", "fa-truck"),
        ("frequency.kpi_componentes_vencidos", counts.get(sf.SOLICITAR, 0), components, caption_components,
         "frequency.chip_solicitar_muestra", "alto", "fa-bell"),
        ("frequency.kpi_proximos_a_vencer", counts.get(sf.PROXIMA, 0), components, caption_components,
         "frequency.chip_atencion", "atencion", "fa-hourglass-half"),
        ("frequency.kpi_al_dia", counts.get(sf.AL_DIA, 0), components, caption_components,
         "frequency.chip_sin_accion", "bajo", "fa-check-circle"),
        ("frequency.kpi_sin_historial", counts.get(sf.SIN_MUESTRA, 0), components, caption_components,
         "frequency.chip_revisar", None, "fa-question-circle"),
    ]
    cols = [
        dbc.Col(
            kpi_tile(t(label), str(int(count)), icon=icon, tier=tier, chip=t(chip),
                     gauge_pct=_share(int(count), total), caption=caption),
            xs=12, sm=6, lg=True, className="mb-3",
        )
        for label, count, total, caption, chip, tier, icon in tiles
    ]
    return dbc.Row(cols, className="g-3 oil-kpis--aligned")      # a two-line label must not push its number down


def render_criteria_card(data: dict) -> dbc.Card:
    """"Criterios de Criticidad": one block per group, over the filtered rows. It is the reference for
    reading every status, so it stays above the list."""
    blocks = []
    groups = data.get("groups", [])
    width = max(1, 12 // max(1, len(groups)))
    for g in groups:
        blocks.append(dbc.Col(
            html.Div([
                html.Div(group_label(g["days"]), className="oil-group-card__title"),
                html.Div(", ".join(component_label(c) for c in g["components"]) or MISSING,
                         className="oil-group-card__components"),
                html.Div([
                    html.Span(t("frequency.x_de_n_vencidas", vencidas=g["overdue"], total=g["total"]),
                              className="oil-group-card__figure"),
                    html.Span(t("frequency.promedio_historico_n", dias=sf.format_days(g["avg"])),
                              className="oil-group-card__figure"),
                ], className="oil-group-card__stats"),
            ], className="oil-group-card"),
            md=width, className="mb-2",
        ))
    return dbc.Card(dbc.CardBody([
        html.H5(t("frequency.criterios_de_criticidad"), className="fw-bold mb-2"),
        dbc.Row(blocks, className="g-2"),
        html.P(t("frequency.criterios_nota"), className="oil-footnote mb-0"),
    ]), className="shadow-sm mb-4")


# ---------------------------------------------------------------------------------------------
# Unit list
# ---------------------------------------------------------------------------------------------

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


def _dash() -> html.Span:
    return html.Span(MISSING, className="text-muted", role="img", **{"aria-label": t("frequency.sin_dato")})


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


# The stacked bar of a unit: vencidos, próximos, al día, sin muestra (the key of each count in a unit summary).
_STACK = ((sf.SOLICITAR, "solicitar"), (sf.PROXIMA, "proxima"), (sf.AL_DIA, "al_dia"), (sf.SIN_MUESTRA, "sin_muestra"))


def _stack(unit: dict) -> html.Div:
    """Components of the unit split by status. The same split is spelled out for assistive technology
    and as a tooltip: the colors are never the only signal."""
    total = unit["total"]
    segments = []
    for status, key in _STACK:
        count = unit[key]
        if not count:
            continue
        tier = _TIER_BY_STATUS.get(status)
        fill = SEVERITY_TIERS[tier]["fill"] if tier else NEUTRAL["fill"]
        segments.append(html.Span(className="oil-stack__segment",
                                  style={"width": f"{count * 100.0 / total:.2f}%", "background": fill}))
    label = t("frequency.barra_de_estados", vencidos=unit["solicitar"], proximos=unit["proxima"],
              al_dia=unit["al_dia"], sin_muestra=unit["sin_muestra"])
    return html.Div(segments, className="oil-stack", role="img", title=label, **{"aria-label": label})


def late_text(unit: dict) -> Optional[str]:
    """"Más Atrasado": "<Componente> · vencida hace N d" / "· vence en N d" / "· vence hoy"."""
    if unit["late_component"] is None:
        return None
    days = unit["late_days_to_due"]
    name = component_label(unit["late_component"])
    if days < 0:
        return t("frequency.mas_atrasado_vencida", componente=name, dias=-days)
    if days == 0:
        return t("frequency.mas_atrasado_vence_hoy", componente=name)
    return t("frequency.mas_atrasado_vence_en", componente=name, dias=days)


def _detail_id(unit_id: str) -> str:
    return "freq-detail-" + hashlib.md5(str(unit_id).encode("utf-8")).hexdigest()[:12]


def _component_cells(row: dict) -> list:
    """The cells of one component of a unit's detail. The date opens that component's last report; the
    unit and component come from the button's own id, never from the position of the row."""
    missing = row["status"] == sf.SIN_MUESTRA
    last = (_dash() if missing else html.Button(
        row["last_sample"], id={"type": f"{TABLE}-open", "unit": row["unit_id"], "component": row["component"]},
        className="oil-link-btn", type="button", n_clicks=0,
        title=t("frequency.abrir_reporte", unidad=row["unit_id"], componente=component_label(row["component"]))))
    return [
        html.Th(component_label(row["component"]), scope="row", className="oil-col-left"),
        html.Td(group_short_label(row["group_days"]), className="oil-col-center"),
        html.Td(last, className="oil-col-center"),
        html.Td(_dash() if missing else str(row["days_since"]), className="oil-col-center"),
        html.Td(_dash() if missing else _bar(row["interval_pct"], row["status"]), className="oil-col-center"),
        html.Td(_dash() if missing else row["due_date"], className="oil-col-center"),
        html.Td(_dash() if missing else vencimiento_text(row["days_to_due"]), className="oil-col-center"),
        html.Td(_dash() if row["avg_hist"] is None else sf.format_days(row["avg_hist"]), className="oil-col-center"),
        html.Td(_status_chip(row["status"]), className="oil-col-center"),
    ]


def _detail_table(unit_id: str, components: List[dict]) -> html.Table:
    headers = [
        ("frequency.col_componente", "left"), ("frequency.col_criticidad", "center"),
        ("frequency.col_ultima_muestra", "center"), ("frequency.col_dias", "center"),
        ("frequency.col_intervalo_consumido", "center"), ("frequency.col_fecha_limite", "center"),
        ("frequency.col_vencimiento", "center"), ("frequency.col_promedio", "center"),
        ("frequency.col_estado", "center"),
    ]
    head = html.Tr([html.Th(t(key), scope="col", className=f"oil-col-{align}") for key, align in headers])
    return html.Table(
        [html.Thead(head), html.Tbody([html.Tr(_component_cells(row)) for row in components])],
        className="oil-table oil-table--detail", **{"aria-label": t("frequency.componentes_de", unidad=unit_id)},
    )


def _unit_body(unit: dict, components: List[dict]) -> html.Tbody:
    """One unit: its row and, hidden under it, the table of its components."""
    unit_id = unit["unit_id"]
    detail_id = _detail_id(unit_id)
    toggle = html.Button(
        html.I(className="fas fa-chevron-right oil-expand__icon", **{"aria-hidden": "true"}),
        className="oil-expand", type="button",
        **{"aria-expanded": "false", "aria-controls": detail_id, "data-oil-expand": "1",
           "aria-label": t("frequency.detalle_de", unidad=unit_id)},
    )
    late = late_text(unit)
    latest = (_dash() if unit["latest_sample"] is None else
              t("frequency.fecha_hace", fecha=unit["latest_sample"], dias=unit["latest_days"]))
    row = html.Tr([
        html.Td(toggle, className="oil-col-center"),
        html.Th(unit_id, scope="row", className="oil-col-left"),
        html.Td(_status_chip(unit["status"]), className="oil-col-center"),
        html.Td(html.Div([
            html.Span(t("frequency.n_de_m", n=unit["solicitar"], m=unit["total"]), className="oil-pending__count"),
            _stack(unit),
        ], className="oil-pending"), className="oil-col-center"),
        html.Td(_dash() if late is None else late, className="oil-col-left"),
        html.Td(latest, className="oil-col-center"),
    ], className="oil-unit__row")
    detail = html.Tr(
        html.Td(html.Div(_detail_table(unit_id, components), className="oil-detail"), colSpan=6),
        id=detail_id, className="oil-unit__detail", hidden=True,
    )
    return html.Tbody([row, detail], className="oil-unit")


def _columns() -> list:
    """The sortable columns of the unit list (the Detalle column is a button, not a value)."""
    return [
        ("unit_id", t("frequency.col_unidad"), "left"),
        ("status", t("frequency.col_estado"), "center"),
        ("pending", t("frequency.col_componentes_por_solicitar"), "center"),
        ("late", t("frequency.col_mas_atrasado"), "left"),
        ("latest", t("frequency.col_muestra_mas_reciente"), "center"),
    ]


def render_frequency_table(data: Optional[dict], view: Optional[dict]):
    """`(unit list block, sort note, units chip)`: the list for the stored units and the view."""
    if not data:
        return html.Div(), "", ""
    if data.get("message") or not data.get("units"):
        key = data.get("message") or "frequency.sin_filas"
        text = t(key) + (f" {data['detail']}" if data.get("detail") else "")
        return html.P(text, className="text-muted text-center py-4"), "", ""
    sort = (view or {}).get("sort") or {}
    units = sf.sort_units(data["units"], sort.get("col"), sort.get("dir") != DESC)
    page_units, page, _ = page_slice(units, view)

    by_unit: Dict[str, List[dict]] = {}
    for row in data["rows"]:                       # already in the order a unit's detail lists them
        by_unit.setdefault(row["unit_id"], []).append(row)

    columns = _columns()
    header = html.Tr(
        [html.Th(t("frequency.col_detalle"), scope="col", className="oil-col-center")]
        + [sortable_th(TABLE, col_id, label, view, align=align) for col_id, label, align in columns]
    )
    table = html.Div(
        html.Table(
            [html.Thead(header)] + [_unit_body(unit, by_unit.get(unit["unit_id"], [])) for unit in page_units],
            className="oil-table oil-table--units", **{"aria-label": t("frequency.estado_de_muestreo")},
        ),
        className="oil-table-wrap",
    )
    labels = {col_id: label for col_id, label, _ in columns}
    note = (t("frequency.ordenado_por_columna", columna=labels.get(sort["col"], sort["col"]))
            if sort.get("col") else t("frequency.ordenado_por_urgencia"))
    chip = html.Span(t("frequency.n_unidades_m_componentes", n=len(units), m=len(data["rows"])),
                     className="kpi-chip oil-neutral-chip")
    return html.Div([table, pager(TABLE, page=page, total_rows=len(units), page_size=PAGE_SIZE)]), note, chip
