"""The real app on :8000 over the seeded fixture corpus with the model faked, for the
Playwright suite in frontend/e2e. Run as `uv run python -m tests.e2e.server`."""

import asyncio
import json
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
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.chat.schemas import ChatRequest
from app.core.config import config
from app.core.db.session import async_session_factory
from app.ingestion.parse.html.document import parse_eurlex_html
from app.ingestion.parse.models import ParsedDocument
from app.main import app
from tests.conftest import (
    FUELEU_HTML,
    MRV_HTML,
    ON_TOPIC_COSINE,
    install_chat_model,
    migrate_to_head,
    store_corpus,
    toy_query_embed,
)

PORT = 8000
ANSWER = "The limit falls over time [1]."
LONG_ANSWER_CUE = "at length"
"""A question holding this is answered slowly enough to be stopped mid-stream."""
LONG_ANSWER = " ".join(["The limit tightens every five years [1]."] * 60)
TOKEN_DELAY = 0.03
LONG_TOKEN_DELAY = 0.05
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
        reply = reply_to(messages, kwargs)
        delay = LONG_TOKEN_DELAY if reply == LONG_ANSWER else TOKEN_DELAY
        for token in re.split(r"(\s)", reply):
            await asyncio.sleep(delay)
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=token))
            if run_manager:
                await run_manager.on_llm_new_token(token, chunk=chunk)
            yield chunk


def reply_to(messages: list[BaseMessage], kwargs: dict[str, Any]) -> str:
    """A call bound to a response format is the rewrite; any other is the answer."""
    if "response_format" in kwargs:
        return json.dumps({"question": RESTATED})
    return LONG_ANSWER if LONG_ANSWER_CUE in messages[-1].text else ANSWER


async def seed() -> None:
    """The fixture acts stored and embedded, and the ledger and Redis index emptied."""
    engine = create_async_engine(config.SQLALCHEMY_DATABASE_URI, poolclass=NullPool)
    fueleu = ParsedDocument(
        celex="32023R1805", topic="fueleu", sections=parse_eurlex_html(FUELEU_HTML)
    )
    mrv = ParsedDocument(celex="32015R0757", topic="mrv", sections=parse_eurlex_html(MRV_HTML))
    await store_corpus(engine, fueleu, mrv)
    async with async_session_factory(bind=engine) as session:
        await session.execute(delete(ChatRequest))
        await session.commit()
    await engine.dispose()
    redis = Redis.from_url(config.REDIS_URL)
    await redis.flushdb()
    await redis.aclose()


def install_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model and query embeddings faked, rerank and the loop off, and the limiter on
    with a per-client allowance of two: every scenario but the rate-limit one stays under it."""
    install_chat_model(monkeypatch, ScriptedChatModel())
    monkeypatch.setattr("app.retrieval.search.embed", toy_query_embed)
    monkeypatch.setattr(config, "MIN_COSINE_SIMILARITY", ON_TOPIC_COSINE)
    monkeypatch.setattr(config, "RERANK_ENABLED", False)
    monkeypatch.setattr(config, "ASSESS_ENABLED", False)
    monkeypatch.setattr(config, "DECOMPOSE_ENABLED", False)
    monkeypatch.setattr(config, "CHAT_CACHE_ENABLED", False)
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(config, "RATE_LIMIT_PER_CLIENT", 2)
    monkeypatch.setattr(config, "RATE_LIMIT_PER_IP", 1000)


def main() -> None:
    assert config.DB_NAME == "regrag_e2e", "the launcher deletes rows, so never on a dev database"
    migrate_to_head()
    anyio.run(seed)
    install_fakes(pytest.MonkeyPatch())
    uvicorn.run(app, host="127.0.0.1", port=PORT, access_log=False)


if __name__ == "__main__":
    main()
