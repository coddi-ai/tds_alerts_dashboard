"""
Componentes de gráficos para la página de evidencia.
"""
import json
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from src.i18n import t as _t
from dashboard.components.labels import status_label
logger = logging.getLogger(__name__)
import numpy as np
import plotly.graph_objects as go
import pandas as pd

from dashboard.components.oil_charts import (
    get_essay_limits_four,
    consolidate_limit_entries,
    limit_line_color,
)
from dashboard.components.predictive_state import (
    STATE_COLORS,
    STATE_SEVERITY,
    STATE_ZONE_FILL,
    STATE_ZONE_TEXT,
    normalize_state,
    state_marker_size,
)


def _oil_date_col(df) -> str:
    """
    Nombre de la columna de fecha de las muestras de aceite.
    CDA usa 'sampleDate'; Capstone no la tiene y usa 'Fecha' para todo.
    """
    if "sampleDate" in df.columns:
        return "sampleDate"
    return "Fecha"


# Short View quadrants in the red / yellow / green state language: the critical
# quadrant is Anormal (red), the two mixed ones Alerta (yellow), the healthy one
# Normal (green). Fill and label come from predictive_state, shared with the
# Long View's reference band.
_ZONE_STATE = {
    "critical": "Anormal",
    "worsened": "Alerta",
    "improved": "Alerta",
    "healthy": "Normal",
}


# Short View axis fields (config.settings.FLEET_SCATTER_AXIS_FIELDS): name -> (column
# of the per-unit frame, axis-title i18n key). 60d / 90d are the loader's rolling means.
SCATTER_AXIS_FIELDS = {
    "ranking_today": ("ranking", "predictive_charts.ranking_hoy"),
    "ranking_7d": ("avg_ranking_7d", "predictive_charts.ranking_7_dias"),
    "ranking_30d": ("avg_ranking_30d", "predictive_charts.ranking_30_dias"),
    "ranking_60d": ("avg_ranking_60d", "predictive_charts.ranking_60_dias"),
    "ranking_90d": ("ranking_acum_90d", "predictive_charts.ranking_90_dias"),
}


def scatter_axis_columns(axes):
    """Frame columns of the configured (x, y) axis fields. Raises on a missing or
    unknown pair: there is no default pairing to fall back to."""
    try:
        return tuple(SCATTER_AXIS_FIELDS[field][0] for field in axes)
    except (KeyError, TypeError) as exc:
        raise ValueError(f"fleet scatter axes {axes!r} must be two of {list(SCATTER_AXIS_FIELDS)}") from exc


def _axis_range(values, thresh, min_pad):
    """Axis range around the data that always contains `thresh` (so no zone
    collapses when the whole fleet sits on one side of it). Without a threshold
    it is just the padded data range; with no finite data, a default window."""
    finite = values[values.notna() & (values.abs() != float("inf"))]
    lo, hi = (float(finite.min()), float(finite.max())) if not finite.empty else (None, None)
    if lo is None:
        return (0.0, 2 * thresh if thresh is not None else 100.0)
    pad = max((hi - lo) * 0.12, min_pad)
    lo, hi = max(0.0, lo - pad), hi + pad
    if thresh is not None:
        lo, hi = max(0.0, min(lo, thresh - 5)), max(hi, thresh + 5)
    return (lo, hi)


# ── Scatter-style charts: state-scaled markers and aligned unit labels ─────────

# Normal (baseline) marker of every scatter-style chart; Alerta/Anormal scale
# from it by predictive_state.STATE_SIZE_FACTOR.
SCATTER_BASE_MARKER = 8
# Selected-unit highlight: the state's own marker, enlarged and ringed in blue
# (8px Normal -> 14px, as before) so the state color/size rule still holds.
SELECTED_MARKER_SCALE = 1.75
SELECTED_COLOR = "#2563EB"
# Unit labels are always neutral gray, whatever the unit's state: only the marker
# carries the state color.
LABEL_COLOR = "#4b5563"
LABEL_FONT_PX = 9
# What a label shrinks to where the normal size would crowd a neighbour.
LABEL_FONT_SMALL_PX = 7

# Plotly `textposition` -> direction of the label from its point (x, y in {-1, 0, 1}).
_TEXT_DIRECTION = {
    "top center": (0, 1), "bottom center": (0, -1),
    "middle right": (1, 0), "middle left": (-1, 0),
    "top right": (1, 1), "top left": (-1, 1),
    "bottom right": (1, -1), "bottom left": (-1, -1),
}
_SCATTER_LABEL_ORDER = (
    "top center", "bottom center", "middle right", "middle left",
    "top right", "top left", "bottom right", "bottom left",
)
_LABEL_GAP_PX = 3
# A label sits `_LABEL_GAP_PX` from its own marker and must stay this far from
# every OTHER marker and label, so it always reads as belonging to the nearest
# point - its own. Where no position keeps that clearance the label is omitted:
# the point is still drawn, and a connector line to a far-off label is never used.
_OTHER_MARKER_CLEARANCE_PX = 5
_OTHER_LABEL_CLEARANCE_PX = 1
# Past this many points the pairwise search is skipped and no labels are drawn -
# far more points than any readable chart carries.
_LABEL_SEARCH_LIMIT = 400


class LabelPlacement(NamedTuple):
    """Where one point's label goes. `position` is the Plotly `textposition` of
    the direction; (`dx`, `dy`) is the pixel offset (y up) from the point's
    centre to the label's anchor corner/edge; `font_px` the size it is drawn at."""
    position: str
    dx: float
    dy: float
    font_px: float


