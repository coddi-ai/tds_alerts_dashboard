"""Fuentes de Datos popover on the pages added by the amendment: Informe de Confiabilidad, Campbell AI,
Troubleshooting, Reportabilidad, Informe preliminar de falla, Conexión ERP and Administración, plus the
three-state status model and how `n/total` is counted per client and component."""

from datetime import timedelta

import pandas as pd
import pytest

from config.service_data_sources import (
    CLIENT_GATED_SOURCES,
    NO_DATE_SOURCES,
    RESOLVED_SOURCES,
    SERVICE_DATA_SOURCES,
    SOURCE_DATE_FIELDS,
    data_sources_for_service,
)
from dashboard.callbacks import data_sources_callbacks
from dashboard.components import source_status
from dashboard.components.data_sources import AVAILABLE, PARTIAL, UNAVAILABLE, DataSource, render_data_sources
from src.data.catalog import MAINTENANCE_QUERY_FILES, build_client_availability, clear_availability_cache
from src.data.source_freshness import today_local

NEW_PAGES = (
    "monitoring-mantenciones", "agents-campbell-ai", "agents-troubleshooting", "reporting-main",
    "reporting-informe-falla", "integration-validacion-avisos", "integration-seguimiento-avisos",
    "admin-user-registry", "admin-mailing",
)


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            if hasattr(child, "children") or hasattr(child, "id"):
                yield from _walk(child)
    elif children is not None and (hasattr(children, "children") or hasattr(children, "id")):
        yield from _walk(children)


def _classes(rendered, name):
    return [c for c in _walk(rendered) if name in str(getattr(c, "className", "")).split()]


def _text(component):
    return " | ".join(n.children for n in _walk(component) if isinstance(getattr(n, "children", None), str))


def _ids(layout):
    return {getattr(c, "id", None) for c in _walk(layout)} - {None}


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    clear_availability_cache()
    yield tmp_path
    clear_availability_cache()


# ---------------------------------------------------------------------------
# Three-state status model and n/total
# ---------------------------------------------------------------------------

def test_the_chip_shows_one_word_per_state_with_an_icon_never_color_alone():
    rendered = render_data_sources([
        DataSource("a", "A", AVAILABLE), DataSource("p", "P", PARTIAL), DataSource("u", "U", UNAVAILABLE),
    ])
    chips = _classes(rendered, "ds-chip")
    assert [_text(c) for c in chips] == ["Disponible", "Parcial", "No Disponible"]
    for chip, icon in zip(chips, ("fa-check-circle", "fa-exclamation-triangle", "fa-exclamation-circle")):
        assert icon in str(chip)
    assert [c.className.split()[-1] for c in chips] == ["ds-chip--available", "ds-chip--partial", "ds-chip--unavailable"]


def test_a_reason_does_not_replace_the_state_word():
    rendered = render_data_sources([DataSource("p", "Fuente", PARTIAL, reason="Desactualizado desde 14:20")])
    assert _text(_classes(rendered, "ds-chip")[0]) == "Parcial"
    assert "Desactualizado desde 14:20" in str(_classes(rendered, "ds-source")[0].to_plotly_json()["props"]["title"])


@pytest.mark.parametrize("statuses, shown, tone", [
    ((AVAILABLE, AVAILABLE, AVAILABLE), "3/3", "ok"),
    ((AVAILABLE, PARTIAL, AVAILABLE), "2/3", "warn"),
    ((AVAILABLE, UNAVAILABLE, AVAILABLE), "2/3", "warn"),
    ((PARTIAL, PARTIAL), "0/2", "warn"),
    ((UNAVAILABLE,), "0/1", "warn"),
])
def test_n_counts_only_available_sources_and_the_badge_is_amber_otherwise(statuses, shown, tone):
    rendered = render_data_sources([DataSource(str(i), f"S{i}", s) for i, s in enumerate(statuses)])
    badge = _classes(rendered, "ds-badge")[0]
    assert _text(badge) == shown
    assert f"ds-badge--{tone}" in badge.className.split()


# ---------------------------------------------------------------------------
# total depends on the client and the component
# ---------------------------------------------------------------------------

def test_aceite_component_hours_are_listed_and_counted_only_for_the_clients_that_read_them(monkeypatch):
    monkeypatch.setattr(source_status, "build_client_availability", lambda client: {})
    totals = {
        client: len(source_status.service_data_sources(client, "monitoring-oil"))
        for client in ("CDA", "ENEX", "CAPSTONE", "EMIN")
    }
    assert totals == {"CDA": 4, "ENEX": 4, "CAPSTONE": 4, "EMIN": 3}
    assert CLIENT_GATED_SOURCES == {"oil_component_hours"}


