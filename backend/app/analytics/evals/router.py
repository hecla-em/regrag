"""The stored eval runs, and the settings the server runs with."""

from fastapi import APIRouter

from app.analytics.evals.models import EvalRunSummary, EvalSettings
from app.core.config import EVAL_CONFIG_SECTIONS, config, get_config_snapshot
from app.core.db.session import SessionDep
from app.evals.service import list_eval_runs

router = APIRouter(prefix="/evals")


@router.get("/runs")
async def get_eval_runs(session: SessionDep) -> list[EvalRunSummary]:
    return [EvalRunSummary.model_validate(run) for run in await list_eval_runs(session)]


@router.get("/settings")
async def get_eval_settings() -> EvalSettings:
    return EvalSettings(
        build_id=config.BUILD_ID, settings=get_config_snapshot(EVAL_CONFIG_SECTIONS)
    )
