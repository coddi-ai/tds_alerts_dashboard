"""Alertas -> Detalle redesign: source filter, header, AI analysis, telemetry grid,
context tiles and oil view. Each section mirrors one acceptance list."""

import json
import re

import numpy as np
import pandas as pd
import pytest
from dash import html

from dashboard.callbacks import alerts_callbacks as callbacks
from dashboard.components import alert_signal_grid as grid
from dashboard.components.alert_case_header import (
    analysis_block,
    evidence_source_chips,
    trigger_signal_callout,
    verification_callout,
)
from dashboard.components.alerts_charts import create_context_kpis_cards_golden
from dashboard.components.alerts_tables import parse_ia_message_sections
from dashboard.components.oil_charts import build_oil_radar_view, build_oil_time_series_grid
from dashboard.tabs.tab_alerts_detail import SOURCE_FILTER_DEFAULT, create_layout
from src.i18n import load_catalog


def _walk(component, found=None):
    found = [] if found is None else found
    found.append(component)
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            _walk(child, found)
    elif children is not None and not isinstance(children, str):
        _walk(children, found)
    return found


def _text(component):
    if isinstance(component, str):
        return component
    if isinstance(component, (list, tuple)):
        return " ".join(_text(child) for child in component)
    return _text(getattr(component, "children", None) or "")


def _by_class(component, class_name):
    return [c for c in _walk(component) if class_name in str(getattr(c, "className", "") or "").split()]


def _by_id(component, component_id):
    return [c for c in _walk(component) if getattr(c, "id", None) == component_id]


# ---------------------------------------------------------------------------
# Con Tribología: three-option segmented control
# ---------------------------------------------------------------------------

def test_source_filter_is_a_three_option_segmented_control_defaulting_to_si():
    (control,) = _by_id(create_layout(), "detail-filter-tribology")
    assert type(control).__name__ == "RadioItems"
    assert [o["label"] for o in control.options] == ["Todas", "Sí", "No"]
    assert [o["value"] for o in control.options] == ["all", "yes", "no"]
    assert control.value == SOURCE_FILTER_DEFAULT == "yes"
    assert "segmented-control" in control.className


def _alerts():
    frame = pd.DataFrame([
        {"FusionID": "F-oil", "Timestamp": pd.Timestamp("2026-07-09 16:00"), "UnitId": "U1",
         "sistema": "motor", "componente": "engine", "Trigger_type": "Mixto", "has_tribology": True},
        {"FusionID": "F-tel", "Timestamp": pd.Timestamp("2026-07-10 16:00"), "UnitId": "U1",
         "sistema": "motor", "componente": "engine", "Trigger_type": "Telemetria", "has_tribology": False},
    ])
    return frame


@pytest.fixture
def alerts(monkeypatch):
    monkeypatch.setattr(callbacks, "load_alerts_data", lambda client: _alerts())


def _ids(options):
    return {o["value"] for o in options}


def test_dropdown_starts_filtered_to_the_default_selection(alerts):
    options = callbacks.initialize_alert_dropdown("capstone", None, None, None, SOURCE_FILTER_DEFAULT, None)
    assert _ids(options) == {"F-oil"}


def test_selecting_todas_restores_every_alert_and_no_is_the_complement(alerts):
    f = callbacks.filter_alert_dropdown_by_criteria
    assert _ids(f(None, None, None, "all", "capstone", None)) == {"F-oil", "F-tel"}
    assert _ids(f(None, None, None, "no", "capstone", None)) == {"F-tel"}
    assert _ids(f(None, None, None, "yes", "capstone", None)) == {"F-oil"}


def test_alert_reached_from_the_general_tab_stays_selectable_despite_the_default(alerts):
    options = callbacks.initialize_alert_dropdown(
        "capstone", None, None, None, SOURCE_FILTER_DEFAULT, {"alert_id": "F-tel"}
    )
    assert _ids(options) == {"F-oil", "F-tel"}


