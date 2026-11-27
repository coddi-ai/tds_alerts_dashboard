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
from dashboard.components.emin_beta import _weekly_facts, evidence_page, fleet_figure, fleet_table, unit_records_page, unit_story
from dashboard.components.predictive_state import STATE_ZONE_FILL
from dashboard.tabs.tab_emin_historical import create_layout as create_emin_historical_layout
from src.data.emin_historical import InvalidHistoricalBundle, _validate_condition_model, load_emin_historical_bundle
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


def _walk_components(component):
    if component is None:
        return
    if isinstance(component, (list, tuple)):
        for child in component:
            yield from _walk_components(child)
        return
    yield component
    yield from _walk_components(getattr(component, "children", None))


def test_beta_has_static_cutoff_and_a_single_fleet_table_filter():
    components = list(_walk_components(create_emin_historical_layout()))
    tabs = {component.id: component for component in components if isinstance(component, dcc.Tabs)}
    ids = {getattr(component, "id", None) for component in components}
    assert [tab.value for tab in tabs["emin-history-view-tabs"].children] == ["fleet", "unit"]
    assert len(tabs) == 1
    assert {"emin-beta-cutoff", "emin-beta-group", "emin-beta-ranking", "emin-beta-story"} <= ids
    assert {"emin-beta-milestones-graph", "emin-beta-milestones-rows", "emin-beta-oil-graph",
            "emin-beta-oil-rows", "emin-beta-oil-red"} <= ids
    assert "emin-history-cutoff" not in ids
    assert "emin-history-cumulative-score" not in ids


def test_beta_retains_labels_for_coincident_units_and_preserves_filtered_rank():
    common = dict(points=5.5, rank=2, domains={"Motor": 5.5}, observed_weeks=3,
                  comparison=dict(previous_average=5, current_average=6, delta=1, previous_bucket="2026-W45",
                                  current_bucket="2026-W48", status="stable", missing=[], quadrant="recent_worsening"))
    report = {"cutoff": {"week": "2026-W48"}, "units": {}, "domains": ["Motor"], "quadrants": {"threshold": 5}, "rows": [
        dict(common, unit="CT-1", groups=["Motor / Emisiones"]),
        dict(common, unit="CT-2", groups=["Seguridad / Frenos"]),
    ]}
    figure = fleet_figure(report)
    assert [(point["unit"], point["x"], point["y"]) for point in figure.layout.meta["fleetLabels"]] == [
        ("CT-1", 6, 5), ("CT-2", 6, 5),
    ]
    assert sum(shape.type == "rect" for shape in figure.layout.shapes) == 4
    filtered = _visible(fleet_table(report, "Seguridad / Frenos"))
    assert "CT-1" not in filtered and "CT-2" in filtered and "5.5" in filtered
    assert "1 de 2 equipos" in filtered
    assert "No hay equipos" in _visible(fleet_table(report, "Grupo inexistente"))


def test_beta_abnormal_oil_filter_uses_the_original_condition():
    row = dict(id=3, category="oil", kind="oil", day="2024-01-01", component="Motor",
               description="Metales altos", severity="", reference="M-100", hours=None, failures=None)
    report = {"units": {"CT-1": {"records": [
        dict(row, state="abnormal"), dict(row, id=4, state="alert", reference="M-101"),
    ]}}}
    result, page, at_start, at_end = evidence_page(report, "CT-1", "abnormal_oil", "", 0)
    text = _visible(result)
    assert "M-100" in text and "Anormal" in text and "M-101" not in text
    assert page == 0 and at_start and at_end


def test_beta_weekly_fact_links_to_exact_record_and_does_not_promote_an_old_alert():
    recorded = dict(id=8, kind="event", category="event", day="2026-11-25", week="2026-W48",
                    state="high", component="Frenos", description="Presión baja", severity="Alta",
                    reference="OT-10", hours=None, failures=None)
    older = dict(recorded, id=7, kind="oil", category="oil", day="2026-11-19", week="2026-W47",
                 state="abnormal", description="Aceite anterior")
    report = {"cutoff": {"week": "2026-W48"}, "units": {
        "CT-1": {"records": [recorded, older], "headline": [7], "timeline": [], "oil": []},
        "CT-2": {"records": [older]},
    }}
    assert _weekly_facts(report) == {"CT-1": recorded}
    finding = dict(recorded, id=9, kind="oil", category="oil", state="abnormal", description="Aceite reciente")
    report["units"]["CT-1"]["records"].append(finding)
    report["rows"] = [{"unit": "CT-1", "scoring_review": {"finding_id": 9}}]
    report["scoring_review_version"] = 1
    assert _weekly_facts(report) == {"CT-1": finding}
    summary = _visible(unit_story(report, "CT-1", {"unit": "CT-1", "record": 8})[0])
    assert "Presión baja" in summary and "Aceite anterior" not in summary
    assert "Registro que abriste desde la flota" in summary and "OT-10" in summary


