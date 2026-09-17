"""Eval test factories shared across the eval test modules."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.chat.enums import ChatNode, RefusalReason, ToolStep
from app.chat.graph.nodes.refuse import REFUSAL_ANSWER
from app.chat.models import ChatState, ChatStepResult, Refusal
from app.core.config import EVAL_CONFIG_SECTIONS, config, get_config_snapshot
from app.evals.dataset.enums import EvalKind
from app.evals.dataset.models import CaseReference, CaseSelection, EvalCase, EvalDataset
from app.evals.judge.enums import CorrectnessFailure, JudgeVerdict
from app.evals.judge.models import (
    CaseJudgement,
    ClaimVerdict,
    CorrectnessVerdict,
    FaithfulnessVerdict,
    RefusalVerdict,
)
from app.evals.metrics import compute_metrics
from app.evals.models import EvalMetrics, EvalResult, EvalRun
from app.evals.schemas import EvalRunRecord
from tests.conftest import REPORTED_USAGE, retrieved_chunk, search_result

REFERENCE = CaseReference(celex="32023R1805", article="4")


@pytest.fixture(autouse=True)
def no_assess_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eval tests fake the chat model, not assess — the loop stays off here; its
    coverage lives in tests/chat."""
    monkeypatch.setattr(config, "ASSESS_ENABLED", False)


@pytest.fixture(autouse=True)
def no_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    """The judge is a paid model call, faked in tests/evals/judge; here the judging pass
    hands the results back unjudged, so a run's judged metrics read as unmeasured unless a
    test says otherwise."""

    async def unjudged(results):
        return list(results)

    monkeypatch.setattr("app.evals.service.judge_results", unjudged)


IN_CORPUS_CASE: dict[str, Any] = {
    "id": "case",
    "kind": EvalKind.IN_CORPUS,
    "question": "q?",
    "answer": "a",
    "references": (REFERENCE,),
}


def eval_case(**overrides: Any) -> EvalCase:
    """An in-corpus case with sane defaults, overridable per field."""
    return EvalCase(**{**IN_CORPUS_CASE, **overrides})


def out_of_corpus_case(id: str = "ooc") -> EvalCase:
    return EvalCase(id=id, kind=EvalKind.OUT_OF_CORPUS, question="q?")


def eval_dataset(*cases: EvalCase, **selection: Any) -> EvalDataset:
    """A dataset of the given cases, selecting on the CaseSelection criteria passed."""
    return EvalDataset(cases=cases, selection=CaseSelection(**selection))


def eval_result(
    case: EvalCase | None = None, judgement: CaseJudgement | None = None, **state: Any
) -> EvalResult:
    """A completed in-corpus case whose answer cites its one authored reference, with the
    state's fields overridable — nodes, hits, sources, answer, error."""
    defaults: dict[str, Any] = {
        "question": "q?",
        "steps": (
            ChatStepResult(step=ChatNode.RETRIEVE, ms=100),
            ChatStepResult(step=ChatNode.SYNTHESIZE, ms=900, usage=REPORTED_USAGE),
        ),
        "hits": (search_result(),),
        "sources": (retrieved_chunk(),),
        "answer": "Yes [1].",
        "total_ms": 1000,
    }
    return EvalResult(
        case=case or eval_case(), state=ChatState(**{**defaults, **state}), judgement=judgement
    )


def passed_judgement() -> CaseJudgement:
    """A judged in-corpus answer that matched the reference and stayed on its context."""
    return CaseJudgement(
        correctness=CorrectnessVerdict(critique="states the half rule", verdict=JudgeVerdict.PASS),
        faithfulness=FaithfulnessVerdict(
            critique="every claim is in [1]",
            claims=(ClaimVerdict(claim="half the energy counts", supported=True),),
        ),
    )


