"""Which acts belong in the corpus, and at what version."""

import pytest

from app.core.config import config
from app.ingestion.discover.models import ActsQueryRow, CandidateAct
from app.ingestion.discover.select import extract_candidate_acts, select_documents
from tests.conftest import act_row

MRV, MRV_2024, MRV_2025 = "32015R0757", "02015R0757-20240101", "02015R0757-20250101"
ETS = "32003L0087"


@pytest.mark.parametrize(
    ("rows", "acts"),
    [
        pytest.param(
            [
                act_row("32023R2449", in_force=True),
                act_row(MRV, in_force=True, consolidation=MRV_2024),
                act_row("32023R2449", in_force=True, consolidation="02023R2449-20250101"),
            ],
            [
                CandidateAct(celex=MRV, in_force=True, consolidations=frozenset({MRV_2024})),
                CandidateAct(
                    celex="32023R2449",
                    in_force=True,
                    consolidations=frozenset({"02023R2449-20250101"}),
                ),
            ],
            id="interleaved rows are grouped by celex",
        ),
        pytest.param(
            [
                act_row(MRV, in_force=True, consolidation=MRV_2024, title="MRV"),
                act_row(MRV, in_force=True, consolidation=MRV_2025, title="MRV"),
            ],
            [
                CandidateAct(
                    celex=MRV,
                    in_force=True,
                    consolidations=frozenset({MRV_2024, MRV_2025}),
                    title="MRV",
                )
            ],
            id="every consolidation is collected under the flag and title each row repeats",
        ),
        pytest.param(
            [
                act_row("32023D2895", in_force=True, basis_article="A12P3-c"),
                act_row("32023D2895", in_force=True, basis_article="A12P3-d"),
            ],
            [
                CandidateAct(
                    celex="32023D2895",
                    in_force=True,
                    basis_articles=frozenset({"A12P3-c", "A12P3-d"}),
                )
            ],
            id="so is every basis article",
        ),
        pytest.param(
            [act_row("32023R2449", in_force=True)],
            [CandidateAct(celex="32023R2449", in_force=True)],
            id="an act with no consolidations is kept",
        ),
        pytest.param(
            [act_row("32016R1927", in_force=False), act_row("52024IP0025")],
            [CandidateAct(celex="32016R1927", in_force=False), CandidateAct(celex="52024IP0025")],
            id="a missing in-force flag stays distinct from a false one",
        ),
    ],
)
def test_the_rows_cellar_explodes_an_act_into_fold_back_into_one_act(
    rows: list[ActsQueryRow], acts: list[CandidateAct]
) -> None:
    assert extract_candidate_acts(rows) == acts


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


@pytest.mark.parametrize(
    ("consolidations", "candidates"),
    [
        pytest.param(
            [MRV_2024, MRV_2025, "02015R0757-20161216"],
            (MRV_2025, MRV_2024, "02015R0757-20161216"),
            id="every consolidation of the act itself, newest first",
        ),
        pytest.param(
            [MRV_2025, "02023R1805-20260101"],
            (MRV_2025,),
            id="another act's consolidation is ignored even when it sorts higher",
        ),
        pytest.param([None], (), id="an act nothing has consolidated is still fetched, with none"),
    ],
)
def test_a_documents_candidates_are_its_own_consolidations(
    consolidations: list[str | None], candidates: tuple[str, ...]
) -> None:
    rows = [act_row(MRV, in_force=True, consolidation=version) for version in consolidations]

    selected = select_documents("mrv", rows)

    assert [(document.celex, document.candidates) for document in selected] == [(MRV, candidates)]


@pytest.mark.parametrize(
    ("celex", "basis_articles", "kept"),
    [
        pytest.param("32023R2599", ["A03gfP4"], True, id="Articles 3ga to 3gg are shipping"),
        pytest.param("32023D2895", ["A12P3-c"], True, id="so are the 12(3-b) to 12(3-e) cases"),
        pytest.param("32024R2620", ["A12P3bL2"], False, id="12(3b) is carbon capture"),
        pytest.param("32010D0001", ["A03gP1"], False, id="Article 3g itself is aviation"),
        pytest.param("32009R0748", ["A03cP6"], False, id="another sector's article"),
        pytest.param("32010D0002", ["XA03ga"], False, id="an article is matched from its start"),
        pytest.param("32010D0670", [None], False, id="an act naming no article"),
        pytest.param(
            "32024D0411",
            ["A03gfP2PTA)", "A03gfP4"],
            False,
            id="a list of shipping companies is left out whatever else it was adopted under",
        ),
        pytest.param(
            "32028D0100", ["A03gfP2PTB)"], False, id="and so is whichever act replaces that list"
        ),
    ],
)
def test_ets_keeps_the_base_act_and_the_maritime_acts_adopted_under_it(
    celex: str, basis_articles: list[str | None], kept: bool
) -> None:
    rows = [act_row(ETS, in_force=True)]
    rows += [act_row(celex, in_force=True, basis_article=article) for article in basis_articles]

    selected = select_documents(
        "ets",
        rows,
        base_celex=ETS,
        kept_basis=config.TOPIC_BASIS_ARTICLES["ets"],
        excluded_basis=config.TOPIC_EXCLUDED_BASIS_ARTICLES["ets"],
    )

    assert [document.celex for document in selected] == [ETS, *([celex] if kept else [])]
