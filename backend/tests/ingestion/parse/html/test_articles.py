"""Article boundaries, titles, and their numbered paragraphs, in both dialects."""

from app.ingestion.parse.html.document import parse_eurlex_html
from app.ingestion.parse.models import ParsedDocument
from tests.ingestion.parse.html.helpers import articles


def test_oj_article_boundaries(fueleu: ParsedDocument):
    assert [a.number for a in articles(fueleu.sections)] == ["4", "5"]


def test_consolidated_article_boundaries(mrv: ParsedDocument):
    assert [a.number for a in articles(mrv.sections)] == ["3", "4", "11a"]


def test_oj_article_title(fueleu: ParsedDocument):
    first = articles(fueleu.sections)[0]
    assert first.title == "GHG intensity limit on energy used on board by a ship"


def test_consolidated_article_title(mrv: ParsedDocument):
    assert articles(mrv.sections)[0].title == "Definitions"


def test_lettered_article_title(mrv: ParsedDocument):
    lettered = articles(mrv.sections)[2]
    assert lettered.number == "11a"
    assert lettered.title == (
        "Reporting and submission of the aggregated emissions data at company level"
    )


def test_oj_paragraphs_are_numbered_and_split_from_their_text(fueleu: ParsedDocument):
    first = articles(fueleu.sections)[0]
    numbers = [p.number for p in first.children]
    assert numbers == ["1", "2", "3", "4"]
    assert first.children[0].text == (
        "The yearly average GHG intensity of the energy used on board by a ship "
        "during a reporting period shall not exceed the limit set out in paragraph 2."
    )


def test_consolidated_paragraphs_are_numbered(mrv: ParsedDocument):
    article_4 = articles(mrv.sections)[1]
    assert [p.number for p in article_4.children] == ["1", "2", "3", "4", "5", "6", "7", "8"]


def test_consolidated_paragraph_text_excludes_its_number(mrv: ParsedDocument):
    article_4 = articles(mrv.sections)[1]
    assert article_4.children[0].text.startswith("In accordance with Articles 8 to 12")


def test_amendment_markers_are_stripped_but_wrapped_text_survives(mrv: ParsedDocument):
    article_4 = articles(mrv.sections)[1]
    text = article_4.children[1].text
    assert "►" not in text and "◄" not in text and "▼" not in text
    assert "greenhouse gas" in text


ETS_ARTICLE = (
    '<html><body><div class="eli-subdivision" id="art_3ga">'
    '<p class="title-article-norm">Article 3ga</p>'
    '<div class="eli-title"><p class="stitle-article-norm">Scope</p></div>'
    '<div class="norm"><span class="no-parag">3.  </span>'
    '<div class="norm inline-element">Surrender applies.</div></div>'
    '<div class="norm"><span class="no-parag">3-e.  </span>'
    '<div class="norm inline-element">By way of derogation.</div></div>'
    "</div></body></html>"
)


def test_an_article_number_keeps_every_letter_of_its_suffix():
    assert parse_eurlex_html(ETS_ARTICLE)[0].number == "3ga"


def test_a_paragraph_inserted_before_another_keeps_its_hyphened_number():
    paragraphs = parse_eurlex_html(ETS_ARTICLE)[0].children
    assert [p.number for p in paragraphs] == ["3", "3-e"]
