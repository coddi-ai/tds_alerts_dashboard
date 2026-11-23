"""
Laboratory Compliance Tab — July 2026 v4.

KPIs:
- Transit Time: labDate - sampleDate
- Lab Time: reportDate - labDate
- Edge case: if Lab Time has no positive values → show Diagnostic Time (reportDate - sampleDate)

Date Filtering: Uses reportDate as the date reference for period selection.

Visualization: Weekly grouped bar chart (Transit Time vs Lab Time side-by-side).
"""

from src.i18n import t
from dash import dcc, html
import dash_bootstrap_components as dbc

from dashboard.components.oil_ui import kpi_tile, page_header


def create_lab_compliance_tab() -> dbc.Container:
    """Create the Laboratory Compliance tab layout."""
    return dbc.Container([
        # "Total de muestras" is metadata, not a decision value: a caption under the title (§5).
        page_header(
            t("tab_lab_compliance.cumplimiento_de_laboratorio"),
            caption=html.Span([html.Span(id='lab-kpi-total-samples', children="—"), " ",
                               t("tab_lab_compliance.muestras_en_el_rango_seleccionado")]),
        ),
        html.Hr(),

        # Date Range Filter
        dbc.Row([
            dbc.Col([
                html.Label(t("tab_lab_compliance.rango_de_fechas_fecha_de_reporte"),
                           htmlFor='lab-compliance-date-range', className="fw-bold small d-block"),
                dcc.DatePickerRange(
                    id='lab-compliance-date-range',
                    display_format=t("tab_lab_compliance.yyyy_mm_dd"),
                    start_date_placeholder_text=t("tab_lab_compliance.fecha_inicio"),
                    end_date_placeholder_text=t("tab_lab_compliance.fecha_fin"),
                    className="mb-2"
                )
            ], md=6),
        ], className="mb-4 p-3 bg-light rounded"),

        # KPI tiles: neutral, no severity threshold is defined for turnaround times
        dbc.Row([
            dbc.Col(kpi_tile(
                t("tab_lab_compliance.tiempo_de_transito_prom"), "—", icon="fa-truck",
                label_id='lab-kpi-1-title', value_id='lab-kpi-1-value',
                caption=t("tab_lab_compliance.dias_labdate_sampledate")), md=6),
            dbc.Col(kpi_tile(
                t("tab_lab_compliance.tiempo_de_laboratorio_prom"), "—", icon="fa-flask",
                label_id='lab-kpi-2-title', value_id='lab-kpi-2-value',
                caption=t("tab_lab_compliance.dias_reportdate_labdate")), md=6),
        ], className="mb-4"),

        # Weekly Bar Chart
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(id='lab-weekly-chart-title',
                                   children=t("tab_lab_compliance.comparacion_semanal_tiempo_de_transito_vs")),
                    dbc.CardBody([
                        dcc.Graph(id='lab-compliance-weekly-chart',
                                  config={'displayModeBar': False},
                                  style={'height': '400px'})
                    ])
                ], className="shadow-sm")
            ], md=12)
        ], className="mb-4"),

        # Distribution by Unit
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(t("tab_lab_compliance.demora_promedio_por_unidad")),
                    dbc.CardBody([
                        dcc.Graph(id='lab-compliance-unit-chart',
                                  config={'displayModeBar': False},
                                  style={'height': '400px'})
                    ])
                ], className="shadow-sm")
            ], md=12)
        ], className="mb-4"),

    ], fluid=True, className="p-0")
