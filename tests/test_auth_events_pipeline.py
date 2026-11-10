"""TR-1: login event capture, daily compaction, data-access layer and legacy migration."""

import json
import logging
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.auth_events import data_access, settings
from src.auth_events.compaction import compact, daily_key
from src.auth_events.events import build_event, raw_key, validate_event
from src.auth_events.migration import migrate
from src.auth_events.parquet_io import events_to_parquet_bytes, parquet_bytes_to_events
from src.auth_events.registry import RegistryCache, load_registry, reset_registry_cache, resolve_user
from src.auth_events.storage import LocalStorage, ObjectNotFound
from src.auth_events.writer import record_login, write_login_event

SEED = Path(__file__).resolve().parent.parent / "config" / "auth_registry"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A local store with the seed registry, wired as the app's configured storage."""
    monkeypatch.setenv("AUTH_EVENTS_LOCAL_DIR", str(tmp_path))
    monkeypatch.setenv("DEPLOY_STATUS", "POC")
    storage = LocalStorage(tmp_path)
    storage.put(settings.REGISTRY_CLIENTS_KEY, (SEED / "clients.json").read_bytes())
    storage.put(settings.REGISTRY_USERS_KEY, (SEED / "users.json").read_bytes())
    reset_registry_cache()
    data_access.clear_cache()
    yield storage
    reset_registry_cache()
    data_access.clear_cache()


def _event(username="cda_user", when="2026-11-05T15:00:00.000Z", event_id=None, env="production",
           user_type="client", client_id="cda"):
    moment = datetime.fromisoformat(when.replace("Z", "+00:00"))
    return build_event(username, user_type, client_id, env, moment=moment, event_id=event_id)


def _put_raw(storage, event):
    storage.put(raw_key(event), json.dumps(event).encode())


# --- capture ----------------------------------------------------------------------------

def test_event_has_every_schema_field_and_utc_timestamp(store):
    event = write_login_event("capstone_user", datetime(2026, 11, 10, 20, 30, 15, 123456, tzinfo=timezone.utc), "id-1")
    assert list(event) == ["schema_version", "event_id", "event_type", "timestamp_utc", "username",
                           "user_type", "client_id", "environment", "source"]
    assert event["timestamp_utc"] == "2026-11-10T20:30:15.123Z"
    assert event["schema_version"] == 1 and event["event_type"] == "login" and event["source"] == "live"
    assert (event["user_type"], event["client_id"]) == ("client", "capstone")


def test_raw_key_layout_and_single_object_per_login(store):
    event = write_login_event("cda_user", datetime(2026, 11, 10, 23, 59, 59, 5000, tzinfo=timezone.utc), "abc")
    assert raw_key(event) == "auth_events/raw/dt=2026-11-10/20261110T235959005Z_abc.json"
    assert store.list("auth_events/") == [raw_key(event)]


def test_unmapped_and_internal_users(store):
    ghost = write_login_event("ghost", datetime.now(timezone.utc), "g1")
    assert (ghost["user_type"], ghost["client_id"]) == ("unmapped", None)
    admin = write_login_event("admin", datetime.now(timezone.utc), "a1")
    assert (admin["user_type"], admin["client_id"]) == ("internal", None)


@pytest.mark.parametrize("deploy_status, expected", [
    ("POC", "production"), ("test", "development"), ("", "unknown"), ("staging", "unknown")])
def test_environment_comes_from_deployment_configuration(store, monkeypatch, deploy_status, expected):
    monkeypatch.setenv("DEPLOY_STATUS", deploy_status)
    event = write_login_event("cda_user", datetime.now(timezone.utc), "e1")
    assert event["environment"] == expected