def _rect_overlap(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _anchor_offset(position, distance):
    ux, uy = _TEXT_DIRECTION[position]
    norm = math.hypot(ux, uy) or 1.0
    return ux / norm * distance, uy / norm * distance


def _label_box(anchor_x, anchor_y, ux, uy, width, height):
    """Label rectangle whose nearest side/corner (by direction) sits on the anchor."""
    left = anchor_x if ux > 0 else anchor_x - width if ux < 0 else anchor_x - width / 2
    bottom = anchor_y if uy > 0 else anchor_y - height if uy < 0 else anchor_y - height / 2
    return (left, bottom, left + width, bottom + height)


def _grow(box, margin):
    return (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)


def place_labels(xs, ys, sizes, labels, x_range, y_range, plot_px, *,
                 priority=None, order=_SCATTER_LABEL_ORDER, bleed_px=(0, 0, 0, 0),
                 font_px=LABEL_FONT_PX, small_font_px=LABEL_FONT_SMALL_PX, blocked=()):
    """A `LabelPlacement` per point - or None where the label is left out - so a
    label always sits right next to its own point and never crowds another.

    Plotly offsets a label by its own point's marker radius, so differing marker
    sizes alone never detach it; what breaks alignment is a neighbour sitting
    where a fixed position puts the label. Labels are placed most-severe first
    (`priority`), each taking the first of `order`'s eight adjacent positions that
    is clear of every other marker, every label already placed and the plot's
    edge. Everything is tried at `font_px` first; a label that fits nowhere at that
    size gets a second chance at the smaller `small_font_px`; one that still fits
    nowhere is omitted (None) and its point is drawn without a label. There is no
    connector line to a far-away label: ambiguity about whose label it is is worse
    than no label.

    Geometry is estimated in pixels from `plot_px` (width, height of the plot
    area); the chart is responsive, so the estimate degrades gracefully with
    width. `sizes`: marker diameter per point. `bleed_px`: (left, right, top,
    bottom) room the figure margins leave outside the axes. `blocked`: further
    rectangles (left, bottom, right, top; plot pixels, y up) no label may cover,
    e.g. the chart's own zone captions. NaN/inf points are not obstacles and get no
    label.
    """
    n = len(labels)
    placements = [None] * n
    if n == 0 or n > _LABEL_SEARCH_LIMIT:
        return placements

    width, height = plot_px
    x0, x1 = x_range
    y0, y1 = y_range
    sx = width / (x1 - x0) if x1 > x0 else 0.0
    sy = height / (y1 - y0) if y1 > y0 else 0.0
    px = (np.asarray(xs, dtype=float) - x0) * sx
    py = (np.asarray(ys, dtype=float) - y0) * sy
    finite = np.isfinite(px) & np.isfinite(py)
    radius = np.asarray(sizes, dtype=float) / 2.0

    # Obstacles for OTHER points' labels: every marker, grown by the clearance.
    obstacles = [
        _grow((px[i] - radius[i], py[i] - radius[i], px[i] + radius[i], py[i] + radius[i]), _OTHER_MARKER_CLEARANCE_PX)
        if finite[i] else None
        for i in range(n)
    ]
    bleed_l, bleed_r, bleed_t, bleed_b = bleed_px
    bounds = (-bleed_l, -bleed_b, width + bleed_r, height + bleed_t)

    ranks = priority if priority is not None else [0] * n
    pending = [i for i in sorted(range(n), key=lambda k: (-ranks[k], k)) if finite[i]]
    placed = []  # boxes of the labels already placed
    sizes_to_try = (font_px,) if small_font_px >= font_px else (font_px, small_font_px)
    for size in sizes_to_try:
        label_h = size * 1.3
        still_pending = []
        for i in pending:
            label_w = len(str(labels[i])) * size * 0.6
            for position in order:
                ux, uy = _TEXT_DIRECTION[position]
                dx, dy = _anchor_offset(position, radius[i] + _LABEL_GAP_PX)
                box = _label_box(px[i] + dx, py[i] + dy, ux, uy, label_w, label_h)
                inside = box[0] >= bounds[0] and box[1] >= bounds[1] and box[2] <= bounds[2] and box[3] <= bounds[3]
                if (inside
                        and not any(_rect_overlap(box, o) for o in blocked)
                        and not any(_rect_overlap(box, o) for j, o in enumerate(obstacles) if o is not None and j != i)
                        and not any(_rect_overlap(_grow(box, _OTHER_LABEL_CLEARANCE_PX), other) for other in placed)):
                    placements[i] = LabelPlacement(position, dx, dy, size)
                    placed.append(box)
                    break
            else:
                still_pending.append(i)
        pending = still_pending
    return placements


def _hex_to_rgba(color, alpha):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def _label_annotation(unit, x, y, placement):
    """Annotation for one unit label, anchored to its data point and shifted by
    pixels so it stays glued to the point at any chart width. Gray, at the size
    `place_labels` settled on, on a light backing so curves running under it do not
    strike it through; never carries a connector line."""
    ux, uy = _TEXT_DIRECTION[placement.position]
    return dict(
        x=x, y=y, xref="x", yref="y", text=unit, name="unit-label", showarrow=False,
        xanchor="left" if ux > 0 else "right" if ux < 0 else "center",
        yanchor="bottom" if uy > 0 else "top" if uy < 0 else "middle",
        xshift=placement.dx, yshift=placement.dy,
        font=dict(size=placement.font_px, color=LABEL_COLOR, family="DM Sans, sans-serif"),
        bgcolor="rgba(255,255,255,0.6)", borderpad=0,
    )


def create_fleet_scatter(df_latest, selected_unit, status_colors, thresholds=None, meter_by_unit=None,
                         height=380, *, axes):
    """
    Crear scatter con todos los equipos. Destaca el equipo seleccionado. El tooltip
    muestra el ranking de hoy, el de 7, 30 y 90 días y las horas de componente, sea
    cual sea el par de ejes.

    `axes` es el (x, y) de campos de ranking configurado para el cliente/componente
    (Settings.get_fleet_scatter_axes; claves de SCATTER_AXIS_FIELDS). Es obligatorio:
    no hay un par por defecto, y uno ausente o desconocido lanza ValueError.

    `height` en px; None deja que el gráfico tome el alto de su contenedor
    (General lo dimensiona 2.5:1 por CSS).

    Cada punto se colorea y dimensiona por el `status` (`unit_status_summary.estado`)
    de esta vista: verde Normal, amarillo Alerta, rojo Anormal; Anormal 1.5x, Alerta
    1.2x y Normal 1x el tamaño base. Las etiquetas de unidad son grises y se ubican
    con `place_labels`: junto a su punto, más chicas donde hay aglomeración y
    omitidas (sin línea de conexión) donde ni así caben.

    `thresholds` es el (x, y) configurado para el cliente/componente
    (Settings.get_fleet_scatter_threshold): divide los ejes en las cuatro
    regiones. Con None no hay regiones, líneas ni etiquetas: scatter simple.
    `meter_by_unit` ({Unit: horas}) agrega las horas de componente al tooltip; None
    lo omite y una unidad sin lectura muestra "—".
    """
    x_col, y_col = scatter_axis_columns(axes)
    x_title, y_title = (_t(SCATTER_AXIS_FIELDS[field][1]) for field in axes)
    x_all = df_latest[x_col].astype(float)
    y_all = df_latest[y_col].astype(float)

    x_thresh, y_thresh = thresholds if thresholds is not None else (None, None)
    x0, x1 = _axis_range(x_all, x_thresh, 5)
    y0, y1 = _axis_range(y_all, y_thresh, 2)

    fig = go.Figure()

    # Plot-area size the label placement assumes: General's 2.5:1 chart at ~1100px
    # wide (l=60, r=20, t=20, b=50 margins), or the fixed height given.
    plot_px = (1020, 370) if height is None else (900, height - 70)
    caption_boxes = []  # the zone captions, in plot pixels: unit labels keep off them

    if thresholds is not None:
        zones = {
            "critical": (x_thresh, y_thresh, x1, y1, "predictive_charts.critica_sostenida"),
            "worsened": (x_thresh, y0, x1, y_thresh, "predictive_charts.empeoro_de_golpe"),
            "improved": (x0, y_thresh, x_thresh, y1, "predictive_charts.mejoro_recientemente"),
            "healthy": (x0, y0, x_thresh, y_thresh, "predictive_charts.zona_saludable"),
        }
        for zone, (qx0, qy0, qx1, qy1, label_key) in zones.items():
            caption = _t(label_key)
            cx = ((qx0 + qx1) / 2 - x0) / (x1 - x0) * plot_px[0] if x1 > x0 else 0.0
            cy = ((qy0 + qy1) / 2 - y0) / (y1 - y0) * plot_px[1] if y1 > y0 else 0.0
            half_w, half_h = len(caption) * 11 * 0.6 / 2, 11 * 1.3 / 2
            caption_boxes.append((cx - half_w, cy - half_h, cx + half_w, cy + half_h))
            state = _ZONE_STATE[zone]
            fill, text_color = STATE_ZONE_FILL[state], STATE_ZONE_TEXT[state]
            fig.add_shape(
                type="rect", x0=qx0, y0=qy0, x1=qx1, y1=qy1,
                fillcolor=fill, line_width=0, layer="below"
            )
            fig.add_annotation(
                x=(qx0 + qx1) / 2, y=(qy0 + qy1) / 2, text=caption,
                showarrow=False, xanchor="center", yanchor="middle",
                font=dict(size=11, color=text_color, family="DM Sans"),
            )

        # Dividers
        fig.add_shape(
            type="line", x0=x_thresh, y0=y0, x1=x_thresh, y1=y1,
            line=dict(color="rgba(0,0,0,0.3)", width=1, dash="dot")
        )
        fig.add_shape(
            type="line", x0=x0, y0=y_thresh, x1=x1, y1=y_thresh,
            line=dict(color="rgba(0,0,0,0.3)", width=1, dash="dot")
        )

    def _meter_hover(units):
        """Per-point hovertext (the horómetro) and the template fragment that shows it."""
        if meter_by_unit is None:
            return None, ""
        texts = []
        for u in units:
            hrs = meter_by_unit.get(u)
            texts.append(f"{hrs:,.0f} hrs" if hrs is not None and pd.notna(hrs) else "—")
        return texts, _t("predictive_charts.hover_component_meter")

    def _hover_template(template, meter_line):
        # The meter line goes right before the closing <extra> of the base tooltip.
        return template.replace("<extra></extra>", meter_line + "<extra></extra>")

    # One group per state (colored and sized by it), then the selected unit on
    # top. Label positions are solved over every group at once so labels never
    # collide across states.
    groups = []  # (state, color, frame, is_selected)
    def _shown(column, spec):
        """{Unit: text} of a ranking column, as the tooltip shows it."""
        if column not in df_latest.columns:
            return {}
        return {u: (format(v, spec) if pd.notna(v) else "—") for u, v in zip(df_latest["Unit"], df_latest[column].astype(float))}

    # The tooltip's ranking values do not depend on which two are plotted.
    today, r7, r30, r90 = (_shown("ranking", ".0f"), _shown("avg_ranking_7d", ".1f"),
                           _shown("avg_ranking_30d", ".1f"), _shown("ranking_acum_90d", ".1f"))
    for st, color in status_colors.items():
        subset = df_latest[(df_latest["status"] == st) & (df_latest["Unit"] != selected_unit)]
        if not subset.empty:
            groups.append((st, color, subset, False))
    sel = df_latest[df_latest["Unit"] == selected_unit]
    if not sel.empty:
        sel_state = sel.iloc[0]["status"]
        groups.append((sel_state, status_colors.get(sel_state, SELECTED_COLOR), sel.iloc[:1], True))

    def _group_size(state, is_selected):
        size = state_marker_size(state, SCATTER_BASE_MARKER)
        return size * SELECTED_MARKER_SCALE if is_selected else size

    all_units, all_x, all_y, all_sizes, all_priority = [], [], [], [], []
    for st, _color, frame, is_selected in groups:
        all_units += list(frame["Unit"])
        all_x += list(frame[x_col].astype(float))
        all_y += list(frame[y_col].astype(float))
        all_sizes += [_group_size(st, is_selected)] * len(frame)
        # most severe first; the selected unit ahead of all so it keeps its label
        all_priority += [(len(STATE_SEVERITY) if is_selected else STATE_SEVERITY.get(normalize_state(st), -1))] * len(frame)
    placements = dict(zip(all_units, place_labels(
        all_x, all_y, all_sizes, all_units, (x0, x1), (y0, y1), plot_px, priority=all_priority,
        blocked=caption_boxes,
    )))

    for st, color, frame, is_selected in groups:
        meter_text, meter_line = _meter_hover(frame["Unit"])
        units = list(frame["Unit"])
        if is_selected:
            template = _t("predictive_charts.hover_fleet_selected", selected_unit=selected_unit)
            marker = dict(color=color, size=_group_size(st, True), line=dict(color=SELECTED_COLOR, width=3), opacity=1.0)
            name = selected_unit
        else:
            template = _t("predictive_charts.hover_fleet")
            marker = dict(color=color, size=_group_size(st, False), line=dict(color="white", width=1.2), opacity=0.85)
            name = status_label(st)
        unit_placements = [placements[u] for u in units]
        fig.add_trace(go.Scatter(
            x=frame[x_col].astype(float),
            y=frame[y_col].astype(float),
            mode="markers+text",
            name=name,
            text=units,
            # [unit, today's, 7-day, 30-day and 90-day ranking]: click-to-Evidence reads the
            # unit from index 0; the tooltip reads the rest (not the plotted x / y)
            customdata=[[u, today.get(u, "—"), r7.get(u, "—"), r30.get(u, "—"), r90.get(u, "—")] for u in units],
            # A label that fits nowhere is left out (blank template) but the point
            # is still drawn; `text` stays for the tooltip and click handler.
            textposition=[p.position if p else _SCATTER_LABEL_ORDER[0] for p in unit_placements],
            texttemplate=["%{text}" if p else "" for p in unit_placements],
            textfont=dict(size=[p.font_px if p else LABEL_FONT_PX for p in unit_placements], color=LABEL_COLOR),
            cliponaxis=False,
            marker=marker,
            hovertext=meter_text,
            hovertemplate=_hover_template(template, meter_line),
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=height,
        margin=dict(l=60, r=20, t=20, b=50),
        showlegend=False,
        xaxis=dict(
            title=x_title,
            showgrid=True, gridcolor="rgba(0,0,0,0.05)",
            zeroline=False, tickfont=dict(size=10), range=[x0, x1]
        ),
        yaxis=dict(
            title=y_title,
            showgrid=True, gridcolor="rgba(0,0,0,0.05)",
            zeroline=False, tickfont=dict(size=10), range=[y0, y1]
        ),
        hovermode="closest",
    )

    return fig


# Terminal-point labels prefer the right of the point (the line's own end); the
# right margin below leaves room for them.
_LONG_LABEL_ORDER = (
    "middle right", "top center", "bottom center", "middle left",
    "top right", "bottom right", "top left", "bottom left",
)
_LONG_RIGHT_MARGIN_PX = 70


def _long_view_band(active, df):
    """(hours, media, umbral) of the fleet reference band. Prefers the `banda`
    metadata the curve reader keeps (the exact grid the classification used);
    falls back to the per-row `banda_media`/`banda_umbral`, which are the same
    function of hours. None when neither exists."""
    banda = (getattr(active, "attrs", None) or {}).get("banda") or {}
    try:
        grid = np.asarray(banda["grid"], dtype=float)
        media = np.asarray(banda["media"], dtype=float)
        umbral = np.asarray(banda["umbral"], dtype=float)
        if grid.size and grid.size == media.size == umbral.size:
            return grid, media, umbral
    except (KeyError, TypeError, ValueError):
        pass
    if {"banda_media", "banda_umbral"}.issubset(df.columns):
        pts = (df[["componentHours_filled", "banda_media", "banda_umbral"]]
               .dropna().drop_duplicates(subset=["componentHours_filled"])
               .sort_values("componentHours_filled"))
        if not pts.empty:
            return (pts["componentHours_filled"].to_numpy(dtype=float),
                    pts["banda_media"].to_numpy(dtype=float),
                    pts["banda_umbral"].to_numpy(dtype=float))
    return None


def _long_view_alert_fraction(active):
    """Where the Normal/Alerta edge sits between `media` and `umbral`:
    K_ALERTA / K_SIGMA of the way, i.e. median + K_ALERTA*sigma given that
    `umbral` = median + K_SIGMA*sigma. Both come from the curve's `config`
    (upstream defaults 1 and 2 -> one sigma, halfway) when it did not survive."""
    config = (getattr(active, "attrs", None) or {}).get("config") or {}
    try:
        k_sigma, k_alerta = float(config.get("K_SIGMA", 2.0)), float(config.get("K_ALERTA", 1.0))
    except (TypeError, ValueError):
        return 0.5
    if not (k_sigma > 0 and 0 < k_alerta <= k_sigma):
        return 0.5
    return k_alerta / k_sigma


def create_empty_selection_figure(message_key="predictive_charts.selection_empty"):
    """A blank chart (no points, no axes) saying that no unit is selected - what an
    empty unit selection shows on either chart. Never a fallback to the whole fleet.
    `message_key` swaps the message (the Short View's "axes not configured" case)."""
    message = _t(message_key)
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        margin=dict(l=70, r=_LONG_RIGHT_MARGIN_PX, t=20, b=50), showlegend=False,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        annotations=[dict(
            text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5,
            font=dict(size=13, color="#6C7280", family="DM Sans, sans-serif"),
        )],
    )
    return fig


def create_long_view_chart(active, selected_units=None):
    """Long View: ranking acumulado ajustado vs horas de componente.

    `active` is `predictive_v2.load_active_cycle_curve` (active-cycle rows only,
    `attrs["banda"]` kept). `selected_units` limits which units are drawn:
    None draws every unit, a list draws exactly those, and an EMPTY list draws an
    empty chart - an empty selection never falls back to the fleet. Both axes
    auto-fit to the units drawn.

    One series per drawn unit: the connecting line is its whole active cycle. Line
    and end dot share one color rule - green Normal, yellow Alerta, red Anormal,
    by `cumulative_risk_curve.estado` of the unit's current (last) row - so two
    units in the same state look alike and are told apart by their gray label,
    which sits at the end dot where it fits (smaller where crowded, omitted where
    even that would crowd; never a connector line). The dot is sized Anormal 1.5x,
    Alerta 1.2x, Normal 1x. The background shades the fleet reference band
    (Normal below median + 1 sigma, Alerta up to median + 2 sigma, Anormal above)
    in the same colors and is independent of the
    units' own `estado`. None when `active` has nothing to plot at all.

    The height is left to the container (General sizes it 2.5:1).
    """
    if active is None or active.empty:
        return None
    df = (active.dropna(subset=["componentHours_filled", "ranking_acumulado_ajustado"])
          .sort_values(["Unit", "Fecha", "componentHours_filled"]))
    if df.empty:
        return None
    if selected_units is not None:
        df = df[df["Unit"].isin(set(selected_units))]
        if df.empty:
            return create_empty_selection_figure()

    x_max = float(df["componentHours_filled"].max())
    y_max = float(df["ranking_acumulado_ajustado"].max())
    x_up = max(math.ceil(x_max / 100.0) * 100.0, 100.0)
    y_up = max(math.ceil(y_max * 1.06 / 100.0) * 100.0, 100.0)

    fig = go.Figure()
    annotations = []

    # ── Reference band: three zones, then the Alerta/Anormal edges ──
    band = _long_view_band(active, df)
    if band is not None:
        grid, media, umbral = band
        order = np.argsort(grid)
        grid, media, umbral = grid[order], media[order], umbral[order]
        if grid[-1] < x_up:  # hold the last band value out to the axis end
            grid = np.append(grid, x_up)
            media, umbral = np.append(media, media[-1]), np.append(umbral, umbral[-1])
        # Normal < median + 1 sigma <= Alerta < median + 2 sigma (= umbral) <= Anormal
        alerta = media + _long_view_alert_fraction(active) * (umbral - media)
        alerta_c, umbral_c = np.minimum(alerta, y_up), np.minimum(umbral, y_up)
        loop_x = np.concatenate([grid, grid[::-1]])
        for zone, lower, upper in (
            ("Normal", np.zeros_like(grid), alerta_c),
            ("Alerta", alerta_c, umbral_c),
            ("Anormal", umbral_c, np.full_like(grid, y_up)),
        ):
            fig.add_trace(go.Scatter(
                x=loop_x, y=np.concatenate([upper, lower[::-1]]), mode="lines",
                fill="toself", fillcolor=STATE_ZONE_FILL[zone], line=dict(width=0),
                hoverinfo="skip", showlegend=False,
            ))
        fig.add_trace(go.Scatter(
            x=grid, y=alerta_c, mode="lines", hoverinfo="skip", showlegend=False,
            line=dict(color="rgba(17,24,39,0.55)", width=1.4, dash="dash"),
        ))
        fig.add_trace(go.Scatter(
            x=grid, y=umbral_c, mode="lines", hoverinfo="skip", showlegend=False,
            line=dict(color="rgba(200,60,40,0.6)", width=1.2, dash="dot"),
        ))
        for zone, x_frac, y_of in (
            ("Anormal", 0.12, lambda xv: np.interp(xv, grid, umbral_c) + (y_up - np.interp(xv, grid, umbral_c)) * 0.6),
            ("Alerta", 0.85, lambda xv: (np.interp(xv, grid, alerta_c) + np.interp(xv, grid, umbral_c)) / 2),
            ("Normal", 0.85, lambda xv: np.interp(xv, grid, alerta_c) * 0.25),
        ):
            xv = x_up * x_frac
            annotations.append(dict(
                x=xv, y=float(y_of(xv)), xref="x", yref="y", text=status_label(zone),
                showarrow=False, font=dict(size=11, color=STATE_ZONE_TEXT[zone], family="DM Sans, sans-serif"),
                bgcolor="rgba(255,255,255,0.6)", borderpad=3,
            ))

    # ── Units: severe ones last so they draw on top ──
    series = {unit: g for unit, g in df.groupby("Unit", sort=True)}
    terminal = {  # where each unit stands now: its last row
        unit: (float(g["componentHours_filled"].iloc[-1]),
               float(g["ranking_acumulado_ajustado"].iloc[-1]),
               normalize_state(g["estado"].iloc[-1]))
        for unit, g in series.items()
    }
    units = list(series)
    sizes = {u: state_marker_size(terminal[u][2], SCATTER_BASE_MARKER) for u in units}
    # Plot area the label placement assumes: General's 2.5:1 chart at ~1100px wide.
    placements = dict(zip(units, place_labels(
        [terminal[u][0] for u in units], [terminal[u][1] for u in units],
        [sizes[u] for u in units], units, (0.0, x_up), (0.0, y_up), (960, 370),
        priority=[STATE_SEVERITY.get(terminal[u][2], -1) for u in units],
        order=_LONG_LABEL_ORDER, bleed_px=(0, _LONG_RIGHT_MARGIN_PX, 0, 0),
    )))
    estado_text = {e: status_label(e) for e in df["estado"].dropna().unique()}
    for unit in sorted(units, key=lambda u: (STATE_SEVERITY.get(terminal[u][2], -1), u)):
        g = series[unit]
        x_last, y_last, state = terminal[unit]
        state_color = STATE_COLORS.get(state, "#6b7280")
        n = len(g)
        fig.add_trace(go.Scatter(
            # Rounded to what the tooltip shows (whole hours' tenths / whole ranking):
            # the active curves are ~16k points, so full-precision floats double the payload.
            x=g["componentHours_filled"].round(1), y=g["ranking_acumulado_ajustado"].round(0),
            mode="lines+markers", name=unit,
            line=dict(color=_hex_to_rgba(state_color, 0.85), width=1.6),
            # Only the current point is drawn (and labeled, below), in the state's
            # color and size; the earlier rows are the line's vertices and stay hoverable.
            marker=dict(color=state_color, size=[0] * (n - 1) + [sizes[unit]],
                        line=dict(color="white", width=1.2), opacity=1),
            cliponaxis=False,
            customdata=g["estado"].map(estado_text).fillna("—").tolist(),
            hovertemplate=_t("predictive_charts.long_hover", unit=unit),
        ))
        if placements[unit] is not None:  # a label that fits nowhere is left out, the dot stays
            annotations.append(_label_annotation(unit, x_last, y_last, placements[unit]))

    fig.update_layout(
        annotations=annotations,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        margin=dict(l=70, r=_LONG_RIGHT_MARGIN_PX, t=20, b=50),
        showlegend=False,
        hovermode="closest",
        xaxis=dict(
            title=_t("predictive_charts.long_x_axis"),
            showgrid=True, gridcolor="rgba(0,0,0,0.05)", zeroline=False,
            tickfont=dict(size=10), range=[0, x_up], rangemode="tozero",
        ),
        yaxis=dict(
            title=_t("predictive_charts.long_y_axis"),
            showgrid=True, gridcolor="rgba(0,0,0,0.05)", zeroline=False,
            tickfont=dict(size=10), range=[0, y_up], rangemode="tozero",
        ),
    )
    return fig


def create_comparative_bars(unit_row, df_latest, failure_modes):
    """
    Crear gráfico de barras horizontales comparativas para modos de falla.
    Reemplaza el radar por mejor legibilidad.
    """
    fm_keys = list(failure_modes.keys())
    fm_labels = [failure_modes[k] for k in fm_keys]
    
    # Valores del equipo seleccionado (7-day means, the Calendario de estado's window)
    unit_vals = [
        float(unit_row[f"{k}_7d"]) if f"{k}_7d" in unit_row.index and pd.notna(unit_row[f"{k}_7d"]) else 0.0
        for k in fm_keys
    ]

    # Valores promedio de la flota (7-day means)
    fleet_vals = [
        float(df_latest[f"{k}_7d"].mean()) if f"{k}_7d" in df_latest.columns else 0.0
        for k in fm_keys
    ]
    
    # Crear dataframe para ordenar por valor de unidad (descendente)
    data = pd.DataFrame({
        'mode': fm_labels,
        'unit': unit_vals,
        'fleet': fleet_vals,
        'diff': [u - f for u, f in zip(unit_vals, fleet_vals)]
    })
    data = data.sort_values('unit', ascending=True)  # True para que el mayor quede arriba
    
    fig = go.Figure()
    
    # Barra: Promedio flota
    fig.add_trace(go.Bar(
        y=data['mode'],
        x=data['fleet'],
        name=_t("predictive_charts.promedio_flota"),
        orientation='h',
        marker=dict(color='rgba(0,0,0,0.15)'),
        hovertemplate=_t("predictive_charts.b_b_br_promedio_flota_extra"),
    ))
    
    # Barra: Unidad seleccionada
    fig.add_trace(go.Bar(
        y=data['mode'],
        x=data['unit'],
        name=unit_row["Unit"],
        orientation='h',
        marker=dict(color='#2563EB'),
        hovertemplate='<b>%{y}</b><br>' + unit_row["Unit"] + ': %{x:.1f}<extra></extra>',
    ))
    
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        margin=dict(l=20, r=20, t=20, b=40),
        height=380,
        barmode='group',
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        xaxis=dict(
            title=_t("predictive_charts.score_de_riesgo_por_modo_de"),
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            zeroline=True,
            zerolinecolor="rgba(0,0,0,0.2)",
            tickfont=dict(size=10),
        ),
        yaxis=dict(
            showgrid=False,
            tickfont=dict(size=10),
        ),
    )
    
    return fig


