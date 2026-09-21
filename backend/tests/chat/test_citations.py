"""Citation markers: how an answer's [n] markers are read, stripped, and bound to blocks."""

import pytest

from app.chat.citations import find_cited_markers, find_cited_sources, strip_markers

BLOCKS = ("first", "second", "third")


@pytest.mark.parametrize(
    ("answer", "markers", "cited"),
    [
        pytest.param(
            "A [2] B [1][2] C [10]",
            (2, 1, 10),
            ((2, "second"), (1, "first")),
            id="markers are read in first-cited order without repeats",
        ),
        pytest.param(
            "So [3], then [4].",
            (3, 4),
            ((3, "third"),),
            id="a marker past the last block binds none",
        ),
        pytest.param(
            "See [0] and [1].", (0, 1), ((1, "first"),), id="nor does a marker below the first"
        ),
        pytest.param(
            "I cannot answer that from the documents I have.",
            (),
            (),
            id="an answer citing nothing has no markers",
        ),
    ],
)
def test_markers_are_read_off_an_answer_and_bound_to_the_blocks_they_address(
    answer, markers, cited
) -> None:
    assert find_cited_markers(answer) == markers
    assert find_cited_sources(answer, BLOCKS) == cited


def test_strip_markers_removes_every_citation_marker_and_nothing_else() -> None:
    assert strip_markers("Ships must report.[1] Yearly.[2][3] Done.") == (
        "Ships must report. Yearly. Done."
    )
    assert strip_markers("No markers here.") == "No markers here."
