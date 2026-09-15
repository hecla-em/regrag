"""Roundtrip tests for the raw documents table."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.enums import IngestRunStatus
from app.ingestion.fetch.schemas import RawDocument
from app.ingestion.schemas import IngestRun

pytestmark = pytest.mark.anyio


async def test_document_belongs_to_run(db_session: AsyncSession, make_document):
    run = IngestRun(status=IngestRunStatus.SUCCESS, corpus_version="2026-08-03-abc1234")
    doc = make_document(run)
    db_session.add(doc)
    await db_session.flush()

    assert doc.ingest_run_id == run.id
    assert doc.run.corpus_version == "2026-08-03-abc1234"


async def test_document_celex_unique_per_run(db_session: AsyncSession, make_document):
    run = IngestRun(status=IngestRunStatus.RUNNING)
    db_session.add(make_document(run))
    db_session.add(make_document(run))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_document_carries_topic(db_session: AsyncSession, make_document):
    run = IngestRun(status=IngestRunStatus.RUNNING)
    doc = make_document(run, topic="fueleu")
    db_session.add(doc)
    await db_session.flush()

    assert doc.topic == "fueleu"


async def test_document_carries_its_title(db_session: AsyncSession, make_document):
    title = "Regulation (EU) 2023/1805 on the use of renewable and low-carbon fuels"
    doc = make_document(IngestRun(status=IngestRunStatus.RUNNING), title=title)
    db_session.add(doc)
    await db_session.flush()
    db_session.expire_all()

    fetched = (await db_session.scalars(select(RawDocument))).one()
    assert fetched.title == title
