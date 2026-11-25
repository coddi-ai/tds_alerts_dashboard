"""Contract and presentation checks for the EMIN historical dashboard page."""

import gzip
import json

import pytest

from dashboard.components.emin_historical import build_historical_view, filter_options
from dashboard.callbacks import emin_historical_callbacks
from src.data.emin_historical import InvalidHistoricalBundle, load_emin_historical_bundle


RUN = "20261124T0000-0300-" + "a" * 64


def _daily(day, unit, rank, points, *, groups=None, observed=False, estimated=False):
    return {
        "cutoff": f"{day}T00:00:00-03:00",
        "day": day,
        "unit": unit,
        "rank": rank,
        "points": points,
        "has_observation": observed,
        "estimated": estimated,
        "alerts": 1 if observed else 0,
        "health_events": 1 if observed else 0,
        "event_groups": groups or [],
    }


def _make_package(root, *, synthetic=False, run=RUN):
    package = root / "emin_historical" / "published" / run
    package.mkdir(parents=True)
    (root / "emin_historical" / "published" / "latest.json").write_text(
        json.dumps({"run": run}), encoding="utf-8"
    )
    (package / "manifest.json").write_text(
        json.dumps({"synthetic": synthetic, "weeks": 12, "units": 2,
                    "dashboard_contract": "coddi.emin.historical-dashboard.v1",
                    "online": {"evidence_as_of": "2026-11-25T12:00:00Z"}}),
        encoding="utf-8",
    )
    daily = [
        _daily("2026-11-23", "EMIN-001", 1, 13.5, groups=["Motor / Emisiones"], observed=True),
        _daily("2026-11-24", "EMIN-001", 1, 12.0, groups=["Motor / Emisiones"], observed=True),
        _daily("2026-11-23", "EMIN-002", 2, 0.0),
        _daily("2026-11-24", "EMIN-002", 2, 0.0),
    ]
    observed = [
        {
            "unit": "EMIN-001", "day": "2026-11-23", "kind": "maintenance_action", "level": "",
            "event_at": "2026-11-23T08:00:00-03:00", "details": {"Evento": "Mantención preventiva"},
        },
        {
            "unit": "EMIN-001", "day": "2026-11-24", "kind": "event", "level": "",
            "event_at": "2026-11-24T11:00:00-03:00", "details": {"Evento": "Temperatura elevada del sistema EGR", "Componente": "Postratamiento"},
        },
        {
            "unit": "EMIN-001", "day": "2026-11-24", "kind": "maintenance_action", "level": "",
            "event_at": "2026-11-24T13:00:00-03:00", "details": {"Evento": "Cambio de motor tras una explosión"},
        },
        {
            "unit": "EMIN-001", "day": "2026-11-25", "kind": "event", "level": "",
            "event_at": "2026-11-25T13:00:00-03:00", "details": {"Evento": "Evento posterior al corte"},
        },
    ]
    (package / "daily.json").write_text(json.dumps(daily), encoding="utf-8")
    (package / "observed.json").write_text(json.dumps(observed), encoding="utf-8")
    movements = {
        "EMIN-001": {"status": "improved", "current": daily[1], "previous": daily[0], "delta": -1.5,
                     "lag_days": 0, "gap_days": 1, "historical_status": None},
        "EMIN-002": {"status": "stable", "current": daily[3], "previous": daily[2], "delta": 0,
                     "lag_days": 0, "gap_days": 1, "historical_status": None},
    }
    annotated = [dict(row, analysis={"major_event": ("text" if row.get("details", {}).get("Evento", "").startswith("Cambio de motor") else None),
                                    "high_signal": False, "replacement_day": None}) for row in observed]
    with gzip.open(package / "dashboard.json.gz", "wt", encoding="utf-8") as dashboard_file:
      json.dump({
        "contract": "coddi.emin.historical-dashboard.v1",
        "catalog": {"cutoffs": ["2026-11-24", "2026-11-23"], "units": ["EMIN-001", "EMIN-002"],
                    "groups": ["Motor / Emisiones"], "periods": ["short", "medium", "long", "history"]},
        "fleet": {
            "2026-11-23": {"rows": [daily[0], daily[2]], "movements": {"EMIN-001": movements["EMIN-001"], "EMIN-002": movements["EMIN-002"]},
                           "movement_counts": {"improved": 1, "stable": 1}, "groups": {"Motor / Emisiones": [daily[0]]},
                           "groups_summary": [{"group": "Motor / Emisiones", "count": 1}], "high_signal_counts": {},
                           "critical_units": [], "critical_remaining": [], "critical_event_days": {}, "critical_total": 0,
                           "score_priority_units": [], "healthiest_units": [], "can_distinguish_health": True},
            "2026-11-24": {"rows": [daily[1], daily[3]], "movements": movements,
                           "movement_counts": {"improved": 1, "stable": 1}, "groups": {"Motor / Emisiones": [daily[1]]},
                           "groups_summary": [{"group": "Motor / Emisiones", "count": 1}], "high_signal_counts": {},
                           "critical_units": [], "critical_remaining": [], "critical_event_days": {}, "critical_total": 0,
                           "score_priority_units": [], "healthiest_units": [], "can_distinguish_health": True},
        },
        "tops": {day: {period: {"start": day, "cutoff": day, "span_days": 1, "covered_days": 1,
                                "insufficient_units": 0, "entries": [], "movement_by_unit": movements,
                                "overlaps_short": False, "history_signal_only": False}
                       for period in ("short", "medium", "long", "history")} for day in ("2026-11-23", "2026-11-24")},
        "units": {"EMIN-001": {"daily": [daily[0], daily[1]], "evidence": annotated,
                                "by_cutoff": {"2026-11-24": {"movement": movements["EMIN-001"],
                                                              "movement_drivers": [],
                                                              "trend": [daily[0], daily[1]],
                                                              "components": {"short": {"start": "2026-11-24", "cutoff": "2026-11-24", "observed_days": 1, "attributed_points": 0, "components": []}}}}}},
        "evidence": annotated,
      }, dashboard_file)
    return root


