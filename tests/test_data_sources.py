"""Shared "Fuentes de Datos" popover: the component, the per-tab configuration and the
adapters that resolve a source's status."""

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from config.service_data_sources import (
    CLIENT_GATED_SOURCES,
    NO_DATE_SOURCES,
    SERVICE_DATA_SOURCES,
    SOURCE_DATE_FIELDS,
    TECHNIQUE_SOURCE,
    DateField,
    data_sources_for_service,
    source_applies_to_client,
)
from dashboard.components import source_status
from dashboard.components.data_sources import (
    AVAILABLE,
    PARTIAL,
    UNAVAILABLE,
    DataSource,
    render_data_sources,
)
from src.data.catalog import SourceProbe
from src.data.source_freshness import days_since, latest_data_date, newest_week_partition, today_local


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            if hasattr(child, "children") or hasattr(child, "id"):
                yield from _walk(child)
    elif children is not None and (hasattr(children, "children") or hasattr(children, "id")):
        yield from _walk(children)


def _by_class(rendered, name):
    return [c for c in _walk(rendered) if name in str(getattr(c, "className", "")).split()]


def _entries(rendered):
    return _by_class(rendered, "ds-source")


def _props(component):
    return component.to_plotly_json()["props"]


def _text(component):
    """All the visible text of a component, in document order."""
    parts = []
    for node in _walk(component):
        children = getattr(node, "children", None)
        if isinstance(children, str):
            parts.append(children)
    return " | ".join(parts)


def _probe(source, status, note=""):
    return SourceProbe(client="X", technique="alerts", source=source, status=status, path=None, candidates=(), note=note)


# ---------------------------------------------------------------------------
# The component: button + popover
# ---------------------------------------------------------------------------

def test_the_trigger_is_a_real_button_with_the_dialog_aria_and_an_n_of_total_badge():
    rendered = render_data_sources([
        DataSource("a", "Alertas Consolidadas", AVAILABLE),
        DataSource("b", "Clasificación de Aceite", UNAVAILABLE),
    ], scope="monitoring-alerts")
    trigger = _by_class(rendered, "ds-trigger")[0]
    assert type(trigger).__name__ == "Button"
    props = _props(trigger)
    assert props["type"] == "button"
    assert props["aria-haspopup"] == "dialog"
    assert props["aria-expanded"] == "false"
    assert props["aria-controls"] == "ds-popover-monitoring-alerts"
    assert props["aria-label"].startswith("Fuentes de Datos")
    assert "Fuentes de Datos" in _text(trigger)
    assert _text(_by_class(trigger, "ds-badge")[0]) == "1/2"


def test_the_badge_is_amber_unless_every_source_is_available():
    amber = render_data_sources([DataSource("a", "A", AVAILABLE), DataSource("b", "B", UNAVAILABLE)])
    green = render_data_sources([DataSource("a", "A", AVAILABLE), DataSource("b", "B", AVAILABLE)])
    assert _by_class(amber, "ds-badge--warn") and not _by_class(amber, "ds-badge--ok")
    assert _by_class(green, "ds-badge--ok") and not _by_class(green, "ds-badge--warn")
    assert _text(_by_class(green, "ds-badge")[0]) == "2/2"


def test_a_partial_or_unknown_source_is_not_counted_as_available():
    rendered = render_data_sources([
        DataSource("a", "A", AVAILABLE), DataSource("b", "B", PARTIAL), DataSource("c", "C", "whatever"),
    ])
    assert _text(_by_class(rendered, "ds-badge")[0]) == "1/3"
    assert _by_class(rendered, "ds-badge--warn")


def test_the_popover_is_a_closed_dialog_with_a_title_and_an_icon_only_close_button():
    rendered = render_data_sources([DataSource("a", "A", AVAILABLE)], scope="oil")
    popover = _by_class(rendered, "ds-popover")[0]
    props = _props(popover)
    assert props["id"] == "ds-popover-oil"
    assert props["role"] == "dialog" and props["hidden"] is True
    assert props["aria-labelledby"] == "ds-title-oil"
    title = _by_class(popover, "ds-popover__title")[0]
    assert _props(title)["id"] == "ds-title-oil" and _text(title) == "Fuentes de Datos"
    close = _by_class(popover, "ds-close")[0]
    assert type(close).__name__ == "Button" and _props(close)["type"] == "button"
    assert _props(close)["aria-label"]
    assert _text(close) == ""  # icon only
    assert _by_class(popover, "ds-popover__caret")


