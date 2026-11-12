"""Regression cases observed in the EMIN POC, without external services."""

import json

import pandas as pd
import pytest

from src.data.emin_alert_evidence import (
    alert_reference,
    evidence_label,
    maintenance_files_for_alert,
    prepare_emin_alert_sources,
    resolve_emin_maintenance_evidence,
)
from src.data.loaders import load_alerts_data


def _case(**changes):
    return {
        "FusionID": "F-c166471923b2a4a5-1747641987",
        "Timestamp": "2025-05-19T08:06:00Z", "UnitId": "BULL-031",
        "sistema": "Sistema de Motor", "subsistema": "Sistema de Enfriamiento",
        "componente": "Refrigerante", "Trigger_Var": "Refrigerante",
        "Trigger_type": "Mixto", "SourceType": "Telemetry",
        "TelemetryID": "TEST-EVENT-REF", "TribologyID": "",
        "Semana_Resumen_Mantencion": "19-2025", "mensaje_ia": "",
        **changes,
    }


def _legacy_row():
    return {
        "UnitId": "BULL-031",
        "Tasks_List": json.dumps({
            "Jueves 15/05": {"Equipo - Lubricación": ["Engrase general"]},
            "Domingo 18/05": {"Sistema de Motor - Sistema de Enfriamiento": [
                "Registro de evento por baja presión de refrigerante del motor.",
                "No se detallan actividades ejecutadas.",
                "Realizar mantenimiento preventivo semanal.",
            ]},
        }),
        "Summary": "Se registró baja presión del refrigerante y mantenimiento preventivo semanal.",
    }


def _visible(component):
    if isinstance(component, str):
        return component
    if isinstance(component, (list, tuple)):
        return "\n".join(_visible(item) for item in component)
    return _visible(getattr(component, "children", []))


def _write_case(tmp_path, monkeypatch, client="emin", **changes):
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DASHBOARD_FRAME_ENGINE", "pandas")
    alerts = tmp_path / "alerts" / "golden" / client / "consolidated_alerts.csv"
    alerts.parent.mkdir(parents=True)
    pd.DataFrame([_case(**changes)]).to_csv(alerts, index=False)
    weekly = tmp_path / "mantentions" / "golden" / client / "19-2025.csv"
    weekly.parent.mkdir(parents=True)
    pd.DataFrame([_legacy_row()]).to_csv(weekly, index=False)
    return alerts, weekly


def test_poc_case_recovers_may_18_maintenance_from_historical_week_19():
    result = resolve_emin_maintenance_evidence(_case(), {"19-2025": pd.DataFrame([_legacy_row()])})
    assert result["status"] == "matched"
    assert result["start"] == "2025-04-21T00:00:00"
    assert result["end"] == "2025-05-19T00:00:00"
    assert result["evidence"].Semana == "20-2025"  # actual ISO week, not the legacy filename
    assert "2025-05-18" in result["evidence"].Tasks_List
    assert "mantenimiento preventivo semanal" in result["evidence"].Tasks_List
    assert "Engrase general" not in result["evidence"].Tasks_List
    assert "baja presión" in result["evidence"].Summary


@pytest.mark.parametrize("value", [None, "", " ", "nan", "NaN", "None", "null", pd.NA, float("nan"), "-", "n/a"])
def test_mixed_type_does_not_imply_an_oil_sample(value):
    original = pd.DataFrame([_case(TribologyID=value)])
    result = prepare_emin_alert_sources(original)
    assert result.iloc[0].Trigger_type == "Mixto"
    assert result.iloc[0].has_telemetry
    assert not result.iloc[0].has_tribology
    assert evidence_label(result.iloc[0]) == "Telemetría"
    assert "source_references_checked" not in original


@pytest.mark.parametrize("value,reference", [("OIL-10", "OIL-10"), (123.0, "123"), ("001", "001")])
def test_published_oil_report_alias_is_resolved_when_legacy_column_is_blank(value, reference):
    result = prepare_emin_alert_sources(pd.DataFrame([_case(OilReportNumber=value)]))
    assert result.iloc[0].TribologyID == reference
    assert result.iloc[0].has_tribology
    assert result.iloc[0].Trigger_type == "Mixto"


def test_source_type_can_identify_event_without_manufacturing_an_id():
    result = prepare_emin_alert_sources(pd.DataFrame([_case(TelemetryID=None)]))
    assert result.iloc[0].has_telemetry
    assert pd.isna(result.iloc[0].TelemetryID)
    assert not result.iloc[0].has_tribology


def test_source_flags_remain_unknown_without_published_references_or_source_type():
    result = prepare_emin_alert_sources(pd.DataFrame([_case(TelemetryID=None, SourceType=None)]))
    assert not result.iloc[0].has_telemetry and not result.iloc[0].has_tribology
    assert result.iloc[0].Trigger_type == "Mixto"


@pytest.mark.parametrize("client", ["cda", "capstone"])
def test_existing_other_client_source_contract_is_preserved(tmp_path, monkeypatch, client):
    _write_case(tmp_path, monkeypatch, client)
    row = load_alerts_data(client).iloc[0]
    assert row.has_telemetry and row.has_tribology
    assert row.Trigger_type == "Mixto"


