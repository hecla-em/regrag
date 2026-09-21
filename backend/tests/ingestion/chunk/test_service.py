"""Chunk persistence: reconciling a document's chunks by content hash."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import EMBED_DIMENSIONS
from app.ingestion.chunk.models import Chunk, Reference
from app.ingestion.chunk.references import extract_references
from app.ingestion.chunk.service import (
    cited_celexes,
    prune_chunks,
    sync_document_chunks,
)
from app.ingestion.enums import CITED_TOPIC
from app.ingestion.exceptions import EmptyChunkSetError
from app.ingestion.schemas import IngestRun
from tests.conftest import chunk, chunk_rows

pytestmark = pytest.mark.anyio

VECTOR = [0.1] * EMBED_DIMENSIONS


async def sync(session: AsyncSession, run: IngestRun, *chunks: Chunk, celex: str = "32023R1805"):
    """Reconcile one document's chunks: every test here spells the same four arguments."""
    return await sync_document_chunks(
        session, celex=celex, chunks=list(chunks), ingest_run_id=run.id
    )


async def test_edited_chunk_is_replaced_not_duplicated(
    db_session: AsyncSession, ingest_run: IngestRun, later_run: IngestRun
):
    await sync(db_session, ingest_run, chunk())

    result = await sync(db_session, later_run, chunk(text="Reworded entirely."))

    assert (result.added, result.deleted, result.kept) == (1, 1, 0)
    rows = await chunk_rows(db_session)
    assert [row.text for row in rows] == ["Reworded entirely."]
    assert rows[0].ingest_run_id == later_run.id


async def test_upserting_nothing_over_a_stored_document_raises_and_keeps_the_rows(
    db_session: AsyncSession, ingest_run: IngestRun
):
    """A document that parsed to no chunks is a parse that went wrong, not a repeal."""
    await sync(db_session, ingest_run, chunk())

    with pytest.raises(EmptyChunkSetError, match="32023R1805"):
        await sync(db_session, ingest_run)

    assert len(await chunk_rows(db_session, "32023R1805")) == 1


async def test_duplicate_chunks_persist_as_separate_occurrences(
    db_session: AsyncSession, ingest_run: IngestRun
):
    result = await sync(db_session, ingest_run, chunk(), chunk())
    assert result.added == 2
    assert sorted(row.occurrence for row in await chunk_rows(db_session)) == [0, 1]


async def test_inserting_a_chunk_renumbers_the_ones_after_it(
    db_session: AsyncSession, ingest_run: IngestRun, later_run: IngestRun
):
    await sync(
        db_session, ingest_run, chunk(position=0), chunk(paragraph="2", text="Second.", position=1)
    )

    result = await sync(
        db_session,
        later_run,
        chunk(position=0),
        chunk(paragraph="1a", text="Inserted.", position=1),
        chunk(paragraph="2", text="Second.", position=2),
    )

    rows = await chunk_rows(db_session)
    assert {row.paragraph: row.position for row in rows} == {"1": 0, "1a": 1, "2": 2}
    assert (result.added, result.updated, result.kept) == (1, 1, 1)


async def test_matched_row_with_changed_references_is_updated_in_place(
    db_session: AsyncSession, ingest_run: IngestRun, later_run: IngestRun
):
    """Same text, corrected extraction: the row updates without losing its embedding."""
    await sync(db_session, ingest_run, chunk())
    before = (await chunk_rows(db_session))[0]
    before_id = before.id
    before.embedding = VECTOR
    await db_session.flush()

    corrected = chunk(references=extract_references("as set out in Annex I"))
    result = await sync(db_session, later_run, corrected)

    assert (result.added, result.deleted, result.kept, result.updated) == (0, 0, 0, 1)
    row = (await chunk_rows(db_session))[0]
    assert row.id == before_id
    assert row.references[0]["annex"] == "I"
    assert row.embedding is not None
    assert row.ingest_run_id == ingest_run.id


async def test_prune_chunks_refuses_to_wipe_everything_when_nothing_is_kept(
    db_session: AsyncSession, ingest_run: IngestRun
):
    await sync(db_session, ingest_run, chunk())
    assert await prune_chunks(db_session, []) == 0
    assert len(await chunk_rows(db_session)) == 1


async def test_the_prune_survives_a_rollback_that_follows_it(
    db_session: AsyncSession, ingest_run: IngestRun
):
    """Committed where the deleting happens, so a later abort cannot quietly restore them.

    The run reports the count either way; leaving them pending would let it report deletes
    that a rollback had already undone.
    """
    for celex in ("repealed", "32023R1805"):
        await sync(db_session, ingest_run, chunk(celex=celex), celex=celex)

    assert await prune_chunks(db_session, ["32023R1805"]) == 1
    await db_session.rollback()

    assert {row.celex for row in await chunk_rows(db_session)} == {"32023R1805"}


async def test_cited_celexes_are_the_instruments_a_division_is_cited_of(
    db_session: AsyncSession, ingest_run: IngestRun
):
    await sync(
        db_session,
        ingest_run,
        chunk(
            references=[
                Reference(
                    raw="Article 7 of Directive (EU) 2018/2001",
                    instrument="32018L2001",
                    article="7",
                )
            ]
        ),
        chunk(
            references=[
                Reference(
                    raw="Annex II to Regulation (EC) No 765/2008",
                    instrument="32008R0765",
                    annex="II",
                )
            ],
            article="5",
        ),
    )
    assert await cited_celexes(db_session) == {"32018L2001", "32008R0765"}


async def test_an_instrument_named_whole_is_not_cited(
    db_session: AsyncSession, ingest_run: IngestRun
):
    """A recital naming an act without a division gives follow_reference nothing to look up."""
    await sync(
        db_session,
        ingest_run,
        chunk(references=[Reference(raw="Regulation (EU) 2020/852", instrument="32020R0852")]),
    )
    assert await cited_celexes(db_session) == set()


async def test_a_division_of_this_act_is_not_a_citation_of_another(
    db_session: AsyncSession, ingest_run: IngestRun
):
    await sync(db_session, ingest_run, chunk(references=[Reference(raw="Article 7", article="7")]))
    assert await cited_celexes(db_session) == set()


async def test_what_a_hop_document_cites_is_not_cited(
    db_session: AsyncSession, ingest_run: IngestRun
):
    """Reading the hop's own citations would follow the graph one step further every run."""
    await sync(
        db_session,
        ingest_run,
        chunk(
            references=[
                Reference(
                    raw="Article 7 of Directive 2010/75/EU", instrument="32010L0075", article="7"
                )
            ],
            topic=CITED_TOPIC,
            celex="32018L2001",
        ),
        celex="32018L2001",
    )
    assert await cited_celexes(db_session) == set()
