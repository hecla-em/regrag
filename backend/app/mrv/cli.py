"""MRV CLI: `uv run mrv ingest [--period 2025 ...]`."""

import argparse
import asyncio
import sys

import httpx

from app.core.db.session import get_session
from app.core.http import http_client
from app.core.logger import setup_logging
from app.core.storage import StorageError, get_object_store
from app.mrv.parse import MrvLayoutError
from app.mrv.service import load_periods


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mrv", description="THETIS-MRV public dataset")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="load the latest file of each period")
    ingest.add_argument(
        "--period", type=int, action="append", help="period to load (default: all from 2024)"
    )
    return parser


async def run_ingest(periods: list[int] | None) -> dict[int, int]:
    async with http_client(timeout=120) as client:
        async with get_session(auto_commit=False) as session:
            return await load_periods(session, client, get_object_store(), periods)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()
    try:
        loaded = asyncio.run(run_ingest(args.period))
    except (httpx.HTTPError, StorageError, MrvLayoutError) as exc:
        print(f"mrv ingest failed: {exc}", file=sys.stderr)
        return 1
    for period, rows in loaded.items():
        print(f"{period}: {rows} reports")
    return 0
