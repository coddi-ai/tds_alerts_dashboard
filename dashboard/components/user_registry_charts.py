"""
Chart components for the admin "Registro de usuarios" view.
"""

from src.i18n import t
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Raw deploy_status values (from the DEPLOY_STATUS env var) mapped to display labels.
DEPLOY_STATUS_KEYS = {
    'POC': 'production',
    'test': 'development',
}


def _deploy_status_labels() -> dict:
    return {raw: t(f"user_registry_charts.env_{key}") for raw, key in DEPLOY_STATUS_KEYS.items()}


def _deploy_status_colors() -> dict:
    """Fixed categorical colors (never cycled), keyed by the translated display label."""
    labels = _deploy_status_labels()
    return {
        labels['POC']: '#109618',
        labels['test']: '#3366CC',
        'unknown': '#898781',
    }


def create_login_events_chart(counts_df: pd.DataFrame) -> go.Figure:
    """
    Create horizontal bar chart of login event counts per user, grouped by deploy_status.

    Args:
        counts_df: DataFrame with columns ['username', 'deploy_status', 'count'].

    Returns:
        Plotly Figure with horizontal bar chart.
    """
    if counts_df.empty:
        logger.info("No login events available for user registry chart")
        return go.Figure().add_annotation(
            text=t("user_registry_charts.no_hay_eventos_de_inicio_de"),
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )

    counts_df = counts_df.assign(
        deploy_status=counts_df['deploy_status'].map(_deploy_status_labels()).fillna(counts_df['deploy_status'])
    )

    fig = px.bar(
        counts_df,
        y='username',
        x='count',
        color='deploy_status',
        orientation='h',
        title=None,
        template='plotly_white',
        labels={'count': t("user_registry_charts.numero_de_inicios_de_sesion"), 'username': t("user_registry_charts.usuario"), 'deploy_status': t("user_registry_charts.ambiente")},
        color_discrete_map=_deploy_status_colors(),
        text='count',
        barmode='group',
    )
    fig.update_traces(textposition='inside')
    fig.update_layout(
        autosize=True,
        yaxis={'categoryorder': 'total ascending'},
        showlegend=True,
        legend=dict(
            title=t("user_registry_charts.ambiente"),
            orientation='h',
            x=1,
            y=1.08,
            xanchor='right',
            yanchor='bottom',
            font=dict(size=11),
        ),
        hovermode='closest',
    )

    logger.info("Created user registry login events chart successfully")
    return fig
