"""Judging a case: which dimensions run, what each call asks, and how a failing call lands."""

import logging

import pytest
from openai import APIConnectionError

from app.core.config import config
from app.evals.judge.enums import JudgeVerdict
from app.evals.judge.models import (
    CaseJudgement,
    ClaimVerdict,
    CorrectnessVerdict,
    FaithfulnessVerdict,
    RefusalVerdict,
)
from app.evals.judge.prompts import REFUSAL_PROMPT, build_refusal_message
from app.evals.judge.service import call_judge_model, judge_case
from app.evals.models import EvalCaseResult
from tests.conftest import provider_error, retrieved_chunk
from tests.evals.conftest import (
    eval_case,
    eval_result,
    judge_response,
    out_of_corpus_case,
    refused_result,
)

pytestmark = pytest.mark.anyio

PASSED = CorrectnessVerdict(critique="states the half rule", verdict=JudgeVerdict.PASS)
GROUNDED = FaithfulnessVerdict(
    critique="in [1]", claims=(ClaimVerdict(claim="half counts", supported=True),)
)
DECLINED = RefusalVerdict(critique="says the corpus lacks it", verdict=JudgeVerdict.PASS)


# The call


@pytest.mark.parametrize(
    ("result", "answers", "calls_made", "judgement", "warned"),
    [
        pytest.param(
            eval_result(out_of_corpus_case()),
            [judge_response('{"critique": "The answer', finish_reason="length")],
            1,
            CaseJudgement(),
            "stopped on length",
            id="an answer off the schema is a failed call that says why it stopped",
        ),
        pytest.param(
            eval_result(out_of_corpus_case()),
            [provider_error(APIConnectionError)] * 3,
            3,
            CaseJudgement(),
            "left unjudged",
            id="a transient provider failure is retried, then left unjudged",
        ),
        pytest.param(
            eval_result(),
            ['{"critique": "not a verdict"}', GROUNDED],
            2,
            CaseJudgement(faithfulness=GROUNDED),
            "left unjudged",
            id="a failed dimension does not stop the next",
        ),
    ],
)
async def test_a_failing_judge_call_leaves_its_dimension_unjudged_and_the_run_going(
    judge_answers,
    caplog,
    result: EvalCaseResult,
    answers: list,
    calls_made: int,
    judgement: CaseJudgement,
    warned: str,
) -> None:
    calls = judge_answers(*answers)

    with caplog.at_level(logging.WARNING):
        judged = await judge_case(result.case, result.state)

    assert judged == judgement
    assert len(calls) == calls_made
    assert warned in caplog.text


# Which dimensions a case is judged on

REFERENCE_ANSWER = "Half of it."
CITED_BLOCK = retrieved_chunk().text


@pytest.mark.parametrize(
    ("result", "judgement", "asked"),
    [
        pytest.param(
            eval_result(eval_case(answer=REFERENCE_ANSWER), answer="Half counts [1]."),
            CaseJudgement(correctness=PASSED, faithfulness=GROUNDED),
            [(CorrectnessVerdict, REFERENCE_ANSWER), (FaithfulnessVerdict, CITED_BLOCK)],
            id="an in-corpus answer on correctness, and on faithfulness to what it cited",
        ),
        pytest.param(
            eval_result(eval_case(answer=REFERENCE_ANSWER), answer="Half counts, uncited."),
            CaseJudgement(correctness=PASSED),
            [(CorrectnessVerdict, REFERENCE_ANSWER)],
            id="an answer citing nothing gets no faithfulness call",
        ),
        pytest.param(
            eval_result(eval_case(answer=REFERENCE_ANSWER), answer="Half counts [7]."),
            CaseJudgement(correctness=PASSED),
            [(CorrectnessVerdict, REFERENCE_ANSWER)],
            id="nor does one citing only blocks it was never given",
        ),
        pytest.param(
            eval_result(out_of_corpus_case(), answer="I can't say from this corpus."),
            CaseJudgement(refusal=DECLINED),
            [(RefusalVerdict, "I can't say from this corpus.")],
            id="an out-of-corpus answer on whether it declined",
        ),
        pytest.param(refused_result(), CaseJudgement(), [], id="a gate refusal by nothing"),
        pytest.param(
            eval_result(error="TimeoutError"), CaseJudgement(), [], id="an errored case by nothing"
        ),
    ],
)
async def test_a_case_is_judged_on_the_dimensions_its_kind_and_its_answer_allow(
    judge_answers,
    result: EvalCaseResult,
    judgement: CaseJudgement,
    asked: list[tuple[type, str]],
) -> None:
    """Each call is named by the verdict it asks for and a text it must carry: the reference
    answer, the cited block, or the answer that may have declined."""
    verdicts = (judgement.correctness, judgement.faithfulness, judgement.refusal)
    calls = judge_answers(*[verdict for verdict in verdicts if verdict is not None])

    judged = await judge_case(result.case, result.state)

    assert judged == judgement
    assert [call["response_format"] for call in calls] == [verdict for verdict, _ in asked]
    for call, (_, carried) in zip(calls, asked, strict=True):
        assert carried in call["messages"][1]["content"]


# The real seam, run only with a key in the environment


@pytest.mark.skipif(not config.OPENROUTER_API_KEY.get_secret_value(), reason="needs a provider key")
async def test_the_judge_model_returns_a_verdict_in_the_asked_shape() -> None:
    message = build_refusal_message(
        "How many ETS allowances must a company surrender for 2025?",
        "The material I have covers FuelEU and MRV, not the ETS, so I can't answer that.",
    )

    verdict = await call_judge_model(REFUSAL_PROMPT, message, RefusalVerdict)

    assert verdict.verdict is JudgeVerdict.PASS
    assert verdict.critique
