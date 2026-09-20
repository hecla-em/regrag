"""Chunk persistence: reconciling a document's chunks by content hash."""

from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import EMBED_DIMENSIONS
from app.ingestion.chunk.models import Chunk, ChunkQuery, Reference
from app.ingestion.chunk.references import extract_references
from app.ingestion.chunk.service import (
    _key_incoming_chunks,
    cited_celexes,
    count_chunks,
    create_chunks,
    delete_chunks,
    get_chunks,
    prune_chunks,
    seed_celexes,
    sync_document_chunks,
    update_chunks,
)
from app.ingestion.enums import CITED_TOPIC, SectionKind
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


async def test_first_upsert_inserts_every_chunk(db_session: AsyncSession, ingest_run: IngestRun):
    result = await sync(db_session, ingest_run, chunk(), chunk(article="5"))
    assert (result.added, result.deleted, result.kept) == (2, 0, 0)
    assert len(await chunk_rows(db_session)) == 2


async def test_repeat_upsert_changes_nothing(db_session: AsyncSession, ingest_run: IngestRun):
    chunks = [chunk(), chunk(article="5")]
    await sync(db_session, ingest_run, *chunks)
    before = {row.id for row in await chunk_rows(db_session)}

    result = await sync(db_session, ingest_run, *chunks)

    assert (result.added, result.deleted, result.kept, result.updated) == (0, 0, 2, 0)
    assert {row.id for row in await chunk_rows(db_session)} == before


async def test_matched_rows_keep_the_run_they_first_appeared_in(
    db_session: AsyncSession, ingest_run: IngestRun, later_run: IngestRun
):
    await sync(db_session, ingest_run, chunk())
    await sync(db_session, later_run, chunk())

    assert [row.ingest_run_id for row in await chunk_rows(db_session)] == [ingest_run.id]


async def test_edited_chunk_is_replaced_not_duplicated(
    db_session: AsyncSession, ingest_run: IngestRun, later_run: IngestRun
):
    await sync(db_session, ingest_run, chunk())

    result = await sync(db_session, later_run, chunk(text="Reworded entirely."))

    assert (result.added, result.deleted, result.kept) == (1, 1, 0)
    rows = await chunk_rows(db_session)
    assert [row.text for row in rows] == ["Reworded entirely."]
    assert rows[0].ingest_run_id == later_run.id


async def test_upsert_touches_only_its_own_document(
    db_session: AsyncSession, ingest_run: IngestRun
):
    await sync(db_session, ingest_run, chunk(celex="32015R0757"), celex="32015R0757")
    await sync(db_session, ingest_run, chunk())

    await sync(db_session, ingest_run, chunk(text="Reworded entirely."))

    assert [row.text for row in await chunk_rows(db_session, "32015R0757")] == [
        "The greenhouse gas intensity limit."
    ]
    assert [row.text for row in await chunk_rows(db_session, "32023R1805")] == [
        "Reworded entirely."
    ]


async def test_upserting_nothing_over_a_stored_document_raises_and_keeps_the_rows(
    db_session: AsyncSession, ingest_run: IngestRun
):
    """A document that parsed to no chunks is a parse that went wrong, not a repeal."""
    await sync(db_session, ingest_run, chunk())

    with pytest.raises(EmptyChunkSetError, match="32023R1805"):
        await sync(db_session, ingest_run)

    assert len(await chunk_rows(db_session, "32023R1805")) == 1


async def test_upserting_nothing_over_a_document_with_no_rows_is_not_an_error(
    db_session: AsyncSession, ingest_run: IngestRun
):
    """Nothing to lose, so nothing to refuse; the document simply contributed no chunks."""
    result = await sync(db_session, ingest_run)
    assert (result.added, result.deleted, result.kept) == (0, 0, 0)


async def test_duplicate_chunks_persist_as_separate_occurrences(
    db_session: AsyncSession, ingest_run: IngestRun
):
    result = await sync(db_session, ingest_run, chunk(), chunk())
    assert result.added == 2
    assert sorted(row.occurrence for row in await chunk_rows(db_session)) == [0, 1]


async def test_chunk_fields_are_mapped_onto_the_row(
    db_session: AsyncSession, ingest_run: IngestRun
):
    await sync(
        db_session,
        ingest_run,
        chunk(heading_path=("Chapter I",), annex=None, part=2, parts=3, points=("a",)),
    )
    row = (await chunk_rows(db_session))[0]
    assert row.topic == "fueleu"
    assert row.citation == "Article 4(1)"
    assert row.heading_path == ["Chapter I"]
    assert row.points == ["a"]
    assert (row.part, row.parts) == (2, 3)
    assert row.kind is SectionKind.PARAGRAPH


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


