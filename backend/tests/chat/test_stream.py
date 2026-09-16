"""Chat stream orchestration: every way a stream ends records one request with what it reached."""

import json
import logging
import re
from uuid import UUID

import anyio
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from sqlalchemy.exc import OperationalError

from app.chat import stream
from app.chat.cache import normalize_question, store_answer
from app.chat.enums import ChatNode, ChatOutcome, ChatStepStatus, RefusalReason, ToolStep
from app.chat.events import DoneEvent, ErrorEvent, SourcesEvent, StepEvent, TextEvent
from app.chat.graph.nodes.refuse import REFUSAL_ANSWER
from app.chat.models import CachedAnswer, ChatQuery, ChatTurn, Refusal
from app.chat.stream import stream_chat_events
from app.core.config import config
from app.core.llm.errors import LLMError
from tests.chat.conftest import (
    RecordingChatModel,
    fake_chat_model,
    restated_message,
    tool_call_message,
)
from tests.conftest import (
    REPORTED_USAGE,
    USAGE,
    install_chat_model,
    install_search,
    retrieved_chunk,
    search_result,
    unreachable_redis,
)

pytestmark = pytest.mark.anyio

NO_REDIS = unreachable_redis()
"""The answer cache is off unless a test turns it on, so these streams never reach Redis."""


async def test_finished_stream_records_timings_sources_and_usage(
    two_results, monkeypatch, recorded_requests
):
    model = fake_chat_model("Two words [1].")
    install_chat_model(monkeypatch, model)

    async for _ in stream_chat_events(ChatQuery(question="q"), NO_REDIS):
        pass

    [state] = recorded_requests
    assert state.question == "q"
    assert state.outcome is ChatOutcome.DONE
    retrieve, synthesize = state.steps
    assert (retrieve.step, synthesize.step) == (ChatNode.RETRIEVE, ChatNode.SYNTHESIZE)
    assert (retrieve.usage, synthesize.usage) == (None, REPORTED_USAGE)
    assert (retrieve.model, synthesize.model) == (None, config.CHAT_MODEL)
    assert len(state.sources) == 2
    assert state.total_ms is not None
    assert 0 <= sum(result.ms for result in state.steps) <= state.total_ms
    assert state.error is None


async def test_failed_stream_records_what_it_reached(monkeypatch, recorded_requests):
    async def failing_search(session, request):
        raise LLMError("embedding call failed")

    install_search(monkeypatch, failing_search)

    async for _ in stream_chat_events(ChatQuery(question="q"), NO_REDIS):
        pass

    [state] = recorded_requests
    assert state.outcome is ChatOutcome.ERROR
    assert state.error == "embedding call failed"
    assert state.steps == ()
    assert state.sources == ()
    assert state.usage() is None


async def test_unexpected_failure_is_recorded_by_its_type_and_sent_as_the_generic_error(
    monkeypatch, recorded_requests
):
    """The wire says only that something went wrong; the ledger keeps what did."""

    async def exploding_search(session, request):
        raise RuntimeError("pool exhausted")

    install_search(monkeypatch, exploding_search)

    events = [event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)]

    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].data.message == "An unexpected error occurred"
    [state] = recorded_requests
    assert state.outcome is ChatOutcome.ERROR
    assert state.error == "RuntimeError"


async def test_abandoned_stream_still_records(two_results, monkeypatch, recorded_requests):
    model = fake_chat_model()
    install_chat_model(monkeypatch, model)

    events = stream_chat_events(ChatQuery(question="q"), NO_REDIS)
    async for event in events:
        if isinstance(event, SourcesEvent):
            break
    await events.aclose()

    [state] = recorded_requests
    assert state.outcome is ChatOutcome.ABORTED
    assert len(state.sources) == 2
    assert [result.step for result in state.steps] == [ChatNode.RETRIEVE]


