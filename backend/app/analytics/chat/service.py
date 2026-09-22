"""The chat ledger aggregated over a range of days: the headline summary, each step and the
top questions, plus the compiled graph's shape."""

import heapq
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute, aliased
from sqlalchemy.sql.functions import WithinGroup

from app.analytics.chat.enums import AnalyticsDays
from app.analytics.chat.models import (
    ChatGraphMetrics,
    ChatSummary,
    CostSummary,
    GraphEdge,
    LatencySummary,
    StepMetrics,
    TopQuestion,
)
from app.chat.cache import normalize_question
from app.chat.enums import ChatOutcome
from app.chat.graph.service import chat_graph
from app.chat.schemas import ChatRequest, ChatRequestStep
from app.core.clock import utc_today

GENERATED = ChatRequest.outcome == ChatOutcome.DONE
"""An answer the graph produced for this request, not one replayed from the answer cache."""


def range_start(days: AnalyticsDays) -> datetime:
    """Midnight UTC on the range's first day, so a range of 7 is today and the six before it."""
    return datetime.combine(utc_today() - timedelta(days=days - 1), time(), tzinfo=UTC)


def percentile(fraction: float, column: QueryableAttribute[Any]) -> WithinGroup[float]:
    """The continuous percentile of a column over the group, NULLs left out."""
    return func.percentile_cont(fraction).within_group(column)


def whole_ms(value: float | None) -> int | None:
    return None if value is None else round(value)


async def count_outcomes(session: AsyncSession, days: AnalyticsDays) -> dict[ChatOutcome, int]:
    """The range's requests by how they ended, every outcome present."""
    stmt = (
        select(ChatRequest.outcome, func.count())
        .where(ChatRequest.created_at >= range_start(days))
        .group_by(ChatRequest.outcome)
    )
    counts = dict((await session.execute(stmt)).tuples().all())
    return {outcome: counts.get(outcome, 0) for outcome in ChatOutcome}


async def summarize_requests(session: AsyncSession, days: AnalyticsDays) -> ChatSummary:
    range_stmt = select(
        func.avg(ChatRequest.cost_usd).filter(GENERATED).label("mean_usd"),
        func.sum(ChatRequest.cost_usd).label("range_usd"),
        func.avg(ChatRequest.total_ms).filter(GENERATED).label("mean_ms"),
        percentile(0.5, ChatRequest.total_ms).filter(GENERATED).label("p50_ms"),
        percentile(0.95, ChatRequest.total_ms).filter(GENERATED).label("p95_ms"),
    ).where(ChatRequest.created_at >= range_start(days))
    kept_stmt = select(
        func.sum(ChatRequest.cost_usd).label("total_usd"),
        func.min(ChatRequest.created_at).label("kept_since"),
    )
    in_range = (await session.execute(range_stmt)).one()
    kept = (await session.execute(kept_stmt)).one()
    return ChatSummary(
        outcomes=await count_outcomes(session, days),
        cost=CostSummary(
            mean_usd=in_range.mean_usd,
            range_usd=in_range.range_usd or 0.0,
            total_usd=kept.total_usd or 0.0,
        ),
        latency=LatencySummary(
            mean_ms=whole_ms(in_range.mean_ms),
            p50_ms=whole_ms(in_range.p50_ms),
            p95_ms=whole_ms(in_range.p95_ms),
        ),
        kept_since=kept.kept_since,
    )


async def list_step_metrics(session: AsyncSession, days: AnalyticsDays) -> tuple[StepMetrics, ...]:
    stmt = (
        select(
            ChatRequestStep.step,
            func.count().label("runs"),
            func.avg(ChatRequestStep.ms).label("mean_ms"),
            func.avg(ChatRequestStep.cost_usd).label("mean_cost_usd"),
        )
        .join(ChatRequest)
        .where(ChatRequest.created_at >= range_start(days))
        .group_by(ChatRequestStep.step)
        .order_by(ChatRequestStep.step)
    )
    return tuple(
        StepMetrics(
            step=row.step,
            runs=row.runs,
            mean_ms=round(row.mean_ms),
            mean_cost_usd=row.mean_cost_usd,
        )
        for row in await session.execute(stmt)
    )


async def get_graph_metrics(session: AsyncSession, days: AnalyticsDays) -> ChatGraphMetrics:
    """The graph as compiled, so the drawing cannot drift from the code, with each step's
    measures over the range."""
    drawable = chat_graph.get_graph()
    return ChatGraphMetrics(
        nodes=tuple(drawable.nodes),
        edges=tuple(
            GraphEdge(source=edge.source, target=edge.target, conditional=edge.conditional)
            for edge in drawable.edges
        ),
        steps=await list_step_metrics(session, days),
    )


async def list_top_questions(
    session: AsyncSession, days: AnalyticsDays, limit: int
) -> list[TopQuestion]:
    """The range's first questions, grouped by normalize_question as the answer cache folds
    them, most asked first. A follow-up is left out, since it means nothing outside its thread."""
    earlier = aliased(ChatRequest)
    continues_thread = (
        select(earlier.id)
        .where(earlier.thread_id == ChatRequest.thread_id, earlier.id < ChatRequest.id)
        .exists()
    )
    stmt = (
        select(ChatRequest.question, ChatRequest.outcome, ChatRequest.created_at)
        .where(ChatRequest.created_at >= range_start(days), ~continues_thread)
        .order_by(ChatRequest.created_at)
    )
    questions: dict[str, TopQuestion] = {}
    for row in await session.execute(stmt):
        key = normalize_question(row.question)
        seen = questions.get(key)
        questions[key] = TopQuestion(
            question=row.question,
            asked=(seen.asked if seen else 0) + 1,
            cached=(seen.cached if seen else 0) + (row.outcome is ChatOutcome.CACHED),
            last_asked=row.created_at,
        )
    return heapq.nlargest(limit, questions.values(), key=lambda q: (q.asked, q.last_asked))
