"""Eval scoring: what counts as a retrieved reference and a grounded citation, per case;
and the run's measures, each a plain function over its results."""

from collections.abc import Sequence

from app.chat.citations import find_cited_markers, find_cited_sources
from app.chat.enums import ChatOutcome, RefusalReason
from app.core.llm.models import Usage
from app.evals.dataset.enums import EvalKind
from app.evals.judge.models import CaseJudgement
from app.evals.models import (
    AssessMetrics,
    CaseCounts,
    CitationMetrics,
    ContextMetrics,
    EvalCaseResult,
    EvalMetrics,
    GateMetrics,
    JudgeMetrics,
    LatencyMetrics,
    RetrievalMetrics,
)
from app.retrieval.models import ReferenceTarget, RetrievedChunk


def _division(item: ReferenceTarget | RetrievedChunk) -> tuple[str, str | None, str | None]:
    """The act and division a reference names: article case-folded, annex verbatim, and
    "" an unnumbered annex rather than none. Coarser than `follow`, which also matches the
    paragraph: a case names the article that answers it, so any chunk of that article
    counts as having found the reference."""
    article = item.article.lower() if item.article is not None else None
    return item.celex, article, item.annex


def score_reference_recall(
    targets: Sequence[ReferenceTarget], chunks: Sequence[RetrievedChunk]
) -> float:
    """Share of a case's authored references some retrieved chunk covers."""
    if not targets:
        return 0.0
    retrieved = {_division(chunk) for chunk in chunks}
    return sum(_division(target) in retrieved for target in targets) / len(targets)


def score_citation_validity(answer: str, sources: Sequence[RetrievedChunk]) -> float | None:
    """Share of the answer's markers addressing a block it was given; None when it cited
    nothing, which is unmeasured rather than zero."""
    markers = find_cited_markers(answer)
    if not markers:
        return None
    return len(find_cited_sources(answer, sources)) / len(markers)


def score_reference_citation_rate(
    answer: str,
    sources: Sequence[RetrievedChunk],
    targets: Sequence[ReferenceTarget],
) -> float | None:
    """Share of a case's authored references the answer cited, scored over the references
    so an extra citation is not an error; None when the case names none."""
    if not targets:
        return None
    cited = {_division(source) for _, source in find_cited_sources(answer, sources)}
    return sum(_division(target) in cited for target in targets) / len(targets)


# Run metrics: each a plain function over the run's results, scoring the cases it applies to


def mean_or_none(values: Sequence[float | bool]) -> float | None:
    """The mean, or None when there is nothing to average — unmeasured, not zero."""
    return sum(values) / len(values) if values else None


def _scored(results: Sequence[EvalCaseResult]) -> list[EvalCaseResult]:
    """The cases that completed; one the graph raised on is counted but not scored."""
    return [r for r in results if r.state.error is None]


def scored_in_corpus(results: Sequence[EvalCaseResult]) -> list[EvalCaseResult]:
    return [r for r in _scored(results) if r.case.kind is EvalKind.IN_CORPUS]


def scored_out_of_corpus(results: Sequence[EvalCaseResult]) -> list[EvalCaseResult]:
    return [r for r in _scored(results) if r.case.kind is EvalKind.OUT_OF_CORPUS]


# Counts: the run's shape


def count_errors(results: Sequence[EvalCaseResult]) -> int:
    return len(results) - len(_scored(results))


def count_cases_of_kind(results: Sequence[EvalCaseResult], kind: EvalKind) -> int:
    """Cases of this kind the run covered, errored or not: the dataset's shape, which a
    case the graph raised on does not change."""
    return sum(result.case.kind is kind for result in results)


def compute_case_counts(results: Sequence[EvalCaseResult]) -> CaseCounts:
    return CaseCounts(
        cases=len(results),
        in_corpus=count_cases_of_kind(results, EvalKind.IN_CORPUS),
        out_of_corpus=count_cases_of_kind(results, EvalKind.OUT_OF_CORPUS),
        errors=count_errors(results),
    )


# Retrieval: what search found, raw and expanded


def _raw_recall(result: EvalCaseResult) -> float:
    return score_reference_recall(result.case.references, result.state.hits)


def _expanded_recall(result: EvalCaseResult) -> float:
    return score_reference_recall(result.case.references, result.state.sources)


def compute_raw_hit_rate(results: Sequence[EvalCaseResult]) -> float | None:
    """Share of in-corpus cases where search found at least one authored reference."""
    return mean_or_none([_raw_recall(r) > 0 for r in scored_in_corpus(results)])


