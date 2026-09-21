"""Dump the database with pg_dump into the backups bucket, and restore a dump with pg_restore."""

import os
import subprocess
from datetime import datetime
from pathlib import Path

from app.core.config import Environment, R2Config, config
from app.core.storage import ObjectNotFoundError, S3ObjectStore, r2_object_store

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
    check = ["pg_restore", "--list", str(path)]
    subprocess.run(check, env=libpq, stdout=subprocess.DEVNULL, check=True)


def restore_database(path: Path, database: str) -> None:
    """Restore into an existing database on the configured server, in one transaction so a
    database that already holds the tables is left as it was."""
    libpq = {**os.environ, **config.LIBPQ_ENVIRONMENT}
    restore = ["pg_restore", "--single-transaction", "--no-owner", "--no-privileges"]
    subprocess.run([*restore, f"--dbname={database}", str(path)], env=libpq, check=True)


def fetch_dump(name: str | None) -> Path:
    """Download a dump by name, or the newest prod one: the timestamps in the names sort as
    dates."""
    store = get_backup_store()
    prefix = f"{DUMP_PREFIX}/regrag-{Environment.PROD.value}-"
    key = f"{DUMP_PREFIX}/{name}" if name else max(store.list_keys(prefix), default=None)
    if key is None:
        raise ObjectNotFoundError("list", prefix, "no dumps stored")
    path = Path(Path(key).name)
    store.get_file(key, path)
    return path


def get_backup_store() -> S3ObjectStore:
    """The R2 credentials pointed at the backups bucket rather than the one R2_BUCKET names,
    read now so a missing one fails before the dump."""
    return r2_object_store(R2Config(R2_BUCKET=config.BACKUP_BUCKET))
