"""Tune test factories and guards shared across the tune test modules."""

from typing import Any

from app.core.config import EVAL_CONFIG_SECTIONS, get_config_snapshot
from app.evals.metrics import compute_metrics
from app.evals.models import EvalMetrics
from app.evals.tune.models import TuneResult, TuneRun

HEALTHY = compute_metrics(()).model_dump() | {
    "counts": {"cases": 20, "in_corpus": 15, "out_of_corpus": 5, "errors": 0},
    "retrieval": {
        "raw_hit_rate": 1.0,
        "raw_recall": 0.97,
        "expanded_hit_rate": 1.0,
        "expanded_recall": 0.97,
    },
    "context": {"mean_context_chunks": 14.2, "mean_context_chars": 28100.0},
    "gate": {"refusal_rate": 1.0, "false_refusals": 0, "refused_a_found_reference": 0},
    "latency": {"mean_step_ms": {"retrieve": 412}, "mean_total_ms": 412},
}
"""A healthy retrieval-only measurement: the blocks retrieval fills, the rest unmeasured."""


def metrics(**overrides: Any) -> EvalMetrics:
    """The healthy measurement with any field overridden by name, routed to its block, so a
    test names only the figure it moves."""
    blocks = {name: dict(fields) for name, fields in HEALTHY.items()}
    for field, value in overrides.items():
        block = next(name for name, fields in blocks.items() if field in fields)
        blocks[block][field] = value
    return EvalMetrics.model_validate(blocks)


def tune_run(*results: TuneResult) -> TuneRun:
    """A run with a healthy baseline and the given varied results."""
    return TuneRun(
        dataset_sha="a" * 64,
        settings=get_config_snapshot(EVAL_CONFIG_SECTIONS),
        baseline=metrics(),
        results=results,
    )