async def test_position_holds_document_order_once_ids_no_longer_do(
    db_session: AsyncSession, ingest_run: IngestRun, later_run: IngestRun
):
    """An annex has no (paragraph, part) to sort by, and a re-ingest moves the changed chunk's
    id to the end of the sequence."""
    annex = [
        chunk(article=None, annex="I", paragraph=None, text=text, position=index)
        for index, text in enumerate(["First.", "Second.", "Third."])
    ]
    await sync(db_session, ingest_run, *annex)

    amended = [annex[0], annex[1].model_copy(update={"text": "Second, amended."}), annex[2]]
    await sync(db_session, later_run, *amended)

    rows = sorted(await chunk_rows(db_session), key=lambda row: row.position)
    assert [row.text for row in rows] == ["First.", "Second, amended.", "Third."]
    assert [row.id for row in rows] != sorted(row.id for row in rows)


async def test_references_are_stored_as_json(db_session: AsyncSession, ingest_run: IngestRun):
    text = "As set out in Annex I to this Regulation."
    await sync(db_session, ingest_run, chunk(text=text, references=extract_references(text)))
    row = (await chunk_rows(db_session))[0]
    assert row.references
    assert row.references[0]["annex"] == "I"


async def seed_two_topics(session: AsyncSession, run: IngestRun) -> None:
    """One fueleu document and one mrv document, a chunk each."""
    await sync(session, run, chunk())
    await sync(session, run, chunk(celex="32015R0757", topic="mrv"), celex="32015R0757")


def test_occurrence_counts_up_for_duplicates():
    keys = list(_key_incoming_chunks([chunk(), chunk(), chunk()]))
    assert [n for _, n in keys] == [0, 1, 2]
    assert len({digest for digest, _ in keys}) == 1


def test_distinct_chunks_each_start_at_occurrence_zero():
    keys = list(_key_incoming_chunks([chunk(), chunk(article="5")]))
    assert [n for _, n in keys] == [0, 0]
    assert len({digest for digest, _ in keys}) == 2


def test_content_keys_hold_the_original_chunks_in_order():
    chunks = [chunk(), chunk(article="5")]
    assert list(_key_incoming_chunks(chunks).values()) == chunks


async def test_returns_only_the_chunks_without_a_vector(db_session, ingest_run, make_chunk_row):
    db_session.add(make_chunk_row(ingest_run, content_hash="a" * 64))
    db_session.add(make_chunk_row(ingest_run, content_hash="b" * 64, embedding=VECTOR))
    await db_session.flush()

    pending = await get_chunks(db_session, ChunkQuery(has_embedding=False, limit=100))

    assert [row.content_hash for row in pending] == ["a" * 64]


async def test_orders_by_document_then_insertion(db_session, ingest_run, make_chunk_row):
    """groupby in the stage only groups adjacent rows, so this ordering is load-bearing."""
    for celex, digest in [("32023R1805", "a"), ("32015R0757", "b"), ("32023R1805", "c")]:
        db_session.add(make_chunk_row(ingest_run, celex=celex, content_hash=digest * 64))
    await db_session.flush()

    pending = await get_chunks(db_session, ChunkQuery(has_embedding=False, limit=100))

    assert [row.celex for row in pending] == ["32015R0757", "32023R1805", "32023R1805"]
    assert [row.content_hash[0] for row in pending] == ["b", "a", "c"]


async def test_counts_only_the_chunks_that_carry_a_vector(db_session, ingest_run, make_chunk_row):
    db_session.add(make_chunk_row(ingest_run, content_hash="a" * 64))
    db_session.add(make_chunk_row(ingest_run, content_hash="b" * 64, embedding=VECTOR))
    db_session.add(make_chunk_row(ingest_run, content_hash="c" * 64, embedding=VECTOR))
    await db_session.flush()

    assert await count_chunks(db_session, has_embedding=True) == 2


async def test_counts_zero_on_an_empty_table(db_session):
    assert await count_chunks(db_session, has_embedding=True) == 0


async def test_reconciling_does_not_load_the_stored_text(
    db_engine, db_session: AsyncSession, ingest_run: IngestRun, later_run: IngestRun
):
    """Matching is on hashes, so the read must not drag every stored chunk's text back with it."""
    await sync(db_session, ingest_run, chunk())
    selects: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "document_chunks" in statement:
            selects.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", record)
    try:
        await sync(db_session, later_run, chunk())
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", record)

    assert selects
    assert not any("document_chunks.text" in statement for statement in selects)


async def test_stored_chunk_records_its_metadata_hash(
    db_session: AsyncSession, ingest_run: IngestRun
):
    await sync(db_session, ingest_run, chunk())
    assert (await chunk_rows(db_session))[0].metadata_hash == chunk().metadata_hash


async def test_row_without_a_metadata_hash_is_updated_and_backfilled(
    db_session: AsyncSession, ingest_run: IngestRun
):
    """Rows from before the column exists read as drifted, so the next sync fills them in."""
    await sync(db_session, ingest_run, chunk())
    (await chunk_rows(db_session))[0].metadata_hash = None
    await db_session.flush()

    result = await sync(db_session, ingest_run, chunk())

    assert (result.kept, result.updated) == (0, 1)
    assert (await chunk_rows(db_session))[0].metadata_hash == chunk().metadata_hash


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