# ---------------------------------------------------------------------------
# Header: evidence chips + trigger callout
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flags,expected", [
    ({"has_telemetry": True}, ["Telemetría"]),
    ({"has_telemetry": True, "has_tribology": True}, ["Telemetría", "Tribología"]),
    ({"has_telemetry": True, "has_tribology": True, "has_maintenance": True},
     ["Telemetría", "Tribología", "Mantenimiento"]),
])
def test_one_chip_per_actual_evidence_source(flags, expected):
    chips = _by_class(evidence_source_chips(pd.Series(flags)), "alert-evidence-chip")
    assert [_text(chip).strip() for chip in chips] == expected


def test_chips_use_the_info_palette_not_severity_colors():
    css = open("dashboard/assets/alerts_detail.css", encoding="utf-8").read()
    block = css[css.index(".alert-evidence-chip {"):].split("}")[0]
    for severity in ("#dc3545", "#ffc107", "#28a745"):
        assert severity not in block
    assert "#17a2b8" in block


def test_header_has_no_fuente_pill_or_evidencia_line_and_always_has_the_trigger_callout():
    row = pd.Series({
        "FusionID": "F-1", "Timestamp": pd.Timestamp("2026-07-10 16:00:00"), "UnitId": "CA-42",
        "sistema": "motor", "componente": "engine", "Trigger_type": "Mixto",
        "Trigger_Var": "EngCoolTemp", "mensaje_ia": "", "has_telemetry": True, "has_tribology": True,
    })
    header = callbacks._alert_case_header(row)
    text = _text(header)
    assert not re.search(r"Fuente", text) and "Evidencia:" not in text
    (callout,) = _by_class(header, "alert-trigger-callout")
    assert "Señal gatillo" in _text(callout)
    assert "Temperatura del refrigerante" in _text(callout)


def test_trigger_callout_renders_even_without_a_signal():
    assert "Señal gatillo" in _text(trigger_signal_callout(None))


# ---------------------------------------------------------------------------
# Análisis Inteligente: verification question in its own field
# ---------------------------------------------------------------------------

def _message(**changes):
    return json.dumps({
        "diagnostic": "Aceite degradado.",
        "recommended_actions": ["Cambiar el aceite.", "¿Se revisó el filtro?"],
        "evidence": ["telemetry"], **changes,
    })


def test_verification_question_is_read_from_its_own_field():
    sections = parse_ia_message_sections(_message(verification_question="¿Se realizó un cambio de aceite?"))
    assert sections["verificacion"] == "¿Se realizó un cambio de aceite?"


@pytest.mark.parametrize("message", [_message(), _message(verification_question=None),
                                     _message(verification_question="  "), "DIAGNÓSTICO: x. ACCIONES: ¿Y esto?"])
def test_no_field_means_no_question_even_when_the_narrative_has_a_question_mark(message):
    assert parse_ia_message_sections(message)["verificacion"] == ""


def test_verificar_callout_sits_above_the_narrative_and_is_absent_without_a_question():
    with_q = analysis_block("Acción Recomendada", "Cambiar el aceite.", "fa-wrench", verification="¿Se cambió?")
    callout_idx = [i for i, c in enumerate(with_q.children[0].children)
                   if "alert-verify-callout" in str(getattr(c, "className", ""))]
    assert callout_idx and callout_idx[0] < len(with_q.children[0].children) - 1
    assert "Verificar" in _text(with_q) and "¿Se cambió?" in _text(with_q)

    without_q = analysis_block("Acción Recomendada", "Cambiar el aceite.", "fa-wrench", verification=None)
    assert not _by_class(without_q, "alert-verify-callout")
    assert verification_callout("") is None


def test_the_three_titles_carry_their_accents():
    es = load_catalog("es")
    assert es["alerts_callbacks.analisis_inteligente"] == "Análisis Inteligente"
    assert es["ai_analysis_panel.diagnostico"] == "Diagnóstico"
    assert es["alerts_callbacks.accion_recomendada"] == "Acción Recomendada"
    unaccented = [k for k, v in es.items()
                  if not k.startswith("vocab.") and any(w in v.split() for w in ("Analisis", "Diagnostico", "Accion"))]
    assert not unaccented


