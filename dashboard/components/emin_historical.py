"""Presentation helpers for the EMIN historical fleet page."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from math import isfinite
import re
import unicodedata
from zoneinfo import ZoneInfo

import plotly.graph_objects as go
import dash_bootstrap_components as dbc
from dash import dcc, html

from src.charts.theme import BRAND_ACCENT, BRAND_MUTED, apply_dashboard_theme
from dashboard.components.predictive_state import STATE_ZONE_FILL, STATE_ZONE_TEXT
from src.data.emin_historical import EminHistoricalBundle
from src.i18n import t


CHILE = ZoneInfo("America/Santiago")
_MOVEMENT_COLORS = {
    "improved": "#28a745",
    "worsened": "#dc3545",
    "stable": "#3498db",
    "insufficient": "#7f8c8d",
}
def filter_options(bundle: EminHistoricalBundle) -> dict:
    """Read the prebuilt dashboard catalog; only display labels are formatted here."""
    catalog = bundle.dashboard["catalog"]
    weekly_cutoffs = catalog.get("iso_week_cutoffs", [])
    if not weekly_cutoffs:
        # Older packages expose only daily cutoffs. Keep the selector weekly by
        # choosing the latest available cutoff in each ISO week; completeness
        # cannot be asserted without the producer's explicit weekly catalog.
        by_week = {}
        for cutoff in sorted(catalog.get("cutoffs", []), reverse=True):
            try:
                iso = date.fromisoformat(cutoff).isocalendar()
            except (TypeError, ValueError):
                continue
            week = f"{iso.year}-W{iso.week:02d}"
            by_week.setdefault(week, {"week": week, "cutoff": cutoff, "complete": False})
        weekly_cutoffs = list(by_week.values())
    days = [item.get("cutoff") for item in weekly_cutoffs if item.get("cutoff")]
    week_by_cutoff = {item.get("cutoff"): item for item in weekly_cutoffs}
    groups = catalog.get("groups", [])
    units = catalog.get("units", [])
    fleet = bundle.dashboard.get("fleet", {}).get(days[0], {}) if days else {}
    movements = fleet.get("movements", {})
    default_unit = next((
        row["unit"] for row in fleet.get("rows", [])
        if movements.get(row["unit"], {}).get("status") in {"improved", "worsened", "stable"}
    ), units[0] if units else None)
    return {
        "days": [{"label": (t("emin_history.iso_week_cutoff", week=week_by_cutoff[day]["week"],
                                date=_day_label(day),
                                status=t("emin_history.iso_week_partial") if not week_by_cutoff[day].get("complete", True) else "")
                            if day in week_by_cutoff else _day_label(day)), "value": day} for day in days],
        "groups": [{"label": t("emin_history.all_groups"), "value": "__all__"}]
        + [{"label": group, "value": group} for group in groups],
        "units": [{"label": unit, "value": unit} for unit in units],
        "default_day": days[0] if days else None,
        "default_unit": default_unit,
    }


def build_historical_view(
    bundle: EminHistoricalBundle,
    day: str | None,
    group: str | None,
    unit: str | None,
    search: str | None = None,
    movement_filter: str | None = None,
    evidence_period: str | None = None,
    include_chronology: bool = True,
    require_high_signal: bool = False,
    trend_window: str = "long",
    fleet_window: str = "short",
) -> dict:
    """Build fleet overview and an evidence-backed individual equipment timeline."""
    all_days = bundle.dashboard["catalog"].get("cutoffs", [])
    selected_day = day if day in all_days else (all_days[0] if all_days else None)
    fleet_data = bundle.dashboard.get("fleet", {}).get(selected_day, {})
    daily_rows = fleet_data.get("rows", [])
    filtered_rows = daily_rows
    if group and group != "__all__":
        filtered_rows = fleet_data.get("groups", {}).get(group, [])

    all_units = set(bundle.dashboard["catalog"].get("units", []))
    selected_unit = unit if unit in all_units else (daily_rows[0]["unit"] if daily_rows else None)
    unit_data = bundle.dashboard.get("units", {}).get(selected_unit, {})
    selected_unit_rows = unit_data.get("daily", [])
    selected_data = unit_data.get("by_cutoff", {}).get(selected_day, {})
    available_trend = unit_data.get("by_cutoff", {}).get(selected_day, {}).get("trend", [])
    if trend_window == "short" and selected_day:
        trend_start = (date.fromisoformat(selected_day) - timedelta(days=6)).isoformat()
        trend_rows = [row for row in available_trend if trend_start <= row.get("day", "") <= selected_day]
    else:
        trend_rows = available_trend
    movements = fleet_data.get("movements", {})
    query = (search or "").strip().casefold()
    high_counts = fleet_data.get("high_signal_counts") if require_high_signal else None
    filtered_rows = [
        row for row in filtered_rows
        if query in row["unit"].casefold()
        and (movement_filter in (None, "__all__") or movements[row["unit"]]["status"] == movement_filter)
        and (high_counts is None or high_counts.get(row["unit"], 0))
    ]
    status = movements.get(selected_unit) or {"status": "insufficient", "current": None, "previous": None, "delta": None}
    evidence_rows = [row for row in unit_data.get("evidence", []) if not selected_day or str(row.get("day") or "") <= selected_day]
    selected_period = evidence_period if evidence_period in CRITICALITY_PERIODS else "week"
    period_start = fleet_criticality_top(bundle, selected_day, selected_period).get("start")
    top_context = (
        _top_unit_context(bundle, selected_day, selected_period, selected_unit, trend_rows, evidence_rows)
        if period_start else None
    )
    movement_drivers = _movement_drivers_panel(status, selected_data.get("movement_drivers", []))
    legacy_period = {"week": "short", "month": "medium", "quarter": "long", "history": "history"}[selected_period]
    contributors = _criticality_components_panel(selected_data.get("components", {}).get(selected_period)
                                                 or selected_data.get("components", {}).get(legacy_period, {}))
    fleet_highlights = {
        "critical": fleet_data.get("critical_units", []),
        "critical_remaining": fleet_data.get("critical_remaining", []),
        "critical_events": fleet_data.get("critical_event_days", {}),
        "has_history": fleet_data.get("has_history", False),
        "critical_total": fleet_data.get("critical_total", 0),
        "score_priority": fleet_data.get("score_priority_units", []),
        "healthiest": fleet_data.get("healthiest_units", []),
        "can_distinguish": fleet_data.get("can_distinguish_health", False),
        "scores": fleet_data.get("scores_by_unit", {}),
        "coverage_end": selected_day,
    }

    return {
        "meta": _metadata(bundle, selected_day),
        "daily_rows": daily_rows,
        "fleet_highlights": fleet_highlights,
        "movements": movements,
        "kpis": _fleet_movement_trend(bundle, selected_day, fleet_window),
        "groups": _groups_panel_from_items(fleet_data.get("groups_summary", []), group),
        "ranking": _ranking_table(filtered_rows, movements, high_counts),
        "status": html.Div([top_context, _status_panel(selected_unit, status), movement_drivers, contributors]),
        "trend": _period_delta_figure(
            selected_data.get("period_variations", {}).get(trend_window, []), selected_unit, trend_window
        ) if trend_window in {"week", "month", "quarter", "history"} and selected_data.get("period_variations")
        else _trend_figure(trend_rows, selected_unit, status.get("status", "insufficient")),
        "cumulative_score": _cumulative_score_figure(
            [row for row in unit_data.get("cumulative_weekly_score", [])
             if not selected_day or row.get("cutoff", "") <= selected_day],
            selected_unit,
        ),
        "evidence": _timeline_panel(selected_unit, evidence_rows, period_start, selected_day, include_chronology),
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
    catalog = bundle.dashboard.get("catalog", {})
    week_cutoffs = catalog.get("iso_week_cutoffs", [])
    selected_week = next((item for item in week_cutoffs if item.get("cutoff") == selected_day), None)
    if selected_week:
        cutoff_caption = t(
            "emin_history.iso_week_meta",
            week=selected_week.get("week", ""),
            day=_day_label(selected_day),
            status=t("emin_history.iso_week_partial") if not selected_week.get("complete", True) else "",
        )
        history_caption = t("emin_history.weeks_meta", count=len(week_cutoffs))
    else:
        cutoff_caption = t("emin_history.cutoff_meta", day=_day_label(selected_day))
        history_caption = t("emin_history.days_meta", count=len(catalog.get("cutoffs", [])))
    captions = [
        cutoff_caption,
        t("emin_history.captured_meta", timestamp=_format_timestamp(evidence_as_of)),
        history_caption,
        t("emin_history.units_meta", count=len(catalog.get("units", []))),
    ]
    return html.Small(" · ".join(captions), className="text-muted")


def section_header(title: str, icon: str):
    """Match the section headers used in Resumen de unidad."""
    return dbc.CardHeader(
        html.H5([html.I(className=f"{icon} me-2", **{"aria-hidden": "true"}), title], className="mb-0"),
        class_name="bg-light",
    )


def _movement_label(status: str) -> str:
    return t({
        "improved": "emin_history.movement_improved",
        "worsened": "emin_history.movement_worsened",
        "stable": "emin_history.movement_stable",
        "insufficient": "emin_history.movement_insufficient",
    }[status])


def _movement_chart_label(status: str) -> str:
    if status == "insufficient":
        return t("emin_history.movement_insufficient_chart_label")
    return _movement_label(status)


def _movement_date_notes(movement):
    notes = []
    if movement.get("historical_status"):
        notes.append(t("emin_history.movement_older_comparison", label=_movement_label(movement["historical_status"])))
    if (movement.get("lag_days") or 0) > 0:
        notes.append(t("emin_history.movement_observation_lag", days=movement["lag_days"]))
    if (movement.get("gap_days") or 0) > 1:
        notes.append(t("emin_history.movement_comparison_gap", days=movement["gap_days"]))
    return notes


def _number(value) -> float | None:
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _fleet_point_label_position(previous: float, current: float, index: int, extent: float) -> str:
    """Keep priority labels inside the plot and offset dense mobile clusters."""
    if previous >= extent * 0.72:
        return "middle left"
    if current >= extent * 0.82:
        return "bottom center"
    return "top center" if index % 2 == 0 else "bottom center"


def _fleet_movement_trend(bundle: EminHistoricalBundle, cutoff: str | None, period: str):
    """Render producer-calculated variation for the whole fleet, prioritizing critical units."""
    all_days = bundle.dashboard.get("catalog", {}).get("cutoffs", [])
    selected_day = cutoff if cutoff in all_days else (all_days[0] if all_days else None)
    fleet = bundle.dashboard.get("fleet", {}).get(selected_day, {}) if selected_day else {}
    variations = fleet.get("period_variations", {}).get(period, {})
    units = bundle.dashboard.get("catalog", {}).get("units", [])
    if not variations:
        note = t("emin_history.period_data_pending")
        return dcc.Graph(
            id="emin-history-movement-trend",
            figure=_empty_figure(t("emin_history.variation_title"), note, 390),
            config={"displayModeBar": False}, responsive=True,
            style={"height": "390px", "width": "100%"},
        )

    priority = set(fleet.get("critical_units", [])) | set(fleet.get("score_priority_units", []))
    top_units = {
        row.get("unit") for row in bundle.dashboard.get("period_tops", {}).get(selected_day, {}).get(period, {}).get("entries", [])
    }
    label_units = top_units or set(fleet.get("critical_units", [])[:5])
    priority |= top_units
    figure = go.Figure()
    valid = [item for item in variations.values()
             if _number(item.get("previous_average")) is not None and _number(item.get("current_average")) is not None]
    if not valid:
        note = t("emin_history.fleet_plot_coverage", shown=0, total=len(units), unavailable=len(units))
        if period == "quarter":
            note += "<br>" + t("emin_history.quarter_comparison_unavailable")
        figure = _empty_figure(t("emin_history.variation_title"), note, 430)
        figure.update_xaxes(visible=False)
        figure.update_yaxes(visible=False)
        return dcc.Graph(id="emin-history-movement-trend", figure=figure,
                         config={"displayModeBar": False}, responsive=True,
                         style={"height": "430px", "width": "100%"})
    if valid:
        metadata = bundle.dashboard.get("metadata", {})
        tolerance = _number(metadata.get("variation_stability_tolerance"))
        if tolerance is None or tolerance < 0:
            # Older v2 captures used an effectively exact comparison.
            tolerance = 0.001
        extent = max(max(item["previous_average"], item["current_average"]) for item in valid) or 1
        extent = max((extent + tolerance) * 1.12, 1)
        band = min(tolerance, extent * 0.45)
        # Match the Predictivo background palette. The producer publishes the
        # stability tolerance so the colored zones agree with point status.
        zones = (
            ("Normal", [(0, 0), (extent, 0), (extent, extent - band), (band, 0), (0, 0)]),
            ("Alerta", [(0, band), (extent - band, extent), (extent, extent),
                        (extent, extent - band), (band, 0), (0, 0), (0, band)]),
            ("Anormal", [(0, band), (0, extent), (extent, extent), (extent - band, extent), (0, band)]),
        )
        for state, points in zones:
            path = "M " + " L ".join(f"{x},{y}" for x, y in points) + " Z"
            figure.add_shape(type="path", xref="x", yref="y", path=path,
                             fillcolor=STATE_ZONE_FILL[state], line={"width": 0}, layer="below")
        for label, x, y, color in (
            (t("emin_history.zone_improving"), 0.20, 0.12, STATE_ZONE_TEXT["Normal"]),
            (t("emin_history.zone_stable"), 0.53, 0.50, STATE_ZONE_TEXT["Alerta"]),
            (t("emin_history.zone_worsening"), 0.82, 0.86, STATE_ZONE_TEXT["Anormal"]),
        ):
            figure.add_annotation(x=x, y=y, xref="paper", yref="paper", text=label,
                                  showarrow=False, font={"size": 11, "color": color},
                                  bgcolor="rgba(255,255,255,0.58)", borderpad=3)
        figure.add_trace(go.Scatter(x=[0, extent], y=[0, extent], mode="lines", name=t("emin_history.no_change_line"),
                                    line={"color": "#8b95a1", "dash": "dash", "width": 1.4}, hoverinfo="skip"))
        figure.update_xaxes(range=[0, extent], rangemode="tozero")
        figure.update_yaxes(range=[0, extent], rangemode="tozero")
    plotted = 0
    for state in ("worsened", "stable", "improved", "insufficient"):
        entries = [(unit, variations.get(unit, {})) for unit in units]
        entries = [(unit, item) for unit, item in entries if item.get("status") == state
                   and _number(item.get("previous_average")) is not None
                   and _number(item.get("current_average")) is not None]
        if not entries:
            continue
        plotted += len(entries)
        figure.add_trace(go.Scatter(
            x=[item["previous_average"] for _, item in entries],
            y=[item["current_average"] for _, item in entries],
            customdata=[[unit, item.get("delta"), item.get("current_days"), item.get("major_event_count", 0), period]
                        for unit, item in entries],
            text=[unit if unit in label_units else "" for unit, _ in entries],
            textposition=[_fleet_point_label_position(item["previous_average"], item["current_average"], index, extent)
                          for index, (_, item) in enumerate(entries)],
            textfont={"size": 10}, mode="markers+text",
            name=_movement_chart_label(state),
            marker={"color": _MOVEMENT_COLORS[state],
                    "size": [17 if unit in priority else 10 for unit, _ in entries],
                    "line": {"color": "white", "width": 1.5}, "opacity": 0.9},
            hovertemplate=("<b>%{customdata[0]}</b><br>"
                           + t("emin_history.previous_period_hover") + ": %{x:.2f}<br>"
                           + t("emin_history.current_period_hover") + ": %{y:.2f}<br>"
                           + t("emin_history.delta_hover") + ": %{customdata[1]:+.2f}<br>"
                           + t("emin_history.coverage_hover") + ": %{customdata[2]}<br>"
                           + t("emin_history.major_events_hover") + ": %{customdata[3]}<extra></extra>"),
        ))
    unavailable = max(0, len(units) - plotted)
    figure.update_xaxes(title_text=t("emin_history.previous_period_axis"), gridcolor="#ecf0f1", rangemode="tozero", automargin=True)
    figure.update_yaxes(title_text=t("emin_history.current_period_axis"), gridcolor="#ecf0f1", rangemode="tozero", automargin=True)
    figure = apply_dashboard_theme(figure, title=t("emin_history.variation_title"), height=485)
    figure.update_layout(hovermode="closest", showlegend=True,
                         margin={"l": 62, "r": 28, "t": 82, "b": 112},
                         legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.32, "yanchor": "top"},
                         clickmode="event+select")
    coverage_note = t("emin_history.fleet_plot_coverage", shown=plotted, total=len(units), unavailable=unavailable)
    if period == "quarter" and plotted == 0:
        coverage_note += "<br>" + t("emin_history.quarter_comparison_unavailable")
    figure.add_annotation(x=0.5, y=1.06, xref="paper", yref="paper", xanchor="center", yanchor="bottom",
                          text=coverage_note,
                          showarrow=False, bgcolor="rgba(255,255,255,.88)", font={"size": 11, "color": BRAND_MUTED})
    return dcc.Graph(id="emin-history-movement-trend", figure=figure,
                     config={"displayModeBar": False}, responsive=True,
                     style={"height": "485px", "width": "100%"})


def _period_delta_figure(rows: list[dict], unit: str | None, period: str) -> dcc.Graph:
    """Plot only producer-supplied period deltas; zero marks no directional movement."""
    usable = [row for row in rows if _number(row.get("delta")) is not None]
    if not usable:
        return dcc.Graph(
            id="emin-history-trend",
            figure=_empty_figure(t("emin_history.trend_title", unit=unit or t("emin_history.no_unit")),
                                 t("emin_history.period_comparison_insufficient"), 340),
            config={"displayModeBar": False}, responsive=True,
            style={"height": "340px", "width": "100%"},
        )
    colors = [_MOVEMENT_COLORS.get(row.get("status"), _MOVEMENT_COLORS["insufficient"]) for row in usable]
    figure = go.Figure(go.Bar(
        x=[row.get("bucket") for row in usable], y=[row["delta"] for row in usable],
        marker={"color": colors, "line": {"color": "white", "width": 1}},
        customdata=[[row.get("previous_average"), row.get("current_average"), row.get("current_days"), row.get("major_event_count", 0)] for row in usable],
        hovertemplate=("%{x}<br>" + t("emin_history.delta_hover") + ": %{y:+.2f}<br>"
                       + t("emin_history.previous_period_hover") + ": %{customdata[0]:.2f}<br>"
                       + t("emin_history.current_period_hover") + ": %{customdata[1]:.2f}<br>"
                       + t("emin_history.coverage_hover") + ": %{customdata[2]}<br>"
                       + t("emin_history.major_events_hover") + ": %{customdata[3]}<extra></extra>"),
    ))
    figure.add_hline(y=0, line={"color": "#64748b", "width": 1.5})
    figure.update_xaxes(title_text=t("emin_history.period_axis", period=t(f"emin_history.period_{period}")),
                        gridcolor="#ecf0f1", automargin=True)
    figure.update_yaxes(title_text=t("emin_history.delta_hover"), zeroline=False,
                        gridcolor="#ecf0f1", automargin=True)
    figure = apply_dashboard_theme(figure, title=t("emin_history.trend_title", unit=unit or t("emin_history.no_unit")), height=340)
    figure.update_layout(showlegend=False, margin={"l": 58, "r": 24, "t": 54, "b": 68})
    return dcc.Graph(id="emin-history-trend", figure=figure,
                     config={"displayModeBar": False}, responsive=True,
                     style={"height": "340px", "width": "100%"})


def _cumulative_score_figure(rows: list[dict], unit: str | None) -> dcc.Graph:
    """Render producer-calculated cumulative weekly means without filling data gaps."""
    usable = [row for row in rows if _number(row.get("cumulative_score")) is not None]
    if not usable:
        figure = _empty_figure(t("emin_history.cumulative_score_title", unit=unit or t("emin_history.no_unit")),
                               t("emin_history.cumulative_score_empty"), 340)
    else:
        figure = go.Figure(go.Scatter(
            x=[row.get("week") for row in rows],
            y=[row.get("cumulative_score") for row in rows],
            customdata=[[row.get("weekly_mean"), row.get("observed_days"), row.get("available_days"),
                         t("emin_history.iso_week_partial") if not row.get("complete", False)
                         else t("emin_history.iso_week_complete")] for row in rows],
            mode="lines+markers",
            line={"color": BRAND_ACCENT, "width": 3},
            marker={"size": 6, "color": BRAND_ACCENT, "line": {"color": "white", "width": 1}},
            fill="tozeroy", fillcolor="rgba(93, 123, 170, 0.12)",
            connectgaps=False,
            hovertemplate=("%{x}<br>" + t("emin_history.cumulative_weekly_hover") + ": %{customdata[0]:.2f}<br>"
                           + t("emin_history.cumulative_total_hover") + ": %{y:.2f}<br>"
                           + t("emin_history.cumulative_coverage_hover") + ": %{customdata[1]} / %{customdata[2]}<br>"
                           + "%{customdata[3]}<extra></extra>"),
        ))
        ticks = [row["week"] for index, row in enumerate(rows) if index % 4 == 0 or index == len(rows) - 1]
        figure.update_xaxes(title_text=t("emin_history.iso_week_axis"), tickmode="array", tickvals=ticks,
                            ticktext=ticks, tickangle=-35, gridcolor="#ecf0f1", automargin=True,
                            tickfont={"size": 9})
        figure.update_yaxes(title_text=t("emin_history.cumulative_score_axis"), rangemode="tozero",
                            gridcolor="#ecf0f1", automargin=True)
        figure = apply_dashboard_theme(
            figure,
            title=t("emin_history.cumulative_score_title", unit=unit or t("emin_history.no_unit")),
            height=340,
        )
        figure.update_layout(showlegend=False, hovermode="x unified", margin={"l": 62, "r": 22, "t": 52, "b": 74})
    return dcc.Graph(id="emin-history-cumulative-score", figure=figure,
                     config={"displayModeBar": False}, responsive=True,
                     style={"height": "340px", "width": "100%"})


def _open_unit(unit: str, origin: str, period: str = ""):
    return html.Button(
        unit,
        type="button",
        className="fleet-unit-link emin-history-unit-link",
        **{
            "data-emin-open-unit": unit,
            "data-emin-origin": origin,
            "data-emin-period": period,
            "aria-label": t("emin_history.open_unit_label", unit=unit),
        },
    )


CRITICALITY_PERIODS = {"week": 7, "month": 31, "quarter": 92, "history": None}


def fleet_criticality_top(bundle: EminHistoricalBundle, day, period):
    """Read the producer's precomputed top for one selected cutoff and window."""
    period = period if isinstance(period, str) and period in CRITICALITY_PERIODS else "week"
    available = bundle.dashboard.get("catalog", {}).get("cutoffs", [])
    periods = bundle.dashboard.get("period_tops", {})
    cutoff = day if day in periods else (available[0] if available else None)
    if cutoff in periods:
        return periods.get(cutoff, {}).get(period, {})
    # A legacy v1 package can still serve weekly and historical tops; it has no
    # calendar-month or quarter read models, so those views remain unavailable.
    legacy = {"week": "short", "history": "history"}.get(period)
    return bundle.dashboard.get("tops", {}).get(cutoff, {}).get(legacy, {}) if legacy else {}


