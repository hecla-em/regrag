"""Blocks flattened to one line each, and the sub-headings read out of them."""

from app.ingestion.parse.html.consolidated import SUBHEADING_LEVEL_RE
from app.ingestion.parse.html.paragraphs import Subheading, collect_lines
from tests.ingestion.parse.html.helpers import subdivision


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
