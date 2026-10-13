"""
Component Hours (Horómetro) tab for Multi-Technical-Alerts dashboard.

Shows component operating hours evolution for each unit and component.
Available for CDA and ENEX clients.
"""

from src.i18n import t
from dash import dcc, html
import dash_bootstrap_components as dbc


def create_component_hours_tab() -> dbc.Container:
    """
    Create Tab: Component Hours (Horómetro).
    
    Layout includes:
    1. Unit selector and component selector
    2. Summary table with latest hours per component
    3. Time series chart of component hours evolution
    
    Returns:
        Bootstrap container with tab layout
    """
    return dbc.Container([
        html.H3([
            html.I(className="fas fa-clock me-2"),
            t("tab_component_hours.horometro_de_componentes")
        ], className="mt-4 mb-3"),
        html.P(
            t("tab_component_hours.seguimiento_de_horas_de_operacion_de"),
            className="text-muted"
        ),
        html.Hr(),
        
        # ========================================
        # SECTION 1: Summary Table - Latest hours per component
        # ========================================
        html.H4(t("tab_component_hours.resumen_de_horometro_por_equipo"), className="mt-4 mb-3"),
        
        # Unit selector
        dbc.Row([
            dbc.Col([
                html.Label(t("tab_component_hours.seleccionar_equipo"), className="fw-bold"),
                dcc.Dropdown(
                    id='comp-hours-unit-selector',
                    placeholder=t("tab_component_hours.seleccionar_equipo_2"),
                    className="mb-3"
                )
            ], width=4),
        ], className="mb-3"),
        
        # Summary table
        dbc.Card([
            dbc.CardHeader(t("tab_component_hours.ultimo_horometro_por_componente"), className="fw-bold"),
            dbc.CardBody(
                html.Div(id='comp-hours-summary-table')
            )
        ], className="mb-4"),
        
        # ========================================
        # SECTION 2: Time Series Chart
        # ========================================
        html.H4(t("tab_component_hours.evolucion_de_horas_de_componentes"), className="mt-4 mb-3"),
        
        # Component multi-selector
        dbc.Row([
            dbc.Col([
                html.Label(t("tab_component_hours.seleccionar_componentes"), className="fw-bold"),
                dcc.Dropdown(
                    id='comp-hours-component-selector',
                    placeholder=t("tab_component_hours.seleccionar_componentes_2"),
                    multi=True,
                    className="mb-3"
                )
            ], width=8),
        ], className="mb-3"),
        
        # Time series chart
        dbc.Card([
            dbc.CardBody([
                dcc.Graph(id='comp-hours-time-series')
            ])
        ], className="mb-4"),
        
    ], fluid=True)
