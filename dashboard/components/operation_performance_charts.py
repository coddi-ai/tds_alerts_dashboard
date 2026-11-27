"""Figures of Monitoreo > Operación y rendimiento (one function per panel of the OP-PE specification).

Pure functions: DataFrames in, a Plotly figure out (the data rules live in
src/data/operation_performance.py). Titles and "how to read" notes are rendered by the panel card
around each figure (dashboard/components/operation_performance_views.py), so figures carry no title.

On the page today: ranking, fleet map (demand + performance), ramp boxes (Flota view); curve, the
unit's weeks and the unit-vs-fleet map (Evidencia por unidad view). The diagnosis (causes, lost minutes,
power, exhaust), trend, descent (retarder, brakes) and data-quality figures are off the page for now
and kept here, tested, to be brought back.

Colors: a truck's decision takes the dashboard's one severity scale (shared/severity.py); the
probable causes take a validated categorical order (CAUSE_COLORS), with the causes that do not
point at the engine in neutral gray. Data values (decisions, causes, unit ids) are never translated.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from shared.severity import SEVERITY_TIERS
from src.charts.theme import BRAND_AXIS, BRAND_GRID, BRAND_MUTED, BRAND_TITLE, FONT_FAMILY, SEQUENTIAL_SCALE
from src.data import operation_performance as op
from src.i18n import current_language, t

# Categorical order for identities with no status meaning (engine causes, highlighted trucks).
# Validated with the dataviz palette checker (lightness band, chroma floor, CVD and normal-vision
# separation, contrast on white): keep the order when adding a slot.
CAUSE_COLORS = ("#2471a3", "#a04000", "#7d3c98", "#138d75", "#922b21")
# Units highlighted together over the manufacturer curve: one categorical hue each, never cycled.
MAX_CURVE_UNITS = len(CAUSE_COLORS)
NEUTRAL_MARK = "#a3acb9"          # "no engine cause", the rest of the fleet, "Sin datos suficientes"
INK = BRAND_TITLE
LOADED_COLOR, EMPTY_COLOR = CAUSE_COLORS[1], CAUSE_COLORS[0]
DIVERGING_SCALE = [[0.0, CAUSE_COLORS[0]], [0.5, "#f1f5f9"], [1.0, "#c2410c"]]


# ------------------------------------------------------------------------------------------------
# Shared look
# ------------------------------------------------------------------------------------------------

def separators() -> str:
    """Decimal comma in Spanish (as the specification asks), decimal point in English."""
    return ".," if current_language() == "en" else ",."


def fmt(value, decimals: int = 2) -> str:
    """A number with the current language's separators; "—" for missing."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    text = f"{value:,.{decimals}f}"
    if current_language() != "en":
        text = text.replace(",", " ").replace(".", ",").replace(" ", ".")
    return text


def decision_color(decision) -> str:
    tier = op.DECISION_TIER.get(decision)
    return SEVERITY_TIERS[tier]["fill"] if tier else NEUTRAL_MARK


def _axis(title: Optional[str] = None, **extra) -> dict:
    axis = {"gridcolor": BRAND_GRID, "linecolor": BRAND_AXIS, "zerolinecolor": BRAND_GRID, "automargin": True}
    if title:
        axis["title"] = {"text": title, "font": {"size": 12, "color": INK}}
    axis.update(extra)
    return axis


def _style(fig: go.Figure, *, height: int, x: Optional[str] = None, y: Optional[str] = None,
           legend: bool = True, xaxis: Optional[dict] = None, yaxis: Optional[dict] = None) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        separators=separators(),
        font={"family": FONT_FAMILY, "size": 12, "color": INK},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        margin={"l": 56, "r": 24, "t": 36 if legend else 16, "b": 48},
        showlegend=legend,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "left", "x": 0, "font": {"size": 11}},
        hovermode="closest",
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": BRAND_AXIS, "font": {"size": 12, "family": FONT_FAMILY}},
        xaxis=_axis(x, **(xaxis or {})),
        yaxis=_axis(y, **(yaxis or {})),
    )
    return fig


def empty_figure(message: str, height: int = 260) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper",
                       font={"size": 14, "color": BRAND_MUTED})
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _style(fig, height=height, legend=False)


def _present_decisions(values: Iterable) -> List[str]:
    present = set(values)
    return [d for d in op.DECISIONS if d in present] + sorted(present - set(op.DECISIONS) - {None})


def _rows_height(n: int, per_row: int = 22, base: int = 110, minimum: int = 300) -> int:
    return max(minimum, per_row * n + base)


def _reference_line(fig: go.Figure, categories: Sequence[str], y: float, name: str) -> None:
    """A horizontal reference across a categorical x axis, named in the legend (never an annotation
    that can sit on top of a box)."""
    if not categories:
        return
    fig.add_trace(go.Scatter(
        x=[categories[0], categories[-1]], y=[y, y], mode="lines", name=name,
        line={"color": INK, "width": 1.5, "dash": "dash"}, hoverinfo="skip",
    ))


def _robust_range(values: pd.Series, pad: float = 0.15) -> Optional[list]:
    """p1-p99 of the values with some margin: one noisy day (few passes) must not flatten every line.
    The full range is one click away (autoscale)."""
    values = pd.to_numeric(values, errors="coerce").dropna()
    if len(values) < 20:
        return None
    low, high = float(values.quantile(0.01)), float(values.quantile(0.99))
    if high <= low:
        return None
    margin = (high - low) * pad
    return [low - margin, high + margin]


def _text(value) -> str:
    return "—" if value is None or (isinstance(value, float) and np.isnan(value)) or value == "" else str(value)


# ------------------------------------------------------------------------------------------------
# Resumen
# ------------------------------------------------------------------------------------------------

def ranking_figure(camiones: Optional[pd.DataFrame], show_fleet: bool = False,
                   selected: Optional[str] = None) -> go.Figure:
    """Relative IV per truck, highest on top, colored by decision; 1,00 and 0,97 marked. The selected
    unit is outlined, its label in bold and pointed at, so the unit under analysis is never lost.
    `customdata[5]` of every bar is its unit id (a click on a bar selects that unit)."""
    if camiones is None or camiones.empty or camiones["iv_rel_p50"].notna().sum() == 0:
        return empty_figure(t("opp.empty.no_ranking"))
    df = camiones.dropna(subset=["iv_rel_p50"]).sort_values("iv_rel_p50").copy()
    df["etiqueta"] = df["unidad"] + ((" · " + df["flota"]) if show_fleet else "")
    hover = (
        "<b>%{y}</b><br>" + t("opp.hover.iv_rel") + " %{x:.3f}<br>" + t("opp.hover.iv_curve")
        + " %{customdata[2]:.3f}<br>" + t("opp.hover.decision") + " %{customdata[0]}<br>"
        + t("opp.hover.cause") + " %{customdata[1]}<br>%{customdata[3]} " + t("opp.hover.climbs")
        + " · %{customdata[4]:.0f} " + t("opp.hover.lost_min") + "<br><i>" + t("opp.hover.click_to_select")
        + "</i><extra></extra>"
    )
    fig = go.Figure()
    for decision in _present_decisions(df["decision"]):
        part = df[df["decision"] == decision]
        is_selected = (part["unidad"] == selected).tolist()
        fig.add_trace(go.Bar(
            x=part["iv_rel_p50"], y=part["etiqueta"], orientation="h", name=decision,
            marker={"color": decision_color(decision),
                    "line": {"color": [INK if s else "rgba(0,0,0,0)" for s in is_selected],
                             "width": [3 if s else 0 for s in is_selected]},
                    "opacity": [1 if (s or not selected) else 0.8 for s in is_selected]},
            text=[fmt(v) for v in part["iv_rel_p50"]], textposition="outside", cliponaxis=False,
            textfont={"size": 12, "color": INK},
            customdata=np.column_stack([
                part["decision"], part["causa_principal"].map(_text), part["iv_p50"],
                part["pasadas_capacidad"], part["min_perdidos_flota"].fillna(0), part["unidad"],
            ]),
            hovertemplate=hover,
        ))
    low, high = float(df["iv_rel_p50"].min()), float(df["iv_rel_p50"].max())
    # Below the bars' value labels, so a "1,00" next to the line stays readable.
    fig.add_vline(x=op.IV_REL_OK, line={"color": INK, "width": 1.5}, layer="below")
    fig.add_vline(x=op.IV_REL_REVIEW, line={"color": decision_color(op.REVISAR), "width": 1.5, "dash": "dot"},
                  layer="below")
    labels = df["etiqueta"].tolist()
    ticktext = [f"<b>▶ {label}</b>" if unit == selected else label for label, unit in zip(labels, df["unidad"])]
    _style(
        fig, height=_rows_height(len(df), per_row=24, base=120), x=t("opp.axis.iv_rel"),
        xaxis={"range": [min(low, op.IV_REL_REVIEW) - 0.02, max(high, op.IV_REL_OK) + 0.04], "side": "top"},
        yaxis={"categoryorder": "array", "categoryarray": labels, "tickvals": labels, "ticktext": ticktext,
               "gridcolor": "rgba(0,0,0,0)", "tickfont": {"size": 12}},
    )
    # No legend: the decision counts above the chart name the colors, each with its word.
    fig.update_layout(bargap=0.22, barmode="overlay", uirevision="opp-ranking", showlegend=False,
                      margin={"l": 56, "r": 24, "t": 56, "b": 24})
    return fig


