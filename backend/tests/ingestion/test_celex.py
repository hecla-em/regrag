"""CELEX id format: recognition, assembly and the consolidated-version stem."""

import pytest

from app.ingestion import celex


@pytest.mark.parametrize(
    ("kind", "year", "number", "expected"),
    [
        ("Regulation", "2015", "757", "32015R0757"),
        ("Directive", "2003", "87", "32003L0087"),
        ("Decision", "2013", "162", "32013D0162"),
        ("regulation", "2008", "765", "32008R0765"),
        ("Regulation", "2023", "1805", "32023R1805"),
        ("Directive", "92", "43", "31992L0043"),
        ("Regulation", "92", "2913", "31992R2913"),
    ],
)
def test_build_pads_the_number_and_maps_the_kind(kind, year, number, expected) -> None:
    assert celex.build(kind, year, number) == expected


@pytest.mark.parametrize("year", ["3021", "1", "757"])
def test_build_rejects_a_year_no_act_can_have(year: str) -> None:
    with pytest.raises(ValueError, match="not a legislation citation"):
        celex.build("Regulation", year, "757")


@pytest.mark.parametrize(
    ("kind", "pair", "expected"),
    [
        pytest.param(
            "Regulation",
            ("765", "2008"),
            ("765", "2008"),
            id="only one half can be a year: Regulation (EC) No 765/2008",
        ),
        pytest.param(
            "Regulation",
            ("2913", "92"),
            ("2913", "92"),
            id="only one half can be a year: Regulation (EEC) No 2913/92",
        ),
        pytest.param(
            "Regulation",
            ("2015", "757"),
            ("757", "2015"),
            id="only one half can be a year: Regulation (EU) No 2015/757",
        ),
        pytest.param(
            "Regulation",
            ("2018", "2066"),
            ("2066", "2018"),
            id="only one half can be a year: Regulation (EU) 2018/2066",
        ),
        pytest.param(
            "Decision",
            ("1600", "2002"),
            ("1600", "2002"),
            id="only one half can be a year: Decision No 1600/2002/EC",
        ),
        pytest.param(
            "Regulation",
            ("95", "93"),
            ("95", "93"),
            id="an older regulation, number first: Regulation (EEC) No 95/93",
        ),
        pytest.param(
            "Regulation",
            ("2003", "2003"),
            ("2003", "2003"),
            id="an older regulation, number first: Regulation (EC) No 2003/2003",
        ),
        pytest.param(
            "Regulation",
            ("1907", "2006"),
            ("1907", "2006"),
            id="an older regulation, number first: Regulation (EC) 1907/2006",
        ),
        pytest.param(
            "Regulation",
            ("17", "62"),
            ("17", "62"),
            id="an older regulation, number first: Regulation 17/62",
        ),
        pytest.param(
            "Regulation",
            ("2015", "1998"),
            ("1998", "2015"),
            id="a regulation from 2015, year first: Regulation (EU) No 2015/1998",
        ),
        pytest.param(
            "Regulation",
            ("2019", "2020"),
            ("2020", "2019"),
            id="a regulation from 2015, year first: Regulation (EU) 2019/2020",
        ),
        pytest.param(
            "Directive",
            ("2003", "87"),
            ("87", "2003"),
            id="a directive, always year first: Directive 2003/87/EC",
        ),
        pytest.param(
            "Directive",
            ("92", "43"),
            ("43", "92"),
            id="a directive, always year first: Council Directive 92/43/EEC",
        ),
        pytest.param(
            "Directive",
            ("70", "50"),
            ("50", "70"),
            id="a directive, always year first: Commission Directive No 70/50/EEC",
        ),
        pytest.param(
            "Decision",
            ("2002", "584"),
            ("584", "2002"),
            id="a decision, always year first: Council Framework Decision 2002/584/JHA",
        ),
    ],
)
def test_a_cited_pair_is_ordered_as_number_then_year(kind, pair, expected) -> None:
    """Where both halves are year-shaped the kind and the 2015 scheme settle it."""
    assert celex.order_number_and_year(kind, *pair) == expected


@pytest.mark.parametrize(
    ("celex_id", "is_legislation"),
    [
        pytest.param("32015R0757", True, id="a regulation"),
        pytest.param("32003L0087", True, id="a directive"),
        pytest.param("32013D0162", True, id="a decision"),
        pytest.param("02015R0757-20250101", False, id="a consolidated version"),
        pytest.param("52015PC0337", False, id="a proposal, from another sector"),
        pytest.param("62015CJ0001", False, id="case law, from another sector"),
        pytest.param("32015X0757", False, id="a kind letter that is not an act"),
        pytest.param("3201", False, id="too short to be an id"),
        pytest.param("392L0043", False, id="a two-digit year"),
        pytest.param("3201XR0757", False, id="a year that is not digits"),
        pytest.param("32015R075A", False, id="a number that is not digits"),
    ],
)
def test_only_a_regulation_directive_or_decision_id_is_legislation(
    celex_id: str, is_legislation: bool
) -> None:
    assert celex.is_legislation(celex_id) is is_legislation


@pytest.mark.parametrize(
    ("celex_id", "expected"),
    [
        ("32023R1805", "Regulation (EU) 2023/1805"),
        ("32015R0757", "Regulation (EU) 2015/757"),
        ("32026R0394", "Regulation (EU) 2026/394"),
        ("32023L0959", "Directive (EU) 2023/959"),
        ("32023D0852", "Decision (EU) 2023/852"),
    ],
)
def test_act_names_read_as_the_act_is_cited(celex_id: str, expected: str) -> None:
    assert celex.format_act_name(celex_id) == expected


@pytest.mark.parametrize(
    "celex_id", ["32008R0765", "31992L0043", "02015R0757-20250101", "3201", "3201XR0757"]
)
def test_act_names_fall_back_to_the_id_outside_the_year_first_scheme(celex_id: str) -> None:
    assert celex.format_act_name(celex_id) == celex_id


@pytest.mark.parametrize(
    ("celex_id", "title", "expected"),
    [
        (
            "32003L0087",
            "Directive 2003/87/EC of the European Parliament and of the Council of 13 October 2003",
            "Directive 2003/87/EC",
        ),
        (
            "32006R0336",
            "Regulation (EC) No 336/2006 of the European Parliament and of the Council of  15 Feb",
            "Regulation (EC) No 336/2006",
        ),
        (
            "32003L0096",
            "Council Directive 2003/96/EC of 27 October 2003 restructuring the Community framework",
            "Directive 2003/96/EC",
        ),
        (
            "32010R1095",
            "Regulation (EU) No 1095/2010 of the European Parliament and of the Council",
            "Regulation (EU) No 1095/2010",
        ),
    ],
)
def test_older_act_names_are_read_off_their_title(celex_id: str, title: str, expected: str) -> None:
    assert celex.format_act_name(celex_id, title) == expected


def test_older_act_names_fall_back_to_the_id_on_a_title_without_a_citation() -> None:
    title = "Directive on the use of emissions trading"
    assert celex.format_act_name("32003L0087", title) == "32003L0087"


def test_year_first_act_names_ignore_the_title() -> None:
    title = "Commission Implementing Regulation (EU) 2023/2599 of 22 November 2023"
    assert celex.format_act_name("32023R2599", title) == "Regulation (EU) 2023/2599"
