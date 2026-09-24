"""Ingest CLI: `uv run ingest [topics...]`, the corpus and then the THETIS-MRV files."""

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
from app.mrv.parse import MrvLayoutError
from app.mrv.service import load_new_files

logger = logging.getLogger(__name__)

MONITOR_SLUG = "nightly-ingest"
# The schedule and the job timeout in .github/workflows/ingest.yml. The margin is eight
# hours because GitHub starts this scheduled run about five hours late every night.
MONITOR_CONFIG: MonitorConfig = {
    "schedule": {"type": "crontab", "value": "0 3 * * *"},
    "timezone": "UTC",
    "checkin_margin": 480,
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


async def _load_mrv() -> dict[int, int]:
    async with http_client(timeout=120) as client:
        async with get_session(auto_commit=False) as session:
            return await load_new_files(session, client, get_object_store())


def ingest_corpus(topics: list[str]) -> bool:
    """Whether every document got through; an abort or a failure is logged as an error, so
    Sentry holds why beside the check-in."""
    try:
        report = asyncio.run(_ingest(topics))
    except (DiscoveryError, StorageError, httpx.HTTPError, ValidationError) as exc:
        logger.exception("ingest aborted")
        print(f"ingest aborted: {exc}", file=sys.stderr)
        return False
    print(report.summary())
    if report.ok:
        return True
    failed = {stage.value: sorted(lost) for stage, lost in report.failures.items() if lost}
    logger.error("ingest run %s finished with failures: %s", report.run_id, failed)
    return False


def ingest_mrv() -> bool:
    """Whether every THETIS-MRV period EMSA has republished since the last run loaded."""
    try:
        loaded = asyncio.run(_load_mrv())
    except (httpx.HTTPError, StorageError, MrvLayoutError) as exc:
        logger.exception("mrv ingest failed")
        print(f"mrv ingest failed: {exc}", file=sys.stderr)
        return False
    print(
        "mrv: "
        + (", ".join(f"{period} {rows} reports" for period, rows in loaded.items()) or "unchanged")
    )
    return True


@monitor_cron_job(MONITOR_SLUG, MONITOR_CONFIG)
def run_ingest(topics: list[str]) -> int:
    """One run's exit code: 0 when the corpus and the MRV files both got through, else 1. Each
    runs whatever the other did, so an outage at one source leaves the other current."""
    corpus_ok = ingest_corpus(topics)
    mrv_ok = ingest_mrv()
    return 0 if corpus_ok and mrv_ok else 1


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
