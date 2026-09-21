"""Eval run values: when a judged run's scores mean what a full run's mean."""

import pytest

from app.core.config import config
from app.evals.models import EvalCaseResult
from tests.evals.conftest import eval_case, eval_result, eval_run, passed_judgement, refused_result


def answered_cases(judged: int, unjudged: int) -> list[EvalCaseResult]:
    """Answered cases, the first of them carrying a verdict and the rest none."""
    return [
        eval_result(eval_case(id=f"case-{i}"), judgement=passed_judgement() if i < judged else None)
        for i in range(judged + unjudged)
    ]


ERRORED = eval_result(eval_case(id="boom"), judgement=passed_judgement(), error="TimeoutError")


@pytest.mark.parametrize(
    ("results", "judge_on", "coverage", "too_few", "never_answered"),
    [
        pytest.param(
            [*answered_cases(1, 0), refused_result(), ERRORED],
            True,
            1.0,
            False,
            False,
            id="a gate refusal and an errored case are owed no verdict",
        ),
        pytest.param(
            answered_cases(6, 4), True, 0.6, True, False, id="a share under the threshold fails"
        ),
        pytest.param(
            answered_cases(9, 1), True, 0.9, False, False, id="a share exactly at it passes"
        ),
        pytest.param(
            answered_cases(0, 1), True, 0.0, True, True, id="no verdict at all is a silent judge"
        ),
        pytest.param(
            answered_cases(0, 1), False, None, False, False, id="a judge that was off is not"
        ),
        pytest.param(
            [refused_result()], True, None, False, False, id="nor is a run that answered nothing"
        ),
    ],
)
def test_judged_coverage_is_the_share_of_answered_cases_the_judge_came_back_on(
    monkeypatch: pytest.MonkeyPatch,
    results: list[EvalCaseResult],
    judge_on: bool,
    coverage: float | None,
    too_few: bool,
    never_answered: bool,
) -> None:
    """A part-judged run's scores are that subset's, which is worse than no number."""
    monkeypatch.setattr(config, "EVAL_JUDGE_MIN_COVERAGE", 0.9)

    run = eval_run(*results, judged=judge_on)

    assert run.judged_coverage == coverage
    assert run.judged_too_few is too_few
    assert run.judge_never_answered is never_answered
