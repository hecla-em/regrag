"""Retrieval fixtures: every test reads the stored corpus through the toy embedder."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.ingestion.chunk.schemas import DocumentChunk
from tests.conftest import rolled_back_session


@pytest.fixture
async def db_session(
    db_engine: AsyncEngine, corpus: list[DocumentChunk]
) -> AsyncGenerator[AsyncSession, None]:
    """Retrieval reads the committed corpus, so its session must not clear it away."""
    async with rolled_back_session(db_engine, clear=False) as session:
        yield session


@pytest.fixture(autouse=True)
def toy_retrieval(query_embeddings: None, identity_rerank: None) -> None:
    """Every retrieval test searches in the corpus's own vector space, in fused order."""
