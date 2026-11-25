"""Contract and presentation checks for the EMIN historical dashboard page."""

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
                    "online": {"evidence_as_of": "2026-11-25T12:00:00Z"}}),
        encoding="utf-8",
    )
    daily = [
        _daily("2026-11-23", "EMIN-001", 1, 13.5, groups=["Motor / Emisiones"], observed=True),
        _daily("2026-11-24", "EMIN-001", 1, 12.0, groups=["Motor / Emisiones"], observed=True),
        _daily("2026-11-23", "EMIN-002", 2, 0.0),
        _daily("2026-11-24", "EMIN-002", 2, 0.0),
    ]
    (package / "daily.json").write_text(json.dumps(daily), encoding="utf-8")
    observed = [{
        "unit": "EMIN-001",
        "day": "2026-11-24",
        "kind": "event",
        "level": "",
        "event_at": "2026-11-24T11:00:00-03:00",
        "details": {"Evento": "Temperatura elevada del sistema EGR", "Componente": "Postratamiento"},
    }]
    (package / "observed.json").write_text(json.dumps(observed), encoding="utf-8")
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
    assert bundle.observed[0]["details"]["Evento"].endswith("EGR")


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


def test_filter_options_and_view_keep_group_evidence_and_heuristic_language(tmp_path):
    root = _make_package(tmp_path)
    bundle = load_emin_historical_bundle(root)
    options = filter_options(bundle)

    assert options["default_day"] == "2026-11-24"
    assert {item["value"] for item in options["groups"]} == {"__all__", "Motor / Emisiones"}
    view = build_historical_view(bundle, "2026-11-24", "Motor / Emisiones", "EMIN-001")

    assert "EMIN-001" in _visible(view["ranking"])
    assert "EMIN-002" not in _visible(view["ranking"])
    assert "Temperatura elevada del sistema EGR" in _visible(view["evidence"])
    assert list(view["trend"].data[0].x) == ["2026-11-23", "2026-11-24"]
    assert view["trend"].layout.yaxis.autorange == "reversed"
    assert "no representa una probabilidad" in _visible(view["kpis"]).lower()


def test_page_callbacks_require_server_authorization_for_emin(monkeypatch):
    monkeypatch.setattr(emin_historical_callbacks, "allowed_clients", lambda user: ["CDA"])
    assert not emin_historical_callbacks._authorized_emin("EMIN", {"username": "cda-user"})
    assert not emin_historical_callbacks._authorized_emin("CDA", {"username": "cda-user"})

    monkeypatch.setattr(emin_historical_callbacks, "allowed_clients", lambda user: ["eMin"])
    assert emin_historical_callbacks._authorized_emin("EMIN", {"username": "emin-user"})
