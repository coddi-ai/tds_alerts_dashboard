"""
Componentes de gráficos para la página de evidencia.
"""
from src.i18n import t as _t
from dashboard.components.labels import status_label
import plotly.graph_objects as go
import pandas as pd

from dashboard.components.oil_charts import (
    get_essay_limits_four,
    consolidate_limit_entries,
    limit_line_color,
)


def _oil_date_col(df) -> str:
    """
    Nombre de la columna de fecha de las muestras de aceite.
    CDA usa 'sampleDate'; Capstone no la tiene y usa 'Fecha' para todo.
    """
    if "sampleDate" in df.columns:
        return "sampleDate"
    return "Fecha"


FLEET_SCATTER_THRESHOLD = 50.0  # splits both axes (ranking today / 30d average)


def create_fleet_scatter(df_latest, selected_unit, status_colors):
    """
    Crear scatter de ranking vs avg_ranking_30d con todos los equipos.
    Destaca el equipo seleccionado. Ambos ejes se dividen en
    FLEET_SCATTER_THRESHOLD para formar las cuatro regiones.
    """
    x_all = df_latest["ranking"].astype(float)
    y_all = df_latest["avg_ranking_30d"].astype(float)

    x_thresh = y_thresh = FLEET_SCATTER_THRESHOLD

    x_min, x_max = float(x_all.min()), float(x_all.max())
    y_min, y_max = float(y_all.min()), float(y_all.max())
    x_pad = max((x_max - x_min) * 0.12, 5)
    y_pad = max((y_max - y_min) * 0.12, 2)
    # The range always contains the threshold, so no region collapses when the
    # whole fleet sits on one side of it.
    x0, x1 = max(0, min(x_min - x_pad, x_thresh - 5)), max(x_max + x_pad, x_thresh + 5)
    y0, y1 = max(0, min(y_min - y_pad, y_thresh - 5)), max(y_max + y_pad, y_thresh + 5)

    fig = go.Figure()

    # Quadrant fills
    for (qx0, qy0, qx1, qy1), color in [
        ((x_thresh, y_thresh, x1, y1), "rgba(226,75,74,0.05)"),
        ((x_thresh, y0, x1, y_thresh), "rgba(239,159,39,0.05)"),
        ((x0, y_thresh, x_thresh, y1), "rgba(239,159,39,0.05)"),
        ((x0, y0, x_thresh, y_thresh), "rgba(29,158,117,0.05)"),
    ]:
        fig.add_shape(
            type="rect", x0=qx0, y0=qy0, x1=qx1, y1=qy1,
            fillcolor=color, line_width=0, layer="below"
        )

    # Dividers
    fig.add_shape(
        type="line", x0=x_thresh, y0=y0, x1=x_thresh, y1=y1,
        line=dict(color="rgba(0,0,0,0.12)", width=1, dash="dot")
    )
    fig.add_shape(
        type="line", x0=x0, y0=y_thresh, x1=x1, y1=y_thresh,
        line=dict(color="rgba(0,0,0,0.12)", width=1, dash="dot")
    )

    # Quadrant labels
    ql = dict(
        showarrow=False, font=dict(size=9, color="rgba(0,0,0,0.2)"),
        xanchor="center", yanchor="middle"
    )
    fig.add_annotation(x=(x_thresh + x1) / 2, y=(y_thresh + y1) / 2, text=_t("predictive_charts.critica_sostenida"), **ql)
    fig.add_annotation(x=(x_thresh + x1) / 2, y=(y0 + y_thresh) / 2, text=_t("predictive_charts.empeoro_de_golpe"), **ql)
    fig.add_annotation(x=(x0 + x_thresh) / 2, y=(y_thresh + y1) / 2, text=_t("predictive_charts.mejoro_recientemente"), **ql)
    fig.add_annotation(x=(x0 + x_thresh) / 2, y=(y0 + y_thresh) / 2, text=_t("predictive_charts.zona_saludable"), **ql)

    # Fleet points (all units except selected)
    for st, color in status_colors.items():
        mask = (df_latest["status"] == st) & (df_latest["Unit"] != selected_unit)
        subset = df_latest[mask]
        if subset.empty:
            continue
        fig.add_trace(go.Scatter(
            x=subset["ranking"].astype(float),
            y=subset["avg_ranking_30d"].astype(float),
            mode="markers+text",
            name=status_label(st),
            text=subset["Unit"],
            customdata=subset["Unit"],  # read back by click-to-Evidence
            textposition="top center",
            textfont=dict(size=9, color=color),
            marker=dict(
                color=color, size=8,
                line=dict(color="white", width=1.2), opacity=0.5
            ),
            hovertemplate=_t("predictive_charts.b_b_br_ranking_br_prom"),
        ))

    # Selected unit — highlighted
    sel = df_latest[df_latest["Unit"] == selected_unit]
    if not sel.empty:
        fig.add_trace(go.Scatter(
            x=sel["ranking"].astype(float),
            y=sel["avg_ranking_30d"].astype(float),
            mode="markers+text",
            name=selected_unit,
            text=[selected_unit],
            customdata=[selected_unit],
            textposition="top center",
            textfont=dict(size=11, color="#2563EB", family="DM Sans"),
            marker=dict(
                color="#2563EB", size=14,
                line=dict(color="white", width=2), opacity=1.0
            ),
            hovertemplate=_t("predictive_charts.b_b_br_ranking_br_prom_2", selected_unit=selected_unit),
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=380,
        margin=dict(l=60, r=20, t=20, b=50),
        showlegend=False,
        xaxis=dict(
            title=_t("tab_predictive_evidence.ranking_actual"),
            showgrid=True, gridcolor="rgba(0,0,0,0.05)",
            zeroline=False, tickfont=dict(size=10), range=[x0, x1]
        ),
        yaxis=dict(
            title=_t("predictive_charts.ranking_30_dias"),
            showgrid=True, gridcolor="rgba(0,0,0,0.05)",
            zeroline=False, tickfont=dict(size=10), range=[y0, y1]
        ),
        hovermode="closest",
    )

    return fig


def create_comparative_bars(unit_row, df_latest, failure_modes):
    """
    Crear gráfico de barras horizontales comparativas para modos de falla.
    Reemplaza el radar por mejor legibilidad.
    """
    fm_keys = list(failure_modes.keys())
    fm_labels = [failure_modes[k] for k in fm_keys]
    
    # Valores del equipo seleccionado (use 30d averages for consistency)
    unit_vals = [
        float(unit_row[f"{k}_30d"]) if f"{k}_30d" in unit_row.index and pd.notna(unit_row[f"{k}_30d"]) else 0.0
        for k in fm_keys
    ]
    
    # Valores promedio de la flota (use 30d averages)
    fleet_vals = [
        float(df_latest[f"{k}_30d"].mean()) if f"{k}_30d" in df_latest.columns else 0.0
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


def classify_criticidad(value):
    """Band index (0..3) of a risk score, or None when there is no score -
    a missing day is "no data", never implicitly Saludable."""
    if value is None or pd.isna(value):
        return None
    return sum(float(value) >= edge for edge in _CRITICIDAD_EDGES)


def create_mode_status_calendar(df_unit, failure_modes, end_date, days=90):
    """Calendar heatmap: one row per failure mode, one column per day over the
    `days` days ending at `end_date`, coloured by the criticidad band of that
    day's `risk_value`. `df_unit` is the unit's wide risk frame (Fecha + one
    column per mode); a mode/day with no value renders as "Sin datos".
    Dotted vertical lines mark each Monday (week start).
    """
    if df_unit is None or df_unit.empty or end_date is None:
        return None
    modes = [k for k in failure_modes if k in df_unit.columns]
    if not modes:
        return None

    end = pd.Timestamp(end_date).normalize()
    dates = pd.date_range(end=end, periods=days, freq="D")
    daily = (
        df_unit.assign(Fecha=pd.to_datetime(df_unit["Fecha"]).dt.normalize())
        .drop_duplicates(subset="Fecha", keep="last")
        .set_index("Fecha")
        .reindex(dates)[modes]
    )
    # Worst mode on top: order by mean over the window, ties by catalogue order.
    order = sorted(modes, key=lambda m: (-(daily[m].mean() if daily[m].notna().any() else -1.0), modes.index(m)))

    z, hover = [], []
    for m in order:
        row_z, row_h = [], []
        for d, v in zip(dates, daily[m]):
            band = classify_criticidad(v)
            row_z.append(_NO_DATA_CODE if band is None else band)
            row_h.append(
                _t("predictive_charts.sin_datos", d=d) if band is None
                else f"{d:%d %b %Y}: {float(v):.1f} · {_band_label(band)}"
            )
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