def test_registry_never_loaded_means_unmapped(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_EVENTS_LOCAL_DIR", str(tmp_path))  # no registry files at all
    reset_registry_cache()
    event = write_login_event("cda_user", datetime.now(timezone.utc), "n1")
    assert (event["user_type"], event["client_id"]) == ("unmapped", None)
    reset_registry_cache()


def test_failed_reload_keeps_last_good_registry(store):
    clock = [0.0]
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("S3 down")
        return load_registry(store)

    cache = RegistryCache(loader=loader, ttl=10, clock=lambda: clock[0])
    first = cache.get()
    clock[0] = 11
    assert cache.get() is first          # reload failed -> last good copy
    assert resolve_user(first, "cda_user") == ("client", "cda")


def test_fifty_concurrent_logins_produce_fifty_distinct_objects(store):
    threads = [threading.Thread(target=write_login_event, args=("emin_user", datetime.now(timezone.utc), f"id-{i}"))
               for i in range(50)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(store.list(settings.RAW_PREFIX)) == 50


class _SpyStorage:
    def __init__(self, inner, fail_puts=0):
        self.inner, self.calls, self.fail_puts = inner, [], fail_puts

    def put(self, key, body, content_type="x"):
        self.calls.append(("put", key))
        if self.fail_puts:
            self.fail_puts -= 1
            raise OSError("S3 unavailable")
        self.inner.put(key, body)

    def get(self, key):
        self.calls.append(("get", key))
        return self.inner.get(key)

    def list(self, prefix):
        self.calls.append(("list", prefix))
        return self.inner.list(prefix)

    def delete(self, key):
        self.calls.append(("delete", key))
        self.inner.delete(key)


def test_login_path_only_puts_a_new_key_under_auth_events(store):
    spy = _SpyStorage(store)
    write_login_event("cda_user", datetime.now(timezone.utc), "spy-1", storage=spy)
    touching_events = [c for c in spy.calls if c[1].startswith("auth_events/")]
    assert [c[0] for c in touching_events] == ["put"]


def test_s3_down_logs_error_with_full_payload_after_three_retries(store, caplog):
    spy = _SpyStorage(store, fail_puts=99)
    sleeps = []
    with caplog.at_level(logging.ERROR):
        result = write_login_event("cda_user", datetime(2026, 11, 10, 1, 2, 3, tzinfo=timezone.utc), "fail-1",
                                   storage=spy, sleep=sleeps.append)
    assert result is None
    assert [c[0] for c in spy.calls if c[0] == "put"] == ["put"] * 4     # 1 try + 3 retries
    assert sleeps == [0.5, 1.0, 2.0]
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and '"event_id":"fail-1"' in errors[-1].getMessage().replace(" ", "")


def test_record_login_returns_without_waiting_for_the_store(store, monkeypatch):
    release = threading.Event()
    done = threading.Event()

    class Slow(_SpyStorage):
        def put(self, key, body, content_type="x"):
            release.wait(5)
            super().put(key, body)
            done.set()

    slow = Slow(store)
    monkeypatch.setattr("src.auth_events.writer.get_storage", lambda: slow)
    started = time.perf_counter()
    record_login("cda_user")
    assert time.perf_counter() - started < 0.5
    release.set()
    assert done.wait(5)


# --- compaction ---------------------------------------------------------------------------

def test_compaction_is_idempotent_and_picks_up_late_events(store):
    first = _event(event_id="e1", when="2026-11-01T10:00:00.000Z")
    second = _event(event_id="e2", when="2026-11-01T09:00:00.000Z")
    _put_raw(store, first)
    _put_raw(store, second)
    today = date(2026, 11, 10)

    compact(store, today=today, retention_days=30)
    snapshot = store.get(daily_key("2026-11-01"))
    compact(store, today=today, retention_days=30)
    assert store.get(daily_key("2026-11-01")) == snapshot                       # identical file
    assert [e["event_id"] for e in parquet_bytes_to_events(snapshot)] == ["e2", "e1"]  # sorted by time

    _put_raw(store, _event(event_id="e3", when="2026-11-01T23:00:00.000Z"))     # late arrival
    compact(store, today=today, retention_days=30)
    assert {e["event_id"] for e in parquet_bytes_to_events(store.get(daily_key("2026-11-01")))} == {"e1", "e2", "e3"}


def test_raw_objects_are_deleted_only_after_retention_and_verification(store):
    old, recent = _event(event_id="old", when="2026-10-01T10:00:00.000Z"), _event(event_id="new", when="2026-11-08T10:00:00.000Z")
    _put_raw(store, old)
    _put_raw(store, recent)
    compact(store, today=date(2026, 11, 10), retention_days=7)
    remaining = store.list(settings.RAW_PREFIX)
    assert remaining == [raw_key(recent)]                       # old one pruned, recent one kept
    assert store.get(daily_key("2026-10-01"))                   # ...because its daily file exists


def test_invalid_raw_object_is_reported_and_kept(store):
    store.put("auth_events/raw/dt=2026-10-01/20261001T000000000Z_bad.json", b"{not json")
    good = _event(event_id="ok", when="2026-10-01T10:00:00.000Z")
    _put_raw(store, good)
    report = compact(store, today=date(2026, 11, 10), retention_days=7)
    assert report.days[0].invalid_raw
    assert "auth_events/raw/dt=2026-10-01/20261001T000000000Z_bad.json" in store.list(settings.RAW_PREFIX)


# --- data-access layer --------------------------------------------------------------------

def test_event_in_raw_and_daily_is_returned_once(store):
    event = _event(event_id="dup", when="2026-11-05T15:00:00.000Z")
    store.put(daily_key("2026-11-05"), events_to_parquet_bytes([event]))
    _put_raw(store, event)
    events = data_access.get_events(date(2026, 11, 1), date(2026, 11, 10))
    assert list(events["event_id"]) == ["dup"]


def test_range_is_cut_in_the_display_timezone(store, monkeypatch):
    monkeypatch.setenv("AUTH_EVENTS_DISPLAY_TZ", "America/Santiago")   # UTC-3 in November (DST)
    late = _event(event_id="late", when="2026-11-06T01:30:00.000Z")     # 5 Nov 22:30 in Santiago
    early = _event(event_id="early", when="2026-11-06T03:30:00.000Z")   # 6 Nov 00:30 in Santiago
    _put_raw(store, late)
    _put_raw(store, early)
    day5 = data_access.get_events(date(2026, 11, 5), date(2026, 11, 5))
    day6 = data_access.get_events(date(2026, 11, 6), date(2026, 11, 6))
    assert list(day5["event_id"]) == ["late"] and list(day6["event_id"]) == ["early"]
    assert str(day5["timestamp"].iloc[0].tzinfo) == "America/Santiago"
    assert data_access.last_loaded_at() is not None


def test_environment_filter_and_full_history(store):
    _put_raw(store, _event(event_id="p", env="production"))
    _put_raw(store, _event(event_id="d", env="development", when="2026-10-01T00:00:00.000Z"))
    assert len(data_access.get_events()) == 2
    assert list(data_access.get_events(environment="development")["event_id"]) == ["d"]


def test_unavailable_when_no_storage(monkeypatch):
    monkeypatch.delenv("AUTH_EVENTS_LOCAL_DIR", raising=False)
    monkeypatch.delenv("BUCKET_NAME", raising=False)
    monkeypatch.setattr("src.auth_events.storage.load_dotenv", lambda *a, **k: None)
    data_access.clear_cache()
    with pytest.raises(data_access.AuthDataUnavailable):
        data_access.get_events()


def test_validate_event_rejects_bad_events():
    good = _event()
    assert validate_event(good)
    for broken in ({**good, "environment": "staging"}, {**good, "timestamp_utc": "yesterday"},
                   {k: v for k, v in good.items() if k != "username"}, {**good, "user_type": "robot"}):
        with pytest.raises(ValueError):
            validate_event(broken)


# --- migration -----------------------------------------------------------------------------

def _legacy_json(storage, name, **row):
    storage.put(f"{settings.LEGACY_S3_PREFIX}year=2026/month=10/day=01/{name}.json", json.dumps(row).encode())


def test_migration_preserves_counts_is_idempotent_and_archives(store):
    _legacy_json(store, "a", event_id="1", username="cda_user", timestamp="2026-10-01T10:00:00.000Z", deploy_status="POC")
    _legacy_json(store, "b", event_id="2", username="cda_user", timestamp="2026-10-02T10:00:00.000Z", deploy_status="unknown")
    _legacy_json(store, "c", event_id="3", username="ghost", timestamp="2026-10-02T11:00:00.000Z", deploy_status="test")
    _legacy_json(store, "d", event_id="4", username="admin", timestamp="", deploy_status="POC")        # no timestamp
    legacy_before = {k: store.get(k) for k in store.list(settings.LEGACY_S3_PREFIX)}

    report = migrate(store, apply=True)
    assert report.migrated == 4 and report.undated == 1
    assert dict(report.by_user) == {"cda_user": 2, "ghost": 1, "admin": 1}
    assert dict(report.by_environment) == {"production": 2, "unknown": 1, "development": 1}

    events = data_access.get_events()
    assert len(events) == 3                                       # undated row excluded from time views
    assert set(events["source"]) == {"legacy_migration"}
    ghost = events[events["username"] == "ghost"].iloc[0]
    assert ghost["user_type"] == "unmapped" and ghost["client_id"] is None
    legacy_partition = parquet_bytes_to_events(store.get("auth_events/daily/dt=legacy/events.parquet"))
    assert [e["username"] for e in legacy_partition] == ["admin"]

    snapshot = {k: store.get(k) for k in store.list(settings.DAILY_PREFIX)}
    migrate(store, apply=True)                                    # idempotent
    assert {k: store.get(k) for k in store.list(settings.DAILY_PREFIX)} == snapshot

    for key, body in legacy_before.items():                      # archived unchanged, originals kept
        assert store.get(f"{settings.LEGACY_PREFIX}{key}") == body and store.get(key) == body


def test_migration_dry_run_writes_nothing(store):
    _legacy_json(store, "a", event_id="1", username="cda_user", timestamp="2026-10-01T10:00:00.000Z", deploy_status="POC")
    report = migrate(store, apply=False)
    assert report.migrated == 1
    assert store.list("auth_events/") == [] or all(k.startswith(settings.LEGACY_S3_PREFIX) is False for k in store.list("auth_events/"))
    with pytest.raises(ObjectNotFound):
        store.get(daily_key("2026-10-01"))


def test_seed_registry_is_valid_and_maps_known_users():
    registry = load_registry(LocalStorage(SEED.parent) if False else _SeedStorage())
    assert resolve_user(registry, "capstone_user") == ("client", "capstone")
    assert resolve_user(registry, "admin") == ("internal", None)
    assert resolve_user(registry, "nobody") == ("unmapped", None)


class _SeedStorage:
    def get(self, key):
        return (SEED / key.rsplit("/", 1)[-1]).read_bytes()
