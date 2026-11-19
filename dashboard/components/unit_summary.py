"""
Unit Detail (Resumen > Unidad): per-unit drill-down, laid out as a master-detail view.

Opening a unit (from a Fleet Overview row, or an item of the list below) shows two panels: the
list of the fleet's units on the left - searchable, grouped by Estado, each group collapsible -
and the selected unit's detail on the right, headed by the unit id and its Estado with
Anterior / n of total / Siguiente / Cerrar Unidad. Under 900 px the list stacks above the detail.
The detail keeps the banner identifying the unit (its Estado, monitored components, horometro and
last sample) and the per-technique content built by dashboard/components/unit_summary_content.py.

The unit is still the URL's (`/overview/unit/<id>`), so every item, Anterior and Siguiente
change it through Dash Pages' client-side router (dcc.Link): switching units never reloads the
page. What is on screen - the search text, which groups are open, and therefore which units
Anterior / Siguiente move through - is browser-side state kept by assets/unit_master_detail.js,
which also carries it from one unit to the next (the page is rebuilt on every navigation).
"""

from datetime import datetime
from typing import Optional

from src.i18n import current_language, t
import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard.components.fleet_overview import band_css, band_slug, get_ordered_units
from dashboard.components.labels import status_label
from dashboard.components.status_chip import canonical_status, status_chip
from dashboard.components.unit_summary_content import (
    build_unit_summary_content,
    last_sample_date,
    monitored_components,
)
from dashboard.services_registry import nav_path, relative_path, unit_summary_path
from src.data.unit_horometer import unit_horometer
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Shown where a banner value is missing.
NO_VALUE = "—"


# The list's search box (assets/unit_master_detail.js finds it by this id).
SEARCH_ID = "unit-list-search"

# Groups the list opens with: the ones that need attention, plus the one holding the unit.
_OPEN_BY_DEFAULT = ("Anormal", "Alerta")

_BAND_ICONS = {
    "Anormal": "fas fa-exclamation-circle", "Alerta": "fas fa-exclamation-triangle",
    "Normal": "fas fa-check-circle", "Sin Datos": "fas fa-question-circle",
}


def _close_link() -> dcc.Link:
    """"Cerrar Unidad": back to the general view (the Fleet Overview table)."""
    return dcc.Link(
        [html.I(className="fas fa-xmark me-1", **{"aria-hidden": "true"}), t("unit_summary.cerrar_unidad")],
        href=relative_path(nav_path("overview-general")),
        className="unit-btn unit-btn--close",
    )


def _bands_in_order(ordered: list) -> list:
    """`(band, [entries])` in list order: the order `ordered` already has (band, then unit)."""
    groups: dict = {}
    for entry in ordered:
        groups.setdefault(entry["band"], []).append(entry)
    return list(groups.items())


def _open_bands(ordered: list, unit: Optional[str]) -> set:
    """The groups the list is rendered open in (the browser then applies the user's own choice)."""
    selected_band = next((e["band"] for e in ordered if e["unit"] == unit), None)
    return {band for band, _ in _bands_in_order(ordered) if band in _OPEN_BY_DEFAULT or band == selected_band}


def _unit_item(entry: dict, selected: bool) -> html.Li:
    """One unit of the list: a real link (a `dcc.Link`, so it navigates through the router)
    showing the unit id and its Estado chip."""
    unit = entry["unit"]
    return html.Li(
        dcc.Link(
            [html.Span(unit, className="unit-item__id"), status_chip(entry["band"])],
            href=relative_path(unit_summary_path(unit)),
            # (assets/unit_master_detail.js marks the selected link `aria-current="page"`: dcc.Link
            # has no such property.)
            className="unit-item" + (" unit-item--selected" if selected else ""),
        ),
        **{"data-unit-item": unit},
    )


def _unit_group(band: str, entries: list, unit: Optional[str], expanded: bool) -> html.Div:
    """One Estado group: a toggle button (real `<button aria-expanded aria-controls>`) with the
    group's title and unit count, and the list of its units."""
    slug = band_slug(band)
    body_id = f"unit-group-body-{slug}"
    return html.Div([
        html.Button([
            html.Span(html.I(className=_BAND_ICONS.get(band, "fas fa-circle")),
                      className=f"icon-badge icon-badge--{band_css(band)}", **{"aria-hidden": "true"}),
            html.Span(status_label(band), className="unit-group__title"),
            html.Span(f"({len(entries)})", className="unit-group__count", **{"data-unit-group-count": len(entries)}),
            html.I(className="fas fa-chevron-down unit-group__chevron", **{"aria-hidden": "true"}),
        ], type="button", className="unit-group__header", **{
            "data-unit-group-toggle": "true", "aria-expanded": "true" if expanded else "false", "aria-controls": body_id,
        }),
        html.Ul([_unit_item(e, e["unit"] == unit) for e in entries], id=body_id, className="unit-group__items",
                hidden=not expanded),
    ], className="unit-group", **{"data-unit-group": band})


