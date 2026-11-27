"""
The criteria behind every state of the General tab, printed on the page.

A collapsed panel under the search box answers three questions: what makes a technique Normal / Alerta /
Anormal, how old data changes that, and how the unit's Estado comes out of its techniques.

The text is not written next to the logic: every number in it is read from the constants the scheduled run
classifies with (`config/estado_rules.py`: the Alertas score limits, the Tribología score limits,
`STALENESS_FLOOR`, `NO_STATUS_TECHNIQUES`, and the thresholds of `config/freshness_thresholds.py`), so
changing a rule changes the page with it. `tests/test_fleet_status.py` pins that the text follows the
constants and that the constants are what the classification uses.
"""

from dash import html

from config.estado_rules import (
    ALERTS_ALERTA_MAX_SCORE,
    ALERTS_COMPONENT_WEIGHT,
    ALERTS_WINDOW_DAYS,
    NO_STATUS_TECHNIQUES,
    OIL_COMPONENT_POINTS,
    OIL_SCORE_ANORMAL_FROM,
    RISK_RANK,
    staleness_floor_limits,
)
from dashboard.components.fleet_overview import technique_label
from dashboard.components.labels import age_text, status_label
from dashboard.components.status_chip import status_chip
from src.data.fleet_status import TECHNIQUE_FRESHNESS_KEY, applicable_techniques
from src.i18n import current_language, t as _t

# Techniques that publish a finished state (their rule lives upstream): the page says so in one sentence.
# Alertas and Tribología have limits the page can state as numbers (`_NUMERIC_CRITERIA` below).
_PUBLISHED_RULE_KEYS = {
    "telemetry": "fleet_criteria.telemetry_rule",
    "predictive": "fleet_criteria.predictive_rule",
}
_STALE_KEYS = {"Alerta": "unit_summary_content.stale_to_alert", "Anormal": "unit_summary_content.stale_to_abnormal"}


def _number(value) -> str:
    """15 -> "15", 0.5 -> "0,5" / "0.5" (decimal comma in Spanish)."""
    text = f"{value:g}"
    return text.replace(".", ",") if current_language() == "es" else text


def alerts_criteria() -> dict:
    """{estado: sentence} of Alertas, from the limits `calculate_alert_criticality_score` classifies with."""
    return {
        "Normal": _t("fleet_criteria.alerts_normal", days=ALERTS_WINDOW_DAYS),
        "Alerta": _t("fleet_criteria.alerts_alerta", limit=_number(ALERTS_ALERTA_MAX_SCORE)),
        "Anormal": _t("fleet_criteria.alerts_anormal", limit=_number(ALERTS_ALERTA_MAX_SCORE)),
    }


def oil_criteria() -> dict:
    """{estado: sentence} of Tribología: the rule of the oil pipeline's published machine status."""
    limit = _number(OIL_SCORE_ANORMAL_FROM)
    return {
        "Normal": _t("fleet_criteria.oil_normal"),
        "Alerta": _t("fleet_criteria.oil_alerta"),
        "Anormal": _t("fleet_criteria.oil_anormal", limit=limit),
    }


def oil_score_note() -> str:
    return _t(
        "fleet_criteria.oil_score_note",
        alerta=_number(OIL_COMPONENT_POINTS["Alerta"]), anormal=_number(OIL_COMPONENT_POINTS["Anormal"]),
    )


_NUMERIC_CRITERIA = {"alerts": alerts_criteria, "oil": oil_criteria}


def stale_data_sentences(technique: str) -> list:
    """What a technique's data age forces: "Más de 2 h sin actualizarse cuenta como Alerta.", ... Empty when
    the technique has no thresholds."""
    limits = staleness_floor_limits(TECHNIQUE_FRESHNESS_KEY[technique])
    return [_t(_STALE_KEYS[estado], age=age_text(limits[estado])) for estado in _STALE_KEYS if estado in limits]


def _technique_row(technique: str) -> html.Tr:
    if technique not in _NUMERIC_CRITERIA:
        return html.Tr([
            html.Th(technique_label(technique), scope="row", className="fleet-criteria__technique"),
            html.Td(_t(_PUBLISHED_RULE_KEYS[technique]), colSpan=3),
        ])
    criteria = _NUMERIC_CRITERIA[technique]()
    if technique == "alerts":
        how = _t("fleet_criteria.alerts_score_note", weight=_number(ALERTS_COMPONENT_WEIGHT), days=ALERTS_WINDOW_DAYS)
    else:
        how = oil_score_note()
    return html.Tr(
        [html.Th([technique_label(technique), html.Div(how, className="fleet-criteria__note")],
                 scope="row", className="fleet-criteria__technique")]
        + [html.Td(criteria[estado]) for estado in ("Normal", "Alerta", "Anormal")]
    )


def _overall_order() -> str:
    """"Anormal > Alerta > Normal": the worst-of order of `RISK_RANK`."""
    return " > ".join(status_label(estado) for estado in sorted(RISK_RANK, key=RISK_RANK.get, reverse=True))


def render_fleet_criteria(client: str) -> html.Details:
    """The collapsed "how the states are assigned" panel for `client`'s techniques."""
    applicable = applicable_techniques(client)
    techniques = [t for t in ("alerts", "telemetry", "oil", "predictive") if applicable.get(t) and t not in NO_STATUS_TECHNIQUES]
    if not techniques:
        return html.Div()

    table = html.Table([
        html.Thead(html.Tr(
            [html.Th(_t("fleet_criteria.col_technique"), scope="col")]
            + [html.Th(status_chip(estado), scope="col") for estado in ("Normal", "Alerta", "Anormal")]
        )),
        html.Tbody([_technique_row(t) for t in techniques]),
    ], className="fleet-criteria__table")

    age_items = []
    for technique in techniques:
        sentences = stale_data_sentences(technique)
        if sentences:
            age_items.append(html.Li([html.Strong(technique_label(technique) + ": "), " ".join(sentences)]))

    return html.Details([
        html.Summary([
            html.I(className="fas fa-circle-info me-2", **{"aria-hidden": "true"}),
            _t("fleet_criteria.title"),
        ], className="fleet-criteria__summary"),
        html.Div([
            html.P(_t("fleet_criteria.intro"), className="fleet-criteria__lead"),
            html.H3(_t("fleet_criteria.technique_title"), className="fleet-criteria__heading"),
            html.Div(table, className="fleet-criteria__scroll"),
            html.P(_t("fleet_criteria.no_data"), className="fleet-criteria__text"),
            html.H3(_t("fleet_criteria.age_title"), className="fleet-criteria__heading"),
            html.P(_t("fleet_criteria.age_intro"), className="fleet-criteria__text"),
            html.Ul(age_items, className="fleet-criteria__list"),
            *([html.P(_t("fleet_criteria.age_alerts_note"), className="fleet-criteria__note")] if "alerts" in techniques else []),
            html.H3(_t("fleet_criteria.overall_title"), className="fleet-criteria__heading"),
            html.P(_t("fleet_criteria.overall_text", order=_overall_order()), className="fleet-criteria__text"),
            html.P(_t("fleet_criteria.refresh_note"), className="fleet-criteria__note"),
        ], className="fleet-criteria__body"),
    ], className="fleet-criteria", id="fleet-criteria")