async def test_failed_write_is_logged_not_raised(two_results, monkeypatch, caplog):
    """The ledger write failing after the answer went out is a log line, not a broken stream."""
    model = fake_chat_model()
    install_chat_model(monkeypatch, model)

    async def broken_create_chat_request(session, state):
        raise OperationalError("insert", {}, ConnectionRefusedError("database away"))

    monkeypatch.setattr("app.chat.stream.create_chat_request", broken_create_chat_request)

    events = [event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)]

    assert isinstance(events[-1], DoneEvent)
    [error] = [
        r for r in caplog.records if r.name == stream.logger.name and r.levelno == logging.ERROR
    ]
    assert error.getMessage() == "chat request not recorded"
    assert error.exc_info is not None


async def test_cancelled_stream_still_records(two_results, monkeypatch, recorded_requests):
    """A client leaving cancels the streaming task mid-stream; the record still lands. It
    leaves once the sources are out, so the run has reached something worth recording; the
    fake write yields once, so an unshielded await there would be cancelled, not run."""
    model = fake_chat_model()
    install_chat_model(monkeypatch, model)

    async def yielding_create_chat_request(session, state):
        await anyio.sleep(0)
        recorded_requests.append(state)

    monkeypatch.setattr("app.chat.stream.create_chat_request", yielding_create_chat_request)

    async with anyio.create_task_group() as tg:

        async def consume_until_sources_then_leave():
            async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS):
                if isinstance(event, SourcesEvent):
                    tg.cancel_scope.cancel()

        tg.start_soon(consume_until_sources_then_leave)

    [state] = recorded_requests
    assert state.outcome is ChatOutcome.ABORTED
    assert len(state.sources) == 2


async def test_refused_stream_carries_the_refusal_as_its_answer_and_records_it(
    one_junk_result, answer_model, recorded_requests
):
    """No context, so no model call: an empty sources event, the refusal as the one text frame,
    done — and the ledger says refused, with nothing spent past retrieval."""
    events = [
        event
        async for event in stream_chat_events(ChatQuery(question="best pizza topping?"), NO_REDIS)
    ]

    assert step_frames(events) == [
        (ChatNode.RETRIEVE, ChatStepStatus.RUNNING, None),
        (ChatNode.RETRIEVE, ChatStepStatus.COMPLETED, None),
        (ChatNode.REFUSE, ChatStepStatus.RUNNING, None),
        (ChatNode.REFUSE, ChatStepStatus.COMPLETED, None),
    ]
    assert [e for e in events if isinstance(e, SourcesEvent)] == [SourcesEvent(data=())]
    assert [e for e in events if isinstance(e, TextEvent)] == [TextEvent(data=REFUSAL_ANSWER)]
    assert answer_model.received == []
    [state] = recorded_requests
    assert state.outcome is ChatOutcome.REFUSED
    assert [result.step for result in state.steps] == [ChatNode.RETRIEVE, ChatNode.REFUSE]
    assert state.sources == ()
    assert state.usage() is None


async def test_a_refusal_assess_asked_for_sends_the_context_it_read_then_the_refusal(
    loop_on, one_result, monkeypatch, recorded_requests
):
    """The tool step carries the explanation, the context settled when it ran, so the sources go
    out as on any answered question; the one text frame is the fixed refusal, and the ledger
    says refused."""
    assess = ToolCallStreamingModel(
        messages=iter([tool_call_message("refuse", {"explanation": "nothing bears on it"})]),
        usage=USAGE,
    )
    monkeypatch.setattr("app.chat.graph.nodes.assess.assess_model", lambda: assess)
    model = fake_chat_model()
    install_chat_model(monkeypatch, model)

    events = [event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)]

    assert step_frames(events)[4:] == [
        (ToolStep.REFUSE, ChatStepStatus.RUNNING, "nothing bears on it"),
        (ToolStep.REFUSE, ChatStepStatus.COMPLETED, "nothing bears on it"),
        (ChatNode.REFUSE, ChatStepStatus.RUNNING, None),
        (ChatNode.REFUSE, ChatStepStatus.COMPLETED, None),
    ]
    [sources] = [e for e in events if isinstance(e, SourcesEvent)]
    assert [source.chunk_id for source in sources.data] == [1]
    assert [e for e in events if isinstance(e, TextEvent)] == [TextEvent(data=REFUSAL_ANSWER)]
    assert model.received == []
    [state] = recorded_requests
    assert state.outcome is ChatOutcome.REFUSED
    assert state.refusal == Refusal(
        reason=RefusalReason.INSUFFICIENT_CONTEXT, explanation="nothing bears on it"
    )


