"""S3 side of the partitioned alert storage.

Keys mirror the local layout under the bucket's medallion prefix, so the existing download
(``MultiTechnique Alerts/`` -> ``data/``) lands them exactly where the dashboard reads::

    s3://{bucket}/{prefix}/{client}/{week}/file.parquet
    default prefix: "MultiTechnique Alerts/alerts/golden"

The sync is **comparison based and stateless**, which is what makes it re-runnable:

* every local partition is compared with what S3 holds (size + ETag, or the ``sha256``
  object metadata when the ETag is not an MD5, e.g. with KMS);
* only partitions that are missing or different are uploaded, each with one ``PutObject``
  (an object appears whole or not at all — a reader of the bucket never sees half a file) under
  its final key, so a re-run overwrites and never duplicates;
* a failed upload is recorded and the run reports it, but local files stay as they are and the
  next run finds the same partition still different and retries it — no pending list to lose;
* keys under the client prefix that follow the partition layout but are no longer produced
  locally are deleted (only after every upload succeeded); anything else in the folder
  (``consolidated_alerts.csv``, ``backtest/``, ``state/``) is never touched.

Sequencing guard: the weekly run refuses to sync a client whose full history has not been
pushed by a backfill (``--backfill --sync-s3``), which leaves ``_backfill_complete.json``.
Without it S3 would hold only the recent weeks and a deployment that mirrors the bucket would
lose history.

The same code syncs and verifies the **telemetry** partitions
(``{week}/telemetry.parquet`` + ``_telemetry_index.parquet``, see `src.data.telemetry_partitions`)
through an `S3Dataset`: ``ALERTS_DATASET`` (the default, behaviour unchanged) or
``TELEMETRY_DATASET``. Each has its own backfill marker (the alerts marker never satisfies the
telemetry guard) and owns only its own keys, so syncing one can never delete or overwrite the other.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from src.data import alert_partitions as layout
from src.data import telemetry_partitions as telemetry_layout
from src.data.alert_partition_builder import BuildResult, LocalFile

logger = logging.getLogger(__name__)

DEFAULT_S3_PREFIX = "MultiTechnique Alerts/alerts/golden"
_DELETE_BATCH = 1000
_SINGLE_PUT_LIMIT = 64 * 1024 * 1024

# ``{week}/file.parquet``, plus the previous ``{week}/{unit}/file.parquet`` layout so a sync also
# clears any object of it that is still in the bucket.
_LAYOUT_KEY = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}|undated)/(?:[^/]+/)?" + re.escape(layout.PARTITION_FILE) + r"$"
)


@dataclass(frozen=True)
class S3Dataset:
    """What differs between the datasets stored under a client's prefix.

    The alerts and the telemetry partitions share the bucket, the prefix and every upload /
    comparison rule; only the file names differ. Each dataset keeps its **own** backfill marker
    (the sequencing guard of one never satisfies the other) and recognises only its own keys as
    "layout keys" (the only ones the sync may delete as stale), so syncing one dataset can never
    delete or overwrite an object of the other.
    """

    name: str
    marker_file: str
    layout_key: "re.Pattern[str]"
    index_file: str
    history: str = "history"      # how the sequencing guard names what is missing in its error


ALERTS_DATASET = S3Dataset("alerts", layout.BACKFILL_MARKER_FILE, _LAYOUT_KEY, layout.INDEX_FILE)

# ``{week}/telemetry.parquet`` (``undated`` / ``unmatched`` folders included). Its own marker: the
# alerts backfill marker does not satisfy the telemetry sequencing guard.
TELEMETRY_DATASET = S3Dataset(
    "telemetry",
    telemetry_layout.BACKFILL_MARKER_FILE,
    re.compile(
        r"^(?:\d{4}-\d{2}-\d{2}|undated|unmatched)/" + re.escape(telemetry_layout.TELEMETRY_FILE) + r"$"
    ),
    telemetry_layout.INDEX_FILE,
    history="telemetry history",
)


class S3SyncError(RuntimeError):
    """The sync did not complete: some uploads failed, or the sequencing guard refused it."""


@dataclass
class S3Config:
    bucket: str
    prefix: str = DEFAULT_S3_PREFIX
    region: str = "us-east-1"

    @classmethod
    def from_env(cls, *, bucket: Optional[str] = None, prefix: Optional[str] = None,
                 region: Optional[str] = None) -> "S3Config":
        """Bucket/prefix shared by the backfill and the weekly run (CLI flag > env > default)."""
        resolved = bucket or os.getenv("ALERT_PARTITIONS_S3_BUCKET") or os.getenv("BUCKET_NAME")
        if not resolved:
            raise S3SyncError(
                "No S3 bucket configured: set ALERT_PARTITIONS_S3_BUCKET (or BUCKET_NAME)"
            )
        return cls(
            bucket=resolved,
            prefix=(prefix or os.getenv("ALERT_PARTITIONS_S3_PREFIX") or DEFAULT_S3_PREFIX).strip("/"),
            region=region or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        )

    def client_prefix(self, client: str) -> str:
        return f"{self.prefix}/{(client or '').lower()}"


def make_s3_client(config: S3Config):
    """A boto3 S3 client from the same credential sources the other S3 scripts use."""
    import boto3
    from botocore.config import Config

    kwargs = {
        "region_name": config.region,
        "config": Config(retries={"max_attempts": 5, "mode": "standard"}),
    }
    access, secret = os.getenv("ACCESS_KEY"), os.getenv("SECRET_KEY")
    if access and secret:
        kwargs.update(aws_access_key_id=access, aws_secret_access_key=secret)
    return boto3.client("s3", **kwargs)


@dataclass
class SyncResult:
    client: str
    uploaded: list[str] = field(default_factory=list)
    unchanged: int = 0
    deleted: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    marker_written: bool = False

    @property
    def ok(self) -> bool:
        return not self.failed


def _is_not_found(exc: Exception) -> bool:
    code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
    return code in {"404", "NoSuchKey", "NotFound"}


def _list_remote(s3, bucket: str, client_prefix: str) -> dict[str, dict]:
    remote: dict[str, dict] = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=client_prefix + "/"):
        for item in page.get("Contents", []):
            remote[item["Key"]] = {"Size": item["Size"], "ETag": str(item.get("ETag", "")).strip('"')}
    return remote


def _head(s3, bucket: str, key: str) -> Optional[dict]:
    try:
        return s3.head_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001 - botocore ClientError, or a stub's
        if _is_not_found(exc):
            return None
        raise


def _matches_remote(s3, bucket: str, key: str, local: LocalFile, remote: Optional[dict]) -> bool:
    """True when S3 already holds exactly this file."""
    if remote is None or remote["Size"] != local.size:
        return False
    if remote["ETag"] == local.md5:
        return True
    head = _head(s3, bucket, key)  # ETag is not an MD5 (multipart / KMS): use our metadata
    return bool(head) and head.get("Metadata", {}).get("sha256") == local.sha256


def _upload(s3, bucket: str, key: str, local: LocalFile) -> None:
    metadata = {"sha256": local.sha256, "rows": str(local.rows)}
    if local.size <= _SINGLE_PUT_LIMIT:
        with open(local.path, "rb") as handle:
            s3.put_object(
                Bucket=bucket, Key=key, Body=handle.read(),
                ContentType="application/vnd.apache.parquet", Metadata=metadata,
            )
    else:  # multipart; still only visible under the final key once complete
        s3.upload_file(str(local.path), bucket, key, ExtraArgs={"Metadata": metadata})


def _marker_key(config: S3Config, client: str, dataset: S3Dataset = ALERTS_DATASET) -> str:
    return f"{config.client_prefix(client)}/{dataset.marker_file}"


def backfill_marker_exists(s3, config: S3Config, client: str, dataset: S3Dataset = ALERTS_DATASET) -> bool:
    return _head(s3, config.bucket, _marker_key(config, client, dataset)) is not None


def sync_client(
    s3,
    config: S3Config,
    build: BuildResult,
    *,
    require_backfill_marker: bool,
    write_backfill_marker: bool = False,
    delete_stale: bool = True,
    dataset: S3Dataset = ALERTS_DATASET,
) -> SyncResult:
    """Make the client's S3 prefix equal to the local partitions of ``build``.

    ``require_backfill_marker`` is the weekly run's guard; ``write_backfill_marker`` is set by
    the backfill, once everything is uploaded. Raises `S3SyncError` when any upload failed
    (after attempting all of them) or the guard refuses. ``dataset`` selects the marker and the
    keys this sync owns (alerts by default).
    """
    client = build.client
    result = SyncResult(client=client)
    if require_backfill_marker and not backfill_marker_exists(s3, config, client, dataset):
        raise S3SyncError(
            f"{client}: S3 has no complete {dataset.history} yet ({dataset.marker_file} missing under "
            f"s3://{config.bucket}/{config.client_prefix(client)}/). Validate the local backfill and "
            f"run it with --sync-s3 first."
        )

    prefix = config.client_prefix(client)
    remote = _list_remote(s3, config.bucket, prefix)
    for rel, local in sorted(build.files.items()):
        key = f"{prefix}/{rel}"
        try:
            if _matches_remote(s3, config.bucket, key, local, remote.get(key)):
                result.unchanged += 1
                continue
            _upload(s3, config.bucket, key, local)
            result.uploaded.append(rel)
        except Exception as exc:  # noqa: BLE001 - keep going: report every failure, retry next run
            logger.error("%s: upload of %s failed: %s", client, rel, exc)
            result.failed[rel] = f"{type(exc).__name__}: {exc}"

    if result.failed:
        raise S3SyncError(
            f"{client}: {len(result.failed)} of {len(build.files)} uploads failed "
            f"(local partitions are intact; the next run retries them): "
            + ", ".join(sorted(result.failed)[:5])
        )

    if delete_stale:
        wanted = {f"{prefix}/{rel}" for rel in build.partition_files}
        stale = [
            key for key in remote
            if key not in wanted and dataset.layout_key.match(key[len(prefix) + 1:])
        ]
        for start in range(0, len(stale), _DELETE_BATCH):
            batch = stale[start:start + _DELETE_BATCH]
            s3.delete_objects(
                Bucket=config.bucket,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )
        result.deleted = [key[len(prefix) + 1:] for key in stale]

    if write_backfill_marker:
        body = json.dumps({
            "client": client,
            "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_rows": build.source_rows,
            "partitions": len(build.partition_files),
        }).encode()
        s3.put_object(Bucket=config.bucket, Key=_marker_key(config, client, dataset), Body=body,
                      ContentType="application/json")
        result.marker_written = True

    logger.info(
        "%s: S3 %s sync -> %d uploaded, %d already in sync, %d stale deleted",
        client, dataset.name, len(result.uploaded), result.unchanged, len(result.deleted),
    )
    return result


def verify_client(
    s3, config: S3Config, build: BuildResult, *, dataset: S3Dataset = ALERTS_DATASET
) -> list[str]:
    """Differences between the local partitions and S3 (same keys, sizes, hashes, row counts).

    An empty list means S3 matches the local output. Read-only.
    """
    prefix = config.client_prefix(build.client)
    remote = _list_remote(s3, config.bucket, prefix)
    problems = []
    expected = {f"{prefix}/{rel}": local for rel, local in build.files.items()}
    for key, local in sorted(expected.items()):
        entry = remote.get(key)
        if entry is None:
            problems.append(f"missing in S3: {key}")
            continue
        head = _head(s3, config.bucket, key) or {}
        metadata = head.get("Metadata", {})
        if entry["Size"] != local.size:
            problems.append(f"size differs: {key} (S3 {entry['Size']}, local {local.size})")
        elif metadata.get("sha256") != local.sha256 and entry["ETag"] != local.md5:
            problems.append(f"content differs: {key}")
        elif local.rel != dataset.index_file and metadata.get("rows") not in (None, str(local.rows)):
            problems.append(f"row count differs: {key} (S3 {metadata.get('rows')}, local {local.rows})")
    for key in sorted(remote):
        if key not in expected and dataset.layout_key.match(key[len(prefix) + 1:]):
            problems.append(f"extra in S3: {key}")
    return problems
