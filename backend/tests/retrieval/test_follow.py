"""Following a stored cross-reference to the division it names."""

from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.chunk.schemas import DocumentChunk
from app.ingestion.schemas import IngestRun
from app.retrieval.follow import follow_reference
from app.retrieval.models import ReferenceTarget

pytestmark = pytest.mark.anyio

INVENTED_CELEX = "39999R9999"


async def test_follow_reference_sorts_a_chapeau_first_and_a_lettered_paragraph_after_its_number(
    db_session: AsyncSession,
    corpus: list[DocumentChunk],
    ingest_run: IngestRun,
    make_chunk_row: Callable[..., DocumentChunk],
) -> None:
    """The orderings no fixture act exercises: '2' before '11', '11' before '11a'."""
    for index, paragraph in enumerate(["11a", "2", "11", None]):
        db_session.add(
            make_chunk_row(
                ingest_run,
                celex=INVENTED_CELEX,
                article="7",
                paragraph=paragraph,
                citation=f"Article 7({paragraph})" if paragraph else "Article 7",
                content_hash=f"{index:064d}",
            )
        )
    await db_session.flush()

    found = await follow_reference(db_session, ReferenceTarget(celex=INVENTED_CELEX, article="7"))

    assert [chunk.citation for chunk in found] == [
        "Article 7",
        "Article 7(2)",
        "Article 7(11)",
        "Article 7(11a)",
    ]


async def test_follow_reference_puts_a_split_chapeau_in_part_order(
    db_session: AsyncSession, corpus: list[DocumentChunk]
) -> None:
    """A RetrievedChunk carries no part, so the order is checked against the rows' own parts."""
    found = await follow_reference(db_session, ReferenceTarget(celex="32015R0757", article="3"))

    parts = select(DocumentChunk.id, DocumentChunk.part).where(
        DocumentChunk.celex == "32015R0757", DocumentChunk.article == "3"
    )
    part_of = {id_: part for id_, part in await db_session.execute(parts)}
    assert [chunk.citation for chunk in found] == ["Article 3", "Article 3"]
    assert [part_of[chunk.id] for chunk in found] == [1, 2]


async def test_follow_reference_matches_the_article_number_case_insensitively(
    db_session: AsyncSession, corpus: list[DocumentChunk]
) -> None:
    upper = await follow_reference(db_session, ReferenceTarget(celex="32015R0757", article="11A"))
    lower = await follow_reference(db_session, ReferenceTarget(celex="32015R0757", article="11a"))

    assert lower
    assert upper == lower


async def test_follow_reference_does_not_reach_into_another_act(
    db_session: AsyncSession, corpus: list[DocumentChunk]
) -> None:
    found = await follow_reference(db_session, ReferenceTarget(celex="32015R0757", article="4"))

    assert {chunk.celex for chunk in found} == {"32015R0757"}


async def test_an_annex_comes_back_in_document_order(
    db_session: AsyncSession, corpus: list[DocumentChunk]
) -> None:
    """An annex has no paragraph to sort on, so position is the only reading order it has."""
    found = await follow_reference(db_session, ReferenceTarget(celex="32015R0757", annex="I"))

    positions = select(DocumentChunk.id, DocumentChunk.position).where(
        DocumentChunk.celex == "32015R0757", DocumentChunk.annex == "I"
    )
    order = {id_: position for id_, position in await db_session.execute(positions)}
    assert len(found) == 5
    assert [order[chunk.id] for chunk in found] == sorted(order.values())


async def test_an_annex_a_single_annex_act_left_unnumbered_is_still_addressable(
    db_session: AsyncSession,
    corpus: list[DocumentChunk],
    ingest_run: IngestRun,
    make_chunk_row: Callable[..., DocumentChunk],
) -> None:
    """RRG-75 writes '' for an act whose one annex carries no number; None is not-in-an-annex."""
    db_session.add(
        make_chunk_row(
            ingest_run,
            celex=INVENTED_CELEX,
            article=None,
            annex="",
            citation="Annex",
            content_hash=f"{1:064d}",
        )
    )
    await db_session.flush()

    found = await follow_reference(db_session, ReferenceTarget(celex=INVENTED_CELEX, annex=""))

    assert [chunk.citation for chunk in found] == ["Annex"]


