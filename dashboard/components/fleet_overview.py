"""
Fleet Overview - the General tab's unified per-unit table. It READS the golden layer and draws it.

    data/general/golden/{client}/fleet_status.parquet     (written by scripts/build_fleet_status.py)

Nothing here reads a raw source or decides a state: the per-technique status of every unit, the data-age
rule, the merge of a unit's spellings (`CT-184` / `CT_184`) and the unit's overall Estado are all in the file
(`src/data/fleet_status.py` documents what a run does). When the file of a client is missing or unreadable
the tab says so (`FleetStatusUnavailable`) - it does not rebuild the answer from raw data, and it keeps
showing the last good file when a later run fails, because a failed run never replaces it.

Layout, per documentation/general/general_specs/08_fleet_overview_table_format.md: one table per status band
(Anormal / Alerta / Normal / Sin Datos) - rows = units, columns = Unidad, Estado and one column per technique
applicable to the client - with a hover/focus/click explanation on every status chip that is generated from
the same stored fields as the chip (`MergedCell`). The criteria the states follow are printed on the page by
`dashboard/components/fleet_criteria.py`, from the same constants the run classifies with.

Rules that still hold (documentation/general/general_specs/00_implementation_guide.md): §3.1 overall status
= worst-of across the techniques, Maintenance excluded (own operational badge instead), per-client
applicability gated through config.client_services; §3.2 per-technique freshness thresholds
(config/freshness_thresholds.py); §3.3 inside a band, natural ascending unit order (CA-2 before CA-10).
"""

import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from dash import dcc, html

from config.estado_rules import NO_STATUS_TECHNIQUES
from dashboard.components.labels import localize_elapsed, status_label
from dashboard.components.status_chip import STATUS_SOLID_COLORS, canonical_status, status_chip
from dashboard.services_registry import relative_path, unit_summary_path
from src.data.fleet_status import (
    ALERT_WINDOW_DAYS,
    FleetStatusUnavailable,
    applicable_techniques,
    enabled_predictive_components,
    get_predictive_component_status,
    load_fleet_status,
    resolve_cell,
    techniques_in,
)
from src.data.unit_ids import unit_key
from src.i18n import t as _t, t_or as _t_or
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Other views import these from here (they used to live in this module, with the processing).
__all__ = [
    "applicable_techniques", "enabled_predictive_components", "get_predictive_component_status",
]

# ── Technique registry ──────────────────────────────────────────────────────
# ── Technique registry ──────────────────────────────────────────────────────
# Row order on every card matches the spec's order: Alerts, Telemetry, Oil,
# Maintenance, Predictive Models.

TECHNIQUE_LABELS = {
    "alerts": "Alertas",
    "telemetry": "Telemetría",
    "oil": "Tribología",
    "maintenance": "Mantención",
    "predictive": "Predictivo",
}

def technique_label(technique: str) -> str:
    """Display label of a technique in the current language (TECHNIQUE_LABELS holds the Spanish source)."""
    return _t_or(f"fleet_overview.technique_{technique}", TECHNIQUE_LABELS[technique])

# "Sin Datos" is appended after the three severity bands, never inserted
# between them - 06_fleet_overview_revision_2.md's Functional Rules keep the
# existing Anormal -> Alerta -> Normal grouping/order intact. It exists
# because "every applicable technique reported Sin Datos" is not the same
# fact as "every applicable technique reported Normal", and conflating the
# two is exactly the contradiction that revision fixes (Required Changes #4).
_BAND_ORDER = ["Anormal", "Alerta", "Normal", "Sin Datos"]
_BAND_LABEL_KEYS = {
    "Anormal": "fleet_overview.band_abnormal",
    "Alerta": "fleet_overview.band_alert",
    "Normal": "fleet_overview.band_normal",
    "Sin Datos": "fleet_overview.band_no_data",
}
# Icon-driven scannability (ui_notes.md): one recognizable icon per band,
# consistent with the status vocabulary used across every technique card.
_BAND_ICONS = {
    "Anormal": "fas fa-exclamation-circle",
    "Alerta": "fas fa-exclamation-triangle",
    "Normal": "fas fa-check-circle",
    "Sin Datos": "fas fa-question-circle",
}
# Tint of each band's icon badge (assets/status_chip.css).
_BAND_CSS = {"Anormal": "anormal", "Alerta": "alerta", "Normal": "normal", "Sin Datos": "nodata"}


