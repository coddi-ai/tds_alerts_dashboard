"""Display-time choice between a long-text column and its `_eng` translation.

Covers the helper (`src/i18n/data_text.py`) and its wiring in the six tabs that use it:
Oil (fleet overview, report detail), Alerts (general, detailed) and Predictive evidence.
English shows `<column>_eng` where it has text; Spanish, or an empty/missing `_eng`, shows the
original column.
"""

import numpy as np
import pandas as pd
import pytest
from flask import Flask

from src.i18n import LANGUAGE_COOKIE
from src.i18n.data_text import eng_column, is_eng_column, localized_series, localized_value


def _in(language):
    app = Flask(__name__)
    headers = {"Cookie": f"{LANGUAGE_COOKIE}={language}"} if language else {}
    return app.test_request_context("/", headers=headers)


def test_naming():
    assert eng_column("comment") == "comment_eng"
    assert is_eng_column("ai_recommendation_eng")
    assert not is_eng_column("ai_recommendation") and not is_eng_column(None)


def test_value_follows_the_language():
    row = {"a": "hola", "a_eng": "hello"}
    assert localized_value(row, "a") == "hola"  # outside a request: Spanish
    with _in("es"):
        assert localized_value(row, "a") == "hola"
    with _in("en"):
        assert localized_value(row, "a") == "hello"
        assert localized_value(pd.Series(row), "a") == "hello"


@pytest.mark.parametrize("missing", [None, "", "   ", np.nan, pd.NA])
def test_value_falls_back_to_spanish_when_the_translation_is_blank(missing):
    with _in("en"):
        assert localized_value({"a": "hola", "a_eng": missing}, "a") == "hola"


def test_value_without_an_eng_column_and_default():
    with _in("en"):
        assert localized_value({"a": "hola"}, "a") == "hola"
        assert localized_value({}, "a", "dflt") == "dflt"


def test_series_substitutes_row_by_row():
    df = pd.DataFrame({"a": ["uno", "dos", "tres"], "a_eng": ["one", "", None]})
    with _in("en"):
        assert localized_series(df, "a").tolist() == ["one", "dos", "tres"]
    with _in("es"):
        assert localized_series(df, "a").tolist() == ["uno", "dos", "tres"]
    with _in("en"):
        assert localized_series(df[["a"]], "a").tolist() == ["uno", "dos", "tres"]


# ── Wiring in the dashboard ─────────────────────────────────────────────────────

def _alerts_frame():
    return pd.DataFrame({
        "FusionID": ["f1", "f2"],
        "Timestamp": pd.to_datetime(["2026-09-01 10:00", "2026-09-01 11:00"]),
        "UnitId": ["CA-1", "CA-2"],
        "sistema": ["Motor", "Motor"],
        "componente": ["Turbo", "Turbo"],
        "Trigger_type": ["Telemetria", "Telemetria"],
        "Trigger_Var": ["EngCoolTemp", "EngCoolTemp"],
        "has_telemetry": [True, True],
        "has_tribology": [False, False],
        "mensaje_ia": [
            "DIAGNÓSTICO: Falla de bomba.\nCAUSA PROBABLE: Desgaste.\nACCIONES RECOMENDADAS: Revisar.",
            "DIAGNÓSTICO: Sin traducir.\nCAUSA PROBABLE: Otra.\nACCIONES RECOMENDADAS: Medir.",
        ],
        # The second row has no translation yet: it must fall back to Spanish, not go blank.
        "mensaje_ia_eng": [
            "DIAGNÓSTICO: Pump failure.\nCAUSA PROBABLE: Wear.\nACCIONES RECOMENDADAS: Inspect.",
            "",
        ],
    })


def test_alerts_rows_use_the_english_message_but_the_parser_still_finds_the_sections():
    from dashboard.components.alerts_report import prepare_alert_rows

    df = _alerts_frame()
    with _in("en"):
        rows = prepare_alert_rows(df)
        assert rows["diagnosis_display"].tolist() == ["Pump failure.", "Sin traducir."]
        assert rows["cause_display"].tolist() == ["Wear.", "Otra."]
        assert rows["action_display"].tolist() == ["Inspect.", "Medir."]
    with _in("es"):
        assert prepare_alert_rows(df)["diagnosis_display"].tolist() == ["Falla de bomba.", "Sin traducir."]


def test_alerts_general_table_and_detail_header_use_the_english_message():
    from dashboard.callbacks.alerts_callbacks import _alert_case_header
    from dashboard.components.alerts_tables import create_alerts_report_table

    df = _alerts_frame()
    with _in("en"):
        table = create_alerts_report_table(df)
        by_id = {row["ID"]: row for row in table.data}
        assert by_id["f1"]["Diagnóstico"] == "Pump failure." and by_id["f1"]["Acción"] == "Inspect."
        assert by_id["f2"]["Diagnóstico"] == "Sin traducir."
        assert "Pump failure." in repr(_alert_case_header(df.iloc[0]).to_plotly_json())
    with _in("es"):
        by_id = {row["ID"]: row for row in create_alerts_report_table(df).data}
        assert by_id["f1"]["Diagnóstico"] == "Falla de bomba."


