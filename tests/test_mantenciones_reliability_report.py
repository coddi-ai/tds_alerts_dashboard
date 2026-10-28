"""Informe de Confiabilidad redesign: filters, KPI treatment, layout and charts."""

from types import SimpleNamespace

import pandas as pd
import pytest

from dashboard.callbacks import mantenciones_general_callbacks as callbacks
from dashboard.tabs.tab_mantenciones_general import (
    JUMP_NAV_SECTIONS,
    create_kpi_card,
    layout_mantenciones_general,
    percent_value,
)


def _handlers():
    handlers = {}

    class App:
        def callback(self, *args, **kwargs):
            def capture(function):
                handlers[function.__name__] = function
                return function
            return capture

    callbacks.register_mantenciones_general_callbacks(App())
    return handlers


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None and not isinstance(children, str):
        yield from _walk(children)


def _by_id(component, wanted):
    return next(item for item in _walk(component) if getattr(item, "id", None) == wanted)


# ---- 1 / 2: Refrescar keeps the selection; Sistema control -------------------------


class _Repo:
    def __init__(self):
        self.refreshed = False

    def refresh(self):
        self.refreshed = True

    def get_available_months(self):
        return ["2026-01", "2026-02", "2026-03"]

    def get_available_weeks(self):
        return []

    def get_monthly_payload(self, month):
        return {"meta": {"client": "EMIN", "pareto": {"available_systems": ["A", "B", "C"]}}}

    def get_available_equipment(self, **kwargs):
        return ["T_01"]

    def get_available_fleets(self):
        return ["Camiones", "Palas"]

    def get_available_systems(self):
        return ["A", "B", "C"]

    def get_available_subsystems(self):
        return []


def test_refrescar_requeries_without_moving_the_filter_selection(monkeypatch):
    repo = _Repo()
    monkeypatch.setattr(callbacks, "get_repository", lambda **kwargs: repo)
    monkeypatch.setattr(callbacks, "ctx", SimpleNamespace(triggered_id="btn-refresh-maintenance"))
    result = _handlers()["load_maintenance_metadata"]("EMIN", 1, "2026-01", ["Palas", "Gone"], ["A", "C", "Gone"])

    assert repo.refreshed is True
    assert result[2] == "2026-01"
    assert result[4] == ["Palas"]
    assert result[10] == ["A", "C"]


def test_changing_client_still_resets_to_the_latest_month_and_all_systems(monkeypatch):
    monkeypatch.setattr(callbacks, "get_repository", lambda **kwargs: _Repo())
    monkeypatch.setattr(callbacks, "ctx", SimpleNamespace(triggered_id="client-selector"))
    result = _handlers()["load_maintenance_metadata"]("EMIN", None, "2026-01", ["Palas"], ["A"])

    assert result[2] == "2026-03"
    assert result[4] == []
    assert result[10] == ["A", "B", "C"]


@pytest.mark.parametrize(
    "selected, expected",
    [
        ([], "Ningún sistema seleccionado"),
        (None, "Ningún sistema seleccionado"),
        (["A", "B", "C"], "Todos los sistemas"),
        (["A"], "1 seleccionados"),
        (["A", "B"], "2 seleccionados"),
    ],
)
def test_systems_summary_covers_none_partial_and_all(selected, expected):
    assert callbacks.systems_summary_label(selected, ["A", "B", "C"]) == expected


def test_systems_control_keeps_the_checklist_id_and_offers_all_or_none(monkeypatch):
    layout = layout_mantenciones_general()
    checklist = _by_id(layout, "maintenance-summary-systems")
    assert type(checklist).__name__ == "Checklist"
    handlers = _handlers()
    options = [{"label": "A", "value": "A"}, {"label": "B", "value": "B"}]
    monkeypatch.setattr(callbacks, "ctx", SimpleNamespace(triggered_id="maintenance-systems-none"))
    assert handlers["set_all_or_no_systems"](0, 1, options) == []
    monkeypatch.setattr(callbacks, "ctx", SimpleNamespace(triggered_id="maintenance-systems-all"))
    assert handlers["set_all_or_no_systems"](1, 0, options) == ["A", "B"]
    assert handlers["update_systems_summary"]([], options) == "Ningún sistema seleccionado"