def _movement_drivers_panel(movement, changes):
    previous, current = movement.get("previous"), movement.get("current")
    if not previous or not current or not changes:
        return None
    rows = [
        html.Tr([
            html.Th(t(f"emin_history.drivers_{item['key']}") if item["key"] in {"alert_points", "oil_points", "unattributed"} else item["key"], scope="row", className="emin-history-driver-label"),
            html.Td(f"{item['before']:.2f}", className="text-end"),
            html.Td(f"{item['after']:.2f}", className="text-end"),
            html.Td(f"{item['delta']:+.2f}", className="text-end fw-semibold"),
        ])
        for item in changes
    ]
    headings = [
        html.Th(t("emin_history.drivers_category"), scope="col"),
        html.Th(_day_label(previous["day"]), scope="col", className="text-end"),
        html.Th(_day_label(current["day"]), scope="col", className="text-end"),
        html.Th(t("emin_history.driver_change_delta"), scope="col", className="text-end"),
    ]
    return dbc.Card([
        section_header(t("emin_history.driver_change_title"), "fas fa-exchange-alt"),
        dbc.CardBody(html.Details([
            html.Summary(t("emin_history.driver_change_summary", count=len(changes), delta=f'{movement["delta"]:+.2f}')),
            html.P(t("emin_history.driver_change_note"), className="small text-muted mt-2 mb-2"),
            dbc.Table([
                html.Thead(html.Tr(headings)),
                html.Tbody(rows),
            ], responsive=True, size="sm", class_name="emin-history-table emin-history-drivers-table mb-0"),
        ], open=False)),
    ], class_name="shadow-sm unit-card mb-3")


