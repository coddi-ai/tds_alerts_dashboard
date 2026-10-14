"""EMIN alert types come from data; maintenance context has a strict scope."""

import json

import pandas as pd
import pytest

from src.data.emin_alert_evidence import (
    enrich_emin_alert_evidence,
    evidence_label,
    maintenance_week,
    maintenance_weeks_for_alert,
    maintenance_window,
    resolve_emin_maintenance_evidence,
)
from src.data.loaders import load_alerts_data, load_emin_maintenance_evidence


def _alert(**changes):
    return {
        "FusionID": "F-1", "Timestamp": "2026-07-14T16:00:00Z",
        "UnitId": "E-01", "sistema": "motor", "subsistema": "engine",
        "componente": "engine", "Trigger_type": "Telemetria",
        "TelemetryID": "T-1", "TribologyID": "", "Trigger_Var": "EngCoolTemp",
        "mensaje_ia": "Hay detenciones y evidencia de mantenciones.",
        "Semana_Resumen_Mantencion": "28-2026",
        "has_telemetry": True, "has_tribology": False, **changes,
    }


def _weekly(**changes):
    return {
        "UnitId": "E-01", "Summary": "Inspección del motor.",
        "Tasks_List": json.dumps({"Viernes 10/07": {"Motor": ["Inspección de refrigeración"]}}),
        **changes,
    }


def _frames(**changes):
    return {"28-2026": pd.DataFrame([_weekly(**changes)])}


def _task(day, system="Motor", activity="Actividad válida"):
    return json.dumps({day: {system: [activity]}})


def _visible(component):
    if isinstance(component, str):
        return component
    if isinstance(component, (list, tuple)):
        return "\n".join(_visible(item) for item in component)
    return _visible(getattr(component, "children", []))


def test_maintenance_context_does_not_reclassify_published_telemetry():
    original = pd.DataFrame([_alert()])
    result = enrich_emin_alert_evidence(original, _frames())
    row = result.iloc[0]
    assert row.Trigger_type == row.Trigger_type_original == "Telemetria"
    assert row.has_telemetry and row.has_maintenance and not row.has_tribology
    assert evidence_label(row) == "Telemetría + Mantenimiento"
    assert original.iloc[0].Trigger_type == "Telemetria"
    assert "has_maintenance" not in original


@pytest.mark.parametrize("source_type", ["Telemetria", "Tribologia", "Mixto", "Otro"])
@pytest.mark.parametrize("context", [True, False])
def test_published_type_is_never_overridden_or_filtered(source_type, context):
    original = pd.DataFrame([_alert(Trigger_type=source_type)])
    result = enrich_emin_alert_evidence(original, _frames() if context else {})
    assert result.Trigger_type.tolist() == original.Trigger_type.tolist()
    assert result.Trigger_type_original.tolist() == original.Trigger_type.tolist()


@pytest.mark.parametrize("system", [
    "motor", " MOTOR ", "Sistema Motor", "Sistema de Motor",
    "Sistema de Motor - Sistema de Motor Básico", "Engine",
])
def test_matching_system_uses_contract_aliases(system):
    result = resolve_emin_maintenance_evidence(_alert(), _frames(Tasks_List=_task("2026-07-10", system)))
    assert result["status"] == "matched"
    assert "Actividad válida" in result["evidence"].Tasks_List


@pytest.mark.parametrize("system", ["Frenos", "Equipo - Equipo", "Sistema eléctrico", "Desconocido"])
def test_other_or_unknown_system_does_not_become_alert_evidence(system):
    # A narrative mention of Motor must never establish a system match.
    result = enrich_emin_alert_evidence(
        pd.DataFrame([_alert()]), _frames(Tasks_List=_task("2026-07-10", system))
    ).iloc[0]
    assert result.Trigger_type == "Telemetria"
    assert not result.has_maintenance
    assert result.maintenance_evidence_summary == ""
    assert result.maintenance_evidence_tasks == ""


@pytest.mark.parametrize("weekly", [
    pd.DataFrame(), pd.DataFrame([_weekly(UnitId="OTHER")]),
    pd.DataFrame([_weekly(Tasks_List="{}")]),
    pd.DataFrame([_weekly(Tasks_List="[]")]),
    pd.DataFrame([_weekly(Tasks_List="invalid-json")]),
    pd.DataFrame([_weekly(Tasks_List='{"2026-07-10": {"Motor": []}}')]),
    pd.DataFrame([_weekly(Tasks_List='["not-the-weekly-contract"]')]),
    pd.DataFrame([_weekly(Tasks_List='{"2026-07-10": "not-a-task-list"}')]),
    pd.DataFrame([_weekly(Tasks_List='{"Viernes": {"Motor": ["Sin fecha"]}}')]),
])
def test_summary_or_ia_text_alone_is_not_dated_system_evidence(weekly):
    result = enrich_emin_alert_evidence(pd.DataFrame([_alert()]), {"28-2026": weekly}).iloc[0]
    assert result.Trigger_type == "Telemetria"
    assert not result.has_maintenance


