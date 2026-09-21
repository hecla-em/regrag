"""Backup service: the dump's name, the pg_dump call and its environment, the upload key."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.backup import service
from app.backup.service import dump_database, get_backup_store, name_dump, upload_dump
from app.core.config import Environment, config
from app.core.storage import S3ObjectStore
from tests.conftest import R2_ENV


class RecordingS3:
    def __init__(self):
        self.uploads: list[tuple[str, str, str]] = []

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.uploads.append((filename, bucket, key))


@pytest.fixture
def commands(monkeypatch) -> list[tuple[list[str], dict]]:
    """Every subprocess the service starts, with the keyword arguments it was given."""
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: ran.append((args, kwargs)))
    return ran


def test_a_dump_is_named_for_the_environment_and_the_utc_second():
    taken_at = datetime(2026, 9, 20, 2, 0, 7, tzinfo=UTC)
    assert name_dump(Environment.PROD, taken_at) == "regrag-prod-20260920-020007.dump"


def test_pg_dump_connects_with_the_configured_database(commands):
    dump_database(Path("x.dump"))

    dump, kwargs = commands[0]
    assert dump == ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--file=x.dump"]
    assert kwargs["env"]["PGDATABASE"] == config.DB_NAME
    assert kwargs["check"] is True


def test_the_dump_is_read_back_before_it_counts(commands):
    dump_database(Path("x.dump"))

    listing, kwargs = commands[1]
    assert listing == ["pg_restore", "--list", "x.dump"]
    assert kwargs["check"] is True


def test_a_failed_pg_dump_is_not_read_back(monkeypatch):
    def _fail(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", _fail)
    with pytest.raises(subprocess.CalledProcessError):
        dump_database(Path("x.dump"))


def test_the_dump_is_stored_under_the_daily_prefix():
    client = RecordingS3()
    key = upload_dump(S3ObjectStore(client, "regrag-db-backups"), Path("/tmp/regrag-prod-1.dump"))

    assert key == "daily/regrag-prod-1.dump"
    assert client.uploads == [("/tmp/regrag-prod-1.dump", "regrag-db-backups", key)]


def test_the_backup_store_is_the_backups_bucket_not_the_raw_docs_one(monkeypatch):
    for name, value in R2_ENV.items():
        monkeypatch.setenv(name, value)
        monkeypatch.setenv(f"BACKUP_{name}", value)
    monkeypatch.setenv("BACKUP_R2_BUCKET", "regrag-db-backups")
    monkeypatch.setattr(service, "r2_object_store", lambda r2: r2.R2_BUCKET)

    assert get_backup_store() == "regrag-db-backups"
