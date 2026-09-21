"""Annex assembly: labels and titles, detached data tables, and prose folded under
the sub-headings that introduce it."""

import pytest
from selectolax.parser import Node

from app.ingestion.enums import SectionKind
from app.ingestion.parse.html import consolidated, oj
from app.ingestion.parse.html.annexes import (
    _detach_data_tables,
    _nest_under_subheadings,
)
from app.ingestion.parse.html.paragraphs import Subheading
from app.ingestion.parse.models import ParsedDocument
from tests.conftest import FUELEU_HTML, MRV_HTML
from tests.ingestion.parse.html.helpers import all_sections, annexes, of_kind, subdivision


def test_nesting_puts_prose_under_the_subheading_that_introduces_it():
    sections = _nest_under_subheadings([Subheading(2, "A. First"), "prose under A"])
    assert len(sections) == 1
    assert sections[0].kind is SectionKind.HEADING
    assert sections[0].title == "A. First"
    assert [child.text for child in sections[0].children] == ["prose under A"]


def test_nesting_deepens_then_returns_for_a_shallower_subheading():
    sections = _nest_under_subheadings(
        [
            Subheading(2, "A"),
            "under A",
            Subheading(3, "A.1"),
            "under A.1",
            Subheading(2, "B"),
            "under B",
        ]
    )
    assert [section.title for section in sections] == ["A", "B"]
    prose, nested = sections[0].children
    assert prose.kind is SectionKind.PARAGRAPH
    assert prose.text == "under A"
    assert nested.kind is SectionKind.HEADING
    assert nested.title == "A.1"
    assert [child.text for child in nested.children] == ["under A.1"]


def test_prose_before_the_first_subheading_stays_at_the_top_level():
    sections = _nest_under_subheadings(["preamble", Subheading(2, "A"), "under A"])
    assert sections[0].kind is SectionKind.PARAGRAPH
    assert sections[0].text == "preamble"
    assert sections[1].kind is SectionKind.HEADING


def test_a_stream_with_no_subheadings_becomes_one_flat_paragraph():
    sections = _nest_under_subheadings(["one", "two"])
    assert len(sections) == 1
    assert sections[0].kind is SectionKind.PARAGRAPH
    assert sections[0].text == "one\ntwo"


def test_oj_annex_label_and_title(fueleu: ParsedDocument):
    annex = annexes(fueleu.sections)[0]
    assert annex.number == "II"
    assert annex.title == "Default emission factors"


def test_consolidated_annex_label_and_title(mrv: ParsedDocument):
    annex = annexes(mrv.sections)[0]
    assert annex.number == "I"
    assert annex.title == "Methods for monitoring greenhouse gas emissions"


def test_oj_annex_prose_is_kept_alongside_its_tables(fueleu: ParsedDocument):
    annex = annexes(fueleu.sections)[0]
    prose = of_kind(annex.children, SectionKind.PARAGRAPH)
    assert prose
    assert "The default emission factors contained in the table below" in prose[0].text
    assert "Fuel Class" not in prose[0].text


def test_consolidated_annex_headings_nest_by_level(mrv: ParsedDocument):
    annex = annexes(mrv.sections)[0]
    top = of_kind(annex.children, SectionKind.HEADING)
    assert top
    assert (top[0].title or "").startswith("A.")
    nested = of_kind(top[0].children, SectionKind.HEADING)
    assert nested
    assert (nested[0].title or "").startswith("1.")


def test_oj_annexes_are_flat(fueleu: ParsedDocument):
    annex = annexes(fueleu.sections)[0]
    assert not of_kind(annex.children, SectionKind.HEADING)
    assert of_kind(annex.children, SectionKind.TABLE)


def test_consolidated_annex_prose_excludes_its_heading_lines(mrv: ParsedDocument):
    annex = annexes(mrv.sections)[0]
    sections = list(all_sections(annex.children))
    prose = "\n".join(s.text for s in sections)
    titles = [s.title for s in sections if s.kind is SectionKind.HEADING and s.title]
    assert titles
    assert annex.title is not None
    assert annex.title not in prose
    assert not [title for title in titles if title in prose]


def test_consolidated_annex_prose_sits_under_the_heading_that_introduces_it(mrv: ParsedDocument):
    annex = annexes(mrv.sections)[0]
    part_a = of_kind(annex.children, SectionKind.HEADING)[0]
    formulae = of_kind(part_a.children, SectionKind.HEADING)[0]
    prose = of_kind(formulae.children, SectionKind.PARAGRAPH)
    assert prose
    assert "companies shall apply the following formula" in prose[0].text


@pytest.fixture
def fueleu_annex() -> Node:
    """Function-scoped: detaching tables mutates the tree, so it cannot be shared."""
    return subdivision(FUELEU_HTML, "anx_II")


def test_data_table_rows_are_a_raw_grid(fueleu_annex: Node):
    grids = _detach_data_tables(fueleu_annex, oj.DATA_TABLE)
    assert grids
    assert grids[0].kind is SectionKind.TABLE
    rows = grids[0].rows
    assert rows[0] == ("1", "2", "3", "4", "5", "6", "7", "8", "9")
    assert any("Fuel Class" in cell for row in rows for cell in row)


def test_formula_images_become_placeholders_in_table_cells(fueleu_annex: Node):
    cells = [
        cell
        for grid in _detach_data_tables(fueleu_annex, oj.DATA_TABLE)
        for row in grid.rows
        for cell in row
    ]
    assert any("[formula]" in cell for cell in cells)
    assert not any("base64" in cell for cell in cells)


def test_consolidated_data_table_rows_are_a_raw_grid():
    grids = _detach_data_tables(subdivision(MRV_HTML, "anx_I"), consolidated.DATA_TABLE)
    assert len(grids) == 2
    assert grids[0].kind is SectionKind.TABLE
    assert grids[0].rows[0] == ("Term", "Explanation")


def test_consolidated_data_tables_do_not_stay_behind_as_annex_prose(mrv: ParsedDocument):
    annex = annexes(mrv.sections)[0]
    prose = "\n".join(s.text or "" for s in all_sections(annex.children))
    assert "Explanation" not in prose
