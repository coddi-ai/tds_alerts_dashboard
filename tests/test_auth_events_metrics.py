"""TR-7 calculations: periods, change chips, relative times, merged overview and client detail (logins + page views)."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.auth_events import metrics as m
from src.auth_events.data_access import _frame
from src.auth_events.events import build_event, build_page_view_event
from src.auth_events.registry import PagesRegistry, parse_pages
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


PAGES = parse_pages(
    b'[{"page_id":"alertas","display_name":"Alertas","path":"/monitoring/alerts","tab":null},'
    b'{"page_id":"aceite","display_name":"Aceite","path":"/monitoring/oil","tab":null}]')


def _local(local):
    return datetime.strptime(local, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(TZ)).astimezone(timezone.utc)


def frame(*specs):
    """specs: login (username, user_type, client_id, 'YYYY-MM-DD HH:MM' local, environment) or page view
    (username, user_type, client_id, local, environment, path)."""
    events = []
    for i, spec in enumerate(specs):
        username, user_type, client_id, local, env = spec[:5]
        if len(spec) > 5:
            path = spec[5]
            entry = PAGES.match(path, None)
            events.append(build_page_view_event(username, user_type, client_id, env, entry["page_id"] if entry else "unregistered",
                                                path, None, moment=_local(local), event_id=f"e{i}"))
        else:
            events.append(build_event(username, user_type, client_id, env, moment=_local(local), event_id=f"e{i}"))
    return _frame(events, TZ, PAGES)


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




CAPTURE = date(2026, 9, 1)                      # page views exist from this day on


def _overview_events():
    return frame(
        ("cda_user", "client", "cda", "2026-11-09 10:00", "production"),                       # login
        ("cda_user", "client", "cda", "2026-11-09 10:01", "production", "/monitoring/alerts"),
        ("cda_user", "client", "cda", "2026-11-09 10:05", "production", "/monitoring/oil"),
        ("cda_user", "client", "cda", "2026-11-09 11:00", "development", "/monitoring/alerts"),
        ("cda_idle", "client", "cda", "2026-11-05 12:00", "production"),
        ("emin_user", "client", "emin", "2026-10-20 12:00", "production", "/somewhere/new"),     # unregistered page
        ("emin_user", "client", "emin", "2026-10-20 12:00", "production"),
        ("emin_user", "client", "emin", "2026-09-20 12:00", "production", "/monitoring/oil"),   # previous period
        ("admin", "internal", None, "2026-11-08 09:00", "production"),
        ("admin", "internal", None, "2026-11-08 09:01", "production", "/monitoring/alerts"),
        ("ghost", "unmapped", None, "2026-11-08 10:00", "production"),
        ("ghost", "unmapped", None, "2026-11-08 10:01", "production", "/monitoring/alerts"),
        ("old_user", "client", "old", "2026-11-08 11:00", "production", "/monitoring/alerts"),   # inactive client
    )


def test_overview_totals_membership_and_active_users_count_any_event_type():
    ov = m.build_overview(_overview_events(), REGISTRY, m.resolve_period("30", TODAY), False, CAPTURE)
    assert (ov.page_views, ov.logins) == (4, 3)
    assert sum(r.page_views for r in ov.rows) == ov.page_views and sum(r.logins for r in ov.rows) == ov.logins
    assert [r.client_id for r in ov.rows] == ["cda", "emin"]                    # inactive client excluded
    assert (ov.active_clients, ov.registered_clients) == (2, 2)
    assert (ov.active_users, ov.registered_users) == (3, 3)                     # cda_user, cda_idle, emin_user
    assert (ov.previous_page_views, ov.previous_logins) == (1, 0)
    assert ov.views_change.text == "▲ +300,0%" and ov.logins_change.text == "Nuevo"
    cda = ov.rows[0]
    assert (cda.active_users, cda.registered_users) == (2, 2) and sum(cda.spark) == cda.page_views == 3
    assert ov.rows[1].last_activity is not None
    assert (ov.internal_hidden_logins, ov.internal_hidden_views) == (1, 1)
    assert (ov.unmapped_logins, ov.unmapped_views, ov.unmapped_usernames) == (1, 1, ["ghost"])
    assert (ov.orphan_logins, ov.orphan_views) == (0, 1)
    assert sum(ov.chart_views) == ov.page_views and sum(ov.chart_logins) == ov.logins


def test_overview_internal_users_are_added_to_views_logins_and_active_users():
    ov = m.build_overview(_overview_events(), REGISTRY, m.resolve_period("30", TODAY), True, CAPTURE)
    assert (ov.page_views, ov.logins) == (5, 4) and sum(ov.chart_views) == 5 and sum(ov.chart_logins) == 4
    assert ov.active_users == 4 and ov.registered_users == 4                    # + admin
    assert ov.active_clients == 2                                               # clients only
    assert ov.rows[-1].client_id == "internal" and ov.rows[-1].page_views == 1 and ov.rows[-1].is_internal
    assert (ov.internal_hidden_logins, ov.internal_hidden_views) == (0, 0)
    assert m.sort_rows_by_views(ov.rows)[-1].is_internal


def test_pages_panel_top_six_plus_others_and_unregistered_pages_keep_their_own_entry():
    specs = []
    for page, count in (("/a", 8), ("/b", 7), ("/c", 6), ("/d", 5), ("/e", 4), ("/f", 3), ("/g", 2), ("/h", 1)):
        specs += [("cda_user", "client", "cda", "2026-11-09 10:00", "production", page)] * count
    specs.append(("cda_idle", "client", "cda", "2026-11-09 10:00", "production", "/monitoring/alerts"))
    pages = m.build_pages(m.in_period(frame(*specs), m.resolve_period("30", TODAY)))
    assert [p.name for p in pages[:6]] == ["/a", "/b", "/c", "/d", "/e", "/f"]
    other = pages[-1]
    assert other.is_other and other.name == "Otras Páginas" and other.views == 4 and other.users == 2
    assert sum(p.views for p in pages) == 8 + 7 + 6 + 5 + 4 + 3 + 2 + 1 + 1
    assert pages[0].share == m.half_up(8 / 37 * 100)


def test_registered_pages_group_by_page_id_and_unregistered_ones_by_path():
    events = frame(("cda_user", "client", "cda", "2026-11-09 10:00", "production", "/monitoring/alerts"),
                   ("cda_idle", "client", "cda", "2026-11-09 10:01", "production", "/monitoring/alerts"),
                   ("cda_user", "client", "cda", "2026-11-09 10:02", "production", "/x"),
                   ("cda_user", "client", "cda", "2026-11-09 10:03", "production", "/y"))
    pages = {p.name: p for p in m.build_pages(events)}
    assert pages["Alertas"].views == 2 and pages["Alertas"].users == 2
    assert pages["/x"].views == 1 and pages["/y"].views == 1


def test_page_view_chip_needs_the_whole_previous_period_after_capture_start():
    events = _overview_events()
    period = m.resolve_period("30", TODAY)                   # previous period starts 2026-09-12
    assert m.build_overview(events, REGISTRY, period, False, date(2026, 9, 12)).views_change.text == "▲ +300,0%"
    early = m.build_overview(events, REGISTRY, period, False, date(2026, 9, 13))
    assert early.views_change.text == "–" and early.logins_change.text == "Nuevo"   # logins are unaffected
    assert early.notice is None                                                     # the period itself starts after capture
    late = m.build_overview(events, REGISTRY, period, False, date(2026, 10, 20))
    assert late.notice == ("since", date(2026, 10, 20)) and late.views_change.text == "–"
    assert m.build_overview(events, REGISTRY, period, False, date(2026, 10, 12)).notice is None
    none_yet = m.build_overview(events, REGISTRY, period, False, None)
    assert none_yet.notice == ("none", None) and none_yet.views_change.text == "–"


def test_client_with_no_events_still_listed_with_last_activity_from_full_history():
    events = frame(("emin_user", "client", "emin", "2026-06-01 12:00", "production"))
    ov = m.build_overview(events, REGISTRY, m.resolve_period("30", TODAY), False, None)
    emin = next(r for r in ov.rows if r.client_id == "emin")
    assert emin.page_views == 0 and emin.change.text == "–" and emin.last_activity.date() == date(2026, 6, 1)
    cda = next(r for r in ov.rows if r.client_id == "cda")
    assert cda.last_activity is None and m.relative_access(cda.last_activity, datetime.now(ZoneInfo(TZ))) == "Sin accesos"
    assert ov.empty and ov.active_clients == 0


def test_last_activity_is_a_page_view_even_when_the_last_login_is_old():
    events = frame(("cda_user", "client", "cda", "2026-10-01 09:00", "production"),
                   ("cda_user", "client", "cda", "2026-11-09 16:00", "production", "/monitoring/alerts"))
    d = m.build_detail(events, REGISTRY, "cda", m.resolve_period("30", TODAY), CAPTURE)
    user = next(u for u in d.users if u.username == "cda_user")
    assert user.last_activity.date() == date(2026, 11, 9) and user.last_login.date() == date(2026, 10, 1)
    assert (d.last_activity_user, d.last_activity_type, d.last_activity_detail) == ("cda_user", "page_view", "Alertas")


def _detail_events():
    specs = []
    users = ["u1", "u2", "u3", "u4", "u5", "u6", "u7"]
    for i, user in enumerate(users):
        for n in range(len(users) - i):                    # u1 has 7 page views ... u7 has 1
            specs.append((user, "client", "cda", f"2026-11-0{1 + (n % 5)} {10 + n:02d}:30", "production", "/monitoring/alerts"))
    specs.append(("u1", "client", "cda", "2026-11-03 22:15", "unknown"))
    specs.append(("cda_user", "client", "cda", "2026-11-07 00:30", "development", "/monitoring/oil"))   # Saturday, block 00
    return frame(*specs)


def test_detail_stacking_top_five_and_others_for_each_metric():
    d = m.build_detail(_detail_events(), REGISTRY, "cda", m.resolve_period("30", TODAY), CAPTURE)
    names = [n for n, _ in d.series_views]
    assert names[0] == "u1" and names[-1] == m.OTHERS and len(names) == m.MAX_STACKED_USERS + 1
    assert sum(sum(counts) for _, counts in d.series_views) == d.page_views == sum(u.page_views for u in d.users)
    assert [n for n, _ in d.series_logins] == ["u1"] and d.logins == 1
    assert sum(sum(row) for row in d.heatmap) == d.page_views                   # heatmap counts page views only
    assert d.heatmap_max >= 1 and d.heatmap[5][0] == 1


def test_detail_lists_registered_users_without_activity():
    events = frame(("cda_user", "client", "cda", "2026-11-09 10:00", "production", "/monitoring/alerts"))
    d = m.build_detail(events, REGISTRY, "cda", m.resolve_period("30", TODAY), CAPTURE)
    assert {u.username for u in d.users} == {"cda_user", "cda_idle"}
    idle = next(u for u in d.users if u.username == "cda_idle")
    assert (idle.page_views, idle.logins, idle.last_activity, idle.last_login) == (0, 0, None, None)
    assert (d.active_users, d.registered_users, d.active_days) == (1, 2, 1)
    assert d.users[0].username == "cda_user"                                    # default sort: page views, descending


def test_detail_heatmap_uses_display_timezone():
    # 2026-11-07 00:30 Santiago is Saturday 03:30 UTC; the block must be the local one (00-02).
    events = frame(("cda_user", "client", "cda", "2026-11-07 00:30", "production", "/monitoring/alerts"))
    d = m.build_detail(events, REGISTRY, "cda", m.resolve_period("30", TODAY), CAPTURE)
    assert d.heatmap[5][0] == 1 and sum(map(sum, d.heatmap)) == 1


def test_detail_internal_and_log_holds_both_types_newest_first():
    events = frame(("admin", "internal", None, "2026-11-08 09:00", "production"),
                   ("admin", "internal", None, "2026-11-09 09:00", "production", "/monitoring/oil"))
    d = m.build_detail(events, REGISTRY, m.INTERNAL_ID, m.resolve_period("30", TODAY), CAPTURE)
    assert (d.logins, d.page_views, d.registered_users) == (1, 1, 1)
    assert list(d.log["date"]) == [date(2026, 11, 9), date(2026, 11, 8)]       # newest first
    assert list(d.log["event_type"]) == ["page_view", "login"]


def test_activity_chip_and_log_date_formats():
    tz = ZoneInfo(TZ)
    now = datetime(2026, 11, 10, 15, 0, tzinfo=tz)
    assert m.fmt_activity_chip(datetime(2026, 11, 10, 9, 5, tzinfo=tz), now) == "Hoy, 09:05"
    assert m.fmt_activity_chip(datetime(2026, 11, 6, 16, 12, tzinfo=tz), now) == "Vie 6 Nov, 16:12"
    assert m.fmt_log_datetime(datetime(2026, 11, 6, 16, 12, tzinfo=tz), now) == "6 Nov, 16:12"
    assert m.fmt_log_datetime(datetime(2025, 12, 31, 8, 0, tzinfo=tz), now) == "31 Dic 2025, 08:00"


def test_heatmap_levels_and_contrast():
    assert [m.heatmap_level(c, 100) for c in (0, 1, 15, 16, 35, 36, 65, 66, 100)] == [0, 1, 1, 2, 2, 3, 3, 4, 4]
