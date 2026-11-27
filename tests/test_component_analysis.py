"""Análisis por Componente (Monitor de Aceite): the rules in src/data/component_analysis.py.

Synthetic frames, same shape as `classified.parquet`; no Dash involved.
"""

import json
import os
import time
from datetime import date

import pandas as pd
import pytest

from src.data import component_analysis as ca

TODAY = date(2026, 11, 26)


def breach(essay, threshold="Marginal", group="Desgaste", use=1, direction="upper"):
    return {"essay": essay, "value": 1.0, "threshold": threshold, "limit": 1.0, "points": 1, "group": group,
            "use_for_classification": use, "direction": direction}


def sample(unit, days_ago, status="Normal", component="diferencial trasero", normalized="diferencial", anomaly=None,
           breaches=(), hours=1000.0, oil=500.0, fleet="camion", previous_days_ago=None, report_offset=1):
    when = pd.Timestamp(TODAY) - pd.Timedelta(days=days_ago)
    return {
        "unitId": unit, "machineName": fleet, "componentName": component, "componentNameNormalized": normalized,
        "sampleDate": when, "reportDate": when + pd.Timedelta(days=report_offset),
        "previousSampleDate": (pd.Timestamp(TODAY) - pd.Timedelta(days=previous_days_ago)
                               if previous_days_ago is not None else pd.NaT),
        "report_status": status, "anomalyType": anomaly if anomaly is not None else ("Normal" if status == "Normal" else None),
        "componentHours": hours, "oilMeter": oil, "breached_essays": json.dumps(list(breaches)),
    }


@pytest.fixture
def config():
    return ca.parse_config({
        "stale_days": 90, "age_edges": [30, 60],
        "components": {"diferencial": {"criticality": "importante", "names": ["diferencial"]},
                       "motor": {"criticality": "critico", "names": ["motor", "Motor Diesel"]}},
    })


def rows_for(samples, config, key="diferencial", fleet="camion"):
    return ca.build_component_rows(pd.DataFrame(samples), config.spec(key), fleet)


def by_pair(rows):
    return {(r["unit_id"], r["component"]): r for r in rows}


# ---- Reading the frame ------------------------------------------------------------------------------------

def test_one_row_per_unit_and_component_from_the_latest_sample(config):
    rows = rows_for([
        sample("U1", 100, "Normal", previous_days_ago=None),
        sample("U1", 40, "Alerta", anomaly="Desgaste de Componentes", previous_days_ago=100),
        sample("U1", 10, "Anormal", anomaly="Contaminación Lubricante", previous_days_ago=40),
        sample("U2", 5, "Normal"),
    ], config)
    pairs = by_pair(rows)
    assert len(rows) == 2
    latest = pairs[("U1", "diferencial trasero")]
    assert latest["estado"] == "Anormal" and latest["anomaly"] == "Contaminación Lubricante"
    assert latest["sample_date"] == "2026-11-16"
    assert latest["prev_estado"] == "Alerta"                        # the sample dated previousSampleDate


def test_a_unit_with_two_differentials_gives_two_rows_that_both_count(config):
    rows = rows_for([
        sample("U1", 5, "Alerta", component="diferencial delantero", anomaly="Desgaste de Componentes"),
        sample("U1", 6, "Normal", component="diferencial trasero"),
        sample("U2", 7, "Normal", component="diferencial trasero"),
    ], config)
    assert sorted((r["unit_id"], r["component"]) for r in rows) == [
        ("U1", "diferencial delantero"), ("U1", "diferencial trasero"), ("U2", "diferencial trasero")]
    assert ca.estado_counts(rows) == {"Anormal": 0, "Alerta": 1, "Normal": 2}


def test_the_estado_is_the_samples_own_report_status_never_recomputed_from_essays(config):
    anormal_without_essays = sample("U1", 3, "Anormal", anomaly="Desgaste de Componentes", breaches=[])
    normal_with_essays = sample("U2", 3, "Normal", breaches=[breach("Hierro", "Critico")])
    rows = by_pair(rows_for([anormal_without_essays, normal_with_essays], config))
    assert rows[("U1", "diferencial trasero")]["estado"] == "Anormal"
    assert rows[("U1", "diferencial trasero")]["breaches"] == []
    assert rows[("U2", "diferencial trasero")]["estado"] == "Normal"


