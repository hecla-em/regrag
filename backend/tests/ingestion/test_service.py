"""Ingestion rows and corpus-wide reads: run lifecycle, the version, and the prune's keep-set."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.enums import IngestRunStatus
from app.ingestion.schemas import IngestRun
from app.ingestion.service import (
    corpus_fingerprint,
    next_corpus_version,
)

pytestmark = pytest.mark.anyio


async def test_unchanged_corpus_keeps_the_previous_version(db_session: AsyncSession, make_document):
    run = IngestRun(status=IngestRunStatus.SUCCESS)
    doc = make_document(run, "32015R0757")
    stamped = IngestRun(
        status=IngestRunStatus.SUCCESS,
        corpus_version=f"2020-01-01-{corpus_fingerprint([doc])}",
    )
    db_session.add_all([doc, stamped])
    await db_session.flush()

    assert await next_corpus_version(db_session) == stamped.corpus_version


async def test_version_covers_topics_the_run_did_not_fetch(db_session: AsyncSession, make_document):
    """Re-fetching one topic must not mint a version describing only that topic."""
    first = IngestRun(status=IngestRunStatus.SUCCESS)
    db_session.add_all(
        [
            make_document(first, "32015R0757", topic="mrv"),
            make_document(first, "32023R1805", topic="fueleu"),
        ]
    )
    await db_session.flush()
    whole_corpus = await next_corpus_version(db_session)

    second = IngestRun(status=IngestRunStatus.SUCCESS)
    db_session.add(make_document(second, "32015R0757", topic="mrv"))
    await db_session.flush()

    assert await next_corpus_version(db_session) == whole_corpus