def test_deselecting_every_system_renders_an_explicit_empty_report(monkeypatch):
    class Boom:
        def get_monthly_payload(self, *args, **kwargs):
            raise AssertionError("no query when no system is selected")

    monkeypatch.setattr(callbacks, "get_repository", lambda **kwargs: Boom())
    handlers = _handlers()
    payload, _ = handlers["load_monthly_payload"](
        "EMIN", "2026-01", [], "__all__", [], None, {"client": "EMIN"},
    )
    assert payload["meta"]["no_systems_selected"] is True

    rendered = handlers["render_monthly_payload"](payload)
    assert "Selecciona al menos un sistema" in str(rendered[10])
    assert rendered[0] == rendered[1] == "—"


def test_unset_system_selection_before_metadata_is_not_treated_as_none(monkeypatch):
    seen = {}

    class Repo:
        def get_monthly_payload(self, month, **kwargs):
            seen["systems"] = kwargs["systems"]
            return {"status": "ok"}

    monkeypatch.setattr(callbacks, "get_repository", lambda **kwargs: Repo())
    _handlers()["load_monthly_payload"](
        "EMIN", "2026-01", [], "__all__", [], None, {},
    )
    assert seen["systems"] == []


# ---- 3: jump navigation ---------------------------------------------------------------


def test_jump_nav_links_every_section_and_the_duplicate_tab_bar_is_hidden():
    layout = layout_mantenciones_general()
    links = [item for item in _walk(layout) if getattr(item, "className", None) == "maintenance-jump-link"]
    assert [link.children for link in links] == [
        "Resumen", "Actividad", "Pareto", "Indicadores", "Navegación por Unidad", "Detalle de Actividades",
    ]
    for (key, _label), link in zip(JUMP_NAV_SECTIONS, links):
        assert link.href == f"#maintenance-section-{key}"
        assert _by_id(layout, f"maintenance-section-{key}") is not None

    tabs = _by_id(layout, "maintenance-tabs")
    assert tabs.className == "maintenance-tabs__strip"
    css = open("dashboard/assets/maintenance_report.css", encoding="utf-8").read()
    assert ".maintenance-tabs__strip" in css and "display: none" in css


# ---- 4 / 8: neutral KPI treatment, severity only where a target is confirmed -------------


def test_kpi_icons_share_one_neutral_treatment():
    layout = layout_mantenciones_general()
    icons = [
        item for item in _walk(layout)
        if "maintenance-icon" in str(getattr(item, "className", ""))
        and getattr(item, "role", None) == "img"
    ]
    assert len(icons) == 10
    for icon in icons:
        assert "maintenance-icon--neutral" in icon.className
        assert "text-" not in icon.className.replace("text-muted", "")


def test_methodology_lives_in_tooltips_on_disponibilidad_and_downtime_only():
    layout = layout_mantenciones_general()
    tooltips = [item for item in _walk(layout) if type(item).__name__ == "Tooltip"]
    assert sorted(tooltip.target for tooltip in tooltips) == [
        "maintenance-kpi-availability-est-info",
        "maintenance-kpi-downtime-est-info",
    ]
    assert all("no confirma una detención operacional" in tooltip.children for tooltip in tooltips)
    assert "maintenance-kpi-mtbf-est-info" not in str(layout)
    assert create_kpi_card("MTBF", component_id="x").children.children.children[0].children == "MTBF"


def test_availability_stays_neutral_until_a_target_is_confirmed(monkeypatch):
    assert callbacks.availability_status(97.0, "EMIN") is None
    monkeypatch.setitem(callbacks.AVAILABILITY_TARGET_PCT_BY_CLIENT, "EMIN", 95.0)
    met = callbacks.availability_status(96.0, "emin")
    below = callbacks.availability_status(90.0, "EMIN")
    assert "maintenance-status-dot--ok" in met[0].className and "Cumple" in met[1].children
    assert "maintenance-status-dot--below" in below[0].className and "Bajo" in below[1].children
    assert callbacks.availability_status(None, "EMIN") is None


def test_motor_share_is_marked_as_a_percentage_without_a_colour():
    value = percent_value(12.34)
    assert value[0] == "12.3" and value[1].children == "%"
    assert percent_value(None) == "—"


# ---- 5: 2x2 chart grid ------------------------------------------------------------------


