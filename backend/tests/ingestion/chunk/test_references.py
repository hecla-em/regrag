"""Cross-reference extraction: every row is a citation the corpus once misattributed."""

import pytest

from app.ingestion.chunk.models import Reference
from app.ingestion.chunk.references import extract_references, list_points

MRV = "Regulation (EU) 2015/757"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "calculated in accordance with Article 6",
            (Reference(raw="Article 6", article="6"),),
            id="a bare article belongs to this act",
        ),
        pytest.param(
            "as referred to in Article 6(2)",
            (Reference(raw="Article 6(2)", article="6", paragraph="2"),),
            id="a paragraph is carried with its article",
        ),
        pytest.param(
            "the procedure in Article 11a(3) applies",
            (Reference(raw="Article 11a(3)", article="11a", paragraph="3"),),
            id="an article number may end in a letter",
        ),
        pytest.param(
            "the list referred to in Article 3gf(2) and 3ga",
            (
                Reference(raw="Article 3gf(2)", article="3gf", paragraph="2"),
                Reference(raw="Article 3ga", article="3ga"),
            ),
            id="or in two letters",
        ),
        pytest.param(
            "the ports referred to in Article 12(3-d)",
            (Reference(raw="Article 12(3-d)", article="12", paragraph="3-d"),),
            id="a paragraph number may be hyphened",
        ),
        pytest.param(
            "using the methods set out in Annex I",
            (Reference(raw="Annex I", annex="I"),),
            id="an annex belongs to this act",
        ),
        pytest.param(
            "Annex I applies. As stated in Annex I, the factor is fixed.",
            (Reference(raw="Annex I", annex="I"),),
            id="a repeated reference is listed once",
        ),
        pytest.param(
            "This Regulation lays down rules on the use of fuels.",
            (),
            id="prose without a reference yields nothing",
        ),
        pytest.param(
            "in accordance with Articles 6, 7 and 8",
            tuple(Reference(raw=f"Article {n}", article=n) for n in ("6", "7", "8")),
            id="every article of an enumeration is listed",
        ),
        pytest.param(
            "set out in Annexes I and II",
            tuple(Reference(raw=f"Annex {n}", annex=n) for n in ("I", "II")),
            id="every annex of an enumeration is listed",
        ),
        pytest.param(
            "Article 6, 2015 saw the adoption of the scheme",
            (Reference(raw="Article 6", article="6"),),
            id="a trailing year is not a further article",
        ),
        pytest.param(
            f"verified under Article 6(2) of {MRV}",
            (
                Reference(
                    raw=f"Article 6(2) of {MRV}",
                    instrument="32015R0757",
                    article="6",
                    paragraph="2",
                ),
            ),
            id="an article goes to the instrument that qualifies it",
        ),
        pytest.param(
            f"under Articles 6 and 7 of {MRV}",
            tuple(
                Reference(raw=f"Article {n} of {MRV}", instrument="32015R0757", article=n)
                for n in ("6", "7")
            ),
            id="so does every article of an enumeration",
        ),
        pytest.param(
            "Article 6 of this Regulation applies",
            (Reference(raw="Article 6", article="6"),),
            id="this Regulation is not an external instrument",
        ),
        pytest.param(
            f"Article 6 applies. {MRV} does not.",
            (
                Reference(raw="Article 6", article="6"),
                Reference(raw=MRV, instrument="32015R0757"),
            ),
            id="an instrument an article only precedes does not qualify it",
        ),
        pytest.param(
            f"means gross tonnage as defined in Article 3, point (e), of {MRV}",
            (
                Reference(
                    raw=f"Article 3, point (e), of {MRV}",
                    instrument="32015R0757",
                    article="3",
                    point="e",
                ),
            ),
            id="an article cited by point goes to the instrument after the point",
        ),
        pytest.param(
            "‘ice class’ as defined in Article 3, point (23)",
            (Reference(raw="Article 3, point (23)", article="3", point="23"),),
            id="a point cited in this act carries its point",
        ),
        pytest.param(
            f"as set out in Annex I, point (a), of {MRV}",
            (
                Reference(
                    raw=f"Annex I, point (a), of {MRV}",
                    instrument="32015R0757",
                    annex="I",
                    point="a",
                ),
            ),
            id="a point of an annex is attributed with its point",
        ),
        pytest.param(
            "the ship at berth in Article 3(1), point (15), of Regulation (EU) 2023/1805",
            (
                Reference(
                    raw="Article 3(1), point (15), of Regulation (EU) 2023/1805",
                    instrument="32023R1805",
                    article="3",
                    paragraph="1",
                    point="15",
                ),
            ),
            id="a numbered point stays under the paragraph it belongs to",
        ),
        pytest.param(
            f"under Article 6(2), second subparagraph, of {MRV}",
            (
                Reference(
                    raw=f"Article 6(2), second subparagraph, of {MRV}",
                    instrument="32015R0757",
                    article="6",
                    paragraph="2",
                ),
            ),
            id="an article cited by subparagraph goes to the instrument after it",
        ),
        pytest.param(
            "the fictional Regulation 3021/4055",
            (),
            id="an instrument whose citation cannot be a celex id is dropped",
        ),
        pytest.param(
            "under Article 5 of Regulation 3021/4055",
            (),
            id="and the article it qualifies is not taken for this act's",
        ),
        pytest.param(
            f"set out in Annex II. {MRV} applies",
            (
                Reference(raw="Annex II", annex="II"),
                Reference(raw=MRV, instrument="32015R0757"),
            ),
            id="the institution prefix does not reach back over a sentence boundary",
        ),
        pytest.param(
            f"comply with Directive 2003/87/EC and {MRV}",
            (
                Reference(raw="Directive 2003/87/EC", instrument="32003L0087"),
                Reference(raw=MRV, instrument="32015R0757"),
            ),
            id="nor into the act cited before it",
        ),
        pytest.param(
            "THE ANNEX TO COMMISSION IMPLEMENTING REGULATION (EU) 2016/1927",
            (
                Reference(
                    raw="COMMISSION IMPLEMENTING REGULATION (EU) 2016/1927",
                    instrument="32016R1927",
                ),
            ),
            id="nor over the upper-case prose of a heading",
        ),
    ],
)
def test_each_division_is_attributed_to_the_act_it_belongs_to(
    text: str, expected: tuple[Reference, ...]
) -> None:
    assert extract_references(text) == expected


