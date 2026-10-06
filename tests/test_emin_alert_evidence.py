"""EMIN's dashboard patch must resolve evidence, not infer it from IA text."""

import json

import pandas as pd
import pytest

from src.data.emin_alert_evidence import (
    enrich_emin_alert_evidence,
    evidence_label,
    maintenance_evidence_row,
)
from src.data.loaders import load_alerts_data


def _alert(**changes):
    return {
        "FusionID": "F-1", "Timestamp": "2026-07-10T16:00:00Z",
        "UnitId": "E-01", "sistema": "motor", "subsistema": "engine",
        "componente": "engine", "Trigger_type": "Telemetria",
        "TelemetryID": "T-1", "TribologyID": "", "Trigger_Var": "EngCoolTemp",
        "mensaje_ia": "Hay detenciones y evidencia de mantenciones.",
        "Semana_Resumen_Mantencion": "28-2026",
        "has_telemetry": True, "has_tribology": False, **changes,
    }


def _weekly(**changes):
    return {"UnitId": "E-01", "Summary": "Inspección del motor.",
            "Tasks_List": "{}", **changes}


def test_event_with_linked_maintenance_becomes_mixed_without_inventing_oil():
    original = pd.DataFrame([_alert()])
    result = enrich_emin_alert_evidence(original, {"28-2026": pd.DataFrame([_weekly()])})
    row = result.iloc[0]
    assert row.Trigger_type == "Mixto"
    assert row.Trigger_type_original == "Telemetria"
    assert row.has_telemetry and row.has_maintenance and not row.has_tribology
    assert evidence_label(row) == "Telemetría + Mantenimiento"
    assert original.iloc[0].Trigger_type == "Telemetria"
    assert "has_maintenance" not in original


@pytest.mark.parametrize("weekly", [
    pd.DataFrame(), pd.DataFrame([_weekly(UnitId="OTHER")]),
    pd.DataFrame([_weekly(Summary=None, Tasks_List="{}")]),
    pd.DataFrame([_weekly(Summary="  ", Tasks_List="[]")]),
    pd.DataFrame([_weekly(Summary="nan", Tasks_List="invalid-json")]),
    pd.DataFrame([_weekly(Summary=None, Tasks_List='{"day": {"motor": []}}')]),
    pd.DataFrame([_weekly(Summary=None, Tasks_List='["not-the-weekly-contract"]')]),
    pd.DataFrame([_weekly(Summary=None, Tasks_List='{"day": "not-a-task-list"}')]),
])
def test_unresolved_or_empty_evidence_does_not_promote_despite_ia_text(weekly):
    result = enrich_emin_alert_evidence(pd.DataFrame([_alert()]), {"28-2026": weekly})
    assert result.iloc[0].Trigger_type == "Telemetria"
    assert not result.iloc[0].has_maintenance


@pytest.mark.parametrize("week", [None, "", "nan", "27-2026", "../28-2026", "00-2026"])
def test_uses_only_the_explicit_valid_week(week):
    result = enrich_emin_alert_evidence(
        pd.DataFrame([_alert(Semana_Resumen_Mantencion=week)]),
        {"28-2026": pd.DataFrame([_weekly()])},
    )
    assert result.iloc[0].Trigger_type == "Telemetria"


def test_real_tasks_are_evidence_and_detail_uses_the_same_nonempty_row():
    tasks = json.dumps({"Viernes 10/07": {"motor": ["Inspección de refrigeración"]}})
    weekly = pd.DataFrame([_weekly(Summary=None), _weekly(Summary=None, Tasks_List=tasks)])
    result = enrich_emin_alert_evidence(pd.DataFrame([_alert()]), {"28-2026": weekly})
    assert result.iloc[0].has_maintenance
    assert maintenance_evidence_row(weekly, "E-01").Tasks_List == tasks


def test_existing_mixed_and_oil_flags_survive_and_maintenance_alone_is_not_an_event():
    rows = [
        _alert(Trigger_type="Mixto", has_tribology=True, TribologyID="O-1"),
        _alert(Trigger_type="Tribologia", has_telemetry=False, has_tribology=True),
    ]
    result = enrich_emin_alert_evidence(pd.DataFrame(rows), {"28-2026": pd.DataFrame([_weekly()])})
    assert result.Trigger_type.tolist() == ["Mixto", "Tribologia"]
    assert result.has_tribology.tolist() == [True, True]
    assert evidence_label(result.iloc[0]) == "Telemetría + Tribología + Mantenimiento"


def _write_dashboard_data(tmp_path, monkeypatch, client="emin"):
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DASHBOARD_FRAME_ENGINE", "pandas")
    alerts_path = tmp_path / "alerts" / "golden" / client / "consolidated_alerts.csv"
    alerts_path.parent.mkdir(parents=True)
    pd.DataFrame([_alert()]).to_csv(alerts_path, index=False)
    week_path = tmp_path / "mantentions" / "golden" / client / "28-2026.csv"
    week_path.parent.mkdir(parents=True)
    pd.DataFrame([_weekly()]).to_csv(week_path, index=False)
    return week_path


def test_loader_refreshes_changed_and_deleted_evidence_with_unchanged_alerts(tmp_path, monkeypatch):
    week_path = _write_dashboard_data(tmp_path, monkeypatch)
    assert load_alerts_data("EMIN").iloc[0].Trigger_type == "Mixto"
    pd.DataFrame([_weekly(Summary=None, Tasks_List="{}")]).to_csv(week_path, index=False)
    assert load_alerts_data("emin").iloc[0].Trigger_type == "Telemetria"
    pd.DataFrame([_weekly()]).to_csv(week_path, index=False)
    loaded = load_alerts_data("emin")
    assert loaded.iloc[0].Trigger_type == "Mixto"
    loaded.loc[0, "has_tribology"] = True
    assert not load_alerts_data("emin").iloc[0].has_tribology
    week_path.unlink()
    assert load_alerts_data("emin").iloc[0].Trigger_type == "Telemetria"


