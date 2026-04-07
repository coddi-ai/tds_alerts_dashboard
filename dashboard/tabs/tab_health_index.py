"""
Health Index Tab - Visualización del estado de salud de equipos.

Proporciona visualización completa del Health Index por sistema:
- Dirección, Frenos, Motor, Tren de Fuerza
- Métricas generales, gráficos temporales, heatmaps, alertas
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create Health Index tab layout with internal tabs by system.
    
    Returns:
        Dash HTML Div with tabbed interface
    """
    logger.info("Creating Health Index Tab layout")

    layout = html.Div([
        # Header
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-heartbeat me-3"),
                    "Health Index - Estado de Salud de Equipos"
                ], className="text-primary mb-1"),
                html.P(
                    "Monitoreo del índice de salud por sistema y unidad",
                    className="text-muted"
                )
            ])
        ], className="mb-4"),

        # Client restriction notice
        html.Div(
            id='health-index-client-notice',
            children=[
                dbc.Alert([
                    html.I(className="fas fa-info-circle me-2"),
                    "Este módulo está disponible únicamente para el cliente CDA"
                ], color="info", className="mb-4")
            ]
        ),

        # Store for sharing data between callbacks
        dcc.Store(id='health-index-data-store'),
        dcc.Store(id='health-index-filters-store'),

        # === FILTROS GLOBALES ===
        dbc.Card([
            dbc.CardBody([
                html.H5([
                    html.I(className="fas fa-filter me-2"),
                    "Filtros Globales"
                ], className="mb-3"),
                
                dbc.Row([
                    # Rango de fechas
                    dbc.Col([
                        html.Label("Rango de Fechas:", className="fw-bold mb-2"),
                        dcc.DatePickerRange(
                            id='health-index-date-range',
                            display_format='DD/MM/YYYY',
                            start_date_placeholder_text='Fecha Inicio',
                            end_date_placeholder_text='Fecha Fin',
                            className='w-100'
                        )
                    ], md=3),
                    
                    # Filtro por Modelo
                    dbc.Col([
                        html.Label("Modelo:", className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='health-index-model-filter',
                            options=[
                                {'label': 'Todos', 'value': 'all'},
                                {'label': 'CAT 789C', 'value': 'CAT 789C'},
                                {'label': 'CAT 789D', 'value': 'CAT 789D'}
                            ],
                            value='all',
                            clearable=False,
                            className='dash-bootstrap'
                        )
                    ], md=2),
                    
                    # Filtro por Unidad
                    dbc.Col([
                        html.Label("Unidad:", className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='health-index-unit-filter',
                            options=[{'label': 'Todas', 'value': 'all'}],
                            value='all',
                            multi=True,
                            className='dash-bootstrap'
                        )
                    ], md=3),
                    
                    # Filtro por Rango de HI
                    dbc.Col([
                        html.Label("Rango Health Index:", className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='health-index-range-filter',
                            options=[
                                {'label': 'Todos', 'value': 'all'},
                                {'label': '🔴 Crítico (< 0.5)', 'value': 'critical'},
                                {'label': '🟡 Precaución (0.5-0.8)', 'value': 'warning'},
                                {'label': '🟢 Saludable (≥ 0.8)', 'value': 'healthy'}
                            ],
                            value='all',
                            clearable=False,
                            className='dash-bootstrap'
                        )
                    ], md=2),
                    
                    # Botón de actualizar
                    dbc.Col([
                        html.Label("\u00A0", className="fw-bold mb-2 d-block"),
                        dbc.Button(
                            [html.I(className="fas fa-sync-alt me-2"), "Actualizar"],
                            id='health-index-refresh-button',
                            color='primary',
                            className='w-100'
                        )
                    ], md=2)
                ], className="g-3")
            ])
        ], className="mb-4"),

        # === ALERTAS CRÍTICAS ===
        html.Div(id='health-index-critical-alerts'),

        # === MÉTRICAS GENERALES ===
        html.Div(id='health-index-kpi-cards'),

        # === TABS POR SISTEMA ===
        dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-chart-line me-2"),
                    "Análisis por Sistema"
                ], className="mb-0")
            ]),
            dbc.CardBody([
                dcc.Tabs(
                    id='health-index-system-tabs',
                    value='all-systems',
                    children=[
                        dcc.Tab(
                            label='Vista General',
                            value='all-systems',
                            className='custom-tab',
                            selected_className='custom-tab--selected'
                        ),
                        dcc.Tab(
                            label='Dirección',
                            value='Direccion',
                            className='custom-tab',
                            selected_className='custom-tab--selected'
                        ),
                        dcc.Tab(
                            label='Frenos',
                            value='Frenos',
                            className='custom-tab',
                            selected_className='custom-tab--selected'
                        ),
                        dcc.Tab(
                            label='Motor',
                            value='Motor',
                            className='custom-tab',
                            selected_className='custom-tab--selected'
                        ),
                        dcc.Tab(
                            label='Tren de Fuerza',
                            value='Tren de fuerza',
                            className='custom-tab',
                            selected_className='custom-tab--selected'
                        )
                    ]
                ),
                
                # Contenido dinámico según el tab seleccionado
                html.Div(id='health-index-tab-content', className='mt-4')
            ])
        ], className="mb-4"),

        # === PANEL LATERAL DE DETALLES (modal) ===
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle(id='health-index-modal-title')),
            dbc.ModalBody(id='health-index-modal-body'),
            dbc.ModalFooter(
                dbc.Button("Cerrar", id='health-index-modal-close', className="ms-auto")
            )
        ], id='health-index-detail-modal', size='xl', is_open=False),

        # Loading overlay
        dcc.Loading(
            id='health-index-loading',
            type='default',
            children=html.Div(id='health-index-loading-output')
        )
    ])

    return layout


