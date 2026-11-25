"""S3 sync freshness checks for same-size objects, using a local fake client."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.data.s3_downloader import S3Downloader


class _Paginator:
    def __init__(self, contents):
        self.contents = contents

    def paginate(self, **kwargs):
        return [{"Contents": self.contents}]


class _FakeS3:
    def __init__(self, key, content, modified):
        self.key = key
        self.content = content
        self.modified = modified
        self.downloads = 0

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _Paginator([{
            "Key": self.key,
            "Size": len(self.content),
            "LastModified": self.modified,
        }])

    def download_file(self, bucket, key, target):
        assert (bucket, key) == ("test-bucket", self.key)
        self.downloads += 1
        Path(target).write_bytes(self.content)


def _downloader(fake):
    downloader = S3Downloader.__new__(S3Downloader)
    downloader.bucket_name = "test-bucket"
    downloader.s3_client = fake
    return downloader


def test_same_size_object_is_downloaded_when_s3_modification_is_newer(tmp_path):
    key = "MultiTechnique Alerts/fleet_history/golden/emin/2026-W48/latest.json"
    previous = b'{"run":"old-package"}'
    latest = b'{"run":"new-package"}'
    assert len(previous) == len(latest)
    local = tmp_path / "fleet_history" / "golden" / "emin" / "2026-W48" / "latest.json"
    local.parent.mkdir(parents=True)
    local.write_bytes(previous)
    old = datetime.now(timezone.utc) - timedelta(days=1)
    local.touch()
    import os
    os.utime(local, (old.timestamp(), old.timestamp()))

    remote_time = datetime.now(timezone.utc)
    fake = _FakeS3(key, latest, remote_time)
    stats = _downloader(fake).download_folder("MultiTechnique Alerts/", tmp_path)

    assert stats["downloaded"] == 1
    assert fake.downloads == 1
    assert local.read_bytes() == latest
    assert abs(local.stat().st_mtime - remote_time.timestamp()) < 1


def test_same_size_object_is_skipped_when_local_copy_matches_remote_time(tmp_path):
    key = "MultiTechnique Alerts/fleet_history/golden/emin/2026-W48/latest.json"
    content = b'{"run":"same-package"}'
    remote_time = datetime.now(timezone.utc) - timedelta(hours=1)
    local = tmp_path / "fleet_history" / "golden" / "emin" / "2026-W48" / "latest.json"
    local.parent.mkdir(parents=True)
    local.write_bytes(content)
    import os
    os.utime(local, (remote_time.timestamp(), remote_time.timestamp()))
    fake = _FakeS3(key, content, remote_time)

    stats = _downloader(fake).download_folder("MultiTechnique Alerts/", tmp_path)

    assert stats["skipped"] == 1
    assert fake.downloads == 0
