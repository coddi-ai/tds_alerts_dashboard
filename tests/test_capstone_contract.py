import json

import pandas as pd

from dashboard.components.alerts_charts import (
    FEATURE_NAMES_ES,
    NO_SIGNAL_KEY,
    PARETO_BAR_COLOR,
    create_alerts_per_unit_chart,
    create_alerts_per_week_chart,
    create_system_signal_treemap,
    create_context_kpis_cards_golden,
    create_sensor_trends_chart_golden,
)
from dashboard.callbacks.alerts_callbacks import _select_telemetry_alert_data
from dashboard.components.alerts_report import (
    prepare_alert_rows,
    translate_alert_component,
    translate_alert_system,
)
from dashboard.components.alerts_tables import parse_ia_message_sections
from src.data.loaders import _load_alerts_data_cached, load_alerts_data


def test_capstone_canonical_signals_and_structured_ai_are_client_facing():
    message = json.dumps(
        {
            "diagnostic": "engine_speed_rpm supera el límite",
            "recommended_actions": ["Revisar coolant_pressure_psi"],
            "evidence": ["telemetry"],
        }
    )

    sections = parse_ia_message_sections(message)
    rows = prepare_alert_rows(
        pd.DataFrame(
            [
                {
                    "Timestamp": "2026-07-10T12:00:00-04:00",
                    "UnitId": "CA-42",
                    "sistema": "motor",
                    "componente": "engine",
                    "Trigger_type": "Telemetria",
                    "Trigger_Var": "engine_speed_rpm",
                    "mensaje_ia": message,
                    "has_telemetry": True,
                    "has_tribology": False,
                }
            ]
        )
    )

    assert FEATURE_NAMES_ES["engine_speed_rpm"] == "Velocidad del motor"
    assert "Velocidad del motor" in sections["diagnostico"]
    assert "Presión del refrigerante" in sections["acciones"]
    assert rows.loc[0, "component_display"] == "Motor"
    assert rows.loc[0, "signal_display"] == "Velocidad del motor"


def test_component_labels_are_consistent_for_mixed_source_casing():
    assert translate_alert_component("engine") == "Motor"
    assert translate_alert_component("Engine") == "Motor"
    assert translate_alert_component("lubrication") == "Lubricación"
    assert translate_alert_component("Lubrication") == "Lubricación"


def test_capstone_loader_uses_configured_data_root(tmp_path, monkeypatch):
    alerts_path = tmp_path / "alerts" / "golden" / "capstone" / "consolidated_alerts.csv"
    alerts_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "FusionID": "F-1",
                "Timestamp": "2026-07-10T12:00:00-04:00",
                "UnitId": "CA-42",
                "sistema": "motor",
                "subsistema": "engine",
                "componente": "engine",
                "Trigger_type": "Mixto",
                "TribologyID": 12.0,
            }
        ]
    ).to_csv(alerts_path, index=False)

    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    _load_alerts_data_cached.cache_clear()
    loaded = load_alerts_data("CAPSTONE")
    _load_alerts_data_cached.cache_clear()

    assert len(loaded) == 1
    assert loaded.loc[0, "TribologyID"] == "12"
    assert loaded.loc[0, "Timestamp"].tzinfo is None
    assert bool(loaded.loc[0, "has_telemetry"])
    assert bool(loaded.loc[0, "has_tribology"])


def test_capstone_telemetry_detail_matches_string_telemetry_or_fusion_id():
    telemetry_detail = pd.DataFrame(
        [
            {"AlertID": "CAP-fusion-1", "Unit": "CA-42", "value": 10},
            {"AlertID": "CAP-other", "Unit": "CA-43", "value": 20},
        ]
    )
    alert = pd.Series(
        {
            "TelemetryID": "CAP-telemetry-1",
            "FusionID": "CAP-fusion-1",
            "UnitId": "CA-42",
        }
    )

    selected, identifiers, unit_id = _select_telemetry_alert_data(telemetry_detail, alert)

    assert identifiers == ["CAP-telemetry-1", "CAP-fusion-1"]
    assert unit_id == "CA-42"
    assert selected["AlertID"].tolist() == ["CAP-fusion-1"]

    telemetry_keyed = pd.DataFrame([{"AlertID": "CAP-telemetry-1", "Unit": "CA-42"}])
    selected, _, _ = _select_telemetry_alert_data(telemetry_keyed, alert)
    assert selected["AlertID"].tolist() == ["CAP-telemetry-1"]


