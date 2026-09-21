"""Evals CLI: exit codes, what `run` prints and stores, and what `compare` prints."""

from contextlib import asynccontextmanager

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.exc import OperationalError

from app.core.config import EVAL_CONFIG_SECTIONS, config, get_config_snapshot
from app.core.llm.errors import LLMError
from app.evals import cli
from app.evals.cli import load_eval_runs, main, score_dataset
from app.evals.dataset.enums import EvalKind
from app.evals.dataset.models import EvalCase
from app.evals.judge.enums import JudgeVerdict
from app.evals.judge.models import ClaimVerdict, CorrectnessVerdict, FaithfulnessVerdict
from app.evals.judge.service import judge_results
from app.evals.metrics import compute_metrics
from app.evals.models import CaseCounts, EvalCaseResult, EvalMetrics, EvalRunResult
from app.evals.report import format_run_comparison
from app.evals.service import get_eval_run
from tests.chat.conftest import RecordingChatModel, fake_chat_model
from tests.conftest import (
    USAGE,
    install_chat_model,
    install_search,
    junk_result,
    no_session,
    search_result,
)
from tests.evals.conftest import (
    comparison_line,
    eval_case,
    eval_dataset,
    eval_result,
    passed_judgement,
    stored_run,
)


@pytest.fixture
def fake_run(monkeypatch, no_database):
    """Replace the graph run with a stub returning a chosen list of results."""
    results: list[EvalCaseResult] = []

    async def _fake_corpus_read(dataset):
        return (), "2026-08-01-a3f1c2"

    async def _fake(dataset, corpus_version=None, stale_cases=(), *, judge=True, retrieval=True):
        chosen = tuple(results)
        return EvalRunResult(
            dataset_sha=dataset.sha256,
            selection=dataset.selection,
            corpus_version=corpus_version,
            stale_cases=stale_cases,
            judged=judge,
            retrieval=retrieval,
            settings=get_config_snapshot(EVAL_CONFIG_SECTIONS),
            metrics=compute_metrics(chosen),
            results=chosen,
        )

    monkeypatch.setattr(cli, "check_against_corpus", _fake_corpus_read)
    monkeypatch.setattr(cli, "evaluate_all_cases", _fake)
    return results


@pytest.fixture
def no_database(monkeypatch) -> None:
    """Stand in for storing a run, for the tests whose run is a stub."""

    async def store(session, result: EvalRunResult):
        return stored_run(7)

    monkeypatch.setattr(cli, "get_session", no_session)
    monkeypatch.setattr(cli, "create_eval_run", store)


def judged_result():
    """An answered case the judge passed: what a healthy judged run holds."""
    return eval_result(judgement=passed_judgement())


@pytest.mark.parametrize(
    ("results", "argv", "exit_code"),
    [
        pytest.param([judged_result()], ["run"], 0, id="a clean judged run passes"),
        pytest.param(
            [eval_result(eval_case(id="boom"), error="TimeoutError")],
            ["run"],
            1,
            id="a case that raised fails it",
        ),
        pytest.param([eval_result()], ["run"], 1, id="so does a judge that answered on no case"),
        pytest.param(
            [judged_result(), eval_result(eval_case(id="unjudged"))],
            ["run"],
            1,
            id="and one that came back on too few",
        ),
        pytest.param(
            [eval_result()], ["run", "--no-judge"], 0, id="a run told not to judge owes no verdict"
        ),
    ],
)
def test_run_exits_nonzero_when_its_scores_cannot_be_trusted(
    fake_run, results: list[EvalCaseResult], argv: list[str], exit_code: int
) -> None:
    """Every judge call failing is only warnings, so without this a misnamed judge model
    would print the same summary as --no-judge and pass."""
    fake_run.extend(results)

    assert main(argv) == exit_code


# Storing and comparing runs


def test_a_run_that_could_not_be_stored_still_prints_and_exits_nonzero(
    fake_run, monkeypatch, capsys
):
    async def refuse(session, result):
        raise OperationalError("insert", {}, Exception("database is down"))

    fake_run.append(judged_result())
    monkeypatch.setattr(cli, "create_eval_run", refuse)

    assert main(["run"]) == 1

    out = capsys.readouterr().out
    assert '"raw_recall": 1.0' in out
    assert "the run was not stored" in out


