"""Alerts table: explicit source labels, compact fields and selection metadata."""

import pandas as pd

from dashboard.components.alerts_tables import create_alerts_report_table


def _sample_alerts_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "FusionID": "F-1",
                "Timestamp": pd.Timestamp("2026-07-10 16:00:00"),
                "UnitId": "CA-42",
                "sistema": "motor",
                "componente": "engine",
                "Trigger_type": "Mixto",
                "Trigger_Var": "EngCoolTemp",
                "mensaje_ia": "",
                "has_telemetry": True,
                "has_tribology": True,
            },
            {
                "FusionID": "F-2",
                "Timestamp": pd.Timestamp("2026-07-11 10:00:00"),
                "UnitId": "CA-43",
                "sistema": "motor",
                "componente": "rifle",
                "Trigger_type": "Telemetria",
                "Trigger_Var": "EngOilPres",
                "mensaje_ia": "",
                "has_telemetry": True,
                "has_tribology": False,
            },
        ]
    )


def test_published_source_is_visible_while_id_and_evidence_remain_metadata():
    table = create_alerts_report_table(_sample_alerts_df())
    visible_ids = {column["id"] for column in table.columns}
    assert "ID" not in visible_ids
    assert "Fuente" in visible_ids
    assert "Evidencia" not in visible_ids


def test_id_fuente_evidencia_still_present_in_row_data():
    """store_selected_alert and render_selected_alert_summary
    (alerts_callbacks.py) read these three fields from
    the table's `data` (matched by the row's `id`) — all three must survive
    presentation changes."""
    table = create_alerts_report_table(_sample_alerts_df())
    for row in table.data:
        assert row["id"] == row["ID"]
        assert "ID" in row and row["ID"] in ("F-1", "F-2")
        assert "Fuente" in row and row["Fuente"] in ("Multitécnica", "Telemetría")
        assert "Evidencia" in row and row["Evidencia"]


def test_mixto_row_highlight_rule_still_targets_the_fuente_field():
    """Highlight the full row, with one accent rather than a border per cell."""
    table = create_alerts_report_table(_sample_alerts_df())
    filter_queries = [rule["if"].get("filter_query") for rule in table.style_data_conditional if "filter_query" in rule.get("if", {})]
    assert '{Fuente} = "Multitécnica"' in filter_queries
    accent_rules = [rule for rule in table.style_data_conditional if "borderLeft" in rule]
    assert accent_rules and all(rule["if"]["column_id"] == "Fecha" for rule in accent_rules)
    assert any(
        rule["if"] == {"filter_query": '{Fuente} = "Multitécnica"'} and "backgroundColor" in rule
        for rule in table.style_data_conditional
    )


def test_visible_columns_include_the_source_next_to_the_unit():
    table = create_alerts_report_table(_sample_alerts_df())
    visible_ids = [column["id"] for column in table.columns]
    assert visible_ids == [
        "Fecha", "Unidad", "Fuente", "Sistema", "Componente",
        "Señal / variable", "Diagnóstico", "Acción",
    ]


def test_source_label_does_not_depend_on_available_evidence():
    alerts = _sample_alerts_df()
    alerts["has_tribology"] = False
    alerts["has_maintenance"] = True
    table = create_alerts_report_table(alerts)
    by_id = {row["ID"]: row for row in table.data}
    assert by_id["F-1"]["Fuente"] == "Multitécnica"
    assert by_id["F-2"]["Fuente"] == "Telemetría"


def test_legacy_datatable_variant_is_not_imported_by_the_live_callback_module():
    """The regression this guards against: create_alerts_datatable (which DOES
    expose ID/Fuente as visible columns) must not be reachable from
    alerts_callbacks.py — if it were re-imported and wired to the same
    id='alerts-datatable', the columns W34-03 removed would reappear."""
    import dashboard.callbacks.alerts_callbacks as callbacks_module

    assert not hasattr(callbacks_module, "create_alerts_datatable")


def test_legacy_datatable_variant_still_exists_as_deliberately_unused_code():
    """Confirms it wasn't deleted outright — alerts_tables.py keeps it as a
    documented-legacy function per the W34 plan (leave dead code alone
    unless directly required)."""
    from dashboard.components import alerts_tables

    assert hasattr(alerts_tables, "create_alerts_datatable")