def test_beta_dedicated_tables_use_sample_states_and_full_milestone_ids():
    row = dict(id=3, category="oil", kind="oil", day="2024-01-01", component="Motor",
               description="Metales altos", severity="", reference="M-100", hours=None, failures=None)
    intervention = dict(row, id=7, category="downtime", kind="downtime_record", state="recorded",
                        reference="OT-1", description="Detención", corrected_from="2014-11-11")
    report = {"units": {"CT-1": {"records": [
        dict(row, state="abnormal", week="2024-W01"),
        dict(row, id=4, state="alert", reference="M-101", week="2024-W02"), intervention,
    ], "milestone_ids": [7]}}}
    oil = _visible(unit_records_page(report, "CT-1", "oil", True, 0)[0])
    assert "M-100" in oil and "M-101" not in oil and "OT-1" not in oil
    week = _visible(unit_records_page(report, "CT-1", "oil", False, 0, "2024-W02")[0])
    assert "M-101" in week and "M-100" not in week
    milestones = _visible(unit_records_page(report, "CT-1", "milestones", False, 0)[0])
    assert "OT-1" in milestones and "M-100" not in milestones and "Fecha de origen corregida" in milestones


def test_beta_unit_without_oil_shows_missing_evidence():
    report = {"units": {"CT-1": {"records": [], "headline": [], "timeline": [], "oil": []}}}
    story = _visible(unit_story(report, "CT-1"))
    assert "no tiene muestras de aceite" in story
    assert "Ver muestras de aceite en rojo" not in story


def test_loads_current_package_and_resolves_only_inside_data_root(tmp_path):
    root = _make_package(tmp_path)

    bundle = load_emin_historical_bundle(root)

    assert bundle.run == RUN
    assert len(bundle.daily) == 4
    assert bundle.observed[0]["details"]["Evento"] == "Mantención preventiva"


