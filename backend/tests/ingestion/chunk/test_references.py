import pytest

from app.ingestion.chunk.models import Reference
from app.ingestion.chunk.references import (
    _find_division_mentions,
    _find_instrument_mentions,
    extract_references,
    list_points,
)


def test_extracts_internal_article_reference() -> None:
    references = extract_references("calculated in accordance with Article 6 of this Regulation")
    assert Reference(raw="Article 6", instrument=None, article="6") in references


def test_extracts_paragraph_from_internal_article_reference() -> None:
    references = extract_references("as referred to in Article 6(2)")
    assert references == (
        Reference(raw="Article 6(2)", instrument=None, article="6", paragraph="2"),
    )


def test_extracts_letter_suffixed_article_number() -> None:
    references = extract_references("the procedure in Article 11a(3) applies")
    assert references == (
        Reference(raw="Article 11a(3)", instrument=None, article="11a", paragraph="3"),
    )


def test_extracts_an_article_number_with_a_two_letter_suffix() -> None:
    references = extract_references("the list referred to in Article 3gf(2) and 3ga")
    assert [(r.article, r.paragraph) for r in references] == [("3gf", "2"), ("3ga", None)]


def test_extracts_a_hyphened_paragraph_number() -> None:
    references = extract_references("the ports referred to in Article 12(3-d)")
    assert references == (
        Reference(raw="Article 12(3-d)", instrument=None, article="12", paragraph="3-d"),
    )


def test_extracts_internal_annex_reference() -> None:
    references = extract_references("using the methods set out in Annex I")
    assert references == (Reference(raw="Annex I", instrument=None, annex="I"),)


def test_deduplicates_repeated_references() -> None:
    references = extract_references("Annex I applies. As stated in Annex I, the factor is fixed.")
    assert len(references) == 1


def test_ignores_prose_without_references() -> None:
    assert extract_references("This Regulation lays down rules on the use of fuels.") == ()


def test_resolves_regulation_to_celex() -> None:
    references = extract_references("as defined in Regulation (EU) 2015/757")
    assert references == (Reference(raw="Regulation (EU) 2015/757", instrument="32015R0757"),)


def test_resolves_directive_to_celex() -> None:
    references = extract_references("the scope of Directive 2003/87/EC")
    assert references == (Reference(raw="Directive 2003/87/EC", instrument="32003L0087"),)


def test_resolves_numbered_instrument_as_number_before_year() -> None:
    references = extract_references("repealing Regulation (EC) No 765/2008")
    assert references == (Reference(raw="Regulation (EC) No 765/2008", instrument="32008R0765"),)


def test_resolves_a_two_digit_year_to_the_twentieth_century() -> None:
    references = extract_references("as amended by Council Directive 92/43/EEC")
    assert references == (Reference(raw="Council Directive 92/43/EEC", instrument="31992L0043"),)


def test_drops_an_instrument_whose_citation_cannot_be_a_celex_id() -> None:
    assert extract_references("the fictional Regulation 3021/4055") == ()


def test_extracts_every_article_of_an_enumeration() -> None:
    references = extract_references("in accordance with Articles 6, 7 and 8")
    assert references == tuple(Reference(raw=f"Article {n}", article=n) for n in ("6", "7", "8"))


def test_attributes_every_article_of_an_enumeration_to_its_instrument() -> None:
    references = extract_references("under Articles 6 and 7 of Regulation (EU) 2015/757")
    assert references == tuple(
        Reference(
            raw=f"Article {n} of Regulation (EU) 2015/757",
            instrument="32015R0757",
            article=n,
        )
        for n in ("6", "7")
    )


def test_extracts_every_annex_of_an_enumeration() -> None:
    references = extract_references("set out in Annexes I and II")
    assert references == tuple(Reference(raw=f"Annex {n}", annex=n) for n in ("I", "II"))


def test_does_not_read_a_trailing_year_as_a_further_article() -> None:
    references = extract_references("Article 6, 2015 saw the adoption of the scheme")
    assert references == (Reference(raw="Article 6", article="6"),)


def test_attributes_article_to_the_instrument_it_qualifies() -> None:
    references = extract_references("verified under Article 6(2) of Regulation (EU) 2015/757")
    assert references == (
        Reference(
            raw="Article 6(2) of Regulation (EU) 2015/757",
            instrument="32015R0757",
            article="6",
            paragraph="2",
        ),
    )


def test_does_not_treat_this_regulation_as_an_external_instrument() -> None:
    references = extract_references("Article 6 of this Regulation applies")
    assert references == (Reference(raw="Article 6", instrument=None, article="6"),)


def test_lists_the_points_the_text_opens_lines_with() -> None:
    """A definitions article lists its terms one to a line, '(e)' or '(15)' first."""
    text = "For the purposes of this Regulation:\n(a) ‘ship’ means a vessel;\n(15) ‘berth’ means"
    assert list_points(text) == ("a", "15")