def test_options_match_normalized_names_ignoring_case_and_accents_and_only_the_selected_fleet(config):
    frame = [
        sample("U1", 3, component="MOTOR DIESEL", normalized="motor diesel", fleet="camion"),
        sample("U2", 3, component="motor", normalized="Motor", fleet="camion"),
        sample("U3", 3, component="motor", normalized="motor", fleet="pala"),
        sample("U4", 3, component="diferencial trasero", normalized="diferencial", fleet="camion"),
        sample("U5", 3, component="motor de giro", normalized="motor de giro", fleet="camion"),   # not mapped
    ]
    assert sorted(r["unit_id"] for r in rows_for(frame, config, "motor")) == ["U1", "U2"]
    assert sorted(r["unit_id"] for r in rows_for(frame, config, "motor", fleet="pala")) == ["U3"]
    assert ca.build_component_rows(pd.DataFrame(frame), config.spec("motor"), None) == []   # no Flota: nothing


def test_changing_the_mapping_changes_the_rows_without_touching_the_data(config):
    frame = [sample("U1", 3, component="diferencial trasero", normalized="diferencial"),
             sample("U2", 3, component="reductor", normalized="reductor")]
    wider = ca.parse_config({"components": {"diferencial": {"criticality": "importante",
                                                            "names": ["diferencial", "Reductor"]}}})
    assert [r["unit_id"] for r in rows_for(frame, config)] == ["U1"]
    assert sorted(r["unit_id"] for r in rows_for(frame, wider)) == ["U1", "U2"]


def test_samples_of_the_same_day_fall_back_to_the_later_report(config):
    rows = rows_for([sample("U1", 5, "Normal", report_offset=1), sample("U1", 5, "Alerta", report_offset=3,
                                                                       anomaly="Desgaste de Componentes")], config)
    assert rows[0]["estado"] == "Alerta"


def test_previous_state_is_none_without_a_previous_sample_or_when_it_is_not_in_the_data(config):
    rows = by_pair(rows_for([
        sample("U1", 5, "Alerta", anomaly="X"),                                    # previousSampleDate is empty
        sample("U2", 5, "Alerta", anomaly="X", previous_days_ago=50),              # nothing dated that day
    ], config))
    assert rows[("U1", "diferencial trasero")]["prev_estado"] is None
    assert rows[("U2", "diferencial trasero")]["prev_estado"] is None


def test_hours_are_kept_and_missing_hours_are_none(config):
    rows = by_pair(rows_for([sample("U1", 3, hours=None, oil=1234.0), sample("U2", 3, hours=8000.0, oil=float("nan"))], config))
    assert (rows[("U1", "diferencial trasero")]["component_hours"], rows[("U1", "diferencial trasero")]["oil_hours"]) == (None, 1234.0)
    assert (rows[("U2", "diferencial trasero")]["component_hours"], rows[("U2", "diferencial trasero")]["oil_hours"]) == (8000.0, None)


def test_anomaly_type_unclassified_cases(config):
    rows = by_pair(rows_for([
        sample("U1", 3, "Alerta", anomaly=None),                    # no label
        sample("U2", 3, "Alerta", anomaly="Normal"),                # labelled "Normal" on a non-Normal sample (real data does this)
        sample("U3", 3, "Alerta", anomaly="  "),
        sample("U4", 3, "Alerta", anomaly="Desgaste de Componentes"),
        sample("U5", 3, "Normal"),
    ], config))
    anomalies = {unit: rows[(unit, "diferencial trasero")]["anomaly"] for unit in ("U1", "U2", "U3", "U4", "U5")}
    assert anomalies == {"U1": None, "U2": None, "U3": None, "U4": "Desgaste de Componentes", "U5": None}


def test_a_sample_with_an_unknown_status_is_left_out_so_the_counts_add_up(config):
    rows = rows_for([sample("U1", 3, "Normal"), sample("U2", 3, "Sin Datos")], config)
    assert [r["unit_id"] for r in rows] == ["U1"]


# ---- Essays out of limit -----------------------------------------------------------------------------------

def test_levels_critico_is_merged_into_condenatorio_and_lower_limits_count_the_same():
    found = {b["essay"]: b for b in ca.parse_breaches(json.dumps([
        breach("Hierro", "Marginal"), breach("Cobre", "Condenatorio"), breach("Sodio", "Critico"),
        breach("Calcio", "Critico", direction="lower"), breach("Agua", "Raro"),
    ]))}
    assert {k: v["level"] for k, v in found.items()} == {
        "Hierro": "Marginal", "Cobre": "Condenatorio", "Sodio": "Condenatorio", "Calcio": "Condenatorio"}


@pytest.mark.parametrize("raw", [None, float("nan"), "", "[]", "not json", 7, "{}"])
def test_unreadable_or_empty_breached_essays_are_no_breaches(raw):
    assert ca.parse_breaches(raw) == []