# ------------------------------------------------------------------------------------------------
# Diagnóstico
# ------------------------------------------------------------------------------------------------

def causes_figure(counts: pd.DataFrame) -> go.Figure:
    """Stacked bars: passes below the fleet per truck, one segment per probable cause."""
    if counts is None or counts.empty:
        return empty_figure(t("opp.empty.no_causes"))
    units = list(dict.fromkeys(counts["unidad"]))
    fig = go.Figure()
    engine_index = 0
    for cause in op.cause_order(counts):
        if op.is_neutral_cause(cause):
            color = NEUTRAL_MARK
        else:
            color = CAUSE_COLORS[engine_index % len(CAUSE_COLORS)]
            engine_index += 1
        part = counts[counts["causa"] == cause]
        fig.add_trace(go.Bar(
            x=part["unidad"], y=part["pasadas"], name=cause,
            marker={"color": color, "line": {"color": "#ffffff", "width": 1}},
            hovertemplate="<b>%{x}</b><br>" + cause + "<br>%{y} " + t("opp.hover.passes") + "<extra></extra>",
        ))
    _style(fig, height=440, x=t("opp.axis.unit"), y=t("opp.axis.passes_below_fleet"),
           xaxis={"categoryorder": "array", "categoryarray": units, "type": "category"})
    fig.update_layout(barmode="stack", bargap=0.3, legend={"traceorder": "normal"})
    return fig


def lost_minutes_figure(camiones: Optional[pd.DataFrame]) -> go.Figure:
    """Bars: minutes lost against the fleet median; diamonds: against the manufacturer curve."""
    if camiones is None or camiones.empty:
        return empty_figure(t("opp.empty.no_trucks"))
    df = camiones.sort_values("min_perdidos_flota", ascending=False)
    units = df["unidad"].tolist()
    fig = go.Figure()
    for decision in _present_decisions(df["decision"]):
        part = df[df["decision"] == decision]
        fig.add_trace(go.Bar(
            x=part["unidad"], y=part["min_perdidos_flota"], name=decision,
            marker={"color": decision_color(decision), "line": {"width": 0}},
            hovertemplate="<b>%{x}</b> · " + decision + "<br>" + t("opp.hover.vs_fleet") + " %{y:.0f} min<extra></extra>",
        ))
    fig.add_trace(go.Scatter(
        x=df["unidad"], y=df["min_perdidos_curva"], mode="markers", name=t("opp.legend.vs_curve"),
        marker={"symbol": "diamond", "size": 9, "color": INK, "line": {"color": "#ffffff", "width": 1}},
        hovertemplate="<b>%{x}</b><br>" + t("opp.hover.vs_curve") + " %{y:.0f} min<extra></extra>",
    ))
    _style(fig, height=420, x=t("opp.axis.unit"), y=t("opp.axis.minutes_week"),
           xaxis={"categoryorder": "array", "categoryarray": units, "type": "category"})
    fig.update_layout(barmode="overlay", bargap=0.3)
    return fig


def power_figure(potencia: Optional[pd.DataFrame]) -> go.Figure:
    """Capstone: sustained engine power per truck, one point per day, nominal 2.500 HP marked."""
    if potencia is None or potencia.empty:
        return empty_figure(t("opp.empty.no_power"))
    anomalous = set(op.anomalous_power_units(potencia))
    order = potencia.groupby("unidad")["potencia_p50_hp"].median().sort_values().index.tolist()
    fig = go.Figure()
    groups = [(fleet, potencia[(potencia["flota"] == fleet) & ~potencia["unidad"].isin(anomalous)])
              for fleet in sorted(potencia["flota"].dropna().unique())]
    groups.append((t("opp.legend.anomalous_signal"), potencia[potencia["unidad"].isin(anomalous)]))
    for index, (name, part) in enumerate(groups):
        if part.empty:
            continue
        is_anomalous = index == len(groups) - 1
        color = SEVERITY_TIERS["alto"]["fill"] if is_anomalous else CAUSE_COLORS[(0, 3, 2)[index % 3]]
        fig.add_trace(go.Box(
            x=part["unidad"], y=part["potencia_p50_hp"], name=name, boxpoints="all", jitter=0.35, pointpos=0,
            marker={"color": color, "size": 6, "opacity": 0.8}, line={"color": color, "width": 1.5},
            fillcolor="rgba(0,0,0,0)",
            customdata=np.column_stack([part["flota"], part["dia"].dt.strftime("%d-%m"), part["potencia_vs_flota"]]),
            hovertemplate="<b>%{x}</b> · %{customdata[0]}<br>%{customdata[1]}: %{y:,.0f} HP<br>"
            + t("opp.hover.vs_fleet") + " %{customdata[2]:.2f}×"
            + ("<br>" + t("opp.hover.anomalous_signal") if is_anomalous else "") + "<extra></extra>",
        ))
    _reference_line(fig, order, op.NOMINAL_ENGINE_HP, t("opp.annotation.nominal_hp"))
    _style(fig, height=460, x=t("opp.axis.unit"), y=t("opp.axis.hp_day"),
           xaxis={"categoryorder": "array", "categoryarray": order, "type": "category"})
    fig.update_layout(boxmode="overlay")
    return fig


def escape_figure(escape: Optional[pd.DataFrame]) -> go.Figure:
    """Capstone: per-cylinder exhaust deviation from the fleet pattern (diverging, fixed +-60 °C)."""
    matrix, suspicious = op.escape_matrix(escape)
    if matrix.empty:
        return empty_figure(t("opp.empty.no_escape"))
    units, cylinders = matrix.index.tolist(), [str(c) for c in matrix.columns]
    fig = go.Figure(go.Heatmap(
        z=matrix.values, x=cylinders, y=units, zmid=0, zmin=-op.ESCAPE_SCALE_C, zmax=op.ESCAPE_SCALE_C,
        colorscale=DIVERGING_SCALE, xgap=1, ygap=1,
        colorbar={"title": {"text": "°C", "side": "top"}, "thickness": 12, "len": 0.6},
        hovertemplate="<b>%{y}</b> · " + t("opp.hover.cylinder") + " %{x}<br>%{z:+.1f} °C "
        + t("opp.hover.vs_fleet_pattern") + "<extra></extra>",
    ))
    cells = suspicious.stack().dropna().reset_index() if not suspicious.empty else pd.DataFrame()
    if not cells.empty:
        cells.columns = ["unidad", "cilindro", "valor"]
        fig.add_trace(go.Scatter(
            x=cells["cilindro"].astype(str), y=cells["unidad"], mode="markers", name=t("opp.legend.suspicious_sensor"),
            marker={"symbol": "x-thin", "size": 11, "color": INK, "line": {"width": 2, "color": INK}},
            customdata=cells["valor"],
            hovertemplate="<b>%{y}</b> · " + t("opp.hover.cylinder") + " %{x}<br>%{customdata:+.0f} °C · "
            + t("opp.hover.dropped_reading") + "<extra></extra>",
        ))
    _style(fig, height=_rows_height(len(units), per_row=20, base=120), x=t("opp.axis.cylinder"),
           legend=not cells.empty,
           xaxis={"type": "category", "showgrid": False},
           yaxis={"autorange": "reversed", "type": "category", "showgrid": False})
    return fig


# ------------------------------------------------------------------------------------------------
# Curva y rampas
# ------------------------------------------------------------------------------------------------

FORCE_TICKS = (5, 10, 15, 20, 30, 40, 60, 80, 100, 150, 200)


