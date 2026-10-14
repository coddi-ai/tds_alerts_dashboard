"""EMIN maintenance context; published data owns the alert type."""

import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import date

import pandas as pd
from src.i18n import t
from src.utils.date_utils import to_utc_naive


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
    if not isinstance(value, str) and (value is None or pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "null", "<na>"} else text


def _fold(value) -> str:
    return " ".join("".join(
        char for char in unicodedata.normalize("NFKD", _text(value).casefold())
        if not unicodedata.combining(char)
    ).split())


# Weekly contract aliases; "System - Subsystem" uses only the first field.
# Never identify systems by searching a narrative summary or component name.
_SYSTEM_ALIASES = {
    "engine": "motor", "transmission": "transmision", "hydraulic": "hidraulico",
    "electrical": "electrico", "brake": "frenos", "cooling": "refrigeracion",
    "enfriamiento": "refrigeracion", "fuel": "combustible",
    "tire": "neumaticos", "structural": "estructura",
}
_UNKNOWN_SYSTEMS = {"", "equipo", "otros", "other", "desconocido", "sin sistema", "n/a"}


def maintenance_system(value) -> str:
    system = re.split(r"\s+-\s+", _text(value), maxsplit=1)[0]
    system = re.sub(r"^sistema(?: de)?\s+", "", _fold(system))
    return "" if system in _UNKNOWN_SYSTEMS else _SYSTEM_ALIASES.get(system, system)


def _week_start(value):
    text = _text(value)
    if not re.fullmatch(r"(?:0[1-9]|[1-4]\d|5[0-3])-\d{4}", text):
        return None
    week, year = map(int, text.split("-"))
    try:
        return pd.Timestamp(date.fromisocalendar(year, week, 1))
    except ValueError:
        return None


def maintenance_week(value) -> str:
    return _text(value) if _week_start(value) is not None else ""


def maintenance_window(timestamp):
    """Use the loader's UTC-naive alert clock, without a second local shift."""
    try:
        instant = timestamp if isinstance(timestamp, pd.Timestamp) and timestamp.tzinfo is None else to_utc_naive(timestamp)
        if pd.isna(instant):
            return None
        monday = instant.normalize() - pd.Timedelta(days=instant.weekday())
        return monday - pd.Timedelta(weeks=4), monday
    except (TypeError, ValueError, OverflowError):
        return None


def maintenance_weeks_for_alert(timestamp) -> tuple[str, ...]:
    window = maintenance_window(timestamp)
    if window is None:
        return ()
    start, _ = window
    return tuple(
        f"{iso.week:02d}-{iso.year}"
        for iso in ((start + pd.Timedelta(weeks=offset)).isocalendar() for offset in range(4))
    )


_WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def _task_date(value, week_start):
    """Validate date against its ISO file week; preserve EMIN's written clock."""
    text = _text(value)
    match = re.fullmatch(r"(?:(\w+)\s+)?(\d{2})/(\d{2})", text)
    if match:
        weekday, day, month = match.groups()
        candidates = [
            week_start + pd.Timedelta(days=offset) for offset in range(7)
            if (week_start + pd.Timedelta(days=offset)).day == int(day)
            and (week_start + pd.Timedelta(days=offset)).month == int(month)
        ]
        if len(candidates) != 1:
            return None
        instant = candidates[0]
        if weekday and _fold(weekday) != _WEEKDAYS[instant.weekday()]:
            return None
    elif re.fullmatch(
        r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?",
        text,
    ):
        try:
            instant = pd.Timestamp(text)
            # The EMIN maintenance contract treats offset suffixes as ingestion
            # artifacts. Validate first; drop the suffix without UTC conversion.
            if instant.tzinfo is not None:
                instant = instant.tz_localize(None)
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    return instant if week_start <= instant < week_start + pd.Timedelta(weeks=1) else None


def _tasks(value) -> dict:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def maintenance_tasks_text(value) -> str:
    lines = []
    for day, systems in _tasks(value).items():
        if not isinstance(systems, dict):
            continue
        for system, activities in systems.items():
            if isinstance(activities, list):
                lines.extend(
                    f"{day} · {system}: {activity.strip()}"
                    for activity in activities if isinstance(activity, str) and _text(activity)
                )
    return "\n".join(lines)