def test_breaches_accept_an_already_parsed_list_and_keep_the_worst_level_of_a_repeated_essay():
    parsed = ca.parse_breaches([breach("Hierro", "Marginal"), breach("Hierro", "Critico"), breach("Hierro", "Marginal")])
    assert [(b["essay"], b["level"]) for b in parsed] == [("Hierro", "Condenatorio")]


def test_use_for_classification_flag_and_group_are_kept():
    parsed = {b["essay"]: b for b in ca.parse_breaches([
        breach("Hierro", use=1, group="Desgaste"), breach("Zinc", use=0, group="Aditivo"),
        {"essay": "Agua", "threshold": "Marginal", "group": "Conteo"},        # no flag: counts
    ])}
    assert (parsed["Hierro"]["counts"], parsed["Zinc"]["counts"], parsed["Agua"]["counts"]) == (True, False, True)
    assert parsed["Zinc"]["group"] == "Aditivo"


# ---- Staleness and age buckets -----------------------------------------------------------------------------

def test_stale_means_older_than_the_threshold_so_exactly_90_days_is_still_current(config):
    assert [ca.is_stale(d, config) for d in (0, 89, 90, 91, 400)] == [False, False, False, True, True]
    assert not ca.is_stale(None, config)


def test_days_since_are_calendar_days_computed_from_today_and_never_negative():
    assert ca.days_since("2026-11-16", TODAY) == 10
    assert ca.days_since("2026-11-26", TODAY) == 0
    assert ca.days_since("2026-12-05", TODAY) == 0
    assert ca.days_since(None, TODAY) is None


def test_age_buckets_and_the_stale_count_agree_on_the_90_day_edge(config):
    ages = [0, 30, 31, 60, 61, 90, 91, 500]
    rows = rows_for([sample(f"U{i}", d) for i, d in enumerate(ages)], config)
    buckets = ca.age_buckets(rows, config, TODAY)
    assert [(b["lo"], b["hi"], b["count"]) for b in buckets] == [(0, 30, 2), (31, 60, 2), (61, 90, 2), (91, None, 2)]
    assert sum(b["count"] for b in buckets) == len(rows)
    assert buckets[-1]["count"] == ca.stale_count(rows, config, TODAY) == 2


def test_the_threshold_and_the_buckets_come_from_the_configuration(config):
    tight = ca.parse_config({"stale_days": 20, "age_edges": [7], "components": {
        "diferencial": {"criticality": "importante", "names": ["diferencial"]}}})
    rows = rows_for([sample(f"U{i}", d) for i, d in enumerate([3, 7, 8, 20, 21])], tight)
    assert [(b["lo"], b["hi"], b["count"]) for b in ca.age_buckets(rows, tight, TODAY)] == [
        (0, 7, 2), (8, 20, 2), (21, None, 1)]
    assert ca.stale_count(rows, tight, TODAY) == 1
    assert ca.stale_count(rows, config, TODAY) == 0                 # the standard 90 days: nothing is stale


# ---- Cards -------------------------------------------------------------------------------------------------

def _population(config):
    return rows_for([
        sample("U1", 5, "Anormal", anomaly="Desgaste de Componentes",
               breaches=[breach("Hierro", "Critico"), breach("Cobre", "Marginal"), breach("Zinc", "Marginal", "Aditivo", use=0)]),
        sample("U2", 5, "Anormal", anomaly="Contaminación Lubricante", breaches=[breach("Sodio", "Condenatorio", "Contaminante")]),
        sample("U3", 5, "Alerta", anomaly="Desgaste de Componentes", breaches=[breach("Hierro", "Marginal")]),
        sample("U4", 5, "Alerta", anomaly="Contaminación Lubricante", breaches=[breach("Hierro", "Marginal"), breach("Sodio", "Marginal", "Contaminante")]),
        sample("U5", 5, "Alerta", anomaly=None, breaches=[]),
        sample("U6", 5, "Normal", breaches=[breach("Hierro", "Critico"), breach("Plata", "Marginal")]),
    ], config)


def test_anomaly_card_counts_only_alerta_and_anormal_stacked_by_estado_biggest_first(config):
    result = ca.anomaly_counts(_population(config), unclassified="Sin clasificar")
    assert [(e["type"], e["anormal"], e["alerta"], e["total"]) for e in result] == [
        ("Contaminación Lubricante", 1, 1, 2), ("Desgaste de Componentes", 1, 1, 2), ("Sin clasificar", 0, 1, 1)]
    assert sum(e["total"] for e in result) == 5                    # every Alerta + Anormal component, none of the Normal