def _unit_list(ordered: list, unit: Optional[str]) -> html.Aside:
    """The master panel: "Buscar Unidad", "Estado al <fecha>" and the units grouped by Estado."""
    open_bands = _open_bands(ordered, unit)
    return html.Aside([
        html.Label(t("unit_summary.buscar_unidad"), htmlFor=SEARCH_ID, className="unit-list__label"),
        dcc.Input(id=SEARCH_ID, type="search", value="", debounce=False, autoComplete="off",
                  className="form-control form-control-sm"),
        html.P(t("unit_summary.estado_al", date=datetime.now().strftime("%d/%m/%Y")), className="unit-list__caption"),
        html.P(t("unit_summary.sin_coincidencias"), className="unit-list__empty", role="status", hidden=True,
               **{"data-unit-no-match": "true"}),
        html.Div([_unit_group(band, entries, unit, band in open_bands) for band, entries in _bands_in_order(ordered)],
                 className="unit-list__groups"),
    ], className="unit-list", **{"aria-label": t("unit_summary.unidades"), "data-unit-list": unit or ""})


def _nav_button(kind: str, label: str, icon: str, icon_after: bool, enabled: bool) -> html.Button:
    """Anterior / Siguiente: a real `<button>`; the browser script points it at the neighbouring
    shown unit and disables it at either end of the shown units (`data-unit-nav`)."""
    glyph = html.I(className=f"{icon} {'ms-1' if icon_after else 'me-1'}", **{"aria-hidden": "true"})
    return html.Button([label, glyph] if icon_after else [glyph, label], type="button",
                       className="unit-btn", disabled=not enabled, **{"data-unit-nav": kind})


def _detail_header(ordered: list, unit: str, estado: str) -> html.Div:
    """Unit id and Estado, then Anterior / "n / total" / Siguiente / Cerrar Unidad. What this is
    rendered with is what the browser script starts from; it then follows the shown units."""
    open_bands = _open_bands(ordered, unit)
    shown = [e["unit"] for e in ordered if e["band"] in open_bands]
    position = shown.index(unit) if unit in shown else None
    counter = t("unit_summary.posicion", n=position + 1 if position is not None else "–", total=len(shown))
    return html.Div([
        html.Div([
            html.H2(unit, className="unit-detail__unit"),
            status_chip(estado),
        ], className="unit-detail__identity"),
        html.Div([
            _nav_button("prev", t("unit_summary.anterior"), "fas fa-chevron-left", False,
                        position is not None and position > 0),
            html.Span(counter, className="unit-detail__position", role="status", **{
                "data-unit-position": "true",
                # The text the browser script fills in as the shown units change.
                "data-unit-position-format": t("unit_summary.posicion", n="{n}", total="{total}"),
            }),
            _nav_button("next", t("unit_summary.siguiente"), "fas fa-chevron-right", True,
                        position is not None and position < len(shown) - 1),
            _close_link(),
        ], className="unit-detail__controls"),
    ], className="unit-detail__header")


def _format_hours(hours: float) -> str:
    """"116.846 h" in Spanish, "116,846 h" in English."""
    grouped = f"{hours:,.0f}"
    if current_language() == "es":
        grouped = grouped.replace(",", ".")
    return t("unit_summary.hours_value", value=grouped)


def _banner_item(label: str, value: str, note: Optional[str] = None) -> html.Div:
    """A labeled fact of the banner; `note` is a small visible line under the value."""
    return html.Div([
        html.Dt(label),
        html.Dd([value, html.Span(note, className="unit-banner__note")] if note else value),
    ], className="unit-banner__item")


