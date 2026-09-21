"""synthesize: the prompt it assembles, the client it streams through, and its retries."""

from collections.abc import AsyncIterator
from typing import Any

import litellm
import pytest
from langchain_core.messages import SystemMessage

from app.chat.graph.nodes.synthesize import (
    BASELINE_SYSTEM_PROMPT,
    synthesize,
)
from app.chat.graph.service import chat_graph
from app.chat.models import ChatState
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
from tests.conftest import (
    REPORTED_USAGE,
    install_chat_model,
    install_search,
    search_result,
)

pytestmark = pytest.mark.anyio


def streamed_text(data: Any) -> str:
    """The text of one messages-mode stream item, a (chunk, metadata) pair."""
    chunk, _ = data
    return chunk.text


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


async def test_model_receives_system_prompt_and_numbered_context(monkeypatch):
    async def fake_search(session, request):
        return (search_result(text="A very specific clause."),)

    model = fake_chat_model()
    install_search(monkeypatch, fake_search)
    install_chat_model(monkeypatch, model)

    await run_graph()

    (prompt,) = model.received
    assert isinstance(prompt[0], SystemMessage)
    assert "[1] (Regulation (EU) 2023/1805, Article 4(1))" in prompt[1].content
    assert "A very specific clause." in prompt[1].content


async def test_a_persistent_provider_failure_becomes_a_transient_llm_error(one_result, monkeypatch):
    model = FailingModel(messages=iter([]), failures=10)
    install_chat_model(monkeypatch, model)

    with pytest.raises(LLMError) as exc_info:
        await run_graph()

    assert exc_info.value.transient is True
    assert str(exc_info.value) == "chat call failed"
    assert len(model.received) == 3


async def test_the_chat_client_streams_one_token_per_litellm_delta(one_result, monkeypatch):
    """The seam below the fakes: chat_model()'s ChatLiteLLM asks litellm to stream, and
    the graph's message stream sees each delta as it lands."""
    calls = litellm_stream(
        monkeypatch, {"role": "assistant", "content": "Ships must "}, {"content": "comply [1]."}
    )

    texts = [
        streamed_text(data)
        async for mode, data in chat_graph.astream(
            ChatState(question=QUESTION), stream_mode=["updates", "messages"]
        )
        if mode == "messages"
    ]

    assert calls[0]["stream"] is True
    assert calls[0]["model"] == config.CHAT_MODEL
    assert [text for text in texts if text] == ["Ships must ", "comply [1]."]


async def test_the_chat_client_asks_litellm_for_usage_and_the_node_records_it(
    one_result, monkeypatch
):
    """litellm strips usage from streamed chunks unless asked for it in stream_options;
    asked, it sends one usage-only chunk last, which becomes synthesize's tokens."""
    calls = litellm_stream(
        monkeypatch,
        {"role": "assistant", "content": "Ships must comply [1]."},
        usage={"prompt_tokens": 1500, "completion_tokens": 40, "total_tokens": 1540},
    )

    state = await run_graph()

    assert calls[0]["stream_options"] == {"include_usage": True}
    [_retrieve, synthesize] = state.steps
    assert synthesize.usage == REPORTED_USAGE


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


@pytest.mark.parametrize("enabled", [True, False])
async def test_the_answer_call_thinks_only_when_switched_on(one_result, monkeypatch, enabled):
    monkeypatch.setattr(config, "CHAT_THINKING_ENABLED", enabled)
    calls = litellm_stream(monkeypatch, {"role": "assistant", "content": ANSWER})

    await run_graph()

    assert ("thinking" in calls[0]) is enabled


async def test_no_sources_answers_from_memory_under_the_baseline_prompt(monkeypatch):
    model = fake_chat_model()
    install_chat_model(monkeypatch, model)

    update = await synthesize(ChatState(question=QUESTION))

    (prompt,) = model.received
    assert prompt[0].content == BASELINE_SYSTEM_PROMPT
    assert prompt[1].content == QUESTION
    assert update["answer"] == ANSWER