def compute_raw_recall(results: Sequence[EvalCaseResult]) -> float | None:
    """Mean share of authored references search found, before expansion widened it."""
    return mean_or_none([_raw_recall(r) for r in scored_in_corpus(results)])


def compute_expanded_hit_rate(results: Sequence[EvalCaseResult]) -> float | None:
    """Share of in-corpus cases where at least one authored reference reached the prompt."""
    return mean_or_none([_expanded_recall(r) > 0 for r in scored_in_corpus(results)])


def compute_expanded_recall(results: Sequence[EvalCaseResult]) -> float | None:
    """Mean share of authored references that reached the prompt."""
    return mean_or_none([_expanded_recall(r) for r in scored_in_corpus(results)])


def compute_retrieval_metrics(results: Sequence[EvalCaseResult]) -> RetrievalMetrics:
    return RetrievalMetrics(
        raw_hit_rate=compute_raw_hit_rate(results),
        raw_recall=compute_raw_recall(results),
        expanded_hit_rate=compute_expanded_hit_rate(results),
        expanded_recall=compute_expanded_recall(results),
    )


# Context: what reached the prompt, and what it cost


def compute_mean_context_chunks(results: Sequence[EvalCaseResult]) -> float | None:
    """Mean context blocks per scored in-corpus case."""
    return mean_or_none([float(len(r.state.sources)) for r in scored_in_corpus(results)])


def compute_mean_context_chars(results: Sequence[EvalCaseResult]) -> float | None:
    """Mean context text length per scored in-corpus case."""
    return mean_or_none(
        [float(sum(len(c.text) for c in r.state.sources)) for r in scored_in_corpus(results)]
    )


def compute_context_metrics(results: Sequence[EvalCaseResult]) -> ContextMetrics:
    return ContextMetrics(
        mean_context_chunks=compute_mean_context_chunks(results),
        mean_context_chars=compute_mean_context_chars(results),
    )


# Gate: the pre-model routing decision


def _refused_for(result: EvalCaseResult, reason: RefusalReason) -> bool:
    """Whether the run recorded a refusal, and this is the one it recorded."""
    return result.state.refusal is not None and result.state.refusal.reason is reason


def _gate_refused(result: EvalCaseResult) -> bool:
    """A refusal before any model call, as the run recorded it. A retrieval-only run stops
    before the graph routes, so it refused nothing and is read for what the gate left."""
    if result.state.outcome is ChatOutcome.ABORTED:
        return not result.state.sources
    return _refused_for(result, RefusalReason.NOTHING_RETRIEVED)


def _assess_refused(result: EvalCaseResult) -> bool:
    """A refusal assess asked for, once the gate had passed."""
    return _refused_for(result, RefusalReason.INSUFFICIENT_CONTEXT)


def compute_gate_refusal_rate(results: Sequence[EvalCaseResult]) -> float | None:
    """Share of out-of-corpus cases the pre-model gate refused."""
    return mean_or_none([_gate_refused(r) for r in scored_out_of_corpus(results)])


def count_false_refusals(results: Sequence[EvalCaseResult]) -> int:
    """In-corpus cases the gate refused."""
    return sum(_gate_refused(r) for r in scored_in_corpus(results))


def count_refusals_of_a_found_reference(results: Sequence[EvalCaseResult]) -> int:
    """In-corpus cases refused though search had found an authored reference: the gate too
    tight, rather than a corpus that does not cover the question."""
    return sum(_gate_refused(r) and _raw_recall(r) > 0 for r in scored_in_corpus(results))


def compute_gate_metrics(results: Sequence[EvalCaseResult]) -> GateMetrics:
    return GateMetrics(
        refusal_rate=compute_gate_refusal_rate(results),
        false_refusals=count_false_refusals(results),
        refused_a_found_reference=count_refusals_of_a_found_reference(results),
    )


# Assess: the loop's refusal, after the gate passed


def compute_assess_refusal_rate(results: Sequence[EvalCaseResult]) -> float | None:
    """Share of out-of-corpus cases assess refused."""
    return mean_or_none([_assess_refused(r) for r in scored_out_of_corpus(results)])


def count_assess_false_refusals(results: Sequence[EvalCaseResult]) -> int:
    """In-corpus cases assess refused."""
    return sum(_assess_refused(r) for r in scored_in_corpus(results))


def compute_assess_metrics(results: Sequence[EvalCaseResult]) -> AssessMetrics:
    return AssessMetrics(
        refusal_rate=compute_assess_refusal_rate(results),
        false_refusals=count_assess_false_refusals(results),
    )


# Citations: what the answers cited


