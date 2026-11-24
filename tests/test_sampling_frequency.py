"""Panel de Frecuencia rules (src/data/sampling_frequency.py): intervals, status, "Sin muestra",
ordering and the configuration file."""

from datetime import date

import pandas as pd
import pytest

from src.data import sampling_frequency as sf

TODAY = date(2026, 11, 23)


def _config(**overrides):
    raw = {
        "groups": {"A": {"days": 15}, "B": {"days": 30}, "C": {"days": 60}},
        "thresholds": {"proxima_pct": 80, "vencida_pct": 100},
        "mapping": {
            "camion": {"motor": "A", "transmision": "B", "mando final": "C"},
        },
    }
    raw.update(overrides)
    return sf.parse_config(raw)


def _sample(unit, component, sample_date, *, days_prev=None, machine="camion", normalized=None, site="Mina",
            report_date=None):
    return {
        "unitId": unit, "machineName": machine, "componentName": component,
        "componentNameNormalized": normalized or component, "site": site,
        "sampleDate": pd.Timestamp(sample_date), "daysSincePrevious": days_prev,
        "reportDate": pd.Timestamp(report_date or sample_date),
    }


def _days_ago(n):
    return pd.Timestamp(TODAY) - pd.Timedelta(days=n)


def _rows(samples, config=None, today=TODAY):
    frame = pd.DataFrame(samples)
    frame["daysSincePrevious"] = frame["daysSincePrevious"].astype("Int64")
    return sf.build_frequency_rows(frame, config or _config(), today)


def _one(rows, unit, component):
    found = rows[(rows["unit_id"] == unit) & (rows["component"] == component)]
    assert len(found) == 1, found
    return found.iloc[0]


# ---- the acceptance examples ---------------------------------------------------------------

def test_36_days_in_a_15_day_group_is_240_percent_and_overdue():
    rows = _rows([_sample("T1", "motor", _days_ago(36))])
    row = _one(rows, "T1", "motor")
    assert row["days_since"] == 36
    assert row["interval_pct"] == 240
    assert row["status"] == sf.SOLICITAR
    assert row["days_to_due"] == -21


def test_51_days_in_a_60_day_group_is_85_percent_and_due_soon():
    rows = _rows([_sample("T1", "mando final", _days_ago(51))])
    row = _one(rows, "T1", "mando final")
    assert row["interval_pct"] == 85
    assert row["status"] == sf.PROXIMA
    assert row["days_to_due"] == 9
    assert row["due_date"] == pd.Timestamp(TODAY) + pd.Timedelta(days=9)


@pytest.mark.parametrize("days, status", [
    (11, sf.AL_DIA),        # 73.3 %
    (12, sf.PROXIMA),       # 80 % exactly is already "Próxima a vencer"
    (14, sf.PROXIMA),       # 93.3 %
    (15, sf.SOLICITAR),     # 100 % exactly is "Solicitar muestra" ...
    (16, sf.SOLICITAR),
])
def test_thresholds_are_80_and_100_percent(days, status):
    rows = _rows([_sample("T1", "motor", _days_ago(days))])
    assert _one(rows, "T1", "motor")["status"] == status


def test_the_limit_day_reads_vence_hoy_but_is_already_due():
    from dashboard.components.oil_frequency import vencimiento_text

    row = _one(_rows([_sample("T1", "motor", _days_ago(15))]), "T1", "motor")
    assert row["days_to_due"] == 0
    assert vencimiento_text(0) == "Vence hoy"
    assert vencimiento_text(9) == "Vence en 9 d"
    assert vencimiento_text(-21) == "Vencida hace 21 d"


def test_classification_uses_the_unrounded_percentage():
    # 79.9 % must not be rounded up into the 80 % bucket
    config = _config(groups={"A": {"days": 1000}, "B": {"days": 30}, "C": {"days": 60}})
    assert sf.classify_interval(799 * 100 / 1000, config) == sf.AL_DIA
    assert sf.classify_interval(800 * 100 / 1000, config) == sf.PROXIMA


# ---- row data --------------------------------------------------------------------------------

