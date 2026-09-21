"""Chat request recording: the row, its node rows, and the log line."""

import logging
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import service
from app.chat.enums import ChatNode, ChatOutcome
from app.chat.models import ChatState, ChatStepResult, ChatTurn
from app.chat.schemas import ChatRequest, ChatRequestStep
from app.chat.service import create_chat_request, load_thread_history, spent_since
from app.core.clock import utc_now
from app.core.config import config
from app.core.logger import request_id_var
from tests.conftest import REPORTED_USAGE, reply_message, retrieved_chunk

pytestmark = pytest.mark.anyio

THREAD_ID = UUID("11111111-2222-3333-4444-555555555555")


def answered_state() -> ChatState:
    """A state as the graph leaves it once an answer has been synthesized."""
    return ChatState(
        question="What must ships report?",
        thread_id=THREAD_ID,
        steps=(
            ChatStepResult(step=ChatNode.RETRIEVE, ms=120),
            ChatStepResult.from_reply(ChatNode.SYNTHESIZE, 1300, reply_message()),
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


async def test_an_answered_run_is_recorded_with_its_steps_its_price_and_one_stats_line(
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
    assert row.cost_usd == REPORTED_USAGE.cost_usd is not None
    assert row.total_ms == 1500
    assert row.error is None
    assert row.created_at is not None

    nodes = (await db_session.scalars(node_rows())).all()
    assert [(n.chat_request_id, n.position, n.step, n.ms) for n in nodes] == [
        (row.id, 0, "retrieve", 120),
        (row.id, 1, "synthesize", 1300),
    ]
    assert [(n.input_tokens, n.output_tokens) for n in nodes] == [(None, None), (1500, 40)]
    assert [n.model for n in nodes] == [None, config.CHAT_MODEL]
    assert [n.cost_usd for n in nodes] == [None, REPORTED_USAGE.cost_usd]

    [line] = stats_lines(caplog)
    assert line.__dict__["cost_usd"] == REPORTED_USAGE.cost_usd
    assert not {"question", "answer"} & set(line.__dict__)


REFUSED_PATH = (
    ChatStepResult(step=ChatNode.RETRIEVE, ms=90),
    ChatStepResult(step=ChatNode.REFUSE, ms=0),
)


@pytest.mark.parametrize(
    ("ending", "outcome", "answer", "error", "steps"),
    [
        pytest.param(
            {"error": "embedding call failed"},
            ChatOutcome.ERROR,
            None,
            "embedding call failed",
            [],
            id="a failed run keeps its error and nulls where it never got",
        ),
        pytest.param(
            {"steps": REFUSED_PATH, "answer": "The corpus doesn't cover this."},
            ChatOutcome.REFUSED,
            "The corpus doesn't cover this.",
            None,
            [("retrieve", 90), ("refuse", 0)],
            id="a refused run keeps the path to its refusal",
        ),
        pytest.param(
            {"cached": True, "answer": "A regulation.[1]"},
            ChatOutcome.CACHED,
            "A regulation.[1]",
            None,
            [],
            id="a cached answer is recorded with no path behind it",
        ),
    ],
)
async def test_a_run_that_called_no_model_is_recorded_unpriced_under_its_ending(
    db_session: AsyncSession, ending, outcome, answer, error, steps
):
    state = ChatState(question="q", total_ms=40, **ending)

    await create_chat_request(db_session, state)

    [row] = (await db_session.scalars(select(ChatRequest))).all()
    assert (row.outcome, row.answer, row.error) == (outcome, answer, error)
    assert row.thread_id == state.thread_id
    assert (row.model, row.input_tokens, row.output_tokens, row.cost_usd) == (None,) * 4
    assert row.sources == 0
    nodes = (await db_session.scalars(node_rows())).all()
    assert [(n.step, n.ms) for n in nodes] == steps


def turn(question: str, answer: str, *, thread_id: UUID, **ending: Any) -> ChatState:
    """A finished turn on a thread, answered unless given another ending."""
    answered = (
        ChatStepResult(step=ChatNode.RETRIEVE, ms=10),
        ChatStepResult(step=ChatNode.SYNTHESIZE, ms=100),
    )
    fields: dict[str, Any] = {"steps": answered, "total_ms": 120, **ending}
    return ChatState(question=question, thread_id=thread_id, answer=answer, **fields)


async def test_a_threads_history_is_its_answered_turns_oldest_first_without_markers(
    db_session: AsyncSession,
):
    """A cache hit mints its own thread, so a follow-up on it must see the answer it got. A
    DONE row can hold no answer text, and an empty assistant turn is one the provider
    rewrites into a placeholder line the thread never said."""
    thread, other = uuid4(), uuid4()
    for recorded in (
        turn("What is FuelEU?", "A regulation.[1]", thread_id=thread, steps=(), cached=True),
        turn("Unrelated", "Elsewhere.[1]", thread_id=other),
        turn("Pizza?", "The corpus doesn't cover this.", thread_id=thread, steps=REFUSED_PATH),
        turn("Timed out?", "Half an ans", thread_id=thread, error="chat call failed"),
        turn("Empty?", "", thread_id=thread),
        turn("Its penalties?", "Fines.[2][3]", thread_id=thread),
    ):
        await create_chat_request(db_session, recorded)

    history = await load_thread_history(db_session, thread)

    assert history == (
        ChatTurn(question="What is FuelEU?", answer="A regulation."),
        ChatTurn(question="Its penalties?", answer="Fines."),
    )


async def test_history_is_capped_to_the_latest_thread_turns(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(config, "CHAT_THREAD_TURNS", 2)
    thread = uuid4()
    for n in range(3):
        await create_chat_request(db_session, turn(f"q{n}", f"a{n}", thread_id=thread))

    history = await load_thread_history(db_session, thread)

    assert [t.question for t in history] == ["q1", "q2"]


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


@pytest.mark.parametrize(
    ("rows", "spent"),
    [
        pytest.param(
            [(0.5, 1), (0.25, 23), (None, 2), (4.0, 25)],
            0.75,
            id="priced rows inside the window are summed, unpriced ones adding nothing",
        ),
        pytest.param([(None, 1)], 0.0, id="a ledger of unpriced rows reads as zero"),
        pytest.param([], 0.0, id="so does an empty ledger"),
    ],
)
async def test_the_spend_is_the_sum_of_the_last_days_priced_rows(
    db_session: AsyncSession, rows, spent
):
    db_session.add_all([ledger_row(cost_usd, hours_ago) for cost_usd, hours_ago in rows])
    await db_session.flush()

    assert await spent_since(db_session, utc_now() - timedelta(days=1)) == pytest.approx(spent)
