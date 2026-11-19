"""Maintenance KPIs in Campbell AI, and parity with Monitoreo > Mantenciones.

The chat must report the numbers on the tab's KPI cards. The synthetic cases pin each formula
to a hand-checkable value; the parity case drives both paths over the real data and compares
them, so neither side can drift without failing here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from src.campbell_ai import maintenance_kpis
from src.campbell_ai.chart_registry import DashboardChartRegistry
from src.campbell_ai.data import (
    ANALYSIS_CAPABILITIES,
    DATASET_MAP,
    DashboardDataRepository,
)
from src.campbell_ai.errors import CampbellDataError

VIEWS = "Maintance_Labeler_Views"


def _write(root: Path, client: str, name: str, rows: list[dict]) -> None:
    folder = root / "mantentions" / "golden" / client / VIEWS
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(folder / f"{name}.parquet", index=False)


def _hours(client: str, unit: str, month: str, hours: float, calendar: float = 720.0) -> dict:
    return {"source_system": client.upper(), "machine_code": unit, "year_month": month,
            "intervention_hours": hours, "calendar_hours_month": calendar}


def _reliability(client: str, unit: str, month: str, failures: int, downtime: float,
                 intervals: int, mtbf: float | None, low: bool = False) -> dict:
    return {"source_system": client.upper(), "machine_code": unit, "year_month": month,
            "n_failures": failures, "mttr_hours": downtime / failures, "total_downtime_hours": downtime,
            "n_mtbf_intervals": intervals, "mtbf_hours": mtbf, "low_confidence": low}


def _fleet(client: str, start: str, end: str, hours: float, fleet: int) -> list[dict]:
    return [
        {"source_system": client.upper(), "day": day, "year_month": day.strftime("%Y-%m"),
         "intervention_hours": hours, "calendar_hours_fleet": fleet * 24.0, "n_machines_fleet": fleet}
        for day in pd.date_range(start, end, freq="D")
    ]


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    client = "capstone"
    _write(tmp_path, client, "query_8_intervention_hours_monthly", [
        _hours(client, "CA-30", "2026-04", 72.0),
        _hours(client, "CA-31", "2026-04", 0.0),
        _hours(client, "CA-30", "2026-05", 36.0, 744.0),
        _hours(client, "CA-31", "2026-05", 108.0, 744.0),
        _hours(client, "CA-30", "2026-06", 10.0, 720.0),
    ])
    _write(tmp_path, client, "query_5_reliability_monthly", [
        _reliability(client, "CA-30", "2026-05", 2, 30.0, 1, 100.0, low=True),
        _reliability(client, "CA-31", "2026-05", 1, 6.0, 3, 300.0, low=True),
        _reliability(client, "CA-30", "2026-04", 1, 10.0, 0, None, low=True),
    ])
    # Data reaches 2026-06-10: June is partial, so May is the default month.
    _write(tmp_path, client, "query_9_fleet_intervention_daily", _fleet(client, "2026-04-01", "2026-06-10", 1.0, 2))
    return tmp_path


def _kpis(root: Path, client: str = "capstone", **kwargs) -> dict:
    return json.loads(DashboardDataRepository(root).query_maintenance_kpis(client, **kwargs))


# ---------------------------------------------------------------- formulas


def test_default_period_is_the_latest_complete_month(data_root):
    payload = _kpis(data_root)
    assert payload["period"]["selected"] == "2026-05"
    assert payload["period"]["partial_month"] is False
    assert payload["period"]["data_until"] == "2026-06-10"


def test_time_kpis_follow_query_8(data_root):
    kpis = _kpis(data_root, period="2026-05")["kpis"]
    # (1488 - 144) / 1488
    assert kpis["downtime_hours"] == 144.0
    assert kpis["availability_pct"] == round((1488 - 144) / 1488 * 100, 1)
    assert kpis["equipment"] == 2


def test_mtbf_is_weighted_by_intervals_and_mttr_by_failures(data_root):
    kpis = _kpis(data_root, period="2026-05")["kpis"]
    assert kpis["mtbf_hours"] == round((100 * 1 + 300 * 3) / 4, 1)   # 250.0, not the mean 200
    assert kpis["mttr_hours"] == round((30 + 6) / 3, 1)              # 12.0
    assert kpis["failures"] == 3


def test_a_missing_mtbf_is_null_not_zero(data_root):
    kpis = _kpis(data_root, period="2026-04")["kpis"]
    assert kpis["mtbf_hours"] is None
    assert kpis["mttr_hours"] == 10.0


def test_all_low_confidence_is_reported(data_root):
    quality = _kpis(data_root, period="2026-05")["reliability_quality"]
    assert quality["all_low_confidence"] is True


def test_baseline_compares_against_previous_months_per_month(data_root):
    base = _kpis(data_root, period="2026-05")["baseline_previous_months"]
    assert base["months"] == "2026-04 a 2026-04"
    assert base["downtime_hours_per_month"] == 72.0


def test_ranking_orders_units_by_downtime_with_cumulative_share(data_root):
    top = _kpis(data_root, period="2026-05")["top_units_by_downtime"]
    assert [row["unit_id"] for row in top] == ["CA-31", "CA-30"]
    assert top[0]["share_pct"] == 75.0
    assert top[-1]["cumulative_pct"] == 100.0


def test_unit_ids_are_matched_in_any_format(data_root):
    payload = _kpis(data_root, period="2026-05", unit_id="ca30")
    assert payload["unit_id"] == "CA-30"
    assert payload["kpis"]["downtime_hours"] == 36.0
    assert "top_units_by_downtime" not in payload


def test_an_unknown_unit_returns_the_units_that_exist(data_root):
    payload = _kpis(data_root, unit_id="XX-99")
    assert payload["unit_found"] is False
    assert "CA-30" in payload["filter_hints"]["available_values"]["unit_id"]


def test_a_month_without_data_is_an_explained_error(data_root):
    with pytest.raises(CampbellDataError, match="Meses disponibles: 2026-04 a 2026-06"):
        _kpis(data_root, period="2019-01")


def test_a_month_after_the_data_points_to_the_latest_complete_month(data_root):
    """A period computed from today's date must not end on the partial newest month."""
    with pytest.raises(CampbellDataError, match="ultimo mes completo con datos es 2026-05") as error:
        _kpis(data_root, period="2026-11")
    assert "2026-06-10" in str(error.value)