# Four-band criticidad classification, the same one `mode_failure_analisis`
# uses for every client (lower bound inclusive): Saludable <35, Monitoreo
# 35-55, Prioridad alta 55-75, Crítico >=75. Index == band code in the heatmap.
CRITICIDAD_BANDS = [
    ("Saludable", "#1d9e75"),
    ("Monitoreo", "#f2d04b"),
    ("Prioridad alta", "#ef7f27"),
    ("Crítico", "#e24b4a"),
]
_CRITICIDAD_EDGES = (35.0, 55.0, 75.0)
_BAND_LABEL_KEYS = (
    "predictive_charts.band_healthy",
    "predictive_charts.band_monitoring",
    "predictive_charts.band_high_priority",
    "predictive_charts.band_critical",
)


def _band_label(index: int) -> str:
    """Display label of band `index` of CRITICIDAD_BANDS (which holds the Spanish source text)."""
    return _t(_BAND_LABEL_KEYS[index])


_NO_DATA_CODE = len(CRITICIDAD_BANDS)
_NO_DATA_COLOR = "#e5e7eb"

_WEAR_PALETTE = ["#2563EB", "#E24B4A", "#1D9E75", "#7C3AED", "#EF9F27", "#0891B2"]


_THRESHOLDS_DIR = Path(__file__).resolve().parents[2] / "config" / "umbrales_criticidad"
_MEAN_WINDOW_DAYS = 7


