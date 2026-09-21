"""Chat stream orchestration: the frames a run sends in order, and the one request every
ending records."""

import logging

import anyio
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.exc import OperationalError

from app.chat import stream
from app.chat.enums import ChatNode, ChatOutcome, ChatStepStatus, RefusalReason, ToolStep
from app.chat.events import (
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    SourcesEvent,
    StepEvent,
    TextEvent,
)
from app.chat.graph.nodes.refuse import REFUSAL_ANSWER
from app.chat.models import ChatQuery, Refusal
from app.chat.stream import stream_chat_events
from app.core.config import config
from app.core.llm.errors import LLMError
from tests.chat.conftest import (
    collect_events,
    fake_chat_model,
    search_giving,
    tool_call_message,
)
from tests.conftest import (
    REPORTED_USAGE,
    install_chat_model,
    junk_result,
    search_result,
)

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("recorded_requests", "no_tool_session")]

RUNNING, COMPLETED = ChatStepStatus.RUNNING, ChatStepStatus.COMPLETED
TWO_HITS = (search_result(), search_result(id=2, citation="Article 5(1)"))


def frames(events: list[ChatEvent]) -> list[tuple]:
    """The stream as the client reads it, one tuple per frame, an answer's tokens joined:
    a step with its status and subject, the sources by chunk id, the text, the ending."""
    read: list[tuple] = []
    for event in events:
        match event:
            case StepEvent():
                read.append((event.data.step, event.data.status, event.data.subject))
            case SourcesEvent():
                read.append(("sources", [source.chunk_id for source in event.data]))
            case TextEvent() if read and read[-1][0] == "text":
                read[-1] = ("text", read[-1][1] + event.data)
            case TextEvent():
                read.append(("text", event.data))
            case ErrorEvent():
                read.append(("error", event.data.error))
            case DoneEvent():
                read.append(("done",))
    return read


@pytest.mark.parametrize(
    ("search_gives", "outcome", "error", "path", "last_frame"),
    [
        pytest.param(
            TWO_HITS,
            ChatOutcome.DONE,
            None,
            [ChatNode.RETRIEVE, ChatNode.SYNTHESIZE],
            ("done",),
            id="an answer is recorded with its path, sources and usage",
        ),
        pytest.param(
            (junk_result(),),
            ChatOutcome.REFUSED,
            None,
            [ChatNode.RETRIEVE, ChatNode.REFUSE],
            ("done",),
            id="a gate refusal is recorded with nothing spent past retrieval",
        ),
        pytest.param(
            LLMError("embedding call failed"),
            ChatOutcome.ERROR,
            "embedding call failed",
            [],
            ("error", "LLMError"),
            id="a domain failure is recorded by its message",
        ),
        pytest.param(
            RuntimeError("pool exhausted"),
            ChatOutcome.ERROR,
            "RuntimeError",
            [],
            ("error", "InternalServerError"),
            id="an unexpected failure is recorded by its type and sent as the generic error",
        ),
    ],
)
async def test_every_ending_records_one_request_with_what_the_run_reached(
    monkeypatch, answer_model, recorded_requests, search_gives, outcome, error, path, last_frame
):
    """The wire says only that something went wrong, and the ledger keeps what did."""
    search_giving(monkeypatch, search_gives)

    events = await collect_events(ChatQuery(question="q"))

    assert frames(events)[-1] == last_frame
    assert "pool exhausted" not in events[-1].model_dump_json()
    [state] = recorded_requests
    assert (state.question, state.outcome, state.error) == ("q", outcome, error)
    assert [result.step for result in state.steps] == path
    answered = outcome is ChatOutcome.DONE
    assert len(state.sources) == (2 if answered else 0)
    assert state.usage() == (REPORTED_USAGE if answered else None)
    assert state.called_model() == (config.CHAT_MODEL if answered else None)
    assert state.total_ms is not None
    assert 0 <= sum(result.ms for result in state.steps) <= state.total_ms


async def test_a_refusal_is_logged_as_a_warning(monkeypatch, recorded_requests, caplog):
    monkeypatch.setattr(config, "CHAT_DAILY_SPEND_CAP_USD", 2.0)

    async def spent_the_cap(session, since):
        return 2.0

    monkeypatch.setattr("app.chat.stream.spent_since", spent_the_cap)

    await collect_events(ChatQuery(question="q"))

    [line] = [r for r in caplog.records if "chat stream failed" in r.getMessage()]
    assert line.levelno == logging.WARNING


