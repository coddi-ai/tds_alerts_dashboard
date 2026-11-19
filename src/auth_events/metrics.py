"""Calculations behind "Actividad de Usuarios": the client overview and the client detail (TR-7).

Pure functions over the normalized events table of `data_access.get_events()` (logins AND page
views) and the registry: no I/O, no UI. Dates are display-timezone calendar days.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd

from src.auth_events.events import EVENT_TYPE_LOGIN, EVENT_TYPE_PAGE_VIEW, UNREGISTERED_PAGE_ID
from src.auth_events.registry import Registry
from src.i18n import t

INTERNAL_ID = "internal"
PERIOD_CHOICES = ("7", "30", "90", "custom")
DEFAULT_PERIOD = "30"
WEEKLY_AFTER_DAYS = 90
MAX_STACKED_USERS = 5
TOP_PAGES = 6
RECENT_ACTIVITY_SIZE = 7
OTHERS = "Otros"
HEATMAP_BLOCKS = 12
HEATMAP_THRESHOLDS = (0.15, 0.35, 0.65)

WEEKDAYS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
MONTHS = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")


# ---------------------------------------------------------------------------------------------
# es-CL formatting

def fmt_int(value: int | float) -> str:
    return f"{int(value):,}".replace(",", ".")


def fmt_decimal(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def half_up(value: float) -> int:
    """Round to the nearest integer, halves away from zero (Python's round() is banker's)."""
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def fmt_pct_int(value: float) -> str:
    return f"{half_up(value)}%"


def fmt_day_month(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}"


def fmt_weekday_day_month(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {fmt_day_month(day)}"


def fmt_datetime(moment: datetime) -> str:
    """D Mmm YYYY, HH:mm"""
    return f"{fmt_day_month(moment)} {moment.year}, {moment:%H:%M}"


def fmt_weekday_datetime(moment: datetime) -> str:
    """Vie 6 Nov, 16:12"""
    return f"{fmt_weekday_day_month(moment)}, {moment:%H:%M}"


# ---------------------------------------------------------------------------------------------
# Periods

@dataclass(frozen=True)
class Period:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def previous(self) -> "Period":
        return Period(self.start - timedelta(days=self.days), self.start - timedelta(days=1))

    def dates(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.days)]

    def caption(self) -> str:
        return f"{fmt_day_month(self.start)} {self.start.year} – {fmt_day_month(self.end)} {self.end.year}"


def parse_date(value) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def resolve_period(kind: str | None, today: date, start=None, end=None) -> Period:
    """Inclusive range in the display timezone; default is the last 30 days including today."""
    if kind in ("7", "30", "90"):
        return Period(today - timedelta(days=int(kind) - 1), today)
    if kind == "custom":
        first, last = parse_date(start), parse_date(end)
        if first and last and first <= last:
            return Period(first, last)
    return Period(today - timedelta(days=int(DEFAULT_PERIOD) - 1), today)


def normalize_period_kind(kind: str | None, start=None, end=None) -> str:
    if kind == "custom" and parse_date(start) and parse_date(end) and parse_date(start) <= parse_date(end):
        return "custom"
    return kind if kind in ("7", "30", "90") else DEFAULT_PERIOD


# ---------------------------------------------------------------------------------------------
# Change vs previous period and relative times

@dataclass(frozen=True)
class Change:
    kind: str          # new | none | zero | up | down
    text: str

    @property
    def direction(self) -> str:
        return self.kind if self.kind in ("up", "down") else "flat"


def change_vs_previous(current: int, previous: int) -> Change:
    if previous == 0:
        return Change("new", t("user_registry.change.new")) if current > 0 else Change("none", "–")
    pct = (current - previous) / previous * 100
    rounded = round(abs(pct), 1)
    if pct == 0:
        return Change("zero", "0,0%")
    text = fmt_decimal(rounded, 1)
    return Change("up", f"▲ +{text}%") if pct > 0 else Change("down", f"▼ −{text}%")


def relative_access(last: datetime | None, now: datetime, never: str | None = None) -> str:
    """Time since the last event, in the display timezone (`now` and `last` are tz-aware).
    `never` replaces the text for "no event at all" (default `Sin accesos`)."""
    if last is None:
        return never if never is not None else t("user_registry.relative.never")
    delta = now - last
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return t("user_registry.relative.minutes", n=max(minutes, 0))
    if delta < timedelta(hours=24):
        return t("user_registry.relative.hours", n=minutes // 60)
    days_apart = (now.date() - last.date()).days
    if days_apart == 1:
        return t("user_registry.relative.yesterday", time=f"{last:%H:%M}")
    return t("user_registry.relative.days", n=days_apart)


# ---------------------------------------------------------------------------------------------
# Event scoping

def in_period(events: pd.DataFrame, period: Period) -> pd.DataFrame:
    return events[(events["date"] >= period.start) & (events["date"] <= period.end)]


def scope_client_events(events: pd.DataFrame, registry: Registry) -> pd.DataFrame:
    """Events of users of an active client (attributed by the client_id stored in the event)."""
    active = {c["client_id"] for c in registry.active_clients()}
    return events[(events["user_type"] == "client") & (events["client_id"].isin(active))]


def scope_internal_events(events: pd.DataFrame) -> pd.DataFrame:
    return events[events["user_type"] == "internal"]


def scope_for(events: pd.DataFrame, client_id: str) -> pd.DataFrame:
    if client_id == INTERNAL_ID:
        return scope_internal_events(events)
    return events[(events["user_type"] == "client") & (events["client_id"] == client_id)]


def daily_counts(events: pd.DataFrame, period: Period) -> list[int]:
    if events.empty:
        return [0] * period.days
    counts = events.groupby("date").size()
    return [int(counts.get(day, 0)) for day in period.dates()]


def last_event(events: pd.DataFrame):
    """The newest event row of `events` (a full-history slice), or None."""
    return None if events.empty else events.iloc[-1]


# ---------------------------------------------------------------------------------------------
# Time buckets for the daily charts

@dataclass(frozen=True)
class Bucket:
    start: date
    end: date           # inclusive
    label: str
    tooltip: str
    weekly: bool = False


def build_buckets(period: Period) -> list[Bucket]:
    """One bucket per day; Monday-to-Sunday weeks when the period is longer than 90 days."""
    if period.days <= WEEKLY_AFTER_DAYS:
        return [Bucket(d, d, fmt_day_month(d), fmt_weekday_day_month(d)) for d in period.dates()]
    buckets = []
    cursor = period.start
    while cursor <= period.end:
        week_start = cursor - timedelta(days=cursor.weekday())
        week_end = min(week_start + timedelta(days=6), period.end)
        first = max(week_start, period.start)
        buckets.append(Bucket(first, week_end, fmt_day_month(first),
                              t("user_registry.chart.week_tooltip", start=fmt_day_month(first), end=fmt_day_month(week_end)),
                              weekly=True))
        cursor = week_end + timedelta(days=1)
    return buckets


def bucket_counts(events: pd.DataFrame, buckets: list[Bucket]) -> list[int]:
    if events.empty:
        return [0] * len(buckets)
    counts = events.groupby("date").size()
    return [int(sum(counts.get(d, 0) for d in _days_between(b.start, b.end))) for b in buckets]


def _days_between(first: date, last: date):
    return (first + timedelta(days=i) for i in range((last - first).days + 1))


# ---------------------------------------------------------------------------------------------
# Page-view helpers shared by both views (TR-7 items 3-4)

def page_views(events: pd.DataFrame) -> pd.DataFrame:
    return events[events["event_type"] == EVENT_TYPE_PAGE_VIEW]


def login_events(events: pd.DataFrame) -> pd.DataFrame:
    return events[events["event_type"] == EVENT_TYPE_LOGIN]


def page_view_change(current: int, previous: int, period: Period, capture_start: date | None) -> Change:
    """The page-view chip is `–` unless the WHOLE previous period is on or after the capture start
    (before it no page views exist, so the comparison would be meaningless)."""
    if capture_start is None or period.previous.start < capture_start:
        return Change("none", "–")
    return change_vs_previous(current, previous)


def capture_notice(capture_start: date | None, period: Period) -> tuple[str, date | None] | None:
    """`("none", None)` when no page view exists yet, `("since", date)` when the period starts
    before the capture start, else None."""
    if capture_start is None:
        return ("none", None)
    if period.start < capture_start:
        return ("since", capture_start)
    return None


def fmt_activity_chip(moment: datetime, now: datetime) -> str:
    """`Hoy, HH:mm`, otherwise `Vie 6 Nov, HH:mm`."""
    if moment.date() == now.date():
        return t("user_registry.relative.today", time=f"{moment:%H:%M}")
    return fmt_weekday_datetime(moment)


def fmt_log_datetime(moment: datetime, now: datetime) -> str:
    """`D Mmm, HH:mm`, with the year when it is not the current one."""
    year = f" {moment.year}" if moment.year != now.year else ""
    return f"{fmt_day_month(moment)}{year}, {moment:%H:%M}"


@dataclass
class PageRow:
    key: str
    name: str
    views: int
    share: int            # integer percent of all views in the selection (may not add up to 100)
    users: int
    is_other: bool = False


def build_pages(selection: pd.DataFrame) -> list[PageRow]:
    """The 6 most viewed pages plus `Otras Páginas`. An unregistered page is its own entry,
    named by its path (and tab); registered pages are grouped by `page_id`."""
    views = page_views(selection)
    total = len(views)
    if total == 0:
        return []
    keyed = views.assign(_key=[
        pid if pid and pid != UNREGISTERED_PAGE_ID else f"{UNREGISTERED_PAGE_ID}|{path}|{tab or ''}"
        for pid, path, tab in zip(views["page_id"], views["path"], views["tab"])])
    grouped = []
    for key, rows in keyed.groupby("_key", sort=False):
        grouped.append((key, rows["display_name"].iloc[0], len(rows), int(rows["username"].nunique())))
    grouped.sort(key=lambda g: (-g[2], g[1].casefold()))

    out = [PageRow(key, name, count, half_up(count / total * 100), users) for key, name, count, users in grouped[:TOP_PAGES]]
    rest = grouped[TOP_PAGES:]
    if rest:
        rest_keys = {g[0] for g in rest}
        count = sum(g[2] for g in rest)
        users = int(keyed[keyed["_key"].isin(rest_keys)]["username"].nunique())
        out.append(PageRow("other", t("user_registry.pages.other"), count, half_up(count / total * 100), users, is_other=True))
    return out


# ---------------------------------------------------------------------------------------------
# Resumen de Clientes (TR-7 item 2)

@dataclass
class ClientRow:
    client_id: str
    name: str
    page_views: int
    previous_views: int
    change: Change
    logins: int
    active_users: int
    registered_users: int
    spark: list[int]                      # daily page views across the period
    last_activity: datetime | None
    is_internal: bool = False


@dataclass
class Overview:
    period: Period
    include_internal: bool
    capture_start: date | None = None
    page_views: int = 0
    previous_page_views: int = 0
    views_change: Change = field(default_factory=lambda: Change("none", "–"))
    logins: int = 0
    previous_logins: int = 0
    logins_change: Change = field(default_factory=lambda: Change("none", "–"))
    active_clients: int = 0
    registered_clients: int = 0
    active_users: int = 0
    registered_users: int = 0
    rows: list[ClientRow] = field(default_factory=list)
    buckets: list[Bucket] = field(default_factory=list)
    chart_views: list[int] = field(default_factory=list)
    chart_logins: list[int] = field(default_factory=list)
    pages: list[PageRow] = field(default_factory=list)
    internal_hidden_logins: int = 0
    internal_hidden_views: int = 0
    unmapped_logins: int = 0
    unmapped_views: int = 0
    unmapped_usernames: list[str] = field(default_factory=list)
    orphan_logins: int = 0
    orphan_views: int = 0

    @property
    def empty(self) -> bool:
        return self.page_views == 0 and self.logins == 0

    @property
    def notice(self):
        return capture_notice(self.capture_start, self.period)


def _pct(part: int, whole: int) -> float | None:
    return None if whole == 0 else part / whole * 100


def build_overview(all_events: pd.DataFrame, registry: Registry, period: Period,
                   include_internal: bool, capture_start: date | None = None) -> Overview:
    """`all_events`: full history of BOTH event types (already filtered by Ambiente)."""
    previous = period.previous
    current = in_period(all_events, period)
    prior = in_period(all_events, previous)

    client_cur, client_prior = scope_client_events(current, registry), scope_client_events(prior, registry)
    shown_cur, shown_prior = client_cur, client_prior
    if include_internal:
        shown_cur = pd.concat([client_cur, scope_internal_events(current)]).sort_values("timestamp_utc", kind="stable")
        shown_prior = pd.concat([client_prior, scope_internal_events(prior)])

    clients = registry.active_clients()
    client_user_names = {u["username"] for c in clients for u in registry.users_of_client(c["client_id"])}
    registered_users = len(client_user_names) + (len(registry.internal_users()) if include_internal else 0)

    ov = Overview(period=period, include_internal=include_internal, capture_start=capture_start)
    cur_views, prior_views = page_views(shown_cur), page_views(shown_prior)
    cur_logins, prior_logins = login_events(shown_cur), login_events(shown_prior)
    ov.page_views, ov.previous_page_views = len(cur_views), len(prior_views)
    ov.views_change = page_view_change(ov.page_views, ov.previous_page_views, period, capture_start)
    ov.logins, ov.previous_logins = len(cur_logins), len(prior_logins)
    ov.logins_change = change_vs_previous(ov.logins, ov.previous_logins)
    ov.registered_clients = len(clients)
    ov.active_clients = int(client_cur["client_id"].nunique())          # any event type
    ov.registered_users = registered_users
    ov.active_users = int(shown_cur["username"].nunique())              # any event type

    def row_for(client_id: str, name: str, history: pd.DataFrame, registered: int, is_internal: bool) -> ClientRow:
        cur, prev = in_period(history, period), in_period(history, previous)
        views, prev_views = page_views(cur), page_views(prev)
        return ClientRow(
            client_id=client_id, name=name, page_views=len(views), previous_views=len(prev_views),
            change=page_view_change(len(views), len(prev_views), period, capture_start),
            logins=len(login_events(cur)), active_users=int(cur["username"].nunique()),
            registered_users=registered, spark=daily_counts(views, period),
            last_activity=_last_ts(history), is_internal=is_internal,
        )

    for client in clients:
        cid = client["client_id"]
        ov.rows.append(row_for(cid, client["display_name"], scope_for(all_events, cid),
                               len(registry.users_of_client(cid)), False))
    if include_internal:
        ov.rows.append(row_for(INTERNAL_ID, "Equipo Interno", scope_internal_events(all_events),
                               len(registry.internal_users()), True))

    ov.buckets = build_buckets(period)
    ov.chart_views = bucket_counts(cur_views, ov.buckets)
    ov.chart_logins = bucket_counts(cur_logins, ov.buckets)
    ov.pages = build_pages(shown_cur)

    internal_cur = scope_internal_events(current)
    if not include_internal:
        ov.internal_hidden_logins = len(login_events(internal_cur))
        ov.internal_hidden_views = len(page_views(internal_cur))
    unmapped = current[current["user_type"] == "unmapped"]
    ov.unmapped_logins, ov.unmapped_views = len(login_events(unmapped)), len(page_views(unmapped))
    ov.unmapped_usernames = sorted(unmapped["username"].unique())
    orphan = len(current) - len(client_cur) - len(internal_cur) - len(unmapped)
    if orphan:
        accounted = pd.concat([client_cur, internal_cur, unmapped])
        orphans = current[~current["event_id"].isin(accounted["event_id"])]
        ov.orphan_logins, ov.orphan_views = len(login_events(orphans)), len(page_views(orphans))
    return ov


def _last_ts(events: pd.DataFrame) -> datetime | None:
    row = last_event(events)
    return None if row is None else row["timestamp"].to_pydatetime()


# ---------------------------------------------------------------------------------------------
# Detalle de Cliente (TR-7 item 3)

@dataclass
class UserRow:
    username: str
    page_views: int
    logins: int
    active_days: int
    last_activity: datetime | None
    last_login: datetime | None


@dataclass
class Detail:
    client_id: str
    period: Period
    capture_start: date | None = None
    page_views: int = 0
    previous_page_views: int = 0
    views_change: Change = field(default_factory=lambda: Change("none", "–"))
    logins: int = 0
    previous_logins: int = 0
    logins_change: Change = field(default_factory=lambda: Change("none", "–"))
    active_users: int = 0
    registered_users: int = 0
    active_days: int = 0
    last_activity: datetime | None = None
    last_activity_user: str | None = None
    last_activity_type: str | None = None
    last_activity_detail: str | None = None          # display name of the page, for a page view
    buckets: list[Bucket] = field(default_factory=list)
    series_views: list[tuple[str, list[int]]] = field(default_factory=list)   # stacking order, bottom first
    series_logins: list[tuple[str, list[int]]] = field(default_factory=list)
    users: list[UserRow] = field(default_factory=list)
    heatmap: list[list[int]] = field(default_factory=list)                    # page views [weekday][block]
    heatmap_max: int = 0
    pages: list[PageRow] = field(default_factory=list)
    log: pd.DataFrame = field(default_factory=pd.DataFrame)                   # selection, newest first

    @property
    def empty(self) -> bool:
        return len(self.log) == 0

    @property
    def notice(self):
        return capture_notice(self.capture_start, self.period)


def heatmap_level(count: int, maximum: int) -> int:
    if count <= 0 or maximum <= 0:
        return 0
    ratio = count / maximum
    for level, limit in enumerate(HEATMAP_THRESHOLDS, start=1):
        if ratio <= limit:
            return level
    return len(HEATMAP_THRESHOLDS) + 1


def _stack(selection: pd.DataFrame, buckets: list[Bucket]) -> list[tuple[str, list[int]]]:
    """Top users individually (most events at the bottom), the rest as `Otros`."""
    totals = selection["username"].value_counts()
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    top = [name for name, _ in ranked[:MAX_STACKED_USERS]]
    series = [(name, bucket_counts(selection[selection["username"] == name], buckets)) for name in top]
    rest = selection[~selection["username"].isin(top)]
    if not rest.empty:
        series.append((OTHERS, bucket_counts(rest, buckets)))
    return series


def build_detail(all_events: pd.DataFrame, registry: Registry, client_id: str, period: Period,
                 capture_start: date | None = None) -> Detail:
    """`all_events`: full history of BOTH event types (already filtered by Ambiente)."""
    history = scope_for(all_events, client_id)
    selection = in_period(history, period)
    previous = in_period(history, period.previous)

    registered = ([u["username"] for u in registry.internal_users()] if client_id == INTERNAL_ID
                  else [u["username"] for u in registry.users_of_client(client_id)])

    d = Detail(client_id=client_id, period=period, capture_start=capture_start)
    views, logins = page_views(selection), login_events(selection)
    d.page_views, d.previous_page_views = len(views), len(page_views(previous))
    d.views_change = page_view_change(d.page_views, d.previous_page_views, period, capture_start)
    d.logins, d.previous_logins = len(logins), len(login_events(previous))
    d.logins_change = change_vs_previous(d.logins, d.previous_logins)
    d.registered_users = len(registered)
    d.active_users = int(selection["username"].nunique())               # any event type
    d.active_days = int(selection["date"].nunique())
    newest = last_event(history)
    if newest is not None:
        d.last_activity, d.last_activity_user = newest["timestamp"].to_pydatetime(), newest["username"]
        d.last_activity_type = newest["event_type"]
        d.last_activity_detail = newest["display_name"] if newest["event_type"] == EVENT_TYPE_PAGE_VIEW else None

    d.buckets = build_buckets(period)
    d.series_views = _stack(views, d.buckets)
    d.series_logins = _stack(logins, d.buckets)
    d.pages = build_pages(selection)

    # Users table: every registered user plus anyone with events under this client.
    names = list(dict.fromkeys(registered + list(selection["username"].unique())))
    for name in names:
        mine, mine_all = selection[selection["username"] == name], history[history["username"] == name]
        d.users.append(UserRow(
            username=name, page_views=len(page_views(mine)), logins=len(login_events(mine)),
            active_days=int(mine["date"].nunique()), last_activity=_last_ts(mine_all),
            last_login=_last_ts(login_events(mine_all)),
        ))
    d.users.sort(key=lambda u: (-u.page_views, -u.logins, u.username))

    # Heatmap of page views: weekday x 2-hour block, display timezone.
    grid = [[0] * HEATMAP_BLOCKS for _ in range(7)]
    if not views.empty:
        stamps = views["timestamp"]
        for weekday, hour in zip(stamps.dt.weekday, stamps.dt.hour):
            grid[int(weekday)][int(hour) // 2] += 1
    d.heatmap = grid
    d.heatmap_max = max(max(row) for row in grid)

    d.log = selection.sort_values(["timestamp_utc", "event_id"], ascending=False, kind="stable").reset_index(drop=True)
    return d


def sort_rows_by_views(rows: list[ClientRow]) -> list[ClientRow]:
    """Descending by page views (logins, then name, break ties); `Equipo Interno` stays last."""
    regular = sorted((r for r in rows if not r.is_internal), key=lambda r: (-r.page_views, -r.logins, r.name.casefold()))
    return regular + [r for r in rows if r.is_internal]