@pytest.mark.parametrize("week,day,included", [
    ("25-2026", "2026-06-15T00:00:00", True),
    ("24-2026", "2026-06-14T23:59:59", False),
    ("26-2026", "2026-06-23", True),
    ("28-2026", "2026-07-12T23:59:59", True),
    ("29-2026", "2026-07-13T00:00:00", False),
    ("23-2026", "2026-06-04", False),
    # Even a date written into the wrong weekly file must not escape validation.
    ("28-2026", "2026-07-13T00:00:00", False),
    ("25-2026", "2026-06-14T23:59:59", False),
])
def test_four_complete_iso_weeks_have_inclusive_start_and_exclusive_end(week, day, included):
    frames = {week: pd.DataFrame([_weekly(Tasks_List=_task(day))])}
    result = resolve_emin_maintenance_evidence(_alert(), frames)
    assert (result["evidence"] is not None) is included
    assert result["start"] == "2026-06-15T00:00:00"
    assert result["end"] == "2026-07-13T00:00:00"


def test_iso_window_crosses_year_with_valid_week_53():
    alert = _alert(Timestamp="2021-01-06T12:00:00Z")
    assert maintenance_weeks_for_alert(alert["Timestamp"]) == (
        "50-2020", "51-2020", "52-2020", "53-2020"
    )
    frames = {
        "50-2020": pd.DataFrame([_weekly(Tasks_List=_task("Lunes 07/12", activity="Límite inferior"))]),
        "53-2020": pd.DataFrame([_weekly(Tasks_List=_task("Domingo 03/01", activity="Año nuevo válido"))]),
        "01-2021": pd.DataFrame([_weekly(Tasks_List=_task("Lunes 04/01", activity="Semana excluida"))]),
        "49-2020": pd.DataFrame([_weekly(Tasks_List=_task("Domingo 06/12", activity="Antigua"))]),
    }
    result = resolve_emin_maintenance_evidence(alert, frames)
    assert result["start"] == "2020-12-07T00:00:00"
    assert result["end"] == "2021-01-04T00:00:00"
    assert "Límite inferior" in result["evidence"].Tasks_List
    assert "Año nuevo válido" in result["evidence"].Tasks_List
    assert "Semana excluida" not in result["evidence"].Tasks_List
    assert "Antigua" not in result["evidence"].Tasks_List
    assert maintenance_week("53-2020") == "53-2020"
    assert maintenance_week("53-2024") == ""


def test_alert_offset_uses_existing_utc_instant_and_maintenance_preserves_written_clock():
    # UTC Monday, despite Sunday in the explicit event offset.
    assert maintenance_window("2026-07-12T23:30:00-04:00")[1] == pd.Timestamp("2026-07-13")
    frames = {
        "28-2026": pd.DataFrame([_weekly(
            Tasks_List=_task("2026-07-12T23:30:00-04:00", activity="Reloj EMIN")
        )]),
    }
    result = resolve_emin_maintenance_evidence(_alert(), frames)
    assert "2026-07-12T23:30:00" in result["evidence"].Tasks_List
    assert "Reloj EMIN" in result["evidence"].Tasks_List


@pytest.mark.parametrize("day", ["Viernes", "Jueves 10/07", "2026-07-99", "2026-07-10T12:00:00+99:00", "10/99", "../10/07"])
def test_undetermined_or_invalid_dates_are_not_inferred(day):
    result = resolve_emin_maintenance_evidence(_alert(), _frames(Tasks_List=_task(day)))
    assert result["status"] == "undetermined"
    assert result["evidence"] is None


@pytest.mark.parametrize("changes,status", [
    ({"Timestamp": None}, "invalid_alert_date"),
    ({"Timestamp": "invalid"}, "invalid_alert_date"),
    ({"sistema": None}, "unknown_alert_system"),
    ({"sistema": "Equipo"}, "unknown_alert_system"),
    ({"UnitId": ""}, "missing_unit"),
])
def test_undetermined_alert_context_is_explicit(changes, status):
    result = resolve_emin_maintenance_evidence(_alert(**changes), _frames())
    assert result["status"] == status
    assert result["evidence"] is None


