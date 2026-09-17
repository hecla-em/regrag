"""Chat test fakes shared across the chat test modules."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import datetime
from typing import Any

import openai
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from pydantic import Field
from redis.asyncio import Redis

from app.chat.cache import normalize_question, pending_stores
from app.chat.events import ChatEvent
from app.chat.graph.service import chat_graph
from app.chat.models import ChatQuery, ChatState
from app.chat.stream import stream_chat_events
from app.chat.toolbox.models import ToolCall
from app.core.config import config
from app.core.redis import redis_client
from app.retrieval.models import RetrievedChunk, SearchRequest, SearchResult
from tests.conftest import (
    REPLY_METADATA,
    USAGE,
    install_chat_model,
    install_search,
    junk_result,
    no_session,
    provider_error,
    search_result,
)


class RecordingChatModel(GenericFakeChatModel):
    """Streams a canned answer with real message chunks, recording each prompt once:
    the fake's _stream is built on its _generate, so that is the one place to record."""

    received: list[list[BaseMessage]] = Field(default_factory=list)
    usage: UsageMetadata | None = None
    """Reported as litellm does: on the message when invoked outright, and as a final
    usage-only chunk after the answer's text when streamed. The model litellm's wrapper
    stamps on the reply rides along with it."""

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self.received.append(list(messages))
        result = super()._generate(messages, *args, **kwargs)
        message = result.generations[0].message
        if self.usage and isinstance(message, AIMessage):
            message.usage_metadata = self.usage
            message.response_metadata = REPLY_METADATA
        return result

    def _stream(
        self, messages: list[BaseMessage], *args: Any, **kwargs: Any
    ) -> Iterator[ChatGenerationChunk]:
        yield from super()._stream(messages, *args, **kwargs)
        if self.usage:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="", usage_metadata=self.usage, response_metadata=REPLY_METADATA
                )
            )


def fake_chat_model(answer: str = "Ships must comply [1].") -> RecordingChatModel:
    """A chat model that streams one canned answer and reports USAGE for it."""
    return RecordingChatModel(messages=iter([AIMessage(content=answer)]), usage=USAGE)


def tool_call_message(name: str, args: dict) -> AIMessage:
    """An assess turn asking for one tool, shaped as litellm parses provider tool calls."""
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": "call_1", "type": "tool_call"}]
    )


THINKING = "weighing the context"
ANSWER = "Ships must comply [1]."


class ReasoningChatModel(GenericFakeChatModel):
    """Streams block-list content, as litellm returns it once the model reasons."""

    def _stream(
        self, messages: list[BaseMessage], *args: Any, **kwargs: Any
    ) -> Iterator[ChatGenerationChunk]:
        for block in (
            {"type": "thinking", "thinking": THINKING},
            {"type": "text", "text": ANSWER},
        ):
            yield ChatGenerationChunk(message=AIMessageChunk(content=[block]))


def reasoning_chat_model() -> ReasoningChatModel:
    """A chat model whose chunks carry content blocks rather than strings."""
    return ReasoningChatModel(messages=iter([AIMessage(content="unused")]))


def recording_search(monkeypatch: pytest.MonkeyPatch, *hits: SearchResult) -> list[SearchRequest]:
    """Install a search answering every query with the same hits, and hand back the list
    the requests it receives accumulate in."""
    requests: list[SearchRequest] = []

    async def fake_search(session, request):
        requests.append(request)
        return hits

    install_search(monkeypatch, fake_search)
    return requests


@pytest.fixture
def one_result(monkeypatch: pytest.MonkeyPatch) -> list[SearchRequest]:
    """Search finds one chunk; the returned list collects what it was asked for."""
    return recording_search(monkeypatch, search_result())


@pytest.fixture
def two_results(monkeypatch: pytest.MonkeyPatch) -> list[SearchRequest]:
    """Search finds two chunks; the returned list collects what it was asked for."""
    return recording_search(
        monkeypatch, search_result(), search_result(id=2, citation="Article 5(1)")
    )