def step_frames(events) -> list[tuple]:
    """Every step frame as (step, status, subject) — the path as the client is told it."""
    return [
        (event.data.step, event.data.status, event.data.subject)
        for event in events
        if isinstance(event, StepEvent)
    ]


async def test_each_step_is_announced_as_it_starts_and_again_once_it_finishes(
    two_results, answer_model
):
    """A trail that only reported finished work would name a step at the moment it stopped
    being true; the running frame is what the reader is actually waiting on."""
    events = [event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)]

    assert step_frames(events) == [
        (ChatNode.RETRIEVE, ChatStepStatus.RUNNING, None),
        (ChatNode.RETRIEVE, ChatStepStatus.COMPLETED, None),
        (ChatNode.SYNTHESIZE, ChatStepStatus.RUNNING, None),
        (ChatNode.SYNTHESIZE, ChatStepStatus.COMPLETED, None),
    ]


async def test_retrieve_is_running_before_the_sources_it_finds_arrive(two_results, answer_model):
    events = [event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)]

    first_step = next(i for i, e in enumerate(events) if isinstance(e, StepEvent))
    sources = next(i for i, e in enumerate(events) if isinstance(e, SourcesEvent))
    assert first_step < sources
    assert step_frames(events)[0] == (ChatNode.RETRIEVE, ChatStepStatus.RUNNING, None)


async def test_retrieve_is_reported_finished_before_the_sources_it_found_arrive(
    two_results, answer_model
):
    """The finished frame comes from the node's task result, the sources from the state
    snapshot after it. Were that order to flip, the sources would land while the trail still
    said retrieve was running."""
    events = [event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)]

    finished = next(
        i
        for i, event in enumerate(events)
        if isinstance(event, StepEvent)
        and (event.data.step, event.data.status) == (ChatNode.RETRIEVE, ChatStepStatus.COMPLETED)
    )
    sources = next(i for i, event in enumerate(events) if isinstance(event, SourcesEvent))
    assert finished < sources


async def test_a_running_step_reports_no_timing_and_the_ledger_never_sees_one(
    two_results, answer_model, recorded_requests
):
    """Timing belongs to work that has happened; the path the ledger keeps is finished work."""
    events = [event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)]

    steps = [event.data for event in events if isinstance(event, StepEvent)]
    running = [step for step in steps if step.status is ChatStepStatus.RUNNING]
    completed = [step for step in steps if step.status is ChatStepStatus.COMPLETED]
    assert all(step.ms == 0 for step in running)
    [state] = recorded_requests
    assert len(completed) == len(state.steps)
    assert all(step.status is ChatStepStatus.COMPLETED for step in state.steps)


class ToolCallStreamingModel(RecordingChatModel):
    """Streams tool calls as litellm's real chunks do; the base fake's `_stream` only
    carries content, so an assess call driven through the messages stream would lose them."""

    def _stream(self, messages, *args, **kwargs):
        message = self._generate(messages, *args, **kwargs).generations[0].message
        assert isinstance(message, AIMessage)
        if message.tool_calls:
            for call in message.tool_calls:
                yield ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {
                                "name": call["name"],
                                "args": json.dumps(call["args"]),
                                "id": call["id"],
                                "index": 0,
                            }
                        ],
                    )
                )
        elif isinstance(message.content, str) and message.content:
            for token in re.split(r"(\s)", message.content):
                yield ChatGenerationChunk(message=AIMessageChunk(content=token))
        if self.usage:
            yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=self.usage))