def curve_figure(pasadas: Optional[pd.DataFrame], curvas: Optional[pd.DataFrame], model: Optional[str],
                 highlight: Sequence[str] = (), height: int = 500) -> go.Figure:
    """Loaded full-throttle climbs (required force vs real speed) over the model's propulsion curve."""
    climbs = op.base_climbs(pasadas)
    if model:
        climbs = climbs[climbs["modelo"] == model]
    if climbs.empty:
        return empty_figure(t("opp.empty.no_climbs"))
    curve = pd.DataFrame()
    if curvas is not None and not curvas.empty:
        curve = curvas[(curvas["modelo"] == model) & (curvas["tipo"] == "propulsión")]
    climbs = climbs.dropna(subset=["v_kmh", "fuerza_req_t"])
    v_p99 = float(climbs["v_kmh"].quantile(0.99)) if not climbs.empty else 40.0
    x_max = min(float(curve["v_kmh"].max()) if not curve.empty else np.inf, 1.6 * v_p99)

    fig = go.Figure()
    if not curve.empty:
        fig.add_trace(go.Scatter(
            x=curve["v_kmh"], y=curve["fuerza_t"], mode="lines", name=str(curve["curva"].iloc[0]),
            line={"color": INK, "width": 2.5}, hovertemplate="%{x:.1f} km/h · %{y:.1f} t<extra></extra>",
        ))
    highlight = [u for u in highlight if u in set(climbs["unidad"])][:MAX_CURVE_UNITS]
    rest = op.sample(climbs[~climbs["unidad"].isin(highlight)])
    point_hover = ("<b>%{customdata[0]}</b> · " + t("opp.hover.slope") + " %{customdata[1]:.1f} % · %{customdata[2]:.0f} t<br>"
                   "%{x:.1f} km/h · " + t("opp.hover.iv_curve") + " %{customdata[3]:.2f}<extra></extra>")

    def custom(frame):
        return np.column_stack([frame["unidad"], frame["pend_pct"], frame["gvw_t"], frame["iv"]])

    fig.add_trace(go.Scattergl(
        x=rest["v_kmh"], y=rest["fuerza_req_t"], mode="markers", name=t("opp.legend.fleet_passes"),
        marker={"color": NEUTRAL_MARK, "size": 5, "opacity": 0.4}, customdata=custom(rest), hovertemplate=point_hover,
    ))
    for index, unit in enumerate(highlight):
        part = climbs[climbs["unidad"] == unit]
        fig.add_trace(go.Scattergl(
            x=part["v_kmh"], y=part["fuerza_req_t"], mode="markers", name=t("opp.legend.truck", unidad=unit),
            marker={"color": CAUSE_COLORS[index], "size": 8, "opacity": 0.85,
                    "line": {"color": "#ffffff", "width": 1}},
            customdata=custom(part), hovertemplate=point_hover,
        ))
    return _style(fig, height=height, x=t("opp.axis.speed"), y=t("opp.axis.force_log"),
                  xaxis={"range": [0, x_max]},
                  # Whole values on the log axis (plotly's default labels minor ticks "9, 8, 6..." for 90, 80, 60).
                  yaxis={"type": "log", "tickvals": FORCE_TICKS, "ticktext": [fmt(v, 0) for v in FORCE_TICKS]})


def ramp_box_figure(climbs: pd.DataFrame, camiones: Optional[pd.DataFrame], metric: str = "hp_pendiente",
                    selected: Optional[str] = None, height: int = 460) -> go.Figure:
    """One box per truck on a ramp (natural unit order), colored by the truck's decision; fleet median marked.
    The selected unit's box is drawn bold, with its own legend entry."""
    climbs = climbs.dropna(subset=[metric]) if not climbs.empty else climbs
    if climbs.empty:
        return empty_figure(t("opp.empty.no_ramp_climbs"))
    decisions = {}
    if camiones is not None and not camiones.empty:
        decisions = dict(zip(camiones["unidad"], camiones["decision"]))
    df = climbs.assign(decision=climbs["unidad"].map(decisions).fillna(op.SIN_DATOS))
    units = op.sort_units(df["unidad"].unique())
    label = t(f"opp.metric.{metric}")
    value_format = ":,.0f" if metric == "hp_pendiente" else ":.3f"
    fig = go.Figure()
    rest = df[df["unidad"] != selected]
    for decision in _present_decisions(rest["decision"]):
        part = rest[rest["decision"] == decision]
        color = decision_color(decision)
        fig.add_trace(go.Box(
            x=part["unidad"], y=part[metric], name=decision, boxpoints="outliers",
            marker={"color": color, "size": 4}, line={"color": color, "width": 1.5}, fillcolor="rgba(0,0,0,0)",
            hovertemplate="<b>%{x}</b><br>" + label + " %{y" + value_format + "}<extra>" + decision + "</extra>",
        ))
    mine = df[df["unidad"] == selected]
    if not mine.empty:
        color = decision_color(mine["decision"].iloc[0])
        fig.add_trace(go.Box(
            x=mine["unidad"], y=mine[metric], name=t("opp.legend.selected_unit", unidad=selected),
            boxpoints="all", jitter=0.3, pointpos=0, marker={"color": INK, "size": 5},
            line={"color": INK, "width": 3}, fillcolor=color,
            hovertemplate="<b>%{x}</b><br>" + label + " %{y" + value_format + "}<extra></extra>",
        ))
    median = float(df[metric].median())
    value = fmt(median, 0) if metric == "hp_pendiente" else fmt(median, 3)
    _reference_line(fig, units, median, f'{t("opp.annotation.fleet_median")} ({value})')
    _style(fig, height=height, x=t("opp.axis.unit"), y=label,
           xaxis={"categoryorder": "array", "categoryarray": units, "type": "category"})
    fig.update_layout(boxmode="overlay")
    return fig


# Base maps of the ramps map. Satellite imagery comes from Esri World Imagery tiles (no key needed,
# fetched by the browser); "calles" is OpenStreetMap. Both need internet access in the browser.
SATELLITE_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
SATELLITE_ATTRIBUTION = "Esri, Maxar, Earthstar Geographics"
# Grade (how demanding a stretch is): one hue, light to dark, readable on satellite imagery.
GRADE_SCALE = [[0.0, "#fff7bc"], [0.35, "#fec44f"], [0.7, "#ec7014"], [1.0, "#8c2d04"]]
# Performance against a reference of 1: red below (slower), white at 1, blue above (faster).
PERFORMANCE_SCALE = [[0.0, "#b91c1c"], [0.35, "#f87171"], [0.5, "#f8fafc"], [0.65, "#60a5fa"], [1.0, "#1d4ed8"]]
PERFORMANCE_SPAN = 0.15     # the performance scale runs 0,85 - 1,15


MAP_HEIGHT = 580
MAP_FIT_WIDTH = 900         # px; the card is wider on a desktop, narrower on a laptop, so fit a modest width
MAP_FIT_MARGIN = 1.25       # room around the paths (and for the colorbar)


def _map_view(lat: pd.Series, lon: pd.Series) -> dict:
    """Center and zoom that fit every point in a MAP_FIT_WIDTH x MAP_HEIGHT map. MapLibre tiles are
    512 px, so at zoom z the world is 512·2^z px wide; a degree of latitude is 1/cos(lat) times taller
    than one of longitude (Web Mercator)."""
    center_lat = float((lat.max() + lat.min()) / 2)
    lat_span = max(float(lat.max() - lat.min()), 0.002) / np.cos(np.radians(center_lat))
    lon_span = max(float(lon.max() - lon.min()), 0.002)
    fit = min(np.log2(MAP_FIT_WIDTH * 360 / (512 * lon_span)), np.log2(MAP_HEIGHT * 360 / (512 * lat_span)))
    zoom = float(np.clip(fit - np.log2(MAP_FIT_MARGIN), 9, 16.5))
    return {"center": {"lat": center_lat, "lon": float((lon.max() + lon.min()) / 2)}, "zoom": zoom}


