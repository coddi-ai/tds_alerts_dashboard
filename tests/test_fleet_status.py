"""The General tab's golden layer (src/data/fleet_status.py, scripts/build_fleet_status.py).

Covers the requirement "Unit status dashboard (criteria visibility, "Sin Datos" fix, unit merge, golden-layer
reads)":

* a unit with no alerts is Normal in Alertas; Sin Datos only where there is nothing to evaluate;
* `CT-184` / `CT_184` are one row, with every technique merged, and the Estado comes from the merge;
* the file is written atomically, a failed run leaves the previous one, and the view reads only the file;
* the criteria printed on the page are the ones the classification uses.

The sources are patched with `tests.test_fleet_overview._patch_all_sources`, the same canned data the
view's own tests use; the golden file is written to a temporary data root, never to `data/`.
"""

from __future__ import annotations

import ast
import importlib.util
import os

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

import dashboard.components.fleet_overview as fo
import src.data.fleet_status as fs
from config import estado_rules as rules
from dashboard.components import fleet_criteria
from dashboard.components.labels import age_text
from src.data.unit_ids import normalize_unit_id, unit_key, unit_matches
from tests.test_fleet_overview import (
    _all_rows,
    _band_titles,
    _isolated_data_root,
    _patch_all_sources,
    _publish,
    _text,
    _walk,
)

ROOT = Path(__file__).resolve().parents[1]
ALL_ENABLED = {"monitoring-alerts": True, "monitoring-telemetry": True, "monitoring-oil": True,
               "monitoring-mantenciones": True}


@pytest.fixture(autouse=True)
def _clean_caches():
    fo._ENTRIES.clear()
    fs._read_cached.cache_clear()
    yield
    fo._ENTRIES.clear()
    fs._read_cached.cache_clear()


def _script():
    spec = importlib.util.spec_from_file_location("build_fleet_status_script", ROOT / "scripts" / "build_fleet_status.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _by_unit(frame) -> pd.DataFrame:
    return frame.set_index("unit_id")


# ---------------------------------------------------------------------------
# Unit ids: one spelling per unit
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,name", [
    ("CT_184", "CT-184"), ("CT-184", "CT-184"), ("BULL_027", "BULL-027"), ("21_CRU_001", "21-CRU-001"),
    ("T_9", "T-9"), ("CA-80", "CA-80"), ("CT__184", "CT-184"),
])
def test_normalize_unit_id_hyphenates_the_separators(raw, name):
    assert normalize_unit_id(raw) == name


def test_normalize_unit_id_changes_nothing_but_the_separators():
    """Case, spaces and zero padding are the unit's own: they are not part of this rule."""
    assert normalize_unit_id("ca_80") == "ca-80"
    assert normalize_unit_id("CA 80") == "CA 80"
    assert normalize_unit_id("T_09") == "T-09"


@pytest.mark.parametrize("a,b", [("CT_184", "CT-184"), ("T_09", "T_9"), ("T_09", "T-9"), ("BULL_027", "BULL-27")])
def test_two_spellings_of_a_unit_share_one_identity(a, b):
    assert unit_key(a) == unit_key(b)


def test_different_units_never_share_an_identity():
    assert unit_key("CT-184") != unit_key("CT-185")
    assert unit_key("T_9") != unit_key("T_90")
    assert unit_key("CA-10") != unit_key("CA-1")


def test_unit_matches_finds_every_spelling_in_a_column():
    column = pd.Series(["CT-184", "CT_184", "CT_185", "T_09", None])
    assert list(unit_matches(column, "CT-184")) == [True, True, False, False, False]
    assert list(unit_matches(column, "T-9")) == [False, False, False, True, False]


# ---------------------------------------------------------------------------
# Change 2: "Sin Datos" in Alertas
# ---------------------------------------------------------------------------

def test_a_unit_with_no_alerts_is_normal_in_alertas(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True, "monitoring-oil": True},
        alerts=({"U1": "Alerta"}, {}, "Ok", "1h"),
        oil={"U1": "Normal", "U2": "Normal"},  # U2 is in the fleet, but never had an alert
        freshness={("oil", "U1"): ("Ok", "1 día"), ("oil", "U2"): ("Ok", "1 día")},
        publish=False,
    )
    frame = _by_unit(fs.build_fleet_status("TESTCO"))
    assert frame.loc["U2", "alerts_estado"] == "Normal"
    assert frame.loc["U1", "alerts_estado"] == "Alerta"
    assert frame.loc["U2", "estado"] == "Normal"