def test_activity_charts_form_a_two_by_two_grid_that_stacks_on_narrow_screens():
    layout = layout_mantenciones_general()
    grid = next(item for item in _walk(layout) if getattr(item, "className", "") and "maintenance-chart-grid" in item.className)
    graph_ids = [
        next(inner.id for inner in _walk(card) if type(inner).__name__ == "Graph")
        for card in grid.children
    ]
    assert graph_ids == [
        "maintenance-chart-daily",
        "maintenance-chart-daily-equipment",
        "maintenance-chart-system-mix",
        "maintenance-chart-equipment",
    ]
    css = open("dashboard/assets/maintenance_report.css", encoding="utf-8").read()
    assert "repeat(2, minmax(0, 1fr))" in css
    assert "max-width: 991.98px" in css


# ---- 6: Equipos con Mayor Actividad expand / collapse --------------------------------------


def _activity_payload(units):
    payload = callbacks._empty_contract()
    payload["status"] = "ok"
    payload["meta"].update({"client": "EMIN", "period": "2026-01"})
    payload["data"]["equipment_system_mix"] = [
        {"machine_code": f"EQ-{i:02d}", "system_name": system, "count": 50 - i}
        for i in range(units)
        for system in ("Sistema de Motor", "Sistema Hidráulico")
    ]
    return payload


def test_equipment_toggle_reports_the_real_remaining_count_and_expands_in_place():
    handlers = _handlers()
    payload = _activity_payload(20)

    rendered = handlers["render_monthly_payload"](payload, False)
    assert len(rendered[16].data[0].y) == 8
    assert rendered[27] == "Mostrar 12 equipos adicionales"
    assert rendered[28] is False

    expanded, figure, label, style = handlers["toggle_equipment_view"](1, False, payload)
    assert expanded is True
    assert len(figure.data[0].y) == 20
    assert label == "Mostrar menos equipos"
    assert int(style["height"][:-2]) > 340

    collapsed, figure, label, _ = handlers["toggle_equipment_view"](2, True, payload)
    assert collapsed is False and len(figure.data[0].y) == 8
    assert label == "Mostrar 12 equipos adicionales"


def test_equipment_toggle_is_hidden_at_or_below_eight_units_and_singular_for_one():
    handlers = _handlers()
    for units in (3, 8):
        rendered = handlers["render_monthly_payload"](_activity_payload(units), False)
        assert rendered[28] is True and rendered[27] == ""
    assert handlers["render_monthly_payload"](_activity_payload(9), False)[27] == "Mostrar 1 equipo adicional"


def test_every_client_gets_the_top_eight_cap_and_toggle():
    for client in ("CDA", "CAPSTONE"):
        payload = _activity_payload(20)
        payload["meta"]["client"] = client
        rendered = _handlers()["render_monthly_payload"](payload, False)
        figure = rendered[16]
        assert len({x for trace in figure.data for x in trace.x}) == 8
        assert rendered[27] == "Mostrar 12 equipos adicionales"
        assert rendered[28] is False
        _, expanded, _, _ = _handlers()["toggle_equipment_view"](1, False, payload)
        assert len({x for trace in expanded.data for x in trace.x}) == 20


# ---- 7: Pareto scope statement ---------------------------------------------------------------


def test_actions_pareto_states_its_system_filter_scope():
    handlers = _handlers()
    payload = _activity_payload(3)
    payload["meta"]["pareto"] = {
        "available_systems": ["Sistema de Motor", "Sistema Hidráulico"],
        "selected_systems": ["Sistema de Motor"],
        "hours_available": True,
        "system_filter_partial": True,
    }
    partial = str(handlers["render_monthly_payload"](payload)[22])
    assert "Las acciones se filtran por los sistemas seleccionados" in partial
    assert "solo está disponible con todos los sistemas" in partial

    payload["meta"]["pareto"]["system_filter_partial"] = False
    assert "todos los sistemas" in str(handlers["render_monthly_payload"](payload)[22])


# ---- 9: Días desde mantención --------------------------------------------------------------------


