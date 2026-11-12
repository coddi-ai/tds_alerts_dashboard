"""Calculations behind "Resumen de Clientes" and "Detalle de Cliente" (TR-2, TR-3).

Pure functions over the normalized events table of `data_access.get_events()` and the registry:
no I/O, no UI. Dates are display-timezone calendar days.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd

from src.auth_events.registry import Registry
from src.i18n import t

INTERNAL_ID = "internal"
PERIOD_CHOICES = ("7", "30", "90", "custom")
DEFAULT_PERIOD = "30"
WEEKLY_AFTER_DAYS = 90
MAX_STACKED_USERS = 5
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
# Change vs previous period and "Último Acceso"

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


def relative_access(last: datetime | None, now: datetime) -> str:
    """Time since the last login, in the display timezone (`now` and `last` are tz-aware)."""
    if last is None:
        return t("user_registry.relative.never")
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
# Resumen de Clientes (TR-2)

@dataclass
class ClientRow:
    client_id: str
    name: str
    logins: int
    previous: int
    change: Change
    active_users: int
    registered_users: int
    spark: list[int]
    last_access: datetime | None
    is_internal: bool = False


@dataclass
class Overview:
    period: Period
    include_internal: bool
    logins: int = 0
    previous_logins: int = 0
    logins_change: Change = field(default_factory=lambda: Change("none", "–"))
    active_clients: int = 0
    registered_clients: int = 0
    active_users: int = 0
    registered_users: int = 0
    rows: list[ClientRow] = field(default_factory=list)
    buckets: list[Bucket] = field(default_factory=list)
    chart_counts: list[int] = field(default_factory=list)
    internal_hidden_logins: int = 0
    unmapped_logins: int = 0
    unmapped_usernames: list[str] = field(default_factory=list)
    orphan_client_logins: int = 0

    @property
    def empty(self) -> bool:
        return sum(self.chart_counts) == 0


def _pct(part: int, whole: int) -> float | None:
    return None if whole == 0 else part / whole * 100


def build_overview(all_events: pd.DataFrame, registry: Registry, period: Period,
                   include_internal: bool) -> Overview:
    """`all_events`: full history (already filtered by Ambiente)."""
    previous = period.previous
    current = in_period(all_events, period)
    prior = in_period(all_events, previous)

    client_cur, client_prior = scope_client_events(current, registry), scope_client_events(prior, registry)
    shown_cur = client_cur
    shown_prior = client_prior
    if include_internal:
        shown_cur = pd.concat([client_cur, scope_internal_events(current)]).sort_values("timestamp_utc", kind="stable")
        shown_prior = pd.concat([client_prior, scope_internal_events(prior)])

    clients = registry.active_clients()
    client_user_names = {u["username"] for c in clients for u in registry.users_of_client(c["client_id"])}

    ov = Overview(period=period, include_internal=include_internal)
    ov.logins, ov.previous_logins = len(shown_cur), len(shown_prior)
    ov.logins_change = change_vs_previous(ov.logins, ov.previous_logins)
    ov.registered_clients = len(clients)
    ov.active_clients = int(client_cur["client_id"].nunique())
    ov.registered_users = len(client_user_names)
    ov.active_users = int(client_cur["username"].nunique())

    for client in clients:
        cid = client["client_id"]
        cur, prev = scope_for(current, cid), scope_for(prior, cid)
        ov.rows.append(ClientRow(
            client_id=cid, name=client["display_name"], logins=len(cur), previous=len(prev),
            change=change_vs_previous(len(cur), len(prev)),
            active_users=int(cur["username"].nunique()),
            registered_users=len(registry.users_of_client(cid)),
            spark=daily_counts(cur, period),
            last_access=_last_ts(scope_for(all_events, cid)),
        ))
    if include_internal:
        cur, prev = scope_internal_events(current), scope_internal_events(prior)
        ov.rows.append(ClientRow(
            client_id=INTERNAL_ID, name="Equipo Interno", logins=len(cur), previous=len(prev),
            change=change_vs_previous(len(cur), len(prev)),
            active_users=int(cur["username"].nunique()),
            registered_users=len(registry.internal_users()),
            spark=daily_counts(cur, period),
            last_access=_last_ts(scope_internal_events(all_events)),
            is_internal=True,
        ))

    ov.buckets = build_buckets(period)
    ov.chart_counts = bucket_counts(shown_cur, ov.buckets)

    internal_cur = scope_internal_events(current)
    ov.internal_hidden_logins = 0 if include_internal else len(internal_cur)
    unmapped = current[current["user_type"] == "unmapped"]
    ov.unmapped_logins = len(unmapped)
    ov.unmapped_usernames = sorted(unmapped["username"].unique())
    ov.orphan_client_logins = len(current) - len(client_cur) - len(internal_cur) - len(unmapped)
    return ov


def _last_ts(events: pd.DataFrame) -> datetime | None:
    row = last_event(events)
    return None if row is None else row["timestamp"].to_pydatetime()


# ---------------------------------------------------------------------------------------------
# Detalle de Cliente (TR-3)

@dataclass
class UserRow:
    username: str
    production: int
    development: int
    unknown: int
    total: int
    active_days: int
    last_access: datetime | None


@dataclass
class Detail:
    client_id: str
    period: Period
    logins: int = 0
    previous_logins: int = 0
    logins_change: Change = field(default_factory=lambda: Change("none", "–"))
    active_users: int = 0
    registered_users: int = 0
    active_days: int = 0
    last_access: datetime | None = None
    last_access_user: str | None = None
    buckets: list[Bucket] = field(default_factory=list)
    series: list[tuple[str, list[int]]] = field(default_factory=list)   # stacking order, bottom first
    users: list[UserRow] = field(default_factory=list)
    show_unknown: bool = False
    heatmap: list[list[int]] = field(default_factory=list)              # [weekday][block]
    heatmap_max: int = 0
    log: pd.DataFrame = field(default_factory=pd.DataFrame)             # selection, newest first

    @property
    def empty(self) -> bool:
        return self.logins == 0


def heatmap_level(count: int, maximum: int) -> int:
    if count <= 0 or maximum <= 0:
        return 0
    ratio = count / maximum
    for level, limit in enumerate(HEATMAP_THRESHOLDS, start=1):
        if ratio <= limit:
            return level
    return len(HEATMAP_THRESHOLDS) + 1


def build_detail(all_events: pd.DataFrame, registry: Registry, client_id: str, period: Period) -> Detail:
    """`all_events`: full history (already filtered by Ambiente)."""
    history = scope_for(all_events, client_id)
    selection = in_period(history, period)
    previous = in_period(history, period.previous)

    registered = ([u["username"] for u in registry.internal_users()] if client_id == INTERNAL_ID
                  else [u["username"] for u in registry.users_of_client(client_id)])

    d = Detail(client_id=client_id, period=period)
    d.logins, d.previous_logins = len(selection), len(previous)
    d.logins_change = change_vs_previous(d.logins, d.previous_logins)
    d.registered_users = len(registered)
    d.active_users = int(selection["username"].nunique())
    d.active_days = int(selection["date"].nunique())
    newest = last_event(history)
    if newest is not None:
        d.last_access, d.last_access_user = newest["timestamp"].to_pydatetime(), newest["username"]

    # Stacked chart: top users individually, the rest as "Otros".
    totals = selection["username"].value_counts()
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    top = [name for name, _ in ranked[:MAX_STACKED_USERS]]
    d.buckets = build_buckets(period)
    for name in top:
        d.series.append((name, bucket_counts(selection[selection["username"] == name], d.buckets)))
    rest = selection[~selection["username"].isin(top)]
    if not rest.empty:
        d.series.append((OTHERS, bucket_counts(rest, d.buckets)))

    # Users table: every registered user plus anyone who logged in under this client.
    d.show_unknown = bool((selection["environment"] == "unknown").any())
    names = list(dict.fromkeys(registered + list(totals.index)))
    for name in names:
        mine, mine_all = selection[selection["username"] == name], history[history["username"] == name]
        env = mine["environment"].value_counts()
        d.users.append(UserRow(
            username=name, production=int(env.get("production", 0)), development=int(env.get("development", 0)),
            unknown=int(env.get("unknown", 0)), total=len(mine), active_days=int(mine["date"].nunique()),
            last_access=_last_ts(mine_all),
        ))
    d.users.sort(key=lambda u: (-u.total, u.username))

    # Heatmap: weekday x 2-hour block, display timezone.
    grid = [[0] * HEATMAP_BLOCKS for _ in range(7)]
    if not selection.empty:
        stamps = selection["timestamp"]
        for weekday, hour in zip(stamps.dt.weekday, stamps.dt.hour):
            grid[int(weekday)][int(hour) // 2] += 1
    d.heatmap = grid
    d.heatmap_max = max(max(row) for row in grid)

    d.log = selection.sort_values(["timestamp_utc", "event_id"], ascending=False, kind="stable").reset_index(drop=True)
    return d


def sort_rows_by_logins(rows: list[ClientRow]) -> list[ClientRow]:
    """Descending by logins (name breaks ties); `Equipo Interno` stays last."""
    regular = sorted((r for r in rows if not r.is_internal), key=lambda r: (-r.logins, r.name.casefold()))
    return regular + [r for r in rows if r.is_internal]
