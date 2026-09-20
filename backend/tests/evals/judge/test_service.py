"""Judging a case: which dimensions run, what each call asks, and how a failing call lands."""

import asyncio
import logging
from typing import Any

import litellm
import pytest
from litellm import Choices, Message, ModelResponse, Usage
from openai import APIConnectionError

from app.core.config import config
from app.core.models import FrozenModel
from app.evals.judge import service
from app.evals.judge.enums import CorrectnessFailure, JudgeVerdict
from app.evals.judge.models import (
    CaseJudgement,
    ClaimVerdict,
    CorrectnessVerdict,
    FaithfulnessVerdict,
    RefusalVerdict,
)
from app.evals.judge.prompts import CORRECTNESS_PROMPT, REFUSAL_PROMPT, build_refusal_message
from app.evals.judge.service import call_judge_model, judge_case, judge_results
from tests.conftest import provider_error
from tests.evals.conftest import eval_case, eval_result, out_of_corpus_case, refused_result

pytestmark = pytest.mark.anyio

PASSED = CorrectnessVerdict(critique="states the half rule", verdict=JudgeVerdict.PASS)
GROUNDED = FaithfulnessVerdict(
    critique="in [1]", claims=(ClaimVerdict(claim="half counts", supported=True),)
)
DECLINED = RefusalVerdict(critique="says the corpus lacks it", verdict=JudgeVerdict.PASS)


def judge_response(payload: FrozenModel | str, finish_reason: str = "stop") -> ModelResponse:
    """A completion as litellm returns one, its content the verdict's JSON."""
    content = payload if isinstance(payload, str) else payload.model_dump_json()
    return ModelResponse(
        choices=[Choices(message=Message(content=content), finish_reason=finish_reason)],
        usage=Usage(prompt_tokens=200, completion_tokens=60),
    )


@pytest.fixture
def judge_answers(monkeypatch: pytest.MonkeyPatch):
    """Install a judge answering each call with the next given verdict, or raising the next
    given error; hands back the list every call's arguments are recorded in. Gathered calls
    still arrive in the order they were made, as the fake never yields."""
    calls: list[dict[str, Any]] = []

    def install(*answers: FrozenModel | str | ModelResponse | Exception) -> list[dict[str, Any]]:
        queue = list(answers)

        async def fake_acompletion(**kwargs: Any) -> ModelResponse:
            calls.append(kwargs)
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            if isinstance(answer, ModelResponse):
                return answer
            return judge_response(answer)

        monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
        return calls

    return install


# The call


async def test_a_judge_call_asks_for_the_verdicts_shape_and_drops_what_the_model_rejects(
    judge_answers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "EVAL_JUDGE_MODEL", "openrouter/anthropic/claude-sonnet-5")
    calls = judge_answers(DECLINED)

    verdict = await call_judge_model(REFUSAL_PROMPT, "user turn", RefusalVerdict)

    assert verdict == DECLINED
    [call] = calls
    assert call["model"] == "openrouter/anthropic/claude-sonnet-5"
    assert call["response_format"] is RefusalVerdict
    assert call["api_key"] == config.OPENROUTER_API_KEY.get_secret_value()
    assert call["messages"] == [
        {"role": "system", "content": REFUSAL_PROMPT},
        {"role": "user", "content": "user turn"},
    ]