def test_days_since_maintenance_uses_one_decimal_in_table_and_detail_panel():
    layout = layout_mantenciones_general()
    table = _by_id(layout, "maintenance-unit-navigation-table")
    column = next(item for item in table.columns if item["id"] == "days_since_last_maintenance")
    assert column["type"] == "numeric"
    assert column["format"].to_plotly_json()["specifier"] == ".1f"

    rows = callbacks._unit_status_rows([
        {"equipment": "T_01", "days_since_last_maintenance": "3"},
        {"equipment": "T_02", "days_since_last_maintenance": 4.25},
        {"equipment": "T_03", "days_since_last_maintenance": None},
    ])
    assert [row["days_since_last_maintenance"] for row in rows] == [3.0, 4.25, None]

    payload = callbacks._empty_contract()
    payload["meta"]["client"] = "CDA"
    payload["data"]["unit_status"] = [{"equipment": "T_01", "days_since_last_maintenance": 3}]
    panel = str(_handlers()["render_unit_detail"](payload, "T_01"))
    assert "3.0" in panel
    assert callbacks._format_days(None) == "Sin dato"


# ---- 11: charts are read-only -----------------------------------------------------------------------


def test_no_chart_on_the_page_feeds_a_filter_callback():
    from dashboard.callbacks.mantenciones_general_callbacks import register_mantenciones_general_callbacks
    import dash

    app = dash.Dash(__name__)
    app.layout = layout_mantenciones_general()
    register_mantenciones_general_callbacks(app)
    graph_ids = {item.id for item in _walk(app.layout) if type(item).__name__ == "Graph"}
    for entry in app.callback_map.values():
        for dependency in entry["inputs"]:
            assert not (dependency["id"] in graph_ids), dependency


# ---- Release blocker: no diagnostic text on the page ---------------------------------------

_DEBUG_FRAGMENTS = (
    "query", "parquet", "fallback", "ilustrativ", "tribolog", "sin coincidencia",
    "cobertura de fuente", "concilia", "no se truncaron", "filas válidas", "baja confianza",
    "no es estado de hoy",
)


def _visible_text(component):
    parts = []
    for item in _walk(component):
        children = getattr(item, "children", None)
        if isinstance(children, str):
            parts.append(children)
    return " ".join(parts)


def _diagnostic_payload(client):
    payload = callbacks._empty_contract()
    payload["status"] = "ok"
    payload["meta"].update({
        "client": client,
        "period_label": "2026-01",
        "is_current_period": False,
        "estimated_kpis": {
            "status": "unavailable",
            "reason": "query_4 rechazado por plausibilidad (valores ilustrativos)",
            "coverage": {"partial_month": True, "observed_days": 10, "calendar_days": 31,
                         "reference_date": "2026-01-10", "long_records": 3},
            "reconciliation": {"status": "mismatch", "max_delta_hours": 4.2},
        },
        "reliability_kpis": {"rows": 3, "valid_mtbf_rows": 3, "valid_mttr_rows": 3, "low_confidence_rows": 1},
    })
    payload["data"]["unit_status"] = [{"equipment": "T_01", "days_since_last_maintenance": 2}]
    return payload


@pytest.mark.parametrize("client", ["CDA", "CAPSTONE", "EMIN"])
def test_no_diagnostic_text_reaches_the_rendered_page(client):
    handlers = _handlers()
    rendered = handlers["render_monthly_payload"](_diagnostic_payload(client), False)
    visible = (_visible_text(rendered[10]) + " " + str(rendered[22]) + " " + str(rendered[25])).lower()
    visible += " " + _visible_text(handlers["render_unit_detail"](_diagnostic_payload(client), "T_01")).lower()
    visible += " " + _visible_text(layout_mantenciones_general()).lower()
    for fragment in _DEBUG_FRAGMENTS:
        assert fragment not in visible, fragment


def test_errors_show_a_generic_message_and_keep_the_exception_in_the_log(monkeypatch, caplog):
    def boom(**kwargs):
        raise RuntimeError("secret /srv/data/query_3.parquet missing")

    monkeypatch.setattr(callbacks, "get_repository", boom)
    handlers = _handlers()
    with caplog.at_level("ERROR"):
        result = handlers["load_maintenance_metadata"]("CDA", None)
        payload, _ = handlers["load_monthly_payload"]("CDA", "2026-01", [], "__all__", [], None, {})
    assert "query_3" not in str(result)
    rendered = handlers["render_monthly_payload"](payload, False)
    assert "query_3" not in str(rendered[10]) and "No se dispone" in str(rendered[10])
    assert "query_3.parquet" in caplog.text