@lru_cache(maxsize=8)
def _load_mode_thresholds(client_key: str) -> dict:
    """{mode: (p75, p90, p98)} from config/umbrales_criticidad/<client>.json
    (the `umbrales_criticidad` dictionary written by the calibration script),
    or {} when the client has no file or it can't be parsed. Edges are the
    lower bounds of Monitoreo / Prioridad alta / Crítico."""
    if not client_key:
        return {}
    path = _THRESHOLDS_DIR / f"{client_key}.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("No se pudo leer %s", path)
        return {}
    modes = (data.get("umbrales_criticidad", data) or {}).get("modos") or {}
    edges = {}
    for mode, v in modes.items():
        try:
            e = (float(v["p75"]), float(v["p90"]), float(v["p98"]))
        except (KeyError, TypeError, ValueError):
            continue
        if e[0] <= e[1] <= e[2]:
            edges[mode] = e
    return edges


def get_mode_thresholds(client) -> dict:
    """Calibrated criticidad edges per failure mode for `client` ({} if none)."""
    return _load_mode_thresholds((client or "").lower())


def classify_criticidad(value, edges=_CRITICIDAD_EDGES):
    """Band index (0..3) of a risk score, or None when there is no score -
    a missing day is "no data", never implicitly Saludable. `edges` are the
    lower bounds of bands 1..3 (the fixed 35/55/75 unless a mode is calibrated)."""
    if value is None or pd.isna(value):
        return None
    return sum(float(value) >= edge for edge in edges)


