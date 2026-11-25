"""Presentation helpers for the EMIN historical fleet page."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import plotly.graph_objects as go
import dash_bootstrap_components as dbc
from dash import html

from src.charts.theme import BRAND_ACCENT, BRAND_MUTED, CATEGORICAL_COLORS, apply_dashboard_theme
from src.data.emin_historical import EminHistoricalBundle
from src.i18n import t


CHILE = ZoneInfo("America/Santiago")


def filter_options(bundle: EminHistoricalBundle) -> dict:
    """Build ordered day, group and equipment options from the published package."""
    days = sorted({row["day"] for row in bundle.daily}, reverse=True)
    groups = sorted(
        {str(group) for row in bundle.daily for group in row.get("event_groups", []) if group},
        key=str.casefold,
    )
    latest = [row for row in bundle.daily if row["day"] == (days[0] if days else None)]
    latest.sort(key=lambda row: (row.get("rank") is None, row.get("rank") or 9999, row["unit"]))
    units = list(dict.fromkeys(row["unit"] for row in latest))
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
    """Render KPI cards, the fleet ranking, two charts and source evidence."""
    all_days = sorted({row["day"] for row in bundle.daily})
    selected_day = day if day in all_days else (all_days[-1] if all_days else None)
    daily_rows = [row for row in bundle.daily if row["day"] == selected_day]
    daily_rows.sort(key=lambda row: (row.get("rank") is None, row.get("rank") or 9999, row["unit"]))
    filtered_rows = daily_rows
    if group and group != "__all__":
        filtered_rows = [row for row in daily_rows if group in row.get("event_groups", [])]

    units = {row["unit"] for row in bundle.daily}
    selected_unit = unit if unit in units else (daily_rows[0]["unit"] if daily_rows else None)
    selected_row = next((row for row in daily_rows if row["unit"] == selected_unit), None)
    trend_rows = sorted(
        (row for row in bundle.daily if row["unit"] == selected_unit),
        key=lambda row: row["day"],
    )
    evidence_rows = [
        row for row in bundle.observed
        if row.get("unit") == selected_unit and row.get("day") == selected_day
    ]
    evidence_rows.sort(key=lambda row: (str(row.get("event_at") or row.get("day") or ""), str(row.get("kind", ""))), reverse=True)

    return {
        "meta": _metadata(bundle, selected_day),
        "kpis": _kpi_cards(daily_rows, filtered_rows),
        "ranking": _ranking_table(filtered_rows, selected_unit),
        "trend": _trend_figure(trend_rows, selected_unit),
        "groups": _groups_figure(daily_rows, group),
        "evidence": _evidence_panel(selected_unit, selected_row, evidence_rows),
    }


def _day_label(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d-%m-%Y")
    except (TypeError, ValueError):
        return value


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
            html.Span(t("emin_history.cutoff_meta", day=_day_label(selected_day) if selected_day else "—"), className="emin-history-meta-pill"),
            html.Span(t("emin_history.captured_meta", timestamp=_format_timestamp(evidence_as_of)), className="emin-history-meta-pill"),
            html.Span(t("emin_history.days_meta", count=len({row["day"] for row in bundle.daily})), className="emin-history-meta-pill"),
        ],
        className="emin-history-meta-list",
    )


def _kpi_card(label: str, value: str | int, icon: str, detail: str = ""):
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(
                        [
                            html.Span(label, className="emin-history-kpi-label"),
                            html.I(className=f"{icon} emin-history-kpi-icon"),
                        ],
                        className="emin-history-kpi-top",
                    ),
                    html.Div(str(value), className="emin-history-kpi-value"),
                    html.Div(detail or "\u00a0", className="emin-history-kpi-detail"),
                ]
            ),
            class_name="emin-history-card h-100",
        ),
        xs=12,
        sm=6,
        xl=3,
        class_name="mb-3",
    )


def _kpi_cards(daily_rows: list[dict], filtered_rows: list[dict]):
    observed = sum(bool(row.get("has_observation")) for row in daily_rows)
    max_points = max((float(row.get("points") or 0) for row in filtered_rows), default=0)
    return dbc.Row(
        [
            _kpi_card(t("emin_history.kpi_units"), len(daily_rows), "fas fa-truck"),
            _kpi_card(t("emin_history.kpi_observed"), observed, "fas fa-clipboard-check", t("emin_history.kpi_observed_detail")),
            _kpi_card(t("emin_history.kpi_group_matches"), len(filtered_rows), "fas fa-filter"),
            _kpi_card(t("emin_history.kpi_max_score"), f"{max_points:.3f}", "fas fa-chart-line", t("emin_history.kpi_score_detail")),
        ],
        className="g-3",
    )


def _empty_figure(title: str, message: str, height: int = 340) -> go.Figure:
    figure = go.Figure()
    figure.add_annotation(text=message, showarrow=False, font={"color": BRAND_MUTED, "size": 13})
    return apply_dashboard_theme(figure, title=title, height=height)


def _trend_figure(rows: list[dict], unit: str | None) -> go.Figure:
    title = t("emin_history.trend_title", unit=unit or t("emin_history.no_unit"))
    if not rows:
        return _empty_figure(title, t("emin_history.empty_trend"), 350)
    custom = [
        [row.get("points", 0), bool(row.get("has_observation")), bool(row.get("estimated"))]
        for row in rows
    ]
    figure = go.Figure(
        go.Scatter(
            x=[row["day"] for row in rows],
            y=[row.get("rank") for row in rows],
            customdata=custom,
            mode="lines+markers",
            line={"color": BRAND_ACCENT, "width": 2},
            marker={"size": 6, "color": BRAND_ACCENT},
            hovertemplate=(
                "%{x}<br>Puesto: %{y}<br>Puntaje heurístico: %{customdata[0]}"
                "<br>Observación: %{customdata[1]}<br>Estimado: %{customdata[2]}<extra></extra>"
            ),
        )
    )
    figure.update_xaxes(
        type="date",
        title_text=t("emin_history.axis_day"),
        gridcolor="#ecf0f1",
        automargin=True,
        dtick=3 * 24 * 60 * 60 * 1000,
        tickformat="%d %b",
        tickangle=0,
        tickfont={"size": 9},
    )
    figure.update_yaxes(
        title_text=t("emin_history.axis_rank"),
        autorange="reversed",
        gridcolor="#ecf0f1",
        automargin=True,
        dtick=5,
    )
    figure = apply_dashboard_theme(figure, title=title, height=350)
    figure.update_layout(margin={"l": 48, "r": 22, "t": 52, "b": 52})
    return figure


def _groups_figure(rows: list[dict], selected_group: str | None) -> go.Figure:
    counts = Counter(
        group
        for row in rows
        for group in set(row.get("event_groups", []))
    )
    if not counts:
        return _empty_figure(t("emin_history.groups_title"), t("emin_history.empty_groups"), 350)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))[:10]
    if selected_group and selected_group != "__all__" and selected_group in counts and selected_group not in dict(ordered):
        ordered.append((selected_group, counts[selected_group]))
    ordered.reverse()
    labels = [name for name, _ in ordered]
    colors = [BRAND_ACCENT if name == selected_group else CATEGORICAL_COLORS[0] for name in labels]
    figure = go.Figure(
        go.Bar(
            x=[count for _, count in ordered],
            y=labels,
            orientation="h",
            marker_color=colors,
            cliponaxis=False,
            hovertemplate="%{y}<br>Equipos: %{x}<extra></extra>",
        )
    )
    figure.update_xaxes(
        title_text=t("emin_history.axis_units"),
        gridcolor="#ecf0f1",
        rangemode="tozero",
        automargin=True,
        nticks=3,
        tickangle=0,
    )
    figure.update_yaxes(
        automargin=True,
        ticks="",
        tickvals=labels,
        ticktext=[_group_tick_label(label) for label in labels],
        tickfont={"size": 10},
    )
    figure = apply_dashboard_theme(figure, title=t("emin_history.groups_title"), height=350)
    figure.update_layout(margin={"l": 90, "r": 22, "t": 52, "b": 52})
    return figure


def _group_tick_label(label: str) -> str:
    """Wrap long system/group labels without losing the source classification name."""
    parts = label.split(" / ", 1)
    if len(parts) == 2:
        return f"{parts[0]} /<br>{parts[1]}"
    return label


def _observation_label(row: dict) -> str:
    if row.get("has_observation"):
        return t("emin_history.observed")
    if row.get("estimated"):
        return t("emin_history.estimated")
    return t("emin_history.no_record")


def _ranking_table(rows: list[dict], selected_unit: str | None):
    if not rows:
        return dbc.Alert(t("emin_history.empty_ranking"), color="light", class_name="mb-0")
    headings = [
        t("emin_history.col_rank"), t("emin_history.col_unit"), t("emin_history.col_score"),
        t("emin_history.col_observation"), t("emin_history.col_alerts"),
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
            _observation_label(row),
            row.get("alerts", 0),
            row.get("health_events", 0),
            group_label or "—",
        ]
        body_rows.append(
            html.Tr(
                [html.Td(value) for value in cells],
                className="emin-history-row-selected" if row["unit"] == selected_unit else None,
            )
        )
    return html.Div(
        dbc.Table([header, html.Tbody(body_rows)], hover=True, striped=True, responsive=True, size="sm", class_name="emin-history-table align-middle mb-0"),
        className="emin-history-table-wrap",
    )


def _source_detail(details: dict) -> str:
    if not isinstance(details, dict):
        return str(details or "—")
    preferred = ["Evento", "Variable", "Sistema", "Subsistema", "Componente", "Código", "Detalle", "Description"]
    parts = [f"{key}: {details[key]}" for key in preferred if details.get(key) not in (None, "")]
    if not parts:
        parts = [f"{key}: {value}" for key, value in details.items() if value not in (None, "")]
    value = " · ".join(parts) or "—"
    return value if len(value) <= 260 else value[:257] + "…"


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


def _evidence_panel(unit: str | None, daily_row: dict | None, rows: list[dict]):
    heading = html.Div(
        [
            html.Strong(unit or t("emin_history.no_unit")),
            html.Span(f" · {_day_label(daily_row['day'])}" if daily_row else "", className="text-muted ms-2"),
        ],
        className="emin-history-evidence-heading mb-2",
    )
    groups = (daily_row or {}).get("event_groups", [])
    group_chips = html.Div(
        [dbc.Badge(group, color="light", text_color="dark", class_name="me-1 mb-1") for group in groups]
        or [html.Span(t("emin_history.no_groups"), className="text-muted small")],
        className="mb-2",
    )
    if not rows:
        empty = dbc.Alert(t("emin_history.empty_evidence"), color="light", class_name="mb-0")
        return html.Div([heading, group_chips, empty])

    visible = rows[:16]
    table_head = html.Thead(html.Tr([
        html.Th(t("emin_history.evidence_time")),
        html.Th(t("emin_history.evidence_source")),
        html.Th(t("emin_history.evidence_detail")),
    ]))
    table_body = html.Tbody(
        [
            html.Tr(
                [
                    html.Td(_format_timestamp(row.get("event_at") or row.get("day"))),
                    html.Td(_kind_label(str(row.get("kind", "")))),
                    html.Td(_source_detail(row.get("details") or {})),
                ]
            )
            for row in visible
        ]
    )
    table = html.Div(
        dbc.Table([table_head, table_body], responsive=True, size="sm", class_name="emin-history-evidence-table align-middle mb-0"),
        className="emin-history-evidence-scroll",
    )
    count_note = html.Small(
        t("emin_history.showing_evidence", shown=len(visible), total=len(rows)),
        className="text-muted d-block mt-2",
    )
    return html.Div([heading, group_chips, table, count_note])