@pytest.mark.parametrize(
    ("mention", "celex"),
    [
        pytest.param(MRV, "32015R0757", id="a regulation reads year then number"),
        pytest.param("Directive 2003/87/EC", "32003L0087", id="so does a directive"),
        pytest.param(
            "Regulation (EC) No 765/2008", "32008R0765", id="a numbered act reads number first"
        ),
        pytest.param("Regulation 17/62", "31962R0017", id="so does a pre-1999 regulation"),
        pytest.param(
            "Council Directive 92/43/EEC", "31992L0043", id="a two-digit year is the 1900s"
        ),
        pytest.param("Council Regulation (EEC) No 3577/92", "31992R3577", id="Council"),
        pytest.param(
            "Commission Implementing Regulation (EU) 2016/1927",
            "32016R1927",
            id="Commission Implementing",
        ),
        pytest.param(
            "Commission Delegated Regulation (EU) 2023/1640",
            "32023R1640",
            id="Commission Delegated",
        ),
        pytest.param(
            "European Parliament and Council Directive 95/46/EC",
            "31995L0046",
            id="European Parliament and Council",
        ),
        pytest.param(
            "Council Implementing Regulation (EU) 2020/1998",
            "32020R1998",
            id="Council Implementing",
        ),
        pytest.param(
            "Council Framework Decision 2002/584/JHA", "32002D0584", id="Council Framework"
        ),
    ],
)
def test_an_instrument_is_one_mention_however_it_is_styled(mention: str, celex: str) -> None:
    """The institution naming an act is part of its mention, alone or qualifying an article."""
    assert extract_references(f"as amended by {mention}") == (
        Reference(raw=mention, instrument=celex),
    )
    assert extract_references(f"pursuant to Article 5 of {mention}") == (
        Reference(raw=f"Article 5 of {mention}", instrument=celex, article="5"),
    )


@pytest.mark.parametrize(
    ("text", "points"),
    [
        pytest.param(
            "For the purposes of this Regulation:\n(a) ‘ship’ means a vessel;\n(15) ‘berth’ means",
            ("a", "15"),
            id="a lettered or numbered point opening a line is listed",
        ),
        pytest.param(
            "as defined in Article 3, point (e), of Regulation X",
            (),
            id="a point named mid line is not",
        ),
    ],
)
def test_the_points_a_text_lists_are_the_ones_it_opens_lines_with(
    text: str, points: tuple[str, ...]
) -> None:
    assert list_points(text) == points
