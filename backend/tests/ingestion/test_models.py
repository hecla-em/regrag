"""One ingest run's outcome: what it counts, the row it stores, the summary the CLI prints."""

import pytest

from app.core.config import config
from app.ingestion.chunk.models import ChunkCounts
from app.ingestion.enums import DocChange, IngestRunStatus, Stage
from app.ingestion.exceptions import ParseError
from app.ingestion.models import DocumentOutcome, IngestRunResult


def failed_doc(
    stage: Stage = Stage.PARSE, celex: str = "b", error: str = "ParseError: no body"
) -> DocumentOutcome:
    """A document outcome as the loop records a stage failure."""
    return DocumentOutcome(celex=celex, topic="mrv", failed=stage, error=error)


@pytest.fixture
def run() -> IngestRunResult:
    """A run that discovered two documents, fetched both, and chunked one of them."""
    result = IngestRunResult(run_id=7, corpus_version="2026-08-05-abc1234", discovered=2)
    result.documents.append(
        DocumentOutcome(
            celex="a", topic="mrv", change=DocChange.NEW, chunks=ChunkCounts(added=12, kept=30)
        )
    )
    result.documents.append(
        DocumentOutcome(celex="b", topic="mrv", change=DocChange.REUSED, chunks=ChunkCounts())
    )
    return result


def test_a_run_is_ok_when_no_document_failed(run: IngestRunResult) -> None:
    assert run.ok
    assert run.status is IngestRunStatus.SUCCESS


@pytest.mark.parametrize("stage", [Stage.FETCH, Stage.PARSE, Stage.CHUNK])
def test_a_failure_in_any_stage_fails_the_run(stage: Stage) -> None:
    result = IngestRunResult(run_id=1)
    result.documents.append(failed_doc(stage))
    assert not result.ok
    assert result.status is IngestRunStatus.FAILED


def test_an_embed_failure_fails_the_run() -> None:
    result = IngestRunResult(run_id=1)
    result.embed.fail("a", ParseError("boom"), chunks=1)
    assert not result.ok


def test_a_failed_document_counts_towards_nothing_but_its_failure() -> None:
    """The loop rolled its work back, so no stage may claim it."""
    result = IngestRunResult(run_id=1)
    result.documents.append(failed_doc(Stage.CHUNK, "a"))

    assert result.report()["fetch"] == {
        "documents": 0,
        "new": 0,
        "updated": 0,
        "reused": 0,
        "failed": {},
    }
    assert result.report()["parse"] == {"documents": 0, "parsed": 0, "failed": {}}
    assert result.report()["chunk"]["failed"] == {"a": "ParseError: no body"}


def test_a_stage_line_adds_up_when_a_later_stage_loses_the_document(run: IngestRunResult) -> None:
    """Fetch cleared three documents but only answers for two: chunk rolled the third back."""
    run.documents.append(failed_doc(Stage.CHUNK, "c"))

    assert run.line(Stage.FETCH) == "[fetch] 2 documents: 1 new, 0 updated, 1 reused, 0 failed"
    assert run.line(Stage.PARSE) == "[parse] 2 documents: 2 parsed, 0 failed"
    assert run.line(Stage.CHUNK).endswith("1 failed")


def test_the_prune_is_counted_as_chunks_deleted(run: IngestRunResult) -> None:
    run.pruned = 5
    assert run.chunks == ChunkCounts(added=12, deleted=5, kept=30)


def test_a_run_with_no_fetch_or_parse_failure_may_prune(run: IngestRunResult) -> None:
    assert run.corpus_complete
    run.documents.append(failed_doc(Stage.CHUNK, "c"))
    assert run.corpus_complete


@pytest.mark.parametrize("stage", [Stage.FETCH, Stage.PARSE])
def test_a_run_that_lost_a_document_may_not_prune(run: IngestRunResult, stage: Stage) -> None:
    run.documents.append(failed_doc(stage, "c"))
    assert not run.corpus_complete


def test_report_covers_every_stage_with_its_counts_and_failures(run: IngestRunResult) -> None:
    run.dropped = ["z"]
    run.documents.append(failed_doc(Stage.PARSE, "c"))
    run.embed.embedded = 12

    assert run.report() == {
        "discover": {"documents": 2, "dropped": 1, "failed": {}},
        "fetch": {"documents": 2, "new": 1, "updated": 0, "reused": 1, "failed": {}},
        "parse": {"documents": 3, "parsed": 2, "failed": {"c": "ParseError: no body"}},
        "chunk": {"chunks": 42, "added": 12, "deleted": 0, "kept": 30, "updated": 0, "failed": {}},
        "embed": {"chunks": 12, "embedded": 12, "already_embedded": 0, "failed": {}},
    }


