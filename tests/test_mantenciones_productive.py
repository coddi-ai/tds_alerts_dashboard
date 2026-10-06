import json
from pathlib import Path

import dash
import pandas as pd
import pytest

from dashboard.tabs.tab_mantenciones_general import layout_mantenciones_general
from src.data import maintenance_repository as repository_module
from src.data.loaders import (
    load_maintenance_actions_all_equipment,
    load_maintenance_unit_records_actions,
    load_business_kpis,
    load_maintenance_intervention_hours_daily,
    load_maintenance_intervention_hours_monthly,
    load_maintenance_fleet_intervention_daily,
    load_maintenance_equipment_status,
)
from src.data.maintenance_repository import MaintenanceRepository


def test_component_view_mixed_offsets_follow_client_clock_contract(tmp_path):
    from src.data.loaders import load_maintenance_component_maintenance
    pd.DataFrame({
        "event_ts": ["2026-07-31T23:30:00-03:00", "2026-08-01T02:30:00Z", "2026-08-01 02:30:00"],
        "change_date": ["2026-07-31T23:30:00-03:00", "2026-08-01T02:30:00Z", "2026-08-01 02:30:00"],
    }).to_parquet(tmp_path / "query_1_component_maintenance.parquet", index=False)
    cda = load_maintenance_component_maintenance("cda", base_path=tmp_path)
    assert str(cda["event_ts"].dtype).endswith(", UTC]")
    assert cda["event_ts"].nunique() == 1
    emin = load_maintenance_component_maintenance("emin", base_path=tmp_path)
    assert emin["event_ts"].dt.tz is None
    assert emin.loc[0, "event_ts"].month == 7


def test_emin_large_pareto_keeps_the_initial_80_percent_prefix_with_readable_axis_labels():
    from dashboard.tabs.tab_mantenciones_general import create_emin_hours_pareto_chart
    rows = pd.DataFrame({"equipment": [f"EQ-{i:03d}" for i in range(200)], "value": list(range(200, 0, -1))})
    figure = create_emin_hours_pareto_chart(rows)
    assert len(figure.data[0].x) == len(figure.data[1].x) < 200
    assert len(figure.layout.xaxis.tickvals) <= 6
    assert figure.layout.xaxis.tickvals[0] == "EQ-000"
    assert figure.layout.xaxis.tickvals[-1] == figure.data[0].x[-1]


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
    emin_loaded = load_maintenance_actions_all_equipment("emin", base_path=tmp_path)
    assert str(loaded["event_ts"].dtype).endswith(", UTC]")
    assert str(loaded["change_date"].dtype).endswith(", UTC]")
    assert loaded["event_ts"].notna().all()
    assert emin_loaded["event_ts"].dt.tz is None
    assert emin_loaded.loc[0, "event_ts"].hour == 3


def test_record_loader_normalizes_source_interval_timestamps(tmp_path):
    frame = pd.DataFrame(
        [
            {"record_id": "r1", "machine_code": "T_01", "first_event_ts": "2026-01-02T03:00:00Z", "last_event_ts": "2026-01-03T03:00:00.000000Z"},
        ]
    )
    frame.to_parquet(tmp_path / "query_2_unit_records_actions.parquet", index=False)
    loaded = load_maintenance_unit_records_actions("cda", base_path=tmp_path)
    assert str(loaded["first_event_ts"].dtype).endswith(", UTC]")
    assert str(loaded["last_event_ts"].dtype).endswith(", UTC]")
    assert loaded["last_event_ts"].notna().all()
    emin_loaded = load_maintenance_unit_records_actions("emin", base_path=tmp_path)
    assert emin_loaded["last_event_ts"].dt.tz is None
    assert emin_loaded.loc[0, "first_event_ts"].hour == 3


def test_new_calendar_view_loaders_preserve_local_calendar_clock(tmp_path):
    pd.DataFrame(
        [
            {
                "machine_code": "T_01",
                "year_month": "2026-01",
                "intervention_hours": 4.0,
                "calendar_hours_month": 744.0,
                "reference_date": "2026-01-31 23:59:00",
            }
        ]
    ).to_parquet(tmp_path / "query_4_business_kpis.parquet", index=False)
    pd.DataFrame(
        [
            {
                "machine_code": "T_01",
                "day": "2026-01-02",
                "intervention_hours": 4.0,
                "n_records_touching_day": 1,
            }
        ]
    ).to_parquet(tmp_path / "query_7_intervention_hours_daily.parquet", index=False)
    pd.DataFrame(
        [
            {
                "machine_code": "T_01",
                "year_month": "2026-01",
                "intervention_hours": 4.0,
                "calendar_hours_month": 744.0,
            }
        ]
    ).to_parquet(tmp_path / "query_8_intervention_hours_monthly.parquet", index=False)
    pd.DataFrame(
        [
            {
                "day": "2026-01-02",
                "intervention_hours": 4.0,
                "n_machines_intervened": 1,
            }
        ]
    ).to_parquet(tmp_path / "query_9_fleet_intervention_daily.parquet", index=False)
    pd.DataFrame(
        [
            {
                "machine_code": "T_01",
                "equipment_status": "OPERATIVO",
                "has_open_intervention": False,
                "reference_date": "2026-01-02 12:00:00",
            }
        ]
    ).to_parquet(tmp_path / "query_10_equipment_status.parquet", index=False)

    daily = load_maintenance_intervention_hours_daily("cda", base_path=tmp_path)
    business = load_business_kpis("cda", base_path=tmp_path)
    monthly = load_maintenance_intervention_hours_monthly("cda", base_path=tmp_path)
    fleet = load_maintenance_fleet_intervention_daily("cda", base_path=tmp_path)
    status = load_maintenance_equipment_status("cda", base_path=tmp_path)

    assert daily["day"].dt.tz is None
    assert fleet["day"].dt.tz is None
    assert status["reference_date"].dt.tz is None
    assert business["reference_date"].dt.tz is None
    assert business.loc[0, "intervention_hours"] == 4.0
    assert monthly.loc[0, "year_month"] == "2026-01"


def _canonical_view_frames():
    actions = _actions()
    actions["change_date"] = pd.to_datetime(actions["change_date"], utc=True, format="mixed")
    actions["event_ts"] = pd.to_datetime(actions["event_ts"], utc=True, format="mixed")
    monthly = pd.DataFrame(
        [
            {"machine_code": "T_01", "year_month": "2026-01", "intervention_hours": 10.0, "calendar_hours_month": 744.0, "n_days_with_intervention": 2},
            {"machine_code": "T_02", "year_month": "2026-01", "intervention_hours": 20.0, "calendar_hours_month": 744.0, "n_days_with_intervention": 1},
        ]
    )
    daily = pd.DataFrame(
        [
            {"machine_code": "T_01", "day": "2026-01-01", "intervention_hours": 10.0},
            {"machine_code": "T_02", "day": "2026-01-01", "intervention_hours": 20.0},
        ]
    )
    fleet = pd.DataFrame(
        [
            {"day": "2026-01-01", "n_machines_intervened": 2, "intervention_hours": 30.0},
            {"day": "2026-01-02", "n_machines_intervened": 0, "intervention_hours": 0.0},
        ]
    )
    status = pd.DataFrame(
        [
            {"machine_code": "T_01", "equipment_status": "DETENIDO", "has_open_intervention": True},
            {"machine_code": "T_02", "equipment_status": "OPERATIVO", "has_open_intervention": False},
        ]
    )
    return actions, monthly, daily, fleet, status


def _emin_ten_view_frames():
    actions = _actions()
    actions["action_system_name"] = [
        "Sistema de Motor", "Sistema de Motor", "Sistema Hidráulico", None,
    ]
    actions = pd.concat([actions, actions.iloc[[0]]], ignore_index=True)
    component_actions = pd.DataFrame([
        {"action_id": "a1", "machine_code": "T_01", "component_name": "Bomba de inyección", "change_date": "2026-01-02T03:00:00-03:00"},
    ])
    records = pd.DataFrame([
        {"record_id": "r1", "machine_code": "T_01", "first_event_ts": "2026-01-02T03:00:00-03:00", "last_event_ts": "2026-01-02T07:00:00-03:00"},
        {"record_id": "r2", "machine_code": "T_01", "first_event_ts": "2026-01-05T04:00:00Z", "last_event_ts": "2026-01-05T05:00:00Z"},
    ])
    quality = pd.DataFrame([
        {"machine_code": "T_01", "year_month": "2026-01", "intervention_hours": 5.0, "calendar_hours_month": 744.0, "is_partial_month": True, "touched_by_long_record": True},
        {"machine_code": "T_02", "year_month": "2026-01", "intervention_hours": 1.0, "calendar_hours_month": 744.0, "is_partial_month": True, "touched_by_long_record": False},
    ])
    reliability = pd.DataFrame([
        {"source_system": "EMIN", "machine_code": "T_01", "year_month": "2026-01", "n_failures": 2, "mttr_hours": 3.0, "total_downtime_hours": 6.0, "n_mtbf_intervals": 1, "mtbf_hours": 12.0, "low_confidence": True},
        {"source_system": "EMIN", "machine_code": "T_02", "year_month": "2026-01", "n_failures": 1, "mttr_hours": 3.0, "total_downtime_hours": 3.0, "n_mtbf_intervals": 2, "mtbf_hours": 21.0, "low_confidence": False},
    ])
    failures = pd.DataFrame([
        {"machine_code": "T_01", "component_name": "Bomba", "n_failure_records": 4, "n_failure_actions": 6},
        {"machine_code": "T_02", "component_name": "Alternador", "n_failure_records": 2, "n_failure_actions": 3},
    ])
    daily = pd.DataFrame([
        {"source_system": "EMIN", "machine_code": "T_01", "day": "2026-01-01", "intervention_hours": 4.0},
        {"source_system": "EMIN", "machine_code": "T_01", "day": "2026-01-04", "intervention_hours": 1.0},
        {"source_system": "EMIN", "machine_code": "T_02", "day": "2026-01-01", "intervention_hours": 1.0},
    ])
    monthly = pd.DataFrame([
        {"source_system": "EMIN", "machine_code": "T_01", "year_month": "2026-01", "intervention_hours": 5.0, "calendar_hours_month": 744.0},
        {"source_system": "EMIN", "machine_code": "T_02", "year_month": "2026-01", "intervention_hours": 1.0, "calendar_hours_month": 744.0},
    ])
    fleet = pd.DataFrame([
        {"source_system": "EMIN", "day": "2026-01-01", "intervention_hours": 5.0, "calendar_hours_fleet": 48.0, "n_machines_intervened": 2, "n_machines_fleet": 2},
        {"source_system": "EMIN", "day": "2026-01-04", "intervention_hours": 1.0, "calendar_hours_fleet": 48.0, "n_machines_intervened": 1, "n_machines_fleet": 2},
    ])
    status = pd.DataFrame([
        {"source_system": "EMIN", "machine_code": "T_01", "equipment_status": "OPERATIVO", "has_open_intervention": False, "last_action_date": "2026-01-05", "days_since_last_maintenance": 2, "reference_date": "2026-01-06 10:00:00", "n_long_records": 1},
        {"source_system": "EMIN", "machine_code": "T_02", "equipment_status": "OPERATIVO", "has_open_intervention": False, "last_action_date": "2026-01-06", "days_since_last_maintenance": 1, "reference_date": "2026-01-06 10:00:00", "n_long_records": 0},
    ])
    return actions, component_actions, records, quality, reliability, failures, daily, monthly, fleet, status


