"""POST /chat over the stored corpus, the real ledger and the real Redis. Only the model is
faked, so what is asserted here is what a visitor's question does end to end."""

import json
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
from app.core.llm.errors import LLMError
from app.core.redis import redis_client
from app.ingestion.chunk.schemas import DocumentChunk
from tests.chat.conftest import ANSWER as REASONED_ANSWER
from tests.chat.conftest import (
    THINKING,
    RecordingChatModel,
    fake_chat_model,
    first_payload,
    read_events,
    reasoning_chat_model,
    restated_message,
    search_giving,
    settle_stores,
    tool_calls_message,
)
from tests.conftest import USAGE, RecordingTransport, install_chat_model

ON_TOPIC = "What is the greenhouse gas intensity limit for energy used on board a ship?"
OFF_TOPIC = "How do I bake sourdough bread at home?"
ANSWER = "The limit falls over time [1]."
DEFINITION_QUERY = "What is the definition of port of call under the monitoring regulation?"
"""A search that clears the bar inside the MRV act, and ranks FuelEU first without the filter."""
PERSONAL_QUESTION = "I am Jane Example, does FuelEU apply to me?"
"""Up here, away from the test that asks it: Sentry sends the source lines around a frame."""


def ask(
    client: TestClient, question: str, thread_id: str | None = None, client_id: str | None = None
) -> list[tuple[str, Any]]:
    """One question's frames, read to the end, with any answer store it left landed."""
    body = {"question": question} | ({"thread_id": thread_id} if thread_id else {})
    headers = {"X-Client-ID": client_id} if client_id else {}
    with client.stream("POST", "/chat", json=body, headers=headers) as response:
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


