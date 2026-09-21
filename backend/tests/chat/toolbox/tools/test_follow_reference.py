"""follow_reference: which follows the context already answers, so the round can drop them."""

import pytest

from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.tools.follow_reference import already_in_context
from tests.conftest import search_result

PARAGRAPH = {"celex": "32023R1805", "article": "4", "paragraph": "1"}
"""The address of the default search_result: Article 4(1), shown in its one part."""
DEFINITIONS = {"celex": "32015R0757", "citation": "Article 3", "article": "3", "paragraph": None}
"""A definitions article numbers no paragraphs, so its points hang off the article."""
POINT_C = {"celex": "32015R0757", "article": "3", "point": "c"}


@pytest.mark.parametrize(
    ("shown", "follow", "dropped"),
    [
        pytest.param({}, PARAGRAPH, True, id="a paragraph shown in full is dropped"),
        pytest.param(
            {},
            {**PARAGRAPH, "point": "a"},
            True,
            id="so is a point under a paragraph shown in full",
        ),
        pytest.param(
            {**DEFINITIONS, "points": ("c", "d")},
            POINT_C,
            True,
            id="so is a point a shown part lists",
        ),
        pytest.param(
            {**DEFINITIONS, "points": ("a",)},
            POINT_C,
            False,
            id="a point no shown part lists still runs",
        ),
        pytest.param(
            {"part": 1, "parts": 2},
            PARAGRAPH,
            False,
            id="a paragraph shown only in part still runs",
        ),
        pytest.param(
            {"citation": "Article 4", "paragraph": None},
            {"celex": "32023R1805", "article": "4"},
            False,
            id="a whole article still runs when only its chapeau is shown",
        ),
    ],
)
def test_a_follow_is_dropped_only_when_the_context_shows_all_it_would_fetch(shown, follow, dropped):
    call = ToolCall(name="follow_reference", args=follow)

    assert already_in_context(call, (search_result(**shown),)) is dropped