def test_a_row_per_unit_and_component_name_with_last_sample_and_historical_average():
    rows = _rows([
        _sample("T1", "motor", _days_ago(40), days_prev=None),
        _sample("T1", "motor", _days_ago(20), days_prev=20),
        _sample("T1", "motor", _days_ago(5), days_prev=15),
        # left and right share the normalized name "mando final": two rows, one mapping
        _sample("T1", "mando final izquierdo", _days_ago(30), normalized="mando final"),
        _sample("T1", "mando final derecho", _days_ago(10), normalized="mando final"),
    ])
    motor = _one(rows, "T1", "motor")
    assert motor["last_sample"] == _days_ago(5)
    assert motor["avg_hist"] == 17.5          # nulls ignored
    assert set(rows[rows["component_normalized"] == "mando final"]["component"]) == {
        "mando final izquierdo", "mando final derecho"}
    assert len(rows) == 3


def test_days_are_calendar_days_whatever_the_time_of_day():
    stamp = pd.Timestamp(_days_ago(3)) + pd.Timedelta(hours=23, minutes=59)
    row = _one(_rows([_sample("T1", "motor", stamp)]), "T1", "motor")
    assert row["days_since"] == 3


def test_components_without_a_mapping_are_not_shown():
    rows = _rows([_sample("T1", "motor", _days_ago(1)), _sample("T1", "cubo", _days_ago(1))])
    assert list(rows["component"]) == ["motor"]


def test_a_sample_dated_in_the_future_counts_as_taken_today():
    row = _one(_rows([_sample("T1", "motor", pd.Timestamp(TODAY) + pd.Timedelta(days=2))]), "T1", "motor")
    assert row["days_since"] == 0 and row["status"] == sf.AL_DIA


# ---- Sin muestra ------------------------------------------------------------------------------

def test_a_mapped_component_a_unit_was_never_sampled_for_is_sin_muestra():
    rows = _rows([
        _sample("T1", "motor", _days_ago(3)), _sample("T1", "transmision", _days_ago(3)),
        _sample("T2", "motor", _days_ago(3)),                       # T2 has no transmision samples
    ])
    missing = _one(rows, "T2", "transmision")
    assert missing["status"] == sf.SIN_MUESTRA
    assert pd.isna(missing["last_sample"]) and pd.isna(missing["days_since"])
    assert pd.isna(missing["interval_pct"]) and pd.isna(missing["due_date"]) and pd.isna(missing["avg_hist"])
    assert missing["group"] == "B"


def test_sin_muestra_does_not_flag_a_component_the_clients_fleet_never_samples():
    # camion/motor is mapped, but this client spells it "motor diesel": no unit has "motor", so no
    # unit is reported as missing it.
    rows = _rows([_sample("T1", "motor diesel", _days_ago(3)), _sample("T2", "motor diesel", _days_ago(3))])
    assert rows.empty


def test_sin_muestra_only_for_units_of_a_machine_type_that_maps_the_component():
    rows = _rows([
        _sample("T1", "motor", _days_ago(3)),
        _sample("P1", "cubo", _days_ago(3), machine="pala"),        # pala has no mapping
    ])
    assert set(rows["unit_id"]) == {"T1"}


def test_machine_and_component_names_match_ignoring_case_and_accents():
    config = _config(mapping={"Camión": {"Transmisión": "B"}})
    rows = _rows([_sample("T1", "transmision", _days_ago(3))], config)
    assert len(rows) == 1


# ---- order, filters, summaries -----------------------------------------------------------------

def _mixed():
    return _rows([
        _sample("T1", "motor", _days_ago(36)),           # 240 % solicitar
        _sample("T2", "motor", _days_ago(20)),           # 133 % solicitar
        _sample("T3", "motor", _days_ago(13)),           # 86 % proxima
        _sample("T4", "motor", _days_ago(2)),            # 13 % al dia
        _sample("T1", "transmision", _days_ago(40)),     # 133 % solicitar (T1 / transmision)
        _sample("T5", "transmision", _days_ago(1)),      # T5 has transmision ...
    ] + [_sample("T6", "transmision", _days_ago(1))])    # ... and so does T6; T6 lacks motor


def test_default_order_is_urgency_then_most_consumed():
    ordered = sf.sort_rows(_mixed())
    statuses = list(ordered["status"])
    assert statuses == sorted(statuses, key=sf.urgency_rank)
    overdue = ordered[ordered["status"] == sf.SOLICITAR]["interval_pct"].tolist()
    assert overdue == sorted(overdue, reverse=True)
    # Sin muestra comes right after the overdue rows and before "Próxima a vencer"
    order = list(dict.fromkeys(statuses))
    assert order == [sf.SOLICITAR, sf.SIN_MUESTRA, sf.PROXIMA, sf.AL_DIA]


