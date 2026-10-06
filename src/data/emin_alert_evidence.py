"""Dashboard-only EMIN classification using already-linked weekly evidence."""

import json
import re
from collections.abc import Mapping

import pandas as pd
from src.i18n import t


def evidence_flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "si", "sí"}
    return bool(value) if pd.notna(value) else False


def evidence_label(row) -> str:
    labels = [label for column, label in (
        ("has_telemetry", t("alert_evidence.telemetry")),
        ("has_tribology", t("alert_evidence.tribology")),
        ("has_maintenance", t("alert_evidence.maintenance")),
    ) if evidence_flag(row.get(column))]
    return " + ".join(labels) or t("alerts_report.sin_evidencia")


def _text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "null", "<na>"} else text


def maintenance_week(value) -> str:
    """Accept only the existing weekly file convention; no new time window."""
    week = _text(value)
    return week if re.fullmatch(r"(?:0[1-9]|[1-4]\d|5[0-3])-\d{4}", week) else ""


def _has_tasks(value) -> bool:
    # Existing weekly contract: {day: {system: [activity, ...]}}.
    if not isinstance(value, dict):
        return False
    return any(
        isinstance(systems, dict) and any(
            isinstance(tasks, list) and any(
                isinstance(task, str) and bool(_text(task)) for task in tasks
            ) for tasks in systems.values()
        ) for systems in value.values()
    )


def _has_maintenance_content(row) -> bool:
    if _text(row.get("Summary")):
        return True
    tasks = row.get("Tasks_List")
    if isinstance(tasks, str):
        try:
            tasks = json.loads(tasks)
        except (TypeError, ValueError):
            return False
    return _has_tasks(tasks)


def maintenance_tasks_text(value) -> str:
    """Readable source activities for the executive alert summary."""
    try:
        tasks = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return ""
    if not isinstance(tasks, dict):
        return ""
    lines = []
    for day, systems in tasks.items():
        if not isinstance(systems, dict):
            continue
        for system, activities in systems.items():
            if not isinstance(activities, list):
                continue
            lines.extend(
                f"{day} · {system}: {activity.strip()}"
                for activity in activities if isinstance(activity, str) and _text(activity)
            )
    return "\n".join(lines)


def maintenance_evidence_row(frame: pd.DataFrame, unit_id):
    """Return a matching row with content, also used by the detail renderer."""
    unit = _text(unit_id)
    if not unit or frame.empty or "UnitId" not in frame:
        return None
    matches = frame[frame["UnitId"].map(_text).eq(unit)]
    for _, row in matches.iterrows():
        if _has_maintenance_content(row):
            return row
    return None


def enrich_emin_alert_evidence(
    alerts: pd.DataFrame, weekly_data: Mapping[str, pd.DataFrame]
) -> pd.DataFrame:
    """Promote EMIN event alerts with actual linked maintenance context.

    Keep upstream telemetry/tribology flags independent of the display type.
    Neither the IA message nor an unresolved week reference is evidence.
    """
    frame = alerts.copy(deep=True)
    frame["Trigger_type_original"] = frame["Trigger_type"]
    # Resolve each equipment/week only once, even with many alerts per unit.
    resolved = {}
    flags, summaries, activities = [], [], []
    for _, row in frame.iterrows():
        week = maintenance_week(row.get("Semana_Resumen_Mantencion"))
        unit = _text(row.get("UnitId"))
        key = (week, unit)
        if key not in resolved:
            data = weekly_data.get(week, pd.DataFrame())
            resolved[key] = maintenance_evidence_row(data, unit) if week else None
        evidence = resolved[key]
        flags.append(evidence is not None)
        summaries.append(_text(evidence.get("Summary")) if evidence is not None else "")
        activities.append(maintenance_tasks_text(evidence.get("Tasks_List")) if evidence is not None else "")
    frame["has_maintenance"] = pd.Series(flags, index=frame.index, dtype=bool)
    frame["maintenance_evidence_summary"] = summaries
    frame["maintenance_evidence_tasks"] = activities
    event_with_context = frame["has_telemetry"].map(evidence_flag) & frame["has_maintenance"]
    frame.loc[event_with_context, "Trigger_type"] = "Mixto"
    return frame
