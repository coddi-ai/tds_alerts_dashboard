"""Presentation of the latest EMIN fleet and unit reports."""

from ast import literal_eval
from datetime import date, timedelta
from html import escape

from dash import dcc, html
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from dashboard.components.emin_historical import section_header
from dashboard.components.predictive_state import STATE_COLORS, STATE_ZONE_FILL
from src.charts.theme import apply_dashboard_theme
from src.i18n import t


QUADRANTS = ("healthy", "recent_improvement", "critical", "recent_worsening")
QUADRANT_STYLES = {
    "healthy": ("Normal", "#11654d", "improved"),
    "recent_improvement": ("Alerta", "#785700", "stable"),
    "critical": ("Anormal", "#a32d2d", "worsened"),
    "recent_worsening": ("Alerta", "#785700", "stable"),
}
OIL_STATES = ("abnormal", "alert", "normal", "unknown")
OIL_COLORS = {"abnormal": STATE_COLORS["Anormal"], "alert": STATE_COLORS["Alerta"],
              "normal": STATE_COLORS["Normal"], "unknown": "#64748b"}
CATEGORIES = ("event", "intervention", "downtime", "oil", "monthly")
CATEGORY_COLORS = {"event": "#d53e4f", "intervention": "#6349aa", "downtime": "#476687",
                   "oil": "#b76507", "monthly": "#64748b"}
PAGE_SIZE = 30


def _t(key, **values):
    return t(f"emin_beta.{key}", **values)


def _label_day(value):
    if len(value) == 7:
        year, month = value.split("-")
        return f"{month}/{year}"
    return date.fromisoformat(value).strftime("%d-%m-%Y")


def _points(value):
    return f"{value:.1f}" if value is not None else "—"


def _delta(value):
    if value is None:
        return "—"
    return f"{value:+.1f}" if round(value, 1) else "0.0"


def _movement(state):
    return _t("insufficient") if state == "insufficient" else t(f"emin_history.movement_{state}")


def _state(record):
    if record["severity"] and record["state"] == "recorded":
        return record["severity"]
    return _t(f"state_{record['state']}")


def _description(record):
    parts = [record["description"]]
    if record["hours"] is not None:
        parts.append(_t("hours", value=_points(record["hours"])))
    if record["failures"] is not None:
        parts.append(_t("failures", count=int(record["failures"])))
    return " · ".join(filter(None, parts)) or "—"


def _record_reference(record):
    source = _t("source_" + record["kind"])
    return f"{source} · {record['reference']}" if record["reference"] else source


def _unit_link(unit, record=None):
    attributes = {"data-emin-open-unit": unit}
    if record is not None:
        attributes["data-emin-open-record"] = str(record["id"])
    return html.A(unit, href="#emin-history-detail-heading", className="fleet-unit-link", **attributes)


def _fact_title(record):
    if record["category"] == "oil":
        return _t("abnormal_sample" if record["state"] == "abnormal" else "oil_sample")
    if record["category"] == "event":
        return _t("reported_event")
    return _t("category_" + record["category"])


def _fact_body(record):
    description = _description(record)
    parts = (record["component"], description if description != "—" else "")
    return " · ".join(dict.fromkeys(part.strip() for part in parts if part.strip())) or _state(record)


def _urgent_fact(record):
    return ((record["category"] == "oil" and record["state"] == "abnormal")
            or (record["category"] == "event" and record["state"] in {"critical", "high"}))


def _weekly_facts(report):
    """Select one already published, relevant record per unit for this ISO week."""
    facts = {}
    week = report["cutoff"]["week"]
    for unit, view in report["units"].items():
        selected = None
        for record in view["records"]:
            if record["week"] != week:
                continue
            category, state = record["category"], record["state"]
            if _urgent_fact(record):
                selected = record
                break
            if selected is None and (
                (category == "oil" and state == "alert")
                or (category in {"downtime", "intervention"} and state in {"recorded", "indication"})
                or (category == "event" and state in {"indication", "recorded"})
            ):
                selected = record
        if selected is not None:
            facts[unit] = selected
    if report.get("scoring_review_version") == 1:
        for row in report["rows"]:
            unit = row["unit"]
            finding = row.get("scoring_review", {}).get("finding_id")
            if finding is not None:
                record = next((item for item in report["units"][unit]["records"] if item["id"] == finding), None)
                if record is not None:
                    facts[unit] = record
    return facts


def _fact_snippet(record):
    return html.Div([
        html.Strong(_fact_title(record)),
        html.Small(_state(record), className="d-block text-muted")
        if record["category"] == "event" and record["state"] in {"critical", "high"} else None,
        html.Div(_fact_body(record), className="emin-beta-fact-excerpt"),
        html.Small(f"{_label_day(record['day'])} · {_t('source_' + record['kind'])}",
                   className="d-block text-muted"),
    ])


def _week_without_fact(comparison):
    return _t("no_week_data" if comparison.get("current_average") is None else "no_week_fact")


def _section(title, icon, children, **body_props):
    return dbc.Card([
        section_header(title, icon),
        dbc.CardBody(children, **body_props),
    ], class_name="shadow-sm unit-card mb-3")


def date_caption(report):
    cutoff = report["cutoff"]
    return _t("cutoff", day=_label_day(cutoff["cutoff"]),
              status=_t("complete" if cutoff["complete"] else "partial"),
              start=_label_day(report["start"]))


def _graph(figure, graph_id=None):
    props = {"id": graph_id} if graph_id else {}
    return dcc.Graph(figure=figure, **props, config={"displayModeBar": False}, responsive=True,
                     style={"height": f"{figure.layout.height}px", "width": "100%"})


