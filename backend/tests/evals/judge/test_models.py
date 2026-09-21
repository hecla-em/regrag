"""Judge values: how a verdict becomes a score."""

from app.evals.judge.models import (
    ClaimVerdict,
    FaithfulnessVerdict,
)


def test_faithfulness_is_the_supported_share_of_the_claims() -> None:
    verdict = FaithfulnessVerdict(
        critique="",
        claims=(
            ClaimVerdict(claim="a", supported=True),
            ClaimVerdict(claim="b", supported=False),
            ClaimVerdict(claim="c", supported=True),
            ClaimVerdict(claim="d", supported=False),
        ),
    )

    assert verdict.score() == 0.5
    assert verdict.unsupported_claims() == ("b", "d")


def test_an_answer_making_no_claim_is_unmeasured_not_perfectly_faithful() -> None:
    assert FaithfulnessVerdict(critique="", claims=()).score() is None
