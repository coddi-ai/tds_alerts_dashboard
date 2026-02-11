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
        # Filters Section
        dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-filter me-2"),
                    "Filtros"
                ], className="mb-0")
            ]),
            dbc.CardBody([
                dbc.Row([
                    # Unit Filter
                    dbc.Col([
                        html.Label("Unidad:", className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='detail-filter-unit',
                            placeholder="Seleccionar unidad...",
                            clearable=True,
                            searchable=True,
                            multi=True
                        )
                    ], md=3),
                    
                    # System Filter
                    dbc.Col([
                        html.Label("Sistema:", className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='detail-filter-sistema',
                            placeholder="Seleccionar sistema...",
                            clearable=True,
                            multi=True
                        )
                    ], md=3),
                    
                    # Has Telemetry Filter
                    dbc.Col([
                        html.Label("Con Telemetría:", className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='detail-filter-telemetry',
                            options=[
                                {'label': 'Sí', 'value': 'yes'},
                                {'label': 'No', 'value': 'no'}
                            ],
                            placeholder="Todos",
                            clearable=True
                        )
                    ], md=3),
                    
                    # Has Tribology Filter
                    dbc.Col([
                        html.Label("Con Tribología:", className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='detail-filter-tribology',
                            options=[
                                {'label': 'Sí', 'value': 'yes'},
                                {'label': 'No', 'value': 'no'}
                            ],
                            placeholder="Todos",
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
                    html.I(className="fas fa-search me-2"),
                    "Seleccionar Alerta"
                ], className="mb-0")
            ]),
            dbc.CardBody([
                html.Label("Alerta:", className="fw-bold mb-2"),
                dcc.Dropdown(
                    id='alert-selector-dropdown',
                    placeholder="Seleccione una alerta...",
                    clearable=True,
                    searchable=True
                ),
                html.Small(
                    "También puede seleccionar una alerta desde la Vista General",
                    className="text-muted mt-2 d-block"
                )
            ])
        ], className="shadow-sm mb-4"),
        
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
                        "Por favor, seleccione una alerta para ver los detalles"
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
                            "Información de la Alerta"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        html.Div(id='alert-specification-card')
                    ])
                ], className="shadow-sm mb-4")
            ], md=12)
        ])
    )
    
    # 2. Telemetry Evidence: TimeSeries | GPS Route (conditional)
    if show_telemetry:
        sections.append(
            dbc.Row([
                # Sensor Trends (left side - 6 columns)
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-chart-line me-2"),
                                "Tendencias de Sensores"
                            ], className="mb-0")
                        ]),
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
                ], md=6),
                
                # GPS Map (right side - 6 columns)
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-map-marked-alt me-2"),
                                "Ruta GPS"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-gps-map",
                                type="circle",
                                children=[
                                    dcc.Graph(
                                        id='gps-route-map',
                                        config={'displayModeBar': True},
                                        style={'height': '600px'}
                                    )
                                ]
                            )
                        ])
                    ], className="shadow-sm mb-4")
                ], md=6)
            ])
        )
        
        # 3. KPIs Row (full width: 3 KPIs side by side)
        sections.append(
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-tachometer-alt me-2"),
                                "Indicadores de Contexto"
                            ], className="mb-0")
                        ]),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-context-kpis",
                                type="circle",
                                children=[
                                    dbc.Row(id='context-kpis-container', className="g-3")
                                ]
                            )
                        ])
                    ], className="shadow-sm mb-4")
                ], md=12)
            ])
        )
    
    # 4. Oil Evidence: Radar Chart (conditional - full width)
    if show_oil:
        sections.append(
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-flask me-2"),
                                "Evidencia de Tribología - Análisis de Aceite"
                            ], className="mb-0")
                        ]),
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
        sections.append(
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-tools me-2"),
                                "Evidencia de Mantenimiento"
                            ], className="mb-0")
                        ]),
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
            html.H6("Ensayos en Alerta:", className="text-muted mb-2"),
            html.Ul([
                html.Li(str(essay), className="text-danger")
                for essay in breached_essays
            ]) if (breached_essays and len(breached_essays) > 0) else html.P("Ninguno", className="text-success")
        ], className="mb-3"),
        
        # AI Recommendation
        html.Div([
            html.H6([
                html.I(className="fas fa-robot me-2"),
                "Recomendación AI:"
            ], className="text-primary mb-2"),
            html.P(
                ai_recommendation if ai_recommendation else "No disponible",
                className="text-muted",
                style={'fontSize': '0.9rem', 'whiteSpace': 'pre-wrap'}
            )
        ])
    ])