# ---- Mix de Actividad por Sistema -----------------------------------------------------------------


def test_system_mix_drops_zero_systems_and_keeps_small_counts_visible():
    from dashboard.tabs.tab_mantenciones_general import create_system_activity_chart

    rows = pd.DataFrame([
        {"system_name": "Sistema de Motor", "count": 44},
        {"system_name": "Sistema Hidráulico", "count": 1},
        {"system_name": "Tren de Fuerza", "count": 0},
        {"system_name": "Sistema de Frenado", "count": 0},
    ])
    figure = create_system_activity_chart(rows)
    bar = figure.data[0]
    assert list(bar.x) == ["Sistema de Motor", "Sistema Hidráulico"]
    assert list(bar.text) == [44, 1]
    assert list(bar.customdata) == [44, 1]
    assert bar.y[1] >= 44 * 0.03 > 1
    assert create_system_activity_chart(rows[rows["count"] == 0]).layout.annotations


# ---- Translation coverage (Spanish / English) -----------------------------------------------------

_KEY_PATTERN = __import__("re").compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_SPANISH_TEXT = __import__("re").compile(
    r"[áéíóúñ¿¡]|\b(de|del|por|los|las|para|sin|con|todos|todas|equipos?|acciones|horas|selecciona|mostrar|"
    r"unidad|estado|d[ií]as?|fecha|actividad\w*|disponibilidad|informe|resumen|detalle|otras?|mes|flota|"
    r"acumulado|intervenid\w+|mayor|menos|adicional\w*|ning[uú]n)\b",
    __import__("re").I,
)
# Names that come from the source data (systems, component names) are never translated.
_DATA_VALUES = {"Sistema de Motor", "Sistema Hidráulico", "Tren de Fuerza", "Bomba", "OPERATIVO", "Cambio"}
_SKIP_PROPS = {
    "id", "className", "style", "href", "target", "role", "n_clicks", "data", "value", "selected_rows", "page_size",
    "sort_action", "filter_action", "style_table", "style_cell", "style_header", "style_data_conditional",
    "row_selectable", "hidden", "tabIndex", "htmlFor", "inputClassName", "labelClassName", "multi", "clearable",
    "searchable", "placement", "trigger", "type", "md", "xs", "size", "color", "is_open", "inline", "disabled",
    "figure", "config", "format",
}


def _strings(obj, found):
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _strings(item, found)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if key not in _SKIP_PROPS:
                _strings(value, found)
    elif hasattr(obj, "to_plotly_json"):
        payload = obj.to_plotly_json()
        if "layout" in payload and "data" in payload:
            _figure_strings(payload, found)
            return
        for key, value in payload.get("props", payload).items():
            if key == "columns":
                found.extend(str(column.get("name")) for column in value)
            elif key not in _SKIP_PROPS:
                _strings(value, found)


def _figure_strings(figure, found):
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"text", "name", "hovertemplate", "title"} and isinstance(value, str):
                    found.append(value)
                else:
                    walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(figure.get("layout", {}))
    for trace in figure.get("data", []):
        for key in ("name", "hovertemplate"):
            if isinstance(trace.get(key), str):
                found.append(trace[key])
        found.extend(v for v in (trace.get("customdata") or []) if isinstance(v, str) and v.strip())
        found.extend(v for v in list(trace.get("x") if trace.get("x") is not None else []) if isinstance(v, str))