def ramp_map_figure(segments: pd.DataFrame, mode: str = "pendiente", base: str = "satelite",
                    unit_speed: Optional[pd.DataFrame] = None, unit: Optional[str] = None,
                    selected_ramp: Optional[str] = None) -> go.Figure:
    """The real path of the busiest climb ramps (GPS, one point every 100 m) over a satellite or street
    map. Each 100 m point is colored by `mode`:

    - "pendiente": median grade of that stretch, how demanding it is;
    - "flota": the ramp's median IV against the manufacturer curve, how the fleet performs there;
    - "unidad": the selected unit's median speed on that stretch / the fleet's, where it loses time.

    The selected ramp is outlined in yellow. `customdata[0]` of every colored point is its ramp id
    (a click on a point selects that ramp)."""
    if segments is None or segments.empty:
        return empty_figure(t("opp.empty.no_ramp_paths"), height=520)
    fig = go.Figure()
    for rampa_id, part in segments.groupby("rampa_id", sort=False):
        is_selected = rampa_id == selected_ramp
        if is_selected:
            # Wider than the colored points drawn on top, so the selection shows as a yellow band around
            # them; the dark halo keeps it visible on light imagery.
            fig.add_trace(go.Scattermap(lat=part["lat"], lon=part["lon"], mode="lines", hoverinfo="skip",
                                        showlegend=False, line={"color": "#111827", "width": 24}))
        fig.add_trace(go.Scattermap(
            lat=part["lat"], lon=part["lon"], mode="lines", hoverinfo="skip", showlegend=False,
            line={"color": "#facc15" if is_selected else "rgba(255,255,255,0.75)", "width": 18 if is_selected else 3},
        ))

    points = segments.copy()
    if mode == "unidad" and unit and unit_speed is not None and not unit_speed.empty:
        points = points.merge(unit_speed, on=["rampa_id", "k"], how="inner", suffixes=("", "_unidad"))
        values, scale = points["rel"], PERFORMANCE_SCALE
        cmin, cmax = 1 - PERFORMANCE_SPAN, 1 + PERFORMANCE_SPAN
        title = t("opp.map.colorbar_unit", unidad=unit)
        value_hover = t("opp.map.hover_unit", unidad=unit) + " %{customdata[4]:.2f}× (%{customdata[6]} "
        value_hover += t("opp.hover.climbs") + ")"
        extra = points["pasadas_unidad"]
    elif mode == "flota":
        values, scale = points["iv_rampa"], PERFORMANCE_SCALE
        cmin, cmax = 1 - PERFORMANCE_SPAN, 1 + PERFORMANCE_SPAN
        title = t("opp.map.colorbar_fleet")
        value_hover = t("opp.map.hover_fleet") + " %{customdata[4]:.2f}"
        extra = points["pasadas"]
    else:
        values, scale = points["pend_pct"], GRADE_SCALE
        cmin, cmax = 0.0, max(10.0, float(np.nanpercentile(points["pend_pct"], 95)))
        title = t("opp.map.colorbar_grade")
        value_hover = t("opp.hover.slope") + " %{customdata[4]:.1f} %"
        extra = points["pasadas"]
    if points.empty:
        return empty_figure(t("opp.empty.no_unit_paths", unidad=unit or "—"), height=520)

    fig.add_trace(go.Scattermap(
        lat=points["lat"], lon=points["lon"], mode="markers", showlegend=False,
        marker={"size": 11, "color": values, "colorscale": scale, "cmin": cmin, "cmax": cmax,
                "colorbar": {"title": {"text": title, "side": "right"}, "thickness": 12, "len": 0.75,
                             "bgcolor": "rgba(255,255,255,0.85)", "x": 1.0, "xanchor": "right"}},
        customdata=np.column_stack([
            points["rampa_id"], points["nombre"],
            [f"{100 * k:,}–{100 * (k + 1):,} m".replace(",", ".") for k in points["k"]],
            points["pend_pct"], values, points["v_kmh"], extra,
        ]),
        hovertemplate="<b>%{customdata[0]}</b> · %{customdata[1]}<br>"
        + t("opp.map.hover_stretch") + " %{customdata[2]}<br>"
        + value_hover + "<br>" + t("opp.map.hover_click") + "<extra></extra>",
    ))

    _ramp_labels(fig, segments, base)
    return _map_layout(fig, segments, base, "opp-map")


def _ramp_labels(fig: go.Figure, segments: pd.DataFrame, base: str, labels: Optional[dict] = None) -> None:
    """Ramp ids at the top of each path, so a ramp named in a list can be found on the map. The trace
    carries an invisible marker on purpose: with mode="text" alone plotly.js computes the label
    offset from a missing marker size (NaN), MapLibre rejects the layer and the map then ignores
    every later update (coloring, base map, selected ramp)."""
    tops = segments.sort_values("k").groupby("rampa_id", sort=False).tail(1)
    text = [labels.get(r, r) for r in tops["rampa_id"]] if labels else tops["rampa_id"]
    fig.add_trace(go.Scattermap(
        lat=tops["lat"], lon=tops["lon"], mode="markers+text", text=text, showlegend=False,
        marker={"size": 6, "opacity": 0},
        textfont={"size": 11, "color": "#ffffff" if base == "satelite" else INK}, textposition="top right",
        hoverinfo="skip",
    ))


def _map_layout(fig: go.Figure, segments: pd.DataFrame, base: str, revision: str,
                legend: bool = False) -> go.Figure:
    """Base map (satellite or streets), a view that fits every path, and the shared look."""
    view = _map_view(segments["lat"], segments["lon"])
    if base == "satelite":
        map_layout = {"style": "white-bg", "layers": [{
            "below": "traces", "sourcetype": "raster", "sourceattribution": SATELLITE_ATTRIBUTION,
            "source": [SATELLITE_TILES]}]}
    else:
        map_layout = {"style": "open-street-map"}
    fig.update_layout(
        map={**map_layout, **view}, height=MAP_HEIGHT, margin={"l": 0, "r": 0, "t": 0, "b": 0},
        separators=separators(), font={"family": FONT_FAMILY, "size": 12, "color": INK},
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": BRAND_AXIS}, showlegend=legend,
        legend={"x": 0.01, "y": 0.99, "xanchor": "left", "yanchor": "top", "bgcolor": "rgba(255,255,255,0.88)",
                "bordercolor": BRAND_AXIS, "borderwidth": 1, "font": {"size": 11},
                "title": {"text": t("opp.map.legend_demand"), "font": {"size": 11}}},
        # Keep the user's pan and zoom when the coloring, the unit or the selected ramp change.
        uirevision=revision,
    )
    return fig


# Demand of a 100 m stretch (its median grade): the band drawn under the path, wider and darker the
# steeper. (lower bound, label key, color, width in px)
DEMAND_BANDS = (
    (0.0, "opp.map.band.low", GRADE_SCALE[0][1], 7),
    (6.0, "opp.map.band.mid", GRADE_SCALE[1][1], 11),
    (8.0, "opp.map.band.high", GRADE_SCALE[2][1], 15),
    (10.0, "opp.map.band.top", GRADE_SCALE[3][1], 20),
)
DEMANDING_RAMPS = 3         # ramps named as the most demanding in the caption


def demand_band(grade: float) -> int:
    """Index in DEMAND_BANDS of a stretch's grade (%)."""
    index = 0
    for i, (low, *_rest) in enumerate(DEMAND_BANDS):
        if grade >= low:
            index = i
    return index


def ramp_demand(segments: pd.DataFrame) -> pd.DataFrame:
    """Per ramp: median grade of its stretches, length drawn (km), fleet IV; most demanding first."""
    if segments is None or segments.empty:
        return pd.DataFrame(columns=["rampa_id", "nombre", "pend_pct", "km", "iv_rampa"])
    table = segments.groupby("rampa_id", sort=False).agg(
        nombre=("nombre", "first"), pend_pct=("pend_pct", "median"), tramos=("k", "size"),
        iv_rampa=("iv_rampa", "first"))
    table["km"] = table["tramos"] / 10
    return table.drop(columns="tramos").sort_values("pend_pct", ascending=False).reset_index()


def fleet_ramp_map_figure(segments: pd.DataFrame, base: str = "satelite",
                          selected_ramp: Optional[str] = None) -> go.Figure:
    """Demand and fleet performance on one map. Under each climb ramp's real path, a band as steep as
    each 100 m stretch is (wider and darker = more demanding); on top of it, the path itself colored by
    the fleet's median IV on that ramp (red = slower than the manufacturer curve, blue = faster), and
    the ramp labelled with that IV. The selected ramp is outlined in black. `customdata[0]` of every
    path point is its ramp id (a click selects that ramp)."""
    if segments is None or segments.empty:
        return empty_figure(t("opp.empty.no_ramp_paths"), height=520)
    fig = go.Figure()
    if selected_ramp in set(segments["rampa_id"]):
        part = segments[segments["rampa_id"] == selected_ramp]
        fig.add_trace(go.Scattermap(lat=part["lat"], lon=part["lon"], mode="lines", hoverinfo="skip",
                                    showlegend=False, line={"color": "#111827", "width": 30}))

    # One trace per demand band, its stretches separated by gaps (None), so each band is one legend entry.
    bands = {i: ([], []) for i in range(len(DEMAND_BANDS))}
    for _, part in segments.groupby("rampa_id", sort=False):
        part = part.sort_values("k")
        rows = list(part.itertuples())
        for here, there in zip(rows, rows[1:]):
            if there.k != here.k + 1:
                continue
            lat, lon = bands[demand_band((here.pend_pct + there.pend_pct) / 2)]
            lat += [here.lat, there.lat, None]
            lon += [here.lon, there.lon, None]
    for index, (low, key, color, width) in enumerate(DEMAND_BANDS):
        lat, lon = bands[index]
        fig.add_trace(go.Scattermap(
            lat=lat or [None], lon=lon or [None], mode="lines", name=t(key), hoverinfo="skip",
            line={"color": color, "width": width}, opacity=0.9, showlegend=True,
        ))

    fig.add_trace(go.Scattermap(
        lat=segments["lat"], lon=segments["lon"], mode="markers", showlegend=False,
        marker={"size": 8, "color": segments["iv_rampa"], "colorscale": PERFORMANCE_SCALE,
                "cmin": 1 - PERFORMANCE_SPAN, "cmax": 1 + PERFORMANCE_SPAN,
                "colorbar": {"title": {"text": t("opp.map.colorbar_fleet"), "side": "right"}, "thickness": 12,
                             "len": 0.75, "bgcolor": "rgba(255,255,255,0.85)", "x": 1.0, "xanchor": "right"}},
        customdata=np.column_stack([
            segments["rampa_id"], segments["nombre"],
            [f"{100 * k:,}–{100 * (k + 1):,} m".replace(",", ".") for k in segments["k"]],
            segments["pend_pct"], segments["iv_rampa"], segments["v_kmh"], segments["pasadas"],
            segments["pasadas_rampa"],
        ]),
        hovertemplate="<b>%{customdata[0]}</b> · %{customdata[1]}<br>"
        + t("opp.map.hover_stretch") + " %{customdata[2]} · " + t("opp.hover.slope") + " %{customdata[3]:.1f} %"
        + " · %{customdata[5]:.1f} km/h<br>"
        + t("opp.map.hover_fleet") + " <b>%{customdata[4]:.2f}</b> (%{customdata[7]} " + t("opp.hover.climbs") + ")<br>"
        + t("opp.map.hover_click") + "<extra></extra>",
    ))
    ramps = ramp_demand(segments)
    labels = {r.rampa_id: f"{r.rampa_id} · {fmt(r.iv_rampa)}" for r in ramps.itertuples()}
    _ramp_labels(fig, segments, base, labels)
    return _map_layout(fig, segments, base, "opp-map", legend=True)


