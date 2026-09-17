"""Driving the golden cases through the chat graph, and storing the run."""

import logging

import litellm
import pytest

from app.chat.enums import ChatNode, ChatOutcome
from app.core.config import config
from app.core.exceptions import NotFoundError
from app.core.llm.errors import LLMError
from app.evals import service
from app.evals.dataset.enums import EvalTrait
from app.evals.service import (
    create_eval_run,
    evaluate_all_cases,
    evaluate_case,
    get_eval_run,
)
from tests.chat.conftest import fake_chat_model
from tests.conftest import REPORTED_USAGE, install_chat_model, install_search, search_result
from tests.evals.conftest import eval_case, eval_dataset, eval_result, eval_run, passed_judgement

pytestmark = pytest.mark.anyio


# Running the dataset through the chat graph


@pytest.fixture
def answering_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    """Search finds the authored reference and the model cites it; expansion is a database
    walk covered in tests/retrieval, so it is switched off."""

    async def fake_search(session, request):
        return (search_result(),)

    monkeypatch.setattr(config, "EXPAND_SECTIONS", False)
    install_search(monkeypatch, fake_search)
    install_chat_model(monkeypatch, fake_chat_model("Half of it [1]."))


async def test_a_case_runs_through_the_graph_and_keeps_the_state_it_ended_in(
    answering_graph: None,
) -> None:
    result = await evaluate_case(eval_case())

    assert result.case == eval_case()
    assert result.state.question == "q?"
    assert result.state.answer == "Half of it [1]."
    assert result.state.hits == (search_result(),)
    assert [n.step for n in result.state.steps] == [ChatNode.RETRIEVE, ChatNode.SYNTHESIZE]
    assert result.state.outcome is ChatOutcome.DONE
    assert result.state.total_ms is not None
    assert result.state.usage() == REPORTED_USAGE


async def test_a_case_the_graph_raises_on_is_recorded_rather_than_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One failing case must not end the run; it is named as production names it."""

    async def failing_search(session, request):
        raise LLMError("embedding call failed")

    install_search(monkeypatch, failing_search)

    with caplog.at_level(logging.WARNING):
        result = await evaluate_case(eval_case())

    assert result.state.error == "embedding call failed"
    assert result.state.outcome is ChatOutcome.ERROR
    assert result.state.total_ms is not None
    assert "eval case case failed: embedding call failed" in caplog.text


async def test_a_run_scores_every_case_and_records_what_it_ran_against(
    answering_graph: None,
) -> None:
    case = eval_case(id="fueleu-one", traits=(EvalTrait.MULTI_PART,))
    dataset = eval_dataset(case, id_contains="fueleu", trait=EvalTrait.MULTI_PART)

    run = await evaluate_all_cases(dataset)

    assert [r.case.id for r in run.results] == ["fueleu-one"]
    assert run.selection == dataset.selection
    assert run.dataset_sha == dataset.sha256
    assert run.metrics.counts.cases == 1
    assert run.settings["EXPAND_SECTIONS"] is False
    assert run.cached is False


async def test_a_run_records_that_it_had_the_call_cache_on(
    answering_graph: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cached run's node timings may measure a disk read, so the run has to say so or its
    numbers read as a latency baseline they are not. The flag is read off the live litellm
    cache, so it cannot disagree with what served the calls."""
    monkeypatch.setattr(litellm, "cache", object())

    run = await evaluate_all_cases(eval_dataset(eval_case(id="fueleu-one")))

    assert run.cached is True
    assert '"cached": true' in run.summary()


async def test_a_filtered_run_scores_only_the_selected_cases(answering_graph: None) -> None:
    dataset = eval_dataset(eval_case(id="fueleu-one"), eval_case(id="mrv-one"), id_contains="mrv")

    run = await evaluate_all_cases(dataset)

    assert [r.case.id for r in run.results] == ["mrv-one"]


async def test_a_run_carries_the_corpus_it_was_measured_against(answering_graph: None) -> None:
    """Read before the run and carried through it, so a score always says which text it was
    measured against and which cases owe a re-review."""
    run = await evaluate_all_cases(
        eval_dataset(eval_case()), corpus_version="2026-08-01-a3f1c2", stale_cases=("amended",)
    )

    assert run.corpus_version == "2026-08-01-a3f1c2"
    assert run.stale_cases == ("amended",)


async def test_a_run_records_the_commit_it_ran(
    answering_graph: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "read_git_commit", lambda: ("12265d6", True))

    run = await evaluate_all_cases(eval_dataset(eval_case()))

    assert (run.git_commit, run.git_dirty) == ("12265d6", True)
    assert '"git_commit": "12265d6"' in run.summary()


# Storing a run


async def test_a_stored_run_keeps_its_setup_and_metrics(db_session) -> None:
    run = eval_run(
        eval_result(judgement=passed_judgement()),
        judged=True,
        git_commit="12265d6",
        corpus_version="2026-09-15",
        stale_cases=("amended",),
    )

    created = await create_eval_run(db_session, run)
    db_session.expunge_all()
    stored = await get_eval_run(db_session, created.id)

    assert stored.git_commit == "12265d6"
    assert stored.git_dirty is False
    assert stored.model == config.CHAT_MODEL
    assert stored.judge_model == config.EVAL_JUDGE_MODEL
    assert stored.corpus_version == "2026-09-15"
    assert stored.stale_cases == ["amended"]
    assert stored.selection == run.selection.model_dump(mode="json")
    assert stored.settings["CHAT_MODEL"] == config.CHAT_MODEL
    assert stored.metrics["judge"]["correctness"] == 1.0
    assert type(run.metrics).model_validate(stored.metrics) == run.metrics


async def test_an_unjudged_run_names_no_judge_model(db_session) -> None:
    stored = await create_eval_run(db_session, eval_run(eval_result()))

    assert stored.judged is False
    assert stored.judge_model is None


async def test_a_missing_run_is_not_found(db_session) -> None:
    with pytest.raises(NotFoundError, match="eval run '999999' not found"):
        await get_eval_run(db_session, 999999)


# Judging


@pytest.fixture
def recording_judge(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A judging pass that records which cases it saw and hands them back unjudged."""
    seen: list[str] = []

    async def fake_judge_results(results):
        seen.extend(result.case.id for result in results)
        return list(results)

    monkeypatch.setattr(service, "judge_results", fake_judge_results)
    return seen


async def test_a_run_is_judged_once_every_case_has_run_and_says_so(
    answering_graph: None, recording_judge
) -> None:
    run = await evaluate_all_cases(eval_dataset(eval_case(id="one"), eval_case(id="two")))

    assert recording_judge == ["one", "two"]
    assert run.judged is True
    assert '"judged": true' in run.summary()


async def test_the_judge_can_be_switched_off(answering_graph: None, recording_judge) -> None:
    run = await evaluate_all_cases(eval_dataset(eval_case(id="one")), judge=False)

    assert recording_judge == []
    assert run.judged is False


async def test_a_case_is_not_judged_on_its_own(answering_graph: None, recording_judge) -> None:
    """Judging is a pass over the timed run, so a case's timing never carries a judge call."""
    result = await evaluate_case(eval_case())

    assert recording_judge == []
    assert result.judgement is None