async def test_a_judge_call_waits_the_judges_own_timeout(
    judge_answers, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tier above the chat model and a longer answer, so the chat wait would cut it off."""
    monkeypatch.setattr(config, "EVAL_JUDGE_TIMEOUT", 321)
    calls = judge_answers(DECLINED)

    await call_judge_model(REFUSAL_PROMPT, "user turn", RefusalVerdict)

    [call] = calls
    assert call["timeout"] == 321
    assert call["timeout"] != config.CHAT_TIMEOUT


async def test_a_judge_call_spends_the_judges_own_token_cap(
    judge_answers, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The verdict is critique first, and a judge that thinks spends the cap on that too."""
    monkeypatch.setattr(config, "EVAL_JUDGE_MAX_TOKENS", 4321, raising=False)
    calls = judge_answers(DECLINED)

    await call_judge_model(REFUSAL_PROMPT, "user turn", RefusalVerdict)

    [call] = calls
    assert call["max_tokens"] == 4321


async def test_an_answer_off_the_schema_is_a_failed_call_that_says_why_it_stopped(
    judge_answers, caplog
) -> None:
    judge_answers(judge_response('{"critique": "The answer', finish_reason="length"))

    with caplog.at_level(logging.WARNING):
        judgement = await judge_case(out_of_corpus_case(), eval_result().state)

    assert judgement.refusal is None
    assert "judge answered off its schema, stopped on length" in caplog.text
    assert "RefusalVerdict left unjudged: judge answered off its schema" in caplog.text


async def test_a_transient_provider_failure_is_retried_then_left_unjudged(
    judge_answers, caplog
) -> None:
    calls = judge_answers(*[provider_error(APIConnectionError)] * 3)

    with caplog.at_level(logging.WARNING):
        judgement = await judge_case(out_of_corpus_case(), eval_result().state)

    assert judgement.refusal is None
    assert len(calls) == 3
    assert "left unjudged" in caplog.text


# Which dimensions a case is judged on


async def test_an_in_corpus_answer_is_judged_on_correctness_and_faithfulness(
    judge_answers,
) -> None:
    calls = judge_answers(PASSED, GROUNDED)
    result = eval_result(eval_case(answer="Half of it."), answer="Half counts [1].")

    judgement = await judge_case(result.case, result.state)

    assert judgement.correctness == PASSED
    assert judgement.faithfulness == GROUNDED
    correctness, faithfulness = calls
    assert correctness["messages"][0]["content"] == CORRECTNESS_PROMPT
    assert "Reference answer:\nHalf of it." in correctness["messages"][1]["content"]
    assert correctness["response_format"] is CorrectnessVerdict
    assert faithfulness["response_format"] is FaithfulnessVerdict
    assert "[1] (" in faithfulness["messages"][1]["content"]


async def test_an_answer_citing_nothing_is_not_judged_for_faithfulness(judge_answers) -> None:
    calls = judge_answers(PASSED)
    result = eval_result(answer="Half of it, uncited.")

    judgement = await judge_case(result.case, result.state)

    assert judgement.correctness == PASSED
    assert judgement.faithfulness is None
    assert len(calls) == 1


async def test_an_answer_citing_only_blocks_it_was_never_given_is_not_judged_for_faithfulness(
    judge_answers,
) -> None:
    """There is no cited context to be faithful to, so a call would grade every claim
    unsupported and double-count what markers_in_context already scores."""
    calls = judge_answers(PASSED)
    result = eval_result(answer="Half of it [7].")

    judgement = await judge_case(result.case, result.state)

    assert judgement.correctness == PASSED
    assert judgement.faithfulness is None
    assert len(calls) == 1


async def test_an_out_of_corpus_answer_is_judged_on_whether_it_declined(judge_answers) -> None:
    calls = judge_answers(DECLINED)
    result = eval_result(out_of_corpus_case(), answer="I can't say from this corpus.")

    judgement = await judge_case(result.case, result.state)

    assert judgement.refusal == DECLINED
    assert judgement.correctness is None
    [call] = calls
    assert call["messages"][1]["content"] == build_refusal_message(
        "q?", "I can't say from this corpus."
    )


async def test_a_gate_refusal_or_an_error_is_judged_by_nothing(judge_answers) -> None:
    """The gate metrics score a refusal and nothing scores an error; a judge call on
    either would grade the fixed refusal text or an empty answer."""
    calls = judge_answers()

    refused = await judge_case(out_of_corpus_case(), refused_result().state)
    errored = eval_result(error="TimeoutError")
    failed = await judge_case(errored.case, errored.state)

    assert not refused.judged
    assert not failed.judged
    assert calls == []


async def test_a_failed_dimension_does_not_stop_the_next(judge_answers) -> None:
    judge_answers('{"critique": "not a verdict"}', GROUNDED)
    result = eval_result()

    judgement = await judge_case(result.case, result.state)

    assert judgement.correctness is None
    assert judgement.faithfulness == GROUNDED


# Judging a run


async def test_a_run_is_judged_case_by_case_a_few_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every result comes back with its verdict in the run's order, and no more cases are
    in the judge at once than the limit allows."""
    in_flight, most_in_flight = 0, 0
    monkeypatch.setattr(config, "EVAL_JUDGE_CONCURRENCY", 2)

    async def fake_judge_case(case, state):
        nonlocal in_flight, most_in_flight
        in_flight += 1
        most_in_flight = max(most_in_flight, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return CaseJudgement(refusal=DECLINED) if case.id == "ooc" else CaseJudgement()

    monkeypatch.setattr(service, "judge_case", fake_judge_case)
    results = [eval_result(eval_case(id=f"case-{n}")) for n in range(3)]
    results.append(eval_result(out_of_corpus_case()))

    judged = await judge_results(results)

    assert [r.case.id for r in judged] == ["case-0", "case-1", "case-2", "ooc"]
    assert [r.judgement for r in judged[:3]] == [CaseJudgement()] * 3
    assert judged[3].judgement == CaseJudgement(refusal=DECLINED)
    assert most_in_flight == 2


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
    assert CorrectnessFailure.OTHER  # the enum the correctness turn names, importable here
