"""
Análisis por Componente (Monitor de Aceite): one critical component (Motor, Transmisión, Convertidor or
Diferencial) across the whole fleet. How many there are, how many are in Alerta or Anormal, which anomaly
types and which essays out of limit are the most frequent, and how recent the last sample is.

A preview: the names behind each option, the stale threshold (90 days) and the age buckets are read
from config/component_analysis.yaml. The rules live in src/data/component_analysis.py. The tab is
read-only; every figure comes from the latest sample of each unit + component in `classified.parquet`.
"""

from dash import dcc, html
import dash_bootstrap_components as dbc

from dashboard.components.oil_component_analysis import (
    BUTTON_TYPE,
    COMPONENT_ID,
    FALLBACK_COMPONENTS,
    SOURCE_ID,
    TABLE,
    TABLE_ID,
    criticality_text,
    default_component,
    matrix_title,
    render_header,
    words,
)
from dashboard.components.oil_table import stores
from dashboard.components.oil_ui import filter_field, severity_style
from src.data import component_analysis as ca
from src.i18n import t

SELECTOR_LABEL_ID = "ca-selector-label"
CRITICALITY_ID = "ca-criticality"
HEADER_ID = "ca-header"
FLEET_ID = "ca-fleet-filter"
SHOW_ID = "ca-show"
INCLUDE_ID = "ca-include-all"


def _options():
    """The options of the selector, in the order of the configuration, and the configuration."""
    try:
        config = ca.load_config()
        return list(config.components), config
    except ca.ComponentAnalysisConfigError:
        return list(FALLBACK_COMPONENTS), None      # the data callbacks tell the user what is wrong


def selector(selected: str) -> html.Div:
    """The "Componente" segmented control: one real button per option, `aria-pressed` on the selected
    one, and next to it the criticality class of that option. The buttons are static (a callback only
    flips `aria-pressed` and the chip), so the one that was just pressed keeps the keyboard focus."""
    keys, config = _options()
    buttons = [
        html.Button(
            words(key).title, id={"type": BUTTON_TYPE, "key": key}, className="oil-segmented__btn", type="button",
            n_clicks=0, **{"aria-pressed": "true" if key == selected else "false"},
        )
        for key in keys
    ]
    chip = html.Span(criticality_text(config, selected) if config else "", id=CRITICALITY_ID,
                     className="kpi-chip oil-neutral-chip")
    return html.Div([
        html.Span(t("component_analysis.selector_componente"), id=SELECTOR_LABEL_ID, className="oil-filter-label mb-0"),
        html.Div(buttons, className="oil-segmented", role="group", **{"aria-labelledby": SELECTOR_LABEL_ID}),
        chip,
    ], className="oil-selector mb-2")


def _matrix_card(selected: str) -> dbc.Card:
    """"Qué Explica el Estado de cada <Componente>": its two controls, the level legend, the matrix and its footnote."""
    controls = html.Div([
        html.Div([
            html.Label(t("component_analysis.mostrar"), htmlFor=SHOW_ID, className="oil-filter-label mb-0"),
            dcc.Dropdown(
                id=SHOW_ID, value=ca.SHOW_ALERTA_ANORMAL, clearable=False, searchable=False,
                options=[{"label": t("component_analysis.mostrar_alerta_anormal"), "value": ca.SHOW_ALERTA_ANORMAL},
                         {"label": t("component_analysis.mostrar_anormal"), "value": ca.SHOW_ANORMAL},
                         {"label": t("component_analysis.mostrar_todos"), "value": ca.SHOW_TODOS}],
                className="oil-matrix-show",
            ),
        ], className="oil-matrix-control"),
        dbc.Checkbox(id=INCLUDE_ID, label=t("component_analysis.incluir_ensayos"), value=False, className="oil-matrix-include"),
    ], className="oil-matrix-controls")
    level_legend = html.Div([
        html.Span(t("component_analysis.leyenda_nivel"), className="oil-legend__title"),
        html.Span(t("component_analysis.nivel_cond_abrev"), className="oil-level-pill oil-level-pill--legend",
                  style=severity_style("alto")),
        html.Span(t("component_analysis.nivel_condenatorio")),
        html.Span(t("component_analysis.nivel_marg_abrev"), className="oil-level-pill oil-level-pill--legend",
                  style=severity_style("atencion")),
        html.Span(t("component_analysis.nivel_marginal")),
        html.Span(t("component_analysis.ensayos_leyenda_nota"), className="oil-caption"),
    ], className="oil-level-legend")
    return dbc.Card([
        dbc.CardHeader(dbc.Row([
            dbc.Col([
                html.H5(matrix_title({"component": selected}), id="ca-matrix-title", className="fw-bold d-inline mb-0"),
                html.Span(id="ca-count-chip"),
            ], md=6),
            dbc.Col(controls, md=6),
        ], align="center")),
        dbc.CardBody([
            level_legend,
            dcc.Loading(html.Div(id=TABLE_ID), type="circle", delay_show=250),
            html.P(t("component_analysis.matriz_nota"), className="oil-footnote mb-0"),
        ]),
    ], className="shadow-sm mb-4")


def create_component_analysis_tab() -> dbc.Container:
    """Create Tab: Análisis por Componente."""
    selected = default_component()
    return dbc.Container([
        selector(selected),
        html.Div(render_header({"component": selected}), id=HEADER_ID),
        html.Hr(),

        # The only filter: Flota (Tipo de Equipo). Nothing is displayed until one is selected.
        dbc.Row([
            filter_field(t("component_analysis.filtro_flota"),
                         dcc.Dropdown(id=FLEET_ID, placeholder=t("component_analysis.seleccionar"), className="mb-2"),
                         FLEET_ID, md=6, lg=3),
        ], className="mb-3 p-3 bg-light rounded"),

        html.Div(id="ca-kpis", className="mb-2"),
        html.Div(id="ca-age", className="mb-0"),
        dbc.Row([
            dbc.Col(html.Div(id="ca-anomalies", className="h-100"), lg=5, className="mb-0"),
            dbc.Col(html.Div(id="ca-essays", className="h-100"), lg=7, className="mb-0"),
        ], className="g-3"),
        _matrix_card(selected),

        dcc.Store(id=COMPONENT_ID, data=selected),
        dcc.Store(id=SOURCE_ID),
        *stores(TABLE),
    ], fluid=True)