CONDITION_LABELS = {None: "Sin evaluación", "clear": "Sin hallazgos activos registrados",
                    "monitor": "Seguimiento", "alert": "Alerta", "critical": "Crítico"}


def _new_condition(current):
    return any(change["change"] in {"new", "worsened"} for change in current.get("changes", []))


def _condition_label(entry):
    label = entry["label"]
    if label.startswith("[") and label.endswith("]"):
        try:
            parsed = literal_eval(label)
            if isinstance(parsed, list) and all(isinstance(value, str) for value in parsed):
                return " · ".join(parsed)
        except (SyntaxError, ValueError):
            pass
    return label


def _condition_evidence(entry):
    source = {"alert": "Alerta EMIN", "oil": "Tribología", "maintenance": "Mantención o detención"}.get(entry["source"])
    delta = entry.get("point_delta")
    references = entry.get("references") or [entry["reference"]]
    reference = ", ".join(references[:3]) + (f" y {len(references) - 3} más" if len(references) > 3 else "")
    if entry.get("change") == "reconciled":
        impact = f" · Conciliación de registros vinculados: {delta:+d} puntos" if delta is not None else " · Conciliación"
    else:
        impact = (f" · {delta:+d} puntos" if delta else " · Sin cambio en el puntaje") if delta is not None else None
    return html.Li([html.Strong(_condition_label(entry)), " · ", _label_day(entry["day"]),
                    f" · {source or entry['source']} · {reference}",
                    html.Strong(impact) if impact else None])


def _condition_week_points(week):
    points, previous = week["points"], week.get("previous_points")
    if points is None:
        return "Sin evaluación"
    if previous is None:
        return f"{points} puntos en el corte"
    delta = points - previous
    change = f"{delta:+d}" if delta else "sin cambio"
    rate = f" · {week['rate']:.1f} puntos nuevos por 100 h" if week.get("rate") is not None else ""
    return f"{previous} → {points} puntos ({change}){rate}"


def _condition_breakdown(condition):
    groups = condition["active"]
    if not groups:
        return html.P("Sin condiciones activas registradas en las fuentes disponibles.", className="text-muted")
    ranked = sorted(groups, key=lambda group: -group["points"])
    return html.Div([
        html.P([html.Strong(f"{condition['points']} puntos en {len(groups)} condiciones abiertas."),
                " Una condición respaldada por varios registros aporta una sola vez, con su mayor gravedad."]),
        html.Ul([
            html.Li(html.Details([
                html.Summary([html.Strong(f"+{group['points']} · "),
                              _condition_label(max(group["evidence"], key=lambda entry: entry["points"]))]),
                html.Ul([_condition_evidence(entry) for entry in group["evidence"]]),
            ])) for group in ranked
        ], className="mb-3", **{"aria-label": "Aportes al puntaje"}),
    ])


def _condition_source_dates(dates, cutoff=None):
    if not dates:
        return None
    labels = {"alerts": "Alertas de condición", "events": "Eventos", "oil": "Aceite",
              "maintenance": "Mantenciones y detenciones", "hourmeter": "Horómetro"}
    def freshness(day):
        if not day or not cutoff:
            return None
        age = (cutoff - date.fromisoformat(day)).days
        if age >= 14:
            return html.Small(f" · Antiguo · hace {age} días", className="text-warning")
        return html.Small(f" · hace {age} días", className="text-muted") if age else None

    return html.Details([
        html.Summary("Últimos registros por fuente"),
        html.P("Se muestra la última fecha de registro encontrada hasta el corte. Una fecha antigua o sin registro no certifica cobertura completa.",
               className="small text-muted mt-2 mb-1"),
        html.Dl([
            html.Div([html.Dt(label), html.Dd([
                _label_day(dates[source]) if dates.get(source) else "Sin registro",
                freshness(dates.get(source)),
            ])])
            for source, label in labels.items()
        ], className="mb-0"),
    ], className="emin-beta-disclosure mb-3")


