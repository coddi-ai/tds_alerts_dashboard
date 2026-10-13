"""
Stewart Limits tab for Multi-Technical-Alerts dashboard.

Displays Stewart Limits thresholds with filtering capabilities.
"""

from src.i18n import t
from dash import dcc, html
import dash_bootstrap_components as dbc
from dashboard.components.filters import create_machine_selector, create_component_selector
from dashboard.components.tables import create_limits_table


def create_limits_tab() -> dbc.Container:
    """
    Create Tab 1: Stewart Limits visualization.
    
    Features:
    - Machine/Component filters
    - Limits table with color-coded thresholds
    - Export functionality
    
    Returns:
        Bootstrap container with tab layout
    """
    return dbc.Container([
        html.H3(t("tab_limits.stewart_limits"), className="mt-4 mb-3"),
        html.Hr(),
        
        # Filters
        dbc.Row([
            dbc.Col([
                html.Label(t("tab_limits.select_machine"), className="fw-bold"),
                dcc.Dropdown(
                    id='machine-selector',
                    placeholder=t("tab_limits.select_a_machine"),
                    className="mb-3"
                )
            ], width=4),
            dbc.Col([
                html.Label(t("tab_limits.select_component"), className="fw-bold"),
                dcc.Dropdown(
                    id='component-selector',
                    placeholder=t("tab_limits.select_a_component"),
                    className="mb-3"
                )
            ], width=4),
            dbc.Col([
                html.Label(t("tab_limits.search"), className="fw-bold"),
                dcc.Input(
                    id='limits-search',
                    type='text',
                    placeholder=t("tab_limits.search_essays"),
                    className="form-control mb-3"
                )
            ], width=4)
        ], className="mb-4"),
        
        # Info card
        dbc.Alert([
            html.H5(t("tab_limits.about_stewart_limits"), className="alert-heading"),
            html.P([
                t("tab_limits.stewart_limits_define_the_statistical_thre"),
                html.Br(),
                html.Strong(t("tab_limits.lic_inferior_condenatorio_2")), t("tab_limits.lower_critical_threshold_only_present_for"),
                html.Br(),
                html.Strong(t("tab_limits.lim_inferior_marginal_5")), t("tab_limits.lower_warning_threshold_only_present_for"),
                html.Br(),
                html.Strong(t("tab_limits.lsm_superior_marginal_95")), t("tab_limits.upper_warning_threshold"),
                html.Br(),
                html.Strong(t("tab_limits.lsc_superior_condenatorio_98")), t("tab_limits.upper_critical_threshold")
            ])
        ], color="info", className="mb-4"),
        
        # Table container
        dbc.Card([
            dbc.CardHeader(t("tab_limits.limits_table"), className="fw-bold"),
            dbc.CardBody(
                html.Div(id='limits-table-container')
            )
        ])
        
    ], fluid=True)
