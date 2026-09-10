from app.ingestion.chunk.models import Locator, Reference
from app.ingestion.chunk.tree import chunk_document, locate
from app.ingestion.enums import SectionKind
from app.ingestion.parse.models import ParsedDocument, Section


def paragraph(number: str | None, text: str) -> Section:
    return Section(kind=SectionKind.PARAGRAPH, number=number, text=text)


def document(*sections: Section) -> ParsedDocument:
    return ParsedDocument(celex="32023R1805", topic="fueleu", sections=sections)


def article(number: str, title: str, *children: Section) -> Section:
    return Section(kind=SectionKind.ARTICLE, number=number, title=title, children=children)


def heading(title: str) -> Section:
    return Section(kind=SectionKind.HEADING, title=title)


ARTICLE_6 = article("6", "Monitoring")
ANNEX_I = Section(kind=SectionKind.ANNEX, number="I", title="Methods")
PARAGRAPH_2 = Section(kind=SectionKind.PARAGRAPH, number="2")


def test_an_article_ancestor_gives_its_number_and_title() -> None:
    locator = locate((ARTICLE_6, PARAGRAPH_2))
    assert (locator.article, locator.title, locator.annex) == ("6", "Monitoring", None)


def test_the_nearest_division_wins_so_an_annex_inside_an_article_is_not_an_article() -> None:
    locator = locate((ARTICLE_6, ANNEX_I, PARAGRAPH_2))
    assert (locator.annex, locator.article, locator.title) == ("I", None, "Methods")


def test_headings_stack_in_the_order_they_were_entered() -> None:
    locator = locate((ANNEX_I, heading("Part A"), heading("Part B"), PARAGRAPH_2))
    assert locator.heading_path == ("Part A", "Part B")


def test_a_paragraph_contributes_nothing_to_the_address() -> None:
    assert locate((ARTICLE_6, PARAGRAPH_2)) == locate((ARTICLE_6,))


def test_a_path_with_no_article_or_annex_has_an_empty_address() -> None:
    assert locate((heading("Part A"),)) == Locator(heading_path=("Part A",))


def test_emits_one_chunk_per_numbered_paragraph() -> None:
    doc = document(
        article("4", "GHG intensity limit", paragraph("1", "First."), paragraph("2", "Second."))
    )
    chunks = chunk_document(doc)
    assert [c.text for c in chunks] == ["First.", "Second."]


def test_chunk_carries_article_number_and_title() -> None:
    doc = document(article("4", "GHG intensity limit", paragraph("1", "First.")))
    chunk = chunk_document(doc)[0]
    assert (chunk.article, chunk.title, chunk.paragraph) == ("4", "GHG intensity limit", "1")


def test_chunk_carries_document_identity() -> None:
    doc = document(article("4", "Limits", paragraph("1", "First.")))
    chunk = chunk_document(doc)[0]
    assert (chunk.celex, chunk.topic) == ("32023R1805", "fueleu")


def test_a_non_paragraph_section_leaves_paragraph_unset() -> None:
    doc = document(article("4", "Limits", Section(kind=SectionKind.HEADING, text="Preamble.")))
    assert chunk_document(doc)[0].paragraph is None


def test_citation_combines_article_and_paragraph() -> None:
    doc = document(article("11a", "Reporting", paragraph("3", "Text.")))
    assert chunk_document(doc)[0].citation == "Article 11a(3)"


def test_citation_omits_paragraph_when_article_is_unnumbered() -> None:
    doc = document(article("3", "Definitions", paragraph(None, "For the purposes of...")))
    chunk = chunk_document(doc)[0]
    assert (chunk.citation, chunk.paragraph) == ("Article 3", None)


def test_annex_table_becomes_its_own_chunk() -> None:
    table = Section(kind=SectionKind.TABLE, rows=(("Fuel", "Factor"), ("LNG", "2.75")))
    doc = document(
        Section(kind=SectionKind.ANNEX, number="II", title="Emission factors", children=(table,))
    )
    chunk = chunk_document(doc)[0]
    assert chunk.kind is SectionKind.TABLE
    assert chunk.text == "Fuel | Factor\nLNG | 2.75"
    assert (chunk.annex, chunk.citation) == ("II", "Annex II")


