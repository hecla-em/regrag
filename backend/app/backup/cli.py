"""Backup CLI: `uv run backup [--no-upload]`."""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError
from sentry_sdk.types import MonitorConfig

from app.backup.service import dump_database, get_backup_store, name_dump, upload_dump
from app.core.clock import utc_now
from app.core.config import config
from app.core.logger import setup_logging
from app.core.sentry import monitor_cron_job
from app.core.storage import StorageError

logger = logging.getLogger(__name__)

MONITOR_SLUG = "nightly-backup"
# The schedule and the job timeout in .github/workflows/backup.yml. The margin is eight
# hours because GitHub starts scheduled runs hours late.
MONITOR_CONFIG: MonitorConfig = {
    "schedule": {"type": "crontab", "value": "0 2 * * *"},
    "timezone": "UTC",
    "checkin_margin": 480,
    "max_runtime": 20,
    "failure_issue_threshold": 1,
    "recovery_threshold": 1,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backup", description="RegRag database backup")
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="leave the dump in the working directory rather than sending it to R2",
    )
    return parser


@monitor_cron_job(MONITOR_SLUG, MONITOR_CONFIG)
def run_backup(upload: bool) -> int:
    """One run's exit code: 0 once the dump is written and, unless told not to, stored."""
    path = Path(name_dump(config.ENVIRONMENT, utc_now()))
    try:
        store = get_backup_store() if upload else None
        dump_database(path)
        stored_as = upload_dump(store, path) if store else None
    except (subprocess.CalledProcessError, OSError, StorageError, ValidationError) as exc:
        logger.exception("backup aborted")
        print(f"backup aborted: {exc}", file=sys.stderr)
        return 1
    print(f"backup stored: {stored_as}" if stored_as else f"backup written: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()
    return run_backup(upload=not args.no_upload)
