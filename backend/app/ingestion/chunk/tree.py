"""Section tree -> chunks: one chunk per piece of a section's text, addressed by its ancestors."""

from collections.abc import Iterator

from app.core.config import config
from app.ingestion.chunk.models import Chunk, Locator
from app.ingestion.chunk.references import extract_references, list_points
from app.ingestion.chunk.split import pack_leaves, split_section_text
from app.ingestion.enums import SectionKind
from app.ingestion.parse.models import ParsedDocument, Section

DIVISIONS = (SectionKind.ARTICLE, SectionKind.ANNEX)
"""Section kinds that enclose a chunk: the innermost one is the division it belongs to."""


def locate(path: tuple[Section, ...]) -> Locator:
    """Where a section sits, read off its ancestors: the nearest article or annex encloses it,
    and every heading on the way down is part of the path."""
    headings = tuple(s.title for s in path if s.kind is SectionKind.HEADING and s.title)
    division = next((s for s in reversed(path) if s.kind in DIVISIONS), None)
    if division is None:
        return Locator(heading_path=headings)
    is_article = division.kind is SectionKind.ARTICLE
    return Locator(
        article=division.number if is_article else None,
        annex=None if is_article else division.number or "",
        title=division.title,
        heading_path=headings,
    )


def chunk_section_tree(
    section: Section, document: ParsedDocument, ancestors: tuple[Section, ...], max_chars: int
) -> Iterator[Chunk]:
    """This section's own text as chunks, then everything nested beneath it."""
    path = (*ancestors, section)
    locator = locate(path)
    pieces = split_section_text(section, max_chars)
    for part, piece in enumerate(pieces, start=1):
        yield Chunk(
            **locator.model_dump(),
            celex=document.celex,
            topic=document.topic,
            act_title=document.act_title,
            kind=section.kind,
            paragraph=section.number if section.kind is SectionKind.PARAGRAPH else None,
            text=piece,
            part=part,
            parts=len(pieces),
            points=list_points(piece),
            references=extract_references(piece),
        )
    for child in pack_leaves(section.children, max_chars):
        yield from chunk_section_tree(child, document, path, max_chars)


def chunk_document(
    document: ParsedDocument, max_chars: int = config.MAX_CHARS
) -> tuple[Chunk, ...]:
    """Every text-bearing section of the parsed tree as a chunk, numbered in document order."""
    chunks = (
        chunk
        for section in document.sections
        for chunk in chunk_section_tree(section, document, (), max_chars)
    )
    numbered_chunks = (
        chunk.model_copy(update={"position": position}) for position, chunk in enumerate(chunks)
    )
    return tuple(numbered_chunks)
