"""In-app schedule of the alert partitioner (src/data/partition_scheduler.py) and the e-mail's dependency on it.

The partitioner runs inside the app (Wednesday 08:00, EMIN daily 11:30, America/Santiago), once per
schedule across workers, in the background; the alert-summary e-mail (Wednesday 08:30) only goes out when
this period's run finished OK.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.data import partition_scheduler as ps
from src.mailing import ReportContent, config, delivery, periods, register_report_builder, report, run_scheduled, state
from src.mailing.scheduler import MailingScheduler

SANTIAGO = ZoneInfo("America/Santiago")
WEDNESDAY = date(2026, 12, 2)  # the first Wednesday after the move (a deadline of the task)
assert WEDNESDAY.weekday() == 2


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=SANTIAGO)


@pytest.fixture(autouse=True)
def hermetic(monkeypatch, tmp_path):
    for name in ("ALERT_PARTITIONS_TIMEZONE", "ALERT_PARTITIONS_WEEKDAY", "ALERT_PARTITIONS_TIME",
                 "ALERT_PARTITIONS_DAILY_CLIENTS", "ALERT_PARTITIONS_DAILY_TIME", "ALERT_PARTITIONS_GRACE_MINUTES",
                 "ALERT_PARTITIONS_SCHEDULER_ENABLED", "ALERT_PARTITIONS_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_DOTENV_LOADED", True)  # no real .env
    monkeypatch.setenv("DEPLOY_STATUS", "test")
    monkeypatch.setenv("ALERT_PARTITIONS_STATE_DIR", str(tmp_path / "partitions"))
    monkeypatch.setenv("MAILING_STATE_DIR", str(tmp_path / "mailing"))
    monkeypatch.setenv("LAMBDA_FUNCTION_NAME", "arn:aws:lambda:us-east-1:111122223333:function:x")
    monkeypatch.setenv("MAILING_RETRY_DELAYS", "1")
    monkeypatch.setenv("SYNC_DATA", "false")
    monkeypatch.setattr(config, "SCHEDULED_TECHNICAL_ONLY_CLIENTS", frozenset())
    ps.stop_partition_scheduler()
    yield
    ps.stop_partition_scheduler()


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setenv("DEPLOY_STATUS", "POC")


def fake_runner(code=0, calls=None):
    def runner(command, timeout):
        if calls is not None:
            calls.append((list(command), timeout))
        return code
    return runner


# --------------------------------------------------------------------------- settings and schedule


def test_defaults_are_wednesday_0800_and_emin_daily_1030_in_santiago():
    settings = ps.load_settings()
    assert (settings.timezone, settings.weekday, settings.weekly_time.strftime("%H:%M")) == ("America/Santiago", 2, "08:00")
    assert (settings.daily_clients, settings.daily_time.strftime("%H:%M")) == (("emin",), "11:30")


def test_the_schedule_is_configurable_from_the_environment(monkeypatch):
    monkeypatch.setenv("ALERT_PARTITIONS_TIMEZONE", "UTC")
    monkeypatch.setenv("ALERT_PARTITIONS_WEEKDAY", "thursday")
    monkeypatch.setenv("ALERT_PARTITIONS_TIME", "05:30")
    monkeypatch.setenv("ALERT_PARTITIONS_DAILY_CLIENTS", "emin, cda")
    monkeypatch.setenv("ALERT_PARTITIONS_DAILY_TIME", "11:15")
    settings = ps.load_settings()
    assert (settings.timezone, settings.weekday, settings.weekly_time.strftime("%H:%M")) == ("UTC", 3, "05:30")
    assert (settings.daily_clients, settings.daily_time.strftime("%H:%M")) == (("emin", "cda"), "11:15")
    monkeypatch.setenv("ALERT_PARTITIONS_DAILY_CLIENTS", "none")
    assert ps.load_settings().daily_clients == ()


def test_the_weekly_job_is_due_on_wednesday_from_0800_for_the_grace_window_only():
    assert ps.due_job_dates(at(WEDNESDAY, 7, 59)) == []
    assert ps.due_job_dates(at(WEDNESDAY, 8, 0)) == [("weekly", WEDNESDAY)]
    assert ps.due_job_dates(at(WEDNESDAY, 8, 14)) == [("weekly", WEDNESDAY)]
    assert ps.due_job_dates(at(WEDNESDAY, 8, 15)) == []
    for offset in (1, 2, 3, 4, 5, 6):  # Thursday .. Tuesday: not at 08:00
        assert ps.due_job_dates(at(WEDNESDAY + timedelta(days=offset), 8, 0)) == []


def test_the_daily_job_is_due_every_day_at_1130_and_can_be_switched_off(monkeypatch):
    for offset in range(7):
        day = WEDNESDAY + timedelta(days=offset)
        assert ("daily", day) in ps.due_job_dates(at(day, 11, 30))
        assert ps.due_job_dates(at(day, 11, 29)) == []
    monkeypatch.setenv("ALERT_PARTITIONS_DAILY_CLIENTS", "none")
    assert ps.due_job_dates(at(WEDNESDAY, 11, 30)) == []


@pytest.mark.parametrize("zone", ["Asia/Tokyo", "America/New_York", "UTC", "Pacific/Auckland"])
def test_the_hour_is_chile_time_whatever_the_machine_zone(zone):
    machine = ZoneInfo(zone)
    assert ps.due_job_dates(at(WEDNESDAY, 8, 0).astimezone(machine)) == [("weekly", WEDNESDAY)]
    assert ps.due_job_dates(at(WEDNESDAY, 7, 59).astimezone(machine)) == []


def test_the_wall_clock_hour_holds_across_the_chile_daylight_saving_change():
    before, after = date(2026, 9, 2), date(2026, 9, 9)  # Wednesdays; winter (UTC-4) and summer (UTC-3)
    assert at(before, 8).utcoffset() != at(after, 8).utcoffset()
    assert ps.due_job_dates(at(before, 8)) == [("weekly", before)]
    assert ps.due_job_dates(at(after, 8)) == [("weekly", after)]


def test_the_scheduler_starts_only_in_production_and_can_be_switched_off(production, monkeypatch, caplog):
    assert ps.disabled_reason() is None
    monkeypatch.setenv("ALERT_PARTITIONS_SCHEDULER_ENABLED", "false")
    assert "ALERT_PARTITIONS_SCHEDULER_ENABLED" in ps.disabled_reason()
    assert ps.start_partition_scheduler() is None
    monkeypatch.setenv("DEPLOY_STATUS", "dev")
    monkeypatch.delenv("ALERT_PARTITIONS_SCHEDULER_ENABLED")
    with caplog.at_level(logging.INFO):
        assert ps.start_partition_scheduler() is None
    assert "not production" in ps.disabled_reason()


def test_in_production_it_starts_once_and_stops(production):
    first = ps.start_partition_scheduler()
    try:
        assert first is not None and ps.start_partition_scheduler() is first  # idempotent
    finally:
        ps.stop_partition_scheduler()
    assert ps._SCHEDULER is None


# --------------------------------------------------------------------------- what runs


def test_the_weekly_job_runs_every_client_and_the_daily_one_only_the_daily_clients():
    weekly, daily = ps.build_command("weekly"), ps.build_command("daily")
    assert weekly[1] == daily[1] == str(ps.SCRIPT_PATH) and weekly[0] == sys.executable
    assert weekly[2:] == []  # no --client: every client found
    assert daily[2:] == ["--client", "emin"]
    for command in (weekly, daily):
        assert "--backfill" not in command and "--sync-s3" not in command  # the normal weekly run, which syncs by itself


def test_run_job_runs_the_script_and_records_the_status():
    calls = []
    assert ps.run_job("weekly", WEDNESDAY, runner=fake_runner(0, calls)) == "ok"
    (command, timeout), = calls
    assert command[1].endswith("partition_alerts.py") and timeout == ps.DEFAULT_TIMEOUT_SECONDS
    marker = ps.read("weekly", WEDNESDAY)
    assert marker["status"] == "ok" and marker["exit_code"] == 0 and "started_at" in marker and "finished_at" in marker


@pytest.mark.parametrize("code", [1, 2])
def test_a_failed_run_is_an_error_in_the_log_and_in_the_status(code, caplog):
    with caplog.at_level(logging.ERROR):
        assert ps.run_job("weekly", WEDNESDAY, runner=fake_runner(code)) == "failed"
    assert ps.read("weekly", WEDNESDAY)["status"] == "failed" and ps.read("weekly", WEDNESDAY)["exit_code"] == code
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("FAILED" in m and f"exit status {code}" in m for m in errors)


def test_a_crashing_run_is_recorded_as_failed_and_never_raises(caplog):
    def boom(command, timeout):
        raise OSError("no python")

    with caplog.at_level(logging.ERROR):
        assert ps.run_job("weekly", WEDNESDAY, runner=boom) == "failed"
    assert ps.read("weekly", WEDNESDAY)["status"] == "failed"


def test_a_run_is_never_retried():
    calls = []
    assert ps.run_job("weekly", WEDNESDAY, runner=fake_runner(2, calls)) == "failed"
    assert ps.run_job("weekly", WEDNESDAY, runner=fake_runner(0, calls)) == "skipped"  # same day: the marker holds
    assert len(calls) == 1


def test_a_job_with_no_daily_client_is_skipped(monkeypatch):
    monkeypatch.setenv("ALERT_PARTITIONS_DAILY_CLIENTS", "none")
    calls = []
    assert ps.run_job("daily", WEDNESDAY, runner=fake_runner(0, calls)) == "skipped" and calls == []


# --------------------------------------------------------------------------- once per schedule (workers / restarts)


def test_the_same_run_from_many_threads_happens_once():
    calls, release = [], threading.Event()

    def slow(command, timeout):
        calls.append(1)
        release.wait(2)
        return 0

    results = []
    threads = [threading.Thread(target=lambda: results.append(ps.run_job("weekly", WEDNESDAY, runner=slow))) for _ in range(12)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    release.set()
    for t in threads:
        t.join(5)
    assert sorted(results) == ["ok"] + ["skipped"] * 11 and len(calls) == 1


def test_the_marker_survives_a_restart_so_no_run_is_repeated():
    assert ps.run_job("weekly", WEDNESDAY, runner=fake_runner(0)) == "ok"
    ps.stop_partition_scheduler()  # a "restart": new process state, same marker directory
    scheduler = ps.PartitionScheduler()
    calls = []
    scheduler._runner = lambda job, day: calls.append(ps.run_job(job, day, runner=fake_runner(0)))
    scheduler.tick(at(WEDNESDAY, 8, 5))
    for w in list(scheduler._workers):
        w.join(2)
    assert calls == ["skipped"]


def test_two_processes_racing_for_the_same_marker_run_it_once(tmp_path):
    """Real processes (gunicorn workers) share only the marker directory: exactly one wins the claim."""
    import subprocess

    code = (
        "import os, sys; sys.path.insert(0, %r); from datetime import date; from src.data import partition_scheduler as ps; "
        "print('won' if ps.claim('weekly', date(2026, 12, 2)) else 'lost')" % str(ps.REPOSITORY_ROOT)
    )
    env = dict(__import__("os").environ, ALERT_PARTITIONS_STATE_DIR=str(tmp_path / "shared"), PYTHONPATH=str(ps.REPOSITORY_ROOT))
    procs = [subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, text=True) for _ in range(6)]
    outputs = sorted(p.communicate(timeout=60)[0].strip().splitlines()[-1] for p in procs)
    assert outputs == ["lost"] * 5 + ["won"]


# --------------------------------------------------------------------------- never blocks the dashboard


def test_a_tick_returns_immediately_while_the_job_runs_in_the_background():
    started, release = threading.Event(), threading.Event()

    def slow(job, day):
        started.set()
        release.wait(5)

    scheduler = ps.PartitionScheduler(runner=slow)
    t0 = time.monotonic()
    assert scheduler.tick(at(WEDNESDAY, 8, 0)) == [("weekly", WEDNESDAY)]
    assert time.monotonic() - t0 < 1.0  # the loop (and the app) was not held
    assert started.wait(2)
    assert scheduler.tick(at(WEDNESDAY, 8, 1)) == []  # not launched twice
    release.set()
    for w in list(scheduler._workers):
        w.join(2)


def test_the_real_runner_streams_the_script_log_and_returns_its_exit_status(caplog):
    program = "import sys; print('2026 INFO x: all good'); print('2026 ERROR x: boom'); sys.exit(2)"
    with caplog.at_level(logging.INFO):
        code = ps._run_subprocess([sys.executable, "-c", program], 30)
    assert code == 2
    assert any("all good" in r.getMessage() and r.levelno == logging.INFO for r in caplog.records)
    assert any("boom" in r.getMessage() and r.levelno == logging.ERROR for r in caplog.records)


def test_a_run_that_exceeds_the_timeout_is_killed_and_fails():
    code = ps._run_subprocess([sys.executable, "-c", "import time; time.sleep(60)"], 0.5)
    assert code != 0


# --------------------------------------------------------------------------- the run status the e-mail reads


def test_no_run_means_the_email_must_not_go():
    assert "did not run" in ps.partition_run_problem("weekly", WEDNESDAY)
    assert "did not run" in ps.partition_run_problem("daily", WEDNESDAY)


def test_a_run_still_running_or_interrupted_blocks_the_email():
    assert ps.claim("weekly", WEDNESDAY)  # claimed, never finished
    assert "not finished" in ps.partition_run_problem("weekly", WEDNESDAY)


def test_a_failed_run_blocks_the_email_and_says_so():
    ps.run_job("weekly", WEDNESDAY, runner=fake_runner(2))
    assert "failed (exit status 2)" in ps.partition_run_problem("weekly", WEDNESDAY)


def test_a_successful_run_lets_the_email_go():
    ps.run_job("weekly", WEDNESDAY, runner=fake_runner(0))
    assert ps.partition_run_problem("weekly", WEDNESDAY) is None


def test_the_weekly_run_must_be_of_the_same_week_as_the_email():
    previous_week = WEDNESDAY - timedelta(days=7)
    ps.run_job("weekly", previous_week, runner=fake_runner(0))  # last week's run does not count
    assert "did not run" in ps.partition_run_problem("weekly", WEDNESDAY)
    monday = WEDNESDAY - timedelta(days=2)
    ps.run_job("weekly", monday, runner=fake_runner(0))  # a run earlier in the same week does
    assert ps.partition_run_problem("weekly", WEDNESDAY) is None


def test_the_newest_run_of_the_week_decides():
    ps.run_job("weekly", WEDNESDAY - timedelta(days=1), runner=fake_runner(0))
    ps.run_job("weekly", WEDNESDAY, runner=fake_runner(2))
    assert "failed" in ps.partition_run_problem("weekly", WEDNESDAY)


def test_the_daily_run_must_be_the_one_of_the_same_day():
    ps.run_job("daily", WEDNESDAY - timedelta(days=1), runner=fake_runner(0))
    assert "did not run" in ps.partition_run_problem("daily", WEDNESDAY)
    ps.run_job("daily", WEDNESDAY, runner=fake_runner(0))
    assert ps.partition_run_problem("daily", WEDNESDAY) is None


# --------------------------------------------------------------------------- the e-mail waits for the partitioner


@pytest.fixture
def mail(monkeypatch):
    """A fake builder and delivery that record what happens, with the shipped dependency map."""
    events = {"built": [], "sent": []}

    def fake_builder(request):
        events["built"].append(request)
        return ReportContent(subject=periods.build_subject(request.send_date), html="<html>ok</html>", meta={})

    register_report_builder(report.ALERT_SUMMARY, fake_builder)
    monkeypatch.setattr(delivery, "send_email", lambda subject, html, emails: events["sent"].append(subject) or delivery.DeliveryResult(True))
    monkeypatch.setattr(config, "MAILING_PARTITION_DEPENDENCY", {"emin": "daily", "capstone": "weekly"})
    monkeypatch.setattr(config, "MAILING_REQUIRE_ALERTS", frozenset())  # the alerts check has its own tests below
    yield events
    report.unregister_report_builder(report.ALERT_SUMMARY)


@pytest.mark.parametrize("setup, reason", [
    (lambda: None, "did not run"),
    (lambda: ps.claim("weekly", WEDNESDAY), "not finished"),
    (lambda: ps.run_job("weekly", WEDNESDAY, runner=fake_runner(1)), "failed"),
    (lambda: ps.run_job("weekly", WEDNESDAY, runner=fake_runner(2)), "failed"),
])
def test_the_email_is_not_sent_unless_the_weeks_partitioner_run_finished_ok(mail, caplog, setup, reason):
    setup()
    with caplog.at_level(logging.ERROR):
        assert run_scheduled("capstone", WEDNESDAY, sleep=lambda s: None) == "failed"
    assert mail["built"] == [] and mail["sent"] == []  # not even built
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("NOT SENT" in m and "capstone" in m and reason in m for m in errors)
    marker = state.read("capstone", WEDNESDAY)
    assert marker["status"] == "failed" and reason in marker["detail"]
    # No retry: the same schedule slot cannot send it later.
    ps.run_job("weekly", WEDNESDAY - timedelta(days=1), runner=fake_runner(0))
    assert run_scheduled("capstone", WEDNESDAY, sleep=lambda s: None) == "skipped" and mail["sent"] == []


def test_the_email_goes_out_after_a_successful_run_and_is_the_regular_email(mail):
    ps.run_job("weekly", WEDNESDAY, runner=fake_runner(0))
    assert run_scheduled("capstone", WEDNESDAY) == "sent"
    assert mail["sent"] == ["[CODDI] Monitoreo de Alertas 02/12/2026"]
    assert [r.erratum for r in mail["built"]] == [False]


def test_emin_waits_for_its_own_daily_run(mail):
    ps.run_job("weekly", WEDNESDAY, runner=fake_runner(0))  # the weekly run is not EMIN's dependency
    assert run_scheduled("emin", WEDNESDAY) == "failed" and mail["sent"] == []
    ps.run_job("daily", WEDNESDAY + timedelta(days=1), runner=fake_runner(0))
    assert run_scheduled("emin", WEDNESDAY + timedelta(days=1)) == "sent"


def test_a_client_without_a_dependency_is_not_checked(mail, monkeypatch):
    monkeypatch.setattr(config, "MAILING_PARTITION_DEPENDENCY", {})
    assert run_scheduled("capstone", WEDNESDAY) == "sent"


def test_the_weekly_data_is_ready_before_the_email_is_due():
    schedule = config.MAILING_SCHEDULES["capstone"]
    assert schedule["weekday"] == "wednesday" and schedule["time"] == "08:30"
    settings = ps.load_settings()
    weekly_at = datetime.combine(WEDNESDAY, settings.weekly_time)
    mail_at = datetime.combine(WEDNESDAY, periods.parse_time(schedule["time"]))
    assert mail_at - weekly_at == timedelta(minutes=30)
    assert settings.weekday == 2 and settings.weekly_time.strftime("%H:%M") == "08:00"


def test_dry_run_of_a_wednesday_partitioner_first_then_the_email(mail, monkeypatch):
    """Walk Wednesday with one clock: 08:00 -> partitioner, 08:30 -> e-mail, in that order."""
    order = []
    scheduler = ps.PartitionScheduler(runner=lambda job, day: order.append(f"partitioner-{job}") or ps.run_job(
        job, day, runner=lambda c, t: order.append("script-ran") or 0))
    mailer = MailingScheduler(runner=lambda client, day: order.append(f"mail-{client}") or run_scheduled(client, day))
    monkeypatch.setattr(delivery, "send_email", lambda s, h, e: order.append("mail-delivered") or delivery.DeliveryResult(True))

    def settle(*schedulers):
        for s in schedulers:
            for w in list(s._workers):
                w.join(5)

    for hour, minute in ((8, 0), (8, 10), (8, 30), (8, 31)):
        now = at(WEDNESDAY, hour, minute)
        scheduler.tick(now)
        settle(scheduler)
        mailer.tick(now)
        settle(mailer)
    assert order == ["partitioner-weekly", "script-ran", "mail-capstone", "mail-delivered"]
    assert ps.read("weekly", WEDNESDAY)["status"] == "ok"
    assert state.read("capstone", WEDNESDAY)["status"] == "sent"


def test_dry_run_when_the_partitioner_fails_the_email_is_not_sent(mail, monkeypatch, caplog):
    order = []
    scheduler = ps.PartitionScheduler(runner=lambda job, day: ps.run_job(job, day, runner=lambda c, t: 2))
    mailer = MailingScheduler(runner=lambda client, day: order.append(run_scheduled(client, day)))
    with caplog.at_level(logging.ERROR):
        scheduler.tick(at(WEDNESDAY, 8, 0))
        for w in list(scheduler._workers):
            w.join(5)
        mailer.tick(at(WEDNESDAY, 8, 30))
        for w in list(mailer._workers):
            w.join(5)
    assert order == ["failed"] and mail["sent"] == []
    assert any("NOT SENT" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- the capstone e-mail also needs alerts


@pytest.fixture
def alerts(mail, monkeypatch):
    """The shipped rule (capstone needs alerts) with a controllable number of alerts in the period."""
    from src.mailing import alert_summary

    box = {"count": 0, "asked": [], "boom": False}

    def fake_records(client, start, end):
        box["asked"].append((client, start, end))
        if box["boom"]:
            raise OSError("parquet corrupto")
        return [object()] * box["count"]

    monkeypatch.setattr(alert_summary, "load_period_records", fake_records)
    monkeypatch.setattr(config, "MAILING_REQUIRE_ALERTS", frozenset({"capstone"}))
    ps.run_job("weekly", WEDNESDAY, runner=fake_runner(0))  # the partitioner part is fine in these tests
    return box


def test_capstone_is_not_sent_when_the_period_has_no_alert(alerts, mail, caplog):
    with caplog.at_level(logging.ERROR):
        assert run_scheduled("capstone", WEDNESDAY, sleep=lambda s: None) == "failed"
    assert mail["built"] == [] and mail["sent"] == []
    assert alerts["asked"] == [("capstone", date(2026, 11, 23), date(2026, 11, 29))]  # the e-mail's own period
    assert any("NOT SENT" in r.getMessage() and "no alerts generated" in r.getMessage() for r in caplog.records
               if r.levelno >= logging.ERROR)
    assert "no alert of capstone" in state.read("capstone", WEDNESDAY)["detail"]
    assert run_scheduled("capstone", WEDNESDAY) == "skipped" and mail["sent"] == []  # no retry


def test_capstone_is_sent_when_the_period_has_alerts_and_the_partitioner_ran(alerts, mail):
    alerts["count"] = 43
    assert run_scheduled("capstone", WEDNESDAY) == "sent"
    assert mail["sent"] == ["[CODDI] Monitoreo de Alertas 02/12/2026"]


def test_unreadable_alerts_block_the_email_too(alerts, mail):
    alerts["boom"] = True
    assert run_scheduled("capstone", WEDNESDAY, sleep=lambda s: None) == "failed"
    assert mail["sent"] == [] and "could not be read" in state.read("capstone", WEDNESDAY)["detail"]


def test_the_partitioner_check_comes_first_and_stops_before_counting_alerts(mail, monkeypatch):
    from src.mailing import alert_summary

    asked = []
    monkeypatch.setattr(alert_summary, "load_period_records", lambda *a: asked.append(a) or [object()])
    monkeypatch.setattr(config, "MAILING_REQUIRE_ALERTS", frozenset({"capstone"}))
    assert run_scheduled("capstone", WEDNESDAY, sleep=lambda s: None) == "failed"  # the partitioner never ran
    assert asked == [] and "partitioner dependency" in state.read("capstone", WEDNESDAY)["detail"]


def test_emin_is_never_blocked_for_a_day_without_alerts(mail, monkeypatch):
    """EMIN generates alerts daily and not every day has alerts: an empty day still gets its e-mail."""
    from src.mailing import alert_summary

    monkeypatch.setattr(alert_summary, "load_period_records", lambda *a: [])
    monkeypatch.setattr(config, "MAILING_REQUIRE_ALERTS", frozenset({"capstone"}))  # as shipped
    ps.run_job("daily", WEDNESDAY, runner=fake_runner(0))
    assert run_scheduled("emin", WEDNESDAY) == "sent" and len(mail["sent"]) == 1