def test_each_source_shows_its_name_a_status_chip_with_icon_and_text_and_its_last_update():
    rendered = render_data_sources([
        DataSource("a", "Alertas Consolidadas", AVAILABLE, days_since_update=3),
        DataSource("b", "Clasificación de Aceite", UNAVAILABLE),
        DataSource("c", "Frescura de Datos", PARTIAL, reason="Desactualizado desde 14:20"),
    ])
    entries = {_props(e)["data-source"]: e for e in _entries(rendered)}
    assert list(entries) == ["a", "b", "c"]

    available, unavailable, partial = entries["a"], entries["b"], entries["c"]
    assert "Alertas Consolidadas" in _text(available)
    assert "Disponible" in _text(_by_class(available, "ds-chip")[0])
    assert "fa-check-circle" in str(available)
    assert "Última actualización: Hace 3 días" in _text(available)

    assert "ds-chip--unavailable" in _by_class(unavailable, "ds-chip")[0].className
    assert "No Disponible" in _text(unavailable) and "fa-exclamation-circle" in str(unavailable)
    assert "Última actualización: —" in _text(unavailable)

    assert "ds-chip--partial" in _by_class(partial, "ds-chip")[0].className
    assert "Parcial" in _text(partial) and "fa-exclamation-triangle" in str(partial)
    assert "Desactualizado desde 14:20" in _props(partial)["title"]  # the reason is hover text, not the chip


def test_partial_without_a_reason_falls_back_to_the_generic_word():
    entry = _entries(render_data_sources([DataSource("c", "Fuente", PARTIAL)]))[0]
    assert "Parcial" in _text(entry)


def test_an_unknown_status_is_never_shown_as_healthy():
    entry = _entries(render_data_sources([DataSource("x", "Fuente", "whatever")]))[0]
    assert "ds-chip--unavailable" in _by_class(entry, "ds-chip")[0].className
    assert _props(entry)["data-status"] == UNAVAILABLE


def test_no_sources_renders_nothing():
    assert render_data_sources([]) is None
    assert render_data_sources(()) is None


def test_two_popovers_on_one_document_get_distinct_ids():
    one = _by_class(render_data_sources([DataSource("a", "A", AVAILABLE)], scope="predictive-motor"), "ds-popover")[0]
    two = _by_class(render_data_sources([DataSource("a", "A", AVAILABLE)], scope="monitoring-oil"), "ds-popover")[0]
    assert _props(one)["id"] != _props(two)["id"]


def test_the_old_always_open_strip_is_gone():
    rendered = render_data_sources([DataSource("a", "Fuente", AVAILABLE)])
    text = str(rendered)
    assert "source-chips" not in text and "source-chip" not in text and "borderLeft" not in text
    for name in ("render_service_source_status", "render_fleet_overview_source_status", "render_source_chips"):
        assert not hasattr(source_status, name)


# ---------------------------------------------------------------------------
# Last update text: the existing "Hace N días" logic
# ---------------------------------------------------------------------------

def _updated(days):
    return _text(_entries(render_data_sources([DataSource("a", "Fuente", AVAILABLE, days_since_update=days)]))[0])


def test_last_update_text_today_one_day_and_n_days():
    assert "Última actualización: Hoy" in _updated(0)
    assert "Hace 0 días" not in _updated(0)
    assert "Hace 1 día" in _updated(1) and "Hace 1 días" not in _updated(1)
    assert "Hace 3 días" in _updated(3)


def test_unknown_last_update_shows_a_dash():
    assert "Última actualización: —" in _updated(None)