# ------------------------------------------------------------------------------------------------
# Estrés operacional por unidad
# ------------------------------------------------------------------------------------------------

STRESS_DECIMALS = {"viajes": 0, "km_rampa": 0, "carga_t": 0, "h_carga_alta": 1, "carga_motor": 0,
                   "potencia_hp": 0, "rpm": 0, "combustible_l_km": 1, "pend_subida": 1, "iv_rel_p50": 2,
                   "iv_p50": 2, "s_perdidos_viaje": 0, "indice_estres": 2, "pend_pct": 1,
                   "carga_motor_pct_media": 0, "rpm_media": 0, "potencia_hp_media": 0}
# Less worked than its fleet (blue) - like it (white) - more worked (orange): no good/bad reading.
STRESS_SCALE = [[0.0, CAUSE_COLORS[0]], [0.5, "#f8fafc"], [1.0, "#c2410c"]]
STRESS_SPAN = 0.3           # the heat map runs 0,70 - 1,30 x the fleet median


def stress_label(metric: str, measured_payload: bool = True) -> str:
    """Display name of a stress, performance or load variable. The load is the measured payload
    (CDA) or the apparent mass the pipeline estimates (Capstone)."""
    if metric == "carga_t" and not measured_payload:
        return t("opp.stress.metric.carga_t_estimated")
    return t(f"opp.stress.metric.{metric}")


def _selected_line(units: Sequence[str], selected: Optional[str]) -> list:
    return [INK if u == selected else "rgba(0,0,0,0)" for u in units]


def stress_heatmap_figure(stress: pd.DataFrame, measured_payload: bool = True,
                          selected: Optional[str] = None) -> go.Figure:
    """Units (rows, most worked on top) by stress figure (columns): each cell is the unit's value over
    its fleet's median (orange = worked more, blue = less) and shows the value itself. The last column is
    the stress index (the mean of those ratios). `customdata` of every cell is its unit id."""
    metrics = op.stress_metrics(stress)
    if stress is None or stress.empty or not metrics:
        return empty_figure(t("opp.empty.no_stress"))
    df = stress.sort_values("indice_estres", ascending=True).reset_index(drop=True)
    columns = metrics + ["indice_estres"]
    ratios = []
    for metric in metrics:
        median = df.groupby("flota")[metric].transform("median")
        ratios.append((df[metric] / median.where(median > 0)).to_numpy())
    ratios.append(df["indice_estres"].to_numpy())
    z = np.column_stack(ratios)
    text = np.column_stack([[fmt(v, STRESS_DECIMALS.get(m, 1)) for v in df[m]] for m in columns])
    labels = [stress_label(m, measured_payload) for m in columns]
    units = df["unidad"].tolist()
    fig = go.Figure(go.Heatmap(
        z=z, x=labels, y=units, zmid=1, zmin=1 - STRESS_SPAN, zmax=1 + STRESS_SPAN, colorscale=STRESS_SCALE,
        text=text, texttemplate="%{text}", textfont={"size": 11}, xgap=2, ygap=2,
        customdata=np.array([[u] * len(columns) for u in units]),
        colorbar={"title": {"text": t("opp.stress.colorbar"), "side": "right"}, "thickness": 12, "len": 0.5},
        hovertemplate="<b>%{y}</b> · %{x}<br>%{text} · %{z:.2f}× " + t("opp.stress.vs_fleet_median")
        + "<extra></extra>",
    ))
    ticktext = [f"<b>▶ {u}</b>" if u == selected else u for u in units]
    _style(fig, height=_rows_height(len(units), per_row=24, base=140, minimum=320), legend=False,
           xaxis={"side": "top", "showgrid": False, "tickangle": 0, "automargin": True},
           yaxis={"showgrid": False, "type": "category", "tickvals": units, "ticktext": ticktext})
    fig.update_layout(margin={"l": 70, "r": 24, "t": 72, "b": 16}, uirevision="opp-stress")
    return fig


PERFORMANCE_COLUMNS = ("iv_rel_p50", "iv_p50")      # colored against 1 (red slower, blue faster)
DECISION_TINT = {op.CONFORME: SEVERITY_TIERS["bajo"]["bg"], op.SEGUIMIENTO: SEVERITY_TIERS["atencion"]["bg"],
                 op.REVISAR: SEVERITY_TIERS["alto"]["bg"], op.SIN_DATOS: "#e2e8f0"}


def _discrete_scale(colors: Sequence[str]) -> list:
    """A colorscale with one flat band per category (z = 0..n-1, zmin -0.5, zmax n-0.5)."""
    n = len(colors)
    scale = []
    for i, color in enumerate(colors):
        scale += [[i / n, color], [(i + 1) / n, color]]
    return scale


def _header(label: str) -> str:
    """A column title on two lines ("Masa aparente<br>(t, estimada)"), so neighbours never overlap."""
    return label.replace(" (", "<br>(", 1)


def fleet_heatmap_figure(stress: pd.DataFrame, columns: Sequence[str], measured_payload: bool = True) -> go.Figure:
    """Who goes to the bottom of the pit: one row per unit, best relative IV on top. The first column is
    the unit's decision (its tint and word); IV columns are colored against 1 (red = slower than the
    reference, blue = faster); load and operation columns against the unit's fleet median (orange =
    more than its fleet, blue = less). Every cell shows its value; `customdata` of every cell is its
    unit id (a click opens that unit's evidence).

    One trace per column on a numeric x axis (column i spans i ± 0,5): heat maps of different color
    scales on one categorical axis are not placed column by column, so cells and their text drift.
    The axes are fixed: the figure is read, not zoomed."""
    columns = [c for c in columns if c in getattr(stress, "columns", [])]
    if stress is None or stress.empty:
        return empty_figure(t("opp.empty.no_stress"))
    df = stress.sort_values(["iv_rel_p50", "unidad"], ascending=[False, True], na_position="last").reset_index(drop=True)
    units = df["unidad"].tolist()
    rows = np.arange(len(units))
    custom = np.array(units, dtype=object).reshape(-1, 1)
    fig = go.Figure()

    def column(i: int, z, text, **style) -> go.Heatmap:
        return go.Heatmap(
            z=np.asarray(z, dtype=float).reshape(-1, 1), x=[i], y=rows, text=np.asarray(text, dtype=object).reshape(-1, 1),
            texttemplate="%{text}", textfont={"size": 12}, xgap=2, ygap=2, customdata=custom, **style)

    order = list(op.DECISIONS)
    codes = df["decision"].map({d: i for i, d in enumerate(order)}).fillna(order.index(op.SIN_DATOS))
    fig.add_trace(column(
        0, codes, df["decision"], zmin=-0.5, zmax=len(order) - 0.5, showscale=False,
        colorscale=_discrete_scale([DECISION_TINT[d] for d in order]),
        hovertemplate="<b>%{customdata}</b> · %{text}<extra></extra>"))
    shown = {"perf": False, "stress": False}
    for i, metric in enumerate(columns, start=1):
        label = stress_label(metric, measured_payload)
        text = [fmt(v, STRESS_DECIMALS.get(metric, 2)) for v in df[metric]]
        if metric in PERFORMANCE_COLUMNS:
            fig.add_trace(column(i, df[metric], text, coloraxis="coloraxis",
                                 hovertemplate="<b>%{customdata}</b> · " + label + " %{text}<extra></extra>"))
            shown["perf"] = True
            continue
        if metric == "indice_estres":
            ratio = df[metric]
        else:
            median = df.groupby("flota")[metric].transform("median")
            ratio = df[metric] / median.where(median > 0)
        fig.add_trace(column(i, ratio, text, coloraxis="coloraxis2",
                             hovertemplate="<b>%{customdata}</b> · " + label + " %{text} · %{z:.2f}× "
                             + t("opp.stress.vs_fleet_median") + "<extra></extra>"))
        shown["stress"] = True

    headers = [t("opp.heatmap.decision")] + [_header(stress_label(m, measured_payload)) for m in columns]
    colorbar = {"thickness": 10, "len": 0.42, "yanchor": "middle", "x": 1.01, "xanchor": "left"}
    fig.update_layout(
        coloraxis={"colorscale": PERFORMANCE_SCALE, "cmid": 1, "cmin": 1 - PERFORMANCE_SPAN, "cmax": 1 + PERFORMANCE_SPAN,
                   "showscale": shown["perf"],
                   "colorbar": {**colorbar, "y": 0.78, "title": {"text": t("opp.heatmap.colorbar_iv"), "side": "right"}}},
        coloraxis2={"colorscale": STRESS_SCALE, "cmid": 1, "cmin": 1 - STRESS_SPAN, "cmax": 1 + STRESS_SPAN,
                    "showscale": shown["stress"],
                    "colorbar": {**colorbar, "y": 0.26, "title": {"text": t("opp.stress.colorbar"), "side": "right"}}},
    )
    _style(fig, height=_rows_height(len(units), per_row=26, base=120, minimum=320), legend=False,
           xaxis={"side": "top", "showgrid": False, "zeroline": False, "tickvals": list(range(len(headers))),
                  "ticktext": headers, "range": [-0.5, len(headers) - 0.5], "fixedrange": True, "tickfont": {"size": 12}},
           yaxis={"showgrid": False, "zeroline": False, "tickvals": rows, "ticktext": units, "autorange": "reversed",
                  "fixedrange": True, "tickfont": {"size": 12}})
    fig.update_layout(margin={"l": 64, "r": 90, "t": 70, "b": 12}, uirevision="opp-heatmap", dragmode=False)
    return fig


