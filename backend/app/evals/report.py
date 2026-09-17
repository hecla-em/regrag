"""Each eval case as one line: what search found, what reached the prompt, what was cited,
what the judge made of it — and, under a case the judge failed, why. And two stored runs
side by side, metric by metric."""

from collections.abc import Sequence
from typing import Any

from app.evals.judge.enums import JudgeVerdict
from app.evals.judge.models import CaseJudgement
from app.evals.metrics import score_reference_citation_rate, score_reference_recall
from app.evals.models import EvalCaseResult, EvalMetrics
from app.evals.schemas import EvalRun

INDENT = "    "
UNMEASURED = "-"
"""Holds a figure's place when no case measured it."""


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


def _flatten_metrics(metrics: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Nested metric blocks as one level, each named by its dotted path."""
    flat: dict[str, Any] = {}
    for key, value in metrics.items():
        if isinstance(value, dict):
            flat |= _flatten_metrics(value, f"{prefix}{key}.")
        else:
            flat[f"{prefix}{key}"] = value
    return flat


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
    return f"#{run.id}  {run.created_at:%Y-%m-%d %H:%M}  {commit}  {run.model}"


def _format_rows(rows: list[tuple[str, str, str, str]]) -> list[str]:
    width = max(len(row[0]) for row in rows)
    return [
        f"{name:<{width}}  {base:>10}  {other:>10}  {delta:>8}".rstrip()
        for name, base, other, delta in rows
    ]


def format_run_comparison(base: EvalRun, other: EvalRun) -> str:
    """Each run's origin, then every metric of both with the other's delta from the base, then
    the settings the two ran with that differ. The metrics are read back through EvalMetrics,
    since JSONB keeps no key order."""
    base_metrics, other_metrics = (
        _flatten_metrics(EvalMetrics.model_validate(run.metrics).model_dump(mode="json"))
        for run in (base, other)
    )
    header = ("metric", f"#{base.id}", f"#{other.id}", "delta")
    metric_rows = [
        (
            name,
            _format_value(base_metrics.get(name)),
            _format_value(other_metrics.get(name)),
            _format_delta(base_metrics.get(name), other_metrics.get(name)),
        )
        for name in dict.fromkeys([*base_metrics, *other_metrics])
    ]
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
        setting_rows = [
            (
                name,
                _format_value(base.settings.get(name)),
                _format_value(other.settings.get(name)),
                "",
            )
            for name in differing
        ]
        blocks.append("\n".join(["settings that differ:", *_format_rows(setting_rows)]))
    return "\n\n".join(blocks)