def _patch_emin_ten_views(monkeypatch):
    frames = _emin_ten_view_frames()
    loaders = (
        "load_maintenance_actions_all_equipment",
        "load_maintenance_component_maintenance",
        "load_maintenance_unit_records_actions",
        "load_business_kpis",
        "load_maintenance_reliability_monthly",
        "load_maintenance_component_failure_ranking",
        "load_maintenance_intervention_hours_daily",
        "load_maintenance_intervention_hours_monthly",
        "load_maintenance_fleet_intervention_daily",
        "load_maintenance_equipment_status",
    )
    for loader, frame in zip(loaders, frames):
        monkeypatch.setattr(repository_module, loader, lambda client, frame=frame: frame.copy())
    return frames


def test_emin_global_system_filter_includes_general_and_scopes_attributed_metrics(monkeypatch):
    frames = _patch_emin_ten_views(monkeypatch)
    actions = frames[0].copy()
    general_action = actions.iloc[[0]].copy()
    general_action["action_id"] = "general-action"
    general_action["record_id"] = "general-record"
    general_action["action_system_name"] = "Equipo"
    actions = pd.concat([actions, general_action], ignore_index=True)
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: actions.copy())
    repo = MaintenanceRepository(mode="parquet", client="emin")

    all_systems = repo.get_monthly_payload("2026-01")
    available = all_systems["meta"]["filter_systems"]
    assert "Equipo" in available
    assert all_systems["kpis"]["actions"] == 5
    assert sum(row["value"] for row in all_systems["data"]["emin_hours_pareto"]) == 6.0

    general_only = repo.get_monthly_payload("2026-01", systems=["Equipo"])
    assert general_only["filters"]["systems"] == ["Equipo"]
    assert general_only["kpis"]["actions"] == 1
    assert {row["system_name"] for row in general_only["data"]["system_mix"]} == {"Equipo"}
    assert general_only["kpis"]["downtime_est_hours"] is None
    assert general_only["data"]["emin_hours_pareto"] == []
    assert general_only["data"]["daily"]
    assert all(row["hours_out_of_service"] is None for row in general_only["data"]["daily"])

    without_general = [system for system in available if system != "Equipo"]
    excluded = repo.get_monthly_payload("2026-01", systems=without_general)
    assert excluded["kpis"]["actions"] == 4
    assert "Equipo" not in {row["system_name"] for row in excluded["data"]["system_mix"]}
    assert excluded["meta"]["pareto"]["system_filter_partial"] is True

    from types import SimpleNamespace
    from dashboard.callbacks import mantenciones_general_callbacks as callbacks

    monkeypatch.setattr(callbacks, "get_repository", lambda **kwargs: repo)
    monkeypatch.setattr(callbacks, "ctx", SimpleNamespace(triggered_id=None))
    handlers = _capture_maintenance_callbacks()
    metadata = handlers["load_maintenance_metadata"]("EMIN", None)
    options, selection = metadata[-2:]
    assert {option["value"] for option in options} == set(available)
    assert set(selection) == set(available)
    assert next(option["label"] for option in options if option["value"] == "Equipo") == "General del equipo (sin sistema técnico atribuido)"

    payload, _ = handlers["load_monthly_payload"](
        "EMIN", "2026-01", [], "__all__", ["Equipo"],
        None, None, None, [], "actions", None,
    )
    assert payload["filters"]["systems"] == ["Equipo"]
    assert payload["kpis"]["actions"] == 1


def test_emin_ten_view_payload_reconciles_hours_and_scopes_pareto_independently(monkeypatch):
    _patch_emin_ten_views(monkeypatch)
    repo = MaintenanceRepository(mode="parquet", client="emin")

    all_systems_hours = repo.get_monthly_payload("2026-01", pareto_metric="hours")
    assert all_systems_hours["status"] == "ok"
    assert all_systems_hours["kpis"]["downtime_est_hours"] == 6.0
    assert all_systems_hours["kpis"]["availability_est_pct"] == 93.8
    assert all_systems_hours["kpis"]["mtbf_est_hours"] == 18.0
    assert all_systems_hours["kpis"]["mttr_est_hours"] == 3.0
    assert all_systems_hours["meta"]["estimated_kpis"]["coverage"]["partial_month"] is True
    reconciliation = all_systems_hours["meta"]["estimated_kpis"]["reconciliation"]
    assert reconciliation["status"] == "consistent"
    assert reconciliation["source_totals_hours"] == {
        "query_7": 6.0, "query_8": 6.0, "query_4": 6.0, "query_9": 6.0,
    }
    assert all_systems_hours["meta"]["reliability_kpis"]["low_confidence_rows"] == 1
    assert sum(row["value"] for row in all_systems_hours["data"]["pareto"]) == 6.0
    zero_action_day = next(row for row in all_systems_hours["data"]["daily"] if row["date"] == "2026-01-04")
    assert zero_action_day["count"] == 0
    assert zero_action_day["hours_out_of_service"] == 1.0
    assert all_systems_hours["data"]["unit_status"][0]["equipment"] == "T_01"
    action_detail = next(row for row in all_systems_hours["data"]["detail"] if row["action_id"] == "a1")
    assert action_detail["component"] == "Bomba de inyección"
    assert action_detail["intervention_start"] == "2026-01-02 03:00"
    assert all_systems_hours["data"]["historical_failures"][0]["component_name"] == "Bomba"

    # A partial system scope filters action views and makes system-unattributed
    # time metrics unavailable. Selecting every system keeps total hours.
    one_system = repo.get_monthly_payload("2026-01", systems=["Sistema de Motor"])
    several_systems = repo.get_monthly_payload(
        "2026-01", systems=["Sistema de Motor", "Sistema Hidráulico", "Sin sistema"]
    )
    no_systems = repo.get_monthly_payload("2026-01", systems=[])
    assert one_system["meta"]["pareto"]["selected_systems"] == ["Sistema de Motor"]
    assert one_system["meta"]["pareto"]["system_filter_partial"] is True
    assert one_system["meta"]["pareto"]["hours_available"] is False
    assert one_system["kpis"]["actions"] == 2
    assert one_system["kpis"]["downtime_est_hours"] is None
    assert one_system["data"]["emin_hours_pareto"] == []
    assert next(row["count"] for row in one_system["data"]["pareto"] if row["equipment"] == "T_01") == 2
    assert several_systems["meta"]["pareto"]["selected_systems"] == ["Sistema de Motor", "Sistema Hidráulico", "Sin sistema"]
    assert several_systems["kpis"]["downtime_est_hours"] == 6.0
    assert no_systems["kpis"] == all_systems_hours["kpis"]
    assert no_systems["meta"]["pareto"]["selected_systems"] == all_systems_hours["meta"]["pareto"]["available_systems"]

    unit = repo.get_monthly_payload("2026-01", equipment=["T_01"])
    assert unit["kpis"]["downtime_est_hours"] == 5.0
    assert unit["kpis"]["availability_est_pct"] == 89.6
    assert unit["meta"]["time_measure"]["source"] == "query_7_intervention_hours_daily.parquet"
    assert unit["meta"]["estimated_kpis"]["reconciliation"]["status"] == "consistent"

    partial_hours = repo.get_monthly_payload("2026-01", systems=["Sistema de Motor"])
    assert partial_hours["meta"]["pareto"]["hours_available"] is False
    assert "no se atribuyen a sistemas" in partial_hours["meta"]["pareto"]["reason"]

    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: pd.DataFrame())
    no_actions_repo = MaintenanceRepository(mode="parquet", client="emin")
    monkeypatch.setattr(no_actions_repo, "_actions_source_state", lambda: ("missing", "query_3 ausente"))
    hours_only = no_actions_repo.get_monthly_payload("2026-01")
    assert hours_only["status"] == "ok"
    assert hours_only["meta"]["source_status"] == "partial"
    assert hours_only["kpis"]["availability_est_pct"] == 93.8
    assert hours_only["kpis"]["downtime_est_hours"] == 6.0
    assert sum(row["value"] for row in hours_only["data"]["emin_hours_pareto"]) == 6.0
    assert hours_only["data"]["emin_action_systems"] == []


def test_monthly_payload_uses_canonical_monthly_and_fleet_views(monkeypatch):
    actions, monthly, daily, fleet, status = _canonical_view_frames()
    business = monthly.copy()
    business["downtime_hours_70d"] = 9999.0
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: actions.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_unit_records_actions", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: business.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_reliability_monthly", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_component_failure_ranking", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_intervention_hours_monthly", lambda client: monthly.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_intervention_hours_daily", lambda client: daily.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_fleet_intervention_daily", lambda client: fleet.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_equipment_status", lambda client: status.copy())

    repo = MaintenanceRepository(mode="parquet", client="cda")
    payload = repo.get_monthly_payload("2026-01")

    assert payload["status"] == "ok"
    assert payload["kpis"]["downtime_est_hours"] == 30.0
    assert payload["kpis"]["availability_est_pct"] == 98.0
    assert payload["data"]["daily"][:2] == [
        {"date": "2026-01-01", "count": 0, "equipment_count": 2, "hours_out_of_service": 30.0},
        {"date": "2026-01-02", "count": 1, "equipment_count": 0, "hours_out_of_service": 0.0},
    ]
    assert payload["meta"]["estimated_kpis"]["source"] == ["query_4_business_kpis.parquet"]
    assert payload["meta"]["time_measure"]["source"] == "query_9_fleet_intervention_daily.parquet"
    assert payload["kpis"]["downtime_est_hours"] != 9999.0


