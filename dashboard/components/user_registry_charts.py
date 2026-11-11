"""Charts of the admin "Registro de Usuarios" views (daily bars, stacked by user).

Neutral blue palette only: these are activity counts, not severity scores.
"""

import math

import plotly.graph_objects as go

from src.auth_events.metrics import OTHERS, Bucket
from src.i18n import t

BAR_COLOR = "#2563eb"
# Blue shades that differ in lightness (not just hue); "Otros" is gray.
USER_COLORS = ("#1e3a8a", "#2563eb", "#60a5fa", "#93c5fd", "#bfdbfe")
OTHERS_COLOR = "#94a3b8"
ENV_COLORS = {"production": "#1e3a8a", "development": "#60a5fa", "unknown": "#cbd5e1"}
ENV_BORDER = {"production": "#1e3a8a", "development": "#60a5fa", "unknown": "#94a3b8"}
TARGET_LABELS = 7          # x-axis labels aimed for in weekly charts
DAILY_LABEL_STEP = 5       # "about every 5 days"


def _int_dtick(maximum: int) -> int:
    """A y-axis step that is a whole number (1, 2, 5, 10, 20, 50, ...)."""
    if maximum <= 5:
        return 1
    raw = maximum / 5
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 5, 10):
        if raw <= factor * magnitude:
            return int(factor * magnitude)
    return int(10 * magnitude)


def _is_weekly(buckets: list[Bucket]) -> bool:
    return bool(buckets) and buckets[0].weekly


def _label_step(count: int, weekly: bool) -> int:
    return max(1, math.ceil(count / TARGET_LABELS)) if weekly else DAILY_LABEL_STEP


def _empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                       font={"size": 14, "color": "#475569"})
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(template="plotly_white", height=300, margin={"l": 10, "r": 10, "t": 10, "b": 10})
    return fig


def _style(fig: go.Figure, buckets: list[Bucket], maximum: int) -> None:
    step = _label_step(len(buckets), _is_weekly(buckets))
    positions = range(0, len(buckets), step)
    fig.update_xaxes(
        type="category", tickmode="array",
        tickvals=[buckets[i].tooltip for i in positions],
        ticktext=[buckets[i].label for i in positions],
        title=None, showgrid=False, tickangle=0,
    )
    fig.update_yaxes(
        rangemode="tozero", tickformat="d", dtick=_int_dtick(maximum),
        title=None, gridcolor="#e2e8f0",
    )
    # Every label plus the desktop interval: dashboard/assets/user_registry_axis.js thins them to the width.
    fig.update_layout(meta={"urTicks": {
        "vals": [b.tooltip for b in buckets], "text": [b.label for b in buckets], "step": step}})
    fig.update_layout(
        template="plotly_white", height=340, separators=",.", bargap=0.25,
        margin={"l": 40, "r": 10, "t": 10, "b": 40}, font={"color": "#0f172a"},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )


def create_daily_chart(buckets: list[Bucket], counts: list[int]) -> go.Figure:
    """One bar per day (or per Monday-Sunday week above 90 days), a single series."""
    if sum(counts) == 0:
        return _empty_figure(t("user_registry.empty.no_logins"))
    fig = go.Figure(go.Bar(
        x=[b.tooltip for b in buckets], y=counts, marker_color=BAR_COLOR,
        hovertemplate="%{x} · %{y} " + t("user_registry.chart.logins_unit") + "<extra></extra>",
        name=t("user_registry.chart.logins_series"),
    ))
    fig.update_layout(showlegend=False)
    _style(fig, buckets, max(counts))
    return fig


def create_stacked_chart(buckets: list[Bucket], series: list[tuple[str, list[int]]]) -> go.Figure:
    """Bars stacked by user: biggest user at the bottom, at most 5 users plus "Otros"."""
    if not series or sum(sum(counts) for _, counts in series) == 0:
        return _empty_figure(t("user_registry.empty.no_logins"))
    fig = go.Figure()
    for index, (name, counts) in enumerate(series):
        color = OTHERS_COLOR if name == OTHERS else USER_COLORS[index % len(USER_COLORS)]
        fig.add_trace(go.Bar(
            x=[b.tooltip for b in buckets], y=counts, name=name,
            marker={"color": color, "line": {"color": "#ffffff", "width": 1}},
            hovertemplate="%{y}<extra>" + name + "</extra>",
        ))
    totals = [sum(col) for col in zip(*(c for _, c in series))]
    _style(fig, buckets, max(totals))
    fig.update_layout(
        barmode="stack", hovermode="x unified",
        legend={"title": {"text": t("user_registry.chart.legend_user")}, "orientation": "h",
                "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0, "traceorder": "normal"},
        margin={"l": 40, "r": 10, "t": 70, "b": 40},
    )
    return fig