def test_anomaly_ties_are_alphabetical():
    rows = [{"estado": "Alerta", "anomaly": name} for name in ("Zeta", "alfa", "Beta")]
    assert [e["type"] for e in ca.anomaly_counts(rows)] == ["alfa", "Beta", "Zeta"]


def test_essay_card_counts_samples_by_level_and_orders_by_n_then_condenatorio_then_name(config):
    result = ca.essay_counts(_population(config))
    assert [(e["essay"], e["n"], e["cond"], e["marg"]) for e in result] == [
        ("Hierro", 3, 1, 2), ("Sodio", 2, 1, 1), ("Cobre", 1, 0, 1)]
    assert {e["essay"]: e["group"] for e in result}["Sodio"] == "Contaminante"
    assert all(e["essay"] not in ("Zinc", "Plata") for e in result)  # Zinc does not classify; Plata is on a Normal sample


def test_the_checkbox_adds_the_essays_that_do_not_affect_the_state(config):
    with_all = {e["essay"]: e for e in ca.essay_counts(_population(config), include_all=True)}
    assert with_all["Zinc"]["n"] == 1 and with_all["Zinc"]["group"] == "Aditivo"
    assert "Zinc" not in {e["essay"] for e in ca.essay_counts(_population(config))}


def test_equal_counts_break_the_tie_by_condenatorio_then_alphabetically():
    rows = [{"estado": "Alerta", "breaches": [
        {"essay": "B", "level": "Marginal", "group": None, "counts": True},
        {"essay": "A", "level": "Marginal", "group": None, "counts": True},
        {"essay": "C", "level": "Condenatorio", "group": None, "counts": True}]}]
    assert [e["essay"] for e in ca.essay_counts(rows)] == ["C", "A", "B"]


# ---- Matrix ------------------------------------------------------------------------------------------------

def test_matrix_default_order_is_anormal_then_alerta_then_normal_then_condenatorio_then_marginal(config):
    ordered = ca.matrix_rows(_population(config), config, today=TODAY)
    estados = [r["estado"] for r in ordered]
    assert estados == ["Anormal", "Anormal", "Alerta", "Alerta", "Alerta", "Normal"]
    # inside Anormal: U1 has 1 condenatorio and 1 marginal that count, U2 has 1 condenatorio -> U1 first on Marginal
    assert [r["unit_id"] for r in ordered[:2]] == ["U1", "U2"]
    # inside Alerta: neither U3 nor U4 nor U5 has a condenatorio; more marginals first
    assert [r["unit_id"] for r in ordered[2:5]] == ["U4", "U3", "U5"]
    assert [(r["n_essays"], r["n_cond"], r["n_marg"]) for r in ordered[:2]] == [(2, 1, 1), (1, 1, 0)]


def test_matrix_counts_follow_the_checkbox_and_a_row_without_essays_says_zero(config):
    rows = _population(config)
    narrow = {r["unit_id"]: r for r in ca.matrix_rows(rows, config, today=TODAY)}
    wide = {r["unit_id"]: r for r in ca.matrix_rows(rows, config, include_all=True, today=TODAY)}
    assert narrow["U1"]["n_essays"] == 2 and wide["U1"]["n_essays"] == 3
    assert narrow["U5"]["n_essays"] == 0 and narrow["U5"]["levels"] == {}


def test_mostrar_only_changes_which_rows_the_matrix_lists(config):
    rows = _population(config)
    assert len(ca.shown_rows(rows, "alerta_anormal")) == 5
    assert len(ca.shown_rows(rows, "anormal")) == 2
    assert len(ca.shown_rows(rows, "todos")) == 6
    assert len(ca.shown_rows(rows, "algo raro")) == 5               # an unknown option behaves as the default
    assert sum(ca.estado_counts(rows).values()) == 6                # the tiles do not move


def test_trend_compares_the_estado_with_the_previous_sample():
    assert ca.trend_of("Alerta", "Normal") == ca.WORSENING
    assert ca.trend_of("Anormal", "Alerta") == ca.WORSENING
    assert ca.trend_of("Normal", "Anormal") == ca.IMPROVING
    assert ca.trend_of("Alerta", "Alerta") == ca.UNCHANGED
    assert ca.trend_of("Alerta", None) is None


def test_a_component_whose_previous_sample_was_normal_and_latest_is_alerta_is_worsening_with_before_normal(config):
    rows = rows_for([sample("U1", 60, "Normal"), sample("U1", 10, "Alerta", anomaly="Desgaste de Componentes",
                                                        previous_days_ago=60)], config)
    row = ca.matrix_rows(rows, config, today=TODAY)[0]
    assert (row["trend"], row["prev_estado"]) == (ca.WORSENING, "Normal")