def test_same_unit_window_cache_separates_systems_and_preserves_mixed_sources():
    rows = [
        _alert(sistema="motor"),
        _alert(sistema="frenos", FusionID="F-2"),
        _alert(Trigger_type="Mixto", has_tribology=True, TribologyID="O-1", FusionID="F-3"),
        _alert(Trigger_type="Tribologia", has_telemetry=False, has_tribology=True, FusionID="F-4"),
    ]
    result = enrich_emin_alert_evidence(pd.DataFrame(rows), _frames())
    assert result.has_maintenance.tolist() == [True, False, True, True]
    assert result.Trigger_type.tolist() == ["Telemetria", "Telemetria", "Mixto", "Tribologia"]
    assert result.has_tribology.tolist() == [False, False, True, True]
    assert evidence_label(result.iloc[2]) == "Telemetría + Tribología + Mantenimiento"


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


def test_loader_refreshes_context_without_changing_published_type(tmp_path, monkeypatch):
    week_path = _write_dashboard_data(tmp_path, monkeypatch)
    assert load_alerts_data("EMIN").iloc[0].has_maintenance
    pd.DataFrame([_weekly(Tasks_List="{}")]).to_csv(week_path, index=False)
    assert not load_alerts_data("emin").iloc[0].has_maintenance
    pd.DataFrame([_weekly()]).to_csv(week_path, index=False)
    loaded = load_alerts_data("emin")
    assert loaded.iloc[0].Trigger_type == "Telemetria"
    loaded.loc[0, "has_tribology"] = True
    assert not load_alerts_data("emin").iloc[0].has_tribology
    week_path.unlink()
    assert not load_alerts_data("emin").iloc[0].has_maintenance


@pytest.mark.parametrize("client", ["cda", "capstone"])
def test_other_clients_keep_classification_and_detail_contract(tmp_path, monkeypatch, client):
    from dashboard.callbacks import alerts_callbacks as callbacks

    _write_dashboard_data(tmp_path, monkeypatch, client=client)
    loaded = load_alerts_data(client)
    assert loaded.iloc[0].Trigger_type == "Telemetria"
    assert "has_maintenance" not in loaded
    monkeypatch.setattr(callbacks, "load_emin_maintenance_evidence", lambda row: pytest.fail("EMIN resolver used for another client"))
    detail = _visible(callbacks.create_maintenance_evidence_section(pd.Series(_alert()), client))
    assert "Inspección del motor." in detail


def test_loader_reads_iso_and_legacy_names_without_week_reference_fallback(monkeypatch):
    from src.data import loaders

    calls = []
    def read(client, week):
        calls.append((client, week))
        return _frames().get(week, pd.DataFrame())
    monkeypatch.setattr(loaders, "load_maintenance_week", read)
    result = load_emin_maintenance_evidence(_alert(Semana_Resumen_Mantencion="../invalid"))
    assert calls == [("emin", week) for week in ("25-2026", "24-2026", "26-2026", "27-2026", "28-2026")]
    assert result["status"] == "matched"


def test_table_summary_and_detail_keep_source_type_and_show_matching_context(tmp_path, monkeypatch):
    from dashboard.components.alerts_tables import create_alerts_report_table
    from dashboard.components.alerts_report import alert_summary
    from dashboard.callbacks import alerts_callbacks as callbacks

    _write_dashboard_data(tmp_path, monkeypatch)
    loaded = load_alerts_data("emin")
    table = create_alerts_report_table(loaded)
    assert table.data[0]["Fuente"] == "Telemetría"
    assert table.data[0]["Evidencia"] == "Telemetría + Mantenimiento"
    assert alert_summary(loaded)["mixed"] == 0
    summary = _visible(callbacks.render_selected_alert_summary({"row": 0}, table.data))
    assert "Contexto de mantenciones" in summary and "28-2026" in summary
    assert "2026-06-15" in summary and "2026-07-13" in summary
    assert "Inspección del motor." in summary
    assert "Duración de detención: no informada" in summary
    detail = _visible(callbacks.create_maintenance_evidence_section(loaded.iloc[0], "emin"))
    assert "Inspección del motor." in detail and "Inspección de refrigeración" in detail
    assert "2026-06-15" in detail and "2026-07-13" in detail
    assert "Resumen semanal de la unidad" in detail
    assert "Multitécnica" not in summary
    assert "N/A" not in detail