def test_capstone_context_kpis_use_canonical_engine_signals():
    context = create_context_kpis_cards_golden(
        pd.DataFrame(
            [
                {
                    "TimeStart": pd.Timestamp("2026-07-10 12:00:00"),
                    "engine_load_pct_Value": 42.5,
                    "engine_speed_rpm_Value": 1234.0,
                }
            ]
        ),
        pd.Timestamp("2026-07-10 12:00:00"),
        "engine_speed_rpm",
    )

    def component_text(component):
        if isinstance(component, (list, tuple)):
            return " ".join(component_text(child) for child in component)
        children = getattr(component, "children", None)
        if children is not None:
            return component_text(children)
        return str(component)

    rendered = component_text(context)

    assert "42%" in rendered
    assert "1234 RPM" in rendered


def test_capstone_system_labels_are_translated_in_alert_charts():
    alerts = pd.DataFrame(
        [
            {
                "UnitId": "CA-42",
                "sistema": "motor",
                "Timestamp": "2026-07-10T12:00:00",
            }
        ]
    )

    unit_chart = create_alerts_per_unit_chart(alerts)
    week_chart = create_alerts_per_week_chart(alerts)
    system_chart = create_system_signal_treemap(alerts)

    assert translate_alert_system("motor") == "Motor"
    # Pareto chart: units on X, a single (non-system) bar color, and a
    # cumulative-percentage line that reaches 100% at the last point.
    assert list(unit_chart.data[0].x) == ["CA-42"]
    assert unit_chart.data[0].marker.color == PARETO_BAR_COLOR
    assert unit_chart.data[1].y[-1] == 100
    assert {trace.name for trace in week_chart.data} == {"Motor"}
    # System/subsystem/signal treemap: translated Sistema is the sole level-1 node,
    # colored via the shared system palette. This alert has neither a subsistema nor
    # a signal, so both lower levels fall back to their "none" labels; each node says
    # which filter a click on it applies ([key, value]; subsystems filter nothing).
    treemap = system_chart.data[0]
    assert list(treemap.labels) == ["Motor", "Sin subsistema", "Sin señal registrada"]
    assert list(treemap.parents) == ["", "0", "0/0"]
    assert treemap.marker.colors[0] == "#355c7d"
    assert [list(node) for node in treemap.customdata] == [
        ["system", "Motor"], ["", ""], ["trigger", NO_SIGNAL_KEY],
    ]


