"""Cumulative-share cutoff shared by every Pareto chart (src/utils/pareto.py)."""

from types import SimpleNamespace

import pandas as pd
import pytest
from flask import Flask

from src.i18n import LANGUAGE_COOKIE
from src.utils import pareto
from src.utils.pareto import rule_unit_count, split_pareto, summary_text, with_others


def _frame(values):
    return pd.DataFrame({"unit": [f"U{i:02d}" for i in range(len(values))], "n": values})


def _split(values, **kwargs):
    return split_pareto(_frame(values), "n", "unit", **kwargs)


def _five_units_hold_81_percent():
    # 30 + 20 + 15 + 10 + 6 = 81 of 100; the other fifteen units share the last 19.
    return [30, 20, 15, 10, 6] + [19 / 15] * 15


def _thirteen_units_hold_80_6_percent():
    # Twelve units reach 74.4%, the thirteenth takes it to 80.6%; seventeen more share 19.4.
    return [6.2] * 13 + [19.4 / 17] * 17


# ---- acceptance scenarios -------------------------------------------------------------------------

def test_five_units_reaching_the_target_give_five_bars_and_one_others():
    split = _split(_five_units_hold_81_percent())
    assert len(split.shown) == 5 and split.others_count == 15 and not split.capped
    assert split.reached_pct == pytest.approx(81.0)


def test_thirteen_needed_units_give_thirteen_bars_not_a_fixed_eight():
    split = _split(_thirteen_units_hold_80_6_percent())
    assert len(split.shown) == 13 and split.others_count == 17 and not split.capped


def test_a_flat_set_stops_at_the_cap_and_reports_the_share_it_reached():
    split = _split([2.5] * 40)
    assert len(split.shown) == 15 and split.others_count == 25 and split.capped
    assert split.reached_pct == pytest.approx(37.5)
    text = summary_text(split, "acciones")
    assert text == "15 de 40 unidades representan el 37% de las acciones."
    assert "80" not in text


def test_the_cumulative_line_always_ends_at_100_with_the_aggregate_included():
    for values in (_five_units_hold_81_percent(), _thirteen_units_hold_80_6_percent(), [2.5] * 40, [79, 21], [5]):
        frame = with_others(_split(values), "n", "unit", "Otras")
        running = frame["n"].cumsum() / frame["n"].sum() * 100
        assert running.iloc[-1] == pytest.approx(100.0)
        assert frame["n"].sum() == pytest.approx(sum(values))


# ---- the rule itself -------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "values, target, cap, bars, capped",
    [
        ([40, 40, 5, 5, 4, 3, 3], 80, 15, 2, False),   # exactly 80% after two units
        ([79, 21], 80, 15, 2, False),                  # the last unit is needed
        ([10] * 10, 80, 15, 8, False),
        ([10] * 10, 80, 5, 5, True),                   # the cap wins over the target
        ([10] * 10, 100, 15, 10, False),
        ([0, 0, 0], 80, 15, 3, False),                 # nothing to rank: no share to reach
        ([], 80, 15, 0, False),
    ],
)
def test_rule_unit_count(values, target, cap, bars, capped):
    shown, _reached, was_capped = rule_unit_count(sorted(values, reverse=True), target, cap)
    assert (shown, was_capped) == (bars, capped)


def test_ties_keep_a_stable_order_and_a_kept_unit_is_never_folded():
    frame = pd.DataFrame({"unit": ["B", "A", "C", "D"], "n": [10, 10, 1, 1]})
    split = split_pareto(frame, "n", "unit", target_pct=80, max_bars=15, keep=["D"])
    assert list(split.shown["unit"]) == ["A", "B", "D"]
    assert list(split.rest["unit"]) == ["C"]
    # The summary still describes the rule, not the selection.
    assert split.rule_units == 2


def test_the_target_and_the_cap_are_parameters():
    values = [30, 25, 20, 15, 10]
    assert len(_split(values, target_pct=50).shown) == 2
    assert len(_split(values, target_pct=90).shown) == 4
    assert len(_split(values, target_pct=90, max_bars=3).shown) == 3


# ---- the sentence, in both languages ---------------------------------------------------------------------------

def _sentence(language, values, noun):
    app = Flask(__name__)
    with app.test_request_context("/", headers={"Cookie": f"{LANGUAGE_COOKIE}={language}"}):
        return summary_text(_split(values), noun)