def _criticality_components_panel(data):
    body = []
    components = data.get("components", []) if isinstance(data, dict) else []
    if not data or not data.get("observed_days"):
        body.append(html.P(t("emin_history.drivers_no_observation"), className="text-muted mb-0"))
    else:
        context = t("emin_history.drivers_period", start=_day_label(data["start"]), end=_day_label(data["cutoff"]), count=data["observed_days"])
        body.append(html.P(context, className="small text-muted mb-2"))
        if not components:
            body.append(html.P(t("emin_history.drivers_zero"), className="mb-0"))
        else:
            total = sum(item["points"] for item in components)
            attributed = data.get("attributed_points", 0)
            special_keys = {"alert_points", "oil_points", "unattributed"}
            labels_by_key = {
                item["key"]: t(f"emin_history.drivers_{item['key']}")
                if item["key"] in special_keys else item["key"]
                for item in components
            }
            body.append(html.P(
                t("emin_history.drivers_attribution", points=f"{attributed:.2f}", total=f"{total:.2f}"),
                className="mb-2 fw-semibold",
            ))
            labels = [labels_by_key[item["key"]] for item in components]
            figure = go.Figure(go.Bar(
                x=[item["points"] for item in components],
                y=labels,
                orientation="h",
                marker={"color": BRAND_ACCENT},
                text=[f"{item['points']:.2f} · {item['share']:.0%}" for item in components],
                textposition="outside",
                cliponaxis=False,
                customdata=[item["share"] for item in components],
                hovertemplate="%{y}<br>%{x:.2f} · %{customdata:.1%}<extra></extra>",
            ))
            height = max(230, min(420, 80 + len(components) * 44))
            figure = apply_dashboard_theme(figure, title=t("emin_history.drivers_chart_title"), height=height)
            figure.update_layout(
                showlegend=False,
                margin={"l": 150, "r": 45, "t": 52, "b": 35},
                xaxis={"title": None, "rangemode": "tozero", "gridcolor": "#ecf0f1", "zeroline": False},
                yaxis={"title": None, "categoryorder": "array", "categoryarray": labels[::-1]},
            )
            body.append(dcc.Graph(
                figure=figure,
                config={"displayModeBar": False},
                responsive=True,
                style={"height": f"{height}px", "width": "100%"},
            ))
            body.append(html.Details([
                html.Summary(t("emin_history.drivers_show_events")),
                html.Ul([
                    html.Li([
                        html.Strong(f"{labels_by_key[item['key']]} · {item['points']:.2f} ({item['share']:.0%})"),
                        html.Ul([
                            html.Li(f"{_day_label(event['day'])} · {event['event'] or t('emin_history.drivers_event_unavailable')} · {event['points']:.2f}")
                            for event in item.get("events", [])[:12]
                        ]) if item.get("events") else None,
                    ])
                    for item in components
                ], className="mb-0"),
            ], className="emin-history-driver-evidence mb-2"))
            body.append(html.P(t("emin_history.drivers_note"), className="small text-muted mb-0"))
    return dbc.Card([
        section_header(t("emin_history.drivers_title"), "fas fa-cogs"),
        dbc.CardBody(body),
    ], class_name="shadow-sm unit-card mb-3")


