"""Test support: put alerts where the Alertas views now read them.

The views read ``{week}/file.parquet`` partitions, not ``consolidated_alerts.csv``. These
helpers write a consolidated CSV under a data root and run the real partitioner over it, so a
test exercises the same CSV -> partitions -> view path production does.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
from botocore.exceptions import ClientError

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


class FakeS3:
    """In-memory stand-in for the boto3 calls the sync makes."""

    def __init__(self):
        self.objects: dict[str, dict] = {}
        self.fail_put: set[str] = set()
        self.puts: list[str] = []
        self.deleted: list[str] = []

    def _etag(self, body):
        return hashlib.md5(body).hexdigest()

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        fake = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                items = [
                    {"Key": k, "Size": len(v["Body"]), "ETag": f'"{fake._etag(v["Body"])}"'}
                    for k, v in sorted(fake.objects.items()) if k.startswith(Prefix)
                ]
                yield {"Contents": items} if items else {}

        return Paginator()

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        item = self.objects[Key]
        return {"ContentLength": len(item["Body"]), "Metadata": item["Metadata"]}

    def put_object(self, Bucket, Key, Body, Metadata=None, **kwargs):
        if Key in self.fail_put:
            raise ClientError({"Error": {"Code": "503", "Message": "SlowDown"}}, "PutObject")
        self.puts.append(Key)
        self.objects[Key] = {"Body": bytes(Body), "Metadata": dict(Metadata or {})}

    def delete_objects(self, Bucket, Delete):
        for entry in Delete["Objects"]:
            self.objects.pop(entry["Key"], None)
            self.deleted.append(entry["Key"])


def csv_history(client: str, root=None) -> pd.DataFrame:
    """Test oracle: the whole history as the removed whole-CSV loader produced it.

    Reads the consolidated CSV (allowed in a test: it is the source the partitions are built
    from), applies the shared normalization and, for EMIN, the evidence enrichment. The
    partitioned readers must return exactly this for the same snapshot.
    """
    import os

    from src.data import loaders
    from src.data.fast_io import read_csv

    base = Path(root if root is not None else os.getenv("DASHBOARD_DATA_ROOT", "data"))
    path = base / "alerts" / "golden" / client.lower() / "consolidated_alerts.csv"
    frame = loaders._normalize_alerts_frame(read_csv(path))
    if client.lower() == "emin" and not frame.empty:
        frame = loaders._enrich_emin_alerts(frame)
    return frame


def partition_csv(csv_path) -> None:
    """Partition the ``.../alerts/golden/{client}/consolidated_alerts.csv`` that was just written.

    For tests of readers that no longer open the CSV (Campbell AI): they write the CSV the way
    the pipeline publishes it and run the real partitioner over it.
    """
    csv_path = Path(csv_path)
    build_client(csv_path.parent.name, csv_path.parents[3])