def test_the_sentence_states_the_finding_in_spanish_and_english():
    values = _five_units_hold_81_percent()
    assert _sentence("es", values, "acciones") == "5 de 20 unidades concentran el 80% de las acciones."
    assert _sentence("en", values, "actions") == "5 of 20 units account for 80% of actions."
    assert _sentence("es", [2.5] * 40, "horas") == "15 de 40 unidades representan el 37% de las horas."
    assert _sentence("en", [2.5] * 40, "hours") == "15 of 40 units represent 37% of hours."


def test_when_every_unit_is_needed_the_sentence_says_100_percent():
    assert _sentence("es", [79, 21], "acciones") == "2 de 2 unidades concentran el 100% de las acciones."
    assert summary_text(_split([]), "x") == ""


# ---- one implementation for every page --------------------------------------------------------------------------

def test_informe_de_confiabilidad_and_alertas_call_the_same_cutoff(monkeypatch):
    from dashboard.components import alerts_charts
    from dashboard.tabs import tab_mantenciones_general as tab

    calls = []

    def recording(*args, **kwargs):
        calls.append(kwargs)
        return pareto.split_pareto(*args, **kwargs)

    for module in (alerts_charts, tab):
        monkeypatch.setattr(module, "split_pareto", recording)
    monkeypatch.setattr(tab, "get_settings", lambda: SimpleNamespace(pareto_target_pct=60.0, pareto_max_bars=4))

    values = [30, 25, 20, 15, 10]
    rows = pd.DataFrame({"equipment": [f"E{i}" for i in range(5)], "value": values})
    actions = pd.DataFrame({"equipment": rows["equipment"], "system_name": "Motor", "count": values})
    tab.create_actions_pareto_chart(actions)
    tab.create_hours_pareto_chart(rows)
    alerts = pd.DataFrame([{"UnitId": f"E{i}", "sistema": "motor"} for i, n in enumerate(values) for _ in range(n)])
    alerts_charts.create_alerts_per_unit_chart(alerts, target_pct=60.0, max_bars=4)

    assert len(calls) == 3
    assert {(call["target_pct"], call["max_bars"]) for call in calls} == {(60.0, 4)}


def test_both_reliability_charts_follow_the_configured_target_and_cap(monkeypatch):
    from dashboard.tabs import tab_mantenciones_general as tab

    monkeypatch.setattr(tab, "get_settings", lambda: SimpleNamespace(pareto_target_pct=50.0, pareto_max_bars=15))
    values = [30, 25, 20, 15, 10]
    rows = pd.DataFrame({"equipment": [f"E{i}" for i in range(5)], "value": values})
    actions = pd.DataFrame({"equipment": rows["equipment"], "system_name": "Motor", "count": values})
    assert list(tab.create_hours_pareto_chart(rows).data[1].x) == ["E0", "E1", "Otras (3)"]
    assert list(tab.create_actions_pareto_chart(actions).data[1].x) == ["E0", "E1", "Otras (3)"]
    assert tab.actions_pareto_summary(actions) == "2 de 5 unidades concentran el 50% de las acciones."
    assert tab.hours_pareto_summary(rows) == "2 de 5 unidades concentran el 50% de las horas."


# ---- the emphasised cutoff point -----------------------------------------------------------------------------

from src.utils.pareto import cutoff_marker, format_pct  # noqa: E402


def _both_charts(values, system_values=None):
    from dashboard.tabs import tab_mantenciones_general as tab

    rows = pd.DataFrame({"equipment": [f"E{i:02d}" for i in range(len(values))], "value": values})
    actions = pd.DataFrame({"equipment": rows["equipment"], "system_name": "Motor", "count": values})
    return tab.create_actions_pareto_chart(actions), tab.create_hours_pareto_chart(rows)


def _marker_parts(figure):
    dots = [trace for trace in figure.data if getattr(trace, "mode", None) == "markers"]
    return list(figure.layout.shapes), dots


def _curve_labels(figure):
    """Texts written above the cumulative line, left to right, with the annotation behind each."""
    notes = [a for a in figure.layout.annotations if a.yref == "y2"]
    return [a.text for a in notes], notes


def test_a_target_reached_normally_is_labelled_80():
    values = [30, 25, 15, 10, 6, 4, 4, 3, 3]            # 30+25+15+10 = 80 exactly
    for figure in _both_charts(values):
        shapes, dots = _marker_parts(figure)
        assert len(shapes) == 1 and len(dots) == 1
        assert _curve_labels(figure)[0][3] == "80%"
        assert list(dots[0].y) == [80.0] and list(dots[0].x) == ["E03"]
        assert shapes[0].line.dash == "dash" and shapes[0].y0 == 0 and shapes[0].y1 == 80.0
        assert shapes[0].x0 == shapes[0].x1 == "E03"


