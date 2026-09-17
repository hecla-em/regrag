"""Each eval case as one line: what search found, what reached the prompt, what was cited,
what the judge made of it — and, under a case the judge failed, why. And two stored runs
side by side, metric by metric."""

from collections.abc import Iterable, Sequence
from typing import Any, cast

from pydantic import BaseModel

from app.core.mappings import flatten_dict
from app.evals.judge.enums import JudgeVerdict
from app.evals.judge.models import CaseJudgement
from app.evals.metrics import score_reference_citation_rate, score_reference_recall
from app.evals.models import EvalCaseResult, EvalMetrics
from app.evals.schemas import EvalRun

INDENT = "    "
UNMEASURED = "-"
"""Holds a figure's place when no case measured it."""

METRIC_FIELDS = [
    f"{block}.{field}"
    for block, info in EvalMetrics.model_fields.items()
    for field in cast(type[BaseModel], info.annotation).model_fields
]
"""Every metric block and field, in the order EvalMetrics declares them."""


def format_rate(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else UNMEASURED


def _format_case_line(result: EvalCaseResult, width: int) -> str:
    """One case on one line: what search found, what reached the prompt, what the answer
    cited of the references the case authors, what the judge scored, then how the run ended."""
    state, references, judgement = result.state, result.case.references, result.judgement
    scored = state.error is None
    recalled = scored and bool(references)
    raw = score_reference_recall(references, state.hits) if recalled else None
    expanded = score_reference_recall(references, state.sources) if recalled else None
    cited = (
        score_reference_citation_rate(state.answer, state.sources, references) if scored else None
    )
    correctness = judgement.correctness.score() if judgement and judgement.correctness else None
    faithfulness = judgement.faithfulness.score() if judgement and judgement.faithfulness else None
    return (
        f"{result.case.id:<{width}}  raw {format_rate(raw):>4}  exp {format_rate(expanded):>4}  "
        f"cite {format_rate(cited):>4}  corr {format_rate(correctness):>4}  "
        f"faith {format_rate(faithfulness):>4}  {state.outcome.value:<8}{state.total_ms or 0:>6}ms"
        f"{'  ' + state.error if state.error else ''}"
    )


def _format_critiques(judgement: CaseJudgement) -> list[str]:
    """The judge's reasons, for the dimensions it did not pass: a pass stays on the case
    line, so the report reads as one line per case until something needs reading."""
    lines = []
    correctness, faithfulness, refusal = (
        judgement.correctness,
        judgement.faithfulness,
        judgement.refusal,
    )
    if correctness and correctness.verdict is not JudgeVerdict.PASS:
        failure = f" ({correctness.failure.value})" if correctness.failure else ""
        lines.append(f"correctness {correctness.verdict.value}{failure}: {correctness.critique}")
    if faithfulness and (unsupported := faithfulness.unsupported_claims()):
        lines.append(f"faithfulness {format_rate(faithfulness.score())}: {faithfulness.critique}")
        lines.extend(f"unsupported: {claim}" for claim in unsupported)
    if refusal and refusal.verdict is not JudgeVerdict.PASS:
        lines.append(f"refusal {refusal.verdict.value}: {refusal.critique}")
    return [INDENT + line for line in lines]


def format_case_lines(results: Sequence[EvalCaseResult]) -> list[str]:
    """Every case as its own line, the id column sized to the longest id in the run, with
    the queries decompose split it into, assess's words for a refusal it asked for, and the
    judge's critiques under any case it did not pass. A case that raised scores nothing, as the
    aggregate leaves it out; one authoring no reference has no recall to measure, and prints
    a dash rather than a zero."""
    if not results:
        return []
    width = max(len(result.case.id) for result in results)
    lines = []
    for result in results:
        lines.append(_format_case_line(result, width))
        if result.state.queries:
            lines.append(INDENT + "split: " + " | ".join(result.state.queries))
        if result.state.refusal is not None and result.state.refusal.explanation:
            lines.append(INDENT + "refused: " + result.state.refusal.explanation)
        if result.judgement is not None:
            lines.extend(_format_critiques(result.judgement))
    return lines


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _format_value(value: Any) -> str:
    if value is None:
        return UNMEASURED
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _format_delta(base: Any, other: Any) -> str:
    """How far the other run moved from the base, blank where either side is not a number."""
    if not (_is_number(base) and _is_number(other)):
        return ""
    delta = other - base
    return f"{delta:+.3f}" if isinstance(delta, float) else f"{delta:+d}"


def _format_run_header(run: EvalRun) -> str:
    commit = (run.git_commit or UNMEASURED)[:7] + (" (dirty)" if run.git_dirty else "")
    retrieval = "" if run.retrieval else "  no retrieval"
    return f"#{run.id}  {run.created_at:%Y-%m-%d %H:%M}  {commit}  {run.model}{retrieval}"


def _format_rows(rows: list[tuple[str, str, str, str]]) -> list[str]:
    width = max(len(row[0]) for row in rows)
    return [
        f"{name:<{width}}  {base:>10}  {other:>10}  {delta:>8}".rstrip()
        for name, base, other, delta in rows
    ]


def _comparison_rows(
    names: Iterable[str], base: dict[str, Any], other: dict[str, Any], *, with_delta: bool
) -> list[tuple[str, str, str, str]]:
    return [
        (
            name,
            _format_value(base.get(name)),
            _format_value(other.get(name)),
            _format_delta(base.get(name), other.get(name)) if with_delta else "",
        )
        for name in names
    ]


def _metric_rank(name: str) -> int:
    """A flattened metric's place in EvalMetrics, since JSONB keeps no key order; a metric the
    model no longer has sorts last, so runs stored before a change still compare."""
    block_field = ".".join(name.split(".")[:2])
    return METRIC_FIELDS.index(block_field) if block_field in METRIC_FIELDS else len(METRIC_FIELDS)


def format_run_comparison(base: EvalRun, other: EvalRun) -> str:
    """Each run's origin, every metric of both with the other's delta, then differing settings."""
    base_metrics, other_metrics = flatten_dict(base.metrics), flatten_dict(other.metrics)
    metric_names = sorted(dict.fromkeys([*base_metrics, *other_metrics]), key=_metric_rank)
    header = ("metric", f"#{base.id}", f"#{other.id}", "delta")
    metric_rows = _comparison_rows(metric_names, base_metrics, other_metrics, with_delta=True)
    blocks = [
        "\n".join([_format_run_header(base), _format_run_header(other)]),
        "\n".join(_format_rows([header, *metric_rows])),
    ]
    differing = sorted(
        name
        for name in base.settings.keys() | other.settings.keys()
        if base.settings.get(name) != other.settings.get(name)
    )
    if differing:
        setting_rows = _comparison_rows(differing, base.settings, other.settings, with_delta=False)
        blocks.append("\n".join(["settings that differ:", *_format_rows(setting_rows)]))
    return "\n\n".join(blocks)
