"""Chat request recording: the row, its node rows, and the log line."""

import logging
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import service
from app.chat.enums import ChatNode, ChatOutcome
from app.chat.exceptions import SpendCapReachedError, ThreadFullError
from app.chat.models import ChatState, ChatStepResult, ChatTurn
from app.chat.schemas import ChatRequest, ChatRequestStep
from app.chat.service import create_chat_request, load_thread_history, spent_since
from app.chat.toolbox.models import ToolCall
from app.chat.toolbox.service import build_call_step
from app.core.clock import utc_now
from app.core.config import config
from app.core.logger import request_id_var
from tests.conftest import TOKEN_USAGE, USAGE, retrieved_chunk

pytestmark = pytest.mark.anyio

THREAD_ID = UUID("11111111-2222-3333-4444-555555555555")


def answered_state() -> ChatState:
    """A state as the graph leaves it once an answer has been synthesized."""
    return ChatState(
        question="What must ships report?",
        thread_id=THREAD_ID,
        steps=(
            ChatStepResult(step=ChatNode.RETRIEVE, ms=120),
            ChatStepResult.from_usage(ChatNode.SYNTHESIZE, 1300, USAGE),
        ),
        sources=tuple(retrieved_chunk(id=n) for n in range(6)),
        answer="Ships must report [1].",
        total_ms=1500,
    )


def node_rows() -> Select[tuple[ChatRequestStep]]:
    """The node rows in path order — the order the relationship reads them in."""
    return select(ChatRequestStep).order_by(ChatRequestStep.position)


def stats_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The stats lines the service logged, with their extra fields as record attributes."""
    return [
        record
        for record in caplog.records
        if record.name == service.logger.name and record.levelno == logging.INFO
    ]


async def test_recorded_row_reads_the_stats_and_the_request_context(
    db_session: AsyncSession, caplog
):
    token = request_id_var.set("abc123")
    try:
        await create_chat_request(db_session, answered_state())
    finally:
        request_id_var.reset(token)

    [row] = (await db_session.scalars(select(ChatRequest))).all()
    assert row.question == "What must ships report?"
    assert row.thread_id == THREAD_ID
    assert row.answer == "Ships must report [1]."
    assert row.request_id == "abc123"
    assert row.outcome is ChatOutcome.DONE
    assert row.model == config.CHAT_MODEL
    assert row.sources == 6
    assert (row.input_tokens, row.output_tokens) == (1500, 40)
    assert row.total_ms == 1500
    assert row.error is None
    assert row.created_at is not None
    assert len(stats_lines(caplog)) == 1

    nodes = (await db_session.scalars(node_rows())).all()
    assert [(n.chat_request_id, n.position, n.step, n.ms) for n in nodes] == [
        (row.id, 0, "retrieve", 120),
        (row.id, 1, "synthesize", 1300),
    ]
    assert [(n.input_tokens, n.output_tokens) for n in nodes] == [(None, None), (1500, 40)]


async def test_failed_run_records_its_error_and_nulls_where_it_never_got(
    db_session: AsyncSession, caplog
):
    failed = ChatState(question="q", total_ms=40, error="embedding call failed")
    await create_chat_request(db_session, failed)

    [row] = (await db_session.scalars(select(ChatRequest))).all()
    assert row.outcome is ChatOutcome.ERROR
    assert row.error == "embedding call failed"
    assert row.answer is None
    assert row.thread_id == failed.thread_id
    assert (row.input_tokens, row.output_tokens) == (None, None)
    assert row.sources == 0
    assert (await db_session.scalars(select(ChatRequestStep))).all() == []


async def test_log_line_carries_the_stats_but_not_the_content(db_session: AsyncSession, caplog):
    """A tool step's subject is the query the model wrote from the question: content, so the
    line keeps the step and its timing and drops that."""
    state = answered_state()
    search = ToolCall(name="search", args={"query": "penalties for a missing monitoring plan"})
    state.steps = (*state.steps, build_call_step(search, ms=80))
    await create_chat_request(db_session, state)

    [record] = stats_lines(caplog)
    assert record.getMessage() == "chat done in 1500ms"
    assert record.__dict__["outcome"] == "done"
    assert record.__dict__["sources"] == 6
    assert record.__dict__["cost_usd"] == TOKEN_USAGE.cost_usd(config.CHAT_MODEL)
    assert record.__dict__["steps"] == [
        {"step": "retrieve", "ms": 120, "usage": None},
        {"step": "synthesize", "ms": 1300, "usage": {"input_tokens": 1500, "output_tokens": 40}},
        {"step": "tool_search", "ms": 80, "usage": None},
    ]
    assert "question" not in record.__dict__
    assert "answer" not in record.__dict__


async def test_a_refused_request_is_recorded_as_such(db_session: AsyncSession, caplog):
    """The gate's outcome fits the column as migrated: refused is no longer than aborted."""
    refused = ChatState(
        question="best pizza topping?",
        steps=(
            ChatStepResult(step=ChatNode.RETRIEVE, ms=90),
            ChatStepResult(step=ChatNode.REFUSE, ms=0),
        ),
        total_ms=95,
    )
    await create_chat_request(db_session, refused)

    [row] = (await db_session.scalars(select(ChatRequest))).all()
    assert row.outcome is ChatOutcome.REFUSED
    assert (row.sources, row.input_tokens) == (0, None)
    nodes = (await db_session.scalars(node_rows())).all()
    assert [(n.step, n.ms) for n in nodes] == [("retrieve", 90), ("refuse", 0)]
    assert stats_lines(caplog)[0].getMessage() == "chat refused in 95ms"


