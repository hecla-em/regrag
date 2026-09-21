"""The embed stage: how it sweeps, what it retries, and what a failure costs."""

import pytest
from sqlalchemy import select

from app.core.config import config
from app.core.llm.errors import LLMError
from app.ingestion.chunk.models import ChunkQuery
from app.ingestion.chunk.schemas import DocumentChunk
from app.ingestion.chunk.service import get_chunks
from app.ingestion.embed.stage import embed_chunks

pytestmark = pytest.mark.anyio


def rows(make_chunk_row, run, celex: str, count: int, start: int = 0):
    """`count` chunk rows for one document, each with a distinct content hash."""
    return [
        make_chunk_row(run, celex=celex, content_hash=f"{celex}-{index + start}".ljust(64, "x"))
        for index in range(count)
    ]


async def test_vectors_land_on_the_rows_in_input_order(db_session, ingest_run, make_chunk_row):
    """The stub numbers vectors 0..n within a batch, so a mis-zip shows up as a shuffle."""
    db_session.add_all(rows(make_chunk_row, ingest_run, "32023R1805", 3))
    await db_session.flush()

    await embed_chunks(db_session)

    stored = await db_session.scalars(select(DocumentChunk.embedding).order_by(DocumentChunk.id))
    assert [vector[0] for vector in stored.all()] == [0.0, 1.0, 2.0]


async def test_a_failed_batch_costs_its_document_only_the_chunks_in_it(
    db_session, ingest_run, make_chunk_row, embeddings
):
    """Batches never span documents and each commits alone. Ordering is by celex, so calls 1
    to 3 are 32015R0757's batches and call 4 is 32023R1805's."""
    embeddings.errors[2] = LLMError("embedding call failed")
    embeddings.errors[3] = LLMError("embedding call failed")
    db_session.add_all(rows(make_chunk_row, ingest_run, "32015R0757", 300))
    db_session.add_all(rows(make_chunk_row, ingest_run, "32023R1805", 1))
    await db_session.flush()

    result = await embed_chunks(db_session)

    assert [len(call) for call in embeddings.calls] == [128, 128, 44, 1]
    assert result.embedded == 129
    assert {celex: failure.chunks for celex, failure in result.failed.items()} == {
        "32015R0757": 172
    }
    vectorless = await get_chunks(db_session, ChunkQuery(has_embedding=False, limit=500))
    assert [chunk.celex for chunk in vectorless] == ["32015R0757"] * 172


async def test_a_corpus_larger_than_one_page_ends_with_every_chunk_embedded(
    db_session, ingest_run, make_chunk_row, monkeypatch
):
    """The sweep writes vectors as it reads, so the cursor must not skip rows beneath it."""
    monkeypatch.setattr(config, "EMBED_PAGE_SIZE", 2)
    db_session.add_all(rows(make_chunk_row, ingest_run, "32023R1805", 7))
    await db_session.flush()

    result = await embed_chunks(db_session)

    assert result.embedded == 7
    assert await get_chunks(db_session, ChunkQuery(has_embedding=False, limit=100)) == []


async def test_a_batch_that_keeps_failing_does_not_loop_the_sweep(
    db_session, ingest_run, make_chunk_row, monkeypatch
):
    """A failed chunk stays vectorless, so a cursor that did not advance would never finish."""
    sizes: list[int] = []

    async def always_fails(texts, input_type):
        sizes.append(len(texts))
        raise LLMError("provider down")

    monkeypatch.setattr("app.ingestion.embed.batch.embed", always_fails)
    monkeypatch.setattr(config, "EMBED_PAGE_SIZE", 2)
    db_session.add_all(rows(make_chunk_row, ingest_run, "32023R1805", 5))
    await db_session.flush()

    result = await embed_chunks(db_session)

    assert sizes == [2, 2, 1]
    assert result.embedded == 0
    assert list(result.failed) == ["32023R1805"]