def test_equipment_filter_uses_query7_instead_of_fleet_total(monkeypatch):
    actions, monthly, daily, fleet, status = _canonical_view_frames()
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: actions.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_unit_records_actions", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_reliability_monthly", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_component_failure_ranking", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_intervention_hours_monthly", lambda client: monthly.loc[monthly.machine_code.eq("T_01")].copy())
    monkeypatch.setattr(repository_module, "load_maintenance_intervention_hours_daily", lambda client: daily.loc[daily.machine_code.eq("T_01")].copy())
    monkeypatch.setattr(repository_module, "load_maintenance_fleet_intervention_daily", lambda client: fleet.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_equipment_status", lambda client: status.copy())

    payload = MaintenanceRepository(mode="parquet", client="cda").get_monthly_payload(
        "2026-01", equipment=["T_01"]
    )

    assert payload["kpis"]["downtime_est_hours"] == 10.0
    assert payload["data"]["daily"][0]["equipment_count"] == 1
    assert payload["meta"]["time_measure"]["source"] == "query_7_intervention_hours_daily.parquet"


def test_fleet_equipment_counts_survive_query9_source_index_offset(monkeypatch):
    actions, monthly, daily, fleet, status = _canonical_view_frames()
    fleet = pd.concat(
        [
            pd.DataFrame(
                [{"day": "2025-12-31", "n_machines_intervened": 9, "intervention_hours": 4.0}]
            ),
            fleet,
        ],
        ignore_index=True,
    )
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: actions.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_unit_records_actions", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: monthly.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_reliability_monthly", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_component_failure_ranking", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_intervention_hours_monthly", lambda client: monthly.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_intervention_hours_daily", lambda client: daily.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_fleet_intervention_daily", lambda client: fleet.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_equipment_status", lambda client: status.copy())

    payload = MaintenanceRepository(mode="parquet", client="cda").get_monthly_payload("2026-01")

    assert payload["data"]["daily"][:2] == [
        {"date": "2026-01-01", "count": 0, "equipment_count": 2, "hours_out_of_service": 30.0},
        {"date": "2026-01-02", "count": 1, "equipment_count": 0, "hours_out_of_service": 0.0},
    ]


def test_status_counts_use_query10_equipment_status(monkeypatch):
    _, _, _, _, status = _canonical_view_frames()
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: _actions())
    monkeypatch.setattr(repository_module, "load_maintenance_unit_records_actions", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_reliability_monthly", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_component_failure_ranking", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_intervention_hours_monthly", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_intervention_hours_daily", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_fleet_intervention_daily", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_equipment_status", lambda client: status.copy())

    result = MaintenanceRepository(mode="parquet", client="cda").get_status_counts()
    counts = dict(zip(result["machine_status"], result["n_machines"]))
    assert counts == {"DETENIDO": 1, "SANO": 1}


def test_reliability_payload_preserves_missing_metrics_and_low_confidence(monkeypatch):
    reliability = pd.DataFrame(
        [
            {
                "source_system": "EMIN",
                "machine_id": "m1",
                "machine_code": "BULL-022",
                "year_month": "2026-01",
                "n_failures": 1,
                "mttr_hours": 4.0,
                "total_downtime_hours": 4.0,
                "n_mtbf_intervals": 1,
                "mtbf_hours": float("nan"),
                "mttf_hours": float("nan"),
                "low_confidence": True,
            },
            {
                "source_system": "EMIN",
                "machine_id": "m2",
                "machine_code": "BULL-024",
                "year_month": "2026-01",
                "n_failures": 4,
                "mttr_hours": 2.5,
                "total_downtime_hours": 10.0,
                "n_mtbf_intervals": 3,
                "mtbf_hours": 20.0,
                "mttf_hours": 17.5,
                "low_confidence": False,
            },
        ]
    )
    components = pd.DataFrame(
        [
            {"source_system": "EMIN", "machine_id": "m2", "machine_code": "BULL-024", "component_id": "c2", "component_name": "Motor", "n_failure_records": 3, "n_failure_actions": 5},
            {"source_system": "EMIN", "machine_id": "m1", "machine_code": "BULL-022", "component_id": "c1", "component_name": "Bomba", "n_failure_records": 1, "n_failure_actions": 2},
        ]
    )
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: _actions())
    monkeypatch.setattr(repository_module, "load_maintenance_unit_records_actions", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_maintenance_reliability_monthly", lambda client: reliability.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_component_failure_ranking", lambda client: components.copy())
    repo = MaintenanceRepository(mode="parquet", client="emin")

    payload = repo.get_reliability_payload("2026-01")

    assert payload["status"] == "ok"
    assert payload["meta"]["low_confidence_rows"] == 1
    assert payload["data"]["monthly"][0]["mtbf_hours"] is None
    assert payload["data"]["monthly"][0]["mttf_hours"] is None
    assert payload["data"]["components"][0]["component_name"] == "Motor"
    assert json.dumps(payload, allow_nan=False)


def test_reliability_charts_mark_low_confidence_without_imputing_nan():
    from dashboard.tabs.tab_mantenciones_general import (
        create_reliability_mtbf_mttf_chart,
        create_reliability_mttr_downtime_chart,
    )

    frame = pd.DataFrame(
        [
            {"year_month": "2026-01", "machine_code": "BULL-022", "mtbf_hours": None, "mttf_hours": None, "mttr_hours": 4.0, "total_downtime_hours": 4.0, "low_confidence": True},
            {"year_month": "2026-02", "machine_code": "BULL-022", "mtbf_hours": 20.0, "mttf_hours": 17.0, "mttr_hours": 3.0, "total_downtime_hours": 3.0, "low_confidence": False},
        ]
    )
    mtbf_mttf = create_reliability_mtbf_mttf_chart(frame)
    mttr_downtime = create_reliability_mttr_downtime_chart(frame)

    assert any(trace.marker.symbol == "diamond-open" for trace in mtbf_mttf.data if hasattr(trace, "marker")) or any(annotation.text == "⚠" for annotation in (mtbf_mttf.layout.annotations or []))
    assert any(getattr(trace.marker, "symbol", None) == "diamond-open" for trace in mttr_downtime.data if hasattr(trace, "marker"))
    assert all(value is not None for trace in mtbf_mttf.data for value in (trace.y or []) if value is not None)


def test_monthly_payload_counts_actions_not_inferred_failures(monkeypatch):
    frame = _actions()
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload("2026-01")
    assert payload["status"] == "ok"
    assert payload["kpis"] == {
        "equipment": 2,
        "actions": 4,
        "records": 3,
        "systems": 2,
        "activity_days": 4,
        "motor_share_pct": 50.0,
        "availability_est_pct": 98.4,
        "downtime_est_hours": 24.0,
        "mtbf_est_hours": None,
        "mttr_est_hours": None,
    }
    assert payload["meta"]["estimated_kpis"]["status"] == "source"
    assert payload["meta"]["estimated_kpis"]["coverage"]["calendar_days"] == 31
    assert payload["meta"]["estimated_kpis"]["formula"]["downtime_est_hours"] == "sum(hours_out_of_service)"
    assert payload["data"]["system_mix"] == [
        {"system_name": "Motor", "count": 2},
        {"system_name": "Hidráulico", "count": 1},
        {"system_name": "Sin sistema", "count": 1},
    ]
    assert payload["data"]["daily"][0]["equipment_count"] == 1
    assert payload["data"]["daily"][0]["hours_out_of_service"] == 21.0
    assert payload["data"]["pareto"] == [{"equipment": "T_01", "value": 2, "cumulative_pct": 100.0, "count": 2}]
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
    assert filtered["data"]["system_mix"] == [{"system_name": "Motor", "count": 2}]

    empty = repo.get_monthly_payload("2025-12")
    assert empty["status"] == "empty"
    assert empty["kpis"]["actions"] == 0


def test_summary_unit_filter_reconciles_all_payload_aggregates(monkeypatch):
    frame = _actions()
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload("2026-01", equipment=["T_01"])

    assert payload["status"] == "ok"
    assert payload["filters"]["equipment"] == ["T_01"]
    assert payload["kpis"]["equipment"] == 1
    assert payload["kpis"]["actions"] == 3
    assert {row["equipment"] for row in payload["data"]["pareto"]} == {"T_01"}
    assert {row["machine_code"] for row in payload["data"]["equipment"]} == {"T_01"}
    assert {row["machine_code"] for row in payload["data"]["equipment_system_mix"]} == {"T_01"}
    assert {row["equipment"] for row in payload["data"]["detail"]} == {"T_01"}
    assert all(row["equipment_count"] == 1 for row in payload["data"]["daily"])


