"""
Mailing service: the operations the dashboard and the scheduler call.

Public operations (admin-only, enforced here on the server, not by hiding the menu):
    get_mailing_context(client, user_data)
    build_preview(client, user_data)
    send_manual(client, selected_emails, user_data)

Internal entry point of the scheduler (no user involved):
    run_scheduled(client)

The scheduled run and the manual send share the same report builder and the same delivery
function. A manual send never touches the scheduled-run markers, so it neither skips nor
reschedules the automatic send.

`user_data` is the signed `user-info-store` payload the Dash callbacks already hold. The
identity is re-resolved from the Flask session / signed proof and the role is read from the
server-side user registry; the `role` the browser claims is ignored.
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Sequence

from src.utils.logger import get_logger

from . import config, data_sync, delivery, periods, recipients, report, state
from .errors import (
    MailingBusyError,
    MailingError,
    MailingPermissionError,
    MailingValidationError,
)

logger = get_logger(__name__)

NOT_CONFIGURED_MESSAGE = "Este cliente no tiene envío de resúmenes configurado."
GENERIC_BUILD_ERROR = "No se pudo generar el resumen."

TRIGGER_SCHEDULED = "scheduled"
TRIGGER_MANUAL = "manual"
TRIGGER_ERRATUM = "erratum"

# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def require_admin(user_data: Optional[dict]) -> str:
    """Return the verified admin username or raise MailingPermissionError.

    Never trusts the `role` inside `user_data`: the username is resolved from the Flask
    session (or the signed identity proof) and the role comes from `config.users.USERS`.
    """
    from config.users import is_admin
    from dashboard.auth import resolve_authenticated_username

    username = resolve_authenticated_username(user_data)
    if not username or not is_admin(username):
        logger.warning("mailing: denied non-admin call (user=%s)", username or "anonymous")
        raise MailingPermissionError()
    return username


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def _schedule_or_raise(client: str) -> dict:
    schedule = config.get_schedule(client)
    if schedule is None:
        raise MailingError(NOT_CONFIGURED_MESSAGE, code="not_configured")
    return schedule


def _build_report(
    client: str,
    schedule: dict,
    send_date: date,
    subject: Optional[str] = None,
    period: Optional[periods.Period] = None,
    erratum: bool = False,
) -> report.ReportContent:
    """Build the email through the registered report builder (shared by every trigger).

    `subject` and `period` are the validated custom values of a manual send; scheduled sends
    never pass them. `erratum` is only passed by the one-time correction send.
    """
    period = period or periods.compute_period(schedule["frequency"], send_date)
    request = report.ReportRequest(
        client=client,
        frequency=schedule["frequency"],
        period_start=period.start,
        period_end=period.end,
        send_date=send_date,
        subject=subject,
        erratum=erratum,
    )
    builder = report.get_report_builder()
    try:
        content = builder(request)
    except MailingError:
        raise
    except Exception:  # noqa: BLE001 - the UI must not see internals
        logger.exception("mailing: report builder failed (client=%s)", client)
        raise MailingError(GENERIC_BUILD_ERROR, code="build_failed")
    expected = subject or periods.build_subject(send_date, erratum=erratum)
    if content.subject != expected:
        # The subject is a contract (and what get_mailing_context shows): the service owns it.
        logger.warning("mailing: builder subject differs from contract; using contract subject")
        content = report.ReportContent(subject=expected, html=content.html, meta=content.meta)
    return content


# ---------------------------------------------------------------------------
# Operations for the admin screen
# ---------------------------------------------------------------------------


def get_mailing_context(client: str, user_data: Optional[dict], now: Optional[datetime] = None) -> dict:
    """Everything the admin screen shows for the client. Admin-only."""
    require_admin(user_data)
    key = config.normalize_client(client)
    production = config.is_production()
    base = {
        "client": key,
        "client_label": config.client_display_name(key),
        "environment": config.environment_name(),
        "is_production": production,
    }
    schedule = config.get_schedule(key)
    if schedule is None:
        return {**base, "configured": False, "message": NOT_CONFIGURED_MESSAGE, "recipients": []}

    send_date = (now or periods.now_local()).astimezone(periods.chile_tz()).date()
    period = periods.compute_period(schedule["frequency"], send_date)
    return {
        **base,
        "configured": True,
        "report_type": schedule["frequency"],
        "report_title": periods.report_title(schedule["frequency"]),
        "schedule_description": periods.describe_schedule(schedule),
        "subject": periods.build_subject(send_date),
        "send_date": send_date.isoformat(),
        "period": {
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "text": periods.describe_period(period, schedule["frequency"]),
        },
        # What the screen lets the admin change for one send, and its limits (validated again on send).
        "limits": {
            "max_date": send_date.isoformat(),
            "max_days": periods.MAX_CUSTOM_PERIOD_DAYS,
            "max_subject": periods.MAX_SUBJECT_CHARS,
        },
        "recipients": [r.to_dict() for r in recipients.list_recipients(key, production)],
    }


def build_preview(
    client: str,
    user_data: Optional[dict],
    now: Optional[datetime] = None,
    *,
    subject: Optional[str] = None,
    period_start=None,
    period_end=None,
) -> dict:
    """`{"subject", "html"}` exactly as a real send would produce them. Sends nothing.

    `subject` / `period_start` / `period_end` are the optional custom values of the screen.
    """
    require_admin(user_data)
    key = config.normalize_client(client)
    schedule = _schedule_or_raise(key)
    send_date = (now or periods.now_local()).astimezone(periods.chile_tz()).date()
    custom_subject = periods.clean_subject(subject)
    custom_period = periods.resolve_custom_period(period_start, period_end, send_date)
    content = _build_report(key, schedule, send_date, custom_subject, custom_period)
    return {"subject": content.subject, "html": content.html}


# --- manual send -----------------------------------------------------------

_manual_locks: Dict[str, threading.Lock] = {}
_manual_last_success: Dict[str, float] = {}
_manual_guard = threading.Lock()


def _manual_lock(client: str) -> threading.Lock:
    with _manual_guard:
        return _manual_locks.setdefault(client, threading.Lock())


def _result(status: str, subject: str, emails: Sequence[str], reason: Optional[str]) -> dict:
    ok = status == "sent"
    count = len(emails)
    if ok:
        message = f"Resumen enviado a {count} destinatario{'s' if count != 1 else ''}."
    else:
        message = "No se pudo enviar el resumen. Intente nuevamente."
    return {
        "ok": ok,
        "status": status,
        "subject": subject,
        "sent": count if ok else 0,
        "total": count,
        "message": message,
        "recipients": [
            {"email": e, "status": "sent" if ok else "failed", "error": None if ok else reason}
            for e in emails
        ],
    }


def send_manual(
    client: str,
    selected_emails: Sequence[str],
    user_data: Optional[dict],
    now: Optional[datetime] = None,
    *,
    subject: Optional[str] = None,
    period_start=None,
    period_end=None,
) -> dict:
    """Send the summary now to the validated selection. Admin-only, no automatic retry.

    `subject` / `period_start` / `period_end` are the optional custom values of the screen; they
    are validated here (empty = the automatic value) and only change this one send.

    The UI is never the source of truth: any email outside the registry of this client
    rejects the whole send, and Coddi Técnico is added when missing.
    Raises MailingError subclasses for expected refusals (permission, not configured,
    invalid recipients, busy); a delivery failure is returned in the result.
    """
    requested_by = require_admin(user_data)
    key = config.normalize_client(client)
    schedule = _schedule_or_raise(key)

    final, rejected = recipients.resolve_manual_selection(key, selected_emails)
    if rejected:
        logger.warning(
            "mailing: manual send rejected (client=%s requested_by=%s rejected=%s)",
            key, requested_by, rejected,
        )
        raise MailingValidationError(
            "La selección incluye destinatarios no permitidos para este cliente.",
            rejected=rejected,
        )

    send_date = (now or periods.now_local()).astimezone(periods.chile_tz()).date()
    custom_subject = periods.clean_subject(subject)
    custom_period = periods.resolve_custom_period(period_start, period_end, send_date)

    lock = _manual_lock(key)
    if not lock.acquire(blocking=False):
        raise MailingBusyError()
    try:
        cooldown = config.get_manual_cooldown_seconds()
        last = _manual_last_success.get(key)
        if last is not None and time.monotonic() - last < cooldown:
            raise MailingBusyError()

        content = _build_report(key, schedule, send_date, custom_subject, custom_period)
        outcome = delivery.send_email(content.subject, content.html, final)
        custom = None
        if custom_subject or custom_period:
            custom = "custom" + (f" period={custom_period.start}..{custom_period.end}" if custom_period else "")
        _log_attempt(key, TRIGGER_MANUAL, requested_by, content.subject, final, outcome, attempt=1, custom=custom)
        if outcome.ok:
            _manual_last_success[key] = time.monotonic()
            return _result("sent", content.subject, final, None)
        return _result("failed", content.subject, final, outcome.reason)
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Scheduled run
# ---------------------------------------------------------------------------


def partition_dependency_problem(client: str, scheduled_date: date) -> Optional[str]:
    """Why the scheduled e-mail cannot be built from the partitions yet, or None (see
    `config.MAILING_PARTITION_DEPENDENCY`). The run status is the one the partitioner records."""
    job = config.MAILING_PARTITION_DEPENDENCY.get(config.normalize_client(client))
    if job is None:
        return None
    from src.data import partition_scheduler  # imported here: the data layer imports this package's config

    return partition_scheduler.partition_run_problem(job, scheduled_date)


def alerts_generated_problem(client: str, scheduled_date: date) -> Optional[str]:
    """Why the scheduled e-mail must not go for lack of alerts, or None (see `config.MAILING_REQUIRE_ALERTS`).

    Counts the client's alerts of the e-mail's period with the very pipeline the e-mail uses
    (`alert_summary.load_period_records`: the partitions, Chile days), so what is checked is what would be sent.
    Unreadable data counts as a problem too: the e-mail is not built on data that cannot be read.
    """
    key = config.normalize_client(client)
    if key not in config.MAILING_REQUIRE_ALERTS:
        return None
    schedule = config.get_schedule(key)
    period = periods.compute_period(schedule["frequency"], scheduled_date)
    try:
        from . import alert_summary

        found = len(alert_summary.load_period_records(key, period.start, period.end))
    except Exception as exc:  # noqa: BLE001 - fail closed, say why
        logger.exception("mailing: could not count the alerts of the period (client=%s)", key)
        return f"the alerts of {period.start}..{period.end} could not be read ({type(exc).__name__})"
    if found == 0:
        return (
            f"no alert of {key} in the partitions for {period.start}..{period.end}: the alert creation "
            "did not run or did not reach the partitions"
        )
    return None


def run_scheduled(
    client: str,
    scheduled_date: Optional[date] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Run one scheduled send. Returns `sent`, `failed` or `skipped`.

    `skipped` means another process/thread (or an earlier run) already owns the marker for
    `(client, scheduled_date)`: this is what makes the send exactly-once across workers and
    restarts. The partitioner run it depends on must have finished OK, and (capstone) the period must have
    alerts, or nothing is sent. The data is synced from S3 once before the first build (data_sync.py). Failures are retried with growing
    waits (`MAILING_RETRY_DELAYS`), then logged.
    """
    key = config.normalize_client(client)
    schedule = config.get_schedule(key)
    if schedule is None:
        logger.error("mailing: scheduled run for unconfigured client %s", key)
        return "failed"
    scheduled_date = scheduled_date or periods.today_local()

    if not state.claim(key, scheduled_date):
        logger.info("mailing: scheduled run already claimed (client=%s date=%s)", key, scheduled_date)
        return "skipped"

    # The partitions this e-mail reads must come from a partitioner run that FINISHED OK. Checked before
    # anything is built; not met = not sent, an error in the log, no retry (the claim above holds).
    problem = partition_dependency_problem(key, scheduled_date)
    if problem:
        logger.error(
            "mailing: scheduled send NOT SENT, partitioner dependency not met (client=%s date=%s): %s",
            key, scheduled_date, problem,
        )
        state.finish(key, scheduled_date, "failed", f"partitioner dependency: {problem}")
        return "failed"

    # Fresh data first (the app's own S3 sync, once per date); a failure only logs and the email goes out.
    data_sync.sync_before_send(scheduled_date)

    # Alerts must exist for the period (capstone): checked on the freshly synced partitions, before building.
    problem = alerts_generated_problem(key, scheduled_date)
    if problem:
        logger.error(
            "mailing: scheduled send NOT SENT, no alerts generated (client=%s date=%s): %s", key, scheduled_date, problem
        )
        state.finish(key, scheduled_date, "failed", f"no alerts: {problem}")
        return "failed"

    emails = recipients.scheduled_emails(key)
    delays = list(config.get_retry_delays())
    attempts = len(delays) + 1
    last_reason = GENERIC_BUILD_ERROR
    subject = periods.build_subject(scheduled_date)

    for attempt in range(1, attempts + 1):
        try:
            content = _build_report(key, schedule, scheduled_date)
            subject = content.subject
            outcome = delivery.send_email(content.subject, content.html, emails)
        except MailingError as exc:
            outcome = delivery.DeliveryResult(False, exc.user_message)
        except Exception:  # noqa: BLE001 - a scheduler thread must survive anything
            logger.exception("mailing: unexpected error in scheduled send (client=%s)", key)
            outcome = delivery.DeliveryResult(False, GENERIC_BUILD_ERROR)
        _log_attempt(key, TRIGGER_SCHEDULED, None, subject, emails, outcome, attempt=attempt)
        if outcome.ok:
            state.finish(key, scheduled_date, "sent")
            return "sent"
        last_reason = outcome.reason or last_reason
        if attempt < attempts:
            sleep(delays[attempt - 1])

    logger.error(
        "mailing: scheduled send FAILED after %d attempts (client=%s date=%s subject=%s)",
        attempts, key, scheduled_date, subject,
    )
    state.finish(key, scheduled_date, "failed", last_reason)
    return "failed"


