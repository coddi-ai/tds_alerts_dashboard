"""
Unit Summary — per-unit drill-down navigation shell (Phase 2).

Implements documentation/general/general_specs/02_unit_summary_navigation_shell.md:
entry from a Fleet Overview card, a sticky header identifying the unit and its
current overall status, a control to return to the Fleet Overview, and
prev/next + a unit switcher for lateral navigation between units — all
through Dash Pages' client-side router (dcc.Link everywhere), so switching
units or returning to the Fleet Overview never triggers a full page reload.

Content (per-technique charts, maintenance summary, monitored-components
list) is Phase 3 — documentation/general/general_specs/03_unit_summary_content.md
— built by dashboard/components/unit_summary_content.py and assembled into
the body below.
"""

from src.i18n import t
import dash_bootstrap_components as dbc
from dash import dcc, html

from dashboard.components.fleet_overview import get_ordered_units, get_unit_snapshot, status_badge
from dashboard.components.unit_summary_content import build_unit_summary_content
from dashboard.services_registry import nav_path, relative_path, unit_summary_path
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _back_link():
    """Return-to-Fleet-Overview control. Rendered inside the sticky header,
    so it stays available from anywhere in the Unit Summary (Functional
    Rules: "available from anywhere ... not only from a specific sub-tab or
    scroll position")."""
    return dcc.Link([
        html.I(className="fas fa-arrow-left me-2"), t("unit_summary.volver_a_fleet_overview"),
    ], href=relative_path(nav_path("overview-general")),
        className="unit-summary-back-link btn btn-outline-secondary btn-sm",
        style={"whiteSpace": "nowrap"})


def _nav_control(label: str, icon: str, target_unit, disabled_text: str):
    """One prev/next lateral-navigation control (Required Changes #4)."""
    if target_unit is None:
        return html.Span([
            html.I(className=f"{icon} me-1"), disabled_text,
        ], className="text-muted small", style={"padding": "6px 10px", "whiteSpace": "nowrap"})
    return dcc.Link([
        html.I(className=f"{icon} me-1"), label,
    ], href=relative_path(unit_summary_path(target_unit)),
        className="btn btn-outline-secondary btn-sm", style={"whiteSpace": "nowrap"})


def _unit_switcher(ordered: list, current_unit: str):
    """Dropdown-based unit switcher - the "e.g. ... or a unit switcher"
    alternative lateral-navigation control called out in Required Changes #4,
    on top of prev/next. Every entry is a plain link (`href`), so picking a
    unit routes through Dash Pages' client-side router exactly like prev/next."""
    items = [
        dbc.DropdownMenuItem(
            [
                html.Span(entry["unit"], style={"fontWeight": "700" if entry["unit"] == current_unit else "400"}),
                html.Span(f" · {entry['band']}", className="text-muted ms-1", style={"fontSize": "11px"}),
            ],
            href=relative_path(unit_summary_path(entry["unit"])),
            active=(entry["unit"] == current_unit),
        )
        for entry in ordered
    ]
    return dbc.DropdownMenu(
        items,
        label=[html.I(className="fas fa-truck me-2"), t("unit_summary.cambiar_unidad")],
        color="light",
        size="sm",
        className="unit-summary-switcher",
        align_end=True,
    )


def build_unit_summary(client: str, unit: str) -> html.Div:
    """Build the Unit Summary shell for `unit`, or an explanatory empty
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

    badges = [status_badge(snapshot["overall_status"])]
    if snapshot["maintenance_status"] is not None:
        badges.append(status_badge(snapshot["maintenance_status"]))

    # Persistent unit identification (Required Changes #2): breadcrumb +
    # unit id + current overall status, kept visible while scrolling via
    # `position: sticky` (Functional Rules item 3).
    header = html.Div([
        html.Div([
            html.Nav([
                dcc.Link(t("unit_summary.fleet_overview"), href=relative_path(nav_path("overview-general")),
                         className="text-muted text-decoration-none"),
                html.Span(" / ", className="mx-1 text-muted"),
                html.Span(unit, style={"fontWeight": "700"}),
            ], className="text-muted mb-1 small"),
            html.Div([
                html.H4([
                    html.I(className="fas fa-truck me-2"), unit,
                ], className="text-primary mb-0 me-2 d-inline-block"),
                html.Span(badges, style={"display": "inline-flex", "gap": "6px", "verticalAlign": "middle"}),
            ]),
        ], style={"flex": "1", "minWidth": "200px"}),

        html.Div([
            _back_link(),
            _nav_control(t("unit_summary.anterior"), "fas fa-chevron-left", prev_unit, t("unit_summary.primera_unidad")),
            _unit_switcher(ordered, unit),
            _nav_control(t("unit_summary.siguiente"), "fas fa-chevron-right", next_unit, t("unit_summary.ultima_unidad")),
        ], style={"display": "flex", "alignItems": "center", "gap": "8px", "flexWrap": "wrap"}),
    ], className="unit-summary-sticky-header", style={
        "display": "flex", "alignItems": "center", "gap": "16px", "flexWrap": "wrap",
        "position": "sticky", "top": "80px", "zIndex": "50",
        "background": "var(--surface-1, #fff)", "borderBottom": "1px solid var(--border-strong, #dee2e6)",
        "padding": "14px 16px", "marginBottom": "20px", "borderRadius": "6px",
        "boxShadow": "0 1px 3px rgba(0,0,0,0.08)",
    })

    # Phase 3: per-technique charts, maintenance summary, monitored
    # components (documentation/general/general_specs/03_unit_summary_content.md).
    # Isolated from the header/nav above in its own try/except so a content
    # failure degrades to an inline error card instead of blanking the whole
    # shell (prev/next, back-link, sticky header stay usable either way).
    try:
        # Sourced from the same status computation as the sticky header's
        # badges above and the Fleet Overview cards - never recalculated
        # independently (documentation/general/general_specs/
        # 05_unit_summary_restructure_and_predictive_comparison.md,
        # Functional Rules).
        body = build_unit_summary_content(client, unit, technique_status=snapshot.get("technique_status"))
    except Exception:
        logger.exception("Error building Unit Summary content for client=%s unit=%s", client, unit)
        body = dbc.Alert([
            html.I(className="fas fa-exclamation-triangle me-2"),
            t("unit_summary.error_al_generar_el_contenido_de"),
        ], color="danger", className="text-center")

    return html.Div([header, body])
