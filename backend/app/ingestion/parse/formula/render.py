"""Image placeholders to LaTeX: each one read once by the formula model, then rendered or
dropped."""

import re
from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import run_concurrently
from app.core.config import config
from app.ingestion.parse.formula.models import FormulaReading, ImageCounts
from app.ingestion.parse.formula.read import read_formula
from app.ingestion.parse.formula.service import get_renderings, upsert_renderings
from app.ingestion.parse.html.text import IMAGE_PLACEHOLDER_RE
from app.ingestion.parse.models import ParsedDocument, ParsedImage, Section


def render_placeholders(text: str, renderings: Mapping[str, str | None]) -> str:
    """Each placeholder as $$latex$$, or gone with the space before it where it is no formula."""

    def rendered(match: re.Match[str]) -> str:
        latex = renderings[match.group(2)]
        return f"{match.group(1)}$${' '.join(latex.split())}$$" if latex else ""

    return IMAGE_PLACEHOLDER_RE.sub(rendered, text)


def render_section(section: Section, renderings: Mapping[str, str | None]) -> Section:
    """The section and everything under it with its placeholders rendered."""
    return section.model_copy(
        update={
            "title": section.title and render_placeholders(section.title, renderings),
            "text": render_placeholders(section.text, renderings),
            "rows": tuple(
                tuple(render_placeholders(cell, renderings) for cell in row) for row in section.rows
            ),
            "children": tuple(render_section(child, renderings) for child in section.children),
        }
    )


async def _read_image(item: tuple[str, ParsedImage]) -> FormulaReading:
    return await read_formula(item[1])


async def render_document_formulas(
    session: AsyncSession, document: ParsedDocument
) -> tuple[ParsedDocument, ImageCounts]:
    """The document with every image placeholder rendered from the cache, reading the misses."""
    model = config.FORMULA_MODEL
    renderings = await get_renderings(session, document.images.keys(), model=model)
    cached = len(renderings)
    unread = [
        (digest, image) for digest, image in document.images.items() if digest not in renderings
    ]
    read: dict[str, str | None] = {}
    async with run_concurrently(unread, _read_image, limit=config.FORMULA_CONCURRENCY) as pending:
        for (digest, _), reading in pending:
            answer = await reading
            read[digest] = answer.latex if answer.is_formula else None
    await upsert_renderings(session, read, model=model)
    renderings |= read
    sections = tuple(render_section(section, renderings) for section in document.sections)
    rendered = document.model_copy(update={"sections": sections, "images": {}})
    return rendered, ImageCounts(read=len(read), reused=cached)