def test_a_report_of_a_run_that_did_nothing_counts_nothing() -> None:
    """Every stage still appears, so a reader of an aborted run sees zeros rather than gaps."""
    assert IngestRunResult(run_id=1).report() == {
        "discover": {"documents": 0, "dropped": 0, "failed": {}},
        "fetch": {"documents": 0, "new": 0, "updated": 0, "reused": 0, "failed": {}},
        "parse": {"documents": 0, "parsed": 0, "failed": {}},
        "chunk": {"chunks": 0, "added": 0, "deleted": 0, "kept": 0, "updated": 0, "failed": {}},
        "embed": {"chunks": 0, "embedded": 0, "already_embedded": 0, "failed": {}},
    }


def test_report_leaves_out_the_run_s_own_columns(run: IngestRunResult) -> None:
    """Both are columns already, and corpus_version is stamped after the row is written."""
    assert "run_id" not in run.report()
    assert "corpus_version" not in run.report()


def test_report_caps_a_failure_message_a_provider_made_too_long() -> None:
    result = IngestRunResult(run_id=1)
    result.embed.fail("c", ParseError("x" * (config.MAX_FAILURE_CHARS + 100)), chunks=1)
    stored = result.report()["embed"]["failed"]["c"]
    assert len(stored) == config.MAX_FAILURE_CHARS
    assert stored.startswith("1 chunk: ParseError: xxx")


def test_report_leaves_the_recorded_failure_message_whole() -> None:
    """Capping is a storage concern: the summary still prints the message in full."""
    message = "x" * (config.MAX_FAILURE_CHARS + 100)
    result = IngestRunResult(run_id=1)
    result.embed.fail("c", ParseError(message), chunks=1)
    result.report()
    assert message in result.summary()


def test_the_discover_line_reports_what_discovery_found_not_the_documents_seen_so_far() -> None:
    """The mid-run discover log fires before the loop populates documents."""
    result = IngestRunResult(run_id=1, discovered=2, dropped=["z"])
    assert result.line(Stage.DISCOVER) == "[discover] 2 documents: 1 dropped, 0 failed"


def test_summary_reports_every_stage_on_its_own_line_with_its_unit(run: IngestRunResult) -> None:
    run.embed.embedded, run.embed.already_embedded = 12, 30

    assert run.summary().splitlines() == [
        "run 7 (2026-08-05-abc1234)",
        "  [discover] 2 documents: 0 dropped, 0 failed",
        "  [fetch] 2 documents: 1 new, 0 updated, 1 reused, 0 failed",
        "  [parse] 2 documents: 2 parsed, 0 failed",
        "  [chunk] 42 chunks: 12 added, 0 deleted, 30 kept, 0 updated, 0 failed",
        "  [embed] 42 chunks: 12 embedded, 30 already embedded, 0 failed",
        "  fetch new: a",
    ]


def test_summary_says_so_when_no_version_was_stamped() -> None:
    assert IngestRunResult(run_id=7).summary().startswith("run 7 (not stamped)")


def test_summary_lists_what_discovery_dropped_and_what_each_stage_failed() -> None:
    result = IngestRunResult(run_id=7, dropped=["z"])
    result.documents.append(failed_doc(Stage.FETCH, "a", "ConnectionError: 404"))
    result.documents.append(failed_doc(Stage.PARSE, "b"))
    result.embed.fail("c", ParseError("provider down"), chunks=1)

    assert "  discover dropped: z" in result.summary()
    assert "  fetch failed: a (ConnectionError: 404)" in result.summary()
    assert "  parse failed: b (ParseError: no body)" in result.summary()
    assert "  embed failed: c (1 chunk: ParseError: provider down)" in result.summary()


def test_updated_chunks_are_summed_across_documents(run: IngestRunResult) -> None:
    run.documents.append(
        DocumentOutcome(
            celex="d", topic="mrv", change=DocChange.UPDATED, chunks=ChunkCounts(updated=4)
        )
    )
    assert run.chunks.updated == 4