def status_color(status: str, default: str) -> str:
    """Public: the solid severity color of `status` - the same tier colors the status
    chips (dashboard/components/status_chip.py) draw from. Charts inside a card that
    carries a chip must color their severity elements through this, never from a mapping
    of their own, so the two can't drift apart (10_unit_summary_monitoreo_polish_and_
    component_source_fix.md, Functional Rules). `default` is for statuses with no
    severity color (the no-data tone is a CSS variable, which a chart can't use)."""
    from dashboard.components.status_chip import canonical_status

    canonical = canonical_status(status)
    return STATUS_SOLID_COLORS[canonical] if canonical != "Sin Datos" else default

# ── max_risk: one shared severity ranking for label and estado_datos ────────
# The rule (worse of the technique's status and its data age, on Normal < Alerta <
# Anormal) is `config.estado_rules.technique_estado`; `max_risk` wraps its outcome with
# the data a cell needs to show and explain itself (08_fleet_overview_table_format.md,
# Functional Rules).
# What each freshness tier is called in the tooltip's plain-language text.
_DATA_STATE_TEXT_KEYS = {
    "Ok": "fleet_overview.data_state_ok", "Atención": "fleet_overview.data_state_attention",
    "Preocupante": "fleet_overview.data_state_concerning", "Sin Datos": "fleet_overview.data_state_no_data",
}


def _data_state_text(estado_datos: str) -> str:
    return _t(_DATA_STATE_TEXT_KEYS[estado_datos])


def _shown_status(label) -> str:
    """A technique's own status as the General tab names it: Crítico (Alertas) is Anormal,
    Atención is Alerta. Anything else is left as it is."""
    canonical = canonical_status(label)
    return canonical if canonical != "Sin Datos" or str(label).strip().casefold() == "sin datos" else label


@dataclass(frozen=True)
class MergedCell:
    """Result of one `max_risk` evaluation - the cell's displayed value and
    the tooltip, both derived from the same rule application so the
    explanation can never drift from the logic (08, Functional Rules)."""
    value: str
    label: str
    estado_datos: str
    driver: str  # "label" | "data" | "both" | "none"
    # Catalog key of the explanation. The text itself is rendered on demand (see
    # `explanation`): cells are cached in `_SNAPSHOTS` and shared across requests, so
    # storing the sentence would freeze it in the language of whoever built the cache.
    explanation_key: str
    elapsed: Optional[str] = None
    score: Optional[float] = None
    # Alerts only: (last week, last 4 weeks, last 8 weeks) alert counts.
    alert_counts: Optional[tuple] = None

    @property
    def explanation(self) -> str:
        return _t(
            self.explanation_key,
            label=status_label(_shown_status(self.label)),
            estado_datos=status_label(self.estado_datos),
            data_state=_data_state_text(self.estado_datos) if self.estado_datos in _DATA_STATE_TEXT_KEYS else "",
            shown=status_label(self.value),
        )

    @property
    def tooltip(self) -> str:
        data_text = status_label(self.estado_datos)
        if self.elapsed and self.elapsed != "N/A":
            data_text += _t("fleet_overview.tooltip_last_update", elapsed=localize_elapsed(self.elapsed))
        lines = [
            _t("fleet_overview.tooltip_technique_status", label=status_label(_shown_status(self.label))),
            _t("fleet_overview.tooltip_data_status", data_text=data_text),
        ]
        if self.score is not None and not pd.isna(self.score):
            lines.append(
                _t("fleet_overview.tooltip_severity_value")
                + (f"{self.score:.1f}" if isinstance(self.score, float) else str(self.score))
            )
        if self.alert_counts is not None:
            week, four_weeks, eight_weeks = self.alert_counts
            lines.append(_t(
                "fleet_overview.tooltip_alert_counts",
                week=week, four_weeks=four_weeks, eight_weeks=eight_weeks,
            ))
        lines.append(self.explanation)
        return "\n".join(lines)