def fleet_criticality_panel(bundle, day, period):
    period = period if isinstance(period, str) and period in CRITICALITY_PERIODS else "week"
    payload = fleet_criticality_top(bundle, day, period)
    entries = payload.get("entries", [])
    start, cutoff = payload.get("start"), payload.get("cutoff")
    span = payload.get("span_days", 0)
    insufficient = payload.get("insufficient_units", 0)
    if not start:
        return html.P(t("emin_history.top_empty"), className="text-muted mb-0")
    cards = []
    for rank, entry in enumerate(entries, 1):
        unit = entry["unit"]
        reason_data = entry.get("reason", {})
        critical_days = entry.get("critical_days", 0)
        if reason_data.get("kind") == "critical_days":
            reason = t("emin_history.top_critical_days", count=reason_data.get("count", 0))
        elif reason_data.get("kind") == "intervention_days":
            reason = t("emin_history.top_intervention_days", count=reason_data.get("count", 0))
        else:
            signal = t("emin_history.top_signal_count", count=reason_data.get("positive_days", 0), observed=reason_data.get("observed_days", 0))
            average = reason_data.get("average")
            average_label = t("emin_history.top_average", score=f"{average:.2f}") if average is not None else ""
            reason = f"{average_label} · {signal}" if period == "week" else f"{signal} · {average_label}"
        main_group = entry.get("main_component")
        card_body = [
            html.Div([
                dbc.Badge(f"#{rank}", color="danger" if critical_days else "primary"),
                _open_unit(unit, "criticality", period),
            ], className="d-flex align-items-center gap-2 mb-2"),
            html.Div([
                dbc.Badge(reason, color="danger", class_name="text-wrap text-start") if critical_days else html.Strong(reason),
                html.Small(t("emin_history.top_main_component", component=main_group), className="d-block text-muted")
                if main_group else None,
            ], className="mb-2"),
            _movement_summary(payload.get("movement_by_unit", {}).get(unit, {"status": "insufficient"})),
            html.Small([
                t("emin_history.top_last_milestone"), ": ",
                _day_label(entry["latest_milestone"]) if entry.get("latest_milestone") else "—",
            ], className="d-block text-muted mt-2"),
            html.Small([
                t("emin_history.top_coverage"), ": ",
                html.Strong(f"{entry.get('observed_days', 0)}/{span}"),
            ], className="d-block text-muted"),
        ]
        cards.append(dbc.Col(
            dbc.Card(dbc.CardBody(card_body), class_name=(
                "emin-history-top-unit-card h-100 "
                + ("emin-history-top-unit-card--critical" if critical_days else "")
            )),
            xs=12, sm=6, xl=4,
        ))
    coverage = payload.get("covered_days", 0)
    same_scores = payload.get("overlaps_short", False)
    history_uses_signal = payload.get("history_signal_only", False)
    return html.Div([
        html.P(t(f"emin_history.top_question_{period}"), className="fw-semibold mb-1"),
        html.P(t("emin_history.top_window", start=_day_label(start), end=_day_label(cutoff)), className="small text-muted mb-1"),
        html.P(t("emin_history.top_coverage_days", count=coverage, span=span), className="small text-muted mb-2"),
        html.P(t("emin_history.top_overlap"), className="small text-muted mb-2") if same_scores else None,
        html.P(t("emin_history.top_history_coverage"), className="small text-muted mb-2") if period == "history" else None,
        html.P(t("emin_history.top_history_signal_only"), className="small text-muted mb-2") if history_uses_signal else None,
        dbc.Row(cards, class_name="g-2 mb-2")
        if cards else html.P(t("emin_history.top_empty"), className="text-muted mb-2"),
        html.Small(t("emin_history.top_low_coverage", count=insufficient), className="text-muted"),
    ])


