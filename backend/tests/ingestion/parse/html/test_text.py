"""EUR-Lex text conventions: whitespace, amendment glyphs, emptied brackets."""

from app.ingestion.parse.html.text import clean_text


def test_clean_strips_amendment_markers_but_keeps_the_text_they_wrap():
    assert clean_text("▼M1 greenhouse gas emissions ◄") == "greenhouse gas emissions"


def test_clean_strips_the_brackets_an_emptied_footnote_leaves_behind():
    assert clean_text("Directive 2009/16/EC (  ) of the Council") == (
        "Directive 2009/16/EC of the Council"
    )


def test_clean_keeps_parentheses_that_still_have_content():
    assert clean_text("(a) ‘voyage’ means") == "(a) ‘voyage’ means"