def test_full_poc_detail_shows_event_and_maintenance_without_blank_oil_warning(tmp_path, monkeypatch):
    from dashboard.callbacks import alerts_callbacks as callbacks
    from dashboard.components.alerts_tables import create_alerts_report_table

    _write_case(tmp_path, monkeypatch)
    monkeypatch.setattr(callbacks, "load_telemetry_alert_detail_for_alert", lambda *args: pd.DataFrame())
    monkeypatch.setattr(callbacks, "load_oil_classified", lambda *args: pytest.fail("Oil was queried without a reference"))
    row = load_alerts_data("emin").iloc[0]
    assert row.Trigger_type == "Mixto"
    assert row.has_maintenance and not row.has_tribology
    assert evidence_label(row) == "Telemetría + Mantenimiento"
    detail = _visible(callbacks.update_detail_view(row.FusionID, "emin", None))
    # The header lists the evidence sources as chips; it no longer repeats the
    # published type ("Multitécnica") or a "Telemetría + Mantenimiento" line.
    assert "Telemetría" in detail and "Mantenimiento" in detail
    assert "Multitécnica" not in detail
    assert "Telemetría + Mantenimiento" not in detail
    assert "Tribología" not in detail
    assert "Evento registrado" not in detail and "TEST-EVENT-REF" not in detail
    assert "Referencia del evento" not in detail
    assert "19/05/2025 04:06" in detail
    assert "2025-05-18" in detail
    assert "mantenimiento preventivo semanal" in detail
    assert "baja presión" in detail
    assert "Resumen semanal de la unidad" in detail
    assert "Reporte no encontrado para muestra:" not in detail
    assert "No se pudo atribuir" not in detail
    assert "Engrase general" not in detail
    table = create_alerts_report_table(pd.DataFrame([row]))
    assert table.data[0]["Fuente"] == "Multitécnica"
    assert table.data[0]["Evidencia"] == "Telemetría + Mantenimiento"
    summary = callbacks.render_selected_alert_summary({"row": 0, "row_id": table.data[0]["id"]}, table.data)
    assert "mantenimiento preventivo semanal" in _visible(summary)
    assert "Sistema de Motor - Sistema de Enfriamiento" in _visible(summary)
    maintenance = callbacks._maintenance_context_summary(table.data[0])
    activities = [child for child in maintenance.children if getattr(child, "open", None) is True]
    assert len(activities) == 1
    assert "mantenimiento preventivo semanal" in _visible(activities[0])


def test_mixed_source_label_is_preserved_when_some_evidence_is_unavailable(tmp_path, monkeypatch):
    from dashboard.callbacks import alerts_callbacks as callbacks

    _, weekly = _write_case(tmp_path, monkeypatch)
    weekly.unlink()
    monkeypatch.setattr(callbacks, "load_telemetry_alert_detail_for_alert", lambda *args: pd.DataFrame())
    detail = _visible(callbacks.update_detail_view(_case()["FusionID"], "emin", None))
    assert "Multitécnica" in detail
    assert "Las evidencias disponibles no permiten mostrar todas sus fuentes" in detail
    assert "Tribología" not in detail
    assert "Reporte no encontrado" not in detail


def test_direct_oil_call_without_reference_does_not_load_data_or_print_an_empty_sample(monkeypatch):
    from dashboard.callbacks import alerts_callbacks as callbacks

    monkeypatch.setattr(callbacks, "load_oil_classified", lambda *args: pytest.fail("Empty sample must not query oil"))
    detail = _visible(callbacks.create_oil_evidence_section(pd.Series(_case()), "emin"))
    assert "no referencia ninguna muestra de aceite" in detail
    assert "Reporte no encontrado" not in detail


def test_oil_reference_and_sample_identifier_share_numeric_normalization(tmp_path, monkeypatch):
    from dashboard.callbacks import alerts_callbacks as callbacks

    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(callbacks, "load_oil_classified", lambda *args: pd.DataFrame({"sampleNumber": [123]}))
    detail = _visible(callbacks.create_oil_evidence_section(pd.Series(_case(OilReportNumber="123.0")), "emin"))
    assert "Reporte no encontrado" not in detail
    assert "essays_elements" in detail  # sample resolved; unrelated downstream file is absent
    assert alert_reference("123.0") == "123"


@pytest.mark.parametrize("file,day,included", [
    ("16-2025", "Lunes 21/04", True),
    ("15-2025", "Domingo 20/04", False),
    ("19-2025", "Domingo 18/05", True),
    ("20-2025", "Lunes 19/05", False),
    ("20-2025", "Domingo 25/05", False),
])
def test_actual_activity_date_enforces_iso_window_with_legacy_names(file, day, included):
    row = _legacy_row()
    row["Tasks_List"] = json.dumps({day: {"Sistema de Motor": ["Actividad con fecha"]}})
    result = resolve_emin_maintenance_evidence(_case(), {file: pd.DataFrame([row])})
    assert (result["evidence"] is not None) is included


def test_legacy_week_53_at_year_boundary_uses_actual_year_of_activity():
    row = _legacy_row()
    row["Tasks_List"] = json.dumps({"Domingo 05/01": {"Motor": ["Trabajo del año nuevo"]}})
    result = resolve_emin_maintenance_evidence(
        _case(Timestamp="2025-01-06T10:00:00Z"),
        {"53-2024": pd.DataFrame([row])},
    )
    assert result["status"] == "matched"
    assert result["evidence"].Semana == "01-2025"
    assert "2025-01-05" in result["evidence"].Tasks_List


def test_duplicate_iso_and_legacy_files_do_not_duplicate_activity_or_summary():
    row = _legacy_row()
    result = resolve_emin_maintenance_evidence(
        _case(), {"19-2025": pd.DataFrame([row]), "20-2025": pd.DataFrame([row])}
    )
    assert result["evidence"].Tasks_List.count("mantenimiento preventivo semanal") == 1
    assert result["evidence"].Summary.count("Se registró baja presión") == 1


def test_candidate_files_support_both_calendars_without_expanding_the_date_window():
    assert set(maintenance_files_for_alert(_case()["Timestamp"])) == {
        "16-2025", "17-2025", "18-2025", "19-2025", "20-2025"
    }