def _top_unit_context(bundle, cutoff, period, unit, trend_rows, evidence_rows):
    payload = fleet_criticality_top(bundle, cutoff, period)
    entries = payload.get("entries", [])
    match = next(((position, entry) for position, entry in enumerate(entries, 1) if entry["unit"] == unit), None)
    if not match:
        return None
    position, entry = match
    start, span = payload.get("start"), payload.get("span_days", 0)
    reason_data = entry.get("reason", {})
    if reason_data.get("kind") == "critical_days":
        reason = t("emin_history.top_critical_days", count=reason_data.get("count", 0))
    elif reason_data.get("kind") == "intervention_days":
        reason = t("emin_history.top_intervention_days", count=reason_data.get("count", 0))
    else:
        signal = t("emin_history.top_signal_count", count=reason_data.get("positive_days", 0), observed=reason_data.get("observed_days", 0))
        average = reason_data.get("average")
        average_label = t("emin_history.top_average", score=f"{average:.2f}") if average is not None else ""
        reason = f"{average_label} · {signal}" if period == "week" else f"{signal} · {average_label}"
    context = [
        html.P(t("emin_history.top_unit_position", rank=position, period=t(f"emin_history.top_{period}")), className="mb-1 fw-semibold"),
        html.P(reason, className="mb-1"),
        html.P(t("emin_history.top_coverage_days", count=entry.get("observed_days", 0), span=span), className="text-muted small mb-2"),
    ]
    if entry.get("critical_days"):
        context.append(html.P([
            t("emin_history.top_source_on", day=_day_label(entry.get("latest_critical"))), " ",
            html.A(t("emin_history.top_go_evidence"), href="#emin-history-milestones"),
        ], className="mb-2"))
    elif period == "history" and entry.get("intervention_days"):
        context.append(html.P([
            t("emin_history.top_intervention_on", day=_day_label(entry.get("latest_intervention"))), " ",
            html.A(t("emin_history.top_go_evidence"), href="#emin-history-milestones"),
        ], className="mb-2"))
    return dbc.Card([
        section_header(t("emin_history.top_why_unit"), "fas fa-clipboard-list"),
        dbc.CardBody(context),
    ], class_name="shadow-sm unit-card mb-3")