def test_records_nested_heading_path_within_an_annex() -> None:
    inner = Section(
        kind=SectionKind.HEADING, title="1. Formulae", children=(paragraph(None, "Body."),)
    )
    outer = Section(kind=SectionKind.HEADING, title="A. CALCULATION", children=(inner,))
    doc = document(Section(kind=SectionKind.ANNEX, number="I", title="Methods", children=(outer,)))
    chunk = chunk_document(doc)[0]
    assert chunk.heading_path == ("A. CALCULATION", "1. Formulae")
    assert chunk.annex == "I"


def test_numbers_chunks_by_their_place_in_the_document() -> None:
    doc = document(
        article("4", "Limits", paragraph("1", "First."), paragraph("2", "Second.")),
        Section(
            kind=SectionKind.ANNEX,
            number="I",
            title="Methods",
            children=(paragraph(None, "Body."),),
        ),
    )
    assert [c.position for c in chunk_document(doc)] == [0, 1, 2]


def test_identical_annex_chunks_differ_only_by_position() -> None:
    """The MRV Annex I case: byte-identical tables with nothing else to tell them apart."""
    table = Section(kind=SectionKind.TABLE, rows=(("Fuel", "Factor"),))
    doc = document(
        Section(kind=SectionKind.ANNEX, number="I", title="Methods", children=(table, table))
    )
    first, second = chunk_document(doc)
    assert first.model_dump(exclude={"position"}) == second.model_dump(exclude={"position"})
    assert (first.position, second.position) == (0, 1)


def test_attaches_references_found_in_the_chunk_text() -> None:
    doc = document(article("4", "Limits", paragraph("1", "as set out in Annex I")))
    assert chunk_document(doc)[0].references == (Reference(raw="Annex I", annex="I"),)


def test_attaches_the_points_the_chunk_text_lists() -> None:
    doc = document(article("3", "Definitions", paragraph(None, "For the purposes:\n(a) ‘ship’;")))
    assert chunk_document(doc)[0].points == ("a",)


def test_skips_sections_with_no_text() -> None:
    doc = document(article("4", "Limits", paragraph("1", ""), paragraph("2", "Second.")))
    assert [c.paragraph for c in chunk_document(doc)] == ["2"]


def test_does_not_split_a_section_within_the_limit() -> None:
    doc = document(article("4", "Limits", paragraph("1", "Short.")))
    chunk = chunk_document(doc, max_chars=100)[0]
    assert (chunk.part, chunk.parts) == (1, 1)


def test_splits_a_long_section_on_line_boundaries() -> None:
    doc = document(article("4", "Limits", paragraph("1", "aaaa\nbbbb\ncccc")))
    chunks = chunk_document(doc, max_chars=9)
    assert [c.text for c in chunks] == ["aaaa\nbbbb", "cccc"]


def test_numbers_each_part_of_a_split_section() -> None:
    doc = document(article("4", "Limits", paragraph("1", "aaaa\nbbbb\ncccc")))
    chunks = chunk_document(doc, max_chars=9)
    assert [(c.part, c.parts) for c in chunks] == [(1, 2), (2, 2)]


def test_split_parts_keep_the_same_citation_and_metadata() -> None:
    doc = document(article("4", "Limits", paragraph("2", "aaaa\nbbbb\ncccc")))
    chunks = chunk_document(doc, max_chars=9)
    assert {c.citation for c in chunks} == {"Article 4(2)"}
    assert {c.paragraph for c in chunks} == {"2"}


def test_an_annex_after_an_article_is_not_cited_as_an_article() -> None:
    inner = Section(kind=SectionKind.ANNEX, number="I", children=(paragraph(None, "Body."),))
    doc = document(article("4", "Limits", inner))
    chunk = chunk_document(doc)[0]
    assert (chunk.article, chunk.annex, chunk.citation) == (None, "I", "Annex I")


def test_an_unnumbered_annex_still_encloses_what_sits_under_it() -> None:
    """An act with one annex labels it 'ANNEX' and nothing else, so there is no number to read."""
    locator = locate((Section(kind=SectionKind.ANNEX, title="Template"), PARAGRAPH_2))
    assert (locator.annex, locator.article) == ("", None)


def test_the_sole_unnumbered_annex_is_cited_as_the_annex() -> None:
    doc = document(Section(kind=SectionKind.ANNEX, children=(paragraph(None, "Body."),)))
    assert chunk_document(doc)[0].citation == "Annex"