def max_risk(label, estado_datos, elapsed: Optional[str] = None, score=None) -> MergedCell:
    """The worse of a technique's own status `label` and its data-freshness `estado_datos` (rule:
    `config.estado_rules.technique_estado`), as a cell. The run that writes the golden file resolves every
    cell with the same `resolve_cell`; this wraps one for display."""
    return MergedCell(*resolve_cell(label, estado_datos, elapsed, score))


def natural_key(unit) -> list:
    """Sort key for natural ascending order of unit IDs: CA-2 before CA-10, T_9 before T_10.
    The ID is split into text and number runs, so numbers compare as numbers; the split always
    alternates text, number, text... so two keys are comparable position by position."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(unit))]

# ── The golden file as entries ───────────────────────────────────────────────

def _alert_counts(row) -> Optional[tuple]:
    """(last week, last 4 weeks, last 8 weeks) alert counts of an Alertas row; None when the client has no alert feed."""
    counts = [row.get(f"alerts_count_{days}d") for days in ALERT_WINDOW_DAYS]
    return None if any(pd.isna(c) for c in counts) else tuple(int(c) for c in counts)


def _cell_from_row(technique: str, row) -> MergedCell:
    """The stored fields of one technique for one unit, as the cell the table draws."""
    elapsed = row.get(f"{technique}_elapsed")
    score = row.get(f"{technique}_score")
    return MergedCell(
        value=row[f"{technique}_estado"],
        label=row[f"{technique}_status"],
        estado_datos=row[f"{technique}_data_state"],
        driver=row[f"{technique}_driver"],
        explanation_key=row[f"{technique}_explanation_key"],
        elapsed=None if pd.isna(elapsed) else elapsed,
        score=None if pd.isna(score) else float(score),
        alert_counts=_alert_counts(row) if technique == "alerts" else None,
    )


def _entries_from_frame(frame: pd.DataFrame) -> list:
    """One entry per row of the golden frame, ordered as the tab draws them: band, then natural unit order.
    This only reshapes stored values; it decides nothing."""
    all_techniques = techniques_in(frame)
    shown = [t for t in all_techniques if t not in NO_STATUS_TECHNIQUES]
    entries = []
    for row in frame.to_dict("records"):
        cells = {t: _cell_from_row(t, row) for t in all_techniques}
        entries.append({
            "unit": row["unit_id"],
            "band": row["estado"],
            "sort_key": natural_key(row["unit_id"]),
            "overall_status": row["estado"],  # band label doubles as the overall status name
            # What the Unit Detail reads its status tiles and chips from: the table's own values.
            "technique_status": {t: cells[t].value for t in shown},
            "techniques": shown,
            "cells": cells,
        })
    entries.sort(key=lambda e: (_BAND_ORDER.index(e["band"]), e["sort_key"]))
    return entries


def _group_by_band(entries: list) -> dict:
    grouped: dict = {band: [] for band in _BAND_ORDER}
    for entry in entries:
        grouped[entry["band"]].append(entry)
    return grouped


# {client: (frame, entries, entries_by_band)} of the golden generation last read. `load_fleet_status` hands
# back the same frame object until the file changes, so identity says whether this is still the generation
# on disk: the next run is picked up without a restart, and "load more" pages through the very ordering the
# user is looking at.
_ENTRIES: dict = {}


def _entries_for(client: str) -> tuple:
    """`(entries, entries_by_band)` of the client's golden file. Raises `FleetStatusUnavailable`."""
    frame = load_fleet_status(client)
    cached = _ENTRIES.get(client)
    if cached is None or cached[0] is not frame:
        entries = _entries_from_frame(frame)
        cached = _ENTRIES[client] = (frame, entries, _group_by_band(entries))
    return cached[1], cached[2]


# ── Table rendering ──────────────────────────────────────────────────────────