# ---------------------------------------------------------------------------
# One-time erratum send
# ---------------------------------------------------------------------------


def build_erratum_preview(client: str, send_date: date) -> dict:
    """`{"subject", "html", "recipients", "meta"}` of the erratum send. Sends nothing.

    The regular summary of `send_date` (same period, content and recipients as the scheduled
    e-mail) with the FE DE ERRATA notice and subject prefix. Internal entry point, like
    `run_scheduled`: no user involved.
    """
    key = config.normalize_client(client)
    schedule = _schedule_or_raise(key)
    content = _build_report(key, schedule, send_date, erratum=True)
    return {
        "subject": content.subject,
        "html": content.html,
        "recipients": recipients.scheduled_emails(key),
        "meta": content.meta,
    }


def send_erratum(client: str, send_date: date) -> str:
    """Send the corrected summary with the FE DE ERRATA notice, once. Returns `sent`, `failed` or `skipped`.

    Same builder, same recipients (`recipients.scheduled_emails`) and same delivery function as the
    regular scheduled e-mail; only the notice and the subject prefix are added. It has its own
    at-most-once marker (`erratum_<client>_<date>.json`), so it never touches the scheduled-run
    markers and a second call cannot send it again. No retry: a delivery that timed out may still
    have gone out, so after a `failed` result the operator checks and removes the marker by hand.
    """
    key = config.normalize_client(client)
    schedule = _schedule_or_raise(key)
    if not state.claim(key, send_date, kind=state.KIND_ERRATUM):
        logger.warning("mailing: erratum send already claimed (client=%s date=%s)", key, send_date)
        return "skipped"

    emails = recipients.scheduled_emails(key)
    subject = periods.build_subject(send_date, erratum=True)
    try:
        content = _build_report(key, schedule, send_date, erratum=True)
        subject = content.subject
        outcome = delivery.send_email(content.subject, content.html, emails)
    except MailingError as exc:
        outcome = delivery.DeliveryResult(False, exc.user_message)
    except Exception:  # noqa: BLE001
        logger.exception("mailing: unexpected error in the erratum send (client=%s)", key)
        outcome = delivery.DeliveryResult(False, GENERIC_BUILD_ERROR)
    _log_attempt(key, TRIGGER_ERRATUM, None, subject, emails, outcome, attempt=1)
    if outcome.ok:
        state.finish(key, send_date, "sent", kind=state.KIND_ERRATUM)
        return "sent"
    logger.error("mailing: erratum send FAILED (client=%s date=%s subject=%s)", key, send_date, subject)
    state.finish(key, send_date, "failed", outcome.reason, kind=state.KIND_ERRATUM)
    return "failed"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _log_attempt(
    client: str,
    trigger: str,
    requested_by: Optional[str],
    subject: str,
    emails: Sequence[str],
    outcome: delivery.DeliveryResult,
    attempt: int,
    custom: Optional[str] = None,
) -> None:
    """One line per attempt. Never the HTML body, never the Lambda URL."""
    result = "sent" if outcome.ok else "failed"
    per_recipient: List[str] = [f"{email}={result}" for email in emails]
    logger.info(
        "mailing send | client=%s trigger=%s requested_by=%s environment=%s host=%s attempt=%d "
        "subject=%r recipients=%s results=[%s]%s%s",
        client, trigger, requested_by or "-", config.environment_name(), config.get_hostname(),
        attempt, subject, list(emails),
        ", ".join(per_recipient),
        "" if outcome.ok else f" reason={outcome.reason!r}",
        f" {custom}" if custom else "",
    )
