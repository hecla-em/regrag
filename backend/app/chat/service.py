"""Chat request recording — one row per handled question, with a row per step — the vote a
reader casts on one, and the thread history read back from those rows."""

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.citations import strip_markers
from app.chat.enums import ANSWERED_OUTCOMES, Vote
from app.chat.models import ChatState, ChatTurn
from app.chat.schemas import ChatRequest, ChatRequestStep
from app.core.clock import utc_now
from app.core.config import config
from app.core.db.crud import create_record
from app.core.exceptions import NotFoundError

logger = logging.getLogger(__name__)


async def create_chat_request(session: AsyncSession, state: ChatState) -> None:
    """The run as recorded: one stats line, and a chat_requests row with a row per step."""
    usage = state.usage()
    fields = state.log_fields() | {"cost_usd": usage.cost_usd if usage else None}
    logger.info("chat %(outcome)s in %(total_ms)sms", fields, extra=fields)
    steps = [
        ChatRequestStep(
            position=idx,
            step=result.step.value,
            ms=result.ms,
            model=result.model,
            **(result.usage.model_dump() if result.usage else {}),
        )
        for idx, result in enumerate(state.steps)
    ]
    request = ChatRequest(
        request_id=state.request_id,
        question=state.question,
        thread_id=state.thread_id,
        answer=state.answer or None,
        outcome=state.outcome,
        model=state.called_model(),
        total_ms=state.total_ms,
        sources=len(state.sources),
        **(usage.model_dump() if usage else {}),
        error=state.error,
        steps=steps,
    )
    await create_record(session, request)


async def record_vote(session: AsyncSession, request_id: str, vote: Vote | None) -> None:
    """The reader's vote on the answer a request gave, in place of any earlier one; None
    takes it back. A request the ledger never recorded is not found."""
    stmt = (
        update(ChatRequest)
        .where(ChatRequest.request_id == request_id)
        .values(vote=vote, voted_at=utc_now() if vote else None)
        .returning(ChatRequest.id)
    )
    if (await session.execute(stmt)).scalar_one_or_none() is None:
        raise NotFoundError("chat request", request_id)
    await session.commit()


async def spent_since(session: AsyncSession, since: datetime) -> float:
    """What the requests recorded since that moment cost between them; unpriced rows add
    nothing, and a sum over none is NULL, so an empty or unmeasured ledger reads as zero."""
    stmt = select(func.sum(ChatRequest.cost_usd)).where(ChatRequest.created_at >= since)
    return (await session.execute(stmt)).scalar_one() or 0.0


async def load_thread_history(session: AsyncSession, thread_id: UUID) -> tuple[ChatTurn, ...]:
    """The thread's answered turns, oldest first, at most the turns a thread may hold:
    what a follow-up's prompts see, and how full the thread is."""
    stmt = (
        select(ChatRequest.question, ChatRequest.answer)
        .where(
            ChatRequest.thread_id == thread_id,
            ChatRequest.outcome.in_(ANSWERED_OUTCOMES),
            ChatRequest.answer.is_not(None),
        )
        .order_by(ChatRequest.created_at.desc(), ChatRequest.id.desc())
        .limit(config.CHAT_THREAD_TURNS)
    )
    rows = (await session.execute(stmt)).all()
    return tuple(
        ChatTurn(question=question, answer=strip_markers(answer))
        for question, answer in reversed(rows)
    )