def stress_scatter_figure(stress: pd.DataFrame, x: str, y: str, measured_payload: bool = True,
                          selected: Optional[str] = None) -> go.Figure:
    """One bubble per unit: how hard it was worked (x) against how it performed (y), sized by its trips
    and colored by its decision; the fleet medians split the plane in four. `customdata[0]` = unit."""
    if stress is None or stress.empty or x not in stress or y not in stress:
        return empty_figure(t("opp.empty.no_stress"))
    df = stress.dropna(subset=[x, y])
    if df.empty:
        return empty_figure(t("opp.empty.no_stress"))
    trips = pd.to_numeric(df.get("viajes", pd.Series(1, index=df.index)), errors="coerce").fillna(1)
    size_ref = 2.0 * max(float(trips.max()), 1.0) / 34 ** 2
    xl, yl = stress_label(x, measured_payload), stress_label(y, measured_payload)
    xf, yf = STRESS_DECIMALS.get(x, 1), STRESS_DECIMALS.get(y, 2)
    fig = go.Figure()
    for decision in _present_decisions(df["decision"]):
        part = df[df["decision"] == decision]
        fig.add_trace(go.Scatter(
            x=part[x], y=part[y], mode="markers+text", name=decision, text=part["unidad"],
            textposition="top center", textfont={"size": 10, "color": BRAND_MUTED},
            marker={"color": decision_color(decision), "size": trips.loc[part.index], "sizemode": "area",
                    "sizeref": size_ref, "sizemin": 6, "opacity": 0.85,
                    "line": {"color": _selected_line(part["unidad"], selected),
                             "width": [3 if u == selected else 0 for u in part["unidad"]]}},
            customdata=np.column_stack([part["unidad"], trips.loc[part.index]]),
            hovertemplate="<b>%{customdata[0]}</b> · " + decision + "<br>" + xl + f" %{{x:,.{xf}f}}<br>" + yl
            + f" %{{y:,.{yf}f}}<br>%{{customdata[1]:.0f}} " + t("opp.stress.trips") + "<extra></extra>",
        ))
    fig.add_vline(x=float(df[x].median()), line={"color": BRAND_MUTED, "width": 1, "dash": "dash"})
    fig.add_hline(y=float(df[y].median()), line={"color": BRAND_MUTED, "width": 1, "dash": "dash"})
    if y == "iv_rel_p50":
        fig.add_hline(y=op.IV_REL_REVIEW, line={"color": decision_color(op.REVISAR), "width": 1.5, "dash": "dot"})
    elif y == "iv_p50":
        # 1,00 = the truck climbs at what its manufacturer curve says.
        fig.add_hline(y=1.0, line={"color": INK, "width": 1.5},
                      annotation={"text": t("opp.scatter.curve_line"), "font": {"size": 11, "color": INK}},
                      annotation_position="bottom left")
    return _style(fig, height=520, x=xl, y=yl)


def stress_bars_figure(stress: pd.DataFrame, metric: str, measured_payload: bool = True,
                       selected: Optional[str] = None) -> go.Figure:
    """One bar per unit for one stress figure, most worked first, colored by decision; its fleet's
    median marked. `customdata[0]` of every bar is its unit id."""
    if stress is None or stress.empty or metric not in stress or stress[metric].notna().sum() == 0:
        return empty_figure(t("opp.empty.no_stress"))
    df = stress.dropna(subset=[metric]).sort_values(metric, ascending=False)
    units = df["unidad"].tolist()
    label = stress_label(metric, measured_payload)
    decimals = STRESS_DECIMALS.get(metric, 1)
    fig = go.Figure()
    for decision in _present_decisions(df["decision"]):
        part = df[df["decision"] == decision]
        fig.add_trace(go.Bar(
            x=part["unidad"], y=part[metric], name=decision,
            marker={"color": decision_color(decision), "line": {"color": _selected_line(part["unidad"], selected),
                                                                "width": [3 if u == selected else 0 for u in part["unidad"]]}},
            customdata=np.column_stack([part["unidad"], part["flota"]]),
            hovertemplate="<b>%{x}</b> · %{customdata[1]} · " + decision + "<br>" + label
            + f" %{{y:,.{decimals}f}}<extra></extra>",
        ))
    median = float(df[metric].median())
    _reference_line(fig, units, median, f'{t("opp.annotation.fleet_median")} ({fmt(median, decimals)})')
    ticktext = [f"<b>▶ {u}</b>" if u == selected else u for u in units]
    _style(fig, height=460, y=label,
           xaxis={"categoryorder": "array", "categoryarray": units, "type": "category", "tickvals": units,
                  "ticktext": ticktext, "tickangle": -45 if len(units) > 20 else 0})
    fig.update_layout(barmode="overlay", bargap=0.25)
    return fig


def load_performance_figure(bins: pd.DataFrame, variable: str, metric: str, unit: Optional[str] = None,
                            measured_payload: bool = True) -> go.Figure:
    """Performance against how loaded (or how pushed) the truck was, climb by climb: the fleet's
    median and middle half in each sixth of the load variable, and the unit's median in the same bins."""
    if bins is None or bins.empty:
        return empty_figure(t("opp.empty.no_stress"))
    xl, yl = stress_label(variable, measured_payload), stress_label(metric, measured_payload)
    yf = 0 if metric == "s_perdidos_viaje" else 3
    if metric == "s_perdidos_viaje":
        yl = t("opp.stress.metric.s_perdidos_subida")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=bins["x"], y=bins["p25"], mode="lines", line={"width": 0}, hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(go.Scatter(
        x=bins["x"], y=bins["p75"], mode="lines", line={"width": 0}, fill="tonexty",
        fillcolor="rgba(163,172,185,0.3)", name=t("opp.stress.fleet_band"), hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=bins["x"], y=bins["p50"], mode="lines+markers", name=t("opp.legend.fleet_median"),
        line={"color": INK, "width": 2, "dash": "dash"}, marker={"size": 7},
        customdata=bins["n"],
        hovertemplate=xl + " %{x:,.1f}<br>" + t("opp.legend.fleet_median") + f" %{{y:,.{yf}f}}"
        + "<br>%{customdata} " + t("opp.hover.climbs") + "<extra></extra>",
    ))
    if unit and bins["unidad"].notna().any():
        fig.add_trace(go.Scatter(
            x=bins["x"], y=bins["unidad"], mode="lines+markers", name=t("opp.legend.truck", unidad=unit),
            line={"color": CAUSE_COLORS[0], "width": 3}, marker={"size": 10},
            customdata=bins["n_unidad"],
            hovertemplate="<b>" + unit + "</b> · " + xl + " %{x:,.1f}<br>" + yl + f" %{{y:,.{yf}f}}"
            + "<br>%{customdata} " + t("opp.hover.climbs") + "<extra></extra>",
        ))
    if metric == "iv_p50":
        fig.add_hline(y=1.0, line={"color": BRAND_MUTED, "width": 1})
    elif metric == "iv_rel_p50":
        fig.add_hline(y=op.IV_REL_OK, line={"color": BRAND_MUTED, "width": 1})
    return _style(fig, height=520, x=xl, y=yl)


# ------------------------------------------------------------------------------------------------
# Evidencia por unidad: semanas anteriores
# ------------------------------------------------------------------------------------------------

HISTORY_METRIC = "iv_rel_p50"
ROLLING_WINDOW = "3D"       # moving window of the history (calendar days)