def status_badge(status: str):
    """Public: the tinted status chip. Unit Detail draws every technique and section
    status with it, so a status reads the same in both views."""
    return status_chip(status)


def _unit_link(unit: str):
    """The row's link to the unit's Unit Detail: a real `<a href>` (a `dcc.Link`, so
    navigating goes through Dash Pages' client-side router). Its click area is stretched over
    the whole row by the stylesheet (`.fleet-unit-link::after`), so clicking anywhere on the
    row follows this one link; the status chips stay above it, as they open their own
    explanation."""
    return dcc.Link(unit, href=relative_path(unit_summary_path(unit)), className="fleet-unit-link")


def _estado_tooltip(overall_status: str, cells: dict) -> str:
    if overall_status == "Sin Datos":
        return _t("fleet_overview.estado_tooltip_no_data")
    drivers = [
        technique_label(tech) for tech, c in cells.items()
        if tech not in NO_STATUS_TECHNIQUES and c.value == overall_status
    ]
    return _t("fleet_overview.estado_tooltip", overall_status=status_label(overall_status), drivers=", ".join(drivers))


def chip_button(chip, tip: str, label: str) -> html.Button:
    """A status chip that explains itself: a real `<button>` whose explanation opens on hover,
    focus and click/Enter (assets/chip_popover.js) - never on hover alone. `label` is its
    accessible name."""
    return html.Button(
        chip, type="button", className="chip-button",
        **{"data-tip": tip, "aria-label": label},
    )


def _technique_cell(technique: str, cell: MergedCell):
    label = f"{technique_label(technique)}: {status_label(cell.value)}. {_t('fleet_overview.show_explanation')}"
    return html.Td(chip_button(status_chip(cell.value), cell.tooltip, label), className="fleet-table-cell")


def _unit_row(entry: dict):
    unit = entry["unit"]
    estado = entry["overall_status"]
    cells = entry["cells"]
    return html.Tr(
        [
            html.Td(_unit_link(unit), className="fleet-table-unit"),
            html.Td(
                chip_button(
                    status_chip(estado, solid=True), _estado_tooltip(estado, cells),
                    f"{_t('fleet_overview.col_status')}: {status_label(estado)}. {_t('fleet_overview.show_explanation')}",
                ),
                className="fleet-table-cell fleet-table-estado",
            ),
        ]
        + [_technique_cell(t, cells[t]) for t in entry["techniques"]]
        # Decorative: the link above is what a keyboard or screen reader reaches.
        + [html.Td(
            [_t("fleet_overview.view_detail"), html.I(className="fas fa-chevron-right ms-1")],
            className="fleet-table-cue", **{"aria-hidden": "true"},
        )],
        className="fleet-table-row",
    )

# ── Pagination ───────────────────────────────────────────────────────────────
# A band renders its first PAGE_SIZE rows; further chunks are fetched on demand (`get_band_rows_chunk`,
# appended by the "Mostrar siguientes" callback in dashboard/callbacks/overview_general_callbacks.py).
# Fleets like EMIN have ~870 units, which as full tables meant ~2 MB / ~10k components shipped and built on
# every visit.
PAGE_SIZE = 50


def more_button_label(remaining: int) -> str:
    return _t("fleet_overview.show_more", count=min(PAGE_SIZE, remaining), remaining=remaining)


def matching_entries(entries: list, query) -> list:
    """The entries whose unit ID contains `query` (case-insensitive); all of them when the
    query is empty."""
    needle = str(query or "").strip().casefold()
    if not needle:
        return entries
    return [e for e in entries if needle in str(e["unit"]).casefold()]

def get_band_rows_chunk(client: str, band: str, page: int, query=None) -> tuple:
    """Public: `(rows, remaining)` for chunk number `page` (0 is the first, already rendered with the band)
    of a band - `remaining` counts the units still not shown after this chunk. With a `query`, the band is
    the units matching it. `([], 0)` when the client's file is not available."""
    try:
        _, by_band = _entries_for(client)
    except FleetStatusUnavailable:
        logger.error("Fleet status of %s unavailable while paging a band", client)
        return [], 0
    entries = matching_entries(by_band.get(band, []), query)
    start = PAGE_SIZE * page
    chunk = entries[start:start + PAGE_SIZE]
    return [_unit_row(e) for e in chunk], max(len(entries) - (start + len(chunk)), 0)