def test_other_clients_keep_existing_classification(tmp_path, monkeypatch):
    _write_dashboard_data(tmp_path, monkeypatch, client="capstone")
    loaded = load_alerts_data("capstone")
    assert loaded.iloc[0].Trigger_type == "Telemetria"
    assert "has_maintenance" not in loaded


def test_table_summary_and_detail_agree_on_sources(tmp_path, monkeypatch):
    from dashboard.components.alerts_tables import create_alerts_report_table
    from dashboard.components.alerts_report import alert_summary, prepare_alert_rows
    from dashboard.callbacks import alerts_callbacks as callbacks
    from dash import html

    _write_dashboard_data(tmp_path, monkeypatch)
    loaded = load_alerts_data("emin")
    table = create_alerts_report_table(loaded)
    assert table.data[0]["Fuente"] == "Multitécnica"
    assert table.data[0]["Evidencia"] == "Telemetría + Mantenimiento"
    assert prepare_alert_rows(loaded).iloc[0].evidence_display == "Telemetría + Mantenimiento"
    assert alert_summary(loaded)["mixed"] == 1
    called = []
    for name in ("telemetry", "oil", "maintenance"):
        def render(row, client, name=name):
            called.append(name)
            return html.Div(name)
        monkeypatch.setattr(callbacks, f"create_{name}_evidence_section", render)
    detail = callbacks.update_detail_view("F-1", "emin", None)
    assert called == ["telemetry", "maintenance"]
    assert "Multitécnica" in str(detail)
    assert "Telemetría + Mantenimiento" in str(detail)


def test_maintenance_detail_displays_the_evidence_used_for_classification(monkeypatch):
    from dashboard.callbacks import alerts_callbacks as callbacks
    weekly = pd.DataFrame([_weekly(Summary=None), _weekly(Summary="Evidencia real del motor")])
    monkeypatch.setattr(callbacks, "load_maintenance_week", lambda client, week: weekly)
    detail = callbacks.create_maintenance_evidence_section(pd.Series(_alert()), "emin")
    assert "Evidencia real del motor" in str(detail)


def test_weekly_context_is_visible_even_when_tasks_are_for_another_system(monkeypatch):
    from dashboard.callbacks import alerts_callbacks as callbacks
    tasks = json.dumps({"Viernes 10/07": {"frenos": ["Inspección de frenos"]}})
    weekly = pd.DataFrame([_weekly(Summary=None, Tasks_List=tasks)])
    monkeypatch.setattr(callbacks, "load_maintenance_week", lambda client, week: weekly)
    result = enrich_emin_alert_evidence(pd.DataFrame([_alert()]), {"28-2026": weekly})
    assert result.iloc[0].Trigger_type == "Mixto"
    detail = callbacks.create_maintenance_evidence_section(result.iloc[0], "emin")
    assert "Inspección de frenos" in str(detail)
    assert "Actividades reportadas" in str(detail)


def test_executive_summary_exposes_external_evidence_without_claiming_downtime(tmp_path, monkeypatch):
    from dashboard.components.alerts_tables import create_alerts_report_table
    from dashboard.callbacks.alerts_callbacks import render_selected_alert_summary
    week_path = _write_dashboard_data(tmp_path, monkeypatch)
    tasks = json.dumps({"Viernes 10/07": {"motor": ["Inspección de refrigeración"]}})
    pd.DataFrame([_weekly(Tasks_List=tasks)]).to_csv(week_path, index=False)
    table = create_alerts_report_table(load_alerts_data("emin"))
    summary = str(render_selected_alert_summary({"row": 0}, table.data))
    assert "Multitécnica" in summary
    assert "Contexto de mantenciones" in summary and "28-2026" in summary
    assert "Inspección del motor" in summary and "Inspección de refrigeración" in summary
    assert "Duración de detención: no informada" in summary


def test_summary_has_no_maintenance_context_when_reference_cannot_be_resolved(tmp_path, monkeypatch):
    from dashboard.components.alerts_tables import create_alerts_report_table
    from dashboard.callbacks.alerts_callbacks import render_selected_alert_summary
    week_path = _write_dashboard_data(tmp_path, monkeypatch)
    week_path.unlink()
    table = create_alerts_report_table(load_alerts_data("emin"))
    summary = str(render_selected_alert_summary({"row": 0}, table.data))
    assert "Contexto de mantenciones" not in summary
    assert "Multitécnica" not in summary


@pytest.mark.parametrize("missing_source", [True, False])
def test_missing_sensor_series_message_keeps_the_recorded_alert_clear(monkeypatch, missing_source):
    from dashboard.callbacks import alerts_callbacks as callbacks
    source = pd.DataFrame() if missing_source else pd.DataFrame({
        "AlertID": ["UNRELATED"], "Unit": ["OTHER"]
    })
    monkeypatch.setattr(callbacks, "load_telemetry_alert_detail_for_alert", lambda *args: source)
    rendered = str(callbacks.create_telemetry_evidence_section(pd.Series(_alert()), "emin"))
    assert "Esta alerta está registrada" in rendered
    assert "series de sensores" in rendered
    assert "resumen y el detalle" in rendered
    assert "No hay datos de telemetría" not in rendered
