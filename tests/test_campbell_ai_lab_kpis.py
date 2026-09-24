"""Acceptance cases AC17-AC19: laboratory KPIs, and parity with Monitoring > Oil > Laboratorio.

The point of C09 is that the chat and that tab report the same numbers, so the parity case
drives both paths over one fixture and compares them, instead of asserting each side against
a hand-written constant that could drift apart.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.campbell_ai.data import DashboardDataRepository
from src.data.lab_kpis import (
    DEFAULT_PERIOD_MONTHS,
    compute_lab_kpis,
    default_lab_period,
    has_positive_lab_time,
    normalize_lab_frame,
)


def _row(
    unit: str,
    sample: str,
    lab: str | None,
    report: str | None,
    *,
    unit_id: str = "T_9",
) -> dict:
    return {
        "unitId": unit_id,
        "sampleNumber": unit,
        "componentName": "motor",
        "componentNameNormalized": "motor",
        "report_status": "Normal",
        "sampleDate": sample,
        "labDate": lab,
        "reportDate": report,
    }


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _repository(tmp_path, rows: list[dict]) -> DashboardDataRepository:
    oil = tmp_path / "oil" / "golden" / "enex"
    oil.mkdir(parents=True)
    _frame(rows).to_parquet(oil / "classified.parquet", index=False)
    return DashboardDataRepository(tmp_path)


# ---------------------------------------------------------------------- AC17


def test_ac17_the_chat_and_the_dashboard_report_the_same_numbers(tmp_path):
    """Same source, same range: total, denominators and averages must coincide."""
    import dashboard.callbacks.lab_compliance_callbacks as tab

    rows = [
        _row("S-1", "2026-06-01", "2026-06-03", "2026-06-05"),   # transit 2, lab 2
        _row("S-2", "2026-06-10", "2026-06-11", "2026-06-15"),   # transit 1, lab 4
        _row("S-3", "2026-06-20", "2026-06-24", "2026-06-27"),   # transit 4, lab 3
    ]
    repository = _repository(tmp_path, rows)
    monkey_frame = _frame(rows)

    chat = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    # Drive the dashboard callback over the same fixture.
    original = tab.load_oil_classified
    tab.load_oil_classified = lambda client: monkey_frame.copy()
    try:
        cards = tab.update_kpis("2026-06-01", "2026-06-30", "enex", "lab-compliance")
    finally:
        tab.load_oil_classified = original

    transit_title, transit_value, lab_title, lab_value, total = cards
    assert total == str(chat["total_samples"]) == "3"
    # avg transit = (2+1+4)/3 = 2.333 -> 2.3 ; avg lab = (2+4+3)/3 = 3.0
    assert transit_value == f"{chat['metrics']['transit_time']['average']:.1f}" == "2.3"
    assert lab_value == f"{chat['metrics']['lab_time']['average']:.1f}" == "3.0"
    assert "Tránsito" in transit_title and "Laboratorio" in lab_title
    assert chat["metrics"]["transit_time"]["valid_samples"] == 3
    assert chat["dashboard_reference"] == "Monitoreo > Aceite > Laboratorio"


def test_ac17_the_default_period_is_six_months_and_is_declared(tmp_path):
    rows = [
        _row("S-old", "2024-01-05", "2024-01-06", "2024-01-08"),
        _row("S-mid", "2026-05-01", "2026-05-02", "2026-05-04"),
        _row("S-new", "2026-08-01", "2026-08-02", "2026-08-04"),
    ]
    repository = _repository(tmp_path, rows)

    payload = json.loads(repository.query_lab_kpis("enex"))

    assert payload["period_default_months"] == DEFAULT_PERIOD_MONTHS == 6
    # Six months back from the newest report present, not from today.
    assert payload["period"] == {
        "field": "reportDate",
        "start": "2026-02-04",
        "end": "2026-08-04",
        "source": "default",
        "final_day_included": True,
    }
    # The 2024 sample is outside it; the other two are in.
    assert payload["total_samples"] == 2


def test_the_default_period_is_floored_at_the_oldest_report():
    """A client with three weeks of history gets three weeks, not a six-month claim."""
    frame = normalize_lab_frame(
        _frame(
            [
                _row("S-1", "2026-08-01", "2026-08-02", "2026-08-03"),
                _row("S-2", "2026-08-18", "2026-08-19", "2026-08-20"),
            ]
        )
    )

    period = default_lab_period(frame)

    assert period.start == pd.Timestamp("2026-08-03")
    assert period.end == pd.Timestamp("2026-08-20")


# ---------------------------------------------------------------------- AC18


def test_ac18_a_missing_lab_date_is_unavailable_not_zero(tmp_path):
    """The failure this guards: an absent date silently becoming a zero-day duration."""
    repository = _repository(
        tmp_path,
        [
            _row("S-1", "2026-06-01", None, "2026-06-05"),   # no reception recorded
            _row("S-2", "2026-06-10", "2026-06-12", "2026-06-15"),
        ],
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    transit = payload["metrics"]["transit_time"]
    assert payload["total_samples"] == 2
    # The average is over the one sample that has both dates, not over two with a zero.
    assert transit["valid_samples"] == 1
    assert transit["missing_samples"] == 1
    assert transit["average"] == 2.0
    assert payload["samples_without_lab_date"] == 1
    # Diagnostic time needs only the two ends, so it still covers both samples.
    assert payload["metrics"]["diagnostic_time"]["valid_samples"] == 2


def test_ac18_a_source_without_any_lab_date_falls_back_to_diagnostic_time(tmp_path):
    repository = _repository(
        tmp_path,
        [
            _row("S-1", "2026-06-01", None, "2026-06-05"),
            _row("S-2", "2026-06-10", None, "2026-06-13"),
        ],
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    assert payload["reporting_mode"] == "solo_diagnostico"
    assert "no lo presentes como cero" in payload["reporting_mode_detail"]
    assert payload["metrics"]["transit_time"]["average"] is None
    assert "no disponible, no cero" in payload["metrics"]["transit_time"]["reason"]
    # avg diagnostic = (4 + 3) / 2
    assert payload["metrics"]["diagnostic_time"]["average"] == 3.5


def test_ac18_a_lab_time_of_all_zeros_is_not_read_as_an_instant_lab(tmp_path):
    """labDate stamped equal to reportDate means reception was not recorded separately."""
    rows = [
        _row("S-1", "2026-06-01", "2026-06-05", "2026-06-05"),
        _row("S-2", "2026-06-10", "2026-06-14", "2026-06-14"),
    ]
    repository = _repository(tmp_path, rows)

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    assert has_positive_lab_time(normalize_lab_frame(_frame(rows))) is False
    assert payload["reporting_mode"] == "solo_diagnostico"
    assert payload["metrics"]["lab_time"]["zero_samples"] == 2


def test_ac18_negative_durations_are_counted_not_clipped(tmp_path):
    """An inverted pair of dates is a data problem to surface, not a zero."""
    repository = _repository(
        tmp_path,
        [
            _row("S-1", "2026-06-10", "2026-06-08", "2026-06-15"),   # transit -2
            _row("S-2", "2026-06-01", "2026-06-03", "2026-06-05"),   # transit 2
        ],
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    transit = payload["metrics"]["transit_time"]
    assert transit["negative_samples"] == 1
    assert transit["min"] == -2
    assert transit["average"] == 0.0   # (-2 + 2) / 2, reported as measured


def test_ac18_two_samples_of_one_day_are_two_rows(tmp_path):
    """One row is one sample here: the KPI counts reports, not components."""
    repository = _repository(
        tmp_path,
        [
            _row("S-1", "2026-06-01", "2026-06-02", "2026-06-04"),
            _row("S-2", "2026-06-01", "2026-06-03", "2026-06-04"),
        ],
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    assert payload["total_samples"] == 2
    assert payload["metrics"]["transit_time"]["valid_samples"] == 2


# ---------------------------------------------------------------------- AC19


def test_ac19_an_empty_period_is_missing_data_not_full_compliance(tmp_path):
    repository = _repository(
        tmp_path, [_row("S-1", "2026-06-01", "2026-06-03", "2026-06-05")]
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-01-01", end_date="2026-01-31")
    )

    assert payload["metrics_available"] is False
    assert payload["total_samples"] == 0
    assert "no cumplimiento" in payload["detail"]
    assert "metrics" not in payload
    # The period it looked at is still reported, so the answer can name it.
    assert payload["period"]["start"] == "2026-01-01"


def test_ac19_a_report_published_during_the_final_day_is_included(tmp_path):
    """`<= Timestamp(end_date)` dropped anything stamped after midnight on the last day."""
    repository = _repository(
        tmp_path,
        [
            _row("S-1", "2026-06-01", "2026-06-02", "2026-06-30T14:00:00"),
            _row("S-2", "2026-06-05", "2026-06-06", "2026-06-29T23:30:00"),
        ],
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    assert payload["total_samples"] == 2
    assert payload["period"]["final_day_included"] is True


def test_ac19_rows_without_a_report_date_are_excluded_and_counted(tmp_path):
    repository = _repository(
        tmp_path,
        [
            _row("S-1", "2026-06-01", "2026-06-03", "2026-06-05"),
            _row("S-2", "2026-06-10", "2026-06-12", None),
        ],
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    # Excluded from the period (no publication date) but reported, not silently dropped.
    assert payload["total_samples"] == 1
    assert payload["samples_without_report_date"] == 1


def test_ac19_a_source_with_no_dates_at_all_reports_no_metrics(tmp_path):
    repository = _repository(tmp_path, [_row("S-1", None, None, None)])

    payload = json.loads(repository.query_lab_kpis("enex"))

    assert payload["metrics_available"] is False
    assert payload["total_samples"] == 0


# ------------------------------------------------------------------ contract


def test_the_capability_is_not_announced_without_the_dates_it_needs(tmp_path, monkeypatch):
    """"Oil exists" is not enough: the KPI needs sampleDate and reportDate.

    Capability resolution trusts the declared schema for a declared dataset, so the
    declaration is stubbed out to exercise the path that reads the real columns.
    """
    import src.campbell_ai.data as data_module

    monkeypatch.setattr(data_module, "declared_columns", lambda *args, **kwargs: None)
    oil = tmp_path / "oil" / "golden" / "enex"
    oil.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "unitId": "T_9",
                "componentName": "motor",
                "componentNameNormalized": "motor",
                "report_status": "Normal",
                "sampleDate": "2026-06-01",
                # No reportDate at all: the period field does not exist.
            }
        ]
    ).to_parquet(oil / "classified.parquet", index=False)
    repository = DashboardDataRepository(tmp_path)

    capabilities = repository.client_capabilities("enex")
    available = {item["key"] for item in capabilities["available"]}
    reasons = {item["key"]: item["reason"] for item in capabilities["unavailable"]}

    assert "oil_lab_kpis" not in available
    assert "reportDate" in reasons["oil_lab_kpis"]
    # Component condition still works: one analysis is missing, not the client.
    assert "oil_components" in available


def test_a_threshold_is_reference_only_and_carries_no_compliance_percentage(tmp_path):
    repository = _repository(
        tmp_path, [_row("S-1", "2026-06-01", "2026-06-03", "2026-06-05")]
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    assert "no es un sla" in payload["compliance_threshold_note"].lower()
    for forbidden in ("compliance_pct", "compliance_rate", "percentile", "sla"):
        assert forbidden not in payload


def test_a_unit_filter_narrows_the_same_population(tmp_path):
    repository = _repository(
        tmp_path,
        [
            _row("S-1", "2026-06-01", "2026-06-03", "2026-06-05", unit_id="T_9"),
            _row("S-2", "2026-06-02", "2026-06-08", "2026-06-10", unit_id="T_15"),
        ],
    )

    scoped = json.loads(
        repository.query_lab_kpis(
            "enex", start_date="2026-06-01", end_date="2026-06-30", unit_id="T_15"
        )
    )

    assert scoped["unit_id"] == "T_15"
    assert scoped["total_samples"] == 1
    assert scoped["metrics"]["transit_time"]["average"] == 6.0
    # A per-unit ranking makes no sense once a single unit was requested.
    assert "slowest_units" not in scoped


@pytest.mark.parametrize("metric", ["transit_time", "lab_time", "diagnostic_time"])
def test_every_average_declares_its_unit_and_denominator(tmp_path, metric):
    repository = _repository(
        tmp_path, [_row("S-1", "2026-06-01", "2026-06-03", "2026-06-05")]
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    entry = payload["metrics"][metric]
    assert entry["unit"] == "dias"
    assert "valid_samples" in entry
    assert payload["duration_unit"] == "dias"


def test_the_prompt_documents_the_units_exception_without_widening_it():
    from src.campbell_ai.prompts import load_prompt

    prompt = load_prompt("data_analyst_query.md")

    assert "query_lab_kpis" in prompt
    assert "Única excepción" in prompt
    assert "no habilita ninguna otra unidad" in prompt
    # The general prohibition still stands.
    assert "**No escribas unidades de medida.**" in prompt


def test_compute_lab_kpis_tolerates_an_empty_frame():
    payload = compute_lab_kpis(pd.DataFrame())

    assert payload["metrics_available"] is False
    assert payload["total_samples"] == 0


# ------------------------------------ H06: the population can be reconciled


def test_h06_a_sample_without_an_extraction_date_is_counted_as_excluded(tmp_path):
    """It was dropped silently, leaving a total that could not be checked against the source."""
    repository = _repository(
        tmp_path,
        [
            _row("S-1", "2026-06-01", "2026-06-03", "2026-06-05"),
            _row("S-2", "2026-06-10", "2026-06-12", "2026-06-15"),
            _row("S-3", None, "2026-06-20", "2026-06-22"),
        ],
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    assert payload["source_rows"] == 3
    assert payload["excluded_without_sample_date"] == 1
    assert payload["dated_samples"] == 2
    assert payload["total_samples"] == 2
    # The identity that makes the numbers auditable.
    assert (
        payload["source_rows"]
        == payload["excluded_without_sample_date"] + payload["dated_samples"]
    )
    assert "no como demora cero" in payload["excluded_without_sample_date_detail"]


def test_h06_an_exclusion_is_distinct_from_a_missing_report_date(tmp_path):
    """Two different reasons a row is not in the total, counted separately."""
    repository = _repository(
        tmp_path,
        [
            _row("S-1", "2026-06-01", "2026-06-03", "2026-06-05"),
            _row("S-2", None, "2026-06-12", "2026-06-15"),      # no extraction date
            _row("S-3", "2026-06-10", "2026-06-12", None),      # never published
        ],
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    assert payload["source_rows"] == 3
    assert payload["excluded_without_sample_date"] == 1
    assert payload["samples_without_report_date"] == 1
    assert payload["dated_samples"] == 2
    assert payload["total_samples"] == 1


def test_h06_the_counts_are_present_even_when_the_period_is_empty(tmp_path):
    repository = _repository(
        tmp_path,
        [
            _row("S-1", "2026-06-01", "2026-06-03", "2026-06-05"),
            _row("S-2", None, "2026-06-12", "2026-06-15"),
        ],
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-01-01", end_date="2026-01-31")
    )

    assert payload["metrics_available"] is False
    assert payload["total_samples"] == 0
    assert payload["source_rows"] == 2
    assert payload["excluded_without_sample_date"] == 1


def test_h06_nothing_is_reported_as_excluded_when_nothing_was(tmp_path):
    repository = _repository(
        tmp_path, [_row("S-1", "2026-06-01", "2026-06-03", "2026-06-05")]
    )

    payload = json.loads(
        repository.query_lab_kpis("enex", start_date="2026-06-01", end_date="2026-06-30")
    )

    assert payload["excluded_without_sample_date"] == 0
    assert "excluded_without_sample_date_detail" not in payload
