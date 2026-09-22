"""Parse stage: one fetched document's HTML as a section tree, its formula images read into
LaTeX."""

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.errors import LLMError
from app.ingestion.enums import Stage
from app.ingestion.exceptions import DocumentFailed, ParseError
from app.ingestion.fetch.schemas import RawDocument
from app.ingestion.parse.formula.models import ImageCounts
from app.ingestion.parse.formula.render import render_document_formulas
from app.ingestion.parse.html.document import parse_eurlex_html
from app.ingestion.parse.models import ParsedDocument


async def parse_document(
    session: AsyncSession, raw: RawDocument, html: bytes
) -> tuple[ParsedDocument, ImageCounts]:
    """Parse one document's HTML and read its images, or say why it would not."""
    try:
        parsed = parse_eurlex_html(html.decode("utf-8"))
        document = ParsedDocument(
            celex=raw.celex,
            topic=raw.topic,
            act_title=raw.title,
            sections=parsed.sections,
            images=parsed.images,
        )
        return await render_document_formulas(session, document)
    except (ParseError, UnicodeDecodeError, LLMError, SQLAlchemyError) as exc:
        raise DocumentFailed(Stage.PARSE, raw.celex, exc) from exc