def test_reliability_is_optional(data_root):
    (data_root / "mantentions/golden/capstone" / VIEWS / "query_5_reliability_monthly.parquet").unlink()
    kpis = _kpis(data_root, period="2026-05")["kpis"]
    assert kpis["availability_pct"] is not None
    assert kpis["mtbf_hours"] is None and kpis["mttr_hours"] is None


def test_emin_fleet_availability_uses_the_whole_fleet_calendar(tmp_path):
    """The tab divides EMIN's fleet by query 9; the chat must do the same."""
    _write(tmp_path, "emin", "query_8_intervention_hours_monthly", [_hours("emin", "BULL-1", "2026-05", 62.0, 744.0)])
    _write(tmp_path, "emin", "query_9_fleet_intervention_daily", _fleet("emin", "2026-05-01", "2026-05-31", 2.0, 10))
    kpis = _kpis(tmp_path, client="emin", period="2026-05")["kpis"]
    assert kpis["downtime_hours"] == 62.0
    assert kpis["availability_pct"] == round((7440 - 62) / 7440 * 100, 1)
    assert kpis["equipment"] == 10


# ---------------------------------------------------------------- catalogue and charts


def test_sources_and_capability_are_declared():
    for key in ("maintenance_hours_monthly", "maintenance_reliability", "maintenance_fleet_daily"):
        assert key in DATASET_MAP
    capability = next(c for c in ANALYSIS_CAPABILITIES if c.key == "maintenance_kpis")
    assert capability.requires == ("maintenance_hours_monthly",)
    assert capability.requires_services == ("monitoring-mantenciones",)


def test_named_charts_render_from_the_same_numbers(data_root):
    registry = DashboardChartRegistry(DashboardDataRepository(data_root))
    listed = {chart["chart_id"] for chart in registry.list_charts("capstone")}
    assert {"maintenance_kpi_summary", "maintenance_downtime_ranking"} <= listed

    summary = registry.render("capstone", "maintenance_kpi_summary", {})
    assert summary.chart_type == "indicator"
    assert summary.summary["kpis"]["downtime_hours"] == 144.0
    assert "disponibilidad calendario" in summary.description
    assert "baja confianza" in summary.description

    ranking = registry.render("capstone", "maintenance_downtime_ranking", {"period": "2026-04"})
    assert list(ranking.summary["top"]) == ["CA-30"]


def test_a_kpi_without_data_is_drawn_as_missing(data_root):
    registry = DashboardChartRegistry(DashboardDataRepository(data_root))
    figure = registry.render("capstone", "maintenance_kpi_summary", {"period": "2026-04"}).figure
    titles = [trace["title"]["text"] for trace in figure["data"]]
    assert any(title.startswith("MTBF") and "sin dato" in title for title in titles)


# ---------------------------------------------------------------- parity with the tab


REAL_ROOT = Path(__file__).resolve().parents[1] / "data"


@pytest.mark.parametrize("client", ["capstone", "emin", "cda"])
def test_parity_with_the_mantenciones_tab_on_real_data(client, monkeypatch):
    source = REAL_ROOT / "mantentions" / "golden" / client / VIEWS / "query_8_intervention_hours_monthly.parquet"
    if not source.exists():
        pytest.skip("datos reales de mantenciones no disponibles")
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(REAL_ROOT))
    from src.data.maintenance_repository import MaintenanceRepository

    chat = _kpis(REAL_ROOT, client=client)
    period = chat["period"]["selected"]
    tab = MaintenanceRepository(mode="parquet", client=client).get_monthly_payload(period=period)["kpis"]
    pairs = {
        "availability_pct": "availability_est_pct",
        "downtime_hours": "downtime_est_hours",
        "mtbf_hours": "mtbf_est_hours",
        "mttr_hours": "mttr_est_hours",
    }
    for chat_key, tab_key in pairs.items():
        assert chat["kpis"][chat_key] == tab.get(tab_key), (client, period, chat_key)
