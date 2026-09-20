"""Ingest CLI: `uv run ingest [topics...]`."""

import argparse
import asyncio
import logging
import sys

import httpx
from pydantic import ValidationError
from sentry_sdk.types import MonitorConfig

from app.core.config import config
from app.core.db.session import get_session
from app.core.http import http_client
from app.core.logger import setup_logging
from app.core.sentry import monitor_cron_job
from app.core.storage import StorageError, get_object_store
from app.ingestion.exceptions import DiscoveryError
from app.ingestion.models import IngestRunResult
from app.ingestion.pipeline import ingest

logger = logging.getLogger(__name__)

MONITOR_SLUG = "nightly-ingest"
# The schedule and the job timeout in .github/workflows/ingest.yml. The margin is wide
# because GitHub often starts a scheduled run late.
MONITOR_CONFIG: MonitorConfig = {
    "schedule": {"type": "crontab", "value": "0 3 * * *"},
    "timezone": "UTC",
    "checkin_margin": 60,
    "max_runtime": 60,
    "failure_issue_threshold": 1,
    "recovery_threshold": 1,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ingest", description="RegRag corpus ingestion")
    parser.add_argument(
        "topics",
        nargs="*",
        metavar="topic",
        help=f"topics to ingest (default: {', '.join(sorted(config.TOPIC_BASE_ACTS))})",
    )
    return parser


async def _ingest(topics: list[str]) -> IngestRunResult:
    store = get_object_store()
    async with http_client(delays=config.CRAWL_DELAYS) as client:
        async with get_session(auto_commit=False) as session:
            return await ingest(session, client=client, topics=topics, store=store)


@monitor_cron_job(MONITOR_SLUG, MONITOR_CONFIG)
def run_ingest(topics: list[str]) -> int:
    """One run's exit code: 0 when every document got through, 1 when any failed or it aborted.
    Either failure is logged as an error, so Sentry holds why beside the check-in."""
    try:
        report = asyncio.run(_ingest(topics))
    except (DiscoveryError, StorageError, httpx.HTTPError, ValidationError) as exc:
        logger.exception("ingest aborted")
        print(f"ingest aborted: {exc}", file=sys.stderr)
        return 1
    print(report.summary())
    if report.ok:
        return 0
    failed = {stage.value: sorted(lost) for stage, lost in report.failures.items() if lost}
    logger.error("ingest run %s finished with failures: %s", report.run_id, failed)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    topics = args.topics or sorted(config.TOPIC_BASE_ACTS)
    unknown = sorted(set(topics) - config.TOPIC_BASE_ACTS.keys())
    if unknown:
        known = ", ".join(sorted(config.TOPIC_BASE_ACTS))
        parser.error(f"unknown topics: {', '.join(unknown)} (known: {known})")
    setup_logging()
    return run_ingest(topics)