def test_selects_latest_iso_week_even_if_an_older_week_is_republished(tmp_path):
    _make_package(tmp_path, published_at="2026-12-04T12:00:00Z")
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
    bundle.dashboard["units"]["EMIN-001"]["evidence"].append({
        "unit": "EMIN-001", "day": "2026-07-10", "event_at": "2026-07-10T08:00:00-03:00",
        "kind": "maintenance_action", "details": {"Evento": "Cambio histórico de motor"},
        "analysis": {"major_event": "text", "high_signal": False, "replacement_day": None},
    })
    options = filter_options(bundle)
    bundle.dashboard["units"]["EMIN-001"]["cumulative_weekly_score"] = [
        {"week": "2026-W46", "cutoff": "2026-11-15", "weekly_mean": 8, "cumulative_score": 8, "observed_days": 3,
         "available_days": 7, "complete": True, "fleet_mean_cumulative_score": 9,
         "difference_from_fleet_mean": -1, "fleet_relative_position": "below", "observed_weeks": 1, "fleet_observed_weeks": 1},
        {"week": "2026-W47", "cutoff": "2026-11-22", "weekly_mean": None, "cumulative_score": None, "observed_days": 0,
         "available_days": 7, "complete": True, "fleet_mean_cumulative_score": None,
         "difference_from_fleet_mean": None, "fleet_relative_position": None, "observed_weeks": 1, "fleet_observed_weeks": 1},
        {"week": "2026-W48", "cutoff": "2026-11-24", "weekly_mean": 12, "cumulative_score": 20, "observed_days": 2,
         "available_days": 2, "complete": False, "fleet_mean_cumulative_score": 22,
         "difference_from_fleet_mean": -2, "fleet_relative_position": "below", "observed_weeks": 2, "fleet_observed_weeks": 2},
    ]
    bundle.dashboard["units"]["EMIN-002"] = {"cumulative_weekly_score": [
        {"week": "2026-W46", "cutoff": "2026-11-15", "weekly_mean": 10, "cumulative_score": 10,
         "observed_days": 2, "available_days": 7, "complete": True, "fleet_mean_cumulative_score": 9,
         "difference_from_fleet_mean": 1, "fleet_relative_position": "above", "observed_weeks": 1, "fleet_observed_weeks": 1},
        {"week": "2026-W47", "cutoff": "2026-11-22", "weekly_mean": None, "cumulative_score": None,
         "observed_days": 0, "available_days": 7, "complete": True, "fleet_mean_cumulative_score": None,
         "difference_from_fleet_mean": None, "fleet_relative_position": None, "observed_weeks": 1, "fleet_observed_weeks": 1},
        {"week": "2026-W48", "cutoff": "2026-11-24", "weekly_mean": 14, "cumulative_score": 24,
         "observed_days": 2, "available_days": 2, "complete": False, "fleet_mean_cumulative_score": 22,
         "difference_from_fleet_mean": 2, "fleet_relative_position": "above", "observed_weeks": 2, "fleet_observed_weeks": 2},
    ]}
    bundle.dashboard["fleet"]["2026-11-24"]["cumulative_weekly_score"] = [
        {"week": "2026-W46", "cutoff": "2026-11-15", "weekly_mean": 9, "cumulative_score": 9,
         "observed_units": 2, "fleet_units": 2, "complete": True, "observed_weeks": 1},
        {"week": "2026-W47", "cutoff": "2026-11-22", "weekly_mean": 0, "cumulative_score": 9,
         "observed_units": 1, "fleet_units": 2, "complete": True, "observed_weeks": 2},
        {"week": "2026-W48", "cutoff": "2026-11-24", "weekly_mean": 13, "cumulative_score": 22,
         "observed_units": 1, "fleet_units": 2, "complete": False, "observed_weeks": 2},
    ]
    bundle.dashboard["fleet"]["2026-11-24"]["cumulative_comparison_by_unit"] = {
        "EMIN-001": {"position": "below"}, "EMIN-002": {"position": "above"},
    }
    bundle.dashboard["fleet"]["2026-11-23"]["cumulative_weekly_score"] = bundle.dashboard["fleet"]["2026-11-24"]["cumulative_weekly_score"][:2]

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
    assert "Cambio histórico de motor" in timeline
    assert t("emin_history.milestones_history_note", start="24-11-2026") in timeline
    assert t("emin_history.evidence_title") in timeline
    assert "Temperatura elevada del sistema EGR" in timeline
    assert "Mantención preventiva" in timeline
    assert "Evento posterior al corte" not in timeline
    assert timeline.count("Coincidencia textual de cambio/falla mayor") == 4
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
    fleet_cumulative = view["fleet_cumulative_score"].figure
    unit_traces = [trace for trace in fleet_cumulative.data
                   if str(trace.legendgroup).startswith("fleet-relative-")]
    mean_trace = fleet_cumulative.data[-1]
    assert len(unit_traces) == 2
    assert {trace.customdata[0][0] for trace in unit_traces} == {"EMIN-001", "EMIN-002"}
    assert list(unit_traces[0].x) == ["2026-W46", "2026-W47", "2026-W48"]
    assert list(mean_trace.x) == ["2026-W46", "2026-W47", "2026-W48"]
    assert list(mean_trace.y) == [9, 9, 22]
    assert mean_trace.name == t("emin_history.fleet_cumulative_mean")
    assert mean_trace.line.dash == "dash"
    assert "flota EMIN" in fleet_cumulative.layout.title.text
    assert "Equipos observados" in mean_trace.hovertemplate
    assert unit_traces[0].customdata[0][4] == "history"
    assert {trace.name for trace in unit_traces} == {
        t("emin_history.fleet_relative_above"), t("emin_history.fleet_relative_below"),
    }
    zone_traces = [trace for trace in fleet_cumulative.data if trace.legendgroup == "relative-zones"]
    assert len(zone_traces) == 2
    assert all(trace.fill == "toself" for trace in zone_traces)
    assert any(t("emin_history.fleet_cumulative_difference") in trace.hovertemplate for trace in unit_traces)
    earlier_view = build_historical_view(bundle, "2026-11-23", "__all__", "EMIN-001")
    assert "Cambio histórico de motor" in _visible(earlier_view["evidence"])
    assert "Cambio de motor tras una explosión" not in _visible(earlier_view["evidence"])
    assert list(earlier_view["cumulative_score"].figure.data[0].x) == ["2026-W46", "2026-W47"]
    assert list(earlier_view["fleet_cumulative_score"].figure.data[-1].x) == ["2026-W46", "2026-W47"]


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

