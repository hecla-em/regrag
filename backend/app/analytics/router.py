"""Read-only analytics for hecla-admin, behind the analytics key and out of the public
OpenAPI schema."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.analytics.enums import AnalyticsDays
from app.analytics.models import (
    ChatGraphMetrics,
    ChatSummary,
    TopQuestion,
)
from app.analytics.service import (
    get_graph_metrics,
    list_top_questions,
    summarize_requests,
)
from app.core.db.session import SessionDep
from app.core.security import verify_analytics_key

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(verify_analytics_key)],
    include_in_schema=False,
)


@router.get("/chat/summary")
async def get_chat_summary(
    session: SessionDep, days: AnalyticsDays = AnalyticsDays.MONTH
) -> ChatSummary:
    return await summarize_requests(session, days)


@router.get("/chat/graph")
async def get_chat_graph(
    session: SessionDep, days: AnalyticsDays = AnalyticsDays.MONTH
) -> ChatGraphMetrics:
    return await get_graph_metrics(session, days)


@router.get("/chat/questions")
async def get_top_questions(
    session: SessionDep,
    days: AnalyticsDays = AnalyticsDays.MONTH,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[TopQuestion]:
    return await list_top_questions(session, days, limit)
