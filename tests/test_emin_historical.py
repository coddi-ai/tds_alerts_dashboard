"""Contract and presentation checks for the EMIN historical dashboard page."""

import gzip
import json
from types import SimpleNamespace

import pytest
from dash import dcc
import plotly.graph_objects as go

from dashboard.components.emin_historical import _fleet_movement_trend, _fleet_point_label_position, build_historical_view, filter_options, fleet_criticality_top
from dashboard.callbacks import emin_historical_callbacks
from dashboard.callbacks.emin_historical_callbacks import _trend_figure_from_view
from dashboard.components.predictive_state import STATE_ZONE_FILL
from src.data.emin_historical import InvalidHistoricalBundle, load_emin_historical_bundle
from src.i18n import t


RUN = "20261124T0000-0300-" + "a" * 64


def test_trend_callback_value_accepts_legacy_figures_and_v2_graphs():
    figure = go.Figure()

    assert _trend_figure_from_view({"trend": figure}) is figure
    assert _trend_figure_from_view({"trend": dcc.Graph(figure=figure)}) is figure


def _fleet_view_bundle(variations):
    return SimpleNamespace(dashboard={
        "metadata": {"variation_stability_tolerance": 1.0},
        "catalog": {"cutoffs": ["2026-11-24"], "units": ["EMIN-001", "EMIN-002"]},
        "fleet": {"2026-11-24": {
            "period_variations": {"week": variations},
            "critical_units": [],
            "score_priority_units": [],
        }},
        "period_tops": {},
    })


def test_fleet_variation_plot_includes_every_comparable_unit():
    bundle = _fleet_view_bundle({
        "EMIN-001": {"status": "worsened", "previous_average": 4.0, "current_average": 8.0,
                     "delta": 4.0, "current_days": 7},
        "EMIN-002": {"status": "improved", "previous_average": 9.0, "current_average": 3.0,
                     "delta": -6.0, "current_days": 7},
    })
    bundle.dashboard["period_tops"] = {
        "2026-11-24": {"week": {"entries": [{"unit": "EMIN-002"}]}}
    }

    graph = _fleet_movement_trend(bundle, "2026-11-24", "week")

    points = [trace for trace in graph.figure.data if trace.name != t("emin_history.no_change_line")]
    assert sum(len(trace.x) for trace in points) == 2
    assert {label for trace in points for label in (trace.text or []) if label} == {"EMIN-002"}
    assert all(row[4] == "week" for trace in points for row in trace.customdata)
    assert graph.figure.layout.xaxis.range[0] == 0
    assert graph.figure.layout.xaxis.range == graph.figure.layout.yaxis.range
    assert graph.figure.layout.yaxis.scaleanchor is None
    assert graph.figure.layout.showlegend is True
    assert graph.figure.layout.legend.orientation == "h"
    zone_colors = {shape.fillcolor for shape in graph.figure.layout.shapes}
    assert zone_colors == {STATE_ZONE_FILL["Normal"], STATE_ZONE_FILL["Alerta"], STATE_ZONE_FILL["Anormal"]}
    assert all(shape.layer == "below" and shape.type == "path" for shape in graph.figure.layout.shapes)
    assert len([annotation for annotation in graph.figure.layout.annotations
                if annotation.text in {t("emin_history.zone_improving"), t("emin_history.zone_stable"),
                                       t("emin_history.zone_worsening")}]) == 3
    assert any(annotation.y > 1 for annotation in graph.figure.layout.annotations)
    coverage = next(annotation for annotation in graph.figure.layout.annotations if annotation.y > 1)
    assert coverage.x == 0.5
    assert _fleet_point_label_position(21, 21, 0, 24) == "middle left"
    assert _fleet_point_label_position(12, 21, 0, 24) == "bottom center"


