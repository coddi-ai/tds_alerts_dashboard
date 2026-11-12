"""Object storage for the login-event pipeline: S3 in deployments, a directory in tests and
local development. Keys are relative ("auth_events/raw/..."); each backend adds its own root."""

import os
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv

from src.auth_events import settings


class ObjectNotFound(KeyError):
    """The object does not exist (as opposed to the storage being unreachable)."""


class Storage(Protocol):
    def put(self, key: str, body: bytes, content_type: str = "application/octet-stream") -> None: ...
    def get(self, key: str) -> bytes: ...
    def list(self, prefix: str) -> list[str]: ...
    def delete(self, key: str) -> None: ...


class S3Storage:
    def __init__(self, bucket: str, root: str, client):
        self.bucket = bucket
        self.root = root
        self.client = client

    def _full(self, key: str) -> str:
        return f"{self.root}{key}"

    def put(self, key, body, content_type="application/octet-stream"):
        self.client.put_object(Bucket=self.bucket, Key=self._full(key), Body=body, ContentType=content_type)

    def get(self, key):
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._full(key))["Body"].read()
        except self.client.exceptions.NoSuchKey as exc:
            raise ObjectNotFound(key) from exc

    def list(self, prefix):
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self._full(prefix)):
            for obj in page.get("Contents", []):
                if not obj["Key"].endswith("/"):
                    keys.append(obj["Key"][len(self.root):])
        return keys

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=self._full(key))


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(self, key, body, content_type="application/octet-stream"):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def get(self, key):
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFound(key) from exc

    def list(self, prefix):
        walk_root = self._path(prefix)
        if not walk_root.is_dir():
            walk_root = walk_root.parent
        if not walk_root.exists():
            return []
        found = []
        for path in walk_root.rglob("*"):
            if path.is_file():
                key = path.relative_to(self.root).as_posix()
                if key.startswith(prefix):
                    found.append(key)
        return sorted(found)

    def delete(self, key):
        self._path(key).unlink(missing_ok=True)


def get_storage() -> Storage | None:
    """The configured backend, or None when neither a local directory nor a bucket is set."""
    local = settings.local_dir()
    if local is not None:
        return LocalStorage(local)

    load_dotenv(Path(__file__).parent.parent.parent / ".env")
    bucket = os.getenv("BUCKET_NAME")
    if not bucket:
        return None

    import boto3

    kwargs = {"region_name": "us-east-1"}
    access, secret = os.getenv("ACCESS_KEY"), os.getenv("SECRET_KEY")
    if access and secret:
        kwargs.update(aws_access_key_id=access, aws_secret_access_key=secret)
    return S3Storage(bucket, settings.s3_root(), boto3.client("s3", **kwargs))
