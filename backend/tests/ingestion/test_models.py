"""One ingest run's outcome: what it counts, the row it stores, the summary the CLI prints."""

import pytest

from app.ingestion.chunk.models import ChunkCounts
from app.ingestion.enums import DocChange, Stage
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


def test_report_covers_every_stage_with_its_counts_and_failures(run: IngestRunResult) -> None:
    run.dropped = ["z"]
    run.documents.append(failed_doc(Stage.PARSE, "c"))
    run.embed.embedded = 12

    assert run.report() == {
        "discover": {"documents": 2, "dropped": 1, "failed": {}},
        "fetch": {"documents": 2, "new": 1, "updated": 0, "reused": 1, "failed": {}},
        "parse": {
            "documents": 3,
            "parsed": 2,
            "images_read": 0,
            "images_reused": 0,
            "failed": {"c": "ParseError: no body"},
        },
        "chunk": {"chunks": 42, "added": 12, "deleted": 0, "kept": 30, "updated": 0, "failed": {}},
        "embed": {"chunks": 12, "embedded": 12, "already_embedded": 0, "failed": {}},
    }
