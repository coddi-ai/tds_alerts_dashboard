"""Telemetry evidence of an alert: the trigger signal featured, the rest in a grid.

An alert ties together anywhere from a handful to 20+ telemetry signals. Instead of
stacking one full-width panel per signal, the section shows

* the signal that triggered the alert as one large chart, annotated with its peak and
  the limit it is measured against;
* every other signal as a compact chart in a responsive grid, those currently outside
  their limits first;
* only the first N supporting signals up front - the rest sit behind a toggle that
  expands them in place.

Everything is derived from the alert's own signal list: nothing here knows how many
signals an alert has. Each chart labels only its extremes (min/max) on both axes, so
labels cannot pile up however small the card gets.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from dashboard.components.alerts_charts import (
    LIMIT_LINE_WIDTH,
    SIGNAL_LINE_COLOR,
    SIGNAL_LINE_WIDTH,
    TRIGGER_ACCENT_COLOR,
    _split_gap_segments,
    _state_color,
    _state_label,
)
from src.i18n import t
from src.utils.date_utils import to_local_naive
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Telemetry window around the alert, same as the previous stacked chart.
WINDOW_MINUTES_BEFORE = 90
WINDOW_MINUTES_AFTER = 10

# Capstone may publish a context signal under its legacy CDA alias as well.
_CAPSTONE_ALIASES = {'engine_speed_rpm': 'EngSpd', 'engine_load_pct': 'EngLoad'}

LIMIT_COLOR = 'rgba(231, 76, 60, 0.55)'
FEATURED_HEIGHT = 320
COMPACT_HEIGHT = 170

SIGNALS_TOGGLE_ID = 'alert-signals-toggle'
SIGNALS_COLLAPSE_ID = 'alert-signals-collapse'
SIGNALS_LABELS_ID = 'alert-signals-toggle-labels'


@dataclass
class SignalPanel:
    """One signal's window of data, ready to chart."""
    feature: str
    display_name: str
    values: pd.DataFrame                      # TimeStart (local), value, state_label, state_color
    upper: Optional[pd.DataFrame] = None      # TimeStart (local), limit
    lower: Optional[pd.DataFrame] = None
    is_trigger: bool = False
    alert_value: Optional[float] = None       # value at the sample nearest to the alert
    upper_at_alert: Optional[float] = None
    lower_at_alert: Optional[float] = None
    out_of_range: bool = field(default=False)


def _nearest(df: pd.DataFrame, column: str, when: pd.Timestamp) -> Optional[float]:
    """Value of ``column`` at the sample nearest to ``when`` (None for an empty frame)."""
    if df is None or df.empty:
        return None
    idx = (df['TimeStart'] - when).abs().idxmin()
    value = df.loc[idx, column]
    return None if pd.isna(value) else float(value)


def _limit_frame(alert_data: pd.DataFrame, column: str) -> Optional[pd.DataFrame]:
    if column not in alert_data.columns:
        return None
    limit = alert_data[['TimeStart', column]].copy()
    limit[column] = pd.to_numeric(limit[column], errors='coerce')
    limit = limit.dropna(subset=[column]).sort_values('TimeStart')
    if limit.empty:
        return None
    return limit.rename(columns={column: 'limit'})


