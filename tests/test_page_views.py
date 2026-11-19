"""TR-6: page-view capture (hook), batched writes, schema v2, compaction and the data-access layer."""

import json
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.auth_events import data_access, pageviews, settings
from src.auth_events.compaction import compact, daily_key
from src.auth_events.events import (
    InvalidEvent, batch_key, build_event, build_page_view_event, decode_batch, encode_batch, raw_key, validate_event,
)
from src.auth_events.pageviews import PageViewRecorder
from src.auth_events.parquet_io import events_to_parquet_bytes, parquet_bytes_to_events
from src.auth_events.registry import (
    RegistryCache, normalize_path, parse_pages, reset_registry_cache,
)
from src.auth_events.storage import LocalStorage

SEED = Path(__file__).resolve().parent.parent / "config" / "auth_registry"
UTC = timezone.utc


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_EVENTS_LOCAL_DIR", str(tmp_path))
    monkeypatch.setenv("DEPLOY_STATUS", "POC")
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEWS", "1")
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_WINDOW", "always")   # tests run at any hour; the window has its own test
    storage = LocalStorage(tmp_path)
    storage.put(settings.REGISTRY_CLIENTS_KEY, (SEED / "clients.json").read_bytes())
    storage.put(settings.REGISTRY_USERS_KEY, (SEED / "users.json").read_bytes())
    storage.put(settings.REGISTRY_PAGES_KEY, (SEED / "pages.json").read_bytes())
    reset_registry_cache()
    data_access.clear_cache()
    yield storage
    reset_registry_cache()
    data_access.clear_cache()


def recorder_for(storage, **kwargs):
    return PageViewRecorder(storage_factory=lambda: storage, sleep=lambda s: None, **kwargs)


def _batches(storage):
    return sorted(k for k in storage.list(settings.RAW_PREFIX) if k.endswith(".jsonl"))


def _events_in(storage, keys=None):
    out = []
    for key in keys if keys is not None else _batches(storage):
        events, rejected = decode_batch(storage.get(key))
        assert not rejected
        out.extend(events)
    return out


def _view(username="cda_user", when="2026-11-05T15:00:00.000Z", path="/monitoring/alerts", tab="general",
          page_id="monitoreo.alertas.general", event_id=None):
    moment = datetime.fromisoformat(when.replace("Z", "+00:00"))
    return build_page_view_event(username, "client", "cda", "production", page_id, path, tab, moment=moment, event_id=event_id)


def _login(when="2026-11-05T15:00:00.000Z", event_id=None, username="cda_user"):
    moment = datetime.fromisoformat(when.replace("Z", "+00:00"))
    return build_event(username, "client", "cda", "production", moment=moment, event_id=event_id)


# --- schema v2 --------------------------------------------------------------------------------

def test_page_view_event_has_the_v2_fields():
    event = _view(event_id="e1")
    assert list(event) == ["schema_version", "event_id", "event_type", "timestamp_utc", "username", "user_type",
                           "client_id", "environment", "source", "page_id", "path", "tab"]
    assert event["schema_version"] == 2 and event["event_type"] == "page_view"
    assert validate_event(event)["tab"] == "general"


def test_login_stays_a_version_1_object_and_reads_back_with_null_page_columns():
    login = _login(event_id="l1")
    assert login["schema_version"] == 1 and "page_id" not in login and len(login) == 9
    clean = validate_event(login)
    assert (clean["page_id"], clean["path"], clean["tab"]) == (None, None, None) and clean["schema_version"] == 1


@pytest.mark.parametrize("field", ["page_id", "path"])
def test_page_view_without_page_id_or_path_is_rejected(field):
    event = _view()
    event[field] = None
    with pytest.raises(InvalidEvent):
        validate_event(event)
    event[field] = ""
    with pytest.raises(InvalidEvent):
        validate_event(event)


def test_unknown_event_type_is_rejected():
    event = _view()
    event["event_type"] = "click"
    with pytest.raises(InvalidEvent):
        validate_event(event)


def test_batch_codec_keeps_good_lines_and_reports_bad_ones():
    good, bad = _view(event_id="g"), _view(event_id="b")
    bad["path"] = None
    data = encode_batch([good]) + json.dumps(bad).encode() + b"\n" + b"not json\n"
    events, rejected = decode_batch(data)
    assert [e["event_id"] for e in events] == ["g"] and len(rejected) == 2


