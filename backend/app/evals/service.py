"""Driving the golden cases through the chat graph, recording what the run measured, and
storing the run."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.graph.nodes.synthesize import synthesize
from app.chat.graph.service import chat_graph
from app.chat.models import ChatState
from app.core.clock import elapsed_ms
from app.core.config import EVAL_CONFIG_SECTIONS, get_config_snapshot
from app.core.db.crud import create_record
from app.core.exceptions import DomainError, NotFoundError
from app.core.git import read_git_commit
from app.core.llm.cache import call_cache_enabled
from app.evals.dataset.models import EvalCase, EvalDataset
from app.evals.judge.service import judge_results
from app.evals.metrics import compute_metrics
from app.evals.models import EvalCaseResult, EvalRunResult
from app.evals.schemas import EvalRun

logger = logging.getLogger(__name__)


EvalGraph = Callable[[ChatState], Awaitable[dict[str, Any]]]
"""Which set of nodes to use when evaluating an EvalCase."""


async def _full_chat_graph(state: ChatState) -> dict[str, Any]:
    return await chat_graph.ainvoke(state)


async def synthesize_graph(state: ChatState) -> dict[str, Any]:
    """Run synthesize only, with no sources, so the model answers from memory."""
    return await synthesize(state) | {"question": state.question}


async def evaluate_case(case: EvalCase, graph: EvalGraph = _full_chat_graph) -> EvalCaseResult:
    """One case driven to the state a chat request ends in — through the whole chat graph
    unless told otherwise. A case the driver raises on is recorded by name, not raised:
    the run goes on."""
    state = ChatState(question=case.question)
    start = time.perf_counter()
    try:
        state.sync_from_snapshot(await graph(state))
    except Exception as exc:
        state.record_error(exc)
        if isinstance(exc, DomainError):
            logger.warning("eval case %s failed: %s", case.id, state.error)
        else:
            logger.exception("eval case %s failed unexpectedly", case.id)
    state.total_ms = elapsed_ms(start)
    return EvalCaseResult(case=case, state=state)


async def evaluate_all_cases(
    dataset: EvalDataset,
    corpus_version: str | None = None,
    stale_cases: tuple[str, ...] = (),
    *,
    judge: bool = True,
    retrieval: bool = True,
) -> EvalRunResult:
    """Every case in the dataset, one at a time, so a per-case timing measures the case alone;
    then, unless told otherwise, the judge over the timed results.

    The corpus version and the stale cases are read before the run and carried through it, so
    a score always says which text it was measured against and which cases owe a re-review.
    Whether the run was cached is read off the live litellm cache, not a caller's word, so the
    recorded flag cannot disagree with what served the calls. With retrieval off every case
    is answered from the model's memory alone: the baseline a normal run is set beside.
    """
    graph = _full_chat_graph if retrieval else synthesize_graph
    results = [await evaluate_case(case, graph) for case in dataset.selected_cases]
    if judge:
        results = await judge_results(results)
    settings = get_config_snapshot(EVAL_CONFIG_SECTIONS)
    git_commit, git_dirty = await asyncio.to_thread(read_git_commit)
    return EvalRunResult(
        dataset_sha=dataset.sha256,
        selection=dataset.selection,
        corpus_version=corpus_version,
        git_commit=git_commit,
        git_dirty=git_dirty,
        stale_cases=stale_cases,
        cached=call_cache_enabled(),
        judged=judge,
        retrieval=retrieval,
        settings=settings,
        metrics=compute_metrics(results),
        results=tuple(results),
    )


async def create_eval_run(session: AsyncSession, result: EvalRunResult) -> EvalRun:
    """The run's setup and metrics as an eval_runs row; the per-case results are not kept."""
    run = EvalRun(
        **result.model_dump(mode="json", exclude={"results"}),
        model=result.settings["CHAT_MODEL"],
        judge_model=result.settings["EVAL_JUDGE_MODEL"] if result.judged else None,
    )
    return await create_record(session, run)


async def list_eval_runs(session: AsyncSession) -> list[EvalRun]:
    """Every stored run, newest first."""
    stmt = select(EvalRun).order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
    return list(await session.scalars(stmt))


async def get_eval_run(session: AsyncSession, run_id: int) -> EvalRun:
    stmt = select(EvalRun).where(EvalRun.id == run_id)
    run = await session.scalar(stmt)
    if run is None:
        raise NotFoundError("eval run", run_id)
    return run
