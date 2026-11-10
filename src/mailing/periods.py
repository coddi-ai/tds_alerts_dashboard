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
    """Daily: the previous day. Weekly: the 7 days ending the day before the send date."""
    end = send_date - timedelta(days=1)
    if frequency == DAILY:
        return Period(start=end, end=end)
    if frequency == WEEKLY:
        return Period(start=end - timedelta(days=6), end=end)
    raise ValueError(f"Unknown frequency: {frequency!r}")


def describe_period(period: Period) -> str:
    """`04/11/2026 – 10/11/2026 (últimos 7 días)` / `09/11/2026 (último día)`."""
    if period.days == 1:
        return f"{format_date(period.start)} (último día)"
    return f"{format_date(period.start)} – {format_date(period.end)} (últimos {period.days} días)"


def parse_time(value: str) -> time:
    hours, minutes = value.strip().split(":")
    return time(int(hours), int(minutes))


def describe_schedule(schedule: dict) -> str:
    """`se envía automáticamente los miércoles a las 08:00 (hora de Chile)`."""
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
    """The wall-clock instant (08:00 Chile) the schedule fires on `day`.

    Built from the local date and time in the zone, never from a fixed UTC hour, so the
    send stays at 08:00 Chile on both sides of a daylight-saving change.
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
