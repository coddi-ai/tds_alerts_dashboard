"""Telemetry fleet overview layout."""

from src.i18n import t
from dash import html, dcc
import dash_bootstrap_components as dbc


def create_telemetry_fleet_layout() -> html.Div:
    """Create the compact fleet matrix used in weekly maintenance meetings."""
    return html.Div([
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label(t("tab_telemetry_fleet.modelo_de_equipo"), className="small fw-bold"),
                        dcc.Dropdown(
                            id="telemetry-fleet-model-filter",
                            placeholder=t("tab_telemetry_fleet.todos_los_modelos"),
                            clearable=True,
                            options=[],
                        ),
                    ], md=6),
                    dbc.Col([
                        html.Label(t("tab_telemetry_fleet.estado"), className="small fw-bold"),
                        dcc.Dropdown(
                            id="telemetry-fleet-status-filter",
                            placeholder=t("tab_telemetry_fleet.todos_los_estados"),
                            multi=True,
                            options=[
                                {"label": t("tab_machines.normal"), "value": "Normal"},
                                {"label": t("tab_machines.alerta"), "value": "Alerta"},
                                {"label": t("tab_machines.anormal"), "value": "Anormal"},
                                {"label": t("tab_telemetry_fleet.sin_evidencia_suficiente"), "value": "InsufficientData"},
                            ],
                        ),
                    ], md=6),
                ], className="g-3"),
            ])
        ], className="shadow-sm mb-3"),
        dbc.Card([
            dbc.CardHeader([
                dbc.Row([
                    dbc.Col([
                        html.H5([
                            html.I(className="fas fa-table me-2"),
                            t("tab_telemetry_fleet.estado_por_sistema_y_unidad"),
                        ], className="mb-0"),
                        html.Small(
                            t("tab_telemetry_fleet.las_filas_se_ordenan_por_severidad"),
                            className="text-muted",
                        ),
                    ], md=7),
                    dbc.Col([
                        html.Label(t("tab_telemetry_fleet.sistemas_visibles"), className="small fw-bold mb-1"),
                        dcc.Dropdown(
                            id="telemetry-fleet-system-filter",
                            placeholder=t("tab_telemetry_fleet.todos_los_sistemas"),
                            multi=True,
                            options=[],
                            value=[],
                            closeOnSelect=False,
                        ),
                    ], md=5),
                ], className="align-items-center g-2"),
            ], className="bg-light"),
            dbc.CardBody([
                dcc.Loading(
                    html.Div(id="telemetry-fleet-table-container"),
                    type="circle",
                )
            ], className="p-2"),
        ], className="shadow-sm mb-4"),
    ])