@pytest.mark.parametrize("status", [AVAILABLE, UNAVAILABLE, PARTIAL])
@pytest.mark.parametrize("days", [None, 0, 3, 400])
def test_last_update_never_changes_the_status_tier(status, days):
    entry = _entries(render_data_sources([DataSource("a", "Fuente", status, days_since_update=days)]))[0]
    assert f"ds-chip--{status}" in _by_class(entry, "ds-chip")[0].className.split()
    assert _props(entry)["data-status"] == status


# ---------------------------------------------------------------------------
# Per-tab configuration (data_sources_documentation_dashboard.md)
# ---------------------------------------------------------------------------

def test_a_tab_without_configured_sources_has_none():
    for service in ("admin-main", "not-a-service"):
        assert data_sources_for_service(service) == ()


def test_the_documented_lists_are_the_configured_lists():
    assert data_sources_for_service("monitoring-alerts") == (
        "alerts_consolidated", "telemetry_alert_detail", "oil_classified", "oil_limits_four", "maintenance_weekly",
    )
    assert data_sources_for_service("monitoring-telemetry")[:3] == (
        "telemetry_unit_health", "telemetry_system_health", "telemetry_manifest",
    )
    assert len(data_sources_for_service("monitoring-telemetry")) == 9
    assert data_sources_for_service("monitoring-oil") == (
        "oil_classified", "oil_machine_status", "oil_limits_four", "oil_component_hours",
    )


def test_predictive_components_share_one_configured_list_of_the_v2_tables():
    assert data_sources_for_service("predictive-motor") == data_sources_for_service("predictive-transmision")
    assert data_sources_for_service("predictive-motor") == SERVICE_DATA_SOURCES["predictive-*"]
    # The legacy flat files are no longer read by any Predictivo page.
    assert "predictive_components" not in SERVICE_DATA_SOURCES["predictive-*"]
    assert "predictive_ai" not in SERVICE_DATA_SOURCES["predictive-*"]
    assert {"predictive_unit_status", "predictive_unit_analysis", "predictive_curve"} <= set(SERVICE_DATA_SOURCES["predictive-*"])


def test_the_component_hours_source_is_listed_only_for_the_clients_that_read_it(monkeypatch):
    from config.settings import get_settings

    assert CLIENT_GATED_SOURCES == {"oil_component_hours"}
    allowed = get_settings().component_hours_allowed_clients
    assert source_applies_to_client("oil_component_hours", allowed[0].lower())
    assert not source_applies_to_client("oil_component_hours", "EMIN")
    assert source_applies_to_client("oil_classified", "EMIN")
    monkeypatch.setattr(source_status, "build_client_availability", lambda client: {})
    keys = [s.key for s in source_status.service_data_sources("EMIN", "monitoring-oil")]
    assert "oil_component_hours" not in keys and "oil_classified" in keys


def test_page_with_no_sources_renders_nothing(monkeypatch):
    monkeypatch.setattr(source_status, "build_client_availability", lambda client: pytest.fail("must not probe"))
    assert source_status.render_service_data_sources("CDA", "admin-main") is None


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

def test_catalog_probe_statuses_map_onto_component_statuses(monkeypatch):
    monkeypatch.setitem(SERVICE_DATA_SOURCES, "test-tab", ("alerts_consolidated", "oil_classified", "telemetry_alert_detail", "data_freshness"))
    monkeypatch.setattr(source_status, "build_client_availability", lambda client: {
        "alerts_consolidated": _probe("alerts_consolidated", "available"),
        "oil_classified": _probe("oil_classified", "missing"),
        "telemetry_alert_detail": _probe("telemetry_alert_detail", "partial", note="Directorio sin archivos de datos."),
        # data_freshness has no probe at all: unavailable, not left out.
    })
    sources = source_status.service_data_sources("CDA", "test-tab")
    assert [(s.key, s.status) for s in sources] == [
        ("alerts_consolidated", AVAILABLE),
        ("oil_classified", UNAVAILABLE),
        ("telemetry_alert_detail", PARTIAL),
        ("data_freshness", UNAVAILABLE),
    ]
    assert sources[0].label == "Alertas Consolidadas"
    assert sources[2].detail == "Directorio sin archivos de datos."