async def test_failed_write_is_logged_not_raised(two_results, monkeypatch, caplog):
    """The ledger write failing after the answer went out is a log line, not a broken stream."""
    model = fake_chat_model()
    install_chat_model(monkeypatch, model)

    async def broken_create_chat_request(session, state):
        raise OperationalError("insert", {}, ConnectionRefusedError("database away"))

    monkeypatch.setattr("app.chat.stream.create_chat_request", broken_create_chat_request)

    events = await collect_events(ChatQuery(question="q"))

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
            async for event in stream_chat_events(ChatQuery(question="q")):
                if isinstance(event, SourcesEvent):
                    tg.cancel_scope.cancel()

        tg.start_soon(consume_until_sources_then_leave)

    [state] = recorded_requests
    assert state.outcome is ChatOutcome.ABORTED
    assert len(state.sources) == 2


async def test_an_answered_question_sends_its_frames_in_order(
    two_results, answer_model, recorded_requests
):
    """Each step is announced as it starts and again once it finishes, so the trail names
    what the reader is waiting on. Retrieve is reported finished before the sources it found
    arrive: were that order to flip, they would land while the trail still said it ran."""
    events = await collect_events(ChatQuery(question="q"))

    assert frames(events) == [
        (ChatNode.RETRIEVE, RUNNING, None),
        (ChatNode.RETRIEVE, COMPLETED, None),
        ("sources", [1, 2]),
        (ChatNode.SYNTHESIZE, RUNNING, None),
        ("text", "Answered [1]."),
        (ChatNode.SYNTHESIZE, COMPLETED, None),
        ("done",),
    ]
    steps = [event.data for event in events if isinstance(event, StepEvent)]
    assert all(step.ms == 0 for step in steps if step.status is RUNNING)
    [state] = recorded_requests
    assert all(step.status is COMPLETED for step in state.steps)


SEARCH_ROUND = (
    tool_call_message("search", {"query": "gap"}),
    AIMessage(content="The context now covers the question."),
)
REFUSE_CALL = (tool_call_message("refuse", {"explanation": "nothing bears on it"}),)
ASSESS = [(ChatNode.ASSESS, RUNNING, None), (ChatNode.ASSESS, COMPLETED, None)]


@pytest.mark.parametrize(
    ("assess_says", "fetched", "after_the_first_assess", "outcome"),
    [
        pytest.param(
            SEARCH_ROUND,
            (search_result(id=2, citation="Article 5(1)"),),
            [
                (ToolStep.SEARCH, RUNNING, "gap"),
                (ToolStep.SEARCH, COMPLETED, "gap"),
                *ASSESS,
                ("sources", [1, 2]),
                (ChatNode.SYNTHESIZE, RUNNING, None),
                ("text", "Answered [1]."),
                (ChatNode.SYNTHESIZE, COMPLETED, None),
                ("done",),
            ],
            ChatOutcome.DONE,
            id="a tool round names its call, then the merged sources go out once",
        ),
        pytest.param(
            REFUSE_CALL,
            (),
            [
                (ToolStep.REFUSE, RUNNING, "nothing bears on it"),
                (ToolStep.REFUSE, COMPLETED, "nothing bears on it"),
                ("sources", [1]),
                (ChatNode.REFUSE, RUNNING, None),
                (ChatNode.REFUSE, COMPLETED, None),
                ("text", REFUSAL_ANSWER),
                ("done",),
            ],
            ChatOutcome.REFUSED,
            id="a refusal assess asked for sends the context it read, then the refusal",
        ),
    ],
)
async def test_the_loop_streams_its_calls_by_subject_and_none_of_what_assess_said(
    loop_on,
    one_result,
    answer_model,
    assess_turns,
    tool_results,
    recorded_requests,
    assess_says,
    fetched,
    after_the_first_assess,
    outcome,
):
    """The round announces one step per call assess asked for, each carrying what it was
    for, so the reader sees what is being searched for while it is being searched for."""
    assess_turns(*assess_says)
    tool_results(*fetched)

    events = await collect_events(ChatQuery(question="q"))

    assert frames(events) == [
        (ChatNode.RETRIEVE, RUNNING, None),
        (ChatNode.RETRIEVE, COMPLETED, None),
        *ASSESS,
        *after_the_first_assess,
    ]
    [state] = recorded_requests
    assert state.outcome is outcome
    if outcome is ChatOutcome.REFUSED:
        assert answer_model.received == []
        assert state.refusal == Refusal(
            reason=RefusalReason.INSUFFICIENT_CONTEXT, explanation="nothing bears on it"
        )