def create_mode_status_calendar(df_unit, failure_modes, end_date, days=90, client=None):
    """Calendar heatmap: one row per failure mode, one column per day over the
    `days` days ending at `end_date`, coloured by the criticidad band of that
    day's value. `df_unit` is the unit's wide risk frame (Fecha + one column
    per mode); a mode/day with no value renders as "Sin datos".

    A mode with calibrated thresholds for `client` (config/umbrales_criticidad)
    is classified on its trailing 7-day mean - the series the P75/P90/P98 edges
    were computed on - against its own edges. Any other mode keeps the daily
    `risk_value` against the fixed 35/55/75 bands. A day without a reading stays
    "Sin datos" in both cases, so the mean never paints a day the unit skipped.
    Dotted vertical lines mark each Monday (week start).
    """
    if df_unit is None or df_unit.empty or end_date is None:
        return None
    modes = [k for k in failure_modes if k in df_unit.columns]
    if not modes:
        return None

    end = pd.Timestamp(end_date).normalize()
    dates = pd.date_range(end=end, periods=days, freq="D")
    unit_days = (
        df_unit.assign(Fecha=pd.to_datetime(df_unit["Fecha"]).dt.normalize())
        .drop_duplicates(subset="Fecha", keep="last")
        .set_index("Fecha")
    )
    daily = unit_days.reindex(dates)[modes]
    # The mean needs the days before the window too; calendar days, so a gap
    # lowers the divisor instead of stretching the mean over older readings.
    lead = pd.date_range(end=end, periods=days + _MEAN_WINDOW_DAYS - 1, freq="D")
    mean_7d = unit_days.reindex(lead)[modes].rolling(_MEAN_WINDOW_DAYS, min_periods=1).mean().reindex(dates)
    thresholds = get_mode_thresholds(client)
    # Worst mode on top: order by mean over the window, ties by catalogue order.
    order = sorted(modes, key=lambda m: (-(daily[m].mean() if daily[m].notna().any() else -1.0), modes.index(m)))

    z, hover = [], []
    for m in order:
        edges = thresholds.get(m)
        series = mean_7d[m].where(daily[m].notna()) if edges else daily[m]
        row_z, row_h = [], []
        for d, v in zip(dates, series):
            band = classify_criticidad(v, edges or _CRITICIDAD_EDGES)
            row_z.append(_NO_DATA_CODE if band is None else band)
            if band is None:
                row_h.append(_t("predictive_charts.sin_datos", d=d))
            elif edges:
                row_h.append(_t("predictive_charts.hover_mean_7d", d=d, v=float(v), band=_band_label(band)))
            else:
                row_h.append(f"{d:%d %b %Y}: {float(v):.1f} · {_band_label(band)}")
        z.append(row_z)
        hover.append(row_h)

    # Discrete colorscale: code k occupies [k/n, (k+1)/n] with n = bands + no data.
    palette = [c for _, c in CRITICIDAD_BANDS] + [_NO_DATA_COLOR]
    n = len(palette)
    colorscale = []
    for i, c in enumerate(palette):
        colorscale += [[i / n, c], [(i + 1) / n, c]]

    fig = go.Figure(go.Heatmap(
        x=dates, y=[failure_modes[m] for m in order], z=z,
        zmin=-0.5, zmax=n - 0.5,  # each integer code sits mid-bin
        colorscale=colorscale, showscale=False,
        xgap=1, ygap=1,
        text=hover, hovertemplate="<b>%{y}</b><br>%{text}<extra></extra>",
    ))

    # Week starts: the line sits on the left edge of each Monday's cell.
    for d in dates[dates.dayofweek == 0]:
        edge = d - pd.Timedelta(hours=12)
        fig.add_shape(
            type="line", xref="x", yref="paper", x0=edge, x1=edge, y0=0, y1=1,
            line=dict(color="rgba(0,0,0,0.45)", width=1, dash="dot"), layer="above",
        )

    # Legend: heatmaps have none, so one empty marker trace per band.
    for label, color in [*[(_band_label(i), c) for i, (_, c) in enumerate(CRITICIDAD_BANDS)], (_t("oil_machine_detail.sin_datos"), _NO_DATA_COLOR)]:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name=label, hoverinfo="skip",
            marker=dict(symbol="square", size=10, color=color),
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=380,
        margin=dict(l=20, r=20, t=20, b=60),
        showlegend=True,
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5, font=dict(size=10)),
        xaxis=dict(
            showgrid=False, zeroline=False, tickfont=dict(size=10), tickformat="%d %b",
            range=[dates[0] - pd.Timedelta(hours=12), dates[-1] + pd.Timedelta(hours=12)],
        ),
        yaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=10), autorange="reversed"),
    )
    return fig


