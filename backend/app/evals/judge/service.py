"""Judging a run's cases: the dimensions that apply to each, one model call per dimension."""

import asyncio
import logging
from collections.abc import Sequence

import litellm

from app.chat.citations import find_cited_sources
from app.chat.enums import ChatOutcome
from app.chat.models import ChatState
from app.core.concurrency import run_concurrently
from app.core.config import config
from app.core.llm.errors import LLMError, llm_retry, parse_model_answer, wrap_provider_errors
from app.core.llm.keys import api_key_for
from app.core.models import FrozenModel
from app.evals.dataset.enums import EvalKind
from app.evals.dataset.models import EvalCase
from app.evals.judge.models import (
    CaseJudgement,
    CorrectnessVerdict,
    FaithfulnessVerdict,
    RefusalVerdict,
)
from app.evals.judge.prompts import (
    CORRECTNESS_PROMPT,
    FAITHFULNESS_PROMPT,
    REFUSAL_PROMPT,
    build_correctness_message,
    build_faithfulness_message,
    build_refusal_message,
)
from app.evals.models import EvalCaseResult

logger = logging.getLogger(__name__)


@llm_retry
@wrap_provider_errors("judge call")
async def call_judge_model[T: FrozenModel](system: str, user: str, output: type[T]) -> T:
    """One blocking judge turn answering in the verdict's own shape, with the key of whichever
    provider the judge names; an answer off the schema is a failed call, not a verdict."""
    response = await litellm.acompletion(
        model=config.EVAL_JUDGE_MODEL,
        api_key=api_key_for(config.EVAL_JUDGE_MODEL),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format=output,
        max_tokens=config.EVAL_JUDGE_MAX_TOKENS,
        timeout=config.EVAL_JUDGE_TIMEOUT,
    )
    choice = response.choices[0]
    return parse_model_answer(
        output, choice.message.content or "", label="judge", stopped_on=choice.finish_reason
    )


async def _judge[T: FrozenModel](system: str, user: str, output: type[T]) -> T | None:
    """A dimension's verdict, or None when the call failed: a judge that cannot be reached
    leaves the dimension unmeasured rather than failing the run."""
    try:
        return await call_judge_model(system, user, output)
    except LLMError as exc:
        logger.warning("%s left unjudged: %s", output.__name__, exc)
        return None


async def _judge_answer(case: EvalCase, state: ChatState) -> CaseJudgement:
    """An in-corpus answer on its correctness, and on its faithfulness when it cited a block
    it was given to be faithful to; the two calls share nothing, so they run together."""
    message = build_correctness_message(case.question, case.answer or "", state.answer)
    correctness = _judge(CORRECTNESS_PROMPT, message, CorrectnessVerdict)
    if not find_cited_sources(state.answer, state.sources):
        return CaseJudgement(correctness=await correctness)
    message = build_faithfulness_message(state.answer, state.sources)
    faithfulness = _judge(FAITHFULNESS_PROMPT, message, FaithfulnessVerdict)
    correct, faithful = await asyncio.gather(correctness, faithfulness)
    return CaseJudgement(correctness=correct, faithfulness=faithful)


async def judge_case(case: EvalCase, state: ChatState) -> CaseJudgement:
    """The dimensions this case can be judged on. Only an answered case is judged: a gate
    refusal is scored by the gate metrics, and an errored case is scored by nothing. An
    out-of-corpus answer is judged on whether it declined; an in-corpus answer on its
    correctness and faithfulness."""
    if state.outcome is not ChatOutcome.DONE:
        return CaseJudgement()
    if case.kind is EvalKind.OUT_OF_CORPUS:
        message = build_refusal_message(case.question, state.answer)
        return CaseJudgement(refusal=await _judge(REFUSAL_PROMPT, message, RefusalVerdict))
    return await _judge_answer(case, state)


async def judge_results(results: Sequence[EvalCaseResult]) -> list[EvalCaseResult]:
    """Every result with its judgement filled in, the cases judged a few at a time. Runs
    once the cases have all been timed, so judge latency never reaches a case's timing."""

    async def judge_one(result: EvalCaseResult) -> CaseJudgement:
        return await judge_case(result.case, result.state)

    async with run_concurrently(results, judge_one, limit=config.EVAL_JUDGE_CONCURRENCY) as pairs:
        return [result.model_copy(update={"judgement": await task}) for result, task in pairs]
