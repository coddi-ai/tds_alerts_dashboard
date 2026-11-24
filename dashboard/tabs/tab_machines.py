"""
Machines Overview tab for Multi-Technical-Alerts dashboard (Monitor de Aceite > Visión de Flota).

Updated July 2026 v3:
- Filter order: Site → Fleet → Status (dynamic dependencies)
- Heatmap depends on fleet selection (empty if multiple fleets, no selection)
- Default components: all with ≥1 sample for selected fleet
- Machine status visually prominent

Updated November 2026 (Monitor de Aceite UI/UX alignment, ui_notes_improved.md):
- the matrix is a table of real buttons (dashboard/components/oil_fleet_matrix.py); Estado Máquina sits
  right after Unidad and the component columns are ordered by coverage;
- every filter has its <label for>; status colors come from shared/severity.py.
"""

from src.i18n import t
from dash import dcc, html
import dash_bootstrap_components as dbc

from dashboard.components.oil_table import stores
from dashboard.components.oil_ui import page_header
from shared.severity import STATUS_TIERS, STATUS_TIER_BY_ESTADO


def _kpi_count(estado: str, value_id: str, label: str):
    """"● 12 Normal": the shape and the word carry the state, the tier color only reinforces it."""
    tier = STATUS_TIERS[STATUS_TIER_BY_ESTADO[estado]]
    # Normal's tier is white (quiet); its dot uses the badge green so it is visible on the page.
    color = tier["badge_text"] if estado == "Normal" else tier["bg"]
    return dbc.Col(html.Div([
        html.Span("● ", style={'color': color}, **{"aria-hidden": "true"}),
        html.Span(id=value_id, children="0", className="fw-bold"),
        html.Span(label, className="text-muted small ms-1"),
    ], className="text-center"), width=3)


