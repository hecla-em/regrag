"""Evals CLI: exit codes, what `run` prints and stores, and what `compare` prints."""

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import EVAL_CONFIG_SECTIONS, get_config_snapshot
from app.evals import cli
from app.evals.cli import main
from app.evals.metrics import compute_metrics
from app.evals.models import EvalCaseResult, EvalRunResult
from tests.conftest import no_session
from tests.evals.conftest import eval_case, eval_result, passed_judgement, stored_run


@pytest.fixture
def fake_run(monkeypatch):
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


@pytest.fixture(autouse=True)
def no_database(monkeypatch) -> None:
    """Stand in for storing a run. Autouse so no test here writes one."""

    async def store(session, result: EvalRunResult):
        return stored_run(7)

    monkeypatch.setattr(cli, "get_session", no_session)
    monkeypatch.setattr(cli, "create_eval_run", store)


def judged_result():
    """An answered case the judge passed: what a healthy judged run holds."""
    return eval_result(judgement=passed_judgement())


def test_run_prints_the_summary_and_exits_zero(fake_run, capsys):
    fake_run.append(judged_result())

    assert main(["run"]) == 0

    out = capsys.readouterr().out
    assert '"raw_recall": 1.0' in out
    assert '"CHAT_MODEL"' in out


def test_run_exits_nonzero_when_a_case_raised(fake_run, capsys):
    fake_run.append(eval_result(eval_case(id="boom"), error="TimeoutError"))

    assert main(["run"]) == 1
    assert "boom  TimeoutError" in capsys.readouterr().out


def test_run_exits_nonzero_when_the_judge_answered_on_no_case(fake_run, capsys):
    """Every judge call failing is only warnings, so without this a misnamed judge model
    would print the same summary as --no-judge and pass."""
    fake_run.append(eval_result())

    assert main(["run"]) == 1
    assert "the judge returned no verdict on any answered case" in capsys.readouterr().out

    assert main(["run", "--no-judge"]) == 0


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
