"""Article and paragraph numbering the fixture acts do not carry."""

from app.ingestion.parse.html.document import parse_eurlex_html

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


def test_an_inserted_article_and_paragraph_keep_their_whole_number():
    """The ETS directive numbers an article '3ga' and a paragraph put in ahead of 3a '3-e'."""
    (article,) = parse_eurlex_html(ETS_ARTICLE)

    assert article.number == "3ga"
    assert [paragraph.number for paragraph in article.children] == ["3", "3-e"]
