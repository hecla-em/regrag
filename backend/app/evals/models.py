"""Eval run values: one scored case, and what a whole run measured."""

from typing import Any

from app.chat.enums import ChatOutcome
from app.chat.models import ChatState
from app.core.llm.models import Usage
from app.core.models import FrozenModel
from app.evals.dataset.models import CaseSelection, EvalCase
from app.evals.judge.models import CaseJudgement


class EvalCaseResult(FrozenModel):
    """One case driven through the chat graph: the case, and the run it produced — the
    same state a chat request ends in, so a run is scored off what production records."""

    case: EvalCase
    state: ChatState
    judgement: CaseJudgement | None = None


class CaseCounts(FrozenModel):
    """The run's shape: how its cases were authored, and how many the graph raised on.
    An errored case still counts toward its kind, so errors overlaps the kinds."""

    cases: int
    in_corpus: int
    out_of_corpus: int
    errors: int


class RetrievalMetrics(FrozenModel):
    """What search found, over the in-corpus cases. raw_*: what search returned;
    expanded_*: what reached the prompt. None when no case measured it."""

    raw_hit_rate: float | None
    raw_recall: float | None
    expanded_hit_rate: float | None
    expanded_recall: float | None


class ContextMetrics(FrozenModel):
    """What the prompt carried, per scored in-corpus case: the text recall is bought with."""

    mean_context_chunks: float | None
    mean_context_chars: float | None


class GateMetrics(FrozenModel):
    """The pre-model gate's routing. refusal_rate: out-of-corpus cases it refused.
    false_refusals: in-corpus cases it refused; refused_a_found_reference: those where
    search had already found an authored reference — the gate too tight."""

    refusal_rate: float | None
    false_refusals: int
    refused_a_found_reference: int


class AssessMetrics(FrozenModel):
    """The loop's refusal, once the gate has passed. refusal_rate: out-of-corpus cases assess
    refused; false_refusals: in-corpus cases it refused — a question the corpus answers,
    read as one it does not."""

    refusal_rate: float | None
    false_refusals: int


class CitationMetrics(FrozenModel):
    """What the answers cited. cited_references: share of authored references cited;
    markers_in_context: share of [n] markers addressing a block that was in context."""

    cited_references: float | None
    markers_in_context: float | None


class JudgeMetrics(FrozenModel):
    """The judge's three dimensions over the cases it returned a verdict on. judged says how
    many, so a run with the judge off reads as unmeasured rather than perfect. refusal_rate:
    out-of-corpus cases that passed the gate and declined in the model's own words."""

    judged: int
    correctness: float | None
    faithfulness: float | None
    refusal_rate: float | None


class LatencyMetrics(FrozenModel):
    """mean_step_ms: each step's mean over the cases that ran it."""

    mean_step_ms: dict[str, int]
    mean_total_ms: int


class EvalMetrics(FrozenModel):
    """Every measure of a run, in blocks. A retrieval-only run leaves the blocks past the
    model call unmeasured: None rates, zero counts."""

    counts: CaseCounts
    retrieval: RetrievalMetrics
    context: ContextMetrics
    gate: GateMetrics
    assess: AssessMetrics
    citations: CitationMetrics
    judge: JudgeMetrics
    latency: LatencyMetrics
    usage: Usage


class EvalRunResult(FrozenModel):
    """One eval run: which dataset and settings it scored, what it measured, and every case.

    dataset_sha hashes what the cases assert; selection names the subset actually scored.
    corpus_version names the ingest the corpus stands at, so two scores are only compared
    when they were measured against the same text; git_commit and git_dirty name the code it
    ran, and whether that code had uncommitted edits; stale_cases names the cases whose cited
    text has moved since they were authored, whose reference answers are owed a re-review.
    cached says the run had the call cache on, so an embed or rerank timing may measure a
    disk read rather than the provider — a cached run is not a latency baseline. judged says
    the judge was on, so a run reading judged: 0 with it on is a judge that never answered,
    not a run that did not ask. retrieval off is the memory baseline: the model answered
    every case with no context, so its retrieval and citation scores are zero by construction.
    """

    dataset_sha: str
    selection: CaseSelection = CaseSelection()
    corpus_version: str | None = None
    git_commit: str | None = None
    git_dirty: bool = False
    stale_cases: tuple[str, ...] = ()
    cached: bool = False
    judged: bool = False
    retrieval: bool = True
    settings: dict[str, Any]
    metrics: EvalMetrics
    results: tuple[EvalCaseResult, ...]

    @property
    def judge_never_answered(self) -> bool:
        """The judge was on and some case was answered, yet no verdict came back: every
        judge call failed, which a misnamed judge model does silently."""
        answered = any(r.state.outcome is ChatOutcome.DONE for r in self.results)
        return self.judged and answered and self.metrics.judge.judged == 0

    def summary(self) -> str:
        """The run's setup and scores as JSON, then any case owed a re-review, then any case
        the graph raised on, then a judge that never answered. A stale case is reported,
        never failed: only a human can repair one, so the run stays green and says what
        needs reading."""
        blocks = [
            self.model_dump_json(
                indent=2,
                include={
                    "dataset_sha",
                    "selection",
                    "corpus_version",
                    "git_commit",
                    "git_dirty",
                    "cached",
                    "judged",
                    "retrieval",
                    "settings",
                    "metrics",
                },
            )
        ]
        if self.stale_cases:
            count = len(self.stale_cases)
            subject = "case cites" if count == 1 else "cases cite"
            blocks.append(
                f"{count} {subject} text that changed since authoring:\n"
                + "\n".join(f"  {case_id}" for case_id in self.stale_cases)
            )
        errored = [f"  {r.case.id}  {r.state.error}" for r in self.results if r.state.error]
        if errored:
            blocks.append("\n".join(["errored:", *errored]))
        if self.judge_never_answered:
            blocks.append(
                "the judge returned no verdict on any answered case: check EVAL_JUDGE_MODEL "
                "and the warnings above"
            )
        return "\n\n".join(blocks)
