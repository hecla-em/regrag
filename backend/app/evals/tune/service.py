"""Run retrieval tuning against the golden dataset, one parameter value at a time."""

from collections.abc import Sequence
from typing import Any

from app.chat.graph.nodes.retrieve import retrieve
from app.chat.models import ChatState
from app.core.config import EVAL_CONFIG_SECTIONS, config, get_config_snapshot
from app.core.llm.cache import call_cache_enabled
from app.evals.dataset.models import EvalCase, EvalDataset
from app.evals.metrics import compute_metrics
from app.evals.models import EvalCaseResult, EvalMetrics
from app.evals.service import evaluate_case
from app.evals.tune.models import TunableParam, TuneResult, TuneRun


async def retrieve_graph(state: ChatState) -> dict[str, Any]:
    """Run retrieval only, carrying the question through the state update."""
    return await retrieve(state) | {"question": state.question}


async def _measure(cases: tuple[EvalCase, ...]) -> EvalMetrics:
    """Run the selected cases through retrieval alone and score what it found."""
    results: list[EvalCaseResult] = [
        await evaluate_case(case, graph=retrieve_graph) for case in cases
    ]
    return compute_metrics(results)


async def tune(dataset: EvalDataset, params: Sequence[TunableParam]) -> TuneRun:
    """Measure the baseline, then each parameter value independently."""
    for param in params:
        param.validate_config()

    settings = get_config_snapshot(EVAL_CONFIG_SECTIONS)
    baseline = await _measure(dataset.selected_cases)

    results: list[TuneResult] = []
    for param in params:
        for value in param.values:
            if value == getattr(config, param.name):
                continue

            with param.override(value):
                metrics = await _measure(dataset.selected_cases)

            result = TuneResult(
                param=param.name, value=value, requires=param.requires, metrics=metrics
            )
            results.append(result)

    return TuneRun(
        dataset_sha=dataset.sha256,
        selection=dataset.selection,
        cached=call_cache_enabled(),
        settings=settings,
        baseline=baseline,
        results=tuple(results),
    )
