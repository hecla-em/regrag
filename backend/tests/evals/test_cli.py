"""Evals CLI: exit codes, what `run` prints and stores, and what `compare` prints."""

from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import EVAL_CONFIG_SECTIONS, config, get_config_snapshot
from app.core.exceptions import NotFoundError
from app.evals import cli
from app.evals.cli import main
from app.evals.dataset.enums import DriftKind
from app.evals.dataset.models import CaseReference, DriftedReference
from app.evals.metrics import compute_metrics
from app.evals.models import EvalRunResult
from tests.conftest import no_session
from tests.evals.conftest import eval_case, eval_result, passed_judgement, stored_run


def test_a_subcommand_is_required(capsys):
    with pytest.raises(SystemExit):
        main([])


class _RecordedResults(list):
    """The results a stubbed run returns, plus the judge flag each run was asked for."""

    def __init__(self) -> None:
        super().__init__()
        self.judged: list[bool] = []
        self.retrieval: list[bool] = []


@pytest.fixture
def fake_run(monkeypatch):
    """Replace the graph run with a stub returning a chosen list of results."""
    results = _RecordedResults()
    judged = results.judged

    async def _fake_corpus_read(dataset):
        return (), "2026-08-01-a3f1c2"

    async def _fake(dataset, corpus_version=None, stale_cases=(), *, judge=True, retrieval=True):
        judged.append(judge)
        results.retrieval.append(retrieval)
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
def stored(monkeypatch) -> list[EvalRunResult]:
    """Record the runs `run` stored, without a database. Autouse so no test here writes one."""
    stored: list[EvalRunResult] = []

    async def record(session, result: EvalRunResult):
        stored.append(result)
        return stored_run(7)

    monkeypatch.setattr(cli, "get_session", no_session)
    monkeypatch.setattr(cli, "create_eval_run", record)
    return stored


def judged_result():
    """An answered case the judge passed: what a healthy judged run holds."""
    return eval_result(judgement=passed_judgement())


def test_run_judges_unless_told_not_to(fake_run):
    fake_run.append(judged_result())

    main(["run"])
    main(["run", "--no-judge"])

    assert fake_run.judged == [True, False]


def test_run_retrieves_unless_told_not_to(fake_run, stored):
    fake_run.append(judged_result())

    main(["run"])
    main(["run", "--no-retrieval"])

    assert fake_run.retrieval == [True, False]
    assert [run.retrieval for run in stored] == [True, False]


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


def test_run_exits_nonzero_when_no_case_matches_the_filter(fake_run, capsys):
    assert main(["run", "--case", "nothing-here"]) == 1
    assert "nothing-here" in capsys.readouterr().out


def test_run_scores_the_cases_carrying_a_trait_and_records_the_filter(fake_run, capsys):
    fake_run.append(judged_result())

    assert main(["run", "--trait", "multi_part"]) == 0
    assert '"trait": "multi_part"' in capsys.readouterr().out


def test_run_scores_the_cases_of_a_kind_and_records_the_selection(fake_run, capsys):
    fake_run.append(judged_result())

    assert main(["run", "--kind", "out_of_corpus"]) == 0
    assert '"kind": "out_of_corpus"' in capsys.readouterr().out


def test_run_rejects_a_trait_the_dataset_does_not_define(fake_run):
    with pytest.raises(SystemExit):
        main(["run", "--trait", "hard"])


# Storing and comparing runs


def test_run_stores_the_run_and_prints_its_id(fake_run, stored, capsys):
    fake_run.append(judged_result())

    assert main(["run"]) == 0

    assert len(stored) == 1
    assert stored[0].judged is True
    assert "stored as eval run 7" in capsys.readouterr().out


def test_run_stores_a_run_that_had_errors(fake_run, stored):
    fake_run.append(eval_result(eval_case(id="boom"), error="TimeoutError"))

    assert main(["run"]) == 1
    assert len(stored) == 1


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


def test_no_store_only_prints(fake_run, stored, capsys):
    fake_run.append(judged_result())

    assert main(["run", "--no-store"]) == 0

    assert not stored
    assert "stored as eval run" not in capsys.readouterr().out


def test_compare_prints_the_two_runs(monkeypatch, capsys):
    async def load(*run_ids):
        return [stored_run(run_id) for run_id in run_ids]

    monkeypatch.setattr(cli, "load_eval_runs", load)

    assert main(["compare", "42", "41"]) == 0
    assert "metric" in capsys.readouterr().out


def test_compare_exits_nonzero_on_a_run_that_is_not_stored(monkeypatch, capsys):
    async def load(*run_ids):
        raise NotFoundError("eval run", 999)

    monkeypatch.setattr(cli, "load_eval_runs", load)

    assert main(["compare", "42", "999"]) == 1
    assert "eval run '999' not found" in capsys.readouterr().out


# Which commands replay their paid calls


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    """Record whether the command turned the call cache on, without turning it on. Autouse
    so no test here installs a real cache: `run` enables one by default, which would put a
    cache under the real data directory and leave it set for whatever runs next."""
    enabled: list[Path] = []

    def record(directory: Path) -> None:
        enabled.append(directory)

    monkeypatch.setattr(cli, "enable_call_cache", record)
    return enabled


def test_run_replays_its_embed_and_rerank_calls_by_default(fake_run, enabled):
    fake_run.append(judged_result())

    assert main(["run"]) == 0
    assert enabled == [config.EVAL_CACHE_DIR]


def test_no_cache_makes_a_run_pay_for_its_calls_again(fake_run, enabled):
    fake_run.append(judged_result())

    assert main(["run", "--no-cache"]) == 0
    assert not enabled


def test_run_lists_every_case_only_when_asked(fake_run, capsys):
    fake_run.append(judged_result())

    assert main(["run"]) == 0
    assert "raw 1.00" not in capsys.readouterr().out

    assert main(["run", "--verbose"]) == 0
    out = capsys.readouterr().out
    assert "raw 1.00" in out
    assert '"raw_recall": 1.0' in out


def test_run_reports_the_corpus_and_the_stale_cases_it_read_before_scoring(
    fake_run, monkeypatch, capsys
):
    """Tuning compares two runs, so a score has to say which corpus it was measured against
    and which of its reference answers are owed a re-review."""

    async def _fake_corpus_read(dataset):
        moved = CaseReference(celex="32023R1805", article="4")
        drifted = DriftedReference(case_id="amended", target=moved, kind=DriftKind.STALE)
        return (drifted,), "2026-08-01-a3f1c2"

    fake_run.append(judged_result())
    monkeypatch.setattr(cli, "check_against_corpus", _fake_corpus_read)

    assert main(["run"]) == 0

    out = capsys.readouterr().out
    assert '"corpus_version": "2026-08-01-a3f1c2"' in out
    assert "1 case cites text that changed since authoring:" in out
    assert "  amended" in out