def _rolling(days: pd.DataFrame, metric: str) -> pd.Series:
    """3-day moving mean of a daily value, each day weighted by its climbs (a day with few climbs is
    noisy). Indexed by day."""
    days = days.dropna(subset=[metric]).sort_values("dia")
    if days.empty:
        return pd.Series(dtype=float)
    weight = pd.to_numeric(days["pasadas"], errors="coerce").fillna(1) if "pasadas" in days else pd.Series(1.0, index=days.index)
    frame = pd.DataFrame({"v": days[metric].to_numpy() * weight.to_numpy(), "w": weight.to_numpy()},
                         index=pd.DatetimeIndex(days["dia"]))
    frame = frame.groupby(level=0).sum()
    rolled = frame.rolling(ROLLING_WINDOW).sum()
    return rolled["v"] / rolled["w"].where(rolled["w"] > 0)


def unit_history_figure(weekly: pd.DataFrame, daily: Optional[pd.DataFrame], unit: Optional[str],
                        metric: str = HISTORY_METRIC, current: Optional[op.Week] = None) -> go.Figure:
    """A unit's weeks, day by day: the 3-day moving mean of the unit (days weighted by their climbs)
    against the same moving mean of its fleet's daily median. The selected week is shaded; the
    decision thresholds are marked; each week labelled on the axis."""
    if daily is None or daily.empty or not unit or metric not in daily:
        return empty_figure(t("opp.empty.no_history"))
    mine = daily[daily["unidad"] == unit].dropna(subset=[metric])
    if mine.empty:
        return empty_figure(t("opp.empty.no_unit_history", unidad=unit))
    flota = mine["flota"].iloc[-1] if "flota" in mine else None
    fleet_days = daily[(daily["flota"] == flota)] if flota is not None else daily
    fleet_median = fleet_days.dropna(subset=[metric]).groupby("dia")[metric].median().sort_index()
    fleet_median.index = pd.DatetimeIndex(fleet_median.index)
    fleet_line = fleet_median.rolling(ROLLING_WINDOW).mean()
    unit_line = _rolling(mine, metric)
    label = t(f"opp.metric.{metric}")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=fleet_line.index, y=fleet_line.values, mode="lines", name=t("opp.legend.fleet_rolling", flota=flota or "—"),
        line={"color": BRAND_MUTED, "width": 2, "dash": "dash"},
        hovertemplate="%{x|%d-%m-%Y}<br>" + t("opp.legend.fleet_median") + " %{y:.3f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=unit_line.index, y=unit_line.values, mode="lines", name=t("opp.legend.unit_rolling", unidad=unit),
        line={"color": CAUSE_COLORS[0], "width": 3, "shape": "spline", "smoothing": 0.6},
        hovertemplate="<b>" + unit + "</b> · %{x|%d-%m-%Y}<br>" + label + " %{y:.3f}<extra></extra>",
    ))
    if metric == "iv_rel_p50":
        fig.add_hline(y=op.IV_REL_OK, line={"color": INK, "width": 1})
        fig.add_hline(y=op.IV_REL_REVIEW, line={"color": decision_color(op.REVISAR), "width": 1.5, "dash": "dot"})
    else:
        fig.add_hline(y=1.0, line={"color": INK, "width": 1})
    if current is not None:
        start = pd.Timestamp(current.monday)
        fig.add_vrect(x0=start, x1=start + pd.Timedelta(days=7), fillcolor="#1e3a5f", opacity=0.06,
                      line_width=0, layer="below")
    xaxis = {"showgrid": False, "tickformat": "%d-%m"}
    if weekly is not None and not weekly.empty and "mitad" in weekly:
        weeks = weekly.drop_duplicates("mitad").sort_values("mitad")
        xaxis.update(tickvals=weeks["mitad"], ticktext=[t("opp.axis.week_short", n=n) for n in weeks["semana_n"]],
                     range=[weeks["lunes"].min(), weeks["lunes"].max() + pd.Timedelta(days=7)])
    values = pd.concat([unit_line, fleet_line]).dropna()
    low, high = (float(values.min()), float(values.max())) if not values.empty else (0.9, 1.1)
    if metric == "iv_rel_p50":
        low, high = min(low, op.IV_REL_REVIEW), max(high, op.IV_REL_OK)
    pad = max(0.02, (high - low) * 0.15)
    return _style(fig, height=420, y=label, xaxis=xaxis, yaxis={"range": [low - pad, high + pad]})


# ------------------------------------------------------------------------------------------------
# Evidencia por unidad: la unidad en sus rampas
# ------------------------------------------------------------------------------------------------

# How each 100 m of the unit can be colored: its IV against the curve, or how hard the engine works.
UNIT_MAP_COLORS = ("iv", "carga_motor", "rpm", "potencia_hp")
EFFORT_SCALE = [[0.0, "#f1f5f9"], [0.5, "#a78bfa"], [1.0, "#4c1d95"]]     # light to deep violet


def _demand_of(pend: float) -> tuple:
    _low, key, color, width = DEMAND_BANDS[demand_band(pend)]
    return key, color, width


def unit_ramp_map_figure(segments: pd.DataFrame, stretches: pd.DataFrame, ramps: pd.DataFrame,
                         unit: Optional[str], color_by: str = "iv", selected_ramp: Optional[str] = None) -> go.Figure:
    """The unit on its ramps over satellite imagery. Each ramp is a band colored (and widened) by how
    demanding it is (its median grade, the same bands as the fleet map); on it, each 100 m the unit
    climbed is a point colored by its IV against the manufacturer curve (or by engine load, rpm or
    power). With a ramp selected, only that ramp carries data and the view fits it; the unit's other
    ramps stay as a faint line. `customdata[0]` of every point is its ramp id."""
    if segments is None or segments.empty or stretches is None or stretches.empty or ramps is None or ramps.empty:
        return empty_figure(t("opp.empty.no_unit_paths", unidad=unit or "—"), height=520)
    shown_ramps = [r for r in ramps["rampa_id"] if r in set(stretches["rampa_id"]) and r in set(segments["rampa_id"])]
    if not shown_ramps:
        return empty_figure(t("opp.empty.no_unit_paths", unidad=unit or "—"), height=520)
    focus = [selected_ramp] if selected_ramp in shown_ramps else shown_ramps
    grade = dict(zip(ramps["rampa_id"], ramps["pend_pct"]))
    paths = segments[segments["rampa_id"].isin(shown_ramps)]
    fig = go.Figure()

    for rampa_id, part in paths.groupby("rampa_id", sort=False):
        if rampa_id not in focus:
            fig.add_trace(go.Scattermap(lat=part["lat"], lon=part["lon"], mode="lines", hoverinfo="skip",
                                        showlegend=False, line={"color": "rgba(255,255,255,0.55)", "width": 3}))
    if selected_ramp in focus and len(focus) == 1:
        part = paths[paths["rampa_id"] == selected_ramp]
        fig.add_trace(go.Scattermap(lat=part["lat"], lon=part["lon"], mode="lines", hoverinfo="skip",
                                    showlegend=False, line={"color": "#111827", "width": 32}))
    # One trace per demand band (one legend entry each); a ramp takes the band of its median grade.
    for index, (_low, key, color, width) in enumerate(DEMAND_BANDS):
        lat, lon = [], []
        for rampa_id in focus:
            if demand_band(grade.get(rampa_id, 0.0)) != index:
                continue
            part = paths[paths["rampa_id"] == rampa_id].sort_values("k")
            lat += part["lat"].tolist() + [None]
            lon += part["lon"].tolist() + [None]
        fig.add_trace(go.Scattermap(lat=lat or [None], lon=lon or [None], mode="lines", name=t(key),
                                    hoverinfo="skip", line={"color": color, "width": width}, opacity=0.9))

    points = stretches[stretches["rampa_id"].isin(focus)].merge(
        segments[["rampa_id", "k", "lat", "lon", "pend_pct", "nombre"]], on=["rampa_id", "k"], how="inner")
    color_by = color_by if color_by in UNIT_MAP_COLORS and points[color_by].notna().any() else "iv"
    values = points[color_by]
    if color_by == "iv":
        marker = {"colorscale": PERFORMANCE_SCALE, "cmin": 1 - PERFORMANCE_SPAN, "cmax": 1 + PERFORMANCE_SPAN}
    else:
        low, high = np.nanpercentile(values, [5, 95]) if values.notna().sum() > 1 else (0, 1)
        marker = {"colorscale": EFFORT_SCALE, "cmin": float(low), "cmax": float(max(high, low + 1e-6))}
    title = t(f"opp.unit_map.colorbar.{color_by}", unidad=unit)
    fig.add_trace(go.Scattermap(
        lat=points["lat"], lon=points["lon"], mode="markers", showlegend=False,
        marker={"size": 11, "color": values, **marker,
                "colorbar": {"title": {"text": title, "side": "right"}, "thickness": 12, "len": 0.7,
                             "bgcolor": "rgba(255,255,255,0.85)", "x": 1.0, "xanchor": "right"}},
        customdata=np.column_stack([
            points["rampa_id"], points["nombre"],
            [f"{100 * k:,}–{100 * (k + 1):,} m".replace(",", ".") for k in points["k"]],
            points["pend_pct"], points["iv"], points["carga_motor"], points["rpm"], points["pasadas"],
        ]),
        hovertemplate="<b>%{customdata[0]}</b> · %{customdata[1]}<br>"
        + t("opp.map.hover_stretch") + " %{customdata[2]} · " + t("opp.hover.slope") + " %{customdata[3]:.1f} %<br>"
        + t("opp.unit_map.hover_iv", unidad=unit) + " <b>%{customdata[4]:.2f}</b><br>"
        + t("opp.unit_map.hover_effort") + " %{customdata[5]:.0f} % · %{customdata[6]:.0f} rpm<br>"
        + "%{customdata[7]} " + t("opp.hover.climbs") + "<extra></extra>",
    ))
    labels = {r: f"{r} · {fmt(grade.get(r), 1)} %" for r in focus}
    _ramp_labels(fig, paths[paths["rampa_id"].isin(focus)], "satelite", labels)
    fig = _map_layout(fig, paths[paths["rampa_id"].isin(focus)], "satelite",
                      f"opp-unit-map-{unit}-{selected_ramp or 'todas'}", legend=True)
    return fig