def _band_table(band: str, entries: list, techniques: list):
    """One table per status band, first page only. Columns come from the
    client's technique availability alone, so every row has a cell for every
    column - never hidden or blank for some rows (08, Required Changes #1)."""
    header = html.Thead(html.Tr(
        [
            html.Th(_t("fleet_overview.col_unit"), scope="col", className="fleet-table-unit"),
            html.Th(_t("fleet_overview.col_status"), scope="col"),
        ]
        + [html.Th(technique_label(tech), scope="col") for tech in techniques]
        + [html.Th(html.Span(_t("fleet_overview.view_detail"), className="visually-hidden"), scope="col")]
    ))
    table = html.Table(
        [header, html.Tbody(
            [_unit_row(e) for e in entries[:PAGE_SIZE]],
            id={"type": "fleet-rows", "band": band},
        )],
        className="fleet-table",
    )
    remaining = max(len(entries) - PAGE_SIZE, 0)
    if not remaining:
        return table
    button = html.Button(
        more_button_label(remaining),
        id={"type": "fleet-more", "band": band},
        n_clicks=0,
        className="fleet-more-btn",
    )
    return html.Div([table, button])

# ── Top-level orchestration ─────────────────────────────────────────────────

def build_fleet_overview(client: str, query=None) -> html.Div:
    """Build the full Fleet Overview from the client's golden file: bands (Anormal/Alerta/Normal), each
    containing a table of units (one row per unit, one column per applicable technique) in natural unit
    order. When the file is missing or unreadable it says so - it never rebuilds the data."""
    if not client:
        return html.Div(html.P(_t("fleet_overview.select_client"), className="text-muted text-center p-4"))
    try:
        return _build_fleet_overview(client, query)
    except FleetStatusUnavailable:
        logger.error("Fleet status of client=%s is unavailable (missing or unreadable golden file)", client, exc_info=True)
        return html.Div(html.P(_t("fleet_overview.status_unavailable"), className="text-warning text-center p-4", role="alert"))
    except Exception:
        logger.exception("Error building Fleet Overview for client=%s", client)
        return html.Div(html.P(_t("fleet_overview.build_error"), className="text-danger text-center p-4"))


def technique_availability(client: str) -> dict:
    """Public: {technique: bool} - whether a technique has at least one unit with a real reading (a stored
    cell that isn't Sin Datos), for every technique applicable to this client (§3.1 gate; inapplicable
    techniques are omitted, matching how they get no column at all in the table).

    This reads the very cells the table draws - for Mantención, which has no column, the cell stored only for
    this signal - used by the "Fuentes de datos" banner (dashboard/components/source_status.py) instead of an
    independent raw file-existence probe, so the banner can never claim "Disponible" for a technique whose
    column reads "Sin Datos" right below it. {} when the client's file is not available."""
    if not client:
        return {}
    try:
        entries, _ = _entries_for(client)
    except FleetStatusUnavailable:
        logger.error("Fleet status of %s unavailable: no technique availability to report", client)
        return {}
    except Exception:
        logger.exception("Error reading technique availability for client=%s", client)
        return {}
    techniques = entries[0]["cells"].keys() if entries else ()
    return {
        technique: any(e["cells"][technique].value != "Sin Datos" for e in entries)
        for technique in techniques
    }


def get_ordered_units(client: str) -> list:
    """Ordered `{unit, band, overall_status, technique_status}` list, in the same order the Fleet Overview
    renders units - used by the Unit Detail navigation bar for prev/next lateral navigation and its unit
    switcher, and for the banner's current status. [] if the client has no file (see
    `FleetStatusUnavailable`) or no units."""
    if not client:
        return []
    try:
        entries, _ = _entries_for(client)
    except FleetStatusUnavailable:
        logger.error("Fleet status of %s unavailable: no unit list", client)
        return []
    except Exception:
        logger.exception("Error reading the unit order for client=%s", client)
        return []
    return [
        {
            "unit": e["unit"],
            "band": e["band"],
            "overall_status": e["overall_status"],
            "technique_status": e["technique_status"],
        }
        for e in entries
    ]