# ---------------------------------------------------------------------------
# Evidencia de Telemetría: featured trigger + progressive grid
# ---------------------------------------------------------------------------

ALERT_TIME = pd.Timestamp("2026-07-10 16:00:00")


def _telemetry(n_signals, out_of_range=(), trigger="sig_0"):
    times = pd.date_range(ALERT_TIME - pd.Timedelta(minutes=30), periods=40, freq="1min")
    data = {"TimeStart": times, "Trigger": trigger, "State": "Operacional"}
    for i in range(n_signals):
        base = np.linspace(10, 20, len(times))
        data[f"sig_{i}_Value"] = base + (100 if i in out_of_range else 0)
        data[f"sig_{i}_Upper_Limit"] = 50.0
    return pd.DataFrame(data)


def _evidence(n_signals, visible=3, **kwargs):
    names = [f"sig_{i}" for i in range(n_signals)]
    panels, local_time = grid.prepare_signal_panels(
        _telemetry(n_signals, **kwargs), names, ALERT_TIME, kwargs.get("trigger", "sig_0"),
        {n: n.upper() for n in names},
    )
    return panels, grid.create_signal_evidence(panels, local_time, visible)


def test_three_signals_need_no_expand_control():
    _, section = _evidence(3)
    assert not _by_id(section, "alert-signals-toggle")
    assert len(_by_class(section, "alert-signal-featured")) == 1
    assert len(_by_class(section, "alert-signal-card")) == 2


def test_twenty_signals_show_trigger_three_supporting_and_a_toggle_for_sixteen():
    _, section = _evidence(20)
    (toggle,) = _by_id(section, "alert-signals-toggle")
    assert toggle.children == "Mostrar 16 señales adicionales"
    (collapse,) = _by_id(section, "alert-signals-collapse")
    assert collapse.is_open is False
    assert len(_by_class(collapse, "alert-signal-card")) == 16
    (labels,) = _by_id(section, "alert-signals-toggle-labels")
    assert labels.data["less"] == "Mostrar menos señales"
    assert len(_by_class(section, "alert-signal-card")) == 19


def test_visible_count_is_configurable():
    _, section = _evidence(10, visible=5)
    assert _by_id(section, "alert-signals-toggle")[0].children == "Mostrar 4 señales adicionales"


def test_trigger_is_featured_and_never_repeated_in_the_grid():
    panels, section = _evidence(8)
    trigger, supporting = grid.split_signal_panels(panels)
    assert trigger.feature == "sig_0"
    assert all(panel.feature != "sig_0" for panel in supporting)
    titles = [_text(c) for c in _by_class(section, "alert-signal-card__title")]
    assert "SIG_0" not in titles and len(titles) == 7


def test_out_of_range_supporting_signals_come_first_then_source_order():
    panels, _ = _evidence(6, out_of_range=(4, 2))
    _, supporting = grid.split_signal_panels(panels)
    assert [p.feature for p in supporting] == ["sig_2", "sig_4", "sig_1", "sig_3", "sig_5"]


def test_each_chart_labels_only_its_extremes():
    panels, _ = _evidence(3)
    for featured in (True, False):
        fig = grid.build_signal_figure(panels[0], panels[0].values["TimeStart"].iloc[-1], featured=featured)
        assert len(fig.layout.yaxis.tickvals) <= 2
        assert len(fig.layout.xaxis.tickvals) <= 2
        assert fig.layout.yaxis.tickmode == fig.layout.xaxis.tickmode == "array"


def test_featured_chart_is_annotated_with_peak_and_limit():
    panels, _ = _evidence(3, out_of_range=(0,))
    fig = grid.build_signal_figure(panels[0], panels[0].values["TimeStart"].iloc[-1], featured=True)
    notes = " ".join(a.text or "" for a in fig.layout.annotations)
    assert "Pico" in notes and "Límite Superior" in notes


