"""EUR-Lex text conventions: the markup stripped before any text is read, and the
cleaning every read goes through."""

import re
from collections.abc import Sequence

from selectolax.parser import HTMLParser

from app.ingestion.exceptions import ParseError

FORMULA_PLACEHOLDER = "[formula]"

AMENDMENT_REF = "p.modref"
FOOTNOTE_MARKER = "span.superscript, span.oj-super"
FOOTNOTE_BLOCK = "p.footnote, p.oj-note, div[id^=fnp]"
NON_LEGAL_MARKUP = (AMENDMENT_REF, FOOTNOTE_MARKER, FOOTNOTE_BLOCK)

WHITESPACE_RE = re.compile(r"\s+")
AMENDMENT_MARKER_RE = re.compile(r"[▼►]\s*[A-Z]+\d*|◄")
EMPTY_PARENS_RE = re.compile(r"\s*\(\s*\)")

ARTICLE_NUMBER = r"\d+(?!st\b|nd\b|rd\b|th\b)[a-z]{0,2}\b"
"""An article number as headed and as cited: '3', '3a', '3ga', never an ordinal like '20th'."""

ARTICLE_NUMBER_RE = re.compile(rf"Article\s+({ARTICLE_NUMBER})", re.IGNORECASE)
ANNEX_NUMBER_RE = re.compile(r"ANNEX\s+([IVXLC]+|\d+)", re.IGNORECASE)
LEADING_NUMBER_RE = re.compile(r"^(\d+(?:-?[a-z]+)?)\.\s*")


def replace_formula_images(tree: HTMLParser, formulas: Sequence[str] | None) -> None:
    """Stand each base64 image down to its Formex formula in document order, or to [formula]."""
    images = [
        image
        for image in tree.css("img")
        if (image.attributes.get("src") or "").startswith("data:")
    ]
    if formulas is not None and len(formulas) != len(images):
        raise ParseError(f"Formex has {len(formulas)} formulas for {len(images)} inline images")
    for index, image in enumerate(images):
        image.replace_with(FORMULA_PLACEHOLDER if formulas is None else formulas[index])


def drop_non_legal_markup(tree: HTMLParser) -> None:
    """Remove amendment references, footnote markers and footnote blocks before any text
    is read: dropping a footnote superscript leaves an empty "()" that clean_text strips.
    """
    for selector in NON_LEGAL_MARKUP:
        for node in tree.css(selector):
            node.replace_with("")


def clean_text(text: str) -> str:
    """Collapse whitespace, dropping amendment glyphs and the brackets that
    drop_non_legal_markup leaves behind when it empties a footnote reference.
    """
    text = AMENDMENT_MARKER_RE.sub(" ", text)
    text = EMPTY_PARENS_RE.sub("", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def heading_number(headings: list[str], pattern: re.Pattern[str]) -> str | None:
    """The number as written in the first heading, or None where the heading is absent."""
    match = pattern.search(headings[0]) if headings else None
    return match.group(1) if match else None