def create_accumulated_wear_chart(df_meter, metal_suffix="_acum_total"):
    """Cumulative wear curves from `oil_meter_history`: one line per wear metal
    (`{Metal}_acum_total`) over `Fecha`. `df_meter` must already be scoped to a
    single component life (see predictive_v2.load_latest_cycle_oil_meter_history),
    so nothing here encodes `ciclo_motor`; each metal only gets its own colour.
    Values are plotted as published - the totals can dip between samples of the
    same oil charge, so there is no smoothing, clipping or monotonic fix-up.
    Returns None when there is nothing to plot.
    """
    if df_meter is None or df_meter.empty:
        return None
    metals = [c for c in df_meter.columns if c.endswith(metal_suffix)]
    if not metals:
        return None

    df = df_meter.sort_values("Fecha")
    fig = go.Figure()
    for i, metal_col in enumerate(metals):
        series = df[["Fecha", metal_col]].dropna(subset=[metal_col])
        if series.empty:
            continue
        fig.add_trace(go.Scatter(
            x=series["Fecha"], y=series[metal_col].astype(float),
            mode="lines", name=metal_col[: -len(metal_suffix)],
            line=dict(width=2, color=_WEAR_PALETTE[i % len(_WEAR_PALETTE)]),
            hovertemplate="%{x|%d %b %Y}<br><b>%{y:.1f}</b><extra></extra>",
        ))
    if not fig.data:
        return None

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=360,
        margin=dict(l=60, r=24, t=30, b=50),
        showlegend=True,
        hovermode="x unified",
        xaxis=dict(title="", showgrid=False, zeroline=False, tickfont=dict(size=10), tickformat="%b %Y"),
        yaxis=dict(title=_t("predictive_charts.desgaste_acumulado_ppm"), showgrid=True, gridcolor="rgba(0,0,0,0.05)",
                   zeroline=False, tickfont=dict(size=10)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def create_radar_comparison(unit_row, df_latest, failure_modes):
    """
    Crear gráfico radar comparando el equipo seleccionado vs promedio de la flota.
    """
    fm_labels = [failure_modes[k] for k in failure_modes.keys()]
    fm_keys = list(failure_modes.keys())

    # Valores del equipo seleccionado (use 30d averages for consistency)
    fm_vals = [
        float(unit_row[f"{k}_30d"]) if f"{k}_30d" in unit_row.index and pd.notna(unit_row[f"{k}_30d"]) else 0.0
        for k in fm_keys
    ]

    # Valores promedio de la flota (use 30d averages)
    avg_vals = [
        float(df_latest[f"{k}_30d"].mean()) if f"{k}_30d" in df_latest.columns else 0.0
        for k in fm_keys
    ]

    # Cerrar el polígono
    fm_labels_closed = fm_labels + [fm_labels[0]]
    fm_vals_closed = fm_vals + [fm_vals[0]]
    avg_vals_closed = avg_vals + [avg_vals[0]]

    fig = go.Figure()

    # Promedio de la flota
    fig.add_trace(go.Scatterpolar(
        r=avg_vals_closed,
        theta=fm_labels_closed,
        fill="toself",
        name=_t("predictive_charts.promedio_flota"),
        line=dict(color="rgba(0,0,0,0.15)", width=1),
        fillcolor="rgba(0,0,0,0.04)",
    ))

    # Equipo seleccionado
    fig.add_trace(go.Scatterpolar(
        r=fm_vals_closed,
        theta=fm_labels_closed,
        fill="toself",
        name=unit_row["Unit"],
        line=dict(color="#2563EB", width=2),
        fillcolor="rgba(37,99,235,0.12)",
    ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=10, color="#6C7280"),
        margin=dict(l=40, r=40, t=40, b=40),
        height=320,
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                tickfont=dict(size=9),
                gridcolor="rgba(0,0,0,0.08)",
                linecolor="rgba(0,0,0,0.08)",
            ),
            angularaxis=dict(
                tickfont=dict(size=10),
                gridcolor="rgba(0,0,0,0.08)",
                linecolor="rgba(0,0,0,0.08)",
            ),
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=-0.15,
            xanchor="center", x=0.5,
            font=dict(size=10),
        ),
        showlegend=True,
    )

    return fig