# ------------------------------------------------------------------------------------------------
# Tendencia
# ------------------------------------------------------------------------------------------------

def trend_figure(history: pd.DataFrame, metric: str, highlight: Sequence[str] = ()) -> go.Figure:
    """One line per truck by day: highlighted trucks in color, the rest thin gray, fleet median dotted."""
    if history is None or history.empty or metric not in history:
        return empty_figure(t("opp.empty.no_history"))
    df = history.dropna(subset=[metric]).sort_values("dia")
    if df.empty:
        return empty_figure(t("opp.empty.no_history"))
    label = t(f"opp.metric.{metric}")
    value_format = ":.3f" if metric.startswith(("iv", "eficiencia")) else ":,.1f"
    highlight = [u for u in highlight if u in set(df["unidad"])]
    fig = go.Figure()
    first = True
    for unit, part in df[~df["unidad"].isin(highlight)].groupby("unidad"):
        fig.add_trace(go.Scatter(
            x=part["dia"], y=part[metric], mode="lines", name=t("opp.legend.other_trucks"),
            legendgroup="others", showlegend=first, line={"color": NEUTRAL_MARK, "width": 1}, opacity=0.6,
            hovertemplate=f"<b>{unit}</b> · " + "%{x|%d-%m-%Y}<br>" + label + " %{y" + value_format + "}<extra></extra>",
        ))
        first = False
    median = df.groupby("dia")[metric].median()
    fig.add_trace(go.Scatter(
        x=median.index, y=median.values, mode="lines", name=t("opp.legend.fleet_median"),
        line={"color": INK, "width": 2, "dash": "dot"},
        hovertemplate=t("opp.legend.fleet_median") + " · %{x|%d-%m-%Y}<br>" + label + " %{y" + value_format + "}<extra></extra>",
    ))
    for index, unit in enumerate(highlight):
        part = df[df["unidad"] == unit]
        fig.add_trace(go.Scatter(
            x=part["dia"], y=part[metric], mode="lines+markers", name=unit,
            line={"color": CAUSE_COLORS[index % len(CAUSE_COLORS)], "width": 2.5}, marker={"size": 6},
            hovertemplate=f"<b>{unit}</b> · " + "%{x|%d-%m-%Y}<br>" + label + " %{y" + value_format + "}<extra></extra>",
        ))
    if metric == "iv_rel_p50":
        fig.add_hline(y=op.IV_REL_REVIEW, line={"color": decision_color(op.REVISAR), "width": 1, "dash": "dot"})
    # The gray lines get a robust range; the highlighted trucks and the median are always shown whole.
    y_range = _robust_range(df[metric])
    if y_range:
        shown = pd.concat([df.loc[df["unidad"].isin(highlight), metric], median])
        y_range = [min(y_range[0], float(shown.min())), max(y_range[1], float(shown.max()))]
    return _style(fig, height=460, x=t("opp.axis.day"), y=label, xaxis={"tickformat": "%d-%m"},
                  yaxis={"range": y_range} if y_range else None)


# ------------------------------------------------------------------------------------------------
# Bajada
# ------------------------------------------------------------------------------------------------

def retarder_figure(pasadas: Optional[pd.DataFrame]) -> go.Figure:
    """Real speed vs the retarder's maximum safe speed; above the diagonal = faster than the brakes hold."""
    df = op.descents(pasadas)
    if df.empty:
        return empty_figure(t("opp.empty.no_descents"))
    shown = op.sample(df)
    top = float(max(shown["v_kmh"].max(), shown["v_max_retardo_kmh"].max())) * 1.05
    hover = ("<b>%{customdata[0]}</b> · " + t("opp.hover.slope") + " %{customdata[1]:.1f} % · %{customdata[2]:,.0f} m<br>"
             + t("opp.hover.real_speed") + " %{y:.1f} · " + t("opp.hover.max_speed") + " %{x:.1f} km/h<br>"
             "%{customdata[3]}<extra></extra>")
    fig = go.Figure()
    for estado, color in (("cargado", LOADED_COLOR), ("vacío", EMPTY_COLOR)):
        part = shown[shown["estado"] == estado]
        if part.empty:
            continue
        fig.add_trace(go.Scattergl(
            x=part["v_max_retardo_kmh"], y=part["v_kmh"], mode="markers", name=estado,
            marker={"color": color, "size": 6, "opacity": 0.45},
            customdata=np.column_stack([part["unidad"], part["pend_pct"], part["dist_m"], part["curva_retardo"].map(_text)]),
            hovertemplate=hover,
        ))
    fig.add_trace(go.Scatter(
        x=[0, top], y=[0, top], mode="lines", name=t("opp.legend.retarder_limit"),
        line={"color": INK, "width": 1.5, "dash": "dash"}, hoverinfo="skip",
    ))
    return _style(fig, height=480, x=t("opp.axis.max_retarder_speed"), y=t("opp.axis.real_speed"),
                  xaxis={"range": [0, top]}, yaxis={"range": [0, top]})


def brakes_figure(frenos: Optional[pd.DataFrame]) -> go.Figure:
    """CDA: hottest of the four brakes per descent, weekly median, by truck and load state."""
    if frenos is None or frenos.empty:
        return empty_figure(t("opp.empty.no_brakes"))
    units = sorted(frenos["unidad"].unique())
    fig = go.Figure()
    for estado, color in (("cargado", LOADED_COLOR), ("vacío", EMPTY_COLOR)):
        part = frenos[frenos["estado"] == estado]
        if part.empty:
            continue
        fig.add_trace(go.Bar(
            x=part["unidad"], y=part["freno_max_p50_c"], name=estado, marker={"color": color, "line": {"width": 0}},
            customdata=np.column_stack([part["freno_max_p90_c"], part["bajadas"], part["freno_vs_flota_c"]]),
            hovertemplate="<b>%{x}</b> · " + estado + "<br>p50 %{y:.1f} °C · p90 %{customdata[0]:.1f} °C<br>"
            "%{customdata[1]} " + t("opp.hover.descents") + " · " + t("opp.hover.vs_fleet")
            + " %{customdata[2]:+.1f} °C<extra></extra>",
        ))
    _style(fig, height=400, x=t("opp.axis.unit"), y=t("opp.axis.brake_temp"),
           xaxis={"categoryorder": "array", "categoryarray": units, "type": "category"})
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08)
    return fig


# ------------------------------------------------------------------------------------------------
# Calidad de datos
# ------------------------------------------------------------------------------------------------

def quality_figure(calidad: Optional[pd.DataFrame], column: str = "horas_con_gps") -> go.Figure:
    """Hours of data per truck and day (0-24 h, white to blue)."""
    matrix = op.quality_matrix(calidad, column)
    if matrix.empty:
        return empty_figure(t("opp.empty.no_quality"))
    days = [pd.Timestamp(d).strftime("%d-%m") for d in matrix.columns]
    fig = go.Figure(go.Heatmap(
        z=matrix.values, x=days, y=matrix.index.tolist(), zmin=0, zmax=24,
        colorscale=[list(step) for step in SEQUENTIAL_SCALE], xgap=1, ygap=1,
        text=matrix.values, texttemplate="%{z:.0f}", textfont={"size": 10},
        colorbar={"title": {"text": "h", "side": "top"}, "thickness": 12, "len": 0.6},
        hovertemplate="<b>%{y}</b> · %{x}<br>%{z:.1f} h<extra></extra>",
    ))
    return _style(fig, height=_rows_height(len(matrix), per_row=20, base=100), legend=False, x=t("opp.axis.day"),
                  xaxis={"type": "category", "showgrid": False},
                  yaxis={"autorange": "reversed", "type": "category", "showgrid": False})
