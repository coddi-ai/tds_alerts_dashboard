import json
from pathlib import Path

import dash
import pandas as pd

from dashboard.tabs.tab_mantenciones_general import layout_mantenciones_general
from src.data import maintenance_repository as repository_module
from src.data.loaders import load_maintenance_actions_all_equipment
from src.data.maintenance_repository import MaintenanceRepository


def _actions():
    return pd.DataFrame(
        [
            {"action_id": "a1", "job_id": "j1", "record_id": "r1", "machine_id": "m1", "machine_code": "T_01", "event_ts": "2026-01-02T03:00:00Z", "change_date": "2026-01-02", "action_type_name": "Inspección", "job_system_name": "Motor", "job_subsystem_name": "Lubricación", "action_subsystem_name": "Lubricación", "action_system_name": "Motor", "action_detail_clean": "A", "component_names": [], "component_count": 0, "target_level": "COMPONENT", "source_system": "test", "record_original_text": ""},
            {"action_id": "a2", "job_id": "j1", "record_id": "r1", "machine_id": "m1", "machine_code": "T_01", "event_ts": "2026-01-03T03:00:00.000000Z", "change_date": "2026-01-03", "action_type_name": "Cambio", "job_system_name": "Motor", "job_subsystem_name": "Lubricación", "action_subsystem_name": "Lubricación", "action_system_name": "Motor", "action_detail_clean": "B", "component_names": [], "component_count": 0, "target_level": "COMPONENT", "source_system": "test", "record_original_text": ""},
            {"action_id": "a3", "job_id": "j2", "record_id": "r2", "machine_id": "m1", "machine_code": "T_01", "event_ts": "2026-01-05T04:00:00+00:00", "change_date": "2026-01-05", "action_type_name": "Reparación", "job_system_name": "Hidráulico", "job_subsystem_name": "Bomba", "action_subsystem_name": "Bomba", "action_system_name": "Hidráulico", "action_detail_clean": "C", "component_names": [], "component_count": 0, "target_level": "SUBSYSTEM", "source_system": "test", "record_original_text": ""},
            {"action_id": "a4", "job_id": "j3", "record_id": "r3", "machine_id": "m2", "machine_code": "T_02", "event_ts": "2026-01-06T05:00:00Z", "change_date": "2026-01-06", "action_type_name": "Inspección", "job_system_name": None, "job_subsystem_name": None, "action_subsystem_name": None, "action_system_name": None, "action_detail_clean": None, "component_names": [], "component_count": 0, "target_level": "COMPONENT", "source_system": "test", "record_original_text": ""},
        ]
    )


def test_loader_normalizes_mixed_iso_timestamps(tmp_path):
    frame = _actions()
    frame.to_parquet(tmp_path / "query_3_actions_all_equipment.parquet", index=False)
    loaded = load_maintenance_actions_all_equipment("cda", base_path=tmp_path)
    assert str(loaded["event_ts"].dtype).endswith(", UTC]")
    assert str(loaded["change_date"].dtype).endswith(", UTC]")
    assert loaded["event_ts"].notna().all()


def test_monthly_payload_counts_actions_not_inferred_failures(monkeypatch):
    frame = _actions()
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload("2026-01")
    assert payload["status"] == "ok"
    assert payload["kpis"] == {"equipment": 2, "actions": 4, "records": 3, "systems": 2}
    assert payload["data"]["pareto"] == [{"equipment": "T_01", "count": 2, "cumulative_pct": 100.0}]
    assert payload["meta"]["pareto_scope"]["dimension"] == "equipment"
    assert payload["meta"]["pareto_scope"]["metric"] == "unique_action_id_count"
    assert json.dumps(payload)


def test_monthly_filters_and_empty_period(monkeypatch):
    frame = _actions()
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    filtered = repo.get_monthly_payload("2026-01", systems=["Motor"], equipment=["T_01"], subsystems=["Lubricación"])
    assert filtered["kpis"]["actions"] == 2
    assert {row["equipment"] for row in filtered["data"]["pareto"]} == {"T_01"}

    empty = repo.get_monthly_payload("2025-12")
    assert empty["status"] == "empty"
    assert empty["kpis"]["actions"] == 0