def _report_strings(language):
    from flask import Flask
    from src.i18n import LANGUAGE_COOKIE

    app = Flask(__name__)
    found = []
    with app.test_request_context("/", headers={"Cookie": f"{LANGUAGE_COOKIE}={language}"}):
        handlers = _handlers()
        _strings(layout_mantenciones_general(), found)
        for partial in (False, True):
            payload = _activity_payload(12)
            payload["meta"].update({"filter_systems": ["Sistema de Motor", "Equipo"], "pareto": {
                "available_systems": ["Sistema de Motor", "Equipo"], "hours_available": True, "system_filter_partial": partial,
                "selected_systems": ["Sistema de Motor"] if partial else ["Sistema de Motor", "Equipo"]}})
            payload["data"]["action_systems"] = [
                {"equipment": r["machine_code"], "system_name": r["system_name"], "count": r["count"]}
                for r in payload["data"]["equipment_system_mix"]
            ]
            payload["data"]["system_mix"] = [{"system_name": "Sistema de Motor", "count": 5}, {"system_name": "Sin sistema", "count": 1}]
            payload["data"]["hours_pareto"] = [{"equipment": f"EQ-{i:02d}", "value": 50 - i} for i in range(12)]
            payload["data"]["daily"] = [{"date": "2026-01-02", "count": 2, "hours_out_of_service": 3.0, "equipment_count": 2}]
            payload["data"]["unit_status"] = [{"equipment": "EQ-00", "equipment_status": "OPERATIVO", "has_open_intervention": "No",
                                               "days_since_last_maintenance": 3.0, "last_action_date": "2026-01-02"}]
            payload["data"]["detail"] = [{"date": "2026-01-02", "equipment": "EQ-00", "system_name": "Equipo",
                                          "component": "Sin atribución única", "action_type": "Cambio", "detail": "Sin detalle",
                                          "subsystem_name": "Sin subsistema"}]
            payload["data"]["historical_failures"] = [{"machine_code": "EQ-00", "component_name": "Bomba", "n_failure_records": 1, "n_failure_actions": 2}]
            payload["kpis"].update({"motor_share_pct": 30.0, "availability_est_pct": 96.0, "downtime_est_hours": 4.0})
            for item in handlers["render_monthly_payload"](payload, False):
                _strings(item, found)
            for item in handlers["toggle_equipment_view"](1, False, payload)[1:3]:
                _strings(item, found)
            _strings(handlers["render_unit_detail"](payload, "EQ-00"), found)
        empty = callbacks._empty_contract()
        empty["meta"].update({"client": "EMIN", "no_systems_selected": True})
        for state in (empty, {**callbacks._empty_contract(), "status": "error"}, callbacks._empty_contract()):
            for item in handlers["render_monthly_payload"](state, False):
                _strings(item, found)
        _strings(handlers["render_unit_detail"](payload, None), found)
        _strings(handlers["render_unit_detail"](payload, "EQ-99"), found)
        options = [{"value": "a"}, {"value": "b"}, {"value": "c"}]
        found.extend(handlers["update_systems_summary"](chosen, options) for chosen in ([], ["a"], ["a", "b", "c"]))
        found.extend(callbacks._equipment_toggle_label(total, expanded) for total, expanded in ((20, False), (20, True), (9, False)))
        found.append(str(callbacks.availability_status(90.0, "X") or ""))
        found.extend(option["label"] for option in callbacks._fleet_options(["otros", "Camiones"]))
        found.extend(option["label"] for option in callbacks._pareto_system_options(["Equipo", "Sin sistema"]))
    return [text.strip() for text in found if text and text.strip()]


def test_every_report_string_is_translated_in_both_languages(monkeypatch):
    monkeypatch.setitem(callbacks.AVAILABILITY_TARGET_PCT_BY_CLIENT, "X", 95.0)
    spanish, english = _report_strings("es"), _report_strings("en")
    assert len(english) > 100
    assert "Summary" in english and "Resumen" in spanish
    assert any(text.startswith("Others (") for text in english) and any(text.startswith("Otras (") for text in spanish)
    assert any("units account for" in text or "units represent" in text for text in english)
    assert any("unidades concentran" in text or "unidades representan" in text for text in spanish)

    for language, strings in (("es", spanish), ("en", english)):
        keys = sorted({text for text in strings if _KEY_PATTERN.match(text)})
        assert not keys, (language, keys)

    leftover = sorted({text for text in english if _SPANISH_TEXT.search(text) and not any(v in text for v in _DATA_VALUES)})
    assert not leftover, leftover

    # Sentences and phrases must differ between languages; single words that match are
    # acronyms, data values or identifiers (the Spanish-leftover check above covers labels).
    same = sorted({
        text for text in set(spanish) & set(english)
        if " " in text and __import__("re").search(r"[A-Za-z]{3,}", text.replace(" h", "")) and not any(v in text for v in _DATA_VALUES) and not text.startswith(("<b>", "{", "["))
    })
    assert not same, same
