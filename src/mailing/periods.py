"""
Report period, subject and schedule arithmetic. Pure functions, no I/O.

All dates are calendar dates in ``MAILING_TIMEZONE``. Period maths is done on dates, not on
24-hour offsets, so a Chile daylight-saving change inside the range cannot shift a day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from . import config
from .errors import MailingValidationError

DAILY = "daily"
WEEKLY = "weekly"

WEEKDAY_ES = {
    "monday": "lunes", "tuesday": "martes", "wednesday": "miércoles",
    "thursday": "jueves", "friday": "viernes", "saturday": "sábado", "sunday": "domingo",
}


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def chile_tz() -> ZoneInfo:
    return ZoneInfo(config.MAILING_TIMEZONE)


def now_local() -> datetime:
    return datetime.now(chile_tz())


def today_local() -> date:
    return now_local().date()


def format_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def build_subject(send_date: date) -> str:
    """`[CODDI] Monitoreo de Alertas DD/MM/YYYY`, dated with the SEND date."""
    return f"[CODDI] Monitoreo de Alertas {format_date(send_date)}"


def compute_period(frequency: str, send_date: date) -> Period:
    """Daily: the previous day. Weekly: the last COMPLETE Monday-to-Sunday week before the send date.

    The data reaches the server about 60 hours late, so a weekly summary covers the whole previous
    calendar week (Monday to Sunday), never a sliding window ending yesterday. Sent on a Wednesday
    it covers the Monday and Sunday of the week before; sent on a Monday it covers the week that
    ended yesterday; sent on a Sunday it covers the week that ended the Sunday before.
    """
    if frequency == DAILY:
        end = send_date - timedelta(days=1)
        return Period(start=end, end=end)
    if frequency == WEEKLY:
        end = send_date - timedelta(days=send_date.weekday() + 1)  # the Sunday before this week
        return Period(start=end - timedelta(days=6), end=end)
    raise ValueError(f"Unknown frequency: {frequency!r}")


def describe_period(period: Period, frequency: Optional[str] = None) -> str:
    """`09/11/2026 – 15/11/2026 (semana anterior, lunes a domingo)` / `09/11/2026 (último día)`."""
    if frequency == WEEKLY and period.days == 7 and period.start.weekday() == 0:
        return f"{format_date(period.start)} – {format_date(period.end)} (semana anterior, lunes a domingo)"
    if period.days == 1:
        return f"{format_date(period.start)} (último día)"
    return f"{format_date(period.start)} – {format_date(period.end)} (últimos {period.days} días)"


# ----------------------------------------------------------------------------- custom period / subject
# The admin screen may change the period and the subject of ONE manual send (preview or send).
# The server validates both: the UI is never the source of truth.

MAX_CUSTOM_PERIOD_DAYS = 366
MAX_SUBJECT_CHARS = 200


def _as_date(value, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        raise MailingValidationError(f"La fecha de {label} no es válida.")


def resolve_custom_period(start, end, today: date) -> Optional[Period]:
    """`None` when no custom period was requested; otherwise the validated `Period`.

    Both dates or none; start not after end; end not after `today` (the send date); at most
    `MAX_CUSTOM_PERIOD_DAYS` days.
    """
    missing_start, missing_end = start in (None, ""), end in (None, "")
    if missing_start and missing_end:
        return None
    if missing_start or missing_end:
        raise MailingValidationError("Indique la fecha de inicio y la de término del período.")
    first, last = _as_date(start, "inicio"), _as_date(end, "término")
    if first > last:
        raise MailingValidationError("La fecha de inicio no puede ser posterior a la de término.")
    if last > today:
        raise MailingValidationError("El período no puede terminar después de hoy.")
    period = Period(first, last)
    if period.days > MAX_CUSTOM_PERIOD_DAYS:
        raise MailingValidationError(f"El período no puede superar {MAX_CUSTOM_PERIOD_DAYS} días.")
    return period


def clean_subject(subject) -> Optional[str]:
    """`None` (use the automatic subject) for an empty value; otherwise the validated subject."""
    if subject is None:
        return None
    text = str(subject).strip()
    if not text:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise MailingValidationError("El asunto no puede contener saltos de línea ni caracteres de control.")
    if len(text) > MAX_SUBJECT_CHARS:
        raise MailingValidationError(f"El asunto no puede superar {MAX_SUBJECT_CHARS} caracteres.")
    return text


def parse_time(value: str) -> time:
    hours, minutes = value.strip().split(":")
    return time(int(hours), int(minutes))


def describe_schedule(schedule: dict) -> str:
    """`se envía automáticamente los miércoles a las 12:00 (hora de Chile)`."""
    when = parse_time(schedule["time"]).strftime("%H:%M")
    if schedule["frequency"] == WEEKLY:
        day = WEEKDAY_ES[schedule["weekday"].lower()]
        return f"se envía automáticamente los {day} a las {when} (hora de Chile)"
    return f"se envía automáticamente todos los días a las {when} (hora de Chile)"


def report_title(frequency: str) -> str:
    return "Resumen Semanal de Alertas" if frequency == WEEKLY else "Resumen Diario de Alertas"


def is_due_day(schedule: dict, day: date) -> bool:
    """Does the schedule fire on this calendar day?"""
    if schedule["frequency"] == DAILY:
        return True
    if schedule["frequency"] == WEEKLY:
        return config.WEEKDAYS[day.weekday()] == schedule["weekday"].lower()
    raise ValueError(f"Unknown frequency: {schedule['frequency']!r}")


def scheduled_moment(schedule: dict, day: date) -> datetime:
    """The wall-clock instant (12:00 Chile) the schedule fires on `day`.

    Built from the local date and time in the zone, never from a fixed UTC hour, so the
    send stays at 12:00 Chile on both sides of a daylight-saving change.
    """
    return datetime.combine(day, parse_time(schedule["time"]), tzinfo=chile_tz())


def due_scheduled_date(
    schedule: dict, now: datetime, grace_minutes: Optional[int] = None
) -> Optional[date]:
    """The scheduled date to run right now, or None.

    A run is due from the scheduled moment until `grace_minutes` later (absorbs scheduler
    jitter and a quick restart; a longer outage is a missed run, not a catch-up).
    """
    if grace_minutes is None:
        grace_minutes = config.get_scheduler_grace_minutes()
    local_now = now.astimezone(chile_tz())
    day = local_now.date()
    if not is_due_day(schedule, day):
        return None
    start = scheduled_moment(schedule, day)
    if start <= local_now < start + timedelta(minutes=grace_minutes):
        return day
    return None
