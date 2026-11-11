"""Contratos del servicio de mailing (01_mailing_service_backend.md), con la Lambda simulada."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from flask import Flask, session as flask_session

from config.users import USERS
from src.mailing import (
    MailingBusyError,
    MailingError,
    MailingPermissionError,
    MailingValidationError,
    ReportContent,
    build_preview,
    config,
    delivery,
    get_mailing_context,
    periods,
    recipients,
    register_report_builder,
    report,
    run_scheduled,
    send_manual,
    state,
)
from src.mailing.scheduler import MailingScheduler

SANTIAGO = ZoneInfo("America/Santiago")
SECRET_URL = "https://abc123secret.lambda-url.us-east-2.on.aws/"
TECH = "tds@coddi.ai"
TECHS = [r["email"] for r in config.CODDI_RECIPIENTS["technical"]]  # every Coddi technical contact
GERENCIA = ["eduardo@coddi.ai", "pedro@coddi.ai"]
EMIN_SEND = [r["email"] for r in config.MAILING_RECIPIENTS["emin"] if r["send_email"]]
EMIN_ALL = [r["email"] for r in config.MAILING_RECIPIENTS["emin"]]
CAPSTONE_SEND = [r["email"] for r in config.MAILING_RECIPIENTS["capstone"] if r["send_email"]]

ADMIN = next(n for n, u in USERS.items() if u.get("role") == "admin")
CLIENT_USER = next(n for n, u in USERS.items() if u.get("role") != "admin")


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def hermetic(monkeypatch, tmp_path):
    """Sin .env real: ni la URL de la Lambda, ni el entorno, ni el estado salen de la maquina."""
    monkeypatch.setattr(config, "_DOTENV_LOADED", True)
    monkeypatch.setenv("LAMBDA_URL", SECRET_URL)
    monkeypatch.setenv("LAMBDA_ACCESS_KEY", "AKIAFAKEFAKEFAKEFAKE")
    monkeypatch.setenv("LAMBDA_SECRET_ACCESS_KEY", "fake-secret-key-for-signing-tests")
    monkeypatch.setenv("DEPLOY_STATUS", "test")
    monkeypatch.setenv("MAILING_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MAILING_RETRY_DELAYS", "1,2,3")
    monkeypatch.setenv("MAILING_MANUAL_COOLDOWN_SECONDS", "0")
    monkeypatch.delenv("MAILING_SCHEDULER_ENABLED", raising=False)
    service_module = __import__("src.mailing.service", fromlist=["x"])
    service_module._manual_locks.clear()
    service_module._manual_last_success.clear()


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setenv("DEPLOY_STATUS", "POC")


@pytest.fixture
def builder():
    """Un constructor de reporte falso: el real es el ticket 02."""
    calls = []

    def fake(request):
        calls.append(request)
        return ReportContent(
            subject=periods.build_subject(request.send_date),
            html="<html><body>CUERPO-SECRETO-DEL-CORREO</body></html>",
            meta={"total": 3},
        )

    register_report_builder(report.ALERT_SUMMARY, fake)
    fake.calls = calls
    yield fake
    report.unregister_report_builder(report.ALERT_SUMMARY)


@pytest.fixture
def sent(monkeypatch):
    """Reemplaza el envio real; devuelve la lista de envios y permite fijar resultados."""
    box = {"calls": [], "results": []}

    def fake_send(subject, html, emails):
        box["calls"].append({"subject": subject, "html": html, "emails": list(emails)})
        if box["results"]:
            return box["results"].pop(0)
        return delivery.DeliveryResult(True)

    monkeypatch.setattr(delivery, "send_email", fake_send)
    return box


@pytest.fixture
def flask_app():
    app = Flask(__name__)
    app.secret_key = "test-secret-key-with-enough-entropy"
    app.pushed_contexts = []
    yield app
    while app.pushed_contexts:
        app.pushed_contexts.pop().pop()


def as_user(app, username):
    """Contexto de peticion con la sesion de Flask de `username`; devuelve `user_data`."""
    ctx = app.test_request_context()
    ctx.push()
    app.pushed_contexts.append(ctx)
    flask_session["dashboard_user"] = username
    return {"username": username, "role": USERS[username]["role"], "clients": []}


def at(day: date, hour=8, minute=0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=SANTIAGO)


# --------------------------------------------------------------------------- recipients


def test_non_production_allows_the_whole_registry_of_the_client(sent):
    assert not config.is_production()
    assert recipients.allowed_emails("emin") == EMIN_ALL + TECHS + GERENCIA
    for r in recipients.list_recipients("emin"):
        assert r.locked == (r.group == config.GROUP_TECHNICAL)
        assert r.disabled == r.locked  # nothing is disabled because of the environment


def test_non_production_only_technical_is_selected_by_default():
    selected = [r.email for r in recipients.list_recipients("emin") if r.selected_by_default]
    assert selected == TECHS


def test_production_defaults_are_client_send_email_technical_and_management(production):
    selected = [r.email for r in recipients.list_recipients("emin") if r.selected_by_default]
    assert selected == EMIN_SEND + TECHS + GERENCIA
    assert [r.email for r in recipients.list_recipients("emin") if r.locked] == TECHS


def test_scheduled_recipients_are_identical_in_production_and_non_production(monkeypatch):
    monkeypatch.setenv("DEPLOY_STATUS", "test")
    outside = {c: recipients.scheduled_emails(c) for c in ("emin", "capstone")}
    monkeypatch.setenv("DEPLOY_STATUS", "POC")
    inside = {c: recipients.scheduled_emails(c) for c in ("emin", "capstone")}
    assert outside == inside
    assert inside["emin"] == EMIN_SEND + TECHS + GERENCIA
    assert inside["capstone"] == CAPSTONE_SEND + TECHS + GERENCIA


def test_production_scheduled_goes_to_client_flagged_technical_and_management(production):
    assert recipients.scheduled_emails("emin") == EMIN_SEND + TECHS + GERENCIA


def test_production_scheduled_skips_client_contacts_without_send_email(production, monkeypatch):
    registry = {"emin": [
        {"name": "A", "email": "a@x.cl", "send_email": True},
        {"name": "B", "email": "b@x.cl", "send_email": False},
    ]}
    monkeypatch.setattr(config, "MAILING_RECIPIENTS", registry)
    assert recipients.scheduled_emails("emin") == ["a@x.cl", *TECHS] + GERENCIA
    # B sigue siendo seleccionable a mano, pero no viene marcado.
    by_email = {r.email: r for r in recipients.list_recipients("emin")}
    assert not by_email["b@x.cl"].selected_by_default and not by_email["b@x.cl"].disabled
    assert by_email["a@x.cl"].selected_by_default


def test_technical_is_locked_and_preselected_everywhere(production):
    tech = next(r for r in recipients.list_recipients("capstone") if r.email == TECH)
    assert tech.locked and tech.selected_by_default
    assert recipients.technical_emails("capstone") == TECHS


def test_unknown_client_still_has_technical_and_management(production):
    emails = recipients.allowed_emails("zzz")
    assert TECH in emails and not any("capstone" in e for e in emails)


def test_production_flag_defaults_to_non_production(monkeypatch):
    monkeypatch.delenv("DEPLOY_STATUS", raising=False)
    assert not config.is_production()
    monkeypatch.setenv("DEPLOY_STATUS", "POC")
    assert config.is_production()
    monkeypatch.setenv("DEPLOY_STATUS", "test")
    assert not config.is_production()


# --------------------------------------------------------------------------- periods / subject


def test_subject_uses_send_date():
    assert periods.build_subject(date(2026, 11, 11)) == "[CODDI] Monitoreo de Alertas 11/11/2026"


def test_capstone_weekly_example_from_the_spec():
    period = periods.compute_period("weekly", date(2026, 11, 11))
    assert (period.start, period.end) == (date(2026, 11, 4), date(2026, 11, 10))
    assert period.days == 7
    assert periods.describe_period(period) == "04/11/2026 – 10/11/2026 (últimos 7 días)"


def test_daily_period_is_previous_day():
    period = periods.compute_period("daily", date(2026, 11, 10))
    assert (period.start, period.end) == (date(2026, 11, 9), date(2026, 11, 9))
    assert periods.describe_period(period) == "09/11/2026 (último día)"


def test_period_crossing_chile_daylight_saving_change_keeps_seven_calendar_days():
    # Chile pasa a horario de verano la noche del sab 5 -> dom 6 de septiembre de 2026.
    send = date(2026, 9, 9)
    period = periods.compute_period("weekly", send)
    assert (period.start, period.end) == (date(2026, 9, 2), date(2026, 9, 8))
    assert period.days == 7
    # y al revés: fin del horario de verano, sab 4 -> dom 5 de abril de 2026.
    period = periods.compute_period("weekly", date(2026, 4, 8))
    assert (period.start, period.end) == (date(2026, 4, 1), date(2026, 4, 7))


def test_unknown_frequency_is_rejected():
    with pytest.raises(ValueError):
        periods.compute_period("monthly", date(2026, 1, 1))


# --------------------------------------------------------------------------- schedule evaluation


def test_emin_is_due_every_day_at_0800_chile():
    schedule = config.MAILING_SCHEDULES["emin"]
    for offset in range(7):
        day = date(2026, 11, 9) + timedelta(days=offset)
        assert periods.due_scheduled_date(schedule, at(day)) == day


def test_capstone_is_due_only_on_wednesday():
    schedule = config.MAILING_SCHEDULES["capstone"]
    wednesday = date(2026, 11, 11)
    assert wednesday.weekday() == 2
    assert periods.due_scheduled_date(schedule, at(wednesday)) == wednesday
    for offset in (1, 2, 3, 4, 5, 6):
        assert periods.due_scheduled_date(schedule, at(wednesday + timedelta(days=offset))) is None


def test_not_due_before_0800_nor_after_the_grace_window():
    schedule = config.MAILING_SCHEDULES["emin"]
    day = date(2026, 11, 10)
    assert periods.due_scheduled_date(schedule, at(day, 7, 59)) is None
    assert periods.due_scheduled_date(schedule, at(day, 8, 0)) == day
    assert periods.due_scheduled_date(schedule, at(day, 8, 14)) == day
    assert periods.due_scheduled_date(schedule, at(day, 8, 15)) is None


def test_schedule_stays_at_0800_chile_across_the_daylight_saving_change():
    schedule = config.MAILING_SCHEDULES["emin"]
    before, after = date(2026, 9, 2), date(2026, 9, 9)  # invierno (UTC-4) y verano (UTC-3)
    m_before, m_after = periods.scheduled_moment(schedule, before), periods.scheduled_moment(schedule, after)
    assert (m_before.hour, m_after.hour) == (8, 8)
    assert m_before.utcoffset() != m_after.utcoffset()
    # Una hora UTC fija se correria: 12:00 UTC es las 08:00 antes del cambio y las 09:00 despues.
    utc = ZoneInfo("UTC")
    assert periods.due_scheduled_date(schedule, datetime(2026, 9, 2, 12, 0, tzinfo=utc)) == before
    assert periods.due_scheduled_date(schedule, datetime(2026, 9, 9, 12, 0, tzinfo=utc)) is None
    assert periods.due_scheduled_date(schedule, datetime(2026, 9, 9, 11, 0, tzinfo=utc)) == after


def test_mailing_schedules_hold_exactly_the_intended_values():
    """Guards against a temporary test schedule being committed (01.1)."""
    assert config.MAILING_TIMEZONE == "America/Santiago"
    assert config.MAILING_SCHEDULES == {
        "emin": {"frequency": "daily", "time": "08:00"},
        "capstone": {"frequency": "weekly", "weekday": "wednesday", "time": "08:00"},
    }


@pytest.mark.parametrize("zone", ["Asia/Tokyo", "America/New_York", "Europe/Madrid", "UTC", "Pacific/Auckland"])
def test_schedule_is_evaluated_in_chile_time_whatever_the_machine_zone(zone):
    """`now` expressed in any machine zone fires at 08:00 Chile, never at 08:00 of that zone."""
    schedule = config.MAILING_SCHEDULES["emin"]
    machine = ZoneInfo(zone)
    day = date(2026, 11, 10)
    chile_0800 = datetime(2026, 11, 10, 8, 0, tzinfo=SANTIAGO)
    assert periods.due_scheduled_date(schedule, chile_0800.astimezone(machine)) == day
    local_0800 = datetime(2026, 11, 10, 8, 0, tzinfo=machine)
    if local_0800.astimezone(SANTIAGO).strftime("%H:%M") != "08:00":
        assert periods.due_scheduled_date(schedule, local_0800) is None


def test_chile_0800_is_fixed_in_chile_time_across_a_daylight_saving_change_seen_from_another_zone():
    schedule = config.MAILING_SCHEDULES["emin"]
    tokyo = ZoneInfo("Asia/Tokyo")  # no daylight saving: its offset to Chile moves when Chile changes
    for day in (date(2026, 9, 4), date(2026, 9, 7)):  # before and after Chile's spring forward (Sep 6)
        moment = periods.scheduled_moment(schedule, day)
        assert (moment.hour, moment.minute) == (8, 0)
        assert periods.due_scheduled_date(schedule, moment.astimezone(tokyo)) == day
        assert periods.due_scheduled_date(schedule, (moment - timedelta(minutes=1)).astimezone(tokyo)) is None


def test_scheduler_tick_runs_each_due_client_once_per_day():
    started = []
    scheduler = MailingScheduler(runner=lambda c, d: started.append((c, d)) or "sent")
    wednesday = date(2026, 11, 11)
    first = scheduler.tick(at(wednesday))
    for w in list(scheduler._workers):
        w.join(2)
    assert sorted(c for c, _ in first) == ["capstone", "emin"]
    assert scheduler.tick(at(wednesday, 8, 1)) == []  # mismo dia: no se relanza
    next_day = scheduler.tick(at(wednesday + timedelta(days=1)))
    for w in list(scheduler._workers):
        w.join(2)
    assert [c for c, _ in next_day] == ["emin"]  # el jueves solo corre el diario
    assert len(started) == 3


def test_scheduler_is_on_by_default_and_can_be_switched_off(monkeypatch):
    from src.mailing import scheduler as scheduler_module

    assert config.scheduler_enabled()  # default: yes
    monkeypatch.setenv("MAILING_SCHEDULER_ENABLED", "false")
    assert not config.scheduler_enabled()
    scheduler_module.stop_mailing_scheduler()
    assert scheduler_module.start_mailing_scheduler() is None


# --------------------------------------------------------------------------- exactly once / retries


def test_scheduled_run_triggered_twice_sends_once(builder, sent):
    day = date(2026, 11, 10)
    assert run_scheduled("emin", day) == "sent"
    assert run_scheduled("emin", day) == "skipped"
    assert len(sent["calls"]) == 1
    assert state.read("emin", day)["status"] == "sent"


def test_scheduled_run_from_many_threads_sends_once(builder, sent):
    day = date(2026, 11, 10)
    outcomes = []
    threads = [threading.Thread(target=lambda: outcomes.append(run_scheduled("emin", day))) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert outcomes.count("sent") == 1 and outcomes.count("skipped") == 11
    assert len(sent["calls"]) == 1


def test_marker_survives_a_restart(builder, sent):
    day = date(2026, 11, 10)
    run_scheduled("emin", day)
    # "Reinicio": nada en memoria, solo el archivo en disco.
    assert run_scheduled("emin", day) == "skipped"
    # otro dia u otro cliente si corren
    assert run_scheduled("emin", day + timedelta(days=1)) == "sent"
    assert run_scheduled("capstone", day) == "sent"


def test_scheduled_failure_is_retried_with_growing_waits_then_succeeds(builder, sent):
    sent["results"] = [delivery.DeliveryResult(False, "boom"), delivery.DeliveryResult(False, "boom")]
    waits = []
    assert run_scheduled("emin", date(2026, 11, 10), sleep=waits.append) == "sent"
    assert len(sent["calls"]) == 3
    assert waits == [1.0, 2.0]


def test_scheduled_failure_gives_up_after_three_retries_and_logs_an_error(builder, sent, caplog):
    sent["results"] = [delivery.DeliveryResult(False, "boom")] * 10
    waits = []
    with caplog.at_level(logging.ERROR):
        assert run_scheduled("emin", date(2026, 11, 10), sleep=waits.append) == "failed"
    assert len(sent["calls"]) == 4  # 1 intento + 3 reintentos
    assert waits == [1.0, 2.0, 3.0]
    assert any("FAILED after 4 attempts" in r.getMessage() for r in caplog.records)
    assert state.read("emin", date(2026, 11, 10))["status"] == "failed"


def test_scheduled_send_in_production_reaches_every_expected_recipient(builder, sent, production):
    run_scheduled("emin", date(2026, 11, 10))
    assert sent["calls"][0]["emails"] == EMIN_SEND + TECHS + GERENCIA


def test_scheduled_send_outside_production_reaches_the_same_recipients(builder, sent):
    run_scheduled("capstone", date(2026, 11, 11))
    assert sent["calls"][0]["emails"] == CAPSTONE_SEND + TECHS + GERENCIA


def test_scheduled_and_manual_share_builder_and_delivery(builder, sent, flask_app):
    run_scheduled("emin", date(2026, 11, 10))
    admin = as_user(flask_app, ADMIN)
    send_manual("emin", [], admin)
    assert len(builder.calls) == 2 and len(sent["calls"]) == 2


# --------------------------------------------------------------------------- manual send


def test_manual_send_always_adds_technical(builder, sent, flask_app, production):
    admin = as_user(flask_app, ADMIN)
    result = send_manual("emin", [EMIN_SEND[0]], admin)
    assert result["ok"] and result["status"] == "sent"
    assert sent["calls"][0]["emails"] == [EMIN_SEND[0], *TECHS]
    assert [r["status"] for r in result["recipients"]] == ["sent"] * (1 + len(TECHS))


def test_manual_mock_test_is_just_technical_selected(builder, sent, flask_app, production):
    admin = as_user(flask_app, ADMIN)
    send_manual("emin", [TECH], admin)
    assert sent["calls"][0]["emails"] == TECHS


def test_manual_send_rejects_emails_outside_the_allowed_set(builder, sent, flask_app, production):
    admin = as_user(flask_app, ADMIN)
    with pytest.raises(MailingValidationError) as info:
        send_manual("emin", [EMIN_SEND[0], "intruso@evil.com"], admin)
    assert info.value.rejected == ["intruso@evil.com"]
    assert sent["calls"] == []


def test_manual_send_rejects_another_clients_contact(builder, sent, flask_app, production):
    admin = as_user(flask_app, ADMIN)
    capstone_contact = config.MAILING_RECIPIENTS["capstone"][0]["email"]
    with pytest.raises(MailingValidationError):
        send_manual("emin", [capstone_contact], admin)
    assert sent["calls"] == []


def test_manual_send_outside_production_accepts_the_whole_registry(builder, sent, flask_app):
    admin = as_user(flask_app, ADMIN)
    assert not config.is_production()
    send_manual("emin", [EMIN_SEND[0], GERENCIA[0], TECH], admin)
    assert sent["calls"][0]["emails"] == [EMIN_SEND[0], GERENCIA[0], *TECHS]


def test_manual_send_outside_production_still_rejects_emails_outside_the_registry(builder, sent, flask_app):
    admin = as_user(flask_app, ADMIN)
    with pytest.raises(MailingValidationError) as info:
        send_manual("emin", [EMIN_SEND[0], "intruso@evil.com"], admin)
    assert info.value.rejected == ["intruso@evil.com"]
    assert sent["calls"] == []


def test_manual_send_outside_production_always_adds_technical(builder, sent, flask_app):
    admin = as_user(flask_app, ADMIN)
    send_manual("emin", [GERENCIA[0]], admin)
    assert sent["calls"][0]["emails"] == [GERENCIA[0], *TECHS]
    send_manual("emin", [], admin)
    assert sent["calls"][1]["emails"] == TECHS


def test_manual_send_matches_emails_case_insensitively_without_duplicates(builder, sent, flask_app, production):
    admin = as_user(flask_app, ADMIN)
    send_manual("emin", [EMIN_SEND[0].upper(), EMIN_SEND[0], TECH.upper()], admin)
    assert sent["calls"][0]["emails"] == [EMIN_SEND[0], *TECHS]


def test_manual_failure_is_returned_not_retried(builder, sent, flask_app):
    sent["results"] = [delivery.DeliveryResult(False, "El servicio de correo rechazó el envío.")]
    admin = as_user(flask_app, ADMIN)
    result = send_manual("emin", [], admin)
    assert not result["ok"] and result["status"] == "failed"
    assert result["recipients"][0]["status"] == "failed"
    assert len(sent["calls"]) == 1
    assert "http" not in result["message"].lower()


def test_manual_send_does_not_touch_the_scheduled_marker(builder, sent, flask_app):
    admin = as_user(flask_app, ADMIN)
    send_manual("emin", [], admin)
    today = periods.today_local()
    assert state.read("emin", today) is None
    assert run_scheduled("emin", today) == "sent"


def test_double_trigger_during_a_send_is_rejected(builder, flask_app, monkeypatch):
    admin = as_user(flask_app, ADMIN)
    entered, release = threading.Event(), threading.Event()

    def slow_send(subject, html, emails):
        entered.set()
        release.wait(5)
        return delivery.DeliveryResult(True)

    monkeypatch.setattr(delivery, "send_email", slow_send)
    def first_click():
        with flask_app.test_request_context():  # cada peticion de Flask tiene su propio contexto
            flask_session["dashboard_user"] = ADMIN
            send_manual("emin", [], admin)

    first = threading.Thread(target=first_click)
    first.start()
    assert entered.wait(5)
    with pytest.raises(MailingBusyError):
        send_manual("emin", [], admin)
    release.set()
    first.join(5)


def test_second_manual_send_within_the_cooldown_is_rejected(builder, sent, flask_app, monkeypatch):
    monkeypatch.setenv("MAILING_MANUAL_COOLDOWN_SECONDS", "60")
    admin = as_user(flask_app, ADMIN)
    send_manual("emin", [], admin)
    with pytest.raises(MailingBusyError):
        send_manual("emin", [], admin)
    assert len(sent["calls"]) == 1


def test_failed_manual_send_can_be_retried_immediately(builder, sent, flask_app, monkeypatch):
    monkeypatch.setenv("MAILING_MANUAL_COOLDOWN_SECONDS", "60")
    sent["results"] = [delivery.DeliveryResult(False, "x")]
    admin = as_user(flask_app, ADMIN)
    assert not send_manual("emin", [], admin)["ok"]
    assert send_manual("emin", [], admin)["ok"]


def test_manual_send_for_unconfigured_client_is_refused(builder, sent, flask_app):
    admin = as_user(flask_app, ADMIN)
    with pytest.raises(MailingError) as info:
        send_manual("cda", [], admin)
    assert info.value.user_message == "Este cliente no tiene envío de resúmenes configurado."
    assert sent["calls"] == []


def test_without_a_registered_builder_the_error_is_readable(flask_app, sent, monkeypatch):
    import sys

    report.unregister_report_builder(report.ALERT_SUMMARY)
    monkeypatch.setitem(sys.modules, "src.mailing.alert_summary", None)  # import -> ImportError
    admin = as_user(flask_app, ADMIN)
    with pytest.raises(MailingError) as info:
        send_manual("emin", [], admin)
    assert info.value.code == "report_unavailable"
    assert sent["calls"] == []


def test_a_crashing_builder_does_not_leak_internals(flask_app, sent):
    def broken(request):
        raise RuntimeError("secret internals /srv/app/path https://x")

    register_report_builder(report.ALERT_SUMMARY, broken)
    try:
        admin = as_user(flask_app, ADMIN)
        with pytest.raises(MailingError) as info:
            build_preview("emin", admin)
        assert "secret" not in info.value.user_message and "http" not in info.value.user_message
    finally:
        report.unregister_report_builder(report.ALERT_SUMMARY)


# --------------------------------------------------------------------------- context / preview


def test_context_for_capstone_in_production(flask_app, production):
    admin = as_user(flask_app, ADMIN)
    ctx = get_mailing_context("CAPSTONE", admin, now=at(date(2026, 11, 11), 10, 0))
    assert ctx["configured"] and ctx["client"] == "capstone"
    assert ctx["report_type"] == "weekly" and ctx["report_title"] == "Resumen Semanal de Alertas"
    assert ctx["subject"] == "[CODDI] Monitoreo de Alertas 11/11/2026"
    assert ctx["period"]["text"] == "04/11/2026 – 10/11/2026 (últimos 7 días)"
    assert ctx["schedule_description"] == "se envía automáticamente los miércoles a las 08:00 (hora de Chile)"
    assert ctx["environment"] == "production"
    groups = [r["group"] for r in ctx["recipients"]]
    assert groups == sorted(groups, key=config.GROUP_ORDER.index)
    for r in ctx["recipients"]:
        assert {"name", "email", "group", "selected_by_default", "locked", "disabled", "disabled_reason"} <= set(r)
        assert r["disabled"] == r["locked"]
    tech = next(r for r in ctx["recipients"] if r["email"] == TECH)
    assert tech["locked"] and tech["selected_by_default"]


def test_context_outside_production_selects_only_technical_and_disables_nothing_else(flask_app):
    admin = as_user(flask_app, ADMIN)
    ctx = get_mailing_context("emin", admin)
    assert ctx["environment"] == "development" and not ctx["is_production"]
    assert [r["email"] for r in ctx["recipients"]] == EMIN_ALL + TECHS + GERENCIA
    for r in ctx["recipients"]:
        is_tech = r["email"] in TECHS
        assert r["selected_by_default"] == is_tech
        assert r["locked"] == is_tech
        assert r["disabled"] == is_tech  # only locked rows
        if not is_tech:
            assert not r["disabled_reason"]


def test_context_in_production_keeps_the_ticket_01_defaults(flask_app, production):
    admin = as_user(flask_app, ADMIN)
    ctx = get_mailing_context("emin", admin)
    assert ctx["environment"] == "production" and ctx["is_production"]
    defaults = [r["email"] for r in ctx["recipients"] if r["selected_by_default"]]
    assert defaults == EMIN_SEND + TECHS + GERENCIA
    assert [r["email"] for r in ctx["recipients"] if r["locked"]] == TECHS


def test_context_for_emin_is_daily(flask_app):
    admin = as_user(flask_app, ADMIN)
    ctx = get_mailing_context("emin", admin, now=at(date(2026, 11, 10), 15, 0))
    assert ctx["report_title"] == "Resumen Diario de Alertas"
    assert ctx["period"]["text"] == "09/11/2026 (último día)"
    assert ctx["schedule_description"] == "se envía automáticamente todos los días a las 08:00 (hora de Chile)"


def test_context_for_unconfigured_client_says_so(flask_app):
    admin = as_user(flask_app, ADMIN)
    ctx = get_mailing_context("cda", admin)
    assert ctx["configured"] is False
    assert ctx["message"] == "Este cliente no tiene envío de resúmenes configurado."


def test_preview_equals_what_a_send_would_deliver_and_sends_nothing(builder, sent, flask_app):
    admin = as_user(flask_app, ADMIN)
    now = at(date(2026, 11, 10), 12, 0)
    preview = build_preview("emin", admin, now=now)
    assert sent["calls"] == []
    send_manual("emin", [], admin, now=now)
    assert (preview["subject"], preview["html"]) == (sent["calls"][0]["subject"], sent["calls"][0]["html"])


def test_service_enforces_the_subject_contract(flask_app, sent):
    register_report_builder(
        report.ALERT_SUMMARY, lambda r: ReportContent(subject="otro asunto", html="<p>x</p>")
    )
    try:
        admin = as_user(flask_app, ADMIN)
        now = at(date(2026, 11, 10), 12, 0)
        assert build_preview("emin", admin, now=now)["subject"] == "[CODDI] Monitoreo de Alertas 10/11/2026"
    finally:
        report.unregister_report_builder(report.ALERT_SUMMARY)


# --------------------------------------------------------------------------- authorization


@pytest.mark.parametrize("operation", ["context", "preview", "send"])
def test_non_admin_cannot_call_any_operation(builder, sent, flask_app, operation):
    user = as_user(flask_app, CLIENT_USER)
    calls = {
        "context": lambda u: get_mailing_context("emin", u),
        "preview": lambda u: build_preview("emin", u),
        "send": lambda u: send_manual("emin", [], u),
    }
    with pytest.raises(MailingPermissionError):
        calls[operation](user)
    assert sent["calls"] == [] and builder.calls == []


def test_a_browser_claiming_the_admin_role_is_not_believed(builder, sent, flask_app):
    forged = as_user(flask_app, CLIENT_USER)
    forged["role"] = "admin"
    with pytest.raises(MailingPermissionError):
        send_manual("emin", [], forged)
    assert sent["calls"] == []


def test_without_a_session_or_proof_nobody_is_admin(builder, sent, flask_app):
    with flask_app.test_request_context():
        with pytest.raises(MailingPermissionError):
            send_manual("emin", [], {"username": ADMIN, "role": "admin"})
    with pytest.raises(MailingPermissionError):  # ni siquiera hay peticion
        get_mailing_context("emin", {"username": ADMIN, "role": "admin"})
    assert sent["calls"] == []


# --------------------------------------------------------------------------- delivery


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, json_error=False):
        self.status_code, self._body, self.headers, self._json_error = status, body, headers or {}, json_error

    def json(self):
        if self._json_error:
            raise ValueError("no json")
        return self._body


def test_delivery_posts_the_lambda_contract(monkeypatch):
    seen = {}

    def fake_post(url, data, headers, timeout):
        seen.update(url=url, data=data, headers=headers, timeout=timeout)
        return FakeResponse(200, {"statusCode": 200})

    monkeypatch.setattr(delivery.requests, "post", fake_post)
    result = delivery.send_email("Asunto", "<p>Hola</p>", ["a@x.cl", "b@x.cl"])
    assert result.ok
    import json

    body = json.loads(seen["data"])
    assert body == {
        "fieldName": "CDA-alert",
        "variables": {"sendCDAAlertEmailInput": {
            "mailTo": ["a@x.cl", "b@x.cl"], "mailSubject": "Asunto", "mailText": "<p>Hola</p>",
        }},
    }
    assert seen["url"] == SECRET_URL


def test_requests_are_signed_with_sigv4_for_the_function_url_region(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        delivery.requests, "post",
        lambda url, data, headers, timeout: seen.update(headers=headers) or FakeResponse(200, {}),
    )
    assert delivery.send_email("s", "h", ["a@x.cl"]).ok
    auth = seen["headers"]["Authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIAFAKEFAKEFAKEFAKE/")
    assert "/us-east-2/lambda/aws4_request" in auth
    assert seen["headers"]["Content-Type"] == "application/json"
    assert "X-Amz-Date" in seen["headers"]


def test_the_s3_keys_are_never_used_to_sign(monkeypatch):
    monkeypatch.delenv("LAMBDA_ACCESS_KEY")
    monkeypatch.delenv("LAMBDA_SECRET_ACCESS_KEY")
    monkeypatch.setenv("ACCESS_KEY", "AKIAS3S3S3S3S3S3S3S3")
    monkeypatch.setenv("SECRET_KEY", "s3-secret")
    import botocore.session

    monkeypatch.setattr(botocore.session.Session, "get_credentials", lambda self: None)
    assert set(delivery._signed_headers(SECRET_URL, "{}")) == {"Content-Type"}


def test_without_any_credentials_the_request_goes_out_unsigned(monkeypatch):
    monkeypatch.delenv("LAMBDA_ACCESS_KEY")
    monkeypatch.delenv("LAMBDA_SECRET_ACCESS_KEY")
    monkeypatch.setattr(delivery, "_credentials", lambda: None)
    seen = {}
    monkeypatch.setattr(
        delivery.requests, "post",
        lambda url, data, headers, timeout: seen.update(headers=headers) or FakeResponse(200, {}),
    )
    assert delivery.send_email("s", "h", ["a@x.cl"]).ok
    assert "Authorization" not in seen["headers"]


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(500, {}),
        FakeResponse(502, {}),
        FakeResponse(200, {"statusCode": 500, "body": "x"}),
        FakeResponse(200, {"errorMessage": "Task timed out", "errorType": "Sandbox.Timedout"}),
        FakeResponse(200, {}, headers={"X-Amz-Function-Error": "Unhandled"}),
        FakeResponse(200, {"errors": [{"message": "bad"}]}),
    ],
)
def test_anything_but_a_confirmed_success_is_a_failure(monkeypatch, response):
    monkeypatch.setattr(delivery.requests, "post", lambda *a, **k: response)
    assert not delivery.send_email("s", "h", ["a@x.cl"]).ok


@pytest.mark.parametrize("response", [FakeResponse(200, {"statusCode": 200}), FakeResponse(200, json_error=True), FakeResponse(200, {})])
def test_success_shapes(monkeypatch, response):
    monkeypatch.setattr(delivery.requests, "post", lambda *a, **k: response)
    assert delivery.send_email("s", "h", ["a@x.cl"]).ok


@pytest.mark.parametrize("exc", [delivery.requests.Timeout, delivery.requests.ConnectionError])
def test_network_errors_never_expose_the_lambda_url(monkeypatch, caplog, exc):
    def boom(*a, **k):
        raise exc(f"HTTPSConnectionPool host={SECRET_URL} failed")

    monkeypatch.setattr(delivery.requests, "post", boom)
    with caplog.at_level(logging.DEBUG):
        result = delivery.send_email("s", "h", ["a@x.cl"])
    assert not result.ok
    assert "secret" not in (result.reason or "") and "http" not in (result.reason or "").lower()
    assert "abc123secret" not in caplog.text


def test_scheduled_run_without_lambda_url_logs_an_error_and_does_not_raise(builder, monkeypatch, caplog):
    monkeypatch.delenv("LAMBDA_URL")
    with caplog.at_level(logging.ERROR):
        outcome = run_scheduled("emin", date(2026, 11, 10), sleep=lambda s: None)
    assert outcome == "failed"
    assert any("FAILED" in r.getMessage() for r in caplog.records)
    assert state.read("emin", date(2026, 11, 10))["status"] == "failed"


def test_missing_lambda_url_is_a_failure_not_a_crash(monkeypatch):
    monkeypatch.delenv("LAMBDA_URL")
    result = delivery.send_email("s", "h", ["a@x.cl"])
    assert not result.ok


def test_delivery_refuses_an_empty_recipient_list():
    assert not delivery.send_email("s", "h", []).ok


def test_lambda_url_tolerates_quotes_and_spaces_in_the_env_value(monkeypatch):
    monkeypatch.setenv("LAMBDA_URL", f'  "{SECRET_URL}"  ')
    assert config.get_lambda_url() == SECRET_URL


# --------------------------------------------------------------------------- logging


def test_send_attempts_are_logged_without_body_or_url(builder, flask_app, monkeypatch, caplog, production):
    monkeypatch.setattr(delivery.requests, "post", lambda *a, **k: FakeResponse(200, {"statusCode": 200}))
    admin = as_user(flask_app, ADMIN)
    with caplog.at_level(logging.DEBUG):
        send_manual("emin", [EMIN_SEND[0]], admin)
        run_scheduled("capstone", date(2026, 11, 11))
    text = caplog.text
    assert "CUERPO-SECRETO-DEL-CORREO" not in text and "abc123secret" not in text
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("mailing send")]
    assert len(lines) == 2
    manual, scheduled = lines
    for field in ("client=emin", "trigger=manual", f"requested_by={ADMIN}", EMIN_SEND[0], TECH, "[CODDI] Monitoreo de Alertas", f"{TECH}=sent"):
        assert field in manual
    for field in ("client=capstone", "trigger=scheduled", "requested_by=-"):
        assert field in scheduled
    host = config.get_hostname()
    for line in (manual, scheduled):
        assert "environment=production" in line and f"host={host}" in line
