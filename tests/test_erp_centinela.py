"""Centinela's inspection warnings must load in both ERP views."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from plotly.utils import PlotlyJSONEncoder

from dashboard.callbacks import integration_avisos_callbacks as callbacks
from dashboard.tabs.tab_integration_seguimiento_avisos import create_layout
from src.data import erp_warning_store as store


class CentinelaWarningsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        pending = root / "centinela" / "pending.parquet"
        pending.parent.mkdir()
        pd.DataFrame([{
            "warning_id": "centinela-inspection-1",
            "client_id": "centinela",
            "asset_id": "TEST-001",
            "source": "pautas",
            "system": "lubricacion",
            "condition_label": "anormal",
            "severity": "critical",
            "title": "Revisar lubricacion",
            "description": "Hallazgo de inspeccion",
            "recommended_action": "Inspeccionar sistema",
            "supporting_data": '{"raw_signal": []}',
            "generated_at": "2026-09-07T12:00:00Z",
            "status": "pending",
            "erp_type": "sap",
        }]).to_parquet(pending, index=False)
        self.enterContext(patch.object(
            store, "_path", side_effect=lambda client, state: root / client.lower() / f"{state}.parquet"
        ))

    def test_pending_list_and_detail(self):
        cards = callbacks._refresh_pending_list("CENTINELA", None, None)
        self.assertEqual(len(cards), 1)
        self.assertIn("Pautas", json.dumps(cards, cls=PlotlyJSONEncoder))
        warning, state = store.find_by_id("centinela", "centinela-inspection-1")
        self.assertEqual(state, "pending")
        with patch.object(store, "find_by_id_any_client", return_value=(warning, "centinela", state)):
            detail = callbacks._render_detail(warning.warning_id)
        self.assertIn("Lubricación", json.dumps(detail, cls=PlotlyJSONEncoder, ensure_ascii=False))

    def test_tracking_table_charts_and_filters(self):
        result = callbacks._refresh(
            "CENTINELA", None, "pautas", "lubricacion", None, None, None, None, None, None
        )
        self.assertEqual(result[:2], ("1", "1"))
        self.assertEqual(len(result[-1]), 1)
        self.assertEqual(result[-1][0]["warning_id"], "centinela-inspection-1")
        self.assertEqual(list(result[7].data[0].labels), ["Lubricación"])
        layout = json.dumps(create_layout(), cls=PlotlyJSONEncoder, ensure_ascii=False)
        self.assertIn('"value": "pautas"', layout)
        self.assertIn('"value": "lubricacion"', layout)


if __name__ == "__main__":
    unittest.main()