def _banner(client: str, unit: str, estado: str) -> html.Section:
    """Unit identification: id, Estado, number of monitored components, the unit's horómetro and
    the last oil sample. The banner takes the color of the unit's Estado (Alerta orange, Anormal
    deep red, anything else neutral). A value that cannot be resolved shows "—"."""
    components = monitored_components(client, unit)
    horometer = unit_horometer(client, unit)
    sample = last_sample_date(client, unit)
    items = [
        _banner_item(t("unit_summary.componentes_monitoreados"), str(len(components)) if components else NO_VALUE),
        _banner_item(
            t("unit_summary.horometro"),
            _format_hours(horometer.hours) if horometer else NO_VALUE,
            note=(t("unit_summary.horometro_as_of", date=horometer.as_of.strftime("%d/%m/%Y"))
                  if horometer and horometer.as_of else None),
        ),
        _banner_item(t("unit_summary.ultima_muestra"), sample.strftime("%d/%m/%Y") if sample is not None else NO_VALUE),
    ]
    tier = canonical_status(estado)
    on_dark = tier in ("Alerta", "Anormal")
    return html.Section([
        html.Div([
            html.Span(html.I(className="fas fa-truck"), className="icon-badge icon-badge--nodata unit-banner__icon",
                      **{"aria-hidden": "true"}),
            html.Div([
                html.Div(t("unit_summary.unidad"), className="unit-banner__eyebrow"),
                html.H1(unit, className="unit-banner__title"),
            ]),
            html.Div([
                html.Div(t("fleet_overview.col_status"), className="unit-banner__eyebrow"),
                status_chip(estado, solid=not on_dark, on_dark=on_dark),
            ], className="unit-banner__estado"),
        ], className="unit-banner__identity"),
        html.Dl(items, className="unit-banner__facts"),
    ], className=f"unit-banner unit-banner--{tier.replace(' ', '').lower()}", **{"aria-label": t("unit_summary.unidad")})


def build_unit_summary(client: str, unit: str) -> html.Div:
    """Build the Unit Detail for `unit`, or an explanatory empty
    state if the client/unit combination can't be resolved."""
    if not client:
        return dbc.Alert([
            html.I(className="fas fa-arrow-up me-2"), t("unit_summary.seleccione_un_cliente_para_ver_el"),
        ], color="info", className="text-center m-4")
    try:
        return _build_unit_summary(client, unit)
    except Exception:
        logger.exception("Error building Unit Summary for client=%s unit=%s", client, unit)
        return dbc.Alert([
            html.I(className="fas fa-exclamation-triangle me-2"), t("unit_summary.error_al_generar_el_resumen_de"),
        ], color="danger", className="text-center m-4")


def _empty_state(message: str) -> html.Div:
    return html.Div([
        dbc.Alert([html.I(className="fas fa-info-circle me-2"), message], color="info", className="text-center"),
        html.Div(_close_link(), className="text-center"),
    ], className="p-4")


def _split(ordered: list, unit: Optional[str], detail) -> html.Div:
    return html.Div([
        _unit_list(ordered, unit),
        html.Section(detail, className="unit-detail", **{"aria-label": t("unit_summary.detalle_de_la_unidad")}),
    ], className="unit-split")


def _build_unit_summary(client: str, unit: str) -> html.Div:
    ordered = get_ordered_units(client)
    if not ordered:
        return _empty_state(t("unit_summary.no_hay_unidades_disponibles_para_este"))

    snapshot = next((entry for entry in ordered if entry["unit"] == unit), None)
    if snapshot is None:
        # The list stays usable, so the user can pick another unit.
        return _split(ordered, None, dbc.Alert(
            [html.I(className="fas fa-info-circle me-2"), t("unit_summary.la_unidad_no_se_encuentra_para", unit=unit)],
            color="info", className="text-center m-4",
        ))

    # The banner's Estado is the unit's, the same one the Fleet Overview row shows.
    banner = _banner(client, unit, snapshot["overall_status"])

    # Per-technique content, isolated from the header in its own try/except so a content
    # failure degrades to an inline error card instead of blanking the whole shell (the
    # list, header and banner stay usable either way). Every status in it is read from the
    # same snapshot as the banner's Estado and the Fleet Overview - never recalculated
    # independently (documentation/general/general_specs/
    # 05_unit_summary_restructure_and_predictive_comparison.md, Functional Rules).
    try:
        body = build_unit_summary_content(client, unit, technique_status=snapshot.get("technique_status"))
    except Exception:
        logger.exception("Error building Unit Summary content for client=%s unit=%s", client, unit)
        body = dbc.Alert([
            html.I(className="fas fa-exclamation-triangle me-2"),
            t("unit_summary.error_al_generar_el_contenido_de"),
        ], color="danger", className="text-center")

    return _split(ordered, unit, [_detail_header(ordered, unit, snapshot["overall_status"]), banner, body])
