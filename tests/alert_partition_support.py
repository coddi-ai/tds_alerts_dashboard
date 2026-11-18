"""Test support: put alerts where the Alertas views now read them.

The views read ``{week}/file.parquet`` partitions, not ``consolidated_alerts.csv``. These
helpers write a consolidated CSV under a data root and run the real partitioner over it, so a
test exercises the same CSV -> partitions -> view path production does.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.alert_partition_builder import build_client

# Derived by the loader's normalization; never part of the published CSV.
_DERIVED = ("has_telemetry", "has_tribology", "Month")


def write_consolidated_csv(root: Path, client: str, frame: pd.DataFrame) -> Path:
    path = Path(root) / "alerts" / "golden" / client / "consolidated_alerts.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def build_partitions(root: Path, client: str):
    """Run the partitioner over the client's consolidated CSV under ``root``."""
    return build_client(client, root)


def raw_alerts_csv(frame: pd.DataFrame) -> pd.DataFrame:
    """The published-CSV form of a (possibly already normalized) alerts frame."""
    raw = frame.drop(columns=[c for c in _DERIVED if c in frame.columns]).copy()
    if pd.api.types.is_datetime64_any_dtype(raw["Timestamp"]):
        raw["Timestamp"] = raw["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    for required in ("sistema", "subsistema", "componente", "Trigger_type"):
        if required not in raw.columns:
            raw[required] = "Telemetria" if required == "Trigger_type" else None
    return raw


def install_alerts(monkeypatch, tmp_path: Path, frame: pd.DataFrame, client: str = "capstone"):
    """Make the views read ``frame`` for ``client`` (through real partitions)."""
    from dashboard.callbacks import alerts_callbacks

    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    write_consolidated_csv(tmp_path, client, raw_alerts_csv(frame))
    build_partitions(tmp_path, client)
    alerts_callbacks._cached_alert_catalog.cache_clear()