def test_sin_datos_in_alertas_only_when_there_is_no_feed_to_evaluate(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True, "monitoring-oil": True},
        alerts=({}, {}, "Sin Datos", "N/A"),  # the client has no (dated) alerts at all
        oil={"U1": "Normal"}, freshness={("oil", "U1"): ("Ok", "1 día")},
        publish=False,
    )
    assert _by_unit(fs.build_fleet_status("TESTCO")).loc["U1", "alerts_estado"] == "Sin Datos"


def test_sin_datos_stays_for_a_technique_with_no_record_of_the_unit(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True, "monitoring-oil": True},
        alerts=({"U1": "Alerta", "U2": "Alerta"}, {}, "Ok", "1h"),
        oil={"U1": "Normal"}, freshness={("oil", "U1"): ("Ok", "1 día")},  # U2 is not in the oil source
        publish=False,
    )
    frame = _by_unit(fs.build_fleet_status("TESTCO"))
    assert frame.loc["U2", "oil_estado"] == "Sin Datos"
    assert frame.loc["U1", "oil_estado"] == "Normal"


def test_the_alert_feed_age_still_applies_to_a_unit_with_no_alerts(monkeypatch):
    """Same rule as every other cell (config/estado_rules.technique_estado): a feed whose newest alert is
    weeks old is stale data, whether or not the unit has alerts in it."""
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True, "monitoring-oil": True},
        alerts=({"U1": "Alerta"}, {}, "Preocupante", "40 días"),
        oil={"U1": "Normal", "U2": "Normal"},
        freshness={("oil", "U1"): ("Ok", "1 día"), ("oil", "U2"): ("Ok", "1 día")},
        publish=False,
    )
    frame = _by_unit(fs.build_fleet_status("TESTCO"))
    assert frame.loc["U2", "alerts_estado"] == "Anormal" and frame.loc["U2", "alerts_driver"] == "data"


# ---------------------------------------------------------------------------
# Change 3: one row per unit, merged
# ---------------------------------------------------------------------------

def _merge_fleet(monkeypatch, **overrides):
    sources = dict(
        enabled={"monitoring-alerts": True, "monitoring-oil": True},
        alerts=({"CT-184": "Alerta"}, {"CT-184": 9.0}, "Ok", "1h"),
        oil={"CT_184": "Anormal"},
        freshness={("oil", "CT_184"): ("Ok", "2 días")},
    )
    sources.update(overrides)
    _patch_all_sources(monkeypatch, publish=False, **sources)
    monkeypatch.setattr(fs, "_alerts_source_units", lambda client: {"CT-184": "CT-184"})
    return fs.build_fleet_status("TESTCO")


def test_ct_184_and_ct_underscore_184_are_one_row_with_every_technique_merged(monkeypatch):
    frame = _merge_fleet(monkeypatch)
    assert list(frame["unit_id"]) == ["CT-184"]
    row = frame.iloc[0]
    assert row["alerts_estado"] == "Alerta"  # from the alert feed's spelling
    assert row["oil_estado"] == "Anormal"    # from the oil report's spelling
    assert row["alerts_source_unit"] == "CT-184" and row["oil_source_unit"] == "CT_184"


def test_the_overall_estado_is_calculated_after_the_merge(monkeypatch):
    """Alerta in one spelling, Anormal in the other: the unit is Anormal - not Alerta, not two units."""
    frame = _merge_fleet(monkeypatch)
    assert frame.iloc[0]["estado"] == "Anormal"
    merged_view = fo.get_unit_snapshot  # the view reads the same value (see the golden-file tests)
    assert callable(merged_view)


