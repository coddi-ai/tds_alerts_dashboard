"""
Mailing service: recipients, report builders, delivery through the email Lambda, and the
automatic schedule. See documentation/mailling/01_mailing_service_backend.md.

    from src.mailing import get_mailing_context, build_preview, send_manual
    from src.mailing import start_mailing_scheduler
"""

from .errors import (
    MailingBusyError,
    MailingError,
    MailingPermissionError,
    MailingValidationError,
)
from .report import ReportContent, ReportRequest, register_report_builder
from .scheduler import start_mailing_scheduler, stop_mailing_scheduler
from .service import (
    build_erratum_preview,
    build_preview,
    get_mailing_context,
    run_scheduled,
    send_erratum,
    send_manual,
)

__all__ = [
    "MailingBusyError",
    "MailingError",
    "MailingPermissionError",
    "MailingValidationError",
    "ReportContent",
    "ReportRequest",
    "build_erratum_preview",
    "build_preview",
    "get_mailing_context",
    "register_report_builder",
    "run_scheduled",
    "send_erratum",
    "send_manual",
    "start_mailing_scheduler",
    "stop_mailing_scheduler",
]
