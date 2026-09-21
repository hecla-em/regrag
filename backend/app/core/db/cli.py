"""Database CLI: `uv run db backup [--no-upload]`, `uv run db shell [--writable] [psql args]`."""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sentry_sdk.types import MonitorConfig

from app.core.clock import utc_now
from app.core.config import config
from app.core.db.backup import dump_database, get_backup_store, name_dump, upload_dump
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
READ_ONLY_OPTIONS = "-c default_transaction_read_only=on"


def register_backup_command(commands: Any) -> None:
    backup = commands.add_parser("backup", help="pg_dump the database and store the dump in R2")
    backup.add_argument(
        "--no-upload",
        action="store_true",
        help="leave the dump in the working directory rather than sending it to R2",
    )


def register_shell_command(commands: Any) -> None:
    shell = commands.add_parser(
        "shell", help="psql on the database; other arguments pass through to psql"
    )
    shell.add_argument(
        "--writable", action="store_true", help="allow writes (sessions are read-only otherwise)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="db", description="RegRag database", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    register_backup_command(commands)
    register_shell_command(commands)
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


def run_shell(writable: bool, psql_args: list[str]) -> int:
    """Replace this process with psql on the configured database, read-only unless asked."""
    libpq = {**os.environ, **config.LIBPQ_ENVIRONMENT}
    if not writable:
        libpq["PGOPTIONS"] = f"{READ_ONLY_OPTIONS} {libpq.get('PGOPTIONS', '')}".strip()
    access = "writable" if writable else "read-only"
    target = f"{config.DB_USER}@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}"
    print(f"psql {target} ({config.ENVIRONMENT.value}, {access})", file=sys.stderr)
    try:
        os.execvpe("psql", ["psql", *psql_args], libpq)
    except OSError as exc:
        print(f"psql could not be started: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, psql_args = parser.parse_known_args(argv)
    if args.command == "shell":
        return run_shell(args.writable, psql_args)
    if psql_args:
        parser.error(f"unrecognized arguments: {' '.join(psql_args)}")
    setup_logging()
    return run_backup(upload=not args.no_upload)
