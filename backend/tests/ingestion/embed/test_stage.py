"""The embed stage: how it sweeps, what it retries, and what a failure costs."""

import asyncio

import pytest
from sqlalchemy import select

from app.core.config import EMBED_DIMENSIONS, config
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


async def test_a_failed_batch_is_recorded_against_its_document(
    db_session, ingest_run, make_chunk_row, embeddings
):
    embeddings.errors[1] = LLMError("embedding call failed")
    db_session.add_all(rows(make_chunk_row, ingest_run, "32023R1805", 2))
    await db_session.flush()

    result = await embed_chunks(db_session)

    assert result.embedded == 0
    assert result.failures == {"32023R1805": "2 chunks: LLMError: embedding call failed"}


async def test_every_failed_batch_of_a_document_counts_towards_its_loss(
    db_session, ingest_run, make_chunk_row, embeddings
):
    """A document spanning several batches reports every chunk it lost, not just the last one's."""
    embeddings.errors[1] = LLMError("embedding call failed")
    embeddings.errors[2] = LLMError("embedding call failed")
    db_session.add_all(rows(make_chunk_row, ingest_run, "32023R1805", 200))
    await db_session.flush()

    result = await embed_chunks(db_session)

    assert result.embedded == 0
    assert result.failures == {"32023R1805": "200 chunks: LLMError: embedding call failed"}


async def test_one_document_failing_does_not_stop_the_others(
    db_session, ingest_run, make_chunk_row, embeddings
):
    """Ordering is by celex, so 32015R0757's batch is call 1 and 32023R1805's is call 2."""
    embeddings.errors[1] = LLMError("embedding call failed")
    db_session.add_all(rows(make_chunk_row, ingest_run, "32015R0757", 1))
    db_session.add_all(rows(make_chunk_row, ingest_run, "32023R1805", 1))
    await db_session.flush()

    result = await embed_chunks(db_session)

    assert list(result.failed) == ["32015R0757"]
    assert result.embedded == 1


async def test_a_later_batch_failing_keeps_the_earlier_batches_vectors(
    db_session, ingest_run, make_chunk_row, embeddings
):
    """Each batch commits alone, so work already done survives a failure further in."""
    embeddings.errors[2] = LLMError("embedding call failed")
    db_session.add_all(rows(make_chunk_row, ingest_run, "32023R1805", 200))
    await db_session.flush()

    result = await embed_chunks(db_session)

    assert [len(call) for call in embeddings.calls] == [128, 72]
    assert result.embedded == 128
    assert list(result.failed) == ["32023R1805"]
    assert len(await get_chunks(db_session, ChunkQuery(has_embedding=False, limit=100))) == 72


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


def overlap_tracker(peaks: list[int]):
    """An embed stub that records how many calls are in flight when each call runs."""
    active = 0

    async def tracking(texts, *, input_type):
        nonlocal active
        active += 1
        await asyncio.sleep(0)
        peaks.append(active)
        active -= 1
        return [[0.0] * EMBED_DIMENSIONS] * len(texts)

    return tracking