def answer_ttls(client: TestClient) -> list[int]:
    """How long each kept answer has left, read on the app's own loop."""

    async def read() -> list[int]:
        keys = redis_client.scan_iter("chat:answer:*")
        return [await redis_client.ttl(key) async for key in keys]

    assert client.portal is not None
    return client.portal.call(read)


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
    assert step_names(request) == ["rewrite", "retrieve", "synthesize"]
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

    assert [name for name, _ in refused] == ["error"]
    assert first_payload(refused, "error")["error"] == "ThreadFullError"
    assert unasked.received == []
    third = ledger(seeded_client)[-1]
    assert (third.outcome, step_names(third)) == (ChatOutcome.ERROR, [])
    assert third.thread_id == first.thread_id


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
    monkeypatch.setattr(config, "ASSESS_SEARCH_LIMIT", 2)
    answering(monkeypatch)
    assess_turns(
        tool_calls_message(
            ("follow_reference", {"celex": "32015R0757", "article": "11a"}),
            ("search", {"query": DEFINITION_QUERY, "celex": "32015R0757"}),
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
        ("tool_search", f"{DEFINITION_QUERY} · 32015R0757"),
    ]
    [sources] = [payload for name, payload in events if name == "sources"]
    followed = [source for source in sources if source["citation"].startswith("Article 11a")]
    assert len(followed) == 4
    assert {source["celex"] for source in followed} == {"32015R0757"}
    searched = sources[sources.index(followed[-1]) + 1 :]
    assert 0 < len(searched) <= config.ASSESS_SEARCH_LIMIT
    assert {source["celex"] for source in searched} == {"32015R0757"}
    [request] = ledger(seeded_client)
    assert request.sources == len(sources)
    assert step_names(request) == [
        "rewrite",
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
    [ttl] = answer_ttls(seeded_client)
    assert ttl == pytest.approx(config.CHAT_CACHE_TTL_SECONDS, abs=60)


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

    assert [name for name, _ in paused] == ["error"]
    assert first_payload(paused, "error")["error"] == "SpendCapReachedError"
    assert unasked.received == []
    assert answer_of(cached) == ANSWER
    assert [(request.outcome, step_names(request)) for request in ledger(seeded_client)[-2:]] == [
        (ChatOutcome.ERROR, []),
        (ChatOutcome.CACHED, []),
    ]


def test_a_reasoning_models_thinking_never_reaches_the_wire_or_the_ledger(
    seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    install_chat_model(monkeypatch, reasoning_chat_model())

    events = ask(seeded_client, ON_TOPIC)

    assert answer_of(events) == REASONED_ANSWER
    assert THINKING not in json.dumps(events)
    [request] = ledger(seeded_client)
    assert request.answer == REASONED_ANSWER


def test_a_question_over_the_limit_is_refused_before_the_graph_runs(
    seeded_client: TestClient, rate_limited_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_CLIENT", 1)
    model = answering(monkeypatch)
    ask(seeded_client, ON_TOPIC, client_id="reader")

    second = seeded_client.post(
        "/chat", json={"question": ON_TOPIC}, headers={"X-Client-ID": "reader"}
    )

    assert second.status_code == 429
    assert second.json()["error"] == "RateLimitedError"
    assert len(model.received) == 1
    assert len(ledger(seeded_client)) == 1


def provider_failure() -> LLMError:
    """An LLMError as the embed wrapper raises one: caused by a provider error whose text
    quotes the request it was sent."""
    error = LLMError("embedding call failed")
    error.__cause__ = ConnectionRefusedError(f"could not embed: {PERSONAL_QUESTION}")
    return error


@pytest.mark.parametrize(
    ("failure", "code", "recorded", "exceptions"),
    [
        pytest.param(
            RuntimeError("pool exhausted"),
            "InternalServerError",
            "RuntimeError",
            ["RuntimeError"],
            id="an unexpected failure goes out as the generic error and is reported whole",
        ),
        pytest.param(
            provider_failure(),
            "LLMError",
            "embedding call failed",
            [],
            id="a provider failure is reported as its log line, without the provider's text",
        ),
    ],
)
def test_a_failed_stream_ends_in_one_error_frame_recorded_and_reported_without_the_question(
    seeded_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    sentry: RecordingTransport,
    failure: Exception,
    code: str,
    recorded: str,
    exceptions: list[str],
):
    """The step that was running when it failed still went out, so the trail says where."""
    search_giving(monkeypatch, failure)

    with seeded_client.stream("POST", "/chat", json={"question": PERSONAL_QUESTION}) as response:
        assert response.status_code == 200
        request_id = response.headers["X-Request-ID"]
        events = read_events(response)

    assert [name for name, _ in events] == ["step", "step", "step", "error"]
    error = first_payload(events, "error")
    assert set(error) == {"error", "message", "request_id"}
    assert (error["error"], error["request_id"]) == (code, request_id)
    assert "pool exhausted" not in error["message"]

    [request] = ledger(seeded_client)
    assert (request.outcome, request.error) == (ChatOutcome.ERROR, recorded)
    assert request.request_id == request_id

    [event] = sentry.events
    assert event["tags"]["request_id"] == request_id
    assert [value["type"] for value in event.get("exception", {}).get("values", [])] == exceptions
    reported = json.dumps(event, default=str)
    assert "Jane Example" not in reported
    assert "could not embed" not in reported


def test_the_frames_are_documented_as_an_event_stream(client: TestClient):
    """The generated client types the frames from the one media type sent, as a union
    it can narrow on the event name."""
    spec = client.get("/openapi.json").json()
    content = spec["paths"]["/chat"]["post"]["responses"]["200"]["content"]
    (media_type,) = content
    assert media_type == "text/event-stream"
    schema = content[media_type]["schema"]
    assert schema["discriminator"]["propertyName"] == "event"
    assert schema["discriminator"]["mapping"]["text"] == "#/components/schemas/TextEvent"
    assert schema["discriminator"]["mapping"]["step"] == "#/components/schemas/StepEvent"
    text_event = spec["components"]["schemas"]["TextEvent"]
    assert text_event["properties"]["event"]["const"] == "text"
    assert set(text_event["required"]) == {"event", "data"}