def test_zero_padded_spellings_of_predictive_join_the_other_techniques(monkeypatch):
    frame = _merge_fleet(
        monkeypatch,
        enabled={"monitoring-alerts": True, "monitoring-oil": True},
        alerts=({"T_9": "Normal"}, {}, "Ok", "1h"),
        oil={"T_9": "Normal"}, freshness={("oil", "T_9"): ("Ok", "1 día")},
        predictive_components=["motor"],
        predictive=({"T-9": "Alerta"}, {"T-9": 3.0}, "Ok", "1 día"),  # Predictivo wrote T_09
    )
    assert list(frame["unit_id"]) == ["T-9"]
    assert frame.iloc[0]["predictive_estado"] == "Alerta" and frame.iloc[0]["estado"] == "Alerta"


def test_one_source_spelling_a_unit_two_ways_keeps_the_worst_status(monkeypatch):
    frame = _merge_fleet(
        monkeypatch, oil={"CT_184": "Normal", "CT-184": "Anormal"},
        freshness={("oil", "CT_184"): ("Ok", "2 días"), ("oil", "CT-184"): ("Ok", "2 días")},
    )
    assert list(frame["unit_id"]) == ["CT-184"]
    assert frame.iloc[0]["oil_estado"] == "Anormal"


def test_no_unit_appears_twice(monkeypatch):
    units = [f"CT_{n}" for n in range(180, 190)]
    _patch_all_sources(
        monkeypatch, enabled={"monitoring-alerts": True, "monitoring-oil": True},
        alerts=({u.replace("_", "-"): "Alerta" for u in units}, {}, "Ok", "1h"),
        oil={u: "Normal" for u in units},
        freshness={("oil", u): ("Ok", "1 día") for u in units},
        publish=False,
    )
    frame = fs.build_fleet_status("TESTCO")
    assert len(frame) == len(units) and frame["unit_id"].is_unique
    assert all("_" not in unit for unit in frame["unit_id"])


def test_the_view_shows_the_merged_unit_once_with_its_name_hyphenated(monkeypatch):
    _merge_fleet(monkeypatch)
    _publish()
    result = fo.build_fleet_overview("TESTCO")
    assert _all_rows(result) == {"CT-184": ["Anormal", "Alerta", "Anormal"]}
    assert _band_titles(result) == ["UNIDADES ANORMAL (1)"]
    assert fo.get_unit_snapshot("TESTCO", "CT_184")["unit"] == "CT-184"  # an old link still finds it


def test_alert_counts_and_the_maintenance_signal_are_stored(monkeypatch):
    _patch_all_sources(
        monkeypatch, enabled=ALL_ENABLED,
        alerts=({"U1": "Alerta"}, {"U1": 4.5}, "Ok", "1h"), alert_counts={"U1": (1, 3, 5)},
        telemetry={"U1": "Normal"}, oil={"U1": "Normal"},
        maintenance=({"U1": "SANO"}, "Ok", "1 día"),
        freshness={("telemetry", "U1"): ("Ok", "1h"), ("oil", "U1"): ("Ok", "1 día")},
        publish=False,
    )
    frame = fs.build_fleet_status("TESTCO")
    row = frame.iloc[0]
    assert (row["alerts_count_7d"], row["alerts_count_28d"], row["alerts_count_56d"]) == (1, 3, 5)
    assert row["alerts_score"] == 4.5
    assert fs.techniques_in(frame) == ["alerts", "telemetry", "oil", "maintenance"]
    assert row["maintenance_estado"] == "SANO" and row["estado"] == "Alerta"  # Maintenance never enters the Estado


# ---------------------------------------------------------------------------
# The golden file: where, atomically, last good file wins
# ---------------------------------------------------------------------------

def _canned(monkeypatch, units=("U1", "U2"), **overrides):
    sources = dict(
        enabled={"monitoring-alerts": True},
        alerts=({u: "Normal" for u in units}, {}, "Ok", "1h"),
    )
    sources.update(overrides)
    _patch_all_sources(monkeypatch, publish=False, **sources)


def _leftovers(path: Path) -> list:
    return sorted(p.name for p in path.parent.iterdir() if p.name != path.name)


def test_the_file_lives_at_data_general_golden_client(monkeypatch):
    root = _isolated_data_root(monkeypatch)
    path = fs.golden_path("CAPSTONE")
    assert path == Path(root) / "general" / "golden" / "capstone" / "fleet_status.parquet"