def test_batch_key_layout():
    key = batch_key("2026-11-10", datetime(2026, 11, 10, 23, 59, 59, 5000, tzinfo=UTC), "abc123")
    assert key == "auth_events/raw/dt=2026-11-10/pv_20261110T235959005Z_abc123.jsonl"


# --- pages registry ---------------------------------------------------------------------------

def test_normalize_path_drops_query_fragment_and_trailing_slash():
    assert normalize_path("/monitoring/alerts/?client=cda#x") == "/monitoring/alerts"
    assert normalize_path("monitoring/alerts") == "/monitoring/alerts" and normalize_path("") == "/" and normalize_path("/") == "/"


def test_pages_registry_matches_on_path_and_tab_and_resolves_names():
    pages = parse_pages(SEED.joinpath("pages.json").read_bytes())
    assert pages.match("/monitoring/alerts", "general")["page_id"] == "monitoreo.alertas.general"
    assert pages.match("/monitoring/alerts/", "detail")["page_id"] == "monitoreo.alertas.detalle"
    assert pages.match("/monitoring/alerts", "nope") is None and pages.match("/monitoring/alerts", None) is None
    assert pages.match("/overview/unit/FLOTA-1", None)["page_id"] == "overview.unit"      # <unit_id> template
    assert pages.match("/overview/general", None)["page_id"] == "overview.general"
    assert pages.display_name("monitoreo.alertas.general") == "Alertas › Vista General"
    assert pages.display_name("unregistered", "/x/y", None) == "/x/y"
    assert pages.display_name("unregistered", "/x/y", "tab1") == "/x/y › tab1"


def test_pages_registry_keeps_the_last_good_copy_like_users_json():
    state = {"fail": False}

    def loader():
        if state["fail"]:
            raise RuntimeError("s3 down")
        return parse_pages(b'[{"page_id":"a","display_name":"A","path":"/a","tab":null}]')

    clock = {"now": 0.0}
    cache = RegistryCache(loader=loader, ttl=10, clock=lambda: clock["now"])
    first = cache.get()
    state["fail"] = True
    clock["now"] = 11
    assert cache.get() is first                       # reload failed: last good copy kept


def test_invalid_pages_file_is_rejected():
    with pytest.raises(ValueError):
        parse_pages(b'[{"page_id":"a"}]')


# --- recorder: buffering, batching, flush -----------------------------------------------------

def test_record_adds_no_storage_call_and_no_thread_work_in_the_request(store):
    calls = []

    class Spy(LocalStorage):
        def put(self, *a, **k):
            calls.append("put")
            super().put(*a, **k)

        def get(self, *a, **k):
            calls.append("get")
            return super().get(*a, **k)

        def list(self, *a, **k):
            calls.append("list")
            return super().list(*a, **k)

    rec = PageViewRecorder(storage_factory=lambda: Spy(store.root), sleep=lambda s: None)
    started = time.perf_counter()
    assert rec.record("cda_user", "/monitoring/alerts?client=cda", "general") is True
    assert time.perf_counter() - started < 0.05 and calls == []
    rec.shutdown()


def test_disabled_capture_records_nothing_and_starts_no_thread(store, monkeypatch):
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEWS", "")
    rec = recorder_for(store)
    assert rec.record("cda_user", "/monitoring/alerts", "general") is False
    assert rec.pending() == 0 and rec._thread is None and rec.flush() == [] and _batches(store) == []


def test_flush_writes_one_jsonl_with_resolved_fields(store):
    rec = recorder_for(store)
    rec.record("cda_user", "/monitoring/alerts/?client=cda", "general")
    rec.record("admin", "/admin/actividad-usuarios", None)
    rec.record("ghost", "/never/registered", "t")
    keys = rec.flush()
    assert len(keys) == 1 and re.fullmatch(r"auth_events/raw/dt=\d{4}-\d{2}-\d{2}/pv_\d{8}T\d{9}Z_[0-9a-f]{12}\.jsonl", keys[0])
    by_user = {e["username"]: e for e in _events_in(store, keys)}
    cda = by_user["cda_user"]
    assert (cda["page_id"], cda["path"], cda["tab"]) == ("monitoreo.alertas.general", "/monitoring/alerts", "general")
    assert (cda["user_type"], cda["client_id"], cda["environment"], cda["event_type"]) == ("client", "cda", "production", "page_view")
    assert cda["timestamp_utc"].endswith("Z")
    assert (by_user["admin"]["user_type"], by_user["admin"]["client_id"], by_user["admin"]["page_id"]) == ("internal", None, "admin.actividad")
    ghost = by_user["ghost"]
    assert (ghost["page_id"], ghost["path"], ghost["tab"], ghost["user_type"]) == ("unregistered", "/never/registered", "t", "unmapped")
    assert rec.pending() == 0 and rec.flush() == []


