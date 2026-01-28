"""
Reusable table components for Multi-Technical-Alerts dashboard.
"""

from dash import dash_table, html
import dash_bootstrap_components as dbc
import pandas as pd
from typing import List, Dict


def create_limits_table(df: pd.DataFrame) -> dash_table.DataTable:
    """
    Create Stewart Limits table with color coding.
    
    Args:
        df: DataFrame with limits (machine, component, essay, thresholds)
    
    Returns:
        Dash DataTable
    """
    if df.empty:
        return html.Div("No limits data available", className="text-muted p-3")
    
    return dash_table.DataTable(
        id='limits-table',
        columns=[
            {'name': 'Machine', 'id': 'machine'},
            {'name': 'Component', 'id': 'component'},
            {'name': 'Essay', 'id': 'essay'},
            {'name': 'Marginal (90%)', 'id': 'threshold_normal', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'Condenatorio (95%)', 'id': 'threshold_alert', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'Crítico (98%)', 'id': 'threshold_critic', 'type': 'numeric', 'format': {'specifier': '.2f'}}
        ],
        data=df.to_dict('records'),
        style_table={'overflowX': 'auto'},
        style_cell={
            'textAlign': 'left',
            'padding': '10px',
            'fontSize': '14px'
        },
        style_header={
            'backgroundColor': '#17a2b8',
            'color': 'white',
            'fontWeight': 'bold',
            'textAlign': 'center'
        },
        style_data_conditional=[
            {
                'if': {'column_id': 'threshold_normal'},
                'backgroundColor': '#d4edda'
            },
            {
                'if': {'column_id': 'threshold_alert'},
                'backgroundColor': '#fff3cd'
            },
            {
                'if': {'column_id': 'threshold_critic'},
                'backgroundColor': '#f8d7da'
            }
        ],
        filter_action='native',
        sort_action='native',
        page_action='native',
        page_size=20
    )


def create_priority_table(df: pd.DataFrame) -> dash_table.DataTable:
    """
    Create priority table for machines requiring attention.
    
    Args:
        df: DataFrame with machine statuses
    
    Returns:
        Dash DataTable
    """
    if df.empty:
        return html.Div("No priority machines", className="text-success p-3")
    
    # Filter to non-Normal machines and sort by priority
    priority_df = df[df['overall_status'] != 'Normal'].copy()
    priority_df = priority_df.sort_values('priority_score', ascending=False).head(10)
    
    if priority_df.empty:
        return html.Div("All machines are Normal", className="text-success p-3")
    
    # Select columns
    display_df = priority_df[['unit_id', 'overall_status', 'machine_score', 
                               'components_anormal', 'components_alerta', 
                               'latest_sample_date']].copy()
    
    return dash_table.DataTable(
        id='priority-table',
        columns=[
            {'name': 'Unit ID', 'id': 'unit_id'},
            {'name': 'Status', 'id': 'overall_status'},
            {'name': 'Score', 'id': 'machine_score', 'type': 'numeric'},
            {'name': 'Anormal', 'id': 'components_anormal', 'type': 'numeric'},
            {'name': 'Alerta', 'id': 'components_alerta', 'type': 'numeric'},
            {'name': 'Last Sample', 'id': 'latest_sample_date'}
        ],
        data=display_df.to_dict('records'),
        style_table={'overflowX': 'auto'},
        style_cell={
            'textAlign': 'left',
            'padding': '10px',
            'fontSize': '14px'
        },
        style_header={
            'backgroundColor': '#343a40',
            'color': 'white',
            'fontWeight': 'bold',
            'textAlign': 'center'
        },
        style_data_conditional=[
            {
                'if': {
                    'filter_query': '{overall_status} = "Anormal"',
                    'column_id': 'overall_status'
                },
                'backgroundColor': '#dc3545',
                'color': 'white',
                'fontWeight': 'bold'
            },
            {
                'if': {
                    'filter_query': '{overall_status} = "Alerta"',
                    'column_id': 'overall_status'
                },
                'backgroundColor': '#ffc107',
                'color': 'black',
                'fontWeight': 'bold'
            }
        ],
        sort_action='native'
    )


def create_machine_detail_table(df: pd.DataFrame) -> dash_table.DataTable:
    """
    Create detailed machine component table.
    
    Args:
        df: DataFrame with component statuses for a machine
    
    Returns:
        Dash DataTable
    """
    if df.empty:
        return html.Div("Select a machine to view details", className="text-muted p-3")
    
    # Dynamic columns based on available data
    columns = []
    if 'unitId' in df.columns:
        columns.append({'name': 'Machine', 'id': 'unitId'})
    
    columns.extend([
        {'name': 'Component', 'id': 'componentName'},
        {'name': 'Status', 'id': 'report_status'},
        {'name': 'Severity Score', 'id': 'severity_score', 'type': 'numeric'},
        {'name': 'Essays Broken', 'id': 'essays_broken', 'type': 'numeric'},
        {'name': 'Sample Date', 'id': 'sampleDate'}
    ])
    
    return dash_table.DataTable(
        id='machine-detail-table',
        columns=columns,
        data=df.to_dict('records'),
        style_table={'overflowX': 'auto'},
        style_cell={
            'textAlign': 'left',
            'padding': '10px',
            'fontSize': '14px'
        },
        style_header={
            'backgroundColor': '#6c757d',
            'color': 'white',
            'fontWeight': 'bold',
            'textAlign': 'center'
        },
        style_data_conditional=[
            {
                'if': {
                    'filter_query': '{report_status} = "Anormal"',
                    'column_id': 'report_status'
                },
                'backgroundColor': '#f8d7da',
                'color': '#721c24',
                'fontWeight': 'bold'
            },
            {
                'if': {
                    'filter_query': '{report_status} = "Alerta"',
                    'column_id': 'report_status'
                },
                'backgroundColor': '#fff3cd',
                'color': '#856404',
                'fontWeight': 'bold'
            },
            {
                'if': {
                    'filter_query': '{report_status} = "Normal"',
                    'column_id': 'report_status'
                },
                'backgroundColor': '#d4edda',
                'color': '#155724'
            }
        ],
        sort_action='native'
    )


def create_ai_recommendations_card(recommendations: List[Dict]) -> dbc.Card:
    """
    Create card displaying AI recommendations.
    
    Args:
        recommendations: List of recommendation dictionaries
    
    Returns:
        Bootstrap card with recommendations
    """
    if not recommendations:
        return dbc.Card(
            dbc.CardBody("No AI recommendations available"),
            className="mb-3"
        )
    
    cards = []
    for rec in recommendations[:5]:  # Show top 5
        cards.append(
            dbc.Card([
                dbc.CardHeader(f"Sample: {rec.get('sampleNumber', 'N/A')}", className="fw-bold"),
                dbc.CardBody([
                    html.P(f"Status: {rec.get('status', 'N/A')}", className="mb-2"),
                    html.P(rec.get('recommendation', 'N/A'), className="text-muted")
                ])
            ], className="mb-2")
        )
    
    return dbc.Card(
        dbc.CardBody(cards),
        className="mb-3"
    )