def test_fleet_filter_uses_catalog_and_groups_unmatched_units_as_otros(monkeypatch):
    frame = _actions().copy()
    extra_l = frame.loc[frame["action_id"] == "a4"].copy()
    extra_l["action_id"] = "a5"
    extra_l["record_id"] = "r4"
    extra_l["machine_code"] = "L_01"
    extra_r = frame.iloc[[0]].copy()
    extra_r["action_id"] = "a6"
    extra_r["record_id"] = "r5"
    extra_r["machine_code"] = "R_01"
    extra_r["change_date"] = "2026-01-07"
    extra_r["event_ts"] = "2026-01-07T05:00:00Z"
    extra_unknown = frame.iloc[[0]].copy()
    extra_unknown["action_id"] = "a7"
    extra_unknown["record_id"] = "r6"
    extra_unknown["machine_code"] = None
    extra_unknown["change_date"] = "2026-01-08"
    extra_unknown["event_ts"] = "2026-01-08T05:00:00Z"
    frame = pd.concat([frame, extra_l, extra_r, extra_unknown], ignore_index=True)
    business_kpis = pd.DataFrame(
        [
            {"machine_code": "T_01", "downtime_hours_70d": 10.0, "repairs_70d": 2, "total_actions_70d": 4, "reference_date": "2026-01-20"},
            {"machine_code": "T_02", "downtime_hours_70d": 20.0, "repairs_70d": 3, "total_actions_70d": 5, "reference_date": "2026-01-20"},
            {"machine_code": "L_01", "downtime_hours_70d": 100.0, "repairs_70d": 4, "total_actions_70d": 6, "reference_date": "2026-01-20"},
        ]
    )
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: business_kpis.copy())
    monkeypatch.setattr(
        repository_module,
        "load_oil_classified",
        lambda client: pd.DataFrame(
            [
                {"unitId": "T_01", "machineName": "camion"},
                {"unitId": "T_02", "machineName": "camion"},
                {"unitId": "L_01", "machineName": "cargador frontal"},
            ]
        ),
    )
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload("2026-01", fleets=["camion"])

    assert repo.get_available_fleets() == ["camion", "cargador frontal", "otros"]
    assert repo.get_available_equipment(fleets=["cargador frontal"]) == ["L_01"]
    assert repo.get_available_equipment(fleets=["otros"]) == ["R_01"]
    assert payload["filters"]["fleets"] == ["camion"]
    assert payload["kpis"]["actions"] == 4
    assert payload["kpis"]["downtime_est_hours"] == 24.0
    assert payload["kpis"]["availability_est_pct"] == 98.4
    assert {row["equipment"] for row in payload["data"]["detail"]} == {"T_01", "T_02"}

    unknown_fleet_payload = repo.get_monthly_payload("2026-01", fleets=["otros"])
    assert unknown_fleet_payload["kpis"]["actions"] == 2
    assert unknown_fleet_payload["kpis"]["downtime_est_hours"] is None
    assert unknown_fleet_payload["meta"]["estimated_kpis"]["source_kind"] == "record_intervals"
    assert unknown_fleet_payload["meta"]["estimated_kpis"]["status"] == "unavailable"


def test_fleet_filter_uses_tribologia_catalog_for_emin(monkeypatch):
    frame = _actions().copy()
    frame["machine_code"] = ["BULL-022", "BULL-022", "BULL-024", "BULL-031"]
    oil_catalog = pd.DataFrame(
        [
            {"unitId": "BULL_022", "machineName": "bulldozer"},
            {"unitId": "BULL_024", "machineName": "bulldozer"},
            {"unitId": "BULL_031", "machineName": "bulldozer"},
        ]
    )
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    monkeypatch.setattr(repository_module, "load_oil_classified", lambda client: oil_catalog.copy())
    repo = MaintenanceRepository(mode="parquet", client="emin")

    assert repository_module._normalize_unit_key("BULL-022") == "BULL_22"
    assert repository_module._normalize_unit_key("T_09") == "T_9"
    assert repo.get_available_fleets() == ["bulldozer"]
    assert repo.get_available_equipment(fleets=["bulldozer"]) == ["BULL-022", "BULL-024", "BULL-031"]

    payload = repo.get_monthly_payload("2026-01", fleets=["bulldozer"])
    assert payload["filters"]["fleets"] == ["bulldozer"]
    assert payload["kpis"]["equipment"] == 3
    assert payload["kpis"]["actions"] == 4


def test_refresh_invalidates_tribologia_fleet_catalog(monkeypatch):
    catalogs = iter(
        [
            pd.DataFrame([{"unitId": "T_01", "machineName": "camion"}]),
            pd.DataFrame([{"unitId": "T_01", "machineName": "excavadora"}]),
        ]
    )
    monkeypatch.setattr(repository_module, "load_oil_classified", lambda client: next(catalogs).copy())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    assert repo._fleet_for_machine_code("T_01") == "camion"
    repo.refresh()
    assert repo._fleet_for_machine_code("T_01") == "excavadora"


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
    train_extra = frame.iloc[[0]].copy()
    train_extra["action_id"] = "a6"
    train_extra["machine_code"] = "T_02"
    train_extra["action_system_name"] = "Tren de Fuerza"
    train_extra["change_date"] = "2026-01-08"
    train_extra["event_ts"] = "2026-01-08T05:00:00Z"
    frame = pd.concat([frame, train_extra], ignore_index=True)

    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload("2026-01")
    pareto = payload["data"]["pareto"]

    assert pareto == [
        {"equipment": "T_01", "value": 2, "count": 2, "cumulative_pct": 50.0},
        {"equipment": "T_02", "value": 2, "count": 2, "cumulative_pct": 100.0},
    ]
    assert all("Hidráulico" not in str(row) for row in pareto)
    assert payload["data"]["train_force_pareto"] == [{"equipment": "T_02", "count": 1, "cumulative_pct": 100.0}]


@pytest.mark.parametrize("client", ["emin", "capstone"])
def test_emin_and_capstone_pareto_and_mix_include_all_systems(monkeypatch, client):
    frame = _actions()
    extra = frame.iloc[[0, 1, 2]].copy().reset_index(drop=True)
    extra["action_id"] = ["a5", "a6", "a7"]
    extra["record_id"] = ["r4", "r5", "r6"]
    extra["job_id"] = ["j4", "j5", "j6"]
    extra["machine_id"] = "m2"
    extra["machine_code"] = "T_02"
    extra["action_system_name"] = [
        "Equipo",
        "Estación del Operador - Cabina",
        "Sistema de Dirección",
    ]
    extra["job_system_name"] = extra["action_system_name"]
    extra["change_date"] = ["2026-01-07", "2026-01-08", "2026-01-09"]
    extra["event_ts"] = [
        "2026-01-07T05:00:00Z",
        "2026-01-08T05:00:00Z",
        "2026-01-09T05:00:00Z",
    ]
    frame = pd.concat([frame, extra], ignore_index=True)
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())

    payload = MaintenanceRepository(mode="parquet", client=client).get_monthly_payload("2026-01")

    assert payload["meta"]["client"] == client.upper()
    assert payload["meta"]["pareto_scope"]["mode"] == "all_systems"
    assert payload["meta"]["pareto_scope"]["system_filter"] is None
    assert payload["meta"]["pareto_scope"]["system_aliases"] == []
    assert {row["system_name"] for row in payload["data"]["system_pareto"]} >= {
        "Equipo",
        "Estación del Operador - Cabina",
        "Sistema de Dirección",
    }
    assert {row["system_name"] for row in payload["data"]["system_mix"]} >= {
        "Equipo",
        "Estación del Operador - Cabina",
        "Sistema de Dirección",
    }
    assert {row["equipment"]: row["count"] for row in payload["data"]["pareto"]}["T_02"] == 4
    assert payload["data"]["train_force_pareto"] == []
    assert payload["data"]["system_pareto"][-1]["cumulative_pct"] == 100.0


@pytest.mark.parametrize("client, expected_generic_systems", [
    ("emin", {"Equipo", "Estación del Operador - Cabina"}),
    ("capstone", {"Equipo", "Estación del Operador - Cabina"}),
    ("cda", set()),
])
def test_legacy_system_pareto_is_unrestricted_only_for_emin_and_capstone(monkeypatch, client, expected_generic_systems):
    frame = _actions()
    extra = frame.iloc[[0, 1]].copy().reset_index(drop=True)
    extra["action_id"] = ["generic-equipment", "generic-cabina"]
    extra["action_system_name"] = ["Equipo", "Estación del Operador - Cabina"]
    frame = pd.concat([frame, extra], ignore_index=True)
    repo = MaintenanceRepository(mode="parquet", client=client)
    monkeypatch.setattr(repo, "_filtered_actions", lambda **kwargs: frame.copy())

    pareto = repo.get_maintenance_by_system()

    assert expected_generic_systems <= set(pareto["system_name"])
    if client == "cda":
        assert not expected_generic_systems.intersection(set(pareto["system_name"]))
    assert pareto.iloc[-1]["cumulative_pct"] == 100.0


def test_system_activity_charts_can_include_all_systems_and_large_legends():
    from dashboard.tabs.tab_mantenciones_general import (
        _system_color_map,
        create_equipment_activity_chart,
        create_system_activity_chart,
    )

    systems = ["Equipo", "Estación del Operador - Cabina"] + [f"Sistema auxiliar {i}" for i in range(1, 12)]
    detailed = pd.DataFrame(
        [
            {"machine_code": "T_01", "equipment": "T_01", "system_name": system, "count": len(systems) - index}
            for index, system in enumerate(systems)
        ]
    )

    system_figure = create_system_activity_chart(detailed.drop(columns="machine_code"), include_all_systems=True)
    equipment_figure = create_equipment_activity_chart(detailed, include_all_systems=True)

    assert {trace.name for trace in system_figure.data} == {"Acciones registradas"}
    assert list(system_figure.data[0].x) == systems
    assert {trace.name for trace in equipment_figure.data} == set(systems)
    assert len(_system_color_map(systems)) == len(systems)
    assert _system_color_map(systems) == _system_color_map(reversed(systems))


def test_pareto_titles_are_unrestricted_only_for_emin_and_capstone():
    from dashboard.callbacks.mantenciones_general_callbacks import _pareto_presentation

    emin = _pareto_presentation("EMIN")
    capstone = _pareto_presentation("CAPSTONE")
    cda = _pareto_presentation("CDA")

    assert emin["all_systems"] is True
    assert emin["equipment_title"] == "Pareto de acciones por unidad"
    assert emin["system_title"] == "Pareto de horas intervenidas por unidad"
    assert "por sistema" in capstone["system_title"]
    assert cda["all_systems"] is False
    assert "Motor por equipo" in cda["equipment_title"]


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
    assert figure.layout.showlegend is True
    assert [trace.name for trace in figure.data] == ["Acciones Motor", "% acumulado"]


def test_emin_pareto_compact_mode_keeps_all_equipment_and_the_80_percent_crossing():
    from dashboard.tabs.tab_mantenciones_general import create_equipment_pareto_chart

    frame = pd.DataFrame(
        [{"equipment": f"EQ-{index:02d}", "count": 101 - index} for index in range(40)]
    )
    figure = create_equipment_pareto_chart(
        frame, system_label="Todos los sistemas", compact=True
    )

    counts = frame.sort_values(["count", "equipment"], ascending=[False, True])[
        "count"
    ]
    threshold_index = next(
        index for index, value in enumerate(counts.cumsum() / counts.sum() * 100)
        if value >= 80
    )
    assert len(figure.data[0].x) == 40
    assert len(figure.layout.xaxis.tickvals) <= 9
    assert figure.layout.xaxis.tickvals[0] == "EQ-00"
    assert figure.layout.xaxis.tickvals[-1] == "EQ-39"
    assert frame.sort_values("count", ascending=False).iloc[threshold_index]["equipment"] in figure.layout.xaxis.tickvals
    assert sum(bool(label) for label in figure.data[0].text) < 40
    assert figure.data[1].mode == "lines"
    assert figure.layout.shapes[0].x0 == threshold_index