def test_quarter_without_prior_comparison_shows_a_clear_empty_state():
    bundle = _fleet_view_bundle({
        unit: {"status": "insufficient", "previous_average": None, "current_average": None}
        for unit in ("EMIN-001", "EMIN-002")
    })
    bundle.dashboard["fleet"]["2026-11-24"]["period_variations"] = {"quarter": bundle.dashboard["fleet"]["2026-11-24"]["period_variations"]["week"]}

    graph = _fleet_movement_trend(bundle, "2026-11-24", "quarter")

    assert graph.figure.layout.xaxis.visible is False
    assert graph.figure.layout.yaxis.visible is False
    message = graph.figure.layout.annotations[0].text
    assert t("emin_history.quarter_comparison_unavailable") in message


def test_criticality_top_tracks_the_selected_period():
    bundle = _fleet_view_bundle({})
    week = {"start": "2026-11-23", "entries": [{"unit": "EMIN-001"}]}
    month = {"start": "2026-11-01", "entries": [{"unit": "EMIN-002"}]}
    bundle.dashboard["period_tops"] = {"2026-11-24": {"week": week, "month": month}}

    assert fleet_criticality_top(bundle, "2026-11-24", "week") == week
    assert fleet_criticality_top(bundle, "2026-11-24", "month") == month


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


