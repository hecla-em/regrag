"""Database shell: `uv run dbshell [--writable] [psql arguments...]`."""

import argparse
import os
import sys

from app.core.config import config

READ_ONLY_OPTIONS = "-c default_transaction_read_only=on"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dbshell",
        description="psql on the configured database; other arguments pass through to psql",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--writable", action="store_true", help="allow writes (sessions are read-only otherwise)"
    )
    return parser


def build_shell_environment(writable: bool) -> dict[str, str]:
    """The process environment plus the configured database, read-only unless asked."""
    shell = {**os.environ, **config.LIBPQ_ENVIRONMENT}
    if not writable:
        shell["PGOPTIONS"] = f"{READ_ONLY_OPTIONS} {shell.get('PGOPTIONS', '')}".strip()
    return shell


def main(argv: list[str] | None = None) -> int:
    args, psql_args = build_parser().parse_known_args(argv)
    access = "writable" if args.writable else "read-only"
    target = f"{config.DB_USER}@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}"
    print(f"psql {target} ({config.ENVIRONMENT.value}, {access})", file=sys.stderr)
    try:
        os.execvpe("psql", ["psql", *psql_args], build_shell_environment(args.writable))
    except OSError as exc:
        print(f"psql could not be started: {exc}", file=sys.stderr)
        return 1
