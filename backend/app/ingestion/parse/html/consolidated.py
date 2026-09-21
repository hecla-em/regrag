"""The consolidated dialect: norm classes and title-gr-seq-level-N sub-headings."""

import re

from selectolax.parser import HTMLParser, Node

from app.ingestion.enums import SectionKind
from app.ingestion.parse.html.paragraphs import block_text
from app.ingestion.parse.html.text import LEADING_NUMBER_RE, clean_text
from app.ingestion.parse.models import Section

SIGNATURE = "p.norm, div.norm"
ARTICLE_HEADING = "p.title-article-norm"
PARAGRAPH_CONTAINER = "div.norm"
PARAGRAPH_NUMBER = "span.no-parag"
PARAGRAPH_TEXT = "div.norm.inline-element"
ANNEX_LABEL = "p.title-annex-1"
ANNEX_TITLE = "p.title-gr-seq-level-1"
DATA_TABLE = "table.borderOj"
SUBHEADING_LEVEL_RE = re.compile(r"title-gr-seq-level-(\d+)")
ARTICLE_TITLE = "p.stitle-article-norm"
ANNEX_SEPARATOR = "hr.separator-annex"
NOTES_SEPARATOR = "hr.separator-short"


def find_paragraphs(node: Node) -> list[Node]:
    """Only the norm blocks carrying a number marker are paragraphs; the rest are prose."""
    return [child for child in node.css(PARAGRAPH_CONTAINER) if child.css_first(PARAGRAPH_NUMBER)]


def build_paragraph(node: Node) -> Section:
    """Consolidated paragraphs number themselves in their own marker span, not in the text."""
    marker = node.css_first(PARAGRAPH_NUMBER)
    body = node.css_first(PARAGRAPH_TEXT)
    number = LEADING_NUMBER_RE.match(clean_text(marker.text()) if marker else "")
    return Section(
        kind=SectionKind.PARAGRAPH,
        number=number.group(1) if number else None,
        text=block_text(body) if body is not None else "",
    )


def wrap_flat_layout(tree: HTMLParser) -> str:
    """Older consolidated texts lay articles and annexes flat under the body: the body
    regrouped into the ELI containers the wrapped layout has, up to the footnotes."""
    parts: list[str] = []
    open_container = False
    for index, node in enumerate(tree.body.iter() if tree.body else ()):
        if node.css_matches(NOTES_SEPARATOR):
            break
        starts_article = node.css_matches(ARTICLE_HEADING)
        if starts_article or node.css_matches(ANNEX_SEPARATOR):
            parts.append("</div>" if open_container else "")
            kind = '<div class="eli-subdivision" id="art_' if starts_article else '<div id="anx_'
            parts.append(f'{kind}{index}">')
            open_container = True
        html = node.html or ""
        parts.append(
            f'<div class="eli-title">{html}</div>' if node.css_matches(ARTICLE_TITLE) else html
        )
    parts.append("</div>" if open_container else "")
    return f"<html><body>{''.join(parts)}</body></html>"