def test_matrix_rows_carry_days_and_the_stale_flag(config):
    rows = ca.matrix_rows(rows_for([sample("U1", 120, "Alerta", anomaly="X"), sample("U2", 90, "Alerta", anomaly="X")], config),
                          config, today=TODAY)
    assert {r["unit_id"]: (r["days"], r["stale"]) for r in rows} == {"U1": (120, True), "U2": (90, False)}


def test_every_column_can_be_sorted_and_rows_with_nothing_to_sort_on_go_last(config):
    rows = ca.matrix_rows(rows_for([
        sample("B1", 10, "Alerta", anomaly="Zeta", hours=500.0, breaches=[breach("Hierro", "Critico")]),
        sample("A1", 50, "Anormal", anomaly="Alfa", hours=None, oil=9000.0, breaches=[breach("Hierro", "Marginal")]),
        sample("C1", 90, "Alerta", anomaly="Beta", hours=800.0, breaches=[]),
    ], config), config, today=TODAY)
    ids = lambda col, desc=False: [r["unit_id"] for r in ca.sort_matrix(rows, col, desc)]
    assert ids("unit") == ["A1", "B1", "C1"] and ids("unit", True) == ["C1", "B1", "A1"]
    assert ids("estado", True) == ["A1", "B1", "C1"]
    assert ids("anomaly") == ["A1", "C1", "B1"]
    assert ids("essays", True) == ["B1", "A1", "C1"]
    assert ids("last") == ["B1", "A1", "C1"] and ids("last", True) == ["C1", "A1", "B1"]
    assert ids("component_hours", True) == ["C1", "B1", "A1"] and ids("component_hours") == ["B1", "C1", "A1"]   # no hours: last either way
    assert ids("oil_hours", True)[0] == "A1"
    assert ids("essay:Hierro", True) == ["B1", "A1", "C1"] and ids("essay:Hierro") == ["A1", "B1", "C1"]
    assert set(ids("trend")) == {"A1", "B1", "C1"}
    assert ids(None) == ids("no-such-column") == [r["unit_id"] for r in rows]
    for column in ca.SORT_COLUMNS:
        ca.sort_matrix(rows, column, False)


# ---- Configuration -----------------------------------------------------------------------------------------

def test_the_shipped_configuration_has_the_four_options_in_order():
    config = ca.load_config()
    assert list(config.components) == ["motor", "transmision", "convertidor", "diferencial"]
    assert config.default_component() == "motor"
    assert {k: v.criticality for k, v in config.components.items()} == {
        "motor": "critico", "transmision": "critico", "convertidor": "importante", "diferencial": "importante"}
    assert "motor diesel" in config.components["motor"].names
    assert config.stale_days == 90 and config.age_edges == (30, 60)


@pytest.mark.parametrize("raw", [
    None, [], {"components": {}},
    {"components": {"a": {"criticality": "raro", "names": ["a"]}}},
    {"components": {"a": {"criticality": "critico", "names": []}}},
    {"components": {"a": "texto"}},
    {"stale_days": 0, "components": {"a": {"criticality": "critico", "names": ["a"]}}},
    {"stale_days": 90, "age_edges": [60, 30], "components": {"a": {"criticality": "critico", "names": ["a"]}}},
    {"stale_days": 90, "age_edges": [30, 90], "components": {"a": {"criticality": "critico", "names": ["a"]}}},
])
def test_a_malformed_configuration_is_reported(raw):
    with pytest.raises(ca.ComponentAnalysisConfigError):
        ca.parse_config(raw)


def test_the_configuration_is_re_read_when_the_file_changes(tmp_path):
    path = tmp_path / "component_analysis.yaml"
    path.write_text("stale_days: 90\ncomponents:\n  motor: {criticality: critico, names: [motor]}\n", encoding="utf-8")
    assert ca.load_config(path).stale_days == 90
    path.write_text("stale_days: 45\ncomponents:\n  motor: {criticality: critico, names: [motor, motor diesel]}\n", encoding="utf-8")
    stamp = time.time() + 5
    os.utime(path, (stamp, stamp))                                  # a coarse filesystem clock must not hide the edit
    changed = ca.load_config(path)
    assert changed.stale_days == 45 and changed.components["motor"].names == ("motor", "motor diesel")
    with pytest.raises(ca.ComponentAnalysisConfigError):
        ca.load_config(tmp_path / "missing.yaml")


def test_an_unknown_option_falls_back_to_the_default(config):
    assert config.spec("nope").key == "diferencial" and config.spec(None).key == "diferencial"
