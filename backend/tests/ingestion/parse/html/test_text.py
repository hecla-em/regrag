"""EUR-Lex text conventions: whitespace, amendment glyphs, emptied brackets."""

import pytest

from app.ingestion.parse.html.text import clean_text


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        pytest.param(
            "▼M1 greenhouse gas emissions ◄",
            "greenhouse gas emissions",
            id="amendment markers go and the text they wrap stays",
        ),
        pytest.param(
            "Directive 2009/16/EC (  ) of the Council",
            "Directive 2009/16/EC of the Council",
            id="the brackets an emptied footnote leaves behind go too",
        ),
        pytest.param(
            "(a) ‘voyage’ means",
            "(a) ‘voyage’ means",
            id="parentheses that still have content are kept",
        ),
    ],
)
def test_cleaning_strips_only_what_eurlex_added_to_the_law(raw: str, cleaned: str) -> None:
    assert clean_text(raw) == cleaned