def turn(question: str, answer: str, *, thread_id: UUID, outcome_steps=None) -> ChatState:
    """A finished turn on a thread, answered unless given a path that ends elsewhere."""
    steps = (
        ChatStepResult(step=ChatNode.RETRIEVE, ms=10),
        ChatStepResult(step=ChatNode.SYNTHESIZE, ms=100),
    )
    return ChatState(
        question=question,
        thread_id=thread_id,
        steps=outcome_steps if outcome_steps is not None else steps,
        answer=answer,
        total_ms=120,
    )


async def test_a_threads_history_is_its_answered_turns_oldest_first_without_markers(
    db_session: AsyncSession,
):
    thread, other = uuid4(), uuid4()
    await create_chat_request(
        db_session, turn("What is FuelEU?", "A regulation.[1]", thread_id=thread)
    )
    await create_chat_request(db_session, turn("Unrelated", "Elsewhere.[1]", thread_id=other))
    refused = (
        ChatStepResult(step=ChatNode.RETRIEVE, ms=5),
        ChatStepResult(step=ChatNode.REFUSE, ms=0),
    )
    await create_chat_request(
        db_session,
        turn("Pizza?", "The corpus doesn't cover this.", thread_id=thread, outcome_steps=refused),
    )
    await create_chat_request(db_session, turn("Its penalties?", "Fines.[2][3]", thread_id=thread))

    history = await load_thread_history(db_session, thread)

    assert history == (
        ChatTurn(question="What is FuelEU?", answer="A regulation."),
        ChatTurn(question="Its penalties?", answer="Fines."),
    )


async def test_an_answered_row_without_an_answer_is_left_out_of_the_history(
    db_session: AsyncSession,
):
    """A DONE row can hold no answer text; passed through, an empty assistant turn is
    rewritten by the provider into a placeholder line the thread never said."""
    thread = uuid4()
    await create_chat_request(db_session, turn("What is FuelEU?", "", thread_id=thread))
    await create_chat_request(db_session, turn("Its penalties?", "Fines.[1]", thread_id=thread))

    history = await load_thread_history(db_session, thread)

    assert history == (ChatTurn(question="Its penalties?", answer="Fines."),)


async def test_history_is_capped_to_the_latest_thread_turns(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(config, "CHAT_THREAD_TURNS", 2)
    thread = uuid4()
    for n in range(3):
        await create_chat_request(db_session, turn(f"q{n}", f"a{n}", thread_id=thread))

    history = await load_thread_history(db_session, thread)

    assert [t.question for t in history] == ["q1", "q2"]


async def test_an_unknown_thread_has_no_history(db_session: AsyncSession):
    assert await load_thread_history(db_session, uuid4()) == ()


def test_a_full_thread_names_its_cap():
    assert ThreadFullError(5).message == (
        "This thread has reached its 5 turns; start a new thread to keep asking"
    )
    assert ThreadFullError(5).status_code == 409


def test_a_reached_spend_cap_is_a_pause_not_a_fault():
    assert SpendCapReachedError().message == "The service is paused for the day; ask again later"
    assert SpendCapReachedError().status_code == 503


def ledger_row(cost_usd: float | None, hours_ago: float) -> ChatRequest:
    """A recorded request of a given cost, created that many hours ago."""
    return ChatRequest(
        question="q",
        outcome=ChatOutcome.DONE,
        model=config.CHAT_MODEL,
        total_ms=1,
        sources=0,
        cost_usd=cost_usd,
        created_at=utc_now() - timedelta(hours=hours_ago),
    )


async def test_recorded_row_prices_its_tokens_at_the_models_rates(db_session: AsyncSession):
    await create_chat_request(db_session, answered_state())

    [row] = (await db_session.scalars(select(ChatRequest))).all()
    assert row.cost_usd == TOKEN_USAGE.cost_usd(config.CHAT_MODEL) is not None


async def test_a_run_with_no_usage_records_no_cost(db_session: AsyncSession):
    await create_chat_request(db_session, ChatState(question="q", total_ms=40, error="boom"))

    [row] = (await db_session.scalars(select(ChatRequest))).all()
    assert row.cost_usd is None


async def test_spent_since_sums_the_priced_rows_inside_the_window(db_session: AsyncSession):
    db_session.add_all(
        [
            ledger_row(0.5, hours_ago=1),
            ledger_row(0.25, hours_ago=23),
            ledger_row(None, hours_ago=2),
            ledger_row(4.0, hours_ago=25),
        ]
    )
    await db_session.flush()

    assert await spent_since(db_session, utc_now() - timedelta(days=1)) == pytest.approx(0.75)


async def test_spent_since_is_zero_on_an_empty_ledger(db_session: AsyncSession):
    assert await spent_since(db_session, utc_now() - timedelta(days=1)) == 0.0
