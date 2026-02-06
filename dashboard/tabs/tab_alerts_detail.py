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
        # Header
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-search me-3"),
                    "Alertas - Vista Detallada"
                ], className="text-primary mb-1"),
                html.P(
                    "Análisis profundo de alertas individuales con evidencia multi-fuente",
                    className="text-muted"
                )
            ])
        ], className="mb-4"),
        
        # Client restriction notice
        html.Div(
            id='alerts-detail-client-notice',
            children=[
                dbc.Alert([
                    html.I(className="fas fa-info-circle me-2"),
                    "Este módulo está disponible únicamente para el cliente CDA"
                ], color="info", className="mb-4")
            ]
        ),
        
        # Alert Selector
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-filter me-2"),
                            "Seleccionar Alerta"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        html.P("Seleccione una alerta de la lista para ver su análisis detallado:", className="mb-3"),
                        dcc.Dropdown(
                            id='alert-selector-dropdown',
                            placeholder="Seleccione una alerta...",
                            clearable=True,
                            searchable=True,
                            className="mb-2"
                        ),
                        html.Small(
                            "También puede seleccionar una alerta desde la Vista General",
                            className="text-muted"
                        )
                    ])
                ], className="shadow-sm mb-4")
            ], md=12)
        ]),
        
        # Alert Detail Content Container
        html.Div(id='alert-detail-content', children=[
            # Placeholder when no alert selected
            dbc.Alert([
                html.I(className="fas fa-arrow-up me-2"),
                "Por favor, seleccione una alerta para ver los detalles"
            ], color="info", className="text-center")
        ])
    ], className="container-fluid p-4")
    
    logger.info("Alerts Detail Tab layout created successfully")
    return layout


def create_alert_detail_content(
    show_telemetry: bool,
    show_oil: bool,
    show_maintenance: bool
) -> html.Div:
    """
    Create conditional detail content layout based on alert trigger type.
    
    Args:
        show_telemetry: Whether to show telemetry evidence section
        show_oil: Whether to show oil evidence section
        show_maintenance: Whether to show maintenance evidence section
    
    Returns:
        Dash HTML Div with conditional sections
    """
    sections = []
    
    # Always show alert specification
    sections.append(
        dbc.Row([
            dbc.Col([
                html.Div(id='alert-specification-card')
            ], md=12)
        ], className="mb-4")
    )
    
    # Telemetry Evidence (conditional)
    if show_telemetry:
        sections.append(
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.H4([
                            html.I(className="fas fa-satellite-dish me-2"),
                            "Evidencia de Telemetría"
                        ], className="text-info mb-3")
                    ])
                ]),
                
                # Sensor Trends
                dbc.Row([
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
                    ], md=12)
                ]),
                
                # GPS Map and Context KPIs
                dbc.Row([
                    # GPS Map
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
                                            config={'displayModeBar': True}
                                        )
                                    ]
                                )
                            ])
                        ], className="shadow-sm mb-4")
                    ], md=8),
                    
                    # Context KPIs
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.H5([
                                    html.I(className="fas fa-info-circle me-2"),
                                    "Contexto"
                                ], className="mb-0")
                            ]),
                            dbc.CardBody([
                                html.Div(id='context-kpis-container')
                            ])
                        ], className="shadow-sm mb-4")
                    ], md=4)
                ])
            ], className="mb-5")
        )
    
    # Oil Evidence (conditional)
    if show_oil:
        sections.append(
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.H4([
                            html.I(className="fas fa-flask me-2"),
                            "Evidencia de Tribología"
                        ], className="text-warning mb-3")
                    ])
                ]),
                
                dbc.Row([
                    # Radar Chart
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.H5([
                                    html.I(className="fas fa-vial me-2"),
                                    "Análisis de Aceite"
                                ], className="mb-0")
                            ]),
                            dbc.CardBody([
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
                            ])
                        ], className="shadow-sm mb-4")
                    ], md=8),
                    
                    # Oil Report Status
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.H5([
                                    html.I(className="fas fa-clipboard-check me-2"),
                                    "Estado del Reporte"
                                ], className="mb-0")
                            ]),
                            dbc.CardBody([
                                html.Div(id='oil-report-status-container')
                            ])
                        ], className="shadow-sm mb-4")
                    ], md=4)
                ])
            ], className="mb-5")
        )
    
    # Maintenance Evidence (always if available)
    if show_maintenance:
        sections.append(
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.H4([
                            html.I(className="fas fa-tools me-2"),
                            "Evidencia de Mantenimiento"
                        ], className="text-secondary mb-3")
                    ])
                ]),
                
                dbc.Row([
                    dbc.Col([
                        html.Div(id='maintenance-display-container')
                    ], md=12)
                ])
            ], className="mb-4")
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
                html.Li(essay, className="text-danger")
                for essay in breached_essays
            ]) if breached_essays else html.P("Ninguno", className="text-success")
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
