"""Centinela's inspection warnings must load in both ERP views.

The fixture mirrors what the ERP pipeline actually writes for this client
(`data/warnings/centinela/pending.parquet`): `source` arrives as the English
`inspections` while the rest of the record follows the shared contract. An
earlier fixture used a `pautas` value no pipeline emits, so the views passed
their tests while every real Centinela warning failed schema validation.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from plotly.utils import PlotlyJSONEncoder

from config.settings import get_settings
from dashboard.callbacks import integration_avisos_callbacks as callbacks
from dashboard.tabs.tab_integration_seguimiento_avisos import create_layout
from src.data import erp_warning_store as store
from src.data.erp_client_config import load_client_config
from src.data.erp_sap_adapter import SAPAdapter
from src.data.erp_write_operations import approve_and_send

_SUPPORTING_DATA = json.dumps(
    {"raw_signal": [], "threshold_context": {}, "pipeline_severity_hint": "medium"}
)


def _warning_row(warning_id, asset_id, condition_label, severity, generated_at, **overrides) -> dict:
    row = {
        "warning_id": warning_id,
        "client_id": "centinela",
        "asset_id": asset_id,
        "source": "inspections",
        "system": "lubricacion",
        "condition_label": condition_label,
        "severity": severity,
        "title": f"Holder de mangueras sucio en {asset_id}",
        "description": "Puntos de lubricación sucios según inspección bajo pauta.",
        "recommended_action": "Realizar limpieza de los puntos de lubricación.",
        "supporting_data": _SUPPORTING_DATA,
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


class CentinelaWarningsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / "centinela").mkdir()
        # Two pending rows so the list ordering (anormal before alerta) is
        # exercised; timestamps carry microseconds + Z like the pipeline's.
        pd.DataFrame([
            _warning_row("centinela-inspection-1", "BHD011", "alerta", "medium", "2026-05-15T14:01:10.961000Z"),
            _warning_row("centinela-inspection-2", "CLS005", "anormal", "critical", "2026-05-19T04:49:45.131000Z"),
        ]).to_parquet(root / "centinela" / "pending.parquet", index=False)
        # One already sent, to cover the terminal-state rendering and row detail.
        pd.DataFrame([
            _warning_row(
                "centinela-inspection-3",
                "GDR004",
                "alerta",
                "high",
                "2026-05-20T09:15:00.000000Z",
                status="sent",
                validated_by="operador",
                validated_at="2026-05-20T11:15:00.000000Z",
                sent_at="2026-05-20T11:16:00.000000Z",
                erp_reference="9000456789",
            )
        ]).to_parquet(root / "centinela" / "sent.parquet", index=False)
        self.enterContext(patch.object(
            store, "_path", side_effect=lambda client, state: root / client.lower() / f"{state}.parquet"
        ))

    def test_pending_list_and_detail(self):
        cards = callbacks._refresh_pending_list("CENTINELA", None, None)
        self.assertEqual(len(cards), 2)
        self.assertIn("Pautas", json.dumps(cards, cls=PlotlyJSONEncoder))
        # Anormal sorts ahead of alerta regardless of generated_at.
        self.assertEqual(cards[0].id["index"], "centinela-inspection-2")
        warning, state = store.find_by_id("centinela", "centinela-inspection-1")
        self.assertEqual(state, "pending")
        self.assertEqual(warning.source.value, "inspections")
        with patch.object(store, "find_by_id_any_client", return_value=(warning, "centinela", state)):
            detail = callbacks._render_detail(warning.warning_id)
        rendered_detail = json.dumps(detail, cls=PlotlyJSONEncoder, ensure_ascii=False)
        self.assertIn("Lubricación", rendered_detail)
        self.assertIn("Pautas", rendered_detail)

    def test_tracking_table_charts_and_filters(self):
        result = callbacks._refresh(
            "CENTINELA", None, "inspections", "lubricacion", None, None, None, None, None, None
        )
        self.assertEqual(result[:3], ("3", "2", "1"))
        table = result[-1]
        self.assertEqual(len(table), 3)
        self.assertEqual(
            {row["warning_id"] for row in table},
            {"centinela-inspection-1", "centinela-inspection-2", "centinela-inspection-3"},
        )
        self.assertEqual(list(result[7].data[0].labels), ["Lubricación"])
        layout = json.dumps(create_layout(), cls=PlotlyJSONEncoder, ensure_ascii=False)
        self.assertIn('"value": "inspections"', layout)
        self.assertIn('"label": "Pautas"', layout)
        self.assertIn('"value": "lubricacion"', layout)

    def test_table_columns_use_declared_spanish_labels(self):
        table = callbacks._refresh(
            "CENTINELA", None, None, None, None, None, None, None, None, None
        )[-1]
        by_id = {row["warning_id"]: row for row in table}
        self.assertEqual({row["source"] for row in table}, {"Pautas"})
        self.assertEqual({row["system"] for row in table}, {"Lubricación"})
        self.assertEqual(by_id["centinela-inspection-1"]["severity"], "Medio")
        self.assertEqual(by_id["centinela-inspection-2"]["severity"], "Crítico")
        self.assertEqual(by_id["centinela-inspection-3"]["severity"], "Alto")
        self.assertEqual(by_id["centinela-inspection-1"]["condition_label"], "Alerta")
        self.assertEqual(by_id["centinela-inspection-2"]["condition_label"], "Anormal")
        self.assertEqual(by_id["centinela-inspection-1"]["status"], "Pendiente")
        self.assertEqual(by_id["centinela-inspection-3"]["status"], "Enviado")

    def test_row_detail_opens_only_for_terminal_states(self):
        table = callbacks._refresh(
            "CENTINELA", None, None, None, None, None, None, None, None, None
        )[-1]
        sent_row = next(i for i, row in enumerate(table) if row["warning_id"] == "centinela-inspection-3")
        pending_row = next(i for i, row in enumerate(table) if row["warning_id"] == "centinela-inspection-1")
        self.assertEqual(callbacks._row_detail({"row": pending_row, "column": 0}, table), "")
        detail = callbacks._row_detail({"row": sent_row, "column": 0}, table)
        self.assertIn("9000456789", json.dumps(detail, cls=PlotlyJSONEncoder, ensure_ascii=False))

    def test_approve_sends_to_erp_with_the_client_sap_config(self):
        result = approve_and_send(
            "centinela",
            "centinela-inspection-1",
            operator_id="operador",
            title="Holder de mangueras sucio",
            description="Puntos de lubricación sucios.",
            recommended_action="Realizar limpieza.",
            operator_notes=None,
            severity="medium",
        )
        self.assertEqual(result.status, "sent")
        self.assertTrue(result.erp_reference)
        self.assertEqual(store.find_by_id("centinela", "centinela-inspection-1")[1], "sent")

        payload = SAPAdapter(load_client_config("centinela")).build_payload(result)
        self.assertEqual(payload["notificationType"], "M1")
        self.assertEqual(payload["responsibility"]["planningPlant"], "planta_centinela")
        self.assertEqual(payload["responsibility"]["mainWorkCenter"], "work_center_centinela")
        self.assertEqual(payload["technicalObject"]["equipment"], "BHD011")
        self.assertIsNone(payload["technicalObject"]["functionalLocation"])
        self.assertEqual(payload["priority"], "3")

    def test_unknown_source_filter_returns_nothing(self):
        result = callbacks._refresh(
            "CENTINELA", None, "pautas", None, None, None, None, None, None, None
        )
        self.assertEqual(result[:2], ("0", "0"))
        self.assertEqual(result[-1], [])


class ClientSapConfigTests(unittest.TestCase):
    """Every client with warnings on disk needs its SAP config to approve them."""

    def test_each_client_with_warnings_has_a_sap_config(self):
        warnings_dir = get_settings().data_root / "warnings"
        if not warnings_dir.exists():
            self.skipTest(f"No hay datos de avisos en {warnings_dir}")
        for client_dir in sorted(p for p in warnings_dir.iterdir() if p.is_dir()):
            with self.subTest(client=client_dir.name):
                config = load_client_config(client_dir.name)
                self.assertEqual(config.client_id, client_dir.name)
                self.assertIn(config.sap.notification_type, {"M1", "M2", "M3"})


class StoredWarningsMatchSchemaTests(unittest.TestCase):
    """Every warning already on disk must parse with the declared schema.

    This is the check the Centinela regression slipped past: the views can
    only render records that `Warning` accepts, so any enum value the ERP
    pipeline emits has to be declared before the data lands here.
    """

    def test_every_stored_warning_parses(self):
        warnings_dir = get_settings().data_root / "warnings"
        if not warnings_dir.exists():
            self.skipTest(f"No hay datos de avisos en {warnings_dir}")
        checked = 0
        for client_dir in sorted(p for p in warnings_dir.iterdir() if p.is_dir()):
            for state in store.STATES:
                if not (client_dir / f"{state}.parquet").exists():
                    continue
                with self.subTest(client=client_dir.name, state=state):
                    checked += len(store.read_warnings(client_dir.name, state))
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
