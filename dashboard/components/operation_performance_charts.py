"""Figures of Monitoreo > Operación y rendimiento (one function per panel of the OP-PE specification).

Pure functions: DataFrames in, a Plotly figure out (the data rules live in
src/data/operation_performance.py). Titles and "how to read" notes are rendered by the panel card
around each figure (dashboard/components/operation_performance_views.py), so figures carry no title.

On the page today: ranking, ramp map, curve and ramp boxes. The diagnosis (causes, lost minutes,
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

def curve_figure(pasadas: Optional[pd.DataFrame], curvas: Optional[pd.DataFrame], model: Optional[str],
                 highlight: Sequence[str] = ()) -> go.Figure:
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
    highlight = [u for u in highlight if u in set(climbs["unidad"])]
    rest = op.sample(climbs[~climbs["unidad"].isin(highlight)])
    point_hover = ("<b>%{customdata[0]}</b> · " + t("opp.hover.slope") + " %{customdata[1]:.1f} % · %{customdata[2]:.0f} t<br>"
                   "%{x:.1f} km/h · IV %{customdata[3]:.2f}<extra></extra>")

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
            marker={"color": CAUSE_COLORS[index % len(CAUSE_COLORS)], "size": 8, "opacity": 0.85,
                    "line": {"color": "#ffffff", "width": 1}},
            customdata=custom(part), hovertemplate=point_hover,
        ))
    return _style(fig, height=500, x=t("opp.axis.speed"), y=t("opp.axis.force_log"),
                  xaxis={"range": [0, x_max]}, yaxis={"type": "log"})


def ramp_box_figure(climbs: pd.DataFrame, camiones: Optional[pd.DataFrame], metric: str = "hp_pendiente",
                    selected: Optional[str] = None) -> go.Figure:
    """One box per truck on a ramp (alphabetical), colored by the truck's decision; fleet median marked.
    The selected unit's box is drawn bold, with its own legend entry."""
    climbs = climbs.dropna(subset=[metric]) if not climbs.empty else climbs
    if climbs.empty:
        return empty_figure(t("opp.empty.no_ramp_climbs"))
    decisions = {}
    if camiones is not None and not camiones.empty:
        decisions = dict(zip(camiones["unidad"], camiones["decision"]))
    df = climbs.assign(decision=climbs["unidad"].map(decisions).fillna(op.SIN_DATOS))
    units = sorted(df["unidad"].unique())
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
    _style(fig, height=460, x=t("opp.axis.unit"), y=label,
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


def _map_view(lat: pd.Series, lon: pd.Series) -> dict:
    """Center and zoom that fit the points (a ~1.000 x 560 px map)."""
    lat_span = float(lat.max() - lat.min()) or 0.005
    lon_span = float(lon.max() - lon.min()) or 0.005
    span = max(lon_span, 1.8 * lat_span, 0.002)
    zoom = float(np.clip(9.4 - np.log2(span), 10, 16.5))
    return {"center": {"lat": float((lat.max() + lat.min()) / 2), "lon": float((lon.max() + lon.min()) / 2)},
            "zoom": zoom}


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

    # Ramp ids at the top of each path, so a ramp named in a list can be found on the map.
    tops = segments.sort_values("k").groupby("rampa_id", sort=False).tail(1)
    fig.add_trace(go.Scattermap(
        lat=tops["lat"], lon=tops["lon"], mode="text", text=tops["rampa_id"], showlegend=False,
        textfont={"size": 11, "color": "#ffffff" if base == "satelite" else INK}, textposition="top right",
        hoverinfo="skip",
    ))

    view = _map_view(segments["lat"], segments["lon"])
    if base == "satelite":
        map_layout = {"style": "white-bg", "layers": [{
            "below": "traces", "sourcetype": "raster", "sourceattribution": SATELLITE_ATTRIBUTION,
            "source": [SATELLITE_TILES]}]}
    else:
        map_layout = {"style": "open-street-map"}
    fig.update_layout(
        map={**map_layout, **view}, height=580, margin={"l": 0, "r": 0, "t": 0, "b": 0},
        separators=separators(), font={"family": FONT_FAMILY, "size": 12, "color": INK},
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": BRAND_AXIS}, showlegend=False,
        # Keep the user's pan and zoom when the coloring, the unit or the selected ramp change.
        uirevision="opp-map",
    )
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
