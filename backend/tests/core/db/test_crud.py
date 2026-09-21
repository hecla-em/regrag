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


async def test_update_record_leaves_updated_at_loaded(db_session: AsyncSession):
    """The server-side onupdate arrives via RETURNING; lazy-loading it raises MissingGreenlet."""
    run = await create_record(db_session, IngestRun(status=IngestRunStatus.RUNNING))
    await update_record(db_session, run, CorpusVersionUpdate(corpus_version="2026-08-04-abc1234"))
    assert "updated_at" not in inspect(run).unloaded
    assert run.updated_at is not None


@pytest.mark.parametrize(
    ("update", "expected"),
    [
        pytest.param(CorpusVersionUpdate(corpus_version="v2"), "v2", id="a given field is applied"),
        pytest.param(CorpusVersionUpdate(), "v1", id="an omitted field is left alone"),
        pytest.param(CorpusVersionUpdate(corpus_version=None), None, id="an explicit None nulls"),
    ],
)
async def test_update_record_tells_an_omitted_field_from_an_explicit_none(
    db_session: AsyncSession, update: CorpusVersionUpdate, expected: str | None
):
    run = IngestRun(status=IngestRunStatus.RUNNING, corpus_version="v1")
    await create_record(db_session, run)

    await update_record(db_session, run, update)

    assert run.corpus_version == expected
    assert run.status is IngestRunStatus.RUNNING
