"""Roundtrip tests for the document chunks table."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import EMBED_DIMENSIONS
from app.ingestion.chunk.schemas import DocumentChunk
from app.ingestion.enums import SectionKind

pytestmark = pytest.mark.anyio


async def test_document_chunk_roundtrip(db_session: AsyncSession, ingest_run, make_chunk_row):
    chunk = make_chunk_row(ingest_run, article="4", paragraph="1", citation="Article 4(1)")
    db_session.add(chunk)
    await db_session.flush()
    db_session.expire_all()

    fetched = (await db_session.scalars(select(DocumentChunk))).one()
    assert fetched.citation == "Article 4(1)"
    assert fetched.kind is SectionKind.PARAGRAPH
    assert fetched.heading_path == ["Chapter I", "Section 2"]
    assert fetched.references == [{"raw": "Annex I", "annex": "I"}]
    assert fetched.created_at is not None


async def test_document_chunk_carries_the_title_of_its_act(
    db_session: AsyncSession, ingest_run, make_chunk_row
):
    db_session.add(
        make_chunk_row(ingest_run, act_title="Regulation (EU) 2023/1805 on renewable fuels")
    )
    await db_session.flush()
    db_session.expire_all()

    fetched = (await db_session.scalars(select(DocumentChunk))).one()
    assert fetched.act_title == "Regulation (EU) 2023/1805 on renewable fuels"


async def test_chunk_identity_unique_per_document(
    db_session: AsyncSession, ingest_run, make_chunk_row
):
    db_session.add(make_chunk_row(ingest_run))
    db_session.add(make_chunk_row(ingest_run))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_same_hash_at_a_later_occurrence_is_allowed(
    db_session: AsyncSession, ingest_run, make_chunk_row
):
    db_session.add(make_chunk_row(ingest_run, occurrence=0))
    db_session.add(make_chunk_row(ingest_run, occurrence=1))
    await db_session.flush()

    assert len((await db_session.scalars(select(DocumentChunk))).all()) == 2


async def test_a_new_chunk_has_no_vector_until_the_embed_stage_fills_it(
    db_session, ingest_run, make_chunk_row
):
    row = make_chunk_row(ingest_run)
    db_session.add(row)
    await db_session.flush()

    assert row.embedding is None


async def test_search_vector_is_generated_from_the_chunk_without_being_written(
    db_session, ingest_run, make_chunk_row
):
    """Postgres derives it, so it exists after a flush nothing set it in."""
    row = make_chunk_row(ingest_run, citation="Article 4(1)", text="Greenhouse gas intensity.")
    db_session.add(row)
    await db_session.flush()
    await db_session.refresh(row)

    assert "intens" in row.search_vector
    assert "'articl':1A" in row.search_vector


async def test_search_vector_follows_the_text_it_derives_from(
    db_session, ingest_run, make_chunk_row
):
    row = make_chunk_row(ingest_run, text="Verification of compliance.")
    db_session.add(row)
    await db_session.flush()

    row.text = "Penalties for non-compliance."
    await db_session.flush()
    await db_session.refresh(row)

    assert "penalti" in row.search_vector
    assert "verif" not in row.search_vector


async def test_the_migrated_column_is_as_wide_as_the_embeddings_we_ask_for(
    db_session: AsyncSession,
):
    """A constant wider than the column embeds a whole run the database then refuses to store."""
    column_type = await db_session.scalar(
        text(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute"
            " WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
        )
    )

    assert column_type == f"vector({EMBED_DIMENSIONS})"


async def test_a_vector_of_the_wrong_width_is_rejected(db_session, ingest_run, make_chunk_row):
    db_session.add(make_chunk_row(ingest_run, embedding=[0.1] * 512))

    with pytest.raises(DBAPIError):
        await db_session.flush()