def test_source_condition_preview_shows_known_and_unevaluated_units():
    from dashboard.components.emin_beta import fleet_intro
    model = {"version": 2, "threshold": 3, "review_order": ["CT-1"],
             "provenance": {"preview": True, "coverage_limitations": ["maintenance_classification"]},
             "rows": [
                 {"unit": "CT-1", "historical_points": 2, "previous_average": 2, "quadrant": "recent_worsening",
                  "current": {"points": 4, "level": "critical", "movement": "worsened", "changes": [], "active": []}},
                 {"unit": "CT-2", "historical_points": None, "previous_average": None, "current": None},
             ]}
    report = {"condition_model": model, "rows": [{"unit": "CT-1", "groups": []}, {"unit": "CT-2", "groups": []}],
              "methodology": "", "cutoff": {"cutoff": "2026-11-25", "week": "2026-W48"}}
    visible = _visible(fleet_intro(report))
    assert "Vista previa" in visible
    assert "Sin hallazgos graves nuevos registrados hasta el corte." in visible
    assert "probabilidad de falla" in visible
    assert "Críticos sostenidos" in visible
    assert "aparece en Empeoraron" in visible
    assert "Sin evaluación" in _visible(fleet_table(report, "__all__"))
    assert "Tasa no disponible" in _visible(fleet_table(report, "__all__"))


def test_condition_source_dates_distinguish_old_recent_and_missing():
    from datetime import date
    from dashboard.components.emin_beta import _condition_source_dates

    visible = _visible(_condition_source_dates({"alerts": "2026-11-01", "oil": "2026-11-23", "events": None},
                                               date(2026, 11, 25)))
    assert "Antiguo · hace 24 días" in visible
    assert "hace 2 días" in visible
    assert "Sin registro" in visible


def test_condition_rank_group_column_keeps_historical_groups_without_week_metadata():
    from dashboard.components.emin_beta import _condition_table

    row = {"unit": "CT-1", "rank": 1, "priority": None, "historical_points": 2,
           "groups": ["Motor / Emisiones", "Eléctrico / Red de datos"],
           "group_scopes": {"Motor / Emisiones": "histórico"},
           "current": {"level": "monitor", "points": 2, "movement": "stable", "active": [], "rate": None}}
    visible = _visible(_condition_table([row], "Eléctrico / Red de datos"))
    assert "Eléctrico / Red de datos · historial sin semana" in visible


def test_condition_model_contract_validates_hashes_units_and_cutoff_dates():
    digest = "a" * 64
    provenance = {
        "run_id": "alert-run", "sha256": digest, "manifest_sha256": digest,
        "base_package_run": RUN, "cutoff": "2026-11-25", "source_columns_sha256": digest,
        "base_package_manifest_sha256": digest, "alerts_rows": 1,
        "coverage_limitations": [], "preview": True,
        "base_package_files_sha256": {key: digest for key in ("daily.json", "observed.json", "dashboard.json.gz")},
    }
    row = {"unit": "CT-1", "historical_points": 1.0, "current": {
        "level": "monitor", "movement": "stable", "points": 1, "changes": [], "active": []},
        "weeks": [{"week": "2026-W48", "points": 1}], "source_dates": {"alerts": "2026-11-25"}}
    model = {"version": 2, "threshold": 29, "alert_threshold": 11, "rows": [row], "provenance": provenance}
    report = {"rows": [{"unit": "CT-1"}], "cutoff": {"week": "2026-W48", "cutoff": "2026-11-25"}}
    _validate_condition_model(model, dict(provenance), report)

    row["source_dates"]["alerts"] = "2026-11-26"
    with pytest.raises(InvalidHistoricalBundle, match="contrato"):
        _validate_condition_model(model, dict(provenance), report)