class TestLoopStreaming:
    @pytest.fixture
    def one_assess_round(self, monkeypatch):
        assess = ToolCallStreamingModel(
            messages=iter([tool_call_message("search", {"query": "gap"}), AIMessage(content="")]),
            usage=USAGE,
        )
        monkeypatch.setattr("app.chat.graph.nodes.assess.assess_model", lambda: assess)

        async def fake_run_tool_call(call):
            return (search_result(id=2, citation="Article 5(1)"),)

        monkeypatch.setattr("app.chat.graph.nodes.assess.run_tool_call", fake_run_tool_call)

    async def test_sources_arrive_once_with_the_merged_context(
        self, loop_on, one_result, one_assess_round, answer_model
    ):
        events = [event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)]

        sources_events = [e for e in events if isinstance(e, SourcesEvent)]
        assert len(sources_events) == 1
        assert [source.chunk_id for source in sources_events[0].data] == [1, 2]
        assert events.index(sources_events[0]) < events.index(
            next(e for e in events if isinstance(e, TextEvent))
        )

    async def test_assess_turns_leak_no_text_events(
        self, loop_on, one_result, one_assess_round, monkeypatch
    ):
        install_chat_model(monkeypatch, fake_chat_model("The answer [1]."))

        events = [event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)]

        text = "".join(e.data for e in events if isinstance(e, TextEvent))
        assert text == "The answer [1]."

    async def test_a_tool_round_names_its_calls_before_it_runs_them(
        self, loop_on, one_result, one_assess_round, answer_model
    ):
        """The round announces one step per call assess asked for, each carrying the query,
        so the reader sees what is being searched for while it is being searched for."""
        events = [event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)]

        running, completed = ChatStepStatus.RUNNING, ChatStepStatus.COMPLETED
        assert step_frames(events) == [
            (ChatNode.RETRIEVE, running, None),
            (ChatNode.RETRIEVE, completed, None),
            (ChatNode.ASSESS, running, None),
            (ChatNode.ASSESS, completed, None),
            (ToolStep.SEARCH, running, "gap"),
            (ToolStep.SEARCH, completed, "gap"),
            (ChatNode.ASSESS, running, None),
            (ChatNode.ASSESS, completed, None),
            (ChatNode.SYNTHESIZE, running, None),
            (ChatNode.SYNTHESIZE, completed, None),
        ]


THREAD_ID = UUID("11111111-2222-3333-4444-555555555555")


def history_of(*turns: ChatTurn):
    """A load_thread_history answering every thread with these turns, recording the ids
    asked for."""
    asked: list[UUID] = []

    async def fake_load(session, thread_id):
        asked.append(thread_id)
        return turns

    return fake_load, asked