def _visible(component):
    if isinstance(component, str):
        return component
    if isinstance(component, (list, tuple)):
        return "\n".join(_visible(item) for item in component)
    return _visible(getattr(component, "children", []))


def test_loads_current_package_and_resolves_only_inside_data_root(tmp_path):
    root = _make_package(tmp_path)

    bundle = load_emin_historical_bundle(root)

    assert bundle.run == RUN
    assert len(bundle.daily) == 4
    assert bundle.observed[0]["details"]["Evento"] == "Mantención preventiva"


def test_rejects_synthetic_package(tmp_path):
    root = _make_package(tmp_path, synthetic=True)

    with pytest.raises(InvalidHistoricalBundle, match="observados"):
        load_emin_historical_bundle(root)


def test_rejects_invalid_pointer_and_incomplete_daily_schema(tmp_path):
    root = tmp_path / "emin_historical" / "published"
    root.mkdir(parents=True)
    (root / "latest.json").write_text(json.dumps({"run": "../latest.json"}), encoding="utf-8")
    with pytest.raises(InvalidHistoricalBundle, match="identificador"):
        load_emin_historical_bundle(tmp_path)

    package = _make_package(tmp_path)
    path = package / "emin_historical" / "published" / RUN / "daily.json"
    path.write_text("[{}]", encoding="utf-8")
    with pytest.raises(InvalidHistoricalBundle, match="contrato"):
        load_emin_historical_bundle(package)


def test_fleet_and_unit_views_keep_evidence_and_heuristic_language(tmp_path):
    root = _make_package(tmp_path)
    bundle = load_emin_historical_bundle(root)
    options = filter_options(bundle)

    assert options["default_day"] == "2026-11-24"
    assert {item["value"] for item in options["groups"]} == {"__all__", "Motor / Emisiones"}
    view = build_historical_view(bundle, "2026-11-24", "Motor / Emisiones", "EMIN-001")

    ranking = _visible(view["ranking"])
    timeline = _visible(view["evidence"])
    assert "EMIN-001" in ranking
    assert "EMIN-002" not in ranking
    assert "Mejoró" in ranking
    assert "Cambio de motor tras una explosión" in timeline
    assert "Temperatura elevada del sistema EGR" in timeline
    assert "Mantención preventiva" in timeline
    assert "Evento posterior al corte" not in timeline
    assert timeline.count("Coincidencia textual de cambio/falla mayor") == 2
    assert "señal heurística bajó" in _visible(view["status"]).lower()
    assert list(view["trend"].data[0].x) == ["2026-11-23", "2026-11-24"]
    assert list(view["trend"].data[0].y) == [13.5, 12.0]
    assert "Puntaje heurístico" in view["trend"].layout.yaxis.title.text


def test_page_callbacks_require_server_authorization_for_emin(monkeypatch):
    monkeypatch.setattr(emin_historical_callbacks, "allowed_clients", lambda user: ["CDA"])
    assert not emin_historical_callbacks._authorized_emin("EMIN", {"username": "cda-user"})
    assert not emin_historical_callbacks._authorized_emin("CDA", {"username": "cda-user"})

    monkeypatch.setattr(emin_historical_callbacks, "allowed_clients", lambda user: ["eMin"])
    assert emin_historical_callbacks._authorized_emin("EMIN", {"username": "emin-user"})
