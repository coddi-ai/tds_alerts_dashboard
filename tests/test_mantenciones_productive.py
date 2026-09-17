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
    assert payload["kpis"] == {
        "equipment": 2,
        "actions": 4,
        "records": 3,
        "systems": 2,
        "activity_days": 4,
        "motor_share_pct": 50.0,
        "availability_est_pct": 99.6,
        "downtime_est_hours": 6.0,
        "mtbf_est_hours": 494.0,
        "mttr_est_hours": 2.0,
    }
    assert payload["meta"]["estimated_kpis"]["status"] == "estimated"
    assert payload["meta"]["estimated_kpis"]["coverage"]["calendar_days"] == 31
    assert "unique_action_id_count × 1.5" in payload["meta"]["estimated_kpis"]["formula"]["downtime_est_hours"]
    assert payload["data"]["system_mix"] == [
        {"system_name": "Motor", "count": 2},
        {"system_name": "Hidráulico", "count": 1},
        {"system_name": "Sin sistema", "count": 1},
    ]
    assert payload["data"]["daily"][0]["equipment_count"] == 1
    assert payload["data"]["daily"][0]["hours_estimated"] == 1.5
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
        {"equipment": "T_01", "count": 2, "cumulative_pct": 50.0},
        {"equipment": "T_02", "count": 2, "cumulative_pct": 100.0},
    ]
    assert all("Hidráulico" not in str(row) for row in pareto)
    assert payload["data"]["train_force_pareto"] == [{"equipment": "T_02", "count": 1, "cumulative_pct": 100.0}]


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
                {"date": "2026-01-01", "count": 2, "hours_estimated": 3.0, "equipment_count": 2},
                {"date": "2026-01-02", "count": 1, "hours_estimated": 1.5, "equipment_count": 1},
            ]
        )
    )

    assert [trace.name for trace in figure.data] == ["Horas de intervención"]
    assert figure.layout.yaxis.title.text == "Horas de intervención"
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
    assert "maintenance-chart-system-mix" in rendered
    assert "maintenance-chart-pareto-tren-fuerza" in rendered
    assert "maintenance-chart-daily-equipment" in rendered
    assert "maintenance-summary-equipment" in rendered
    assert "(proxy)" not in rendered
    assert "maintenance-source-alert" in rendered
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
    assert all("Equipo" not in str(trace.name) and "Cabina" not in str(trace.name) for trace in system_figure.data)

    equipment_figure = create_equipment_activity_chart(
        detailed.rename(columns={"equipment": "machine_code"})
    )
    assert equipment_figure.layout.barmode == "stack"
    assert set(equipment_figure.layout.yaxis.categoryarray) == {"T_01", "T_02"}
    assert {trace.name for trace in equipment_figure.data} == {"Sistema de Motor", "Sistema Hidráulico"}

    pareto_figure = create_equipment_pareto_chart(
        pd.DataFrame([{"equipment": "T_02", "count": 3, "cumulative_pct": 100.0}])
    )
    mix_colors = {trace.name: trace.marker.color for trace in system_figure.data}
    assert list(pareto_figure.data[0].marker.color) == [mix_colors["T_02"]]


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


def test_estimated_kpis_prefer_business_70d_and_expose_window(monkeypatch):
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

    assert payload["kpis"]["downtime_est_hours"] == 150.0
    assert payload["kpis"]["availability_est_pct"] == 95.5
    assert payload["kpis"]["mtbf_est_hours"] == 214.0
    assert payload["kpis"]["mttr_est_hours"] == 10.0
    meta = payload["meta"]["estimated_kpis"]
    assert meta["source_kind"] == "business_kpis_70d"
    assert meta["coverage"]["window_label"] == "ventana móvil 70d"
    assert meta["coverage"]["calendar_days"] == 70
    assert meta["formula"]["downtime_est_hours"] == "sum(downtime_hours_70d)"


def test_system_filter_falls_back_to_monthly_action_proxy(monkeypatch):
    frame = _actions()
    business = pd.DataFrame(
        [{"machine_code": "T_01", "downtime_hours_70d": 100.0, "repairs_70d": 10, "total_actions_70d": 20, "reference_date": "2026-01-22T10:00:00Z"}]
    )
    monkeypatch.setattr(repository_module, "load_maintenance_actions_all_equipment", lambda client: frame.copy())
    monkeypatch.setattr(repository_module, "load_business_kpis", lambda client: business.copy())
    repo = MaintenanceRepository(mode="parquet", client="cda")

    payload = repo.get_monthly_payload("2026-01", systems=["Motor"])

    assert payload["meta"]["estimated_kpis"]["source_kind"] == "actions_monthly_proxy"
    assert "desglose por sistema" in payload["meta"]["estimated_kpis"]["reason"]


def test_implausible_business_downtime_falls_back_to_monthly_proxy(monkeypatch):
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

    assert payload["kpis"]["downtime_est_hours"] == 6.0
    assert payload["meta"]["estimated_kpis"]["source_kind"] == "actions_monthly_proxy"
    assert "plausibilidad" in payload["meta"]["estimated_kpis"]["reason"]