def get_unit_snapshot(client: str, unit: str):
    """A single unit's `{unit, band, overall_status, technique_status}`, or None if that unit isn't found for
    this client (Unit Detail's banner). `unit` may be spelled any way (`CT_184` finds `CT-184`)."""
    ordered = get_ordered_units(client)
    for entry in ordered:
        if entry["unit"] == unit:
            return entry
    key = unit_key(unit)
    for entry in ordered:
        if unit_key(entry["unit"]) == key:
            return entry
    return None


def _band_slug(band: str) -> str:
    return band.lower().replace(" ", "-")


def band_slug(band: str) -> str:
    """Public: the band as an id / data attribute fragment ("Sin Datos" -> "sin-datos")."""
    return _band_slug(band)


def band_css(band: str) -> str:
    """Public: the tint of the band's icon badge (assets/status_chip.css)."""
    return _BAND_CSS[band]


def _band_section(band: str, band_entries: list, matches: list, techniques: list, expanded: bool) -> html.Div:
    """One status band: a toggle button (tinted icon badge, title, unit count) and the
    band's table. The toggle is a real `<button aria-expanded aria-controls>`. `band_entries`
    is the whole band (the count in the header never changes with a search); `matches` is what
    the table lists. `expanded` is the state it is rendered in; the user's own choice is kept
    client-side afterwards (assets/fleet_overview_state.js)."""
    css = _BAND_CSS[band]
    body_id = f"fleet-band-body-{_band_slug(band)}"
    return html.Div([
        html.Button([
            html.Span(html.I(className=_BAND_ICONS[band]), className=f"icon-badge icon-badge--{css}",
                      **{"aria-hidden": "true"}),
            html.Span(_t(_BAND_LABEL_KEYS[band]), className="fleet-band-title"),
            html.Span(f"({len(band_entries)})", className="fleet-band-count"),
            html.I(className="fas fa-chevron-down fleet-band-chevron", **{"aria-hidden": "true"}),
        ], type="button", className="fleet-band-header" + ("" if expanded else " fleet-band-collapsed"),
            **{"data-fleet-band-toggle": "true", "aria-expanded": "true" if expanded else "false",
               "aria-controls": body_id}),
        html.Div(
            _band_table(band, matches, techniques),
            id=body_id,
            className="fleet-table-wrap",
            style=None if expanded else {"display": "none"},
            **{"data-fleet-band-body": "true"},
        ),
    ], **{"data-fleet-band": band.lower()})

def _build_fleet_overview(client: str, query=None) -> html.Div:
    """The bands. With a `query`, every band lists only the units whose ID contains it, the bands with
    matches are open and the others keep their place; without one only Anormal starts open."""
    entries, entries_by_band = _entries_for(client)
    if not entries:
        if not any(applicable_techniques(client).values()):
            return html.Div(html.P(
                _t("fleet_overview.no_techniques"),
                className="text-muted text-center p-4",
            ))
        return html.Div(html.P(_t("fleet_overview.no_units"), className="text-muted text-center p-4"))

    # Columns depend only on the client's technique availability, so every band's table shares the same
    # set (08, Required Changes #1).
    techniques = entries[0]["techniques"]
    query = str(query or "").strip()

    sections = []
    any_match = False
    for band in _BAND_ORDER:
        band_entries = entries_by_band[band]
        if not band_entries:
            continue
        matches = matching_entries(band_entries, query)
        any_match = any_match or bool(matches)
        expanded = bool(matches) if query else band == "Anormal"
        sections.append(_band_section(band, band_entries, matches, techniques, expanded))

    if query and not any_match:
        sections.insert(0, html.P(_t("fleet_overview.search_no_results", query=query),
                                  className="text-muted p-2", role="status"))
    return html.Div(sections, **({"data-fleet-search": "active"} if query else {}))
