"""Parse stage: one fetched document's HTML as a section tree."""

from app.ingestion.enums import Stage
from app.ingestion.exceptions import DocumentFailed, ParseError
from app.ingestion.fetch.schemas import RawDocument
from app.ingestion.parse.html.document import parse_eurlex_html
from app.ingestion.parse.models import ParsedDocument


def parse_document(raw: RawDocument, html: bytes) -> ParsedDocument:
    """Parse one document's HTML, the one format storage keeps, or say why it would not."""
    try:
        parsed = parse_eurlex_html(html.decode("utf-8"))
    except (ParseError, UnicodeDecodeError) as exc:
        raise DocumentFailed(Stage.PARSE, raw.celex, exc) from exc
    return ParsedDocument(
        celex=raw.celex,
        topic=raw.topic,
        act_title=raw.title,
        sections=parsed.sections,
        images=parsed.images,
    )