def test_emin_equipment_ranking_shows_top_fifteen_high_to_low():
    from dashboard.tabs.tab_mantenciones_general import create_equipment_activity_chart

    rows = [
        {"machine_code": f"EQ-{unit:02d}", "system_name": system, "count": 40 - unit}
        for unit in range(35)
        for system in ("Sistema de Motor", "Sistema Hidráulico")
    ]
    figure = create_equipment_activity_chart(
        pd.DataFrame(rows), include_all_systems=True, compact=True
    )

    assert list(figure.data[0].y) == [f"EQ-{unit:02d}" for unit in range(15)]
    assert len(figure.data[0].x) == 15
    assert figure.layout.yaxis.autorange == "reversed"
    assert list(figure.layout.yaxis.categoryarray) == [f"EQ-{unit:02d}" for unit in range(15)]
    assert len(figure.layout.yaxis.tickvals) == 15
    assert figure.layout.xaxis.title.text == "Acciones únicas"


def test_emin_system_display_labels_do_not_change_filter_values_or_other_clients():
    from dashboard.callbacks.mantenciones_general_callbacks import (
        _display_system_label,
        _display_system_rows,
        _pareto_system_options,
    )

    options = _pareto_system_options("EMIN", ["Equipo", "Sistema de Motor"])
    assert options[0] == {
        "label": "General del equipo (sin sistema técnico atribuido)",
        "value": "Equipo",
    }
    assert _display_system_label("EMIN", "Equipo") == "General del equipo"
    assert _display_system_label("CDA", "Equipo") == "Equipo"
    rows = _display_system_rows(
        [{"system_name": "Equipo", "count": 7}], "EMIN"
    )
    assert rows.iloc[0]["system_name"] == "General del equipo"
    assert rows.iloc[0]["count"] == 7


def test_emin_pareto_metric_falls_back_to_actions_for_partial_scope_or_client_change():
    from dashboard.callbacks.mantenciones_general_callbacks import _effective_pareto_metric

    available = ["Equipo", "Sistema de Motor", "Sistema Hidráulico"]
    assert _effective_pareto_metric(
        "EMIN", "hours", available, available, True
    ) == "hours"
    assert _effective_pareto_metric(
        "EMIN", "hours", ["Sistema de Motor"], available, True
    ) == "actions"
    assert _effective_pareto_metric(
        "EMIN", "hours", available, available, True, client_changed=True
    ) == "actions"
    assert _effective_pareto_metric(
        "EMIN", "hours", [], available, True
    ) == "actions"
    assert _effective_pareto_metric(
        "EMIN", "hours", available, available, False
    ) == "actions"


def test_emin_compact_activity_table_prioritizes_executive_columns():
    from dashboard.tabs.tab_mantenciones_general import create_activity_table

    table = create_activity_table(
        [
            {
                "date": "2026-01-02",
                "equipment": "T_01",
                "system_name": "Sistema de Motor",
                "component": "Bomba",
                "action_type": "Reparación",
                "detail": "Reparación de prueba",
                "timestamp": "2026-01-02 03:00",
                "intervention_start": "2026-01-02 03:00",
                "intervention_end": "2026-01-02 04:00",
                "subsystem_name": "Combustible",
            }
        ],
        compact=True,
    )

    assert [column["id"] for column in table.columns] == [
        "date", "equipment", "system_name", "component", "action_type", "detail"
    ]
    assert any(
        item["if"].get("column_id") == "detail"
        for item in table.style_cell_conditional
    )


def test_emin_responsive_shell_rules_are_scoped_to_reliability_view():
    css = (Path(__file__).parents[1] / "dashboard" / "assets" / "custom_layout.css").read_text(encoding="utf-8")
    from dashboard.callbacks.mantenciones_general_callbacks import _maintenance_root_class

    assert _maintenance_root_class("EMIN").endswith("maintenance-emin")
    assert not _maintenance_root_class("CDA").endswith("maintenance-emin")
    assert "#dashboard-shell:has(#maintenance-view-root.maintenance-emin)" in css
    assert "mobile-nav-open" in css
    assert '#maintenance-view-root.maintenance-emin .text-warning[role="status"]' in css
    assert "color: #854d0e !important" in css


def test_executive_kpi_label_sits_above_value_not_below():
    from dashboard.tabs.tab_mantenciones_general import create_kpi_card

    card = create_kpi_card("Disponibilidad", component_id="test-kpi")
    children = card.children.children.children
    title_index = next(
        index for index, child in enumerate(children)
        if getattr(child, "children", None) == "Disponibilidad"
    )
    value_index = next(
        index for index, child in enumerate(children)
        if getattr(child, "id", None) == "test-kpi"
    )

    assert title_index < value_index
    assert not any(
        getattr(child, "children", None) == "Disponibilidad"
        for child in children[value_index + 1 :]
    )


def test_system_activity_builder_labels_activity_not_failures():
    from dashboard.tabs.tab_mantenciones_general import create_system_activity_chart

    figure = create_system_activity_chart(pd.DataFrame([{"system_name": "Motor", "count": 4}]))

    assert list(figure.data[0].x) == ["Motor"]
    assert figure.layout.yaxis.title.text == "Acciones únicas"


def test_daily_intervention_hours_chart_shows_hours_and_equipment():
    from dashboard.tabs.tab_mantenciones_general import create_daily_equipment_chart, create_daily_intervention_hours_chart

    figure = create_daily_intervention_hours_chart(
        pd.DataFrame(
            [
                {"date": "2026-01-01", "count": 2, "hours_out_of_service": 3.0, "equipment_count": 2},
                {"date": "2026-01-02", "count": 1, "hours_out_of_service": 1.5, "equipment_count": 1},
            ]
        )
    )

    assert [trace.name for trace in figure.data] == ["Horas-equipo intervenidas"]
    assert figure.layout.yaxis.title.text == "Horas-equipo intervenidas"
    assert "proxy" not in str(figure).lower()

    equipment_figure = create_daily_equipment_chart(
        pd.DataFrame(
            [
                {"date": "2026-01-01", "equipment_count": 2},
                {"date": "2026-01-02", "equipment_count": 1},
            ]
        )
    )
    assert [trace.name for trace in equipment_figure.data] == ["Equipos intervenidos"]
    assert equipment_figure.layout.yaxis.title.text == "Equipos intervenidos"


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


def test_layout_keeps_future_views_mounted_but_hides_monthly_reliability_section():
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
    assert "maintenance-kpi-days" in rendered
    assert "maintenance-kpi-motor-share" in rendered
    assert "maintenance-kpi-availability-est" in rendered
    assert "maintenance-kpi-downtime-est" in rendered
    assert "maintenance-kpi-mtbf-est" in rendered
    assert "maintenance-kpi-mttr-est" in rendered
    assert "maintenance-executive-signals" not in rendered
    assert "Lectura ejecutiva" not in rendered
    assert "ESTIMADA" not in rendered
    assert "ESTIMADO" not in rendered
    assert rendered.index("maintenance-kpi-availability-est") < rendered.index("maintenance-chart-pareto")
    assert rendered.index("maintenance-chart-daily") < rendered.index("maintenance-chart-system-mix")
    assert rendered.index("maintenance-chart-system-mix") < rendered.index("maintenance-chart-pareto")
    assert rendered.index("maintenance-chart-pareto") < rendered.index("maintenance-kpi-equipment")
    assert "Resumen ejecutivo" in rendered
    assert "Informe de confiabilidad" in rendered
    assert "Esperando datos de confiabilidad" in rendered
    assert "query_5 · mes seleccionado" not in rendered
    assert "intervalos · mes seleccionado" not in rendered
    assert "horas-equipo · mes seleccionado" not in rendered
    assert "maintenance-chart-system-mix" in rendered
    assert "maintenance-chart-pareto-tren-fuerza" in rendered
    assert "maintenance-chart-daily-equipment" in rendered
    assert "maintenance-summary-equipment" in rendered
    assert "maintenance-summary-fleet" in rendered
    assert "maintenance-summary-detail-table" in rendered
    assert rendered.index("Indicadores de Interés") < rendered.index("maintenance-summary-detail-table")
    assert "Confiabilidad mensual" not in rendered
    assert "maintenance-chart-reliability-mtbf-mttf" not in rendered
    assert "maintenance-chart-reliability-mttr-downtime" not in rendered
    assert "maintenance-reliability-components-table" not in rendered
    assert "maintenance-reliability-equipment" not in rendered
    assert "(proxy)" not in rendered
    assert "maintenance-source-alert" in rendered
    assert "maintenance-view-root" in rendered
    assert "maintenance-system-mix-note" not in rendered
    assert "maintenance-chart-equipment-note" not in rendered
    assert "maintenance-summary-systems" in rendered
    assert "Mostrar todos" not in rendered
    assert "maintenance-context-kpi-note" in rendered
    assert "Indicadores de Interés" in rendered
    assert "'display': 'none'" in rendered or "display: none" in rendered
    assert "Indicadores de Interés" in rendered
    assert "Estos agregados ayudan a explicar el Pareto" not in rendered
    assert "Equipos Sanos" not in rendered
    assert "Horas Detenidas" not in rendered


def test_activity_charts_exclude_non_system_labels_and_keep_system_legend():
    from dashboard.tabs.tab_mantenciones_general import create_equipment_activity_chart, create_equipment_pareto_chart, create_system_activity_chart

    detailed = pd.DataFrame(
        [
            {"system_name": "Equipo", "equipment": "T_01", "count": 8},
            {"system_name": "Estación del Operador - Cabina", "equipment": "T_01", "count": 4},
            {"system_name": "Sistema de Motor", "equipment": "T_01", "count": 5},
            {"system_name": "Sistema Hidráulico", "equipment": "T_01", "count": 3},
            {"system_name": "Sistema de Motor", "equipment": "T_02", "count": 2},
        ]
    )

    system_figure = create_system_activity_chart(detailed)
    assert list(system_figure.data[0].x) == ["Sistema de Motor", "Sistema Hidráulico"]
    assert len(system_figure.data) == 1
    assert system_figure.data[0].orientation == "v"
    assert system_figure.data[0].name == "Acciones registradas"

    equipment_figure = create_equipment_activity_chart(
        detailed.rename(columns={"equipment": "machine_code"})
    )
    assert equipment_figure.layout.barmode == "stack"
    assert list(equipment_figure.layout.xaxis.categoryarray) == ["T_01", "T_02"]
    assert all(trace.orientation == "v" for trace in equipment_figure.data)
    assert {trace.name for trace in equipment_figure.data} == {"Sistema de Motor", "Sistema Hidráulico"}

    pareto_figure = create_equipment_pareto_chart(
        pd.DataFrame([{"equipment": "T_02", "count": 3, "cumulative_pct": 100.0}])
    )
    assert list(pareto_figure.data[0].marker.color) == ["#4f8a8b"]


