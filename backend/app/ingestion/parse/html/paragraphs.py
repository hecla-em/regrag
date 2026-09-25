"""Paragraph text, one line per block: EUR-Lex renders lists as layout tables and
grids, so blocks are flattened by hand instead of trusting Node.text()."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from selectolax.parser import Node

from app.ingestion.parse.html.text import clean_text

CELL = "td, th"
GRID_CONTAINER = "div.grid-container"
GRID_MARKER = "div.grid-list-column-1"
GRID_BODY = "div.grid-list-column-2"


@dataclass(frozen=True)
class Subheading:
    """A sub-heading in a line stream, at the depth its own class was written at."""

    level: int
    title: str


type Line = Subheading | str


def _join_texts(nodes: Iterable[Node | None]) -> str:
    """Clean each node's text and join the non-empty ones with a space."""
    return " ".join(text for text in (clean_text(n.text()) for n in nodes if n is not None) if text)


def detach_texts(node: Node, selector: str) -> list[str]:
    """The cleaned text of each matching node, which is removed from the tree once read."""
    matches = node.css(selector)
    texts = [clean_text(match.text()) for match in matches]
    for match in matches:
        match.replace_with("")
    return texts


def _grid_line(node: Node) -> str:
    """A consolidated list row: the '(a)' marker column joined to its text column."""
    return _join_texts((node.css_first(GRID_MARKER), node.css_first(GRID_BODY)))


def _row_line(node: Node) -> str:
    """A layout table row: its cells joined, so a bullet stays with the text it marks."""
    return _join_texts(node.css(CELL))


def _read_subheading(node: Node, subheading_re: re.Pattern[str] | None) -> Subheading | None:
    """The sub-heading this paragraph introduces; a container carrying the class opens one."""
    if node.tag != "p" or subheading_re is None:
        return None
    match = subheading_re.search(node.attributes.get("class") or "")
    return Subheading(level=int(match.group(1)), title=clean_text(node.text())) if match else None


def collect_lines(node: Node, subheading_re: re.Pattern[str] | None = None) -> list[Line]:
    """Walk in document order, one line per block, falling back to the node's own text."""
    lines: list[Line] = []
    _collect(node.iter(include_text=False), lines, subheading_re)
    if not lines and (text := clean_text(node.text())):
        lines.append(text)
    return lines


def _collect(
    nodes: Iterable[Node], lines: list[Line], subheading_re: re.Pattern[str] | None
) -> None:
    """Recurse into containers, emitting one line per text block."""
    for child in nodes:
        subheading = _read_subheading(child, subheading_re)
        if subheading is not None:
            lines.append(subheading)
            continue
        if child.tag == "div" and child.css_matches(GRID_CONTAINER):
            line = _grid_line(child)
        elif child.tag == "tr":
            line = _row_line(child)
        elif child.tag in ("p", "td"):
            line = clean_text(child.text())
        else:
            _collect(child.iter(include_text=False), lines, subheading_re)
            continue
        if line:
            lines.append(line)


def block_text(node: Node) -> str:
    """Join a node's text block by block, so flattened list rows stay on separate lines."""
    return "\n".join(line for line in collect_lines(node) if isinstance(line, str))


def blocks_text(nodes: Iterable[Node]) -> str:
    """Join a run of sibling blocks line by line, each read as block_text reads a child."""
    lines: list[Line] = []
    _collect(nodes, lines, None)
    return "\n".join(line for line in lines if isinstance(line, str))