def prepare_signal_panels(
    alert_data: pd.DataFrame,
    feature_names: List[str],
    alert_time,
    trigger: Optional[str],
    feature_name_map: Optional[Dict[str, str]] = None,
    client: Optional[str] = None,
) -> Tuple[List[SignalPanel], Optional[pd.Timestamp]]:
    """Window the telemetry around the alert and build one panel per signal with data.

    The window is applied in UTC-naive like the rest of the detail view; only then are
    timestamps shifted to local wall-clock for display. Panels keep the order of
    ``feature_names`` (the source order). Returns ``(panels, local alert time)``.
    """
    if alert_data.empty or not feature_names:
        return [], None

    window_start = alert_time - timedelta(minutes=WINDOW_MINUTES_BEFORE)
    window_end = alert_time + timedelta(minutes=WINDOW_MINUTES_AFTER)
    windowed = alert_data[
        (alert_data['TimeStart'] >= window_start) & (alert_data['TimeStart'] <= window_end)
    ].copy()
    if windowed.empty:
        logger.warning(f"No data in time window [{window_start}, {window_end}]")
        return [], None

    windowed['TimeStart'] = to_local_naive(windowed['TimeStart'])
    local_alert_time = to_local_naive(alert_time)
    is_capstone = str(client or '').strip().upper() == 'CAPSTONE'
    trigger_key = str(trigger).strip().casefold() if trigger is not None and pd.notna(trigger) else None

    panels: List[SignalPanel] = []
    for feature in feature_names:
        value_col = f'{feature}_Value'
        upper_col = f'{feature}_Upper_Limit'
        lower_col = f'{feature}_Lower_Limit'
        if is_capstone:
            alias = _CAPSTONE_ALIASES.get(feature)
            if alias:
                canonical_has_values = (
                    value_col in windowed.columns
                    and pd.to_numeric(windowed[value_col], errors='coerce').notna().any()
                )
                if not canonical_has_values and f'{alias}_Value' in windowed.columns:
                    value_col, upper_col, lower_col = f'{alias}_Value', f'{alias}_Upper_Limit', f'{alias}_Lower_Limit'
        if value_col not in windowed.columns:
            logger.warning("Skipping feature without value column: %s", feature)
            continue

        columns = ['TimeStart', value_col] + (['State'] if 'State' in windowed.columns else [])
        values = windowed[columns].copy()
        values[value_col] = pd.to_numeric(values[value_col], errors='coerce')
        values = values.dropna(subset=['TimeStart', value_col]).sort_values('TimeStart')
        if values.empty:
            continue
        values = values.rename(columns={value_col: 'value'})
        if 'State' not in values.columns:
            values['State'] = ''
        states = values['State'].fillna('').astype(str)
        values['state_label'] = states.map(lambda state: _state_label(state) if state.strip() else '')
        values['state_color'] = states.map(lambda state: _state_color(state) if state.strip() else SIGNAL_LINE_COLOR)

        upper = _limit_frame(windowed, upper_col)
        lower = _limit_frame(windowed, lower_col)
        alert_value = _nearest(values, 'value', local_alert_time)
        upper_at = _nearest(upper, 'limit', local_alert_time)
        lower_at = _nearest(lower, 'limit', local_alert_time)
        out_of_range = alert_value is not None and (
            (upper_at is not None and alert_value > upper_at)
            or (lower_at is not None and alert_value < lower_at)
        )

        panels.append(SignalPanel(
            feature=feature,
            display_name=(feature_name_map or {}).get(feature, feature),
            values=values, upper=upper, lower=lower,
            is_trigger=trigger_key is not None and trigger_key == str(feature).strip().casefold(),
            alert_value=alert_value, upper_at_alert=upper_at, lower_at_alert=lower_at,
            out_of_range=bool(out_of_range),
        ))
    return panels, local_alert_time


def split_signal_panels(panels: List[SignalPanel]) -> Tuple[Optional[SignalPanel], List[SignalPanel]]:
    """``(trigger panel or None, supporting panels)``.

    The trigger never appears among the supporting signals. Supporting signals that are
    outside their limits at the alert come first; the others keep their source order
    (the sort is stable).
    """
    trigger = next((panel for panel in panels if panel.is_trigger), None)
    supporting = [panel for panel in panels if panel is not trigger]
    supporting.sort(key=lambda panel: not panel.out_of_range)
    return trigger, supporting


def _fmt(value: float) -> str:
    """Short number for an axis end or annotation."""
    if abs(value) >= 1e6 or abs(value) >= 1000:
        return f"{value:.0f}"
    return f"{round(value, 2):g}"


def _peak_point(panel: SignalPanel) -> Tuple[pd.Timestamp, float, bool]:
    """The extreme of the window in the direction the signal is measured against its limit.

    Normally the maximum; the minimum when the signal only has a lower limit or sits
    below it at the alert. Returns ``(time, value, is_minimum)``.
    """
    values = panel.values
    below = panel.lower_at_alert is not None and panel.alert_value is not None and panel.alert_value < panel.lower_at_alert
    above = panel.upper_at_alert is not None and panel.alert_value is not None and panel.alert_value > panel.upper_at_alert
    use_min = (below and not above) or (panel.lower is not None and panel.upper is None)
    idx = values['value'].idxmin() if use_min else values['value'].idxmax()
    return values.loc[idx, 'TimeStart'], float(values.loc[idx, 'value']), bool(use_min)


