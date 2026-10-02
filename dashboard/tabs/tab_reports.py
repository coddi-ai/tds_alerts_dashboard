"""
Reports Detail tab for Multi-Technical-Alerts dashboard.

Updated July 2026 v2:
- Removed Evidence by Test section
- Removed radar charts
- Added detected anomaly to decision summary
- Time series: DatePickerRange instead of dropdown, only upper condemnation limit
- Added Advanced Analytics section at end
"""

from src.i18n import t
from dash import dcc, html
import dash_bootstrap_components as dbc


def create_reports_tab() -> dbc.Container:
    """Create Tab: Reports Detail Analysis."""
    return dbc.Container([
        html.H3(t("tab_reports.analisis_detallado_de_reportes"), className="mt-4 mb-3"),
        html.Hr(),

        # ========================================
        # STICKY REPORT IDENTITY HEADER
        # ========================================
        html.Div([
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label(t("tab_reports.familia"), className="fw-bold mb-1", style={'fontSize': '0.85rem'}),
                            dcc.Dropdown(id='reports-familia-selector',
                                         placeholder=t("tab_reports.tipo_de_maquina"), className="mb-2")
                        ], width=3),
                        dbc.Col([
                            html.Label(t("tab_machines.equipo"), className="fw-bold mb-1", style={'fontSize': '0.85rem'}),
                            dcc.Dropdown(id='reports-equipo-selector',
                                         placeholder=t("tab_machines.equipo_2"), className="mb-2")
                        ], width=3),
                        dbc.Col([
                            html.Label(t("tab_machines.componente"), className="fw-bold mb-1", style={'fontSize': '0.85rem'}),
                            dcc.Dropdown(id='reports-component-selector',
                                         placeholder=t("tab_machines.componente_2"), className="mb-2")
                        ], width=3),
                        dbc.Col([
                            html.Label(t("tab_reports.fecha_muestra"), className="fw-bold mb-1", style={'fontSize': '0.85rem'}),
                            dcc.Dropdown(id='reports-date-selector',
                                         placeholder=t("tab_reports.fecha"), className="mb-2")
                        ], width=3)
                    ]),
                    html.Div(id='reports-identity-display')
                ])
            ], className="mb-2")
        ], style={
            'position': 'sticky', 'top': '80px', 'zIndex': '999',
            'backgroundColor': '#f8f9fa', 'paddingTop': '10px', 'paddingBottom': '10px'
        }),

        # ========================================
        # DECISION SUMMARY (includes anomaly type)
        # ========================================
        dbc.Card([
            dbc.CardHeader(t("tab_reports.resumen_de_decision"), className="fw-bold bg-primary text-white"),
            dbc.CardBody(
                html.Div(id='reports-decision-summary')
            )
        ], className="mb-4"),

        # ========================================
        # AI RECOMMENDATION
        # ========================================
        dbc.Card([
            dbc.CardHeader(t("tab_reports.analisis_y_recomendacion_de_ia"), className="fw-bold bg-info text-white"),
            dbc.CardBody(
                html.Div(id='reports-ai-diagnosis')
            )
        ], className="mb-4"),

        # ========================================
        # EVIDENCE BY TEST - REMOVED (July 2026 v2)
        # Kept as hidden container for callback compatibility
        # ========================================
        html.Div(id='reports-evidence-container', style={'display': 'none'}),

        # ========================================
        # TIME SERIES ANALYSIS (DatePickerRange, upper limit only)
        # ========================================
        dbc.Card([
            dbc.CardHeader(t("tab_reports.analisis_de_series_temporales"), className="fw-bold"),
            dbc.CardBody([
                html.P(
                    t("tab_reports.evolucion_de_variables_de_analisis_de"),
                    className="text-muted mb-3"
                ),
                dcc.Tabs(
                    id='reports-oil-view-selector',
                    value='tendencia',
                    children=[
                        dcc.Tab(label=t("tab_reports.tendencia"), value='tendencia',
                                className='custom-tab', selected_className='custom-tab--selected'),
                        dcc.Tab(label=t("tab_reports.ultimo_ensayo"), value='ultimo_ensayo',
                                className='custom-tab', selected_className='custom-tab--selected'),
                    ],
                    className='mb-3'
                ),
                html.Div(id='reports-tendencia-view', children=[
                    # Dedicated filter toolbar — visually separated from the chart grid (FR-04)
                    html.Div([
                        dbc.Row([
                            dbc.Col([
                                html.Label(t("tab_reports.rango_de_fechas"), className="fw-bold small mb-1 d-block"),
                                dcc.DatePickerRange(
                                    id='reports-date-range-picker',
                                    display_format=t("tab_lab_compliance.yyyy_mm_dd"),
                                    start_date_placeholder_text=t("tab_lab_compliance.fecha_inicio"),
                                    end_date_placeholder_text=t("tab_lab_compliance.fecha_fin"),
                                )
                            ], width="auto"),
                        ], align="center", className="g-3"),
                    ], className="p-3 mb-4", style={
                        'backgroundColor': '#f8f9fa',
                        'border': '1px solid #e9ecef',
                        'borderRadius': '6px'
                    }),
                    dcc.Loading(
                        html.Div(id='reports-time-series-grid'),
                        type="circle"
                    ),
                ]),
                html.Div(id='reports-ultimo-ensayo-view', style={'display': 'none'}, children=[
                    dcc.Loading(
                        html.Div(id='reports-oil-radar-view'),
                        type="circle"
                    ),
                ]),
                # Hidden elements for backward callback compatibility
                html.Div([
                    dcc.Dropdown(id='reports-time-range-selector', value='ALL', style={'display': 'none'}),
                    dcc.Dropdown(id='reports-essays-selector', multi=True, style={'display': 'none'}),
                    dcc.Graph(id='reports-time-series-chart', style={'display': 'none'})
                ], style={'display': 'none'})
            ])
        ], className="mb-4"),

        # ========================================
        # DELTA SUMMARY (Analysis vs Previous Report)
        # ========================================
        dbc.Card([
            dbc.CardHeader(t("tab_reports.analisis_de_cambios_vs_reporte_anterior"), className="fw-bold"),
            dbc.CardBody(
                html.Div(id='reports-delta-summary')
            )
        ], className="mb-4"),

        # ========================================
        # COMMENT HISTORY (traceability by unit/component)
        # ========================================
        dbc.Card([
            dbc.CardHeader(t("tab_reports.historial_de_comentarios"), className="fw-bold"),
            dbc.CardBody([
                html.P(
                    t("tab_reports.historial_de_comentarios_recomendaciones_p"),
                    className="text-muted mb-3"
                ),
                html.Div(id='reports-comment-history-container')
            ])
        ], className="mb-4"),

        # ========================================
        # ADVANCED ANALYTICS (new section)
        # ========================================
        dbc.Card([
            dbc.CardHeader(t("tab_reports.analitica_avanzada"), className="fw-bold"),
            dbc.CardBody([
                html.P(
                    t("tab_reports.genere_un_grafico_de_tendencia_personaliza"),
                    className="text-muted mb-3"
                ),
                dbc.Row([
                    dbc.Col([
                        html.Label(t("tab_reports.variables"), className="fw-bold small"),
                        dcc.Dropdown(
                            id='advanced-analytics-variables',
                            placeholder=t("tab_reports.seleccionar_variables"),
                            multi=True,
                            className="mb-2"
                        )
                    ], md=6),
                    dbc.Col([
                        html.Label(t("tab_reports.opciones"), className="fw-bold small"),
                        dbc.Checklist(
                            id='advanced-analytics-show-limits',
                            options=[{'label': t("tab_reports.mostrar_limite_condenatorio"), 'value': 'show'}],
                            value=['show'],
                            inline=True,
                            className="mt-1"
                        )
                    ], md=4),
                    dbc.Col([
                        html.Label("\u00a0", className="small"),
                        dbc.Button(t("tab_reports.generar"), id='advanced-analytics-generate',
                                   color="primary", size="sm", className="w-100")
                    ], md=2),
                ]),
                dcc.Loading(
                    html.Div(id='advanced-analytics-chart-container', className="mt-3"),
                    type="circle"
                )
            ])
        ], className="mb-4"),

    ], fluid=True)
