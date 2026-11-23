"""
Panel de Frecuencia (Monitor de Aceite): for each unit and component, when it was last sampled and
whether a new sample must be requested.

The interval of each criticality group (15 / 30 / 60 days) and the machine/component mapping are
read from config/sampling_frequency.yaml; the rules live in src/data/sampling_frequency.py. The panel
is read-only: it does not create or send sample requests.
"""

from dash import dcc, html
import dash_bootstrap_components as dbc

from dashboard.components.oil_frequency import group_label, status_text
from dashboard.components.oil_table import stores
from dashboard.components.oil_ui import filter_field, page_header
from src.data import sampling_frequency as sf
from src.i18n import t


def _dropdown(control_id: str, placeholder: str, **kwargs):
    return dcc.Dropdown(id=control_id, placeholder=placeholder, className="mb-2", **kwargs)


def _group_options() -> list:
    """"Todas" plus one option per configured group (its label follows the interval in the file)."""
    options = [{"label": t("frequency.todas"), "value": "all"}]
    try:
        options += [{"label": group_label(g.days), "value": g.key} for g in sf.load_config().ordered_groups()]
    except sf.FrequencyConfigError:
        pass   # the panel itself reports the configuration problem
    return options


def _status_options() -> list:
    return [{"label": t("frequency.todos_los_estados"), "value": "all"}] + [
        {"label": status_text(status), "value": status}
        for status in (sf.SOLICITAR, sf.PROXIMA, sf.AL_DIA, sf.SIN_MUESTRA)
    ]


def create_frequency_tab() -> dbc.Container:
    """Create Tab: Panel de Frecuencia."""
    return dbc.Container([
        page_header(
            t("frequency.panel_de_frecuencia"),
            subtitle=t("frequency.subtitulo"),
            # "Datos al <fecha> (último reporte validado)", filled from the client's latest reportDate.
            caption=html.Span(id="freq-data-as-of", children=""),
        ),
        html.Hr(),

        # Filters
        dbc.Row([
            filter_field(t("frequency.filtro_sitio_area"),
                         _dropdown("freq-site-filter", t("frequency.todos")), "freq-site-filter", md=6, lg=2),
            filter_field(t("frequency.filtro_flota"),
                         _dropdown("freq-fleet-filter", t("frequency.seleccionar")), "freq-fleet-filter", md=6, lg=2),
            filter_field(t("frequency.filtro_componente"),
                         _dropdown("freq-component-filter", t("frequency.todos_los_componentes")),
                         "freq-component-filter", md=6, lg=3),
            filter_field(t("frequency.filtro_criticidad"),
                         _dropdown("freq-group-filter", "", value="all", clearable=False, options=_group_options()),
                         "freq-group-filter", md=6, lg=2),
            filter_field(t("frequency.filtro_estado_de_frecuencia"),
                         _dropdown("freq-status-filter", "", value="all", clearable=False, options=_status_options()),
                         "freq-status-filter", md=6, lg=3),
        ], className="mb-3 p-3 bg-light rounded"),

        # KPI tiles (follow the filters)
        html.Div(id="freq-kpis", className="mb-2"),

        # Grupos de Criticidad
        html.Div(id="freq-groups"),

        # Main table
        dbc.Card([
            dbc.CardHeader(dbc.Row([
                dbc.Col([
                    html.H5(t("frequency.estado_de_muestreo"), className="fw-bold d-inline mb-0"),
                    html.Span(id="freq-count-chip", className="ms-2"),
                ], md=8),
                dbc.Col(html.Span(id="freq-sort-note", className="oil-caption"), md=4,
                        className="text-md-end"),
            ], align="center")),
            dbc.CardBody([
                dcc.Loading(html.Div(id="freq-table-container"), type="circle", delay_show=250),
                html.P(t("frequency.nota_al_pie"), className="oil-footnote mb-0"),
            ]),
        ], className="shadow-sm mb-4"),

        *stores("freq"),
    ], fluid=True)