async def test_matched_row_picks_up_a_changed_topic(
    db_session: AsyncSession, ingest_run: IngestRun
):
    await sync(db_session, ingest_run, chunk())

    result = await sync(db_session, ingest_run, chunk(topic="mrv"))

    assert (result.kept, result.updated) == (0, 1)
    assert (await chunk_rows(db_session))[0].topic == "mrv"


async def test_delete_chunks_removes_only_the_given_ids(
    db_session: AsyncSession, ingest_run: IngestRun
):
    await sync(db_session, ingest_run, chunk(), chunk(article="5"))
    rows = await chunk_rows(db_session)

    assert await delete_chunks(db_session, [rows[0].id]) == 1

    assert [row.id for row in await chunk_rows(db_session)] == [rows[1].id]


async def test_delete_chunks_leaves_the_table_alone_when_given_nothing(
    db_session: AsyncSession, ingest_run: IngestRun
):
    await sync(db_session, ingest_run, chunk())
    assert await delete_chunks(db_session, []) == 0
    assert len(await chunk_rows(db_session)) == 1


async def test_prune_chunks_drops_only_the_celexes_not_kept(
    db_session: AsyncSession, ingest_run: IngestRun
):
    for celex in ("32023R1805", "32015R0757"):
        await sync(db_session, ingest_run, chunk(celex=celex), celex=celex)

    assert await prune_chunks(db_session, ["32023R1805"]) == 1

    assert {row.celex for row in await chunk_rows(db_session)} == {"32023R1805"}


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


async def test_create_chunks_stores_each_chunk_under_its_content_key(
    db_session: AsyncSession, ingest_run: IngestRun
):
    incoming = _key_incoming_chunks([chunk(), chunk()])

    await create_chunks(db_session, incoming, ingest_run_id=ingest_run.id)

    rows = await chunk_rows(db_session)
    assert {(row.content_hash, row.occurrence) for row in rows} == set(incoming)
    assert {row.ingest_run_id for row in rows} == {ingest_run.id}


async def test_update_chunks_is_one_round_trip(db_engine, db_session, ingest_run, make_chunk_row):
    """One executemany UPDATE for the whole batch, not a RETURNING round trip per row."""
    created = [
        make_chunk_row(ingest_run, content_hash=str(index).ljust(64, "b")) for index in range(3)
    ]
    db_session.add_all(created)
    await db_session.flush()
    updates: list[bool] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE"):
            updates.append(executemany)

    event.listen(db_engine.sync_engine, "before_cursor_execute", record)
    try:
        await update_chunks(
            db_session, [{"id": row.id, "embedding": [0.5] * EMBED_DIMENSIONS} for row in created]
        )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", record)

    assert updates == [True]


def cites(*references: Reference, **overrides: Any) -> Chunk:
    """A chunk carrying the cross-references the hop reads."""
    return chunk(references=references, **overrides)


async def test_cited_celexes_are_the_instruments_a_division_is_cited_of(
    db_session: AsyncSession, ingest_run: IngestRun
):
    await sync(
        db_session,
        ingest_run,
        cites(
            Reference(
                raw="Article 7 of Directive (EU) 2018/2001", instrument="32018L2001", article="7"
            )
        ),
        cites(
            Reference(
                raw="Annex II to Regulation (EC) No 765/2008", instrument="32008R0765", annex="II"
            ),
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
        cites(Reference(raw="Regulation (EU) 2020/852", instrument="32020R0852")),
    )
    assert await cited_celexes(db_session) == set()


async def test_a_division_of_this_act_is_not_a_citation_of_another(
    db_session: AsyncSession, ingest_run: IngestRun
):
    await sync(db_session, ingest_run, cites(Reference(raw="Article 7", article="7")))
    assert await cited_celexes(db_session) == set()


async def test_what_a_hop_document_cites_is_not_cited(
    db_session: AsyncSession, ingest_run: IngestRun
):
    """Reading the hop's own citations would follow the graph one step further every run."""
    await sync(
        db_session,
        ingest_run,
        cites(
            Reference(
                raw="Article 7 of Directive 2010/75/EU", instrument="32010L0075", article="7"
            ),
            topic=CITED_TOPIC,
            celex="32018L2001",
        ),
        celex="32018L2001",
    )
    assert await cited_celexes(db_session) == set()


async def test_seed_celexes_leave_out_what_the_hop_brought_in(
    db_session: AsyncSession, ingest_run: IngestRun
):
    await sync(db_session, ingest_run, chunk(), celex="32023R1805")
    await sync(
        db_session,
        ingest_run,
        chunk(topic=CITED_TOPIC, celex="32018L2001"),
        celex="32018L2001",
    )
    assert await seed_celexes(db_session) == {"32023R1805"}
