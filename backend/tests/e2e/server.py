"""The real app on :8000 over the seeded fixture corpus with the model faked, for the
Playwright suite in frontend/e2e. Run as `uv run python -m tests.e2e.server`."""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

import anyio
import pytest
import uvicorn
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from redis.asyncio import Redis

from app.core.config import config
from app.core.db.session import async_engine
from app.main import app
from tests.chat.conftest import restated_message
from tests.conftest import (
    ON_TOPIC_COSINE,
    clear_ledger,
    install_chat_model,
    migrate_to_head,
    parse_fixture,
    store_corpus,
    toy_query_embed,
)

ANSWER = "The limit falls over time [1]."
LONG_ANSWER_CUE = "at length"
"""A question holding this is answered slowly enough to be stopped mid-stream."""
LONG_ANSWER = " ".join(["The limit tightens every five years [1]."] * 60)
TOKEN_DELAY = 0.03
RESTATED = "What is the greenhouse gas intensity limit for energy used on board a ship?"
"""What every follow-up is restated as, on topic so it clears the refusal gate."""


class ScriptedChatModel(BaseChatModel):
    """Answers each call from what it was asked rather than from a queue, so concurrent
    visitors share one fake: a rewrite gets its JSON shape, an answer streams word by word."""

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        reply = AIMessage(content=reply_to(messages, kwargs))
        return ChatResult(generations=[ChatGeneration(message=reply)])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for token in re.findall(r"\S+\s*", reply_to(messages, kwargs)):
            await asyncio.sleep(TOKEN_DELAY)
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=token))
            if run_manager:
                await run_manager.on_llm_new_token(token, chunk=chunk)
            yield chunk


def reply_to(messages: list[BaseMessage], kwargs: dict[str, Any]) -> str:
    """A call bound to a response format is the rewrite; any other is the answer."""
    if "response_format" in kwargs:
        return restated_message(RESTATED).text
    return LONG_ANSWER if LONG_ANSWER_CUE in messages[-1].text else ANSWER


async def seed() -> None:
    """The fixture acts stored and embedded, and the ledger and Redis index emptied. The
    engine is disposed after, so no pooled connection outlives this loop."""
    fueleu = parse_fixture("32023R1805", "fueleu")
    mrv = parse_fixture("32015R0757", "mrv")
    await store_corpus(async_engine, fueleu, mrv)
    await clear_ledger()
    await async_engine.dispose()
    redis = Redis.from_url(config.REDIS_URL)
    await redis.flushdb()
    await redis.aclose()


def install_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model and query embeddings faked, and rerank and the loop off. The limiter and
    the answer cache are already off, by the tests package."""
    install_chat_model(monkeypatch, ScriptedChatModel())
    monkeypatch.setattr("app.retrieval.search.embed", toy_query_embed)
    monkeypatch.setattr(config, "MIN_COSINE_SIMILARITY", ON_TOPIC_COSINE)
    monkeypatch.setattr(config, "RERANK_ENABLED", False)
    monkeypatch.setattr(config, "ASSESS_ENABLED", False)


def main() -> None:
    assert config.DB_NAME == "regrag_e2e", "the launcher deletes rows, so never on a dev database"
    migrate_to_head()
    anyio.run(seed)
    install_fakes(pytest.MonkeyPatch())
    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)


if __name__ == "__main__":
    main()
