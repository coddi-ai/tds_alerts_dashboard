"""Test support: put alert telemetry where the readers now find it.

The dashboard and the Campbell AI assistant read ``{week}/telemetry.parquet`` partitions, not the
wide telemetry CSV. These helpers write that CSV under a data root and run the real partitioner
over it, so a test exercises the same CSV -> partitions -> reader path production does.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data import telemetry_partition_builder as builder

# The published name of the per-alert telemetry CSV (only the partitioner reads it).
SOURCE_FILE = "alerts_detail_wide_with_gps.csv"


def write_source_csv(root: Path, client: str, frame: pd.DataFrame, name: str = SOURCE_FILE) -> Path:
    path = Path(root) / "telemetry" / "golden" / client / name
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def alerts_for(frame: pd.DataFrame) -> pd.DataFrame:
    """A minimal ``consolidated_alerts.csv`` with one alert per telemetry (AlertID, Unit): the
    alert's ``TelemetryID`` is the telemetry's ``AlertID`` and its ``Timestamp`` is the
    telemetry's ``Alert_TimeStart`` (or, without it, the first sample)."""
    when = "Alert_TimeStart" if "Alert_TimeStart" in frame.columns else "TimeStart"
    rows = []
    for number, ((alert, unit), chunk) in enumerate(frame.groupby(["AlertID", "Unit"], sort=False)):
        rows.append({
            "FusionID": f"F-{alert}-{1_000_000_000 + number}",
            "TelemetryID": alert,
            "UnitId": unit,
            "Timestamp": str(chunk[when].dropna().iloc[0]) if chunk[when].notna().any() else None,
        })
    return pd.DataFrame(rows)


def install_telemetry(
    root: Path,
    client: str,
    frame: pd.DataFrame,
    *,
    alerts: pd.DataFrame | None = None,
):
    """Write ``frame`` as the client's telemetry CSV (and ``alerts``, or the minimal alerts the
    telemetry implies, as ``consolidated_alerts.csv`` when none exists) and partition it."""
    write_source_csv(root, client, frame)
    alerts_csv = Path(root) / "alerts" / "golden" / client / "consolidated_alerts.csv"
    if alerts is not None or not alerts_csv.exists():
        alerts_csv.parent.mkdir(parents=True, exist_ok=True)
        (alerts if alerts is not None else alerts_for(frame)).to_csv(alerts_csv, index=False)
    return builder.build_client(client, SOURCE_FILE, root)