def _condition_cards(report):
    model = report.get("condition_model")
    if not model or not model["provenance"].get("preview"):
        return None
    model_rows = model["rows"]
    rows_by_unit = {row["unit"]: row for row in model_rows}
    critical = [row["current"] for row in model_rows if (row["current"] or {}).get("level") == "critical"]
    recent = sum(any(change["change"] in {"new", "worsened"} and change.get("point_delta", 0) > 0
                     for change in current.get("changes", [])) for current in critical)
    urgent_rows = [row for row in model_rows if row.get("urgent_week")]
    classified = model.get("classification", {})
    comparable = []
    for row in model_rows:
        current = row["current"] or {}
        if row.get("quadrant"):
            priority = current.get("level") == "critical" or row.get("urgent_week")
            comparable.append({"unit": row["unit"], "priority": "high" if priority else None, "comparison": {
                "current_average": current["points"], "previous_average": row["previous_average"],
                "quadrant": row["quadrant"], "missing": [],
            }})
    zone_labels = {
        "healthy": "Estables",
        "recent_improvement": "Mejoraron",
        "critical": "Críticos sostenidos",
        "recent_worsening": "Empeoraron",
    }
    candidate_plot = fleet_figure({"rows": comparable, "quadrants": {"threshold": model["threshold"]},
                                   "zone_labels": zone_labels, "condition_jackknife": True})
    if candidate_plot:
        candidate_plot.update_xaxes(title_text="Puntaje del corte")
        candidate_plot.update_yaxes(title_text="Promedio histórico anterior")
    return _section("Condición desde fuentes · Vista previa", "fas fa-stethoscope", [
        html.P("Puntos de Riesgo suman condiciones adversas registradas que siguen abiertas. "
               "Cada condición aporta 1, 2 o 3 puntos según la gravedad documentada; señales repetidas o corroboradas no se duplican. "
               "Es una medida de priorización observada, no una probabilidad de falla."),
        html.P([
            html.Strong(f"{len(urgent_rows)} equipos con un hallazgo grave nuevo o agravado en la semana. "),
            f"{len(critical)} equipos mantienen nivel crítico; {recent} de ellos tuvieron un aumento adverso en este corte.",
        ]),
        html.P(f"Bandas piloto: Seguimiento 1–{model['alert_threshold'] - 1} · "
               f"Alerta {model['alert_threshold']}–{model['threshold'] - 1} · Crítico desde {model['threshold']} puntos.",
               className="small text-muted") if "alert_threshold" in model else None,
        html.Details([
            html.Summary("Cómo leer el puntaje y qué fuentes aportaron"),
            html.P("Alertas de salud del equipo, seguridad, estado operacional y fluidos pueden aportar según su severidad: "
                   "baja 1, media 2, alta o crítica 3 puntos. Tribología aporta por condición del resultado. "
                   "Mantención y detención solo afectan el nivel con clasificación y severidad explícitas; "
                   "un reemplazo ejecutado puede cerrar condiciones anteriores del mismo componente."),
            html.P("Las alertas de conectividad, conducta y cumplimiento administrativo se excluyen. "
                   "Una muestra normal posterior cierra solo la condición de su compartimento. "
                   "La semana sin una nueva señal conserva las condiciones abiertas. El horómetro sirve para mostrar una tasa, no aumenta el nivel."),
            html.P(f"Alertas puntuadas: {classified.get('alerts_scored', '—')} · "
                   f"alertas del archivo sin aporte por alcance o severidad: {classified.get('alerts_not_scored', '—')} · "
                   f"señales de otras fuentes revisadas: {classified.get('other_source_signals', '—')}.",
                   className="small text-muted"),
        ], className="emin-beta-disclosure mb-3"),
        _condition_source_dates(model.get("source_dates"), date.fromisoformat(report["cutoff"]["cutoff"])),
        html.H6("Hallazgos graves nuevos o agravados esta semana"),
        html.P("Sin hallazgos graves nuevos registrados hasta el corte.", className="text-muted") if not urgent_rows else None,
        html.Ul([html.Li([_unit_link(row["unit"]), " · ",
                         html.Ul([_condition_evidence(entry) for entry in row["current"]["changes"]
                                  if entry["change"] in {"new", "worsened"} and entry["points"] == 3
                                  and entry.get("point_delta", 0) > 0])])
                 for row in urgent_rows[:3]], className="emin-beta-review-list") if urgent_rows else None,
        html.Details([
            html.Summary(f"Ver los {len(urgent_rows) - 3} hallazgos graves restantes"),
            html.Ul([html.Li([_unit_link(row["unit"]), " · ",
                             html.Ul([_condition_evidence(entry) for entry in row["current"]["changes"]
                                      if entry["change"] in {"new", "worsened"} and entry["points"] == 3
                                      and entry.get("point_delta", 0) > 0])])
                     for row in urgent_rows[3:]], className="emin-beta-review-list"),
        ], className="emin-beta-disclosure mb-3") if len(urgent_rows) > 3 else None,
        html.P(f"Nivel acumulado de la flota · {sum((row['current'] or {}).get('level') == 'critical' for row in model_rows)} críticos, "
               f"{sum((row['current'] or {}).get('level') == 'alert' for row in model_rows)} en alerta, "
               f"{sum((row['current'] or {}).get('level') == 'monitor' for row in model_rows)} en seguimiento, "
               f"{sum((row['current'] or {}).get('level') == 'clear' for row in model_rows)} sin hallazgos activos registrados."),
        html.Details([
            html.Summary("Ver otros cambios de condición de la semana"),
            html.Ul([html.Li([_unit_link(unit), " · ",
                             html.Ul([_condition_evidence(change) for change in rows_by_unit[unit]["current"]["changes"]])])
                     for unit in model["review_order"]
                     if not rows_by_unit[unit].get("urgent_week") and rows_by_unit[unit]["current"].get("changes")],
                    className="emin-beta-review-list"),
        ], className="emin-beta-disclosure mb-3"),
        html.Div([
            html.H6("Jackknife de criticidad"),
            html.P(f"Cada punto es un equipo. Las líneas marcan el umbral crítico de {model['threshold']} puntos. "
                   "El eje vertical resume el historial y el horizontal muestra el corte actual. "
                   "Estables y Críticos sostenidos quedan del mismo lado del umbral; Mejoraron y Empeoraron lo cruzan. "
                   "Una unidad con puntaje actual crítico, pero promedio histórico bajo el umbral, aparece en Empeoraron.",
                   className="small text-muted mb-2"),
            html.Dl([
                html.Div([html.Dt(zone_labels[key]),
                          html.Dd(sum(row["comparison"]["quadrant"] == key for row in comparable))],
                         className=f"emin-beta-stat emin-beta-{QUADRANT_STYLES[key][2]}")
                for key in ("healthy", "recent_improvement", "recent_worsening", "critical")
            ], className="emin-beta-stats"),
            html.Div(dbc.Checkbox(id="emin-beta-jackknife-show-names", label="Mostrar todos los nombres",
                                  value=False), className="emin-beta-label-toggle mb-2"),
            html.Div(_graph(candidate_plot), className="emin-beta-fleet-plot"),
        ], className="mt-3") if candidate_plot else None,
        dbc.Alert("Clasificación de mantenciones y detenciones no disponible en este corte.", color="warning")
        if "maintenance_classification" in model["provenance"]["coverage_limitations"] else None,

    ])


