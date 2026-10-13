"""
Per-unit oil-analysis overview ("Detalle de Máquina" of Monitoring > Oil > General).

Single source for both Monitoring > Oil > General (machines_callbacks.update_machine_detail)
and the Unit Summary's Tribología card
(documentation/general/general_specs/09_unit_summary_monitoreo_grid_and_oil_overview.md),
so the two views cannot drift apart.
"""

from src.i18n import t as _t
from dashboard.components.labels import status_label
import dash_bootstrap_components as dbc
import pandas as pd
from dash import dash_table, html

from config.settings import get_settings
from dashboard.components.tables import create_machine_detail_table
from src.data.loaders import get_latest_component_hours, load_machine_status_for_client, load_oil_classified
from src.utils.logger import get_logger

logger = get_logger(__name__)


_STATUS_STYLE = {
    'Anormal': ('#f8d7da', '#721c24'),
    'Alerta': ('#fff3cd', '#856404'),
    'Normal': ('#d4edda', '#155724'),
}
_STATUS_ORDER = {'Anormal': 0, 'Alerta': 1, 'Normal': 2}


def _compact_table(latest: pd.DataFrame) -> dash_table.DataTable:
    """Transposed DataTable for already-sorted component rows: one column per
    component, Estado/Anomalía rows, AI recommendation as hover text."""
    columns = [{'name': '', 'id': 'row'}]
    estado = {'row': _t("tab_telemetry_fleet.estado")}
    anomalia = {'row': _t("oil_machine_detail.anomalia")}
    tips = {}
    style_cond = []
    for i, (_, r) in enumerate(latest.iterrows()):
        cid = f'c{i}'
        columns.append({'name': str(r['componentName']).title(), 'id': cid})
        status = r['report_status']
        shown_status = status_label(status) if pd.notna(status) else '—'
        estado[cid] = shown_status
        anomaly = r.get('anomalyType') if 'anomalyType' in latest.columns else None
        anomalia[cid] = str(anomaly) if pd.notna(anomaly) and anomaly != 'Normal' else '—'
        rec = r.get('ai_recommendation') if 'ai_recommendation' in latest.columns else None
        tips[cid] = {'value': str(rec) if pd.notna(rec) and str(rec).strip() else _t("oil_machine_detail.sin_recomendacion"),
                     'type': 'text'}
        if status in _STATUS_STYLE:
            bg, fg = _STATUS_STYLE[status]
            style_cond.append({
                'if': {'filter_query': '{%s} = "%s"' % (cid, shown_status), 'column_id': cid},
                'backgroundColor': bg, 'color': fg, 'fontWeight': 'bold',
            })

    row_tip = {'row': {'value': '', 'type': 'text'}, **tips}
    return dash_table.DataTable(
        columns=columns,
        data=[estado, anomalia],
        tooltip_header={cid: t['value'] for cid, t in tips.items()},
        tooltip_data=[row_tip, row_tip],
        tooltip_duration=None,
        css=[{'selector': '.dash-table-tooltip', 'rule': 'max-width: 400px; white-space: normal;'}],
        style_table={'overflowX': 'auto'},
        style_cell={'textAlign': 'center', 'padding': '8px 10px', 'fontSize': '12px',
                    'minWidth': '90px', 'whiteSpace': 'normal', 'height': 'auto'},
        style_header={'backgroundColor': '#6c757d', 'color': 'white', 'fontWeight': 'bold',
                      'textAlign': 'center', 'whiteSpace': 'normal', 'height': 'auto',
                      'overflowWrap': 'anywhere'},
        style_cell_conditional=[
            {'if': {'column_id': 'row'}, 'textAlign': 'left', 'fontWeight': '600', 'minWidth': '80px'},
        ],
        style_data_conditional=style_cond,
    )


