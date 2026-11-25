"""Presentation helpers for the EMIN historical fleet page."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from math import isfinite
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
    search: str | None = None,
    movement_filter: str | None = None,
    evidence_period: str | None = None,
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
    query = (search or "").strip().casefold()
    filtered_rows = [
        row for row in filtered_rows
        if query in row["unit"].casefold()
        and (movement_filter in (None, "__all__") or movements[row["unit"]]["status"] == movement_filter)
    ]
    status = movements.get(selected_unit) or _movement_for_unit(bundle.daily, selected_unit, selected_day)
    evidence_rows = [
        row for row in bundle.observed
        if row.get("unit") == selected_unit and (not selected_day or str(row.get("day") or "") <= selected_day)
    ]
    evidence_rows.sort(
        key=lambda row: (str(row.get("event_at") or row.get("day") or ""), str(row.get("kind", ""))),
        reverse=True,
    )
    period_start = (
        _criticality_start(all_days, selected_day, evidence_period, evidence_rows)
        if isinstance(evidence_period, str) and evidence_period in CRITICALITY_PERIODS
        else None
    )
    top_context = (
        _top_unit_context(bundle, selected_day, evidence_period, selected_unit, trend_rows, evidence_rows)
        if period_start else None
    )
    contributors = _criticality_components_panel(trend_rows, period_start, selected_day)
    fleet_highlights = _fleet_highlights(daily_rows, bundle.observed, selected_day)

    return {
        "meta": _metadata(bundle, selected_day),
        "daily_rows": daily_rows,
        "fleet_highlights": fleet_highlights,
        "movements": movements,
        "kpis": _movement_kpis(movements),
        "movement": _movement_figure(movements),
        "groups": _groups_figure(daily_rows, group),
        "ranking": _ranking_table(filtered_rows, movements),
        "status": html.Div([top_context, _status_panel(selected_unit, status), contributors]),
        "trend": _trend_figure(trend_rows, selected_unit),
        "evidence": _timeline_panel(selected_unit, evidence_rows, period_start, selected_day),
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
    captions = [
        t("emin_history.cutoff_meta", day=_day_label(selected_day)),
        t("emin_history.captured_meta", timestamp=_format_timestamp(evidence_as_of)),
        t("emin_history.days_meta", count=len({row["day"] for row in bundle.daily})),
        t("emin_history.units_meta", count=len({row["unit"] for row in bundle.daily})),
    ]
    return html.Small(" · ".join(captions), className="text-muted")


def section_header(title: str, icon: str):
    """Match the section headers used in Resumen de unidad."""
    return dbc.CardHeader(
        html.H5([html.I(className=f"{icon} me-2", **{"aria-hidden": "true"}), title], className="mb-0"),
        class_name="bg-light",
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
        number = float(value)
        return number if isfinite(number) else None
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


def _fleet_highlights(daily_rows: list[dict], observed_rows: tuple[dict, ...], cutoff: str | None):
    """Build source-backed critical and lower-score lists for the selected cut."""
    try:
        start = (date.fromisoformat(cutoff) - timedelta(days=6)).isoformat()
    except (TypeError, ValueError):
        start = cutoff

    known_units = {row["unit"] for row in daily_rows}
    critical_events = {}
    for row in observed_rows:
        unit = row.get("unit")
        day = str(row.get("day") or "")
        if not start or unit not in known_units or not start <= day <= cutoff:
            continue
        if _explicit_milestone(row) == "source" and day > critical_events.get(unit, ""):
            critical_events[unit] = day
    critical_units = set(critical_events)
    scored = [
        row for row in daily_rows
        if row.get("has_observation") is True and not row.get("estimated")
        and (score := _number(row.get("points"))) is not None
        and score >= 0 and isfinite(score)
    ]
    scored.sort(key=lambda row: (_number(row.get("points")), str(row.get("unit", "")).casefold()))
    critical = sorted(critical_units, key=str.casefold)
    critical.sort(key=critical_events.get, reverse=True)
    eligible = [row for row in scored if row.get("unit") not in critical_units]
    distinct_scores = sorted({_number(row["points"]) for row in eligible})
    low_signal, score_priority = [], []
    if len(distinct_scores) >= 2:
        upper_start = distinct_scores[len(distinct_scores) // 2]
        low_signal = [row for row in eligible if _number(row["points"]) < upper_start][:5]
        upper = [row for row in eligible if _number(row["points"]) >= upper_start]
        score_priority = sorted(upper, key=lambda row: -_number(row["points"]))[:5]
    return {
        "critical": critical[:5],
        "critical_remaining": critical[5:],
        "critical_events": critical_events,
        "has_history": any(start and start <= str(row.get("day") or "") <= cutoff for row in observed_rows),
        "critical_total": len(critical),
        "score_priority": [row["unit"] for row in score_priority],
        "healthiest": [row["unit"] for row in low_signal],
        "can_distinguish": len(distinct_scores) >= 2,
        "coverage_start": start,
        "coverage_end": cutoff,
    }


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


CRITICALITY_PERIODS = {"short": 7, "medium": 90, "long": 180, "history": None}


def _criticality_start(days, cutoff, period, evidence=()):
    if not cutoff or not days:
        return None
    window = CRITICALITY_PERIODS[period]
    if window is None:
        first = days[0]
        for row in evidence:
            day = row.get("day")
            if isinstance(day, str) and day < first:
                try:
                    first = date.fromisoformat(day).isoformat()
                except ValueError:
                    continue
        return first
    return (date.fromisoformat(cutoff) - timedelta(days=window - 1)).isoformat()


def fleet_criticality_top(bundle: EminHistoricalBundle, day, period):
    """Rank units by explicit critical days, then by their observed signal."""
    period = period if isinstance(period, str) and period in CRITICALITY_PERIODS else "short"
    days = sorted({row["day"] for row in bundle.daily})
    cutoff = day if day in days else (days[-1] if days else None)
    start = _criticality_start(days, cutoff, period, bundle.observed)
    if not start:
        return [], None, None, 0, 0

    scores = {}
    units = {row["unit"] for row in bundle.daily if start <= row["day"] <= cutoff}
    for row in bundle.daily:
        if not start <= row["day"] <= cutoff or row.get("has_observation") is not True or row.get("estimated"):
            continue
        points = _number(row.get("points"))
        if points is not None:
            scores.setdefault(row["unit"], {})[row["day"]] = points

    critical = {}
    interventions = {}
    latest = {}
    for row in bundle.observed:
        unit, event_day = row.get("unit"), str(row.get("day") or "")
        if unit not in units or not start <= event_day <= cutoff:
            continue
        kind = _explicit_milestone(row)
        if kind in {"source", "intervention"}:
            latest[unit] = max(event_day, latest.get(unit, ""))
        if kind == "source":
            critical.setdefault(unit, set()).add(event_day)
        if kind == "intervention":
            interventions.setdefault(unit, set()).add(event_day)

    entries = []
    for unit in sorted(units):
        daily = scores.get(unit, {})
        observed = len(daily)
        critical_days = len(critical.get(unit, ()))
        intervention_days = len(interventions.get(unit, ()))
        comparable = observed >= 2
        has_history = period == "history" and intervention_days > 0
        if not critical_days and not has_history and (not comparable or not any(value > 0 for value in daily.values())):
            continue
        average = sum(daily.values()) / observed if comparable else None
        recurrence = sum(value > 0 for value in daily.values()) / observed if comparable else None
        entries.append((unit, critical_days, average, recurrence, observed, latest.get(unit), intervention_days))

    def rank(entry):
        _, critical_days, average, recurrence, observed, _, intervention_days = entry
        average = average if average is not None else -1
        recurrence = recurrence if recurrence is not None else -1
        signal = (average, recurrence) if period == "short" else (recurrence, average)
        historical_priority = intervention_days if period == "history" else 0
        return (critical_days, historical_priority, *signal, observed)

    entries.sort(key=rank, reverse=True)
    score_start = max(start, days[0]) if period == "history" else start
    span = (date.fromisoformat(cutoff) - date.fromisoformat(score_start)).days + 1
    insufficient = sum(len(scores.get(unit, {})) < 2 for unit in units)
    return entries[:5], start, cutoff, span, insufficient


def _component_points(rows):
    """Attribute the published, applied event points without allocating other sources."""
    groups = Counter()
    days = set()
    for row in rows:
        total = _number(row.get("points"))
        if row.get("has_observation") is not True or row.get("estimated") or total is None:
            continue
        days.add(row["day"])
        source_points = {
            key: amount for key in ("alert_points", "oil_points")
            if (amount := _number(row.get(key))) is not None and amount > 0
        }
        if sum(source_points.values()) > total + 1e-6:
            groups["source", "unattributed"] += total
            continue
        for key, amount in source_points.items():
            groups["source", key] += amount
        residual = total - sum(source_points.values())
        contributions = row.get("event_contributions")
        event_budget = _number(row.get("event_points"))
        allocated = Counter()
        if isinstance(contributions, list):
            for item in contributions:
                if not isinstance(item, dict):
                    continue
                group, applied = item.get("group"), _number(item.get("applied"))
                if isinstance(group, str) and group.strip() and applied is not None and applied > 0:
                    allocated[group.strip()] += applied
        # Older packages may only have the event subtotal. Inconsistent
        # breakdowns stay unattributed instead of crediting a wrong component.
        if event_budget is not None and sum(allocated.values()) <= min(event_budget, residual) + 1e-6:
            for group, applied in allocated.items():
                groups["group", group] += applied
                residual -= applied
        if residual > 1e-6:
            groups["source", "unattributed"] += residual
    return groups, days


def _criticality_components_panel(trend_rows, period_start, cutoff):
    if period_start and cutoff:
        rows = [row for row in trend_rows if period_start <= row["day"] <= cutoff]
    else:
        last_observed = next((
            row for row in reversed(trend_rows)
            if row.get("has_observation") is True and not row.get("estimated")
            and _number(row.get("points")) is not None
        ), None)
        rows = [last_observed] if last_observed else []

    totals, days = _component_points(rows)
    body = []
    if not days:
        body.append(html.P(t("emin_history.drivers_no_observation"), className="text-muted mb-0"))
    else:
        last = max(days)
        context = (
            t("emin_history.drivers_period", start=_day_label(period_start), end=_day_label(cutoff), count=len(days))
            if period_start else t("emin_history.drivers_day", day=_day_label(last))
        )
        body.append(html.P(context, className="small text-muted mb-2"))
        if not totals:
            body.append(html.P(t("emin_history.drivers_zero"), className="mb-0"))
        else:
            labels = {key: key[1] if key[0] == "group" else t(f"emin_history.drivers_{key[1]}") for key in totals}
            ordered = sorted(totals, key=lambda key: (key[0] != "group", -totals[key], labels[key].casefold()))
            body.append(dbc.Table([
                html.Thead(html.Tr([
                    html.Th(t("emin_history.drivers_category"), scope="col"),
                    html.Th(t("emin_history.drivers_points"), scope="col", className="text-end"),
                ])),
                html.Tbody([
                    html.Tr([
                        html.Td(labels[key]),
                        html.Td(f"{totals[key]:.2f}", className="text-end"),
                    ])
                    for key in ordered
                ]),
            ], responsive=True, size="sm", class_name="emin-history-table mb-2"))
            body.append(html.P(t("emin_history.drivers_note"), className="small text-muted mb-0"))
    return dbc.Card([
        section_header(t("emin_history.drivers_title"), "fas fa-cogs"),
        dbc.CardBody(body),
    ], class_name="shadow-sm unit-card mb-3")


def _top_reason(entry, period):
    _, critical_days, average, recurrence, observed, _, intervention_days = entry
    if critical_days:
        return t("emin_history.top_critical_days", count=critical_days)
    if period == "history" and intervention_days:
        return t("emin_history.top_intervention_days", count=intervention_days)
    signal = t("emin_history.top_signal_count", count=round(recurrence * observed), observed=observed)
    average_label = t("emin_history.top_average", score=f"{average:.2f}")
    return f"{average_label} · {signal}" if period == "short" else f"{signal} · {average_label}"


def _observed_points(rows, start, cutoff):
    points_by_day = {}
    for row in rows:
        day = row["day"]
        if start <= day <= cutoff and row.get("has_observation") is True and not row.get("estimated"):
            points = _number(row.get("points"))
            if points is not None:
                points_by_day[day] = points
    return points_by_day


def fleet_criticality_panel(bundle, day, period):
    period = period if isinstance(period, str) and period in CRITICALITY_PERIODS else "short"
    entries, start, cutoff, span, insufficient = fleet_criticality_top(bundle, day, period)
    if not start:
        return html.P(t("emin_history.top_empty"), className="text-muted mb-0")
    headers = ("col_rank", "col_unit", "top_reason", "col_movement", "top_last_milestone", "top_coverage")
    rows = []
    for rank, entry in enumerate(entries, 1):
        unit, critical_days, _, _, observed, latest, _ = entry
        reason = _top_reason(entry, period)
        rows.append(html.Tr([
            html.Td(rank),
            html.Td(_open_unit(unit, "criticality", period)),
            html.Td(dbc.Badge(reason, color="danger") if critical_days else reason),
            html.Td(_movement_summary(_movement_for_unit(bundle.daily, unit, cutoff))),
            html.Td(_day_label(latest) if latest else "—"),
            html.Td(f"{observed}/{span}"),
        ]))
    short_bounds = (date.fromisoformat(cutoff) - timedelta(days=89)).isoformat()
    long_bounds = (date.fromisoformat(cutoff) - timedelta(days=179)).isoformat()
    coverage = _observed_points(bundle.daily, start, cutoff)
    same_scores = period in {"medium", "long"} and bool(coverage) and not _observed_points(bundle.daily, long_bounds, (date.fromisoformat(short_bounds) - timedelta(days=1)).isoformat())
    history_uses_signal = period == "history" and entries and not any(entry[1] or entry[-1] for entry in entries)
    return html.Div([
        html.P(t(f"emin_history.top_question_{period}"), className="fw-semibold mb-1"),
        html.P(t("emin_history.top_window", start=_day_label(start), end=_day_label(cutoff)), className="small text-muted mb-1"),
        html.P(t("emin_history.top_coverage_days", count=len(coverage), span=span), className="small text-muted mb-2"),
        html.P(t("emin_history.top_overlap"), className="small text-muted mb-2") if same_scores else None,
        html.P(t("emin_history.top_history_coverage"), className="small text-muted mb-2") if period == "history" else None,
        html.P(t("emin_history.top_history_signal_only"), className="small text-muted mb-2") if history_uses_signal else None,
        dbc.Table([
            html.Thead(html.Tr([html.Th(t(f"emin_history.{key}"), scope="col") for key in headers])),
            html.Tbody(rows),
        ], responsive=True, hover=True, size="sm", class_name="emin-history-table mb-2")
        if rows else html.P(t("emin_history.top_empty"), className="text-muted mb-2"),
        html.Small(t("emin_history.top_low_coverage", count=insufficient), className="text-muted"),
    ])


def _top_unit_context(bundle, cutoff, period, unit, trend_rows, evidence_rows):
    entries, start, _, span, _ = fleet_criticality_top(bundle, cutoff, period)
    match = next(((position, entry) for position, entry in enumerate(entries, 1) if entry[0] == unit), None)
    if not match:
        return None
    position, entry = match
    points = _observed_points(trend_rows, start, cutoff)
    dated_events = [row for row in evidence_rows if start <= str(row.get("day") or "") <= cutoff]
    context = [
        html.P(t("emin_history.top_unit_position", rank=position, period=t(f"emin_history.top_{period}")), className="mb-1 fw-semibold"),
        html.P(_top_reason(entry, period), className="mb-1"),
        html.P(t("emin_history.top_coverage_days", count=len(points), span=span), className="text-muted small mb-2"),
    ]
    if entry[1]:
        critical = next(row for row in dated_events if _explicit_milestone(row) == "source")
        context.append(html.P([
            t("emin_history.top_source_on", day=_day_label(critical["day"])), " ",
            html.A(t("emin_history.top_go_evidence"), href="#emin-history-milestones"),
        ], className="mb-2"))
    elif period == "history" and entry[-1]:
        context.append(html.P([
            t("emin_history.top_intervention_on", day=_day_label(entry[-2])), " ",
            html.A(t("emin_history.top_go_evidence"), href="#emin-history-milestones"),
        ], className="mb-2"))

    if period == "medium":
        component_days = {}
        for row in trend_rows:
            if row["day"] not in points or points[row["day"]] <= 0:
                continue
            for component in row.get("event_groups", []):
                if isinstance(component, str) and component.strip():
                    component_days.setdefault(component, set()).add(row["day"])
        most_frequent = sorted(component_days, key=lambda key: (-len(component_days[key]), key.casefold()))[:3]
        context.append(html.H6(t("emin_history.top_recurrent_groups"), className="mt-3"))
        context.append(html.Ul([
            html.Li(t("emin_history.top_group_days", group=group, count=len(component_days[group])))
            for group in most_frequent
        ], className="mb-0") if most_frequent else html.P(t("emin_history.top_no_groups"), className="small text-muted mb-0"))

    if period == "long":
        months = {}
        for day, points_for_day in sorted(points.items()):
            months.setdefault(day[:7], []).append(points_for_day)
        context.append(html.H6(t("emin_history.top_monthly"), className="mt-3"))
        context.append(html.Ul([
            html.Li(t("emin_history.top_month_signal", month=month, count=sum(value > 0 for value in values), observed=len(values)))
            for month, values in months.items()
        ]) if months else html.P(t("emin_history.top_empty"), className="small text-muted"))
        comparison = t("emin_history.top_no_comparison")
        for intervention in dated_events:
            if _explicit_milestone(intervention) != "intervention":
                continue
            event = date.fromisoformat(intervention["day"])
            lower, upper = (event - timedelta(days=14)).isoformat(), (event + timedelta(days=14)).isoformat()
            before = [value for day, value in points.items() if lower <= day < intervention["day"]]
            after = [value for day, value in points.items() if intervention["day"] < day <= upper]
            if len(before) >= 2 and len(after) >= 2:
                comparison = t(
                    "emin_history.top_intervention_comparison", day=_day_label(intervention["day"]),
                    before=f"{sum(before)/len(before):.2f}", after=f"{sum(after)/len(after):.2f}",
                    before_days=len(before), after_days=len(after),
                )
                break
        context.append(html.P(comparison, className="small text-muted mb-0"))
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
    ])


def fleet_highlights_panel(highlights: dict, daily_rows: list[dict], movements: dict[str, dict]):
    scores = {row["unit"]: _number(row.get("points")) for row in daily_rows}
    has_history = highlights["has_history"]
    lower_note = "distinct_scores_required"
    if highlights["can_distinguish"]:
        lower_note = "lower_signal_note" if has_history else "lower_signal_partial"
    return dbc.Card(dbc.CardBody(html.Details([
        html.Summary(t("emin_history.healthiest_title" if has_history else "emin_history.lowest_cut_title")),
        html.P(t(f"emin_history.{lower_note}"), className="text-muted small mb-1"),
        html.Ul([
            html.Li([
                html.Div([
                    _open_unit(unit, "lowest_observed_score"),
                    html.Small(
                        t("emin_history.score_on_cut", score=f"{scores[unit]:.3f}", day=_day_label(highlights["coverage_end"])),
                        className="d-block text-muted",
                    ),
                ]),
                _movement_summary(movements[unit]),
            ], className="emin-history-unit-item")
            for unit in highlights["healthiest"]
        ], className="list-unstyled mb-0"),
    ])), class_name="shadow-sm unit-card mb-3")


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


def _ranking_table(rows: list[dict], movements: dict[str, dict]):
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
            _open_unit(row["unit"], "ranking"),
            f"{score:.3f}" if (score := _number(row.get("points"))) is not None else "—",
            _movement_summary(movements[row["unit"]]),
            _observation_label(row),
            row.get("alerts", 0),
            row.get("health_events", 0),
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


def _explicit_milestone(row: dict) -> str | None:
    """Classify flags and severity supplied by the source."""
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    for key in ("critical", "is_critical", "catastrophic"):
        if details.get(key) is True or row.get(key) is True:
            return "source"
    levels = [row.get("level"), row.get("severity"), details.get("level"), details.get("severity")]
    if any(_normalized_text(str(level or "")).strip() in {"critical", "critico", "severe", "grave", "catastrophic", "catastrofico"} for level in levels):
        return "source"
    if any(details.get(key) is True or row.get(key) is True for key in ("is_major", "major_event")):
        return "intervention" if str(row.get("kind", "")).startswith("maintenance_") else "text"
    return None


def _major_event(row: dict) -> str | None:
    """Highlight explicit high severity or major-event wording from source fields."""
    explicit = _explicit_milestone(row)
    if explicit:
        return explicit
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    text = _normalized_text(" ".join(str(value) for value in details.values() if value is not None))
    text += " " + _normalized_text(str(row.get("summary") or row.get("description") or ""))
    if re.search(r"\b(pendiente|programad[oa]|planificad[oa]|sin evidencia|no se (?:registro|detecto|realizo)|scheduled|pending)\b", text):
        return None
    if any(re.search(pattern, text) for pattern in _MAJOR_TEXT_PATTERNS):
        return "text"
    return None


def _timeline_panel(unit: str | None, rows: list[dict], period_start=None, cutoff=None):
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
    labels = {"source": "major_source", "intervention": "major_intervention", "text": "major_text"}
    colors = {"source": "danger", "intervention": "primary", "text": "warning"}

    def badge(level):
        return dbc.Badge(t(f"emin_history.{labels[level]}"), color=colors[level], text_color="dark" if level == "text" else "white")

    table_rows = []
    highlights = []
    for row in rows:
        major = _major_event(row)
        source_detail = _source_detail(row.get("details") or row.get("summary") or row.get("description") or {})
        if major:
            highlights.append((major, str(row.get("event_at") or row.get("day") or ""), row, source_detail))
        marker = badge(major) if major else html.Span("—", className="text-muted")
        table_rows.append(html.Tr(
            [
                html.Td(_format_timestamp(row.get("event_at") or row.get("day"))),
                html.Td(_kind_label(str(row.get("kind", "")))),
                html.Td(source_detail),
                html.Td(marker),
            ],
            className="emin-history-major-row" if major else None,
        ))
    table = html.Div(
        dbc.Table([table_head, html.Tbody(table_rows)], hover=True, striped=True, responsive=True, size="sm", class_name="emin-history-evidence-table align-middle mb-0"),
        className="emin-history-evidence-scroll",
    )
    note = html.Small(t("emin_history.timeline_note", count=len(rows)), className="text-muted d-block mt-2")
    highlights.sort(key=lambda item: item[1], reverse=True)
    priority = {"source": 0, "intervention": 1, "text": 2}
    highlights.sort(key=lambda item: (
        bool(period_start and str(item[2].get("day") or "") < period_start),
        priority[item[0]],
    ))

    def event_row(item):
        level, _, row, detail = item
        fields = row.get("details")
        evidence = (
            html.Dl([
                element
                for key, value in fields.items() if value not in (None, "")
                for element in (html.Dt(str(key)), html.Dd(str(value)))
            ], className="mb-0")
            if isinstance(fields, dict) and fields
            else html.P(str(row.get("summary") or row.get("description") or detail), className="mb-0")
        )
        return html.Li([
            html.Div([
                badge(level),
                html.Span(_format_timestamp(row.get("event_at") or row.get("day")), className="text-muted small"),
            ], className="d-flex flex-wrap gap-2 mb-2"),
            html.Div(detail, className="emin-history-highlight-detail"),
            html.Details([
                html.Summary(t("emin_history.open_record")),
                evidence,
            ], className="emin-history-record mt-2"),
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
        dbc.Card([
            section_header(t("emin_history.full_chronology"), "fas fa-history"),
            dbc.CardBody([heading, table, note]),
        ], class_name="shadow-sm unit-card mb-3"),
    ])