def fleet_intro(report):
    preview = _condition_cards(report)
    if preview is not None:
        return [preview, html.Details([html.Summary(_t("methodology")), dcc.Markdown(report["methodology"])])]
    zones = report["quadrants"]
    facts = _weekly_facts(report)
    ordered = report.get("weekly_review_order")
    if ordered is None:
        legacy = [row["unit"] for row in report["rows"] if row["unit"] in facts
                  and row["comparison"].get("quadrant") in {"critical", "recent_worsening"}]
        finding_units = [row["unit"] for row in report["rows"]
                         if row.get("scoring_review", {}).get("finding_id") is not None]
        ordered = list(dict.fromkeys(finding_units + sorted(legacy, key=lambda unit: not _urgent_fact(facts[unit]))))[:3]

    def review_cards(units):
        return html.Ul([
            html.Li([_unit_link(unit, facts[unit]), _fact_snippet(facts[unit])],
                    className="emin-beta-review-unit") for unit in units
        ], className="emin-beta-review-list")

    cutoff = date.fromisoformat(report["cutoff"]["cutoff"])
    monday = cutoff - timedelta(days=cutoff.weekday())
    summary = html.Dl([
        html.Div([
            html.Dt(f"{QUADRANTS.index(key) + 1} · {_t('quadrant_' + key)}"),
            html.Dd(zones["counts"][key]),
        ], className=f"emin-beta-stat emin-beta-{QUADRANT_STYLES[key][2]}")
        for key in ("critical", "recent_worsening", "recent_improvement", "healthy")
    ], className="emin-beta-stats")
    missing = {key: [] for key in ("previous", "current", "both")}
    for row in report["rows"]:
        gaps = row["comparison"]["missing"]
        if gaps:
            missing["both" if len(gaps) == 2 else gaps[0]].append(row["unit"])
    graph = fleet_figure(report, facts)
    coverage = report.get("scoring_coverage")
    return [
        _section(_t("week_review_title"), "fas fa-clipboard-check", [
            html.P(_t("week_review_note" if "weekly_review_order" in report else "week_review_legacy_note", start=_label_day(monday.isoformat()), end=_label_day(cutoff.isoformat())),
                   className="small text-muted mb-2"),
            review_cards(ordered[:3]) if ordered else html.P(_t("week_review_empty"), className="mb-0"),
            html.Details([
                html.Summary(_t("week_review_more", count=len(ordered) - 3), className="mb-2"),
                review_cards(ordered[3:]),
            ], className="mt-3") if len(ordered) > 3 else None,
        ]),
        _section(_t("fleet_title"), "fas fa-chart-area", [
            summary,
            html.P(_t("scoring_reference_note"), className="small text-muted mb-2")
            if report.get("scoring_review_version") == 1 else None,
            dbc.Alert(_t("coverage_fleet_summary", **coverage), color="light", className="small py-2 mb-2")
            if coverage is not None else None,
            html.Div([
                html.P(_t("compare_explanation", current_start=_label_day(monday.isoformat()),
                         current_end=_label_day(cutoff.isoformat()), historical_start=_label_day(report["start"]),
                         historical_end=_label_day((monday - timedelta(days=1)).isoformat())),
                       className="small text-muted mb-1"),
                html.P(_t("plot_row_note"), className="small text-muted mb-1"),
                html.Div(_graph(graph), className="emin-beta-fleet-plot"),
                html.P(className="emin-beta-plot-status small text-muted", role="status",
                       **{"data-missing-text": _t("plot_unit_filtered")}),
            ]) if graph is not None else None,
            dbc.Alert(_t("no_comparable"), color="light") if graph is None else None,
            html.Div([
                html.Strong(_t("insufficient")),
                html.Ul([
                    html.Li([html.Span(_t(f"missing_{key}") + " · ", className="fw-semibold"), ", ".join(units)])
                    for key, units in missing.items() if units
                ], className="mb-0 mt-1 ps-3"),
            ], className="emin-beta-coverage small") if any(missing.values()) else None,
            html.A(_t("see_fleet_table"), href="#emin-history-ranking-heading", className="d-inline-block mt-2"),
        ]),
        html.Details([
            html.Summary(_t("methodology")),
            html.P(_t("quadrant_threshold", value=_points(zones["threshold"])), className="small mt-3 mb-1")
            if zones["threshold"] is not None else None,
            dcc.Markdown(report["methodology"], className="emin-beta-method mt-3"),
        ], className="emin-beta-disclosure mb-3"),
    ]