class TestThreads:
    async def test_a_first_question_mints_a_thread_and_returns_it_on_done(
        self, two_results, answer_model, monkeypatch, recorded_requests
    ):
        fake_load, asked = history_of()
        monkeypatch.setattr("app.chat.stream.load_thread_history", fake_load)

        events = [event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)]

        done = events[-1]
        assert isinstance(done, DoneEvent)
        [state] = recorded_requests
        assert done.data.thread_id == state.thread_id
        assert asked == []
        assert state.history == ()

    async def test_a_follow_up_loads_its_thread_and_answers_on_it(
        self, monkeypatch, recorded_requests, rewrite_turns
    ):
        rewrite_turns(restated_message("What penalties does FuelEU impose?"))
        model = fake_chat_model("Fines [1].")
        install_chat_model(monkeypatch, model)
        prior = ChatTurn(question="What is FuelEU?", answer="A regulation.")
        fake_load, asked = history_of(prior)
        monkeypatch.setattr("app.chat.stream.load_thread_history", fake_load)

        async def fake_search(session, request):
            assert request.query == "What penalties does FuelEU impose?"
            return (search_result(),)

        install_search(monkeypatch, fake_search)

        query = ChatQuery(question="What penalties does it impose?", thread_id=THREAD_ID)
        events = [event async for event in stream_chat_events(query, NO_REDIS)]

        assert asked == [THREAD_ID]
        assert [s for s, _, _ in step_frames(events)][:2] == [ChatNode.REWRITE, ChatNode.REWRITE]
        assert events[-1] == DoneEvent(data={"thread_id": THREAD_ID})
        [state] = recorded_requests
        assert state.thread_id == THREAD_ID
        assert state.history == (prior,)
        assert state.outcome is ChatOutcome.DONE

    async def test_a_full_thread_is_refused_before_the_graph_runs_and_recorded(
        self, monkeypatch, recorded_requests
    ):
        monkeypatch.setattr(config, "CHAT_THREAD_TURNS", 2)
        turns = tuple(ChatTurn(question=f"q{n}", answer=f"a{n}") for n in range(2))
        fake_load, _ = history_of(*turns)
        monkeypatch.setattr("app.chat.stream.load_thread_history", fake_load)
        model = fake_chat_model()
        install_chat_model(monkeypatch, model)

        query = ChatQuery(question="one more?", thread_id=THREAD_ID)
        events = [event async for event in stream_chat_events(query, NO_REDIS)]

        [error] = events
        assert isinstance(error, ErrorEvent)
        assert error.data.error == "ThreadFullError"
        assert error.data.message == (
            "This thread has reached its 2 turns; start a new thread to keep asking"
        )
        assert model.received == []
        [state] = recorded_requests
        assert state.outcome is ChatOutcome.ERROR
        assert state.steps == ()
        assert state.thread_id == THREAD_ID


class TestSpendCap:
    """The day's recorded spend is checked before anything runs."""

    async def test_at_the_cap_the_question_is_refused_before_the_graph_runs_and_recorded(
        self, monkeypatch, recorded_requests
    ):
        monkeypatch.setattr(config, "CHAT_DAILY_SPEND_CAP_USD", 2.0)

        async def spent_the_cap(session, since):
            return 2.0

        monkeypatch.setattr("app.chat.stream.spent_since", spent_the_cap)
        model = fake_chat_model()
        install_chat_model(monkeypatch, model)

        events = [event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)]

        [error] = events
        assert isinstance(error, ErrorEvent)
        assert error.data.error == "SpendCapReachedError"
        assert "paused" in error.data.message
        assert model.received == []
        [state] = recorded_requests
        assert state.outcome is ChatOutcome.ERROR
        assert state.steps == ()

    async def test_under_the_cap_the_run_goes_through_and_the_days_spend_is_logged(
        self, two_results, monkeypatch, recorded_requests, caplog
    ):
        monkeypatch.setattr(config, "CHAT_DAILY_SPEND_CAP_USD", 2.0)

        async def spent_some(session, since):
            return 1.99

        monkeypatch.setattr("app.chat.stream.spent_since", spent_some)
        install_chat_model(monkeypatch, fake_chat_model())

        with caplog.at_level(logging.INFO, logger=stream.logger.name):
            events = [
                event async for event in stream_chat_events(ChatQuery(question="q"), NO_REDIS)
            ]

        assert isinstance(events[-1], DoneEvent)
        [spend_line] = [r for r in caplog.records if "spend" in r.getMessage()]
        assert (spend_line.spent_usd, spend_line.cap_usd) == (1.99, 2.0)


@pytest.fixture
def cache_on(monkeypatch, answer_cache):
    """The answer cache on, over an emptied Redis, under a corpus version the test does not
    need a database for; the returned client is the one the stream is handed."""
    monkeypatch.setattr(config, "CHAT_CACHE_ENABLED", True)

    async def versioned_key(session, question):
        return f"chat:answer:v1:{normalize_question(question)}"

    monkeypatch.setattr("app.chat.stream.answer_key", versioned_key)
    return answer_cache


