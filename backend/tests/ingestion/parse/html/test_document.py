"""Whole-document parsing: dialect detection, section order, and stripped markup."""

from app.ingestion.parse.html.document import parse_eurlex_html
from tests.ingestion.parse.html.helpers import all_sections, annexes, articles


def test_recitals_and_citations_are_excluded():
    sections = parse_eurlex_html(
        "<html><body>"
        '<div class="eli-subdivision" id="rct_1"><p class="oj-normal">Whereas something.</p></div>'
        '<div class="eli-subdivision" id="cit_1">'
        '<p class="oj-normal">Having regard to the Treaty.</p></div>'
        '<div class="eli-subdivision" id="art_1"><p class="oj-ti-art">Article 1</p>'
        '<p class="oj-normal">Subject matter.</p></div>'
        "</body></html>"
    ).sections
    text = " ".join(s.text for s in all_sections(sections))
    assert "Subject matter." in text
    assert "Whereas" not in text
    assert "Having regard to the Treaty" not in text


def test_a_footnote_marker_is_dropped_with_the_brackets_around_it():
    (article,) = parse_eurlex_html(
        "<html><body>"
        '<div class="eli-subdivision" id="art_1"><p class="oj-ti-art">Article 1</p>'
        '<p class="oj-normal">Directive 2003/87/EC of the Council (<a href="#E0001">'
        '<span class="oj-super">1</span></a>);</p></div>'
        "</body></html>"
    ).sections
    assert article.children[0].text == "Directive 2003/87/EC of the Council;"


FLAT_CONSOLIDATED_HTML = (
    "<html><body>"
    '<p class="title-doc-first">REGULATION (EU) 2018/842</p>'
    '<p class="modref">▼B</p>'
    '<p class="title-article-norm">Article 1</p>'
    '<p class="stitle-article-norm">Subject matter</p>'
    '<p class="norm">This Regulation lays down obligations.</p>'
    '<p class="title-article-norm">Article 2</p>'
    '<p class="stitle-article-norm">Scope</p>'
    '<div class="norm"><span class="no-parag">1.  </span>'
    '<div class="norm inline-element">It applies to emissions.</div></div>'
    '<div class="norm"><span class="no-parag">2.  </span>'
    '<div class="norm inline-element">It does not apply to aviation.</div></div>'
    '<hr class="separator-annex"/>'
    '<p class="title-annex-1">ANNEX I</p>'
    '<p class="title-gr-seq-level-1">REDUCTIONS</p>'
    '<p class="norm">Annex prose.</p>'
    '<hr class="separator-short"/>'
    '<p class="footnote">(1) Regulation (EU) 2021/1119.</p>'
    "</body></html>"
)


def test_flat_consolidated_articles_are_grouped_under_their_headings():
    sections = articles(parse_eurlex_html(FLAT_CONSOLIDATED_HTML).sections)
    assert [(s.number, s.title) for s in sections] == [("1", "Subject matter"), ("2", "Scope")]
    assert sections[0].children[0].text == "This Regulation lays down obligations."
    assert [p.number for p in sections[1].children] == ["1", "2"]
    assert "Annex prose." not in sections[1].children[-1].text


def test_flat_consolidated_annexes_end_at_the_footnotes():
    sections = annexes(parse_eurlex_html(FLAT_CONSOLIDATED_HTML).sections)
    assert [s.number for s in sections] == ["I"]
    text = " ".join(s.text for s in all_sections(sections))
    assert "Annex prose." in text
    assert "2021/1119" not in text