def failed_judgement() -> CaseJudgement:
    """A judged in-corpus answer with the wrong figure and one claim its context lacks."""
    return CaseJudgement(
        correctness=CorrectnessVerdict(
            critique="says all of it, the reference says half",
            verdict=JudgeVerdict.FAIL,
            failure=CorrectnessFailure.WRONG_FIGURE,
        ),
        faithfulness=FaithfulnessVerdict(
            critique="the 5,000 GT threshold is not in the cited block",
            claims=(
                ClaimVerdict(claim="all the energy counts", supported=True),
                ClaimVerdict(claim="ships above 5,000 GT", supported=False),
            ),
        ),
    )


def refusal_judgement(verdict: JudgeVerdict = JudgeVerdict.PASS) -> CaseJudgement:
    """A judged out-of-corpus answer: declined, or answered from memory."""
    return CaseJudgement(
        refusal=RefusalVerdict(critique="says the corpus lacks it", verdict=verdict)
    )


REFUSED_PATH = (
    ChatStepResult(step=ChatNode.RETRIEVE, ms=80),
    ChatStepResult(step=ChatNode.REFUSE, ms=0),
)
"""The path a gate refusal leaves: retrieve ran, then refuse, and no model call."""


def refused_result(case: EvalCase | None = None, **state: Any) -> EvalResult:
    """A case the gate refused: the refusal path, no sources, the fixed answer."""
    defaults: dict[str, Any] = {
        "steps": REFUSED_PATH,
        "hits": (),
        "sources": (),
        "refusal": Refusal(reason=RefusalReason.NOTHING_RETRIEVED),
        "answer": REFUSAL_ANSWER,
        "total_ms": 85,
    }
    return EvalResult(
        case=case or out_of_corpus_case(), state=ChatState(question="q?", **{**defaults, **state})
    )


ASSESS_REFUSED_PATH = (
    ChatStepResult(step=ChatNode.RETRIEVE, ms=80),
    ChatStepResult(step=ChatNode.ASSESS, ms=900, usage=REPORTED_USAGE),
    ChatStepResult(step=ToolStep.REFUSE, ms=0),
    ChatStepResult(step=ChatNode.REFUSE, ms=0),
)
"""The path assess's refusal leaves: the gate passed, assess read the context and found it
insufficient, and the graph refused."""


def assess_refused_result(case: EvalCase | None = None, **state: Any) -> EvalResult:
    """A case assess refused: context reached it, and it found nothing bearing on the question."""
    defaults: dict[str, Any] = {
        "steps": ASSESS_REFUSED_PATH,
        "hits": (search_result(),),
        "sources": (retrieved_chunk(),),
        "refusal": Refusal(
            reason=RefusalReason.INSUFFICIENT_CONTEXT,
            explanation="no block concerns the question",
        ),
        "answer": REFUSAL_ANSWER,
        "total_ms": 985,
    }
    return EvalResult(
        case=case or out_of_corpus_case(), state=ChatState(question="q?", **{**defaults, **state})
    )


def eval_run(*results: EvalResult, **overrides: Any) -> EvalRun:
    """A run over the given results, scored and with the live settings, overridable per field."""
    defaults: dict[str, Any] = {
        "dataset_sha": "9f3c",
        "settings": get_config_snapshot(EVAL_CONFIG_SECTIONS),
        "metrics": compute_metrics(results),
        "results": results,
    }
    return EvalRun(**{**defaults, **overrides})


def judged_metrics() -> EvalMetrics:
    """What a run of one answered, passed case measured."""
    return compute_metrics((eval_result(judgement=passed_judgement()),))


def stored_run(id: int, metrics: EvalMetrics | None = None, **overrides: Any) -> EvalRunRecord:
    """An eval_runs row as the database hands it back, its metrics a judged run's by default."""
    defaults: dict[str, Any] = {
        "id": id,
        "created_at": datetime(2026, 9, 18, 3, 0, tzinfo=UTC),
        "git_commit": "12265d6abcdef",
        "git_dirty": False,
        "model": "anthropic/claude-haiku-4-5",
        "settings": {"CHAT_MODEL": "anthropic/claude-haiku-4-5", "CHAT_THINKING_ENABLED": True},
        "metrics": (metrics or judged_metrics()).model_dump(mode="json"),
    }
    return EvalRunRecord(**{**defaults, **overrides})