def test_oil_report_detail_uses_the_english_recommendation_and_ignores_eng_columns_as_essays():
    from dashboard.callbacks.reports_callbacks import create_ai_diagnosis_and_action, get_essay_options

    sample = pd.Series({
        "ai_recommendation": "Diagnóstico: Desgaste alto.\nAcción: Cambiar aceite.",
        "ai_recommendation_eng": "Diagnóstico: High wear.\nAcción: Change oil.",
    })

    def text_of(component):
        return repr(component.to_plotly_json())

    with _in("en"):
        body = text_of(create_ai_diagnosis_and_action(sample)[0])
        assert "High wear." in body and "Change oil." in body and "Desgaste alto" not in body
    with _in("es"):
        body = text_of(create_ai_diagnosis_and_action(sample)[0])
        assert "Desgaste alto." in body and "High wear" not in body

    frame = pd.DataFrame({"unitId": ["u"], "Hierro": [1.0], "ai_recommendation_eng": ["x"]})
    assert [o["value"] for o in get_essay_options(frame)] == ["Hierro"]


def test_oil_machine_detail_table_and_recommendation_card(monkeypatch):
    from dashboard.components import oil_machine_detail as omd

    classified = pd.DataFrame({
        "unitId": ["T1"], "machineName": ["Camión"], "componentName": ["motor"],
        "sampleDate": ["2026-09-01"], "report_status": ["Alerta"], "severity_score": [3],
        "essays_broken": [1], "breached_essays": [[]], "anomalyType": ["Normal"],
        "ai_recommendation": ["Cambio de aceite."], "ai_recommendation_eng": ["Oil change."],
    })
    status = pd.DataFrame({
        "unit_id": ["T1"], "machine_ai_recommendation": ["Revisar motor."],
        "machine_ai_recommendation_eng": ["Check the engine."],
    })
    monkeypatch.setattr(omd, "load_oil_classified", lambda client: classified.copy())
    monkeypatch.setattr(omd, "load_machine_status_for_client", lambda client: status.copy())

    class _Path:
        def exists(self):
            return True

    class _Settings:
        component_hours_allowed_clients = []
        get_classified_reports_path = get_machine_status_path = staticmethod(lambda client: _Path())

    monkeypatch.setattr(omd, "get_settings", lambda: _Settings())

    with _in("en"):
        _, _, card, table = omd.build_machine_detail("cda", "T1")
        assert "Check the engine." in repr(card.to_plotly_json())
        assert [r["ai_text"] for r in table.data] == ["Oil change."]
    with _in("es"):
        _, _, card, table = omd.build_machine_detail("cda", "T1")
        assert "Revisar motor." in repr(card.to_plotly_json())
        assert [r["ai_text"] for r in table.data] == ["Cambio de aceite."]


def test_predictive_evidence_panels_use_the_english_columns():
    from dashboard.tabs import tab_predictive_evidence as ev

    unit = pd.Series({
        "diagnostico": "Diag es", "causa_probable": "Causa es", "acciones": '["Revisar"]',
        "diagnostico_eng": "Diag en", "causa_probable_eng": "Cause en", "acciones_eng": '["Inspect"]',
        "analisis_fuente": "llm",
    })
    mode = pd.Series({
        "diagnostico": "Modo es", "probable_cause": "Causa modo es", "recommended_actions": '["Medir"]',
        "diagnostico_eng": "Mode en", "probable_cause_eng": "Mode cause en",
        "recommended_actions_eng": '["Measure"]', "analysis_status": "ok",
    })
    with _in("en"):
        assert ev._unit_narrative_panel(unit)["diagnostico"] == "Diag en"
        assert ev._unit_narrative_panel(unit)["acciones"] == '["Inspect"]'
        panel = ev._mode_narrative_panel(mode, "alerta")
        assert (panel["diagnostico"], panel["causa_probable"], panel["acciones"]) == (
            "Mode en", "Mode cause en", '["Measure"]')
    with _in("es"):
        assert ev._unit_narrative_panel(unit)["diagnostico"] == "Diag es"
        assert ev._mode_narrative_panel(mode, "alerta")["acciones"] == '["Medir"]'


# ── Telemetry ───────────────────────────────────────────────────────────────────

def test_telemetry_comment_helpers_read_the_english_columns():
    from dashboard.callbacks.telemetry_callbacks import _text_value
    from dashboard.components.telemetry_report import _comment_text

    comment = pd.Series({
        "description": "Motor sobrecalentado", "description_eng": "Engine overheating",
        "explaining": "Explicacion", "explaining_eng": "",
    })
    with _in("en"):
        assert _text_value(comment, "description") == "Engine overheating"
        assert _comment_text(comment, {}, "description") == "Engine overheating"
        assert _text_value(comment, "explaining") == "Explicacion"  # blank translation -> Spanish
    with _in("es"):
        assert _text_value(comment, "description") == "Motor sobrecalentado"


def test_client_facing_text_hides_scores_in_english_without_spanish_leaking_in():
    from dashboard.components.telemetry_report import client_facing_text

    text = ("Engine shows a priority score of 7.2 and a risk score of 5.5 out of 10, with confidence of 85%. "
            "Criticality is 3 and the signal ranges between 10% and 20%.")
    with _in("en"):
        out = client_facing_text(text, {"EngCoolTemp": "Temperatura del refrigerante"})
    for number in ("7.2", "5.5", "85", "10%", "20%"):
        assert number not in out, out
    assert "Engine" in out  # not rewritten to the Spanish "Motor"
    for spanish in ("nivel de riesgo", "prioridad asignada", "evidencia", "Motor"):
        assert spanish not in out, out


def test_client_facing_text_in_spanish_is_unchanged():
    from dashboard.components.telemetry_report import client_facing_text

    text = "Engine con un puntaje de prioridad de 7.2 y confianza del 85%, riesgos de 3.2 y 4.1 respectivamente."
    expected = "Motor con una prioridad asignada y evidencia disponible, niveles de riesgo."
    assert client_facing_text(text) == expected
    with _in("es"):
        assert client_facing_text(text) == expected
