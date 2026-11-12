"""TR-2 / TR-3 calculations: periods, change chips, Último Acceso, overview, client detail."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.auth_events import metrics as m
from src.auth_events.data_access import _frame
from src.auth_events.events import build_event
from src.auth_events.registry import parse_registry

TZ = "America/Santiago"
CLIENTS = (b'[{"client_id":"cda","display_name":"CDA","active":true},'
           b'{"client_id":"emin","display_name":"Emin","active":true},'
           b'{"client_id":"old","display_name":"Old","active":false}]')
USERS = (b'[{"username":"cda_user","user_type":"client","client_id":"cda"},'
         b'{"username":"cda_idle","user_type":"client","client_id":"cda"},'
         b'{"username":"emin_user","user_type":"client","client_id":"emin"},'
         b'{"username":"admin","user_type":"internal"}]')
REGISTRY = parse_registry(CLIENTS, USERS)
TODAY = date(2026, 11, 10)


def frame(*specs):
    """specs: (username, user_type, client_id, 'YYYY-MM-DD HH:MM' local time, environment)."""
    events = []
    for i, (username, user_type, client_id, local, env) in enumerate(specs):
        moment = datetime.strptime(local, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(TZ)).astimezone(timezone.utc)
        events.append(build_event(username, user_type, client_id, env, moment=moment, event_id=f"e{i}"))
    return _frame(events, TZ)


def test_period_defaults_and_previous():
    p = m.resolve_period(None, TODAY)
    assert (p.start, p.end, p.days) == (date(2026, 10, 12), TODAY, 30)
    prev = p.previous
    assert (prev.start, prev.end) == (date(2026, 9, 12), date(2026, 10, 11))
    assert m.resolve_period("7", TODAY).days == 7
    custom = m.resolve_period("custom", TODAY, "2026-11-01", "2026-11-05")
    assert (custom.start, custom.end, custom.days) == (date(2026, 11, 1), date(2026, 11, 5), 5)
    assert m.resolve_period("custom", TODAY, "2026-11-09", "2026-11-01").days == 30   # invalid -> default


@pytest.mark.parametrize("cur, prev, kind, text", [
    (5, 0, "new", "Nuevo"), (0, 0, "none", "–"), (10, 10, "zero", "0,0%"),
    (113, 100, "up", "▲ +13,0%"), (1046, 1000, "up", "▲ +4,6%"), (957, 1000, "down", "▼ −4,3%"),
    (0, 4, "down", "▼ −100,0%"),
])
def test_change_chip_rules(cur, prev, kind, text):
    change = m.change_vs_previous(cur, prev)
    assert (change.kind, change.text) == (kind, text)


def test_es_cl_number_formatting():
    assert m.fmt_int(1450) == "1.450" and m.fmt_int(0) == "0" and m.fmt_int(1234567) == "1.234.567"
    assert m.fmt_decimal(13.1) == "13,1" and m.fmt_decimal(1234.5) == "1.234,5"
    assert m.fmt_pct_int(12.5) == "13%" and m.fmt_pct_int(0.4) == "0%"


def test_relative_access_formats():
    tz = ZoneInfo(TZ)
    now = datetime(2026, 11, 10, 15, 0, tzinfo=tz)
    assert m.relative_access(None, now) == "Sin accesos"
    assert m.relative_access(now - timedelta(minutes=5), now) == "Hace 5 min"
    assert m.relative_access(now - timedelta(hours=3), now) == "Hace 3 h"
    assert m.relative_access(datetime(2026, 11, 9, 8, 5, tzinfo=tz) - timedelta(hours=0), now) == "Ayer, 08:05"
    assert m.relative_access(datetime(2026, 11, 6, 16, 12, tzinfo=tz), now) == "Hace 4 días"
    assert m.fmt_weekday_datetime(datetime(2026, 11, 6, 16, 12, tzinfo=tz)) == "Vie 6 Nov, 16:12"
    assert m.fmt_datetime(datetime(2026, 11, 6, 16, 12, tzinfo=tz)) == "6 Nov 2026, 16:12"


def test_buckets_daily_and_weekly():
    daily = m.build_buckets(m.Period(date(2026, 11, 1), date(2026, 11, 10)))
    assert len(daily) == 10 and daily[0].tooltip == "Dom 1 Nov"
    long = m.Period(date(2026, 1, 1), date(2026, 6, 30))                       # 181 days -> weekly
    weeks = m.build_buckets(long)
    assert weeks[0].start == date(2026, 1, 1) and weeks[0].end == date(2026, 1, 4)   # Thu..Sun
    assert all(w.start.weekday() == 0 for w in weeks[1:]) and weeks[-1].end == long.end
    assert sum((w.end - w.start).days + 1 for w in weeks) == long.days


def _overview_events():
    return frame(
        ("cda_user", "client", "cda", "2026-11-09 10:00", "production"),
        ("cda_user", "client", "cda", "2026-11-09 11:00", "development"),
        ("cda_idle", "client", "cda", "2026-11-05 12:00", "production"),
        ("emin_user", "client", "emin", "2026-10-20 12:00", "production"),
        ("emin_user", "client", "emin", "2026-09-20 12:00", "production"),     # previous period
        ("admin", "internal", None, "2026-11-08 09:00", "production"),
        ("ghost", "unmapped", None, "2026-11-08 10:00", "production"),
        ("old_user", "client", "old", "2026-11-08 11:00", "production"),        # inactive client
    )


def test_overview_totals_and_membership():
    ov = m.build_overview(_overview_events(), REGISTRY, m.resolve_period("30", TODAY), include_internal=False)
    assert ov.logins == 4 and sum(r.logins for r in ov.rows) == ov.logins
    assert [r.client_id for r in ov.rows] == ["cda", "emin"]                    # inactive client excluded
    assert (ov.active_clients, ov.registered_clients) == (2, 2)
    assert (ov.active_users, ov.registered_users) == (3, 3)
    assert ov.previous_logins == 1 and ov.logins_change.text == "▲ +300,0%"
    cda = ov.rows[0]
    assert (cda.active_users, cda.registered_users) == (2, 2) and sum(cda.spark) == 3
    assert ov.internal_hidden_logins == 1
    assert (ov.unmapped_logins, ov.unmapped_usernames, ov.orphan_client_logins) == (1, ["ghost"], 1)
    assert sum(ov.chart_counts) == ov.logins


def test_overview_with_internal_users():
    ov = m.build_overview(_overview_events(), REGISTRY, m.resolve_period("30", TODAY), include_internal=True)
    assert ov.logins == 5 and sum(ov.chart_counts) == 5
    assert ov.rows[-1].client_id == "internal" and ov.rows[-1].logins == 1 and ov.rows[-1].is_internal
    assert ov.active_clients == 2 and ov.internal_hidden_logins == 0
    assert m.sort_rows_by_logins(ov.rows)[-1].is_internal


def test_client_with_no_events_still_listed_with_last_access_from_full_history():
    events = frame(("emin_user", "client", "emin", "2026-06-01 12:00", "production"))
    ov = m.build_overview(events, REGISTRY, m.resolve_period("30", TODAY), include_internal=False)
    emin = next(r for r in ov.rows if r.client_id == "emin")
    assert emin.logins == 0 and emin.change.text == "–" and emin.last_access.date() == date(2026, 6, 1)
    cda = next(r for r in ov.rows if r.client_id == "cda")
    assert cda.last_access is None and m.relative_access(cda.last_access, datetime.now(ZoneInfo(TZ))) == "Sin accesos"
    assert ov.empty and ov.active_clients == 0


def _detail_events():
    specs = []
    users = ["u1", "u2", "u3", "u4", "u5", "u6", "u7"]
    for i, user in enumerate(users):
        for n in range(len(users) - i):                    # u1 has 7 events ... u7 has 1
            specs.append((user, "client", "cda", f"2026-11-0{1 + (n % 5)} {10 + n:02d}:30", "production"))
    specs.append(("u1", "client", "cda", "2026-11-03 22:15", "unknown"))
    specs.append(("cda_user", "client", "cda", "2026-11-07 00:30", "development"))   # Saturday, block 00
    return frame(*specs)


def test_detail_stacking_top_five_and_others():
    reg = parse_registry(CLIENTS, USERS)
    d = m.build_detail(_detail_events(), reg, "cda", m.resolve_period("30", TODAY))
    names = [n for n, _ in d.series]
    assert names[0] == "u1" and names[-1] == m.OTHERS and len(names) == m.MAX_STACKED_USERS + 1
    chart_total = sum(sum(counts) for _, counts in d.series)
    assert chart_total == d.logins == sum(u.total for u in d.users)
    assert sum(sum(row) for row in d.heatmap) == d.logins
    assert d.show_unknown and d.heatmap_max >= 1


def test_detail_lists_registered_users_without_events_and_hides_unknown_column():
    events = frame(("cda_user", "client", "cda", "2026-11-09 10:00", "production"))
    d = m.build_detail(events, REGISTRY, "cda", m.resolve_period("30", TODAY))
    assert {u.username for u in d.users} == {"cda_user", "cda_idle"}
    idle = next(u for u in d.users if u.username == "cda_idle")
    assert idle.total == 0 and idle.last_access is None
    assert (d.active_users, d.registered_users, d.active_days) == (1, 2, 1) and not d.show_unknown
    assert d.last_access_user == "cda_user"


def test_detail_heatmap_uses_display_timezone():
    # 2026-11-07 00:30 Santiago is Saturday 03:30 UTC; the block must be the local one (00-02).
    events = frame(("cda_user", "client", "cda", "2026-11-07 00:30", "production"))
    d = m.build_detail(events, REGISTRY, "cda", m.resolve_period("30", TODAY))
    assert d.heatmap[5][0] == 1 and sum(map(sum, d.heatmap)) == 1


def test_detail_internal_and_log_order():
    events = frame(("admin", "internal", None, "2026-11-08 09:00", "production"),
                   ("admin", "internal", None, "2026-11-09 09:00", "production"))
    d = m.build_detail(events, REGISTRY, m.INTERNAL_ID, m.resolve_period("30", TODAY))
    assert d.logins == 2 and d.registered_users == 1
    assert list(d.log["date"]) == [date(2026, 11, 9), date(2026, 11, 8)]       # newest first


def test_heatmap_levels_and_contrast():
    assert [m.heatmap_level(c, 100) for c in (0, 1, 15, 16, 35, 36, 65, 66, 100)] == [0, 1, 1, 2, 2, 3, 3, 4, 4]