def test_predictivo_lists_seven_or_eight_sources_depending_on_the_component(data_root):
    year, week = 2026, 40
    for table, technique in (("risk_scores", "predictive"), ("unit_status_summary", "predictive")):
        folder = data_root / technique / "golden" / "capstone" / "motor" / table / f"year={year}" / f"week={week}"
        folder.mkdir(parents=True)
        pd.DataFrame({"Unit": ["T_1"], "Fecha": [pd.Timestamp("2026-10-01")]}).to_parquet(folder / "p.parquet")
    meter = data_root / "oil" / "golden" / "capstone" / "motor" / "oil_meter_history" / "year=2026" / "week=40"
    meter.mkdir(parents=True)
    pd.DataFrame({"Unit": ["T_1"], "Fecha": [pd.Timestamp("2026-10-01")]}).to_parquet(meter / "p.parquet")

    motor = source_status.service_data_sources("CAPSTONE", "predictive-motor")
    transmision = source_status.service_data_sources("CAPSTONE", "predictive-transmision")
    assert (len(motor), len(transmision)) == (8, 7)


# ---------------------------------------------------------------------------
# Every new page has its list, probes and header slot
# ---------------------------------------------------------------------------

def test_every_new_page_is_configured_and_every_source_has_a_probe_or_a_resolver():
    probes = set(build_client_availability("CDA"))
    resolved = set(RESOLVED_SOURCES)
    from dashboard.components.source_status import _PREDICTIVE_TABLES

    for page in NEW_PAGES:
        sources = data_sources_for_service(page)
        assert sources, page
        for source in sources:
            assert source in probes or source in resolved or source in _PREDICTIVE_TABLES, (page, source)


def test_the_documented_lists_of_the_new_pages():
    assert data_sources_for_service("monitoring-mantenciones") == tuple(MAINTENANCE_QUERY_FILES) + ("maintenance_weekly", "oil_classified")
    assert len(data_sources_for_service("agents-campbell-ai")) == 13
    assert data_sources_for_service("agents-troubleshooting") == ("troubleshooting_agent",)
    assert data_sources_for_service("integration-seguimiento-avisos") == ("erp_warnings",)
    assert data_sources_for_service("integration-validacion-avisos") == ("erp_warnings", "erp_sap_config")
    assert data_sources_for_service("admin-mailing") == ("alerts_consolidated",)
    assert data_sources_for_service("admin-main") == ()  # a placeholder page: no data, no popover


def test_every_listed_source_has_a_date_field_or_is_documented_without_one():
    for page in NEW_PAGES:
        for source in SERVICE_DATA_SOURCES[page]:
            if source.startswith("predictive_") and not source.startswith("predictive_legacy"):
                continue
            assert source in SOURCE_DATE_FIELDS or source in NO_DATE_SOURCES, (page, source)


def test_every_header_slot_is_in_its_pages_layout():
    from dashboard.campbell_ai.layout import create_campbell_ai_layout
    from dashboard.tabs import (
        tab_integration_seguimiento_avisos, tab_integration_validacion_avisos, tab_mailing,
    )

    layouts = {
        "agents-campbell-ai": create_campbell_ai_layout(),
        "integration-validacion-avisos": tab_integration_validacion_avisos.create_layout(),
        "integration-seguimiento-avisos": tab_integration_seguimiento_avisos.create_layout(),
        "admin-mailing": tab_mailing.create_layout(),
    }
    for service, layout in layouts.items():
        assert data_sources_callbacks.HEADER_SLOTS[service] in _ids(layout), service
        assert _classes(layout, "ds-header-slot") or service == "agents-campbell-ai", service


