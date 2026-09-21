"""Retrieval fixtures: a stored corpus, embedded by a deterministic stand-in for Voyage."""

import re
import zlib
from collections.abc import AsyncGenerator, Iterator
from functools import cache
from math import sqrt
from typing import Any

import anyio
import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import EMBED_DIMENSIONS
from app.core.db.session import async_session_factory
from app.ingestion.chunk.schemas import DocumentChunk
from app.ingestion.chunk.service import sync_document_chunks
from app.ingestion.chunk.tree import chunk_document
from app.ingestion.enums import IngestRunStatus
from app.ingestion.parse.models import ParsedDocument
from app.ingestion.schemas import IngestRun
from app.retrieval.models import SearchResult
from tests.conftest import rolled_back_session

TOKEN = re.compile(r"\w+")
PROBES = 64
"""Dimensions each token contributes to: a one-hot token would leave most texts exactly
orthogonal, which gives an HNSW graph walk no gradient to descend."""


@cache
def token_probes(token: str) -> tuple[int, ...]:
    """The dimensions a token lands on, spread wide so any two texts overlap somewhere."""
    return tuple(
        zlib.crc32(f"{token}:{probe}".encode()) % EMBED_DIMENSIONS for probe in range(PROBES)
    )


def toy_embed(text: str) -> list[float]:
    """Token hashes into the real width, L2-normalised, so overlapping texts land near."""
    vector = [0.0] * EMBED_DIMENSIONS
    for token in TOKEN.findall(text.lower()):
        for index in token_probes(token):
            vector[index] += 1.0
    norm = sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


async def vacuum_chunks(db_engine: AsyncEngine) -> None:
    """Reclaim the HNSW entries every rolled-back insert left behind, as autovacuum does live."""
    autocommit = db_engine.execution_options(isolation_level="AUTOCOMMIT")
    async with autocommit.connect() as conn:
        await conn.execute(text("VACUUM document_chunks"))


async def delete_runs(db_engine: AsyncEngine, ingest_run_id: int | None = None) -> None:
    """Committed delete of one run or every run, cascading to the chunks hanging off it."""
    stmt = delete(IngestRun)
    if ingest_run_id is not None:
        stmt = stmt.where(IngestRun.id == ingest_run_id)
    async with async_session_factory(bind=db_engine) as session:
        await session.execute(stmt)
        await session.commit()


async def store_corpus(
    db_engine: AsyncEngine, fueleu: ParsedDocument, mrv: ParsedDocument
) -> list[DocumentChunk]:
    """Chunk, store and embed both fixture acts, committed so every test reads the same rows."""
    await delete_runs(db_engine)
    await vacuum_chunks(db_engine)
    async with async_session_factory(bind=db_engine) as session:
        run = IngestRun(status=IngestRunStatus.RUNNING)
        session.add(run)
        await session.flush()
        for document in (fueleu, mrv):
            await sync_document_chunks(
                session,
                celex=document.celex,
                chunks=chunk_document(document),
                ingest_run_id=run.id,
            )
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.ingest_run_id == run.id)
            .order_by(DocumentChunk.id)
        )
        rows = list(await session.scalars(stmt))
        for row in rows:
            row.embedding = toy_embed(row.text)
        await session.commit()
        session.expunge_all()
        return rows


@pytest.fixture(scope="session")
def corpus(
    db_engine: AsyncEngine, fueleu: ParsedDocument, mrv: ParsedDocument
) -> Iterator[list[DocumentChunk]]:
    """Both fixture acts stored once for the whole session, since retrieval only ever reads them."""
    rows = anyio.run(store_corpus, db_engine, fueleu, mrv)
    yield rows
    anyio.run(delete_runs, db_engine, rows[0].ingest_run_id)


@pytest.fixture
async def db_session(
    db_engine: AsyncEngine, corpus: list[DocumentChunk]
) -> AsyncGenerator[AsyncSession, None]:
    """Retrieval reads the committed corpus, so its session must not clear it away."""
    async with rolled_back_session(db_engine, clear=False) as session:
        yield session


@pytest.fixture(autouse=True)
def query_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Query vectors share the corpus's space, so a search is a real nearest-neighbour test."""

    async def _embed(texts: list[str], **kwargs: Any) -> list[list[float]]:
        return [toy_embed(text) for text in texts]

    monkeypatch.setattr("app.retrieval.search.embed", _embed)


@pytest.fixture(autouse=True)
def identity_rerank(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordering tests assert on fused order, so the rerank stand-in must preserve it."""

    async def _identity(
        query: str, results: tuple[SearchResult, ...], *, limit: int
    ) -> tuple[SearchResult, ...]:
        return results[:limit]

    monkeypatch.setattr("app.retrieval.search.rerank_results", _identity)