def resolve_emin_maintenance_evidence(alert_row, weekly_data: Mapping[str, pd.DataFrame]):
    """Resolve dated system tasks in [ISO W-4 Monday, ISO W Monday)."""
    result = {"evidence": None, "status": "no_data", "start": "", "end": ""}
    window = maintenance_window(alert_row.get("Timestamp"))
    if window is None:
        result["status"] = "invalid_alert_date"
        return result
    start, end = window
    result.update(start=start.isoformat(), end=end.isoformat())
    unit = _text(alert_row.get("UnitId"))
    system = maintenance_system(alert_row.get("sistema"))
    if not unit or not system:
        result["status"] = "missing_unit" if not unit else "unknown_alert_system"
        return result
    selected, summaries, matched_weeks = {}, [], []
    has_rows, undetermined = False, False
    for week in maintenance_weeks_for_alert(alert_row.get("Timestamp")):
        frame = weekly_data.get(week, pd.DataFrame())
        if frame.empty or "UnitId" not in frame:
            continue
        for _, row in frame[frame.UnitId.map(_text).eq(unit)].iterrows():
            has_rows = True
            tasks = _tasks(row.get("Tasks_List"))
            if not tasks:
                undetermined = True
            row_matched = False
            for day, systems in tasks.items():
                instant = _task_date(day, _week_start(week))
                if instant is None or not isinstance(systems, dict):
                    undetermined = True
                    continue
                if not start <= instant < end:
                    continue
                for source_system, activities in systems.items():
                    normalized = maintenance_system(source_system)
                    if not normalized:
                        undetermined = True
                        continue
                    if normalized != system:
                        continue
                    if not isinstance(activities, list):
                        undetermined = True
                        continue
                    valid = [task.strip() for task in activities if isinstance(task, str) and _text(task)]
                    if not valid:
                        continue
                    target = selected.setdefault(instant.isoformat(), {}).setdefault(source_system, [])
                    target.extend(task for task in valid if task not in target)
                    row_matched = True
            if row_matched:
                if week not in matched_weeks:
                    matched_weeks.append(week)
                summary = _text(row.get("Summary"))
                if summary:
                    entry = f"{week} · {summary}"
                    if entry not in summaries:
                        summaries.append(entry)
    if selected:
        result["status"] = "matched"
        result["evidence"] = pd.Series({
            "UnitId": unit, "Semana": ", ".join(matched_weeks),
            # Source Summary remains weekly unit context, not a per-system diagnosis.
            "Summary": "\n\n".join(summaries) or None,
            "Tasks_List": json.dumps(selected, ensure_ascii=False),
        })
    else:
        result["status"] = "undetermined" if undetermined else ("no_match" if has_rows else "no_data")
    return result


def enrich_emin_alert_evidence(alerts: pd.DataFrame, weekly_data: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Attach context without reclassifying the published alert type."""
    frame = alerts.copy(deep=True)
    frame["Trigger_type_original"] = frame["Trigger_type"]
    resolved = {}
    fields = {
        "has_maintenance": [], "maintenance_evidence_summary": [],
        "maintenance_evidence_tasks": [], "maintenance_evidence_weeks": [],
        "maintenance_evidence_status": [], "maintenance_window_start": [],
        "maintenance_window_end": [],
    }
    for _, row in frame.iterrows():
        key = (_text(row.get("UnitId")), maintenance_system(row.get("sistema")),
               maintenance_weeks_for_alert(row.get("Timestamp")))
        if key not in resolved:
            resolved[key] = resolve_emin_maintenance_evidence(row, weekly_data)
        result = resolved[key]
        evidence = result["evidence"]
        fields["has_maintenance"].append(evidence is not None)
        fields["maintenance_evidence_summary"].append(_text(evidence.get("Summary")) if evidence is not None else "")
        fields["maintenance_evidence_tasks"].append(maintenance_tasks_text(evidence.get("Tasks_List")) if evidence is not None else "")
        fields["maintenance_evidence_weeks"].append(evidence["Semana"] if evidence is not None else "")
        fields["maintenance_evidence_status"].append(result["status"])
        fields["maintenance_window_start"].append(result["start"])
        fields["maintenance_window_end"].append(result["end"])
    for column, values in fields.items():
        frame[column] = pd.Series(values, index=frame.index, dtype=bool if column == "has_maintenance" else object)
    return frame
