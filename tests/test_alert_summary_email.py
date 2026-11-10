"""Correo de resumen de alertas (02_alert_summary_email_template.md): reglas, HTML y paridad con la pagina."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from flask import Flask

from src.mailing import alert_stats as stats
from src.mailing import alert_summary, config, periods, report

SANTIAGO = ZoneInfo("America/Santiago")
BASE = datetime(2026, 7, 10, 12, 0, tzinfo=SANTIAGO)


@pytest.fixture(autouse=True)
def production_schedules(monkeypatch):
    """The email text (cada miércoles, 08:00...) comes from the REAL schedules, not a temporary test one."""
    monkeypatch.setattr(config, "MAILING_SCHEDULES", config.PRODUCTION_SCHEDULES)


def rec(unit, minutes=0, system="Motor", source="Telemetría", multi=False, diagnosis="Diagnóstico", component="Turbo"):
    return stats.AlertRecord(
        unit=unit, when=BASE + timedelta(minutes=minutes), system=system, component=component,
        source="Multitécnica" if multi else source, is_multi=multi, diagnosis=diagnosis,
    )


def records_for(counts: dict, **kwargs):
    out = []
    for unit, n in counts.items():
        out += [rec(unit, minutes=len(out) + i, **kwargs) for i in range(n)]
    return out


WORKED_EXAMPLE = {
    "T_18": 18, "T_15": 11, "T_9": 7, "T_22": 4, "T_4": 3, "T_31": 3,
    "T_12": 2, "T_27": 2, "T_7": 2, **{f"U_{i}": 1 for i in range(10)},
}


# --------------------------------------------------------------------------- unit rows (02.1)


def shape(rows):
    return [(r.label, r.shown, r.cumulative_pct) for r in rows]


def test_worked_example_a_reproduces_exactly():
    rows = stats.unit_rows(records_for(WORKED_EXAMPLE))
    assert sum(WORKED_EXAMPLE.values()) == 62 and len(WORKED_EXAMPLE) == 19
    assert shape(rows) == [
        ("T_18", "18", 29),
        ("T_15", "11", 47),
        ("T_9", "7", 58),
        ("T_22", "4", 65),
        ("T_4", "3", 69),
        ("T_31", "3", 74),
        ("T_7", "2", 77),    # the ticket table lists T_12, T_27, T_7 (input order); its own rule
        ("T_12", "2", 81),   # says natural unit ID order, which is what is implemented. The
        ("T_27", "2", 84),   # percentages are identical either way (equal counts).
        ("10 unidades", "1 c/u", 100),
    ]
    assert stats.units_for_concentration(stats.ranked_units(records_for(WORKED_EXAMPLE))) == 8


CASE_B = {"CA-81": 3, "CA-92": 3, "CA-93": 3, "CA-88": 3, "CA-89": 2, "CA-91": 2,
          "CA-1": 1, "CA-2": 1, "CA-3": 1, "CA-4": 1}


def test_worked_example_b_reproduces_exactly():
    rows = stats.unit_rows(records_for(CASE_B))
    assert shape(rows) == [
        ("CA-81", "3", 15), ("CA-88", "3", 30), ("CA-92", "3", 45), ("CA-93", "3", 60),
        ("CA-89", "2", 70), ("CA-91", "2", 80),
        ("4 unidades", "1 c/u", 100),
    ]
    assert stats.units_for_concentration(stats.ranked_units(records_for(CASE_B))) == 6


def test_a_tie_group_straddling_the_80_percent_boundary_is_never_split():
    # 10 alerts: 4+3 = 70%, the 3rd unit reaches 90% (X=3) and ties with the 4th and 5th at 1.
    counts = {"A": 4, "B": 3, "C": 1, "D": 1, "E": 1, "F": 0}
    counts.pop("F")
    rows = stats.unit_rows(records_for(counts))
    assert [r.label for r in rows] == ["A", "B", "C", "D", "E"]  # C, D, E tie at the boundary: all individual
    assert not stats.has_compressed_rows(rows)
    # the same boundary tie with a lower tail below it: the tail compresses, the tie does not
    rows = stats.unit_rows(records_for({"A": 8, "B": 5, "C": 5, "D": 5, "E": 1, "F": 1, "G": 1, "H": 1}))
    assert [r.label for r in rows] == ["A", "B", "C", "D", "4 unidades"]


def test_the_boundary_unit_ties_with_units_just_beyond_it():
    # 24 alerts, 80% = 19.2: A, B, C, D reach 21 (X = 4) but E has D's count: E stays individual too.
    rows = stats.unit_rows(records_for({"A": 12, "B": 3, "C": 3, "D": 3, "E": 3}))
    assert [r.label for r in rows] == ["A", "B", "C", "D", "E"] and not stats.has_compressed_rows(rows)


def test_every_unit_needed_for_80_percent_has_its_own_row_and_only_the_rest_compresses():
    recs = records_for(WORKED_EXAMPLE)
    ranked = stats.ranked_units(recs)
    needed = stats.units_for_concentration(ranked)
    individual = {r.label for r in stats.unit_rows(recs) if r.units == 1}
    assert {unit for unit, _ in ranked[:needed]} <= individual


def test_tail_groups_of_one_two_three_and_more_than_three_units():
    top = {"T1": 40, "T2": 30, "T3": 20}  # three clear leaders: 80% is reached inside them
    one = stats.unit_rows(records_for({**top, "B": 1}))[-1]
    assert (one.label, one.shown) == ("B", "1")  # tail of 1: unit ID, plain number
    two = stats.unit_rows(records_for({**top, "CA-91": 1, "CA-89": 1}))[-1]
    assert (two.label, two.shown) == ("CA-89, CA-91", "1 c/u")
    three = stats.unit_rows(records_for({**top, "CA-9": 1, "CA-81": 1, "CA-10": 1}))[-1]
    assert three.label == "CA-9, CA-10, CA-81"  # natural order
    four = stats.unit_rows(records_for({**top, "A": 1, "B": 1, "C": 1, "D": 1}))[-1]
    assert (four.label, four.shown) == ("4 unidades", "1 c/u")
    # tail groups by identical count, one row per group
    rows = stats.unit_rows(records_for({**top, "B": 2, "C": 2, "D": 1, "E": 1}))
    assert [(r.label, r.shown) for r in rows[3:]] == [("B, C", "2 c/u"), ("D, E", "1 c/u")]


def test_with_three_units_or_fewer_all_are_named_so_all_are_individual():
    rows = stats.unit_rows(records_for({"CA-1": 40, "CA-2": 1, "CA-3": 1}))
    assert [r.label for r in rows] == ["CA-1", "CA-2", "CA-3"]


def test_individual_units_with_equal_counts_are_ordered_by_natural_id():
    rows = stats.unit_rows(records_for({"CA-81": 3, "CA-9": 3, "CA-10": 3}))
    assert [r.label for r in rows] == ["CA-9", "CA-10", "CA-81"]


def test_bar_uses_the_per_unit_count_not_the_group_total():
    rows = stats.unit_rows(records_for({"A": 20, "B": 4, "C": 4, "D": 4, "E": 4}))
    assert rows[0].bar_pct == 100 and rows[1].bar_pct == 20


def test_single_unit_case():
    rows = stats.unit_rows(records_for({"CA-1": 7}))
    assert [(r.label, r.shown, r.bar_pct, r.cumulative_pct) for r in rows] == [("CA-1", "7", 100, 100)]
    assert not stats.has_compressed_rows(rows)


def test_more_than_15_rows_merge_into_a_gray_otras_row():
    counts = {f"U_{i:02d}": 40 - i for i in range(20)}  # 20 distinct counts: every unit individual
    rows = stats.unit_rows(records_for(counts))
    assert len(rows) == 16 and not any(r.is_other for r in rows[:15])
    other = rows[-1]
    assert other.is_other and other.label == "Otras (5)"
    assert other.count == sum(40 - i for i in range(15, 20)) and other.shown == str(other.count)
    assert other.bar_pct == min(100, round(100 * other.count / 40))
    assert other.cumulative_pct == 100


def test_a_tie_group_at_the_row_cut_goes_whole_into_otras():
    # 14 distinct leaders, then 6 units tied at 80 that are needed for the 80% (so individual):
    # the 15-row cut falls inside the tie, so the whole tie moves into `Otras`, tail included.
    counts = {f"A_{i:02d}": 100 - i for i in range(14)}
    counts.update({f"T_{i}": 80 for i in range(6)})
    counts.update({f"Z_{i}": 1 for i in range(2)})
    recs = records_for(counts)
    assert stats.units_for_concentration(stats.ranked_units(recs)) == 16  # X lands inside the tie
    rows = stats.unit_rows(recs)
    labels = [r.label for r in rows]
    assert labels[:14] == [f"A_{i:02d}" for i in range(14)]
    assert not any(label.startswith("T_") for label in labels)  # not one tied unit stays visible
    assert len(rows) == 15 and rows[14].is_other and rows[14].label == "Otras (8)"
    assert rows[14].count == 6 * 80 + 2 and rows[14].bar_pct == 100


def test_otras_bar_is_capped_at_100_percent():
    counts = {f"U_{i:02d}": 100 - i for i in range(15)}
    counts.update({f"V_{i}": 60 - i for i in range(10)})
    other = stats.unit_rows(records_for(counts))[-1]
    assert other.is_other and other.bar_pct == 100


def test_note_only_when_a_row_is_compressed():
    assert stats.has_compressed_rows(stats.unit_rows(records_for(WORKED_EXAMPLE)))
    assert not stats.has_compressed_rows(stats.unit_rows(records_for({"A": 3, "B": 2})))
    merged_only = stats.unit_rows(records_for({f"U_{i:02d}": 40 - i for i in range(20)}))
    assert not stats.has_compressed_rows(merged_only)  # `Otras` is not a `c/u` row


def test_cumulative_percentages_round_half_up_and_end_at_100():
    # 40 of 62 = 64.5 rounds UP to 65 (banker's rounding would say 64).
    assert stats.round_half_up_pct(40, 62) == 65
    assert stats.round_half_up_pct(1, 3) == 33 and stats.round_half_up_pct(2, 3) == 67
    for counts in ({"A": 1, "B": 1, "C": 1}, {"A": 5, "B": 3, "C": 3, "D": 1}, WORKED_EXAMPLE, CASE_B):
        rows = stats.unit_rows(records_for(counts))
        assert rows[-1].cumulative_pct == 100
        assert [r.cumulative_pct for r in rows] == sorted(r.cumulative_pct for r in rows)


def test_no_records_no_rows():
    assert stats.unit_rows([]) == [] and stats.system_rows([]) == []


# --------------------------------------------------------------------------- systems


def test_system_percentages_add_up_to_100_and_drift_goes_to_the_largest():
    recs = records_for({"A": 1}, system="Motor") + records_for({"B": 1}, system="Frenos") + records_for({"C": 1}, system="Dirección")
    rows = stats.system_rows(recs)
    assert sum(r.pct for r in rows) == 100  # 33+33+33 would be 99
    assert [r.name for r in rows] == ["Dirección", "Frenos", "Motor"]  # tie -> alphabetical
    assert rows[0].pct == 34


def test_system_rows_are_ordered_by_count_with_proportional_bars():
    recs = records_for({"A": 6}, system="Motor") + records_for({"B": 3}, system="Frenos")
    rows = stats.system_rows(recs)
    assert [(r.name, r.count, r.bar_pct, r.pct) for r in rows] == [("Motor", 6, 100, 67), ("Frenos", 3, 50, 33)]


# --------------------------------------------------------------------------- 80% sentence


def test_sentence_case_b_names_every_tied_top_unit():
    assert stats.summary_sentence(records_for(CASE_B)) == (
        "6 de 10 unidades concentran el 80% de las alertas. "
        "Analice las unidades con más alertas: CA-81, CA-88, CA-92 y CA-93."
    )


def test_sentence_with_three_distinct_top_units():
    recs = records_for({"CA-1": 10, "CA-2": 6, "CA-3": 2, "CA-4": 1, "CA-5": 1})
    assert stats.summary_sentence(recs) == (
        "2 de 5 unidades concentran el 80% de las alertas. "
        "Analice las unidades con más alertas: CA-1, CA-2 y CA-3."
    )


def test_a_tie_across_the_third_position_names_all_tied_units():
    recs = records_for({"CA-1": 9, "CA-2": 5, "CA-3": 5, "CA-4": 5, "CA-5": 1})
    assert stats.summary_sentence(recs).endswith("más alertas: CA-1, CA-2, CA-3 y CA-4.")


def test_up_to_five_names_then_y_n_mas():
    five = stats.summary_sentence(records_for({f"CA-{i}": 4 for i in range(1, 6)}))
    assert five.endswith("más alertas: CA-1, CA-2, CA-3, CA-4 y CA-5.")
    seven = stats.summary_sentence(records_for({f"CA-{i}": 4 for i in range(1, 8)}))
    assert seven.endswith("más alertas: CA-1, CA-2, CA-3, CA-4, CA-5 y 2 más.")
    ten = stats.summary_sentence(records_for({f"CA-{i}": 4 for i in (10, 9, 2, 1, 30, 3, 4, 5, 6, 7)}))
    assert ten.endswith("CA-1, CA-2, CA-3, CA-4, CA-5 y 5 más.")  # natural unit ID order


def test_when_one_unit_reaches_80_the_verb_is_singular():
    assert stats.summary_sentence(records_for({"CA-1": 9, "CA-2": 1})).startswith("1 de 2 unidades concentra el 80%")


def test_sentence_with_two_units_and_with_a_single_unit():
    assert stats.summary_sentence(records_for({"A": 3, "B": 1})).endswith("más alertas: A y B.")
    assert stats.summary_sentence(records_for({"CA-7": 4})) == "Analice la unidad CA-7."


def test_every_unit_named_in_the_sentence_has_its_own_row():
    cases = [CASE_B, WORKED_EXAMPLE, {"CA-1": 20, **{f"U_{i}": 1 for i in range(5)}},
             {f"CA-{i}": 4 for i in range(1, 6)}, {"A": 9, "B": 5, "C": 5, "D": 5, "E": 1}]
    for counts in cases:
        recs = records_for(counts)
        named = stats.top_units(stats.ranked_units(recs))[: stats.MAX_NAMED_UNITS]
        individual = {r.label for r in stats.unit_rows(recs) if r.units == 1 and not r.is_other}
        assert set(named) <= individual, counts


def test_headline_singular_and_plural():
    assert stats.headline(1, 1) == "1 alerta en 1 unidad"
    assert stats.headline(62, 19) == "62 alertas en 19 unidades"
    assert stats.headline(2, 1) == "2 alertas en 1 unidad"


def test_forbidden_words_never_appear():
    for recs in (records_for(WORKED_EXAMPLE), records_for({"A": 1}), records_for({"A": 2, "B": 1})):
        sentence = stats.summary_sentence(recs)
        assert "Priorice" not in sentence and "mantenimiento" not in sentence.lower()
        assert "Analice" in sentence


# --------------------------------------------------------------------------- featured


def test_featured_ranking_multi_first_then_unit_activity_then_recency_max_five():
    recs = (
        records_for({"BUSY": 8}) +                        # telemetry, busiest unit
        [rec("QUIET", minutes=500, multi=True)] +         # multi, quiet unit, most recent
        [rec("MID", minutes=1, multi=True), rec("MID", minutes=2, multi=True)] +
        [rec("BUSY", minutes=900)]
    )
    top = stats.featured_alerts(recs)
    assert len(top) == 5
    assert [r.unit for r in top[:3]] == ["MID", "MID", "QUIET"]  # multi first; MID is busier
    assert top[3].unit == top[4].unit == "BUSY"
    assert top[3].when > top[4].when  # then most recent


def test_featured_with_fewer_than_five_alerts():
    assert len(stats.featured_alerts(records_for({"A": 2}))) == 2


def test_diagnosis_truncates_at_a_word_boundary_and_cleans_markdown():
    long = "palabra " * 40
    out = stats.truncate_diagnosis(long)
    assert out.endswith("…") and len(out) <= 120 and not out[:-1].endswith(" ")
    assert out[:-1] == out[:-1].rstrip() and out.count("palabra") == out[:-1].count("palabra")
    assert stats.truncate_diagnosis("** BULL-027 presenta **113-299-8**") == "BULL-027 presenta 113-299-8"
    assert stats.truncate_diagnosis("corto") == "corto"
    assert stats.truncate_diagnosis("") == "—" and stats.truncate_diagnosis(None) == "—"


# --------------------------------------------------------------------------- rendering


def render(records, client="capstone", send=date(2026, 11, 11), url="https://dash.example/alertas"):
    schedule = config.get_schedule(client)
    period = periods.compute_period(schedule["frequency"], send)
    return alert_summary.render_alert_summary(client, schedule, period, send, records, url)


def test_weekly_email_content():
    content = render(records_for(WORKED_EXAMPLE))
    html = content.html
    assert content.subject == "[CODDI] Monitoreo de Alertas 11/11/2026"
    for text in (
        "CODDI · MONITOREO DE ALERTAS", "Resumen Semanal de Alertas",
        "Flota Capstone · Período 04/11/2026 – 10/11/2026",
        "62 alertas en 19 unidades", "últimos 7 días", "Total de Alertas", "Unidades Afectadas",
        "Sistema Principal", "Alertas por Unidad", "Alertas por Sistema", "Alertas Destacadas del Período",
        "Ver Alertas en el Dashboard", "10 unidades", "1 c/u",
        "c/u = cada una. Las unidades con la misma cantidad de alertas se agrupan en una sola fila.",
        "Mostrando 5 de 62 alertas del período. Se priorizan las alertas multitécnicas y las unidades con más alertas.",
        "Este resumen se genera automáticamente cada miércoles a las 08:00 (hora de Chile) y cubre las alertas "
        "registradas entre el 04/11/2026 y el 10/11/2026.",
        "Coddi · coddi.ai",
    ):
        assert text in html, text
    assert content.meta == {
        "report": "alert_summary", "variant": "weekly", "total_alerts": 62, "affected_units": 19,
    }


def test_daily_email_variant():
    content = render(records_for({"BULL-1": 2}), client="emin", send=date(2026, 11, 10))
    assert "Resumen Diario de Alertas" in content.html and "Resumen Semanal" not in content.html
    assert "Flota Emin · Período 09/11/2026<" in content.html
    assert "último día" in content.html
    assert "todos los días a las 08:00 (hora de Chile) y cubre las alertas registradas el 09/11/2026." in content.html
    assert "2 alertas en 1 unidad" in content.html and "Analice la unidad BULL-1." in content.html
    assert content.meta["variant"] == "daily"


def test_system_principal_tile_shows_the_alphabetical_winner_on_a_tie():
    recs = records_for({"A": 2}, system="Motor") + records_for({"B": 2}, system="Frenos")
    html = render(recs).html
    assert re.search(r"Sistema Principal.*?>Frenos<.*?2 alertas · 50%", html, re.S)


def test_empty_period_sends_the_zero_alerts_variant():
    content = render([])
    assert "0 alertas en 0 unidades" in content.html
    assert "Sin alertas registradas en el período." in content.html
    for absent in ("Alertas por Unidad", "Alertas por Sistema", "Alertas Destacadas", "Total de Alertas"):
        assert absent not in content.html
    assert "Ver Alertas en el Dashboard" in content.html and content.meta["total_alerts"] == 0


def test_button_only_when_the_dashboard_url_is_configured():
    assert "Ver Alertas en el Dashboard" not in render(records_for({"A": 1}), url=None).html
    assert 'href="https://dash.example/alertas"' in render(records_for({"A": 1})).html


def test_alert_text_is_escaped():
    evil = '<script>alert(1)</script> & "quotes"'
    html = render([rec("A", diagnosis=evil, component="<b>x</b>", system="<i>S</i>")]).html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<b>x</b>" not in html and "<i>S</i>" not in html


def test_email_is_email_safe_html():
    html = render(records_for(WORKED_EXAMPLE) + [rec("M", multi=True)]).html
    for forbidden in ("display:flex", "display: flex", "display:grid", "<svg", "<script", "<link", "@import",
                      "<style", "@font-face", "javascript:", "Priorice", "mantenimiento", "border-left"):
        assert forbidden not in html, forbidden
    assert "Arial,Helvetica,sans-serif" in html and 'width="640"' in html and "max-width:640px" in html
    assert "#1d4ed8" in html and 'height="6"' in html  # solid blue top bar
    assert "http://" not in html and "src=" not in html  # no external assets


def test_chips_carry_their_source_name_as_text():
    html = render(records_for({"A": 2}, source="Telemetría") + [rec("B", multi=True), rec("C", source="Tribología")]).html
    for label, bg, fg in (("Telemetría", "#dbeafe", "#1e40af"), ("Tribología", "#fef3c7", "#92400e"),
                          ("Multitécnica", "#ede9fe", "#5b21b6")):
        assert re.search(rf"background-color:{bg};color:{fg};\">{label}<", html), label


def test_unit_bars_are_navy_and_otras_is_gray():
    html = render(records_for({f"U_{i:02d}": 40 - i for i in range(20)})).html
    unit_section = html.split(">Alertas por Unidad<")[1].split(">Alertas por Sistema<")[0]
    assert "#2f5675" in unit_section and "#1d4ed8" not in unit_section  # not the KPI/button blue
    assert "#94a3b8" in unit_section  # the `Otras` row


def test_system_bar_colors_follow_the_dashboard_palette():
    from dashboard.components.alerts_charts import SISTEMA_COLORS

    names = ["Motor", "Tren de fuerza", "Frenos", "Dirección", "Sistema Raro", "Otro Más"]
    recs = sum((records_for({f"U{i}": 6 - i}, system=name) for i, name in enumerate(names)), [])
    colors = alert_summary.system_colors(names)
    for known in ("Motor", "Tren de fuerza", "Frenos", "Dirección"):
        assert colors[known] == SISTEMA_COLORS[known]
    # unknown systems cycle the qualitative palette instead of all sharing one gray
    assert colors["Sistema Raro"] != colors["Otro Más"]
    html = render(recs).html
    for color in colors.values():
        assert color in html


def test_at_most_fifteen_unit_rows_plus_otras_in_the_html():
    html = render(records_for({f"U_{i}": 40 - i for i in range(30)})).html
    assert "Otras (15)" in html
    unit_section = html.split(">Alertas por Unidad<")[1].split(">Alertas por Sistema<")[0]
    assert unit_section.count('width="26%"') == 16  # one label cell per row: 15 groups + Otras


def test_missing_system_or_component_shows_a_dash():
    html = render([rec("A", system="", component="")]).html
    assert html.count("—") >= 2


# --------------------------------------------------------------------------- data + page parity


def _frame(rows):
    frame = pd.DataFrame(rows)
    frame["Timestamp"] = pd.to_datetime(frame["Timestamp"])
    frame["has_telemetry"] = True
    frame["has_tribology"] = False
    frame["Trigger_type"] = frame.get("Trigger_type", "Telemetria")
    frame["Trigger_Var"] = "imp_lb_psi"
    frame["componente"] = "engine"
    frame["subsistema"] = "admission"
    frame["FusionID"] = [f"F-{i}" for i in range(len(frame))]
    frame["mensaje_ia"] = "Diagnóstico: Presión anómala en admisión."
    frame["mensaje_ia_eng"] = "Diagnosis: Abnormal intake pressure."
    return frame


@pytest.fixture
def page_alerts(monkeypatch):
    """Alertas con timestamps UTC-naive; las del borde cruzan la medianoche UTC <-> Chile."""
    frame = _frame([
        {"UnitId": "CA-1", "sistema": "motor", "Timestamp": "2026-07-10 16:00"},
        {"UnitId": "CA-1", "sistema": "motor", "Timestamp": "2026-07-11 16:00"},
        {"UnitId": "CA-2", "sistema": "motor", "Timestamp": "2026-07-12 16:00", "Trigger_type": "Mixto"},
        {"UnitId": "CA-2", "sistema": "frenos", "Timestamp": "2026-07-20 16:00"},
        {"UnitId": "CA-3", "sistema": "motor", "Timestamp": "2026-07-12 16:00"},
        # 22:00 del 15/07 en Chile (invierno, UTC-4) = 02:00 UTC del 16/07: cae DENTRO del 15.
        {"UnitId": "CA-3", "sistema": "frenos", "Timestamp": "2026-07-16 02:00"},
        # 23:00 del 15/07 UTC = 19:00 del 15/07 Chile: tambien dentro.
        {"UnitId": "CA-4", "sistema": "motor", "Timestamp": "2026-07-15 23:00"},
        # 04:30 UTC del 16/07 = 00:30 del 16/07 Chile: FUERA del rango que termina el 15.
        {"UnitId": "CA-4", "sistema": "motor", "Timestamp": "2026-07-16 04:30"},
    ])
    from dashboard.callbacks import alerts_callbacks
    from src.data import loaders

    monkeypatch.setattr(loaders, "load_alerts_data", lambda client: frame)
    monkeypatch.setattr(alerts_callbacks, "load_alerts_data", lambda client: frame)
    return frame


def test_numbers_equal_the_alertas_page_for_the_same_client_and_range(page_alerts):
    from dashboard.callbacks import alerts_callbacks
    from dashboard.components.alerts_charts import create_alerts_per_unit_chart
    from dashboard.components.alerts_report import alert_summary as page_summary
    from dashboard.components.alerts_report import filter_prepared_rows, prepare_alert_rows

    start, end = date(2026, 7, 1), date(2026, 7, 15)
    records = alert_summary.load_period_records("capstone", start, end)

    # 1. the page's own caption for that range
    caption = alerts_callbacks.update_general_tab("capstone", start.isoformat(), end.isoformat(), {})[5]
    assert f"Mostrando {len(records)} alertas de {len(stats.unit_counts(records))} unidades" in caption
    assert len(records) == 6  # the 20/07 and the 16/07 00:30 (Chile) alert is out; the 22:00 and 19:00 ones are in

    # 2. the page's summary KPIs
    page = page_summary(filter_prepared_rows(prepare_alert_rows(page_alerts), start_date=start, end_date=end))
    assert (page["total"], page["units"]) == (len(records), len(stats.unit_counts(records)))

    # 3. the page's per-unit chart (bars stacked by system: sum them per unit)
    figure = create_alerts_per_unit_chart(filter_prepared_rows(prepare_alert_rows(page_alerts), start_date=start, end_date=end))
    chart: dict = {}
    for trace in figure.data:
        if trace.type == "bar":
            for unit, value in zip(trace.x, trace.y):
                chart[unit] = chart.get(unit, 0) + int(value)
    # The page folds its small units into "Otras (n)" at 80% (the email does not, per its own
    # spec): the units the page does draw must match, and the totals must be equal.
    mine = stats.unit_counts(records)
    drawn = {unit: value for unit, value in chart.items() if not str(unit).startswith("Otras")}
    assert drawn and all(mine[unit] == value for unit, value in drawn.items())
    assert sum(chart.values()) == sum(mine.values())

    # 4. per-system counts equal the page's system labels
    page_systems = filter_prepared_rows(prepare_alert_rows(page_alerts), start_date=start, end_date=end)["system_display"].value_counts().to_dict()
    assert {r.name: r.count for r in stats.system_rows(records)} == page_systems


def test_records_use_chile_dates_and_flag_multitecnica(page_alerts):
    records = alert_summary.load_period_records("capstone", date(2026, 7, 12), date(2026, 7, 12))
    assert {r.unit for r in records} == {"CA-2", "CA-3"}
    multi = next(r for r in records if r.unit == "CA-2")
    assert multi.is_multi and multi.source == "Multitécnica"
    assert multi.when.tzinfo is not None and multi.when.utcoffset() == timedelta(hours=-4)
    assert multi.when.hour == 12  # 16:00 UTC


def test_email_stays_in_spanish_whatever_the_browser_language(page_alerts):
    app = Flask(__name__)
    start, end = date(2026, 7, 1), date(2026, 7, 15)
    plain = alert_summary.load_period_records("capstone", start, end)
    with app.test_request_context(headers={"Cookie": "app_language=en"}):
        english_browser = alert_summary.load_period_records("capstone", start, end)
    assert english_browser == plain
    assert all("Presión anómala" in r.diagnosis for r in plain)


def test_builder_end_to_end_matches_the_service_contract(page_alerts, monkeypatch):
    monkeypatch.setattr(config, "_DOTENV_LOADED", True)
    monkeypatch.setattr(config, "DASHBOARD_URL", "https://dash.example/app/")
    request = report.ReportRequest("capstone", "weekly", date(2026, 7, 9), date(2026, 7, 15), date(2026, 7, 16))
    content = alert_summary.build_alert_summary(request)
    assert content.subject == "[CODDI] Monitoreo de Alertas 16/07/2026"
    assert content.meta["total_alerts"] == 6 and content.meta["affected_units"] == 4
    assert "6 alertas en 4 unidades" in content.html and "https://dash.example/app/monitoring/alerts" in content.html
    # same inputs, same email: what the preview shows is what the send delivers
    assert alert_summary.build_alert_summary(request).html == content.html


def test_builder_for_an_unconfigured_client_is_refused():
    from src.mailing.errors import MailingError

    request = report.ReportRequest("cda", "weekly", date(2026, 7, 9), date(2026, 7, 15), date(2026, 7, 16))
    with pytest.raises(MailingError):
        alert_summary.build_alert_summary(request)


def test_builder_with_no_alert_file_yields_the_empty_email(monkeypatch):
    from src.data import loaders

    monkeypatch.setattr(loaders, "load_alerts_data", lambda client: pd.DataFrame())
    request = report.ReportRequest("emin", "daily", date(2026, 7, 9), date(2026, 7, 9), date(2026, 7, 10))
    assert "Sin alertas registradas en el período." in alert_summary.build_alert_summary(request).html


def test_button_points_at_the_alertas_page_under_the_dashboard_url(monkeypatch):
    assert alert_summary.get_dashboard_alerts_url() == "https://poc.tds.coddi.ai/alerts-dashboard/monitoring/alerts"
    monkeypatch.setattr(config, "DASHBOARD_URL", "")
    assert alert_summary.get_dashboard_alerts_url() is None


def test_alert_summary_is_the_default_registered_builder():
    report.unregister_report_builder(report.ALERT_SUMMARY)
    assert report.get_report_builder() is alert_summary.build_alert_summary
