"""Piezas HTML de Reportabilidad: estado actual, informe de unidad e historial.

Funciones puras que reciben registros del catalogo y devuelven componentes de Dash;
los callbacks (dashboard/callbacks/reporting_callbacks.py) solo las llaman.

Todo lo que se pulsa y se vuelve a dibujar con cada filtro (fichas, tarjetas, filas de
la lista, botones del visor, cabeceras de la tabla) lleva `data-rp="<accion>"` y lo
atiende assets/reporting_actions.js, que lo deja en el Store `reporting-action`. Asi
no hay n_clicks que se reinicien al recrear los elementos. Las tarjetas y fichas son
enlaces de verdad (`href` con `?report=<clave>`): un clic normal abre el informe en la
pagina; abrir en pestaña nueva o copiar el enlace funciona.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from urllib.parse import urlencode

import dash
from dash import dcc, html

from dashboard.components.report_states import (
    ATTENTION_STATES, STATES_BY_SEVERITY, state_chip, state_dot, state_key, state_label, state_vars,
)
from src.data.report_health import NO_DATA
from src.data.report_view import ALL, HISTORY_COLUMNS, health_of
from src.i18n import t, t_or

SYSTEM_PATH = "/reporting"

# Parametros del visor PDF integrado (Chrome/Edge): sin su barra, sin panel lateral, ancho de pagina.
PDF_VIEWER_PARAMS = "#toolbar=0&navpanes=0&view=FitH"


def technique_label(technique: str) -> str:
    return t_or(f"reporting.technique.{technique}", technique.title())


def system_label(system: str) -> str:
    return t_or(f"nav.service.predictive-{system}.short", system.title())


def report_link(key: str) -> str:
    """URL de la pagina con ese informe abierto (para enlaces, pestaña nueva y compartir)."""
    return dash.get_relative_path(SYSTEM_PATH) + "?" + urlencode({"report": key})


def _open(key: str, context: str, focus: Optional[str] = None) -> dict:
    """Atributos de un elemento que abre un informe. `focus` es su identidad estable para devolverle el foco."""
    attrs = {"data-rp": "open", "data-rp-key": key, "data-rp-ctx": context}
    if focus:
        attrs["data-rp-focus"] = focus
    return attrs


def sources_text(record: dict) -> str:
    """Pie de la cabecera: el estado combinado y las dos fuentes que lo originan."""
    return t("reporting.state_sources",
             analysis=state_label(record.get("health_analysis")),
             curve=state_label(record.get("health_curve")))


def sources_detail(record: dict) -> str:
    """Tooltip del chip: de que dia y semana sale cada fuente."""
    parts = []
    if record.get("health_analysis"):
        parts.append(t("reporting.source_analysis_detail", week=record.get("health_analysis_week") or "-",
                       date=record.get("health_analysis_date") or "-"))
    if record.get("health_curve"):
        parts.append(t("reporting.source_curve_detail", date=record.get("health_curve_date") or "-"))
    return " · ".join(parts) if parts else t("reporting.health_missing")


def unit_count_text(count: int) -> str:
    return t("reporting.units_count_one") if count == 1 else t("reporting.units_count", count=count)


# ---------------------------------------------------------------------------
# Estado actual
# ---------------------------------------------------------------------------

def state_filter_row(counts: Dict[str, int], selected: str) -> html.Div:
    """`Todas` + un boton por estado con su conteo; actuan como filtro de las secciones."""
    def button(value: str, label: str, count: int, state: Optional[str]) -> html.Button:
        pressed = value == selected
        children = [state_dot(state)] if state else []
        children += [html.Span(label, className="rp-filter__label"), html.Span(count, className="rp-filter__count")]
        return html.Button(
            children,
            type="button",
            className="rp-filter" + (" rp-filter--active" if pressed else ""),
            style=state_vars(state) if state else None,
            **{"data-rp": "state", "data-rp-state": value, "data-rp-focus": f"state:{value}",
               "aria-pressed": "true" if pressed else "false"},
        )

    buttons = [button(ALL, t("reporting.state_all"), sum(counts.values()), None)]
    buttons += [button(state, state_label(state), counts.get(state, 0), state) for state in STATES_BY_SEVERITY]
    return html.Div(buttons, className="rp-filters", role="group", **{"aria-label": t("reporting.state_filter_aria")})


def attention_card(record: dict) -> html.A:
    state = health_of(record)
    meta = t("reporting.card_meta", system=system_label(record["system"]), date=record["date"])
    return html.A(
        [
            html.Span([
                html.Span(record["unit"], className="rp-card__unit"),
                state_chip(state, title=sources_detail(record)),
            ], className="rp-card__top"),
            html.Span(meta, className="rp-card__meta"),
            html.Span(t("reporting.view_report_arrow"), className="rp-card__cta"),
        ],
        href=report_link(record["key"]),
        className=f"rp-card rp-card--{state}",
        style=state_vars(state),
        **_open(record["key"], "current"),
    )


def clear_tile(record: dict, show_system: bool) -> html.A:
    state = health_of(record)
    system = system_label(record["system"])
    children = [state_dot(state), html.Span(record["unit"], className="rp-tile__unit")]
    if show_system:
        children.append(html.Span(system, className="rp-tile__system"))
    # Sin datos lo dice a la vista; Normal lo dice a lectores de pantalla (el color no es la unica señal).
    children.append(html.Span(state_label(state),
                              className="rp-tile__state" if state == NO_DATA else "rp-sr-only"))
    return html.A(
        children,
        href=report_link(record["key"]),
        className=f"rp-tile rp-tile--{state}",
        style=state_vars(state),
        title=f"{record['unit']} · {system} · {state_label(state)} · {t('reporting.card_meta', system=system, date=record['date'])}",
        **_open(record["key"], "current"),
    )


def _section(section_id: str, title: str, count: int, body: html.Div) -> html.Section:
    return html.Section([
        html.H3([title, html.Span(unit_count_text(count), className="rp-section__count")],
                id=section_id, className="rp-section__title"),
        body,
    ], className="rp-section", **{"aria-labelledby": section_id})


def overview_sections(attention: List[dict], clear: List[dict], show_system: bool) -> list:
    """Secciones "Requieren atencion" y "Sin alertas" + la frase de ayuda."""
    sections = []
    if attention:
        sections.append(_section("rp-attention-title", t("reporting.section_attention"), len(attention),
                                 html.Div([attention_card(r) for r in attention], className="rp-cards")))
    if clear:
        sections.append(_section("rp-clear-title", t("reporting.section_clear"), len(clear),
                                 html.Div([clear_tile(r, show_system) for r in clear], className="rp-tiles")))
    if not sections:
        sections.append(html.P(t("reporting.no_units"), className="rp-empty"))
    sections.append(html.P(t("reporting.overview_hint"), className="rp-hint"))
    return sections


# ---------------------------------------------------------------------------
# Informe de unidad
# ---------------------------------------------------------------------------

def viewer_list(model: dict, visible_rows: List[dict]) -> list:
    """Filas de la lista de la izquierda: unidad + chip; la abierta va resaltada."""
    caption = html.P(t("reporting.viewer_list_caption", date=model["list_date"]), className="rp-list__caption")
    if not visible_rows:
        return [caption, html.P(t("reporting.viewer_no_match"), className="rp-empty")]
    items = []
    for row in visible_rows:
        target = row["target"]
        if target is None:
            continue
        selected = row["selected"]
        items.append(html.Li(html.A(
            [html.Span(row["unit"], className="rp-row__unit"), state_chip(row["health"])],
            href=report_link(target["key"]),
            className="rp-row" + (" rp-row--selected" if selected else ""),
            **_open(target["key"], "keep", f"row:{row['unit']}"),
            **({"aria-current": "true"} if selected else {}),
        )))
    return [caption, html.Ul(items, className="rp-list__items")]


def _nav_button(label_key: str, aria_key: str, row: Optional[dict], arrow: str, focus: str) -> html.Button:
    text = t(label_key)
    inner = [html.Span(arrow, className="rp-nav__arrow", **{"aria-hidden": "true"}), text] if arrow == "←" \
        else [text, html.Span(arrow, className="rp-nav__arrow", **{"aria-hidden": "true"})]
    if row is None or row["target"] is None:
        return html.Button(inner, type="button", className="rp-btn", disabled=True)
    label = t(aria_key, unit=row["unit"])
    return html.Button(inner, type="button", className="rp-btn", title=label,
                       **_open(row["target"]["key"], "keep", focus), **{"aria-label": label})


def report_header(model: dict) -> html.Div:
    record = model["record"]
    state = health_of(record)
    position = model["position"]
    counter = t("reporting.position", n=position + 1 if position is not None else "–", total=model["total"])
    return html.Div([
        html.Div([
            html.Div([
                html.H2(record["unit"], className="rp-report__unit", tabIndex=-1),
                html.Span(f"{system_label(record['system'])} · {t('reporting.report_of', date=record['date'])}",
                          className="rp-report__meta"),
                state_chip(state, title=sources_detail(record), className="rp-chip--lg"),
            ], className="rp-report__title"),
            html.P(sources_text(record), className="rp-report__sources"),
        ], className="rp-report__heading"),
        html.Div([
            _nav_button("reporting.prev", "reporting.prev_aria", model["previous"], "←", "nav:prev"),
            html.Span(counter, className="rp-nav__counter", **{"aria-live": "polite"}),
            _nav_button("reporting.next", "reporting.next_aria", model["next"], "→", "nav:next"),
            html.Button([html.I(className="fas fa-xmark", **{"aria-hidden": "true"}), t("reporting.close_report")],
                        type="button", className="rp-btn rp-btn--close", **{"data-rp": "close"}),
        ], className="rp-nav"),
    ], className="rp-report__header")


def report_toolbar(model: dict) -> html.Div:
    record = model["record"]
    systems = [
        html.Button(
            system_label(system), type="button",
            className="rp-segment__btn" + (" rp-segment__btn--on" if system == record["system"] else ""),
            **_open(target["key"], "keep", f"system:{system}"),
            **{"aria-pressed": "true" if system == record["system"] else "false"},
        )
        for system, target in model["systems"] if target is not None
    ]
    dates = [
        html.Button(
            [state_dot(health_of(r)), html.Span(r["date"], className="rp-date__day"),
             html.Span(state_label(health_of(r)), className="rp-date__state")],
            type="button",
            className="rp-date" + (" rp-date--on" if r["key"] == record["key"] else ""),
            title=sources_detail(r),
            **_open(r["key"], "keep", f"date:{r['date']}"),
            **{"aria-pressed": "true" if r["key"] == record["key"] else "false"},
        )
        for r in model["dates"]
    ]
    return html.Div([
        html.Div([
            html.Div([
                html.Span(t("alerts_general.filter_system"), id="rp-system-label", className="rp-toolbar__label"),
                html.Div(systems, className="rp-segment", role="group", **{"aria-labelledby": "rp-system-label"}),
            ], className="rp-toolbar__group"),
            html.Div([
                html.A([html.I(className="fas fa-up-right-from-square", **{"aria-hidden": "true"}),
                        t("reporting.open_new_tab")],
                       href=record["href"], target="_blank", rel="noopener noreferrer", className="rp-btn"),
                html.A([html.I(className="fas fa-download", **{"aria-hidden": "true"}), t("reporting.download_pdf")],
                       href=record["download_href"], className="rp-btn rp-btn--primary"),
            ], className="rp-toolbar__actions"),
        ], className="rp-toolbar__row"),
        html.Div([
            html.Span(t("reporting.history_strip"), id="rp-history-label", className="rp-toolbar__label"),
            html.Div(dates, className="rp-dates", role="group", **{"aria-labelledby": "rp-history-label"}),
        ], className="rp-toolbar__history"),
    ], className="rp-toolbar")


def pdf_src(record: dict) -> str:
    return record["href"] + PDF_VIEWER_PARAMS


def viewer_shell() -> html.Div:
    """Esqueleto del visor: columna de la lista + informe. El contenido lo llenan los callbacks."""
    return html.Div([
        html.Aside([
            html.Label(t("reporting.viewer_list_label"), htmlFor="reporting-viewer-search", className="rp-list__label"),
            dcc.Input(id="reporting-viewer-search", type="search", value="", debounce=False, autoComplete="off",
                      placeholder=t("reporting.viewer_search_placeholder"), className="rp-input"),
            html.Div(id="reporting-viewer-list", className="rp-list__body"),
        ], className="rp-list", **{"aria-label": t("reporting.viewer_list_aria")}),
        html.Section([
            html.Div(id="reporting-report-header"),
            html.Div(id="reporting-report-toolbar"),
            html.Div(
                html.Iframe(id="reporting-pdf-frame", title=t("reporting.pdf_title"), className="rp-pdf__frame"),
                className="rp-pdf",
            ),
        ], className="rp-report", **{"aria-label": t("reporting.viewer_aria")}),
    ], className="rp-split")


# ---------------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------------

_SORT_ARIA = {"asc": "ascending", "desc": "descending"}


def history_table(rows: List[dict], sort: str, direction: str) -> html.Div:
    """Tabla con cabecera fija: Fecha, Unidad, Sistema, Estado (chip) y Acciones."""
    def header(column: str, label: str) -> html.Th:
        active = column == sort
        arrow = ("▲" if direction == "asc" else "▼") if active else "↕"
        return html.Th(
            html.Button([label, html.Span(arrow, className="rp-sort__arrow", **{"aria-hidden": "true"})],
                        type="button", className="rp-sort" + (" rp-sort--on" if active else ""),
                        **{"data-rp": "sort", "data-rp-col": column, "data-rp-focus": f"sort:{column}"}),
            scope="col",
            **{"aria-sort": _SORT_ARIA[direction] if active else "none"},
        )

    head = html.Thead(html.Tr([
        header("date", t("reporting.col_date")),
        header("unit", t("reporting.filter_unit")),
        header("system", t("alerts_general.filter_system")),
        header("health", t("reporting.col_health")),
        html.Th(t("reporting.col_actions"), scope="col"),
    ]))
    body = []
    for r in rows:
        label = t("reporting.download_aria", unit=r["unit"], date=r["date"])
        body.append(html.Tr([
            html.Td(r["date"]),
            html.Th(r["unit"], scope="row", className="rp-table__unit"),
            html.Td(system_label(r["system"])),
            html.Td(state_chip(health_of(r), title=sources_detail(r))),
            html.Td(html.Div([
                html.Button(t("reporting.view_report"), type="button", className="rp-btn rp-btn--sm",
                            **_open(r["key"], "record")),
                html.A(html.I(className="fas fa-download", **{"aria-hidden": "true"}),
                       href=r["download_href"], className="rp-icon-btn", title=label, **{"aria-label": label}),
            ], className="rp-table__actions")),
        ]))
    if not body:
        body = [html.Tr(html.Td(t("reporting.table_empty"), colSpan=5, className="rp-table__empty"))]
    return html.Div(html.Table([head, html.Tbody(body)], className="rp-table"), className="rp-table__wrap",
                    tabIndex=0, role="region", **{"aria-label": t("reporting.history_table_aria")})


def history_pager(start: int, shown: int, total: int, page: int, pages: int) -> html.Div:
    end = start + shown - 1 if shown else 0
    return html.Div([
        html.Span(t("reporting.showing", start=start, end=end, total=total), className="rp-pager__label"),
        html.Div([
            html.Button(t("reporting.prev"), type="button", className="rp-btn rp-btn--sm", disabled=page <= 1,
                        **{"data-rp": "page", "data-rp-page": page - 1, "data-rp-focus": "page:prev"}),
            html.Span(t("reporting.page_of", page=page, pages=pages), className="rp-pager__page"),
            html.Button(t("reporting.next"), type="button", className="rp-btn rp-btn--sm", disabled=page >= pages,
                        **{"data-rp": "page", "data-rp-page": page + 1, "data-rp-focus": "page:next"}),
        ], className="rp-pager__nav"),
    ], className="rp-pager")


__all__ = [
    "ATTENTION_STATES", "HISTORY_COLUMNS", "attention_card", "clear_tile", "history_pager", "history_table",
    "overview_sections", "pdf_src", "report_header", "report_link", "report_toolbar", "state_filter_row",
    "state_key", "system_label", "technique_label", "viewer_list", "viewer_shell",
]
