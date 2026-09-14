"""Follow a stored cross-reference to the division it names, in reading order."""

from sqlalchemy import Integer, Select, and_, any_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.chunk.schemas import DocumentChunk
from app.retrieval.models import CHUNK_COLUMNS, ReferenceTarget, RetrievedChunk

ARTICLE_ORDER = (
    DocumentChunk.paragraph.is_not(None),
    cast(func.substring(DocumentChunk.paragraph, "^[0-9]+"), Integer),
    func.substring(DocumentChunk.paragraph, "^[0-9]*(.*)$"),
    DocumentChunk.part,
)
"""The chapeau leads its paragraphs, since a NULL paragraph sorts False before their True;
the number sorts numerically and the letter after it, so 2 precedes 11 precedes 11a. A citation
addresses a paragraph by its number, so the number is what orders what a citation reaches."""

ANNEX_ORDER = (DocumentChunk.position, DocumentChunk.part)
"""An annex numbers no paragraphs, so where it sits in the document is the only order it has."""


def _targeted(stmt: Select, target: ReferenceTarget) -> Select:
    """Narrow to the one division the target names. A point reaches the parts listing it. A
    paragraph number an article does not number is read as a point of it, since EU drafting
    writes 'Article 3(15)' for point (15) of a definitions article."""
    stmt = stmt.where(DocumentChunk.celex == target.celex)
    if target.article is not None:
        stmt = stmt.where(func.lower(DocumentChunk.article) == target.article.lower())
    if target.paragraph is not None:
        stmt = stmt.where(
            or_(
                DocumentChunk.paragraph == target.paragraph,
                and_(
                    DocumentChunk.paragraph.is_(None),
                    any_(DocumentChunk.points) == target.paragraph,
                ),
            )
        )
    if target.point is not None:
        stmt = stmt.where(any_(DocumentChunk.points) == target.point.lower())
    if target.annex is not None:
        stmt = stmt.where(DocumentChunk.annex == target.annex)
    return stmt


async def follow_reference(
    session: AsyncSession, target: ReferenceTarget
) -> tuple[RetrievedChunk, ...]:
    """The text a stored cross-reference points at, in reading order."""
    order = ANNEX_ORDER if target.annex is not None else ARTICLE_ORDER
    stmt = _targeted(select(*CHUNK_COLUMNS), target).order_by(*order)
    rows = await session.execute(stmt)
    return tuple(RetrievedChunk.model_validate(row) for row in rows)


async def division_content_hashes(
    session: AsyncSession, target: ReferenceTarget
) -> tuple[str, ...]:
    """The content hash of every chunk covering the division, in the order a reader meets them."""
    order = ANNEX_ORDER if target.annex is not None else ARTICLE_ORDER
    stmt = _targeted(select(DocumentChunk.content_hash), target).order_by(*order)
    return tuple(await session.scalars(stmt))