def test_equipment_activity_ranking_is_descending_top_down_with_unit_filter():
    from dashboard.tabs.tab_mantenciones_general import create_equipment_activity_chart

    detailed = pd.DataFrame(
        [
            {"machine_code": "T_01", "system_name": "Sistema de Motor", "count": 10},
            {"machine_code": "T_01", "system_name": "Sistema Hidráulico", "count": 1},
            {"machine_code": "T_02", "system_name": "Sistema de Motor", "count": 20},
            {"machine_code": "T_02", "system_name": "Sistema Hidráulico", "count": 10},
            {"machine_code": "T_03", "system_name": "Sistema de Motor", "count": 15},
        ]
    )

    figure = create_equipment_activity_chart(detailed)
    expected = ["T_02", "T_03", "T_01"]
    assert list(figure.layout.xaxis.categoryarray) == expected
    assert all(list(trace.x) == expected for trace in figure.data)
    assert all(trace.orientation == "v" for trace in figure.data)

    # A unit-filtered payload must preserve the same contract, rather than
    # falling back to an arbitrary/alphabetical category order.
    filtered = create_equipment_activity_chart(detailed.loc[detailed["machine_code"] == "T_02"])
    assert list(filtered.layout.xaxis.categoryarray) == ["T_02"]
    assert all(list(trace.x) == ["T_02"] for trace in filtered.data)
    assert all(trace.orientation == "v" for trace in filtered.data)


def test_maintenance_bar_charts_use_vertical_orientation_and_descending_rank():
    from dashboard.tabs.tab_mantenciones_general import (
        create_daily_intervention_hours_chart,
        create_equipment_pareto_chart,
        create_system_activity_chart,
    )

    mix = create_system_activity_chart(
        pd.DataFrame(
            [
                {"system_name": "Hidráulico", "count": 2},
                {"system_name": "Motor", "count": 7},
                {"system_name": "Frenos", "count": 4},
            ]
        )
    )
    pareto = create_equipment_pareto_chart(
        pd.DataFrame(
            [
                {"equipment": "T_02", "count": 2, "cumulative_pct": 100.0},
                {"equipment": "T_01", "count": 7, "cumulative_pct": 50.0},
            ]
        )
    )
    daily = create_daily_intervention_hours_chart(
        pd.DataFrame(
            [
                {"date": "2026-01-02", "hours_out_of_service": 1.5},
                {"date": "2026-01-01", "hours_out_of_service": 3.0},
            ]
        )
    )

    assert mix.data[0].orientation == "v"
    assert list(mix.data[0].x) == ["Motor", "Frenos", "Hidráulico"]
    assert pareto.data[0].orientation == "v"
    assert list(pareto.data[0].x) == ["T_01", "T_02"]
    assert list(pareto.data[1].y) == pytest.approx([77.77777777777777, 100.0])
    assert pareto.data[1].mode == "lines"
    assert len(pareto.layout.shapes) == 1
    assert pareto.layout.shapes[0].line.dash == "dot"
    assert pareto.layout.annotations[0].text == "80%"
    assert daily.data[0].orientation == "v"
    assert list(daily.data[0].x) == ["2026-01-01", "2026-01-02"]


def test_pareto_hours_uses_hours_units_and_marks_first_80_percent_equipment():
    from dashboard.tabs.tab_mantenciones_general import create_equipment_pareto_chart

    figure = create_equipment_pareto_chart(
        pd.DataFrame([
            {"equipment": "T_02", "value": 20.0, "count": 20.0},
            {"equipment": "T_01", "value": 80.0, "count": 80.0},
        ]),
        system_label="Todos los sistemas",
        metric="hours",
    )

    assert list(figure.data[0].x) == ["T_01", "T_02"]
    assert list(figure.data[0].y) == [80.0, 20.0]
    assert figure.layout.yaxis.title.text == "Horas-equipo (h)"
    assert figure.data[1].mode == "lines"
    assert figure.layout.shapes[0].x0 == 0


def test_daily_equipment_chart_uses_five_unit_y_ticks():
    from dashboard.tabs.tab_mantenciones_general import create_daily_equipment_chart

    figure = create_daily_equipment_chart(
        pd.DataFrame(
            [
                {"date": "2026-01-01", "equipment_count": 3},
                {"date": "2026-01-02", "equipment_count": 11},
            ]
        )
    )

    assert figure.layout.yaxis.dtick == 5
    assert figure.layout.yaxis.tick0 == 0


def test_callbacks_register_on_concrete_app_and_layout_ids_are_unique():
    from dashboard.callbacks.mantenciones_general_callbacks import register_mantenciones_general_callbacks

    app = dash.Dash(__name__)
    app.layout = layout_mantenciones_general()
    register_mantenciones_general_callbacks(app)

    output_keys = list(app.callback_map)
    assert len(output_keys) == 9
    assert any("maintenance-monthly-store" in key for key in output_keys)
    assert any("maintenance-summary-detail-table" in key for key in output_keys)
    monthly_callback = next(entry for key, entry in app.callback_map.items() if "maintenance-monthly-store" in key)
    assert any(dependency["id"] == "maintenance-summary-fleet" for dependency in monthly_callback["inputs"])
    output_ids = []
    for entry in app.callback_map.values():
        outputs = entry["output"] if isinstance(entry["output"], list) else [entry["output"]]
        output_ids.extend((output.component_id, output.component_property) for output in outputs)
    assert len(output_ids) == len(set(output_ids))


def test_summary_equipment_options_include_all_sentinel():
    from dashboard.callbacks.mantenciones_general_callbacks import _equipment_options

    assert _equipment_options(["T_01", "T_02"]) == [
        {"label": "Todas", "value": "__all__"},
        {"label": "T_01", "value": "T_01"},
        {"label": "T_02", "value": "T_02"},
    ]


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


def test_estimated_kpis_are_unavailable_without_period_data(monkeypatch):
    frame = _actions()
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload("2025-12")

    assert payload["status"] == "empty"
    assert payload["kpis"]["availability_est_pct"] is None
    assert payload["kpis"]["downtime_est_hours"] is None
    assert payload["meta"]["estimated_kpis"]["status"] == "unavailable"


def test_estimated_kpi_formatter_keeps_estimated_values_explicit():
    from dashboard.callbacks.mantenciones_general_callbacks import _format_estimated

    assert _format_estimated(86.25, "%") == "86.2%"
    assert _format_estimated(1128.0, "h") == "1,128.0 h"
    assert _format_estimated(None, "h") == "—"


def test_source_alert_exposes_estimated_source_window_and_fallback_reason():
    from dashboard.callbacks.mantenciones_general_callbacks import _source_alert

    alert = _source_alert(
        {
            "source_start": "2024-12-01",
            "source_end": "2026-01-22",
            "estimated_kpis": {
                "source": ["query_3_actions_all_equipment.parquet"],
                "coverage": {"window_label": "mes seleccionado"},
                "reason": "query_4 rechazado por plausibilidad",
            },
        }
    )

    rendered = str(alert)
    assert "query_3_actions_all_equipment.parquet" in rendered
    assert "mes seleccionado" in rendered
    assert "Fallback" in rendered


def test_monthly_intervals_drive_downtime_and_availability(monkeypatch):
    frame = _actions()
    business = pd.DataFrame(
        [
            {"machine_code": "T_01", "downtime_hours_70d": 100.0, "repairs_70d": 10, "total_actions_70d": 20, "reference_date": "2026-01-22T10:00:00Z"},
            {"machine_code": "T_02", "downtime_hours_70d": 50.0, "repairs_70d": 5, "total_actions_70d": 30, "reference_date": "2026-01-22T10:00:00Z"},
        ]
    )
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: business.copy())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload("2026-01")

    assert payload["kpis"]["downtime_est_hours"] == 24.0
    assert payload["kpis"]["availability_est_pct"] == 98.4
    assert payload["kpis"]["mtbf_est_hours"] is None
    assert payload["kpis"]["mttr_est_hours"] is None
    meta = payload["meta"]["estimated_kpis"]
    assert meta["source_kind"] == "record_intervals"
    assert meta["coverage"]["window_label"] == "mes seleccionado"
    assert meta["coverage"]["calendar_days"] == 31
    assert meta["formula"]["downtime_est_hours"] == "sum(hours_out_of_service)"


def test_reliability_cards_use_query5_weighted_by_intervals_and_failures(monkeypatch):
    frame = _actions()
    reliability = pd.DataFrame(
        [
            {
                "source_system": "CDA",
                "machine_id": "m1",
                "machine_code": "T_01",
                "year_month": "2026-01",
                "n_failures": 2,
                "mttr_hours": 5.0,
                "total_downtime_hours": 10.0,
                "n_mtbf_intervals": 2,
                "mtbf_hours": 100.0,
                "mttf_hours": 90.0,
                "low_confidence": True,
            },
            {
                "source_system": "CDA",
                "machine_id": "m2",
                "machine_code": "T_02",
                "year_month": "2026-01",
                "n_failures": 1,
                "mttr_hours": 2.0,
                "total_downtime_hours": 2.0,
                "n_mtbf_intervals": 1,
                "mtbf_hours": 40.0,
                "mttf_hours": 35.0,
                "low_confidence": True,
            },
            {
                "source_system": "CDA",
                "machine_id": "m3",
                "machine_code": "T_03",
                "year_month": "2026-01",
                "n_failures": 0,
                "mttr_hours": float("nan"),
                "total_downtime_hours": 0.0,
                "n_mtbf_intervals": 0,
                "mtbf_hours": float("nan"),
                "mttf_hours": float("nan"),
                "low_confidence": True,
            },
        ]
    )
    business = pd.DataFrame(
        [
            {"machine_code": "T_01", "downtime_hours_70d": 1.0, "repairs_70d": 1, "total_actions_70d": 1, "reference_date": "2026-01-22T10:00:00Z"},
            {"machine_code": "T_02", "downtime_hours_70d": 1.0, "repairs_70d": 1, "total_actions_70d": 1, "reference_date": "2026-01-22T10:00:00Z"},
        ]
    )
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: business.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_reliability_monthly", lambda client: reliability.copy())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload("2026-01")

    assert payload["kpis"]["mtbf_est_hours"] == 80.0
    assert payload["kpis"]["mttr_est_hours"] == 4.0
    assert payload["meta"]["reliability_kpis"]["source"] == "query_5_reliability_monthly.parquet"
    assert payload["meta"]["reliability_kpis"]["low_confidence_rows"] == 3

    filtered = repo.get_monthly_payload("2026-01", equipment=["T_01"])
    assert filtered["kpis"]["mtbf_est_hours"] == 100.0
    assert filtered["kpis"]["mttr_est_hours"] == 5.0