def test_only_username_page_path_and_tab_are_stored(store):
    rec = recorder_for(store)
    rec.record("cda_user", "/monitoring/alerts?period=7&client=cda#frag", "general")
    (event,) = _events_in(store, rec.flush())
    assert "period=7" not in json.dumps(event) and "frag" not in json.dumps(event)
    assert set(event) == {"schema_version", "event_id", "event_type", "timestamp_utc", "username", "user_type",
                          "client_id", "environment", "source", "page_id", "path", "tab"}


def test_same_user_same_page_within_the_window_is_one_view(store):
    clock = {"t": 100.0}
    rec = PageViewRecorder(storage_factory=lambda: store, sleep=lambda s: None, monotonic=lambda: clock["t"])
    assert rec.record("cda_user", "/monitoring/alerts", "general") is True
    clock["t"] += 1.0
    assert rec.record("cda_user", "/monitoring/alerts", "general") is False      # several callbacks, one navigation
    assert rec.record("cda_user", "/monitoring/alerts", "detail") is True        # another tab: not a duplicate
    assert rec.record("emin_user", "/monitoring/alerts", "general") is True      # another user
    clock["t"] += 2.5
    assert rec.record("cda_user", "/monitoring/alerts", "general") is True       # window over
    assert rec.pending() == 4


def test_flush_spanning_utc_midnight_writes_one_object_per_date(store):
    rec = recorder_for(store)
    before, after = datetime(2026, 11, 5, 23, 59, 59, tzinfo=UTC), datetime(2026, 11, 6, 0, 0, 1, tzinfo=UTC)
    for moment, path in ((before, "/a"), (after, "/b")):
        rec._buffer.append({"event_id": path, "moment": moment, "username": "cda_user", "path": path, "tab": None,
                            "environment": "production"})
    keys = rec.flush()
    assert len(keys) == 2 and {k.split("/")[2] for k in keys} == {"dt=2026-11-05", "dt=2026-11-06"}
    for key in keys:
        day = key.split("dt=")[1][:10]
        assert all(e["timestamp_utc"].startswith(day) for e in _events_in(store, [key]))


def test_buffer_flushes_when_it_reaches_the_batch_size(store, monkeypatch):
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_SIZE", "5")
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_SECONDS", "3600")
    rec = recorder_for(store)
    for i in range(5):
        rec.record("cda_user", f"/p{i}", None)
    _wait_for(lambda: len(_events_in(store)) == 5)
    assert rec.pending() == 0
    rec.shutdown()


def test_buffer_flushes_on_the_interval(store, monkeypatch):
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_SIZE", "1000")
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_SECONDS", "0.1")
    rec = recorder_for(store)
    rec.record("cda_user", "/p", None)
    _wait_for(lambda: len(_events_in(store)) == 1)
    rec.shutdown()


def test_defaults_are_a_20_minute_flush_inside_07_to_22(monkeypatch):
    monkeypatch.delenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_SECONDS", raising=False)
    monkeypatch.delenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_WINDOW", raising=False)
    assert settings.page_view_flush_seconds() == 1200 and settings.page_view_flush_window() == (420, 1320)
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_WINDOW", "always")
    assert settings.page_view_flush_window() is None
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_WINDOW", "6:30-23:00")
    assert settings.page_view_flush_window() == (390, 1380)
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_WINDOW", "garbage")
    assert settings.page_view_flush_window() == (420, 1320)