def test_adding_a_source_to_a_tab_needs_only_configuration(monkeypatch):
    monkeypatch.setitem(SERVICE_DATA_SOURCES, "test-tab", ("alerts_consolidated",))
    monkeypatch.setattr(source_status, "build_client_availability", lambda client: {
        "alerts_consolidated": _probe("alerts_consolidated", "available"),
        "data_freshness": _probe("data_freshness", "available"),
    })
    assert len(_entries(source_status.render_service_data_sources("CDA", "test-tab"))) == 1
    SERVICE_DATA_SOURCES["test-tab"] = ("alerts_consolidated", "data_freshness")
    assert len(_entries(source_status.render_service_data_sources("CDA", "test-tab"))) == 2


def test_fleet_overview_sources_follow_the_technique_readings(monkeypatch):
    from dashboard.components import fleet_overview

    monkeypatch.setattr(fleet_overview, "technique_availability", lambda client: {"alerts": True, "oil": False})
    sources = source_status.fleet_overview_data_sources("CDA")
    assert [(s.key, s.status) for s in sources] == [("alerts", AVAILABLE), ("oil", UNAVAILABLE)]

    monkeypatch.setattr(fleet_overview, "technique_availability", lambda client: {})
    assert source_status.render_fleet_overview_data_sources("CDA") is None


# ---------------------------------------------------------------------------
# Predictivo reads the v2 tables, not the legacy files
# ---------------------------------------------------------------------------

def _write_partition(root, technique, client, component, table, year, week, fecha):
    folder = root / technique / "golden" / client / component / table / f"year={year}" / f"week={week:02d}"
    folder.mkdir(parents=True)
    pd.DataFrame({"Unit": ["T_1"], "Fecha": [pd.Timestamp(fecha)]}).to_parquet(folder / "part-0.parquet")


@pytest.fixture
def predictive_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    return tmp_path


def test_newest_week_partition_orders_numerically_not_alphabetically(predictive_root):
    for week in (9, 10):
        _write_partition(predictive_root, "predictive", "cda", "motor", "risk_scores", 2026, week, "2026-03-01")
    base = predictive_root / "predictive" / "golden" / "cda" / "motor" / "risk_scores"
    assert newest_week_partition(base).name == "week=10"
    assert newest_week_partition(predictive_root / "nothing") is None
    assert newest_week_partition(None) is None


def test_the_predictive_popover_reports_the_v2_run_date_and_not_the_legacy_csv(predictive_root):
    """Reproduces the "Hace 59 días" report: a stale legacy `<component>.csv` (and no
    `analisis_inteligente.parquet`) next to fresh v2 tables used to read "Componentes Predictivos
    Disponible · Hace N días" / "IA Predictiva · No Disponible" while the page showed the real run."""
    today = today_local()
    run = today - timedelta(days=4)
    legacy = predictive_root / "predictive" / "golden" / "capstone"
    legacy.mkdir(parents=True)
    (legacy / "motor.csv").write_text("Unit,Fecha\nT_1,%s\n" % (today - timedelta(days=59)).isoformat(), encoding="utf-8")
    for table in ("risk_scores", "unit_status_summary", "unit_failure_analisis"):
        _write_partition(predictive_root, "predictive", "capstone", "motor", table, run.isocalendar().year, run.isocalendar().week, run)

    sources = {s.key: s for s in source_status.service_data_sources("CAPSTONE", "predictive-motor")}
    assert "predictive_components" not in sources and "predictive_ai" not in sources
    assert [s.label for s in sources.values()][:2] == ["Puntaje de Riesgo", "Estado de Unidades"]
    assert sources["predictive_unit_status"].status == AVAILABLE
    assert sources["predictive_unit_status"].days_since_update == 4
    assert sources["predictive_unit_analysis"].status == AVAILABLE
    # Tables the component does not publish are listed as not available, never as available.
    assert sources["predictive_curve"].status == UNAVAILABLE
    assert sources["predictive_signal_status"].status == UNAVAILABLE
    # An optional table the component never publishes is not part of the page at all.
    assert "predictive_oil_meter" not in sources


