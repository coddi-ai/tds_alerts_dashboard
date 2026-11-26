"""S3 side of the General tab's golden files.

    data/general/golden/{client}/fleet_status.parquet
 -> s3://{bucket}/MultiTechnique Alerts/general/golden/{client}/fleet_status.parquet

The key mirrors the local layout under the prefix the app's start-up download mirrors (``MultiTechnique Alerts/`` ->
``data/``), so a started instance receives the file exactly where the dashboard reads it - instead of losing it, which the
mirror does to every local file S3 does not have (see ``src/data/fleet_status.py``).

Rules: the file is uploaded whole with one ``PutObject`` (a reader of the bucket never sees half of it) under its final
key, so a re-run overwrites and never duplicates; a file S3 already holds byte for byte is not uploaded again; nothing is ever
deleted. Only ``scripts/build_fleet_status.py --sync-s3`` calls this - the scheduled run does, a run by hand does not, so a
development machine cannot overwrite the shared bucket by accident.

Bucket: ``FLEET_STATUS_S3_BUCKET`` (falls back to ``BUCKET_NAME``); prefix: ``FLEET_STATUS_S3_PREFIX`` (default
``MultiTechnique Alerts/general/golden``). Credentials are the ones of the other S3 scripts (``ACCESS_KEY`` / ``SECRET_KEY``,
else the task role).
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.data.alert_partition_s3 import S3SyncError, _is_not_found, make_s3_client
from src.data.alert_partition_s3 import S3Config as _PartitionS3Config
from src.data.fleet_status import GOLDEN_FILE, golden_path

logger = logging.getLogger(__name__)

DEFAULT_S3_PREFIX = "MultiTechnique Alerts/general/golden"


@dataclass(frozen=True)
class FleetS3Config:
    bucket: str
    prefix: str = DEFAULT_S3_PREFIX
    region: str = "us-east-1"

    @classmethod
    def from_env(cls) -> "FleetS3Config":
        bucket = os.getenv("FLEET_STATUS_S3_BUCKET") or os.getenv("BUCKET_NAME")
        if not bucket:
            raise S3SyncError("No S3 bucket configured: set FLEET_STATUS_S3_BUCKET (or BUCKET_NAME)")
        return cls(
            bucket=bucket,
            prefix=(os.getenv("FLEET_STATUS_S3_PREFIX") or DEFAULT_S3_PREFIX).strip("/"),
            region=os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        )

    def key(self, client: str) -> str:
        return f"{self.prefix}/{client.lower()}/{GOLDEN_FILE}"


def upload_client(client: str, root=None, config: Optional[FleetS3Config] = None, s3=None) -> str:
    """Put the client's golden file in S3. Returns ``"uploaded"`` or ``"unchanged"``; raises when it cannot
    (no local file, no bucket, S3 refused): the local file is never touched either way."""
    path: Path = golden_path(client, root)
    if not path.is_file():
        raise S3SyncError(f"{client}: there is no local fleet status file to upload ({path})")
    config = config or FleetS3Config.from_env()
    s3 = s3 or make_s3_client(_PartitionS3Config(bucket=config.bucket, region=config.region))
    body = path.read_bytes()
    key = config.key(client)
    md5 = hashlib.md5(body).hexdigest()  # noqa: S324 - compared with S3's ETag, not a security use
    try:
        head = s3.head_object(Bucket=config.bucket, Key=key)
        if str(head.get("ETag", "")).strip('"') == md5 and head.get("ContentLength", len(body)) == len(body):
            return "unchanged"
    except Exception as exc:  # noqa: BLE001 - botocore ClientError, or a stub's
        if not _is_not_found(exc):
            raise
    s3.put_object(
        Bucket=config.bucket, Key=key, Body=body, ContentType="application/vnd.apache.parquet",
        Metadata={"sha256": hashlib.sha256(body).hexdigest()},
    )
    return "uploaded"
