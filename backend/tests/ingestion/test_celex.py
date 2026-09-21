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
            "Regulation", ("765", "2008"), ("765", "2008"), id="Regulation (EC) No 765/2008"
        ),
        pytest.param(
            "Regulation", ("2913", "92"), ("2913", "92"), id="Regulation (EEC) No 2913/92"
        ),
        pytest.param(
            "Regulation", ("2015", "757"), ("757", "2015"), id="Regulation (EU) No 2015/757"
        ),
        pytest.param(
            "Regulation", ("2018", "2066"), ("2066", "2018"), id="Regulation (EU) 2018/2066"
        ),
        pytest.param("Decision", ("1600", "2002"), ("1600", "2002"), id="Decision No 1600/2002/EC"),
    ],
)
def test_the_half_that_cannot_be_a_year_is_the_act_number(kind, pair, expected) -> None:
    """Where only one half is year-shaped, nothing else needs consulting."""
    assert celex.order_number_and_year(kind, *pair) == expected


@pytest.mark.parametrize(
    ("kind", "pair", "expected"),
    [
        pytest.param("Regulation", ("95", "93"), ("95", "93"), id="Regulation (EEC) No 95/93"),
        pytest.param(
            "Regulation", ("2003", "2003"), ("2003", "2003"), id="Regulation (EC) No 2003/2003"
        ),
        pytest.param(
            "Regulation", ("1907", "2006"), ("1907", "2006"), id="Regulation (EC) 1907/2006"
        ),
        pytest.param("Regulation", ("17", "62"), ("17", "62"), id="Regulation 17/62"),
        pytest.param(
            "Regulation", ("2015", "1998"), ("1998", "2015"), id="Regulation (EU) No 2015/1998"
        ),
        pytest.param(
            "Regulation", ("2019", "2020"), ("2020", "2019"), id="Regulation (EU) 2019/2020"
        ),
        pytest.param("Directive", ("2003", "87"), ("87", "2003"), id="Directive 2003/87/EC"),
        pytest.param("Directive", ("92", "43"), ("43", "92"), id="Council Directive 92/43/EEC"),
        pytest.param(
            "Directive", ("70", "50"), ("50", "70"), id="Commission Directive No 70/50/EEC"
        ),
        pytest.param(
            "Decision",
            ("2002", "584"),
            ("584", "2002"),
            id="Council Framework Decision 2002/584/JHA",
        ),
    ],
)
def test_two_year_shaped_halves_are_split_by_kind_and_scheme(kind, pair, expected) -> None:
    """Directives and decisions were always year-first; regulations only from 2015 on."""
    assert celex.order_number_and_year(kind, *pair) == expected


@pytest.mark.parametrize("celex_id", ["32015R0757", "32003L0087", "32013D0162"])
def test_legislation_ids_are_recognised(celex_id: str) -> None:
    assert celex.is_legislation(celex_id)


@pytest.mark.parametrize(
    "celex_id",
    [
        "02015R0757-20250101",
        "52015PC0337",
        "62015CJ0001",
        "32015X0757",
        "3201",
        "392L0043",
        "3201XR0757",
        "32015R075A",
    ],
)
def test_non_legislation_ids_are_rejected(celex_id: str) -> None:
    assert not celex.is_legislation(celex_id)


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