def create_oil_timeseries_90d(df_unit, variables, oil_labels, oil_limits_four=None, oil_range=None):
    """
    Crear serie temporal de variables de aceite.
    Ventana: max(últimos 90 días, últimas 3 muestras reales).
    Usa sampleDate como identificador de muestra real.

    Si hay 1 sola variable y existen límites, muestra líneas de límite
    (fuente: stewart_limits_four.parquet, LIC/LIM/LSM/LSC - contrato v2.8).
    """

    if not variables:
        return None

    date_col = _oil_date_col(df_unit)
    df_sorted = df_unit.sort_values(date_col)
    if df_sorted.empty:
        return None
    
    # Calcular ventana de 90 días
    fecha_fin = pd.to_datetime(df_sorted[date_col].max())
    fecha_inicio_90d = fecha_fin - pd.Timedelta(days=90)
    
    # Identificar últimas 3 muestras REALES (deduplicar por fecha de muestra)
    muestras_reales = df_sorted.drop_duplicates(subset=[date_col], keep="last").sort_values(date_col)
    
    if len(muestras_reales) >= 3:
        # Tomar las últimas 3 muestras reales
        ultimas_3_muestras = muestras_reales.tail(3)
        fecha_inicio_3_muestras = pd.to_datetime(ultimas_3_muestras[date_col].min())
        
        # Ventana final: lo que cubra más hacia atrás
        fecha_inicio = min(fecha_inicio_90d, fecha_inicio_3_muestras)
    else:
        # Si hay menos de 3 muestras, usar todas las disponibles
        fecha_inicio = pd.to_datetime(muestras_reales[date_col].min()) if not muestras_reales.empty else fecha_inicio_90d
    
    # Filtrar datos con la ventana expandida
    df_filtered = df_sorted[pd.to_datetime(df_sorted[date_col]) >= fecha_inicio]
    
    if df_filtered.empty:
        return None
    
    fig = go.Figure()

    show_limits = (len(variables) == 1 and oil_limits_four and oil_range is not None)

    for var in variables:
        if var not in df_filtered.columns:
            continue

        series = df_filtered[[date_col, var]].dropna(subset=[var])
        if series.empty:
            continue

        x_dates = pd.to_datetime(series[date_col])
        y_values = series[var].astype(float)

        # Main trace: values
        fig.add_trace(go.Scatter(
            x=x_dates,
            y=y_values,
            mode="lines+markers",
            name=oil_labels.get(var, var),
            line=dict(width=2),
            marker=dict(size=6),
            hovertemplate="%{x|%d %b %Y}<br><b>%{y:.2f}</b><extra></extra>",
        ))

        # Threshold lines (only for single variable mode) - four-limit Stewart
        # output (LIC/LIM/LSM/LSC, v2.8). Equal/near-equal limits are
        # consolidated into one line with a user-friendly label, null lower
        # limits are never plotted, and lower-limit lines use the shared
        # purple color - same helpers as every other oil chart in the app.
        if show_limits:
            essay_limits = get_essay_limits_four(oil_limits_four, var, oil_range)
            if essay_limits:
                feature_label = oil_labels.get(var, var)
                tier_entries = [
                    {'value': essay_limits.get('LIC'), 'tier': 'LIC', 'feature': feature_label},
                    {'value': essay_limits.get('LIM'), 'tier': 'LIM', 'feature': feature_label},
                    {'value': essay_limits.get('LSM'), 'tier': 'LSM', 'feature': feature_label},
                    {'value': essay_limits.get('LSC'), 'tier': 'LSC', 'feature': feature_label},
                ]
                if essay_limits.get('LIC') is None or essay_limits.get('LIM') is None:
                    tier_entries = [e for e in tier_entries if e['tier'] not in ('LIC', 'LIM')]

                x_range = [x_dates.min(), x_dates.max()]
                for line in consolidate_limit_entries(tier_entries):
                    fig.add_trace(go.Scatter(
                        x=x_range, y=[line['value'], line['value']],
                        mode="lines", name=line['label'],
                        line=dict(width=1.5, dash="dot", color=limit_line_color(line['tiers'])),
                        hoverinfo="skip",
                    ))
    
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=320,
        margin=dict(l=60, r=24, t=24, b=50),
        showlegend=True,
        hovermode="x unified",
        xaxis=dict(
            title="",
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=10),
            tickformat="%d %b",
        ),
        yaxis=dict(
            title=_t("alerts_charts.valor"),
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            zeroline=False,
            tickfont=dict(size=10),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )
    
    return fig