def test_system_filter_does_not_infer_hours_from_action_proxy(monkeypatch):
    frame = _actions()
    business = pd.DataFrame(
        [{"machine_code": "T_01", "downtime_hours_70d": 100.0, "repairs_70d": 10, "total_actions_70d": 20, "reference_date": "2026-01-22T10:00:00Z"}]
    )
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: business.copy())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload("2026-01", systems=["Motor"])

    assert payload["meta"]["estimated_kpis"]["source_kind"] == "record_intervals"
    assert payload["kpis"]["downtime_est_hours"] == 24.0
    assert payload["kpis"]["availability_est_pct"] == 96.8


def test_monthly_downtime_is_bounded_by_union_of_source_intervals(monkeypatch):
    frame = _actions()
    business = pd.DataFrame(
        [
            {"machine_code": "T_01", "downtime_hours_70d": 4000.0, "repairs_70d": 10, "total_actions_70d": 20, "reference_date": "2026-01-22T10:00:00Z"},
            {"machine_code": "T_02", "downtime_hours_70d": 0.0, "repairs_70d": 5, "total_actions_70d": 30, "reference_date": "2026-01-22T10:00:00Z"},
        ]
    )
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: business.copy())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload("2026-01")

    assert payload["kpis"]["downtime_est_hours"] == 24.0
    assert payload["kpis"]["availability_est_pct"] == 98.4
    assert payload["meta"]["estimated_kpis"]["source_kind"] == "record_intervals"
    assert payload["meta"]["estimated_kpis"]["formula"]["downtime_est_hours"] == "sum(hours_out_of_service)"


def test_monthly_downtime_clips_month_and_unions_overlapping_equipment_intervals(monkeypatch):
    frame = _actions()
    frame.loc[frame["record_id"] == "r1", "change_date"] = "2026-01-01"
    frame.loc[frame["record_id"] == "r2", "change_date"] = "2026-01-01"
    frame.loc[frame["record_id"] == "r3", "change_date"] = "2026-01-31"
    records = pd.DataFrame(
        [
            {"record_id": "r1", "machine_code": "T_01", "first_event_ts": "2026-01-01T00:00:00Z", "last_event_ts": "2026-01-02T12:00:00Z"},
            {"record_id": "r2", "machine_code": "T_01", "first_event_ts": "2026-01-01T12:00:00Z", "last_event_ts": "2026-01-01T18:00:00Z"},
            {"record_id": "r3", "machine_code": "T_02", "first_event_ts": "2026-01-31T00:00:00Z", "last_event_ts": "2026-02-01T12:00:00Z"},
        ]
    )
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_maintenance_unit_records_actions", lambda client: records.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: pd.DataFrame())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload("2026-01")

    # T_01 contributes 36 h after unioning the 6 h overlap; T_02 contributes
    # 24 h after clipping its interval at the end of January.
    assert payload["kpis"]["downtime_est_hours"] == 60.0
    assert payload["kpis"]["availability_est_pct"] == 96.0
    assert sum(row["hours_out_of_service"] or 0 for row in payload["data"]["daily"]) == 60.0
    assert payload["meta"]["time_measure"]["source"] == "query_2_unit_records_actions.parquet"


@pytest.mark.parametrize(
    "values, expected",
    [
        ([40, 40, 5, 5, 4, 3, 3], 5),  # Exact 80% after two units, then three.
        ([80, 20], 2),                  # Fewer than three remaining.
        ([79, 21], 2),                  # Crossing occurs at the last unit.
    ],
)
def test_emin_pareto_initial_prefix_without_expand_control(values, expected):
    from dashboard.tabs.tab_mantenciones_general import pareto_visible_equipment

    rows = pd.DataFrame({"equipment": [f"EQ-{i}" for i in range(len(values))], "value": values})
    initial = pareto_visible_equipment(rows)
    assert len(initial) == expected
    assert list(initial["value"]) == sorted(values, reverse=True)[:expected]
    assert initial.iloc[-1]["cumulative_pct"] <= 100


def test_emin_pareto_actions_are_unique_and_hours_stay_independent(monkeypatch):
    _patch_emin_ten_views(monkeypatch)
    repo = MaintenanceRepository(mode="parquet", client="emin")
    payload = repo.get_monthly_payload("2026-01", systems=["Sistema de Motor"])
    actions = payload["data"]["emin_action_systems"]
    assert sum(row["count"] for row in actions) == 2  # a1 is duplicated in the source.
    assert {row["equipment"] for row in actions} == {"T_01"}
    assert payload["data"]["emin_hours_pareto"] == []
    assert payload["kpis"]["actions"] == 2
    all_systems = repo.get_monthly_payload("2026-01")
    assert sum(row["value"] for row in all_systems["data"]["emin_hours_pareto"]) == 6.0
    assert all_systems["kpis"]["actions"] == 4


def test_emin_pareto_charts_show_system_legend_and_lines_without_markers():
    from dashboard.tabs.tab_mantenciones_general import create_emin_actions_pareto_chart, create_emin_hours_pareto_chart

    actions = pd.DataFrame([
        {"equipment": "EQ-1", "system_name": "Sistema de Motor", "count": 4},
        {"equipment": "EQ-1", "system_name": "Sistema Hidráulico", "count": 1},
        {"equipment": "EQ-2", "system_name": "Sistema de Motor", "count": 2},
    ])
    hours = pd.DataFrame([{"equipment": "EQ-1", "value": 5.0}, {"equipment": "EQ-2", "value": 2.0}])
    action_fig = create_emin_actions_pareto_chart(actions)
    hour_fig = create_emin_hours_pareto_chart(hours)
    assert {trace.name for trace in action_fig.data if trace.type == "bar"} == {"Sistema de Motor", "Sistema Hidráulico"}
    assert action_fig.data[0].mode == hour_fig.data[0].mode == "lines"
    assert action_fig.layout.shapes[0].line.dash == hour_fig.layout.shapes[0].line.dash == "dot"
    assert hour_fig.layout.yaxis.title.text == "Horas-equipo (h)"


def test_emin_reset_controls_preserve_month_and_fleet(monkeypatch):
    from dashboard.callbacks import mantenciones_general_callbacks as callbacks

    class App:
        def __init__(self):
            self.handlers = {}

        def callback(self, *args, **kwargs):
            def capture(function):
                self.handlers[function.__name__] = function
                return function
            return capture

    app = App()
    callbacks.register_mantenciones_general_callbacks(app)
    assert "update_emin_pareto_view" not in app.handlers

    class Repo:
        def get_available_equipment(self, systems=None, fleets=None):
            assert systems is None
            assert fleets == ["Camiones"]
            return ["T_01", "T_02"]

        def get_monthly_payload(self, month, **kwargs):
            assert month == "2026-01"
            assert kwargs["fleets"] == ["Camiones"]
            assert kwargs["equipment"] is None
            assert kwargs["systems"] == ["Sistema de Motor"]
            return {"status": "ok"}

    monkeypatch.setattr(callbacks, "get_repository", lambda **kwargs: Repo())
    monkeypatch.setattr(callbacks, "ctx", type("Trigger", (), {"triggered_id": "maintenance-reset-unit"})())
    options, unit = app.handlers["update_summary_equipment_options"](
        ["Camiones"], "EMIN", [0], 1, ["Sistema de Motor"],
        [{"equipment": "T_01"}], "T_01", {"filter_systems": ["Sistema de Motor"]},
    )
    assert unit == "__all__"
    assert options[0]["value"] == "__all__"
    callbacks.ctx.triggered_id = "maintenance-unit-navigation-table"
    _, unchanged = app.handlers["update_summary_equipment_options"](
        ["Camiones"], "EMIN", [], 1, ["Sistema de Motor"],
        [{"equipment": "T_01"}], "__all__", {"filter_systems": ["Sistema de Motor"]},
    )
    assert unchanged is callbacks.no_update
    app.handlers["load_monthly_payload"](
        "EMIN", "2026-01", ["Camiones"], unit, ["Sistema de Motor"],
        None, None, None, [], "actions", None,
    )


def _capture_maintenance_callbacks():
    from dashboard.callbacks.mantenciones_general_callbacks import register_mantenciones_general_callbacks

    handlers = {}

    class App:
        def callback(self, *args, **kwargs):
            def capture(function):
                handlers[function.__name__] = function
                return function
            return capture

    register_mantenciones_general_callbacks(App())
    return handlers


@pytest.mark.parametrize("client", ["cda", "capstone"])
def test_activity_system_filter_does_not_narrow_other_clients_pareto(monkeypatch, client):
    _patch_emin_ten_views(monkeypatch)
    repo = MaintenanceRepository(mode="parquet", client=client)
    payload = repo.get_monthly_payload(
        "2026-01", systems=["Sistema de Motor"],
        pareto_systems=["Sistema Hidráulico"],
    )
    assert payload["kpis"]["actions"] == 2
    assert sum(row["value"] for row in payload["data"]["pareto"]) == 1


