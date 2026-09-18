"""Which acts belong in the corpus, and at what version."""

from app.ingestion.discover.models import DiscoveredDocument
from app.ingestion.discover.select import (
    extract_candidate_acts,
    filter_acts_by_basis_article,
    filter_legislative_acts,
    select_documents,
)
from tests.conftest import act_row


def test_filter_legislative_acts_drops_resolutions_and_communications():
    rows = [
        act_row("32015R0757", in_force=True),
        act_row("52024XC07469", in_force=True),
        act_row("52024IP0025", in_force=True),
        act_row("E2021X0415(01)", in_force=True),
    ]
    assert [row.celex for row in filter_legislative_acts(rows)] == ["32015R0757"]


def test_extract_candidate_acts_folds_every_row_for_one_celex():
    rows = [
        act_row("32015R0757", in_force=True, consolidation="02015R0757-20240101"),
        act_row("32015R0757", in_force=True, consolidation="02015R0757-20250101"),
    ]
    acts = extract_candidate_acts(rows)
    assert len(acts) == 1
    assert acts[0].consolidations == frozenset({"02015R0757-20240101", "02015R0757-20250101"})
    assert acts[0].in_force is True


def test_extract_candidate_acts_groups_interleaved_rows_by_celex():
    rows = [
        act_row("32023R2449", in_force=True),
        act_row("32015R0757", in_force=True, consolidation="02015R0757-20240101"),
        act_row("32023R2449", in_force=True, consolidation="02023R2449-20250101"),
    ]
    acts = extract_candidate_acts(rows)
    assert [act.celex for act in acts] == ["32015R0757", "32023R2449"]
    assert acts[1].consolidations == frozenset({"02023R2449-20250101"})


def test_extract_candidate_acts_carries_the_title_every_row_repeats():
    rows = [
        act_row("32015R0757", in_force=True, consolidation="02015R0757-20240101", title="MRV"),
        act_row("32015R0757", in_force=True, consolidation="02015R0757-20250101", title="MRV"),
    ]
    assert extract_candidate_acts(rows)[0].title == "MRV"


def test_select_documents_carries_the_title_to_the_document():
    selected = select_documents("mrv", [act_row("32015R0757", in_force=True, title="MRV")])
    assert selected[0].title == "MRV"


def test_extract_candidate_acts_keeps_an_act_that_has_no_consolidations():
    acts = extract_candidate_acts([act_row("32023R2449", in_force=True)])
    assert acts[0].consolidations == frozenset()


def test_extract_candidate_acts_keeps_a_missing_flag_distinct_from_a_false_one():
    acts = extract_candidate_acts([act_row("32016R1927", in_force=False), act_row("52024IP0025")])
    assert [act.in_force for act in acts] == [False, None]


def test_only_acts_flagged_in_force_are_fetched():
    """Repealed (flagged false) and unstated (the flag never bound) are both left out."""
    selected = select_documents(
        "mrv",
        [
            act_row("32016R1927", in_force=False),
            act_row("32016R1926"),
            act_row("32016R1928", in_force=True),
        ],
    )
    assert [s.celex for s in selected] == ["32016R1928"]


def test_folded_amendment_filtered():
    """32023R2776 consolidates only into another act, so its text already lives in 32015R0757."""
    selected = select_documents(
        "mrv",
        [
            act_row("32023R2776", in_force=True, consolidation="02015R0757-20240101"),
            act_row("32015R0757", in_force=True, consolidation="02015R0757-20240101"),
        ],
    )
    assert [s.celex for s in selected] == ["32015R0757"]
    assert selected[0].candidates == ("02015R0757-20240101",)


def test_candidates_are_every_own_stem_consolidation_newest_first():
    selected = select_documents(
        "mrv",
        [
            act_row("32015R0757", in_force=True, consolidation="02015R0757-20240101"),
            act_row("32015R0757", in_force=True, consolidation="02015R0757-20250101"),
            act_row("32015R0757", in_force=True, consolidation="02015R0757-20161216"),
        ],
    )
    assert selected[0].candidates == (
        "02015R0757-20250101",
        "02015R0757-20240101",
        "02015R0757-20161216",
    )


def test_candidates_ignore_another_acts_consolidations_even_when_they_sort_higher():
    selected = select_documents(
        "mrv",
        [
            act_row("32015R0757", in_force=True, consolidation="02015R0757-20250101"),
            act_row("32015R0757", in_force=True, consolidation="02023R1805-20260101"),
        ],
    )
    assert selected[0].candidates == ("02015R0757-20250101",)


def test_no_consolidations_gives_no_candidates():
    """An act nothing has consolidated is not folded into anything, so it is still fetched."""
    selected = select_documents("mrv", [act_row("32023R2449", in_force=True)])
    assert [s.celex for s in selected] == ["32023R2449"]
    assert selected[0].candidates == ()


def test_documents_carry_topic_and_source():
    document = select_documents("fueleu", [act_row("32023R1805", in_force=True)])[0]
    assert document == DiscoveredDocument(
        topic="fueleu", source="eurlex", celex="32023R1805", candidates=()
    )


def test_extract_candidate_acts_collects_every_basis_article():
    rows = [
        act_row("32023D2895", in_force=True, basis_article="A12P3-c"),
        act_row("32023D2895", in_force=True, basis_article="A12P3-d"),
    ]
    assert extract_candidate_acts(rows)[0].basis_articles == frozenset({"A12P3-c", "A12P3-d"})


def test_filter_acts_by_basis_article_keeps_acts_based_on_a_listed_article():
    rows = [
        act_row("32023R2599", basis_article="A03gfP4"),
        act_row("32023D2895", basis_article="A12P3-c"),
        act_row("32024R2620", basis_article="A12P3bL2"),
        act_row("32009R0748", basis_article="A03cP6"),
        act_row("32010D0670"),
    ]
    kept = filter_acts_by_basis_article(
        extract_candidate_acts(rows), "32003L0087", ("A03g", "A12P3-")
    )
    assert [act.celex for act in kept] == ["32023D2895", "32023R2599"]


def test_filter_acts_by_basis_article_always_keeps_the_base_act():
    acts = extract_candidate_acts([act_row("32003L0087"), act_row("32009R0748")])
    kept = filter_acts_by_basis_article(acts, "32003L0087", ("A03g",))
    assert [act.celex for act in kept] == ["32003L0087"]


def test_select_documents_keeps_only_maritime_acts_for_ets():
    rows = [
        act_row("32003L0087", in_force=True),
        act_row("32023R2599", in_force=True, basis_article="A03gfP4"),
        act_row("32009R0748", in_force=True, basis_article="A03cP6"),
    ]
    selected = select_documents("ets", rows)
    assert [document.celex for document in selected] == ["32003L0087", "32023R2599"]


def test_select_documents_keeps_every_act_of_a_topic_with_no_basis_articles():
    rows = [
        act_row("32015R0757", in_force=True),
        act_row("32016R1928", in_force=True, basis_article="A05P2"),
    ]
    assert [d.celex for d in select_documents("mrv", rows)] == ["32015R0757", "32016R1928"]


def test_select_documents_leaves_out_an_act_the_topic_excludes():
    """The list of shipping companies is names, not rules."""
    rows = [
        act_row("32003L0087", in_force=True),
        act_row("32024D0411", in_force=True, basis_article="A03gfP2PTA)"),
    ]
    assert [d.celex for d in select_documents("ets", rows)] == ["32003L0087"]
