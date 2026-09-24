"""Parse stage: one fetched document's HTML as a section tree."""

from xml.etree import ElementTree

from app.ingestion.enums import Stage
from app.ingestion.exceptions import DocumentFailed, ParseError
from app.ingestion.fetch.schemas import RawDocument
from app.ingestion.parse.formex.formulas import read_formex_formulas
from app.ingestion.parse.html.document import parse_eurlex_html
from app.ingestion.parse.models import ParsedDocument


def parse_document(raw: RawDocument, html: bytes, formex: bytes | None) -> ParsedDocument:
    """Parse one document's XHTML with its Formex formulas written in, or say why it would not."""
    try:
        formulas = read_formex_formulas(formex) if formex is not None else None
        sections = parse_eurlex_html(html.decode("utf-8"), formulas)
    except (ParseError, UnicodeDecodeError, ElementTree.ParseError) as exc:
        raise DocumentFailed(Stage.PARSE, raw.celex, exc) from exc
    return ParsedDocument(celex=raw.celex, topic=raw.topic, act_title=raw.title, sections=sections)