def build_signal_figure(panel: SignalPanel, alert_time, featured: bool = False) -> go.Figure:
    """Single-signal chart; ``featured`` adds the peak and limit annotations."""
    fig = go.Figure()
    values = panel.values
    line_width = SIGNAL_LINE_WIDTH * (1.8 if featured else 1.2)
    marker_size = 7 if featured else 4

    for segment in _split_gap_segments(values, 'TimeStart'):
        fig.add_trace(go.Scatter(
            x=segment['TimeStart'], y=segment['value'],
            mode='lines+markers', name=panel.display_name, showlegend=False,
            customdata=segment['state_label'].to_numpy(),
            marker=dict(size=marker_size, color=segment['state_color'].to_numpy(),
                        line=dict(width=1, color='white')),
            line=dict(color=SIGNAL_LINE_COLOR, width=line_width),
            hovertemplate=(
                f'<b>{panel.display_name}</b><br>'
                + t("alerts_charts.hora_br_2") + t("alerts_charts.valor_br") + t("alerts_charts.estado_br_2")
                + '<extra></extra>'
            ),
        ))

    limit_values = []
    for limit_df, limit_label in (
        (panel.lower, t("alerts_charts.limite_inferior")),
        (panel.upper, t("alerts_charts.limite_superior")),
    ):
        if limit_df is None:
            continue
        limit_values.extend(limit_df['limit'].tolist())
        for segment in _split_gap_segments(limit_df, 'TimeStart'):
            fig.add_trace(go.Scatter(
                x=segment['TimeStart'], y=segment['limit'], mode='lines', showlegend=False,
                line=dict(color=LIMIT_COLOR, width=LIMIT_LINE_WIDTH - (0 if featured else 1), dash='dash'),
                hovertemplate=limit_label + '<br>' + t("alerts_charts.hora_br_2") + t("alerts_charts.valor_br")
                + '<extra></extra>',
            ))

    # The alert moment, marked on every chart so the signals read against one reference.
    fig.add_shape(type='line', x0=alert_time, x1=alert_time, y0=0, y1=1, yref='y domain',
                  line=dict(color='rgba(128, 128, 128, 0.7)', width=2, dash='dot'))
    if featured:
        fig.add_annotation(x=alert_time, y=1, yref='y domain', text=t("erp.condition.alerta"),
                           showarrow=False, xanchor='left', yanchor='top',
                           font=dict(size=10, color='#7f8c8d'))

    # Axes label only their extremes: the data's min/max (limits included) vertically,
    # the start and end of the window horizontally.
    y_all = values['value'].tolist() + limit_values
    y_lo, y_hi = min(y_all), max(y_all)
    pad = (y_hi - y_lo) * 0.12 or max(abs(y_hi) * 0.05, 1.0)
    y_ticks = sorted({y_lo, y_hi})
    x_lo, x_hi = values['TimeStart'].min(), values['TimeStart'].max()
    x_ticks = [x_lo] if x_lo == x_hi else [x_lo, x_hi]

    right_margin = 10
    if featured:
        peak_time, peak_value, is_minimum = _peak_point(panel)
        peak_text = t("alerts_charts.minimo_valor" if is_minimum else "alerts_charts.pico_valor", value=_fmt(peak_value))
        fig.add_trace(go.Scatter(
            x=[peak_time], y=[peak_value], mode='markers', showlegend=False, hoverinfo='skip',
            marker=dict(size=13, color='rgba(0,0,0,0)', line=dict(width=3, color=TRIGGER_ACCENT_COLOR)),
        ))
        fig.add_annotation(
            x=peak_time, y=peak_value, text=f"<b>{peak_text}</b>", showarrow=True, arrowhead=2,
            arrowcolor=TRIGGER_ACCENT_COLOR, ax=0, ay=-34 if not is_minimum else 34,
            font=dict(size=12, color=TRIGGER_ACCENT_COLOR),
            bgcolor='rgba(255, 255, 255, 0.85)', bordercolor=TRIGGER_ACCENT_COLOR, borderwidth=1, borderpad=3,
        )
        # The limit the peak is measured against: the lower one for a minimum, else the upper.
        limit_label, limit_value = (
            (t("alerts_charts.limite_inferior"), panel.lower_at_alert) if is_minimum
            else (t("alerts_charts.limite_superior"), panel.upper_at_alert)
        )
        if limit_value is None:
            limit_label, limit_value = next(
                ((label, value) for label, value in (
                    (t("alerts_charts.limite_superior"), panel.upper_at_alert),
                    (t("alerts_charts.limite_inferior"), panel.lower_at_alert),
                ) if value is not None),
                (None, None),
            )
        if limit_value is not None:
            fig.add_annotation(
                x=1, xref='paper', y=limit_value, yref='y', xanchor='left', yanchor='middle',
                text=t("alerts_charts.limite_con_valor", label=limit_label, value=_fmt(limit_value)),
                showarrow=False, font=dict(size=11, color='#c0392b'),
            )
            right_margin = 120

    fig.update_layout(
        template='plotly_white', showlegend=False, hovermode='x unified',
        height=FEATURED_HEIGHT if featured else COMPACT_HEIGHT,
        margin=dict(l=52 if featured else 44, r=right_margin, t=18 if featured else 8, b=30 if featured else 26),
        paper_bgcolor='white', plot_bgcolor='rgba(248, 249, 250, 0.6)',
    )
    fig.update_xaxes(
        tickmode='array', tickvals=x_ticks,
        ticktext=[tick.strftime('%H:%M') for tick in x_ticks],
        tickfont=dict(size=10), showgrid=False, showline=True, linecolor='#e0e0e0',
    )
    fig.update_yaxes(
        tickmode='array', tickvals=y_ticks, ticktext=[_fmt(tick) for tick in y_ticks],
        range=[y_lo - pad, y_hi + pad], tickfont=dict(size=10),
        showgrid=True, gridcolor='rgba(220, 220, 220, 0.5)', showline=True, linecolor='#e0e0e0',
    )
    return fig


