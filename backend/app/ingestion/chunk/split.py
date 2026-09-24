"""Text sizing: a section's text as pieces that fit the embedding budget.

Every break costs something, so they are tried in order: line boundaries, then sentence
boundaries inside an overlong line, then a hard cut where no boundary is left.
"""

import re
from collections.abc import Sequence

from app.ingestion.enums import SectionKind
from app.ingestion.parse.models import Section

CELL_SEPARATOR = " | "
SENTENCE = re.compile(r"(?<=[.;:])\s+")


def format_markdown_table(text: str) -> str:
    """A table chunk's separated rows as a markdown table, its first row the header."""
    header, *body = (f"| {line} |" for line in text.split("\n"))
    rule = "|" + " --- |" * (header.count(CELL_SEPARATOR) + 1)
    return "\n".join([header, rule, *body])


def split_section_text(section: Section, max_chars: int) -> list[str]:
    """A leaf's embeddable text; a section with neither rows nor text yields nothing."""
    if section.rows:
        return _split_table_rows(section.rows, max_chars)
    return _split_text(section.text, max_chars) if section.text else []


def pack_leaves(sections: Sequence[Section], max_chars: int) -> list[Section]:
    """Neighbouring leaves no number or title addresses joined into one paragraph while they
    fit the budget together, so a formula table stays with the prose that introduces it."""
    packed: list[Section] = []
    for section in sections:
        previous = packed[-1] if packed else None
        if previous is not None and _is_packable(previous) and _is_packable(section):
            joined = f"{_leaf_text(previous)}\n{_leaf_text(section)}"
            if len(joined) <= max_chars:
                packed[-1] = Section(kind=SectionKind.PARAGRAPH, text=joined)
                continue
        packed.append(section)
    return packed


def _is_packable(section: Section) -> bool:
    """A paragraph or table with nothing beneath it and no number or title of its own."""
    return (
        section.kind in (SectionKind.PARAGRAPH, SectionKind.TABLE)
        and not section.children
        and section.number is None
        and section.title is None
    )


def _leaf_text(section: Section) -> str:
    """A leaf's text as a chunk carries it, a table one row to a line."""
    if section.rows:
        return "\n".join(CELL_SEPARATOR.join(row) for row in section.rows)
    return section.text


def _split_text(text: str, max_chars: int) -> list[str]:
    """Break at the best boundary available, then pack the pieces back up to the budget."""
    fitted_lines: list[str] = []
    for line in filter(None, text.split("\n")):
        if len(line) <= max_chars:
            fitted_lines.append(line)
        else:
            fitted_lines.extend(_split_on_sentences(line, max_chars))
    return _pack(fitted_lines, "\n", max_chars)


def _split_table_rows(rows: tuple[tuple[str, ...], ...], max_chars: int) -> list[str]:
    """Break on row boundaries, leading every piece with the header row."""
    header, *body = (CELL_SEPARATOR.join(row) for row in rows)
    budget = max_chars - len(header) - 1
    if not body or budget <= 0:
        return _split_text("\n".join([header, *body]), max_chars)
    fitted_rows: list[str] = []
    for row in body:
        fitted_rows.extend(_split_on_characters(row, budget))
    return [f"{header}\n{piece}" for piece in _pack(fitted_rows, "\n", budget)]


def _split_on_sentences(line: str, max_chars: int) -> list[str]:
    """An overlong line at its sentence boundaries, hard-cutting any sentence still too long."""
    fitted_sentences: list[str] = []
    for sentence in SENTENCE.split(line):
        fitted_sentences.extend(_split_on_characters(sentence, max_chars))
    return _pack(fitted_sentences, " ", max_chars)


def _split_on_characters(text: str, max_chars: int) -> list[str]:
    """The last resort, with no boundary left to respect: fixed-width slices."""
    return [text[start : start + max_chars] for start in range(0, len(text), max_chars)]


def _pack(pieces: list[str], joiner: str, max_chars: int) -> list[str]:
    """Join neighbours into as few pieces as the budget allows; every piece must already fit."""
    if not pieces:
        return []
    packed = [pieces[0]]
    for piece in pieces[1:]:
        joined = packed[-1] + joiner + piece
        if len(joined) <= max_chars:
            packed[-1] = joined
        else:
            packed.append(piece)
    return packed
