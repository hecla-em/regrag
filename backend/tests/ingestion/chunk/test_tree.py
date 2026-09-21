from app.ingestion.chunk.tree import chunk_document
from app.ingestion.enums import SectionKind
from app.ingestion.parse.models import ParsedDocument, Section


def paragraph(number: str | None, text: str) -> Section:
    return Section(kind=SectionKind.PARAGRAPH, number=number, text=text)


def document(*sections: Section) -> ParsedDocument:
    return ParsedDocument(
        celex="32023R1805", topic="fueleu", act_title="FuelEU Maritime", sections=sections
    )


def article(number: str, title: str, *children: Section) -> Section:
    return Section(kind=SectionKind.ARTICLE, number=number, title=title, children=children)


def test_records_nested_heading_path_within_an_annex() -> None:
    inner = Section(
        kind=SectionKind.HEADING, title="1. Formulae", children=(paragraph(None, "Body."),)
    )
    outer = Section(kind=SectionKind.HEADING, title="A. CALCULATION", children=(inner,))
    doc = document(Section(kind=SectionKind.ANNEX, number="I", title="Methods", children=(outer,)))
    chunk = chunk_document(doc)[0]
    assert chunk.heading_path == ("A. CALCULATION", "1. Formulae")
    assert chunk.annex == "I"


def test_numbers_each_part_of_a_split_section() -> None:
    doc = document(article("4", "Limits", paragraph("1", "aaaa\nbbbb\ncccc")))
    chunks = chunk_document(doc, max_chars=9)
    assert [(c.part, c.parts) for c in chunks] == [(1, 2), (2, 2)]


def test_split_parts_keep_the_same_citation_and_metadata() -> None:
    doc = document(article("4", "Limits", paragraph("2", "aaaa\nbbbb\ncccc")))
    chunks = chunk_document(doc, max_chars=9)
    assert {c.citation for c in chunks} == {"Article 4(2)"}
    assert {c.paragraph for c in chunks} == {"2"}
