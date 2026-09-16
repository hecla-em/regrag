"""Chat SSE endpoint: event ordering, payload shapes, and the error path."""

import json
from typing import Any
from uuid import UUID

import httpx

from app.chat.graph.nodes.refuse import REFUSAL_ANSWER
from app.core.config import config
from app.core.llm.errors import LLMError
from tests.chat.conftest import THINKING, fake_chat_model, reasoning_chat_model
from tests.conftest import install_chat_model, install_search


def read_events(response: httpx.Response) -> list[tuple[str, Any]]:
    """Parse the SSE body into (event, payload) pairs, ignoring pings."""
    events: list[tuple[str, Any]] = []
    name = None
    for line in response.iter_lines():
        if line.startswith("event:"):
            name = line.removeprefix("event:").strip()
        elif line.startswith("data:") and name is not None:
            events.append((name, json.loads(line.removeprefix("data:").strip())))
            name = None
    return events


def first_payload(events: list[tuple[str, Any]], name: str) -> Any:
    """The payload of the first frame with this event name."""
    return next(payload for event, payload in events if event == name)


def test_stream_orders_steps_then_sources_then_text_then_done(client, two_results, monkeypatch):
    model = fake_chat_model("Two words [1].")
    install_chat_model(monkeypatch, model)

    with client.stream("POST", "/chat", json={"question": "What is FuelEU?"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = read_events(response)

    names = [name for name, _ in events]
    assert names[0] == "step"
    assert names[-1] == "done"
    assert set(names) == {"step", "sources", "text", "done"}
    assert names.index("sources") < names.index("text")
    answer = "".join(payload for name, payload in events if name == "text")
    assert answer == "Two words [1]."


def test_block_list_content_streams_text_without_reasoning(client, two_results, monkeypatch):
    install_chat_model(monkeypatch, reasoning_chat_model())

    with client.stream("POST", "/chat", json={"question": "q"}) as response:
        events = read_events(response)

    answer = "".join(payload for name, payload in events if name == "text")
    assert answer == "Ships must comply [1]."
    assert THINKING not in json.dumps(events)


def test_stream_tells_proxies_and_browsers_not_to_buffer(client, two_results, monkeypatch):
    model = fake_chat_model()
    install_chat_model(monkeypatch, model)

    with client.stream("POST", "/chat", json={"question": "q"}) as response:
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"


def test_sources_event_binds_markers_to_chunks(client, two_results, monkeypatch):
    model = fake_chat_model()
    install_chat_model(monkeypatch, model)

    with client.stream("POST", "/chat", json={"question": "q"}) as response:
        events = read_events(response)

    sources = first_payload(events, "sources")
    assert [source["marker"] for source in sources] == [1, 2]
    assert sources[0]["chunk_id"] == 1
    assert sources[0]["celex"] == "32023R1805"
    assert sources[1]["citation"] == "Article 5(1)"


def test_sources_event_carries_the_paragraph_text(client, two_results, monkeypatch):
    model = fake_chat_model()
    install_chat_model(monkeypatch, model)

    with client.stream("POST", "/chat", json={"question": "q"}) as response:
        events = read_events(response)

    sources = first_payload(events, "sources")
    assert sources[0]["text"] == "The greenhouse gas intensity of the energy used on board."


def test_stream_failure_emits_an_error_event(client, monkeypatch):
    """The step that was running when it failed still went out, so the trail says where."""

    async def failing_search(session, request):
        raise LLMError("embedding call failed")

    install_search(monkeypatch, failing_search)

    with client.stream("POST", "/chat", json={"question": "q"}) as response:
        assert response.status_code == 200
        events = read_events(response)

    assert [name for name, _ in events] == ["step", "error"]
    payload = first_payload(events, "error")
    assert payload["error"] == "LLMError"
    assert payload["message"] == "embedding call failed"
    assert payload["request_id"] == response.headers["X-Request-ID"]
    assert "detail" not in payload


def test_unexpected_failure_emits_a_generic_error_event(client, monkeypatch):
    async def exploding_search(session, request):
        raise RuntimeError("secret internals")

    install_search(monkeypatch, exploding_search)

    with client.stream("POST", "/chat", json={"question": "q"}) as response:
        events = read_events(response)

    assert [name for name, _ in events] == ["step", "error"]
    payload = first_payload(events, "error")
    assert payload["error"] == "InternalServerError"
    assert payload["message"] == "An unexpected error occurred"
    assert "secret internals" not in json.dumps(payload)


def test_a_question_over_the_limit_is_refused_before_the_graph_runs(
    rate_limited_client, two_results, answer_model, monkeypatch
):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_CLIENT", 1)
    client = rate_limited_client
    headers = {"X-Client-ID": "reader"}
    with client.stream("POST", "/chat", json={"question": "q"}, headers=headers) as first:
        assert first.status_code == 200
        read_events(first)

    second = client.post("/chat", json={"question": "q"}, headers=headers)

    assert second.status_code == 429
    assert second.json()["error"] == "RateLimitedError"
    assert second.headers["Retry-After"]
    assert len(answer_model.received) == 1


def test_empty_question_is_rejected(client):
    response = client.post("/chat", json={"question": ""})
    assert response.status_code == 422


def test_the_frames_are_documented_as_an_event_stream(client):
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


def test_a_refused_question_streams_the_refusal_then_done(client, one_junk_result, answer_model):
    with client.stream("POST", "/chat", json={"question": "best pizza topping?"}) as response:
        events = read_events(response)

    assert [name for name, _ in events] == [
        "step",
        "step",
        "sources",
        "step",
        "step",
        "text",
        "done",
    ]
    assert first_payload(events, "sources") == []
    assert first_payload(events, "text") == REFUSAL_ANSWER
    assert answer_model.received == []


def test_done_carries_the_thread_a_first_question_was_recorded_under(
    client, two_results, answer_model
):
    with client.stream("POST", "/chat", json={"question": "q"}) as response:
        events = read_events(response)

    done = first_payload(events, "done")
    assert set(done) == {"thread_id"}
    UUID(done["thread_id"])


def test_a_supplied_thread_is_echoed_back_on_done(client, two_results, answer_model, monkeypatch):
    async def no_history(session, thread_id):
        return ()

    monkeypatch.setattr("app.chat.stream.load_thread_history", no_history)
    thread_id = "11111111-2222-3333-4444-555555555555"

    with client.stream("POST", "/chat", json={"question": "q", "thread_id": thread_id}) as response:
        events = read_events(response)

    assert first_payload(events, "done") == {"thread_id": thread_id}


def test_a_malformed_thread_id_is_rejected(client):
    response = client.post("/chat", json={"question": "q", "thread_id": "not-a-uuid"})
    assert response.status_code == 422
