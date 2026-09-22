"""synthesize: the prompt it assembles, the client it streams through, and its retries."""

from collections.abc import AsyncIterator
from typing import Any

import litellm
import pytest

from app.chat.enums import ChatNode
from app.chat.graph.nodes.synthesize import (
    BASELINE_SYSTEM_PROMPT,
    synthesize,
)
from app.chat.graph.service import chat_graph
from app.chat.models import ChatState, ChatStepResult
from app.core.config import config
from app.core.llm.errors import LLMError
from tests.chat.conftest import (
    ANSWER,
    QUESTION,
    THINKING,
    FailingModel,
    fake_chat_model,
    run_graph,
)
from tests.conftest import REPORTED_USAGE, install_chat_model

pytestmark = pytest.mark.anyio


def streamed_text(data: Any) -> str:
    """The text of one messages-mode stream item, a (chunk, metadata) pair."""
    chunk, _ = data
    return chunk.text


def streamed_by(data: Any) -> str:
    """The node whose model call streamed one messages-mode item."""
    _, metadata = data
    return metadata["langgraph_node"]


def finished_steps(data: Any) -> list[ChatStepResult]:
    """The steps of one updates-mode stream item, a node's update under its name."""
    return [step for update in data.values() for step in update["steps"]]


def litellm_stream(
    monkeypatch, *deltas: dict[str, Any], usage: dict[str, int] | None = None
) -> list[dict[str, Any]]:
    """Stand litellm's completion call in with these deltas — and, as litellm reports it
    when asked, a trailing usage-only chunk; the calls made are returned."""
    calls: list[dict[str, Any]] = []

    async def fake_acompletion(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        calls.append(kwargs)

        async def chunks() -> AsyncIterator[dict[str, Any]]:
            for delta in deltas:
                yield {"choices": [{"delta": delta, "finish_reason": None}]}
            if usage:
                yield {"choices": [], "usage": usage}

        return chunks()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    return calls


async def test_a_persistent_provider_failure_becomes_a_transient_llm_error(one_result, monkeypatch):
    model = FailingModel(messages=iter([]), failures=10)
    install_chat_model(monkeypatch, model)

    with pytest.raises(LLMError) as exc_info:
        await run_graph()

    assert exc_info.value.transient is True
    assert str(exc_info.value) == "chat call failed"
    assert len(model.received) == 3


async def test_the_chat_client_streams_each_litellm_delta_and_the_usage_sent_after_them(
    one_result, monkeypatch
):
    """The seam below the fakes: chat_model()'s ChatLiteLLM asks litellm to stream and to
    report usage, which litellm strips from streamed chunks unless asked. Each delta reaches
    the graph's message stream as it lands, and the usage-only chunk sent last becomes
    synthesize's tokens."""
    calls = litellm_stream(
        monkeypatch,
        {"role": "assistant", "content": "Ships must "},
        {"content": "comply [1]."},
        usage={"prompt_tokens": 1500, "completion_tokens": 40, "total_tokens": 1540},
    )
    texts: list[str] = []
    steps: list[ChatStepResult] = []

    async for mode, data in chat_graph.astream(
        ChatState(question=QUESTION), stream_mode=["updates", "messages"]
    ):
        if mode == "updates":
            steps += finished_steps(data)
        elif streamed_by(data) == ChatNode.SYNTHESIZE:
            texts.append(streamed_text(data))

    assert calls[0]["stream"] is True
    assert calls[0]["stream_options"] == {"include_usage": True}
    assert calls[0]["model"] == config.CHAT_MODEL
    assert [text for text in texts if text] == ["Ships must ", "comply [1]."]
    [_rewrite, _retrieve, synthesized] = steps
    assert synthesized.usage == REPORTED_USAGE


async def test_the_chat_client_answers_with_the_text_of_a_reasoning_response(
    one_result, monkeypatch
):
    """litellm's reasoning_content becomes a thinking block ahead of the text; the answer
    is the text alone, not the repr of the block list."""
    litellm_stream(
        monkeypatch,
        {"role": "assistant", "content": "", "reasoning_content": THINKING},
        {"content": ANSWER},
    )

    state = await run_graph()

    assert state.answer == ANSWER


@pytest.mark.parametrize(
    ("enabled", "max_tokens", "temperature"),
    [
        pytest.param(
            True, 3072, 1.0, id="on, the budget sits on top of the answer cap at temperature 1"
        ),
        pytest.param(False, 2048, 0.0, id="off, the answer cap and the set temperature stand"),
    ],
)
async def test_the_answer_call_thinks_only_when_switched_on(
    one_result, monkeypatch, enabled, max_tokens, temperature
):
    """The provider rejects thinking at any temperature but 1, and counts the reasoning
    against max_tokens, so the answer keeps its own cap."""
    monkeypatch.setattr(config, "CHAT_THINKING_ENABLED", enabled)
    monkeypatch.setattr(config, "CHAT_MAX_TOKENS", 2048)
    monkeypatch.setattr(config, "CHAT_THINKING_BUDGET", 1024)
    monkeypatch.setattr(config, "CHAT_TEMPERATURE", 0.0)
    calls = litellm_stream(monkeypatch, {"role": "assistant", "content": ANSWER})

    await run_graph()

    assert calls[0].get("thinking") == (
        {"type": "enabled", "budget_tokens": 1024} if enabled else None
    )
    assert (calls[0]["max_tokens"], calls[0]["temperature"]) == (max_tokens, temperature)


async def test_no_sources_answers_from_memory_under_the_baseline_prompt(monkeypatch):
    model = fake_chat_model()
    install_chat_model(monkeypatch, model)

    update = await synthesize(ChatState(question=QUESTION))

    (prompt,) = model.received
    assert prompt[0].content == BASELINE_SYSTEM_PROMPT
    assert prompt[1].content == QUESTION
    assert update["answer"] == ANSWER
