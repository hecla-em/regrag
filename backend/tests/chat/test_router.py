"""POST /chat over the stored corpus, the real ledger and the real Redis. Only the model is
faked, so what is asserted here is what a visitor's question does end to end."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.chat.enums import ChatOutcome
from app.chat.graph.nodes.refuse import REFUSAL_ANSWER
from app.chat.schemas import ChatRequest
from app.core.config import config
from app.core.db.session import get_session
from app.core.redis import redis_client
from app.ingestion.chunk.schemas import DocumentChunk
from tests.chat.conftest import (
    RecordingChatModel,
    fake_chat_model,
    first_payload,
    read_events,
    restated_message,
    settle_stores,
)
from tests.conftest import USAGE, install_chat_model

ON_TOPIC = "What is the greenhouse gas intensity limit for energy used on board a ship?"
OFF_TOPIC = "How do I bake sourdough bread at home?"
ANSWER = "The limit falls over time [1]."


def ask(client: TestClient, question: str, thread_id: str | None = None) -> list[tuple[str, Any]]:
    """One question's frames, read to the end, with any answer store it left landed."""
    body = {"question": question} | ({"thread_id": thread_id} if thread_id else {})
    with client.stream("POST", "/chat", json=body) as response:
        assert response.status_code == 200
        events = read_events(response)
    assert client.portal is not None
    client.portal.call(settle_stores)
    return events


def answer_of(events: list[tuple[str, Any]]) -> str:
    return "".join(payload for name, payload in events if name == "text")


def ledger(client: TestClient) -> list[ChatRequest]:
    """Every recorded request with its steps, oldest first, read on the app's own loop."""

    async def read() -> list[ChatRequest]:
        stmt = select(ChatRequest).options(selectinload(ChatRequest.steps)).order_by(ChatRequest.id)
        async with get_session(auto_commit=False) as session:
            return list(await session.scalars(stmt))

    assert client.portal is not None
    return client.portal.call(read)


def step_names(request: ChatRequest) -> list[str]:
    return [step.step for step in sorted(request.steps, key=lambda step: step.position)]


def answering(monkeypatch: pytest.MonkeyPatch, answer: str = ANSWER) -> RecordingChatModel:
    """A fresh answer model for the next question, since a fake holds one reply."""
    model = fake_chat_model(answer)
    install_chat_model(monkeypatch, model)
    return model


def test_a_first_question_is_answered_from_the_corpus_and_recorded(
    seeded_client: TestClient, corpus: list[DocumentChunk], monkeypatch: pytest.MonkeyPatch
):
    model = answering(monkeypatch)

    events = ask(seeded_client, ON_TOPIC)

    names = [name for name, _ in events]
    assert (names[0], names[-1]) == ("step", "done")
    assert names.index("sources") < names.index("text")
    assert answer_of(events) == ANSWER

    sources = first_payload(events, "sources")
    stored = {chunk.id: chunk for chunk in corpus}
    assert [source["marker"] for source in sources] == list(range(1, len(sources) + 1))
    assert all(stored[source["chunk_id"]].text == source["text"] for source in sources)
    assert sources[0]["act"].startswith("Regulation (EU) 2023/1805")
    [prompt] = model.received
    assert sources[0]["text"] in str(prompt[-1].content)

    [request] = ledger(seeded_client)
    assert request.outcome is ChatOutcome.DONE
    assert (request.question, request.answer) == (ON_TOPIC, ANSWER)
    assert request.sources == len(sources)
    assert (request.input_tokens, request.output_tokens) == (
        USAGE["input_tokens"],
        USAGE["output_tokens"],
    )
    assert request.cost_usd is not None and request.cost_usd > 0
    assert step_names(request) == ["retrieve", "synthesize"]
    assert str(request.thread_id) == first_payload(events, "done")["thread_id"]


def test_a_follow_up_reads_its_thread_from_the_ledger_until_the_thread_is_full(
    seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch, rewrite_turns
):
    answering(monkeypatch)
    thread_id = first_payload(ask(seeded_client, ON_TOPIC), "done")["thread_id"]

    rewrite = rewrite_turns(restated_message(ON_TOPIC))
    answering(monkeypatch, "It tightens in 2030 [1].")
    follow_up = ask(seeded_client, "And from 2030?", thread_id)

    assert first_payload(follow_up, "done")["thread_id"] == thread_id
    [restating] = rewrite.received
    thread_in_view = " ".join(str(message.content) for message in restating)
    assert ON_TOPIC in thread_in_view
    assert "The limit falls over time" in thread_in_view
    assert "[1]" not in thread_in_view
    first, second = ledger(seeded_client)
    assert first.thread_id == second.thread_id
    assert step_names(second) == ["rewrite", "retrieve", "synthesize"]

    monkeypatch.setattr(config, "CHAT_THREAD_TURNS", 2)
    unasked = answering(monkeypatch)
    refused = ask(seeded_client, "And from 2035?", thread_id)

    assert first_payload(refused, "error")["error"] == "ThreadFullError"
    assert unasked.received == []
    assert ledger(seeded_client)[-1].outcome is ChatOutcome.ERROR