def _movement_summary(movement: dict):
    previous, current = movement.get("previous"), movement.get("current")
    if previous and current:
        dates = t("emin_history.comparison_dates", previous=_day_label(previous["day"]), current=_day_label(current["day"]))
    elif current:
        dates = t("emin_history.last_observation", day=_day_label(current["day"]))
    else:
        dates = None
    return html.Div([
        _movement_badge(movement),
        html.Small(dates, className="d-block text-muted mt-1") if dates else None,
        *[html.Small(note, className="d-block text-muted") for note in _movement_date_notes(movement)],
    ])


def fleet_highlights_panel(highlights: dict, daily_rows: list[dict], movements: dict[str, dict]):
    scores = highlights.get("scores", {})
    has_history = highlights["has_history"]
    healthy_units = highlights.get("healthiest", [])
    lower_note = "distinct_scores_required"
    if highlights["can_distinguish"]:
        lower_note = "lower_signal_note" if has_history else "lower_signal_partial"
    unit_list = html.Ul([
        html.Li([
            html.Div([
                _open_unit(unit, "lowest_observed_score"),
                html.Small(
                    t("emin_history.score_on_cut", score=f"{scores[unit]:.3f}", day=_day_label(highlights["coverage_end"]))
                    if unit in scores else t("emin_history.no_observed_scores"),
                    className="d-block text-muted",
                ),
            ]),
            _movement_summary(movements.get(unit, {"status": "insufficient"})),
        ], className="emin-history-unit-item")
        for unit in healthy_units
    ], className="list-unstyled mb-0") if healthy_units else html.P(
        t("emin_history.no_highlights"), className="text-muted small mb-0",
    )
    return dbc.Card([
        section_header(
            t("emin_history.healthiest_title" if has_history else "emin_history.lowest_cut_title"),
            "fas fa-heartbeat",
        ),
        dbc.CardBody([
            html.Details([
                html.Summary(t("emin_history.lower_criticality_expand")),
                html.P(t(f"emin_history.{lower_note}"), className="text-muted small my-2"),
                unit_list,
            ]),
        ]),
    ], class_name="shadow-sm unit-card h-100")


def _empty_figure(title: str, message: str, height: int = 340) -> go.Figure:
    figure = go.Figure()
    figure.add_annotation(text=message, showarrow=False, font={"color": BRAND_MUTED, "size": 13})
    return apply_dashboard_theme(figure, title=title, height=height)


def _trend_figure(rows: list[dict], unit: str | None, movement_status: str = "insufficient") -> go.Figure:
    title = t(
        "emin_history.trend_title_status",
        unit=unit or t("emin_history.no_unit"),
        status=_movement_label(movement_status),
    )
    if not rows:
        return _empty_figure(title, t("emin_history.empty_trend"), 430)
    observed = [
        _number(row.get("points"))
        if row.get("has_observation") is True and not row.get("estimated") else None
        for row in rows
    ]
    estimated = [
        (row["day"], score)
        for row in rows
        if row.get("estimated") and (score := _number(row.get("points"))) is not None
    ]
    if all(score is None for score in observed) and not estimated:
        return _empty_figure(title, t("emin_history.empty_trend"), 430)
    figure = go.Figure(go.Scatter(
        x=[row["day"] for row in rows],
        y=observed,
        name=t("emin_history.observed"),
        mode="lines+markers",
        line={"color": BRAND_ACCENT, "width": 2},
        marker={"size": 4, "color": BRAND_ACCENT},
        hovertemplate="%{x|%d-%m-%Y}<br>%{y:.2f}<extra>%{fullData.name}</extra>",
        connectgaps=False,
    ))
    if estimated:
        figure.add_trace(go.Scatter(
            x=[day for day, _ in estimated],
            y=[score for _, score in estimated],
            name=t("emin_history.estimated"),
            mode="markers",
            marker={"size": 8, "color": BRAND_MUTED, "symbol": "diamond-open"},
            hovertemplate="%{x|%d-%m-%Y}<br>%{y:.2f}<extra>%{fullData.name}</extra>",
        ))
    figure.update_xaxes(type="date", title_text=t("emin_history.axis_day"), gridcolor="#ecf0f1", automargin=True, tickformat="%d %b", tickfont={"size": 9})
    figure.update_yaxes(
        title_text=t("emin_history.axis_score"), gridcolor="#ecf0f1", automargin=True,
        autorangeoptions={"include": 0},
    )
    scores = [score for score in observed if score is not None] + [score for _, score in estimated]
    if max(scores) == 0:
        figure.update_yaxes(range=[-0.05, 1], tickvals=[0, 1])
    figure = apply_dashboard_theme(figure, title=title, height=430)
    figure.update_layout(margin={"l": 62, "r": 22, "t": 52, "b": 70}, legend={"orientation": "h", "y": -0.28})
    return figure


def _groups_panel_from_items(items, selected_group):
    if not items:
        return html.P(t("emin_history.empty_groups"), className="text-muted mb-0")
    ordered = list(items)
    return html.Details([
        html.Summary(t("emin_history.group_explore")),
        html.P(t("emin_history.group_explore_note"), className="small text-muted my-2"),
        html.Ul([
            html.Li(html.Button([
                html.Span(item["group"]),
                dbc.Badge(str(item["count"]), color="primary" if item["group"] == selected_group else "secondary"),
            ], type="button", className="btn btn-sm btn-outline-secondary d-flex align-items-center gap-2",
                **{"data-emin-group-filter": item["group"], "aria-pressed": str(item["group"] == selected_group).lower()}))
            for item in ordered
        ], className="list-unstyled d-flex flex-wrap gap-2 mb-0"),
    ])


def _observation_label(row: dict) -> str:
    if row.get("estimated"):
        return t("emin_history.estimated")
    if row.get("has_observation"):
        return t("emin_history.observed")
    return t("emin_history.no_record")