def test_capstone_single_system_treemap_has_three_levels():
    # Capstone alerts are all "motor" (a single system): the treemap still reads
    # Sistema -> Subsistema -> Señal gatillo, with the real subsistema ids shown by
    # their Spanish labels and the signal codes by theirs.
    alerts = pd.DataFrame(
        [
            {"UnitId": "CA-1", "sistema": "motor", "subsistema": "coolant", "Timestamp": "2026-07-10T12:00:00", "Trigger_Var": "coolant_temp_c"},
            {"UnitId": "CA-2", "sistema": "motor", "subsistema": "coolant", "Timestamp": "2026-07-10T12:05:00", "Trigger_Var": "coolant_pressure_psi"},
            {"UnitId": "CA-3", "sistema": "motor", "subsistema": "egt", "Timestamp": "2026-07-10T12:10:00", "Trigger_Var": "egt_01_c"},
            {"UnitId": "CA-4", "sistema": "motor", "subsistema": "oil_filter", "Timestamp": "2026-07-10T12:15:00", "Trigger_Var": "oil_filter_dp_psi"},
        ]
    )

    treemap = create_system_signal_treemap(alerts).data[0]

    labels = set(treemap.labels)
    assert {"Motor", "Refrigerante", "Gases de escape (EGT)", "Filtro de aceite"} <= labels
    # No raw subsistema id leaks into the UI.
    assert not labels & {"coolant", "egt", "oil_filter"}
    # One system, three subsystems, four signals; the areas add up to the alert count.
    assert len(treemap.labels) == 1 + 3 + 4
    assert treemap.values[0] == 4
    # Positional ids keep every node distinct even when names repeat across branches.
    assert len(set(treemap.ids)) == len(treemap.ids)
    customdata = [list(node) for node in treemap.customdata]
    assert customdata.count(["system", "Motor"]) == 1
    assert customdata.count(["", ""]) == 3
    assert sorted(node[1] for node in customdata if node[0] == "trigger") == [
        "coolant_pressure_psi", "coolant_temp_c", "egt_01_c", "oil_filter_dp_psi",
    ]


def test_treemap_hierarchy_comes_from_the_data_not_a_fixed_list():
    alerts = pd.DataFrame(
        [
            {"UnitId": "U1", "sistema": "Motor", "subsistema": "Aire", "Timestamp": "2026-07-10T12:00:00", "Trigger_Var": "['EngCoolTemp']"},
            {"UnitId": "U2", "sistema": "Frenos", "subsistema": "Aire", "Timestamp": "2026-07-10T12:05:00", "Trigger_Var": "['EngCoolTemp', 'Potasio']"},
            {"UnitId": "U3", "sistema": "Frenos", "subsistema": "Freno Delantero", "Timestamp": "2026-07-10T12:10:00", "Trigger_Var": None},
        ]
    )

    treemap = create_system_signal_treemap(alerts).data[0]

    roots = [label for label, parent in zip(treemap.labels, treemap.parents) if parent == ""]
    assert sorted(roots) == ["Frenos", "Motor"]
    # "Aire" exists under both systems and stays two separate cells.
    assert list(treemap.labels).count("Aire") == 2
    # Only the first signal of an alert counts, so no alert is double-counted.
    assert sum(value for value, parent in zip(treemap.values, treemap.parents) if parent == "") == 3
    # An alert without a signal still gets a clickable trigger cell.
    assert ["trigger", NO_SIGNAL_KEY] in [list(node) for node in treemap.customdata]


def test_capstone_state_markers_and_legend_use_semantic_colors():
    alert_time = pd.Timestamp("2026-07-10 12:00:00")
    alert_data = pd.DataFrame(
        [
            {
                "TimeStart": alert_time - pd.Timedelta(minutes=30),
                "crankcase_pressure_inh2o_Value": 2.0,
                "State": "Potencia",
            },
            {
                "TimeStart": alert_time - pd.Timedelta(minutes=15),
                "crankcase_pressure_inh2o_Value": 3.0,
                "State": "TRANSICION",
            },
            {
                "TimeStart": alert_time,
                "crankcase_pressure_inh2o_Value": 4.0,
                "State": "Desconocido",
            },
        ]
    )

    figure = create_sensor_trends_chart_golden(
        alert_data=alert_data,
        feature_names=["crankcase_pressure_inh2o"],
        unit_id="CA-42",
        alert_time=alert_time,
        feature_name_map=FEATURE_NAMES_ES,
        client="CAPSTONE",
    )

    sensor_trace = next(trace for trace in figure.data if trace.mode == "lines+markers")
    assert list(sensor_trace.marker.color) == ["#2ecc71", "#f39c12", "#95a5a6"]

    state_legend = {
        trace.name: trace.marker.color
        for trace in figure.data
        if trace.name in {"Potencia", "Transición"}
    }
    assert state_legend == {"Potencia": "#2ecc71", "Transición": "#f39c12"}
