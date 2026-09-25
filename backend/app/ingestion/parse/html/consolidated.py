"""The consolidated dialect: norm classes and title-gr-seq-level-N sub-headings."""

import re
from collections.abc import Iterator

from selectolax.parser import HTMLParser, Node

from app.ingestion.enums import SectionKind
from app.ingestion.parse.html.paragraphs import block_text, blocks_text
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
NON_ELEMENT_TAGS = ("-text", "_comment")


def _is_numbered(node: Node) -> bool:
    """A norm block with a number marker of its own, not one nested in it, opens a paragraph."""
    marker = node.css_first(PARAGRAPH_NUMBER)
    return marker is not None and marker.parent == node and node.css_matches(PARAGRAPH_CONTAINER)


def _following_blocks(node: Node) -> Iterator[Node]:
    """The blocks after a paragraph's opening one: its later subparagraphs, lists and
    tables sit beside it, not inside it, up to the next numbered paragraph."""
    sibling = node.next
    while sibling is not None and not _is_numbered(sibling):
        if sibling.tag not in NON_ELEMENT_TAGS:
            yield sibling
        sibling = sibling.next


def find_paragraphs(node: Node) -> list[Node]:
    """The article's own numbered norm blocks, led by any text ahead of the first of them;
    numbered blocks nested in a list are quoted amendments, not the article's paragraphs."""
    blocks = [child for child in node.iter(include_text=False) if clean_text(child.text())]
    if not any(_is_numbered(block) for block in blocks):
        return []
    return [block for index, block in enumerate(blocks) if index == 0 or _is_numbered(block)]


def build_paragraph(node: Node) -> Section:
    """A paragraph from its opening block through its following ones; a numbered one
    carries its number in its own marker span, not in the text."""
    marker = node.css_first(PARAGRAPH_NUMBER) if _is_numbered(node) else None
    if marker is None:
        text = blocks_text([node, *_following_blocks(node)])
        return Section(kind=SectionKind.PARAGRAPH, text=text)
    body = node.css_first(PARAGRAPH_TEXT)
    number = LEADING_NUMBER_RE.match(clean_text(marker.text()))
    texts = (block_text(body) if body is not None else "", blocks_text(_following_blocks(node)))
    return Section(
        kind=SectionKind.PARAGRAPH,
        number=number.group(1) if number else None,
        text="\n".join(text for text in texts if text),
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
