"""
Reusable filter components for Multi-Technical-Alerts dashboard.
"""

from src.i18n import t
from dash import dcc, html
import dash_bootstrap_components as dbc


def create_machine_selector(machines: list[str] = None) -> dbc.Col:
    """
    Create machine selector dropdown.
    
    Args:
        machines: List of available machines
    
    Returns:
        Bootstrap column with machine dropdown
    """
    return dbc.Col([
        html.Label(t("tab_limits.select_machine"), className="fw-bold"),
        dcc.Dropdown(
            id='machine-selector',
            options=[{'label': m, 'value': m} for m in (machines or [])],
            value=None,
            placeholder=t("tab_limits.select_a_machine"),
            className="mb-3"
        )
    ], width=4)


def create_component_selector(components: list[str] = None) -> dbc.Col:
    """
    Create component selector dropdown.
    
    Args:
        components: List of available components
    
    Returns:
        Bootstrap column with component dropdown
    """
    return dbc.Col([
        html.Label(t("tab_limits.select_component"), className="fw-bold"),
        dcc.Dropdown(
            id='component-selector',
            options=[{'label': c, 'value': c} for c in (components or [])],
            value=None,
            placeholder=t("tab_limits.select_a_component"),
            className="mb-3"
        )
    ], width=4)


def create_date_range_picker() -> dbc.Col:
    """
    Create date range picker.
    
    Returns:
        Bootstrap column with date range picker
    """
    return dbc.Col([
        html.Label(t("filters.date_range"), className="fw-bold"),
        dcc.DatePickerRange(
            id='date-range-picker',
            display_format='YYYY-MM-DD',
            className="mb-3"
        )
    ], width=6)


def create_status_filter() -> dbc.Col:
    """
    Create status filter checkboxes.
    
    Returns:
        Bootstrap column with status checkboxes
    """
    return dbc.Col([
        html.Label(t("filters.filter_by_status"), className="fw-bold"),
        dcc.Checklist(
            id='status-filter',
            options=[
                {'label': t("filters.normal"), 'value': 'Normal'},
                {'label': t("tab_machines.alerta_2"), 'value': 'Alerta'},
                {'label': t("tab_machines.anormal_2"), 'value': 'Anormal'}
            ],
            value=['Normal', 'Alerta', 'Anormal'],
            inline=True,
            className="mb-3"
        )
    ], width=6)