def test_a_run_writes_one_file_per_client_and_it_reads_back(monkeypatch):
    _canned(monkeypatch)
    for client in ("TESTCO", "OTHERCO"):
        assert fs.refresh_client(client) == fs.golden_path(client)
    frame = fs.load_fleet_status("TESTCO")
    assert list(frame["unit_id"]) == ["U1", "U2"] and list(frame["estado"]) == ["Normal", "Normal"]
    assert fs.golden_path("OTHERCO").is_file()


def test_each_run_overwrites_the_previous_output(monkeypatch):
    _canned(monkeypatch, units=("U1",))
    fs.refresh_client("TESTCO")
    _canned(monkeypatch, units=("U1", "U2", "U3"))
    fs.refresh_client("TESTCO")
    assert list(fs.load_fleet_status("TESTCO")["unit_id"]) == ["U1", "U2", "U3"]
    assert _leftovers(fs.golden_path("TESTCO")) == []


def test_a_failed_build_keeps_the_previous_file_untouched(monkeypatch):
    _canned(monkeypatch)
    path = fs.refresh_client("TESTCO")
    before = path.read_bytes()

    def broken(client):
        raise RuntimeError("the oil source is down")

    monkeypatch.setattr(fs, "_oil_status_map", broken)
    monkeypatch.setattr(fs, "is_service_enabled", lambda client, sid: sid in ("monitoring-alerts", "monitoring-oil"))
    assert _script().run(["testco"]) == 1
    assert path.read_bytes() == before and _leftovers(path) == []


def test_a_crash_while_writing_leaves_the_previous_file_and_no_partial_one(monkeypatch):
    _canned(monkeypatch)
    path = fs.refresh_client("TESTCO")
    before = path.read_bytes()
    _canned(monkeypatch, units=("U1", "U2", "U3", "U4"))

    def half_written(self, target, *args, **kwargs):
        Path(target).write_bytes(b"PAR1 half a file")
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", half_written)
    with pytest.raises(OSError):
        fs.refresh_client("TESTCO")
    assert path.read_bytes() == before and _leftovers(path) == []


def test_a_run_that_finds_no_unit_publishes_nothing_and_keeps_the_previous_file(monkeypatch):
    _canned(monkeypatch)
    path = fs.refresh_client("TESTCO")
    before = path.read_bytes()
    _canned(monkeypatch, units=())
    with pytest.raises(fs.EmptyFleetError):
        fs.refresh_client("TESTCO")
    assert path.read_bytes() == before and _leftovers(path) == []


def test_a_first_failing_run_leaves_no_file_at_all(monkeypatch):
    _canned(monkeypatch, units=())
    with pytest.raises(fs.EmptyFleetError):
        fs.refresh_client("TESTCO")
    assert not fs.golden_path("TESTCO").exists()
    assert not fs.golden_path("TESTCO").parent.exists() or not any(fs.golden_path("TESTCO").parent.iterdir())


def test_a_frame_with_a_duplicated_unit_is_not_published(monkeypatch):
    _canned(monkeypatch)
    frame = fs.build_fleet_status("TESTCO")
    with pytest.raises(fs.EmptyFleetError, match="twice"):
        fs.write_golden("TESTCO", pd.concat([frame, frame]))


def test_one_client_failing_does_not_stop_the_others(monkeypatch):
    _canned(monkeypatch)
    real = fs.build_fleet_status

    def build(client):
        if client.upper() == "FULLCO":
            raise RuntimeError("only this one is broken")
        return real(client)

    monkeypatch.setattr(fs, "build_fleet_status", build)
    assert _script().run(["testco", "fullco", "oilonlyco"]) == 1
    assert fs.golden_path("TESTCO").is_file() and fs.golden_path("OILONLYCO").is_file()
    assert not fs.golden_path("FULLCO").exists()


def test_only_missing_builds_just_the_clients_without_a_file(monkeypatch):
    _canned(monkeypatch)
    fs.refresh_client("TESTCO")
    stamp = fs.golden_path("TESTCO").stat().st_mtime_ns
    assert fs.missing_clients(["testco", "fullco"]) == ["fullco"]
    assert _script().run(["testco", "fullco"], only_missing=True) == 0
    assert fs.golden_path("FULLCO").is_file()
    assert fs.golden_path("TESTCO").stat().st_mtime_ns == stamp
    assert _script().run(["testco", "fullco"], only_missing=True) == 0  # nothing left to do