def fleet_figure(report, facts=None):
    comparable = [row for row in report["rows"] if not row["comparison"]["missing"]]
    if not comparable:
        return None
    facts = facts or {}
    threshold = report["quadrants"]["threshold"]
    current_max = max(row["comparison"]["current_average"] for row in comparable)
    historical_max = max(row["comparison"]["previous_average"] for row in comparable)
    x_limit = max(3, max(current_max, threshold) * 1.10 + .25)
    y_limit = max(3, max(historical_max, threshold) * 1.10 + .25)
    condition_jackknife = report.get("condition_jackknife", False)
    if condition_jackknife:
        # Leave room for the upper quadrants even when every prior average is below the cutoff.
        x_limit = max(x_limit, threshold * 1.45)
        y_limit = max(y_limit, threshold * 1.45)
    figure = go.Figure()
    zone_bounds = ((0, threshold, 0, threshold), (0, threshold, threshold, y_limit),
                   (threshold, x_limit, threshold, y_limit), (threshold, x_limit, 0, threshold))
    markers = []
    zone_labels = report.get("zone_labels", {})
    for index, (key, (x0, x1, y0, y1)) in enumerate(zip(QUADRANTS, zone_bounds), 1):
        fill, color, _ = QUADRANT_STYLES[key]
        figure.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, layer="below",
                         line={"width": 0}, fillcolor=STATE_ZONE_FILL[fill])
        markers.append({"index": index, "label": zone_labels.get(key, _t(f"quadrant_short_{key}")), "color": color,
                        "x0": x0, "x1": x1, "y0": y0, "y1": y1})
    line = {"color": "#687386", "dash": "dot", "width": 1}
    figure.add_shape(type="line", x0=threshold, x1=threshold, y0=0, y1=y_limit, line=line, layer="below")
    figure.add_shape(type="line", x0=0, x1=x_limit, y0=threshold, y1=threshold, line=line, layer="below")

    for key in QUADRANTS:
        rows = [row for row in comparable if row["comparison"]["quadrant"] == key]
        comparisons = [row["comparison"] for row in rows]
        figure.add_trace(go.Scatter(
            x=[item["current_average"] for item in comparisons],
            y=[item["previous_average"] for item in comparisons], mode="markers",
            marker={"color": QUADRANT_STYLES[key][1],
                    "size": [12 if row.get("priority") == "high" else 6 if condition_jackknife else 9 for row in rows],
                    **({"opacity": [1 if row.get("priority") == "high" else .65 for row in rows]}
                       if condition_jackknife else {}),
                    "line": {"color": "white", "width": 1}},
            customdata=[
                [row["unit"], escape(_fact_body(fact)) if fact else _week_without_fact(item),
                 _label_day(fact["day"]) if fact else ""]
                for row, item in zip(rows, comparisons) for fact in [facts.get(row["unit"])]
            ],
            hovertemplate=("<b>%{customdata[0]}</b><br>" + zone_labels.get(key, _t(f"quadrant_{key}")) + "<br>"
                           + ("Corte actual: %{x:.1f} puntos<br>Promedio histórico: %{y:.1f} puntos<extra></extra>"
                            if condition_jackknife else "%{customdata[1]}<br>%{customdata[2]}<extra></extra>")),
            showlegend=False,
        ))

    labels = [{"unit": row["unit"], "x": row["comparison"]["current_average"],
               "y": row["comparison"]["previous_average"],
               "color": QUADRANT_STYLES[row["comparison"]["quadrant"]][1],
               "priority": row.get("priority") == "high"} for row in comparable]
    height = max(385, 16 * len(labels) + 78)
    apply_dashboard_theme(figure, title="", height=height)
    figure.update_layout(margin={"l": 45, "r": 14, "t": 12, "b": 58}, dragmode=False,
                         meta={"fleetLabels": labels, "xLimit": x_limit, "yLimit": y_limit, "zones": markers,
                               "labelTitle": _t("scatter_label_title"), "priorityLabelsOnly": condition_jackknife},
                         hoverlabel={"bgcolor": "white", "font": {"color": "#1f2937"}})
    figure.update_xaxes(range=[0, x_limit], title={"text": _t("axis_latest"), "font": {"size": 12}},
                        nticks=5, automargin=True, fixedrange=True)
    figure.update_yaxes(range=[0, y_limit], title={"text": _t("axis_baseline"), "font": {"size": 12}},
                        nticks=6, automargin=True, fixedrange=True)
    return figure


def _coverage_note(review):
    coverage = review.get("coverage")
    if not coverage:
        return None
    label = _t("coverage_" + coverage["state"])
    details = _t("verified_coverage", days=coverage["verified_current_days"], weeks=coverage["verified_prior_weeks"])
    comparison = (_t("verified_trend", movement=_movement(coverage["change"]),
                     previous=_points(coverage["previous_average"]), current=_points(coverage["current_average"]))
                  if coverage["state"] == "verified" and coverage.get("change") else None)
    return html.Small([f"{label} · {details}", html.Br() if comparison else None, comparison],
                      className="d-block text-muted")


def _condition_table(model_rows, selected_group=None):
    def group_scope(row):
        scopes = row.get("group_scopes", {})
        if selected_group not in (None, "__all__"):
            scope = scopes.get(selected_group)
            return {"esta semana": f"{selected_group} · esta semana",
                    "histórico": f"{selected_group} · solo histórico"}.get(
                        scope, f"{selected_group} · historial sin semana" if selected_group in row.get("groups", [])
                        else "Sin registros del grupo")
        current = sum(scope == "esta semana" for scope in scopes.values())
        historic = sum(scope == "histórico" for scope in scopes.values())
        without_week = sum(group not in scopes for group in row.get("groups", []))
        parts = []
        if current:
            parts.append(f"{current} grupos esta semana")
        if historic:
            parts.append(f"{historic} solo en histórico")
        if without_week:
            parts.append(f"{without_week} sin semana asignada")
        return " · ".join(parts) if parts else "Sin grupo con puntaje"

    return html.Div(dbc.Table([
            html.Thead(html.Tr([html.Th(label) for label in (
                "Puesto", "Equipo", "Grupo en el período", "Nivel actual", "Puntos", "Cambio semanal", "Principal aporte", "Promedio histórico", "Puntos nuevos / 100 h")])),
            html.Tbody([html.Tr([
                html.Td(row.get("rank", "—")),
                html.Th([_unit_link(row["unit"]),
                         html.Small(_t("priority_" + row["priority"]), className="d-block text-muted")
                         if row.get("priority") else None], scope="row"),
                html.Td(group_scope(row)),
                html.Td([
                    CONDITION_LABELS[current.get("level")],
                    html.Small("Sin señal nueva o agravada", className="d-block text-muted")
                    if current.get("level") == "critical" and not _new_condition(current) else None,
                ]),
                html.Td(_points(current.get("points"))),
                html.Td(_movement(current.get("movement", "insufficient"))),
                html.Td(_condition_label(max(
                    max(current["active"], key=lambda group: group["points"])["evidence"],
                    key=lambda entry: entry["points"],
                )) if current.get("active") else "—"),
                html.Td(_points(row["historical_points"])),
                html.Td(_points(current.get("rate")) if current.get("rate") is not None else "Tasa no disponible"),
            ], **{"data-emin-fleet-unit": row["unit"]}) for row in model_rows for current in [row["current"] or {}]]),
        ], striped=True, hover=True, size="sm"), className="emin-beta-table-scroll emin-beta-fleet-table")


