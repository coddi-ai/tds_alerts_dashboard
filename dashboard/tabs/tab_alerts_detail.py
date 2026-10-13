"""
Alerts Detail Tab Layout.

Displays detailed view for a selected alert with:
- Alert Specification Card
- Telemetry Evidence (conditional: if Trigger_type in ['Telemetria', 'Mixto'])
  - Sensor Trends (time series)
  - GPS Route Map
  - Alert Context KPIs
- Oil Evidence (conditional: if Trigger_type in ['Tribologia', 'Mixto'])
  - Essay Levels (radar chart)
  - Report Status
- Maintenance Evidence (always displayed if available)
  - Weekly Maintenance Summary
"""

from src.i18n import t
from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create layout for Alerts Detail tab.
    
    Returns:
        Dash HTML Div with complete detail tab layout
    """
    logger.info("Creating Alerts Detail Tab layout")
    
    layout = html.Div([
        # Page Header
        html.Div([
            html.H3([
                html.I(className="fas fa-microscope me-2"),
                t("tab_alerts_detail.analisis_detallado_de_alerta")
            ], className="text-primary mb-2"),
            html.P(t("tab_alerts_detail.explore_evidencia_completa_de_telemetria_t"), 
                   className="text-muted")
        ], className="mb-4"),
        
        # Filters Section
        dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-filter me-2"),
                    t("tab_alerts_detail.filtros_de_busqueda")
                ], className="mb-0")
            ], className="bg-light"),
            dbc.CardBody([
                dbc.Row([
                    # Unit Filter
                    dbc.Col([
                        html.Label([
                            html.I(className="fas fa-truck me-1"),
                            t("tab_alerts_detail.unidad")
                        ], className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='detail-filter-unit',
                            placeholder=t("tab_alerts_detail.todas_las_unidades"),
                            clearable=True,
                            searchable=True,
                            multi=True
                        )
                    ], md=3),
                    
                    # System Filter
                    dbc.Col([
                        html.Label([
                            html.I(className="fas fa-cogs me-1"),
                            t("tab_alerts_detail.sistema")
                        ], className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='detail-filter-sistema',
                            placeholder=t("tab_alerts_detail.todos_los_sistemas"),
                            clearable=True,
                            multi=True
                        )
                    ], md=3),
                    
                    # W34-05: Date-from filter (replaces "Con Telemetría").
                    # Inclusive: an alert exactly at midnight of the chosen
                    # Chile calendar day is included. No date = no lower
                    # bound. See filter_alert_dropdown_by_criteria for the
                    # UTC-naive Timestamp comparison this drives.
                    dbc.Col([
                        html.Label([
                            html.I(className="fas fa-calendar-alt me-1"),
                            t("tab_alerts_detail.fecha_desde")
                        ], className="fw-bold mb-2"),
                        dcc.DatePickerSingle(
                            id='detail-filter-date-from',
                            placeholder=t("tab_alerts_detail.sin_limite"),
                            display_format='DD/MM/YYYY',
                            clearable=True,
                            className='w-100'
                        )
                    ], md=3),

                    # Has Tribology Filter
                    dbc.Col([
                        html.Label([
                            html.I(className="fas fa-oil-can me-1"),
                            t("tab_alerts_detail.con_tribologia")
                        ], className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='detail-filter-tribology',
                            options=[
                                {'label': t("tab_alerts_detail.si"), 'value': 'yes'},
                                {'label': t("tab_alerts_detail.no"), 'value': 'no'}
                            ],
                            placeholder=t("tab_alerts_detail.todos"),
                            clearable=True
                        )
                    ], md=3)
                ], className="g-3")
            ])
        ], className="shadow-sm mb-4"),
        
        # Alert Selector
        dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-bullseye me-2"),
                    t("tab_alerts_detail.seleccion_de_alerta")
                ], className="mb-0")
            ], className="bg-primary text-white"),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label([
                            html.I(className="fas fa-search me-1"),
                            t("tab_alerts_detail.buscar_alerta")
                        ], className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='alert-selector-dropdown',
                            placeholder=t("tab_alerts_detail.buscar_por_id_unidad_sistema"),
                            clearable=True,
                            searchable=True,
                            className='alerts-detail-selector-dropdown'
                        )
                    ], md=12)
                ]),
                html.Div([
                    html.Small([
                        html.I(className="fas fa-info-circle me-1"),
                        t("tab_alerts_detail.tambien_puede_seleccionar_una_alerta_desde")
                    ], className="text-muted mt-2 d-block")
                ])
            ])
        ], className="alerts-detail-selector-card shadow-sm mb-4"),
        
        # Loading indicator
        dcc.Loading(
            id="loading-alert-detail",
            type="default",
            fullscreen=False,
            children=[
                # Alert Detail Content Container
                html.Div(id='alert-detail-content', children=[
                    # Placeholder when no alert selected
                    dbc.Alert([
                        html.I(className="fas fa-arrow-up me-2"),
                        t("tab_alerts_detail.por_favor_seleccione_una_alerta_para")
                    ], color="info", className="text-center")
                ])
            ]
        )
    ], className="p-4")
    
    logger.info("Alerts Detail Tab layout created successfully")
    return layout


def create_alert_detail_content(
    show_telemetry: bool,
    show_oil: bool,
    show_maintenance: bool
) -> html.Div:
    """
    Create conditional detail content layout based on alert trigger type.
    
    Layout Structure:
    1. Context Table (full width)
    2. TimeSeries | GPS Route (side by side)
    3. KPIs (full width: 3 KPIs side by side)
    4. Radar Charts (full width)
    5. Maintenance Context (full width)
    
    Args:
        show_telemetry: Whether to show telemetry evidence section
        show_oil: Whether to show oil evidence section
        show_maintenance: Whether to show maintenance evidence section
    
    Returns:
        Dash HTML Div with conditional sections
    """
    sections = []
    
    # 1. Alert Context Table (Always shown - full width)
    sections.append(
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-info-circle me-2"),
                            t("tab_alerts_detail.informacion_de_la_alerta")
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        html.Div(id='alert-specification-card')
                    ])
                ], className="shadow-sm mb-4")
            ], md=12)
        ])
    )
    
    # 2. Telemetry Evidence: Stacked layout (Signals → GPS → KPIs)
    if show_telemetry:
        # Section header for telemetry evidence
        sections.append(
            html.Div([
                html.H4([
                    html.I(className="fas fa-signal me-2"),
                    t("tab_alerts_detail.evidencia_de_telemetria")
                ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
                html.P(t("tab_alerts_detail.analisis_de_datos_de_sensores_y"), 
                       className="text-muted mb-3")
            ])
        )
        
        # Row 1: Sensor Trends (full width)
        sections.append(
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-chart-line me-2"),
                                t("tab_alerts_detail.tendencias_de_sensores")
                            ], className="mb-0")
                        ], className="bg-light"),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-sensor-trends",
                                type="circle",
                                children=[
                                    dcc.Graph(
                                        id='sensor-trends-chart',
                                        config={'displayModeBar': True}
                                    )
                                ]
                            )
                        ])
                    ], className="shadow-sm mb-4")
                ], md=12)
            ])
        )
        
        # Row 2: KPIs (left, 1 col x 4 rows) + GPS Map (right) - SAME HEIGHT
        sections.append(
            dbc.Row([
                # Left: KPIs (vertical layout, 1 column x 4 rows)
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-tachometer-alt me-2"),
                                t("tab_alerts_detail.indicadores_de_contexto")
                            ], className="mb-0")
                        ], className="bg-light"),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-context-kpis",
                                type="circle",
                                children=[html.Div(id='context-kpis-container')]
                            )
                        ], className="p-3")
                    ], className="shadow-sm mb-4 h-100")  # Added h-100 for full height
                ], md=4),
                
                # Right: GPS Map
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-map-marked-alt me-2"),
                                t("tab_alerts_detail.ubicacion_y_ruta_gps")
                            ], className="mb-0")
                        ], className="bg-light"),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-gps-map",
                                type="circle",
                                children=[
                                    dcc.Graph(
                                        id='gps-route-map',
                                        config={'displayModeBar': True},
                                        style={'height': '500px'}
                                    )
                                ]
                            )
                        ], className="p-2")  # Reduced padding for consistency
                    ], className="shadow-sm mb-4 h-100")  # Added h-100 for full height
                ], md=8)
            ], className="gx-3")  # Added horizontal spacing between columns
        )
    
    # 4. Oil Evidence: Radar Chart (conditional - full width)
    if show_oil:
        # Section header for oil evidence
        sections.append(
            html.Div([
                html.H4([
                    html.I(className="fas fa-oil-can me-2"),
                    t("tab_alerts_detail.evidencia_tribologica")
                ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
                html.P(t("tab_alerts_detail.analisis_de_aceite_y_desgaste_de"), 
                       className="text-muted mb-3")
            ])
        )
        
        sections.append(
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-flask me-2"),
                                t("tab_alerts_detail.niveles_de_elementos_y_estado")
                            ], className="mb-0")
                        ], className="bg-light"),
                        dbc.CardBody([
                            dbc.Row([
                                # Radar Chart
                                dbc.Col([
                                    dcc.Loading(
                                        id="loading-oil-radar",
                                        type="circle",
                                        children=[
                                            dcc.Graph(
                                                id='oil-radar-chart',
                                                config={'displayModeBar': False}
                                            )
                                        ]
                                    )
                                ], md=8),
                                
                                # Oil Report Status
                                dbc.Col([
                                    html.Div(id='oil-report-status-container')
                                ], md=4)
                            ])
                        ])
                    ], className="shadow-sm mb-4")
                ], md=12)
            ])
        )
    
    # 5. Maintenance Evidence (conditional - full width)
    if show_maintenance:
        # Section header for maintenance evidence
        sections.append(
            html.Div([
                html.H4([
                    html.I(className="fas fa-tools me-2"),
                    t("tab_alerts_detail.historial_de_mantenimiento")
                ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
                html.P(t("tab_alerts_detail.actividades_de_mantenimiento_relacionadas"), 
                       className="text-muted mb-3")
            ])
        )
        
        sections.append(
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-wrench me-2"),
                                t("tab_alerts_detail.intervenciones_recientes")
                            ], className="mb-0")
                        ], className="bg-light"),
                        dbc.CardBody([
                            html.Div(id='maintenance-display-container')
                        ])
                    ], className="shadow-sm mb-4")
                ], md=12)
            ])
        )
    
    return html.Div(sections)


def create_oil_status_display(
    report_status: str,
    breached_essays: list,
    ai_recommendation: str
) -> html.Div:
    """
    Create oil report status display.
    
    Args:
        report_status: Report status (Normal/Marginal/Condenatorio/Critico)
        breached_essays: List of essays that breached limits
        ai_recommendation: AI recommendation text
    
    Returns:
        HTML Div with oil status information
    """
    # Determine status color
    status_colors = {
        'Normal': 'success',
        'Marginal': 'warning',
        'Condenatorio': 'danger',
        'Critico': 'danger'
    }
    status_color = status_colors.get(report_status, 'secondary')
    
    return html.Div([
        # Status Badge
        dbc.Badge(
            report_status,
            color=status_color,
            className="mb-3",
            style={'fontSize': '1.2rem'}
        ),
        
        # Breached Essays
        html.Div([
            html.H6(t("tab_alerts_detail.ensayos_en_alerta"), className="text-muted mb-2"),
            html.Ul([
                html.Li(str(essay), className="text-danger")
                for essay in breached_essays
            ]) if (breached_essays and len(breached_essays) > 0) else html.P(t("tab_alerts_detail.ninguno"), className="text-success")
        ], className="mb-3"),
        
        # AI Recommendation
        html.Div([
            html.H6([
                html.I(className="fas fa-robot me-2"),
                t("tab_alerts_detail.recomendacion_ai")
            ], className="text-primary mb-2"),
            html.P(
                ai_recommendation if ai_recommendation else t("tab_alerts_detail.no_disponible"),
                className="text-muted",
                style={'fontSize': '0.9rem', 'whiteSpace': 'pre-wrap'}
            )
        ])
    ])