def create_general_view_content() -> html.Div:
    """
    Create content for general overview tab.
    
    Returns:
        Dash HTML Div with general visualizations
    """
    return html.Div([
        # Tabla principal y gráfico de distribución (similar a telemetría)
        dbc.Row([
            # Tabla de Estado del Health Index
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-table me-2"),
                            "Estado de Salud por Unidad y Sistema"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            html.Div(id='health-index-detail-table'),
                            type='circle'
                        )
                    ])
                ], className="shadow-sm")
            ], lg=8),
            
            # Gráfico de barras - HI actual por unidad
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-chart-pie me-2"),
                            "Distribución por Estado"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Loading(
                            dcc.Graph(
                                id='health-index-status-pie',
                                config={'displayModeBar': False}
                            ),
                            type='circle'
                        )
                    ])
                ], className="shadow-sm")
            ], lg=4)
        ], className="mb-4"),

        # Gráfico de líneas temporal - HI por unidad
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H6([
                            html.I(className="fas fa-chart-line me-2"),
                            "Evolución Temporal del Health Index por Unidad"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Graph(id='health-index-timeline-chart', config={'displayModeBar': True})
                    ])
                ], className="shadow-sm")
            ], width=12)
        ], className="mb-4"),

        # Heatmap de HI por unidad y sistema
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H6([
                            html.I(className="fas fa-th me-2"),
                            "Heatmap: Health Index por Unidad y Sistema"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Graph(id='health-index-heatmap', config={'displayModeBar': True})
                    ])
                ], className="shadow-sm")
            ], md=6),
            
            # Gráfico de barras - HI actual por unidad
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H6([
                            html.I(className="fas fa-bar-chart me-2"),
                            "Health Index Actual por Unidad"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Graph(id='health-index-bar-chart', config={'displayModeBar': True})
                    ])
                ], className="shadow-sm")
            ], md=6)
        ], className="mb-4"),

        # Botón de descarga
        dbc.Row([
            dbc.Col([
                dbc.Button(
                    [html.I(className="fas fa-download me-2"), "Descargar CSV"],
                    id='health-index-download-button',
                    color='success',
                    size='sm',
                    className='mb-3'
                ),
                dcc.Download(id='health-index-download-data')
            ])
        ])
    ])


def create_system_view_content(system_name: str) -> html.Div:
    """
    Create content for specific system tab.
    
    Args:
        system_name: Name of the system (Direccion, Frenos, Motor, Tren de fuerza)
    
    Returns:
        Dash HTML Div with system-specific visualizations
    """
    return html.Div([
        # KPIs específicos del sistema
        dbc.Row([
            dbc.Col([
                html.Div(id=f'health-index-{system_name}-kpis')
            ])
        ], className="mb-4"),

        # Gráficos específicos del sistema
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H6([
                            html.I(className="fas fa-chart-area me-2"),
                            f"Evolución Temporal - {system_name}"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Graph(id=f'health-index-{system_name}-timeline')
                    ])
                ])
            ], width=12)
        ], className="mb-4"),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H6([
                            html.I(className="fas fa-chart-bar me-2"),
                            f"Distribución por Unidad - {system_name}"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Graph(id=f'health-index-{system_name}-distribution')
                    ])
                ])
            ], md=6),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H6([
                            html.I(className="fas fa-chart-pie me-2"),
                            f"Estado del Sistema - {system_name}"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        dcc.Graph(id=f'health-index-{system_name}-status')
                    ])
                ])
            ], md=6)
        ], className="mb-4"),

        # Tabla de unidades críticas para este sistema
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H6([
                            html.I(className="fas fa-exclamation-triangle me-2"),
                            f"Unidades con Atención Prioritaria - {system_name}"
                        ], className="mb-0")
                    ]),
                    dbc.CardBody([
                        html.Div(id=f'health-index-{system_name}-critical-table')
                    ])
                ])
            ], width=12)
        ])
    ])
