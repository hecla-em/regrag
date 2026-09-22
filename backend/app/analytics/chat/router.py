"""What the chat ledger measured over a range of days."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.analytics.chat.enums import AnalyticsDays
from app.analytics.chat.models import ChatGraphMetrics, ChatSummary, TopQuestion
from app.analytics.chat.service import (
    get_graph_metrics,
    list_top_questions,
    summarize_requests,
)
from app.core.db.session import SessionDep

router = APIRouter(prefix="/chat")


@router.get("/summary")
async def get_chat_summary(
    session: SessionDep, days: AnalyticsDays = AnalyticsDays.MONTH
) -> ChatSummary:
    return await summarize_requests(session, days)


@router.get("/graph")
async def get_chat_graph(
    session: SessionDep, days: AnalyticsDays = AnalyticsDays.MONTH
) -> ChatGraphMetrics:
    return await get_graph_metrics(session, days)


@router.get("/questions")
async def get_top_questions(
    session: SessionDep,
    days: AnalyticsDays = AnalyticsDays.MONTH,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[TopQuestion]:
    return await list_top_questions(session, days, limit)
