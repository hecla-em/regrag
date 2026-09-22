"""The chat ledger aggregated over a range of days: the headline summary, each step and the
top questions, plus the compiled graph's shape."""

from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql.functions import WithinGroup

from app.chat.cache import normalize_question
from app.chat.enums import ChatOutcome, MetricsDays
from app.chat.graph.service import chat_graph
from app.chat.metrics.models import (
    ChatGraphMetrics,
    ChatSummary,
    CostSummary,
    GraphEdge,
    LatencySummary,
    StepMetrics,
    TopQuestion,
)
from app.chat.schemas import ChatRequest, ChatRequestStep
from app.core.clock import utc_today

ANSWERED = ChatRequest.outcome == ChatOutcome.DONE
UNCACHED = ChatRequest.outcome != ChatOutcome.CACHED


def range_start(days: MetricsDays) -> datetime:
    """Midnight UTC on the range's first day, so a range of 7 is today and the six before it."""
    return datetime.combine(utc_today() - timedelta(days=days - 1), time(), tzinfo=UTC)


def percentile(fraction: float, column: QueryableAttribute[Any]) -> WithinGroup[float]:
    """The continuous percentile of a column over the group, NULLs left out."""
    return func.percentile_cont(fraction).within_group(column)


def whole_ms(value: float | None) -> int | None:
    return None if value is None else round(value)


async def summarize_requests(session: AsyncSession, days: MetricsDays) -> ChatSummary:
    outcome = ChatRequest.outcome
    range_stmt = select(
        func.count().label("requests"),
        func.count().filter(ANSWERED).label("answered"),
        func.count().filter(outcome == ChatOutcome.REFUSED).label("refused"),
        func.count().filter(outcome == ChatOutcome.ERROR).label("errors"),
        func.count().filter(outcome == ChatOutcome.CACHED).label("cached"),
        func.avg(ChatRequest.cost_usd).filter(ANSWERED).label("mean_usd"),
        func.sum(ChatRequest.cost_usd).filter(UNCACHED).label("range_usd"),
        func.avg(ChatRequest.total_ms).filter(ANSWERED).label("mean_ms"),
        percentile(0.5, ChatRequest.total_ms).filter(ANSWERED).label("p50_ms"),
        percentile(0.95, ChatRequest.total_ms).filter(ANSWERED).label("p95_ms"),
    ).where(ChatRequest.created_at >= range_start(days))
    kept_stmt = select(
        func.sum(ChatRequest.cost_usd).filter(UNCACHED).label("total_usd"),
        func.min(ChatRequest.created_at).label("kept_since"),
    )
    in_range = (await session.execute(range_stmt)).one()
    kept = (await session.execute(kept_stmt)).one()
    return ChatSummary(
        days=days,
        requests=in_range.requests,
        answered=in_range.answered,
        refused=in_range.refused,
        errors=in_range.errors,
        cached=in_range.cached,
        cache_hit_rate=in_range.cached / in_range.requests if in_range.requests else None,
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


async def list_step_metrics(session: AsyncSession, days: MetricsDays) -> list[StepMetrics]:
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
    return [
        StepMetrics(
            step=row.step,
            runs=row.runs,
            mean_ms=round(row.mean_ms),
            mean_cost_usd=row.mean_cost_usd,
        )
        for row in await session.execute(stmt)
    ]


async def get_graph_metrics(session: AsyncSession, days: MetricsDays) -> ChatGraphMetrics:
    """The graph as compiled, so the drawing cannot drift from the code, with each step's
    measures over the range."""
    drawable = chat_graph.get_graph()
    return ChatGraphMetrics(
        days=days,
        nodes=tuple(str(node) for node in drawable.nodes),
        edges=tuple(
            GraphEdge(
                source=str(edge.source), target=str(edge.target), conditional=edge.conditional
            )
            for edge in drawable.edges
        ),
        steps=tuple(await list_step_metrics(session, days)),
    )


async def list_top_questions(
    session: AsyncSession, days: MetricsDays, limit: int
) -> list[TopQuestion]:
    """The range's questions grouped as the answer cache keys them, most asked first. Grouped
    here rather than in SQL, so the grouping is normalize_question itself."""
    stmt = (
        select(ChatRequest.question, ChatRequest.outcome, ChatRequest.created_at)
        .where(ChatRequest.created_at >= range_start(days))
        .order_by(ChatRequest.created_at)
    )
    groups: dict[str, list[Any]] = defaultdict(list)
    for row in await session.execute(stmt):
        groups[normalize_question(row.question)].append(row)
    questions = [
        TopQuestion(
            question=rows[-1].question,
            asked=len(rows),
            cached=sum(row.outcome is ChatOutcome.CACHED for row in rows),
            last_asked=rows[-1].created_at,
        )
        for rows in groups.values()
    ]
    questions.sort(key=lambda question: (question.asked, question.last_asked), reverse=True)
    return questions[:limit]