def _answered_in_corpus(results: Sequence[EvalCaseResult]) -> list[EvalCaseResult]:
    """The in-corpus cases the model answered: a refused or retrieval-only case wrote no
    answer, so it has nothing to cite with and is unmeasured rather than zero."""
    return [r for r in scored_in_corpus(results) if r.state.outcome is ChatOutcome.DONE]


def compute_cited_references(results: Sequence[EvalCaseResult]) -> float | None:
    """Mean share of authored references the answers cited, over the answered in-corpus cases."""
    rates = [
        score_reference_citation_rate(r.state.answer, r.state.sources, r.case.references)
        for r in _answered_in_corpus(results)
    ]
    return mean_or_none([rate for rate in rates if rate is not None])


def compute_markers_in_context(results: Sequence[EvalCaseResult]) -> float | None:
    """Mean share of markers addressing a block that was in context, over the answers
    that cited anything."""
    validities = [
        score_citation_validity(r.state.answer, r.state.sources) for r in _scored(results)
    ]
    return mean_or_none([v for v in validities if v is not None])


def compute_citation_metrics(results: Sequence[EvalCaseResult]) -> CitationMetrics:
    return CitationMetrics(
        cited_references=compute_cited_references(results),
        markers_in_context=compute_markers_in_context(results),
    )


# Judge: the judge's dimensions over the cases it returned a verdict on


def _judgements(results: Sequence[EvalCaseResult]) -> list[CaseJudgement]:
    """The verdicts of the scored cases the judge came back on."""
    return [r.judgement for r in _scored(results) if r.judgement is not None and r.judgement.judged]


def count_judged(results: Sequence[EvalCaseResult]) -> int:
    return len(_judgements(results))


def compute_correctness(results: Sequence[EvalCaseResult]) -> float | None:
    """Share of judged in-corpus answers the judge passed against the reference answer."""
    scores = [j.correctness.score() for j in _judgements(results) if j.correctness is not None]
    return mean_or_none([s for s in scores if s is not None])


def compute_faithfulness(results: Sequence[EvalCaseResult]) -> float | None:
    """Mean share of an answer's claims its cited context backs, over the judged answers
    that made a checkable claim."""
    scores = [j.faithfulness.score() for j in _judgements(results) if j.faithfulness is not None]
    return mean_or_none([s for s in scores if s is not None])


def compute_model_refusal_rate(results: Sequence[EvalCaseResult]) -> float | None:
    """Share of judged out-of-corpus answers that declined in the model's own words."""
    scores = [j.refusal.score() for j in _judgements(results) if j.refusal is not None]
    return mean_or_none([s for s in scores if s is not None])


def compute_judge_metrics(results: Sequence[EvalCaseResult]) -> JudgeMetrics:
    return JudgeMetrics(
        judged=count_judged(results),
        correctness=compute_correctness(results),
        faithfulness=compute_faithfulness(results),
        refusal_rate=compute_model_refusal_rate(results),
    )


# Latency


def compute_mean_step_ms(results: Sequence[EvalCaseResult]) -> dict[str, int]:
    """Each step's mean time over the cases that ran it, in the order steps first appear."""
    timings: dict[str, list[int]] = {}
    for result in _scored(results):
        for step in result.state.steps:
            timings.setdefault(step.step.value, []).append(step.ms)
    return {name: sum(ms) // len(ms) for name, ms in timings.items()}


def compute_mean_total_ms(results: Sequence[EvalCaseResult]) -> int:
    return int(mean_or_none([r.state.total_ms or 0 for r in _scored(results)]) or 0)


def compute_latency_metrics(results: Sequence[EvalCaseResult]) -> LatencyMetrics:
    return LatencyMetrics(
        mean_step_ms=compute_mean_step_ms(results),
        mean_total_ms=compute_mean_total_ms(results),
    )


# Usage


def compute_usage(results: Sequence[EvalCaseResult]) -> Usage:
    """Tokens and cost summed over the run; zero, not unmeasured, when no case called a model."""
    reported = Usage.sum_reported(r.state.usage() for r in _scored(results))
    return reported or Usage(input_tokens=0, output_tokens=0, cost_usd=0.0)


# The run


def compute_metrics(results: Sequence[EvalCaseResult]) -> EvalMetrics:
    """Every measure of the run, block by block."""
    return EvalMetrics(
        counts=compute_case_counts(results),
        retrieval=compute_retrieval_metrics(results),
        context=compute_context_metrics(results),
        gate=compute_gate_metrics(results),
        assess=compute_assess_metrics(results),
        citations=compute_citation_metrics(results),
        judge=compute_judge_metrics(results),
        latency=compute_latency_metrics(results),
        usage=compute_usage(results),
    )