def test_detail_and_summary_filter_tasks_by_system_across_four_weeks(tmp_path, monkeypatch):
    from dashboard.callbacks import alerts_callbacks as callbacks
    from dashboard.components.alerts_tables import create_alerts_report_table

    week_path = _write_dashboard_data(tmp_path, monkeypatch)
    tasks = json.dumps({"2026-07-10": {"Motor": ["Motor reciente"], "Frenos": ["Frenos incompatible"]}})
    pd.DataFrame([_weekly(Tasks_List=tasks)]).to_csv(week_path, index=False)
    older = week_path.parent / "25-2026.csv"
    pd.DataFrame([_weekly(Summary="Resumen inferior", Tasks_List=_task("2026-06-15", activity="Motor límite"))]).to_csv(older, index=False)
    for week, day in (("24-2026", "2026-06-14"), ("29-2026", "2026-07-13")):
        pd.DataFrame([_weekly(Summary="Resumen fuera", Tasks_List=_task(day, activity="Motor fuera"))]).to_csv(week_path.parent / f"{week}.csv", index=False)
    loaded = load_alerts_data("emin")
    table = create_alerts_report_table(loaded)
    summary = _visible(callbacks.render_selected_alert_summary({"row": 0}, table.data))
    detail = _visible(callbacks.create_maintenance_evidence_section(loaded.iloc[0], "emin"))
    for rendered in (summary, detail):
        assert "Motor reciente" in rendered and "Motor límite" in rendered
        assert "Resumen inferior" in rendered and "Inspección del motor." in rendered
        assert "Frenos incompatible" not in rendered
        assert "Motor fuera" not in rendered and "Resumen fuera" not in rendered
    assert loaded.iloc[0].Trigger_type == "Telemetria"


def test_detail_explains_unattributable_maintenance_without_changing_type(tmp_path, monkeypatch):
    from dashboard.callbacks import alerts_callbacks as callbacks

    week_path = _write_dashboard_data(tmp_path, monkeypatch)
    pd.DataFrame([_weekly(Tasks_List="{}")]).to_csv(week_path, index=False)
    loaded = load_alerts_data("emin")
    rendered = _visible(callbacks.create_maintenance_evidence_section(loaded.iloc[0], "emin"))
    assert "El resumen por sí solo no confirma" in rendered
    assert "Inspección del motor." not in rendered
    assert loaded.iloc[0].Trigger_type == "Telemetria"


@pytest.mark.parametrize("context", [True, False])
@pytest.mark.parametrize("source_type,sections", [
    ("Telemetria", ["telemetry", "maintenance"]),
    ("Mixto", ["telemetry", "oil", "maintenance"]),
    ("Tribologia", ["oil", "maintenance"]),
])
def test_detail_sections_follow_published_sources_with_or_without_maintenance(
    tmp_path, monkeypatch, context, source_type, sections,
):
    from dash import html
    from dashboard.callbacks import alerts_callbacks as callbacks

    week_path = _write_dashboard_data(tmp_path, monkeypatch)
    alerts_path = tmp_path / "alerts/golden/emin/consolidated_alerts.csv"
    pd.DataFrame([_alert(
        Trigger_type=source_type,
        TelemetryID="" if source_type == "Tribologia" else "T-1",
        TribologyID="O-1" if source_type in {"Mixto", "Tribologia"} else "",
    )]).to_csv(alerts_path, index=False)
    if not context:
        week_path.unlink()
    called = []
    for name in ("telemetry", "oil", "maintenance"):
        def render(row, client, name=name):
            called.append(name)
            return html.Div(name)
        monkeypatch.setattr(callbacks, f"create_{name}_evidence_section", render)
    detail = callbacks.update_detail_view("F-1", "emin", None)
    assert called == sections
    assert ("Multitécnica" in str(detail)) is (source_type == "Mixto")
    assert load_alerts_data("emin").iloc[0].Trigger_type == source_type


@pytest.mark.parametrize("missing_source", [True, False])
def test_missing_sensor_series_message_keeps_the_recorded_alert_clear(monkeypatch, missing_source):
    from dashboard.callbacks import alerts_callbacks as callbacks

    source = pd.DataFrame() if missing_source else pd.DataFrame({"AlertID": ["UNRELATED"], "Unit": ["OTHER"]})
    monkeypatch.setattr(callbacks, "load_telemetry_alert_detail_for_alert", lambda *args: source)
    rendered = str(callbacks.create_telemetry_evidence_section(pd.Series(_alert()), "emin"))
    assert "Evento registrado" in rendered and "series de sensores" in rendered
    assert "T-1" in rendered
    assert "No hay datos de telemetría" not in rendered