def test_a_client_with_no_technique_gets_no_file(monkeypatch):
    _patch_all_sources(monkeypatch, enabled={}, publish=False)
    assert _script().run(["testco"]) == 0
    assert not fs.golden_path("TESTCO").exists()


# ---------------------------------------------------------------------------
# The view only reads the file
# ---------------------------------------------------------------------------

def _forbid_raw_sources(monkeypatch):
    """Any read of a raw source from now on fails the test."""
    def boom(*args, **kwargs):
        raise AssertionError("the view went to a raw source")

    for name in ("_alerts_status_map", "_alerts_window_counts", "_alerts_source_units", "_telemetry_status_map",
                 "_oil_status_map", "_maintenance_status_map", "_predictive_status_map",
                 "_telemetry_tribologia_freshness_map", "build_fleet_status"):
        monkeypatch.setattr(fs, name, boom)


def test_the_view_draws_from_the_file_without_touching_a_raw_source(monkeypatch):
    _canned(monkeypatch)
    fs.refresh_client("TESTCO")
    _forbid_raw_sources(monkeypatch)
    fo._ENTRIES.clear()
    result = fo.build_fleet_overview("TESTCO")
    assert _all_rows(result) == {"U1": ["Normal", "Normal"], "U2": ["Normal", "Normal"]}
    assert [u["unit"] for u in fo.get_ordered_units("TESTCO")] == ["U1", "U2"]
    assert fo.technique_availability("TESTCO") == {"alerts": True}
    assert fo.get_band_rows_chunk("TESTCO", "Normal", 0)[1] == 0


def test_without_the_file_the_view_says_so_and_does_not_rebuild_it(monkeypatch):
    _canned(monkeypatch)
    _forbid_raw_sources(monkeypatch)
    result = fo.build_fleet_overview("TESTCO")
    assert "todavía no están disponibles" in _text(result)
    assert not any(isinstance(n, fo.html.Table) for n in _walk(result))
    assert fo.get_ordered_units("TESTCO") == [] and fo.technique_availability("TESTCO") == {}
    assert fo.get_unit_snapshot("TESTCO", "U1") is None
    assert fo.get_band_rows_chunk("TESTCO", "Normal", 1) == ([], 0)
    assert not fs.golden_path("TESTCO").exists()  # reading did not create it either


@pytest.mark.parametrize("content", [b"", b"not a parquet file", b"PAR1"])
def test_an_unreadable_file_is_unavailable_not_rebuilt(monkeypatch, content):
    _canned(monkeypatch)
    _forbid_raw_sources(monkeypatch)
    path = fs.golden_path("TESTCO")
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    assert "todavía no están disponibles" in _text(fo.build_fleet_overview("TESTCO"))
    assert fo.get_ordered_units("TESTCO") == []
    with pytest.raises(fs.FleetStatusUnavailable):
        fs.load_fleet_status("TESTCO")


def test_after_a_failed_run_the_view_keeps_showing_the_last_good_data(monkeypatch):
    _canned(monkeypatch)
    fs.refresh_client("TESTCO")
    first = _all_rows(fo.build_fleet_overview("TESTCO"))

    _canned(monkeypatch, units=("U1", "U2", "U3"))

    def broken(client):
        raise RuntimeError("source down")

    monkeypatch.setattr(fs, "_alerts_status_map", broken)
    assert _script().run(["testco"]) == 1
    assert _all_rows(fo.build_fleet_overview("TESTCO")) == first


def test_the_view_picks_up_the_next_run_without_a_restart(monkeypatch):
    _canned(monkeypatch, units=("U1",))
    fs.refresh_client("TESTCO")
    assert list(_all_rows(fo.build_fleet_overview("TESTCO"))) == ["U1"]
    _canned(monkeypatch, units=("U1", "U2"))
    os.utime(fs.golden_path("TESTCO"), None)
    fs.refresh_client("TESTCO")
    assert list(_all_rows(fo.build_fleet_overview("TESTCO"))) == ["U1", "U2"]