def test_a_binding_cap_is_labelled_with_the_share_actually_reached():
    values = [2.5] * 40                                  # 15 equal units hold 37.5%
    for figure in _both_charts(values):
        shapes, dots = _marker_parts(figure)
        assert _curve_labels(figure)[0][14] == "37%"      # never 80%, never rounded up to 38%
        assert list(dots[0].y) == [37.5]
        assert dots[0].x[0] == "E14" == shapes[0].x0


def test_the_point_sits_at_its_real_height_and_is_labelled_with_the_configured_target(monkeypatch):
    from dashboard.tabs import tab_mantenciones_general as tab

    values = [30, 25, 15, 11, 6, 4, 4, 3, 2]             # four units reach 81%
    for figure in _both_charts(values):
        _, dots = _marker_parts(figure)
        assert list(dots[0].y) == [81.0] and _curve_labels(figure)[0][3] == "80%"
    # The label comes from the configured target, not from a hardcoded string.
    monkeypatch.setattr(tab, "get_settings", lambda: SimpleNamespace(pareto_target_pct=60.0, pareto_max_bars=15))
    for figure in _both_charts(values):
        texts = _curve_labels(figure)[0]
        assert "60%" in texts and "80%" not in texts
    assert format_pct(79.96) == "79%" and format_pct(80.0 - 1e-12) == "80%" and format_pct(100) == "100%"


def test_only_the_threshold_point_is_emphasised_and_the_curve_is_untouched():
    for figure in _both_charts([30, 25, 15, 10, 6, 4, 4, 3, 3]):
        curve = next(trace for trace in figure.data if trace.name == "% acumulado")
        # Four units + "Otras (5)": every point keeps its small marker; only one is emphasised.
        assert curve.mode == "lines+markers" and len(curve.y) == 5 and curve.marker.size == 6
        _, dots = _marker_parts(figure)
        assert len(dots) == 1 and len(dots[0].x) == 1
        assert dots[0].marker.size > 6
        assert dots[0].showlegend is False


def test_both_reliability_charts_draw_the_marker_through_one_function(monkeypatch):
    from dashboard.tabs import tab_mantenciones_general as tab

    calls = []
    real = tab.cutoff_marker
    monkeypatch.setattr(tab, "cutoff_marker", lambda split: calls.append(split) or real(split))
    _both_charts([30, 25, 15, 10, 6, 4, 4, 3, 3])
    assert len(calls) == 2 and calls[0].rule_units == calls[1].rule_units == 4


def test_nothing_to_mark_when_there_is_no_share_to_reach():
    assert cutoff_marker(_split([0, 0, 0])) is None
    assert cutoff_marker(_split([])) is None
    marker = cutoff_marker(_split([79, 21]))
    assert (marker.index, marker.label) == (1, "100%")
    assert _sentence("es", [79, 21], "acciones").startswith("2 de 2 unidades concentran el 100%")


def test_every_point_of_the_curve_states_its_share_with_the_cutoff_point_emphasised():
    values = [30, 25, 15, 11, 6, 4, 4, 3, 2]             # cumulative 30, 55, 70, 81, then "Otras (5)" = 100
    for figure in _both_charts(values):
        texts, notes = _curve_labels(figure)
        assert texts == ["30%", "55%", "70%", "80%", "100%"]    # the 4th point states the target it reached
        sizes = [note.font.size for note in notes]
        assert sizes[3] > max(sizes[:3] + sizes[4:]) and notes[3].font.weight == "bold"
        assert all(note.bgcolor for note in notes)               # white backing: legible over the bars
        _, dots = _marker_parts(figure)
        assert len(dots) == 1 and dots[0].x[0] == notes[3].x


def test_curve_labels_round_down_and_end_at_100():
    for figure in _both_charts([2.5] * 40):                # capped: 15 bars + Otras (25)
        labels = _curve_labels(figure)[0]
        assert len(labels) == 16 and labels[-1] == "100%"
        assert labels[:3] == ["2%", "5%", "7%"]            # 2.5%, 5%, 7.5%: floored, never rounded up
        assert labels[14] == "37%"                          # the cutoff states the share the cap left it at
