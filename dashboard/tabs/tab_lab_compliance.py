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


def create_lab_compliance_tab() -> dbc.Container:
    """Create the Laboratory Compliance tab layout."""
    return dbc.Container([
        html.H3(t("tab_lab_compliance.cumplimiento_de_laboratorio"), className="mt-4 mb-3"),
        html.Hr(),

        # Date Range Filter
        dbc.Row([
            dbc.Col([
                html.Label(t("tab_lab_compliance.rango_de_fechas_fecha_de_reporte"), className="fw-bold small"),
                dcc.DatePickerRange(
                    id='lab-compliance-date-range',
                    display_format=t("tab_lab_compliance.yyyy_mm_dd"),
                    start_date_placeholder_text=t("tab_lab_compliance.fecha_inicio"),
                    end_date_placeholder_text=t("tab_lab_compliance.fecha_fin"),
                    className="mb-2"
                )
            ], md=6),
        ], className="mb-4 p-3 bg-light rounded"),

        # KPI Cards
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6(id='lab-kpi-1-title', children=t("tab_lab_compliance.tiempo_de_transito_prom"),
                                className="text-muted mb-1"),
                        html.H3(id='lab-kpi-1-value', children="—",
                                className="text-primary fw-bold mb-0"),
                        html.Small(t("tab_lab_compliance.dias_labdate_sampledate"), className="text-muted")
                    ])
                ], className="shadow-sm h-100")
            ], md=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6(id='lab-kpi-2-title', children=t("tab_lab_compliance.tiempo_de_laboratorio_prom"),
                                className="text-muted mb-1"),
                        html.H3(id='lab-kpi-2-value', children="—",
                                className="text-info fw-bold mb-0"),
                        html.Small(t("tab_lab_compliance.dias_reportdate_labdate"), className="text-muted")
                    ])
                ], className="shadow-sm h-100")
            ], md=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6(t("tab_lab_compliance.total_muestras"), className="text-muted mb-1"),
                        html.H3(id='lab-kpi-total-samples', children="—",
                                className="text-secondary fw-bold mb-0"),
                        html.Small(t("tab_lab_compliance.en_el_rango_seleccionado"), className="text-muted")
                    ])
                ], className="shadow-sm h-100")
            ], md=4),
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
