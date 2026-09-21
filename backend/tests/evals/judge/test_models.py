"""Judge values: how a verdict becomes a score."""

import pytest

from app.evals.judge.models import ClaimVerdict, FaithfulnessVerdict


@pytest.mark.parametrize(
    ("supported", "score", "unsupported"),
    [
        pytest.param(
            {"a": True, "b": False, "c": True, "d": False},
            0.5,
            ("b", "d"),
            id="the supported share of the claims",
        ),
        pytest.param({}, None, (), id="no claim is unmeasured, not perfectly faithful"),
    ],
)
def test_faithfulness_is_scored_over_the_claims_the_answer_made(
    supported: dict[str, bool], score: float | None, unsupported: tuple[str, ...]
) -> None:
    claims = tuple(ClaimVerdict(claim=claim, supported=held) for claim, held in supported.items())
    verdict = FaithfulnessVerdict(critique="", claims=claims)

    assert verdict.score() == score
    assert verdict.unsupported_claims() == unsupported
