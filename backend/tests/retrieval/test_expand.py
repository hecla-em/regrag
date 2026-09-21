"""Widening a hit to its whole section: articles, split sections, and what has neither."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.chunk.schemas import DocumentChunk
from app.retrieval.expand import expand_sections
from app.retrieval.models import CHUNK_COLUMNS, RetrievedChunk

pytestmark = pytest.mark.anyio

NO_LIMIT = 1000
"""More chunks than any test corpus section holds, for the tests not about the cap."""


async def chunk_at(session: AsyncSession, celex: str, citation: str) -> RetrievedChunk:
    """One stored chunk as a caller sees it, so expansion is driven by real rows."""
    stmt = select(*CHUNK_COLUMNS).where(
        DocumentChunk.celex == celex, DocumentChunk.citation == citation
    )
    row = (await session.execute(stmt)).one()
    return RetrievedChunk.model_validate(row)


async def test_expand_sections_reaches_the_paragraph_relevance_cannot(
    db_session: AsyncSession,
    corpus: list[DocumentChunk],
) -> None:
    """Article 4(2) never restates its own subject, so only its article carries it here."""
    hit = await chunk_at(db_session, "32023R1805", "Article 4(1)")

    expanded = await expand_sections(db_session, [hit], limit=NO_LIMIT)

    assert [chunk.citation for chunk in expanded] == [
        "Article 4(1)",
        "Article 4(2)",
        "Article 4(3)",
        "Article 4(4)",
    ]


async def test_expand_sections_caps_by_rounds_so_every_hit_survives(
    db_session: AsyncSession,
    corpus: list[DocumentChunk],
) -> None:
    """The cap cuts sections' outer edges, never a lower-ranked hit's own chunk."""
    fifth = await chunk_at(db_session, "32023R1805", "Article 5(1)")
    fourth = await chunk_at(db_session, "32023R1805", "Article 4(1)")

    anchors_only = await expand_sections(db_session, [fifth, fourth], limit=2)
    one_more = await expand_sections(db_session, [fifth, fourth], limit=3)

    assert [chunk.citation for chunk in anchors_only] == ["Article 5(1)", "Article 4(1)"]
    assert [chunk.article for chunk in one_more] == ["5", "5", "4"]
    assert {"Article 5(1)", "Article 4(1)"} <= {chunk.citation for chunk in one_more}


async def test_expand_sections_keeps_a_second_hit_in_the_same_section(
    db_session: AsyncSession,
    corpus: list[DocumentChunk],
) -> None:
    """Two non-adjacent hits in one article are both hits; neither may lose its place to
    another section's widening under a tight cap."""
    hits = [
        await chunk_at(db_session, "32023R1805", "Article 4(1)"),
        await chunk_at(db_session, "32023R1805", "Article 4(3)"),
        await chunk_at(db_session, "32023R1805", "Article 5(1)"),
    ]

    for limit in (3, 4, NO_LIMIT):
        expanded = await expand_sections(db_session, hits, limit=limit)
        assert {hit.id for hit in hits} <= {chunk.id for chunk in expanded}


@pytest.mark.parametrize(
    "split",
    [
        pytest.param(False, id="a whole annex section has nothing to widen to"),
        pytest.param(True, id="a later half of a split table brings back the other"),
    ],
)
async def test_expand_sections_widens_a_hit_outside_an_article_to_exactly_its_own_split(
    db_session: AsyncSession, corpus: list[DocumentChunk], split: bool
) -> None:
    parts = (
        (DocumentChunk.parts > 1, DocumentChunk.part > 1) if split else (DocumentChunk.parts == 1,)
    )
    stmt = (
        select(*CHUNK_COLUMNS)
        .where(DocumentChunk.annex.is_not(None), *parts)
        .order_by(DocumentChunk.position)
    )
    row = (await db_session.execute(stmt)).first()
    assert row is not None, "the fixture no longer stores such an annex chunk"
    hit = RetrievedChunk.model_validate(row)

    expanded = await expand_sections(db_session, [hit], limit=NO_LIMIT)

    assert len(expanded) == hit.parts
    assert hit in expanded


async def test_expand_sections_widens_every_section_in_the_same_round(
    db_session: AsyncSession,
    corpus: list[DocumentChunk],
) -> None:
    """A section's widening rounds are its own; three hits in Article 4 must not push its
    first widening chunk behind a lone-hit section's second and third."""
    hits = [
        await chunk_at(db_session, "32023R1805", "Article 4(1)"),
        await chunk_at(db_session, "32023R1805", "Article 4(2)"),
        await chunk_at(db_session, "32023R1805", "Article 4(3)"),
        await chunk_at(db_session, "32023R1805", "Article 5(1)"),
    ]

    expanded = await expand_sections(db_session, hits, limit=6)
    citations = {chunk.citation for chunk in expanded}

    assert {"Article 4(4)", "Article 5(2)"} <= citations
