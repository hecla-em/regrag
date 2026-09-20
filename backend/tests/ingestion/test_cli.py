"""Ingest CLI: argument validation, exit codes, report printing, the Sentry check-in."""

import httpx
import pytest

from app.core.config import config
from app.ingestion import cli
from app.ingestion.chunk.models import ChunkCounts
from app.ingestion.cli import main
from app.ingestion.enums import DocChange, Stage
from app.ingestion.exceptions import MalformedDiscoveryError
from app.ingestion.models import DocumentOutcome, IngestRunResult
from tests.conftest import no_session

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


def test_no_topics_ingests_every_topic(fake_ingest):
    calls, _ = fake_ingest
    assert main([]) == 0
    assert calls == [sorted(config.TOPIC_BASE_ACTS)]


def test_explicit_topics_passed_through(fake_ingest):
    calls, _ = fake_ingest
    assert main(["mrv"]) == 0
    assert calls == [["mrv"]]


def test_unknown_topic_rejected(fake_ingest, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["shipping"])
    assert excinfo.value.code == 2
    assert "unknown topics: shipping" in capsys.readouterr().err


def test_prints_summary_and_exits_zero_when_clean(fake_ingest, capsys):
    _, report = fake_ingest
    report.documents.append(
        DocumentOutcome(celex="32023R1805", change=DocChange.NEW, chunks=ChunkCounts(added=3))
    )
    assert main([]) == 0
    assert "1 new" in capsys.readouterr().out


def test_exits_nonzero_when_documents_failed(fake_ingest, capsys):
    _, report = fake_ingest
    report.documents.append(
        DocumentOutcome(
            celex="32023R2917",
            failed=Stage.FETCH,
            error="ConnectionError: no fetchable HTML",
        )
    )
    assert main([]) == 1
    assert "fetch failed: 32023R2917" in capsys.readouterr().out


def test_exits_nonzero_when_a_document_failed_to_parse(fake_ingest, capsys):
    _, report = fake_ingest
    report.documents.append(
        DocumentOutcome(
            celex="32023R2449",
            failed=Stage.PARSE,
            error="ParseError: unrecognised dialect",
        )
    )
    assert main([]) == 1
    assert "parse failed: 32023R2449" in capsys.readouterr().out


def test_abort_prints_error_and_exits_nonzero(monkeypatch, capsys):
    async def _boom(topics):
        raise MalformedDiscoveryError("mrv: malformed SPARQL response")

    monkeypatch.setattr(cli, "_ingest", _boom)
    assert main([]) == 1
    assert "ingest aborted: mrv" in capsys.readouterr().err


def test_abort_on_http_error(monkeypatch, capsys):
    async def _boom(topics):
        raise httpx.ConnectError("endpoint down")

    monkeypatch.setattr(cli, "_ingest", _boom)
    assert main([]) == 1
    assert "ingest aborted" in capsys.readouterr().err


def test_a_run_with_failed_documents_checks_in_to_the_nightly_monitor_as_an_error(
    fake_ingest, sentry
):
    """Nothing raises when a document fails, so the check-in has to follow the exit code."""
    _, report = fake_ingest
    report.documents.append(DocumentOutcome(celex="32023R2917", failed=Stage.FETCH, error="x"))

    assert main([]) == 1

    started, finished = sentry.check_ins
    assert (started["status"], finished["status"]) == ("in_progress", "error")
    assert started["monitor_slug"] == cli.MONITOR_SLUG
    assert started["monitor_config"]["schedule"] == {"type": "crontab", "value": "0 3 * * *"}
    [event] = sentry.events
    assert event["logentry"]["params"] == [1, {"fetch": ["32023R2917"]}]


def test_an_aborted_run_sends_why_it_aborted(monkeypatch, sentry):
    async def _boom(topics):
        raise MalformedDiscoveryError("mrv: malformed SPARQL response")

    monkeypatch.setattr(cli, "_ingest", _boom)

    assert main([]) == 1

    [event] = sentry.events
    assert event["exception"]["values"][0]["type"] == "MalformedDiscoveryError"


async def test_ingest_hands_the_pipeline_a_paced_client(monkeypatch):
    """The CLI is where the crawl delays are attached, so pin both the delays it asks for and
    that the real client it gets back carries the hook they produce."""
    built: dict = {}
    clients: list[httpx.AsyncClient] = []
    real_client = cli.http_client

    def spy(**kwargs):
        built.update(kwargs)
        return real_client(**kwargs)

    async def capture(_session, *, client, **__):
        clients.append(client)
        return IngestRunResult(run_id=1)

    monkeypatch.setattr(cli, "http_client", spy)
    monkeypatch.setattr(cli, "get_session", no_session)
    monkeypatch.setattr(cli, "ingest", capture)
    await cli._ingest(["mrv"])

    (client,) = clients
    assert built["delays"] == config.CRAWL_DELAYS
    assert client.event_hooks["request"]
