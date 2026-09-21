"""Dump the database with pg_dump and keep the dump in the backups bucket."""

import os
import subprocess
from datetime import datetime
from pathlib import Path

from app.core.config import BackupR2Config, Environment, config
from app.core.storage import S3ObjectStore, r2_object_store

DUMP_PREFIX = "daily"


def name_dump(environment: Environment, taken_at: datetime) -> str:
    """Named for where the rows came from, so a dev dump is never mistaken for a prod one."""
    return f"regrag-{environment.value}-{taken_at:%Y%m%d-%H%M%S}.dump"


def dump_database(path: Path) -> None:
    """Write a custom-format dump, then read its table of contents back. That check catches
    an unreadable archive, not a truncated one: only a restore proves the rows are there."""
    libpq = {**os.environ, **config.LIBPQ_ENVIRONMENT}
    dump = ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", f"--file={path}"]
    subprocess.run(dump, env=libpq, check=True)
    subprocess.run(["pg_restore", "--list", str(path)], stdout=subprocess.DEVNULL, check=True)


def get_backup_store() -> S3ObjectStore:
    """The backups bucket, its settings read now so a missing one fails before the dump."""
    return r2_object_store(BackupR2Config())


def upload_dump(store: S3ObjectStore, path: Path) -> str:
    """The key the dump was stored under."""
    key = f"{DUMP_PREFIX}/{path.name}"
    store.put_file(key, path)
    return key
