"""Annexes as Section subtrees: heading detached, then the prose and data tables folded, in
document order, under the sub-headings that introduce them."""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser, Node

from app.ingestion.enums import SectionKind
from app.ingestion.parse.html.dialect import Dialect
from app.ingestion.parse.html.paragraphs import CELL, Line, collect_lines, detach_texts
from app.ingestion.parse.html.text import ANNEX_NUMBER_RE, clean_text, heading_number
from app.ingestion.parse.models import Section

ANNEX_CONTAINER = "div[id^=anx_]"
TABLE_MARK = "\ue000"
TABLE_MARK_RE = re.compile(rf"\s*{TABLE_MARK}(\d+){TABLE_MARK}\s*")
"""Where a detached table stood, as private-use text a line keeps through cleaning; a table
inside a list row splits that row's line around it."""


def _table_rows(node: Node) -> tuple[tuple[str, ...], ...]:
    """A table as a raw grid of cleaned cells, with no row treated as a header."""
    rows = []
    for row in node.css("tr"):
        cells = tuple(clean_text(cell.text()) for cell in row.css(CELL))
        if cells:
            rows.append(cells)
    return tuple(rows)


def _mark_data_tables(node: Node, selector: str) -> list[Section]:
    """Data tables as TABLE sections, each swapped in the tree for a mark naming it, so its
    cells are not re-read and the line stream can put it back where it stood."""
    sections: list[Section] = []
    for table in node.css(selector):
        rows = _table_rows(table)
        if not rows:
            table.replace_with("")
            continue
        mark = f"<p>{TABLE_MARK}{len(sections)}{TABLE_MARK}</p>"
        table.replace_with(HTMLParser(mark).css_first("p"))  # ty: ignore[invalid-argument-type]
        sections.append(Section(kind=SectionKind.TABLE, rows=rows))
    return sections


def _place_tables(lines: Iterable[Line], tables: list[Section]) -> Iterator[Line | Section]:
    """The line stream with each table mark replaced by the table it stands for."""
    for line in lines:
        if not isinstance(line, str):
            yield line
            continue
        for index, piece in enumerate(TABLE_MARK_RE.split(line)):
            if index % 2:
                yield tables[int(piece)]
            elif piece:
                yield piece


@dataclass
class _OpenSubheading:
    """A sub-heading still being filled: its own prose, then its subsections."""

    level: int
    title: str | None
    lines: list[str] = field(default_factory=list)
    children: list[Section] = field(default_factory=list)

    def flush_prose(self) -> None:
        """Bank the prose read so far as a paragraph, ahead of any subsection after it."""
        if self.lines:
            self.children.append(Section(kind=SectionKind.PARAGRAPH, text="\n".join(self.lines)))
            self.lines.clear()

    def close(self) -> Section:
        """Bank any prose still open and return the finished heading section."""
        self.flush_prose()
        return Section(kind=SectionKind.HEADING, title=self.title, children=tuple(self.children))


def _nest_under_subheadings(lines: Iterable[Line | Section]) -> tuple[Section, ...]:
    """Fold a line stream into sections, each sub-heading owning the prose and tables beneath
    it."""
    stack = [_OpenSubheading(level=0, title=None)]

    def unwind(level: int) -> None:
        while stack[-1].level >= level:
            done = stack.pop()
            stack[-1].children.append(done.close())

    for line in lines:
        if isinstance(line, str):
            stack[-1].lines.append(line)
        elif isinstance(line, Section):
            stack[-1].flush_prose()
            stack[-1].children.append(line)
        else:
            unwind(line.level)
            stack[-1].flush_prose()
            stack.append(_OpenSubheading(level=line.level, title=line.title))
    unwind(1)
    stack[0].flush_prose()
    return tuple(stack[0].children)


def build_annex(node: Node, dialect: Dialect) -> Section:
    """An annex as a Section: detach the heading, and what remains is body prose with its data
    tables in place; OJ annexes are flat, consolidated ones nest by level."""
    labels = detach_texts(node, dialect.annex_label)
    titles = detach_texts(node, dialect.annex_title) if dialect.annex_title else labels[1:]
    tables = _mark_data_tables(node, dialect.data_table)
    lines = _place_tables(collect_lines(node, dialect.subheading_re), tables)
    body = _nest_under_subheadings(lines)
    return Section(
        kind=SectionKind.ANNEX,
        number=heading_number(labels, ANNEX_NUMBER_RE),
        title=titles[0] if titles else None,
        children=body,
    )
