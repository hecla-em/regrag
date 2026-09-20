"""Eval run values: what a run's summary reports."""

import json

from app.core.config import EVAL_CONFIG_SECTIONS, config, get_config_snapshot
from app.evals.dataset.enums import EvalTrait
from app.evals.dataset.models import CaseSelection
from app.evals.metrics import compute_metrics
from app.evals.models import EvalCaseResult, EvalRunResult
from tests.evals.conftest import eval_case, eval_result, passed_judgement, refused_result


def test_the_summary_carries_the_runs_setup_and_scores_then_names_the_cases_that_raised() -> None:
    results = (eval_result(), eval_result(eval_case(id="boom"), error="TimeoutError"))
    run = EvalRunResult(
        dataset_sha="abc",
        selection=CaseSelection(id_contains="fueleu", trait=EvalTrait.MULTI_PART),
        settings=get_config_snapshot(EVAL_CONFIG_SECTIONS),
        metrics=compute_metrics(results),
        results=results,
    )

    summary = run.summary()
    body = json.loads(summary.split("\nerrored:")[0])

    assert body["dataset_sha"] == "abc"
    assert body["selection"] == {"id_contains": "fueleu", "trait": "multi_part", "kind": None}
    assert body["settings"]["CHAT_MODEL"] == config.CHAT_MODEL
    assert body["retrieval"] is True
    assert body["metrics"]["counts"]["errors"] == 1
    assert "results" not in body
    assert summary.rstrip().endswith("boom  TimeoutError")


def test_the_summary_names_the_corpus_and_the_cases_owed_a_re_review() -> None:
    """A stale case is reported, never failed: only a human can repair one, so the run stays
    green and says which reference answers were written against text that has since moved."""
    results = (eval_result(),)
    run = EvalRunResult(
        dataset_sha="abc",
        corpus_version="2026-08-01-a3f1c2",
        stale_cases=("amended-one", "amended-two"),
        settings=get_config_snapshot(EVAL_CONFIG_SECTIONS),
        metrics=compute_metrics(results),
        results=results,
    )

    summary = run.summary()
    body = json.loads(summary.split("\n\n")[0])

    assert body["corpus_version"] == "2026-08-01-a3f1c2"
    assert "2 cases cite text that changed since authoring:" in summary
    assert "  amended-one" in summary
    assert "  amended-two" in summary


def test_a_judged_run_whose_judge_never_answered_says_so() -> None:
    """Every judge call failing leaves only warnings behind, so the run itself has to name
    the difference between a judge that was off and one that never came back."""
    answered = (eval_result(),)
    run = EvalRunResult(
        dataset_sha="abc",
        judged=True,
        settings={},
        metrics=compute_metrics(answered),
        results=answered,
    )

    assert run.judge_never_answered
    assert "the judge returned no verdict on any answered case" in run.summary()


def test_a_run_with_nothing_to_judge_or_a_verdict_is_not_a_silent_judge() -> None:
    judged = (eval_result(judgement=passed_judgement()),)
    refused_only = (refused_result(),)

    assert not EvalRunResult(
        dataset_sha="abc", judged=True, settings={}, metrics=compute_metrics(judged), results=judged
    ).judge_never_answered
    assert not EvalRunResult(
        dataset_sha="abc",
        judged=True,
        settings={},
        metrics=compute_metrics(refused_only),
        results=refused_only,
    ).judge_never_answered
    assert not EvalRunResult(
        dataset_sha="abc",
        judged=False,
        settings={},
        metrics=compute_metrics((eval_result(),)),
        results=(eval_result(),),
    ).judge_never_answered


def judged_run(*results: EvalCaseResult) -> EvalRunResult:
    """A judged run over the given cases, so coverage is what the judgements say it is."""
    return EvalRunResult(
        dataset_sha="abc",
        judged=True,
        settings={},
        metrics=compute_metrics(results),
        results=results,
    )


def test_coverage_counts_only_the_cases_the_judge_was_owed_a_verdict_on() -> None:
    """A gate refusal is scored by the gate metrics and an errored case by nothing, so
    neither is a case the judge failed to come back on."""
    run = judged_run(
        eval_result(judgement=passed_judgement()),
        refused_result(),
        eval_result(eval_case(id="boom"), error="TimeoutError"),
    )

    assert run.judgeable == 1
    assert run.judged_coverage == 1.0
    assert not run.judged_too_few


def test_a_run_the_judge_came_back_on_too_few_of_fails_and_says_the_share() -> None:
    """The scores of a part-judged run are that subset's: a number that looks like a full
    run's and is not, which is worse than no number."""
    judged = [eval_result(eval_case(id=f"j{i}"), judgement=passed_judgement()) for i in range(6)]
    unjudged = [eval_result(eval_case(id=f"u{i}")) for i in range(4)]
    run = judged_run(*judged, *unjudged)

    assert run.judgeable == 10
    assert run.judged_coverage == 0.6
    assert run.judged_too_few
    assert "the judge came back on 6 of 10 answered cases (60%, under 90%)" in run.summary()


def test_a_shortfall_inside_the_allowance_passes(monkeypatch) -> None:
    """A case or two lost to a provider is not a different measurement."""
    monkeypatch.setattr(config, "EVAL_JUDGE_MIN_COVERAGE", 0.9)
    judged = [eval_result(eval_case(id=f"j{i}"), judgement=passed_judgement()) for i in range(9)]
    run = judged_run(*judged, eval_result(eval_case(id="u")))

    assert run.judged_coverage == 0.9
    assert not run.judged_too_few
    assert "the judge came back on" not in run.summary()


def test_the_threshold_is_a_setting(monkeypatch) -> None:
    judged = [eval_result(eval_case(id=f"j{i}"), judgement=passed_judgement()) for i in range(6)]
    run = judged_run(*judged, *[eval_result(eval_case(id=f"u{i}")) for i in range(4)])

    monkeypatch.setattr(config, "EVAL_JUDGE_MIN_COVERAGE", 0.5)

    assert not run.judged_too_few


def test_a_run_with_the_judge_off_has_no_coverage_to_fall_short_of() -> None:
    """Unmeasured, not incomplete: a run that never asked cannot be judged too thinly."""
    results = (eval_result(),)
    run = EvalRunResult(
        dataset_sha="abc",
        judged=False,
        settings={},
        metrics=compute_metrics(results),
        results=results,
    )

    assert run.judged_coverage is None
    assert not run.judged_too_few


def test_a_judge_that_never_answered_is_named_as_that_rather_than_as_a_shortfall() -> None:
    """Both are true of a run with no verdicts; the more specific one is the useful one."""
    run = judged_run(eval_result())

    assert run.judged_too_few
    assert "the judge returned no verdict on any answered case" in run.summary()
    assert "the judge came back on" not in run.summary()