def _make_package(root, *, synthetic=False, run=RUN, week="2026-W48", published_at="2026-11-25T12:00:00Z"):
    package = root / "fleet_history" / "golden" / "emin" / week
    package.mkdir(parents=True, exist_ok=True)
    files = {name: f"{run}--{name}" for name in ("manifest.json", "daily.json", "observed.json", "dashboard.json.gz")}
    (package / "latest.json").write_text(
        json.dumps({"run": run, "week_year_iso": week, "published_at": published_at, "files": files}),
        encoding="utf-8",
    )
    (package / files["manifest.json"]).write_text(
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
    (package / files["daily.json"]).write_text(json.dumps(daily), encoding="utf-8")
    (package / files["observed.json"]).write_text(json.dumps(observed), encoding="utf-8")
    movements = {
        "EMIN-001": {"status": "improved", "current": daily[1], "previous": daily[0], "delta": -1.5,
                     "lag_days": 0, "gap_days": 1, "historical_status": None},
        "EMIN-002": {"status": "stable", "current": daily[3], "previous": daily[2], "delta": 0,
                     "lag_days": 0, "gap_days": 1, "historical_status": None},
    }
    annotated = [dict(row, analysis={"major_event": ("text" if row.get("details", {}).get("Evento", "").startswith("Cambio de motor") else None),
                                    "high_signal": False, "replacement_day": None}) for row in observed]
    with gzip.open(package / files["dashboard.json.gz"], "wt", encoding="utf-8") as dashboard_file:
      json.dump({
        "contract": "coddi.emin.historical-dashboard.v1",
        "catalog": {"cutoffs": ["2026-11-24", "2026-11-23"],
                    "iso_week_cutoffs": [{"week": "2026-W48", "cutoff": "2026-11-24", "complete": False}],
                    "units": ["EMIN-001", "EMIN-002"],
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


def test_selects_newest_capture_across_iso_week_folders(tmp_path):
    _make_package(tmp_path)
    newer_run = "20261201T0000-0300-" + "b" * 64
    _make_package(tmp_path, run=newer_run, week="2026-W49", published_at="2026-12-01T12:00:00Z")

    bundle = load_emin_historical_bundle(tmp_path)

    assert bundle.run == newer_run
    assert load_emin_historical_bundle(tmp_path, run_name=RUN).run == RUN


def test_rejects_synthetic_package(tmp_path):
    root = _make_package(tmp_path, synthetic=True)

    with pytest.raises(InvalidHistoricalBundle, match="observados"):
        load_emin_historical_bundle(root)


def test_rejects_invalid_pointer_and_incomplete_daily_schema(tmp_path):
    root = tmp_path / "fleet_history" / "golden" / "emin" / "2026-W48"
    root.mkdir(parents=True)
    (root / "latest.json").write_text(json.dumps({"run": "../latest.json", "week_year_iso": "2026-W48",
                                                  "files": {}}), encoding="utf-8")
    with pytest.raises(InvalidHistoricalBundle, match="identificador"):
        load_emin_historical_bundle(tmp_path)

    package = _make_package(tmp_path)
    path = package / "fleet_history" / "golden" / "emin" / "2026-W48" / f"{RUN}--daily.json"
    path.write_text("[{}]", encoding="utf-8")
    with pytest.raises(InvalidHistoricalBundle, match="contrato"):
        load_emin_historical_bundle(package)


def test_fleet_and_unit_views_keep_evidence_and_heuristic_language(tmp_path):
    root = _make_package(tmp_path)
    bundle = load_emin_historical_bundle(root)
    options = filter_options(bundle)
    bundle.dashboard["units"]["EMIN-001"]["cumulative_weekly_score"] = [
        {"week": "2026-W46", "cutoff": "2026-11-15", "weekly_mean": 8, "cumulative_score": 8, "observed_days": 3,
         "available_days": 7, "complete": True},
        {"week": "2026-W47", "cutoff": "2026-11-22", "weekly_mean": None, "cumulative_score": None, "observed_days": 0,
         "available_days": 7, "complete": True},
        {"week": "2026-W48", "cutoff": "2026-11-24", "weekly_mean": 12, "cumulative_score": 20, "observed_days": 2,
         "available_days": 2, "complete": False},
    ]

    assert options["default_day"] == "2026-11-24"
    assert options["days"] == [{"label": "2026-W48 · datos hasta 24-11-2026 · parcial", "value": "2026-11-24"}]
    assert {item["value"] for item in options["groups"]} == {"__all__", "Motor / Emisiones"}
    view = build_historical_view(bundle, "2026-11-24", "Motor / Emisiones", "EMIN-001")

    ranking = _visible(view["ranking"])
    timeline = _visible(view["evidence"])
    meta = _visible(view["meta"])
    assert "EMIN-001" in ranking
    assert "EMIN-002" not in ranking
    assert "Mejoró" in ranking
    assert "Cambio de motor tras una explosión" in timeline
    assert t("emin_history.evidence_title") in timeline
    assert "Temperatura elevada del sistema EGR" in timeline
    assert "Mantención preventiva" in timeline
    assert "Evento posterior al corte" not in timeline
    assert timeline.count("Coincidencia textual de cambio/falla mayor") == 2
    assert "señal heurística bajó" in _visible(view["status"]).lower()
    assert "Semana ISO: 2026-W48 · datos hasta 24-11-2026 · parcial" in meta
    assert "Semanas ISO en el paquete: 1" in meta
    assert list(view["trend"].data[0].x) == ["2026-11-23", "2026-11-24"]
    assert list(view["trend"].data[0].y) == [13.5, 12.0]
    assert "Puntaje heurístico" in view["trend"].layout.yaxis.title.text
    cumulative = view["cumulative_score"].figure
    assert list(cumulative.data[0].x) == ["2026-W46", "2026-W47", "2026-W48"]
    assert list(cumulative.data[0].y) == [8, None, 20]
    assert cumulative.data[0].connectgaps is False
    earlier_view = build_historical_view(bundle, "2026-11-23", "__all__", "EMIN-001")
    assert list(earlier_view["cumulative_score"].figure.data[0].x) == ["2026-W46", "2026-W47"]


def test_legacy_catalog_still_offers_one_cutoff_per_iso_week(tmp_path):
    root = _make_package(tmp_path)
    bundle = load_emin_historical_bundle(root)
    bundle.dashboard["catalog"].pop("iso_week_cutoffs")

    options = filter_options(bundle)

    assert options["days"] == [{"label": "2026-W48 · datos hasta 24-11-2026 · parcial", "value": "2026-11-24"}]


def test_page_callbacks_require_server_authorization_for_emin(monkeypatch):
    monkeypatch.setattr(emin_historical_callbacks, "allowed_clients", lambda user: ["CDA"])
    assert not emin_historical_callbacks._authorized_emin("EMIN", {"username": "cda-user"})
    assert not emin_historical_callbacks._authorized_emin("CDA", {"username": "cda-user"})

    monkeypatch.setattr(emin_historical_callbacks, "allowed_clients", lambda user: ["eMin"])
    assert emin_historical_callbacks._authorized_emin("EMIN", {"username": "emin-user"})