def fleet_table(report, group):
    model = report.get("condition_model", {})
    if model.get("provenance", {}).get("preview"):
        eligible = {row["unit"] for row in report["rows"]
                    if group in ("__all__", None) or group in row["groups"]}
        selected = [row for row in model["rows"] if row["unit"] in eligible]
        if not selected:
            return dbc.Alert(_t("empty_filter"), color="light", class_name="mb-0")
        return _condition_table(selected, group)

    rows = [row for row in report["rows"] if group in ("__all__", None) or group in row["groups"]]
    if not rows:
        return dbc.Alert(_t("empty_filter"), color="light", class_name="mb-0")
    domains = report["domains"]
    facts = _weekly_facts(report)
    show_history = any("finding_history" in row.get("scoring_review", {}) for row in rows)
    headers = [_t("rank"), _t("team"), _t("weekly_record"), _t("movement"),
               *([_t("finding_history_header")] if show_history else []), _t("historical_points"), _t("baseline"),
               _t("latest_week"), _t("delta"), *domains]
    body = []
    for row in rows:
        status = row["comparison"]
        priority = row.get("priority")
        review = row.get("scoring_review", {})
        unit_view = report["units"].get(row["unit"], {})
        group_weeks = unit_view.get("group_weeks")
        fact = facts.get(row["unit"])
        scope = None
        if group not in ("__all__", None) and group_weeks is not None:
            weeks = group_weeks.get(group, [])
            scope = (_t("group_result_current") if report["cutoff"]["week"] in weeks
                     else _t("group_result_history") if weeks else _t("group_result_record_only"))
        current_group_records = unit_view.get("current_group_records")
        if group not in ("__all__", None) and current_group_records is not None:
            index = current_group_records.get(group)
            fact = next((record for record in unit_view["records"] if record["id"] == index), None) if index is not None else None
        link = _unit_link(row["unit"], fact)
        history = review.get("finding_history")
        history_cell = html.Div([
            html.Strong(history["weeks"]),
            html.Small(_t("finding_history_latest", week=history["latest_week"]), className="d-block text-muted")
            if history["latest_week"] else html.Small(_t("finding_history_empty"), className="d-block text-muted"),
        ], title=_t("finding_history_breakdown", oil=history["oil_weeks"], safety=history["safety_weeks"],
                    both=history["both_weeks"])) if history else "—"
        score = _points(row["points"]) if row["points"] is not None else _t("no_data")
        values = [
            row["rank"] or "—",
            html.Div([link, html.Small(_t(f"priority_{priority}"), className="d-block text-muted") if priority else None,
                      html.Small(scope, className="d-block text-muted") if scope and fact else None]),
            _fact_snippet(fact) if fact else html.Small(scope or _week_without_fact(status), className="text-muted"),
            html.Div([
                html.Span(_movement(status["status"]), className=f"emin-beta-{status['status']} fw-semibold"),
                html.Small(_t("signal_" + review["level"]), className="d-block") if review.get("level") else None,
                _coverage_note(review),
            ]),
            *([history_cell] if show_history else []),
            html.Div([html.Strong(score), html.Small(_t("weeks", count=row["observed_weeks"]),
                                                   className="d-block text-muted") if row["observed_weeks"] else None]),
            _points(status["previous_average"]), _points(status["current_average"]),
            _delta(status["delta"]),
            *[_points(row["domains"].get(domain, 0)) if row["points"] is not None else "—" for domain in domains],
        ]
        body.append(html.Tr([html.Th(value, scope="row") if index == 1 else html.Td(value)
                             for index, value in enumerate(values)],
                            className=f"emin-beta-priority-{priority}" if priority else "",
                            **{"data-emin-fleet-unit": row["unit"]}))
    return html.Div([
        html.P(_t("fleet_matches", count=len(rows), total=len(report["rows"])), className="small text-muted mb-2"),
        html.Div(dbc.Table([
            html.Thead(html.Tr([html.Th(label, scope="col") for label in headers])),
            html.Tbody(body),
        ], striped=True, hover=True, size="sm", class_name="emin-beta-table align-middle mb-0"),
            role="region", tabIndex=0, className="emin-beta-table-scroll emin-beta-fleet-table",
            **{"aria-label": _t("fleet_table")}),
    ])


