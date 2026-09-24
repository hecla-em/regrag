"""One EUR-Lex document's HTML as a section tree, whichever dialect it is written in."""

from collections.abc import Sequence

from selectolax.parser import HTMLParser

from app.ingestion.exceptions import ParseError
from app.ingestion.parse.html import consolidated
from app.ingestion.parse.html.annexes import ANNEX_CONTAINER, build_annex
from app.ingestion.parse.html.articles import ARTICLE_CONTAINER, build_article
from app.ingestion.parse.html.dialect import detect_dialect
from app.ingestion.parse.html.text import drop_non_legal_markup, replace_formula_images
from app.ingestion.parse.models import Section


def prepare(html: str, formulas: Sequence[str] | None = None) -> HTMLParser:
    """Parse the HTML with a flat consolidated layout regrouped into article and annex
    containers, inline images replaced by formulas and non-legal markup stripped."""
    tree = HTMLParser(html)
    if tree.css_first(ARTICLE_CONTAINER) is None and tree.css_first(consolidated.ARTICLE_HEADING):
        tree = HTMLParser(consolidated.wrap_flat_layout(tree))
    replace_formula_images(tree, formulas)
    drop_non_legal_markup(tree)
    return tree


def parse_eurlex_html(html: str, formulas: Sequence[str] | None = None) -> tuple[Section, ...]:
    """Parse one EUR-Lex document into the format-neutral section tree, each inline image
    replaced by its formula."""
    tree = prepare(html, formulas)
    dialect = detect_dialect(tree)

    articles = [build_article(node, dialect) for node in tree.css(ARTICLE_CONTAINER)]
    if not articles:
        raise ParseError("no articles found")
    annexes = [build_annex(node, dialect) for node in tree.css(ANNEX_CONTAINER)]
    return tuple(articles + annexes)