async def ask(redis, question="What is FuelEU?", **fields):
    return [
        event async for event in stream_chat_events(ChatQuery(question=question, **fields), redis)
    ]


class TestAnswerCache:
    """A repeated first question is answered from Redis, with no graph run behind it."""

    async def test_a_repeated_question_replays_the_answer_without_a_model_call(
        self, cache_on, two_results, answer_model, recorded_requests
    ):
        first = await ask(cache_on)
        second = await ask(cache_on, "  what is FUELEU ")

        assert len(answer_model.received) == 1
        assert [event.event for event in second] == ["sources", "text", "done"]
        assert second[0] == next(e for e in first if isinstance(e, SourcesEvent))
        assert second[1] == TextEvent(data="Answered [1].")
        answered, cached = recorded_requests
        assert (answered.outcome, cached.outcome) == (ChatOutcome.DONE, ChatOutcome.CACHED)
        assert cached.question == "  what is FUELEU "
        assert cached.steps == ()
        assert cached.usage() is None
        assert second[-1] == DoneEvent(data={"thread_id": cached.thread_id})
        assert cached.thread_id != answered.thread_id

    async def test_a_hit_is_served_past_the_spend_cap(
        self, cache_on, answer_model, recorded_requests, monkeypatch
    ):
        """An answer that costs nothing to serve is not what the cap guards."""
        await store_answer(cache_on, "chat:answer:v1:what is fueleu", cached_answer())

        async def spent_the_cap(session, since):
            return config.CHAT_DAILY_SPEND_CAP_USD

        monkeypatch.setattr("app.chat.stream.spent_since", spent_the_cap)

        events = await ask(cache_on)

        assert [event.event for event in events] == ["sources", "text", "done"]

    async def test_a_follow_up_neither_reads_nor_writes_the_cache(
        self, cache_on, two_results, recorded_requests, monkeypatch
    ):
        """A follow-up's answer depends on the thread before it, which the key does not hold."""
        await store_answer(cache_on, "chat:answer:v1:what is fueleu", cached_answer())
        fake_load, _ = history_of()
        monkeypatch.setattr("app.chat.stream.load_thread_history", fake_load)
        install_chat_model(monkeypatch, fake_chat_model("Fresh [1]."))

        events = await ask(cache_on, thread_id=THREAD_ID)

        assert "".join(e.data for e in events if isinstance(e, TextEvent)) == "Fresh [1]."
        assert await cache_on.dbsize() == 1
        [state] = recorded_requests
        assert state.outcome is ChatOutcome.DONE

    async def test_a_refusal_is_not_kept(self, cache_on, one_junk_result, answer_model):
        await ask(cache_on)

        assert await cache_on.dbsize() == 0

    async def test_a_failed_run_is_not_kept(self, cache_on, monkeypatch):
        async def failing_search(session, request):
            raise LLMError("embedding call failed")

        install_search(monkeypatch, failing_search)

        events = await ask(cache_on)

        assert isinstance(events[-1], ErrorEvent)
        assert await cache_on.dbsize() == 0

    async def test_before_any_corpus_the_graph_runs_and_nothing_is_kept(
        self, cache_on, two_results, answer_model, monkeypatch
    ):
        async def no_corpus(session, question):
            return None

        monkeypatch.setattr("app.chat.stream.answer_key", no_corpus)

        await ask(cache_on)
        await ask(cache_on)

        assert len(answer_model.received) == 2
        assert await cache_on.dbsize() == 0

    async def test_redis_away_runs_the_graph(self, cache_on, two_results, answer_model):
        redis = unreachable_redis()

        events = await ask(redis)

        assert isinstance(events[-1], DoneEvent)
        assert len(answer_model.received) == 1
        await redis.aclose()


def cached_answer() -> CachedAnswer:
    return CachedAnswer(answer="From the cache [1].", sources=(retrieved_chunk(),))