@pytest.mark.parametrize("hour, minute, inside", [(6, 59, False), (7, 0, True), (12, 0, True), (21, 59, True), (22, 0, False), (23, 30, False), (3, 0, False)])
def test_flush_window_is_checked_in_the_display_timezone(store, monkeypatch, hour, minute, inside):
    from zoneinfo import ZoneInfo
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_WINDOW", "07:00-22:00")
    rec = PageViewRecorder(storage_factory=lambda: store, clock=lambda: datetime(2026, 11, 19, hour, minute, tzinfo=ZoneInfo("America/Santiago")))
    assert rec.in_flush_window() is inside


def test_views_recorded_outside_the_window_wait_and_shutdown_still_flushes_them(store, monkeypatch):
    from zoneinfo import ZoneInfo
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_WINDOW", "07:00-22:00")
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_SECONDS", "0.05")
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_SIZE", "1")
    night = {"on": True}
    rec = PageViewRecorder(storage_factory=lambda: store, sleep=lambda s: None, clock=lambda: datetime(
        2026, 11, 19, 23 if night["on"] else 9, 0, tzinfo=ZoneInfo("America/Santiago")))
    rec.record("cda_user", "/p", None)
    time.sleep(0.4)                                   # several timer ticks and a size trigger, all at 23:00
    assert _batches(store) == [] and rec.pending() == 1
    night["on"] = False                               # 09:00: the next tick writes it
    _wait_for(lambda: len(_events_in(store)) == 1)
    night["on"] = True
    rec.record("cda_user", "/q", None)
    rec.shutdown()                                    # shutdown ignores the window
    assert len(_events_in(store)) == 2


def test_graceful_shutdown_flushes_what_is_buffered(store, monkeypatch):
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_SECONDS", "3600")
    rec = recorder_for(store)
    rec.record("cda_user", "/p", None)
    assert _batches(store) == []
    rec.shutdown()
    assert len(_events_in(store)) == 1