def _movement_badge(movement: dict):
    status = movement["status"]
    colors = {"improved": "success", "worsened": "danger", "stable": "primary", "insufficient": "secondary"}
    return dbc.Badge(_movement_label(status), color=colors[status], class_name="emin-history-movement-badge")


def _ranking_table(rows: list[dict], movements: dict[str, dict], high_counts=None):
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
        observed = row.get("has_observation") is True and not row.get("estimated")
        score = _number(row.get("points")) if observed or row.get("estimated") else None
        groups = row.get("event_groups", [])
        group_label = ", ".join(str(value) for value in groups[:2])
        if len(groups) > 2:
            group_label += f" +{len(groups) - 2}"
        cells = [
            row.get("rank") if score is not None and row.get("rank") is not None else "—",
            [
                _open_unit(row["unit"], "ranking"),
                html.Small(t("emin_history.ranking_high_count", count=high_counts[row["unit"]]), className="d-block text-muted")
                if high_counts is not None else None,
            ],
            f"{score:.3f}" if score is not None else "—",
            _movement_summary(movements[row["unit"]]),
            _observation_label(row),
            row.get("alerts", 0) if observed else "—",
            row.get("health_events", 0) if observed else "—",
            group_label or "—",
        ]
        body_rows.append(html.Tr([html.Td(value) for value in cells]))
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
            *[html.Small(note, className="d-block text-muted") for note in _movement_date_notes(movement)],
            html.Div(points, className="emin-history-comparison-points"),
            html.Button(
                t("emin_history.open_latest_observation_records"), type="button",
                className="btn btn-link btn-sm p-0 mt-2",
                **{"data-emin-record-filter": "all", "data-emin-record-query": current["day"]},
            ) if current else None,
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
        "maintenance_week": t("emin_history.kind_maintenance"),
        "downtime_observed": t("emin_history.kind_downtime"),
        "downtime_record": t("emin_history.kind_downtime"),
        "downtime": t("emin_history.kind_downtime"),
        "stop": t("emin_history.kind_downtime"),
    }
    return labels.get(kind, kind.replace("_", " ").capitalize() if kind else "—")


def _normalized_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _major_event(row: dict) -> str | None:
    """Read the producer's event classification; this module only labels it."""
    analysis = row.get("analysis")
    return analysis.get("major_event") if isinstance(analysis, dict) else None


CHRONOLOGY_PAGE_SIZE = 40
CHRONOLOGY_SOURCE_TYPES = ("event", "alert", "maintenance", "downtime", "oil", "other")
CHRONOLOGY_TYPES = ("all", "milestones", "high_signal", "replacements", *CHRONOLOGY_SOURCE_TYPES)


def _unit_evidence_rows(bundle, unit, cutoff):
    rows = bundle.dashboard.get("units", {}).get(unit, {}).get("evidence", [])
    return [row for row in rows if not cutoff or str(row.get("day") or "") <= cutoff]


def _evidence_type(row):
    kind = str(row.get("kind") or "")
    if kind.startswith("maintenance_"):
        return "maintenance"
    if kind.startswith("downtime_") or kind in {"downtime", "stop"}:
        return "downtime"
    return kind if kind in {"event", "alert", "oil"} else "other"


def _is_high_signal(row):
    return bool((row.get("analysis") or {}).get("high_signal"))


def _high_signals_panel(rows, start, cutoff):
    if not cutoff:
        return None
    start = start or (date.fromisoformat(cutoff) - timedelta(days=6)).isoformat()
    events = [
        row for row in rows
        if start <= str(row.get("day") or "") <= cutoff and _is_high_signal(row)
    ]
    if not events:
        return None
    days = {row["day"] for row in events}
    return dbc.Card([
        section_header(t("emin_history.chronology_high_signal"), "fas fa-exclamation-circle"),
        dbc.CardBody([
            html.P(t(
                "emin_history.high_signal_summary", count=len(events), days=len(days),
                start=_day_label(start), end=_day_label(cutoff),
            ), className="small text-muted mb-2"),
            html.P(t("emin_history.high_signal_note"), className="small text-muted mb-2"),
            html.Details([
                html.Summary(t("emin_history.high_signal_latest", count=min(3, len(events)))),
                html.Ul([
                    html.Li([
                        html.Strong(str(row["details"].get("Evento") or t("emin_history.drivers_event_unavailable"))),
                        html.Small(_format_timestamp(row.get("event_at") or row["day"]), className="d-block text-muted"),
                        _record_disclosure(row, t("emin_history.chronology_high_signal")),
                    ], className="emin-history-milestone py-2")
                    for row in events[:3]
                ], className="list-unstyled mb-0"),
            ]),
            html.Button(
                t("emin_history.high_signal_open_chronology"), type="button",
                className="btn btn-sm btn-outline-primary mt-2",
                **{"data-emin-record-filter": "high_signal", "data-emin-record-query": f"{start}..{cutoff}"},
            ),
        ]),
    ], class_name="shadow-sm unit-card mb-3")


def _executed_replacement(row):
    """Read the producer's documented replacement date, without reclassifying text."""
    return (row.get("analysis") or {}).get("replacement_day")


def _replacement_records(rows, cutoff):
    dated = []
    for row in rows:
        day = _executed_replacement(row)
        if day and (not cutoff or day <= cutoff):
            dated.append((day, row))
    return sorted(dated, key=lambda item: item[0], reverse=True)


def _replacements_panel(rows, cutoff):
    replacements = _replacement_records(rows, cutoff)
    if not replacements:
        return None
    return dbc.Card([
        section_header(t("emin_history.chronology_replacements"), "fas fa-tools"),
        dbc.CardBody([
            html.P(t("emin_history.replacements_summary", total=len(replacements), shown=min(3, len(replacements))),
                   className="small text-muted mb-2"),
            html.Ul([
                html.Li([
                    html.Strong(row["details"].get("Componente") or t("emin_history.replacements_unknown_component")),
                    html.Small(_day_label(day), className="d-block text-muted"),
                    _record_disclosure(row, t("emin_history.chronology_replacements")),
                ], className="emin-history-milestone py-2")
                for day, row in replacements[:3]
            ], className="list-unstyled mb-2"),
            html.Button(
                t("emin_history.replacements_open_chronology"), type="button",
                className="btn btn-sm btn-outline-primary",
                **{"data-emin-record-filter": "replacements"},
            ),
        ]),
    ], class_name="shadow-sm unit-card mb-3")


def _milestone_badge(level):
    labels = {"source": "major_source", "intervention": "major_intervention", "text": "major_text"}
    colors = {"source": "danger", "intervention": "primary", "text": "warning"}
    return dbc.Badge(t(f"emin_history.{labels[level]}"), color=colors[level], text_color="dark" if level == "text" else "white")