def _history_axis(figure, report):
    start = date.fromisoformat(report["start"])
    end = date.fromisoformat(report["cutoff"]["cutoff"])
    start -= timedelta(days=start.weekday())
    step = max(1, ((end - start).days // 7 + 11) // 12)
    ticks = [start + timedelta(weeks=index) for index in range(0, (end - start).days // 7 + 1, step)]
    figure.update_xaxes(type="date", range=[start - timedelta(days=3), end + timedelta(days=4)],
                        tickmode="array", tickvals=ticks,
                        ticktext=[day.strftime("%d/%m/%y") for day in ticks],
                        tickangle=-35, automargin=True, title_text=_t("axis_weeks"), hoverformat="%d/%m/%Y")


def _timeline_figure(view, report, records, unit=None):
    figure = go.Figure()
    for category in CATEGORIES[:-1]:
        items = [item for item in view["timeline"] if item["category"] == category]
        if not items:
            continue
        category_label = _t(f"category_{category}")
        figure.add_trace(go.Scatter(
            x=[item["week_start"] for item in items], y=[category_label for item in items],
            mode="markers", name=category_label,
            marker={"color": [OIL_COLORS[item["state"]] if category == "oil" else CATEGORY_COLORS[category]
                              for item in items],
                    "size": [min(19, 7 + item["count"] ** .5) for item in items],
                    "symbol": ["diamond-open" if item["state"] == "indication" else "circle" for item in items]},
            customdata=[[item["week"], item["count"], _t(f"state_{item['state']}"),
                         "<br>".join(escape(_description(records[index])) for index in item["example_ids"]), unit]
                        for item in items],
            hovertemplate="<b>%{x|%d/%m/%Y}</b> · %{customdata[2]} · %{customdata[1]}<br>%{customdata[3]}<extra></extra>",
        ))
    apply_dashboard_theme(figure, title="", height=315)
    figure.update_layout(margin={"l": 105, "r": 18, "t": 12, "b": 70})
    figure.update_yaxes(categoryorder="array", categoryarray=[_t(f"category_{category}") for category in reversed(CATEGORIES[:-1])],
                        automargin=True)
    _history_axis(figure, report)
    return figure


def _oil_figure(view, report, unit=None):
    figure = go.Figure()
    by_series = {}
    for item in view["oil"]:
        by_series.setdefault((item["state"], item["component"]), []).append(item)
    for (state, component), rows in by_series.items():
        label = _t(f"state_{state}")
        component = escape(component or _t("unknown_component"))
        figure.add_trace(go.Scatter(
            x=[item["week_start"] for item in rows],
            y=[label] * len(rows), mode="markers", name=label,
            marker={"color": OIL_COLORS[state], "size": [min(20, 8 + item["count"] * 2) for item in rows]},
            customdata=[[item["week"], item["count"], unit] for item in rows],
            hovertemplate=component + " · %{customdata[1]}<extra>" + label + "</extra>",
        ))
    apply_dashboard_theme(figure, title="", height=280)
    figure.update_layout(margin={"l": 95, "r": 18, "t": 12, "b": 70}, hovermode="x unified")
    figure.update_yaxes(categoryorder="array", categoryarray=[_t(f"state_{state}") for state in reversed(OIL_STATES)],
                        automargin=True)
    _history_axis(figure, report)
    return figure


def _score_details(drivers, records):
    if not drivers:
        return None
    items = []
    for item in drivers:
        record = records.get(item["example_id"])
        items.append(html.Li([
            html.Strong(_t("driver_points", domain=item["domain"], points=_points(item["points"]))),
            html.Small([_label_day(record["day"]), " · ", _fact_body(record), " · ", _record_reference(record)],
                       className="d-block text-muted") if record else None,
        ]))
    return html.Details([
        html.Summary(_t("drivers_title")),
        html.P(_t("drivers_note"), className="small text-muted mt-2 mb-1"),
        html.Ul(items, className="mb-0"),
    ], className="emin-beta-disclosure mt-3")


def unit_story(report, unit, focus=None):
    view = report["units"].get(unit)
    if view is None:
        return dbc.Alert(_t("select_team"), color="light"), None, None
    records = {item["id"]: item for item in view["records"]}
    model = report.get("condition_model", {})
    condition_row = next((row for row in model.get("rows", []) if row["unit"] == unit), {})
    condition = condition_row.get("current") if model.get("provenance", {}).get("preview") else None
    condition_changes = [week for week in reversed(condition_row.get("weeks", [])) if week["changes"]][:3]
    focus_id = focus.get("record") if isinstance(focus, dict) and focus.get("unit") == unit else None
    focus = records.get(focus_id) if isinstance(focus_id, int) else None
    highlighted = None
    if focus:
        record = focus
        category = record["category"]
        highlighted = html.Li([
            html.Small(_t("opened_record"), className="d-block fw-semibold text-primary mb-1"),
            html.Div([html.Strong(_fact_title(record)), html.Span(_label_day(record["day"]), className="small text-muted")],
                     className="d-flex justify-content-between gap-2"),
            html.Div(_fact_body(record)),
            html.Small(_state(record), className="d-block") if record["state"] != "recorded" else None,
            html.Small(_record_reference(record), className="text-muted"),
        ], style={"borderInlineStartColor": OIL_COLORS.get(record["state"], CATEGORY_COLORS[category])},
            className="emin-beta-selected-record")
    recurrence = []
    group_weeks = view.get("group_weeks", {})
    for group, weeks in sorted(group_weeks.items(), key=lambda item: (-len(item[1]), item[0]))[:3]:
        if len(weeks) < 2:
            continue
        intervention = records.get(view.get("recurring_interventions", {}).get(group))
        recurrence.append(html.Li([
            _t("recurring_group", group=group, count=len(weeks), latest=weeks[-1]),
            html.Small(_t("intervention_between", date=_label_day(intervention["day"]),
                          source=_record_reference(intervention)), className="d-block text-muted")
            if intervention else None,
        ]))
    return (
        _section(_t("unit_summary", unit=unit), "fas fa-clipboard-list", [
            html.P(_t("unit_coverage", start=_label_day(view["records"][-1]["day"]),
                      end=_label_day(view["records"][0]["day"])), className="small text-muted mb-2")
            if view["records"] else None,
            html.Ul([highlighted], className="emin-beta-facts") if highlighted else None,
            html.Div([
                html.Strong(_t("recurring_groups")),
                html.Ul(recurrence, className="mb-1"),
            ], className="mt-2") if recurrence else None,
            html.Nav([
                html.A(_t("jump_milestones"), href="#emin-beta-milestones-heading"),
                html.A(_t("jump_oil"), href="#emin-beta-oil-heading"),
            ], className="emin-beta-quick-links mt-3", **{"aria-label": _t("unit_quick_links")}),
            _condition_source_dates(condition_row.get("source_dates"), date.fromisoformat(report["cutoff"]["cutoff"]))
            if model.get("provenance", {}).get("preview") else None,
            html.Details([
                html.Summary(f"Condición actual · {CONDITION_LABELS[condition['level']]}"),
                html.P(f"Nivel mantenido desde {condition['since']}") if condition["since"] else None,
                html.P([html.Strong("Semana de corte · "), _condition_week_points(condition)], className="mb-2"),
                _condition_breakdown(condition),
                html.H6("Cambios recientes del puntaje") if condition_changes else None,
                html.Ul([html.Li([
                    html.Strong(f"{week['week']} · {_condition_week_points(week)}"),
                    html.Ul([_condition_evidence(entry) for entry in week["changes"]]),
                ]) for week in condition_changes]) if condition_changes else None,
            ], className="emin-beta-disclosure mt-3") if condition else None,
            _score_details(view.get("score_drivers"), records),
        ]),
        [
            html.P(_t("timeline_note"), className="small text-muted mb-1"),
            _graph(_timeline_figure(view, report, records, unit), "emin-beta-milestones-chart") if view["timeline"] else html.P(_t("no_milestones"), className="mb-0"),
        ],
        [
            html.P(_t("oil_note"), className="small text-muted mb-1"),
            _graph(_oil_figure(view, report, unit), "emin-beta-oil-chart") if view["oil"] else html.P(_t("no_oil"), className="mb-0"),
        ],
    )


def evidence_page(report, unit, category, query, requested_page):
    selected = report["units"].get(unit, {}).get("records", [])
    needle = (query or "").strip().casefold()
    matches = [item for item in selected
               if (category in (None, "__all__") or category == item["category"]
                   or (category == "abnormal_oil" and item["category"] == "oil" and item["state"] == "abnormal"))
               and (not needle or needle in " ".join(str(item.get(key) or "") for key in
                                                     ("day", "week", "component", "description", "reference", "severity")).casefold())]
    columns = ("date", "evidence_type", "component", "condition", "description", "reference")
    return _evidence_rows(matches, columns, "records", requested_page)


def unit_record_weeks(report, unit, table):
    series = report["units"].get(unit, {}).get("oil" if table == "oil" else "timeline", [])
    return sorted({(item["week"], item["week_start"]) for item in series}, reverse=True)


def unit_records_page(report, unit, table, red_only, page, week=None):
    view = report["units"].get(unit, {})
    evidence = view.get("records", [])
    if week:
        evidence = [record for record in evidence if record.get("week") == week]
    if table == "oil":
        rows = [row for row in evidence if row["category"] == "oil" and (not red_only or row["state"] == "abnormal")]
        columns = ("date", "compartment", "condition", "anomaly", "reference")
        return _evidence_rows(rows, columns, "oil_table", page, empty="no_red_oil" if red_only else "no_oil")
    milestones = set(view.get("milestone_ids", []))
    rows = [row for row in evidence if row["id"] in milestones]
    columns = ("date", "evidence_type", "component", "condition", "description", "reference")
    return _evidence_rows(rows, columns, "milestone_table", page, empty="no_milestone_records")


def _evidence_rows(matches, columns, title, requested_page, *, empty="no_records"):
    if not matches:
        return dbc.Alert(_t(empty), color="light"), 0, True, True
    last = (len(matches) - 1) // PAGE_SIZE
    page = max(0, min(requested_page or 0, last))
    offset = page * PAGE_SIZE
    headers = [_t(key) for key in columns]
    rows = []
    for item in matches[offset:offset + PAGE_SIZE]:
        condition = _state(item)
        if item["state"] == "abnormal":
            condition = html.Span(condition, className="emin-beta-worsened fw-semibold")
        if item.get("corrected_from"):
            condition = html.Div([condition, html.Small(_t("date_corrected"), className="d-block text-muted")])
        values = {
            "date": _label_day(item["day"]), "evidence_type": _t(f"category_{item['category']}"),
            "component": item["component"] or "—", "compartment": item["component"] or _t("unknown_component"),
            "condition": condition, "description": _description(item), "anomaly": item["description"] or "—",
            "reference": _record_reference(item),
        }
        rows.append(html.Tr([html.Td(values[key]) for key in columns], className=
                            "emin-beta-record-abnormal" if item["state"] in {"critical", "abnormal"} else ""))
    content = [
        html.P(_t("records_showing", start=offset + 1, end=min(offset + PAGE_SIZE, len(matches)), total=len(matches)),
               className="small text-muted mb-2", role="status"),
        html.Div(dbc.Table([
            html.Thead(html.Tr([html.Th(label, scope="col") for label in headers])),
            html.Tbody(rows),
        ], striped=True, size="sm", class_name="emin-beta-table emin-beta-evidence-table mb-0"),
            className="emin-beta-table-scroll", role="region", tabIndex=0, **{"aria-label": _t(title)}),
    ]
    return content, page, page == 0, page == last