@pytest.mark.parametrize("service, module", [
    ("agents-troubleshooting", "agents_troubleshooting"),
    ("reporting-main", "reporting_main"),
    ("reporting-informe-falla", "reporting_informe_falla"),
])
def test_the_page_modules_that_register_with_dash_carry_their_slot(service, module):
    """These modules call `dash.register_page` on import (it needs a running app), so the layout
    source is checked instead of building it."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "dashboard" / "pages" / f"{module}.py").read_text(encoding="utf-8")
    assert f'id="{data_sources_callbacks.HEADER_SLOTS[service]}"' in source
    assert "ds-header-slot" in source


def test_the_reliability_report_slot_is_in_the_page_header():
    from dashboard.tabs.tab_mantenciones_general import layout_mantenciones_general

    assert data_sources_callbacks.HEADER_SLOTS["monitoring-mantenciones"] in _ids(layout_mantenciones_general())


def test_the_user_registry_renders_its_popover_in_the_header():
    from dashboard.tabs import tab_user_registry

    layout = tab_user_registry.overview_layout(tab_user_registry.parse_query({}))
    assert _classes(layout, "ds-trigger")
    assert "Eventos de Acceso" in _text(layout)


def test_all_the_slots_are_filled_by_the_callbacks_module():
    assert set(data_sources_callbacks.HEADER_SLOTS) == set(NEW_PAGES) - {"admin-user-registry"}


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------

def _touch(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_maintenance_query_probes_follow_the_files_on_disk(data_root):
    views = data_root / "mantentions" / "golden" / "cda" / "Maintance_Labeler_Views"
    _touch(views / MAINTENANCE_QUERY_FILES["maintenance_query_3"])
    _touch(views / MAINTENANCE_QUERY_FILES["maintenance_query_10"])
    probes = build_client_availability("CDA")
    assert probes["maintenance_query_3"].status == "available"
    assert probes["maintenance_query_10"].status == "available"
    assert probes["maintenance_query_1"].status == "missing"


def test_erp_warnings_are_available_with_any_state_file_and_missing_without(data_root):
    assert build_client_availability("CDA")["erp_warnings"].status == "missing"
    clear_availability_cache()
    _touch(data_root / "warnings" / "cda" / "pending.parquet")
    probe = build_client_availability("CDA")["erp_warnings"]
    assert probe.status == "available" and "pending" in probe.note


def test_legacy_predictive_files_and_the_manifest_have_their_own_probes(data_root):
    _touch(data_root / "predictive" / "golden" / "cda" / "motor.csv", b"Unit,Fecha\nT_1,2026-07-18\n")
    _touch(data_root / "auxiliar" / "manifest.json", b"{}")
    probes = build_client_availability("CDA")
    assert probes["predictive_legacy_motor"].status == "available"
    assert probes["predictive_legacy_transmision"].status == "missing"
    assert probes["campbell_manifest"].status == "available"


# ---------------------------------------------------------------------------
# Resolvers (status from configuration)
# ---------------------------------------------------------------------------

def test_troubleshooting_agent_status_follows_its_configuration(monkeypatch):
    from dashboard import troubleshooting_handoff as handoff

    monkeypatch.setattr(source_status, "build_client_availability", lambda client: {})
    monkeypatch.setattr(handoff, "troubleshooting_agent_configured", lambda: False)
    (row,) = source_status.service_data_sources("CDA", "agents-troubleshooting")
    assert row.key == "troubleshooting_agent" and row.status == UNAVAILABLE and row.days_since_update is None


def test_reporting_store_needs_the_service_and_a_bucket(monkeypatch):
    import dashboard.report_files as report_files
    import src.data.report_store as report_store

    monkeypatch.setattr(source_status, "build_client_availability", lambda client: {})
    monkeypatch.setattr(report_files, "reporting_available", lambda client: True)
    monkeypatch.setattr(report_store, "get_report_store", lambda: None)
    sources = {s.key: s for s in source_status.service_data_sources("CDA", "reporting-main")}
    assert sources["reporting_store"].status == UNAVAILABLE

    monkeypatch.setattr(report_store, "get_report_store", lambda: object())
    sources = {s.key: s for s in source_status.service_data_sources("CDA", "reporting-main")}
    assert sources["reporting_store"].status == AVAILABLE


def test_reportabilidad_history_is_partial_when_only_some_components_publish_it(data_root):
    run = today_local() - timedelta(days=3)
    folder = data_root / "predictive" / "golden" / "cda" / "motor" / "unit_failure_analisis" / f"year={run.year}" / "week=40"
    folder.mkdir(parents=True)
    pd.DataFrame({"Unit": ["T_1"], "Fecha": [pd.Timestamp(run)]}).to_parquet(folder / "p.parquet")
    sources = {s.key: s for s in source_status.service_data_sources("CDA", "reporting-main")}
    history = sources["reporting_analysis_history"]
    assert history.status == PARTIAL and history.days_since_update == 3
    assert sources["reporting_curve_history"].status == UNAVAILABLE


def test_informe_de_falla_reads_the_engine_tables_and_follows_its_origin(data_root, monkeypatch):
    from src.informe_falla import config as informe_config

    run = today_local() - timedelta(days=2)
    folder = data_root / "predictive" / "golden" / "cda" / "motor" / "unit_status_summary" / f"year={run.year}" / "week=40"
    folder.mkdir(parents=True)
    pd.DataFrame({"Unit": ["T_1"], "Fecha": [pd.Timestamp(run)]}).to_parquet(folder / "p.parquet")
    sources = {s.key: s for s in source_status.service_data_sources("CDA", "reporting-informe-falla")}
    assert sources["predictive_unit_status"].status == AVAILABLE
    assert sources["predictive_unit_status"].days_since_update == 2
    assert sources["predictive_risk_scores"].status == UNAVAILABLE
    assert len(sources) == 7

    class _S3:
        origen, s3_bucket = "s3", None

    monkeypatch.setattr(informe_config, "get_informe_settings", lambda: _S3())
    sources = {s.key: s for s in source_status.service_data_sources("CDA", "reporting-informe-falla")}
    assert sources["predictive_unit_status"].status == UNAVAILABLE  # no bucket configured for the S3 origin


def test_a_failing_resolver_is_not_available_instead_of_breaking_the_page(monkeypatch):
    import src.auth_events.storage as storage

    def boom():
        raise RuntimeError("no storage")

    monkeypatch.setattr(storage, "get_storage", boom)
    (row,) = source_status.service_data_sources("", "admin-user-registry")
    assert row.status == UNAVAILABLE


# ---------------------------------------------------------------------------
# Resumen General dates
# ---------------------------------------------------------------------------

def test_resumen_telemetria_and_aceite_keep_their_own_data_files_as_date_source():
    from config.service_data_sources import TECHNIQUE_SOURCE

    assert TECHNIQUE_SOURCE["telemetry"] == "telemetry_unit_health"
    assert TECHNIQUE_SOURCE["oil"] == "oil_classified"
    assert "predictive" not in TECHNIQUE_SOURCE  # the documented exception: the v2 model run date