def test_emin_unattributed_actions_count_as_a_system_and_have_consistent_detail(monkeypatch):
    frames = _patch_emin_ten_views(monkeypatch)
    actions = frames[0].copy()
    actions.loc[actions["action_id"].eq("a4"), "action_system_name"] = "   "
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: actions.copy())
    repo = MaintenanceRepository(mode="parquet", client="emin")
    payload = repo.get_monthly_payload("2026-01", systems=["Sin sistema"])
    assert payload["kpis"]["actions"] == 1
    assert payload["kpis"]["systems"] == 1
    assert {row["system_name"] for row in payload["data"]["detail"]} == {"Sin sistema"}
    null_actions = frames[0].copy()
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: null_actions.copy())
    null_payload = MaintenanceRepository(mode="parquet", client="emin").get_monthly_payload("2026-01", systems=["Sin sistema"])
    assert null_payload["kpis"]["systems"] == 1


def test_emin_hidden_activity_filters_do_not_leak_into_global_scope(monkeypatch):
    from dashboard.callbacks import mantenciones_general_callbacks as callbacks
    _patch_emin_ten_views(monkeypatch)
    repo = MaintenanceRepository(mode="parquet", client="emin")
    monkeypatch.setattr(callbacks, "get_repository", lambda **kwargs: repo)
    payload, _ = _capture_maintenance_callbacks()["load_monthly_payload"](
        "EMIN", "2026-01", [], "__all__", [],
        ["Sistema de Motor"], ["Lubricación"], ["T_01"], [], "hours", None,
    )
    assert payload["kpis"]["actions"] == 4
    assert payload["filters"]["subsystems"] == []
    assert sum(row["value"] for row in payload["data"]["emin_hours_pareto"]) == 6


def test_emin_empty_fleet_unit_intersection_does_not_restore_fleet_reliability(monkeypatch):
    _patch_emin_ten_views(monkeypatch)
    monkeypatch.setattr(repository_module, "load_oil_classified", lambda client: pd.DataFrame([
        {"unitId": "T_01", "machineName": "Camiones"},
        {"unitId": "T_02", "machineName": "Excavadoras"},
    ]))
    repo = MaintenanceRepository(mode="parquet", client="emin")
    for fleets, equipment in [(["Camiones"], ["T_02"]), (["Flota inexistente"], None)]:
        payload = repo.get_monthly_payload("2026-01", fleets=fleets, equipment=equipment)
        assert payload["kpis"]["actions"] == 0
        for metric in ("availability_est_pct", "downtime_est_hours", "mtbf_est_hours", "mttr_est_hours"):
            assert payload["kpis"][metric] is None
        assert payload["data"]["emin_hours_pareto"] == []


def test_emin_mobile_unavailable_notice_and_small_equipment_counts_remain_readable(monkeypatch):
    from dashboard.tabs.tab_mantenciones_general import create_daily_equipment_chart
    _patch_emin_ten_views(monkeypatch)
    repo = MaintenanceRepository(mode="parquet", client="emin")
    payload = repo.get_monthly_payload("2026-01", systems=["Sistema de Motor"])
    rendered = _capture_maintenance_callbacks()["render_monthly_payload"](payload)
    assert "<br>" in rendered[11].layout.annotations[0].text
    assert "<br>" in rendered[14].layout.annotations[0].text
    assert rendered[12].layout.yaxis.dtick == 1
    one_day = create_daily_equipment_chart(pd.DataFrame([
        {"date": "2026-01-02", "equipment_count": 1},
    ]), integer_ticks=True)
    assert one_day.layout.xaxis.tickvals == ("2026-01-02",)
    assert one_day.layout.xaxis.tickformat == "%d/%m/%Y"


def test_emin_system_colors_survive_unit_and_system_filter_changes():
    from dashboard.callbacks.mantenciones_general_callbacks import _empty_contract
    render = _capture_maintenance_callbacks()["render_monthly_payload"]
    payload = _empty_contract()
    payload["status"] = "ok"
    payload["meta"].update({"client": "EMIN", "filter_systems": ["Sistema de Motor", "Sistema Eléctrico", "Estación del Operador - Cabina"]})
    rows = [
        {"machine_code": "T_01", "system_name": "Sistema de Motor", "count": 3},
        {"machine_code": "T_01", "system_name": "Estación del Operador - Cabina", "count": 2},
        {"machine_code": "T_02", "system_name": "Sistema Eléctrico", "count": 1},
    ]
    def charts(selected_rows):
        payload["data"]["equipment_system_mix"] = selected_rows
        payload["data"]["system_mix"] = [{"system_name": row["system_name"], "count": row["count"]} for row in selected_rows]
        payload["data"]["emin_action_systems"] = [{"equipment": row["machine_code"], "system_name": row["system_name"], "count": row["count"]} for row in selected_rows]
        result = render(payload)
        return (
            dict(zip(result[15].data[0].x, result[15].data[0].marker.color)),
            {trace.name: trace.marker.color for trace in result[16].data},
            {trace.name: trace.marker.color for trace in result[13].data if trace.type == "bar"},
        )
    all_colors = charts(rows)
    filtered_colors = charts(rows[-1:])
    for original, filtered in zip(all_colors, filtered_colors):
        assert original["Sistema Eléctrico"] == filtered["Sistema Eléctrico"]


def test_emin_pareto_always_keeps_initial_prefix_without_an_expand_control():
    from copy import deepcopy
    from dashboard.callbacks.mantenciones_general_callbacks import _empty_contract

    values = [45, 20, 10, 5, 4, 4, 3, 3, 2, 2, 1, 1]
    payload = _empty_contract()
    payload["status"] = "ok"
    payload["meta"].update({"client": "EMIN", "period": "2026-01"})
    payload["filters"].update({"fleets": ["Camiones"], "equipment": ["T_01"]})
    payload["data"]["emin_action_systems"] = [
        {"equipment": f"EQ-{i:02d}", "system_name": "Sistema de Motor", "count": value}
        for i, value in enumerate(values)
    ]
    payload["data"]["emin_hours_pareto"] = [
        {"equipment": f"EQ-{i:02d}", "value": value}
        for i, value in enumerate(values)
    ]
    original = deepcopy(payload)
    render = _capture_maintenance_callbacks()["render_monthly_payload"]
    initial = render(payload)
    for index in (13, 14):
        assert len(initial[index].data[0].x) == 7
        assert initial[index].data[0].y[-1] == pytest.approx(91)
    assert payload == original
    rendered_layout = str(layout_mantenciones_general())
    assert "Mostrar todos" not in rendered_layout
    assert "maintenance-pareto-actions-show-all" not in rendered_layout
    assert "maintenance-pareto-hours-show-all" not in rendered_layout


def test_emin_visible_messages_hide_internal_sources_and_ranking_disclaimer(monkeypatch):
    from types import SimpleNamespace
    from dashboard.callbacks import mantenciones_general_callbacks as callbacks

    _patch_emin_ten_views(monkeypatch)
    repo = MaintenanceRepository(mode="parquet", client="emin")
    monkeypatch.setattr(callbacks, "get_repository", lambda **kwargs: repo)
    monkeypatch.setattr(callbacks, "ctx", SimpleNamespace(triggered_id=None))
    handlers = _capture_maintenance_callbacks()
    assert handlers["load_maintenance_metadata"]("EMIN", None)[1] is None
    payload = repo.get_monthly_payload("2026-01")
    rendered = handlers["render_monthly_payload"](payload)
    detail = handlers["render_unit_detail"](payload, "T_01")
    visible_notes = str(rendered[10]) + str(rendered[22]) + str(rendered[25]) + str(detail)
    for forbidden in (
        "query", ".parquet", "Cobertura de fuente", "no es estado de hoy",
        "Registros largos", "histórico acumulado", "no se limita al mes",
        "2026-05-25", "2026-08-07", "el último período disponible",
        "cobertura: días observados del mes", "intervenciones anormalmente largas",
        "las horas no se truncaron",
    ):
        assert forbidden.lower() not in visible_notes.lower()
    assert "Días según fecha operacional" in rendered[25]
    assert "estimaciones" in str(rendered[10])
    payload["data"]["historical_failures"] = []
    assert "No se dispone de esta información momentáneamente" in str(handlers["render_unit_detail"](payload, "T_01"))


@pytest.mark.parametrize("client", ["CDA", "CAPSTONE"])
def test_other_clients_keep_the_existing_pareto_rendering(client):
    from dashboard.callbacks.mantenciones_general_callbacks import _empty_contract

    payload = _empty_contract()
    payload["status"] = "ok"
    payload["meta"].update({"client": client, "period_label": "2026-01", "reliability_kpis": {"rows": 2}})
    payload["data"]["pareto"] = [{"equipment": f"EQ-{i:02d}", "value": 100 - i} for i in range(12)]
    rendered = _capture_maintenance_callbacks()["render_monthly_payload"](payload)
    assert len(rendered[13].data[0].x) == 12
    assert rendered[13].data[0].type == "bar"
    assert "Query 5" in str(rendered[10])
    assert "horas intervenidas por unidad" not in rendered[21]


def test_emin_actions_pareto_shares_the_equipment_legend_palette():
    from dashboard.tabs.tab_mantenciones_general import (
        create_equipment_activity_chart,
        create_emin_actions_pareto_chart,
        create_system_activity_chart,
    )

    rows = pd.DataFrame([
        {"equipment": "T_01", "system_name": "General del equipo", "count": 4},
        {"equipment": "T_02", "system_name": "Sistema de Motor", "count": 2},
        {"equipment": "T_02", "system_name": "Otro sistema", "count": 1},
    ])
    equipment = create_equipment_activity_chart(rows.rename(columns={"equipment": "machine_code"}), include_all_systems=True, compact=True)
    pareto = create_emin_actions_pareto_chart(rows, palette_systems=rows["system_name"])
    filtered = create_emin_actions_pareto_chart(rows[rows["system_name"].eq("Otro sistema")], palette_systems=rows["system_name"])
    mix = create_system_activity_chart(rows, include_all_systems=True)
    equipment_colors = {trace.name: trace.marker.color for trace in equipment.data}
    action_colors = {trace.name: trace.marker.color for trace in pareto.data if trace.type == "bar"}
    mix_colors = dict(zip(mix.data[0].x, mix.data[0].marker.color))
    assert equipment.layout.showlegend is False
    assert all(system in trace.hovertemplate for system, trace in zip(equipment_colors, equipment.data))
    for system, color in equipment_colors.items():
        assert action_colors[system] == color
        assert mix_colors[system] == color
    assert filtered.data[1].marker.color == equipment_colors["Otro sistema"]