def test_column_sort_puts_rows_without_a_value_last_in_either_direction():
    rows = _mixed()
    for ascending in (True, False):
        flags = list(sf.sort_rows(rows, "interval_pct", ascending)["interval_pct"].isna())
        assert flags == sorted(flags) and flags[-1]          # values first, "Sin muestra" rows last
    asc = sf.sort_rows(rows, "interval_pct", True)["interval_pct"].dropna().tolist()
    assert asc == sorted(asc)
    desc = sf.sort_rows(rows, "interval_pct", False)["interval_pct"].dropna().tolist()
    assert desc == sorted(desc, reverse=True)


def test_every_displayed_column_can_be_sorted():
    rows = _mixed()
    for column in sf.SORT_COLUMNS:
        assert len(sf.sort_rows(rows, column, True)) == len(rows)


def test_filters_and_counts():
    rows = _mixed()
    assert set(sf.filter_rows(rows, status=sf.SOLICITAR)["status"]) == {sf.SOLICITAR}
    assert set(sf.filter_rows(rows, group="B")["group"]) == {"B"}
    assert set(sf.filter_rows(rows, component="motor")["component"]) == {"motor"}
    assert sf.filter_rows(rows, site="Otra").empty
    assert sf.filter_rows(rows, fleet="pala").empty
    assert sf.status_counts(rows) == {sf.SOLICITAR: 3, sf.SIN_MUESTRA: 5, sf.PROXIMA: 1, sf.AL_DIA: 3}


def test_group_summary_is_over_the_rows_it_is_given():
    rows = _mixed()
    summaries = {s.group.key: s for s in sf.group_summaries(rows, _config())}
    assert summaries["A"].total == len(rows[rows["group"] == "A"])
    assert summaries["A"].overdue == 2
    assert summaries["A"].components == ["motor"]
    only_overdue = sf.group_summaries(sf.filter_rows(rows, status=sf.SOLICITAR), _config())
    assert [s.total for s in only_overdue] == [2, 1, 0]
    assert only_overdue[2].avg_between_samples is None
    averages = sf.group_summaries(_rows([
        _sample("T1", "motor", _days_ago(5), days_prev=10), _sample("T2", "motor", _days_ago(5), days_prev=20)]),
        _config())
    assert averages[0].avg_between_samples == 15


def test_data_as_of_is_the_latest_report_date():
    frame = pd.DataFrame([_sample("T1", "motor", "2026-01-01", report_date="2026-01-05"),
                          _sample("T2", "motor", "2026-03-01", report_date="2026-03-08 14:30")])
    assert sf.data_as_of(frame) == pd.Timestamp("2026-03-08")
    assert sf.data_as_of(frame.iloc[0:0]) is None


# ---- configuration -------------------------------------------------------------------------------

def test_changing_the_file_changes_the_result_without_a_restart(tmp_path):
    path = tmp_path / "freq.yaml"
    path.write_text("groups:\n  A: {days: 15}\nmapping:\n  camion:\n    motor: A\n", encoding="utf-8")
    first = sf.load_config(path)
    assert first.groups["A"].days == 15
    sample = [_sample("T1", "motor", _days_ago(20))]
    assert _one(_rows(sample, first), "T1", "motor")["status"] == sf.SOLICITAR

    path.write_text("groups:\n  A: {days: 45}\nmapping:\n  camion:\n    motor: A\n", encoding="utf-8")
    import os
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))   # coarse mtime clocks
    second = sf.load_config(path)
    assert second.groups["A"].days == 45
    assert _one(_rows(sample, second), "T1", "motor")["status"] == sf.AL_DIA


@pytest.mark.parametrize("raw", [
    None,
    {"groups": {}, "mapping": {}},
    {"groups": {"A": {"days": 0}}, "mapping": {}},
    {"groups": {"A": {"days": "x"}}, "mapping": {}},
    {"groups": {"A": {"days": 15}}, "thresholds": {"proxima_pct": 120, "vencida_pct": 100}, "mapping": {}},
    {"groups": {"A": {"days": 15}}, "mapping": {"camion": {"motor": "Z"}}},
])
def test_a_malformed_configuration_is_reported(raw):
    with pytest.raises(sf.FrequencyConfigError):
        sf.parse_config(raw)


def test_the_shipped_configuration_is_valid():
    config = sf.load_config()
    assert [g.days for g in config.ordered_groups()] == [15, 30, 60]
    assert (config.proxima_pct, config.vencida_pct) == (80, 100)
    assert config.mapping