def test_an_optional_predictive_table_is_listed_once_the_component_publishes_it(predictive_root):
    _write_partition(predictive_root, "oil", "capstone", "motor", "oil_meter_history", 2026, 40, "2026-10-01")
    sources = {s.key: s for s in source_status.service_data_sources("CAPSTONE", "predictive-motor")}
    assert sources["predictive_oil_meter"].status == AVAILABLE


def test_resumen_general_predictivo_row_is_dated_by_the_oldest_model_run(predictive_root, monkeypatch):
    from dashboard.components import fleet_overview

    today = today_local()
    for component, age in (("motor", 2), ("transmision", 9)):
        run = today - timedelta(days=age)
        _write_partition(predictive_root, "predictive", "cda", component, "unit_status_summary", run.isocalendar().year, run.isocalendar().week, run)
    monkeypatch.setattr(fleet_overview, "enabled_predictive_components", lambda client: ["motor", "transmision"])
    monkeypatch.setattr(fleet_overview, "technique_availability", lambda client: {"predictive": True})
    (source,) = source_status.fleet_overview_data_sources("CDA")
    assert source.key == "predictive" and source.days_since_update == 9


def _write_csv(path, column, values):
    path.write_text("\n".join([column, *values]) + "\n", encoding="utf-8")
    return path


TODAY = date(2026, 10, 26)
FIELD = DateField("Timestamp")


def test_freshness_uses_the_date_closest_to_today_inside_the_file(tmp_path):
    csv = _write_csv(tmp_path / "a.csv", "Timestamp", ["2026-10-01 10:00:00", "2026-10-23 08:00:00", "2026-09-01 00:00:00"])
    assert latest_data_date(str(csv), FIELD, TODAY) == date(2026, 10, 23)
    assert days_since(latest_data_date(str(csv), FIELD, TODAY), TODAY) == 3


def test_dates_after_today_are_ignored(tmp_path):
    csv = _write_csv(tmp_path / "a.csv", "Timestamp", ["2026-10-20", "2026-11-15"])
    assert latest_data_date(str(csv), FIELD, TODAY) == date(2026, 10, 20)
    # Nothing on or before today: no value rather than a negative age.
    assert latest_data_date(str(csv), FIELD, date(2026, 1, 1)) is None


def test_the_files_modified_time_is_irrelevant(tmp_path):
    csv = _write_csv(tmp_path / "a.csv", "Timestamp", ["2026-07-09 19:13:00"])  # file written just now
    assert days_since(latest_data_date(str(csv), FIELD, TODAY), TODAY) == 109


def test_timestamps_with_an_offset_are_read_in_chile_time(tmp_path):
    csv = _write_csv(tmp_path / "a.csv", "Timestamp", ["2026-10-26T01:00:00+00:00"])
    assert latest_data_date(str(csv), FIELD, TODAY) == date(2026, 10, 25)  # still the evening of the 25th in Chile


def test_parquet_folder_uses_every_file_matching_the_glob(tmp_path):
    import pandas as pd

    for week, stamp in (("26", "2026-07-01 04:00:00"), ("30", "2026-10-20 04:00:00")):
        part = tmp_path / "year=2026" / f"week={week}"
        part.mkdir(parents=True)
        pd.DataFrame({"evaluation_timestamp": [stamp]}).to_parquet(part / "x.parquet")
    field = DateField("evaluation_timestamp", glob="**/*.parquet")
    assert latest_data_date(str(tmp_path), field, TODAY) == date(2026, 10, 20)


def test_json_source_reads_a_key(tmp_path):
    manifest = tmp_path / "latest.json"
    manifest.write_text('{"execution_timestamp": "2026-10-24T04:43:58Z"}', encoding="utf-8")
    assert latest_data_date(str(manifest), DateField("execution_timestamp"), TODAY) == date(2026, 10, 24)


def test_a_rewritten_file_is_read_again(tmp_path):
    csv = _write_csv(tmp_path / "a.csv", "Timestamp", ["2026-10-01"])
    assert latest_data_date(str(csv), FIELD, TODAY) == date(2026, 10, 1)
    _write_csv(csv, "Timestamp", ["2026-10-01", "2026-10-25"])
    assert latest_data_date(str(csv), FIELD, TODAY) == date(2026, 10, 25)


