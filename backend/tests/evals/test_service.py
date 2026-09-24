"""Driving the golden cases through the chat graph, and storing the run."""

import logging

import pytest

from app.chat.enums import ChatNode, ChatOutcome
from app.core.config import config
from app.core.llm.errors import LLMError
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


async def test_a_run_scores_the_selected_cases_and_records_what_it_ran_against(
    answering_graph: None,
) -> None:
    """Each result keeps the state its chat request ended in, which the run is scored off."""
    selected = eval_case(id="fueleu-one", traits=(EvalTrait.MULTI_PART,))
    dataset = eval_dataset(
        selected, eval_case(id="mrv-one"), id_contains="fueleu", trait=EvalTrait.MULTI_PART
    )

    run = await evaluate_all_cases(dataset)

    [result] = run.results
    assert result.case == selected
    assert result.state.answer == "Half of it [1]."
    assert result.state.hits == (search_result(),)
    assert [n.step for n in result.state.steps] == [
        ChatNode.REWRITE,
        ChatNode.RETRIEVE,
        ChatNode.SYNTHESIZE,
    ]
    assert result.state.outcome is ChatOutcome.DONE
    assert result.state.total_ms is not None
    assert result.state.usage() == REPORTED_USAGE
    assert run.selection == dataset.selection
    assert run.dataset_sha == dataset.sha256
    assert run.metrics.counts.cases == 1
    assert run.settings["EXPAND_SECTIONS"] is False
    assert run.cached is False


async def test_a_no_retrieval_run_answers_every_case_from_memory_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_search(session, request):
        raise AssertionError("a no-retrieval run searched")

    install_search(monkeypatch, no_search)
    install_chat_model(monkeypatch, fake_chat_model("Half of it."))

    run = await evaluate_all_cases(eval_dataset(eval_case()), retrieval=False)

    [result] = run.results
    assert run.retrieval is False
    assert [n.step for n in result.state.steps] == [ChatNode.SYNTHESIZE]
    assert result.state.outcome is ChatOutcome.DONE
    assert result.state.answer == "Half of it."
    assert run.metrics.retrieval.raw_recall == 0.0
    assert run.metrics.retrieval.expanded_recall == 0.0
    assert run.metrics.citations.cited_references == 0.0
    assert run.metrics.gate.false_refusals == 0


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
    assert stored.retrieval is True
    assert stored.model == config.CHAT_MODEL
    assert stored.judge_model == config.EVAL_JUDGE_MODEL
    assert stored.corpus_version == "2026-09-15"
    assert stored.stale_cases == ["amended"]
    assert stored.selection == run.selection.model_dump(mode="json")
    assert stored.settings["CHAT_MODEL"] == config.CHAT_MODEL
    assert stored.metrics["judge"]["correctness"] == 1.0
    assert type(run.metrics).model_validate(stored.metrics) == run.metrics
