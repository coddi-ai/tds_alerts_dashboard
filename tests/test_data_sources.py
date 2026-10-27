"""Shared "Fuentes de datos" indicator: the component, the per-tab configuration and the
adapters that resolve a source's status."""

from datetime import date, datetime, timedelta, timezone

import pytest

from config.service_data_sources import (
    SERVICE_DATA_SOURCES,
    SOURCE_DATE_FIELDS,
    TECHNIQUE_SOURCE,
    DateField,
    data_sources_for_service,
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
from src.data.source_freshness import days_since, latest_data_date


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            if hasattr(child, "children") or hasattr(child, "id"):
                yield from _walk(child)
    elif children is not None and (hasattr(children, "children") or hasattr(children, "id")):
        yield from _walk(children)


def _chips(rendered):
    return [c for c in _walk(rendered) if "source-chip" in str(getattr(c, "className", "")).split()]


def _props(chip):
    return chip.to_plotly_json()["props"]


def _probe(source, status, note=""):
    return SourceProbe(client="X", technique="alerts", source=source, status=status, path=None, candidates=(), note=note)


# ---------------------------------------------------------------------------
# The component
# ---------------------------------------------------------------------------

def test_each_status_renders_its_own_chip_with_label_and_icon():
    rendered = render_data_sources([
        DataSource("a", "Alertas Consolidadas", AVAILABLE),
        DataSource("b", "Clasificación de Aceite", UNAVAILABLE),
        DataSource("c", "Frescura de Datos", PARTIAL, reason="Desactualizado desde 14:20"),
    ])
    by_source = {_props(c)["data-source"]: c for c in _chips(rendered)}
    assert list(by_source) == ["a", "b", "c"]

    available, unavailable, partial = by_source["a"], by_source["b"], by_source["c"]
    assert "source-chip--available" in available.className
    assert "Disponible" in str(available) and "fa-check-circle" in str(available)

    assert "source-chip--unavailable" in unavailable.className
    assert "No disponible" in str(unavailable) and "fa-exclamation-circle" in str(unavailable)

    assert "source-chip--partial" in partial.className
    assert "Desactualizado desde 14:20" in str(partial) and "fa-exclamation-triangle" in str(partial)

    for label in ("Alertas Consolidadas", "Clasificación de Aceite", "Frescura de Datos"):
        assert label in str(rendered)


def test_partial_without_a_reason_falls_back_to_the_generic_word():
    chip = _chips(render_data_sources([DataSource("c", "Fuente", PARTIAL)]))[0]
    assert "Parcial" in str(chip)


def test_an_unknown_status_is_never_shown_as_healthy():
    chip = _chips(render_data_sources([DataSource("x", "Fuente", "whatever")]))[0]
    assert "source-chip--unavailable" in chip.className
    assert _props(chip)["data-status"] == UNAVAILABLE


def test_no_sources_renders_nothing():
    assert render_data_sources([]) is None
    assert render_data_sources(()) is None


def test_chips_are_a_wrapping_row_not_a_left_border_box():
    rendered = render_data_sources([DataSource("a", "Fuente", AVAILABLE)])
    assert "borderLeft" not in str(rendered)
    assert "source-chips" in rendered.className.split()


# ---------------------------------------------------------------------------
# Per-tab configuration
# ---------------------------------------------------------------------------

def test_a_tab_without_configured_sources_has_none():
    for service in ("admin-main", "admin-user-registry", "agents-campbell-ai", "not-a-service"):
        assert data_sources_for_service(service) == ()


def test_predictive_components_share_one_configured_list():
    assert data_sources_for_service("predictive-motor") == data_sources_for_service("predictive-transmision")
    assert data_sources_for_service("predictive-motor") == SERVICE_DATA_SOURCES["predictive-*"]


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
    assert len(_chips(source_status.render_service_data_sources("CDA", "test-tab"))) == 1
    SERVICE_DATA_SOURCES["test-tab"] = ("alerts_consolidated", "data_freshness")
    assert len(_chips(source_status.render_service_data_sources("CDA", "test-tab"))) == 2


def test_fleet_overview_sources_follow_the_technique_readings(monkeypatch):
    from dashboard.components import fleet_overview

    monkeypatch.setattr(fleet_overview, "technique_availability", lambda client: {"alerts": True, "oil": False})
    sources = source_status.fleet_overview_data_sources("CDA")
    assert [(s.key, s.status) for s in sources] == [("alerts", AVAILABLE), ("oil", UNAVAILABLE)]

    monkeypatch.setattr(fleet_overview, "technique_availability", lambda client: {})
    assert source_status.render_fleet_overview_data_sources("CDA") is None


def test_no_legacy_left_border_banner_is_left():
    for name in ("render_service_source_status", "render_fleet_overview_source_status", "render_source_chips"):
        assert not hasattr(source_status, name)


# ---------------------------------------------------------------------------
# Days since last update
# ---------------------------------------------------------------------------

def _freshness(days):
    chip = _chips(render_data_sources([DataSource("a", "Fuente", AVAILABLE, days_since_update=days)]))[0]
    return str(chip)


def test_freshness_text_today_one_day_and_n_days():
    assert "Actualizado hoy" in _freshness(0)
    assert "Hace 0 días" not in _freshness(0)
    assert "Hace 1 día" in _freshness(1) and "Hace 1 días" not in _freshness(1)
    assert "Hace 3 días" in _freshness(3)


def test_unknown_freshness_shows_status_only():
    text = _freshness(None)
    assert "Disponible" in text
    assert "source-chip__freshness" not in text and "Hace" not in text and "Actualizado" not in text


@pytest.mark.parametrize("status", [AVAILABLE, UNAVAILABLE, PARTIAL])
@pytest.mark.parametrize("days", [None, 0, 3, 400])
def test_freshness_never_changes_the_status_tier(status, days):
    chip = _chips(render_data_sources([DataSource("a", "Fuente", status, days_since_update=days)]))[0]
    assert f"source-chip--{status}" in chip.className.split()
    assert _props(chip)["data-status"] == status


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


def test_every_catalog_source_a_tab_lists_has_a_date_field():
    for sources in SERVICE_DATA_SOURCES.values():
        for source in sources:
            assert source in SOURCE_DATE_FIELDS, source
    assert set(TECHNIQUE_SOURCE.values()) <= set(SOURCE_DATE_FIELDS)


def test_every_configured_tab_gets_freshness_without_opting_in(tmp_path, monkeypatch):
    csv = _write_csv(tmp_path / "a.csv", "x", ["1"])
    probes = {
        name: SourceProbe(client="X", technique="t", source=name, status="available", path=str(csv), candidates=())
        for services in SERVICE_DATA_SOURCES.values() for name in services
    }
    monkeypatch.setattr(source_status, "build_client_availability", lambda client: probes)
    monkeypatch.setattr(source_status, "latest_data_date", lambda path, field: date.today())
    for service in ("monitoring-alerts", "monitoring-telemetry", "monitoring-oil", "predictive-motor"):
        sources = source_status.service_data_sources("CDA", service)
        assert sources and all(s.days_since_update == 0 for s in sources)


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