def _graph(fig: go.Figure, height: int, mode_bar: bool = False) -> dcc.Graph:
    return dcc.Graph(figure=fig, config={'displayModeBar': mode_bar}, style={'height': f'{height}px'})


def _signal_card(panel: SignalPanel, alert_time) -> html.Div:
    header = [html.Span(panel.display_name, className='alert-signal-card__title', title=panel.display_name)]
    if panel.out_of_range:
        header.append(html.Span(t("alert_signals.out_of_range"), className='alert-signal-card__flag'))
    return html.Div([
        html.Div(header, className='alert-signal-card__header'),
        _graph(build_signal_figure(panel, alert_time), COMPACT_HEIGHT),
    ], className='alert-signal-card')


def _featured_card(panel: SignalPanel, alert_time) -> html.Div:
    return html.Div([
        html.Div([
            html.Span([html.I(className='fas fa-bolt me-2'), t("alerts_callbacks.senal_gatillo")],
                      className='alert-signal-featured__label'),
            html.Span(panel.display_name, className='alert-signal-featured__title'),
        ], className='alert-signal-featured__header'),
        _graph(build_signal_figure(panel, alert_time, featured=True), FEATURED_HEIGHT, mode_bar=True),
    ], className='alert-signal-featured')


def _legend(panels: List[SignalPanel]) -> html.Div:
    """One legend for the whole section: the operating states seen and the limit line."""
    seen: Dict[str, str] = {}
    for panel in panels:
        for label, color in zip(panel.values['state_label'], panel.values['state_color']):
            if label and label not in seen:
                seen[label] = color
    items = [
        html.Span([html.Span(className='alert-signal-legend__dot', style={'backgroundColor': color}), label],
                  className='alert-signal-legend__item')
        for label, color in seen.items()
    ]
    items.append(html.Span([html.Span(className='alert-signal-legend__dash'), t("alerts_charts.limite")],
                           className='alert-signal-legend__item'))
    return html.Div(items, className='alert-signal-legend')


def _grid(panels: List[SignalPanel], alert_time) -> html.Div:
    return html.Div([_signal_card(panel, alert_time) for panel in panels], className='alert-signal-grid')


def toggle_labels(extra_count: int) -> Dict[str, str]:
    """Button texts for collapsed / expanded, with the number of signals behind it."""
    more = t("alert_signals.show_more_one") if extra_count == 1 else t("alert_signals.show_more", count=extra_count)
    return {'more': more, 'less': t("alert_signals.show_less")}


def create_signal_evidence(
    panels: List[SignalPanel],
    alert_time,
    visible_supporting: int,
) -> html.Div:
    """The section body: featured trigger chart, then the progressive signal grid."""
    trigger, supporting = split_signal_panels(panels)
    visible_supporting = max(int(visible_supporting), 0)
    shown, hidden = supporting[:visible_supporting], supporting[visible_supporting:]

    children = [_legend(panels)]
    if trigger is not None:
        children.append(_featured_card(trigger, alert_time))
    if shown:
        children.append(_grid(shown, alert_time))
    if hidden:
        labels = toggle_labels(len(hidden))
        children.extend([
            dcc.Store(id=SIGNALS_LABELS_ID, data=labels),
            dbc.Button(labels['more'], id=SIGNALS_TOGGLE_ID, color='primary', outline=True, size='sm',
                       className='alert-signals-toggle', n_clicks=0),
            dbc.Collapse(_grid(hidden, alert_time), id=SIGNALS_COLLAPSE_ID, is_open=False),
        ])
    return html.Div(children, className='alert-signal-evidence')