def _wait_for(condition, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def test_unavailable_storage_never_blocks_logs_the_payload_and_bounds_the_buffer(store, monkeypatch, caplog):
    attempts = []

    class Down(LocalStorage):
        def put(self, *a, **k):
            attempts.append(1)
            raise ConnectionError("s3 unreachable")

    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_SECONDS", "3600")
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_BUFFER_CAP", "4")
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEW_FLUSH_SIZE", "1000")
    rec = PageViewRecorder(storage_factory=lambda: Down(store.root), sleep=lambda s: None)
    with caplog.at_level(logging.ERROR):
        for i in range(7):
            assert rec.record("cda_user", f"/page{i}", None) is True       # navigation is never refused
        assert rec.pending() == 4                                          # cap: the 3 oldest were dropped
        dropped = [int(m.group(1)) for r in caplog.records if (m := re.search(r"dropped the (\d+) oldest", r.getMessage()))]
        assert sum(dropped) == 3
        caplog.clear()
        assert rec.flush() == []
    assert len(attempts) == 4                                              # first try + 3 retries
    message = next(r.getMessage() for r in caplog.records if "NOT stored after 3 retries" in r.getMessage())
    assert "/page6" in message and '"event_type":"page_view"' in message   # full payload, replayable
    assert rec.pending() == 0
    rec.shutdown()


def test_a_flush_that_recovers_on_retry_loses_nothing(store):
    state = {"fail": 2}

    class Flaky(LocalStorage):
        def put(self, *a, **k):
            if state["fail"]:
                state["fail"] -= 1
                raise ConnectionError("blip")
            super().put(*a, **k)

    rec = PageViewRecorder(storage_factory=lambda: Flaky(store.root), sleep=lambda s: None)
    rec.record("cda_user", "/p", None)
    assert len(rec.flush()) == 1 and len(_events_in(store)) == 1


def test_concurrent_flushes_from_several_workers_produce_distinct_objects_and_lose_nothing(store):
    workers = [recorder_for(store) for _ in range(4)]
    for w, rec in enumerate(workers):
        for i in range(50):
            rec.record(f"cda_user", f"/w{w}/p{i}", None)
    threads = [threading.Thread(target=rec.flush) for rec in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    keys = _batches(store)
    events = _events_in(store)
    assert len(keys) == len(set(keys)) == 4
    assert len(events) == len({e["event_id"] for e in events}) == 200


def test_login_capture_is_unchanged(store):
    from src.auth_events.writer import write_login_event
    event = write_login_event("cda_user", datetime(2026, 11, 10, 20, 30, 15, tzinfo=UTC), "id-1")
    assert len(event) == 9 and event["schema_version"] == 1
    assert store.list("auth_events/") == [raw_key(event)] and json.loads(store.get(raw_key(event))) == event


# --- compaction --------------------------------------------------------------------------------

TODAY = date(2026, 11, 20)


def _put_batch(storage, events, day="2026-11-05", batch="b1"):
    storage.put(batch_key(day, datetime(2026, 11, 5, 16, 0, tzinfo=UTC), batch), encode_batch(events))


def _daily(storage, day="2026-11-05"):
    return storage.get(daily_key(day))


def test_compaction_merges_logins_and_page_views_into_a_v2_file_and_is_idempotent(store):
    login = _login(event_id="l1")
    store.put(raw_key(login), json.dumps(login).encode())
    _put_batch(store, [_view(event_id="p1", when="2026-11-05T15:01:00.000Z"), _view(event_id="p2", when="2026-11-05T15:02:00.000Z")])
    report = compact(store, today=TODAY, retention_days=30)
    assert report.ok and report.days[0].rows == 3 and report.days[0].wrote
    table = pq.read_table(pa.BufferReader(_daily(store)))
    assert {"page_id", "path", "tab"} <= set(table.column_names)
    events = parquet_bytes_to_events(_daily(store))
    assert [e["event_type"] for e in events] == ["login", "page_view", "page_view"]
    assert events[0]["page_id"] is None and events[1]["path"] == "/monitoring/alerts"
    first = _daily(store)
    again = compact(store, today=TODAY, retention_days=30)
    assert not again.days[0].wrote and _daily(store) == first


def test_a_late_batch_is_included_by_the_next_run(store):
    _put_batch(store, [_view(event_id="p1")], batch="b1")
    compact(store, today=date(2026, 11, 6), retention_days=7)
    _put_batch(store, [_view(event_id="p2", when="2026-11-05T22:00:00.000Z")], batch="b2")
    assert compact(store, today=date(2026, 11, 6), retention_days=7).days[0].new_events == 1
    assert {e["event_id"] for e in parquet_bytes_to_events(_daily(store))} == {"p1", "p2"}


def test_recompacting_a_v1_day_adds_the_new_columns_as_null_and_keeps_every_login(store):
    v1_schema = pa.schema([("schema_version", pa.int64()), ("event_id", pa.string()), ("event_type", pa.string()),
                           ("timestamp_utc", pa.timestamp("ms", tz="UTC")), ("username", pa.string()),
                           ("user_type", pa.string()), ("client_id", pa.string()), ("environment", pa.string()),
                           ("source", pa.string())])
    logins = [_login(event_id=f"l{i}", when=f"2026-11-05T1{i}:00:00.000Z") for i in range(3)]
    rows = {name: [e[name] if name != "timestamp_utc" else datetime.fromisoformat(e[name].replace("Z", "+00:00")) for e in logins]
            for name in v1_schema.names}
    import io
    sink = io.BytesIO()
    pq.write_table(pa.table(rows, schema=v1_schema), sink)
    store.put(daily_key("2026-11-05"), sink.getvalue())
    store.put(raw_key(logins[0]), json.dumps(logins[0]).encode())          # a raw object keeps the day in scope
    assert "page_id" not in pq.read_table(pa.BufferReader(_daily(store))).column_names
    report = compact(store, today=TODAY, retention_days=7)
    assert report.days[0].wrote and report.days[0].rows == 3
    table = pq.read_table(pa.BufferReader(_daily(store)))
    assert {"page_id", "path", "tab"} <= set(table.column_names)
    assert table.column("page_id").null_count == 3 and sorted(table.column("event_id").to_pylist()) == ["l0", "l1", "l2"]


def test_invalid_page_view_lines_are_rejected_logged_and_their_object_kept(store, caplog):
    bad = _view(event_id="bad")
    bad["path"] = None
    good = _view(event_id="good")
    store.put(batch_key("2026-11-05", datetime(2026, 11, 5, 16, 0, tzinfo=UTC), "b1"),
              encode_batch([good]) + json.dumps(bad).encode() + b"\n")
    with caplog.at_level(logging.WARNING):
        report = compact(store, today=date(2026, 12, 31), retention_days=7)
    day = report.days[0]
    assert day.new_events == 1 and len(day.invalid_raw) == 1 and day.raw_deleted == 0      # kept for inspection
    assert [e["event_id"] for e in parquet_bytes_to_events(_daily(store))] == ["good"]
    assert any("invalid event" in r.getMessage() for r in caplog.records)


def test_raw_objects_are_deleted_after_retention_only_when_verified_for_both_types(store):
    login = _login(event_id="l1")
    store.put(raw_key(login), json.dumps(login).encode())
    _put_batch(store, [_view(event_id="p1")])
    report = compact(store, today=date(2026, 11, 20), retention_days=7)
    assert report.days[0].raw_deleted == 2 and store.list(settings.RAW_PREFIX) == []
    assert len(parquet_bytes_to_events(_daily(store))) == 2
    # inside the retention window nothing is deleted
    other = _login(event_id="l2", when="2026-11-18T10:00:00.000Z")
    store.put(raw_key(other), json.dumps(other).encode())
    assert compact(store, today=date(2026, 11, 20), retention_days=7).days[0].raw_deleted == 0


def test_settled_days_do_not_reread_every_batch(store):
    class Counting(LocalStorage):
        gets = 0

        def get(self, key):
            if key.endswith(".jsonl"):
                Counting.gets += 1
            return super().get(key)

    spy = Counting(store.root)
    _put_batch(store, [_view(event_id="p1")])
    compact(spy, today=date(2026, 11, 10), retention_days=7)          # day is 5 days old: first run reads it
    reads = Counting.gets
    assert reads >= 1
    compact(spy, today=date(2026, 11, 10), retention_days=7)          # outside the recompaction window, not yet prunable
    assert Counting.gets == reads


# --- data-access layer --------------------------------------------------------------------------

def _seed_mixed(storage):
    _put_batch(storage, [_view(event_id="p1"), _view(event_id="p2", path="/somewhere", tab="x", page_id="unregistered")],
               day="2026-11-05")
    login = _login(event_id="l1")
    storage.put(raw_key(login), json.dumps(login).encode())
    data_access.clear_cache()


def test_data_access_returns_both_types_by_default_and_can_filter(store):
    _seed_mixed(store)
    both = data_access.get_events()
    assert sorted(both["event_type"].unique()) == ["login", "page_view"] and len(both) == 3
    assert len(data_access.get_events(event_types="login")) == 1
    assert len(data_access.get_events(event_types=["page_view"])) == 2
    assert len(data_access.get_events(date(2026, 11, 5), date(2026, 11, 5), "production")) == 3
    with pytest.raises(ValueError):
        data_access.get_events(event_types="click")


def test_data_access_resolves_display_names_at_read_time_and_unregistered_by_path(store):
    _seed_mixed(store)
    views = data_access.get_events(event_types="page_view").set_index("event_id")
    assert views.loc["p1", "display_name"] == "Alertas › Vista General"
    assert views.loc["p2", "display_name"] == "/somewhere › x"
    assert data_access.get_events(event_types="login")["display_name"].isna().all()
    # renaming a page changes the display, not the stored events
    pages = json.loads((SEED / "pages.json").read_text(encoding="utf-8"))
    for page in pages:
        if page["page_id"] == "monitoreo.alertas.general":
            page["display_name"] = "Alertas › Resumen"
    store.put(settings.REGISTRY_PAGES_KEY, json.dumps(pages).encode())
    reset_registry_cache()
    data_access.clear_cache()
    renamed = data_access.get_events(event_types="page_view").set_index("event_id")
    assert renamed.loc["p1", "display_name"] == "Alertas › Resumen" and renamed.loc["p1", "page_id"] == "monitoreo.alertas.general"


def test_data_access_exposes_capture_start_and_the_pages_registry(store):
    store.put(raw_key(_login(event_id="l0", when="2026-10-01T10:00:00.000Z")), json.dumps(_login(event_id="l0", when="2026-10-01T10:00:00.000Z")).encode())
    data_access.clear_cache()
    assert data_access.page_view_capture_start() is None                  # logins alone: no capture yet
    _put_batch(store, [_view(event_id="p1", when="2026-11-05T15:00:00.000Z"), _view(event_id="p0", when="2026-11-02T12:00:00.000Z")],
               day="2026-11-05")
    _put_batch(store, [_view(event_id="p0", when="2026-11-02T12:00:00.000Z")], day="2026-11-02", batch="b0")
    data_access.clear_cache()
    assert data_access.page_view_capture_start() == date(2026, 11, 2)
    assert data_access.get_pages().by_id("admin.mailing")["path"] == "/admin/mailing"


def test_data_access_without_a_pages_file_shows_paths_instead_of_failing(store):
    store.delete(settings.REGISTRY_PAGES_KEY)
    reset_registry_cache()
    _seed_mixed(store)
    views = data_access.get_events(event_types="page_view").set_index("event_id")
    assert views.loc["p1", "display_name"] == "/monitoring/alerts › general"
    assert data_access.get_pages().pages == ()


def test_v1_only_history_still_reads_with_null_page_columns(store):
    login = _login(event_id="l1")
    store.put(raw_key(login), json.dumps(login).encode())
    frame = data_access.get_events()
    assert len(frame) == 1 and frame["page_id"].isna().all() and frame["tab"].isna().all()


# --- the Dash hook ------------------------------------------------------------------------------

from dashboard import page_view_capture as hook  # noqa: E402


def _payload(output, changed, inputs):
    return {"output": output, "outputs": [], "changedPropIds": changed,
            "inputs": [{"id": i, "property": p, "value": v} for i, p, v in inputs]}


def _pages(pathname="/monitoring/alerts", search="", changed=("_pages_location.pathname",)):
    return _payload("..%s.._pages_store.data.." % hook.PAGES_OUTPUT, list(changed),
                    [("_pages_location", "pathname", pathname), ("_pages_location", "search", search)])


def _tab(component="alerts-internal-tabs", value="detail", changed=None):
    return _payload("alerts-tab-content.children", changed or [f"{component}.value"], [(component, "value", value), ("client-selector", "value", "cda")])


def test_opening_a_page_is_one_view_with_its_default_tab():
    assert hook.detect_view(_pages("/monitoring/alerts"), None) == ("/monitoring/alerts", "general")
    assert hook.detect_view(_pages("/overview/general"), None) == ("/overview/general", None)
    assert hook.detect_view(_pages("/predictive/motor"), None) == ("/predictive/motor", "resumen")
    assert hook.detect_view(_pages("/monitoring/alerts/", "?client=cda"), None) == ("/monitoring/alerts", "general")


def test_a_query_string_only_change_is_not_a_page_opening():
    assert hook.detect_view(_pages(changed=["_pages_location.search"]), None) is None
    assert hook.detect_view(_pages(changed=["_pages_location.search", "_pages_location.hash"]), None) is None


def test_deployment_prefix_root_and_redirect_routes_are_handled():
    assert hook.detect_view(_pages("/alerts-dashboard/monitoring/alerts"), None, "/alerts-dashboard/") == ("/monitoring/alerts", "general")
    assert hook.detect_view(_pages("/"), None) is None
    assert hook.detect_view(_pages("/alerts-dashboard/"), None, "/alerts-dashboard/") is None
    assert hook.detect_view(_pages("/admin/registro-usuarios"), None) is None        # only redirects to the new route


def test_tab_openings_need_a_changed_tab_value_from_the_owning_page():
    assert hook.detect_view(_tab(value="detail"), "/monitoring/alerts") == ("/monitoring/alerts", "detail")
    assert hook.detect_view(_tab(value="general"), "/monitoring/alerts") == ("/monitoring/alerts", "general")   # return to a visited tab
    assert hook.detect_view(_tab("predictive-component-internal-tabs", "evidencia"), "/predictive/transmision") == ("/predictive/transmision", "evidencia")
    assert hook.detect_view(_tab(value="detail"), None) is None
    assert hook.detect_view(_tab(value="detail"), "/monitoring/oil") is None                      # not that page's tab strip
    assert hook.detect_view(_tab("not-watched-tabs", "x"), "/monitoring/alerts") is None


@pytest.mark.parametrize("payload", [
    _payload("alerts-tab-content.children", ["alerts-filter-store.data"], [("alerts-internal-tabs", "value", "general")]),   # a filter changed
    _payload("x.children", ["interval.n_intervals"], [("interval", "n_intervals", 3)]),                                       # dcc.Interval
    _payload("x.children", ["some-button.n_clicks"], [("some-button", "n_clicks", 1)]),                                       # a click inside a page
    _payload("x.children", [], []),                                                                                          # initial call
    None, [], "garbage",
])
def test_filters_intervals_clicks_and_junk_are_never_views(payload):
    assert hook.detect_view(payload, "/monitoring/alerts") is None


def test_payload_nested_inputs_and_states_are_understood():
    payload = _tab(value="detail")
    payload["state"] = [[{"id": "x", "property": "y", "value": 1}]]
    payload["inputs"] = [payload["inputs"]]                         # Dash can nest inputs per callback argument
    assert hook.detect_view(payload, "/monitoring/alerts") == ("/monitoring/alerts", "detail")


@pytest.fixture
def client(store, monkeypatch):
    from flask import Flask, session

    app = Flask(__name__)
    app.secret_key = "test"
    app.before_request(hook.capture_page_view)

    @app.route("/_dash-update-component", methods=["POST"])
    def update():
        return "ok"

    @app.route("/assets/app.js")
    def asset():
        return "js"

    monkeypatch.setattr(hook, "resolve_authenticated_username", lambda user_data=None: session.get("dashboard_user"))
    monkeypatch.setattr(hook, "is_admin", lambda username: username == "admin")
    rec = pageviews.set_recorder_for_tests(PageViewRecorder(storage_factory=lambda: store, sleep=lambda s: None))
    test_client = app.test_client()
    yield test_client, rec
    rec.shutdown()
    pageviews.set_recorder_for_tests(None)


def _sign_in(test_client, username):
    with test_client.session_transaction() as sess:
        sess["dashboard_user"] = username


def test_hook_records_exactly_one_view_per_opening_for_a_signed_in_user(client, store):
    test_client, rec = client
    _sign_in(test_client, "cda_user")
    assert test_client.post("/_dash-update-component", json=_pages()).status_code == 200
    test_client.post("/_dash-update-component", json=_pages())                       # a second callback, same navigation
    test_client.post("/_dash-update-component", json=_tab(value="detail"),
                     headers={"Referer": "http://x/monitoring/alerts?client=cda"})
    test_client.post("/_dash-update-component", json=_payload("x.children", ["f.value"], [("f", "value", 1)]))   # filter
    (key,) = rec.flush()
    events = _events_in(store, [key])
    assert [(e["path"], e["tab"], e["username"], e["page_id"]) for e in events] == [
        ("/monitoring/alerts", "general", "cda_user", "monitoreo.alertas.general"),
        ("/monitoring/alerts", "detail", "cda_user", "monitoreo.alertas.detalle")]


def test_hook_ignores_anonymous_requests_assets_and_get_requests(client, store):
    test_client, rec = client
    test_client.post("/_dash-update-component", json=_pages())                        # not signed in
    _sign_in(test_client, "cda_user")
    assert test_client.get("/assets/app.js").status_code == 200
    assert rec.pending() == 0


def test_hook_does_nothing_when_capture_is_off_and_never_breaks_a_request(client, store, monkeypatch):
    test_client, rec = client
    _sign_in(test_client, "cda_user")
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEWS", "0")
    test_client.post("/_dash-update-component", json=_pages())
    assert rec.pending() == 0 and rec._thread is None
    monkeypatch.setenv("AUTH_EVENTS_PAGE_VIEWS", "1")
    assert test_client.post("/_dash-update-component", data="{not json", content_type="application/json").status_code == 200
    monkeypatch.setattr(hook, "record_page_view", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert test_client.post("/_dash-update-component", json=_pages()).status_code == 200     # best-effort: still served


def test_non_admins_do_not_record_admin_pages_but_admins_do(client, store):
    test_client, rec = client
    _sign_in(test_client, "cda_user")
    test_client.post("/_dash-update-component", json=_pages("/admin/actividad-usuarios"))
    assert rec.pending() == 0
    _sign_in(test_client, "admin")
    test_client.post("/_dash-update-component", json=_pages("/admin/actividad-usuarios"))     # recorded like any other page
    (event,) = _events_in(store, rec.flush())
    assert (event["page_id"], event["user_type"]) == ("admin.actividad", "internal")
