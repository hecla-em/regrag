"""Generic persistence helpers."""

import pytest
from pydantic import BaseModel
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.crud import create_record, update_record
from app.ingestion.enums import IngestRunStatus
from app.ingestion.schemas import IngestRun

pytestmark = pytest.mark.anyio


class CorpusVersionUpdate(BaseModel):
    """Throwaway update model standing in for a domain's own."""

    corpus_version: str | None = None


async def test_update_record_applies_only_given_fields(db_session: AsyncSession):
    run = await create_record(db_session, IngestRun(status=IngestRunStatus.RUNNING))
    await update_record(db_session, run, CorpusVersionUpdate(corpus_version="2026-08-04-abc1234"))
    assert run.corpus_version == "2026-08-04-abc1234"
    assert run.status is IngestRunStatus.RUNNING


async def test_update_record_leaves_updated_at_loaded(db_session: AsyncSession):
    """The server-side onupdate arrives via RETURNING; lazy-loading it raises MissingGreenlet."""
    run = await create_record(db_session, IngestRun(status=IngestRunStatus.RUNNING))
    await update_record(db_session, run, CorpusVersionUpdate(corpus_version="2026-08-04-abc1234"))
    assert "updated_at" not in inspect(run).unloaded
    assert run.updated_at is not None


async def test_update_record_ignores_omitted_fields(db_session: AsyncSession):
    run = IngestRun(status=IngestRunStatus.RUNNING, corpus_version="v1")
    await create_record(db_session, run)
    await update_record(db_session, run, CorpusVersionUpdate())
    assert run.corpus_version == "v1"


async def test_update_record_nulls_explicitly_passed_none(db_session: AsyncSession):
    run = IngestRun(status=IngestRunStatus.RUNNING, corpus_version="v1")
    await create_record(db_session, run)
    await update_record(db_session, run, CorpusVersionUpdate(corpus_version=None))
    assert run.corpus_version is None