@pytest.fixture
def one_junk_result(monkeypatch: pytest.MonkeyPatch) -> list[SearchRequest]:
    """Search finds one chunk below the bar, so nothing clears the gate; the returned list
    collects what it was asked for."""
    return recording_search(monkeypatch, junk_result())


@pytest.fixture(autouse=True)
def no_section_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expansion is a database walk covered in tests/retrieval; here it is switched off,
    so the graph works from exactly what the faked search found."""
    monkeypatch.setattr(config, "EXPAND_SECTIONS", False)


@pytest.fixture(autouse=True)
def no_assess_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loop is off by default so every pre-loop test keeps meaning exactly what it
    said; a loop test takes `loop_on` and fakes assess_model itself."""
    monkeypatch.setattr(config, "ASSESS_ENABLED", False)


@pytest.fixture
def loop_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loop back on, with its default two rounds, undoing the autouse switch-off."""
    monkeypatch.setattr(config, "ASSESS_ENABLED", True)
    monkeypatch.setattr(config, "ASSESS_MAX_ROUNDS", 2)


@pytest.fixture(autouse=True)
def no_decompose(monkeypatch: pytest.MonkeyPatch) -> None:
    """The split is off by default so every test that runs the graph keeps meaning exactly
    what it said; a decompose test takes `decompose_on` and fakes decompose_model itself."""
    monkeypatch.setattr(config, "DECOMPOSE_ENABLED", False)


@pytest.fixture
def decompose_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The split back on, undoing the autouse switch-off."""
    monkeypatch.setattr(config, "DECOMPOSE_ENABLED", True)


@pytest.fixture
def assess_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., RecordingChatModel]:
    """Install an assess model answering with the given turns in order, and hand back the
    fake, whose `received` holds the prompts it saw."""

    def install(*turns: AIMessage) -> RecordingChatModel:
        model = RecordingChatModel(messages=iter(turns), usage=USAGE)
        monkeypatch.setattr("app.chat.graph.nodes.assess.assess_model", lambda: model)
        return model

    return install


@pytest.fixture
def decompose_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., RecordingChatModel]:
    """Install a decompose model answering with the given turns in order, and hand back
    the fake, whose `received` holds the prompts it saw."""

    def install(*turns: AIMessage) -> RecordingChatModel:
        model = RecordingChatModel(messages=iter(turns), usage=USAGE)
        monkeypatch.setattr("app.chat.graph.nodes.decompose.decompose_model", lambda: model)
        return model

    return install


def split_message(*queries: str) -> AIMessage:
    """A decompose turn, shaped as a model bound to the DecomposedQuestion format answers."""
    return AIMessage(content=json.dumps({"queries": list(queries)}))


@pytest.fixture
def rewrite_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., RecordingChatModel]:
    """Install a rewrite model answering with the given turns in order, and hand back
    the fake, whose `received` holds the prompts it saw."""

    def install(*turns: AIMessage) -> RecordingChatModel:
        model = RecordingChatModel(messages=iter(turns), usage=USAGE)
        monkeypatch.setattr("app.chat.graph.nodes.rewrite.rewrite_model", lambda: model)
        return model

    return install


def restated_message(question: str) -> AIMessage:
    """A rewrite turn, shaped as a model bound to the StandaloneQuestion format answers."""
    return AIMessage(content=json.dumps({"question": question}))


@pytest.fixture
def tool_results(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[ToolCall]]:
    """Install a run_tool_call answering every call with the given chunks, and hand back
    the list the calls it received accumulate in."""

    def install(*found: RetrievedChunk) -> list[ToolCall]:
        calls: list[ToolCall] = []

        async def fake_run_tool_call(call):
            calls.append(call)
            return found

        monkeypatch.setattr("app.chat.graph.nodes.assess.run_tool_call", fake_run_tool_call)
        return calls

    return install


