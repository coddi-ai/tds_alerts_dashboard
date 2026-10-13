"""
Menace Control Tab Layout.

This tab provides a critical system monitoring view with:
1. General Equipment Status Table: Shows total alerts/events per equipment and system over last X days
2. Critical Systems Table: Highlights the most critical equipment-system combinations ranked by alert count
"""

from src.i18n import t
from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create layout for Menace Control tab.
    
    Returns:
        Dash HTML Div with complete menace control layout
    """
    logger.info("Creating Menace Control Tab layout")
    
    layout = html.Div([
        # Header Section
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-exclamation-triangle me-3"),
                    t("tab_menace_control.control_de_amenazas")
                ], className="text-danger mb-1"),
                html.P(
                    t("tab_menace_control.monitoreo_de_criticidad_de_equipos_y"),
                    className="text-muted"
                )
            ])
        ], className="mb-4"),
        
        # Time Range Selector
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.Label([
                                html.I(className="fas fa-calendar-alt me-2"),
                                t("tab_menace_control.rango_de_analisis")
                            ], className="fw-bold me-3"),
                            dcc.Dropdown(
                                id='menace-days-selector',
                                options=[
                                    {'label': t("tab_menace_control.ultimos_30_dias"), 'value': 30},
                                    {'label': t("tab_menace_control.ultimos_60_dias"), 'value': 60},
                                    {'label': t("tab_menace_control.ultimos_90_dias"), 'value': 90},
                                    {'label': t("tab_menace_control.ultimos_180_dias"), 'value': 180},
                                    {'label': t("tab_menace_control.ultimo_ano"), 'value': 365}
                                ],
                                value=90,
                                clearable=False,
                                style={'width': '250px', 'display': 'inline-block'}
                            )
                        ], className="d-flex align-items-center")
                    ])
                ], className="shadow-sm")
            ], md=12)
        ], className="mb-4"),
        
        # Summary Statistics Cards
        html.Div(id='menace-summary-cards', className="mb-4"),
        
        # Section 1: General Equipment Status Table
        html.Div([
            html.H4([
                html.I(className="fas fa-table me-2"),
                t("tab_menace_control.estado_general_de_equipos")
            ], className="text-primary mb-3")
        ]),
        
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-truck me-2"),
                            t("tab_menace_control.resumen_de_alertas_por_equipo_y")
                        ], className="mb-0")
                    ], className="bg-light"),
                    dbc.CardBody([
                        html.P(
                            t("tab_menace_control.tabla_que_muestra_el_numero_de"),
                            className="text-muted small mb-3"
                        ),
                        dcc.Loading(
                            id="loading-equipment-status",
                            type="circle",
                            children=[
                                html.Div(id='menace-equipment-status-table')
                            ]
                        )
                    ])
                ], className="shadow-sm mb-4")
            ], md=12)
        ]),
        
        # Section 2: Critical Systems Table
        html.Div([
            html.H4([
                html.I(className="fas fa-fire me-2"),
                t("tab_menace_control.sistemas_mas_criticos")
            ], className="text-danger mb-3 mt-4")
        ]),
        
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-exclamation-circle me-2"),
                            t("tab_menace_control.ranking_de_criticidad_por_equipo_sistema")
                        ], className="mb-0")
                    ], className="bg-light"),
                    dbc.CardBody([
                        html.P(
                            t("tab_menace_control.lista_ordenada_de_los_sistemas_mas"),
                            className="text-muted small mb-3"
                        ),
                        dcc.Loading(
                            id="loading-critical-systems",
                            type="circle",
                            children=[
                                html.Div(id='menace-critical-systems-table')
                            ]
                        )
                    ])
                ], className="shadow-sm mb-4")
            ], md=12)
        ]),
        
    ], className="container-fluid p-4")
    
    logger.info("Menace Control Tab layout created successfully")
    return layout