def create_oil_timeseries(df_unit, variables, oil_labels):
    """
    Crear serie temporal de variables de aceite.
    """
    if not variables:
        return None

    date_col = _oil_date_col(df_unit)
    fig = go.Figure()

    for var in variables:
        if var not in df_unit.columns:
            continue

        series = df_unit[[date_col, var]].dropna(subset=[var])
        if series.empty:
            continue

        fig.add_trace(go.Scatter(
            x=pd.to_datetime(series[date_col]),
            y=series[var].astype(float),
            mode="lines+markers",
            name=oil_labels.get(var, var),
            line=dict(width=2),
            marker=dict(size=6),
            hovertemplate="%{x|%d %b %Y}<br><b>%{y:.2f}</b><extra></extra>",
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=320,
        margin=dict(l=60, r=24, t=24, b=50),
        showlegend=True,
        hovermode="x unified",
        xaxis=dict(
            title="",
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=10),
            tickformat="%b %Y",
        ),
        yaxis=dict(
            title=_t("alerts_charts.valor"),
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            zeroline=False,
            tickfont=dict(size=10),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    return fig


def create_telemetry_signal_chart(df_unit, signal, telemetry_labels):
    """
    Crear gráfico individual para una señal de telemetría.
    Muestra alert_rate y critic_rate separados.
    """
    # Buscar columnas de alert_rate y critic_rate para esta señal
    alert_cols = [col for col in df_unit.columns if f"_{signal}_alert_rate" in col]
    critic_cols = [col for col in df_unit.columns if f"_{signal}_critic_rate" in col]
    
    if not alert_cols and not critic_cols:
        return None
    
    # Agrupar por fecha y sumar todas las tasas (diferentes modos operacionales)
    df_grouped = df_unit.groupby("Fecha").agg({
        **{col: 'sum' for col in alert_cols},
        **{col: 'sum' for col in critic_cols}
    }).reset_index()
    
    # Calcular tasas totales
    df_grouped['alert_rate_total'] = df_grouped[alert_cols].sum(axis=1) if alert_cols else 0
    df_grouped['critic_rate_total'] = df_grouped[critic_cols].sum(axis=1) if critic_cols else 0
    
    # Normalizar (las tasas están por modo operacional, promediamos)
    if alert_cols:
        df_grouped['alert_rate_total'] = df_grouped['alert_rate_total'] / len(alert_cols)
    if critic_cols:
        df_grouped['critic_rate_total'] = df_grouped['critic_rate_total'] / len(critic_cols)
    
    fig = go.Figure()
    
    # Barras: Alert rate
    if alert_cols:
        fig.add_trace(go.Bar(
            x=df_grouped["Fecha"],
            y=df_grouped["alert_rate_total"],
            name=_t("predictive_charts.alert"),
            marker=dict(color="#ef9f27"),
            hovertemplate=_t("predictive_charts.br_alert_extra_extra"),
        ))
    
    # Barras: Critic rate
    if critic_cols:
        fig.add_trace(go.Bar(
            x=df_grouped["Fecha"],
            y=df_grouped["critic_rate_total"],
            name=_t("erp.severity.critical"),
            marker=dict(color="#e24b4a"),
            hovertemplate=_t("predictive_charts.br_critico_extra_extra"),
        ))
    
    signal_label = telemetry_labels.get(signal, signal)
    
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=250,
        margin=dict(l=60, r=24, t=40, b=50),
        showlegend=True,
        barmode="stack",
        title=dict(
            text=signal_label,
            font=dict(size=13, weight="bold"),
            x=0,
            xanchor="left",
        ),
        xaxis=dict(
            title="",
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=10),
            tickformat="%d %b",
        ),
        yaxis=dict(
            title=_t("predictive_charts.tasa"),
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            zeroline=False,
            tickfont=dict(size=10),
            tickformat=".0%",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )
    
    return fig


def create_telemetry_signal_chart_from_long(df_signal, signal, telemetry_labels):
    """
    Data Contract v2.0 (Change 2) equivalent of create_telemetry_signal_chart,
    reading `telemetry/signal_daily_status` (Unit, Fecha, signal_name,
    pct_time_alert, pct_time_critical) - one row per unit/day/signal,
    filtered by row instead of pattern-matching wide column names. No
    per-operational-mode summing needed: the new table is already the daily
    total per signal.

    `df_signal` must already be filtered to the selected unit; this filters
    it to `signal` and plots `pct_time_alert`/`pct_time_critical` by Fecha.
    """
    if df_signal is None or df_signal.empty or "signal_name" not in df_signal.columns:
        return None

    df_sig = df_signal[df_signal["signal_name"] == signal].sort_values("Fecha")
    if df_sig.empty:
        return None

    has_alert = "pct_time_alert" in df_sig.columns and df_sig["pct_time_alert"].notna().any()
    has_critical = "pct_time_critical" in df_sig.columns and df_sig["pct_time_critical"].notna().any()
    if not has_alert and not has_critical:
        return None

    fig = go.Figure()

    if has_alert:
        fig.add_trace(go.Bar(
            x=df_sig["Fecha"],
            y=df_sig["pct_time_alert"] / 100.0,
            name=_t("predictive_charts.alert"),
            marker=dict(color="#ef9f27"),
            hovertemplate=_t("predictive_charts.br_alert_extra_extra"),
        ))
    if has_critical:
        fig.add_trace(go.Bar(
            x=df_sig["Fecha"],
            y=df_sig["pct_time_critical"] / 100.0,
            name=_t("erp.severity.critical"),
            marker=dict(color="#e24b4a"),
            hovertemplate=_t("predictive_charts.br_critico_extra_extra"),
        ))

    signal_label = telemetry_labels.get(signal, signal)

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=250,
        margin=dict(l=60, r=24, t=40, b=50),
        showlegend=True,
        barmode="stack",
        title=dict(
            text=signal_label,
            font=dict(size=13, weight="bold"),
            x=0,
            xanchor="left",
        ),
        xaxis=dict(
            title="",
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=10),
            tickformat="%d %b",
        ),
        yaxis=dict(
            title=_t("predictive_charts.tiempo"),
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            zeroline=False,
            tickfont=dict(size=10),
            tickformat=".0%",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    return fig


def create_telemetry_alerts_timeseries(df_unit, telemetry_vars, telemetry_labels):
    """
    Crear serie temporal de alertas de telemetría.
    Cuenta alertas por fecha para las variables especificadas.
    """
    if not telemetry_vars:
        return None

    # Preparar datos de alertas
    alert_data = []

    for var in telemetry_vars:
        # Buscar columnas de alertas para esta variable
        for col in df_unit.columns:
            if f"_{var}_alert_rate" in col or f"_{var}_critic_rate" in col:
                series = df_unit[["Fecha", col]].dropna(subset=[col])
                if not series.empty:
                    for _, row in series.iterrows():
                        if row[col] > 0:
                            alert_data.append({
                                "Fecha": row["Fecha"],
                                "Variable": telemetry_labels.get(var, var),
                                "Rate": float(row[col])
                            })

    if not alert_data:
        return None

    df_alerts = pd.DataFrame(alert_data)
    
    # Agrupar por fecha y variable
    df_grouped = df_alerts.groupby(["Fecha", "Variable"])["Rate"].sum().reset_index()

    fig = go.Figure()

    for var_label in df_grouped["Variable"].unique():
        subset = df_grouped[df_grouped["Variable"] == var_label]
        fig.add_trace(go.Bar(
            x=subset["Fecha"],
            y=subset["Rate"],
            name=var_label,
            hovertemplate="%{x|%d %b %Y}<br><b>%{y:.2%}</b><extra></extra>",
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=280,
        margin=dict(l=60, r=24, t=24, b=50),
        showlegend=True,
        hovermode="x unified",
        barmode="stack",
        xaxis=dict(
            title="",
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=10),
            tickformat="%b %Y",
        ),
        yaxis=dict(
            title=_t("predictive_charts.tasa_de_alertas"),
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            zeroline=False,
            tickfont=dict(size=10),
            tickformat=".0%",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    return fig