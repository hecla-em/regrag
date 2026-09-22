"""Read-only analytics for hecla-admin, behind the analytics key and out of the public
OpenAPI schema."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.analytics.enums import AnalyticsDays
from app.analytics.models import (
    ChatGraphMetrics,
    ChatSummary,
    EvalRunSummary,
    EvalSettings,
    TopQuestion,
)
from app.analytics.service import (
    get_graph_metrics,
    list_top_questions,
    summarize_requests,
)
from app.core.config import EVAL_CONFIG_SECTIONS, config, get_config_snapshot
from app.core.db.session import SessionDep
from app.core.security import verify_analytics_key
from app.evals.service import list_eval_runs

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


@router.get("/evals/runs")
async def get_eval_runs(session: SessionDep) -> list[EvalRunSummary]:
    return [EvalRunSummary.model_validate(run) for run in await list_eval_runs(session)]


@router.get("/evals/settings")
async def get_eval_settings() -> EvalSettings:
    return EvalSettings(
        build_id=config.BUILD_ID, settings=get_config_snapshot(EVAL_CONFIG_SECTIONS)
    )
