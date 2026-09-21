"""Blocks flattened to one line each: layout tables, grid lists, and the bare-text fallback."""

from app.ingestion.parse.html.consolidated import SUBHEADING_LEVEL_RE
from app.ingestion.parse.html.paragraphs import Subheading, collect_lines
from app.ingestion.parse.models import ParsedDocument
from tests.ingestion.parse.html.helpers import articles, subdivision


def test_a_container_carrying_a_level_class_is_recursed_into_not_read_as_a_heading():
    node = subdivision(
        '<html><body><div id="anx_I">'
        '<div class="eli-subdivision title-gr-seq-level-2">'
        '<p class="title-gr-seq-level-2">A. First part</p>'
        '<p class="norm">Prose under A.</p>'
        "</div></div></body></html>",
        "anx_I",
    )
    assert collect_lines(node, SUBHEADING_LEVEL_RE) == [
        Subheading(2, "A. First part"),
        "Prose under A.",
    ]


def test_layout_tables_flatten_into_the_paragraph_that_contains_them(fueleu: ParsedDocument):
    paragraph_2 = articles(fueleu.sections)[0].children[1]
    assert paragraph_2.children == ()
    assert "2 % from 1 January 2025;" in paragraph_2.text
    assert "6 % from 1 January 2030;" in paragraph_2.text


def test_consolidated_grid_lists_flatten_into_the_paragraph(mrv: ParsedDocument):
    definitions = articles(mrv.sections)[0]
    text = " ".join(p.text for p in definitions.children)
    assert "(a) ‘greenhouse gas emissions’ means" in text
    assert "(c) ‘voyage’ means" in text
