"""Presentation helpers for the EMIN historical fleet page."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import re
import unicodedata
from zoneinfo import ZoneInfo

import plotly.graph_objects as go
import dash_bootstrap_components as dbc
from dash import html

from src.charts.theme import BRAND_ACCENT, BRAND_MUTED, CATEGORICAL_COLORS, apply_dashboard_theme
from src.data.emin_historical import EminHistoricalBundle
from src.i18n import t


CHILE = ZoneInfo("America/Santiago")
_MOVEMENT_COLORS = {
    "improved": "#28a745",
    "worsened": "#dc3545",
    "stable": "#3498db",
    "insufficient": "#7f8c8d",
}
_MAJOR_TEXT_PATTERNS = (
    r"motor.{0,35}(reemplaz|cambi|recambi|swap)",
    r"(reemplaz|cambi|recambi).{0,35}motor",
    r"engine.{0,35}(replac|chang|swap)",
    r"(replac|chang|swap).{0,35}engine",
    r"explosion|exploded|exploto|incendio|\bfire\b|\brevent(?:o|ar|ada|ado|aron|ando)\b|ruptur|fractur|catastrof|gripad|seized|blown",
)


def filter_options(bundle: EminHistoricalBundle) -> dict:
    """Build ordered cutoff, event-group and equipment options from the package."""
    days = sorted({row["day"] for row in bundle.daily}, reverse=True)
    groups = sorted(
        {str(group) for row in bundle.daily for group in row.get("event_groups", []) if group},
        key=str.casefold,
    )
    latest = [row for row in bundle.daily if row["day"] == (days[0] if days else None)]
    latest.sort(key=lambda row: (row.get("rank") is None, row.get("rank") or 9999, row["unit"]))
    current_units = list(dict.fromkeys(row["unit"] for row in latest))
    historical_units = sorted(
        {row["unit"] for row in bundle.daily} - set(current_units),
        key=str.casefold,
    )
    units = current_units + historical_units
    return {
        "days": [{"label": _day_label(day), "value": day} for day in days],
        "groups": [{"label": t("emin_history.all_groups"), "value": "__all__"}]
        + [{"label": group, "value": group} for group in groups],
        "units": [{"label": unit, "value": unit} for unit in units],
        "default_day": days[0] if days else None,
        "default_unit": units[0] if units else None,
    }


def build_historical_view(
    bundle: EminHistoricalBundle,
    day: str | None,
    group: str | None,
    unit: str | None,
) -> dict:
    """Build fleet overview and an evidence-backed individual equipment timeline."""
    all_days = sorted({row["day"] for row in bundle.daily})
    selected_day = day if day in all_days else (all_days[-1] if all_days else None)
    daily_rows = [row for row in bundle.daily if row["day"] == selected_day]
    daily_rows.sort(key=lambda row: (row.get("rank") is None, row.get("rank") or 9999, row["unit"]))
    filtered_rows = daily_rows
    if group and group != "__all__":
        filtered_rows = [row for row in daily_rows if group in row.get("event_groups", [])]

    all_units = {row["unit"] for row in bundle.daily}
    selected_unit = unit if unit in all_units else (daily_rows[0]["unit"] if daily_rows else None)
    selected_unit_rows = [row for row in bundle.daily if row["unit"] == selected_unit]
    trend_rows = sorted(
        (row for row in selected_unit_rows if not selected_day or row["day"] <= selected_day),
        key=lambda row: row["day"],
    )
    movements = {
        row["unit"]: _movement_for_unit(bundle.daily, row["unit"], selected_day)
        for row in daily_rows
    }
    status = movements.get(selected_unit) or _movement_for_unit(bundle.daily, selected_unit, selected_day)
    evidence_rows = [
        row for row in bundle.observed
        if row.get("unit") == selected_unit and (not selected_day or str(row.get("day") or "") <= selected_day)
    ]
    evidence_rows.sort(
        key=lambda row: (str(row.get("event_at") or row.get("day") or ""), str(row.get("kind", ""))),
        reverse=True,
    )

    return {
        "meta": _metadata(bundle, selected_day),
        "kpis": _movement_kpis(movements),
        "movement": _movement_figure(movements),
        "groups": _groups_figure(daily_rows, group),
        "ranking": _ranking_table(filtered_rows, selected_unit, movements),
        "status": _status_panel(selected_unit, status),
        "trend": _trend_figure(trend_rows, selected_unit),
        "evidence": _timeline_panel(selected_unit, evidence_rows),
    }


def _day_label(value: str | None) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d-%m-%Y")
    except (TypeError, ValueError):
        return value or t("emin_history.not_available")


def _format_timestamp(value: str | None) -> str:
    if not value:
        return t("emin_history.not_available")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(CHILE)
        return parsed.strftime("%d-%m-%Y %H:%M")
    except (TypeError, ValueError):
        return str(value)


def _metadata(bundle: EminHistoricalBundle, selected_day: str | None):
    online = bundle.manifest.get("online") or {}
    evidence_as_of = online.get("evidence_as_of") or online.get("prepared_at")
    return html.Div(
        [
            html.Span(t("emin_history.cutoff_meta", day=_day_label(selected_day)), className="emin-history-meta-pill"),
            html.Span(t("emin_history.captured_meta", timestamp=_format_timestamp(evidence_as_of)), className="emin-history-meta-pill"),
            html.Span(t("emin_history.days_meta", count=len({row["day"] for row in bundle.daily})), className="emin-history-meta-pill"),
            html.Span(t("emin_history.units_meta", count=len({row["unit"] for row in bundle.daily})), className="emin-history-meta-pill"),
        ],
        className="emin-history-meta-list",
    )


def _kpi_card(label: str, value: str | int, icon: str, detail: str = "", status: str | None = None):
    color = _MOVEMENT_COLORS.get(status, BRAND_ACCENT)
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(
                        [
                            html.Span(label, className="emin-history-kpi-label"),
                            html.I(className=f"{icon} emin-history-kpi-icon", style={"color": color}),
                        ],
                        className="emin-history-kpi-top",
                    ),
                    html.Div(str(value), className="emin-history-kpi-value"),
                    html.Div(detail or "\u00a0", className="emin-history-kpi-detail"),
                ]
            ),
            class_name="emin-history-card h-100",
            style={"borderTop": f"3px solid {color}"},
        ),
        xs=12,
        sm=6,
        xl=3,
        class_name="mb-3",
    )


def _movement_label(status: str) -> str:
    return t({
        "improved": "emin_history.movement_improved",
        "worsened": "emin_history.movement_worsened",
        "stable": "emin_history.movement_stable",
        "insufficient": "emin_history.movement_insufficient",
    }[status])


def _movement_for_unit(rows: tuple[dict, ...] | list[dict], unit: str | None, cutoff: str | None) -> dict:
    observed = [
        row for row in rows
        if row.get("unit") == unit
        and (not cutoff or str(row.get("day") or "") <= cutoff)
        and row.get("has_observation") is True
        and not row.get("estimated")
        and _number(row.get("points")) is not None
    ]
    by_day = {}
    for row in sorted(observed, key=lambda item: str(item.get("day") or "")):
        by_day[row["day"]] = row
    history = list(by_day.values())
    if len(history) < 2:
        return {"status": "insufficient", "current": history[-1] if history else None, "previous": None, "delta": None}
    previous, current = history[-2], history[-1]
    delta = _number(current.get("points")) - _number(previous.get("points"))
    if delta < -0.001:
        label = "improved"
    elif delta > 0.001:
        label = "worsened"
    else:
        label = "stable"
    return {"status": label, "current": current, "previous": previous, "delta": delta}


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _movement_kpis(movements: dict[str, dict]):
    counts = Counter(value["status"] for value in movements.values())
    return dbc.Row(
        [
            _kpi_card(t("emin_history.movement_improved"), counts["improved"], "fas fa-arrow-down", t("emin_history.movement_improved_detail"), "improved"),
            _kpi_card(t("emin_history.movement_worsened"), counts["worsened"], "fas fa-arrow-up", t("emin_history.movement_worsened_detail"), "worsened"),
            _kpi_card(t("emin_history.movement_stable"), counts["stable"], "fas fa-equals", t("emin_history.movement_stable_detail"), "stable"),
            _kpi_card(t("emin_history.movement_insufficient"), counts["insufficient"], "fas fa-minus-circle", t("emin_history.movement_insufficient_detail"), "insufficient"),
        ],
        className="g-3",
    )


def _empty_figure(title: str, message: str, height: int = 340) -> go.Figure:
    figure = go.Figure()
    figure.add_annotation(text=message, showarrow=False, font={"color": BRAND_MUTED, "size": 13})
    return apply_dashboard_theme(figure, title=title, height=height)


def _movement_figure(movements: dict[str, dict]) -> go.Figure:
    title = t("emin_history.movement_title")
    labels = [
        t("emin_history.movement_improved"),
        t("emin_history.movement_worsened"),
        t("emin_history.movement_stable"),
        t("emin_history.movement_insufficient"),
    ]
    statuses = ["improved", "worsened", "stable", "insufficient"]
    counts = Counter(value["status"] for value in movements.values())
    if not movements:
        return _empty_figure(title, t("emin_history.empty_movement"), 320)
    figure = go.Figure(go.Bar(
        x=[counts[status] for status in statuses],
        y=labels,
        orientation="h",
        marker_color=[_MOVEMENT_COLORS[status] for status in statuses],
        cliponaxis=False,
        hovertemplate="%{y}: %{x}<extra></extra>",
    ))
    figure.update_xaxes(title_text=t("emin_history.axis_units"), gridcolor="#ecf0f1", rangemode="tozero", automargin=True, nticks=4)
    figure.update_yaxes(automargin=True, ticks="", tickfont={"size": 10})
    figure = apply_dashboard_theme(figure, title=title, height=320)
    figure.update_layout(margin={"l": 115, "r": 22, "t": 52, "b": 50})
    return figure


def _trend_figure(rows: list[dict], unit: str | None) -> go.Figure:
    title = t("emin_history.trend_title", unit=unit or t("emin_history.no_unit"))
    if not rows:
        return _empty_figure(title, t("emin_history.empty_trend"), 350)
    custom = [
        [row.get("rank"), bool(row.get("has_observation")), bool(row.get("estimated"))]
        for row in rows
    ]
    symbols = ["circle" if row.get("has_observation") and not row.get("estimated") else "diamond" for row in rows]
    figure = go.Figure(go.Scatter(
        x=[row["day"] for row in rows],
        y=[_number(row.get("points")) for row in rows],
        customdata=custom,
        mode="lines+markers",
        line={"color": BRAND_ACCENT, "width": 2},
        marker={"size": 8, "color": BRAND_ACCENT, "symbol": symbols},
        hovertemplate=(
            "%{x}<br>Puntaje heurístico: %{y}<br>Puesto diario: %{customdata[0]}"
            "<br>Observado: %{customdata[1]}<br>Estimado: %{customdata[2]}<extra></extra>"
        ),
        connectgaps=False,
    ))
    figure.update_xaxes(type="date", title_text=t("emin_history.axis_day"), gridcolor="#ecf0f1", automargin=True, tickformat="%d %b", tickfont={"size": 9})
    figure.update_yaxes(title_text=t("emin_history.axis_score"), gridcolor="#ecf0f1", automargin=True, rangemode="tozero")
    figure = apply_dashboard_theme(figure, title=title, height=350)
    figure.update_layout(margin={"l": 62, "r": 22, "t": 52, "b": 52})
    return figure


def _groups_figure(rows: list[dict], selected_group: str | None) -> go.Figure:
    counts = Counter(group for row in rows for group in set(row.get("event_groups", [])))
    if not counts:
        return _empty_figure(t("emin_history.groups_title"), t("emin_history.empty_groups"), 320)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))[:10]
    if selected_group and selected_group != "__all__" and selected_group in counts and selected_group not in dict(ordered):
        ordered.append((selected_group, counts[selected_group]))
    ordered.reverse()
    labels = [name for name, _ in ordered]
    colors = [BRAND_ACCENT if name == selected_group else CATEGORICAL_COLORS[0] for name in labels]
    figure = go.Figure(go.Bar(
        x=[count for _, count in ordered], y=labels, orientation="h", marker_color=colors,
        cliponaxis=False, hovertemplate="%{y}<br>Equipos: %{x}<extra></extra>",
    ))
    figure.update_xaxes(title_text=t("emin_history.axis_units"), gridcolor="#ecf0f1", rangemode="tozero", automargin=True, nticks=4)
    figure.update_yaxes(automargin=True, ticks="", tickvals=labels, ticktext=[_group_tick_label(label) for label in labels], tickfont={"size": 10})
    figure = apply_dashboard_theme(figure, title=t("emin_history.groups_title"), height=320)
    figure.update_layout(margin={"l": 100, "r": 22, "t": 52, "b": 50})
    return figure


def _group_tick_label(label: str) -> str:
    parts = label.split(" / ", 1)
    return f"{parts[0]} /<br>{parts[1]}" if len(parts) == 2 else label


def _observation_label(row: dict) -> str:
    if row.get("has_observation"):
        return t("emin_history.observed")
    if row.get("estimated"):
        return t("emin_history.estimated")
    return t("emin_history.no_record")


def _movement_badge(movement: dict):
    status = movement["status"]
    colors = {"improved": "success", "worsened": "danger", "stable": "primary", "insufficient": "secondary"}
    return dbc.Badge(_movement_label(status), color=colors[status], class_name="emin-history-movement-badge")


def _ranking_table(rows: list[dict], selected_unit: str | None, movements: dict[str, dict]):
    if not rows:
        return dbc.Alert(t("emin_history.empty_ranking"), color="light", class_name="mb-0")
    headings = [
        t("emin_history.col_rank"), t("emin_history.col_unit"), t("emin_history.col_score"),
        t("emin_history.col_movement"), t("emin_history.col_observation"), t("emin_history.col_alerts"),
        t("emin_history.col_events"), t("emin_history.col_groups"),
    ]
    header = html.Thead(html.Tr([html.Th(label, scope="col") for label in headings]))
    body_rows = []
    for row in rows:
        groups = row.get("event_groups", [])
        group_label = ", ".join(str(value) for value in groups[:2])
        if len(groups) > 2:
            group_label += f" +{len(groups) - 2}"
        cells = [
            row.get("rank") if row.get("rank") is not None else "—",
            row["unit"],
            f"{float(row.get('points') or 0):.3f}",
            _movement_badge(movements.get(row["unit"], {"status": "insufficient"})),
            _observation_label(row),
            row.get("alerts", 0),
            row.get("health_events", 0),
            group_label or "—",
        ]
        body_rows.append(html.Tr(
            [html.Td(value) for value in cells],
            className="emin-history-row-selected" if row["unit"] == selected_unit else None,
        ))
    return html.Div(
        dbc.Table([header, html.Tbody(body_rows)], hover=True, striped=True, responsive=True, size="sm", class_name="emin-history-table align-middle mb-0"),
        className="emin-history-table-wrap",
    )


def _status_panel(unit: str | None, movement: dict):
    current = movement.get("current")
    previous = movement.get("previous")
    status = movement.get("status", "insufficient")
    if previous and current:
        dates = t("emin_history.comparison_dates", previous=_day_label(previous["day"]), current=_day_label(current["day"]))
        points = t(
            "emin_history.comparison_points",
            previous=f"{float(previous['points']):.3f}",
            current=f"{float(current['points']):.3f}",
            delta=f"{float(movement['delta']):+.3f}",
        )
    elif current:
        dates = t("emin_history.last_observation", day=_day_label(current["day"]))
        points = t("emin_history.one_observation")
    else:
        dates = t("emin_history.no_observed_scores")
        points = ""
    return dbc.Card(
        dbc.CardBody([
            html.Div([html.Div([
                html.Div(t("emin_history.unit_condition_label"), className="emin-history-status-eyebrow"),
                html.H4(unit or t("emin_history.no_unit"), className="mb-0"),
            ]), _movement_badge(movement)], className="emin-history-status-top"),
            html.P(t(f"emin_history.status_explain_{status}"), className="text-muted mb-2 mt-3"),
            html.Div(dates, className="emin-history-comparison-dates"),
            html.Div(points, className="emin-history-comparison-points"),
        ]),
        class_name="emin-history-card emin-history-status-card mb-3",
    )


def _source_detail(details) -> str:
    if not isinstance(details, dict):
        return str(details or "—")
    preferred = ["Evento", "Variable", "Sistema", "Subsistema", "Componente", "Código", "Detalle", "Description"]
    parts = [f"{key}: {details[key]}" for key in preferred if details.get(key) not in (None, "")]
    if not parts:
        parts = [f"{key}: {value}" for key, value in details.items() if value not in (None, "")]
    value = " · ".join(parts) or "—"
    return value if len(value) <= 500 else value[:497] + "…"


def _kind_label(kind: str) -> str:
    labels = {
        "alert": t("emin_history.kind_alert"),
        "event": t("emin_history.kind_event"),
        "oil": t("emin_history.kind_oil"),
        "coverage": t("emin_history.kind_state"),
        "maintenance_observed": t("emin_history.kind_maintenance"),
        "maintenance_action": t("emin_history.kind_maintenance"),
        "maintenance_golden_action": t("emin_history.kind_maintenance"),
        "downtime_record": t("emin_history.kind_downtime"),
        "downtime": t("emin_history.kind_downtime"),
    }
    return labels.get(kind, kind.replace("_", " ").capitalize() if kind else "—")


def _normalized_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _major_event(row: dict) -> str | None:
    """Highlight explicit high severity or major-event wording from source fields."""
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    for key in ("is_major", "major_event", "critical", "is_critical", "catastrophic"):
        if details.get(key) is True or row.get(key) is True:
            return "source"
    levels = [row.get("level"), row.get("severity"), details.get("level"), details.get("severity")]
    if any(_normalized_text(str(level or "")).strip() in {"critical", "critico", "severe", "grave", "catastrophic", "catastrofico"} for level in levels):
        return "source"
    text = _normalized_text(" ".join(str(value) for value in details.values() if value is not None))
    text += " " + _normalized_text(str(row.get("summary") or row.get("description") or ""))
    if any(re.search(pattern, text) for pattern in _MAJOR_TEXT_PATTERNS):
        return "text"
    return None


def _timeline_panel(unit: str | None, rows: list[dict]):
    heading = html.Div(
        [
            html.Strong(unit or t("emin_history.no_unit")),
            html.Span(t("emin_history.timeline_count", count=len(rows)), className="text-muted ms-2"),
        ],
        className="emin-history-evidence-heading mb-2",
    )
    if not rows:
        return html.Div([heading, dbc.Alert(t("emin_history.empty_timeline"), color="light", class_name="mb-0")])

    table_head = html.Thead(html.Tr([
        html.Th(t("emin_history.evidence_time")),
        html.Th(t("emin_history.evidence_source")),
        html.Th(t("emin_history.evidence_detail")),
        html.Th(t("emin_history.major_event")),
    ]))
    table_rows = []
    for row in rows:
        major = _major_event(row)
        marker = dbc.Badge(
            t("emin_history.major_source" if major == "source" else "emin_history.major_text"),
            color="danger" if major == "source" else "warning",
            text_color="dark" if major == "text" else "white",
        ) if major else html.Span("—", className="text-muted")
        table_rows.append(html.Tr(
            [
                html.Td(_format_timestamp(row.get("event_at") or row.get("day"))),
                html.Td(_kind_label(str(row.get("kind", "")))),
                html.Td(_source_detail(row.get("details") or row.get("summary") or row.get("description") or {})),
                html.Td(marker),
            ],
            className="emin-history-major-row" if major else None,
        ))
    table = html.Div(
        dbc.Table([table_head, html.Tbody(table_rows)], hover=True, striped=True, responsive=True, size="sm", class_name="emin-history-evidence-table align-middle mb-0"),
        className="emin-history-evidence-scroll",
    )
    note = html.Small(t("emin_history.timeline_note", count=len(rows)), className="text-muted d-block mt-2")
    return html.Div([heading, table, note])