def test_grid_never_goes_below_a_legible_card_width_and_caps_at_three_columns():
    css = open("dashboard/assets/alerts_detail.css", encoding="utf-8").read()
    rule = css[css.index(".alert-signal-grid {"):].split("}")[0]
    assert "minmax(max(300px, calc((100% - 2rem) / 3)), 1fr)" in rule


# ---------------------------------------------------------------------------
# Indicadores de contexto
# ---------------------------------------------------------------------------

def _context(load):
    return create_context_kpis_cards_golden(
        pd.DataFrame([{"TimeStart": ALERT_TIME, "engine_load_pct_Value": load,
                       "engine_speed_rpm_Value": 1500.0, "Payload_Value": 90.0}]),
        ALERT_TIME, "engine_speed_rpm",
    )


def test_context_indicators_share_one_tile_style_without_severity_colors():
    tiles = _by_class(_context(100), "context-tile")
    assert len(tiles) == 4
    assert {str(t.style) for t in tiles} == {str(tiles[0].style)}
    rendered = str(_context(100))
    for severity in ("text-danger", "text-warning", "text-success", "outline"):
        assert severity not in rendered


def test_engine_load_carries_a_caption_that_explains_full_load():
    assert "plena carga" in _text(_by_class(_context(100), "context-tile__caption"))
    (caption,) = _by_class(_context(42), "context-tile__caption")
    assert "100% = plena carga" in _text(caption)
    assert len(_by_class(_context(100), "context-tile__caption")) == 1


# ---------------------------------------------------------------------------
# Análisis de Aceite
# ---------------------------------------------------------------------------

def _history(**columns):
    n = 4
    frame = pd.DataFrame({"sampleDate": pd.date_range("2026-01-01", periods=n, freq="30D")})
    for name, values in columns.items():
        frame[name] = values
    return frame


LIMITS = {"Hierro": {"LIC": None, "LIM": None, "LSM": 15.0, "LSC": 20.0}}


def test_tendencia_has_a_limit_legend_and_a_compact_empty_state(monkeypatch):
    monkeypatch.setattr("dashboard.components.oil_charts.get_essay_limits_four",
                        lambda comp, essay, rng: LIMITS.get(essay))
    out = build_oil_time_series_grid(_history(Hierro=[5, 6, 7, 8]), {}, "LT_1000")
    (legend,) = _by_class(out, "oil-limit-legend")
    assert "Límite crítico superior" in _text(legend)
    empties = _by_class(out, "oil-empty-state")
    assert empties and any("Hollín & Oxidación" in _text(e) and "Sin datos" in _text(e) for e in empties)
    assert not any(type(c).__name__ == "Card" and "Sin datos" in _text(c) for c in _walk(out))


def test_alert_oil_tabs_scope_the_underline_to_the_label():
    source = open("dashboard/callbacks/alerts_callbacks.py", encoding="utf-8").read()
    block = source[source.index("id='alert-oil-view-selector'"):][:900]
    assert block.count("custom-tab pred-tab") == 2
    assert block.count("pred-tab--selected") == 2


def test_ultimo_ensayo_flags_the_out_of_limit_axes(monkeypatch):
    monkeypatch.setattr("dashboard.components.oil_charts.get_essay_limits_four",
                        lambda comp, essay, rng: {"LIC": None, "LIM": None, "LSM": 15.0, "LSC": 20.0})
    essays = pd.DataFrame({"GroupElement": ["Desgaste"] * 3, "ElementNameSpanish": ["Hierro", "Cobre", "Plomo"]})
    report = pd.Series({"Hierro": 30.0, "Cobre": 3.0, "Plomo": 25.0, "report_status": "Anormal"})
    rows = html.Div(build_oil_radar_view(report, {}, "LT_1000", essays))
    figure = [c for c in _walk(rows) if type(c).__name__ == "Graph"][0].figure
    polar = {trace.name: trace for trace in figure.data}
    assert list(polar["Valores Actuales"].theta) == ["Hierro", "Cobre", "Plomo"]
    flagged = polar["Fuera de límite"]
    assert set(flagged.theta) == {"Hierro", "Plomo"}
