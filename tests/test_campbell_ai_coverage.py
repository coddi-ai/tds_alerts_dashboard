"""Tests for per-client data coverage and the per-alert sensor chart.

Companies do not carry the same techniques: one has alerts, oil, telemetry,
maintenance and predictive models, another only oil. An agent that assumes the
richest client promises analyses that cannot run, so capability is resolved from the
datasets actually present and surfaced before the first question.

The sensor chart is the last visual missing from the previous dashboard. Its open
question was how the agent picks signals; the answer here is that the trigger is the
default and the tool reports what else has captured values.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.campbell_ai.chart_registry import DashboardChartRegistry
from src.campbell_ai.data import (
    ANALYSIS_CAPABILITIES,
    DATASET_MAP,
    DashboardDataRepository,
)
from config.client_services import KNOWN_SERVICE_IDS
from src.campbell_ai.errors import CampbellDataError


# --------------------------------------------------------------- data coverage


def _oil_only_client(tmp_path) -> DashboardDataRepository:
    """A client with tribology only, like ENEX."""
    oil = tmp_path / "oil" / "golden" / "enex"
    oil.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "unitId": "T_1",
                "componentNameNormalized": "motor",
                "componentName": "motor",
                "report_status": "Normal",
                "sampleDate": "2026-07-01",
                "severity_score": 1,
            }
        ]
    ).to_parquet(oil / "classified.parquet", index=False)
    pd.DataFrame(
        [{"unit_id": "T_1", "overall_status": "Normal", "latest_sample_date": "2026-07-01"}]
    ).to_parquet(oil / "machine_status.parquet", index=False)
    pd.DataFrame(
        [
            {
                "client": "ENEX",
                "machine": "camion",
                "component": "motor",
                "essay": "Hierro",
                "oilHourRange": "LT_1000",
                "threshold_alert": 50.0,
                "threshold_critic": 60.0,
            }
        ]
    ).to_parquet(oil / "stewart_limits.parquet", index=False)
    # The current calibration: what every four-limit consumer actually reads. The legacy
    # three-threshold file above no longer enables the oil_limits capability on its own.
    pd.DataFrame(
        [
            {
                "client": "ENEX",
                "machine": "camion",
                "component": "motor",
                "essay": "Hierro",
                "oilHourRange": "LT_1000",
                "GroupElement": "Desgaste",
                "min_value": 0.0,
                "LIC": None,
                "LIM": None,
                "LSM": 50.0,
                "LSC": 60.0,
                "sample_count": 12,
                "calculation_date": "2026-08-05T11:15:17",
            }
        ]
    ).to_parquet(oil / "stewart_limits_four.parquet", index=False)
    return DashboardDataRepository(tmp_path)


def test_a_missing_source_is_reported_as_a_missing_source(tmp_path, monkeypatch):
    """With the service enabled, an absent file is named as an absent file."""
    import src.campbell_ai.data as data_module

    repository = _oil_only_client(tmp_path)
    (tmp_path / "oil" / "golden" / "enex" / "machine_status.parquet").unlink()
    monkeypatch.setattr(data_module, "declared_columns", lambda *args, **kwargs: None)
    data_module.clear_presence_cache()

    reasons = {
        item["key"]: item["reason"]
        for item in repository.client_capabilities("enex")["unavailable"]
    }

    assert "Faltan fuentes" in reasons["oil_fleet"]
    assert "servicio" not in reasons["oil_fleet"]


def test_the_limits_capability_names_the_calibration_its_consumers_read():
    """The four-limit analysis must depend on the four-limit file, not the legacy one.

    It used to require `stewart_limits.parquet` while the radar, the chat and the dashboard
    all read `stewart_limits_four.parquet`, so the capability could be advertised for a
    client whose current calibration was absent.
    """
    capability = next(
        item for item in ANALYSIS_CAPABILITIES if item.key == "oil_limits"
    )

    assert "oil_limits_four" in capability.requires
    assert DATASET_MAP["oil_limits_four"].path_template.endswith(
        "stewart_limits_four.parquet"
    )
    assert "describe_oil_limits" in capability.tools


def test_a_client_without_the_four_limit_file_cannot_run_the_limits_analysis(
    tmp_path, monkeypatch
):
    """Behaviour behind the requirement, on the path that looks at disk.

    Capability resolution trusts the declared schema for a declared dataset, so this pins the
    fallback path - an undeclared dataset, resolved by looking - where the file itself decides.
    """
    import src.campbell_ai.data as data_module

    repository = _oil_only_client(tmp_path)
    (tmp_path / "oil" / "golden" / "enex" / "stewart_limits_four.parquet").unlink()
    monkeypatch.setattr(data_module, "declared_columns", lambda *args, **kwargs: None)

    capabilities = repository.client_capabilities("enex")

    available = {item["key"] for item in capabilities["available"]}
    reasons = {item["key"]: item["reason"] for item in capabilities["unavailable"]}
    assert "oil_limits" not in available
    assert "Faltan fuentes" in reasons["oil_limits"]
    # One missing calibration, not an unusable client: the rest of the oil analyses stand.
    assert {"oil_fleet", "oil_components"} <= available


def test_capabilities_state_what_is_possible_and_why_the_rest_is_not(tmp_path):
    repository = _oil_only_client(tmp_path)

    capabilities = repository.client_capabilities("enex")

    available = {item["key"] for item in capabilities["available"]}
    assert {"oil_fleet", "oil_components", "oil_limits"} <= available
    # No alerts, telemetry, maintenance or predictive data exists for this client.
    assert "alerts" not in available
    assert "telemetry_fleet" not in available

    reasons = {item["key"]: item["reason"] for item in capabilities["unavailable"]}
    # ENEX has Monitoreo > Alertas switched off, so the reason names the service rather than
    # the file: having the data would not make the analysis permitted.
    assert "servicio no esta habilitado" in reasons["alerts"]
    assert "monitoring-alerts" in reasons["alerts"]
    # A blocked module is a different reason than a missing file.
    assert "módulo predictivo" in reasons["predictive_motor"]

    assert capabilities["techniques"] == {
        "alertas": False,
        "aceite": True,
        "telemetria": False,
        "mantenimiento": False,
        "predictivo": False,
    }


def test_capabilities_are_offered_to_the_agent_with_instructions(tmp_path):
    payload = json.loads(_oil_only_client(tmp_path).describe_capabilities("enex"))

    assert "available" in payload and "unavailable" in payload
    # The agent must be told not to substitute a missing technique with another.
    assert "no los sustituyas" in payload["note"]


def test_every_capability_declares_registered_datasets():
    """A capability pointing at an unregistered dataset can never become available."""
    for capability in ANALYSIS_CAPABILITIES:
        assert capability.requires, capability.key
        for key in capability.requires:
            assert key in DATASET_MAP, f"{capability.key} -> {key}"
        assert capability.tools, capability.key
        assert capability.label.strip(), capability.key


def test_capability_keys_are_unique():
    keys = [capability.key for capability in ANALYSIS_CAPABILITIES]
    assert len(keys) == len(set(keys))


def test_an_undeclared_client_with_no_data_reports_everything_unavailable(tmp_path):
    """The guarantee that survives assuming presence.

    A declared dataset is taken as present without touching disk, so a *declared* client with
    an empty data root now reports its declared coverage. What must still hold is the case
    that has no declaration to lean on: an unknown client falls back to checking the
    filesystem, finds nothing, and is offered nothing - rather than inheriting some other
    client's catalogue.
    """
    repository = DashboardDataRepository(tmp_path / "empty")

    capabilities = repository.client_capabilities("cliente_nuevo")

    assert capabilities["available"] == []
    assert len(capabilities["unavailable"]) == len(ANALYSIS_CAPABILITIES)
    assert not any(capabilities["techniques"].values())


# ------------------------------------------------------- per-alert sensor chart


def _alert_detail_client(tmp_path) -> DashboardDataRepository:
    """Wide per-sample detail, with a state-dependent limit as production has."""
    telemetry = tmp_path / "telemetry" / "golden" / "cda"
    telemetry.mkdir(parents=True)
    rows = []
    for index, (state, value, limit) in enumerate(
        [
            ("Operacional", 90.0, 105.0),
            ("Operacional", 100.0, 105.0),
            # Idle lowers the ceiling, so 99 breaches it while 100 did not breach 105.
            ("Ralenti", 99.0, 95.0),
            ("Ralenti", 80.0, 95.0),
        ]
    ):
        rows.append(
            {
                "AlertID": 7,
                "Unit": "T_18",
                "Trigger": "EngCoolTemp",
                "TimeStart": f"2026-07-09T1{index}:00:00",
                "State": state,
                "EngCoolTemp_Value": value,
                "EngCoolTemp_Upper_Limit": limit,
                "TCOutTemp_Value": 70.0 + index,
                "TCOutTemp_Upper_Limit": 95.0,
                # Present as a column but never captured: must not become a panel.
                "DiffTemp_Value": None,
                "DiffTemp_Upper_Limit": 80.0,
                "GroundSpd_Value": 10.0 + index,
            }
        )
    pd.DataFrame(rows).to_csv(
        telemetry / "alerts_detail_wide_with_gps.csv", index=False
    )
    return DashboardDataRepository(tmp_path)


def test_alert_detail_compares_each_sample_against_its_own_limit(tmp_path):
    """The threshold moves with machine state; using its maximum hid real breaches."""
    repository = _alert_detail_client(tmp_path)

    payload = json.loads(repository.query_alert_detail("cda", alert_id="7", unit_id="T_18"))
    record = next(
        item for item in payload["records"] if item["trigger"] == "EngCoolTemp"
    )

    assert record["peak_value"] == 100.0
    assert record["state_at_peak"] == "Operacional"
    assert record["upper_limit_at_peak"] == 105.0
    assert record["upper_limit_values"] == [95.0, 105.0]
    # The 99.0 idle sample breaches its 95.0 ceiling even though the peak did not
    # breach 105.0; comparing against the maximum reported zero.
    assert record["samples_above_limit"] == 1
    assert record["worst_above_value"] == 99.0
    assert record["max_above_exceedance"] == 4.0
    assert "estado de maquina" in payload["note"]


def test_signal_listing_separates_captured_values_from_limits(tmp_path):
    repository = _alert_detail_client(tmp_path)

    payload = json.loads(
        repository.query_alert_signals("cda", alert_id="7", unit_id="T_18")
    )

    assert payload["trigger"] == "EngCoolTemp"
    # A column with limits but no readings cannot be plotted.
    assert "DiffTemp" not in payload["signals_available"]
    assert {"EngCoolTemp", "TCOutTemp"} <= set(payload["signals_available"])
    assert "contexto de operacion" in payload["note"]


def test_sensor_series_defaults_to_the_triggering_signal(tmp_path):
    """The trigger is what caused the alert; plotting every sampled sensor is noise."""
    repository = _alert_detail_client(tmp_path)

    payload = repository.alert_signal_series("cda", alert_id="7", unit_id="T_18")

    assert payload["signals_selected"] == ["EngCoolTemp"]
    panel = payload["panels"][0]
    assert panel["values"] == [90.0, 100.0, 99.0, 80.0]
    assert panel["upper"] == [105.0, 105.0, 95.0, 95.0]
    assert panel["lower"] is None
    assert len(panel["times"]) == 4


def test_sensor_series_accepts_extra_signals_and_reports_unknown_ones(tmp_path):
    repository = _alert_detail_client(tmp_path)

    payload = repository.alert_signal_series(
        "cda", alert_id="7", unit_id="T_18", signals=("EngCoolTemp", "TCOutTemp")
    )

    assert payload["signals_selected"] == ["EngCoolTemp", "TCOutTemp"]
    assert len(payload["panels"]) == 2


def test_signal_names_resolve_regardless_of_case(tmp_path):
    """A transcription slip aborted the whole chart and the agent gave up."""
    repository = _alert_detail_client(tmp_path)

    for written in ("engcooltemp", "ENGCOOLTEMP", " EngCoolTemp "):
        payload = repository.alert_signal_series(
            "cda", alert_id="7", unit_id="T_18", signals=(written,)
        )
        # The canonical code is reported back, not the user's spelling.
        assert payload["signals_selected"] == ["EngCoolTemp"], written
        assert payload["signals_unknown"] == []


def test_requesting_only_unknown_signals_fails_instead_of_plotting_another(tmp_path):
    """Substituting the trigger would make the answer describe the wrong series."""
    repository = _alert_detail_client(tmp_path)

    with pytest.raises(CampbellDataError, match="Ninguna de las senales"):
        repository.alert_signal_series(
            "cda", alert_id="7", unit_id="T_18", signals=("DiffTemp",)
        )


def test_sensor_series_falls_back_to_the_latest_alert_of_a_unit(tmp_path):
    repository = _alert_detail_client(tmp_path)

    payload = repository.alert_signal_series("cda", unit_id="T_18")

    assert payload["alert_id"] == 7
    assert payload["trigger"] == "EngCoolTemp"


def test_sensor_chart_renders_one_panel_per_signal_with_its_band(tmp_path):
    registry = DashboardChartRegistry(_alert_detail_client(tmp_path))

    artifact = registry.render(
        "cda",
        "alert_sensor_trend",
        {"unit_id": "T_18", "alert_id": "7", "signal": "EngCoolTemp,TCOutTemp"},
    )

    assert artifact.chart_type == "line"
    layout = artifact.figure["layout"]
    # Two stacked panels share the x axis.
    assert "yaxis2" in layout
    titles = [
        annotation["text"]
        for annotation in layout.get("annotations", [])
        if annotation.get("text")
    ]
    assert any("refrigerante" in title.lower() for title in titles)
    assert artifact.summary["signals_plotted"] == ["EngCoolTemp", "TCOutTemp"]
    assert "estado de máquina" in artifact.summary["note"]


def test_sensor_chart_is_not_offered_to_a_client_without_the_detail_source(tmp_path):
    registry = DashboardChartRegistry(_oil_only_client(tmp_path))

    assert "alert_sensor_trend" not in {
        item["chart_id"] for item in registry.list_charts("enex")
    }
    with pytest.raises(CampbellDataError):
        registry.render("enex", "alert_sensor_trend", {"unit_id": "T_1"})


# -------------------- H05: capabilities honour services and effective presence


def test_h05_a_disabled_service_withdraws_its_analyses(tmp_path, monkeypatch):
    """Data on disk is not permission.

    With Monitoreo > Aceite switched off for a company, its oil files are still there and the
    declaration still lists them - and every oil analysis was still advertised, so the
    suggestion buttons offered questions the company cannot open in the dashboard either.
    """
    import config.client_services as services

    repository = _oil_only_client(tmp_path)
    monkeypatch.setattr(services, "is_service_enabled", lambda client_id, service_id: False)

    capabilities = repository.client_capabilities("enex")

    assert capabilities["available"] == []
    reasons = {item["key"]: item["reason"] for item in capabilities["unavailable"]}
    for key in ("oil_fleet", "oil_components", "oil_limits", "oil_lab_kpis"):
        assert "servicio no esta habilitado" in reasons[key], key
        assert "monitoring-oil" in reasons[key], key
    # And no technique is claimed either.
    assert capabilities["techniques"]["aceite"] is False


def test_h05_only_the_disabled_service_is_withdrawn(tmp_path, monkeypatch):
    """The gate is per service, not a switch that empties the catalogue."""
    import config.client_services as services

    repository = _oil_only_client(tmp_path)
    monkeypatch.setattr(
        services,
        "is_service_enabled",
        lambda client_id, service_id: service_id != "monitoring-oil",
    )

    available = {
        item["key"] for item in repository.client_capabilities("enex")["available"]
    }

    assert not [key for key in available if key.startswith("oil")]


def test_h05_an_unreadable_service_configuration_denies(tmp_path, monkeypatch):
    """Failing closed: offering an analysis a company switched off is the defect."""
    import config.client_services as services

    repository = _oil_only_client(tmp_path)

    def _explode(client_id, service_id):
        raise RuntimeError("configuración ilegible")

    monkeypatch.setattr(services, "is_service_enabled", _explode)

    assert repository.client_capabilities("enex")["available"] == []


def test_h05_a_data_root_that_is_not_there_advertises_nothing(tmp_path, monkeypatch):
    """The declaration says which columns, never whether the file is on disk right now."""
    import src.campbell_ai.data as data_module

    missing_root = tmp_path / "no-existe"
    repository = DashboardDataRepository(missing_root)
    data_module.clear_presence_cache()

    capabilities = repository.client_capabilities("enex")

    assert capabilities["available"] == []
    assert not missing_root.exists(), "la comprobación no debe crear el directorio"
    reasons = {item["key"]: item["reason"] for item in capabilities["unavailable"]}
    assert "Faltan fuentes" in reasons["oil_components"]


def test_a02_usability_rejects_absent_empty_and_unreadable_files(tmp_path):
    """"Present" and "usable" are different questions, and a capability promises the second.

    A zero-byte parquet exists, so an existence check kept advertising the analysis and the
    tool then failed with `ArrowInvalid: Parquet file size is 0 bytes`.
    """
    import pandas as pd

    import src.campbell_ai.data as data_module

    data_module.clear_presence_cache()
    path = tmp_path / "archivo.parquet"

    assert data_module.dataset_usability(path)["state"] == data_module.USABILITY_MISSING

    path.write_bytes(b"")
    data_module.clear_presence_cache()
    empty = data_module.dataset_usability(path)
    assert empty["usable"] is False
    assert empty["state"] == data_module.USABILITY_EMPTY

    path.write_bytes(b"no soy un parquet")
    data_module.clear_presence_cache()
    corrupt = data_module.dataset_usability(path)
    assert corrupt["usable"] is False
    assert corrupt["state"] == data_module.USABILITY_UNREADABLE

    pd.DataFrame([{"unitId": "T_1", "sampleDate": "2026-07-01"}]).to_parquet(path)
    data_module.clear_presence_cache()
    healthy = data_module.dataset_usability(path)
    assert healthy["usable"] is True
    assert healthy["state"] == data_module.USABILITY_OK
    # The real header travels, so required columns can be checked against the file.
    assert set(healthy["columns"]) == {"unitId", "sampleDate"}
    assert healthy["checked_at"]


def test_a02_a_replaced_file_invalidates_its_own_cached_answer(tmp_path):
    """Keyed by generation, so a new version is picked up without waiting for a TTL."""
    import pandas as pd

    import src.campbell_ai.data as data_module

    data_module.clear_presence_cache()
    path = tmp_path / "archivo.parquet"
    path.write_bytes(b"")

    assert data_module.dataset_usability(path)["usable"] is False

    pd.DataFrame([{"unitId": "T_1"}]).to_parquet(path)
    # No cache clear: the file's mtime and size changed, so the memo no longer applies.
    assert data_module.dataset_usability(path)["usable"] is True
    assert data_module.presence_cache_stats()["entries"] >= 1


def test_a02_a_broken_source_withdraws_only_its_own_capabilities(tmp_path):
    """A capability announced for an unusable file is the defect; the siblings stay."""
    import pandas as pd

    import src.campbell_ai.data as data_module

    repository = _oil_only_client(tmp_path)
    (tmp_path / "oil" / "golden" / "enex" / "classified.parquet").write_bytes(b"")
    data_module.clear_presence_cache()

    available = {
        item["key"] for item in repository.client_capabilities("enex")["available"]
    }
    assert "oil_components" not in available
    assert "oil_lab_kpis" not in available
    # machine_status is untouched, so the fleet view survives.
    assert "oil_fleet" in available

    # And a recovered source comes back.
    pd.DataFrame(
        [
            {
                "unitId": "T_1",
                "componentNameNormalized": "motor",
                "componentName": "motor",
                "report_status": "Normal",
                "sampleDate": "2026-07-01",
                "reportDate": "2026-07-03",
                "severity_score": 1,
            }
        ]
    ).to_parquet(tmp_path / "oil" / "golden" / "enex" / "classified.parquet")
    data_module.clear_presence_cache()

    recovered = {
        item["key"] for item in repository.client_capabilities("enex")["available"]
    }
    assert {"oil_components", "oil_lab_kpis"} <= recovered


def test_a02_the_payload_says_when_the_sources_were_checked(tmp_path):
    """A stored capability payload is a snapshot; its age has to be readable."""
    import src.campbell_ai.data as data_module

    repository = _oil_only_client(tmp_path)
    data_module.clear_presence_cache()

    capabilities = repository.client_capabilities("enex")

    assert capabilities["sources_checked_at"]


def test_h05_every_capability_declares_the_service_that_authorizes_it():
    """A capability with no service would be permanently ungated."""
    for capability in ANALYSIS_CAPABILITIES:
        assert capability.requires_services, capability.key
        for service in capability.requires_services:
            assert service in KNOWN_SERVICE_IDS, (capability.key, service)
