"""Building blocks of the Alertas -> Detalle case header.

Three pieces, each one decision the technician reads at a glance:

* evidence-source chips - one per source that contributed to the alert, drawn from
  the alert's own source list (``evidence_sources``), never a fixed pair;
* the "Señal gatillo" callout - the signal/variable that triggered the alert;
* the "Verificar" callout - the yes/no check the generator publishes in its own
  ``verification_question`` field, shown above the narrative recommended action.

Source chips are descriptive, not a severity, so they use the info palette and
never the red/amber/green one.
"""

from typing import Optional

import dash_bootstrap_components as dbc
from dash import html

from src.data.emin_alert_evidence import evidence_sources
from src.i18n import t

# Icon per evidence source id; an unknown source still gets a chip, just a generic icon.
_SOURCE_ICONS = {
    "telemetry": "fa-signal",
    "tribology": "fa-oil-can",
    "maintenance": "fa-tools",
}
_DEFAULT_SOURCE_ICON = "fa-database"


def evidence_source_chips(row) -> html.Div:
    """One neutral chip per evidence source of ``row``; a muted note when it has none."""
    sources = evidence_sources(row)
    if not sources:
        chips = [html.Span(t("alerts_report.sin_evidencia"), className="text-muted small")]
    else:
        chips = [
            html.Span(
                [html.I(className=f"fas {_SOURCE_ICONS.get(source, _DEFAULT_SOURCE_ICON)} me-1"), label],
                className="alert-evidence-chip",
                **{"data-source": source},
            )
            for source, label in sources
        ]
    return html.Div(
        [
            html.Small(t("alerts_callbacks.fuentes_de_evidencia"), className="text-muted d-block text-nowrap mb-1"),
            html.Div(chips, className="d-flex flex-wrap gap-2"),
        ],
        className="alert-evidence-chips",
    )


def trigger_signal_callout(signal: Optional[str]) -> html.Div:
    """The signal/variable that triggered the alert; always rendered."""
    text = str(signal).strip() if signal is not None else ""
    return html.Div(
        [
            html.Div(
                [html.I(className="fas fa-bolt me-2"), t("alerts_callbacks.senal_gatillo")],
                className="alert-trigger-callout__label",
            ),
            html.Div(text or t("alerts_report.sin_senal_registrada"), className="alert-trigger-callout__value"),
        ],
        className="alert-trigger-callout",
    )


def verification_callout(question: Optional[str]) -> Optional[html.Div]:
    """The "Verificar" callout for a published verification question, or None without one."""
    text = str(question).strip() if question is not None else ""
    if not text:
        return None
    return html.Div(
        [
            html.Div(
                [html.I(className="fas fa-clipboard-check me-2"), t("alerts_callbacks.verificar")],
                className="alert-verify-callout__label",
            ),
            html.Div(text, className="alert-verify-callout__question"),
        ],
        className="alert-verify-callout",
    )


def analysis_block(title: str, text: Optional[str], icon: str, verification: Optional[str] = None) -> dbc.Col:
    """One Análisis Inteligente column; ``verification`` adds the callout above the text."""
    body = text or t("tab_alerts_detail.no_disponible")
    return dbc.Col([
        html.Div([
            html.H6([html.I(className=f"fas {icon} me-2"), title], className="mb-2"),
            verification_callout(verification),
            html.P(body, className="mb-0", style={"whiteSpace": "pre-wrap", "lineHeight": "1.5"}),
        ], className="p-3 bg-light rounded h-100")
    ], md=4)
