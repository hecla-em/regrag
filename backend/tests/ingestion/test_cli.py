"""Ingest CLI: argument validation, exit codes, report printing, the Sentry check-in."""

import httpx
import pytest

from app.ingestion import cli
from app.ingestion.cli import main
from app.ingestion.enums import Stage
from app.ingestion.exceptions import MalformedDiscoveryError
from app.ingestion.models import DocumentOutcome, IngestRunResult

pytestmark = pytest.mark.anyio


@pytest.fixture
def fake_ingest(monkeypatch):
    """Replace the DB+network coroutine with a stub recording requested topics."""
    calls = []
    report = IngestRunResult(run_id=1)

    async def _fake(topics):
        calls.append(list(topics))
        return report

    monkeypatch.setattr(cli, "_ingest", _fake)
    return calls, report


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(MalformedDiscoveryError("mrv: malformed SPARQL response"), id="discovery"),
        pytest.param(httpx.ConnectError("endpoint down"), id="the network"),
    ],
)
def test_an_aborted_run_exits_nonzero_and_sends_why_it_aborted(monkeypatch, sentry, error):
    async def _boom(topics):
        raise error

    monkeypatch.setattr(cli, "_ingest", _boom)

    assert main([]) == 1

    [event] = sentry.events
    assert event["exception"]["values"][0]["type"] == type(error).__name__


def test_a_run_with_failed_documents_checks_in_to_the_nightly_monitor_as_an_error(
    fake_ingest, sentry
):
    """Nothing raises when a document fails, so the check-in has to follow the exit code."""
    _, report = fake_ingest
    report.documents.append(
        DocumentOutcome(celex="32023R2917", topic="mrv", failed=Stage.FETCH, error="x")
    )

    assert main([]) == 1

    started, finished = sentry.check_ins
    assert (started["status"], finished["status"]) == ("in_progress", "error")
    assert started["monitor_slug"] == cli.MONITOR_SLUG
    assert started["monitor_config"]["schedule"] == {"type": "crontab", "value": "0 3 * * *"}
    assert started["monitor_config"]["checkin_margin"] == 480
    [event] = sentry.events
    assert event["logentry"]["params"] == [1, {"fetch": ["32023R2917"]}]