@pytest.mark.parametrize("make", ["missing_file", "missing_column", "garbage_values", "no_path", "bad_json"])
def test_unreadable_source_gives_no_freshness(tmp_path, make):
    if make == "missing_file":
        path = str(tmp_path / "nope.csv")
    elif make == "missing_column":
        path = str(_write_csv(tmp_path / "a.csv", "Other", ["2026-10-01"]))
    elif make == "garbage_values":
        path = str(_write_csv(tmp_path / "a.csv", "Timestamp", ["abc", "def"]))
    elif make == "bad_json":
        bad = tmp_path / "latest.json"
        bad.write_text("{not json", encoding="utf-8")
        path = str(bad)
    else:
        path = None
    assert latest_data_date(path, FIELD, TODAY) is None


def test_adapter_measures_from_the_data_date_not_the_file(tmp_path, monkeypatch):
    csv = _write_csv(tmp_path / "a.csv", "Timestamp", ["2020-01-01"])
    probe = SourceProbe(client="X", technique="alerts", source="a", status="available", path=str(csv), candidates=(), modified_utc=datetime.now(timezone.utc).isoformat())
    days = source_status.source_days_since_update("alerts_consolidated", probe)
    assert days is not None and days > 2000  # years old data in a file written today

    # Missing file / no probe / no configured date field: status as usual, no freshness.
    assert source_status.source_days_since_update("alerts_consolidated", _probe("a", "missing")) is None
    assert source_status.source_days_since_update("alerts_consolidated", None) is None
    assert source_status.source_days_since_update("not_configured", probe) is None


def test_every_catalog_source_a_tab_lists_has_a_date_field_or_is_documented_without_one():
    for service, sources in SERVICE_DATA_SOURCES.items():
        for source in sources:
            if source.startswith("predictive_") and not source.startswith("predictive_legacy"):
                continue  # v2 tables: dated from their newest partition, not from this mapping
            assert source in SOURCE_DATE_FIELDS or source in NO_DATE_SOURCES, source
    assert not NO_DATE_SOURCES & set(SOURCE_DATE_FIELDS)
    assert set(TECHNIQUE_SOURCE.values()) <= set(SOURCE_DATE_FIELDS)


def test_every_configured_tab_gets_freshness_without_opting_in(tmp_path, monkeypatch):
    csv = _write_csv(tmp_path / "a.csv", "x", ["1"])
    probes = {
        name: SourceProbe(client="X", technique="t", source=name, status="available", path=str(csv), candidates=())
        for services in SERVICE_DATA_SOURCES.values() for name in services
    }
    monkeypatch.setattr(source_status, "build_client_availability", lambda client: probes)
    monkeypatch.setattr(source_status, "latest_data_date", lambda path, field: date.today())
    for service in ("monitoring-alerts", "monitoring-telemetry", "monitoring-oil"):
        sources = source_status.service_data_sources("CDA", service)
        assert sources
        for s in sources:
            expected = None if s.key in NO_DATE_SOURCES else 0
            assert s.days_since_update == expected, (service, s.key)


def test_fleet_overview_techniques_take_freshness_from_their_backing_source(monkeypatch):
    from dashboard.components import fleet_overview

    monkeypatch.setattr(fleet_overview, "technique_availability", lambda client: {"alerts": True, "oil": False})
    monkeypatch.setattr(source_status, "build_client_availability", lambda client: {
        "alerts_consolidated": SourceProbe(client="X", technique="alerts", source="alerts_consolidated", status="available", path="p", candidates=()),
    })
    monkeypatch.setattr(source_status, "latest_data_date", lambda path, field: date.today() - timedelta(days=2))
    sources = {s.key: s for s in source_status.fleet_overview_data_sources("CDA")}
    assert sources["alerts"].days_since_update == 2
    assert sources["oil"].days_since_update is None  # no probe for it: no freshness, status unchanged
    assert sources["oil"].status == UNAVAILABLE
