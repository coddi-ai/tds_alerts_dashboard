"""
Per-unit oil-analysis overview ("Detalle de Máquina" of Monitoring > Oil > General).

Single source for both Monitoring > Oil > General (machines_callbacks.update_machine_detail)
and the Unit Summary's Tribología card
(documentation/general/general_specs/09_unit_summary_monitoreo_grid_and_oil_overview.md),
so the two views cannot drift apart.
"""

from src.i18n import t as _t
from dataclasses import dataclass
from typing import Optional

import dash_bootstrap_components as dbc
import pandas as pd
from dash import html

from config.settings import get_settings
from dashboard.components.labels import display_component_name
from dashboard.components.tables import create_machine_detail_table
from src.data.loaders import get_latest_component_hours, load_machine_status_for_client, load_oil_classified
from src.i18n.data_text import localized_series, localized_value
from src.utils.logger import get_logger

logger = get_logger(__name__)


_STATUS_ORDER = {'Anormal': 0, 'Alerta': 1, 'Normal': 2}


@dataclass(frozen=True)
class OilComponentRow:
    """One component's latest oil sample, as the Unit Detail's Tribología table shows it."""
    component: str
    status: str
    anomaly: Optional[str]    # None when the sample has no anomaly
    diagnosis: Optional[str]  # AI recommendation; None when there is none
    sample_date: Optional[pd.Timestamp]


def unit_oil_components(client: str, unit_id: str) -> Optional[list]:
    """The unit's components with their latest oil sample, worst-first, as `OilComponentRow`s.

    Worst = Anormal > Alerta > Normal, ties broken by severity score (the ranking used
    everywhere). Returns None when the unit has no oil data.
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

        rows = []
        for _, r in latest.iterrows():
            anomaly = r.get('anomalyType') if 'anomalyType' in latest.columns else None
            diagnosis = localized_value(r, 'ai_recommendation') if 'ai_recommendation' in latest.columns else None
            sample_date = r.get('sampleDate')
            rows.append(OilComponentRow(
                component=display_component_name(r['componentName']),
                status=r['report_status'] if pd.notna(r['report_status']) else 'Sin Datos',
                anomaly=str(anomaly) if pd.notna(anomaly) and anomaly != 'Normal' else None,
                diagnosis=str(diagnosis) if diagnosis is not None and pd.notna(diagnosis) and str(diagnosis).strip() else None,
                sample_date=None if pd.isna(sample_date) else sample_date,
            ))
        return rows
    except Exception as e:
        logger.error(f"Unit oil components error: {e}")
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
                display_df[col] = localized_series(latest, col) if col == 'ai_recommendation' else latest[col]

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
                    rec = localized_value(mr.iloc[0], 'machine_ai_recommendation')
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