def test_motor_pareto_groups_and_orders_equipment_without_other_systems(monkeypatch):
    frame = _actions().copy()
    frame.loc[frame["action_id"] == "a3", ["machine_code", "action_system_name"]] = ["T_02", "Sistema de Motor"]
    frame.loc[frame["action_id"] == "a4", ["machine_code", "action_system_name"]] = ["T_02", "Sistema Hidráulico"]
    motor_extra = frame.iloc[[0]].copy()
    motor_extra["action_id"] = "a5"
    motor_extra["machine_code"] = "T_02"
    motor_extra["action_system_name"] = "Motor"
    motor_extra["change_date"] = "2026-01-07"
    motor_extra["event_ts"] = "2026-01-07T05:00:00Z"
    frame = pd.concat([frame, motor_extra], ignore_index=True)

    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    pareto = repo.get_monthly_payload("2026-01")["data"]["pareto"]

    assert pareto == [
        {"equipment": "T_01", "count": 2, "cumulative_pct": 50.0},
        {"equipment": "T_02", "count": 2, "cumulative_pct": 100.0},
    ]
    assert all("Hidráulico" not in str(row) for row in pareto)


def test_equipment_pareto_builder_uses_equipment_axis():
    from dashboard.tabs.tab_mantenciones_general import create_equipment_pareto_chart

    figure = create_equipment_pareto_chart(
        pd.DataFrame(
            [
                {"equipment": "T_02", "count": 3, "cumulative_pct": 75.0},
                {"equipment": "T_01", "count": 1, "cumulative_pct": 100.0},
            ]
        )
    )

    assert list(figure.data[0].x) == ["T_02", "T_01"]
    assert figure.layout.xaxis.title.text == "Equipo"


def test_weekly_parser_reports_invalid_json(monkeypatch):
    monkeypatch.setattr(repository_module, "list_maintenance_weeks", lambda client: ["03-2026"])
    monkeypatch.setattr(
        repository_module,
        "load_maintenance_week",
        lambda client, week: pd.DataFrame(
            [
                {"UnitId": "T_01", "Summary": "Resumen", "Tasks_List": '{"Lunes": {"Motor": ["Inspección"]}}'},
                {"UnitId": "T_02", "Summary": None, "Tasks_List": "not-json"},
            ]
        ),
    )
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_weekly_evidence("03-2026")
    assert payload["status"] == "partial"
    assert payload["meta"]["invalid_rows"] == 1
    assert payload["tasks"][0]["system_name"] == "Motor"


def test_layout_keeps_future_views_mounted_but_only_summary_visible():
    layout = layout_mantenciones_general()
    tabs = next(component for component in layout.children if getattr(component, "id", None) == "maintenance-tabs")
    summary, activity, weekly = tabs.children

    assert summary.value == "summary"
    assert not getattr(summary, "disabled", False)
    assert activity.value == "activity"
    assert activity.disabled is True
    assert activity.style == {"display": "none"}
    assert weekly.value == "weekly"
    assert weekly.disabled is True
    assert weekly.style == {"display": "none"}

    # The hidden tabs remain mounted so their callback targets are still part
    # of the page contract and can be re-enabled without rebuilding them.
    rendered = str(layout)
    assert "maintenance-activity-table" in rendered
    assert "maintenance-week-task-table" in rendered
    assert "Equipos Sanos" not in rendered
    assert "Horas Detenidas" not in rendered


def test_callbacks_register_on_concrete_app_and_layout_ids_are_unique():
    from dashboard.callbacks.mantenciones_general_callbacks import register_mantenciones_general_callbacks

    app = dash.Dash(__name__)
    app.layout = layout_mantenciones_general()
    register_mantenciones_general_callbacks(app)

    output_keys = list(app.callback_map)
    assert len(output_keys) == 6
    assert any("maintenance-monthly-store" in key for key in output_keys)
    output_ids = []
    for entry in app.callback_map.values():
        outputs = entry["output"] if isinstance(entry["output"], list) else [entry["output"]]
        output_ids.extend((output.component_id, output.component_property) for output in outputs)
    assert len(output_ids) == len(set(output_ids))


def test_mantenciones_service_is_enabled_for_cda_emin_and_capstone():
    config_path = Path(__file__).parents[1] / "config" / "client_services.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for client in ("CDA", "EMIN", "CAPSTONE"):
        assert config[client]["monitoring-mantenciones"]["display"] is True
    assert config.get("ENEX", {}).get("monitoring-mantenciones", {}).get("display", False) is False


def test_missing_or_corrupt_action_source_is_explicit(monkeypatch, tmp_path):
    source_dir = tmp_path / "Maintance_Labeler_Views"
    source_dir.mkdir()
    (source_dir / "query_3_actions_all_equipment.parquet").write_bytes(b"not-a-parquet")
    monkeypatch.setattr(repository_module, "_get_mantentions_data_path", lambda client: source_dir)
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload()
    assert payload["status"] == "error"
    assert payload["meta"]["source_status"] == "error"
