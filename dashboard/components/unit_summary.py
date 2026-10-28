"""
Unit Detail (Resumen > Unidad): per-unit drill-down.

Implements documentation/general/general_specs/02_unit_summary_navigation_shell.md as
revised by the Unit Detail requirements of ui_notes_improved.md: entry from a Fleet
Overview row, a navigation bar (breadcrumb, return to the Fleet Overview, previous / next
and a labeled unit selector) that sits in the page flow and never covers content, and a
banner identifying the unit: its Estado, monitored components, horómetro and last sample.
All navigation goes through Dash Pages' client-side router (dcc.Link for links, the shared
assets/client_nav.js for the selector), so switching units or returning to the Fleet
Overview never triggers a full page reload.

Content (status tiles, per-technique cards) is built by
dashboard/components/unit_summary_content.py and assembled into the body below.
"""

from typing import Optional

from src.i18n import current_language, t
import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard.components.fleet_overview import get_ordered_units, get_unit_snapshot
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


def _back_link():
    """Return-to-Fleet-Overview control. Part of the navigation bar, so it is available
    from anywhere in the Unit Detail (Functional Rules: "available from anywhere ...
    not only from a specific sub-tab or scroll position")."""
    return dcc.Link([
        html.I(className="fas fa-arrow-left me-2"), t("unit_summary.volver_a_fleet_overview"),
    ], href=relative_path(nav_path("overview-general")),
        className="unit-summary-back-link btn btn-outline-secondary btn-sm",
        style={"whiteSpace": "nowrap"})


def _nav_control(label: str, icon: str, target_unit, disabled_text: str, icon_after: bool = False):
    """One prev/next lateral-navigation control (Required Changes #4)."""
    def content(text):
        glyph = html.I(className=f"{icon} {'ms-1' if icon_after else 'me-1'}", **{"aria-hidden": "true"})
        return [text, glyph] if icon_after else [glyph, text]

    if target_unit is None:
        return html.Span(content(disabled_text), className="text-muted small unit-nav__disabled",
                         **{"aria-disabled": "true"})
    return dcc.Link(
        content(label),
        href=relative_path(unit_summary_path(target_unit)),
        className="btn btn-outline-secondary btn-sm", style={"whiteSpace": "nowrap"},
    )


def _unit_selector(ordered: list, current_unit: str):
    """"Cambiar unidad": a real `<select>` with its `<label for>`. Each option's value is the
    unit's URL; picking one navigates through the router (assets/client_nav.js)."""
    options = [
        html.Option(
            f"{entry['unit']} · {status_label(entry['band'])}",
            value=relative_path(unit_summary_path(entry["unit"])),
            selected=(entry["unit"] == current_unit),
        )
        for entry in ordered
    ]
    return html.Div([
        html.Label(t("unit_summary.cambiar_unidad"), htmlFor="unit-switcher", className="unit-nav__label"),
        html.Select(options, id="unit-switcher", className="form-select form-select-sm unit-nav__select",
                    **{"data-unit-nav": "true"}),
    ], className="unit-nav__switcher")


def _navigation_bar(ordered: list, unit: str, prev_unit: Optional[str], next_unit: Optional[str]) -> html.Div:
    """Breadcrumb on the left; Volver, Anterior / Primera unidad, Cambiar unidad and
    Siguiente on the right. It is part of the page flow - not sticky, nothing overlays the
    sections below it."""
    breadcrumb = html.Nav(
        html.Ol([
            html.Li(dcc.Link(t("unit_summary.fleet_overview"), href=relative_path(nav_path("overview-general")),
                             className="text-muted text-decoration-none"), className="breadcrumb-item"),
            html.Li(unit, className="breadcrumb-item active fw-bold", **{"aria-current": "page"}),
        ], className="breadcrumb mb-0"),
        **{"aria-label": t("unit_summary.breadcrumb")},
    )
    controls = html.Nav([
        _back_link(),
        _nav_control(t("unit_summary.anterior"), "fas fa-chevron-left", prev_unit, t("unit_summary.primera_unidad")),
        _unit_selector(ordered, unit),
        _nav_control(t("unit_summary.siguiente"), "fas fa-chevron-right", next_unit, t("unit_summary.ultima_unidad"),
                     icon_after=True),
    ], className="unit-nav__controls", **{"aria-label": t("unit_summary.navegacion_entre_unidades")})
    return html.Div([breadcrumb, controls], className="unit-nav")


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
        html.Div(_back_link(), className="text-center"),
    ], className="p-4")


def _build_unit_summary(client: str, unit: str) -> html.Div:
    ordered = get_ordered_units(client)
    if not ordered:
        return _empty_state(t("unit_summary.no_hay_unidades_disponibles_para_este"))

    snapshot = get_unit_snapshot(client, unit)
    if snapshot is None:
        return _empty_state(t("unit_summary.la_unidad_no_se_encuentra_para", unit=unit))

    unit_ids = [entry["unit"] for entry in ordered]
    idx = unit_ids.index(unit)
    prev_unit = unit_ids[idx - 1] if idx > 0 else None
    next_unit = unit_ids[idx + 1] if idx < len(unit_ids) - 1 else None

    # The banner's Estado is the unit's, the same one the Fleet Overview row shows.
    banner = _banner(client, unit, snapshot["overall_status"])

    # Per-technique content, isolated from the header in its own try/except so a content
    # failure degrades to an inline error card instead of blanking the whole shell (the
    # navigation bar and banner stay usable either way). Every status in it is read from the
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

    return html.Div([_navigation_bar(ordered, unit, prev_unit, next_unit), banner, body])