@pytest.fixture(autouse=True)
def no_call_cache(monkeypatch) -> None:
    """Autouse so no test here installs a real cache: `run` enables one by default, which
    would put a cache under the real data directory and leave it set for whatever runs next."""
    monkeypatch.setattr(cli, "enable_call_cache", lambda directory: None)


# Scoring over the real graph, the real corpus check and the real eval_runs table


@pytest.fixture
def real_database(db_session, monkeypatch):
    """The command's own sessions, handed the test's rolled-back one instead."""

    @asynccontextmanager
    async def the_test_session(**kwargs):
        yield db_session

    monkeypatch.setattr(cli, "get_session", the_test_session)
    monkeypatch.setattr("app.evals.dataset.check.get_session", the_test_session)


@pytest.fixture
def real_judge(monkeypatch, judge_answers):
    """The judging pass back on, undoing the suite-wide switch-off, its model faked."""
    monkeypatch.setattr("app.evals.service.judge_results", judge_results)
    return judge_answers


ANSWERED = eval_case(id="answered", question="What is the limit?")
REFUSED = EvalCase(id="refused", kind=EvalKind.OUT_OF_CORPUS, question="How do I bake bread?")
RAISES = eval_case(id="raises", question="Boom?")
PASSED = CorrectnessVerdict(critique="states the limit", verdict=JudgeVerdict.PASS)
GROUNDED = FaithfulnessVerdict(
    critique="in [1]", claims=(ClaimVerdict(claim="the limit applies", supported=True),)
)


@pytest.fixture
def three_kinds_of_case(monkeypatch):
    """Search finds the reference for one question, junk for another and fails on a third,
    so one case is answered, one refused at the gate and one raises."""

    async def search(session, request):
        if request.query == RAISES.question:
            raise LLMError("embedding call failed")
        return (junk_result(),) if request.query == REFUSED.question else (search_result(),)

    monkeypatch.setattr(config, "EXPAND_SECTIONS", False)
    install_search(monkeypatch, search)
    install_chat_model(monkeypatch, fake_chat_model("The limit applies [1]."))


@pytest.mark.anyio
async def test_a_scored_run_is_judged_counted_and_stored(
    db_session, real_database, real_judge, three_kinds_of_case
):
    real_judge(PASSED, GROUNDED)

    result, run_id = await score_dataset(
        eval_dataset(ANSWERED, REFUSED, RAISES), judge=True, retrieval=True, store=True
    )

    assert result.metrics.counts == CaseCounts(cases=3, in_corpus=2, out_of_corpus=1, errors=1)
    assert result.metrics.retrieval.raw_recall == 1.0
    assert result.metrics.gate.refusal_rate == 1.0
    assert (result.metrics.judge.judged, result.metrics.judge.correctness) == (1, 1.0)
    assert result.judged_coverage == 1.0
    assert "raises  embedding call failed" in result.summary()
    assert run_id is not None
    stored = await get_eval_run(db_session, run_id)
    assert EvalMetrics.model_validate(stored.metrics) == result.metrics
    assert stored.judge_model == config.EVAL_JUDGE_MODEL


@pytest.mark.anyio
async def test_two_stored_runs_compare_on_the_setting_and_the_metric_that_moved(
    db_session, real_database, three_kinds_of_case, monkeypatch
):
    dataset = eval_dataset(ANSWERED, REFUSED)
    _, base_id = await score_dataset(dataset, judge=False, retrieval=True, store=True)

    monkeypatch.setattr(config, "MIN_COSINE_SIMILARITY", 0.0)
    monkeypatch.setattr(config, "MIN_RERANKER_RELEVANCE", 0.0)
    replies = iter([AIMessage(content="The limit applies [1].")] * 2)
    install_chat_model(monkeypatch, RecordingChatModel(messages=replies, usage=USAGE))
    _, other_id = await score_dataset(dataset, judge=False, retrieval=True, store=True)

    assert base_id is not None and other_id is not None
    output = format_run_comparison(*await load_eval_runs(base_id, other_id))

    assert comparison_line(output, "gate.refusal_rate")[1:] == ["1.000", "0.000", "-1.000"]
    assert comparison_line(output, "MIN_COSINE_SIMILARITY")[1:] == ["0.300", "0.000"]
    assert "CHAT_MODEL " not in output
