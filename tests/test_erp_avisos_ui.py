"""Conexión ERP redesign: chips, operator gating, pending-list filters, Seguimiento visuals.

Behavior that needs a browser (layout, focus order, scrolling) was checked by hand; these pin the
rules that live in code: the colors defined once, the operator gate on the action buttons, the
ordering and numbers of the bar visuals, the validation-rate empty state and the table pager.
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from plotly.utils import PlotlyJSONEncoder

from dashboard.callbacks import integration_avisos_callbacks as callbacks
from dashboard.components import erp_bars
from dashboard.components.erp_chips import classification_chip, estado_chip, severity_chip
from dashboard.tabs import tab_integration_validacion_avisos as validator
from dashboard.tabs.tab_integration_seguimiento_avisos import ALL_OPTION, PAGE_SIZE, create_layout
from src.data import erp_warning_store as store


def _dump(component) -> str:
    return json.dumps(component, cls=PlotlyJSONEncoder, ensure_ascii=False)


def _style(chip) -> dict:
    return chip.style


class ChipTests(unittest.TestCase):
    def test_severity_chips_use_the_specified_colors_and_always_carry_text(self):
        expected = {
            "medium": ("Medio", "#fef3c7", "#78350f", "#d97706"),
            "high": ("Alto", "#ffedd5", "#9a3412", "#ea580c"),
            "critical": ("Crítico", "#fee2e2", "#991b1b", "#dc2626"),
        }
        for value, (label, bg, text, dot) in expected.items():
            chip = severity_chip(value)
            rendered = _dump(chip)
            self.assertEqual((_style(chip)["background"], _style(chip)["color"]), (bg, text))
            self.assertIn(dot, rendered)
            self.assertIn(label, rendered)

    def test_classification_chip_never_borrows_severity_colors(self):
        anormal, alerta = classification_chip("anormal"), classification_chip("alerta")
        self.assertEqual((_style(anormal)["background"], _style(anormal)["color"]), ("#1e293b", "#ffffff"))
        self.assertEqual(
            (_style(alerta)["background"], _style(alerta)["borderColor"], _style(alerta)["color"]),
            ("#ffffff", "#94a3b8", "#334155"),
        )
        severity_colors = {"#fef3c7", "#ffedd5", "#fee2e2", "#d97706", "#ea580c", "#dc2626"}
        self.assertFalse(severity_colors & set(_style(anormal).values()) | severity_colors & set(_style(alerta).values()))

    def test_estado_chips(self):
        expected = {
            "pending": ("Pendiente", "#dbeafe", "#1e40af"),
            "sent": ("Enviado", "#dcfce7", "#166534"),
            "rejected": ("Rechazado", "#e5e7eb", "#374151"),
        }
        for value, (label, bg, text) in expected.items():
            chip = estado_chip(value)
            self.assertEqual((_style(chip)["background"], _style(chip)["color"]), (bg, text))
            self.assertIn(label, _dump(chip))


def _warning_row(warning_id, asset_id, label, severity, generated_at, **overrides):
    row = {
        "warning_id": warning_id,
        "client_id": "centinela",
        "asset_id": asset_id,
        "source": "inspections",
        "system": "lubricacion",
        "condition_label": label,
        "severity": severity,
        "title": f"Aviso {asset_id}",
        "description": "Descripción.",
        "recommended_action": "Acción.",
        "supporting_data": json.dumps({"raw_signal": [1, 2, 3]}),
        "generated_at": generated_at,
        "status": "pending",
        "validated_by": None,
        "validated_at": None,
        "operator_notes": None,
        "sent_at": None,
        "erp_type": "sap",
        "erp_reference": None,
    }
    row.update(overrides)
    return row


class StoreBackedTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "centinela").mkdir()
        now = datetime.now(timezone.utc)
        iso = lambda delta: (now - delta).strftime("%Y-%m-%dT%H:%M:%S.000000Z")  # noqa: E731
        pd.DataFrame([
            _warning_row("w-1", "BHD011", "alerta", "medium", iso(timedelta(days=3))),
            _warning_row("w-2", "CLS005", "anormal", "critical", iso(timedelta(hours=5))),
            _warning_row("w-3", "BHD020", "anormal", "high", iso(timedelta(days=1))),
        ]).to_parquet(root / "centinela" / "pending.parquet", index=False)
        sent_at = now - timedelta(days=5)
        pd.DataFrame([
            _warning_row(
                "w-4", "GDR004", "alerta", "high", iso(timedelta(days=6)),
                status="sent", validated_by="ana", validated_at=sent_at.isoformat(), erp_reference="9000",
            ),
            _warning_row(
                "w-5", "GDR005", "anormal", "critical", iso(timedelta(days=7)),
                status="sent", validated_by="ana", validated_at=(sent_at - timedelta(days=1)).isoformat(),
                erp_reference="9001",
            ),
        ]).to_parquet(root / "centinela" / "sent.parquet", index=False)
        self.enterContext(patch.object(
            store, "_path", side_effect=lambda client, state: root / client.lower() / f"{state}.parquet"
        ))

    # -- Validación de Avisos -------------------------------------------------
    def test_pending_list_search_and_segment_filter(self):
        ids = lambda cards: [c.id["index"] for c in cards]  # noqa: E731
        self.assertEqual(ids(callbacks._refresh_pending_list("CENTINELA", None, None)), ["w-2", "w-3", "w-1"])
        self.assertEqual(ids(callbacks._refresh_pending_list("CENTINELA", None, None, "bhd")), ["w-3", "w-1"])
        self.assertEqual(ids(callbacks._refresh_pending_list("CENTINELA", None, None, "", "anormal")), ["w-2", "w-3"])
        self.assertEqual(ids(callbacks._refresh_pending_list("CENTINELA", None, None, "", "alerta")), ["w-1"])
        nothing = callbacks._refresh_pending_list("CENTINELA", None, None, "zzz")
        self.assertIn("Ningún aviso coincide", _dump(nothing))

    def test_pending_count_reads_n_de_total_only_while_narrowed(self):
        self.assertEqual(callbacks._refresh_pending_count("CENTINELA", None, None), "3")
        self.assertEqual(callbacks._refresh_pending_count("CENTINELA", None, None, "bhd"), "2 de 3")

    def test_pending_item_is_a_neutral_button_without_a_severity_border(self):
        card = callbacks._refresh_pending_list("CENTINELA", None, None)[0]
        self.assertEqual(card.type, "button")
        self.assertNotRegex(card.className, r"border-(danger|warning|start)")
        rendered = _dump(card)
        self.assertIn("Anormal · Pautas · Lubricación", rendered)
        self.assertIn("hace 5 h", rendered)
        self.assertIn("Crítico", rendered)
        selected = callbacks._refresh_pending_list("CENTINELA", None, "w-2")[0]
        self.assertIn("is-selected", selected.className)

    def test_age_label_switches_to_days_after_two_days(self):
        cards = callbacks._refresh_pending_list("CENTINELA", None, None)
        self.assertIn("hace 24 h", _dump(cards[1]))  # under 48 h still counts hours
        self.assertIn("hace 3 d", _dump(cards[2]))

    def test_operator_gates_both_action_buttons(self):
        feedback, invalid, hidden, approve_off, reject_off, note = callbacks._update_action_bar("", "w-2")
        self.assertIn("Debe indicar el nombre del operador.", _dump(feedback))
        self.assertTrue(invalid and approve_off and reject_off)
        self.assertFalse(hidden)  # the bar is there, its buttons are not usable

        feedback, invalid, hidden, approve_off, reject_off, note = callbacks._update_action_bar("  Ana ", "w-2")
        self.assertIn("Listo", _dump(feedback))
        self.assertFalse(invalid or approve_off or reject_off)
        self.assertIn("Ana", _dump(note))

        # whitespace is not a name
        self.assertTrue(callbacks._update_action_bar("   ", "w-2")[3])
        # no selection: bar hidden
        self.assertTrue(callbacks._update_action_bar("Ana", None)[2])

    def test_title_counter_and_hard_limit(self):
        self.assertEqual(validator.title_counter_text("abc"), "3 / 40")
        self.assertEqual(validator.title_counter_text(None), "0 / 40")
        self.assertEqual(validator.title_counter_class("x" * 40), "erp-counter erp-counter--full")
        self.assertEqual(validator.title_counter_class("x" * 41), "erp-counter erp-counter--over")
        warning, _ = store.find_by_id("centinela", "w-2")
        form = _dump(validator.create_detail_form(warning))
        self.assertIn('"maxLength": 40', form)
        self.assertIn("Generado por IA · solo lectura", form)
        self.assertIn("Evidencia", form)
        self.assertIn("3 registro(s)", form)
        self.assertIn("Sugerido por IA", form)

    def test_reject_requires_a_reason(self):
        warning, _ = store.find_by_id("centinela", "w-1")
        args = ("w-1", "Ana", "t", "d", "a", None, "medium")
        with patch.object(store, "find_by_id_any_client", return_value=(warning, "centinela", "pending")), \
                patch.object(callbacks.dash, "ctx", type("Ctx", (), {"triggered_id": "erp-validator-btn-confirm-reject"})()), \
                patch.object(callbacks, "reject") as reject:
            result = callbacks._handle_action(0, 1, *args, "   ")
            reject.assert_not_called()
            self.assertIn("motivo de rechazo", _dump(result[5]))
            callbacks._handle_action(0, 1, *args, "Falso positivo")
            reject.assert_called_once()

    # -- Seguimiento de Avisos ------------------------------------------------
    def test_all_option_sentinel_means_no_filter(self):
        unfiltered = callbacks._refresh("CENTINELA", None, None, None, None, None, None, None, None, None)
        all_selected = callbacks._refresh(
            "CENTINELA", None, *([ALL_OPTION] * 6), None, None
        )
        self.assertEqual(unfiltered[:5], all_selected[:5])
        self.assertEqual(unfiltered[0], "5")

    def test_kpis_share_captions_and_duration(self):
        result = callbacks._refresh("CENTINELA", None, *([ALL_OPTION] * 6), None, None)
        total, pending, sent, rejected, avg, pending_share, sent_share, rejected_share = result[:8]
        self.assertEqual((total, pending, sent, rejected), ("5", "3", "2", "0"))
        self.assertEqual((pending_share, sent_share, rejected_share), ("60 % del total", "40 % del total", "0 % del total"))
        self.assertEqual(avg, "24 h")  # both sent warnings were validated a day after generation
        self.assertEqual(callbacks._duration_label(None), "–")
        self.assertEqual(callbacks._duration_label(5.2), "5.2 h")
        self.assertEqual(callbacks._duration_label(72), "3.0 d")

    def test_filters_row_has_labels_for_seven_filters_and_a_clear_button(self):
        layout = _dump(create_layout())
        for filter_id in (
            "erp-viewer-filter-source", "erp-viewer-filter-system", "erp-viewer-filter-label",
            "erp-viewer-filter-severity", "erp-viewer-filter-status", "erp-viewer-filter-asset",
        ):
            self.assertIn(f'"htmlFor": "{filter_id}"', layout)
        self.assertIn('"htmlFor": "erp-viewer-filter-dates-start"', layout)
        self.assertIn("Limpiar filtros", layout)
        self.assertEqual(callbacks._clear_filters(1), (ALL_OPTION,) * 6 + (None, None))
        self.assertEqual(layout.count('"className": "erp-kpi"'), 5)
        self.assertNotIn("border-start", layout)

    def test_refresh_outputs_bars_not_pies_and_an_empty_validation_state(self):
        result = callbacks._refresh("CENTINELA", None, *([ALL_OPTION] * 6), None, None)
        lifecycle, _over_time, caption, by_source, by_severity, by_system, validation, rows = result[8:]
        for bars in (by_source, by_severity, by_system):
            self.assertNotIn('"type": "Graph"', _dump(bars))
        # two distinct validation days -> a chart; fewer -> the empty state, never an empty plot
        self.assertIn("Graph", _dump(validation))
        only_pending = callbacks._refresh("CENTINELA", None, *([ALL_OPTION] * 4), "pending", ALL_OPTION, None, None)
        self.assertIn("Aún no hay suficientes datos para mostrar la tendencia", _dump(only_pending[14]))
        self.assertIn("Fuente", _dump(create_layout()))
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["warning_id"], "w-2")  # newest first

    def test_validation_chart_axis_is_calendar_dates(self):
        result = callbacks._refresh("CENTINELA", None, *([ALL_OPTION] * 6), None, None)
        figure = result[14].figure
        self.assertEqual(figure.layout.xaxis.type, "date")
        self.assertEqual(figure.layout.xaxis.tickformat, "%d/%m/%Y")
        for trace in figure.data:
            for x in trace.x:
                self.assertRegex(str(x), r"^\d{4}-\d{2}-\d{2}$")

    def test_table_pages_and_label(self):
        rows = [
            {"warning_id": f"warning-{i:03d}", "asset_id": "A", "source": "S", "system": "Y", "status": "Pendiente",
             "generated_at": "01/01/2026 00:00", "validated_by": "", "erp_reference": "",
             "_raw": {"condition_label": "alerta", "severity": "medium", "status": "pending"}}
            for i in range(PAGE_SIZE + 5)
        ]
        body, label, indicator, prev_off, next_off = callbacks._render_table(rows, 0)
        self.assertEqual(len(body), PAGE_SIZE)
        self.assertEqual(label, f"Mostrando 1–{PAGE_SIZE} de {PAGE_SIZE + 5}")
        self.assertEqual(indicator, "Página 1 de 2")
        self.assertTrue(prev_off)
        self.assertFalse(next_off)
        self.assertIn("warning-…", _dump(body[0]))  # 8 characters + ellipsis
        self.assertIn('"title": "warning-000"', _dump(body[0]))  # full id on hover
        body, label, _, prev_off, next_off = callbacks._render_table(rows, 5)  # clamped to the last page
        self.assertEqual(label, f"Mostrando {PAGE_SIZE + 1}–{PAGE_SIZE + 5} de {PAGE_SIZE + 5}")
        self.assertTrue(next_off and not prev_off)
        self.assertEqual(callbacks._render_table([], 0)[1], "Mostrando 0–0 de 0")

    def test_empty_cells_render_a_dash(self):
        row = {
            "warning_id": "x", "asset_id": "A", "source": "S", "system": "Y", "status": "Pendiente",
            "generated_at": "01/01/2026 00:00", "validated_by": "", "erp_reference": "",
            "_raw": {"condition_label": "alerta", "severity": "medium", "status": "pending"},
        }
        rendered = _dump(callbacks._table_row(row, frozenset()))
        self.assertEqual(rendered.count('"children": "—"'), 2)


class BarVisualTests(unittest.TestCase):
    def test_lifecycle_bar_segments_are_proportional(self):
        bar = erp_bars.lifecycle_bar(pending=50, sent=30, rejected=20)
        widths = [seg.style["width"] for seg in bar.children[0].children]
        self.assertEqual(widths, ["50.0000%", "30.0000%", "20.0000%"])
        legend = _dump(bar.children[1])
        for text in ("Pendiente · 50 (50 %)", "Enviado · 30 (30 %)", "Rechazado · 20 (20 %)"):
            self.assertIn(text, legend)

    def test_severity_bars_order_and_numbers(self):
        rendered = _dump(erp_bars.severity_bars({"medium": 6, "critical": 2, "high": 2}))
        self.assertLess(rendered.index("Crítico"), rendered.index("Alto"))
        self.assertLess(rendered.index("Alto"), rendered.index("Medio"))
        self.assertIn("6 · 60 %", rendered)
        self.assertNotIn("Bajo", rendered)

    def test_source_bars_show_total_and_split(self):
        bars = erp_bars.source_classification_bars([("Aceites", 3, 10), ("Predictivo", 20, 22)])
        rendered = _dump(bars)
        self.assertIn("42 (20 / 22)", rendered)
        self.assertLess(rendered.index("Predictivo"), rendered.index("Aceites"))  # biggest first

    def test_system_bars_sorted_descending_and_complete(self):
        counts = {"Motor": 5, "Frenos": 1, "Rueda": 3}
        rendered = _dump(erp_bars.system_bars(counts))
        self.assertLess(rendered.index("Motor"), rendered.index("Rueda"))
        self.assertLess(rendered.index("Rueda"), rendered.index("Frenos"))
        self.assertIn("5 · 56 %", rendered)

    def test_empty_states(self):
        for empty in (
            erp_bars.severity_bars({}), erp_bars.system_bars({}),
            erp_bars.source_classification_bars([]), erp_bars.lifecycle_bar(0, 0, 0),
        ):
            self.assertIn("Sin avisos", _dump(empty))


if __name__ == "__main__":
    unittest.main()