def test_a_point_named_mid_line_is_not_listed() -> None:
    assert list_points("as defined in Article 3, point (e), of Regulation X") == ()


def test_a_division_is_not_qualified_by_an_instrument_it_only_precedes() -> None:
    text = "Article 6 applies. Regulation (EU) 2015/757 does not."
    division = _find_division_mentions(text)[0]
    instrument = _find_instrument_mentions(text)[0]
    assert not division.is_qualified_by(instrument, text)


@pytest.mark.parametrize(
    ("mention", "article", "instrument"),
    [
        ("Council Regulation (EEC) No 3577/92", "3", "31992R3577"),
        ("Commission Implementing Regulation (EU) 2016/1927", "2", "32016R1927"),
        ("Commission Delegated Regulation (EU) 2023/1640", "5", "32023R1640"),
        ("European Parliament and Council Directive 95/46/EC", "6", "31995L0046"),
        ("Council Implementing Regulation (EU) 2020/1998", "7", "32020R1998"),
        ("Council Framework Decision 2002/584/JHA", "4", "32002D0584"),
    ],
)
def test_attributes_an_article_across_any_institutional_prefix(
    mention: str, article: str, instrument: str
) -> None:
    """The institution naming an act sits inside its mention, however it is styled."""
    references = extract_references(f"pursuant to Article {article} of {mention}")
    assert references == (
        Reference(
            raw=f"Article {article} of {mention}",
            instrument=instrument,
            article=article,
        ),
    )


def test_an_institutional_prefix_is_kept_when_the_act_is_cited_in_its_own_right() -> None:
    references = extract_references("as amended by Council Implementing Regulation (EU) 2020/1998")
    assert references == (
        Reference(raw="Council Implementing Regulation (EU) 2020/1998", instrument="32020R1998"),
    )


def test_the_prefix_does_not_reach_back_over_a_sentence_boundary() -> None:
    references = extract_references("set out in Annex II. Regulation (EU) 2015/757 applies")
    assert Reference(raw="Regulation (EU) 2015/757", instrument="32015R0757") in references


def test_the_prefix_does_not_reach_back_into_the_act_cited_before_it() -> None:
    """'/EC' ends the preceding citation; it does not name the institution of the next."""
    references = extract_references("comply with Directive 2003/87/EC and Regulation (EU) 2015/757")
    assert references == (
        Reference(raw="Directive 2003/87/EC", instrument="32003L0087"),
        Reference(raw="Regulation (EU) 2015/757", instrument="32015R0757"),
    )


def test_the_prefix_does_not_swallow_upper_case_prose_in_a_heading() -> None:
    references = extract_references(
        "THE ANNEX TO COMMISSION IMPLEMENTING REGULATION (EU) 2016/1927"
    )
    assert references == (
        Reference(raw="COMMISSION IMPLEMENTING REGULATION (EU) 2016/1927", instrument="32016R1927"),
    )


def test_a_pre_1999_regulation_reads_number_first() -> None:
    references = extract_references("competition rules in Regulation 17/62")
    assert references == (Reference(raw="Regulation 17/62", instrument="31962R0017"),)


def test_attributes_an_article_cited_by_point_to_the_instrument_after_the_point() -> None:
    references = extract_references(
        "means gross tonnage as defined in Article 3, point (e), of Regulation (EU) 2015/757"
    )
    assert references == (
        Reference(
            raw="Article 3, point (e), of Regulation (EU) 2015/757",
            instrument="32015R0757",
            article="3",
            point="e",
        ),
    )


def test_a_point_cited_in_this_act_carries_its_point() -> None:
    """Most definition borrows name a point of this act's own definitions article."""
    references = extract_references("‘ice class’ as defined in Article 3, point (23)")
    assert references == (Reference(raw="Article 3, point (23)", article="3", point="23"),)


def test_a_point_of_an_annex_is_attributed_with_its_point() -> None:
    references = extract_references("as set out in Annex I, point (a), of Regulation (EU) 2015/757")
    assert references == (
        Reference(
            raw="Annex I, point (a), of Regulation (EU) 2015/757",
            instrument="32015R0757",
            annex="I",
            point="a",
        ),
    )


def test_keeps_a_numbered_point_under_the_paragraph_it_belongs_to() -> None:
    references = extract_references(
        "the ship at berth in Article 3(1), point (15), of Regulation (EU) 2023/1805"
    )
    assert references == (
        Reference(
            raw="Article 3(1), point (15), of Regulation (EU) 2023/1805",
            instrument="32023R1805",
            article="3",
            paragraph="1",
            point="15",
        ),
    )


def test_attributes_an_article_cited_by_subparagraph_to_the_instrument_after_it() -> None:
    references = extract_references(
        "under Article 6(2), second subparagraph, of Regulation (EU) 2015/757"
    )
    assert references == (
        Reference(
            raw="Article 6(2), second subparagraph, of Regulation (EU) 2015/757",
            instrument="32015R0757",
            article="6",
            paragraph="2",
        ),
    )
