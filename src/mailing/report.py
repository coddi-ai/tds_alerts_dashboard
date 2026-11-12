"""
Report builder contract.

A builder turns `(client, period, send_date)` into the email content. The service knows
nothing about alerts: it only calls whichever builder is registered. The alerts summary
(`02_alert_summary_email_template.md`) registers itself here; other reports can follow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, Optional

from .errors import MailingError

ALERT_SUMMARY = "alert_summary"


@dataclass(frozen=True)
class ReportRequest:
    client: str          # normalised, lower-case (`emin`)
    frequency: str       # "daily" | "weekly"
    period_start: date
    period_end: date     # inclusive
    send_date: date


@dataclass(frozen=True)
class ReportContent:
    subject: str
    html: str
    meta: Dict[str, object] = field(default_factory=dict)  # totals etc., for logging only


ReportBuilder = Callable[[ReportRequest], ReportContent]

_BUILDERS: Dict[str, ReportBuilder] = {}


def register_report_builder(report_type: str, builder: ReportBuilder) -> None:
    _BUILDERS[report_type] = builder


def unregister_report_builder(report_type: str) -> None:
    _BUILDERS.pop(report_type, None)


def get_report_builder(report_type: str = ALERT_SUMMARY) -> ReportBuilder:
    """The registered builder; the alerts summary is imported lazily on first use."""
    builder: Optional[ReportBuilder] = _BUILDERS.get(report_type)
    if builder is None and report_type == ALERT_SUMMARY:
        try:
            from .alert_summary import build_alert_summary  # ticket 02 (not built yet)
        except ImportError:
            builder = None
        else:
            builder = build_alert_summary
    if builder is None:
        raise MailingError(
            "El resumen de alertas aún no está disponible.",
            code="report_unavailable",
        )
    return builder