@pytest.fixture(autouse=True)
def no_tool_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tool call opens its own session; the faked tool paths never touch it, so a null
    one stands in and no chat test reaches the database."""

    monkeypatch.setattr("app.chat.toolbox.service.get_session", no_session)


@pytest.fixture(autouse=True)
def recorded_requests(monkeypatch: pytest.MonkeyPatch) -> list[ChatState]:
    """Capture the state record_run hands to create_chat_request, and give it no session
    to hand over: the write is covered in test_service, so no streaming test needs the
    database."""
    states: list[ChatState] = []

    async def fake_create_chat_request(session: None, state: ChatState) -> None:
        states.append(state)

    async def nothing_spent(session: None, since: datetime) -> float:
        return 0.0

    monkeypatch.setattr("app.chat.stream.get_session", no_session)
    monkeypatch.setattr("app.chat.stream.create_chat_request", fake_create_chat_request)
    monkeypatch.setattr("app.chat.stream.spent_since", nothing_spent)
    return states


QUESTION = "What is the GHG intensity limit?"


class FailingModel(RecordingChatModel):
    """Refuses the first `failures` prompts as a rate limit, then answers."""

    failures: int = 1

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        if len(self.received) < self.failures:
            self.received.append(list(messages))
            raise provider_error(openai.RateLimitError, 429)
        return super()._generate(messages, *args, **kwargs)


@pytest.fixture
def answer_model(monkeypatch):
    model = fake_chat_model("Answered [1].")
    install_chat_model(monkeypatch, model)
    return model


async def run_graph(state: ChatState | None = None) -> ChatState:
    """The graph run, folded back onto the state it started from; the plain question when
    the caller has no state of its own to run."""
    state = state or ChatState(question=QUESTION)
    state.sync_from_snapshot(await chat_graph.ainvoke(state))
    return state


def hits_for(monkeypatch: pytest.MonkeyPatch, **per_query: tuple) -> list[SearchRequest]:
    """Install a search answering each query with its own hits, and hand back the list the
    requests it receives accumulate in."""
    requests: list[SearchRequest] = []

    async def fake_search(session, request):
        requests.append(request)
        return per_query[request.query]

    install_search(monkeypatch, fake_search)
    return requests


async def settle_stores() -> None:
    """Wait out the answer stores a finished stream left in flight."""
    await asyncio.gather(*pending_stores)


async def collect_events(query: ChatQuery) -> list[ChatEvent]:
    """Every event one question's stream sends, run to the end, its answer store landed."""
    events = [event async for event in stream_chat_events(query)]
    await settle_stores()
    return events


FUELEU_KEY = "chat:answer:v1:what is fueleu"
"""Where install_versioned_key files "What is FuelEU?"."""


def install_versioned_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the cache on under a fixed key prefix, so no test needs a database for its keys."""
    monkeypatch.setattr(config, "CHAT_CACHE_ENABLED", True)

    async def versioned_key(session: None, question: str) -> str:
        return f"chat:answer:v1:{normalize_question(question)}"

    monkeypatch.setattr("app.chat.cache.get_session", no_session)
    monkeypatch.setattr("app.chat.cache.answer_key", versioned_key)


@pytest.fixture
async def answer_cache() -> AsyncIterator[Redis]:
    """An emptied Redis index opened on the test's own loop, which the app's shared client,
    bound to the TestClient's loop, cannot serve."""
    redis = Redis.from_url(
        config.REDIS_URL,
        socket_connect_timeout=config.REDIS_TIMEOUT,
        socket_timeout=config.REDIS_TIMEOUT,
    )
    await redis.flushdb()
    yield redis
    await redis.aclose()


@pytest.fixture
def cached_client(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The answer cache on, in the suite's Redis index, emptied first."""
    assert client.portal is not None
    client.portal.call(redis_client.flushdb)
    install_versioned_key(monkeypatch)
    return client