async def test_a_followed_chunk_carries_the_reference_that_leads_on_from_it(
    db_session: AsyncSession, corpus: list[DocumentChunk]
) -> None:
    """The second hop reads the link off the chunk, rather than parsing it back out of the prose."""
    first = await follow_reference(
        db_session, ReferenceTarget(celex="32015R0757", article="4", paragraph="8")
    )

    (cited,) = [reference for chunk in first for reference in chunk.references]

    assert cited.raw == "Article 11a"
    assert cited.instrument is None
    second = await follow_reference(
        db_session, ReferenceTarget.from_reference(cited, citing="32015R0757")
    )
    assert second
    assert all(chunk.citation.startswith("Article 11a") for chunk in second)


# The chunk hashes covering a division, for stamping a golden case against it


@pytest.mark.parametrize(("point", "part"), [("e", 1), ("m", 2)])
async def test_a_point_of_a_definitions_article_reaches_the_part_that_lists_it(
    db_session: AsyncSession, corpus: list[DocumentChunk], point: str, part: int
) -> None:
    """A definitions article numbers no paragraphs; its points are stored on the parts."""
    found = await follow_reference(
        db_session, ReferenceTarget(celex="32015R0757", article="3", point=point)
    )

    parts = select(DocumentChunk.id, DocumentChunk.part).where(DocumentChunk.celex == "32015R0757")
    part_of = {id_: part for id_, part in await db_session.execute(parts)}
    assert [part_of[chunk.id] for chunk in found] == [part]


async def test_a_point_no_part_lists_returns_nothing_rather_than_the_whole_article(
    db_session: AsyncSession, corpus: list[DocumentChunk]
) -> None:
    found = await follow_reference(
        db_session, ReferenceTarget(celex="32015R0757", article="3", point="z")
    )

    assert found == ()


async def test_a_point_is_matched_regardless_of_case_like_an_article(
    db_session: AsyncSession, corpus: list[DocumentChunk]
) -> None:
    upper = await follow_reference(
        db_session, ReferenceTarget(celex="32015R0757", article="3", point="E")
    )
    lower = await follow_reference(
        db_session, ReferenceTarget(celex="32015R0757", article="3", point="e")
    )

    assert lower
    assert upper == lower


async def test_a_point_under_a_paragraph_narrows_to_that_paragraph(
    db_session: AsyncSession, corpus: list[DocumentChunk]
) -> None:
    """'Article 5(7), point (a)': paragraphs 7 and 8 both list an (a), only 7's is wanted."""
    found = await follow_reference(
        db_session, ReferenceTarget(celex="32023R1805", article="5", paragraph="7", point="a")
    )

    assert [chunk.citation for chunk in found] == ["Article 5(7)"]


async def test_a_point_without_a_paragraph_reaches_every_paragraph_that_lists_it(
    db_session: AsyncSession, corpus: list[DocumentChunk]
) -> None:
    """A citation that leaves the paragraph out is read across the article rather than
    turned away: a few candidates beat none."""
    found = await follow_reference(
        db_session, ReferenceTarget(celex="32023R1805", article="5", point="a")
    )

    assert [chunk.citation for chunk in found] == ["Article 5(7)", "Article 5(8)"]


async def test_a_point_cited_in_paragraph_notation_reaches_the_part_that_lists_it(
    db_session: AsyncSession, corpus: list[DocumentChunk]
) -> None:
    """EU drafting writes 'Article 2(5)' for point (5) of a definitions article, and the
    parser cannot tell that from a paragraph; an article that numbers no paragraphs settles it."""
    found = await follow_reference(
        db_session, ReferenceTarget(celex="32015R0757", article="3", paragraph="m")
    )

    parts = select(DocumentChunk.id, DocumentChunk.part).where(DocumentChunk.celex == "32015R0757")
    part_of = {id_: part for id_, part in await db_session.execute(parts)}
    assert [(chunk.citation, part_of[chunk.id]) for chunk in found] == [("Article 3", 2)]