def create_machines_tab() -> dbc.Container:
    """Create Tab: Machines Overview (Oil)."""
    return dbc.Container([
        page_header(t("tab_machines.resumen_de_maquinas")),
        html.Hr(),

        # ========================================
        # SECTION 0: Fleet Filters (Site → Fleet → Status)
        # ========================================
        dbc.Row([
            dbc.Col([
                html.Label(t("tab_machines.sitio_area"), htmlFor='fleet-site-filter', className="fw-bold small"),
                dcc.Dropdown(
                    id='fleet-site-filter',
                    placeholder=t("tab_machines.todos_los_sitios"),
                    multi=False,
                    className="mb-2"
                )
            ], md=4),
            dbc.Col([
                html.Label(t("tab_machines.flota_tipo_de_equipo"), htmlFor='fleet-machine-type-filter', className="fw-bold small"),
                dcc.Dropdown(
                    id='fleet-machine-type-filter',
                    placeholder=t("tab_machines.seleccionar_flota"),
                    multi=False,
                    className="mb-2"
                )
            ], md=4),
            dbc.Col([
                html.Label(t("tab_machines.estado"), htmlFor='fleet-status-filter', className="fw-bold small"),
                dcc.Dropdown(
                    id='fleet-status-filter',
                    placeholder=t("tab_machines.todos_los_estados"),
                    options=[
                        {'label': t("tab_machines.normal"), 'value': 'Normal'},
                        {'label': t("tab_machines.alerta"), 'value': 'Alerta'},
                        {'label': t("tab_machines.anormal"), 'value': 'Anormal'},
                    ],
                    multi=True,
                    className="mb-2"
                )
            ], md=4),
        ], className="mb-3 p-3 bg-light rounded"),

        # ========================================
        # SECTION 1: KPIs (compact, filter-reactive)
        # ========================================
        dbc.Row([
            dbc.Col(html.Div([
                html.Span(t("tab_machines.total"), className="text-muted small"),
                html.Span(id='kpi-total-machines', children="0", className="fw-bold")
            ], className="text-center"), width=3),
            _kpi_count("Normal", 'kpi-normal-machines', t("tab_machines.normal_2")),
            _kpi_count("Alerta", 'kpi-alerta-machines', t("tab_machines.alerta_2")),
            _kpi_count("Anormal", 'kpi-anormal-machines', t("tab_machines.anormal_2")),
        ], className="mb-4 py-2 border rounded"),

        # ========================================
        # SECTION 2: Fleet matrix (units x components)
        # ========================================
        dbc.Card([
            dbc.CardHeader([
                dbc.Row([
                    dbc.Col([
                        html.H5(t("tab_machines.estado_por_componente_y_maquina"), className="fw-bold d-inline mb-0"),
                        html.Span(id='table-filter-badge', className="ms-2")
                    ], md=5),
                    dbc.Col([
                        html.Label(t("tab_machines.componentes"), htmlFor='fleet-component-columns-selector',
                                   className="small text-muted me-2", style={'display': 'inline-block'}),
                        dcc.Dropdown(
                            id='fleet-component-columns-selector',
                            placeholder=t("tab_component_hours.seleccionar_componentes_2"),
                            multi=True,
                            style={'minWidth': '280px', 'fontSize': '0.85rem'}
                        )
                    ], md=7, className="d-flex align-items-center justify-content-end"),
                ])
            ]),
            dbc.CardBody([
                dcc.Loading(
                    html.Div(id='fleet-heatmap-table-container'),
                    type="circle",
                    delay_show=250,
                ),
                html.Small(
                    t("tab_machines.cada_celda_muestra_el_estado_y"),
                    className="text-muted d-block mt-2"
                )
            ])
        ], className="mb-4"),

        # Matrix stores (filters -> data, sort / page -> view) and the hidden click store
        *stores('fleet'),
        dcc.Store(id='heatmap-click-data', data=None),

        # ========================================
        # SECTION 3: Machine Detail
        # ========================================
        html.Hr(),
        html.H5(t("tab_machines.detalle_de_maquina"), className="mt-3 mb-3"),

        html.Div(id='machine-selection-indicator',
                 children=t("tab_machines.ninguna_maquina_seleccionada"), className="text-muted mb-3"),

        dbc.Row([
            dbc.Col([
                html.Label(t("tab_machines.o_seleccione_maquina"), htmlFor='machine-detail-selector', className="fw-bold small"),
                dcc.Dropdown(id='machine-detail-selector', placeholder=t("tab_machines.seleccionar_maquina"), className="mb-3")
            ], width=4)
        ]),

        html.Div(id='machine-recommendation-container', className="mb-3"),

        dbc.Card([
            dbc.CardHeader(t("tab_machines.componentes_ordenado_de_peor_a_mejor"), className="fw-bold"),
            dbc.CardBody(html.Div(id='machine-detail-table-container'))
        ], className="mb-4"),

        # ========================================
        # SECTION 4: Quick Navigation
        # ========================================
        html.Hr(),
        html.H5(t("tab_machines.navegacion_rapida_al_detalle_de_reporte"), className="mt-3 mb-3"),

        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label(t("tab_machines.equipo"), htmlFor='nav-equipment-selector', className="fw-bold small"),
                        dcc.Dropdown(id='nav-equipment-selector', placeholder=t("tab_machines.equipo_2"))
                    ], width=4),
                    dbc.Col([
                        html.Label(t("tab_machines.componente"), htmlFor='nav-component-selector', className="fw-bold small"),
                        dcc.Dropdown(id='nav-component-selector', placeholder=t("tab_machines.componente_2"), disabled=True)
                    ], width=4),
                    dbc.Col([
                        html.Div([
                            html.Div(className="small", style={'height': '1.5em'}),
                            dbc.Button(t("tab_machines.ir_al_detalle"), id='nav-to-report-button',
                                       color="primary", className="w-100", disabled=True)
                        ])
                    ], width=4)
                ])
            ])
        ], className="mb-4"),

        # Hidden elements for callback compat
        dcc.Store(id='component-grouping-state', data={'use_normalized': False}),
        html.Div(id='component-stacked-bar-chart', style={'display': 'none'}),
        html.Div(id='component-grouping-indicator', style={'display': 'none'}),
        html.Div(id='toggle-component-grouping', style={'display': 'none'}),

    ], fluid=True)
