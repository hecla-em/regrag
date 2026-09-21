"""Annex assembly: prose folded under the sub-headings that introduce it."""

import pytest

from app.ingestion.enums import SectionKind
from app.ingestion.parse.html.annexes import _nest_under_subheadings
from app.ingestion.parse.html.paragraphs import Line, Subheading
from app.ingestion.parse.models import Section


def prose(text: str) -> Section:
    return Section(kind=SectionKind.PARAGRAPH, text=text)


def heading(title: str, *children: Section) -> Section:
    return Section(kind=SectionKind.HEADING, title=title, children=children)


@pytest.mark.parametrize(
    ("lines", "sections"),
    [
        pytest.param(
            [
                "preamble",
                Subheading(2, "A"),
                "under A",
                Subheading(3, "A.1"),
                "under A.1",
                Subheading(2, "B"),
                "under B",
            ],
            (
                prose("preamble"),
                heading("A", prose("under A"), heading("A.1", prose("under A.1"))),
                heading("B", prose("under B")),
            ),
            id="prose sits under its sub-heading, which deepens and then returns",
        ),
        pytest.param(
            ["one", "two"], (prose("one\ntwo"),), id="with no sub-heading it is one paragraph"
        ),
    ],
)
def test_a_line_stream_nests_under_the_subheadings_that_introduce_it(
    lines: list[Line], sections: tuple[Section, ...]
) -> None:
    assert _nest_under_subheadings(lines) == sections