def build_machine_compact_table(client: str, unit_id: str, top_n: int | None = None):
    """Compact, transposed per-unit oil view for the Unit Summary card.

    One column per component (worst-first), two rows: Estado and Anomalía.
    Each component's AI recommendation is the hover text of its header and
    cells. Returns the DataTable, or None when the unit has no oil data.

    With `top_n`, only the `top_n` worst components are shown by default and
    the rest sit in a collapsed "show remaining" section underneath (native
    <details>, no callback), so a unit with many components doesn't need a wide
    horizontally-scrolling table (10_unit_summary_monitoreo_polish_and_
    component_source_fix.md Required Changes #4). Worst = the same
    Anormal > Alerta > Normal ranking used everywhere, ties broken by
    severity score.
    """
    if not get_settings().get_classified_reports_path(client.lower()).exists():
        return None
    try:
        df = load_oil_classified(client)
        mdf = df[df['unitId'] == unit_id].copy()
        if mdf.empty:
            return None

        mdf['sampleDate'] = pd.to_datetime(mdf['sampleDate'])
        latest = mdf.loc[mdf.groupby('componentName')['sampleDate'].idxmax()].copy()
        latest['_rank'] = latest['report_status'].map(_STATUS_ORDER).fillna(99)
        sort_cols, ascending = ['_rank'], [True]
        if 'severity_score' in latest.columns:
            sort_cols.append('severity_score')
            ascending.append(False)
        latest = latest.sort_values(sort_cols, ascending=ascending)

        if top_n is None or len(latest) <= top_n:
            return _compact_table(latest)

        rest = latest.iloc[top_n:]
        return html.Div([
            _compact_table(latest.iloc[:top_n]),
            html.Details([
                html.Summary(_t("oil_machine_detail.ver_componentes_restantes", count=len(rest)),
                             style={'cursor': 'pointer', 'fontSize': '12px', 'padding': '6px 0'}),
                _compact_table(rest),
            ], className="mt-2"),
        ])
    except Exception as e:
        logger.error(f"Compact oil table error: {e}")
        return None


def build_machine_detail(client: str, unit_id: str) -> tuple:
    """Build the oil detail for one unit.

    Returns `(indicator, color, recommendation_card, table)`: the machine
    header/summary line, its alert color, the machine-level AI recommendation
    card (empty Div if none) and the worst-first component table. When there
    is nothing to show, `table` is a message string and `recommendation_card`
    an empty Div. `color` is "info" only when real data was found.
    """
    settings = get_settings()
    reports_file = settings.get_classified_reports_path(client.lower())
    machine_file = settings.get_machine_status_path(client.lower())
    if not reports_file.exists():
        return _t("oil_machine_detail.sin_datos"), "light", html.Div(), _t("oil_machine_detail.no_hay_datos")

    try:
        df = load_oil_classified(client)
        mdf = df[df['unitId'] == unit_id].copy()
        if mdf.empty:
            return _t("oil_machine_detail.maquina", unit_id=unit_id), "warning", html.Div(), _t("oil_machine_detail.sin_datos_para", unit_id=unit_id)

        mdf['sampleDate'] = pd.to_datetime(mdf['sampleDate'])
        latest = mdf.loc[mdf.groupby('componentName')['sampleDate'].idxmax()]
        display_df = latest[['componentName', 'report_status', 'severity_score',
                              'essays_broken', 'sampleDate']].copy()
        for col in ['breached_essays', 'ai_recommendation', 'anomalyType']:
            if col in latest.columns:
                display_df[col] = latest[col]

        comp_hours_allowed = [c.upper() for c in settings.component_hours_allowed_clients]
        if client.upper() in comp_hours_allowed:
            chf = settings.get_component_hours_path(client.lower())
            if chf.exists():
                try:
                    lh = get_latest_component_hours(chf)
                    if not lh.empty:
                        uh = lh[lh['unitId'] == unit_id][['componentName', 'componentHours_cleaned']].copy()
                        if not uh.empty:
                            display_df = display_df.merge(uh, on='componentName', how='left')
                except Exception as e:
                    logger.warning(f"Component hours: {e}")

        display_df['sampleDate'] = pd.to_datetime(display_df['sampleDate']).dt.strftime('%Y-%m-%d')
        mt = str(mdf.iloc[0].get('machineName', 'N/A')).title()
        an = (display_df['report_status'] == 'Anormal').sum()
        al = (display_df['report_status'] == 'Alerta').sum()
        no = (display_df['report_status'] == 'Normal').sum()

        indicator = html.Div([
            html.Strong(f"📍 {unit_id} ({mt})", className="me-3"),
            html.Span(f"🟢{no} 🟡{al} 🔴{an}", className="small")
        ])

        rec_card = html.Div()
        if machine_file.exists():
            try:
                ms_df = load_machine_status_for_client(client)
                mr = ms_df[ms_df['unit_id'] == unit_id]
                if not mr.empty:
                    rec = mr.iloc[0].get('machine_ai_recommendation', None)
                    if rec and pd.notna(rec) and str(rec).strip():
                        rec_card = dbc.Card([
                            dbc.CardHeader(_t("oil_machine_detail.recomendacion_ia"), className="fw-bold bg-info text-white"),
                            dbc.CardBody(html.P(str(rec), style={
                                'whiteSpace': 'pre-wrap', 'fontSize': '0.9rem', 'lineHeight': '1.5'}))
                        ], className="mb-3")
            except Exception as e:
                logger.warning(f"Recommendation: {e}")

        table = create_machine_detail_table(display_df)
        return indicator, "info", rec_card, table
    except Exception as e:
        logger.error(f"Machine detail error: {e}")
        return _t("oil_machine_detail.error", unit_id=unit_id), "danger", html.Div(), str(e)