def test_the_view_module_has_no_way_to_the_raw_sources():
    """Structural guard: the component imports no loader and no raw-source helper."""
    tree = ast.parse((ROOT / "dashboard" / "components" / "fleet_overview.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    forbidden = ("src.data.loaders", "src.data.predictive_v2", "dashboard.callbacks.data_freshness_callbacks",
                 "dashboard.callbacks.overview_general_callbacks")
    assert not [name for name in imported if name.startswith(forbidden)], imported
    assert not hasattr(fo, "_compute_unit_entries")


# ---------------------------------------------------------------------------
# Criteria visibility: what the page says is what the run applies
# ---------------------------------------------------------------------------

def _criteria_text(monkeypatch, enabled=None, predictive=("motor",)):
    _patch_all_sources(monkeypatch, enabled=enabled or ALL_ENABLED, predictive_components=list(predictive), publish=False)
    return _text(fleet_criteria.render_fleet_criteria("TESTCO"))


def test_the_page_prints_the_criteria_of_every_state_of_every_technique(monkeypatch):
    text = _criteria_text(monkeypatch)
    for technique in ("Alertas", "Telemetría", "Tribología", "Predictivo"):
        assert technique in text
    assert "Mantención no participa" in text
    for state in ("Normal", "Alerta", "Anormal"):
        assert state in text
    assert "Sin Datos" in text and "Anormal > Alerta > Normal" in text


def test_the_numbers_on_the_page_are_the_constants_the_run_classifies_with(monkeypatch):
    text = _criteria_text(monkeypatch)
    assert f"{rules.ALERTS_ALERTA_MAX_SCORE}." in text
    assert f"últimos {rules.ALERTS_WINDOW_DAYS} días" in text
    assert f"llega a {rules.OIL_SCORE_ANORMAL_FROM}" in text
    for technique, key in (("Alertas", "Alertas"), ("Telemetría", "Telemetria"), ("Tribología", "Tribologia"),
                           ("Predictivo", "Predictivo")):
        limits = rules.staleness_floor_limits(key)
        assert limits, key
        for age in limits.values():
            assert age_text(age) in text


def test_a_technique_the_client_lacks_is_not_described(monkeypatch):
    text = _criteria_text(monkeypatch, enabled={"monitoring-oil": True}, predictive=())
    assert "Tribología" in text
    assert "Telemetría" not in text and "Predictivo" not in text and "puntaje de alertas" not in text.lower()


def test_a_client_with_no_technique_gets_no_panel(monkeypatch):
    _patch_all_sources(monkeypatch, enabled={}, publish=False)
    assert "Cómo se asignan" not in _text(fleet_criteria.render_fleet_criteria("TESTCO"))


def test_the_staleness_sentences_follow_the_rule(monkeypatch):
    """If an age tier no longer forces a state, the page must not say it does."""
    _patch_all_sources(monkeypatch, enabled={"monitoring-alerts": True}, publish=False)
    monkeypatch.setattr(rules, "STALENESS_FLOOR", {"Ok": "Normal", "Atención": "Normal", "Preocupante": "Anormal"})
    sentences = fleet_criteria.stale_data_sentences("alerts")
    assert len(sentences) == 1 and "Anormal" in sentences[0]


def test_the_criteria_are_in_both_languages(monkeypatch):
    from src.i18n import forced_language

    _patch_all_sources(monkeypatch, enabled=ALL_ENABLED, publish=False)
    with forced_language("en"):
        text = _text(fleet_criteria.render_fleet_criteria("TESTCO"))
    assert "How states are assigned" in text and "Overall unit state" in text
    assert "fleet_criteria." not in text  # no key rendered raw


def test_the_page_has_a_slot_for_the_panel_and_a_callback_fills_it():
    from dashboard.tabs.tab_overview_general import create_layout

    assert any(getattr(n, "id", None) == "overview-criteria" for n in _walk(create_layout()))
    source = (ROOT / "dashboard" / "callbacks" / "overview_general_callbacks.py").read_text(encoding="utf-8")
    assert 'Output("overview-criteria", "children")' in source and "render_fleet_criteria" in source


def _alert_frame(unit, alerts, components=2):
    now = datetime.now()
    return pd.DataFrame({
        "UnitId": [unit] * alerts,
        "componente": [f"C{i % components}" for i in range(alerts)],
        "Timestamp": [now - timedelta(days=1)] * alerts,
    })


def test_the_alertas_limits_on_the_page_are_the_ones_that_classify():
    limit = rules.ALERTS_ALERTA_MAX_SCORE
    two_components = 1 + 2 * rules.ALERTS_COMPONENT_WEIGHT  # score = alerts x this
    n_ok = int(limit // two_components)
    ok = fs.calculate_alert_criticality_score(_alert_frame("A", n_ok))
    over = fs.calculate_alert_criticality_score(_alert_frame("B", n_ok + 1))
    assert ok.iloc[0]["criticality_score"] <= limit and ok.iloc[0]["status"] == "Alerta"
    assert over.iloc[0]["criticality_score"] > limit and over.iloc[0]["status"] == "Crítico"  # Crítico == Anormal


def test_no_alert_inside_the_window_means_no_score_and_so_normal():
    old = _alert_frame("A", 3)
    old["Timestamp"] = datetime.now() - timedelta(days=rules.ALERTS_WINDOW_DAYS + 1)
    assert fs.calculate_alert_criticality_score(old).empty


def _published_oil_machines():
    frames = []
    for path in sorted((ROOT / "data" / "oil" / "golden").glob("*/machine_status.parquet")):
        frames.append(pd.read_parquet(path).assign(_client=path.parent.name))
    if not frames:
        pytest.skip("no published oil machine status in this checkout")
    return pd.concat(frames, ignore_index=True)


def test_the_tribologia_rule_on_the_page_reproduces_every_published_machine_status():
    """The page says: worst component, Anormal once the weighted score reaches the limit. The pipeline
    publishes the status; this checks the sentence against every machine of the local mirror."""
    rank = {"Normal": 1, "Alerta": 2, "Anormal": 3}
    wrong = []
    for machine in _published_oil_machines().to_dict("records"):
        components = [dict(c) for c in (machine["component_details"] if machine["component_details"] is not None else [])]
        score = sum(rules.OIL_COMPONENT_POINTS[c["status"]] * float(c["weight"]) for c in components)
        worst = max((rank[c["status"]] for c in components), default=1)
        expected = "Anormal" if worst == 3 or score >= rules.OIL_SCORE_ANORMAL_FROM else ("Alerta" if worst == 2 else "Normal")
        if expected != machine["overall_status"] or abs(score - float(machine["machine_score"])) > 0.51:
            wrong.append((machine["_client"], machine["unit_id"], machine["overall_status"], expected, score))
    assert not wrong, wrong[:5]


# ---------------------------------------------------------------------------
# Other consumers of the General tab's unit names
# ---------------------------------------------------------------------------

def test_the_failure_report_finds_a_hyphenated_unit_in_sources_that_use_underscores(monkeypatch):
    """The report form lists the General tab's names (`T-10`) and looks them up in the Predictivo, oil and
    maintenance tables, which spell them `T_10` / `T_10`: the lookups go through `report_health.unit_key`."""
    from src.informe_falla.service import resolver_unidad

    table = pd.DataFrame({"Unit": ["T_09", "T_10", "T_11"]})
    assert resolver_unidad("T-10", table) == "T_10"
    assert resolver_unidad("T-9", table) == "T_09"
    assert resolver_unidad("T-99", table) is None


def test_the_failure_report_unit_list_comes_from_the_golden_file(monkeypatch):
    from dashboard.callbacks import informe_falla_callbacks as callbacks

    _patch_all_sources(
        monkeypatch, enabled={"monitoring-oil": True},
        oil={"T_10": "Normal", "T_9": "Alerta"}, freshness={("oil", "T_10"): ("Ok", "1 día"), ("oil", "T_9"): ("Ok", "1 día")},
    )
    monkeypatch.setattr(callbacks, "is_service_enabled", lambda client, sid: True)
    monkeypatch.setattr(callbacks, "is_service_dummy", lambda client, sid: False)
    units, notice = callbacks.load_units("TESTCO", ["TESTCO"])
    assert notice is None and units == ["T-9", "T-10"]
