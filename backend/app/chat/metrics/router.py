"""The chat ledger's metrics for hecla-admin, behind the metrics key and out of the public
OpenAPI schema."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.chat.enums import MetricsDays
from app.chat.metrics.models import (
    ChatGraphMetrics,
    ChatSummary,
    TopQuestion,
)
from app.chat.metrics.service import (
    get_graph_metrics,
    list_top_questions,
    summarize_requests,
)
from app.core.db.session import SessionDep
from app.core.security import verify_metrics_key

router = APIRouter(
    prefix="/admin/chat",
    tags=["admin"],
    dependencies=[Depends(verify_metrics_key)],
    include_in_schema=False,
)


@router.get("/summary")
async def get_chat_summary(
    session: SessionDep, days: MetricsDays = MetricsDays.MONTH
) -> ChatSummary:
    return await summarize_requests(session, days)


@router.get("/graph")
async def get_chat_graph(
    session: SessionDep, days: MetricsDays = MetricsDays.MONTH
) -> ChatGraphMetrics:
    return await get_graph_metrics(session, days)


@router.get("/questions")
async def get_top_questions(
    session: SessionDep,
    days: MetricsDays = MetricsDays.MONTH,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[TopQuestion]:
    return await list_top_questions(session, days, limit)
