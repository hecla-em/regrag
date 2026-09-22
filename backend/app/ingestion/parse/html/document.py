"""One EUR-Lex document's HTML as a section tree, whichever dialect it is written in."""

from selectolax.parser import HTMLParser

from app.ingestion.exceptions import ParseError
from app.ingestion.parse.html import consolidated
from app.ingestion.parse.html.annexes import ANNEX_CONTAINER, build_annex
from app.ingestion.parse.html.articles import ARTICLE_CONTAINER, build_article
from app.ingestion.parse.html.dialect import detect_dialect
from app.ingestion.parse.html.text import drop_non_legal_markup, replace_inline_images
from app.ingestion.parse.models import ParsedHtml


def prepare(html: str) -> HTMLParser:
    """Parse the HTML with the non-legal markup already stripped, before any text is read, and
    a flat consolidated layout regrouped into article and annex containers."""
    tree = HTMLParser(html)
    if tree.css_first(ARTICLE_CONTAINER) is None and tree.css_first(consolidated.ARTICLE_HEADING):
        tree = HTMLParser(consolidated.wrap_flat_layout(tree))
    drop_non_legal_markup(tree)
    return tree


def parse_eurlex_html(html: str) -> ParsedHtml:
    """Parse one EUR-Lex document into the format-neutral section tree and its inline images."""
    tree = prepare(html)
    images = replace_inline_images(tree)
    dialect = detect_dialect(tree)

    articles = [build_article(node, dialect) for node in tree.css(ARTICLE_CONTAINER)]
    if not articles:
        raise ParseError("no articles found")
    annexes = [build_annex(node, dialect) for node in tree.css(ANNEX_CONTAINER)]
    return ParsedHtml(sections=tuple(articles + annexes), images=images)
