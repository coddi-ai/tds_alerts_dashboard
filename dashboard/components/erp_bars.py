"""Horizontal bar visuals of Seguimiento de Avisos, drawn as HTML rather than Plotly.

A severity row needs its chip as the label, which a Plotly axis can't carry; doing all the
bar charts the same way keeps their rows, values and legends identical. Every row prints its
numbers as text, and the bars themselves are `aria-hidden` decoration.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from dash import html

from dashboard.components.erp_chips import (
    CLASSIFICATION_SEGMENT_OUTLINE,
    CLASSIFICATION_STYLES,
    ESTADO_STYLES,
    SEVERITY_ORDER,
    SEVERITY_STYLES,
    classification_label,
    estado_label,
    severity_chip,
)
from src.i18n import t

_SYSTEM_BAR_COLOR = "#475569"


def percent(count: int, total: int) -> str:
    """'42 %' of the total ('0 %' when there is nothing to divide by)."""
    return f"{(count / total * 100 if total else 0):.0f} %"


def empty_state(message: str, icon: str = "fa-inbox") -> html.Div:
    return html.Div(
        [html.I(className=f"fas {icon}", **{"aria-hidden": "true"}), html.P(message, className="mb-0")],
        className="erp-empty",
        role="status",
    )


def _segment(width_pct: float, color: str, outline: str | None = None, title: str = "") -> html.Span:
    style = {"width": f"{width_pct:.4f}%", "background": color}
    if outline:
        style["boxShadow"] = f"inset 0 0 0 2px {outline}"
    return html.Span(className="erp-bar__segment", style=style, title=title)


def _row(label, segments: Sequence, value_text: str, fill_pct: float) -> html.Li:
    return html.Li(
        [
            html.Div(label, className="erp-bar-row__label"),
            html.Div(
                html.Div(list(segments), className="erp-bar-row__fill", style={"width": f"{fill_pct:.4f}%"}),
                className="erp-bar-row__track",
                **{"aria-hidden": "true"},
            ),
            html.Div(value_text, className="erp-bar-row__value"),
        ],
        className="erp-bar-row",
    )


def _legend_item(swatch: html.Span, text: str) -> html.Li:
    return html.Li([swatch, html.Span(text)], className="erp-legend__item")


def lifecycle_bar(pending: int, sent: int, rejected: int) -> html.Div:
    """One stacked bar of Pendiente / Enviado / Rechazado, proportional to the counts, with a
    legend that repeats them as text. `sent` already includes validated warnings."""
    total = pending + sent + rejected
    parts = [("pending", pending), ("sent", sent), ("rejected", rejected)]
    if not total:
        return empty_state(t("tab_integration_seguimiento_avisos.sin_avisos_para_los_filtros"))
    summary = "; ".join(f"{estado_label(key)}: {count}" for key, count in parts)
    segments = [
        _segment(count / total * 100, ESTADO_STYLES[key]["fill"], title=f"{estado_label(key)}: {count}")
        for key, count in parts
        if count
    ]
    legend = [
        _legend_item(
            html.Span(className="erp-legend__swatch", style={"background": ESTADO_STYLES[key]["fill"]}),
            f"{estado_label(key)} · {count} ({percent(count, total)})",
        )
        for key, count in parts
    ]
    return html.Div(
        [
            html.Div(
                segments,
                className="erp-lifecycle__bar",
                role="img",
                **{"aria-label": t("tab_integration_seguimiento_avisos.ciclo_de_vida_resumen", summary=summary)},
            ),
            html.Ul(legend, className="erp-legend"),
        ]
    )


def source_classification_bars(rows: Iterable[tuple[str, int, int]]) -> html.Div:
    """Per Fuente, one stacked bar split Anormal / Alerta. `rows` are (Fuente label, anormal,
    alerta); the value column reads 'total (anormal / alerta)'. Bars share one scale, so a
    longer bar always means more warnings."""
    rows = sorted(rows, key=lambda r: (-(r[1] + r[2]), r[0]))
    if not rows:
        return empty_state(t("tab_integration_seguimiento_avisos.sin_avisos_para_los_filtros"))
    top = max(anormal + alerta for _, anormal, alerta in rows) or 1
    anormal_style, alerta_style = CLASSIFICATION_STYLES["anormal"], CLASSIFICATION_STYLES["alerta"]
    body = []
    for source, anormal, alerta in rows:
        total = anormal + alerta
        segments = []
        if anormal:
            segments.append(
                _segment(anormal / total * 100, anormal_style["fill"], title=f"{classification_label('anormal')}: {anormal}")
            )
        if alerta:
            segments.append(
                _segment(
                    alerta / total * 100,
                    alerta_style["fill"],
                    outline=CLASSIFICATION_SEGMENT_OUTLINE,
                    title=f"{classification_label('alerta')}: {alerta}",
                )
            )
        body.append(_row(source, segments, f"{total} ({anormal} / {alerta})", total / top * 100))
    legend = html.Ul(
        [
            _legend_item(
                html.Span(className="erp-legend__swatch", style={"background": anormal_style["fill"]}),
                classification_label("anormal"),
            ),
            _legend_item(
                html.Span(
                    className="erp-legend__swatch",
                    style={"background": alerta_style["fill"], "boxShadow": f"inset 0 0 0 2px {CLASSIFICATION_SEGMENT_OUTLINE}"},
                ),
                classification_label("alerta"),
            ),
        ],
        className="erp-legend",
    )
    return html.Div([legend, html.Ul(body, className="erp-bar-list")])


def severity_bars(counts: dict[str, int]) -> html.Div | html.Ul:
    """Crítico -> Alto -> Medio (Bajo only when present), the severity chip as each row's label."""
    total = sum(counts.values())
    if not total:
        return empty_state(t("tab_integration_seguimiento_avisos.sin_avisos_para_los_filtros"))
    keys = [k for k in SEVERITY_ORDER if k != "low" or counts.get(k)]
    top = max(counts.get(k, 0) for k in keys) or 1
    body = [
        _row(
            severity_chip(key),
            [_segment(100, SEVERITY_STYLES[key]["dot"])] if counts.get(key) else [],
            f"{counts.get(key, 0)} · {percent(counts.get(key, 0), total)}",
            counts.get(key, 0) / top * 100,
        )
        for key in keys
    ]
    return html.Ul(body, className="erp-bar-list")


def system_bars(counts: dict[str, int]) -> html.Div | html.Ul:
    """Every Sistema with warnings, most first."""
    total = sum(counts.values())
    if not total:
        return empty_state(t("tab_integration_seguimiento_avisos.sin_avisos_para_los_filtros"))
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    top = ordered[0][1] or 1
    body = [
        _row(label, [_segment(100, _SYSTEM_BAR_COLOR)], f"{count} · {percent(count, total)}", count / top * 100)
        for label, count in ordered
    ]
    return html.Ul(body, className="erp-bar-list")