def _record_disclosure(row, fallback):
    fields = row.get("details")
    evidence = (
        html.Dl([
            element
            for key, value in fields.items() if value not in (None, "")
            for element in (html.Dt(str(key)), html.Dd(str(value)))
        ], className="mb-0")
        if isinstance(fields, dict) and fields
        else html.P(str(row.get("summary") or row.get("description") or fallback), className="mb-0")
    )
    return html.Details([
        html.Summary(t("emin_history.open_record")),
        evidence,
    ], className="emin-history-record mt-2")


def _chronology_table(rows, *, expand_records=False):
    table_head = html.Thead(html.Tr([
        html.Th(t("emin_history.evidence_time"), scope="col"),
        html.Th(t("emin_history.evidence_source"), scope="col"),
        html.Th(t("emin_history.evidence_detail"), scope="col"),
        html.Th(t("emin_history.major_event"), scope="col"),
    ]))
    table_rows = []
    for row in rows:
        major = _major_event(row)
        detail = _source_detail(row.get("details") or row.get("summary") or row.get("description") or {})
        table_rows.append(html.Tr(
            [
                html.Td(_format_timestamp(row.get("event_at") or row.get("day"))),
                html.Td(_kind_label(str(row.get("kind", "")))),
                html.Td([detail, _record_disclosure(row, detail)] if expand_records else detail),
                html.Td(_milestone_badge(major) if major else html.Span("—", className="text-muted")),
            ],
            className="emin-history-major-row" if major else None,
        ))
    return html.Div(
        dbc.Table([table_head, html.Tbody(table_rows)], hover=True, striped=True, responsive=True,
                  class_name="emin-history-evidence-table align-middle mb-0"),
        className="emin-history-evidence-scroll",
    )


def chronology_page(bundle, unit, cutoff, kind, query, page):
    unit = unit or filter_options(bundle)["default_unit"]
    cutoff = cutoff or next(iter(bundle.dashboard.get("catalog", {}).get("cutoffs", [])), None)
    rows = _unit_evidence_rows(bundle, unit, cutoff)
    needle = _normalized_text((query or "").strip())
    event_day, separator, event_name = needle.partition(" · ")
    exact_event = kind == "event" and separator and re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_day)
    day_range = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", needle)
    exact_day = re.fullmatch(r"\d{4}-\d{2}-\d{2}", needle)
    filtered = []
    candidates = (
        [row for _, row in _replacement_records(rows, cutoff)] if kind == "replacements" else rows
    )
    for row in candidates:
        if kind == "milestones" and not _major_event(row):
            continue
        if kind == "high_signal" and not _is_high_signal(row):
            continue
        if kind in CHRONOLOGY_SOURCE_TYPES and kind != _evidence_type(row):
            continue
        if exact_event:
            details = row.get("details") or {}
            if not isinstance(details, dict) or row.get("day") != event_day or _normalized_text(str(details.get("Evento") or "").strip()) != event_name:
                continue
        elif day_range:
            if not day_range[1] <= str(row.get("day") or "") <= day_range[2]:
                continue
        elif exact_day:
            if row.get("day") != needle:
                continue
        elif needle:
            fields = (row.get("event_at"), row.get("details"), row.get("summary"), row.get("description"))
            if needle not in _normalized_text(" ".join(str(field) for field in fields if field)):
                continue
        filtered.append(row)

    size = CHRONOLOGY_PAGE_SIZE
    last_page = max(0, (len(filtered) - 1) // size)
    page = min(max(0, page), last_page)
    start = page * size
    page_rows = filtered[start:start + size]
    content = html.Div([
        html.P(t(
            "emin_history.chronology_showing", start=start + 1, end=start + len(page_rows),
            count=len(filtered), total=len(rows),
        ), className="small text-muted mb-2", role="status"),
        _chronology_table(page_rows, expand_records=True),
    ]) if page_rows else html.P(t("emin_history.chronology_no_match"), className="text-muted mb-0")
    return content, page, page == 0, page == last_page


def _timeline_panel(unit: str | None, rows: list[dict], period_start=None, cutoff=None, include_chronology=True):
    heading = html.Div(
        [
            html.Strong(unit or t("emin_history.no_unit")),
            html.Span(t("emin_history.timeline_count", count=len(rows)), className="text-muted ms-2"),
        ],
        className="emin-history-evidence-heading mb-2",
    )
    if not rows:
        return html.Div([heading, dbc.Alert(t("emin_history.empty_timeline"), color="light", class_name="mb-0")])

    highlights = []
    for row in rows:
        major = _major_event(row)
        if major:
            detail = _source_detail(row.get("details") or row.get("summary") or row.get("description") or {})
            highlights.append((major, str(row.get("event_at") or row.get("day") or ""), row, detail))
    highlights.sort(key=lambda item: item[1], reverse=True)
    priority = {"source": 0, "intervention": 1, "text": 2}
    highlights.sort(key=lambda item: (
        bool(period_start and str(item[2].get("day") or "") < period_start),
        priority[item[0]],
    ))

    def event_row(item):
        level, _, row, detail = item
        return html.Li([
            html.Div([
                _milestone_badge(level),
                html.Span(_format_timestamp(row.get("event_at") or row.get("day")), className="text-muted small"),
            ], className="d-flex flex-wrap gap-2 mb-2"),
            html.Div(detail, className="emin-history-highlight-detail"),
            _record_disclosure(row, detail),
        ], className="emin-history-milestone py-2")

    highlight_body = (
        [
            html.Ul([event_row(item) for item in highlights[:3]], className="list-unstyled mb-0"),
            html.Details([
                html.Summary(t("emin_history.show_more", count=len(highlights) - 3)),
                html.Ul([event_row(item) for item in highlights[3:]], className="list-unstyled mb-0"),
            ]) if len(highlights) > 3 else None,
        ]
        if highlights else [html.P(t("emin_history.no_major_events"), className="text-muted mb-0")]
    )
    return html.Div([
        dbc.Card([
            section_header(t("emin_history.highlights_title"), "fas fa-flag"),
            dbc.CardBody([
                html.P(t("emin_history.top_detail_window", start=_day_label(period_start), end=_day_label(cutoff)), className="small text-muted")
                if period_start else None,
                *highlight_body,
            ]),
        ], id="emin-history-milestones", class_name="shadow-sm unit-card mb-3"),
        _high_signals_panel(rows, period_start, cutoff),
        _replacements_panel(rows, cutoff),
        dbc.Card([
            section_header(t("emin_history.evidence_title"), "fas fa-history"),
            dbc.CardBody([
                heading, _chronology_table(rows[:CHRONOLOGY_PAGE_SIZE]),
                html.Small(t("emin_history.timeline_note", count=len(rows)), className="text-muted d-block mt-2"),
            ]),
        ], class_name="shadow-sm unit-card mb-3") if include_chronology else None,
    ])