def test_a_question_the_corpus_does_not_cover_is_refused_before_any_model_call(
    seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "CHAT_CACHE_ENABLED", True)
    model = answering(monkeypatch)

    events = ask(seeded_client, OFF_TOPIC)

    assert first_payload(events, "sources") == []
    assert answer_of(events) == REFUSAL_ANSWER
    assert [name for name, _ in events][-1] == "done"
    assert model.received == []
    [request] = ledger(seeded_client)
    assert request.outcome is ChatOutcome.REFUSED
    assert seeded_client.portal is not None
    assert seeded_client.portal.call(redis_client.dbsize) == 0


def test_a_tool_round_fetches_from_the_corpus_and_grows_the_context(
    seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch, loop_on, assess_turns
):
    answering(monkeypatch)
    assess_turns(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "follow_reference",
                    "args": {"celex": "32015R0757", "article": "11a"},
                    "id": "c1",
                    "type": "tool_call",
                },
                {
                    "name": "search",
                    "args": {"query": "port of call", "celex": "32015R0757"},
                    "id": "c2",
                    "type": "tool_call",
                },
            ],
        ),
        AIMessage(content=""),
    )

    events = ask(seeded_client, ON_TOPIC)

    finished = [
        (step["step"], step["subject"])
        for name, step in events
        if name == "step" and step["status"] == "completed" and step["subject"]
    ]
    assert finished == [
        ("tool_follow_reference", "32015R0757 · 11a"),
        ("tool_search", "port of call · 32015R0757"),
    ]
    [sources] = [payload for name, payload in events if name == "sources"]
    followed = [source for source in sources if source["citation"].startswith("Article 11a")]
    assert len(followed) == 4
    assert {source["celex"] for source in followed} == {"32015R0757"}
    [request] = ledger(seeded_client)
    assert request.sources == len(sources)
    assert step_names(request) == [
        "retrieve",
        "assess",
        "tool_follow_reference",
        "tool_search",
        "assess",
        "synthesize",
    ]


def test_a_repeated_question_is_served_from_the_cache_and_recorded_as_cached(
    seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "CHAT_CACHE_ENABLED", True)
    model = answering(monkeypatch)

    asked = ask(seeded_client, ON_TOPIC)
    repeated = ask(seeded_client, f"  {ON_TOPIC.upper()}  ")

    assert answer_of(repeated) == answer_of(asked) == ANSWER
    assert first_payload(repeated, "sources") == first_payload(asked, "sources")
    assert len(model.received) == 1
    first, second = ledger(seeded_client)
    assert second.outcome is ChatOutcome.CACHED
    assert step_names(second) == []
    assert str(second.thread_id) == first_payload(repeated, "done")["thread_id"]
    assert second.thread_id != first.thread_id


def test_the_spend_cap_is_read_off_the_ledger_and_spares_a_cached_answer(
    seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "CHAT_CACHE_ENABLED", True)
    answering(monkeypatch)
    ask(seeded_client, ON_TOPIC)

    async def spend_the_cap() -> None:
        async with get_session() as session:
            session.add(
                ChatRequest(
                    question="an expensive day",
                    outcome=ChatOutcome.DONE,
                    total_ms=1,
                    sources=0,
                    cost_usd=config.CHAT_DAILY_SPEND_CAP_USD,
                )
            )

    assert seeded_client.portal is not None
    seeded_client.portal.call(spend_the_cap)
    unasked = answering(monkeypatch)

    paused = ask(seeded_client, "Which ships must submit a monitoring plan?")
    cached = ask(seeded_client, ON_TOPIC)

    assert first_payload(paused, "error")["error"] == "SpendCapReachedError"
    assert unasked.received == []
    assert answer_of(cached) == ANSWER
    assert [request.outcome for request in ledger(seeded_client)[-2:]] == [
        ChatOutcome.ERROR,
        ChatOutcome.CACHED,
    ]
